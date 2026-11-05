import json
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox
from src.ui_theme import COLORS
from src.helpers import (
    relative_date, inferred_exp, inferred_type, inferred_mode, safe_salary,
    inferred_platform, platform_badge_info
)

class CompanyFilterDialog(tk.Toplevel):
    def __init__(self, parent, company_counts, selected_companies, on_apply):
        super().__init__(parent)
        self.title("Filter by Companies")
        self.geometry("450x550")
        self.minsize(380, 400)
        self.transient(parent)
        self.grab_set()

        self.company_counts = company_counts
        self.selected = set(c.casefold() for c in selected_companies)
        self.on_apply = on_apply
        self.var_dict = {}

        self.configure(bg=COLORS["bg"])

        # Header
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill="x")
        ttk.Label(top_frame, text="Select Companies to Filter", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(top_frame, text="Search and check one or more employers. Uncheck all to include all companies.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 6))

        # Search box
        search_frame = ttk.Frame(top_frame)
        search_frame.pack(fill="x", pady=4)
        ttk.Label(search_frame, text="🔍 Search:").pack(side="left", padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.filter_list())
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side="left", fill="x", expand=True)

        # Quick action buttons
        action_frame = ttk.Frame(self, padding=(10, 0))
        action_frame.pack(fill="x")
        ttk.Button(action_frame, text="Select All", command=self.select_all).pack(side="left", padx=(0, 5))
        ttk.Button(action_frame, text="Deselect All", command=self.deselect_all).pack(side="left")

        # Scrollable list of companies
        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(container, bg=COLORS["card_bg"], highlightthickness=1, highlightbackground=COLORS["card_border"])
        self.scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = ttk.Frame(self.canvas)
        self.scroll_frame.configure(style="Card.TFrame")

        self.scroll_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(xscrollcommand=None, yscrollcommand=self.scrollbar.set)
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self.canvas_window, width=e.width))

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Bottom Buttons
        bottom_frame = ttk.Frame(self, padding=10)
        bottom_frame.pack(fill="x")
        ttk.Button(bottom_frame, text="Apply Filter", style="Primary.TButton", command=self.apply).pack(side="right", padx=(5, 0))
        ttk.Button(bottom_frame, text="Cancel", command=self.destroy).pack(side="right")

        self.populate_list()
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        if self.winfo_exists():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def populate_list(self):
        query = self.search_var.get().strip().casefold()
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        sorted_companies = sorted(self.company_counts.keys(), key=str.casefold)
        for comp in sorted_companies:
            count = self.company_counts[comp]
            label_text = f"{comp} ({count} jobs)"
            if query and query not in comp.casefold():
                continue

            if comp not in self.var_dict:
                self.var_dict[comp] = tk.BooleanVar(value=comp.casefold() in self.selected)

            cb = ttk.Checkbutton(
                self.scroll_frame,
                text=label_text,
                variable=self.var_dict[comp],
                style="TCheckbutton"
            )
            cb.pack(anchor="w", padx=8, pady=3)

    def filter_list(self):
        self.populate_list()

    def select_all(self):
        for comp, var in self.var_dict.items():
            var.set(True)

    def deselect_all(self):
        for comp, var in self.var_dict.items():
            var.set(False)

    def apply(self):
        chosen = [comp for comp, var in self.var_dict.items() if var.get()]
        self.on_apply(chosen)
        self.destroy()


class ResumeEditDialog(tk.Toplevel):
    def __init__(self, parent, current_text, on_apply):
        super().__init__(parent)
        self.title("Resume Text Editor")
        self.geometry("650x500")
        self.minsize(500, 350)
        self.transient(parent)
        self.grab_set()

        self.on_apply = on_apply
        self.configure(bg=COLORS["bg"])

        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Paste or Edit Resume Text", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(top, text="This text is kept in the local session and used for TF-IDF matching and Qwen3 queries.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        content_frame = ttk.Frame(self, padding=12)
        content_frame.pack(fill="both", expand=True)

        self.text_widget = tk.Text(content_frame, wrap="word", font=("Segoe UI", 10), bg="#ffffff",
                                   relief="solid", borderwidth=1, padx=8, pady=8)
        scrollbar = ttk.Scrollbar(content_frame, orient="vertical", command=self.text_widget.yview)
        self.text_widget.configure(yscrollcommand=scrollbar.set)
        self.text_widget.insert("1.0", current_text)

        self.text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        bottom = ttk.Frame(self, padding=12)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Apply Resume", style="Primary.TButton", command=self.apply).pack(side="right", padx=(6, 0))
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(bottom, text="Clear Text", command=lambda: self.text_widget.delete("1.0", "end")).pack(side="left")

    def apply(self):
        text = self.text_widget.get("1.0", "end").strip()
        self.on_apply(text)
        self.destroy()


class SavePresetDialog(tk.Toplevel):
    def __init__(self, parent, filter_data, on_save):
        super().__init__(parent)
        self.title("Save Filter Preset")
        self.geometry("400x180")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.filter_data = filter_data
        self.on_save = on_save
        self.configure(bg=COLORS["bg"])

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Preset Name:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.name_entry = ttk.Entry(frame, font=("Segoe UI", 10))
        self.name_entry.pack(fill="x", pady=(6, 12))
        self.name_entry.insert(0, "My Filter Preset")
        self.name_entry.focus_set()

        btn_box = ttk.Frame(frame)
        btn_box.pack(fill="x", side="bottom")
        ttk.Button(btn_box, text="Save Preset", style="Primary.TButton", command=self.save).pack(side="right", padx=(6, 0))
        ttk.Button(btn_box, text="Cancel", command=self.destroy).pack(side="right")

    def save(self):
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("Warning", "Please enter a preset name.", parent=self)
            return
        self.on_save(name, json.dumps(self.filter_data, ensure_ascii=False))
        self.destroy()


class PresetsDialog(tk.Toplevel):
    def __init__(self, parent, presets, on_load, on_delete):
        super().__init__(parent)
        self.title("Saved Filter Presets")
        self.geometry("500x380")
        self.transient(parent)
        self.grab_set()

        self.presets = presets
        self.on_load = on_load
        self.on_delete = on_delete
        self.configure(bg=COLORS["bg"])

        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Manage Saved Search Presets", font=("Segoe UI", 11, "bold")).pack(anchor="w")

        table_frame = ttk.Frame(self, padding=12)
        table_frame.pack(fill="both", expand=True)

        cols = ("Name", "Created")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("Name", text="Preset Name")
        self.tree.heading("Created", text="Date Created")
        self.tree.column("Name", width=280)
        self.tree.column("Created", width=140)

        sb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.refresh_table()

        btn_box = ttk.Frame(self, padding=12)
        btn_box.pack(fill="x")
        ttk.Button(btn_box, text="Apply Selected Preset", style="Primary.TButton", command=self.load_selected).pack(side="left", padx=(0, 6))
        ttk.Button(btn_box, text="Delete Preset", command=self.delete_selected).pack(side="left")
        ttk.Button(btn_box, text="Close", command=self.destroy).pack(side="right")

    def refresh_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for p in self.presets:
            self.tree.insert("", "end", iid=str(p["id"]), values=(p["name"], p["created_at"][:19]))

    def load_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Select Preset", "Please choose a preset from the list.", parent=self)
            return
        preset_id = int(sel[0])
        match = next((p for p in self.presets if p["id"] == preset_id), None)
        if match:
            self.on_load(match)
            self.destroy()

    def delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        preset_id = int(sel[0])
        match = next((p for p in self.presets if p["id"] == preset_id), None)
        if match:
            if messagebox.askyesno("Confirm Delete", f"Delete preset '{match['name']}'?", parent=self):
                self.on_delete(match["name"])
                self.presets = [p for p in self.presets if p["id"] != preset_id]
                self.refresh_table()


class JobDetailDialog(tk.Toplevel):
    def __init__(self, parent, job, on_status_change, on_favorite_toggle, on_note_save, on_ai_explain):
        super().__init__(parent)
        self.title(f"{job.get('title', 'Job Details')} — {job.get('company', '')}")
        self.geometry("780x680")
        self.minsize(600, 500)
        self.transient(parent)

        self.job = job
        self.on_status_change = on_status_change
        self.on_favorite_toggle = on_favorite_toggle
        self.on_note_save = on_note_save
        self.on_ai_explain = on_ai_explain
        self.configure(bg=COLORS["bg"])

        # Main scrollable canvas
        main_canvas = tk.Canvas(self, bg=COLORS["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=main_canvas.yview)
        content = ttk.Frame(main_canvas, padding=16)

        content.bind("<Configure>", lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all")))
        canvas_win = main_canvas.create_window((0, 0), window=content, anchor="nw")
        main_canvas.bind("<Configure>", lambda e: main_canvas.itemconfig(canvas_win, width=e.width))
        main_canvas.configure(yscrollcommand=scrollbar.set)

        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Header Section
        head_box = ttk.Frame(content)
        head_box.pack(fill="x", pady=(0, 10))

        title_lbl = ttk.Label(head_box, text=job.get("title") or "Untitled role", font=("Segoe UI", 15, "bold"))
        title_lbl.pack(anchor="w")

        comp_loc = f"{job.get('company') or 'Unknown company'} · {job.get('location') or 'Location not specified'}"
        ttk.Label(head_box, text=comp_loc, font=("Segoe UI", 11, "bold"), foreground=COLORS["primary"]).pack(anchor="w", pady=(2, 4))

        plat_name, plat_type, plat_icon = platform_badge_info(job)
        plat_lbl = ttk.Label(head_box, text=f"{plat_icon} Platform: {plat_name} ({plat_type})", style="PlatformPill.TLabel")
        plat_lbl.pack(anchor="w", pady=(2, 4))

        meta1 = f"{relative_date(job.get('posted_at'))} · Source: {job.get('source') or 'Source unknown'}"
        ttk.Label(head_box, text=meta1, style="Muted.TLabel").pack(anchor="w")

        meta2 = f"Experience: {inferred_exp(job)}  |  Job Type: {inferred_type(job)}  |  Work Mode: {inferred_mode(job)}  |  Salary: {safe_salary(job)}"
        ttk.Label(head_box, text=meta2, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(3, 0))

        if job.get("application_deadline"):
            ttk.Label(head_box, text=f"Application Deadline: {job['application_deadline']}", foreground=COLORS["warning"]).pack(anchor="w", pady=(2, 0))

        # Match Score & Skills Card
        match_frame = ttk.LabelFrame(content, text="Resume Match Analysis", padding=10)
        match_frame.pack(fill="x", pady=8)

        score = job.get("match_score")
        if score is not None:
            score_text = f"🎯 Match Score: {score}%"
            score_color = COLORS["success"] if score >= 60 else (COLORS["warning"] if score >= 35 else COLORS["text_muted"])
            ttk.Label(match_frame, text=score_text, font=("Segoe UI", 12, "bold"), foreground=score_color).pack(anchor="w")
        else:
            ttk.Label(match_frame, text="Upload or paste resume in the main tab to calculate match score.", style="Muted.TLabel").pack(anchor="w")

        if job.get("matched_skills"):
            ttk.Label(match_frame, text=f"✅ Matched Skills: {', '.join(job['matched_skills'])}",
                      font=("Segoe UI", 9, "bold"), foreground=COLORS["success"]).pack(anchor="w", pady=(4, 2))
        if job.get("missing_skills"):
            ttk.Label(match_frame, text=f"🔍 Skills Mentioned in Posting: {', '.join(job['missing_skills'])}",
                      font=("Segoe UI", 9), foreground=COLORS["purple"]).pack(anchor="w", pady=(2, 0))

        # Application Status & Actions
        action_bar = ttk.LabelFrame(content, text="Status & Quick Actions", padding=10)
        action_bar.pack(fill="x", pady=8)

        r1 = ttk.Frame(action_bar)
        r1.pack(fill="x", pady=4)

        ttk.Label(r1, text="Status:").pack(side="left", padx=(0, 6))
        statuses = ["New", "Interested", "Saved", "Applied", "Interview", "Offer", "Rejected"]
        curr_status = job.get("status") or "New"
        self.status_var = tk.StringVar(value=curr_status)
        status_cb = ttk.Combobox(r1, textvariable=self.status_var, values=statuses, state="readonly", width=14)
        status_cb.pack(side="left", padx=(0, 15))
        status_cb.bind("<<ComboboxSelected>>", self.on_status_selected)

        # Favorite Toggle
        self.fav_var = tk.BooleanVar(value=bool(job.get("is_favorite") or 0))
        fav_btn = ttk.Button(r1, text="★ Favorited" if self.fav_var.get() else "☆ Add Favorite",
                             command=self.toggle_fav)
        fav_btn.pack(side="left", padx=(0, 15))
        self.fav_btn = fav_btn

        # Open in Browser
        if job.get("job_url"):
            open_btn = ttk.Button(r1, text=f"Open on {plat_name} ↗", style="Primary.TButton",
                                  command=lambda: webbrowser.open(job["job_url"]))
            open_btn.pack(side="left")

        # Notes Row
        r2 = ttk.Frame(action_bar)
        r2.pack(fill="x", pady=(8, 0))
        ttk.Label(r2, text="Notes:").pack(side="left", padx=(0, 6))
        self.note_var = tk.StringVar(value=job.get("notes") or "")
        note_entry = ttk.Entry(r2, textvariable=self.note_var)
        note_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(r2, text="Save Note", command=self.save_note).pack(side="left")

        # Local AI Explanation
        ai_frame = ttk.LabelFrame(content, text="Local AI Insights (Qwen3)", padding=10)
        ai_frame.pack(fill="x", pady=8)

        ai_btn = ttk.Button(ai_frame, text="🤖 Explain This Match with Local AI", command=self.run_ai)
        ai_btn.pack(anchor="w", pady=(0, 6))
        self.ai_btn = ai_btn

        self.ai_text = tk.Text(ai_frame, height=5, wrap="word", font=("Segoe UI", 9), relief="solid",
                               borderwidth=1, bg="#ffffff", padx=6, pady=6)
        self.ai_text.pack(fill="x")
        self.ai_text.insert("1.0", "Click 'Explain This Match with Local AI' to generate grounded insights.")
        self.ai_text.configure(state="disabled")

        # Description
        desc_frame = ttk.LabelFrame(content, text="Full Job Description", padding=10)
        desc_frame.pack(fill="both", expand=True, pady=8)

        desc_text = tk.Text(desc_frame, height=12, wrap="word", font=("Segoe UI", 9), relief="solid",
                            borderwidth=1, bg="#ffffff", padx=8, pady=8)
        desc_sb = ttk.Scrollbar(desc_frame, orient="vertical", command=desc_text.yview)
        desc_text.configure(yscrollcommand=desc_sb.set)

        desc_text.insert("1.0", job.get("description") or "No job description text provided.")
        desc_text.configure(state="disabled")

        desc_text.pack(side="left", fill="both", expand=True)
        desc_sb.pack(side="right", fill="y")

    def on_status_selected(self, event=None):
        new_val = self.status_var.get()
        self.on_status_change(self.job["id"], new_val)
        self.job["status"] = new_val

    def toggle_fav(self):
        new_fav = not self.fav_var.get()
        self.fav_var.set(new_fav)
        self.on_favorite_toggle(self.job["id"], 1 if new_fav else 0)
        self.job["is_favorite"] = 1 if new_fav else 0
        self.fav_btn.configure(text="★ Favorited" if new_fav else "☆ Add Favorite")

    def save_note(self):
        note = self.note_var.get().strip()
        self.on_note_save(self.job["id"], note)
        self.job["notes"] = note
        messagebox.showinfo("Saved", "Note updated successfully.", parent=self)

    def run_ai(self):
        self.ai_btn.configure(state="disabled", text="Generating AI explanation…")
        self.ai_text.configure(state="normal")
        self.ai_text.delete("1.0", "end")
        self.ai_text.insert("1.0", "Consulting local Qwen3 model via LM Studio…")
        self.ai_text.configure(state="disabled")

        def callback(result):
            if self.winfo_exists():
                self.ai_text.configure(state="normal")
                self.ai_text.delete("1.0", "end")
                self.ai_text.insert("1.0", result)
                self.ai_text.configure(state="disabled")
                self.ai_btn.configure(state="normal", text="🤖 Explain This Match with Local AI")

        self.on_ai_explain(self.job, callback)


class SourceHealthDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("🩺 Scraper & ATS Source Health Monitor")
        self.geometry("860x560")
        self.minsize(700, 450)
        self.transient(parent)

        self.configure(bg=COLORS["bg"])
        self.results = []
        self.is_checking = False

        # Top Header
        top_frame = ttk.Frame(self, padding=(12, 10))
        top_frame.pack(fill="x")
        ttk.Label(top_frame, text="🩺 ATS Scraper & Feed Health Monitor", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(top_frame, text="Probes all configured Workday, Greenhouse, Lever, and public endpoints to detect broken scrapers, site structure changes, and rate limits.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 6))

        # Metrics bar
        self.metrics_frame = ttk.Frame(top_frame)
        self.metrics_frame.pack(fill="x", pady=4)
        self.lbl_status = ttk.Label(self.metrics_frame, text="Status: Ready", font=("Segoe UI", 9, "bold"))
        self.lbl_status.pack(side="left", padx=(0, 15))
        self.lbl_healthy = ttk.Label(self.metrics_frame, text="🟢 Healthy: -", foreground="#16a34a", font=("Segoe UI", 9, "bold"))
        self.lbl_healthy.pack(side="left", padx=(0, 10))
        self.lbl_warning = ttk.Label(self.metrics_frame, text="🟡 Warnings: -", foreground="#d97706", font=("Segoe UI", 9, "bold"))
        self.lbl_warning.pack(side="left", padx=(0, 10))
        self.lbl_broken = ttk.Label(self.metrics_frame, text="🔴 Broken: -", foreground="#dc2626", font=("Segoe UI", 9, "bold"))
        self.lbl_broken.pack(side="left")

        # Treeview Table
        tree_frame = ttk.Frame(self, padding=(12, 0))
        tree_frame.pack(fill="both", expand=True)

        cols = ("status", "kind", "name", "code", "latency", "message")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("status", text="Health")
        self.tree.heading("kind", text="Platform")
        self.tree.heading("name", text="Source / Company")
        self.tree.heading("code", text="HTTP Code")
        self.tree.heading("latency", text="Latency")
        self.tree.heading("message", text="Diagnostic Message")

        self.tree.column("status", width=85, anchor="center")
        self.tree.column("kind", width=95, anchor="center")
        self.tree.column("name", width=140)
        self.tree.column("code", width=80, anchor="center")
        self.tree.column("latency", width=75, anchor="center")
        self.tree.column("message", width=340)

        self.tree.tag_configure("broken", background="#fee2e2", foreground="#991b1b")
        self.tree.tag_configure("warning", background="#fef3c7", foreground="#92400e")
        self.tree.tag_configure("healthy", background="#ffffff", foreground="#0f172a")

        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewSelect>>", self._on_select_row)

        # Bottom Diagnosis & Recommendation Card
        diag_frame = ttk.LabelFrame(self, text="Diagnosis & Recommended Fix", padding=8)
        diag_frame.pack(fill="x", padx=12, pady=(6, 8))
        self.diag_text = tk.Text(diag_frame, height=3, wrap="word", font=("Segoe UI", 9), relief="solid", borderwidth=1, bg="#ffffff")
        self.diag_text.pack(fill="x")
        self.diag_text.insert("1.0", "Click on any source row above to see detailed diagnostics, API latency, and resolution steps.")
        self.diag_text.configure(state="disabled")

        # Action Buttons
        btn_box = ttk.Frame(self, padding=(12, 0, 12, 10))
        btn_box.pack(fill="x")
        self.btn_run = ttk.Button(btn_box, text="🔄 Run Full Health Check", style="Primary.TButton", command=self.start_health_check)
        self.btn_run.pack(side="left", padx=(0, 6))
        self.btn_copy = ttk.Button(btn_box, text="📋 Copy Markdown Report", command=self.copy_report)
        self.btn_copy.pack(side="left", padx=(0, 6))
        ttk.Button(btn_box, text="Close", command=self.destroy).pack(side="right")

        # Automatically kick off health check
        self.after(200, self.start_health_check)

    def start_health_check(self):
        if self.is_checking:
            return
        self.is_checking = True
        self.btn_run.configure(state="disabled", text="Probing endpoints…")
        self.lbl_status.configure(text="Status: Probing endpoints in parallel…")
        for item in self.tree.get_children():
            self.tree.delete(item)

        import threading
        def worker():
            from src.source_health import run_source_health_check, summarize_health_results
            try:
                results = run_source_health_check(quick=False)
                summary = summarize_health_results(results)
                if self.winfo_exists():
                    self.after(0, lambda: self._on_check_complete(results, summary))
            except Exception as e:
                if self.winfo_exists():
                    self.after(0, lambda: self._on_check_error(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_check_complete(self, results, summary):
        self.is_checking = False
        self.results = results
        self.btn_run.configure(state="normal", text="🔄 Run Full Health Check")
        self.lbl_status.configure(text=f"Status: Complete ({summary['overall_status']})")
        self.lbl_healthy.configure(text=f"🟢 Healthy: {summary['healthy_count']}")
        self.lbl_warning.configure(text=f"🟡 Warnings: {summary['warning_count']}")
        self.lbl_broken.configure(text=f"🔴 Broken: {summary['broken_count']}")

        for idx, r in enumerate(results):
            icon = "🟢 Healthy" if r["status"] == "healthy" else ("🟡 Warning" if r["status"] == "warning" else "🔴 Broken")
            code_str = str(r["status_code"]) if r["status_code"] else "-"
            lat_str = f"{r['latency_ms']}ms"
            self.tree.insert("", "end", iid=str(idx), values=(icon, r["kind"], r["name"], code_str, lat_str, r["message"]), tags=(r["status"],))

    def _on_check_error(self, err_msg):
        self.is_checking = False
        self.btn_run.configure(state="normal", text="🔄 Run Full Health Check")
        self.lbl_status.configure(text=f"Status: Error during check ({err_msg})")

    def _on_select_row(self, event):
        sel = self.tree.selection()
        if not sel or not self.results:
            return
        idx = int(sel[0])
        if idx < len(self.results):
            r = self.results[idx]
            self.diag_text.configure(state="normal")
            self.diag_text.delete("1.0", "end")
            detail = f"Endpoint: {r.get('url', '')}\nMessage: {r.get('message', '')}"
            if r.get("recommendation"):
                detail += f"\n\nRecommended Action:\n{r['recommendation']}"
            self.diag_text.insert("1.0", detail)
            self.diag_text.configure(state="disabled")

    def copy_report(self):
        if not self.results:
            messagebox.showinfo("Report Empty", "Please run a health check first.", parent=self)
            return
        from src.source_health import format_health_report
        md = format_health_report(self.results, markdown=True)
        self.clipboard_clear()
        self.clipboard_append(md)
        messagebox.showinfo("Copied", "Markdown health report copied to clipboard!", parent=self)


