import io
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import pytest

from docx import Document
from src.resume_parser import extract_resume_text
from src.helpers import (
    inferred_role, inferred_exp, inferred_type, inferred_mode,
    inferred_platform, platform_badge_info, safe_salary,
    parse_date, relative_date, is_outdated_job, is_missed_job
)


class TestResumeParser:
    def test_parse_txt_file(self, tmp_path):
        txt_file = tmp_path / "resume.txt"
        content = "John Doe\nPython Full Stack Developer with 4 years experience in Django & React."
        txt_file.write_text(content, encoding="utf-8")

        result = extract_resume_text(str(txt_file))
        assert "John Doe" in result
        assert "Django & React" in result

    def test_parse_txt_bytesio(self):
        class NamedBytesIO(io.BytesIO):
            def __init__(self, data, name):
                super().__init__(data)
                self.name = name

        data = b"Software Engineer skilled in Go and Kubernetes."
        stream = NamedBytesIO(data, "my_resume.txt")
        result = extract_resume_text(stream)
        assert "Software Engineer" in result
        assert "Kubernetes" in result

    def test_parse_docx_file(self, tmp_path):
        docx_file = tmp_path / "resume.docx"
        doc = Document()
        doc.add_paragraph("Jane Doe - Cloud DevOps Architect")
        doc.add_paragraph("Expert in Terraform, AWS, and Docker CI/CD.")
        doc.save(str(docx_file))

        result = extract_resume_text(str(docx_file))
        assert "Jane Doe" in result
        assert "Terraform" in result

    def test_docx_xml_fallback(self, tmp_path):
        docx_file = tmp_path / "resume_raw.docx"
        xml_content = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
        <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
            <w:body>
                <w:p><w:r><w:t>Fallback Candidate - Linux Kernel Specialist</w:t></w:r></w:p>
            </w:body>
        </w:document>"""
        with zipfile.ZipFile(docx_file, "w") as z:
            z.writestr("word/document.xml", xml_content)

        # Force ImportError for docx.Document to trigger the XML fallback
        with patch.dict("sys.modules", {"docx": None}):
            result = extract_resume_text(str(docx_file))
            assert "Fallback Candidate" in result
            assert "Linux Kernel Specialist" in result

    def test_unsupported_format_raises(self, tmp_path):
        bad_file = tmp_path / "photo.jpg"
        bad_file.write_bytes(b"\xff\xd8\xff")
        with pytest.raises(ValueError, match="Supported resume formats"):
            extract_resume_text(str(bad_file))

    def test_unsupported_input_type_raises(self):
        with pytest.raises(ValueError, match="Unsupported input type"):
            extract_resume_text(12345)


class TestHelperParsers:
    def test_inferred_role_classifications(self):
        assert inferred_role({"title": "Senior Backend Developer"}) == "Backend Engineer"
        assert inferred_role({"title": "React Frontend Engineer"}) == "Frontend Engineer"
        assert inferred_role({"title": "Fullstack Java & Angular Developer"}) == "Full Stack Engineer"
        assert inferred_role({"title": "Staff ML Engineer (LLMs & PyTorch)"}) == "AI / ML / Data Science"
        assert inferred_role({"title": "Data Pipeline & ETL Engineer"}) == "Data Engineer / Analytics"
        assert inferred_role({"title": "DevOps / SRE Specialist"}) == "DevOps / Cloud / SRE"
        assert inferred_role({"title": "iOS Swift App Developer"}) == "Mobile Developer"
        assert inferred_role({"title": "QA Automation Engineer (Playwright)"}) == "QA / Automation / SDET"
        assert inferred_role({"title": "Cybersecurity & SOC Analyst"}) == "Security / Cybersecurity"
        assert inferred_role({"title": "Embedded Systems & Firmware Engineer"}) == "Hardware / Embedded / IoT"
        assert inferred_role({"title": "Product Marketing Lead"}) == "Other Engineering"

    def test_inferred_exp_levels(self):
        assert inferred_exp({"title": "Software Engineer Intern"}) == "Internship"
        assert inferred_exp({"description": "Fresh graduates welcome, entry-level candidates"}) == "Fresher / 0–1 year"
        assert inferred_exp({"title": "Principal Staff Engineer"}) == "5+ years"
        assert inferred_exp({"description": "Requires 3+ years experience in Python"}) == "3–5 years"
        assert inferred_exp({"description": "Requires 2+ years experience with React"}) == "1–3 years"
        assert inferred_exp({"title": "Developer", "description": "Good communication"}) == "Unknown"

    def test_inferred_type(self):
        assert inferred_type({"title": "Summer Intern 2026"}) == "Internship"
        assert inferred_type({"employment_type": "contract", "title": "Developer"}) == "Contract"
        assert inferred_type({"employment_type": "full-time", "title": "Backend Developer"}) == "Full-time"
        assert inferred_type({"title": "Backend Developer"}) == "Unknown"

    def test_inferred_mode(self):
        assert inferred_mode({"location": "Remote - Worldwide"}) == "Remote"
        assert inferred_mode({"location": "Bengaluru (Hybrid)"}) == "Hybrid"
        assert inferred_mode({"location": "Mumbai Onsite Office"}) == "Onsite" or inferred_mode({"location": "Mumbai Onsite Office"}) == "On-site"

    def test_inferred_platform_and_badges(self):
        # Workday
        wd_job = {"job_url": "https://ag.wd3.myworkdayjobs.com/en-US/Airbus/job/123", "source": "Workday career board"}
        assert inferred_platform(wd_job) == "Workday"
        plat_name, plat_type, icon = platform_badge_info(wd_job)
        assert plat_name == "Workday"
        assert plat_type == "Direct ATS Board"
        assert icon == "🏢"

        # Greenhouse
        gh_job = {"job_url": "https://boards.greenhouse.io/databricks/jobs/456", "source": "Greenhouse career board"}
        assert inferred_platform(gh_job) == "Greenhouse"

        # Lever
        lever_job = {"job_url": "https://jobs.lever.co/spotify/789", "source": "Lever career board"}
        assert inferred_platform(lever_job) == "Lever.co"

        # Direct Career Portal
        portal_job = {"job_url": "https://www.accenture.com/in-en/careers/jobdetails?id=1", "source": "Company Career Page"}
        assert inferred_platform(portal_job) == "Career Page"
        plat_name, plat_type, icon = platform_badge_info(portal_job)
        assert plat_type == "Company Career Portal"
        assert icon == "🌐"

        # Public aggregator
        feed_job = {"job_url": "https://remoteok.com/remote-jobs/101", "source": "Remote OK public feed"}
        assert inferred_platform(feed_job) == "Remote OK"
        plat_name, plat_type, icon = platform_badge_info(feed_job)
        assert plat_type == "Public Job Feed"
        assert icon == "⚡"

    def test_safe_salary_normalization(self):
        assert safe_salary({"salary_min": 120000, "salary_max": 140000, "salary_currency": "USD"}) == "USD 120,000–140,000"
        assert safe_salary({"salary_min": 1800000, "salary_currency": "INR"}) == "INR 1,800,000+"
        assert safe_salary({"salary_max": 2500000, "salary_currency": "INR"}) == "Up to INR 2,500,000"
        assert safe_salary({}) == "Not disclosed"

    def test_date_and_missed_outdated_logic(self):
        now = datetime.now(timezone.utc)
        fresh_date = (now - timedelta(days=5)).isoformat()
        old_date = (now - timedelta(days=45)).isoformat()

        fresh_job = {"posted_at": fresh_date, "status": "Interested"}
        old_unapplied = {"posted_at": old_date, "status": "Interested"}
        old_applied = {"posted_at": old_date, "status": "Applied"}

        assert is_outdated_job(fresh_job) is False
        assert is_outdated_job(old_unapplied) is True

        assert is_missed_job(fresh_job) is False
        assert is_missed_job(old_unapplied) is True
        assert is_missed_job(old_applied) is False  # Already applied!
