import os
import sys
import json
import threading
import webbrowser
from pathlib import Path
from datetime import datetime, date

# Ensure root directory is in sys.path
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Auto-detect if current Python is missing required packages, and seamlessly redirect to the verified Python 3.14 installation
if not getattr(sys, "frozen", False):
    PYTHON314 = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python314" / "python.exe"
    if PYTHON314.exists() and Path(sys.executable).resolve() != PYTHON314.resolve():
        try:
            import pandas
            import requests
        except ImportError:
            import subprocess
            sys.exit(subprocess.call([str(PYTHON314)] + sys.argv))

# Set Matplotlib cache directory locally to avoid permission warnings
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "data" / ".mplcache"))

import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from src.database import (
    init_db, list_jobs, upsert_jobs, update_status, update_job_metadata,
    add_watchlist, remove_watchlist, get_watchlist, get_sync_runs,
    get_status_history, save_search, get_saved_searches, delete_saved_search,
    backup_db, restore_db_from_bytes, export_db_bytes, create_sync_run,
    finish_sync_run, purge_expired_jobs
)
from src.job_sources import fetch_all_jobs
from src.resume_parser import extract_resume_text
from src.matcher import rank_jobs, extract_skills
from src.llm import (
    chat, set_config as set_llm_config, get_config as get_llm_config,
    test_connection as test_llm_connection, fetch_available_models,
    POPULAR_MODELS, BASE_URL, MODEL, API_KEY, TIMEOUT
)
from src.helpers import (
    parse_date, relative_date, india_job, remote_job, city_of,
    inferred_exp, inferred_type, inferred_mode, inferred_role, safe_salary,
    is_outdated_job, is_missed_job, opportunity_status, ROLE_CATEGORIES,
    inferred_platform, platform_badge_info, PLATFORM_CATEGORIES
)
from src.ui_theme import COLORS, setup_styles
from src.dialogs import CompanyFilterDialog, ResumeEditDialog, SavePresetDialog, PresetsDialog, JobDetailDialog, SourceHealthDialog


class LocalJobFinderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🧭 Local AI Job Finder — Desktop Edition")
        self.root.geometry("1300x840")
        self.root.minsize(1050, 700)

        # State
        self.resume_text = ""
        self.resume_name = ""
        self.selected_companies = set()
        self.all_jobs = []
        self.filtered_jobs = []
        self.current_job = None
        self.is_fetching = False
        self.llm_connected = False
        self.available_models = list(POPULAR_MODELS)
        self._search_timer = None
        self.tree_sort_col = "match"
        self.tree_sort_desc = True
        self._insights_rendered = False
        self._insights_computing = False
        self.retention_var = tk.StringVar(value="10 days (Default - Recommended)")

        # Initialize DB
        init_db()

        # Styles
        self.style = setup_styles(self.root)

        # Build Main UI
        self._build_header()
        self._build_notebook()

        # Load initial data
        self.refresh_jobs_data()

        # Check LLM connection asynchronously at startup
        self.root.after(300, self.check_llm_status)

    # =========================================================================
    # HEADER BAR: Title + LLM Status & Model Switcher + Sync Action
    # =========================================================================
    def _build_header(self):
        header_frame = ttk.Frame(self.root, padding=(14, 8, 14, 6))
        header_frame.pack(fill="x")

        # 1. Left: Title and Subtitle
        title_box = ttk.Frame(header_frame)
        title_box.pack(side="left", padx=(0, 16))

        title_lbl = ttk.Label(title_box, text="🧭 Local AI Job Finder", style="Header.TLabel")
        title_lbl.pack(anchor="w")

        subtitle_lbl = ttk.Label(
            title_box,
            text="India-first discovery · Resume matcher · Role filters · LM Studio AI · Tracker",
            style="Muted.TLabel"
        )
        subtitle_lbl.pack(anchor="w", pady=(1, 0))

        # 2. Center: LLM Connection Status & Quick Model Switcher (Eliminates empty space)
        llm_bar = ttk.Frame(header_frame, style="Card.TFrame", padding=(10, 4))
        llm_bar.pack(side="left", fill="y", padx=10, expand=True)

        llm_left = ttk.Frame(llm_bar, style="Card.TFrame")
        llm_left.pack(side="left", padx=(0, 8))

        # Status Pill Indicator
        self.header_llm_pill = ttk.Label(
            llm_left,
            text="● Checking LLM…",
            style="StatusPillChecking.TLabel"
        )
        self.header_llm_pill.pack(side="left", padx=(0, 8))

        # Model Label & Combobox
        ttk.Label(llm_left, text="Model:", style="CardBold.TLabel").pack(side="left", padx=(0, 4))
        self.header_model_var = tk.StringVar(value=MODEL)
        self.header_model_cb = ttk.Combobox(
            llm_left,
            textvariable=self.header_model_var,
            values=self.available_models,
            width=26
        )
        self.header_model_cb.pack(side="left", padx=(0, 6))
        self.header_model_cb.bind("<<ComboboxSelected>>", self.on_header_model_selected)
        self.header_model_cb.bind("<Return>", self.on_header_model_selected)

        # Check / Reconnect Button
        self.header_check_llm_btn = ttk.Button(
            llm_bar,
            text="⚡ Check / Refresh",
            style="Outline.TButton",
            command=self.check_llm_status
        )
        self.header_check_llm_btn.pack(side="right")

        # 3. Right: Live Sync Button & Status
        sync_box = ttk.Frame(header_frame)
        sync_box.pack(side="right")

        self.fetch_btn = ttk.Button(
            sync_box,
            text="🌐 Fetch Live Jobs",
            style="Primary.TButton",
            command=self.on_fetch_live_jobs
        )
        self.fetch_btn.pack(side="right", padx=(8, 0))

        status_col = ttk.Frame(sync_box)
        status_col.pack(side="right", padx=6)
        self.status_label = ttk.Label(status_col, text="Ready", style="Muted.TLabel")
        self.status_label.pack(anchor="e")
        self.status_progress = ttk.Progressbar(status_col, mode="determinate", length=110)
        self.status_progress.pack(anchor="e", pady=(2, 0))

    # =========================================================================
    # LLM CONNECTION & MODEL SWITCHING
    # =========================================================================
    def check_llm_status(self):
        """Asynchronously test LLM server connection and update UI indicators & model lists."""
        self.header_llm_pill.configure(text="● Testing...", style="StatusPillChecking.TLabel")
        if hasattr(self, "asst_status_pill"):
            self.asst_status_pill.configure(text="● Testing connection to LM Studio...", style="StatusPillChecking.TLabel")

        def worker():
            cfg = get_llm_config()
            ok, models, msg = test_llm_connection(cfg["base_url"], cfg["api_key"])
            self.root.after(0, lambda: self._on_llm_status_result(ok, models, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_llm_status_result(self, ok, models, msg):
        self.llm_connected = ok
        cfg = get_llm_config()

        if ok:
            self.header_llm_pill.configure(text="● LLM Connected", style="StatusPillOnline.TLabel")
            if models:
                combined = []
                for m in models:
                    if m not in combined:
                        combined.append(m)
                for m in POPULAR_MODELS:
                    if m not in combined:
                        combined.append(m)
                self.available_models = combined
                self.header_model_cb.configure(values=self.available_models)
                if hasattr(self, "asst_model_cb"):
                    self.asst_model_cb.configure(values=self.available_models)

                if cfg["model"] not in models and models:
                    set_llm_config(model=models[0])
                    self.header_model_var.set(models[0])
                    if hasattr(self, "asst_model_var"):
                        self.asst_model_var.set(models[0])

            if hasattr(self, "asst_status_pill"):
                self.asst_status_pill.configure(
                    text=f"● Connected to {cfg['base_url']} · Active Model: {cfg['model']}",
                    style="StatusPillOnline.TLabel"
                )
        else:
            self.header_llm_pill.configure(text="● LLM Disconnected", style="StatusPillOffline.TLabel")
            if hasattr(self, "asst_status_pill"):
                self.asst_status_pill.configure(
                    text=f"● Disconnected from {cfg['base_url']} (Start LM Studio Local Server on port 1234)",
                    style="StatusPillOffline.TLabel"
                )

    def on_header_model_selected(self, event=None):
        new_model = self.header_model_var.get().strip()
        if new_model:
            set_llm_config(model=new_model)
            if hasattr(self, "asst_model_var"):
                self.asst_model_var.set(new_model)
            if hasattr(self, "llm_model_var"):
                self.llm_model_var.set(new_model)
            self._update_assistant_meta()

    # =========================================================================
    # TABS NOTEBOOK
    # =========================================================================
    def _build_notebook(self):
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(4, 10))

        # 6 Main Tabs
        self.tab_find = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_watchlist = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_tracker = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_insights = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_assistant = ttk.Frame(self.notebook, padding=(6, 6))
        self.tab_sources = ttk.Frame(self.notebook, padding=(6, 6))

        self.notebook.add(self.tab_find, text="  🔎 Find Jobs  ")
        self.notebook.add(self.tab_watchlist, text="  🏢 Company Watchlist  ")
        self.notebook.add(self.tab_tracker, text="  📌 Application Tracker  ")
        self.notebook.add(self.tab_insights, text="  📊 Market Insights  ")
        self.notebook.add(self.tab_assistant, text="  🤖 AI Career Assistant  ")
        self.notebook.add(self.tab_sources, text="  ⚙️ Sources & Backups  ")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Build each tab
        self._build_tab_find()
        self._build_tab_watchlist()
        self._build_tab_tracker()
        self._build_tab_insights()
        self._build_tab_assistant()
        self._build_tab_sources()

    def _on_tab_changed(self, event):
        tab_idx = self.notebook.index("current")
        if tab_idx == 1:
            self._refresh_watchlist_tab()
        elif tab_idx == 2:
            self._refresh_tracker_tab()
        elif tab_idx == 3:
            if not self._insights_rendered:
                self._refresh_insights_tab()
        elif tab_idx == 4:
            self._refresh_assistant_tab()
        elif tab_idx == 5:
            self._refresh_sources_tab()

    # =========================================================================
    # TAB 1: FIND JOBS (With Missed & Outdated Jobs Tracking)
    # =========================================================================
    def _build_tab_find(self):
        # 1. Top Section: Resume Card on Left + 5 Evenly Balanced Metric Cards on Right
        top_bar = ttk.Frame(self.tab_find)
        top_bar.pack(fill="x", pady=(0, 6))

        # Resume Box
        resume_card = ttk.Frame(top_bar, style="Card.TFrame", padding=(10, 8))
        resume_card.pack(side="left", padx=(0, 8))

        r_head = ttk.Frame(resume_card, style="Card.TFrame")
        r_head.pack(fill="x")
        ttk.Label(r_head, text="📄 Resume & Matching", font=("Segoe UI", 9, "bold"), style="Card.TLabel").pack(side="left")
        self.resume_info_lbl = ttk.Label(r_head, text="No resume loaded", style="CardMuted.TLabel")
        self.resume_info_lbl.pack(side="right", padx=(10, 0))

        r_btns = ttk.Frame(resume_card, style="Card.TFrame")
        r_btns.pack(fill="x", pady=(6, 0))
        ttk.Button(r_btns, text="Upload Resume", command=self.on_upload_resume).pack(side="left", padx=(0, 4))
        ttk.Button(r_btns, text="Paste / Edit", command=self.on_edit_resume).pack(side="left", padx=(0, 4))
        ttk.Button(r_btns, text="Clear", command=self.on_clear_resume).pack(side="left")

        # 5 Key Metric Cards (Including Missed & Outdated Jobs!)
        metrics_frame = ttk.Frame(top_bar)
        metrics_frame.pack(side="left", fill="both", expand=True)

        self.metric_saved = self._create_metric_card(metrics_frame, "0", "Saved Listings")
        self.metric_india = self._create_metric_card(metrics_frame, "0", "India-Based")
        self.metric_intern = self._create_metric_card(metrics_frame, "0", "Internships")
        self.metric_watch = self._create_metric_card(metrics_frame, "0", "Watchlisted")
        self.metric_missed = self._create_metric_card(
            metrics_frame, "0", "⚠️ Missed Jobs",
            num_style="MetricWarnNum.TLabel",
            on_click=self.filter_to_missed_jobs
        )

        # 2. Filter Bar: Clean 4-Column Grid with Opportunity & Role Filters
        filter_card = ttk.LabelFrame(self.tab_find, text="Search & Filters", padding=(10, 6))
        filter_card.pack(fill="x", pady=(0, 6))

        for col_i in range(4):
            filter_card.columnconfigure(col_i, weight=1, uniform="filter_cols")

        # Row 0: Search, Company, Opportunity Filter (New!), Location Mode
        f0 = ttk.Frame(filter_card)
        f0.grid(row=0, column=0, sticky="ew", padx=4, pady=3)
        ttk.Label(f0, text="Search:").pack(side="left", padx=(0, 4))
        self.query_var = tk.StringVar()
        self.query_var.trace_add("write", self._on_query_input_debounced)
        ttk.Entry(f0, textvariable=self.query_var).pack(side="left", fill="x", expand=True)

        f1 = ttk.Frame(filter_card)
        f1.grid(row=0, column=1, sticky="ew", padx=4, pady=3)
        self.company_btn = ttk.Button(f1, text="🏢 Companies: All", command=self.on_open_company_filter)
        self.company_btn.pack(fill="x", expand=True)

        # Opportunity / Freshness Filter (All, Fresh Only, Missed/Outdated Only)
        f2 = ttk.Frame(filter_card)
        f2.grid(row=0, column=2, sticky="ew", padx=4, pady=3)
        ttk.Label(f2, text="Status:").pack(side="left", padx=(0, 4))
        self.opp_var = tk.StringVar(value="All Listings")
        opp_cb = ttk.Combobox(
            f2,
            textvariable=self.opp_var,
            values=["All Listings", "Active & Fresh (<30d)", "⚠️ Missed / Outdated (>30d)", "In Progress (Applied)"],
            state="readonly"
        )
        opp_cb.pack(side="left", fill="x", expand=True)
        opp_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        f3 = ttk.Frame(filter_card)
        f3.grid(row=0, column=3, sticky="ew", padx=4, pady=3)
        ttk.Label(f3, text="Location:").pack(side="left", padx=(0, 4))
        self.loc_var = tk.StringVar(value="India first")
        loc_cb = ttk.Combobox(f3, textvariable=self.loc_var, values=["India first", "India only", "Remote worldwide", "Worldwide"], state="readonly")
        loc_cb.pack(side="left", fill="x", expand=True)
        loc_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        # Row 1: Role Specialization, Experience, Source, Work Mode
        f4 = ttk.Frame(filter_card)
        f4.grid(row=1, column=0, sticky="ew", padx=4, pady=3)
        ttk.Label(f4, text="Role:").pack(side="left", padx=(0, 4))
        self.role_var = tk.StringVar(value="All Roles")
        role_cb = ttk.Combobox(f4, textvariable=self.role_var, values=ROLE_CATEGORIES, state="readonly")
        role_cb.pack(side="left", fill="x", expand=True)
        role_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        f5 = ttk.Frame(filter_card)
        f5.grid(row=1, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(f5, text="Exp:").pack(side="left", padx=(0, 4))
        self.exp_var = tk.StringVar(value="Any experience")
        exps = ["Any experience", "Fresher / 0–1 year", "Internship", "1–3 years", "3–5 years", "5+ years", "Unknown"]
        exp_cb = ttk.Combobox(f5, textvariable=self.exp_var, values=exps, state="readonly")
        exp_cb.pack(side="left", fill="x", expand=True)
        exp_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        f6 = ttk.Frame(filter_card)
        f6.grid(row=1, column=2, sticky="ew", padx=4, pady=3)
        ttk.Label(f6, text="Platform:").pack(side="left", padx=(0, 4))
        self.source_var = tk.StringVar(value="All platforms")
        self.source_cb = ttk.Combobox(f6, textvariable=self.source_var, values=PLATFORM_CATEGORIES, state="readonly")
        self.source_cb.pack(side="left", fill="x", expand=True)
        self.source_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        f7 = ttk.Frame(filter_card)
        f7.grid(row=1, column=3, sticky="ew", padx=4, pady=3)
        ttk.Label(f7, text="Mode:").pack(side="left", padx=(0, 4))
        self.mode_var = tk.StringVar(value="All modes")
        modes = ["All modes", "Remote", "Hybrid", "On-site", "Unknown"]
        mode_cb = ttk.Combobox(f7, textvariable=self.mode_var, values=modes, state="readonly")
        mode_cb.pack(side="left", fill="x", expand=True)
        mode_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        # Row 2: City, Age, App Status, Salary
        f8 = ttk.Frame(filter_card)
        f8.grid(row=2, column=0, sticky="ew", padx=4, pady=3)
        ttk.Label(f8, text="City:").pack(side="left", padx=(0, 4))
        self.city_var = tk.StringVar(value="Any city")
        cities = ["Any city", "Chennai", "Bengaluru", "Hyderabad", "Pune", "Mumbai", "Delhi NCR", "Kolkata", "Kochi", "Ahmedabad", "Jaipur", "Remote"]
        city_cb = ttk.Combobox(f8, textvariable=self.city_var, values=cities, state="readonly")
        city_cb.pack(side="left", fill="x", expand=True)
        city_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        f9 = ttk.Frame(filter_card)
        f9.grid(row=2, column=1, sticky="ew", padx=4, pady=3)
        ttk.Label(f9, text="Age:").pack(side="left", padx=(0, 4))
        self.age_var = tk.StringVar(value="Any date")
        ages = ["Any date", "Today", "Yesterday", "Last 7 days", "Last 30 days", "Older than 30 days", "Date unknown"]
        age_cb = ttk.Combobox(f9, textvariable=self.age_var, values=ages, state="readonly")
        age_cb.pack(side="left", fill="x", expand=True)
        age_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        f10 = ttk.Frame(filter_card)
        f10.grid(row=2, column=2, sticky="ew", padx=4, pady=3)
        ttk.Label(f10, text="App:").pack(side="left", padx=(0, 4))
        self.status_var = tk.StringVar(value="All statuses")
        statuses = ["All statuses", "New", "Interested", "Saved", "Applied", "Interview", "Offer", "Rejected"]
        status_cb = ttk.Combobox(f10, textvariable=self.status_var, values=statuses, state="readonly")
        status_cb.pack(side="left", fill="x", expand=True)
        status_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        f11 = ttk.Frame(filter_card)
        f11.grid(row=2, column=3, sticky="ew", padx=4, pady=3)
        ttk.Label(f11, text="Salary:").pack(side="left", padx=(0, 4))
        self.sal_var = tk.StringVar(value="Any")
        sal_cb = ttk.Combobox(f11, textvariable=self.sal_var, values=["Any", "Salary disclosed", "Salary not disclosed"], state="readonly")
        sal_cb.pack(side="left", fill="x", expand=True)
        sal_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        # Row 3: Sort by, Favorites checkbox, Count badge, and Action buttons
        action_row = ttk.Frame(filter_card)
        action_row.grid(row=3, column=0, columnspan=4, sticky="ew", padx=4, pady=(5, 1))

        left_acts = ttk.Frame(action_row)
        left_acts.pack(side="left")

        ttk.Label(left_acts, text="Sort:").pack(side="left", padx=(0, 4))
        self.sort_var = tk.StringVar(value="Best match")
        sort_opts = ["Best match", "Newest first", "Oldest first", "Company A–Z", "Salary highest first", "Recently discovered"]
        sort_cb = ttk.Combobox(left_acts, textvariable=self.sort_var, values=sort_opts, state="readonly", width=14)
        sort_cb.pack(side="left", padx=(0, 10))
        sort_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        ttk.Label(left_acts, text="Type:").pack(side="left", padx=(0, 4))
        self.type_var = tk.StringVar(value="All types")
        types_cb = ttk.Combobox(left_acts, textvariable=self.type_var, values=["All types", "Full-time", "Internship", "Contract"], state="readonly", width=11)
        types_cb.pack(side="left", padx=(0, 10))
        types_cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filters())

        self.fav_only_var = tk.BooleanVar(value=False)
        fav_cb = ttk.Checkbutton(left_acts, text="★ Favorites Only", variable=self.fav_only_var, command=self.apply_filters)
        fav_cb.pack(side="left", padx=(0, 14))

        self.count_label = ttk.Label(left_acts, text="Showing 0 of 0 jobs", font=("Segoe UI", 9, "bold"))
        self.count_label.pack(side="left")

        right_acts = ttk.Frame(action_row)
        right_acts.pack(side="right")
        ttk.Button(right_acts, text="Reset Filters", command=self.reset_filters).pack(side="right", padx=(4, 0))
        ttk.Button(right_acts, text="🧹 Clean Expired (>10d)", command=self.on_clean_expired_jobs_click).pack(side="right", padx=(4, 0))
        ttk.Button(right_acts, text="📂 Manage Presets", command=self.on_manage_presets).pack(side="right", padx=(4, 0))
        ttk.Button(right_acts, text="💾 Save Preset", command=self.on_save_preset).pack(side="right")

        # 3. Main Split View: Job List on Left (Treeview), Rich Job Card on Right
        self.paned = ttk.PanedWindow(self.tab_find, orient="horizontal")
        self.paned.pack(fill="both", expand=True, pady=(4, 0))

        # Left Pane: Treeview with Zebra Striping, Missed Row Coloring & Click-to-Sort
        tree_frame = ttk.Frame(self.paned)
        self.paned.add(tree_frame, weight=6)

        cols = ("fav", "title", "company", "platform", "location", "match", "status", "opp", "role", "posted")
        self.job_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")

        self.job_tree.heading("fav", text="★", command=lambda: self._sort_treeview_by("fav"))
        self.job_tree.heading("title", text="Job Title", command=lambda: self._sort_treeview_by("title"))
        self.job_tree.heading("company", text="Company", command=lambda: self._sort_treeview_by("company"))
        self.job_tree.heading("platform", text="Platform", command=lambda: self._sort_treeview_by("platform"))
        self.job_tree.heading("location", text="Location", command=lambda: self._sort_treeview_by("location"))
        self.job_tree.heading("match", text="Match", command=lambda: self._sort_treeview_by("match"))
        self.job_tree.heading("status", text="App Status", command=lambda: self._sort_treeview_by("status"))
        self.job_tree.heading("opp", text="Opportunity", command=lambda: self._sort_treeview_by("opp"))
        self.job_tree.heading("role", text="Role", command=lambda: self._sort_treeview_by("role"))
        self.job_tree.heading("posted", text="Posted", command=lambda: self._sort_treeview_by("posted"))

        self.job_tree.column("fav", width=28, anchor="center")
        self.job_tree.column("title", width=180)
        self.job_tree.column("company", width=110)
        self.job_tree.column("platform", width=95, anchor="center")
        self.job_tree.column("location", width=95)
        self.job_tree.column("match", width=48, anchor="center")
        self.job_tree.column("status", width=70, anchor="center")
        self.job_tree.column("opp", width=105, anchor="center")
        self.job_tree.column("role", width=100)
        self.job_tree.column("posted", width=95)

        # Smooth Tags: Even, Odd, Missed, Favorited
        self.job_tree.tag_configure("evenrow", background="#ffffff")
        self.job_tree.tag_configure("oddrow", background="#f8fafc")
        self.job_tree.tag_configure("missed", background="#fff7ed")
        self.job_tree.tag_configure("favorited", background="#fefce8")

        tree_sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.job_tree.yview)
        tree_x_sb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.job_tree.xview)
        self.job_tree.configure(yscrollcommand=tree_sb.set, xscrollcommand=tree_x_sb.set)

        self.job_tree.pack(side="left", fill="both", expand=True)
        tree_sb.pack(side="right", fill="y")
        tree_x_sb.pack(side="bottom", fill="x")

        # Smooth selection & keyboard navigation
        self.job_tree.bind("<<TreeviewSelect>>", self._on_job_selected)
        self.job_tree.bind("<KeyRelease-Up>", self._on_job_selected)
        self.job_tree.bind("<KeyRelease-Down>", self._on_job_selected)
        self.job_tree.bind("<Double-1>", self._on_job_double_click)

        # Right Pane: Rich Detail Card
        detail_frame = ttk.Frame(self.paned, style="Card.TFrame", padding=10)
        self.paned.add(detail_frame, weight=5)
        self._build_detail_card(detail_frame)

    def _create_metric_card(self, parent, val, label, num_style="MetricNum.TLabel", on_click=None):
        card = ttk.Frame(parent, style="Card.TFrame", padding=(10, 6))
        card.pack(side="left", fill="both", expand=True, padx=4)
        num_lbl = ttk.Label(card, text=val, style=num_style)
        num_lbl.pack(anchor="center")
        title_lbl = ttk.Label(card, text=label, style="MetricTitle.TLabel")
        title_lbl.pack(anchor="center")

        if on_click:
            card.configure(cursor="hand2")
            card.bind("<Button-1>", lambda e: on_click())
            num_lbl.bind("<Button-1>", lambda e: on_click())
            title_lbl.bind("<Button-1>", lambda e: on_click())

        return num_lbl

    def filter_to_missed_jobs(self):
        """One-click filter to display all missed / outdated jobs."""
        self.opp_var.set("⚠️ Missed / Outdated (>30d)")
        self.apply_filters()

    def _on_query_input_debounced(self, *args):
        """Debounce keystroke filtering by 180ms to keep UI silky smooth while typing."""
        if self._search_timer is not None:
            self.root.after_cancel(self._search_timer)
        self._search_timer = self.root.after(180, self.apply_filters)

    def _sort_treeview_by(self, col):
        """Click header to toggle ascending/descending sort smoothly."""
        if self.tree_sort_col == col:
            self.tree_sort_desc = not self.tree_sort_desc
        else:
            self.tree_sort_col = col
            self.tree_sort_desc = False

        if col == "match":
            self.filtered_jobs.sort(key=lambda j: j.get("match_score") or -1, reverse=self.tree_sort_desc)
        elif col == "title":
            self.filtered_jobs.sort(key=lambda j: str(j.get("title") or "").casefold(), reverse=self.tree_sort_desc)
        elif col == "company":
            self.filtered_jobs.sort(key=lambda j: str(j.get("company") or "").casefold(), reverse=self.tree_sort_desc)
        elif col == "platform":
            self.filtered_jobs.sort(key=lambda j: inferred_platform(j).casefold(), reverse=self.tree_sort_desc)
        elif col == "location":
            self.filtered_jobs.sort(key=lambda j: str(j.get("location") or "").casefold(), reverse=self.tree_sort_desc)
        elif col == "status":
            self.filtered_jobs.sort(key=lambda j: str(j.get("status") or "").casefold(), reverse=self.tree_sort_desc)
        elif col == "opp":
            self.filtered_jobs.sort(key=lambda j: is_missed_job(j), reverse=self.tree_sort_desc)
        elif col == "role":
            self.filtered_jobs.sort(key=lambda j: inferred_role(j).casefold(), reverse=self.tree_sort_desc)
        elif col == "posted":
            self.filtered_jobs.sort(key=lambda j: parse_date(j.get("posted_at")) or date.min, reverse=self.tree_sort_desc)
        elif col == "fav":
            self.filtered_jobs.sort(key=lambda j: int(j.get("is_favorite") or 0), reverse=self.tree_sort_desc)

        self._populate_job_tree()

    def _build_detail_card(self, parent):
        # Header of card
        self.card_title = ttk.Label(parent, text="Select a job to view details", font=("Segoe UI", 12, "bold"),
                                    style="Card.TLabel", wraplength=400)
        self.card_title.pack(anchor="w")

        self.card_sub = ttk.Label(parent, text="", font=("Segoe UI", 10, "bold"), foreground=COLORS["primary"],
                                  style="Card.TLabel", wraplength=400)
        self.card_sub.pack(anchor="w", pady=(2, 0))

        # Platform Pill (Greenhouse, Lever.co, Career Page, Remote OK, etc.)
        self.card_platform_pill = ttk.Label(parent, text="", style="PlatformPill.TLabel")
        self.card_platform_pill.pack(anchor="w", pady=(2, 3))

        self.card_meta = ttk.Label(parent, text="", style="CardMuted.TLabel", wraplength=400)
        self.card_meta.pack(anchor="w", pady=(1, 4))

        # Opportunity Alert Pill (Highlights missed vs fresh)
        self.card_opp_alert = ttk.Label(parent, text="", font=("Segoe UI", 8, "bold"))
        self.card_opp_alert.pack(anchor="w", pady=(0, 4))

        self.card_badge = ttk.Label(parent, text="", font=("Segoe UI", 9, "bold"), style="Card.TLabel", wraplength=400)
        self.card_badge.pack(anchor="w", pady=(0, 6))

        # Match Score & Skills
        self.card_match_frame = ttk.Frame(parent, style="Card.TFrame")
        self.card_match_frame.pack(fill="x", pady=(0, 6))

        self.card_match_lbl = ttk.Label(self.card_match_frame, text="", font=("Segoe UI", 11, "bold"), style="Card.TLabel")
        self.card_match_lbl.pack(anchor="w")
        self.card_skills_lbl = ttk.Label(self.card_match_frame, text="", style="Card.TLabel", wraplength=400)
        self.card_skills_lbl.pack(anchor="w", pady=(2, 0))

        # Action Buttons Row
        self.card_actions = ttk.Frame(parent, style="Card.TFrame")
        self.card_actions.pack(fill="x", pady=4)

        self.card_fav_btn = ttk.Button(self.card_actions, text="☆ Favorite", command=self.on_toggle_current_favorite)
        self.card_fav_btn.pack(side="left", padx=(0, 6))

        self.card_status_var = tk.StringVar(value="New")
        self.card_status_cb = ttk.Combobox(
            self.card_actions, textvariable=self.card_status_var,
            values=["New", "Interested", "Saved", "Applied", "Interview", "Offer", "Rejected"],
            state="readonly", width=12
        )
        self.card_status_cb.pack(side="left", padx=(0, 6))
        self.card_status_cb.bind("<<ComboboxSelected>>", self.on_change_current_status)

        self.card_url_btn = ttk.Button(self.card_actions, text="Open URL ↗", style="Primary.TButton", command=self.on_open_current_url)
        self.card_url_btn.pack(side="left", padx=(0, 6))

        ttk.Button(self.card_actions, text="📋 Copy Text", command=self.on_copy_job_description).pack(side="left")

        # Notes Row
        note_box = ttk.Frame(parent, style="Card.TFrame")
        note_box.pack(fill="x", pady=(4, 6))
        ttk.Label(note_box, text="Note:", style="CardBold.TLabel").pack(side="left", padx=(0, 4))
        self.card_note_var = tk.StringVar()
        self.card_note_entry = ttk.Entry(note_box, textvariable=self.card_note_var)
        self.card_note_entry.pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(note_box, text="Save", command=self.on_save_current_note).pack(side="left")

        # Local AI Button
        ai_box = ttk.Frame(parent, style="Card.TFrame")
        ai_box.pack(fill="x", pady=(0, 6))
        self.card_ai_btn = ttk.Button(ai_box, text="🤖 Explain Match with Local AI", command=self.on_explain_current_job)
        self.card_ai_btn.pack(anchor="w")

        # Description text
        ttk.Label(parent, text="Job Description:", style="CardBold.TLabel").pack(anchor="w", pady=(4, 2))
        desc_box = ttk.Frame(parent, style="Card.TFrame")
        desc_box.pack(fill="both", expand=True)

        self.card_desc = tk.Text(desc_box, wrap="word", font=("Segoe UI", 9), relief="solid", borderwidth=1,
                                 bg="#ffffff", padx=8, pady=8)
        desc_sb = ttk.Scrollbar(desc_box, orient="vertical", command=self.card_desc.yview)
        self.card_desc.configure(yscrollcommand=desc_sb.set)

        self.card_desc.pack(side="left", fill="both", expand=True)
        desc_sb.pack(side="right", fill="y")
        self.card_desc.configure(state="disabled")

        # Auto-adjust wraplength when parent resizes
        parent.bind("<Configure>", self._adjust_detail_wraplength)

    def _adjust_detail_wraplength(self, event):
        w = max(260, event.width - 30)
        self.card_title.configure(wraplength=w)
        self.card_sub.configure(wraplength=w)
        self.card_meta.configure(wraplength=w)
        self.card_badge.configure(wraplength=w)
        self.card_skills_lbl.configure(wraplength=w)

    def on_copy_job_description(self):
        if self.current_job:
            desc = self.current_job.get("description") or ""
            if desc:
                self.root.clipboard_clear()
                self.root.clipboard_append(desc)
                messagebox.showinfo("Copied", "Job description copied to clipboard.", parent=self.root)

    # =========================================================================
    # TAB 2: COMPANY WATCHLIST & DIRECTORY
    # =========================================================================
    def _build_tab_watchlist(self):
        paned = ttk.PanedWindow(self.tab_watchlist, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # Left: Discovered Company Directory
        left = ttk.LabelFrame(paned, text="Discovered Company Directory", padding=8)
        paned.add(left, weight=5)

        d_top = ttk.Frame(left)
        d_top.pack(fill="x", pady=(0, 4))
        ttk.Label(d_top, text="Search Directory:").pack(side="left", padx=(0, 6))
        self.dir_search_var = tk.StringVar()
        self.dir_search_var.trace_add("write", lambda *args: self._populate_directory_table())
        ttk.Entry(d_top, textvariable=self.dir_search_var).pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.dir_count_lbl = ttk.Label(left, text="", style="Muted.TLabel")
        self.dir_count_lbl.pack(anchor="w", pady=(0, 4))

        d_cols = ("company", "jobs", "sources")
        self.dir_tree = ttk.Treeview(left, columns=d_cols, show="headings", selectmode="browse")
        self.dir_tree.heading("company", text="Company")
        self.dir_tree.heading("jobs", text="Saved Jobs")
        self.dir_tree.heading("sources", text="Sources")
        self.dir_tree.column("company", width=180)
        self.dir_tree.column("jobs", width=75, anchor="center")
        self.dir_tree.column("sources", width=220)

        self.dir_tree.tag_configure("evenrow", background="#ffffff")
        self.dir_tree.tag_configure("oddrow", background="#f8fafc")

        dir_sb = ttk.Scrollbar(left, orient="vertical", command=self.dir_tree.yview)
        self.dir_tree.configure(yscrollcommand=dir_sb.set)
        self.dir_tree.pack(side="left", fill="both", expand=True)
        dir_sb.pack(side="right", fill="y")

        self.dir_tree.bind("<<TreeviewSelect>>", self._on_directory_selected)

        # Right: Watchlist Management
        right = ttk.LabelFrame(paned, text="Company Watchlist", padding=8)
        paned.add(right, weight=5)

        add_box = ttk.Frame(right)
        add_box.pack(fill="x", pady=(0, 8))

        ttk.Label(add_box, text="Track employers you want to follow.", style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        r_entry1 = ttk.Frame(add_box)
        r_entry1.pack(fill="x", pady=2)
        ttk.Label(r_entry1, text="Company:").pack(side="left", padx=(0, 4))
        self.watch_comp_var = tk.StringVar()
        ttk.Entry(r_entry1, textvariable=self.watch_comp_var, width=18).pack(side="left", padx=(0, 8))

        ttk.Label(r_entry1, text="Notes:").pack(side="left", padx=(0, 4))
        self.watch_notes_var = tk.StringVar()
        ttk.Entry(r_entry1, textvariable=self.watch_notes_var).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ttk.Button(r_entry1, text="Add", style="Primary.TButton", command=self.on_add_watchlist).pack(side="right")

        # Watchlist table
        w_cols = ("company", "jobs", "notes")
        self.watch_tree = ttk.Treeview(right, columns=w_cols, show="headings", selectmode="browse")
        self.watch_tree.heading("company", text="Watchlisted Employer")
        self.watch_tree.heading("jobs", text="Matching Listings")
        self.watch_tree.heading("notes", text="Your Notes")
        self.watch_tree.column("company", width=160)
        self.watch_tree.column("jobs", width=110, anchor="center")
        self.watch_tree.column("notes", width=200)

        self.watch_tree.tag_configure("evenrow", background="#ffffff")
        self.watch_tree.tag_configure("oddrow", background="#f8fafc")

        w_sb = ttk.Scrollbar(right, orient="vertical", command=self.watch_tree.yview)
        self.watch_tree.configure(yscrollcommand=w_sb.set)
        self.watch_tree.pack(fill="both", expand=True)
        w_sb.pack(side="right", fill="y")

        w_btn_box = ttk.Frame(right)
        w_btn_box.pack(fill="x", pady=(6, 0))
        ttk.Button(w_btn_box, text="Remove Selected", command=self.on_remove_watchlist).pack(side="left")
        ttk.Button(w_btn_box, text="Filter Jobs by Selected", command=self.on_filter_by_watchlist).pack(side="right")

    def _refresh_watchlist_tab(self):
        self._populate_directory_table()
        self._populate_watchlist_table()

    def _populate_directory_table(self):
        for item in self.dir_tree.get_children():
            self.dir_tree.delete(item)

        jobs = self.all_jobs or list_jobs()
        counts = {}
        sources = {}
        for j in jobs:
            c = str(j.get("company") or "").strip()
            if c:
                counts[c] = counts.get(c, 0) + 1
                sources.setdefault(c, set()).add(str(j.get("source") or "Unknown"))

        q = self.dir_search_var.get().strip().casefold()
        sorted_comps = sorted(counts.keys(), key=str.casefold)

        idx = 0
        for comp in sorted_comps:
            if q and q not in comp.casefold():
                continue
            src_str = ", ".join(sorted(sources.get(comp, set())))
            tag = "evenrow" if idx % 2 == 0 else "oddrow"
            self.dir_tree.insert("", "end", values=(comp, counts[comp], src_str), tags=(tag,))
            idx += 1

        self.dir_count_lbl.configure(text=f"{len(counts)} companies discovered in {len(jobs):,} saved listings.")

    def _populate_watchlist_table(self):
        for item in self.watch_tree.get_children():
            self.watch_tree.delete(item)

        watchlist = get_watchlist()
        jobs = self.all_jobs or list_jobs()

        for idx, w in enumerate(watchlist):
            comp_name = w["company"]
            matches = [j for j in jobs if str(j.get("company") or "").casefold() == comp_name.casefold()]
            tag = "evenrow" if idx % 2 == 0 else "oddrow"
            self.watch_tree.insert("", "end", iid=str(w["id"]), values=(comp_name, f"{len(matches)} saved", w.get("notes") or ""), tags=(tag,))

    def _on_directory_selected(self, event):
        sel = self.dir_tree.selection()
        if sel:
            values = self.dir_tree.item(sel[0], "values")
            if values:
                self.watch_comp_var.set(values[0])

    def on_add_watchlist(self):
        comp = self.watch_comp_var.get().strip()
        notes = self.watch_notes_var.get().strip()
        if not comp:
            messagebox.showwarning("Warning", "Please enter a company name.", parent=self.root)
            return
        add_watchlist(comp, notes)
        self.watch_comp_var.set("")
        self.watch_notes_var.set("")
        self._populate_watchlist_table()
        self.metric_watch.configure(text=str(len(get_watchlist())))
        messagebox.showinfo("Success", f"Added '{comp}' to watchlist.", parent=self.root)

    def on_remove_watchlist(self):
        sel = self.watch_tree.selection()
        if not sel:
            messagebox.showinfo("Select Company", "Please select a watchlisted company to remove.", parent=self.root)
            return
        values = self.watch_tree.item(sel[0], "values")
        comp = values[0]
        if messagebox.askyesno("Confirm", f"Remove '{comp}' from watchlist?", parent=self.root):
            remove_watchlist(comp)
            self._populate_watchlist_table()
            self.metric_watch.configure(text=str(len(get_watchlist())))

    def on_filter_by_watchlist(self):
        sel = self.watch_tree.selection()
        if not sel:
            return
        values = self.watch_tree.item(sel[0], "values")
        comp = values[0]
        self.selected_companies = {comp}
        self.company_btn.configure(text=f"🏢 Company: {comp}")
        self.notebook.select(0)
        self.apply_filters()

    # =========================================================================
    # TAB 3: APPLICATION TRACKER (With Missed & Inactive Metrics)
    # =========================================================================
    def _build_tab_tracker(self):
        m_frame = ttk.Frame(self.tab_tracker)
        m_frame.pack(fill="x", pady=(0, 6))

        self.tr_int_lbl = self._create_metric_card(m_frame, "0", "Interested")
        self.tr_app_lbl = self._create_metric_card(m_frame, "0", "Applied")
        self.tr_iv_lbl = self._create_metric_card(m_frame, "0", "Interview")
        self.tr_off_lbl = self._create_metric_card(m_frame, "0", "Offer")
        self.tr_rej_lbl = self._create_metric_card(m_frame, "0", "Rejected")
        self.tr_missed_lbl = self._create_metric_card(
            m_frame, "0", "⚠️ Missed",
            num_style="MetricWarnNum.TLabel",
            on_click=lambda: self._set_tracker_filter("⚠️ Missed / Outdated")
        )

        act_bar = ttk.Frame(self.tab_tracker)
        act_bar.pack(fill="x", pady=(0, 6))

        ttk.Label(act_bar, text="Filter Status:").pack(side="left", padx=(0, 4))
        self.tr_filter_var = tk.StringVar(value="All Statuses")
        tr_cb = ttk.Combobox(
            act_bar,
            textvariable=self.tr_filter_var,
            values=["All Statuses", "Interested", "Applied", "Interview", "Offer", "Rejected", "Saved", "New", "⚠️ Missed / Outdated"],
            state="readonly", width=18
        )
        tr_cb.pack(side="left", padx=(0, 10))
        tr_cb.bind("<<ComboboxSelected>>", lambda e: self._populate_tracker_table())

        ttk.Button(act_bar, text="📥 Export Tracker to CSV", command=self.on_export_tracker_csv).pack(side="right")
        ttk.Button(act_bar, text="Open Selected Posting ↗", command=self.on_tracker_open_url).pack(side="right", padx=(0, 8))

        tr_paned = ttk.PanedWindow(self.tab_tracker, orient="vertical")
        tr_paned.pack(fill="both", expand=True)

        top_table_frame = ttk.LabelFrame(tr_paned, text="Active Applications & Opportunity Pipeline", padding=8)
        tr_paned.add(top_table_frame, weight=6)

        cols = ("id", "title", "company", "location", "status", "opp", "role", "posted", "source", "notes")
        self.tr_tree = ttk.Treeview(top_table_frame, columns=cols, show="headings", selectmode="browse")
        self.tr_tree.heading("id", text="ID")
        self.tr_tree.heading("title", text="Job Title")
        self.tr_tree.heading("company", text="Company")
        self.tr_tree.heading("location", text="Location")
        self.tr_tree.heading("status", text="App Status")
        self.tr_tree.heading("opp", text="Opportunity")
        self.tr_tree.heading("role", text="Role")
        self.tr_tree.heading("posted", text="Posted")
        self.tr_tree.heading("source", text="Platform")
        self.tr_tree.heading("notes", text="Notes")

        self.tr_tree.column("id", width=38, anchor="center")
        self.tr_tree.column("title", width=190)
        self.tr_tree.column("company", width=120)
        self.tr_tree.column("location", width=105)
        self.tr_tree.column("status", width=75, anchor="center")
        self.tr_tree.column("opp", width=110, anchor="center")
        self.tr_tree.column("role", width=105)
        self.tr_tree.column("posted", width=95)
        self.tr_tree.column("source", width=105)
        self.tr_tree.column("notes", width=140)

        self.tr_tree.tag_configure("evenrow", background="#ffffff")
        self.tr_tree.tag_configure("oddrow", background="#f8fafc")
        self.tr_tree.tag_configure("missed", background="#fff7ed")

        tr_sb = ttk.Scrollbar(top_table_frame, orient="vertical", command=self.tr_tree.yview)
        self.tr_tree.configure(yscrollcommand=tr_sb.set)
        self.tr_tree.pack(side="left", fill="both", expand=True)
        tr_sb.pack(side="right", fill="y")

        self.tr_tree.bind("<Double-1>", self._on_tracker_double_click)

        # Bottom Table: Status History
        hist_frame = ttk.LabelFrame(tr_paned, text="Application Status History", padding=8)
        tr_paned.add(hist_frame, weight=4)

        h_cols = ("job", "company", "old_status", "new_status", "changed_at")
        self.hist_tree = ttk.Treeview(hist_frame, columns=h_cols, show="headings", selectmode="browse")
        self.hist_tree.heading("job", text="Job Title")
        self.hist_tree.heading("company", text="Company")
        self.hist_tree.heading("old_status", text="Previous Status")
        self.hist_tree.heading("new_status", text="New Status")
        self.hist_tree.heading("changed_at", text="Changed At (UTC)")

        self.hist_tree.column("job", width=240)
        self.hist_tree.column("company", width=150)
        self.hist_tree.column("old_status", width=110, anchor="center")
        self.hist_tree.column("new_status", width=110, anchor="center")
        self.hist_tree.column("changed_at", width=160)

        self.hist_tree.tag_configure("evenrow", background="#ffffff")
        self.hist_tree.tag_configure("oddrow", background="#f8fafc")

        h_sb = ttk.Scrollbar(hist_frame, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=h_sb.set)
        self.hist_tree.pack(side="left", fill="both", expand=True)
        h_sb.pack(side="right", fill="y")

    def _set_tracker_filter(self, val):
        self.tr_filter_var.set(val)
        self._populate_tracker_table()

    def _refresh_tracker_tab(self):
        self._populate_tracker_table()
        self._populate_history_table()

    def _populate_tracker_table(self):
        for item in self.tr_tree.get_children():
            self.tr_tree.delete(item)

        jobs = self.all_jobs or list_jobs()
        status_counts = {}
        missed_count = 0
        for j in jobs:
            st = j.get("status") or "New"
            status_counts[st] = status_counts.get(st, 0) + 1
            if is_missed_job(j):
                missed_count += 1

        self.tr_int_lbl.configure(text=str(status_counts.get("Interested", 0)))
        self.tr_app_lbl.configure(text=str(status_counts.get("Applied", 0)))
        self.tr_iv_lbl.configure(text=str(status_counts.get("Interview", 0)))
        self.tr_off_lbl.configure(text=str(status_counts.get("Offer", 0)))
        self.tr_rej_lbl.configure(text=str(status_counts.get("Rejected", 0)))
        self.tr_missed_lbl.configure(text=str(missed_count))

        f_status = self.tr_filter_var.get()
        idx = 0
        for j in jobs:
            st = j.get("status") or "New"
            missed = is_missed_job(j)

            if f_status == "⚠️ Missed / Outdated":
                if not missed:
                    continue
            elif f_status != "All Statuses" and st != f_status:
                continue

            _, opp_label, _ = opportunity_status(j)
            tag = "missed" if missed else ("evenrow" if idx % 2 == 0 else "oddrow")

            self.tr_tree.insert("", "end", iid=str(j["id"]), values=(
                j["id"], j.get("title", ""), j.get("company", ""), j.get("location", ""),
                st, opp_label, inferred_role(j), relative_date(j.get("posted_at")),
                inferred_platform(j), j.get("notes", "")
            ), tags=(tag,))
            idx += 1

    def _populate_history_table(self):
        for item in self.hist_tree.get_children():
            self.hist_tree.delete(item)

        hist = get_status_history(limit=100)
        for idx, h in enumerate(hist):
            tag = "evenrow" if idx % 2 == 0 else "oddrow"
            self.hist_tree.insert("", "end", values=(
                h.get("title") or "Unknown job",
                h.get("company") or "",
                h.get("old_status") or "Initial",
                h.get("new_status") or "",
                (h.get("changed_at") or "")[:19]
            ), tags=(tag,))

    def _on_tracker_double_click(self, event):
        sel = self.tr_tree.selection()
        if not sel:
            return
        job_id = int(sel[0])
        match = next((j for j in self.all_jobs if j["id"] == job_id), None)
        if match:
            JobDetailDialog(
                self.root, match,
                on_status_change=self.on_dialog_status_change,
                on_favorite_toggle=self.on_dialog_fav_toggle,
                on_note_save=self.on_dialog_note_save,
                on_ai_explain=self.on_dialog_ai_explain
            )

    def on_tracker_open_url(self):
        sel = self.tr_tree.selection()
        if not sel:
            messagebox.showinfo("Select Job", "Please select a job to open.", parent=self.root)
            return
        job_id = int(sel[0])
        match = next((j for j in self.all_jobs if j["id"] == job_id), None)
        if match and match.get("job_url"):
            webbrowser.open(match["job_url"])

    def on_export_tracker_csv(self):
        jobs = self.all_jobs or list_jobs()
        if not jobs:
            messagebox.showinfo("Info", "No jobs to export.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            initialfile="job_tracker.csv"
        )
        if path:
            rows = [{
                "Title": j["title"], "Company": j["company"], "Location": j["location"],
                "Status": j["status"], "Opportunity": "Missed" if is_missed_job(j) else "Active",
                "Role": inferred_role(j), "Experience": inferred_exp(j),
                "Job type": inferred_type(j), "Posted": relative_date(j.get("posted_at")),
                "Platform": inferred_platform(j), "Source": j.get("source", ""),
                "Original posting": j.get("job_url", ""), "Notes": j.get("notes", "")
            } for j in jobs]
            pd.DataFrame(rows).to_csv(path, index=False)
            messagebox.showinfo("Export Successful", f"Saved tracker to {path}", parent=self.root)

    # =========================================================================
    # TAB 4: MARKET INSIGHTS
    # =========================================================================
    def _build_tab_insights(self):
        top = ttk.Frame(self.tab_insights)
        top.pack(fill="x", pady=(0, 6))

        ttk.Label(top, text="Market Insights from your Collected Jobs", font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(top, text="🔄 Refresh Charts", style="Primary.TButton", command=lambda: self._refresh_insights_tab(force=True)).pack(side="right")

        chart_container = ttk.Frame(self.tab_insights)
        chart_container.pack(fill="both", expand=True)

        self.ins_canvas = tk.Canvas(chart_container, bg="#ffffff", highlightthickness=0)
        ins_sb = ttk.Scrollbar(chart_container, orient="vertical", command=self.ins_canvas.yview)
        self.ins_scroll_frame = ttk.Frame(self.ins_canvas)

        self.ins_scroll_frame.bind(
            "<Configure>",
            lambda e: self.ins_canvas.configure(scrollregion=self.ins_canvas.bbox("all"))
        )
        self.ins_win = self.ins_canvas.create_window((0, 0), window=self.ins_scroll_frame, anchor="nw")
        self.ins_canvas.configure(yscrollcommand=ins_sb.set)
        self.ins_canvas.bind("<Configure>", lambda e: self.ins_canvas.itemconfig(self.ins_win, width=e.width))

        self.ins_canvas.pack(side="left", fill="both", expand=True)
        ins_sb.pack(side="right", fill="y")

        self.fig_canvas = None

    def _refresh_insights_tab(self, force=False):
        if self._insights_computing:
            return
        if self._insights_rendered and not force:
            return

        self._insights_computing = True

        for widget in self.ins_scroll_frame.winfo_children():
            widget.destroy()

        jobs = list(self.all_jobs or list_jobs())
        if not jobs:
            self._insights_computing = False
            ttk.Label(self.ins_scroll_frame, text="No jobs collected yet. Fetch live jobs to populate insights.",
                      font=("Segoe UI", 11)).pack(pady=40)
            return

        # Show non-blocking loading state with progress indicator
        loading_box = ttk.Frame(self.ins_scroll_frame, style="Card.TFrame", padding=30)
        loading_box.pack(fill="x", pady=60, padx=40)

        ttk.Label(loading_box, text=f"📊 Analyzing {len(jobs):,} Collected Jobs...", font=("Segoe UI", 12, "bold"), style="Card.TLabel").pack(pady=(0, 6))
        ttk.Label(loading_box, text="Generating employer distributions, in-demand technical skills, and platform analytics in the background.",
                  style="CardMuted.TLabel").pack(pady=(0, 16))

        ins_prog = ttk.Progressbar(loading_box, mode="indeterminate", length=320)
        ins_prog.pack(pady=(0, 10))
        ins_prog.start(12)

        def background_render():
            try:
                df = pd.DataFrame(jobs)
                fig, axes = plt.subplots(3, 2, figsize=(10, 13), dpi=92)
                fig.patch.set_facecolor("#ffffff")
                plt.subplots_adjust(hspace=0.45, wspace=0.3, left=0.1, right=0.95, top=0.96, bottom=0.05)

                # 1. Top Employers
                ax1 = axes[0, 0]
                comp_counts = df["company"].value_counts().head(12)
                comp_counts.plot(kind="barh", ax=ax1, color="#2563eb")
                ax1.set_title("Top Employers", fontsize=10, fontweight="bold")
                ax1.invert_yaxis()
                ax1.grid(axis="x", linestyle="--", alpha=0.5)

                # 2. Opportunity Pipeline (Active vs Missed)
                ax2 = axes[0, 1]
                active_cnt = sum(1 for j in jobs if not is_outdated_job(j))
                missed_cnt = sum(1 for j in jobs if is_missed_job(j))
                applied_cnt = sum(1 for j in jobs if j.get("status") in ["Applied", "Interview", "Offer"])
                pipeline_s = pd.Series({"Active (<30d)": active_cnt, "Missed (>30d)": missed_cnt, "Applied": applied_cnt})
                pipeline_s.plot(kind="bar", ax=ax2, color=["#16a34a", "#d97706", "#2563eb"])
                ax2.set_title("Active vs. Missed Opportunities", fontsize=10, fontweight="bold")
                ax2.tick_params(axis="x", rotation=20)
                ax2.grid(axis="y", linestyle="--", alpha=0.5)

                # 3. Roles Specialization Distribution (sample for speed)
                ax3 = axes[1, 0]
                role_sample = jobs[:2500] if len(jobs) > 2500 else jobs
                role_counts = pd.Series([inferred_role(j) for j in role_sample]).value_counts().head(10)
                role_counts.plot(kind="barh", ax=ax3, color="#7c3aed")
                ax3.set_title("Roles / Specializations", fontsize=10, fontweight="bold")
                ax3.invert_yaxis()
                ax3.grid(axis="x", linestyle="--", alpha=0.5)

                # 4. Location / City
                ax4 = axes[1, 1]
                city_sample = jobs[:2500] if len(jobs) > 2500 else jobs
                city_counts = pd.Series([city_of(j) for j in city_sample]).value_counts().head(10)
                city_counts.plot(kind="bar", ax=ax4, color="#16a34a")
                ax4.set_title("Top Locations / Cities", fontsize=10, fontweight="bold")
                ax4.tick_params(axis="x", rotation=30)
                ax4.grid(axis="y", linestyle="--", alpha=0.5)

                # 5. Technical Skills (Analyzes representative sample of newest 350 jobs for instantaneous response)
                ax5 = axes[2, 0]
                skill_sample = jobs[:350] if len(jobs) > 350 else jobs
                skill_counts = {}
                for j in skill_sample:
                    text = (j.get("title") or "") + " " + (j.get("description") or "")
                    for sk in extract_skills(text):
                        skill_counts[sk] = skill_counts.get(sk, 0) + 1

                if skill_counts:
                    top_skills = pd.Series(skill_counts).sort_values(ascending=False).head(15)
                    top_skills.plot(kind="barh", ax=ax5, color="#d97706")
                    ax5.set_title("Most In-Demand Skills", fontsize=10, fontweight="bold")
                    ax5.invert_yaxis()
                    ax5.grid(axis="x", linestyle="--", alpha=0.5)
                else:
                    ax5.text(0.5, 0.5, "No skills extracted", ha="center", va="center")

                # 6. Platform & ATS Sources
                ax6 = axes[2, 1]
                plat_counts = pd.Series([inferred_platform(j) for j in jobs]).value_counts()
                plat_counts.plot(kind="bar", ax=ax6, color="#0891b2")
                ax6.set_title("Jobs by Platform & ATS Source", fontsize=10, fontweight="bold")
                ax6.tick_params(axis="x", rotation=25)
                ax6.grid(axis="y", linestyle="--", alpha=0.5)

                if self.root.winfo_exists():
                    self.root.after(0, lambda: self._on_insights_ready(fig))
            except Exception as e:
                if self.root.winfo_exists():
                    self.root.after(0, lambda: self._on_insights_error(str(e)))

        threading.Thread(target=background_render, daemon=True).start()

    def _on_insights_ready(self, fig):
        self._insights_computing = False
        self._insights_rendered = True

        for widget in self.ins_scroll_frame.winfo_children():
            widget.destroy()

        self.fig_canvas = FigureCanvasTkAgg(fig, master=self.ins_scroll_frame)
        self.fig_canvas.draw()
        self.fig_canvas.get_tk_widget().pack(fill="both", expand=True)
        self.ins_canvas.configure(scrollregion=self.ins_canvas.bbox("all"))

    def _on_insights_error(self, err_msg):
        self._insights_computing = False
        for widget in self.ins_scroll_frame.winfo_children():
            widget.destroy()
        ttk.Label(self.ins_scroll_frame, text=f"Could not render insights: {err_msg}", foreground="#dc2626").pack(pady=40)

    # =========================================================================
    # TAB 5: AI CAREER ASSISTANT
    # =========================================================================
    def _build_tab_assistant(self):
        asst_conn_card = ttk.Frame(self.tab_assistant, style="Card.TFrame", padding=(12, 8))
        asst_conn_card.pack(fill="x", pady=(0, 8))

        row1 = ttk.Frame(asst_conn_card, style="Card.TFrame")
        row1.pack(fill="x")

        self.asst_status_pill = ttk.Label(
            row1,
            text="● Checking LLM status...",
            style="StatusPillChecking.TLabel"
        )
        self.asst_status_pill.pack(side="left")

        ttk.Button(
            row1,
            text="🔄 Test Connection & Fetch Models",
            style="Outline.TButton",
            command=self.check_llm_status
        ).pack(side="right")

        row2 = ttk.Frame(asst_conn_card, style="Card.TFrame")
        row2.pack(fill="x", pady=(6, 0))

        ttk.Label(row2, text="Server URL:", style="CardBold.TLabel").pack(side="left", padx=(0, 4))
        self.asst_url_var = tk.StringVar(value=BASE_URL)
        ttk.Entry(row2, textvariable=self.asst_url_var, width=24).pack(side="left", padx=(0, 10))

        ttk.Label(row2, text="Active Model:", style="CardBold.TLabel").pack(side="left", padx=(0, 4))
        self.asst_model_var = tk.StringVar(value=MODEL)
        self.asst_model_cb = ttk.Combobox(
            row2,
            textvariable=self.asst_model_var,
            values=self.available_models,
            width=28
        )
        self.asst_model_cb.pack(side="left", padx=(0, 8))
        self.asst_model_cb.bind("<<ComboboxSelected>>", self.on_asst_model_selected)

        ttk.Button(row2, text="Apply Settings", style="Primary.TButton", command=self.on_asst_apply_settings).pack(side="left")

        self.asst_resume_meta = ttk.Label(row2, text="", style="CardMuted.TLabel")
        self.asst_resume_meta.pack(side="right")

        paned = ttk.PanedWindow(self.tab_assistant, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=6)
        paned.add(left, weight=4)

        ttk.Label(left, text="Ask Career / Job Search Question:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.ai_prompt_text = tk.Text(left, height=6, wrap="word", font=("Segoe UI", 9), relief="solid", borderwidth=1, bg="#ffffff", padx=6, pady=6)
        self.ai_prompt_text.pack(fill="x", pady=(4, 8))
        self.ai_prompt_text.insert("1.0", "Compare backend and data engineering roles based on my current resume skills.")

        self.ask_ai_btn = ttk.Button(left, text="🚀 Ask Local Qwen3", style="Primary.TButton", command=self.on_ask_career_assistant)
        self.ask_ai_btn.pack(anchor="w", pady=(0, 12))

        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=(0, 10))
        ttk.Label(left, text="Role-Specific Interview Practice:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        ttk.Label(left, text="Select a saved job to generate 8 targeted interview questions.", style="Muted.TLabel").pack(anchor="w", pady=(1, 4))

        self.ai_job_var = tk.StringVar(value="Choose a saved job")
        self.ai_job_cb = ttk.Combobox(left, textvariable=self.ai_job_var, state="readonly", width=34)
        self.ai_job_cb.pack(fill="x", pady=(0, 6))

        self.practice_btn = ttk.Button(left, text="🎯 Generate Interview Practice", command=self.on_generate_interview_practice)
        self.practice_btn.pack(anchor="w")

        right = ttk.LabelFrame(paned, text="AI Response", padding=8)
        paned.add(right, weight=6)

        r_bar = ttk.Frame(right)
        r_bar.pack(fill="x", pady=(0, 6))
        self.ai_gen_status = ttk.Label(r_bar, text="Ready", style="Muted.TLabel")
        self.ai_gen_status.pack(side="left")
        ttk.Button(r_bar, text="Copy Response", command=self.on_copy_ai_response).pack(side="right")

        self.ai_response_text = tk.Text(right, wrap="word", font=("Segoe UI", 9), relief="solid", borderwidth=1,
                                        bg="#ffffff", padx=10, pady=10)
        ai_sb = ttk.Scrollbar(right, orient="vertical", command=self.ai_response_text.yview)
        self.ai_response_text.configure(yscrollcommand=ai_sb.set)

        self.ai_response_text.pack(side="left", fill="both", expand=True)
        ai_sb.pack(side="right", fill="y")

    def _refresh_assistant_tab(self):
        self._update_assistant_meta()
        jobs = self.all_jobs or list_jobs()
        options = [f"{j['id']}: {j['title']} — {j['company']}" for j in jobs[:300]]
        self.ai_job_cb.configure(values=["Choose a saved job"] + options)
        if options and self.ai_job_var.get() == "Choose a saved job":
            self.ai_job_cb.current(0)

    def _update_assistant_meta(self):
        r_status = f"📄 Resume: Loaded ({len(self.resume_text):,} chars)" if self.resume_text else "📄 Resume: None (Upload in Find Jobs)"
        if hasattr(self, "asst_resume_meta"):
            self.asst_resume_meta.configure(text=r_status)

    def on_asst_model_selected(self, event=None):
        new_model = self.asst_model_var.get().strip()
        if new_model:
            set_llm_config(model=new_model)
            self.header_model_var.set(new_model)
            if hasattr(self, "llm_model_var"):
                self.llm_model_var.set(new_model)
            self.check_llm_status()

    def on_asst_apply_settings(self):
        url = self.asst_url_var.get().strip()
        model = self.asst_model_var.get().strip()
        set_llm_config(base_url=url, model=model)
        self.header_model_var.set(model)
        if hasattr(self, "llm_url_var"):
            self.llm_url_var.set(url)
        if hasattr(self, "llm_model_var"):
            self.llm_model_var.set(model)
        self.check_llm_status()
        messagebox.showinfo("Applied", f"Applied LLM Settings:\nURL: {url}\nModel: {model}", parent=self.root)

    def on_ask_career_assistant(self):
        prompt = self.ai_prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("Warning", "Please enter a question.", parent=self.root)
            return

        self.ask_ai_btn.configure(state="disabled")
        self.practice_btn.configure(state="disabled")
        self.ai_gen_status.configure(text="Generating response with local LLM…")
        self.ai_response_text.delete("1.0", "end")
        self.ai_response_text.insert("1.0", "Consulting local LLM via LM Studio, please wait…\n")

        def worker():
            resume_context = self.resume_text[:6000] if self.resume_text else "None provided."
            query = f"User question: {prompt}\n\nResume context (if supplied):\n{resume_context}"
            res = chat(query, system="You are a grounded career assistant. Distinguish evidence from suggestions. Do not guarantee hiring outcomes.")
            self.root.after(0, lambda: self._on_ai_finish(res))

        threading.Thread(target=worker, daemon=True).start()

    def on_generate_interview_practice(self):
        chosen = self.ai_job_var.get()
        if not chosen or chosen == "Choose a saved job":
            messagebox.showinfo("Select Job", "Please select a job from the dropdown.", parent=self.root)
            return

        job_id = int(chosen.split(":")[0])
        match = next((j for j in self.all_jobs if j["id"] == job_id), None)
        if not match:
            return

        self.ask_ai_btn.configure(state="disabled")
        self.practice_btn.configure(state="disabled")
        self.ai_gen_status.configure(text="Generating role-specific interview practice…")
        self.ai_response_text.delete("1.0", "end")
        self.ai_response_text.insert("1.0", f"Generating 8 role-specific questions for {match.get('title')} at {match.get('company')}…\n")

        def worker():
            desc = match.get("description") or ""
            query = (
                "Create 8 role-specific interview questions with short answer guidance. "
                f"Ground them in this posting:\n{match.get('title')} at {match.get('company')}\n{desc[:6000]}"
            )
            res = chat(query)
            self.root.after(0, lambda: self._on_ai_finish(res))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ai_finish(self, response_text):
        self.ai_response_text.delete("1.0", "end")
        self.ai_response_text.insert("1.0", response_text)
        self.ai_gen_status.configure(text="Response received.")
        self.ask_ai_btn.configure(state="normal")
        self.practice_btn.configure(state="normal")

    def on_copy_ai_response(self):
        text = self.ai_response_text.get("1.0", "end").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo("Copied", "Response copied to clipboard.", parent=self.root)

    # =========================================================================
    # TAB 6: SOURCES & BACKUPS
    # =========================================================================
    def _build_tab_sources(self):
        paned = ttk.PanedWindow(self.tab_sources, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=8)
        paned.add(left, weight=5)

        cfg_frame = ttk.LabelFrame(left, text="Configured Company Boards (config/companies.json)", padding=8)
        cfg_frame.pack(fill="both", expand=True, pady=(0, 6))

        ttk.Label(cfg_frame, text="Edit ATS board identifiers below (Greenhouse, Lever, and Workday):", style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        self.cfg_text = tk.Text(cfg_frame, height=10, wrap="none", font=("Consolas", 9), relief="solid", borderwidth=1, bg="#ffffff")
        cfg_sb = ttk.Scrollbar(cfg_frame, orient="vertical", command=self.cfg_text.yview)
        self.cfg_text.configure(yscrollcommand=cfg_sb.set)
        self.cfg_text.pack(side="left", fill="both", expand=True)
        cfg_sb.pack(side="right", fill="y")

        cfg_btn_box = ttk.Frame(left)
        cfg_btn_box.pack(fill="x", pady=(0, 8))
        ttk.Button(cfg_btn_box, text="Save Configuration", style="Primary.TButton", command=self.on_save_config).pack(side="left", padx=(0, 6))
        ttk.Button(cfg_btn_box, text="Reload File", command=self.on_reload_config).pack(side="left", padx=(0, 6))
        ttk.Button(cfg_btn_box, text="🩺 Run Source Health Check", command=self.on_run_source_health).pack(side="left")

        db_frame = ttk.LabelFrame(left, text="Database Backup & Restore", padding=8)
        db_frame.pack(fill="x", pady=(0, 6))

        d_btns = ttk.Frame(db_frame)
        d_btns.pack(fill="x", pady=2)
        ttk.Button(d_btns, text="💾 Create Daily Backup", command=self.on_create_backup_click).pack(side="left", padx=(0, 6))
        ttk.Button(d_btns, text="Export Snapshot", command=self.on_export_db_click).pack(side="left", padx=(0, 6))
        ttk.Button(d_btns, text="Restore from File", command=self.on_restore_db_click).pack(side="left")

        # Database Maintenance & Retention Section
        clean_frame = ttk.LabelFrame(left, text="Database Maintenance & Expired Jobs Retention", padding=8)
        clean_frame.pack(fill="x", pady=(0, 6))

        c_row = ttk.Frame(clean_frame)
        c_row.pack(fill="x", pady=(0, 4))
        ttk.Label(c_row, text="Retention Policy:").pack(side="left", padx=(0, 4))
        self.retention_cb = ttk.Combobox(
            c_row,
            textvariable=self.retention_var,
            values=[
                "10 days (Default - Recommended)",
                "15 days",
                "30 days",
                "60 days",
                "Keep All (Never)"
            ],
            state="readonly",
            width=28
        )
        self.retention_cb.pack(side="left", padx=(0, 6))
        ttk.Button(c_row, text="🧹 Clean Expired Jobs Now", style="Primary.TButton", command=self.on_clean_expired_jobs_click).pack(side="left")

        ttk.Label(
            clean_frame,
            text="Deletes stale unapplied postings older than the chosen limit (default 10 days) and compacts storage.\nTracked applications, favorites, and notes are ALWAYS safely preserved.",
            style="Muted.TLabel"
        ).pack(anchor="w", pady=(2, 0))

        llm_frame = ttk.LabelFrame(left, text="LM Studio Local AI Settings", padding=8)
        llm_frame.pack(fill="x")

        l1 = ttk.Frame(llm_frame)
        l1.pack(fill="x", pady=2)
        ttk.Label(l1, text="Base URL:").pack(side="left", padx=(0, 4))
        self.llm_url_var = tk.StringVar(value=BASE_URL)
        ttk.Entry(l1, textvariable=self.llm_url_var, width=24).pack(side="left", padx=(0, 10))

        ttk.Label(l1, text="Model:").pack(side="left", padx=(0, 4))
        self.llm_model_var = tk.StringVar(value=MODEL)
        ttk.Entry(l1, textvariable=self.llm_model_var, width=20).pack(side="left")

        l2 = ttk.Frame(llm_frame)
        l2.pack(fill="x", pady=(4, 0))
        ttk.Button(l2, text="Test Connection", command=self.on_test_llm_connection).pack(side="left", padx=(0, 6))
        ttk.Button(l2, text="Save Settings", style="Primary.TButton", command=self.on_save_llm_settings).pack(side="left")

        right = ttk.LabelFrame(paned, text="Recent Sync Runs", padding=8)
        paned.add(right, weight=5)

        s_cols = ("started", "finished", "fetched", "new", "updated", "errors")
        self.sync_tree = ttk.Treeview(right, columns=s_cols, show="headings", selectmode="browse")
        self.sync_tree.heading("started", text="Started")
        self.sync_tree.heading("finished", text="Finished")
        self.sync_tree.heading("fetched", text="Fetched")
        self.sync_tree.heading("new", text="New")
        self.sync_tree.heading("updated", text="Refreshed")
        self.sync_tree.heading("errors", text="Errors")

        self.sync_tree.column("started", width=110)
        self.sync_tree.column("finished", width=110)
        self.sync_tree.column("fetched", width=55, anchor="center")
        self.sync_tree.column("new", width=50, anchor="center")
        self.sync_tree.column("updated", width=65, anchor="center")
        self.sync_tree.column("errors", width=50, anchor="center")

        self.sync_tree.tag_configure("evenrow", background="#ffffff")
        self.sync_tree.tag_configure("oddrow", background="#f8fafc")

        s_sb = ttk.Scrollbar(right, orient="vertical", command=self.sync_tree.yview)
        self.sync_tree.configure(yscrollcommand=s_sb.set)
        self.sync_tree.pack(fill="both", expand=True)
        s_sb.pack(side="right", fill="y")

        self.sync_details_text = tk.Text(right, height=5, wrap="word", font=("Consolas", 8), bg="#ffffff")
        self.sync_details_text.pack(fill="x", pady=(6, 0))

        self.sync_tree.bind("<<TreeviewSelect>>", self._on_sync_selected)

    def _refresh_sources_tab(self):
        self.on_reload_config()
        self._populate_sync_runs()

    def on_reload_config(self):
        cfg_path = ROOT / "config" / "companies.json"
        if cfg_path.exists():
            try:
                content = cfg_path.read_text(encoding="utf-8")
                self.cfg_text.delete("1.0", "end")
                self.cfg_text.insert("1.0", content)
            except Exception as exc:
                messagebox.showerror("Error", f"Failed reading config: {exc}", parent=self.root)

    def on_save_config(self):
        content = self.cfg_text.get("1.0", "end").strip()
        try:
            parsed = json.loads(content)
            cfg_path = ROOT / "config" / "companies.json"
            cfg_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
            messagebox.showinfo("Saved", "Company boards configuration saved successfully.", parent=self.root)
        except json.JSONDecodeError as exc:
            messagebox.showerror("Invalid JSON", f"Please check the JSON formatting:\n{exc}", parent=self.root)

    def on_run_source_health(self):
        SourceHealthDialog(self.root)

    def _populate_sync_runs(self):
        for item in self.sync_tree.get_children():
            self.sync_tree.delete(item)

        runs = get_sync_runs(limit=30)
        for idx, r in enumerate(runs):
            tag = "evenrow" if idx % 2 == 0 else "oddrow"
            self.sync_tree.insert("", "end", iid=str(r["id"]), values=(
                (r.get("started_at") or "")[:19],
                (r.get("finished_at") or "")[:19],
                r.get("fetched_count", 0),
                r.get("inserted_count", 0),
                r.get("updated_count", 0),
                r.get("error_count", 0)
            ), tags=(tag,))

    def _on_sync_selected(self, event):
        sel = self.sync_tree.selection()
        if not sel:
            return
        run_id = int(sel[0])
        runs = get_sync_runs(limit=30)
        match = next((r for r in runs if r["id"] == run_id), None)
        if match:
            self.sync_details_text.delete("1.0", "end")
            msg = match.get("message") or "No errors recorded."
            self.sync_details_text.insert("1.0", f"Run #{match['id']} Log:\n{msg}")

    def on_create_backup_click(self):
        path = backup_db()
        if path:
            messagebox.showinfo("Backup", f"Backup created: {path.name}", parent=self.root)
        else:
            messagebox.showwarning("Warning", "No database found to backup.", parent=self.root)

    def on_export_db_click(self):
        data = export_db_bytes()
        if not data:
            messagebox.showwarning("Warning", "Database snapshot is empty.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".sqlite3",
            filetypes=[("SQLite Database", "*.sqlite3;*.db")],
            initialfile=f"jobs_backup_{date.today().isoformat()}.sqlite3"
        )
        if path:
            Path(path).write_bytes(data)
            messagebox.showinfo("Export Successful", f"Saved backup snapshot to {path}", parent=self.root)

    def on_restore_db_click(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            filetypes=[("SQLite Database", "*.sqlite3;*.db")]
        )
        if not path:
            return
        if messagebox.askyesno("Confirm Restore", "Restoring will replace the current database (a safety backup is created first). Continue?", parent=self.root):
            try:
                data = Path(path).read_bytes()
                restore_db_from_bytes(data)
                self.refresh_jobs_data()
                messagebox.showinfo("Restored", "Database restored successfully.", parent=self.root)
            except Exception as exc:
                messagebox.showerror("Restore Failed", f"Could not restore database:\n{exc}", parent=self.root)

    def on_clean_expired_jobs_click(self):
        sel = self.retention_var.get()
        if "Never" in sel or "Keep All" in sel:
            messagebox.showinfo("Retention Policy", "Retention is currently set to Keep All. Select a retention period (e.g. 10 or 15 days) to prune expired listings.", parent=self.root)
            return

        days = 10
        for d in [10, 15, 30, 60]:
            if str(d) in sel:
                days = d
                break

        if not messagebox.askyesno(
            "Clean Expired Jobs",
            f"This will delete unapplied and non-favorited postings older than {days} days to reduce storage and keep the app fast.\n\nYour tracked applications (Applied, Interview, Offer), favorites, and notes will NEVER be deleted.\n\nProceed with cleanup?",
            parent=self.root
        ):
            return

        try:
            deleted, remaining = purge_expired_jobs(max_age_days=days)
            self._insights_rendered = False
            self.refresh_jobs_data()
            messagebox.showinfo("Cleanup Complete", f"Successfully purged {deleted:,} expired postings!\nDatabase compacted with VACUUM.\nTotal active jobs remaining: {remaining:,}.", parent=self.root)
        except Exception as exc:
            messagebox.showerror("Cleanup Failed", f"Error during expired jobs cleanup:\n{exc}", parent=self.root)

    def on_test_llm_connection(self):
        url = self.llm_url_var.get().strip()
        model = self.llm_model_var.get().strip()
        set_llm_config(base_url=url, model=model)
        self.check_llm_status()

    def on_save_llm_settings(self):
        url = self.llm_url_var.get().strip()
        model = self.llm_model_var.get().strip()
        set_llm_config(base_url=url, model=model)
        self.header_model_var.set(model)
        if hasattr(self, "asst_url_var"):
            self.asst_url_var.set(url)
        if hasattr(self, "asst_model_var"):
            self.asst_model_var.set(model)
        self.check_llm_status()
        messagebox.showinfo("Saved", "LM Studio settings applied.", parent=self.root)

    # =========================================================================
    # CORE LOGIC: FETCH LIVE JOBS
    # =========================================================================
    def on_fetch_live_jobs(self):
        if self.is_fetching:
            return

        self.is_fetching = True
        self.fetch_btn.configure(state="disabled")
        self.status_progress["value"] = 0
        self.status_label.configure(text="Starting sync…")

        def progress_cb(current, total, text):
            self.root.after(0, lambda: self._update_sync_progress(current, total, text))

        def worker():
            run_id = create_sync_run()
            try:
                jobs_fetched, errors, _ = fetch_all_jobs(progress_cb)
                backup_path = backup_db()
                inserted, updated = upsert_jobs(jobs_fetched)
                finish_sync_run(run_id, len(jobs_fetched), inserted, updated, errors)

                self.root.after(0, lambda: self._on_sync_complete(len(jobs_fetched), inserted, updated, errors, backup_path))
            except Exception as exc:
                self.root.after(0, lambda: self._on_sync_error(str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _update_sync_progress(self, current, total, text):
        pct = (current / max(1, total)) * 100
        self.status_progress["value"] = pct
        self.status_label.configure(text=f"Syncing: {text[:28]}")

    def _on_sync_complete(self, total, inserted, updated, errors, backup_path):
        self.is_fetching = False
        self.fetch_btn.configure(state="normal")
        self.status_progress["value"] = 100
        self.status_label.configure(text="Sync complete!")
        self.refresh_jobs_data()

        msg = f"Sync finished!\n\nPostings fetched: {total}\nNew jobs: {inserted}\nRefreshed: {updated}"
        if backup_path:
            msg += f"\nPre-sync backup: {backup_path.name}"
        if errors:
            msg += f"\n\nSource warnings/errors: {len(errors)} (see Sources tab)"

        messagebox.showinfo("Sync Complete", msg, parent=self.root)

    def _on_sync_error(self, err_msg):
        self.is_fetching = False
        self.fetch_btn.configure(state="normal")
        self.status_label.configure(text="Sync failed")
        messagebox.showerror("Sync Error", f"An error occurred while fetching jobs:\n{err_msg}", parent=self.root)

    # =========================================================================
    # CORE LOGIC: DATA REFRESH & FILTERING
    # =========================================================================
    def refresh_jobs_data(self):
        self.all_jobs = list_jobs(limit=10000)
        self._insights_rendered = False

        # Update metric cards (Including Missed Jobs calculation)
        missed_count = sum(1 for j in self.all_jobs if is_missed_job(j))

        self.metric_saved.configure(text=str(len(self.all_jobs)))
        self.metric_india.configure(text=str(sum(1 for j in self.all_jobs if india_job(j))))
        self.metric_intern.configure(text=str(sum(1 for j in self.all_jobs if inferred_type(j) == "Internship")))
        self.metric_watch.configure(text=str(len(get_watchlist())))
        self.metric_missed.configure(text=str(missed_count))

        # Populate Platforms dropdown (Guarantees Workday, Greenhouse, Lever.co, etc. are always visible)
        discovered = {inferred_platform(j) for j in self.all_jobs}
        platforms = []
        for p in PLATFORM_CATEGORIES:
            if p not in platforms:
                platforms.append(p)
        for p in sorted(discovered):
            if p not in platforms:
                platforms.append(p)

        curr_src = self.source_var.get()
        self.source_cb.configure(values=platforms)
        if curr_src not in platforms:
            self.source_var.set("All platforms")

        self.apply_filters()

    def apply_filters(self):
        query = self.query_var.get().strip().lower()
        source = self.source_var.get()
        location_pref = self.loc_var.get()
        opp_filter = self.opp_var.get()
        role = self.role_var.get()
        city = self.city_var.get()
        exp = self.exp_var.get()
        job_type = self.type_var.get()
        mode = self.mode_var.get()
        age = self.age_var.get()
        status = self.status_var.get()
        fav_only = self.fav_only_var.get()
        salary = self.sal_var.get()
        sort_by = self.sort_var.get()

        filtered = list(self.all_jobs)

        # 1. Query
        if query:
            filtered = [
                j for j in filtered if query in
                " ".join(str(j.get(k, "")) for k in ["title", "company", "location", "description", "source"]).lower()
                or query in inferred_platform(j).lower()
            ]

        # 2. Company filter
        if self.selected_companies:
            sel_comps = {c.casefold() for c in self.selected_companies}
            filtered = [j for j in filtered if str(j.get("company") or "").casefold() in sel_comps]

        # 3. Opportunity / Freshness Filter (New!)
        if opp_filter == "Active & Fresh (<30d)":
            filtered = [j for j in filtered if not is_outdated_job(j)]
        elif opp_filter == "⚠️ Missed / Outdated (>30d)":
            filtered = [j for j in filtered if is_missed_job(j)]
        elif opp_filter == "In Progress (Applied)":
            filtered = [j for j in filtered if j.get("status") in ["Applied", "Interview", "Offer"]]

        # 4. Platform / Source filter
        if source not in ["All platforms", "All sources"]:
            filtered = [j for j in filtered if inferred_platform(j) == source or j.get("source") == source]

        # 5. Location preference
        if location_pref == "India only":
            filtered = [j for j in filtered if india_job(j)]
        elif location_pref == "Remote worldwide":
            filtered = [j for j in filtered if remote_job(j)]

        # 6. Role Specialization
        if role != "All Roles":
            filtered = [j for j in filtered if inferred_role(j) == role]

        # 7. City
        if city != "Any city":
            filtered = [j for j in filtered if city_of(j) == city]

        # 8. Experience
        if exp != "Any experience":
            filtered = [j for j in filtered if inferred_exp(j) == exp]

        # 9. Job Type
        if job_type != "All types":
            filtered = [j for j in filtered if inferred_type(j) == job_type]

        # 10. Work mode
        if mode != "All modes":
            filtered = [j for j in filtered if inferred_mode(j) == mode]

        # 11. Status
        if status != "All statuses":
            filtered = [j for j in filtered if (j.get("status") or "New") == status]

        # 12. Favorites
        if fav_only:
            filtered = [j for j in filtered if int(j.get("is_favorite") or 0) == 1]

        # 13. Salary
        if salary == "Salary disclosed":
            filtered = [j for j in filtered if j.get("salary_min") is not None or j.get("salary_max") is not None]
        elif salary == "Salary not disclosed":
            filtered = [j for j in filtered if j.get("salary_min") is None and j.get("salary_max") is None]

        # 14. Age
        today = date.today()
        if age != "Any date":
            def age_days(j):
                d = parse_date(j.get("posted_at"))
                return (today - d).days if d else None

            if age == "Date unknown":
                filtered = [j for j in filtered if age_days(j) is None]
            elif age == "Today":
                filtered = [j for j in filtered if age_days(j) == 0]
            elif age == "Yesterday":
                filtered = [j for j in filtered if age_days(j) == 1]
            elif age == "Last 7 days":
                filtered = [j for j in filtered if age_days(j) is not None and 0 <= age_days(j) <= 7]
            elif age == "Last 30 days":
                filtered = [j for j in filtered if age_days(j) is not None and 0 <= age_days(j) <= 30]
            elif age == "Older than 30 days":
                filtered = [j for j in filtered if age_days(j) is not None and age_days(j) > 30]

        # Rank jobs if resume loaded
        if self.resume_text.strip() and filtered:
            ranked = rank_jobs(self.resume_text, filtered)
        else:
            ranked = [{**j, "match_score": None, "matched_skills": [], "missing_skills": []} for j in filtered]

        # Sorting
        if sort_by == "Best match":
            ranked.sort(key=lambda j: (
                not india_job(j),
                -(j.get("match_score") or 0),
                -(parse_date(j.get("posted_at")).toordinal() if parse_date(j.get("posted_at")) else 0)
            ))
        elif sort_by == "Newest first":
            ranked.sort(key=lambda j: parse_date(j.get("posted_at")) or date.min, reverse=True)
        elif sort_by == "Oldest first":
            ranked.sort(key=lambda j: parse_date(j.get("posted_at")) or date.max)
        elif sort_by == "Company A–Z":
            ranked.sort(key=lambda j: str(j.get("company", "")).lower())
        elif sort_by == "Salary highest first":
            ranked.sort(key=lambda j: j.get("salary_max") or j.get("salary_min") or 0, reverse=True)
        elif sort_by == "Recently discovered":
            ranked.sort(key=lambda j: str(j.get("discovered_at", "")), reverse=True)

        self.filtered_jobs = ranked
        self._populate_job_tree()

    def _populate_job_tree(self):
        for item in self.job_tree.get_children():
            self.job_tree.delete(item)

        self.count_label.configure(text=f"Showing {len(self.filtered_jobs)} of {len(self.all_jobs)} jobs")

        for idx, j in enumerate(self.filtered_jobs):
            is_fav = bool(j.get("is_favorite") or 0)
            fav_char = "★" if is_fav else "☆"
            score_str = f"{j['match_score']}%" if j.get("match_score") is not None else "-"

            missed = is_missed_job(j)
            _, opp_label, _ = opportunity_status(j)

            tag = "favorited" if is_fav else ("missed" if missed else ("evenrow" if idx % 2 == 0 else "oddrow"))

            self.job_tree.insert("", "end", iid=str(j["id"]), values=(
                fav_char,
                j.get("title", ""),
                j.get("company", ""),
                inferred_platform(j),
                j.get("location", ""),
                score_str,
                j.get("status") or "New",
                opp_label,
                inferred_role(j),
                relative_date(j.get("posted_at"))
            ), tags=(tag,))

        if self.filtered_jobs:
            first_id = str(self.filtered_jobs[0]["id"])
            self.job_tree.selection_set(first_id)
            self._display_job_card(self.filtered_jobs[0])
        else:
            self._clear_job_card()

    def _on_job_selected(self, event):
        sel = self.job_tree.selection()
        if not sel:
            return
        job_id = int(sel[0])
        match = next((j for j in self.filtered_jobs if j["id"] == job_id), None)
        if match:
            self._display_job_card(match)

    def _on_job_double_click(self, event):
        sel = self.job_tree.selection()
        if not sel:
            return
        job_id = int(sel[0])
        match = next((j for j in self.filtered_jobs if j["id"] == job_id), None)
        if match:
            JobDetailDialog(
                self.root, match,
                on_status_change=self.on_dialog_status_change,
                on_favorite_toggle=self.on_dialog_fav_toggle,
                on_note_save=self.on_dialog_note_save,
                on_ai_explain=self.on_dialog_ai_explain
            )

    def _display_job_card(self, job):
        self.current_job = job
        plat_name, plat_type, plat_icon = platform_badge_info(job)

        self.card_title.configure(text=job.get("title") or "Untitled role")
        self.card_sub.configure(text=f"{job.get('company') or 'Unknown company'} · {job.get('location') or 'Location not specified'}")

        # Platform Pill
        self.card_platform_pill.configure(
            text=f"{plat_icon} Platform: {plat_name} ({plat_type})",
            style="PlatformPill.TLabel"
        )
        self.card_meta.configure(text=f"{relative_date(job.get('posted_at'))} · {plat_name} · Source: {job.get('source') or 'Source unknown'}")

        # Opportunity Alert
        missed = is_missed_job(job)
        if missed:
            self.card_opp_alert.configure(
                text="⚠️ Missed Opportunity: Posted >30 days ago without an application. Listing may be expired or filled.",
                style="StatusPillMissed.TLabel"
            )
        elif is_outdated_job(job):
            self.card_opp_alert.configure(
                text="ℹ️ Older Listing: Posted >30 days ago. You can still verify the original page.",
                style="StatusPillChecking.TLabel"
            )
        else:
            self.card_opp_alert.configure(
                text="🟢 Active & Fresh Opportunity",
                style="StatusPillOnline.TLabel"
            )

        self.card_badge.configure(text=f"Role: {inferred_role(job)} | Exp: {inferred_exp(job)} | Type: {inferred_type(job)} | Mode: {inferred_mode(job)} | Salary: {safe_salary(job)}")

        score = job.get("match_score")
        if score is not None:
            self.card_match_lbl.configure(text=f"🎯 Resume Match: {score}%", foreground=COLORS["success"] if score >= 60 else COLORS["warning"])
        else:
            self.card_match_lbl.configure(text="Upload resume to view match score", foreground=COLORS["text_muted"])

        matched = job.get("matched_skills") or []
        missing = job.get("missing_skills") or []
        skills_text = ""
        if matched:
            skills_text += f"Matched: {', '.join(matched[:15])}\n"
        if missing:
            skills_text += f"Posting skills: {', '.join(missing[:12])}"
        self.card_skills_lbl.configure(text=skills_text)

        fav = bool(job.get("is_favorite") or 0)
        self.card_fav_btn.configure(text="★ Favorited" if fav else "☆ Favorite")
        self.card_url_btn.configure(text=f"Open on {plat_name} ↗")
        self.card_status_var.set(job.get("status") or "New")
        self.card_note_var.set(job.get("notes") or "")

        self.card_desc.configure(state="normal")
        self.card_desc.delete("1.0", "end")
        self.card_desc.insert("1.0", job.get("description") or "No description provided.")
        self.card_desc.configure(state="disabled")

    def _clear_job_card(self):
        self.current_job = None
        self.card_title.configure(text="No matching jobs found")
        self.card_sub.configure(text="Try relaxing your filters or clicking Fetch live jobs.")
        self.card_platform_pill.configure(text="")
        self.card_url_btn.configure(text="Open URL ↗")
        self.card_meta.configure(text="")
        self.card_opp_alert.configure(text="")
        self.card_badge.configure(text="")
        self.card_match_lbl.configure(text="")
        self.card_skills_lbl.configure(text="")
        self.card_desc.configure(state="normal")
        self.card_desc.delete("1.0", "end")
        self.card_desc.configure(state="disabled")

    # =========================================================================
    # JOB CARD ACTIONS
    # =========================================================================
    def on_toggle_current_favorite(self):
        if not self.current_job:
            return
        job_id = self.current_job["id"]
        new_fav = 0 if bool(self.current_job.get("is_favorite") or 0) else 1
        update_job_metadata(job_id, is_favorite=new_fav)
        self.current_job["is_favorite"] = new_fav

        for j in self.all_jobs:
            if j["id"] == job_id:
                j["is_favorite"] = new_fav

        fav_char = "★" if new_fav else "☆"
        self.card_fav_btn.configure(text="★ Favorited" if new_fav else "☆ Favorite")
        if self.job_tree.exists(str(job_id)):
            vals = list(self.job_tree.item(str(job_id), "values"))
            vals[0] = fav_char
            tag = "favorited" if new_fav else ("missed" if is_missed_job(self.current_job) else "evenrow")
            self.job_tree.item(str(job_id), values=vals, tags=(tag,))

    def on_change_current_status(self, event=None):
        if not self.current_job:
            return
        new_status = self.card_status_var.get()
        job_id = self.current_job["id"]
        update_status(job_id, new_status)
        self.current_job["status"] = new_status

        for j in self.all_jobs:
            if j["id"] == job_id:
                j["status"] = new_status

        if self.job_tree.exists(str(job_id)):
            vals = list(self.job_tree.item(str(job_id), "values"))
            vals[5] = new_status
            self.job_tree.item(str(job_id), values=vals)

        # Update metric counts (e.g. if job was marked Applied, it is no longer missed!)
        missed_count = sum(1 for j in self.all_jobs if is_missed_job(j))
        self.metric_missed.configure(text=str(missed_count))

    def on_save_current_note(self):
        if not self.current_job:
            return
        note = self.card_note_var.get().strip()
        job_id = self.current_job["id"]
        update_job_metadata(job_id, notes=note)
        self.current_job["notes"] = note

        for j in self.all_jobs:
            if j["id"] == job_id:
                j["notes"] = note

        messagebox.showinfo("Saved", "Note saved.", parent=self.root)

    def on_open_current_url(self):
        if self.current_job and self.current_job.get("job_url"):
            webbrowser.open(self.current_job["job_url"])

    def on_explain_current_job(self):
        if not self.current_job:
            return
        job = self.current_job

        self.card_ai_btn.configure(state="disabled", text="Generating AI explanation…")

        def worker():
            desc = job.get("description") or ""
            prompt = (
                "Explain this job against the resume in concise plain English. Identify evidence, missing requirements, "
                "and three realistic next steps. Do not invent facts or imply the match score guarantees selection.\n\n"
                f"RESUME:\n{self.resume_text[:5000]}\n\nJOB:\n{job.get('title')} at {job.get('company')}\n"
                f"DESCRIPTION:\n{desc[:6000]}"
            )
            res = chat(prompt)

            def update_ui():
                self.card_ai_btn.configure(state="normal", text="🤖 Explain Match with Local AI")
                messagebox.showinfo(f"AI Insights: {job.get('title')}", res, parent=self.root)

            self.root.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    # Callbacks for JobDetailDialog
    def on_dialog_status_change(self, job_id, status):
        update_status(job_id, status)
        for j in self.all_jobs:
            if j["id"] == job_id:
                j["status"] = status
        self.refresh_jobs_data()

    def on_dialog_fav_toggle(self, job_id, fav_val):
        update_job_metadata(job_id, is_favorite=fav_val)
        for j in self.all_jobs:
            if j["id"] == job_id:
                j["is_favorite"] = fav_val
        self.apply_filters()

    def on_dialog_note_save(self, job_id, note):
        update_job_metadata(job_id, notes=note)
        for j in self.all_jobs:
            if j["id"] == job_id:
                j["notes"] = note
        self.apply_filters()

    def on_dialog_ai_explain(self, job, callback):
        def worker():
            desc = job.get("description") or ""
            prompt = (
                "Explain this job against the resume in concise plain English. Identify evidence, missing requirements, "
                "and three realistic next steps. Do not invent facts or imply the match score guarantees selection.\n\n"
                f"RESUME:\n{self.resume_text[:5000]}\n\nJOB:\n{job.get('title')} at {job.get('company')}\n"
                f"DESCRIPTION:\n{desc[:6000]}"
            )
            res = chat(prompt)
            self.root.after(0, lambda: callback(res))

        threading.Thread(target=worker, daemon=True).start()

    # =========================================================================
    # RESUME ACTIONS
    # =========================================================================
    def on_upload_resume(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Select Resume",
            filetypes=[("Resume Files", "*.pdf;*.docx;*.txt"), ("PDF", "*.pdf"), ("Word", "*.docx"), ("Text", "*.txt")]
        )
        if not path:
            return
        try:
            text = extract_resume_text(path)
            self.resume_text = text
            self.resume_name = Path(path).name
            self.resume_info_lbl.configure(text=f"Loaded: {self.resume_name} ({len(text):,} chars)")
            self._update_assistant_meta()
            messagebox.showinfo("Resume Loaded", f"Successfully loaded '{self.resume_name}' ({len(text):,} chars). Match scores updated!", parent=self.root)
            self.apply_filters()
        except Exception as exc:
            messagebox.showerror("Error", f"Could not read resume:\n{exc}", parent=self.root)

    def on_edit_resume(self):
        def on_apply(text):
            self.resume_text = text
            self.resume_name = "Pasted Resume"
            self.resume_info_lbl.configure(text=f"Pasted text ({len(text):,} chars)")
            self._update_assistant_meta()
            self.apply_filters()

        ResumeEditDialog(self.root, self.resume_text, on_apply)

    def on_clear_resume(self):
        self.resume_text = ""
        self.resume_name = ""
        self.resume_info_lbl.configure(text="No resume loaded")
        self._update_assistant_meta()
        self.apply_filters()

    # =========================================================================
    # FILTER ACTIONS & PRESETS
    # =========================================================================
    def on_open_company_filter(self):
        counts = {}
        for j in self.all_jobs:
            c = str(j.get("company") or "").strip()
            if c:
                counts[c] = counts.get(c, 0) + 1

        def on_apply(chosen):
            self.selected_companies = set(chosen)
            if not self.selected_companies:
                self.company_btn.configure(text="🏢 Companies: All")
            elif len(self.selected_companies) == 1:
                self.company_btn.configure(text=f"🏢 Company: {list(self.selected_companies)[0]}")
            else:
                self.company_btn.configure(text=f"🏢 Companies: ({len(self.selected_companies)} selected)")
            self.apply_filters()

        CompanyFilterDialog(self.root, counts, self.selected_companies, on_apply)

    def reset_filters(self):
        self.query_var.set("")
        self.selected_companies = set()
        self.company_btn.configure(text="🏢 Companies: All")
        self.opp_var.set("All Listings")
        self.source_var.set("All platforms")
        self.loc_var.set("India first")
        self.role_var.set("All Roles")
        self.city_var.set("Any city")
        self.exp_var.set("Any experience")
        self.type_var.set("All types")
        self.mode_var.set("All modes")
        self.age_var.set("Any date")
        self.status_var.set("All statuses")
        self.fav_only_var.set(False)
        self.sal_var.set("Any")
        self.sort_var.set("Best match")
        self.apply_filters()

    def on_save_preset(self):
        filter_data = {
            "query": self.query_var.get(),
            "companies": list(self.selected_companies),
            "opportunity": self.opp_var.get(),
            "source": self.source_var.get(),
            "location": self.loc_var.get(),
            "role": self.role_var.get(),
            "city": self.city_var.get(),
            "experience": self.exp_var.get(),
            "job_type": self.type_var.get(),
            "work_mode": self.mode_var.get(),
            "posted": self.age_var.get(),
            "status": self.status_var.get(),
            "favorites": self.fav_only_var.get(),
            "salary": self.sal_var.get(),
            "sort": self.sort_var.get()
        }

        def on_save(name, json_str):
            save_search(name, json_str)
            messagebox.showinfo("Saved", f"Preset '{name}' saved.", parent=self.root)

        SavePresetDialog(self.root, filter_data, on_save)

    def on_manage_presets(self):
        presets = get_saved_searches()
        if not presets:
            messagebox.showinfo("Presets", "No saved search presets yet. Click 'Save Preset' to create one.", parent=self.root)
            return

        def on_load(preset):
            try:
                data = json.loads(preset["filters_json"])
                self.query_var.set(data.get("query", ""))
                self.selected_companies = set(data.get("companies", []))
                if not self.selected_companies:
                    self.company_btn.configure(text="🏢 Companies: All")
                elif len(self.selected_companies) == 1:
                    self.company_btn.configure(text=f"🏢 Company: {list(self.selected_companies)[0]}")
                else:
                    self.company_btn.configure(text=f"🏢 Companies: ({len(self.selected_companies)} selected)")

                self.opp_var.set(data.get("opportunity", "All Listings"))
                loaded_plat = data.get("platform") or data.get("source", "All platforms")
                self.source_var.set("All platforms" if loaded_plat == "All sources" else loaded_plat)
                self.loc_var.set(data.get("location", "India first"))
                self.role_var.set(data.get("role", "All Roles"))
                self.city_var.set(data.get("city", "Any city"))
                self.exp_var.set(data.get("experience", "Any experience"))
                self.type_var.set(data.get("job_type", "All types"))
                self.mode_var.set(data.get("work_mode", "All modes"))
                self.age_var.set(data.get("posted", "Any date"))
                self.status_var.set(data.get("status", "All statuses"))
                self.fav_only_var.set(bool(data.get("favorites", False)))
                self.sal_var.set(data.get("salary", "Any"))
                self.sort_var.set(data.get("sort", "Best match"))

                self.apply_filters()
                messagebox.showinfo("Preset Loaded", f"Applied filters from preset '{preset['name']}'.", parent=self.root)
            except Exception as exc:
                messagebox.showerror("Error", f"Failed loading preset: {exc}", parent=self.root)

        def on_delete(name):
            delete_saved_search(name)

        PresetsDialog(self.root, presets, on_load, on_delete)


def main():
    root = tk.Tk()
    app = LocalJobFinderApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
