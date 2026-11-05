import sys
from pathlib import Path
from datetime import datetime, timezone
import sqlite3
import shutil

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "jobs.sqlite3"
BACKUP_DIR = DATA_DIR / "backups"

JOB_COLUMNS = {
    "experience_level": "TEXT DEFAULT 'Unknown'",
    "job_type": "TEXT DEFAULT 'Unknown'",
    "work_mode": "TEXT DEFAULT 'Unknown'",
    "salary_min": "REAL",
    "salary_max": "REAL",
    "salary_currency": "TEXT DEFAULT ''",
    "application_deadline": "TEXT DEFAULT ''",
    "is_favorite": "INTEGER DEFAULT 0",
    "notes": "TEXT DEFAULT ''",
    "last_seen_at": "TEXT DEFAULT ''",
    "first_seen_at": "TEXT DEFAULT ''",
    "source_status": "TEXT DEFAULT 'Unknown'",
}

def connect():
    """Open a busy-timeout SQLite connection without changing journal mode on every rerun."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=45)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=45000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    # Set WAL once at startup, rather than on every Streamlit rerun/connection.
    # A busy timeout handles brief locks from a second Streamlit process or backup operation.
    with connect() as conn:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() and "busy" not in str(exc).lower():
                raise
        conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            location TEXT DEFAULT '',
            description TEXT DEFAULT '',
            job_url TEXT NOT NULL UNIQUE,
            source TEXT DEFAULT '',
            posted_at TEXT DEFAULT '',
            employment_type TEXT DEFAULT '',
            status TEXT DEFAULT 'New',
            discovered_at TEXT NOT NULL
        )""")
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(jobs)")}
        for name, declaration in JOB_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {name} {declaration}")
        conn.execute("UPDATE jobs SET first_seen_at=discovered_at WHERE first_seen_at IS NULL OR first_seen_at=''")
        conn.execute("UPDATE jobs SET last_seen_at=discovered_at WHERE last_seen_at IS NULL OR last_seen_at=''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(posted_at)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            finished_at TEXT DEFAULT '',
            fetched_count INTEGER DEFAULT 0,
            inserted_count INTEGER DEFAULT 0,
            updated_count INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            message TEXT DEFAULT ''
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS company_watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            notes TEXT DEFAULT ''
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id INTEGER NOT NULL,
            old_status TEXT DEFAULT '',
            new_status TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        )""")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS saved_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            filters_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def create_sync_run():
    with connect() as conn:
        cur = conn.execute("INSERT INTO sync_runs(started_at) VALUES (?)", (now_iso(),))
        return cur.lastrowid

def finish_sync_run(run_id, fetched, inserted, updated, errors):
    with connect() as conn:
        conn.execute("""
        UPDATE sync_runs SET finished_at=?, fetched_count=?, inserted_count=?,
        updated_count=?, error_count=?, message=? WHERE id=?
        """, (now_iso(), fetched, inserted, updated, len(errors),
              "\n".join(errors[:30]), run_id))

def upsert_jobs(jobs):
    inserted = updated = 0
    now = now_iso()
    with connect() as conn:
        for job in jobs:
            url = (job.get("job_url") or "").strip()
            title = (job.get("title") or "").strip()
            company = (job.get("company") or "").strip()
            if not url or not title or not company:
                continue
            old = conn.execute("SELECT id, status, discovered_at FROM jobs WHERE job_url=?", (url,)).fetchone()
            values = (
                title, company, job.get("location", ""), job.get("description", ""),
                url, job.get("source", ""), job.get("posted_at", ""),
                job.get("employment_type", ""), job.get("experience_level", "Unknown"),
                job.get("job_type", "Unknown"), job.get("work_mode", "Unknown"),
                job.get("salary_min"), job.get("salary_max"), job.get("salary_currency", ""),
                job.get("application_deadline", ""), now, now
            )
            if old:
                # Preserve application status, notes, favourites and first-seen/discovery history.
                conn.execute("""
                UPDATE jobs SET title=?, company=?, location=?, description=?, source=?,
                    posted_at=CASE WHEN ? != '' THEN ? ELSE posted_at END,
                    employment_type=?, experience_level=?, job_type=?, work_mode=?,
                    salary_min=COALESCE(?, salary_min), salary_max=COALESCE(?, salary_max),
                    salary_currency=CASE WHEN ? != '' THEN ? ELSE salary_currency END,
                    application_deadline=CASE WHEN ? != '' THEN ? ELSE application_deadline END,
                    last_seen_at=?, source_status='Found'
                WHERE job_url=?
                """, (title, company, job.get("location", ""), job.get("description", ""),
                      job.get("source", ""), job.get("posted_at", ""), job.get("posted_at", ""),
                      job.get("employment_type", ""), job.get("experience_level", "Unknown"),
                      job.get("job_type", "Unknown"), job.get("work_mode", "Unknown"),
                      job.get("salary_min"), job.get("salary_max"),
                      job.get("salary_currency", ""), job.get("salary_currency", ""),
                      job.get("application_deadline", ""), job.get("application_deadline", ""),
                      now, url))
                updated += 1
            else:
                conn.execute("""
                INSERT INTO jobs (title, company, location, description, job_url, source,
                    posted_at, employment_type, status, discovered_at, experience_level,
                    job_type, work_mode, salary_min, salary_max, salary_currency,
                    application_deadline, last_seen_at, first_seen_at, source_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'New', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Found')
                """, (title, company, job.get("location", ""), job.get("description", ""),
                      url, job.get("source", ""), job.get("posted_at", ""),
                      job.get("employment_type", ""), now,
                      job.get("experience_level", "Unknown"), job.get("job_type", "Unknown"),
                      job.get("work_mode", "Unknown"), job.get("salary_min"),
                      job.get("salary_max"), job.get("salary_currency", ""),
                      job.get("application_deadline", ""), now, now))
                inserted += 1
    return inserted, updated

def list_jobs(status=None, limit=10000):
    with connect() as conn:
        if status and status != "All":
            rows = conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY discovered_at DESC LIMIT ?", (status, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM jobs ORDER BY discovered_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

def update_status(job_id, status):
    allowed = {"New", "Interested", "Applied", "Interview", "Rejected", "Saved", "Offer"}
    with connect() as conn:
        old = conn.execute("SELECT status FROM jobs WHERE id=?", (int(job_id),)).fetchone()
        if not old:
            return
        if old["status"] != status:
            conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, int(job_id)))
            conn.execute("INSERT INTO status_history(job_id,old_status,new_status,changed_at) VALUES (?,?,?,?)",
                         (int(job_id), old["status"], status, now_iso()))

def update_job_metadata(job_id, **fields):
    allowed = {"is_favorite", "notes", "application_deadline"}
    values = {k: v for k, v in fields.items() if k in allowed}
    if not values:
        return
    clause = ", ".join(f"{k}=?" for k in values)
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {clause} WHERE id=?", (*values.values(), int(job_id)))

def add_watchlist(company, notes=""):
    company = company.strip()
    if not company:
        return
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO company_watchlist(company,created_at,notes) VALUES (?,?,?)",
                     (company, now_iso(), notes))

def remove_watchlist(company):
    with connect() as conn:
        conn.execute("DELETE FROM company_watchlist WHERE company=?", (company,))

def get_watchlist():
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM company_watchlist ORDER BY company").fetchall()]

def get_sync_runs(limit=50):
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

def get_status_history(limit=300):
    with connect() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT h.*, j.title, j.company FROM status_history h
            LEFT JOIN jobs j ON j.id=h.job_id ORDER BY h.id DESC LIMIT ?
        """, (limit,)).fetchall()]

def save_search(name, filters_json):
    with connect() as conn:
        conn.execute("INSERT OR REPLACE INTO saved_searches(name,filters_json,created_at) VALUES (?,?,?)",
                     (name.strip(), filters_json, now_iso()))

def get_saved_searches():
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM saved_searches ORDER BY name").fetchall()]

def delete_saved_search(name):
    with connect() as conn:
        conn.execute("DELETE FROM saved_searches WHERE name=?", (name,))

def backup_db():
    """Create one consistent SQLite backup per day; do not overwrite existing daily backup."""
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    target = BACKUP_DIR / f"jobs_{stamp}.sqlite3"
    if not target.exists():
        # SQLite backup API is safe with WAL mode and active connections.
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
    backups = sorted(BACKUP_DIR.glob("jobs_*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[30:]:
        old.unlink(missing_ok=True)
    return target

def restore_db_from_bytes(data):
    """Restore a user-selected SQLite backup after validating it; current DB is backed up first."""
    import tempfile
    backup_db()
    tmp = DATA_DIR / "restore_candidate.sqlite3"
    tmp.write_bytes(data)
    try:
        check = sqlite3.connect(tmp)
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        check.close()
        if result != "ok" or "jobs" not in tables:
            raise ValueError("This file is not a valid Local AI Job Finder database.")
        with sqlite3.connect(tmp) as src, sqlite3.connect(DB_PATH) as dst:
            src.backup(dst)
    finally:
        tmp.unlink(missing_ok=True)

def export_db_bytes():
    """Create a consistent in-memory SQLite snapshot; avoids Windows temp-file locks."""
    if not DB_PATH.exists():
        return b""
    source = sqlite3.connect(DB_PATH, timeout=45)
    target = sqlite3.connect(":memory:")
    try:
        source.execute("PRAGMA busy_timeout=45000")
        source.backup(target)
        return target.serialize()
    finally:
        target.close()
        source.close()

def purge_expired_jobs(max_age_days=10):
    """
    Deletes unapplied, non-favorited, note-less jobs older than max_age_days.
    Preserves all tracked jobs (Applied, Interview, Offer, Rejected, Favorites, and Notes).
    Runs VACUUM to compact the database file and reduce disk space.
    Returns (deleted_count, remaining_count).
    """
    from datetime import date, timedelta
    try:
        from src.helpers import parse_date
    except ImportError:
        from .helpers import parse_date

    cutoff = date.today() - timedelta(days=max_age_days)
    with connect() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("SELECT id, posted_at, discovered_at, status, is_favorite, notes FROM jobs")
        rows = cur.fetchall()

        ids_to_delete = []
        for r in rows:
            # Protect user's active applications and favorites
            if r["status"] in ("Applied", "Interview", "Offer", "Rejected") or r["is_favorite"] == 1 or (r["notes"] and r["notes"].strip()):
                continue

            dt = parse_date(r["posted_at"]) or parse_date(r["discovered_at"])
            if dt and dt < cutoff:
                ids_to_delete.append(r["id"])

        if ids_to_delete:
            batch_size = 500
            for i in range(0, len(ids_to_delete), batch_size):
                batch = ids_to_delete[i:i + batch_size]
                q = f"DELETE FROM jobs WHERE id IN ({','.join(['?'] * len(batch))})"
                conn.execute(q, batch)
            conn.commit()

    # Reclaim disk space
    with connect() as conn:
        conn.execute("VACUUM")

    with connect() as conn:
        rem = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]

    return len(ids_to_delete), rem

