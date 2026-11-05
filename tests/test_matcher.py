import pytest
from src.matcher import extract_skills, rank_jobs, TECH_SKILLS, _normalise


class TestSkillExtraction:
    def test_extract_single_skill(self):
        text = "Looking for a Python developer with solid experience."
        skills = extract_skills(text)
        assert "python" in skills

    def test_extract_multiple_skills(self):
        text = "Candidate must know Python, FastAPI, Docker, and PostgreSQL on AWS."
        skills = extract_skills(text)
        for s in ["python", "fastapi", "docker", "postgresql", "aws"]:
            assert s in skills

    def test_multi_word_skills(self):
        text = "Deep understanding of machine learning, system design, and prompt engineering."
        skills = extract_skills(text)
        assert "machine learning" in skills
        assert "system design" in skills
        assert "prompt engineering" in skills

    def test_word_boundary_isolation(self):
        # 'go' should not match inside 'good' or 'algorithm'
        text = "He is a good programmer who writes nice algorithms."
        skills = extract_skills(text)
        assert "go" not in skills

    def test_c_sharp_and_c_plus_plus(self):
        text = "Experience with C++ and C# systems programming."
        skills = extract_skills(text)
        assert "c++" in skills
        assert "c#" in skills

    def test_case_insensitivity(self):
        text = "PYtHoN, KUBERNETES, ReAcT, and SQL."
        skills = extract_skills(text)
        assert set(skills) >= {"python", "kubernetes", "react", "sql"}

    def test_empty_and_none_text(self):
        assert extract_skills("") == []
        assert extract_skills(None) == []
        assert extract_skills("   \n\t  ") == []


class TestJobRanking:
    def test_rank_empty_jobs(self):
        ranked = rank_jobs("Experienced python engineer", [])
        assert ranked == []

    def test_rank_empty_resume(self):
        jobs = [
            {"title": "Python Dev", "description": "Write Python code", "company": "Acme"}
        ]
        ranked = rank_jobs("", jobs)
        assert len(ranked) == 1
        assert "match_score" in ranked[0]
        assert ranked[0]["match_score"] >= 0

    def test_matching_vs_non_matching_ranking(self):
        resume = "Senior Python engineer with AWS, Docker, Kubernetes, and FastAPI expertise."
        jobs = [
            {
                "id": 1,
                "title": "Senior Python Backend Engineer",
                "description": "Looking for Python, FastAPI, Docker, and Kubernetes on AWS.",
                "company": "Tech Corp"
            },
            {
                "id": 2,
                "title": "Flutter iOS Mobile Developer",
                "description": "Requires Swift, Kotlin, Flutter, and iOS mobile store deployments.",
                "company": "Mobile Ltd"
            }
        ]
        ranked = rank_jobs(resume, jobs)
        assert len(ranked) == 2
        # First ranked job must be the Python one
        assert ranked[0]["id"] == 1
        assert ranked[0]["match_score"] > ranked[1]["match_score"]
        assert "python" in ranked[0]["matched_skills"]
        assert "docker" in ranked[0]["matched_skills"]
        assert "fastapi" in ranked[0]["matched_skills"]

    def test_skill_difference_lists(self):
        resume = "Python SQL developer"
        jobs = [{
            "id": 10,
            "title": "Full Stack Engineer",
            "description": "Must have Python, SQL, React, and Redis.",
            "company": "Startup"
        }]
        ranked = rank_jobs(resume, jobs)
        assert set(ranked[0]["matched_skills"]) == {"python", "sql"}
        assert "react" in ranked[0]["missing_skills"]
        assert "redis" in ranked[0]["missing_skills"]

    def test_normalise_helper(self):
        raw = "   Senior    PYTHON  \n  Engineer\t "
        assert _normalise(raw) == "senior python engineer"
