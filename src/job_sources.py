import json, os, re, sys
from pathlib import Path
import requests

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "companies.json"
TIMEOUT = 18
HEADERS = {"User-Agent":"LocalJobFinder/2.0 (personal job search app)", "Accept":"application/json"}

def clean_html(value):
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()

def get_json(url, params=None):
    response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()

def load_company_config():
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        data.setdefault("greenhouse", [])
        data.setdefault("lever", [])
        data.setdefault("workday", [])
        data.setdefault("company_names", {})
        return data
    except (OSError, json.JSONDecodeError):
        return {"greenhouse": [], "lever": [], "workday": [], "company_names": {}}

def infer_fields(job):
    text = (job.get("title","") + " " + job.get("description","")).lower()
    loc = (job.get("location","") or "").lower()
    title = (job.get("title","") or "").lower()
    if any(x in title for x in ["intern", "internship", "trainee", "co-op"]):
        job_type = "Internship" if "intern" in title else "Trainee"
    elif any(x in text for x in ["part-time", "part time"]):
        job_type = "Part-time"
    elif any(x in text for x in ["contract role", "contract position", "contractor"]):
        job_type = "Contract"
    elif "full-time" in text or "full time" in text:
        job_type = "Full-time"
    else:
        job_type = job.get("employment_type") or "Unknown"
    if any(x in loc for x in ["remote", "worldwide", "anywhere"]) or "remote" in title:
        work_mode = "Remote"
    elif "hybrid" in loc or "hybrid" in title:
        work_mode = "Hybrid"
    elif loc:
        work_mode = "On-site"
    else:
        work_mode = "Unknown"
    if any(x in text for x in ["0-1 year", "0–1 year", "fresher", "new grad", "graduate program", "entry-level", "entry level", "early career"]):
        experience = "Fresher / 0–1 year"
    elif any(x in text for x in ["intern", "internship", "student"]):
        experience = "Internship"
    elif any(x in text for x in ["5+ years", "5 years", "senior", "staff engineer", "principal"]):
        experience = "5+ years"
    elif any(x in text for x in ["3+ years", "3-5 years", "3–5 years", "mid-level", "mid level"]):
        experience = "3–5 years"
    elif any(x in text for x in ["1+ years", "2+ years", "1-3 years", "1–3 years"]):
        experience = "1–3 years"
    elif any(x in title for x in ["junior", "graduate", "associate"]):
        experience = "Fresher / 0–1 year"
    else:
        experience = job.get("experience_level") or "Unknown"
    job.update({"job_type": job.get("job_type") or job_type,
                "work_mode": job.get("work_mode") or work_mode,
                "experience_level": job.get("experience_level") or experience})
    return job

def fetch_greenhouse(board_token):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs", {"content":"true"})
    result=[]
    for item in data.get("jobs", []):
        result.append(infer_fields({
            "title":item.get("title",""), "company":board_token.replace("-"," ").title(),
            "location":(item.get("location") or {}).get("name",""),
            "description":clean_html(item.get("content","")),
            "job_url":item.get("absolute_url",""), "source":"Greenhouse career board",
            "posted_at":item.get("updated_at","") or "", "employment_type":"Unknown"
        }))
    return result

def fetch_lever(site):
    data = get_json(f"https://api.lever.co/v0/postings/{site}", {"mode":"json"})
    result=[]
    for item in data if isinstance(data,list) else []:
        cats=item.get("categories") or {}
        desc=" ".join([item.get("descriptionPlain",""), item.get("additional","")] +
                      [x.get("content","") for x in (item.get("lists") or [])])
        result.append(infer_fields({
            "title":item.get("text",""), "company":site.replace("-"," ").title(),
            "location":cats.get("location",""), "description":clean_html(desc),
            "job_url":item.get("hostedUrl") or item.get("applyUrl") or "",
            "source":"Lever career board", "posted_at":item.get("createdAt","") or "",
            "employment_type":cats.get("commitment","Unknown")
        }))
    return result

def fetch_workday(domain, tenant, site_name, limit=40, search_text=""):
    """
    Fetches live job postings from a Workday career portal.
    Workday enforces max 20 jobs per page request, so we paginate using limit=20.
    """
    url = f"https://{domain}/wday/cxs/{tenant}/{site_name}/jobs"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    result = []
    base_portal = f"https://{domain}/en-US/{site_name}"
    total_wanted = int(limit)
    page_size = 20
    offset = 0

    while len(result) < total_wanted:
        cur_limit = min(page_size, total_wanted - len(result))
        payload = {
            "appliedFacets": {},
            "limit": cur_limit,
            "offset": offset,
            "searchText": search_text or ""
        }
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except Exception:
            break

        postings = data.get("jobPostings", [])
        if not postings:
            break

        for item in postings:
            path = item.get("externalPath", "")
            job_url = f"{base_portal}{path}" if path else base_portal
            title = item.get("title", "")
            loc = item.get("locationsText") or ""
            if not loc and item.get("bulletFields"):
                bfs = item.get("bulletFields", [])
                for b in bfs:
                    if any(c in b.lower() for c in ["bengaluru", "bangalore", "hyderabad", "pune", "mumbai", "delhi", "gurugram", "chennai", "noida", "kolkata", "india"]):
                        loc = b
                        break
                if not loc and len(bfs) > 1:
                    loc = bfs[1]

            posted = item.get("postedOn", "")
            bullet_req = ", ".join(item.get("bulletFields", []))
            desc = f"{title}. Location: {loc}. Requisition ID: {bullet_req}." if bullet_req else f"{title}. Location: {loc}."

            result.append(infer_fields({
                "title": title,
                "company": tenant.replace("-", " ").title(),
                "location": loc or "",
                "description": clean_html(desc),
                "job_url": job_url,
                "source": "Workday career board",
                "posted_at": posted or "",
                "employment_type": "Unknown"
            }))

        offset += len(postings)
        total_available = data.get("total", 0)
        if offset >= total_available:
            break

    return result

def fetch_arbeitnow(limit=100):
    """Public job-board API; coverage and geography depend on its current feed."""
    data = get_json("https://www.arbeitnow.com/api/job-board-api", {"page": 1})
    result = []
    items = data.get("data", []) if isinstance(data, dict) else []
    for item in items[:int(limit)]:
        result.append(infer_fields({
            "title": item.get("title", ""),
            "company": item.get("company_name", "Unknown company"),
            "location": item.get("location", "Remote" if item.get("remote") else ""),
            "description": clean_html(item.get("description", "")),
            "job_url": item.get("url", ""),
            "source": "Arbeitnow public job feed",
            "posted_at": item.get("created_at", "") or "",
            "employment_type": "Unknown",
        }))
    return result

def fetch_jobicy(limit=50):
    """Public remote-jobs API; listings are primarily remote roles."""
    data = get_json("https://jobicy.com/api/v2/remote-jobs", {"count": int(limit)})
    result = []
    items = data.get("jobs", []) if isinstance(data, dict) else []
    for item in items:
        result.append(infer_fields({
            "title": item.get("jobTitle", ""),
            "company": item.get("companyName", "Unknown company"),
            "location": item.get("jobGeo", "Remote"),
            "description": clean_html(item.get("jobDescription", "")),
            "job_url": item.get("url") or item.get("jobUrl", ""),
            "source": "Jobicy remote jobs feed",
            "posted_at": item.get("pubDate", "") or "",
            "employment_type": ", ".join(item.get("jobType", [])) if isinstance(item.get("jobType"), list) else item.get("jobType", "Unknown"),
        }))
    return result

def fetch_remoteok(limit=100):
    """Public Remote OK feed; remote-only coverage."""
    data = get_json("https://remoteok.com/api", params=None)
    result = []
    items = data[1:] if isinstance(data, list) and data and isinstance(data[0], dict) and "legal" in data[0] else (data if isinstance(data, list) else [])
    for item in items[:int(limit)]:
        if not isinstance(item, dict) or not item.get("position") or not item.get("company"):
            continue
        tags = item.get("tags", [])
        result.append(infer_fields({
            "title": item.get("position", ""),
            "company": item.get("company", "Unknown company"),
            "location": item.get("location", "Remote"),
            "description": clean_html(item.get("description", "")),
            "job_url": item.get("url", ""),
            "source": "Remote OK public feed",
            "posted_at": item.get("date", "") or "",
            "employment_type": "Unknown",
        }))
    return result

def fetch_remotive(limit=None):
    limit=int(limit or os.getenv("REMOTIVE_LIMIT","100"))
    data=get_json("https://remotive.com/api/remote-jobs", {"limit":limit})
    result=[]
    for item in data.get("jobs",[]):
        result.append(infer_fields({
            "title":item.get("title",""), "company":item.get("company_name",""),
            "location":item.get("candidate_required_location","Remote"),
            "description":clean_html(item.get("description","")), "job_url":item.get("url",""),
            "source":"Remotive remote jobs feed", "posted_at":item.get("publication_date","") or "",
            "employment_type":item.get("job_type","Unknown")
        }))
    return result

def fetch_all_jobs(progress_callback=None):
    config = load_company_config()
    jobs, errors, sources = [], [], []
    company_names = config.get("company_names", {})
    for token in config.get("greenhouse", []):
        sources.append(("Greenhouse", token, lambda t=token: fetch_greenhouse(t)))
    for site in config.get("lever", []):
        sources.append(("Lever", site, lambda s=site: fetch_lever(s)))
    for wd in config.get("workday", []):
        if isinstance(wd, dict) and wd.get("domain") and wd.get("tenant") and wd.get("site"):
            c_name = wd.get("company") or wd["tenant"].title()
            sources.append(("Workday", c_name, lambda w=wd: fetch_workday(w["domain"], w["tenant"], w["site"], limit=w.get("limit", 40))))

    total_sources = len(sources) + 4
    completed = 0
    for kind, name, fetcher in sources:
        completed += 1
        try:
            batch = fetcher()
            for job in batch:
                key = name.lower()
                if key in company_names:
                    job["company"] = company_names[key]
            jobs.extend(batch)
            if progress_callback:
                progress_callback(completed, total_sources, f"{kind}: {name} — {len(batch)} jobs")
        except Exception as exc:
            errors.append(f"{kind} / {name}: {type(exc).__name__}: {exc}")

    feed_fetchers = [
        ("Remotive", fetch_remotive),
        ("Arbeitnow", fetch_arbeitnow),
        ("Jobicy", fetch_jobicy),
        ("Remote OK", fetch_remoteok),
    ]
    for kind, fetcher in feed_fetchers:
        completed += 1
        try:
            batch = fetcher()
            jobs.extend(batch)
            if progress_callback:
                progress_callback(completed, total_sources, f"{kind} — {len(batch)} jobs")
        except Exception as exc:
            errors.append(f"{kind}: {type(exc).__name__}: {exc}")

    unique, seen = [], set()
    for job in jobs:
        url = (job.get("job_url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            unique.append(job)
    return unique, errors, len(sources) + len(feed_fetchers)
