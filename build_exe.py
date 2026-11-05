"""
Automated PyInstaller Build & Release Packaging Script
Builds the standalone LocalJobFinder.exe distribution with all dependencies and assets.
"""

import os
import sys
import shutil
import zipfile
import subprocess
from pathlib import Path

# Force UTF-8 stream handling on Windows to prevent cp1252 UnicodeEncodeError
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build():
    print("=" * 60)
    print("[BUILD] Building Local AI Job Finder Standalone Executable")
    print("=" * 60)

    dist_dir = ROOT / "dist"
    build_dir = ROOT / "build"
    app_dist = dist_dir / "LocalJobFinder"

    # Clean previous build artifacts
    if app_dist.exists():
        print("Cleaning previous dist folder...")
        shutil.rmtree(app_dist, ignore_errors=True)

    # Ensure database exists before bundling
    try:
        from src.database import init_db
        init_db()
        print("[INIT] Database initialized successfully.")
    except Exception as e:
        print(f"[WARN] Database initialization note: {e}")

    add_data_args = [
        f"--add-data={ROOT / 'config'}{os.pathsep}config",
    ]
    if (ROOT / "data" / "jobs.sqlite3").exists():
        add_data_args.append(f"--add-data={ROOT / 'data' / 'jobs.sqlite3'}{os.pathsep}data")

    # Ensure setuptools / pkg_resources is available (required by altgraph on Python 3.12+)
    try:
        import pkg_resources
    except ImportError:
        print("[INIT] Installing setuptools for pkg_resources compatibility in Python 3.12+...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "setuptools"])

    # Verify PyInstaller is installed in the current Python environment
    try:
        import PyInstaller
        print(f"[OK] PyInstaller detected: version {PyInstaller.__version__}")
    except ImportError:
        print("[WARN] PyInstaller not imported in current runtime. Installing directly...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "setuptools<72.0.0", "pyinstaller>=6.11.0", "pyinstaller-hooks-contrib"])

    pyinstaller_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=LocalJobFinder",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
    ] + add_data_args + [
        "--hidden-import=matplotlib.backends.backend_tkagg",
        "--hidden-import=sklearn.utils._typedefs",
        "--hidden-import=sklearn.neighbors._typedefs",
        "--hidden-import=PIL._tkinter_finder",
        "--hidden-import=requests",
        "--hidden-import=pandas",
        "--hidden-import=pymupdf",
        str(ROOT / "app.py")
    ]

    print(f"Running PyInstaller command with {sys.executable} in {ROOT}...")
    proc = subprocess.run(pyinstaller_cmd, cwd=str(ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"PyInstaller failed with exit code {proc.returncode}")

    # Verify that LocalJobFinder.exe exists
    exe_path = app_dist / "LocalJobFinder.exe"
    if not exe_path.exists():
        raise RuntimeError(f"Build failed: {exe_path} not found.")

    print(f"[OK] Executable generated successfully: {exe_path}")

    # Ensure config and data folders are present and writable beside the executable
    rel_config = app_dist / "config"
    rel_data = app_dist / "data"
    rel_backups = rel_data / "backups"
    rel_backups.mkdir(parents=True, exist_ok=True)

    if (ROOT / "config" / "companies.json").exists() and not (rel_config / "companies.json").exists():
        rel_config.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "config" / "companies.json", rel_config / "companies.json")

    if (ROOT / "data" / "jobs.sqlite3").exists() and not (rel_data / "jobs.sqlite3").exists():
        rel_data.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "data" / "jobs.sqlite3", rel_data / "jobs.sqlite3")

    # Add quick launcher script inside release folder
    launcher_bat = app_dist / "Launch-LocalJobFinder.bat"
    launcher_bat.write_text("@echo off\r\nstart \"\" \"%~dp0LocalJobFinder.exe\"\r\n", encoding="utf-8")

    # Create portable release ZIP archive
    zip_path = dist_dir / "LocalJobFinder-Windows-Portable.zip"
    print(f"Creating portable zip release archive at: {zip_path}...")
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in app_dist.rglob("*"):
            if file.is_file():
                arcname = file.relative_to(dist_dir)
                zf.write(file, arcname)

    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
    print("=" * 60)
    print(f"[SUCCESS] Standalone Windows Portable Release Ready!")
    print(f" Folder: {app_dist}")
    print(f" Executable: {exe_path}")
    print(f" Portable ZIP: {zip_path} ({zip_size_mb:.1f} MB)")
    print("=" * 60)


if __name__ == "__main__":
    build()
