import tkinter as tk
from tkinter import ttk

# Modern Color Palette
COLORS = {
    "bg": "#f8fafc",
    "card_bg": "#ffffff",
    "card_border": "#e2e8f0",
    "text": "#0f172a",
    "text_muted": "#64748b",
    "primary": "#2563eb",
    "primary_hover": "#1d4ed8",
    "success": "#16a34a",
    "success_bg": "#dcfce7",
    "warning": "#d97706",
    "warning_bg": "#fef3c7",
    "danger": "#dc2626",
    "danger_bg": "#fee2e2",
    "info": "#0284c7",
    "info_bg": "#e0f2fe",
    "purple": "#7c3aed",
    "purple_bg": "#f3e8ff",
    "star": "#eab308",
    "tree_selected": "#bfdbfe"
}

def setup_styles(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=COLORS["bg"])

    # Base TFrame
    style.configure("TFrame", background=COLORS["bg"])
    style.configure("Card.TFrame", background=COLORS["card_bg"], relief="solid", borderwidth=1)
    style.configure("Header.TFrame", background=COLORS["card_bg"], relief="solid", borderwidth=1)

    # Base TLabel
    style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 9))
    style.configure("Header.TLabel", font=("Segoe UI", 15, "bold"), foreground=COLORS["text"], background=COLORS["bg"])
    style.configure("Subheader.TLabel", font=("Segoe UI", 10, "bold"), foreground=COLORS["text"], background=COLORS["bg"])
    style.configure("Muted.TLabel", font=("Segoe UI", 9), foreground=COLORS["text_muted"], background=COLORS["bg"])
    style.configure("Card.TLabel", background=COLORS["card_bg"], foreground=COLORS["text"], font=("Segoe UI", 9))
    style.configure("CardBold.TLabel", background=COLORS["card_bg"], foreground=COLORS["text"], font=("Segoe UI", 9, "bold"))
    style.configure("CardMuted.TLabel", background=COLORS["card_bg"], foreground=COLORS["text_muted"], font=("Segoe UI", 8))

    # Metric Cards
    style.configure("MetricNum.TLabel", font=("Segoe UI", 16, "bold"), foreground=COLORS["primary"], background=COLORS["card_bg"])
    style.configure("MetricWarnNum.TLabel", font=("Segoe UI", 16, "bold"), foreground="#d97706", background=COLORS["card_bg"])
    style.configure("MetricDangerNum.TLabel", font=("Segoe UI", 16, "bold"), foreground="#dc2626", background=COLORS["card_bg"])
    style.configure("MetricSuccessNum.TLabel", font=("Segoe UI", 16, "bold"), foreground="#16a34a", background=COLORS["card_bg"])
    style.configure("MetricTitle.TLabel", font=("Segoe UI", 8), foreground=COLORS["text_muted"], background=COLORS["card_bg"])

    # Status Pills
    style.configure("StatusPillOnline.TLabel", font=("Segoe UI", 8, "bold"), foreground="#15803d",
                    background="#dcfce7", padding=[8, 3])
    style.configure("StatusPillOffline.TLabel", font=("Segoe UI", 8, "bold"), foreground="#b91c1c",
                    background="#fee2e2", padding=[8, 3])
    style.configure("StatusPillChecking.TLabel", font=("Segoe UI", 8, "bold"), foreground="#b45309",
                    background="#fef3c7", padding=[8, 3])
    style.configure("StatusPillMissed.TLabel", font=("Segoe UI", 8, "bold"), foreground="#9a3412",
                    background="#ffedd5", padding=[8, 3])
    style.configure("PlatformPill.TLabel", font=("Segoe UI", 8, "bold"), foreground="#1e40af",
                    background="#dbeafe", padding=[8, 3])

    # Notebook
    style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
    style.configure("TNotebook.Tab", background="#e2e8f0", foreground=COLORS["text"],
                    padding=[12, 6], font=("Segoe UI", 9, "bold"))
    style.map("TNotebook.Tab",
              background=[("selected", COLORS["card_bg"]), ("active", "#cbd5e1")],
              foreground=[("selected", COLORS["primary"])])

    # TButton
    style.configure("TButton", font=("Segoe UI", 9), padding=[8, 4])
    style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"), background=COLORS["primary"],
                    foreground="#ffffff", padding=[10, 5])
    style.map("Primary.TButton",
              background=[("active", COLORS["primary_hover"]), ("disabled", "#94a3b8")],
              foreground=[("active", "#ffffff"), ("disabled", "#e2e8f0")])

    style.configure("Success.TButton", font=("Segoe UI", 9, "bold"), background=COLORS["success"],
                    foreground="#ffffff", padding=[8, 4])
    style.map("Success.TButton",
              background=[("active", "#15803d")])

    style.configure("Warning.TButton", font=("Segoe UI", 9, "bold"), background=COLORS["warning"],
                    foreground="#ffffff", padding=[8, 4])
    style.map("Warning.TButton",
              background=[("active", "#b45309")])

    style.configure("Outline.TButton", font=("Segoe UI", 8, "bold"), padding=[6, 3])

    # Treeview
    style.configure("Treeview",
                    background=COLORS["card_bg"],
                    foreground=COLORS["text"],
                    fieldbackground=COLORS["card_bg"],
                    font=("Segoe UI", 9),
                    rowheight=25)
    style.configure("Treeview.Heading",
                    background="#f1f5f9",
                    foreground=COLORS["text"],
                    font=("Segoe UI", 9, "bold"),
                    padding=[6, 4])
    style.map("Treeview",
              background=[("selected", COLORS["tree_selected"])],
              foreground=[("selected", COLORS["text"])])

    # Combobox & Entry
    style.configure("TCombobox", font=("Segoe UI", 9), padding=2)
    style.configure("TEntry", font=("Segoe UI", 9), padding=2)
    style.configure("TCheckbutton", background=COLORS["bg"], font=("Segoe UI", 9))

    return style
