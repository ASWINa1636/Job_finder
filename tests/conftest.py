import sys
from pathlib import Path
import pytest

# Ensure tkinder is in sys.path
tkinder_dir = Path(__file__).resolve().parent.parent
if str(tkinder_dir) not in sys.path:
    sys.path.insert(0, str(tkinder_dir))

from src.database import init_db
import src.database as db_module


@pytest.fixture(autouse=True)
def isolated_test_db(tmp_path):
    """
    Ensure every test runs against a clean, isolated SQLite test database
    with tables initialized via init_db(), so tests never fail in fresh CI environments.
    """
    orig_db_path = db_module.DB_PATH
    orig_data_dir = db_module.DATA_DIR
    orig_backup_dir = db_module.BACKUP_DIR

    test_db = tmp_path / "test_jobs.sqlite3"
    db_module.DB_PATH = test_db
    db_module.DATA_DIR = tmp_path
    db_module.BACKUP_DIR = tmp_path / "backups"

    # Initialize all database tables
    init_db()

    yield test_db

    # Restore original database pointers
    db_module.DB_PATH = orig_db_path
    db_module.DATA_DIR = orig_data_dir
    db_module.BACKUP_DIR = orig_backup_dir
