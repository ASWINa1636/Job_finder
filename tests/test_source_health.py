from unittest.mock import patch, MagicMock
import requests
import pytest

from src.source_health import (
    check_endpoint, summarize_health_results, format_health_report, build_source_catalog
)


class TestSourceHealth:
    def test_healthy_endpoint(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jobs": [{"title": "Software Engineer"}]}

        with patch("requests.get", return_value=mock_resp):
            res = check_endpoint("Greenhouse", "Acme", "https://api.test/jobs", method="get")
            assert res["status"] == "healthy"
            assert res["items_found"] == 1
            assert res["status_code"] == 200
            assert "OK" in res["message"]

    def test_warning_empty_jobs(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"jobs": []}

        with patch("requests.get", return_value=mock_resp):
            res = check_endpoint("Greenhouse", "Acme", "https://api.test/jobs", method="get")
            assert res["status"] == "warning"
            assert res["items_found"] == 0
            assert "0 postings" in res["message"]
            assert res["recommendation"] != ""

    def test_broken_404_not_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 404

        with patch("requests.get", return_value=mock_resp):
            res = check_endpoint("Lever", "OldCompany", "https://api.test/old", method="get")
            assert res["status"] == "broken"
            assert res["status_code"] == 404
            assert "404" in res["message"]
            assert "not found" in res["recommendation"].lower()

    def test_broken_403_forbidden(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 403

        with patch("requests.get", return_value=mock_resp):
            res = check_endpoint("Workday", "TargetCo", "https://api.test/wd", method="get")
            assert res["status"] == "broken"
            assert res["status_code"] == 403
            assert "Forbidden" in res["message"]

    def test_broken_non_json_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Invalid JSON")

        with patch("requests.get", return_value=mock_resp):
            res = check_endpoint("Feed", "CustomFeed", "https://api.test/feed", method="get")
            assert res["status"] == "broken"
            assert "not valid JSON" in res["message"]

    def test_broken_timeout_exception(self):
        with patch("requests.get", side_effect=requests.exceptions.Timeout("Timed out")):
            res = check_endpoint("Workday", "SlowCo", "https://api.test/slow", method="get", timeout=3)
            assert res["status"] == "broken"
            assert "timed out" in res["message"].lower()

    def test_summarize_health_results(self):
        sample_results = [
            {"status": "healthy", "name": "A", "kind": "GH"},
            {"status": "warning", "name": "B", "kind": "Lever"},
            {"status": "broken", "name": "C", "kind": "WD", "message": "404", "recommendation": "Fix it"}
        ]
        summary = summarize_health_results(sample_results)
        assert summary["total"] == 3
        assert summary["healthy_count"] == 1
        assert summary["warning_count"] == 1
        assert summary["broken_count"] == 1
        assert summary["overall_status"] == "CRITICAL"

    def test_format_reports(self):
        sample_results = [
            {"status": "healthy", "name": "Acme", "kind": "GH", "status_code": 200, "latency_ms": 150, "message": "OK", "recommendation": ""},
            {"status": "broken", "name": "BadCo", "kind": "WD", "status_code": 404, "latency_ms": 200, "message": "404 Not Found", "recommendation": "Check site name"}
        ]
        text_report = format_health_report(sample_results, markdown=False)
        assert "[OK]" in text_report
        assert "[BROKEN]" in text_report
        assert "BadCo" in text_report

        md_report = format_health_report(sample_results, markdown=True)
        assert "## 🩺 Source Health Diagnostic Report" in md_report
        assert "| 🟢 HEALTHY |" in md_report
        assert "| 🔴 BROKEN |" in md_report

    def test_build_source_catalog(self):
        targets = build_source_catalog(quick=True)
        assert len(targets) > 0
        kinds = {t["kind"] for t in targets}
        assert "Greenhouse" in kinds
        assert "Lever.co" in kinds
        assert "Workday" in kinds
        assert "Public Feed" in kinds
