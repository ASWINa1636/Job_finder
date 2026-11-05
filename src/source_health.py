"""
Source Health & Diagnostic Engine
Monitors and verifies scraper endpoints for Workday, Greenhouse, Lever, and public job feeds.
Flags broken endpoints, schema changes, HTTP failures, and silent empty responses.
"""

import time
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
from src.job_sources import load_company_config, TIMEOUT

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*"
}


def check_endpoint(kind, name, url, method="get", payload=None, expected_key=None, timeout=TIMEOUT):
    """
    Performs a single diagnostic probe on an ATS or job feed endpoint.
    Returns a standardized health check dict.
    """
    start_time = time.perf_counter()
    res = {
        "kind": kind,
        "name": name,
        "url": url,
        "status": "broken",
        "status_code": None,
        "latency_ms": 0,
        "items_found": 0,
        "message": "",
        "recommendation": ""
    }

    try:
        if method.lower() == "post":
            resp = requests.post(url, json=payload or {}, headers=DEFAULT_HEADERS, timeout=timeout)
        else:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)

        latency = round((time.perf_counter() - start_time) * 1000)
        res["latency_ms"] = latency
        res["status_code"] = resp.status_code

        # Check HTTP error status
        if resp.status_code == 404:
            res["status"] = "broken"
            res["message"] = "HTTP 404 Not Found"
            res["recommendation"] = f"The career board endpoint for '{name}' was not found. Check if the token or site name in config/companies.json has changed."
            return res

        if resp.status_code in (401, 403):
            res["status"] = "broken"
            res["message"] = f"HTTP {resp.status_code} Forbidden / Access Denied"
            res["recommendation"] = f"Access to '{name}' was blocked or requires authentication/cookies. Consider updating headers or verifying portal accessibility."
            return res

        if resp.status_code >= 500:
            res["status"] = "broken"
            res["message"] = f"HTTP {resp.status_code} Server Error"
            res["recommendation"] = f"The remote server for '{name}' is reporting internal errors. Retry later or check site maintenance."
            return res

        if resp.status_code != 200:
            res["status"] = "broken"
            res["message"] = f"Unexpected HTTP status {resp.status_code}"
            res["recommendation"] = f"Inspect endpoint response manually: {url}"
            return res

        # Validate JSON content
        try:
            data = resp.json()
        except Exception:
            res["status"] = "broken"
            res["message"] = "Malformed response (not valid JSON)"
            res["recommendation"] = f"The site '{name}' returned non-JSON content (likely an HTML error or redirect page). The scraper format may need updating."
            return res

        # Extract items according to schema
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            if expected_key and expected_key in data:
                items = data[expected_key]
            elif "jobPostings" in data:
                items = data["jobPostings"]
            elif "jobs" in data:
                items = data["jobs"]
            elif "data" in data and isinstance(data["data"], list):
                items = data["data"]
            else:
                # Top level dict without standard list
                items = [data]

        item_count = len(items) if isinstance(items, list) else 0
        res["items_found"] = item_count

        if item_count == 0:
            res["status"] = "warning"
            res["message"] = "Empty response (0 postings returned)"
            res["recommendation"] = f"Endpoint is reachable, but returned 0 jobs. The employer '{name}' may currently have no open roles, or the search parameters need adjustment."
        else:
            res["status"] = "healthy"
            res["message"] = f"OK ({item_count} jobs found)"

    except requests.exceptions.Timeout:
        res["latency_ms"] = round((time.perf_counter() - start_time) * 1000)
        res["status"] = "broken"
        res["message"] = f"Connection timed out after {timeout}s"
        res["recommendation"] = f"The server for '{name}' did not respond in time. Network may be slow or the host is throttling requests."
    except requests.exceptions.ConnectionError as exc:
        res["status"] = "broken"
        res["message"] = "Connection refused or DNS failure"
        res["recommendation"] = f"Could not connect to '{name}'. Check internet connection and verify domain name."
    except Exception as exc:
        res["status"] = "broken"
        res["message"] = f"Error: {type(exc).__name__}: {str(exc)}"
        res["recommendation"] = f"Unexpected scraper failure for '{name}'. Check logs for details."

    return res


def build_source_catalog(config=None, quick=False):
    """
    Builds the list of probe targets from config/companies.json and default feeds.
    If quick=True, checks top 2 from each platform plus all feeds.
    """
    cfg = config or load_company_config()
    targets = []

    # 1. Greenhouse
    gh_tokens = cfg.get("greenhouse", [])
    if quick:
        gh_tokens = gh_tokens[:3]
    for token in gh_tokens:
        targets.append({
            "kind": "Greenhouse",
            "name": token.title(),
            "url": f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
            "method": "get",
            "expected_key": "jobs"
        })

    # 2. Lever
    lever_sites = cfg.get("lever", [])
    if quick:
        lever_sites = lever_sites[:3]
    for site in lever_sites:
        targets.append({
            "kind": "Lever.co",
            "name": site.title(),
            "url": f"https://api.lever.co/v0/postings/{site}?mode=json",
            "method": "get"
        })

    # 3. Workday
    wd_entries = cfg.get("workday", [])
    if quick:
        wd_entries = wd_entries[:3]
    for wd in wd_entries:
        if isinstance(wd, dict) and wd.get("domain") and wd.get("tenant") and wd.get("site"):
            c_name = wd.get("company") or wd["tenant"].title()
            targets.append({
                "kind": "Workday",
                "name": c_name,
                "url": f"https://{wd['domain']}/wday/cxs/{wd['tenant']}/{wd['site']}/jobs",
                "method": "post",
                "payload": {"appliedFacets": {}, "limit": 5, "offset": 0, "searchText": ""},
                "expected_key": "jobPostings"
            })

    # 4. Public feeds
    targets.extend([
        {
            "kind": "Public Feed",
            "name": "Arbeitnow",
            "url": "https://www.arbeitnow.com/api/job-board-api?page=1",
            "method": "get",
            "expected_key": "data"
        },
        {
            "kind": "Public Feed",
            "name": "Jobicy",
            "url": "https://jobicy.com/api/v2/remote-jobs?count=5",
            "method": "get",
            "expected_key": "jobs"
        },
        {
            "kind": "Public Feed",
            "name": "Remote OK",
            "url": "https://remoteok.com/api",
            "method": "get"
        },
        {
            "kind": "Public Feed",
            "name": "Remotive",
            "url": "https://remotive.com/api/remote-jobs?limit=5",
            "method": "get",
            "expected_key": "jobs"
        }
    ])

    return targets


def run_source_health_check(quick=True, concurrency=5, progress_callback=None):
    """
    Executes health checks concurrently across all target sources.
    Returns list of diagnostic results.
    """
    targets = build_source_catalog(quick=quick)
    total = len(targets)
    results = []

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_target = {
            executor.submit(
                check_endpoint,
                t["kind"],
                t["name"],
                t["url"],
                t.get("method", "get"),
                t.get("payload"),
                t.get("expected_key")
            ): t for t in targets
        }

        completed = 0
        for future in as_completed(future_to_target):
            completed += 1
            res = future.result()
            results.append(res)
            if progress_callback:
                progress_callback(completed, total, f"Checked {res['kind']}/{res['name']}: {res['status'].upper()}")

    # Sort results: broken first, then warning, then healthy
    status_order = {"broken": 0, "warning": 1, "healthy": 2}
    results.sort(key=lambda r: (status_order.get(r["status"], 3), r["kind"], r["name"]))
    return results


def summarize_health_results(results):
    """
    Produces summary statistics and highlights broken endpoints.
    """
    healthy = [r for r in results if r["status"] == "healthy"]
    warning = [r for r in results if r["status"] == "warning"]
    broken = [r for r in results if r["status"] == "broken"]

    return {
        "total": len(results),
        "healthy_count": len(healthy),
        "warning_count": len(warning),
        "broken_count": len(broken),
        "broken_sources": broken,
        "warning_sources": warning,
        "overall_status": "CRITICAL" if broken else ("DEGRADED" if warning else "HEALTHY")
    }


def format_health_report(results, markdown=False):
    """
    Formats the diagnostic results into a readable text or markdown report.
    """
    summary = summarize_health_results(results)
    lines = []

    if markdown:
        lines.append(f"## 🩺 Source Health Diagnostic Report")
        lines.append(f"**Overall Status**: `{summary['overall_status']}` | Total: {summary['total']} | 🟢 Healthy: {summary['healthy_count']} | 🟡 Warning: {summary['warning_count']} | 🔴 Broken: {summary['broken_count']}\n")
        lines.append("| Status | Platform | Source / Company | Code | Latency | Result / Diagnosis |")
        lines.append("| :--- | :--- | :--- | :---: | :---: | :--- |")
        for r in results:
            icon = "🟢" if r["status"] == "healthy" else ("🟡" if r["status"] == "warning" else "🔴")
            lines.append(f"| {icon} {r['status'].upper()} | {r['kind']} | **{r['name']}** | {r['status_code'] or '-'} | {r['latency_ms']}ms | {r['message']} |")
            if r["recommendation"]:
                lines.append(f"| ↳ | _Action_ | — | — | — | *{r['recommendation']}* |")
    else:
        lines.append(f"=== SOURCE HEALTH DIAGNOSTIC REPORT ===")
        lines.append(f"Status: {summary['overall_status']} | Total: {summary['total']} | Healthy: {summary['healthy_count']} | Warning: {summary['warning_count']} | Broken: {summary['broken_count']}")
        lines.append("-" * 75)
        for r in results:
            icon = "[OK]" if r["status"] == "healthy" else ("[WARN]" if r["status"] == "warning" else "[BROKEN]")
            lines.append(f"{icon:<8} {r['kind']:<12} {r['name']:<18} Code: {str(r['status_code']):<4} {r['latency_ms']}ms - {r['message']}")
            if r["recommendation"]:
                lines.append(f"         ↳ Fix: {r['recommendation']}")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Source Health Diagnostics for Local AI Job Finder")
    parser.add_argument("--all", action="store_true", help="Check all configured sources instead of quick sample")
    parser.add_argument("--markdown", action="store_true", help="Output report in GitHub Markdown format")
    args = parser.parse_args()

    print("Running source health checks...")
    results = run_source_health_check(quick=not args.all)
    print(format_health_report(results, markdown=args.markdown))
