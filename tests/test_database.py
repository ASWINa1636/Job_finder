import pytest
from datetime import datetime, timedelta, timezone

from src.database import (
    upsert_jobs, list_jobs, purge_expired_jobs,
    update_status, update_job_metadata
)


class TestDatabaseMaintenance:
    def test_purge_expired_preserves_tracked_jobs(self):
        now = datetime.now(timezone.utc)
        old_date = (now - timedelta(days=25)).isoformat()
        fresh_date = (now - timedelta(days=2)).isoformat()

        test_jobs = [
            # 1. Old unapplied job (should be purged)
            {
                "title": "Old Unapplied Developer",
                "company": "TestOldCorp",
                "location": "Remote",
                "description": "Old python job",
                "job_url": "https://test.corp/purge_test_1",
                "source": "Greenhouse career board",
                "posted_at": old_date
            },
            # 2. Old applied job (MUST BE PRESERVED)
            {
                "title": "Old Applied Developer",
                "company": "TestGoodCorp",
                "location": "Bengaluru",
                "description": "Applied python job",
                "job_url": "https://test.corp/purge_test_2",
                "source": "Workday career board",
                "posted_at": old_date
            },
            # 3. Old favorited job (MUST BE PRESERVED)
            {
                "title": "Old Favorite Lead",
                "company": "TestFavCorp",
                "location": "Pune",
                "description": "Favorited role",
                "job_url": "https://test.corp/purge_test_3",
                "source": "Lever career board",
                "posted_at": old_date
            },
            # 4. Fresh unapplied job (MUST BE PRESERVED - <10 days)
            {
                "title": "Fresh Junior Dev",
                "company": "TestFreshCorp",
                "location": "Hyderabad",
                "description": "Fresh role",
                "job_url": "https://test.corp/purge_test_4",
                "source": "Greenhouse career board",
                "posted_at": fresh_date
            }
        ]

        # Insert jobs
        upsert_jobs(test_jobs)

        # Mark job 2 as Applied and job 3 as Favorite
        all_now = {j["job_url"]: j["id"] for j in list_jobs()}
        update_status(all_now["https://test.corp/purge_test_2"], "Applied")
        update_job_metadata(all_now["https://test.corp/purge_test_3"], is_favorite=1)

        # Run purge with 10 days retention
        deleted, remaining = purge_expired_jobs(max_age_days=10)

        # Retrieve current jobs
        current_jobs = list_jobs()
        job_urls = {j["job_url"] for j in current_jobs}

        # 1 should be deleted, 2, 3, 4 must remain
        assert "https://test.corp/purge_test_1" not in job_urls
        assert "https://test.corp/purge_test_2" in job_urls
        assert "https://test.corp/purge_test_3" in job_urls
        assert "https://test.corp/purge_test_4" in job_urls
