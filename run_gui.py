import os
import json
import re
import shutil
import sys
import time
import threading
import subprocess
import base64
import bisect
import difflib
import hashlib

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog
import httpx2

# ------------------------------------------------------------------ config --
AGENT_SCRIPT = os.environ.get("MIMO_AGENT_SCRIPT", "/Users/user/Desktop/ai-agent/agent.py")
OLLAMA_URL = "http://localhost:11434/api/chat"
VISION_MODEL = "llava"
PROJECT_SKIP_DIRS = {'.git', '.vscode', '__pycache__', 'node_modules', 'venv', '.venv',
                     'agent-env', '.idea', '.mypy_cache', '.pytest_cache', '.ruff_cache'}
MAX_TRANSCRIPT = 600
RECENT_PROJECTS_FILE = os.path.expanduser("~/.mimo_ide_projects.json")
GEOM_FILE = os.path.expanduser("~/.mimo_ide_geometry.json")
SETTINGS_FILE = os.path.expanduser("~/.mimo_ide_settings.json")

DEFAULT_SETTINGS = {
    "ollama_host": "http://127.0.0.1:11434",
    "num_ctx": 16384,
    "temperature": 0.2,
    "keep_alive": "30m",
    "auto_approve": True,
    "num_predict": -1,
}

BG = "#121212"
PANEL = "#1A1A1A"
CARD = "#242424"
ACTIVE = "#2E2E2E"
GOLD = "#F9A825"
GOLD_DIM = "#3A2E10"
TEXT = "#E8E8E8"
MUTED = "#8A8A8A"
GREEN = "#66BB6A"
RED = "#EF5350"
BLUE = "#64B5F6"

MAIN_TAB_NAMES = ("Chat", "Editor", "Terminal", "Changes", "Git")

STARTERS = (
    ("🔍  Check if this project works", "Check if this project works. Run the tests and fix any failures."),
    ("✨  Add a feature", "Add a small, useful feature to this project and verify it works."),
    ("🐛  Find and fix a bug", "Look for a real bug in this project, fix it, and prove the fix with a test."),
    ("📖  Explain this codebase", "Explain what this codebase does, its main modules, and how to run it."),
)

_agent_py_cache = {"value": None}
_agent_py_lock = threading.Lock()


def _find_agent_python():
    candidates = [os.environ.get("MIMO_AGENT_PY"), sys.executable,
                  shutil.which("python3"), shutil.which("python")]
    for cand in candidates:
        if not cand:
            continue
        try:
            r = subprocess.run([cand, "-c", "import ollama"], capture_output=True, timeout=20)
            if r.returncode == 0:
                return cand
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def get_agent_python():
    with _agent_py_lock:
        if _agent_py_cache["value"] is None:
            _agent_py_cache["value"] = _find_agent_python()
        return _agent_py_cache["value"]


def _load_geometry():
    try:
        with open(GEOM_FILE, encoding="utf-8") as f:
            g = json.load(f)
        if all(isinstance(g.get(k), int) for k in ("w", "h")):
            return g
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return None


def _save_geometry(app):
    try:
        with open(GEOM_FILE, "w", encoding="utf-8") as f:
            json.dump({"w": app.winfo_width(), "h": app.winfo_height(),
                       "x": app.winfo_x(), "y": app.winfo_y()}, f)
    except OSError:
        pass


def _load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            saved = json.load(f)
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
        return merged
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)


def _save_settings(s):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2)
    except OSError:
        pass


def _detect_ram_gb():
    try:
        r = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3)
        return int(r.stdout.strip()) / (1024 ** 3)
    except Exception:
        try:
            r = subprocess.run(["free", "-b"], capture_output=True, text=True, timeout=3)
            for line in r.stdout.splitlines():
                if line.lower().startswith("mem:"):
                    return int(line.split()[1]) / (1024 ** 3)
        except Exception:
            pass
    return None


def _project_prefs_path(root):
    # stable digest — plain hash() is randomized per process, which silently
    # broke prefs persistence across restarts (session_id, model)
    h = hashlib.sha256(os.path.abspath(root).encode("utf-8", "replace")).hexdigest()[:16]
    return os.path.expanduser(f"~/.mimo_ide_proj_{h}.json")


def _load_project_prefs(root):
    try:
        with open(_project_prefs_path(root), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _save_project_prefs(root, prefs):
    try:
        with open(_project_prefs_path(root), "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
    except OSError:
        pass


def _parse_event(line):
    """Parse one JSONL event line emitted by the engine (--events mode).
    Returns the event dict, or None when the line is not an event — so legacy
    human-readable output keeps flowing through the old classifier.
    """
    if not line or line[0] != "{":
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    if isinstance(obj, dict) and isinstance(obj.get("evt"), str):
        return obj
    return None


class Tooltip:
    """Lightweight hover tooltip for any CTk widget."""

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._tip = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._after_id = self.widget.after(500, self._show)

    def _show(self):
        if self._tip is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
            tip = ctk.CTkToplevel(self.widget)
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            tip.attributes("-topmost", True)
            lbl = ctk.CTkLabel(tip, text=self.text, fg_color="#000", text_color="#FFF",
                               corner_radius=6, padx=10, pady=5,
                               font=ctk.CTkFont(size=11))
            lbl.pack()
            self._tip = tip
        except Exception:
            self._tip = None

    def _hide(self, _event=None):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


# ------------------------------------------------------------- project tab --
class ProjectTab:
    """All state for one open project. Tabs are fully independent."""

    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.name = os.path.basename(self.root.rstrip("/")) or self.root
        self.model = "qwen3-coder:30b"
        self.session_id = None
        self.session_labels = {}
        self.transcript = []
        self.tasks_data = []
        self.files = []
        self.proc = None
        self.is_generating = False
        self.stop_requested = False
        self.pending_tasks = []
        self.attached_image = None
        self.editor_path = None
        self.editor_text = ""          # content on disk / last saved
        self.editor_buf = None          # live editor buffer (unsaved edits)
        self.editor_widget = None
        self.editor_dirty = False
        self.inline_preview = None      # ⌘K before-snapshot for diff review
        self.raw_log = []
        self.changed_files = {}
        self.git_root = None
        self.git_branch = ""
        self.git_dirty = 0
        self.git_log = []
        self.run_started = 0.0
        self.cur_phase = ""
        self.cur_step = ""
        self.cur_action = ""
        self.last_prompt_tokens = 0
        self.last_gen_tokens = 0
        self.total_prompt_tokens = 0
        self.total_gen_tokens = 0
        self.context_files = []
        # live assistant streaming (JSONL delta events from the engine)
        self.stream_buf = None
        self.stream_idx = None
        self.stream_anchor = None
        self.stream_pending = False
        self.render_seq = 0


# --------------------------------------------------------------------- app --
class MimoIDE(ctk.CTk):
    MAX_READ_CHARS = 8000

    def __init__(self):
        super().__init__()
        self.title("Mimo Agentic IDE")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        geom = _load_geometry()
        if geom:
            self.geometry(f"{geom['w']}x{geom['h']}+{geom['x']}+{geom['y']}")
        else:
            self.geometry("1480x940")
        self.minsize(1100, 700)
        self.configure(fg_color=BG)
        self.lift()
        self.focus_force()

        self.tabs = []
        self.active_index = 0
        self.settings = _load_settings()
        self.ram_gb = _detect_ram_gb()
        ctk.set_appearance_mode(self.settings.get("theme", "dark").capitalize())
        self.models_inventory = {
            "qwen3-coder:30b": "Qwen 3 Coder (30B)",
            "deepseek-r1:latest": "DeepSeek R1",
            "freebuff-mimo:latest": "FreeBuff Mimo",
            "llama3.2:latest": "Llama 3.2",
        }
        self.models_meta = {}

        self._build_ui()
        self._bind_shortcuts()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.add_project_tab(self._initial_project())
        self.refresh_available_models()
        self._status_tick()

    # ---------------------------------------------------------- helpers --
    def _initial_project(self):
        return os.getcwd()

    def active_tab(self):
        if 0 <= self.active_index < len(self.tabs):
            return self.tabs[self.active_index]
        return None

    # ------------------------------------------------------------- layout --
    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # --- project tab bar ---
        self.tab_bar = ctk.CTkFrame(self, height=46, corner_radius=0, fg_color=PANEL)
        self.tab_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        brand = ctk.CTkLabel(self.tab_bar, text="◈ MIMO", text_color=GOLD,
                             font=ctk.CTkFont(size=14, weight="bold"))
        brand.pack(side="left", padx=(14, 10))
        self.tab_bar_inner = ctk.CTkFrame(self.tab_bar, fg_color="transparent")
        self.tab_bar_inner.pack(side="left", fill="x", expand=True, pady=7)
        self.add_tab_btn = ctk.CTkButton(self.tab_bar, text="＋", width=36, height=30,
                                         fg_color=CARD, hover_color=ACTIVE, text_color=GOLD,
                                         font=ctk.CTkFont(size=16, weight="bold"),
                                         command=self._add_project_dialog)
        self.add_tab_btn.pack(side="right", padx=(4, 14), pady=7)
        Tooltip(self.add_tab_btn, "Open a project (recent list)")
        self.settings_btn = ctk.CTkButton(self.tab_bar, text="⚙", width=36, height=30,
                                          fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
                                          font=ctk.CTkFont(size=15),
                                          command=self._open_settings)
        self.settings_btn.pack(side="right", padx=(0, 4), pady=7)
        Tooltip(self.settings_btn, "Settings  (host, context, temperature, models)")
        self.models_btn = ctk.CTkButton(self.tab_bar, text="⬇", width=36, height=30,
                                        fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
                                        font=ctk.CTkFont(size=15),
                                        command=self._open_model_manager)
        self.models_btn.pack(side="right", padx=(0, 4), pady=7)
        Tooltip(self.models_btn, "Model manager  (pull, delete, sizes)")
        self.theme_btn = ctk.CTkButton(self.tab_bar, text="◐", width=36, height=30,
                                       fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
                                       font=ctk.CTkFont(size=15),
                                       command=self.toggle_theme)
        self.theme_btn.pack(side="right", padx=(0, 4), pady=7)
        Tooltip(self.theme_btn, "Toggle dark / light theme")

        # --- sidebar ---
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0, fg_color=PANEL)
        self.sidebar.grid(row=1, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(7, weight=1)
        self.sidebar.grid_rowconfigure(11, weight=2)
        self.sidebar.grid_columnconfigure(0, weight=1)

        self.project_label = ctk.CTkLabel(self.sidebar, text="PROJECT", text_color=GOLD,
                                          font=ctk.CTkFont(size=13, weight="bold"))
        self.project_label.grid(row=0, column=0, padx=18, pady=(16, 0), sticky="w")
        self.project_path_label = ctk.CTkLabel(self.sidebar, text="", text_color="#666",
                                               font=ctk.CTkFont(size=10), anchor="w")
        self.project_path_label.grid(row=0, column=0, padx=18, pady=(34, 0), sticky="w")

        ctk.CTkLabel(self.sidebar, text="◈ Brain", text_color=MUTED,
                     font=ctk.CTkFont(size=11, weight="bold")
                     ).grid(row=1, column=0, padx=18, pady=(14, 0), sticky="w")
        self.model_dropdown = ctk.CTkOptionMenu(
            self.sidebar, values=list(self.models_inventory.values()),
            command=self.change_model, fg_color=ACTIVE, button_color=GOLD,
            button_hover_color="#FFB300", text_color=TEXT, dropdown_fg_color=CARD,
            dropdown_text_color=TEXT, height=34)
        self.model_dropdown.grid(row=2, column=0, padx=14, pady=(6, 4), sticky="ew")

        ctk.CTkLabel(self.sidebar, text="◈ Sessions", text_color=MUTED,
                     font=ctk.CTkFont(size=11, weight="bold")
                     ).grid(row=3, column=0, padx=18, pady=(10, 0), sticky="w")
        row4 = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        row4.grid(row=4, column=0, padx=14, pady=(6, 4), sticky="ew")
        row4.grid_columnconfigure(0, weight=1)
        self.sessions_dropdown = ctk.CTkOptionMenu(
            row4, values=["(new chat)"], command=self.on_session_selected,
            fg_color=ACTIVE, button_color=GOLD, button_hover_color="#FFB300",
            text_color=TEXT, dropdown_fg_color=CARD, dropdown_text_color=TEXT,
            height=34, dynamic_resizing=False, width=170)
        self.sessions_dropdown.grid(row=0, column=0, sticky="ew")
        self.new_chat_btn = ctk.CTkButton(row4, text="＋", width=34, height=34,
                                          fg_color=CARD, hover_color=ACTIVE, text_color=GOLD,
                                          font=ctk.CTkFont(size=15, weight="bold"),
                                          command=self.new_chat)
        self.new_chat_btn.grid(row=0, column=1, padx=(6, 0))
        Tooltip(self.new_chat_btn, "New chat  (⌘N)")
        self.sess_ops_btn = ctk.CTkButton(row4, text="⋯", width=34, height=34,
                                          fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
                                          font=ctk.CTkFont(size=14, weight="bold"),
                                          command=self._open_session_ops)
        self.sess_ops_btn.grid(row=0, column=2, padx=(4, 0))
        Tooltip(self.sess_ops_btn, "Session options  (rename / delete / export)")

        tasks_hdr = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        tasks_hdr.grid(row=5, column=0, padx=18, pady=(12, 0), sticky="ew")
        tasks_hdr.grid_columnconfigure(0, weight=1)
        self.tasks_label = ctk.CTkLabel(tasks_hdr, text="◈ Tasks", text_color=MUTED,
                                        font=ctk.CTkFont(size=11, weight="bold"))
        self.tasks_label.grid(row=0, column=0, sticky="w")
        self.tasks_expand_btn = ctk.CTkButton(tasks_hdr, text="⤢", width=30, height=22,
                                              fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                              font=ctk.CTkFont(size=13),
                                              command=self._open_tasks_expanded)
        self.tasks_expand_btn.grid(row=0, column=1, padx=(6, 0))
        self.tasks_container = ctk.CTkScrollableFrame(self.sidebar, width=240,
                                                      fg_color=PANEL, label_text="")
        self.tasks_container.grid(row=7, column=0, padx=10, pady=(6, 4), sticky="nsew")

        files_hdr = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        files_hdr.grid(row=8, column=0, padx=18, pady=(10, 0), sticky="ew")
        files_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(files_hdr, text="◈ Files", text_color=MUTED,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, sticky="w")
        self.project_btn = ctk.CTkButton(files_hdr, text="Open…", width=64, height=22,
                                         fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                         font=ctk.CTkFont(size=11),
                                         command=self._add_project_dialog)
        self.project_btn.grid(row=0, column=1, padx=(6, 0))
        self.search_btn = ctk.CTkButton(files_hdr, text="⌕", width=30, height=22,
                                        fg_color=CARD, hover_color=ACTIVE, text_color=GOLD,
                                        font=ctk.CTkFont(size=13, weight="bold"),
                                        command=self._open_search_panel)
        self.search_btn.grid(row=0, column=2, padx=(6, 0))
        Tooltip(self.search_btn, "Search in project  (⌘⇧F)")
        self.files_filter = ctk.CTkEntry(self.sidebar, height=28, fg_color=CARD,
                                         placeholder_text="Filter files…",
                                         placeholder_text_color="#666", border_color=ACTIVE,
                                         text_color=TEXT)
        self.files_filter.grid(row=9, column=0, padx=14, pady=(6, 2), sticky="ew")
        self.files_filter.bind("<KeyRelease>", self._on_files_filter)
        self.files_container = ctk.CTkScrollableFrame(self.sidebar, width=240, fg_color=PANEL)
        self.files_container.grid(row=11, column=0, padx=10, pady=(2, 10), sticky="nsew")

        # --- main area ---
        self.main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.main.grid(row=1, column=1, sticky="nsew")
        self.main.grid_rowconfigure(0, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        self.main_tabs = ctk.CTkTabview(self.main, fg_color=BG, segmented_button_fg_color=CARD,
                                        segmented_button_selected_color=ACTIVE,
                                        segmented_button_selected_hover_color=ACTIVE,
                                        text_color=TEXT)
        self.main_tabs.grid(row=0, column=0, sticky="nsew", padx=16, pady=(12, 8))
        self.chat_tab = self.main_tabs.add("Chat")
        self.editor_tab = self.main_tabs.add("Editor")
        self.terminal_tab = self.main_tabs.add("Terminal")
        self.shell_tab = self.main_tabs.add("Shell")
        self.changes_tab = self.main_tabs.add("Changes")
        self.git_tab = self.main_tabs.add("Git")

        # Chat tab: header + display/welcome stack
        self.chat_tab.grid_columnconfigure(0, weight=1)
        self.chat_tab.grid_rowconfigure(1, weight=1)
        chat_hdr = ctk.CTkFrame(self.chat_tab, fg_color="transparent", height=28)
        chat_hdr.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        chat_hdr.grid_columnconfigure(0, weight=1)
        self.chat_ctx_label = ctk.CTkLabel(chat_hdr, text="", text_color=MUTED,
                                           font=ctk.CTkFont(size=11), anchor="w")
        self.chat_ctx_label.grid(row=0, column=0, sticky="w")
        self.model_badge = ctk.CTkLabel(chat_hdr, text="qwen3-coder:30b", text_color="#000",
                                        fg_color=GOLD, corner_radius=10, padx=10, pady=2,
                                        font=ctk.CTkFont(size=10, weight="bold"))
        self.model_badge.grid(row=0, column=1, padx=(8, 0))
        self.tools_badge = ctk.CTkLabel(chat_hdr, text="", text_color=MUTED,
                                        corner_radius=10, padx=8, pady=2,
                                        font=ctk.CTkFont(size=9, weight="bold"))
        self.tools_badge.grid(row=0, column=2, padx=(4, 0))
        self._update_tools_badge()

        self.chat_display = ctk.CTkTextbox(self.chat_tab, fg_color="#0E0E0E", text_color=TEXT,
                                           wrap="word", font=ctk.CTkFont(size=13))
        self.chat_display.grid(row=1, column=0, sticky="nsew")
        self.chat_display.configure(state="disabled")
        self._setup_chat_tags()

        self.welcome_frame = ctk.CTkFrame(self.chat_tab, fg_color="#0E0E0E", corner_radius=0)
        self.welcome_frame.grid(row=1, column=0, sticky="nsew")
        self._build_welcome()

        # Editor tab
        self.editor_tab.grid_columnconfigure(0, weight=1)
        self.editor_tab.grid_rowconfigure(1, weight=1)
        ebar = ctk.CTkFrame(self.editor_tab, fg_color="transparent")
        ebar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ebar.grid_columnconfigure(0, weight=1)
        self.editor_path_label = ctk.CTkLabel(ebar, text="No file open", text_color=MUTED,
                                              font=ctk.CTkFont(family="Menlo", size=12),
                                              anchor="w")
        self.editor_path_label.grid(row=0, column=0, sticky="w")
        self.editor_reload_btn = ctk.CTkButton(ebar, text="⟳ Reload", width=80, height=28,
                                               fg_color=CARD, text_color=TEXT,
                                               hover_color=ACTIVE, command=self.reload_editor)
        self.editor_reload_btn.grid(row=0, column=1, padx=(8, 0))
        Tooltip(self.editor_reload_btn, "Reload file from disk (discard local edits)")
        self.editor_save_btn = ctk.CTkButton(ebar, text="💾 Save", width=90, height=28,
                                             fg_color=CARD, text_color=TEXT,
                                             hover_color=ACTIVE, command=self.save_editor)
        self.editor_save_btn.grid(row=0, column=2, padx=(8, 0))
        Tooltip(self.editor_save_btn, "Save file  (⌘S)")
        editor_wrap = ctk.CTkFrame(self.editor_tab, fg_color="#0E0E0E", corner_radius=0)
        editor_wrap.grid(row=1, column=0, sticky="nsew")
        editor_wrap.grid_columnconfigure(1, weight=1)
        editor_wrap.grid_rowconfigure(0, weight=1)
        self.editor_gutter = ctk.CTkTextbox(editor_wrap, width=52, fg_color="#0A0A0A",
                                            text_color="#555", wrap="none",
                                            font=ctk.CTkFont(family="Menlo", size=13),
                                            state="disabled", activate_scrollbars=False)
        self.editor_gutter.grid(row=0, column=0, sticky="nsw")
        self.editor_box = ctk.CTkTextbox(editor_wrap, fg_color="#0E0E0E", text_color="#D4D4D4",
                                         font=ctk.CTkFont(family="Menlo", size=13),
                                         wrap="none")
        self.editor_box.grid(row=0, column=1, sticky="nsew")
        self.editor_box.bind("<KeyRelease>", self._on_editor_changed, add="+")
        self.editor_box.bind("<MouseWheel>", self._on_editor_scroll, add="+")
        self.editor_box.bind("<Button-4>", self._on_editor_scroll, add="+")
        self.editor_box.bind("<Button-5>", self._on_editor_scroll, add="+")
        self.editor_box._textbox.configure(tabs=())
        self._setup_editor_tags()

        # find/replace bar (hidden until ⌘F)
        self.find_bar = ctk.CTkFrame(self.editor_tab, fg_color=CARD, corner_radius=8)
        self.find_bar.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.find_bar.grid_columnconfigure(1, weight=1)
        self.find_bar.grid_remove()
        ctk.CTkLabel(self.find_bar, text="Find", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(10, 4), pady=6)
        self.find_entry = ctk.CTkEntry(self.find_bar, height=28, fg_color=BG, border_color=ACTIVE,
                                       text_color=TEXT)
        self.find_entry.grid(row=0, column=1, sticky="ew", pady=6)
        self.find_entry.bind("<Return>", lambda _e: self.find_next())
        ctk.CTkLabel(self.find_bar, text="Replace", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(row=1, column=0, padx=(10, 4), pady=6)
        self.replace_entry = ctk.CTkEntry(self.find_bar, height=28, fg_color=BG, border_color=ACTIVE,
                                          text_color=TEXT)
        self.replace_entry.grid(row=1, column=1, sticky="ew", pady=6)
        find_btns = ctk.CTkFrame(self.find_bar, fg_color="transparent")
        find_btns.grid(row=0, column=2, rowspan=2, padx=(8, 10), pady=6)
        ctk.CTkButton(find_btns, text="Next", width=60, height=26, fg_color=ACTIVE,
                      text_color=TEXT, command=self.find_next).pack(pady=2)
        ctk.CTkButton(find_btns, text="Replace", width=60, height=26, fg_color=ACTIVE,
                      text_color=TEXT, command=self.find_replace).pack(pady=2)
        ctk.CTkButton(find_btns, text="All", width=60, height=26, fg_color=ACTIVE,
                      text_color=TEXT, command=self.find_replace_all).pack(pady=2)
        ctk.CTkButton(find_btns, text="✕", width=60, height=26, fg_color="#4A1A1A",
                      text_color=RED, command=self._hide_find_bar).pack(pady=2)

        # goto-line bar (hidden until ⌘G)
        self.goto_bar = ctk.CTkFrame(self.editor_tab, fg_color=CARD, corner_radius=8)
        self.goto_bar.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        ctk.CTkLabel(self.goto_bar, text="Go to line", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(10, 6))
        self.goto_entry = ctk.CTkEntry(self.goto_bar, width=80, height=28, fg_color=BG,
                                       border_color=ACTIVE, text_color=TEXT)
        self.goto_entry.pack(side="left", pady=6)
        self.goto_entry.bind("<Return>", lambda _e: self.goto_line())
        self.goto_bar.grid_remove()

        # inline edit bar (⌘K) — select code, ask for a change
        self.inline_bar = ctk.CTkFrame(self.editor_tab, fg_color=CARD, corner_radius=8)
        self.inline_bar.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        self.inline_bar.grid_columnconfigure(1, weight=1)
        self.inline_bar.grid_remove()
        ctk.CTkLabel(self.inline_bar, text="⌘K", text_color=GOLD,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, padx=(10, 6), pady=6)
        self.inline_entry = ctk.CTkEntry(self.inline_bar, height=28, fg_color=BG,
                                         border_color=ACTIVE, text_color=TEXT,
                                         placeholder_text="Describe the change for the selected code…")
        self.inline_entry.grid(row=0, column=1, sticky="ew", pady=6)
        self.inline_entry.bind("<Return>", lambda _e: self._send_inline_edit())
        self.inline_entry.bind("<Escape>", lambda _e: self._hide_inline_bar())
        ctk.CTkButton(self.inline_bar, text="Run", width=60, height=26, fg_color=GOLD,
                      text_color="#000", command=self._send_inline_edit).grid(row=0, column=2, padx=(8, 10))
        ctk.CTkButton(self.inline_bar, text="✕", width=30, height=26, fg_color="#4A1A1A",
                      text_color=RED, command=self._hide_inline_bar).grid(row=0, column=3, padx=(0, 10))

        # Terminal tab
        self.terminal_tab.grid_columnconfigure(0, weight=1)
        self.terminal_tab.grid_rowconfigure(1, weight=1)
        tbar = ctk.CTkFrame(self.terminal_tab, fg_color="transparent")
        tbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tbar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tbar, text="Raw agent stream", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        self.run_tests_btn = ctk.CTkButton(tbar, text="🧪 Run tests", width=100, height=26,
                                           fg_color=CARD, hover_color=ACTIVE,
                                           text_color=TEXT, command=self.run_tests)
        self.run_tests_btn.grid(row=0, column=1, padx=(8, 0))
        Tooltip(self.run_tests_btn, "Auto-detect and run the project's test suite")
        self.terminal_clear_btn = ctk.CTkButton(tbar, text="Clear", width=70, height=26,
                                                fg_color=CARD, hover_color=ACTIVE,
                                                text_color=TEXT, command=self._clear_terminal)
        self.terminal_clear_btn.grid(row=0, column=2, padx=(8, 0))
        self.terminal_box = ctk.CTkTextbox(self.terminal_tab, fg_color="#0A0A0A",
                                           text_color="#B8B8B8",
                                           font=ctk.CTkFont(family="Menlo", size=12),
                                           wrap="char")
        self.terminal_box.grid(row=1, column=0, sticky="nsew")
        self.terminal_box.configure(state="disabled")

        # Shell tab — interactive pty terminal
        self.shell_tab.grid_columnconfigure(0, weight=1)
        self.shell_tab.grid_rowconfigure(1, weight=1)
        sbar = ctk.CTkFrame(self.shell_tab, fg_color="transparent")
        sbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        sbar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(sbar, text="Interactive shell", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        self.shell_start_btn = ctk.CTkButton(sbar, text="⏵ Start", width=80, height=26,
                                             fg_color=CARD, hover_color=ACTIVE,
                                             text_color=TEXT, command=self._shell_start)
        self.shell_start_btn.grid(row=0, column=1, padx=(8, 0))
        self.shell_kill_btn = ctk.CTkButton(sbar, text="⏹ Kill", width=70, height=26,
                                            fg_color="#4A1A1A", hover_color=RED,
                                            text_color=RED, command=self._shell_kill)
        self.shell_kill_btn.grid(row=0, column=2, padx=(6, 0))
        self.shell_clear_btn = ctk.CTkButton(sbar, text="Clear", width=70, height=26,
                                             fg_color=CARD, hover_color=ACTIVE,
                                             text_color=TEXT, command=self._shell_clear)
        self.shell_clear_btn.grid(row=0, column=3, padx=(6, 0))
        self.shell_box = ctk.CTkTextbox(self.shell_tab, fg_color="#0A0A0A",
                                        text_color="#B8B8B8",
                                        font=ctk.CTkFont(family="Menlo", size=12),
                                        wrap="char")
        self.shell_box.grid(row=1, column=0, sticky="nsew")
        self.shell_box.bind("<KeyRelease>", self._on_shell_key)
        self.shell_proc = None
        self.shell_buf = ""

        # Changes tab
        self.changes_tab.grid_columnconfigure(0, weight=1)
        self.changes_tab.grid_rowconfigure(1, weight=1)
        cbar = ctk.CTkFrame(self.changes_tab, fg_color="transparent")
        cbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        cbar.grid_columnconfigure(0, weight=1)
        self.changes_title = ctk.CTkLabel(cbar, text="Working tree", text_color=MUTED,
                                          font=ctk.CTkFont(size=11))
        self.changes_title.grid(row=0, column=0, sticky="w")
        self.changes_refresh_btn = ctk.CTkButton(cbar, text="⟳ Refresh", width=90, height=26,
                                                 fg_color=CARD, hover_color=ACTIVE,
                                                 text_color=TEXT, command=self.refresh_changes_panel)
        self.changes_refresh_btn.grid(row=0, column=1, padx=(8, 0))
        changes_split = ctk.CTkFrame(self.changes_tab, fg_color="transparent")
        changes_split.grid(row=1, column=0, sticky="nsew")
        changes_split.grid_columnconfigure(1, weight=1)
        changes_split.grid_rowconfigure(0, weight=1)
        self.changes_list = ctk.CTkScrollableFrame(changes_split, width=260, fg_color=PANEL)
        self.changes_list.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.diff_box = ctk.CTkTextbox(changes_split, fg_color="#0A0A0A", text_color="#D4D4D4",
                                       font=ctk.CTkFont(family="Menlo", size=12), wrap="none")
        self.diff_box.grid(row=0, column=1, sticky="nsew")
        self.diff_box.configure(state="disabled")

        # Git tab
        self.git_tab.grid_columnconfigure(0, weight=1)
        self.git_tab.grid_rowconfigure(3, weight=1)
        gbar = ctk.CTkFrame(self.git_tab, fg_color="transparent")
        gbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        gbar.grid_columnconfigure(0, weight=1)
        self.git_status_label = ctk.CTkLabel(gbar, text="No git repository connected",
                                             text_color=MUTED, font=ctk.CTkFont(size=12),
                                             anchor="w")
        self.git_status_label.grid(row=0, column=0, sticky="w")
        self.git_init_btn = ctk.CTkButton(gbar, text="Initialize", width=100, height=28,
                                          fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                          command=self.git_init_repo)
        self.git_init_btn.grid(row=0, column=1, padx=(8, 0))
        self.git_refresh_btn = ctk.CTkButton(gbar, text="⟳ Sync", width=80, height=28,
                                             fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                             command=self.refresh_git_panel)
        self.git_refresh_btn.grid(row=0, column=2, padx=(6, 0))
        git_actions = ctk.CTkFrame(self.git_tab, fg_color="transparent")
        git_actions.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        for text, cmd, tip in [("Stage all", self.git_stage_all, "git add -A"),
                               ("Commit all", self.git_commit_all, "git add -A && git commit"),
                               ("Pull", self.git_pull, "git pull"),
                               ("Push", self.git_push, "git push")]:
            b = ctk.CTkButton(git_actions, text=text, width=100, height=30,
                              fg_color=CARD, hover_color=ACTIVE, text_color=TEXT, command=cmd)
            b.pack(side="left", padx=(0, 6))
            Tooltip(b, tip)
        self.git_branch_var = ctk.StringVar(value="")
        self.git_branch_menu = ctk.CTkOptionMenu(git_actions, values=["(branch)"],
                                                 variable=self.git_branch_var,
                                                 command=self._on_branch_select,
                                                 fg_color=ACTIVE, button_color=GOLD,
                                                 button_hover_color="#FFB300",
                                                 text_color=TEXT, dropdown_fg_color=CARD,
                                                 dropdown_text_color=TEXT, height=30, width=140)
        self.git_branch_menu.pack(side="right", padx=(6, 0))
        self.git_commit_msg = ctk.CTkEntry(git_actions, height=30, fg_color=CARD,
                                           placeholder_text="Commit message…",
                                           placeholder_text_color=MUTED, border_color=ACTIVE,
                                           text_color=TEXT)
        self.git_commit_msg.pack(side="left", fill="x", expand=True, padx=(6, 0))
        git_log_wrap = ctk.CTkFrame(self.git_tab, fg_color="transparent")
        git_log_wrap.grid(row=3, column=0, sticky="nsew")
        git_log_wrap.grid_columnconfigure(0, weight=1)
        git_log_wrap.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(git_log_wrap, text="Recent commits", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        self.git_log_box = ctk.CTkTextbox(git_log_wrap, fg_color="#0A0A0A", text_color="#D4D4D4",
                                          font=ctk.CTkFont(family="Menlo", size=12))
        self.git_log_box.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.git_log_box.configure(state="disabled")

        # --- input area ---
        self.input_frame = ctk.CTkFrame(self.main, fg_color=BG, corner_radius=0)
        self.input_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))
        self.input_frame.grid_columnconfigure(0, weight=1)

        # live work card — in-place status while the agent runs (hidden when idle)
        self.work_card = ctk.CTkFrame(self.input_frame, fg_color=CARD, corner_radius=10)
        self.work_card.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        self.work_card.grid_columnconfigure(1, weight=1)
        self.work_card.grid_remove()
        self.work_spin = ctk.CTkLabel(self.work_card, text="⠋", text_color=GOLD,
                                      font=ctk.CTkFont(family="Menlo", size=15, weight="bold"))
        self.work_spin.grid(row=0, column=0, rowspan=2, padx=(12, 6), pady=8, sticky="n")
        self.work_phase_lbl = ctk.CTkLabel(self.work_card, text="Starting…", text_color=GOLD,
                                           font=ctk.CTkFont(size=12, weight="bold"), anchor="w")
        self.work_phase_lbl.grid(row=0, column=1, sticky="ew", pady=(8, 0))
        self.work_meta_lbl = ctk.CTkLabel(self.work_card, text="", text_color=MUTED,
                                          font=ctk.CTkFont(size=11), anchor="w")
        self.work_meta_lbl.grid(row=1, column=1, sticky="ew", pady=(0, 8))
        self.work_action_lbl = ctk.CTkLabel(self.work_card, text="", text_color="#B0B0B0",
                                            font=ctk.CTkFont(family="Menlo", size=11),
                                            anchor="w")
        self.work_action_lbl.grid(row=2, column=1, sticky="ew", pady=(0, 8))
        self.work_stop_btn = ctk.CTkButton(self.work_card, text="■ Stop", width=70, height=26,
                                           fg_color=RED, hover_color="#D32F2F", text_color="#FFF",
                                           command=self.stop_generation)
        self.work_stop_btn.grid(row=0, column=2, rowspan=3, padx=(8, 10), sticky="n")

        self.chip_frame = ctk.CTkFrame(self.input_frame, fg_color=CARD, corner_radius=8, height=30)
        self.chip_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        self.chip_frame.grid_remove()
        self.chip_label = ctk.CTkLabel(self.chip_frame, text="", text_color=TEXT,
                                       font=ctk.CTkFont(size=11))
        self.chip_label.pack(side="left", padx=(10, 4), pady=4)
        self.chip_clear_btn = ctk.CTkButton(self.chip_frame, text="✕", width=24, height=20,
                                            fg_color="transparent", hover_color="#4A1A1A",
                                            text_color=MUTED, command=self._clear_attachment)
        self.chip_clear_btn.pack(side="left", padx=(0, 8), pady=4)

        input_wrap = ctk.CTkFrame(self.input_frame, fg_color=CARD, corner_radius=10)
        input_wrap.grid(row=2, column=0, sticky="ew", padx=(0, 10))
        input_wrap.grid_columnconfigure(0, weight=1)
        self.user_input = ctk.CTkTextbox(input_wrap, height=52, fg_color="transparent",
                                         text_color=TEXT, wrap="word",
                                         font=ctk.CTkFont(size=13), corner_radius=10)
        self.user_input.grid(row=0, column=0, sticky="nsew", padx=(12, 4), pady=6)
        input_wrap.grid_rowconfigure(0, weight=1)
        self.user_input.bind("<Return>", self._on_input_return)
        self.user_input.bind("<Shift-Return>", self._on_input_shift_return)
        self.user_input.bind("<KeyRelease>", self._on_input_keyrelease, add="+")
        self.user_input.bind("<FocusIn>", self._on_input_focus_in, add="+")
        self.user_input.bind("<FocusOut>", self._on_input_focus_out, add="+")
        self.user_input._textbox.bind("<Button-1>", self._on_input_click, add="+")
        self.user_input.bind("<Command-v>", self._on_input_paste, add="+")
        input_wrap.bind("<Button-1>", lambda _e: self.user_input.focus_set())
        self.input_hint = ctk.CTkLabel(input_wrap,
                                       text="Describe a task, ask a question, or attach an image…   "
                                            "⏎ run  ·  ⇧⏎ newline",
                                       text_color="#666", font=ctk.CTkFont(size=12),
                                       anchor="w")
        self.input_hint.place(relx=0, rely=0.5, anchor="w", x=14)
        self.input_hint.lower()
        self.input_hint.bind("<Button-1>", lambda _e: self._focus_input())

        self.img_button = ctk.CTkButton(self.input_frame, text="🖼", width=48, height=48,
                                        fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                        command=self.upload_image)
        self.img_button.grid(row=2, column=1, padx=(0, 10))
        Tooltip(self.img_button, "Attach an image for the vision model  (⌘V paste)")
        self.undo_button = ctk.CTkButton(self.input_frame, text="↩", width=40, height=48,
                                         fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
                                         command=self.gui_undo)
        self.undo_button.grid(row=2, column=1, padx=(0, 64))
        Tooltip(self.undo_button, "Undo last agent file change")
        self.send_button = ctk.CTkButton(self.input_frame, text="▶  Run", width=120, height=48,
                                         fg_color=GOLD, text_color="#000", hover_color="#FFB300",
                                         font=ctk.CTkFont(weight="bold"), command=self.send_request)
        self.send_button.grid(row=2, column=2)
        Tooltip(self.send_button, "Send to agent  (⏎)")

        # --- status bar ---
        status_wrap = ctk.CTkFrame(self, height=28, corner_radius=0, fg_color=PANEL)
        status_wrap.grid(row=2, column=0, columnspan=2, sticky="ew")
        status_wrap.grid_columnconfigure(0, weight=1)
        self.status_bar = ctk.CTkLabel(status_wrap, text="○ idle", height=26, anchor="w",
                                       fg_color="transparent", text_color=MUTED,
                                       font=ctk.CTkFont(size=11), padx=14)
        self.status_bar.grid(row=0, column=0, sticky="ew")
        self.shortcut_hint = ctk.CTkLabel(status_wrap,
                                          text="⌘⏎ send · ⌘K inline edit · ⌘F find · ⌘P files · ⌘N new · esc stop",
                                          height=26, anchor="e", fg_color="transparent",
                                          text_color="#555", font=ctk.CTkFont(size=10), padx=14)
        self.shortcut_hint.grid(row=0, column=1, sticky="e")

    def _build_welcome(self):
        inner = ctk.CTkFrame(self.welcome_frame, fg_color="transparent")
        inner.place(relx=0.5, rely=0.4, anchor="center")
        ctk.CTkLabel(inner, text="◈ Mimo Agentic IDE", text_color=GOLD,
                     font=ctk.CTkFont(size=28, weight="bold")).pack(pady=(0, 6))
        ctk.CTkLabel(inner, text="Your local AI engineer — plans, codes, verifies, and reports.",
                     text_color=MUTED, font=ctk.CTkFont(size=14)).pack(pady=(0, 8))
        if self.ram_gb:
            tip = self._ram_model_tip(self.ram_gb)
            ctk.CTkLabel(inner, text=f"RAM {self.ram_gb:.0f} GB · {tip}",
                         text_color=BLUE, font=ctk.CTkFont(size=11), wraplength=480,
                         justify="center").pack(pady=(0, 14))
        ctk.CTkLabel(inner, text="Try one of these:", text_color="#666",
                     font=ctk.CTkFont(size=12)).pack(anchor="w", pady=(0, 8))
        for label, prompt in STARTERS:
            btn = ctk.CTkButton(inner, text=label, anchor="w", height=38, width=420,
                                fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                font=ctk.CTkFont(size=13),
                                command=lambda p=prompt: self._use_starter(p))
            btn.pack(fill="x", pady=3)
        ctk.CTkLabel(inner, text="Attach an image with 🖼 or ⌘V paste to ask about screenshots & designs.",
                     text_color="#555", font=ctk.CTkFont(size=11)).pack(pady=(16, 0))

    def _use_starter(self, prompt):
        self.user_input.delete("1.0", "end")
        self.user_input.insert("1.0", prompt)
        self._refresh_input_hint()
        self._grow_input()
        self.user_input.focus_set()

    def _bind_shortcuts(self):
        self.bind("<Command-n>", lambda _e: (self.new_chat(), "break")[1])
        self.bind("<Command-t>", lambda _e: (self._add_project_dialog(), "break")[1])
        self.bind("<Command-s>", lambda _e: (self.save_editor(), "break")[1])
        self.bind("<Escape>", lambda _e: (self.stop_generation(), "break")[1])
        self.bind("<Command-f>", lambda _e: (self.toggle_find_bar(), "break")[1])
        self.bind("<Command-g>", lambda _e: (self.toggle_goto_bar(), "break")[1])
        self.bind("<Command-p>", lambda _e: (self._open_fuzzy_finder(), "break")[1])
        self.bind("<Command-k>", lambda _e: (self.toggle_inline_bar(), "break")[1])
        self.bind("<Command-Shift-f>", lambda _e: (self._open_search_panel(), "break")[1])
        self.bind("<Command-Shift-F>", lambda _e: (self._open_search_panel(), "break")[1])
        for i, name in enumerate(MAIN_TAB_NAMES):
            self.bind(f"<Command-{i + 1}>",
                      lambda _e, n=name: (self.main_tabs.set(n), "break")[1])

    # ---------------------------------------------------------- tab bar --
    def render_tab_bar(self):
        for w in self.tab_bar_inner.winfo_children():
            w.destroy()
        for i, tab in enumerate(self.tabs):
            active = (i == self.active_index)
            run_dot = " ●" if tab.is_generating else ""
            btn = ctk.CTkButton(
                self.tab_bar_inner, text=f"  📁 {tab.name}{run_dot}  ", height=30,
                corner_radius=8,
                fg_color=GOLD if active else CARD,
                text_color="#000" if active else TEXT,
                hover_color="#FFB300" if active else ACTIVE,
                font=ctk.CTkFont(size=12, weight="bold" if active else "normal"),
                command=lambda idx=i: self.select_tab(idx))
            btn.pack(side="left", padx=(0, 4))
            if len(self.tabs) > 1:
                x = ctk.CTkButton(self.tab_bar_inner, text="×", width=24, height=30,
                                  corner_radius=8, fg_color=CARD, hover_color="#4A1A1A",
                                  text_color=MUTED, font=ctk.CTkFont(size=12),
                                  command=lambda idx=i: self.close_tab(idx))
                x.pack(side="left", padx=(0, 10))

    def add_project_tab(self, path):
        if not path:
            return
        path = os.path.abspath(path)
        for i, t in enumerate(self.tabs):
            if t.root == path:
                self.select_tab(i)
                return
        tab = ProjectTab(path)
        prefs = _load_project_prefs(path)
        if prefs.get("model"):
            tab.model = prefs["model"]
        if prefs.get("session_id"):
            tab.session_id = prefs["session_id"]
        self.tabs.append(tab)
        self.active_index = len(self.tabs) - 1
        self._activate_tab()
        self._scan_files(tab)
        self.refresh_sessions(tab)
        self.render_tab_bar()
        self._remember_project(path)
        # restore the saved chat + tasks for the persisted session (restart-proof)
        if tab.session_id:
            sess_path = os.path.join(tab.root, ".agent_sessions", f"{tab.session_id}.json")
            if os.path.isfile(sess_path):
                self._load_session_tasks(tab, tab.session_id)
                self._load_session_transcript(tab, tab.session_id)
            else:
                tab.session_id = None
                _save_project_prefs(tab.root, {"model": tab.model, "session_id": None})

    def _remember_project(self, path):
        recents = []
        try:
            with open(RECENT_PROJECTS_FILE, encoding="utf-8") as f:
                recents = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
        recents = [p for p in recents if p != path]
        recents.insert(0, path)
        try:
            with open(RECENT_PROJECTS_FILE, "w", encoding="utf-8") as f:
                json.dump(recents[:12], f, indent=2)
        except OSError:
            pass

    def _add_project_dialog(self):
        recents = []
        try:
            with open(RECENT_PROJECTS_FILE, encoding="utf-8") as f:
                recents = [p for p in json.load(f) if os.path.isdir(p)][:8]
        except (OSError, json.JSONDecodeError):
            pass
        win = ctk.CTkToplevel(self)
        win.title("Open project")
        win.geometry("560x470")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()
        ctk.CTkLabel(win, text="Recent projects", text_color=GOLD,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=18, pady=(16, 6))
        box = ctk.CTkScrollableFrame(win, fg_color=PANEL)
        box.pack(fill="both", expand=True, padx=14, pady=4)
        for p in recents:
            btn = ctk.CTkButton(box, text=p, anchor="w", height=34, fg_color="transparent",
                                hover_color=ACTIVE, text_color=TEXT,
                                font=ctk.CTkFont(size=12),
                                command=lambda path=p: (win.destroy(), self.add_project_tab(path)))
            btn.pack(fill="x", padx=4, pady=2)
        if not recents:
            ctk.CTkLabel(box, text="No recent projects yet", text_color="#666",
                         font=ctk.CTkFont(size=12)).pack(pady=20)
        ctk.CTkButton(win, text="📁 Browse…", height=34, fg_color=CARD, hover_color=ACTIVE,
                      text_color=TEXT,
                      command=lambda: (win.destroy(), self._browse_folder())).pack(
            fill="x", padx=14, pady=(8, 16))

    def _browse_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.add_project_tab(path)

    # ------------------------------------------------------ fuzzy finder --
    def _open_fuzzy_finder(self):
        tab = self.active_tab()
        if not tab:
            return
        win = ctk.CTkToplevel(self)
        win.title("Go to file")
        win.geometry("620x480")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()
        entry = ctk.CTkEntry(win, height=36, fg_color=CARD, border_color=GOLD,
                             text_color=TEXT, placeholder_text="Type to search files…",
                             font=ctk.CTkFont(size=14))
        entry.pack(fill="x", padx=14, pady=(14, 6))
        box = ctk.CTkScrollableFrame(win, fg_color=PANEL)
        box.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        files = tab.files or []

        def render(query=""):
            for w in box.winfo_children():
                w.destroy()
            q = query.lower().strip()
            if q:
                scored = []
                for f in files:
                    fl = f.lower()
                    if q in fl:
                        scored.append((fl.index(q), len(f), f))
                scored.sort()
                matches = [f for _, _, f in scored[:40]]
            else:
                matches = files[:40]
            if not matches:
                ctk.CTkLabel(box, text="No matches", text_color="#666",
                             font=ctk.CTkFont(size=12)).pack(pady=20)
                return
            for f in matches:
                btn = ctk.CTkButton(box, text=f, anchor="w", height=30, fg_color="transparent",
                                    hover_color=ACTIVE, text_color=TEXT,
                                    font=ctk.CTkFont(family="Menlo", size=12),
                                    command=lambda path=f: (win.destroy(), self.open_file(path)))
                btn.pack(fill="x", padx=4, pady=1)

        def on_key(_e=None):
            render(entry.get())

        entry.bind("<KeyRelease>", on_key)
        render()
        entry.focus_set()

    # ---------------------------------------------------------- search --
    @staticmethod
    def _project_search(root, query, limit=200):
        """Project-wide content search → [(relpath, lineno, text), ...].
        Uses ripgrep when available (fast, respects .gitignore); falls back to
        a Python scan so search works everywhere.
        """
        if not query:
            return [], ""
        rg = shutil.which("rg")
        if rg:
            try:
                r = subprocess.run(
                    [rg, "-i", "-F", "--no-heading", "--line-number", "--color", "never",
                     "--max-count", "50", "--max-filesize", "2M", "--", query, root],
                    capture_output=True, text=True, timeout=20, errors="replace")
            except (OSError, subprocess.TimeoutExpired):
                r = None
            if r is not None and r.returncode in (0, 1):
                hits = []
                for ln in r.stdout.splitlines():
                    if not ln.strip():
                        continue
                    try:
                        fp, no, body = ln.split(":", 2)
                        rel = os.path.relpath(fp, root)
                        hits.append((rel, int(no), body.strip()[:220]))
                    except ValueError:
                        continue
                    if len(hits) >= limit:
                        break
                return hits, "rg"
        hits = []
        q = query.lower()
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in PROJECT_SKIP_DIRS]
            for name in files:
                fp = os.path.join(dirpath, name)
                try:
                    if os.path.getsize(fp) > 1_000_000:
                        continue
                    with open(fp, encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if q in line.lower():
                                hits.append((os.path.relpath(fp, root), i, line.strip()[:220]))
                                if len(hits) >= limit:
                                    return hits, "python"
                except OSError:
                    continue
        return hits, "python"

    def _open_search_panel(self):
        tab = self.active_tab()
        if not tab:
            return
        if getattr(self, "_search_win", None) is not None:
            try:
                self._search_win.destroy()
            except Exception:
                pass
        win = ctk.CTkToplevel(self)
        self._search_win = win
        win.title("Search project")
        win.geometry("760x540")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()
        entry = ctk.CTkEntry(win, height=36, fg_color=CARD, border_color=GOLD,
                             text_color=TEXT, placeholder_text="Search in all files…  (ripgrep)",
                             font=ctk.CTkFont(size=14))
        entry.pack(fill="x", padx=14, pady=(14, 6))
        status = ctk.CTkLabel(win, text="Type to search the project", text_color=MUTED,
                              font=ctk.CTkFont(size=11), anchor="w")
        status.pack(fill="x", padx=16)
        box = ctk.CTkScrollableFrame(win, fg_color=PANEL)
        box.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        state = {"after": None, "gen": 0, "hits": []}

        def jump(rel, line):
            win.destroy()
            self.open_file(rel, line=line)

        def render(hits, gen):
            if gen != state["gen"] or not win.winfo_exists():
                return
            for w in box.winfo_children():
                w.destroy()
            if not hits:
                ctk.CTkLabel(box, text="No matches", text_color="#666",
                             font=ctk.CTkFont(size=12)).pack(pady=20)
                return
            for rel, no, body in hits[:120]:
                row = ctk.CTkButton(box, text=f"{rel}:{no}   {body}", anchor="w",
                                    height=26, fg_color="transparent", hover_color=ACTIVE,
                                    text_color=TEXT, font=ctk.CTkFont(family="Menlo", size=11),
                                    command=lambda p=rel, n=no: jump(p, n))
                row.pack(fill="x", padx=4, pady=0)
            if len(hits) > 120:
                ctk.CTkLabel(box, text=f"… {len(hits) - 120} more (narrow the query)",
                             text_color="#666", font=ctk.CTkFont(size=10)).pack(pady=4)

        def run(q, gen):
            def bg():
                try:
                    hits, eng = self._project_search(tab.root, q)
                except Exception as e:
                    hits, eng = [], str(e)
                payload = lambda: (state.update(hits=hits),
                                   status.configure(text=f"{len(hits)} matches ({eng})"),
                                   render(hits, gen))
                # Tk serves cross-thread after() only while the main loop is
                # active; retry briefly so results aren't lost if the main
                # thread is momentarily between loop iterations.
                for _ in range(40):
                    try:
                        self.after(0, payload)
                        return
                    except RuntimeError:
                        time.sleep(0.05)
            threading.Thread(target=bg, daemon=True).start()

        def on_key(_e=None):
            q = entry.get().strip()
            state["gen"] += 1
            gen = state["gen"]
            if state["after"]:
                try:
                    win.after_cancel(state["after"])
                except Exception:
                    pass
            state["after"] = None
            if not q:
                status.configure(text="Type to search the project")
                for w in box.winfo_children():
                    w.destroy()
                return
            status.configure(text="Searching…")
            state["after"] = win.after(250, lambda: run(q, gen))

        def on_enter(_e=None):
            if state["hits"]:
                rel, no, _b = state["hits"][0]
                jump(rel, no)

        entry.bind("<KeyRelease>", on_key)
        entry.bind("<Return>", on_enter)
        entry.focus_set()

    # ---------------------------------------------------------- settings --
    def toggle_theme(self):
        mode = ctk.get_appearance_mode()
        new = "Light" if mode == "Dark" else "Dark"
        ctk.set_appearance_mode(new)
        self.settings["theme"] = new.lower()
        _save_settings(self.settings)
        self.append_chat(f"🎨 Theme: {new}", tag="system")

    def _open_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Settings")
        win.geometry("520x520")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()
        ctk.CTkLabel(win, text="⚙ Settings", text_color=GOLD,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=18, pady=(16, 12))
        form = ctk.CTkScrollableFrame(win, fg_color=PANEL)
        form.pack(fill="both", expand=True, padx=14, pady=4)

        s = self.settings
        entries = {}

        def add_row(label, key, tip=""):
            row = ctk.CTkFrame(form, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=6)
            ctk.CTkLabel(row, text=label, text_color=TEXT,
                         font=ctk.CTkFont(size=12), anchor="w").pack(anchor="w")
            if tip:
                ctk.CTkLabel(row, text=tip, text_color="#666",
                             font=ctk.CTkFont(size=10), anchor="w").pack(anchor="w")
            val = s.get(key, DEFAULT_SETTINGS[key])
            if isinstance(val, bool):
                w = ctk.CTkSwitch(row, text="enabled" if val else "disabled",
                                  variable=ctk.BooleanVar(value=val),
                                  fg_color=ACTIVE, progress_color=GOLD, text_color=TEXT)
                w.pack(anchor="w", pady=(2, 0))
                entries[key] = ("switch", w)
            else:
                e = ctk.CTkEntry(row, height=30, fg_color=CARD, border_color=ACTIVE,
                                 text_color=TEXT)
                e.insert(0, str(val))
                e.pack(fill="x", pady=(2, 0))
                entries[key] = ("entry", e)

        add_row("Ollama host", "ollama_host", "Where your Ollama server runs")
        add_row("Context window (num_ctx)", "num_ctx", "Larger = more memory, better long files")
        add_row("Temperature", "temperature", "Lower = more deterministic code")
        add_row("Keep-alive", "keep_alive", "How long the model stays loaded (e.g. 30m)")
        add_row("Max output tokens", "num_predict", "-1 = unlimited")
        add_row("Auto-approve actions", "auto_approve", "Skip per-command confirmation")

        if self.ram_gb:
            ctk.CTkLabel(form, text=f"Detected RAM: {self.ram_gb:.0f} GB",
                         text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=8, pady=(8, 0))
            tip = self._ram_model_tip(self.ram_gb)
            if tip:
                ctk.CTkLabel(form, text=tip, text_color=BLUE, font=ctk.CTkFont(size=11),
                             wraplength=440, justify="left").pack(anchor="w", padx=8, pady=(2, 0))

        def save():
            for key, (kind, w) in entries.items():
                if kind == "switch":
                    s[key] = bool(w.get())
                else:
                    raw = w.get().strip()
                    old = s.get(key, DEFAULT_SETTINGS[key])
                    if isinstance(old, bool):
                        s[key] = raw.lower() in ("1", "true", "yes", "on")
                    elif isinstance(old, int):
                        try:
                            s[key] = int(raw)
                        except ValueError:
                            pass
                    elif isinstance(old, float):
                        try:
                            s[key] = float(raw)
                        except ValueError:
                            pass
                    else:
                        s[key] = raw
            _save_settings(s)
            win.destroy()
            self.append_chat("⚙ Settings saved.", tag="success")

        ctk.CTkButton(win, text="Save", height=36, fg_color=GOLD, text_color="#000",
                      hover_color="#FFB300", font=ctk.CTkFont(weight="bold"),
                      command=save).pack(fill="x", padx=14, pady=(10, 16))

    def _ram_model_tip(self, gb):
        if gb >= 64:
            return "Plenty of RAM — you can run 30B+ coder models comfortably."
        if gb >= 32:
            return "Good — 14B–30B models work well. Prefer quantized (Q4) versions."
        if gb >= 16:
            return "Try 7B–14B models (e.g. qwen2.5-coder:7b, llama3.1:8b)."
        if gb >= 8:
            return "Use small models (3B–8B). Close other apps to free memory."
        return "Very limited RAM — expect slow responses with any model."

    # ------------------------------------------------------ model manager --
    def _open_model_manager(self):
        win = ctk.CTkToplevel(self)
        win.title("Model manager")
        win.geometry("640x560")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()
        ctk.CTkLabel(win, text="⬇ Model manager", text_color=GOLD,
                     font=ctk.CTkFont(size=16, weight="bold")).pack(anchor="w", padx=18, pady=(16, 6))
        if self.ram_gb:
            ctk.CTkLabel(win, text=f"Your RAM: {self.ram_gb:.0f} GB · {self._ram_model_tip(self.ram_gb)}",
                         text_color=BLUE, font=ctk.CTkFont(size=11), wraplength=600,
                         justify="left").pack(anchor="w", padx=18, pady=(0, 8))

        pull_row = ctk.CTkFrame(win, fg_color="transparent")
        pull_row.pack(fill="x", padx=14, pady=4)
        pull_entry = ctk.CTkEntry(pull_row, height=32, fg_color=CARD, border_color=ACTIVE,
                                  text_color=TEXT, placeholder_text="model name (e.g. qwen2.5-coder:7b)")
        pull_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        pull_btn = ctk.CTkButton(pull_row, text="Pull", width=80, height=32,
                                 fg_color=GOLD, text_color="#000", hover_color="#FFB300")
        pull_btn.pack(side="left")

        status = ctk.CTkLabel(win, text="Loading installed models…", text_color=MUTED,
                              font=ctk.CTkFont(size=11))
        status.pack(anchor="w", padx=18, pady=(6, 0))
        box = ctk.CTkScrollableFrame(win, fg_color=PANEL)
        box.pack(fill="both", expand=True, padx=14, pady=6)

        def do_pull():
            name = pull_entry.get().strip()
            if not name:
                return
            pull_btn.configure(state="disabled", text="…")
            status.configure(text=f"Pulling {name} — this can take a while…", text_color=GOLD)

            def bg():
                try:
                    with httpx2.Client(timeout=10.0) as client:
                        r = client.post(f"{self.settings['ollama_host']}/api/pull",
                                        json={"name": name}, timeout=None)
                        ok = r.status_code == 200
                    self.after(0, lambda: (status.configure(
                        text=f"Pulled {name}." if ok else f"Pull failed ({r.status_code}).",
                        text_color=GREEN if ok else RED),
                        pull_btn.configure(state="normal", text="Pull"),
                        self.refresh_available_models()))
                except Exception as e:
                    self.after(0, lambda e=e: (status.configure(text=f"Error: {e}", text_color=RED),
                                             pull_btn.configure(state="normal", text="Pull")))
            threading.Thread(target=bg, daemon=True).start()

        pull_btn.configure(command=do_pull)

        def load():
            try:
                with httpx2.Client(timeout=8.0) as client:
                    r = client.get(f"{self.settings['ollama_host']}/api/tags")
                    r.raise_for_status()
                    models = r.json().get("models", [])
            except Exception as e:
                self.after(0, lambda e=e: status.configure(text=f"Cannot reach Ollama: {e}", text_color=RED))
                return
            self.after(0, lambda: self._fill_model_manager(box, status, models))

        threading.Thread(target=load, daemon=True).start()

    def _fill_model_manager(self, box, status, models):
        for w in box.winfo_children():
            w.destroy()
        status.configure(text=f"{len(models)} model(s) installed", text_color=MUTED)
        self.models_meta = {m["name"]: m for m in models}
        for m in models:
            name = m.get("name", "?")
            size_gb = (m.get("size") or 0) / (1024 ** 3)
            modified = (m.get("modified_at") or "")[:10]
            row = ctk.CTkFrame(box, fg_color=CARD, corner_radius=8)
            row.pack(fill="x", padx=6, pady=4)
            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=10, pady=6)
            ctk.CTkLabel(info, text=name, text_color=TEXT, font=ctk.CTkFont(size=12, weight="bold"),
                         anchor="w").pack(anchor="w")
            meta = f"{size_gb:.1f} GB"
            if modified:
                meta += f"  ·  updated {modified}"
            if size_gb > (self.ram_gb or 999) * 0.8:
                meta += "  ·  ⚠ large for your RAM"
            ctk.CTkLabel(info, text=meta, text_color=MUTED, font=ctk.CTkFont(size=10),
                         anchor="w").pack(anchor="w")
            use_btn = ctk.CTkButton(row, text="Use", width=56, height=26,
                                    fg_color=GOLD, text_color="#000", hover_color="#FFB300",
                                    command=lambda n=name: self._use_model(n))
            use_btn.pack(side="right", padx=(6, 8))
            del_btn = ctk.CTkButton(row, text="✕", width=28, height=26,
                                    fg_color="#4A1A1A", hover_color=RED, text_color=RED,
                                    command=lambda n=name, s=status: self._delete_model(n, s))
            del_btn.pack(side="right", padx=(0, 4))

    def _use_model(self, name):
        tab = self.active_tab()
        if not tab:
            return
        tab.model = name
        if name not in self.models_inventory:
            self.models_inventory[name] = name
            self.model_dropdown.configure(values=list(self.models_inventory.values()))
        self.model_dropdown.set(self.models_inventory.get(name, name))
        self.model_badge.configure(text=name)
        self.append_chat(f"🧠 Brain for {tab.name}: {name}", tag="system")

    def _delete_model(self, name, status):
        status.configure(text=f"Deleting {name}…", text_color=GOLD)

        def bg():
            try:
                with httpx2.Client(timeout=15.0) as client:
                    r = client.delete(f"{self.settings['ollama_host']}/api/delete", json={"name": name})
                    ok = r.status_code == 200
                self.after(0, lambda: (status.configure(
                    text=f"Deleted {name}." if ok else f"Delete failed ({r.status_code}).",
                    text_color=GREEN if ok else RED),
                    self.refresh_available_models()))
            except Exception as e:
                self.after(0, lambda e=e: status.configure(text=f"Error: {e}", text_color=RED))
        threading.Thread(target=bg, daemon=True).start()

    def close_tab(self, i):
        if not (0 <= i < len(self.tabs)):
            return
        if len(self.tabs) <= 1:
            self._on_close()
            return
        tab = self.tabs[i]
        self._stop_tab(tab, silent=True)
        del self.tabs[i]
        if self.active_index >= len(self.tabs):
            self.active_index = len(self.tabs) - 1
        elif self.active_index > i:
            self.active_index -= 1
        self._activate_tab()
        self.render_tab_bar()

    def select_tab(self, i):
        if i == self.active_index or not (0 <= i < len(self.tabs)):
            return
        self._stash_editor()
        self.active_index = i
        self._activate_tab()
        self.render_tab_bar()

    def _activate_tab(self):
        tab = self.active_tab()
        if not tab:
            return
        self.project_label.configure(text=tab.name.upper()[:26])
        self.project_path_label.configure(text=tab.root)
        self.title(f"Mimo Agentic IDE — {tab.name}")
        self.chat_ctx_label.configure(text=f"{tab.name}  ·  {tab.root}")
        self.model_badge.configure(text=tab.model)
        self._update_tools_badge()
        display = self.models_inventory.get(tab.model, tab.model)
        if display in list(self.model_dropdown.cget("values")):
            self.model_dropdown.set(display)
        else:
            self.model_dropdown.configure(values=list(self.models_inventory.values()))
            self.model_dropdown.set(self.models_inventory.get(tab.model, tab.model))
        self.refresh_sessions(tab, keep_selection=True)
        self.refresh_tasks_panel()
        self._render_files(tab)
        self._restore_editor(tab)
        self._render_transcript(tab)
        self._render_terminal(tab)
        self.refresh_changes_panel(silent=True)
        self.refresh_git_panel(silent=True)
        self._sync_send_button()
        self._sync_attachment_ui()
        # keep the live work card in sync with this tab's run state
        if tab.is_generating:
            self._work_card_render(tab)
        else:
            self.work_card.grid_remove()

    # -------------------------------------------------------- chat tags --
    def _setup_chat_tags(self):
        tb = self.chat_display._textbox
        tb.tag_configure("goal", foreground="#FFE082", background=GOLD_DIM,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         lmargin1=260, lmargin2=260, rmargin=16, spacing3=10, spacing1=6)
        tb.tag_configure("assistant", foreground=TEXT, font=ctk.CTkFont(size=13),
                         lmargin1=16, lmargin2=16, rmargin=40, spacing3=8)
        tb.tag_configure("system", foreground=MUTED, font=ctk.CTkFont(size=11),
                         justify="center", spacing3=6)
        tb.tag_configure("activity", foreground=GREEN, font=ctk.CTkFont(size=12, weight="bold"),
                         lmargin1=16, spacing3=2)
        tb.tag_configure("observation", foreground="#9A9A9A",
                         font=ctk.CTkFont(family="Menlo", size=11),
                         lmargin1=16, lmargin2=16, rmargin=16, spacing3=4)
        tb.tag_configure("error", foreground=RED, font=ctk.CTkFont(family="Menlo", size=11),
                         lmargin1=16, lmargin2=16, rmargin=16, spacing3=4)
        tb.tag_configure("success", foreground=GREEN, font=ctk.CTkFont(size=13, weight="bold"),
                         lmargin1=16, spacing3=8)
        tb.tag_configure("h1", foreground=TEXT, font=ctk.CTkFont(size=17, weight="bold"),
                         lmargin1=16, spacing1=8, spacing3=4)
        tb.tag_configure("h2", foreground=TEXT, font=ctk.CTkFont(size=15, weight="bold"),
                         lmargin1=16, spacing1=6, spacing3=3)
        tb.tag_configure("hr", foreground="#444444", lmargin1=16, spacing1=2, spacing3=2)
        tb.tag_configure("bullet", foreground=TEXT, font=ctk.CTkFont(size=13),
                         lmargin1=40, lmargin2=40, spacing3=2)
        tb.tag_configure("num", foreground=GOLD, font=ctk.CTkFont(size=13, weight="bold"),
                         lmargin1=40, lmargin2=40, spacing3=2)
        tb.tag_configure("quote", foreground="#AAAAAA", font=ctk.CTkFont(size=12, slant="italic"),
                         lmargin1=48, lmargin2=48, rmargin=16, spacing3=4)
        tb.tag_configure("cmd", foreground="#C8C8C8", font=ctk.CTkFont(family="Menlo", size=11),
                         lmargin1=48, lmargin2=48, spacing3=2)
        tb.tag_configure("cmdpass", foreground=GREEN, font=ctk.CTkFont(size=12, weight="bold"),
                         lmargin1=32, lmargin2=32, spacing3=2)
        tb.tag_configure("cmdfail", foreground=RED, font=ctk.CTkFont(size=12, weight="bold"),
                         lmargin1=32, lmargin2=32, spacing3=2)
        tb.tag_configure("code", foreground="#D4D4D4", background="#0A0A0A",
                         font=ctk.CTkFont(family="Menlo", size=12),
                         lmargin1=16, lmargin2=16, rmargin=16, spacing1=4, spacing3=4)
        tb.tag_configure("bold", foreground=TEXT, font=ctk.CTkFont(size=13, weight="bold"))
        tb.tag_configure("icode", foreground="#F48FB1", font=ctk.CTkFont(family="Menlo", size=12))

    def _insert_inline(self, text, base_tag):
        tb = self.chat_display._textbox
        pattern = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")
        pos = 0
        for m in pattern.finditer(text):
            if m.start() > pos:
                tb.insert("end", text[pos:m.start()], base_tag)
            tok = m.group(0)
            if tok.startswith("**"):
                tb.insert("end", tok[2:-2], (base_tag, "bold"))
            else:
                tb.insert("end", tok[1:-1], (base_tag, "icode"))
            pos = m.end()
        if pos < len(text):
            tb.insert("end", text[pos:], base_tag)

    def _insert_markdown(self, text, base_tag):
        tb = self.chat_display._textbox
        lines = text.split("\n")
        i = 0
        code_buf = []
        in_code = False
        para = []

        def flush_para():
            nonlocal para
            if not para:
                return
            p = " ".join(para)
            para = []
            self._insert_inline(p, base_tag)
            tb.insert("end", "\n")

        def flush_code():
            nonlocal code_buf
            if not code_buf:
                return
            for n, l in enumerate(code_buf):
                tb.insert("end", f"{n + 1:3} │ {l}\n", "code")
            code_buf = []
            tb.insert("end", "\n")

        def flush_table(buf):
            if not buf:
                return
            rows = [r.strip() for r in buf if r.strip() and not re.match(r"^\|[\s\-:|]+\|$", r)]
            for r in rows:
                cells = [c.strip() for c in r.strip("|").split("|")]
                tb.insert("end", "  ".join(f"{c:<22}" for c in cells).rstrip() + "\n", "code")
            tb.insert("end", "\n")

        table_buf = []
        while i < len(lines):
            line = lines[i]
            s = line.strip()
            if s.startswith("```"):
                if in_code:
                    flush_code()
                    in_code = False
                else:
                    flush_para()
                    flush_table(table_buf)
                    table_buf = []
                    in_code = True
                i += 1
                continue
            if in_code:
                code_buf.append(line)
                i += 1
                continue
            if s.startswith("|") and s.endswith("|") and len(s) > 2:
                flush_para()
                table_buf.append(s)
                i += 1
                continue
            if table_buf:
                flush_table(table_buf)
                table_buf = []
            if s.startswith("#"):
                flush_para()
                lvl = len(s) - len(s.lstrip("#"))
                title = s.lstrip("#").strip()
                tag = "h1" if lvl <= 1 else "h2"
                tb.insert("end", title + "\n", tag)
                if lvl <= 1:
                    tb.insert("end", "─" * min(len(title), 60) + "\n", "hr")
                i += 1
                continue
            if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
                flush_para()
                tb.insert("end", "─" * 50 + "\n", "hr")
                i += 1
                continue
            m = re.match(r"^\$\s+(.+?)\s*→\s*exit\s+(\d+)", s)
            if m:
                flush_para()
                cmd, code = m.group(1), int(m.group(2))
                mark = "✓" if code == 0 else "✗"
                col = "cmdpass" if code == 0 else "cmdfail"
                tb.insert("end", f"  {mark} ", col)
                tb.insert("end", cmd, "cmd")
                tb.insert("end", "\n")
                i += 1
                continue
            if s.startswith(">"):
                flush_para()
                tb.insert("end", "  │ " + s.lstrip("> ").strip() + "\n", "quote")
                i += 1
                continue
            if s.startswith(("- [ ] ", "- [x] ")):
                flush_para()
                mark = "☐" if s[3] == " " else "☑"
                tb.insert("end", f"  {mark} ", "bullet")
                self._insert_inline(s[6:], base_tag)
                tb.insert("end", "\n")
                i += 1
                continue
            m = re.match(r"^(\s*)([-*•]|\d+\.)\s+(.*)$", line)
            if m:
                flush_para()
                indent = len(m.group(1))
                marker = m.group(2)
                content = m.group(3)
                pad = "  " * (indent // 2)
                if marker.isdigit() or marker.rstrip(".").isdigit():
                    tb.insert("end", f"{pad}{marker} ", "num")
                else:
                    tb.insert("end", f"{pad}• ", "bullet")
                self._insert_inline(content, base_tag)
                tb.insert("end", "\n")
                i += 1
                continue
            if not s:
                flush_para()
                i += 1
                continue
            para.append(s)
            i += 1
        flush_para()
        flush_table(table_buf)
        if in_code:
            flush_code()

    def _render_entry(self, tag, text):
        tb = self.chat_display._textbox
        self._show_chat()
        self.chat_display.configure(state="normal")
        try:
            if tag == "goal":
                self._insert_markdown(text, "goal")
            elif tag in ("assistant", None):
                self._insert_markdown(text, "assistant")
                tb.insert("end", "\n")
            elif tag == "system":
                tb.insert("end", text + "\n", "system")
            elif tag == "activity":
                tb.insert("end", text + "\n", "activity")
            elif tag == "observation":
                tb.insert("end", text + "\n", "observation")
            elif tag == "error":
                tb.insert("end", text + "\n", "error")
            elif tag == "success":
                tb.insert("end", text + "\n", "success")
            else:
                tb.insert("end", text + "\n", tag)
        finally:
            self.chat_display.configure(state="disabled")
        try:
            self.chat_display.see("end")
        except Exception:
            pass

    def _show_chat(self):
        try:
            self.chat_display.tkraise()
        except Exception:
            pass

    def _show_welcome(self):
        try:
            self.welcome_frame.tkraise()
        except Exception:
            pass

    def _render_transcript(self, tab):
        # bumped on every full re-render so a deferred stream finalize can
        # detect that its captured anchor is stale and skip repainting
        tab.render_seq = getattr(tab, "render_seq", 0) + 1
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        self.chat_display.configure(state="disabled")
        tb = self.chat_display._textbox
        start = max(0, len(tab.transcript) - MAX_TRANSCRIPT)
        for i in range(start, len(tab.transcript)):
            tag, text = tab.transcript[i]
            if i == tab.stream_idx:
                # capture where the live streaming entry begins so later
                # deltas can repaint just that block
                tab.stream_anchor = tb.index("end-1c")
            self._render_entry(tag, text)
        if not tab.transcript:
            self._show_welcome()

    def append_chat(self, text, tag=None, tab=None):
        tab = tab or self.active_tab()
        if tab is None:
            return
        if tab.stream_idx is not None:
            # seal the live streaming entry before appending anything after it
            self._stream_end(tab)
        tab.transcript.append((tag, text))
        if len(tab.transcript) > MAX_TRANSCRIPT + 100:
            del tab.transcript[:200]
        if tab is self.active_tab():
            if threading.current_thread() is threading.main_thread():
                self._render_entry(tag, text)
            else:
                self.after(0, self._render_entry, tag, text)

    # -------------------------------------------------------- sidebar --
    def refresh_available_models(self):
        def bg():
            try:
                host = self.settings.get("ollama_host", "http://127.0.0.1:11434")
                with httpx2.Client(timeout=5.0) as client:
                    resp = client.get(f"{host}/api/tags")
                    resp.raise_for_status()
                    models = resp.json().get("models", [])
                installed = {m["name"].split(":")[0] for m in models}
                self.models_meta = {m["name"]: m for m in models}
                keep = {k: v for k, v in self.models_inventory.items()
                        if k.split(":")[0] in installed}
                for m in models:
                    if m["name"] not in keep:
                        keep[m["name"]] = m["name"]
                if keep != self.models_inventory:
                    self.after(0, lambda: self._apply_model_inventory(keep))
            except Exception:
                pass
        threading.Thread(target=bg, daemon=True).start()

    def _apply_model_inventory(self, keep):
        self.models_inventory = keep
        tab = self.active_tab()
        values = list(keep.values())
        self.model_dropdown.configure(values=values)
        if tab:
            if tab.model not in keep:
                tab.model = next(iter(keep))
            self.model_dropdown.set(keep.get(tab.model, tab.model))
            self.model_badge.configure(text=tab.model)

    def change_model(self, display):
        tab = self.active_tab()
        if not tab:
            return
        for key, val in self.models_inventory.items():
            if val == display:
                tab.model = key
                self.model_badge.configure(text=key)
                self._update_tools_badge()
                _save_project_prefs(tab.root, {"model": key, "session_id": tab.session_id})
                self.append_chat(f"🧠 Brain for {tab.name}: {display}", tag="system")
                return

    _TOOL_CAPABLE = ("qwen", "llama3.1", "llama3.2", "mistral", "gemma2", "command-r",
                     "firefunction", "nexusrouter", "glm", "kimi", "minicpm", "phi3", "phi4")

    def _update_tools_badge(self):
        tab = self.active_tab()
        if not tab:
            return
        name = tab.model.lower()
        capable = any(k in name for k in self._TOOL_CAPABLE)
        if capable:
            self.tools_badge.configure(text="⚙ tools", fg_color="#1B3A1B", text_color=GREEN)
        else:
            self.tools_badge.configure(text="⚠ no tools", fg_color="#3A1B1B", text_color=RED)

    def refresh_sessions(self, tab, keep_selection=False):
        labels = ["(new chat)"]
        tab.session_labels = {}
        root = os.path.join(tab.root, ".agent_sessions")
        entries = []
        if os.path.isdir(root):
            for fn in os.listdir(root):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(root, fn), encoding="utf-8") as f:
                        data = json.load(f)
                    sid = data.get("id") or fn[:-5]
                    entries.append((data.get("updated") or 0, sid,
                                    data.get("name") or "untitled",
                                    len(data.get("messages") or [])))
                except (OSError, json.JSONDecodeError):
                    continue
        for _u, sid, name, nmsg in sorted(entries, reverse=True)[:20]:
            label = f"{name} · {sid[-6:]} · {nmsg}m"
            labels.append(label)
            tab.session_labels[label] = sid
        self.sessions_dropdown.configure(values=labels)
        current = None
        for label, sid in tab.session_labels.items():
            if sid == tab.session_id:
                current = label
        self.sessions_dropdown.set(current or "(new chat)")

    def on_session_selected(self, label):
        tab = self.active_tab()
        if not tab:
            return
        if label == "(new chat)":
            tab.session_id = None
            _save_project_prefs(tab.root, {"model": tab.model, "session_id": None})
            return
        sid = tab.session_labels.get(label)
        if sid:
            tab.session_id = sid
            _save_project_prefs(tab.root, {"model": tab.model, "session_id": sid})
            self._load_session_tasks(tab, sid)
            self._load_session_transcript(tab, sid)

    @staticmethod
    def _is_loop_garbage(text: str) -> bool:
        if len(text) < 200:
            return False
        for probe in (20, 28, 40):
            head = text[:probe].strip()
            if len(head.split()) >= 3 and text.count(head) >= 3:
                return True
        return False

    def _load_session_transcript(self, tab, sid):
        path = os.path.join(tab.root, ".agent_sessions", f"{sid}.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        messages = data.get("messages") or []
        entries = []
        for m in messages:
            role = m.get("role", "")
            content = (m.get("content") or "").strip()
            if not content:
                continue
            if role == "system":
                continue
            if role == "user":
                entries.append(("goal", content))
            elif role == "assistant":
                if m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        fn = tc.get("function", {})
                        entries.append(("activity", f"🔧 {fn.get('name', '?')} {str(fn.get('arguments', ''))[:120]}"))
                elif self._is_loop_garbage(content):
                    continue
                elif content:
                    entries.append(("assistant", content))
            elif role == "tool":
                short = content[:200].replace("\n", " ")
                entries.append(("observation", short))
        tab.transcript = entries[-MAX_TRANSCRIPT:]
        if tab is self.active_tab():
            self._render_transcript(tab)
            self.append_chat(f"↩ Loaded {len(entries)} messages from session {sid}", tag="system")

    def _load_session_tasks(self, tab, sid):
        try:
            with open(os.path.join(tab.root, ".agent_sessions", f"{sid}.json"),
                      encoding="utf-8") as f:
                tab.tasks_data = list(json.load(f).get("tasks") or [])
        except (OSError, json.JSONDecodeError):
            tab.tasks_data = []
        if tab is self.active_tab():
            self.after(0, self.refresh_tasks_panel)

    # ------------------------------------------------------ session ops --
    def _open_session_ops(self):
        tab = self.active_tab()
        if not tab or not tab.session_id:
            self.append_chat("Select a session first (or start a chat).", tag="system")
            return
        sid = tab.session_id
        win = ctk.CTkToplevel(self)
        win.title(f"Session {sid[-8:]}")
        win.geometry("420x260")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()
        ctk.CTkLabel(win, text=f"Session {sid}", text_color=GOLD,
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=18, pady=(16, 12))

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(row, text="Rename to", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(anchor="w")
        name_entry = ctk.CTkEntry(row, height=30, fg_color=CARD, border_color=ACTIVE,
                                  text_color=TEXT)
        name_entry.pack(fill="x", pady=(2, 0))

        def do_rename():
            new = name_entry.get().strip()
            if not new:
                return
            path = os.path.join(tab.root, ".agent_sessions", f"{sid}.json")
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                data["name"] = new
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                win.destroy()
                self.refresh_sessions(tab, keep_selection=True)
                self.append_chat(f"✎ Session renamed to '{new}'", tag="success")
            except (OSError, json.JSONDecodeError) as e:
                self.append_chat(f"❌ Rename failed: {e}", tag="error")

        ctk.CTkButton(row, text="Rename", height=30, fg_color=GOLD, text_color="#000",
                      hover_color="#FFB300", command=do_rename).pack(anchor="w", pady=(6, 0))

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(16, 0))

        def do_export():
            path = os.path.join(tab.root, ".agent_sessions", f"{sid}.json")
            dest = filedialog.asksaveasfilename(defaultextension=".json",
                                                initialfile=f"session_{sid[-8:]}.json")
            if dest:
                try:
                    shutil.copy2(path, dest)
                    self.append_chat(f"⬇ Exported session to {dest}", tag="success")
                except OSError as e:
                    self.append_chat(f"❌ Export failed: {e}", tag="error")
            win.destroy()

        def do_delete():
            path = os.path.join(tab.root, ".agent_sessions", f"{sid}.json")
            try:
                os.remove(path)
                tab.session_id = None
                _save_project_prefs(tab.root, {"model": tab.model, "session_id": None})
                win.destroy()
                self.refresh_sessions(tab)
                self.append_chat(f"🗑 Deleted session {sid[-8:]}", tag="success")
            except OSError as e:
                self.append_chat(f"❌ Delete failed: {e}", tag="error")

        ctk.CTkButton(btns, text="⬇ Export", height=32, fg_color=CARD, hover_color=ACTIVE,
                      text_color=TEXT, command=do_export).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btns, text="🗑 Delete", height=32, fg_color="#4A1A1A", hover_color=RED,
                      text_color=RED, command=do_delete).pack(side="left")

    def refresh_tasks_panel(self):
        tab = self.active_tab()
        for w in self.tasks_container.winfo_children():
            w.destroy()
        tasks = tab.tasks_data if tab else []
        done = sum(1 for t in tasks if t.get("status") == "done")
        self.tasks_label.configure(
            text=f"◈ Tasks · {done}/{len(tasks)}" if tasks else "◈ Tasks")
        if not tasks:
            ctk.CTkLabel(self.tasks_container, text="No tasks yet — the agent\ncreates these during a run",
                         text_color="#555", font=ctk.CTkFont(size=11), justify="left"
                         ).pack(anchor="w", padx=8, pady=8)
            return
        colors = {"done": GREEN, "in_progress": GOLD, "pending": MUTED}
        marks = {"done": "☑", "in_progress": "◐", "pending": "☐"}
        for t in tasks:
            status = str(t.get("status") or "pending")
            row = ctk.CTkLabel(self.tasks_container,
                               text=f"{marks.get(status, '☐')} {t.get('title', '')}",
                               anchor="w", justify="left", wraplength=210,
                               text_color=colors.get(status, MUTED),
                               font=ctk.CTkFont(size=12,
                                                weight="bold" if status == "in_progress" else "normal"))
            row.pack(anchor="w", fill="x", padx=8, pady=2)

    def _open_tasks_expanded(self):
        tab = self.active_tab()
        if not tab:
            return
        win = ctk.CTkToplevel(self)
        win.title(f"Tasks — {tab.name}")
        win.geometry("560x640")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()
        hdr = ctk.CTkFrame(win, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(14, 6))
        tasks = tab.tasks_data
        done = sum(1 for t in tasks if t.get("status") == "done")
        ctk.CTkLabel(hdr, text=f"Tasks · {done}/{len(tasks)} done",
                     text_color=GOLD, font=ctk.CTkFont(size=14, weight="bold")
                     ).pack(side="left")
        ctk.CTkButton(hdr, text="⟳", width=32, height=26, fg_color=CARD,
                      hover_color=ACTIVE, text_color=TEXT,
                      command=lambda: self._fill_tasks_window(win)).pack(side="right")
        box = ctk.CTkScrollableFrame(win, fg_color=PANEL)
        box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        win._tasks_box = box
        self._fill_tasks_window(win)

    def _fill_tasks_window(self, win):
        box = getattr(win, "_tasks_box", None)
        if box is None or not win.winfo_exists():
            return
        for w in box.winfo_children():
            w.destroy()
        tasks = (self.active_tab().tasks_data if self.active_tab() else [])
        if not tasks:
            ctk.CTkLabel(box, text="No tasks yet", text_color="#666",
                         font=ctk.CTkFont(size=13)).pack(pady=20)
            return
        colors = {"done": GREEN, "in_progress": GOLD, "pending": TEXT}
        marks = {"done": "☑", "in_progress": "◐", "pending": "☐"}
        for t in tasks:
            status = str(t.get("status") or "pending")
            card = ctk.CTkFrame(box, fg_color=CARD, corner_radius=8)
            card.pack(fill="x", padx=8, pady=4)
            lbl = ctk.CTkLabel(card,
                               text=f"{marks.get(status, '☐')}  {t.get('title', '')}",
                               anchor="w", justify="left", wraplength=480,
                               text_color=colors.get(status, MUTED),
                               font=ctk.CTkFont(size=13,
                                                weight="bold" if status == "in_progress" else "normal"))
            lbl.pack(fill="x", padx=12, pady=(10, 4))
            extra = t.get("detail") or t.get("description")
            if extra:
                ctk.CTkLabel(card, text=str(extra), anchor="w", justify="left",
                             wraplength=480, text_color=MUTED,
                             font=ctk.CTkFont(size=12)).pack(fill="x", padx=(34, 12), pady=(0, 10))
            else:
                ctk.CTkFrame(card, height=4, fg_color="transparent").pack()

    def _handle_tasks_line(self, line, tab):
        try:
            tab.tasks_data = json.loads(line[len("@@TASKS@@"):])
        except json.JSONDecodeError:
            return None
        if tab is self.active_tab():
            self.after(0, self.refresh_tasks_panel)
        done = sum(1 for t in tab.tasks_data if t.get("status") == "done")
        return f"☑ Tasks updated — {done}/{len(tab.tasks_data)} done"

    def _track_context_file(self, line, tab):
        m = re.search(r"(?:OK: (?:wrote|edited|deleted) |📖 )(\S+\.\w+)", line)
        if not m:
            return
        path = m.group(1)
        if path not in tab.context_files:
            tab.context_files.append(path)
            if len(tab.context_files) > 30:
                tab.context_files = tab.context_files[-30:]
            if tab is self.active_tab():
                self.after(0, self._update_context_bar)

    def _update_context_bar(self):
        tab = self.active_tab()
        if not tab:
            return
        files = tab.context_files
        if not files:
            self.chat_ctx_label.configure(text="")
            return
        shown = files[-5:]
        txt = " · ".join(shown)
        if len(files) > 5:
            txt = f"+{len(files) - 5} more · {txt}"
        self.chat_ctx_label.configure(text=f"ctx: {txt}")

    def new_chat(self):
        tab = self.active_tab()
        if not tab:
            return
        if tab.is_generating:
            self.append_chat("⏳ Finish or stop the current run before starting a new chat.",
                             tag="system")
            return
        tab.session_id = None
        tab.transcript.clear()
        tab.tasks_data = []
        self.refresh_tasks_panel()
        self._render_transcript(tab)
        self.sessions_dropdown.set("(new chat)")

    # -------------------------------------------------------- files/editor --
    def _scan_files(self, tab):
        found = []
        for root, dirs, files in os.walk(tab.root):
            dirs[:] = [d for d in dirs if d not in PROJECT_SKIP_DIRS and not d.startswith('.')]
            for fn in files:
                if fn.startswith('.'):
                    continue
                rel = os.path.relpath(os.path.join(root, fn), tab.root)
                found.append(rel)
        tab.files = sorted(found)
        return tab.files

    def _on_files_filter(self, _event=None):
        tab = self.active_tab()
        if tab:
            self._render_files(tab)

    def _render_files(self, tab):
        for w in self.files_container.winfo_children():
            w.destroy()
        self._scan_files(tab)
        q = self.files_filter.get().strip().lower()
        shown = [rel for rel in tab.files if q in rel.lower()] if q else tab.files
        if not shown:
            ctk.CTkLabel(self.files_container, text="No files match" if q else "No files",
                         text_color="#555", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=8, pady=8)
            return
        for rel in shown[:400]:
            btn = ctk.CTkButton(self.files_container, text=rel, anchor="w", height=24,
                                fg_color="transparent", hover_color=ACTIVE, text_color=TEXT,
                                font=ctk.CTkFont(family="Menlo", size=11),
                                command=lambda r=rel: self.open_file(r))
            btn.pack(fill="x", padx=4, pady=0)

    def _stash_editor(self):
        tab = self.active_tab()
        if tab is None:
            return
        try:
            # keep the live buffer separate from the on-disk snapshot so
            # unsaved edits survive tab switches and dirty state stays honest
            tab.editor_buf = self.editor_box.get("1.0", "end-1c")
        except Exception:
            pass

    # ---------------------------------------------------- editor syntax --
    _PY_KW = ("def class return if elif else for while try except finally with as import "
              "from pass break continue lambda yield global nonlocal assert del raise "
              "async await not in is and or None True False self").split()
    _JS_KW = ("function return if else for while try catch finally new var let const "
              "class extends super this typeof instanceof import export default "
              "async await null undefined true false").split()
    _SH_KW = ("if then else elif fi for while do done case esac function echo exit "
              "local export return set unset cd mkdir rm cp mv ls cat grep").split()

    def _setup_editor_tags(self):
        tb = self.editor_box._textbox
        tb.tag_configure("kw", foreground="#C792EA")
        tb.tag_configure("str", foreground="#C3E88D")
        tb.tag_configure("com", foreground="#546E7A", font=ctk.CTkFont(family="Menlo", size=13, slant="italic"))
        tb.tag_configure("num", foreground="#F78C6C")
        tb.tag_configure("dec", foreground="#82AAFF")
        tb.tag_configure("fn", foreground="#82AAFF")
        tb.tag_configure("op", foreground="#89DDFF")

    _SYNTAX_LANGS = {
        ".py": "python", ".pyw": "python",
        ".js": "js", ".mjs": "js", ".jsx": "js", ".ts": "js", ".tsx": "js",
        ".json": "json", ".jsonc": "json",
        ".html": "html", ".htm": "html", ".xml": "html", ".svg": "html",
        ".css": "css", ".scss": "css", ".less": "css",
        ".sh": "sh", ".bash": "sh", ".zsh": "sh",
        ".c": "c", ".h": "c", ".cpp": "c", ".hpp": "c", ".cc": "c",
        ".rs": "rs", ".go": "go", ".rb": "rb", ".sql": "sql", ".yaml": "yaml", ".yml": "yaml",
    }

    def _lang_for_path(self, path):
        if not path:
            return None
        ext = os.path.splitext(path)[1].lower()
        return self._SYNTAX_LANGS.get(ext)

    _PATTERN_CACHE = {}

    def _syntax_patterns(self, lang):
        """Compiled (tag, regex) pairs per language — built once, reused."""
        cached = self._PATTERN_CACHE.get(lang)
        if cached is not None:
            return cached
        if lang == "python":
            kw, dec = self._PY_KW, ("def", "class")
        elif lang == "js":
            kw, dec = self._JS_KW, ("function", "class")
        elif lang == "sh":
            kw, dec = self._SH_KW, ("function",)
        else:
            kw, dec = (), ()

        patterns = []
        if kw:
            kw_re = r"\b(" + "|".join(re.escape(k) for k in kw) + r")\b"
            patterns.append(("kw", re.compile(kw_re)))
        patterns.append(("str", re.compile(r"\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")))
        if lang in ("python", "js", "sh", "c", "rs", "go", "rb"):
            patterns.append(("com", re.compile(r"#[^\n]*" if lang in ("python", "sh", "rb") else r"//[^\n]*" if lang in ("js", "c", "rs", "go") else r"#[^\n]*")))
        if lang == "css":
            patterns.append(("com", re.compile(r"/\*[\s\S]*?\*/")))
            patterns.append(("dec", re.compile(r"[.#][A-Za-z_-][\w-]*")))
            patterns.append(("kw", re.compile(r"@[a-z-]+")))
        if lang == "html":
            patterns.append(("com", re.compile(r"<!--[\s\S]*?-->")))
            patterns.append(("dec", re.compile(r"</?[A-Za-z][\w-]*")))
            patterns.append(("str", re.compile(r"\"[^\"]*\"|'[^']*'")))
        if lang == "json":
            patterns.append(("str", re.compile(r"\"(?:\\.|[^\"\\])*\"")))
            patterns.append(("kw", re.compile(r"\b(?:true|false|null)\b")))
        patterns.append(("num", re.compile(r"\b\d+\.?\d*\b")))
        if lang in ("python", "js"):
            patterns.append(("fn", re.compile(r"\b[A-Za-z_]\w*(?=\()")))
        patterns.append(("op", re.compile(r"[=+\-*/%<>!&|^~?:]+")))
        self._PATTERN_CACHE[lang] = patterns
        return patterns

    def _visible_line_range(self):
        tb = self.editor_box._textbox
        total = int(tb.index("end-1c").split(".")[0])
        try:
            first, last = tb.yview()
        except Exception:
            first, last = 0.0, 1.0
        start = max(1, int(first * total) - 8)
        end = min(total, int(last * total) + 12)
        return start, end, total

    def _highlight_editor(self, lang, start_line=None, end_line=None):
        """Syntax-highlight a line range (default: the visible viewport).

        Only the viewport is repainted, so cost stays constant no matter how
        big the file is — the old implementation ran every regex over the
        whole file on each keystroke and lagged on 5k+ line files.
        """
        tb = self.editor_box._textbox
        if start_line is None:
            start_line, end_line, total = self._visible_line_range()
        else:
            total = int(tb.index("end-1c").split(".")[0])
        start_line = max(1, int(start_line))
        end_line = min(total, max(int(end_line or start_line), start_line))
        s_idx, e_idx = f"{start_line}.0", f"{end_line}.end"
        for tag in ("kw", "str", "com", "num", "dec", "fn", "op"):
            tb.tag_remove(tag, s_idx, e_idx)
        if not lang:
            return
        patterns = self._syntax_patterns(lang)
        text = tb.get(s_idx, e_idx)
        if not text:
            return
        lines = text.split("\n")
        starts = [0]
        for ln in lines[:-1]:
            starts.append(starts[-1] + len(ln) + 1)

        def to_idx(off):
            li = bisect.bisect_right(starts, off) - 1
            li = max(0, min(li, len(lines) - 1))
            return start_line + li, off - starts[li]

        for tag, pat in patterns:
            for m in pat.finditer(text):
                sl, sc = to_idx(m.start())
                el, ec = to_idx(m.end())
                tb.tag_add(tag, f"{sl}.{sc}", f"{el}.{ec}")

    def _update_gutter(self):
        tb = self.editor_box._textbox
        gtb = self.editor_gutter._textbox
        total = int(tb.index("end-1c").split(".")[0])
        self.editor_gutter.configure(state="normal")
        self.editor_gutter.delete("1.0", "end")
        self.editor_gutter.insert("1.0", "\n".join(str(i) for i in range(1, total + 1)))
        self.editor_gutter.configure(state="disabled")

    def _sync_gutter_scroll(self, _event=None):
        try:
            self.editor_gutter.yview_moveto(self.editor_box._textbox.yview()[0])
        except Exception:
            pass

    def _on_editor_scroll(self, _event=None):
        self._sync_gutter_scroll()
        # paint syntax for lines that just scrolled into view (throttled)
        self._schedule_highlight(140)

    def _schedule_highlight(self, delay=160):
        after_id = getattr(self, "_hl_after", None)
        if after_id is not None:
            try:
                self.after_cancel(after_id)
            except Exception:
                pass
        self._hl_after = self.after(delay, self._do_highlight)

    def _do_highlight(self):
        self._hl_after = None
        tab = self.active_tab()
        if tab is None:
            return
        self._update_gutter()
        self._highlight_editor(self._lang_for_path(tab.editor_path))
        self._sync_gutter_scroll()

    def _on_editor_changed(self, _event=None):
        # dirty-state stays immediate; gutter + syntax highlighting is
        # debounced so typing never blocks on regex over the file
        self._mark_editor_dirty()
        self._schedule_highlight(180)

    def reload_editor(self):
        tab = self.active_tab()
        if not tab or not tab.editor_path:
            return
        path = os.path.join(tab.root, tab.editor_path)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            self.append_chat(f"❌ Reload failed: {e}", tag="error")
            return
        tab.editor_text = content
        tab.editor_buf = content
        tab.editor_dirty = False
        self._restore_editor(tab)
        self.append_chat(f"⟳ Reloaded {tab.editor_path} from disk", tag="system")

    def _sync_editor_from_disk(self, tab):
        """If the agent edited the open file, reload it (unless user has unsaved edits)."""
        if not tab.editor_path:
            return
        path = os.path.join(tab.root, tab.editor_path)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                disk = f.read()
        except OSError:
            return
        if tab.editor_dirty:
            if tab is self.active_tab():
                self.append_chat(f"⚠️ Agent changed {tab.editor_path} on disk — you have unsaved "
                                 "edits. Use ⟳ Reload to take the agent's version, or 💾 Save to keep yours.",
                                 tag="system")
            return
        if disk != tab.editor_text:
            tab.editor_text = disk
            tab.editor_buf = disk
            if tab is self.active_tab():
                self._restore_editor(tab)
                self.append_chat(f"⟳ Editor synced — {tab.editor_path} was updated by the agent.",
                                 tag="system")

    # --------------------------------------------------- editor find/goto --
    def toggle_find_bar(self):
        self.main_tabs.set("Editor")
        if self.find_bar.winfo_ismapped():
            self._hide_find_bar()
        else:
            self.find_bar.grid()
            self.find_entry.focus_set()
            self.find_entry.select_range(0, "end")

    def _hide_find_bar(self):
        self.find_bar.grid_remove()
        tb = self.editor_box._textbox
        tb.tag_remove("findhl", "1.0", "end")
        self.editor_box.focus_set()

    def find_next(self):
        needle = self.find_entry.get()
        if not needle:
            return
        tb = self.editor_box._textbox
        tb.tag_remove("findhl", "1.0", "end")
        tb.tag_configure("findhl", background="#4A3A00", foreground="#FFE082")
        start = tb.index("insert")
        pos = tb.search(needle, start, stopindex="end", nocase=True)
        if not pos:
            pos = tb.search(needle, "1.0", stopindex="end", nocase=True)
        if pos:
            end = f"{pos}+{len(needle)}c"
            tb.tag_add("findhl", pos, end)
            tb.mark_set("insert", end)
            tb.see(pos)

    def find_replace(self):
        needle = self.find_entry.get()
        repl = self.replace_entry.get()
        if not needle:
            return
        tb = self.editor_box._textbox
        sel = tb.tag_ranges("sel")
        if sel:
            selected = tb.get(sel[0], sel[1])
            if selected.lower() == needle.lower():
                tb.delete(sel[0], sel[1])
                tb.insert(sel[0], repl)
        self.find_next()

    def find_replace_all(self):
        needle = self.find_entry.get()
        repl = self.replace_entry.get()
        if not needle:
            return
        tb = self.editor_box._textbox
        content = tb.get("1.0", "end-1c")
        count = len(re.findall(re.escape(needle), content, re.IGNORECASE))
        if count:
            new = re.sub(re.escape(needle), repl, content, flags=re.IGNORECASE)
            tb.delete("1.0", "end")
            tb.insert("1.0", new)
            self._on_editor_changed()
            self.append_chat(f"Replaced {count} occurrence(s).", tag="system")

    def toggle_goto_bar(self):
        self.main_tabs.set("Editor")
        if self.goto_bar.winfo_ismapped():
            self.goto_bar.grid_remove()
        else:
            self.goto_bar.grid()
            self.goto_entry.focus_set()
            self.goto_entry.select_range(0, "end")

    def goto_line(self):
        try:
            n = int(self.goto_entry.get().strip())
        except ValueError:
            return
        self.goto_line_number(n)
        self.goto_bar.grid_remove()
        self.editor_box.focus_set()

    def goto_line_number(self, n):
        tb = self.editor_box._textbox
        total = int(tb.index("end-1c").split(".")[0])
        n = max(1, min(int(n), total))
        tb.mark_set("insert", f"{n}.0")
        tb.see(f"{n}.0")
        try:
            tb.tag_remove("findhl", "1.0", "end")
            tb.tag_configure("findhl", background="#4A3A00", foreground="#FFE082")
            tb.tag_add("findhl", f"{n}.0", f"{n}.end")
        except Exception:
            pass
        # the viewport moved without a scroll event — repaint its syntax
        self._schedule_highlight(60)

    def toggle_inline_bar(self):
        self.main_tabs.set("Editor")
        if self.inline_bar.winfo_ismapped():
            self.inline_bar.grid_remove()
        else:
            self.inline_bar.grid()
            self.inline_entry.focus_set()
            self.inline_entry.select_range(0, "end")

    def _hide_inline_bar(self):
        self.inline_bar.grid_remove()
        self.editor_box.focus_set()

    def _send_inline_edit(self):
        instruction = self.inline_entry.get().strip()
        if not instruction:
            return
        tb = self.editor_box._textbox
        sel = tb.tag_ranges("sel")
        if sel:
            selected = tb.get(sel[0], sel[1])
        else:
            selected = tb.get("1.0", "end-1c")[:2000]
        self.inline_entry.delete(0, "end")
        tab = self.active_tab()
        if not tab or not tab.editor_path:
            # no file open — plain chat prompt, no diff review
            self._hide_inline_bar()
            prompt = (f"Instruction: {instruction}\n"
                      f"Selected code:\n```\n{selected}\n```\n"
                      f"Apply the change, then verify it compiles/runs.")
            self.main_tabs.set("Chat")
            self.user_input.delete("1.0", "end")
            self.user_input.insert("1.0", prompt)
            self._refresh_input_hint()
            self.send_request()
            return
        rel = tab.editor_path
        # snapshot the file on disk BEFORE the agent runs → diff review after
        try:
            with open(os.path.join(tab.root, rel), encoding="utf-8", errors="replace") as f:
                before = f.read()
        except OSError:
            before = None
        tab.inline_preview = {"path": rel, "before": before}
        prompt = (f"Inline edit of `{rel}` — this is the ONLY file you may change.\n\n"
                  f"Selected code:\n```\n{selected}\n```\n\n"
                  f"Instruction: {instruction}\n\n"
                  f"Apply the change to `{rel}` with edit_file (or write_file for a full "
                  f"rewrite), then verify it still parses/compiles. Do not modify any other file.")
        self._hide_inline_bar()
        self.main_tabs.set("Chat")
        self.user_input.delete("1.0", "end")
        self.user_input.insert("1.0", prompt)
        self._refresh_input_hint()
        self.send_request()

    def _review_inline_edit(self, tab):
        """After a ⌘K run: diff the target file against the pre-run snapshot
        and open an Accept/Reject review window when it changed."""
        prev = tab.inline_preview
        tab.inline_preview = None
        if not prev:
            return
        rel, before = prev["path"], prev["before"]
        path = os.path.join(tab.root, rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                after = f.read()
        except OSError:
            after = None
        if after is None and before is None:
            return
        if after == before:
            if tab is self.active_tab():
                self.append_chat(f"⌘K: no change was produced in {rel}.", tag="system", tab=tab)
            return
        self._show_diff_preview(tab, rel, before or "", after or "")

    def _show_diff_preview(self, tab, rel, before, after):
        win = ctk.CTkToplevel(self)
        win.title(f"Review change — {rel}")
        win.geometry("900x580")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()

        hdr = ctk.CTkFrame(win, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(hdr, text=f"◈ {rel}", text_color=GOLD,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")
        b_count = len(before.splitlines())
        a_count = len(after.splitlines())
        ctk.CTkLabel(hdr, text=f"{b_count} → {a_count} lines · proposed by the agent",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).pack(side="right")

        # plain Tk Text, styled to match: customtkinter's CTkTextbox floods
        # the event loop when created in a Toplevel while the main window is
        # unmapped (minimized/withdrawn), freezing the whole app. Plain Text
        # looks identical and is safe in both states (verified both ways).
        tb = tk.Text(win, wrap="none", bg="#0A0A0A", fg="#D4D4D4",
                     insertbackground="#D4D4D4", relief="flat", highlightthickness=0,
                     font=("Menlo", 12), padx=8, pady=8)
        tb.pack(fill="both", expand=True, padx=14, pady=4)
        tb.tag_configure("add", foreground="#66BB6A", background="#12261A")
        tb.tag_configure("del", foreground="#EF5350", background="#2A1414")
        tb.tag_configure("hunk", foreground="#64B5F6")
        tb.tag_configure("hdr", foreground=GOLD)

        diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(),
                                         fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm=""))
        if not diff:
            diff = ["(whitespace-only or line-ending change)"]
        for i, ln in enumerate(diff[:4000]):
            if ln.startswith("+++") or ln.startswith("---"):
                tag = "hdr"
            elif ln.startswith("@@"):
                tag = "hunk"
            elif ln.startswith("+"):
                tag = "add"
            elif ln.startswith("-"):
                tag = "del"
            else:
                tag = None
            tb.insert("end", ln + "\n", tag)
        if len(diff) > 4000:
            tb.insert("end", f"… {len(diff) - 4000} more diff lines omitted\n", "hunk")
        tb.configure(state="disabled")

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(6, 14))
        ctk.CTkLabel(btns, text="Close (✕) keeps the changes",
                     text_color="#666", font=ctk.CTkFont(size=10)).pack(side="left")

        def accept(_=None):
            win.destroy()
            self.append_chat(f"✓ Accepted — kept changes to {rel}", tag="success", tab=tab)
            self._render_files(tab)
            self.refresh_changes_panel(silent=True)
            self._sync_editor_from_disk(tab)

        def reject():
            win.destroy()
            try:
                with open(os.path.join(tab.root, rel), "w", encoding="utf-8") as f:
                    f.write(before)
            except OSError as e:
                self.append_chat(f"❌ Reject failed: {e}", tag="error", tab=tab)
                return
            tab.editor_text = before
            tab.editor_buf = before
            tab.editor_dirty = False
            if tab is self.active_tab():
                self._restore_editor(tab)
            self.append_chat(f"↩ Rejected — {rel} restored to its pre-edit state.",
                             tag="system", tab=tab)
            self._render_files(tab)
            self.refresh_changes_panel(silent=True)

        ctk.CTkButton(btns, text="✓ Accept", width=120, height=34, fg_color=GREEN,
                      hover_color="#4CAF50", text_color="#000",
                      font=ctk.CTkFont(weight="bold"), command=accept).pack(side="right", padx=(8, 0))
        ctk.CTkButton(btns, text="✕ Reject", width=120, height=34, fg_color="#4A1A1A",
                      hover_color="#5C2222", text_color=RED,
                      font=ctk.CTkFont(weight="bold"), command=reject).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", accept)

    def _restore_editor(self, tab):
        text = tab.editor_buf if tab.editor_buf is not None else (tab.editor_text or "")
        self.editor_box.delete("1.0", "end")
        self.editor_box.insert("1.0", text)
        tab.editor_dirty = bool(tab.editor_path) and text != (tab.editor_text or "")
        self._update_editor_status(tab)
        if getattr(self, "_hl_after", None):
            try:
                self.after_cancel(self._hl_after)
            except Exception:
                pass
            self._hl_after = None
        self._update_gutter()
        self._highlight_editor(self._lang_for_path(tab.editor_path))
        self._sync_gutter_scroll()

    def _update_editor_status(self, tab):
        if not tab.editor_path:
            self.editor_path_label.configure(text="No file open", text_color=MUTED)
            self.editor_save_btn.configure(fg_color=CARD, text_color=TEXT)
            return
        mark = "  ● unsaved" if tab.editor_dirty else ""
        self.editor_path_label.configure(text=f"{tab.editor_path}{mark}",
                                         text_color=GOLD if tab.editor_dirty else MUTED)
        self.editor_save_btn.configure(fg_color=GOLD if tab.editor_dirty else CARD,
                                       text_color="#000" if tab.editor_dirty else TEXT)

    def _mark_editor_dirty(self, _event=None):
        tab = self.active_tab()
        if not tab or not tab.editor_path:
            return
        try:
            current = self.editor_box.get("1.0", "end-1c")
        except Exception:
            return
        tab.editor_dirty = current != tab.editor_text
        self._update_editor_status(tab)

    def open_file(self, rel, line=None):
        tab = self.active_tab()
        if not tab:
            return
        self._stash_editor()
        path = os.path.join(tab.root, rel)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as e:
            self.append_chat(f"❌ Cannot open {rel}: {e}", tag="error")
            return
        if b"\0" in content.encode("utf-8", "replace")[:1000]:
            self.append_chat(f"binary file: {rel}", tag="system")
            return
        tab.editor_path = rel
        tab.editor_text = content
        tab.editor_buf = content
        self._restore_editor(tab)
        if line:
            self.goto_line_number(line)
        self.main_tabs.set("Editor")

    def save_editor(self):
        tab = self.active_tab()
        if not tab or not tab.editor_path:
            return
        content = self.editor_box.get("1.0", "end-1c")
        try:
            with open(os.path.join(tab.root, tab.editor_path), "w", encoding="utf-8") as f:
                f.write(content)
        except OSError as e:
            self.append_chat(f"❌ Save failed: {e}", tag="error")
            return
        tab.editor_text = content
        tab.editor_buf = content
        tab.editor_dirty = False
        self._update_editor_status(tab)
        self.append_chat(f"💾 Saved {tab.editor_path}", tag="success")
        self._render_files(tab)

    # -------------------------------------------------------- terminal --
    def append_terminal(self, line, tab=None):
        tab = tab or self.active_tab()
        if tab is None:
            return
        tab.raw_log.append(line)
        if len(tab.raw_log) > 4000:
            del tab.raw_log[:1000]
        if tab is self.active_tab():
            if threading.current_thread() is threading.main_thread():
                self._terminal_insert(line)
            else:
                self.after(0, self._terminal_insert, line)

    def _terminal_insert(self, line):
        self.terminal_box.configure(state="normal")
        self.terminal_box.insert("end", line + "\n")
        total = int(self.terminal_box.index("end-1c").split(".")[0])
        if total > 4000:
            self.terminal_box.delete("1.0", f"{total - 3000}.0")
        self.terminal_box.configure(state="disabled")
        try:
            self.terminal_box.see("end")
        except Exception:
            pass

    def _clear_terminal(self):
        tab = self.active_tab()
        if tab:
            tab.raw_log.clear()
        self.terminal_box.configure(state="normal")
        self.terminal_box.delete("1.0", "end")
        self.terminal_box.configure(state="disabled")

    def _shell_start(self):
        if self.shell_proc and self.shell_proc.poll() is None:
            return
        import pty, select
        tab = self.active_tab()
        cwd = tab.root if tab else os.getcwd()
        self.shell_proc = pty.fork()
        if self.shell_proc[0] == 0:
            os.execvp("bash", ["bash", "-i"])
        pid, fd = self.shell_proc
        os.set_blocking(fd, False)
        self.shell_box.configure(state="normal")
        self.shell_box.delete("1.0", "end")
        self.shell_box.insert("end", f"$ bash (pid {pid}) — type below, ⏎ to run\n\n")
        self.shell_box.configure(state="disabled")
        self._shell_fd = fd
        self._shell_read_loop(fd)

    def _shell_read_loop(self, fd):
        import select
        try:
            r, _, _ = select.select([fd], [], [], 0.05)
            if r:
                data = os.read(fd, 4096).decode("utf-8", errors="replace")
                self.shell_box.configure(state="normal")
                self.shell_box.insert("end", data)
                self.shell_box.see("end")
                self.shell_box.configure(state="disabled")
        except OSError:
            self._shell_kill()
            return
        if self.shell_proc and self.shell_proc[0] and self.shell_proc[0].poll() is None:
            self.after(50, lambda: self._shell_read_loop(fd))

    def _on_shell_key(self, event):
        if not self.shell_proc or self.shell_proc[0] is None:
            return
        if event.keysym in ("Shift_L", "Shift_R", "Control_L", "Control_R",
                            "Alt_L", "Alt_R", "Meta_L", "Meta_R"):
            return
        pid, fd = self.shell_proc
        ch = event.char if event.char else ""
        if event.keysym == "Return":
            ch = "\r"
        elif event.keysym == "BackSpace":
            ch = "\x7f"
        elif event.keysym == "Tab":
            ch = "\t"
        elif not ch:
            return
        try:
            os.write(fd, ch.encode())
        except OSError:
            pass

    def _shell_kill(self):
        if self.shell_proc and self.shell_proc[0]:
            try:
                os.kill(self.shell_proc[0], 9)
            except OSError:
                pass
        self.shell_proc = None

    def _shell_clear(self):
        self.shell_box.configure(state="normal")
        self.shell_box.delete("1.0", "end")
        self.shell_box.configure(state="disabled")

    def run_tests(self):
        tab = self.active_tab()
        if not tab or tab.is_generating:
            return
        root = tab.root
        cmd = None
        if os.path.isfile(os.path.join(root, "pytest.ini")) or \
           os.path.isfile(os.path.join(root, "conftest.py")) or \
           any(f.startswith("test_") and f.endswith(".py") for f in os.listdir(root)):
            cmd = "python3 -m pytest -q --tb=short"
        elif os.path.isfile(os.path.join(root, "package.json")):
            try:
                with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
                    pkg = json.load(f)
                if "test" in pkg.get("scripts", {}):
                    cmd = "npm test"
            except (OSError, json.JSONDecodeError):
                pass
        if not cmd:
            self.append_chat("No test suite detected (pytest / npm test).", tag="system")
            return
        self.append_chat(f"🧪 Running: {cmd}", tag="system")
        self.run_tests_btn.configure(state="disabled", text="… running")

        def bg():
            try:
                r = subprocess.run(cmd, shell=True, cwd=root, capture_output=True,
                                   text=True, timeout=180)
                out = (r.stdout + r.stderr).strip()
                ok = r.returncode == 0
                summary = "✅ All tests passed." if ok else f"❌ Tests failed (exit {r.returncode})."
                tail = "\n".join(out.splitlines()[-25:])
                self.after(0, lambda: (self.append_chat(summary, tag="success" if ok else "error"),
                                       self.append_chat(tail, tag="observation"),
                                       self.run_tests_btn.configure(state="normal", text="🧪 Run tests")))
            except subprocess.TimeoutExpired:
                self.after(0, lambda: (self.append_chat("❌ Tests timed out (180s).", tag="error"),
                                       self.run_tests_btn.configure(state="normal", text="🧪 Run tests")))
            except OSError as e:
                self.after(0, lambda e=e: (self.append_chat(f"❌ {e}", tag="error"),
                                         self.run_tests_btn.configure(state="normal", text="🧪 Run tests")))
        threading.Thread(target=bg, daemon=True).start()

    def _render_terminal(self, tab):
        self.terminal_box.configure(state="normal")
        self.terminal_box.delete("1.0", "end")
        if tab.raw_log:
            self.terminal_box.insert("1.0", "\n".join(tab.raw_log[-3000:]) + "\n")
        else:
            self.terminal_box.insert(
                "1.0", "— terminal idle —\nraw agent output (plans, tool calls, command results)\n"
                       "streams here while a run is active.\n")
        self.terminal_box.configure(state="disabled")
        try:
            self.terminal_box.see("end")
        except Exception:
            pass

    # -------------------------------------------------------- changes --
    def _git(self, tab, *args):
        try:
            r = subprocess.run(["git", "-C", tab.root, *args],
                               capture_output=True, text=True, timeout=30)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as e:
            return 1, str(e)

    def refresh_changes_panel(self, silent=False):
        tab = self.active_tab()
        if not tab:
            return
        for w in self.changes_list.winfo_children():
            w.destroy()
        code, out = self._git(tab, "status", "--porcelain")
        if code != 0:
            self.changes_title.configure(text="Working tree · not a git repo")
            lbl = ctk.CTkLabel(self.changes_list, text="Run 'Initialize' in the Git tab\nto track changes",
                               text_color="#555", font=ctk.CTkFont(size=12),
                               justify="left")
            lbl.pack(anchor="w", padx=8, pady=8)
            tab.changed_files = {}
            self._show_diff(None, "")
            return
        entries = [l for l in out.splitlines() if l.strip()]
        self.changes_title.configure(
            text=f"Working tree · {len(entries)} file{'s' if len(entries) != 1 else ''}"
                 if entries else "Working tree · clean")
        tab.changed_files = {}
        if not entries:
            lbl = ctk.CTkLabel(self.changes_list, text="✓ Working tree clean",
                               text_color=GREEN, font=ctk.CTkFont(size=12))
            lbl.pack(anchor="w", padx=8, pady=8)
            self._show_diff(None, "")
            return
        status_colors = {"M": GOLD, "A": GREEN, "D": RED, "??": BLUE, "R": GREEN}
        for e in entries:
            st, path = e[:2], e[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            path = path.strip('"')
            key = st.strip()[0] if st.strip() else "?"
            color = status_colors.get(key, MUTED)
            row = ctk.CTkFrame(self.changes_list, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=0)
            btn = ctk.CTkButton(row, text=f"{st.strip():2} {path}", anchor="w",
                                height=24, fg_color="transparent", hover_color=ACTIVE,
                                text_color=color, font=ctk.CTkFont(family="Menlo", size=11),
                                command=lambda p=path, s=key: self._select_change(p, s))
            btn.pack(side="left", fill="x", expand=True)
            rev = ctk.CTkButton(row, text="↩", width=24, height=22,
                                fg_color="transparent", hover_color="#4A1A1A",
                                text_color="#666", font=ctk.CTkFont(size=11),
                                command=lambda p=path: self._revert_file(p))
            rev.pack(side="right", padx=(2, 0))
            openb = ctk.CTkButton(row, text="↗", width=24, height=22,
                                  fg_color="transparent", hover_color=ACTIVE,
                                  text_color="#666", font=ctk.CTkFont(size=11),
                                  command=lambda p=path: self.open_file(p))
            openb.pack(side="right", padx=(2, 0))
            tab.changed_files[path] = key
        if not silent:
            first = next(iter(tab.changed_files))
            self._select_change(first, tab.changed_files[first])

    def _revert_file(self, path):
        tab = self.active_tab()
        if not tab:
            return
        code, out = self._git(tab, "checkout", "--", path)
        if code == 0:
            self.append_chat(f"↩ Reverted {path}", tag="system")
        else:
            self.append_chat(f"❌ Revert failed: {out.strip()[:200]}", tag="error")
        self.refresh_changes_panel(silent=True)

    def _select_change(self, path, status):
        tab = self.active_tab()
        if not tab:
            return
        if status == "A" or status == "?":
            try:
                with open(os.path.join(tab.root, path), encoding="utf-8", errors="replace") as f:
                    content = f.read()
                diff = "".join(f"+ {l}\n" for l in content.splitlines()[:400])
            except OSError as e:
                diff = f"Cannot read {path}: {e}"
        else:
            _code, diff = self._git(tab, "diff", "--", path)
            if len(diff) > 60000:
                diff = diff[:60000] + "\n… (diff truncated)"
        self._show_diff(path, diff)

    def _show_diff(self, path, diff):
        self.diff_box.configure(state="normal")
        self.diff_box.delete("1.0", "end")
        tb = self.diff_box._textbox
        for tag, color in (("add", "#81C784"), ("del", "#EF9A9A"), ("meta", GOLD),
                           ("hunk", "#90CAF9")):
            tb.tag_configure(tag, foreground=color)
        if path is None:
            tb.insert("end", "Select a changed file to view its diff.\n")
        else:
            tb.insert("end", f"── {path} ──\n", "meta")
            for line in diff.splitlines():
                if line.startswith("+"):
                    tb.insert("end", line + "\n", "add")
                elif line.startswith("-"):
                    tb.insert("end", line + "\n", "del")
                elif line.startswith("@@"):
                    tb.insert("end", line + "\n", "hunk")
                else:
                    tb.insert("end", line + "\n")
        self.diff_box.configure(state="disabled")

    # -------------------------------------------------------- git panel --
    def refresh_git_panel(self, silent=False):
        tab = self.active_tab()
        if not tab:
            return
        code, _ = self._git(tab, "rev-parse", "--is-inside-work-tree")
        if code != 0:
            self.git_status_label.configure(text=f"○ {tab.name} — no git repository connected",
                                            text_color=MUTED)
            tab.git_branch = ""
            self.git_branch_menu.configure(values=["(branch)"])
            self.git_branch_var.set("(branch)")
            self._render_git_log("")
            return
        _c, branch = self._git(tab, "rev-parse", "--abbrev-ref", "HEAD")
        _c2, cnt = self._git(tab, "status", "--porcelain")
        n = len([l for l in cnt.splitlines() if l.strip()])
        tab.git_branch = branch.strip()
        tab.git_dirty = n
        self.git_status_label.configure(
            text=f"● {tab.name} · branch {tab.git_branch} · {n} uncommitted change{'s' if n != 1 else ''}",
            text_color=GREEN if n == 0 else GOLD)
        _c3, branches = self._git(tab, "branch", "--format=%(refname:short)")
        blist = [b.strip() for b in branches.splitlines() if b.strip()]
        if blist:
            self.git_branch_menu.configure(values=blist)
            if tab.git_branch in blist:
                self.git_branch_var.set(tab.git_branch)
        _c4, log = self._git(tab, "log", "--oneline", "-15")
        self._render_git_log(log.strip())

    def _render_git_log(self, log):
        self.git_log_box.configure(state="normal")
        self.git_log_box.delete("1.0", "end")
        self.git_log_box.insert("1.0", log if log else "— no commits yet —")
        self.git_log_box.configure(state="disabled")

    def git_init_repo(self):
        tab = self.active_tab()
        if not tab:
            return
        code, out = self._git(tab, "init")
        msg = "✓ Git repository initialized" if code == 0 else f"❌ {out.strip()}"
        self.append_chat(msg, tag="success" if code == 0 else "error")
        self.append_terminal(f"$ git init\n{out}", tab)
        self.refresh_git_panel()
        self.refresh_changes_panel()

    def git_stage_all(self):
        self._git_action("add", ["add", "-A"])

    def _on_branch_select(self, branch):
        tab = self.active_tab()
        if not tab or not branch or branch == "(branch)":
            return
        self._git_action(f"checkout {branch}", ["checkout", branch])

    def _git_action(self, name, args, extra_note=""):
        tab = self.active_tab()
        if not tab:
            return
        code, out = self._git(tab, *args)
        self.append_terminal(f"$ git {' '.join(args)}\n{out}", tab)
        if code == 0:
            self.append_chat(f"✓ git {name} ok{extra_note}", tag="success")
        else:
            self.append_chat(f"❌ git {name} failed:\n{out.strip()[:600]}", tag="error")
        self.refresh_git_panel()
        self.refresh_changes_panel()
        self._scan_files(tab)
        self._render_files(tab)

    def git_commit_all(self):
        tab = self.active_tab()
        if not tab:
            return
        msg = self.git_commit_msg.get().strip() or "Update via Mimo IDE"
        self._git_action("add", ["add", "-A"])
        self._git_action("commit", ["commit", "-m", msg])
        self.git_commit_msg.delete(0, "end")

    def git_pull(self):
        self._git_action("pull", ["pull"])

    def git_push(self):
        self._git_action("push", ["push"])

    # -------------------------------------------------------- image --
    def upload_image(self):
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp")])
        if path:
            tab = self.active_tab()
            if tab:
                tab.attached_image = path
            self.append_chat(f"🖼️ Image attached: {os.path.basename(path)}", tag="system")
            self._sync_attachment_ui()

    def paste_image(self, event=None):
        try:
            from PIL import ImageGrab
        except ImportError:
            return
        try:
            img = ImageGrab.grabclipboard()
        except Exception:
            return
        if img is None:
            return
        tab = self.active_tab()
        if not tab:
            return
        tmp = os.path.join(tab.root, ".mimo_paste.png")
        try:
            img.save(tmp, "PNG")
        except Exception:
            return
        tab.attached_image = tmp
        self.append_chat("🖼️ Image pasted from clipboard", tag="system")
        self._sync_attachment_ui()

    @staticmethod
    def _restore_checkpoint(root, ckpt_dir):
        """Restore the newest agent checkpoint in `ckpt_dir`, without importing
        the agent engine. Understands both checkpoint formats:
          - git-native: manifest {files, blobs} — pre-image read from .git/objects
          - legacy:     manifest {files} + byte-copied files/ tree
        Returns a human-readable status string.
        """
        dirs = sorted((d for d in os.scandir(ckpt_dir) if d.is_dir() and d.name.isdigit()),
                      key=lambda d: d.name)
        if not dirs:
            return "Nothing to undo."
        d = dirs[-1]
        try:
            with open(os.path.join(d.path, "manifest.json"), encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            return "❌ Checkpoint is corrupt."
        blobs = manifest.get("blobs") or {}
        restored, deleted, failed = [], [], []
        for rel, kind in (manifest.get("files") or {}).items():
            live = os.path.join(root, rel)
            if kind == "created":
                if os.path.isfile(live):
                    try:
                        os.remove(live)
                        deleted.append(rel)
                    except OSError as e:
                        failed.append(f"{rel} ({e})")
                continue
            data = None
            sha = blobs.get(rel)
            if sha and re.fullmatch(r"[0-9a-f]{40,64}", sha):
                try:
                    r = subprocess.run(["git", "-C", root, "cat-file", "blob", sha],
                                       capture_output=True, timeout=30)
                    if r.returncode == 0:
                        data = r.stdout
                except (OSError, subprocess.TimeoutExpired):
                    pass
            if data is None:
                legacy = os.path.join(d.path, "files", rel)
                if os.path.isfile(legacy):
                    try:
                        with open(legacy, "rb") as f:
                            data = f.read()
                    except OSError:
                        pass
            if data is None:
                failed.append(rel)
                continue
            try:
                os.makedirs(os.path.dirname(live) or root, exist_ok=True)
                with open(live, "wb") as f:
                    f.write(data)
                restored.append(rel)
            except OSError as e:
                failed.append(f"{rel} ({e})")
        for p in sorted((os.path.join(dp, fp) for dp, dn, fn in os.walk(d.path)
                         for fp in fn), reverse=True):
            try:
                os.remove(p)
            except OSError:
                pass
        for dp, dn, fn in os.walk(d.path, topdown=False):
            for dn_ in dn:
                try:
                    os.rmdir(os.path.join(dp, dn_))
                except OSError:
                    pass
        try:
            os.rmdir(d.path)
        except OSError:
            pass
        parts = []
        if restored:
            parts.append("restored " + ", ".join(restored))
        if deleted:
            parts.append("removed " + ", ".join(deleted))
        if failed:
            parts.append("⚠ could not restore: " + ", ".join(failed))
        return "OK: undo — " + ("; ".join(parts) if parts else "removed empty checkpoint")

    def gui_undo(self):
        tab = self.active_tab()
        if not tab:
            return
        ckpt = os.path.join(tab.root, ".agent_checkpoints")
        if not os.path.isdir(ckpt) or not os.listdir(ckpt):
            self.append_chat("Nothing to undo — no checkpoints yet.", tag="system")
            return
        self.append_chat("↩ Undoing last agent change…", tag="system")
        root, ckpt_dir = tab.root, ckpt

        def bg():
            try:
                out = self._restore_checkpoint(root, ckpt_dir)
                self.after(0, lambda: (self.append_chat(out, tag="observation"),
                                       self._render_files(tab),
                                       self.refresh_changes_panel(silent=True),
                                       self._sync_editor_from_disk(tab)))
            except Exception as e:
                self.after(0, lambda e=e: self.append_chat(f"❌ Undo failed: {e}", tag="error"))
        threading.Thread(target=bg, daemon=True).start()

    def _sync_attachment_ui(self):
        tab = self.active_tab()
        attached = bool(tab and tab.attached_image)
        if attached:
            name = os.path.basename(tab.attached_image)
            self.chip_label.configure(text=f"🖼  {name}")
            self.chip_frame.grid()
            self.img_button.configure(fg_color=GOLD, text_color="#000")
            self._show_image_preview(tab.attached_image)
        else:
            self.chip_frame.grid_remove()
            self.img_button.configure(fg_color=CARD, text_color=TEXT)
            self._hide_image_preview()

    def _show_image_preview(self, path):
        try:
            from PIL import Image, ImageTk
            img = Image.open(path)
            img.thumbnail((48, 48))
            self._preview_img = ImageTk.PhotoImage(img)
            if not hasattr(self, "_preview_label"):
                self._preview_label = ctk.CTkLabel(self.chip_frame, text="", width=48, height=48)
                self._preview_label.pack(side="left", padx=(0, 6), pady=2)
            self._preview_label.configure(image=self._preview_img, text="")
        except Exception:
            pass

    def _hide_image_preview(self):
        if hasattr(self, "_preview_label"):
            self._preview_label.configure(image="", text="")

    def _clear_attachment(self):
        tab = self.active_tab()
        if tab:
            tab.attached_image = None
        self._sync_attachment_ui()

    def image_to_base64(self, path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def describe_image(self, path):
        payload = {
            "model": VISION_MODEL,
            "prompt": ("Describe this image in extreme technical detail. If it's a screenshot of "
                       "code or an error, extract the exact text. If it's a design, describe the "
                       "layout and components. Be precise."),
            "images": [self.image_to_base64(path)],
            "stream": False,
        }
        try:
            with httpx2.Client(timeout=120.0) as client:
                r = client.post(OLLAMA_URL.replace("/api/chat", "/api/generate"), json=payload)
                r.raise_for_status()
                return r.json().get("response", "No description returned.")
        except Exception as e:
            return f"Error describing image: {e}"

    # -------------------------------------------------------- input --
    def _on_input_return(self, _event):
        self.send_request()
        return "break"

    def _on_input_shift_return(self, _event):
        return None

    def _on_input_keyrelease(self, _event):
        if _event.keysym in ("Shift_L", "Shift_R", "Command_L", "Command_R",
                             "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R"):
            return
        self._refresh_input_hint()
        self._grow_input()

    def _on_input_focus_in(self, _event):
        self.input_hint.place_forget()

    def _on_input_focus_out(self, _event):
        self._refresh_input_hint()

    def _on_input_click(self, _event):
        self.after(0, self._focus_input)

    def _on_input_paste(self, _event=None):
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img is not None:
                self.paste_image()
                return "break"
        except Exception:
            pass
        return None

    def _focus_input(self):
        try:
            self.user_input._textbox.focus_set()
            self.user_input.focus_set()
        except Exception:
            pass

    def _refresh_input_hint(self):
        text = self.user_input.get("1.0", "end-1c").strip()
        if text or self.focus_get() == str(self.user_input):
            self.input_hint.place_forget()
        else:
            self.input_hint.place(relx=0, rely=0.5, anchor="w", x=14)

    def _grow_input(self):
        content = self.user_input.get("1.0", "end-1c")
        lines = content.count("\n") + 1 if content else 1
        lines = min(lines, 8)
        h = max(52, lines * 20 + 20)
        self.user_input.configure(height=h)

    # -------------------------------------------------------- work card --
    _SPIN_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    _WORK_PHASE_RE = re.compile(r"^[✦◆]\s*(.*)$")
    _WORK_STEP_RE = re.compile(r"^\[(\d+)/(\d+)\]\s*(.*)$")

    # ---------------------------------------------------- engine events --
    def _handle_engine_event(self, ev, tab):
        """Dispatch one JSONL event from the engine.

        Runs on the engine worker thread; widget touches go through self.after
        or the thread-safe append_chat (same contract as the legacy path).
        """
        t = ev["evt"]
        if t == "intent":
            it = ev.get("intent") or ""
            labels = {"trivial": "💬 Greeting",
                      "fast": "⚡ Quick answer",
                      "plan": "🧭 Plan · analysis only (read-only)",
                      "build": "🔨 Build · plan → execute → verify"}
            self.append_chat(labels.get(it, f"Mode: {it}"), tag="system", tab=tab)
            return
        if t == "delta":
            self._stream_delta(tab, ev.get("text") or "")
            return
        if t == "stream_fix":
            self._stream_fix(tab, ev.get("text") or "", ev.get("note") or "")
            return
        if t == "text_end":
            self._stream_end(tab)
            return
        if t == "thinking":
            txt = (ev.get("text") or "").strip()
            if txt:
                self.append_terminal("⋯ " + txt[:300], tab)
            return
        if t == "tool_start":
            name = ev.get("name") or "?"
            args = (ev.get("args") or "").strip()
            step, total = ev.get("step"), ev.get("total")
            line = (f"[{step}/{total}] {name} {args}".strip()
                    if step else f"{name} {args}".strip())
            self.append_terminal(line, tab)
            # fires BEFORE the tool runs — the work card can show it live
            self._work_card_update(tab, action=f"{name} {args}".strip())
            self.append_chat(line, tag="activity", tab=tab)
            return
        if t == "tool_end":
            preview = (ev.get("preview") or "").strip()
            if not preview:
                return
            for ln in preview.splitlines()[:6]:
                self.append_terminal(ln, tab)
            first = preview.splitlines()[0][:300]
            tag, text = self._classify_engine_line(first)
            if tag != "silent" and text:
                self.append_chat(text, tag=tag, tab=tab)
            return
        if t == "phase":
            body = re.sub(r"\[\d+/\d+\]\s*", "", (ev.get("label") or "")).strip()
            phase_label = body or "Working…"
            for key, lab in self._PHASE_KEYWORDS:
                if key in body:
                    phase_label = lab
                    break
            note = (ev.get("note") or "").strip()
            step, total = ev.get("step"), ev.get("total")
            self._work_card_update(
                tab, phase=phase_label,
                step=f"step {step}/{total}" if step and total else "",
                action=(f"{body} — {note}" if note else ""))
            return
        if t == "tasks":
            tab.tasks_data = list(ev.get("tasks") or [])
            if tab is self.active_tab():
                self.after(0, self.refresh_tasks_panel)
            return
        if t == "metrics":
            try:
                pt = int(ev.get("prompt") or 0)
                gt = int(ev.get("gen") or 0)
                calls = int(ev.get("tool_calls") or 0)
                dur = float(ev.get("duration") or 0)
            except (TypeError, ValueError):
                return
            def _fmt(n):
                return f"{n / 1000:.1f}k" if n >= 1000 else str(n)
            self.append_chat(
                f"📊 {_fmt(pt)} prompt + {_fmt(gt)} gen tokens · {calls} tool calls · {dur:.0f}s",
                tag="system", tab=tab)
            return
        if t == "usage":
            try:
                pt = int(ev.get("prompt") or 0)
                gt = int(ev.get("gen") or 0)
            except (TypeError, ValueError):
                return
            tab.last_prompt_tokens = pt
            tab.last_gen_tokens = gt
            tab.total_prompt_tokens = getattr(tab, "total_prompt_tokens", 0) + pt
            tab.total_gen_tokens = getattr(tab, "total_gen_tokens", 0) + gt
            return
        if t == "session":
            sid = ev.get("id")
            if sid and sid != tab.session_id:
                tab.session_id = sid
                _save_project_prefs(tab.root, {"model": tab.model, "session_id": sid})
                self.after(0, lambda: self.refresh_sessions(tab, keep_selection=True))
            return
        if t == "plan":
            plan = (ev.get("plan") or "").strip()
            if plan:
                self.append_chat("📋 **Proposed plan**\n" + plan, tag="assistant", tab=tab)
            return
        if t in ("notice", "error"):
            msg = (ev.get("msg") or "").strip()
            if not msg:
                return
            lines = msg.splitlines()
            tag, text = self._classify_engine_line(lines[0])
            if tag is None:
                tag = "error" if t == "error" else "assistant"
            elif tag == "silent":
                tag = "system"
            if len(lines) > 1:
                # classify picks the tag from the first line, but multi-line
                # notices must keep their body (headings, lists, details)
                text = msg
            self.append_chat(text or msg, tag=tag, tab=tab)
            return
        # unknown event types are ignored on purpose (forward compatible)

    # --------------------------------------------------- streaming text --
    def _stream_delta(self, tab, text):
        """Append a streamed model-text delta to the live assistant entry."""
        if not text:
            return
        if tab.stream_idx is None:
            tab.stream_buf = text
            tab.transcript.append(("assistant", ""))
            tab.stream_idx = len(tab.transcript) - 1
            tab.stream_anchor = None
        else:
            tab.stream_buf = (tab.stream_buf or "") + text
        tab.transcript[tab.stream_idx] = ("assistant", tab.stream_buf)
        if not tab.stream_pending:
            tab.stream_pending = True
            self.after(50, lambda: self._flush_stream(tab))

    def _stream_fix(self, tab, text, note):
        """Replace the live streaming entry after the engine cut a loop.

        The garbage was already painted delta by delta; this swaps the buffer
        for the clean text (or drops it entirely and shows the note).
        """
        if tab.stream_idx is None:
            if text:
                self.append_chat(text, tag="assistant", tab=tab)
            elif note:
                self.append_chat(note, tag="system", tab=tab)
            return
        if text:
            tab.stream_buf = text
            tab.transcript[tab.stream_idx] = ("assistant", text)
            if tab is self.active_tab():
                if threading.current_thread() is threading.main_thread():
                    self._paint_stream(tab)
                else:
                    self.after(0, self._paint_stream, tab)
        else:
            # nothing worth keeping — seal the (empty) entry, then explain
            tab.stream_buf = ""
            self._stream_end(tab)
            if note:
                self.append_chat(note, tag="system", tab=tab)

    def _flush_stream(self, tab):
        tab.stream_pending = False
        if tab.stream_idx is None:
            return
        if tab is not self.active_tab():
            return
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self._flush_stream, tab)
            return
        self._paint_stream(tab)

    def _paint_stream(self, tab):
        """Re-render only the live streaming entry (not the whole transcript)."""
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self._paint_stream, tab)
            return
        tb = self.chat_display._textbox
        if tab.stream_anchor is None:
            # no anchor yet (fresh stream / after a tab switch): full render
            # re-captures the anchor right before the live entry
            self._render_transcript(tab)
            return
        self.chat_display.configure(state="normal")
        try:
            tb.delete(tab.stream_anchor, "end")
        finally:
            self.chat_display.configure(state="disabled")
        try:
            if tb.index("end-1c") != tab.stream_anchor:
                # Tk silently dropped the delete (cross-thread / disabled
                # widget) — appending again would duplicate the whole buffer,
                # so fall back to a full re-render instead
                self._render_transcript(tab)
                return
        except Exception:
            pass
        self._render_entry("assistant", tab.stream_buf or "")

    def _stream_end(self, tab):
        """Finalize the live entry (also called before any other append).

        The stream state reset happens synchronously on the calling thread,
        but the repaint is always marshalled to the main thread: this runs on
        the engine worker thread, and a cross-thread delete against a text
        widget that the other thread just disabled is silently dropped by Tk
        (that duplication bug: every flush re-appended the full buffer).
        """
        if tab.stream_idx is None:
            return
        idx, anchor = tab.stream_idx, tab.stream_anchor
        buf = (tab.stream_buf or "")
        active = tab is self.active_tab()
        empty = not buf.strip()
        seq = getattr(tab, "render_seq", 0)
        if empty and idx < len(tab.transcript):
            del tab.transcript[idx]
        tab.stream_buf = None
        tab.stream_idx = None
        tab.stream_anchor = None
        tab.stream_pending = False
        if not active:
            return
        if threading.current_thread() is threading.main_thread():
            self._finalize_stream(tab, buf, anchor, empty, seq)
        else:
            self.after(0, self._finalize_stream, tab, buf, anchor, empty, seq)

    def _finalize_stream(self, tab, buf, anchor, empty, seq):
        """Main-thread repaint of a sealed streaming entry."""
        if tab is not self.active_tab():
            return
        if seq != getattr(tab, "render_seq", 0):
            # a full transcript re-render happened after this seal (e.g. a
            # tab re-activation) and already painted the final text
            return
        if anchor is None:
            if not empty:
                self._render_entry("assistant", buf)
            return
        tb = self.chat_display._textbox
        self.chat_display.configure(state="normal")
        try:
            tb.delete(anchor, "end")
        finally:
            self.chat_display.configure(state="disabled")
        if not empty:
            self._render_entry("assistant", buf)

    def _route_to_work_card(self, line, tab):
        """Send phase markers and step lines to the work card instead of chat."""
        m = self._WORK_PHASE_RE.match(line)
        if m:
            body = re.sub(r"\[\d+/\d+\]\s*", "", m.group(1)).strip()
            for key, label in self._PHASE_KEYWORDS:
                if key in body:
                    self._work_card_update(tab, phase=label)
                    return True
            self._work_card_update(tab, phase=body or "Working…")
            return True
        m = self._WORK_STEP_RE.match(line)
        if m:
            step = f"step {m.group(1)}/{m.group(2)}"
            action = m.group(3).strip()
            self._work_card_update(tab, step=step, action=action)
            return True
        return False

    def _show_work_card(self, tab):
        tab.cur_phase = "Starting…"
        tab.cur_step = ""
        tab.cur_action = ""
        if tab is self.active_tab():
            self.after(0, self._work_card_render, tab)

    def _hide_work_card(self, tab):
        tab.cur_phase = ""
        tab.cur_step = ""
        tab.cur_action = ""
        if tab is self.active_tab():
            self.after(0, self.work_card.grid_remove)

    def _work_card_update(self, tab, phase=None, step=None, action=None):
        if phase is not None:
            tab.cur_phase = phase
        if step is not None:
            tab.cur_step = step
        if action is not None:
            tab.cur_action = action
        if tab is self.active_tab():
            self.after(0, self._work_card_render, tab)

    def _work_card_render(self, tab):
        if not tab.is_generating:
            self.work_card.grid_remove()
            return
        self.work_card.grid()
        self.work_phase_lbl.configure(text=tab.cur_phase or "Working…")
        elapsed = int(time.time() - tab.run_started) if tab.run_started else 0
        meta = f"{tab.model}  ·  {elapsed}s"
        if tab.cur_step:
            meta = f"{tab.cur_step}  ·  {meta}"
        self.work_meta_lbl.configure(text=meta)
        self.work_action_lbl.configure(text=tab.cur_action or "")
        if not hasattr(self, "_spin_pos"):
            self._spin_pos = 0
        self._spin_pos = (self._spin_pos + 1) % len(self._SPIN_FRAMES)
        self.work_spin.configure(text=self._SPIN_FRAMES[self._spin_pos])
        self.after(120, self._work_card_anim, tab)

    def _work_card_anim(self, tab):
        if tab.is_generating and tab is self.active_tab() and self.work_card.winfo_ismapped():
            self._spin_pos = (getattr(self, "_spin_pos", 0) + 1) % len(self._SPIN_FRAMES)
            self.work_spin.configure(text=self._SPIN_FRAMES[self._spin_pos])
            elapsed = int(time.time() - tab.run_started) if tab.run_started else 0
            meta = f"{tab.model}  ·  {elapsed}s"
            if tab.cur_step:
                meta = f"{tab.cur_step}  ·  {meta}"
            self.work_meta_lbl.configure(text=meta)
            self.after(120, self._work_card_anim, tab)

    # -------------------------------------------------------- send/stop --
    def send_request(self):
        task = self.user_input.get("1.0", "end-1c").strip()
        if not task:
            return
        self.user_input.delete("1.0", "end")
        self._refresh_input_hint()
        self.user_input.configure(height=52)
        tab = self.active_tab()
        if not tab:
            return
        if tab.is_generating:
            tab.pending_tasks.append(task)
            self.append_chat(f"⏳ Queued ({len(tab.pending_tasks)} waiting): {task}", tag="system")
            return
        self._start_agent_thread(tab, task)

    def _start_agent_thread(self, tab, task):
        self.append_chat(task, tag="goal", tab=tab)
        tab.is_generating = True
        tab.stop_requested = False
        tab.run_started = time.time()
        self._show_work_card(tab)
        self._sync_send_button()
        self.render_tab_bar()
        threading.Thread(target=self.agent_loop, args=(tab, task), daemon=True).start()

    def _sync_send_button(self):
        tab = self.active_tab()
        if tab and tab.is_generating:
            self.send_button.configure(text="■  Stop", fg_color=RED, hover_color="#D32F2F",
                                       text_color="#FFF", command=self.stop_generation)
        else:
            self.send_button.configure(text="▶  Run", fg_color=GOLD, text_color="#000",
                                       hover_color="#FFB300", command=self.send_request)

    def stop_generation(self):
        tab = self.active_tab()
        if tab and tab.is_generating:
            self._stop_tab(tab)

    def _stop_tab(self, tab, silent=False):
        tab.stop_requested = True
        if not silent:
            self.append_chat("⏹ Stopping agent…", tag="system", tab=tab)
        if tab.proc is not None and tab.proc.poll() is None:
            try:
                tab.proc.terminate()
            except OSError:
                pass

    # -------------------------------------------------------- engine loop --
    _PHASE_KEYWORDS = (
        ("Mission", "🚀 Mission"),
        ("Planning", "📋 Planning"),
        ("Execute", "⚙️ Executing"),
        ("Verify", "🧪 Verifying"),
        ("Review", "🔍 Reviewing"),
        ("Summarize", "📝 Summarizing"),
        ("Summary", "✅ Summary"),
    )

    def _classify_engine_line(self, line):
        if line.startswith("@@USAGE@@"):
            parts = line.split()
            try:
                pt = int(parts[1]); gt = int(parts[2])
                tab = self.active_tab()
                if tab:
                    tab.last_prompt_tokens = pt
                    tab.last_gen_tokens = gt
                    tab.total_prompt_tokens = getattr(tab, "total_prompt_tokens", 0) + pt
                    tab.total_gen_tokens = getattr(tab, "total_gen_tokens", 0) + gt
            except (IndexError, ValueError):
                pass
            return "silent", line
        if line.startswith("✦") or line.startswith("◆"):
            body = re.sub(r"\[\d+/\d+\]\s*", "", line.lstrip("✦◆ ").strip())
            for key, label in self._PHASE_KEYWORDS:
                if key in body:
                    suffix = body.split(key, 1)[1].strip(" —…()")
                    return "system", f"{label} ({suffix})" if suffix and key != "Mission" else label
            return "system", body
        if re.match(r"^\[\d+/\d+\]", line):
            return "activity", line
        stripped = line.strip()
        low = stripped.lower()
        if low.startswith("error") or low.startswith("the model kept trying"):
            return "error", stripped
        if stripped.startswith("exit code:") and "exit code: 0" not in stripped[:20]:
            return "error", stripped
        if stripped.startswith("exit code: 0"):
            return "silent", stripped
        if stripped.startswith("OK:"):
            return "observation", stripped
        if stripped.startswith(("plan saved", "Stopped:", "Use /model", "Say 'continue'",
                                "No saved session")):
            return "system", stripped
        return None, line

    def _wait_for_ollama(self, tab, timeout=15):
        host = self.settings.get("ollama_host") or "http://localhost:11434"
        host = host.rstrip("/")
        for attempt in range(timeout):
            try:
                import urllib.request
                req = urllib.request.Request(f"{host}/api/tags", method="GET")
                urllib.request.urlopen(req, timeout=2)
                return True
            except Exception:
                if attempt == 0:
                    self.append_chat(f"⏳ Waiting for Ollama at {host}…", tag="system", tab=tab)
                time.sleep(1)
        self.append_chat(f"❌ Ollama not reachable at {host} after {timeout}s. "
                         f"Start it with: ollama serve", tag="error", tab=tab)
        return False

    def agent_loop(self, tab, goal):
        visual_context = ""
        if tab.attached_image:
            image_path = tab.attached_image
            self.append_chat("👁️ Analyzing image with vision model…", tag="system", tab=tab)
            visual_context = self.describe_image(image_path)
            self.append_chat(f"🖼️ {visual_context}", tag="observation", tab=tab)
            tab.attached_image = None
            if tab is self.active_tab():
                self.after(0, self._sync_attachment_ui)

        full_goal = goal
        if visual_context:
            full_goal = f"Image analysis: {visual_context}\n\nTask: {goal}"

        if not os.path.exists(AGENT_SCRIPT):
            self.append_chat(f"❌ Agent engine not found: {AGENT_SCRIPT}", tag="error", tab=tab)
            self._finish_tab_run(tab)
            return

        py = get_agent_python()
        if not py:
            self.append_chat("❌ No python with the 'ollama' package found "
                             "(set MIMO_AGENT_PY).", tag="error", tab=tab)
            self._finish_tab_run(tab)
            return

        if not self._wait_for_ollama(tab):
            self._finish_tab_run(tab)
            return

        self.append_chat(f"◆ Engine ready · {tab.model} · plan → execute → verify → summarize",
                         tag="system", tab=tab)
        cmd = [py, "-u", AGENT_SCRIPT, tab.root, "--model", tab.model, "--yolo", "--plan",
               "--events"]
        s = self.settings
        if s.get("num_ctx"):
            cmd += ["--num-ctx", str(int(s["num_ctx"]))]
        if s.get("temperature") is not None:
            cmd += ["--temperature", str(s["temperature"])]
        if s.get("keep_alive"):
            cmd += ["--keep-alive", str(s["keep_alive"])]
        if s.get("num_predict"):
            cmd += ["--num-predict", str(int(s["num_predict"]))]
        if tab.session_id:
            self.append_chat(f"↩ Resuming session {tab.session_id}", tag="system", tab=tab)
            cmd += ["--resume", tab.session_id]
        cmd += ["-p", full_goal]
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if s.get("ollama_host"):
            env["OLLAMA_HOST"] = s["ollama_host"]
        try:
            tab.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=tab.root, env=env)
            for raw in tab.proc.stdout:
                if tab.stop_requested:
                    break
                line = re.sub(r"\x1b\[[0-9;]*m", "", raw).rstrip()
                if not line:
                    continue
                ev = _parse_event(line)
                if ev is not None:
                    try:
                        self._handle_engine_event(ev, tab)
                    except Exception as e:
                        self.append_chat(f"⚠ Event handler error ({ev.get('evt')}): {e}",
                                         tag="system", tab=tab)
                    continue
                self.append_terminal(line, tab)
                if line.startswith("@@TASKS@@"):
                    display = self._handle_tasks_line(line, tab)
                    if display:
                        self.append_chat(display, tag="activity", tab=tab)
                    continue
                # presentation: phase + step lines drive the work card, not the chat
                if self._route_to_work_card(line, tab):
                    continue
                tag, text = self._classify_engine_line(line)
                if tag == "silent":
                    continue
                self._track_context_file(line, tab)
                self.append_chat(text, tag=tag, tab=tab)
            tab.proc.wait()
            if tab.stop_requested:
                self.append_chat("⏹ Stopped by user.", tag="system", tab=tab)
            elif tab.proc.returncode not in (0, None):
                self.append_chat(f"⚠️ Engine exited with code {tab.proc.returncode}.",
                                 tag="error", tab=tab)
            else:
                self.append_chat("✓ Run finished.", tag="success", tab=tab)
        except Exception as e:
            self.append_chat(f"❌ Engine error: {e}", tag="error", tab=tab)
        finally:
            tab.proc = None
            self._adopt_newest_session(tab)
            self.after(0, lambda: self._render_files(tab))
            self.after(0, lambda: self.refresh_changes_panel(silent=True))
            self.after(0, lambda: self.refresh_git_panel(silent=True))
            self.after(0, lambda: self._sync_editor_from_disk(tab))
            if tab.pending_tasks and not tab.stop_requested:
                nxt = tab.pending_tasks.pop(0)
                self.append_chat(f"▶ Running queued prompt ({len(tab.pending_tasks)} left)…",
                                 tag="system", tab=tab)
                self._start_agent_thread(tab, nxt)
            else:
                self._finish_tab_run(tab)

    def _adopt_newest_session(self, tab):
        root = os.path.join(tab.root, ".agent_sessions")
        best = None
        if os.path.isdir(root):
            for fn in os.listdir(root):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(root, fn), encoding="utf-8") as f:
                        data = json.load(f)
                    updated = data.get("updated") or 0
                    sid = data.get("id") or fn[:-5]
                    if best is None or updated > best[0]:
                        best = (updated, sid)
                except (OSError, json.JSONDecodeError):
                    continue
        if best:
            tab.session_id = best[1]
            if tab is self.active_tab():
                self.after(0, lambda: self.refresh_sessions(tab, keep_selection=True))

    def _finish_tab_run(self, tab):
        tab.is_generating = False
        tab.stop_requested = False
        tab.run_started = 0.0
        self._hide_work_card(tab)
        if tab is self.active_tab():
            self.after(0, self._sync_send_button)
        self.after(0, self.render_tab_bar)
        if tab.inline_preview:
            # ⌘K run finished → show the inline diff for Accept/Reject
            self.after(0, lambda: self._review_inline_edit(tab))

    # -------------------------------------------------------- status --
    def _status_tick(self):
        tab = self.active_tab()
        if tab:
            tok = ""
            if tab.total_prompt_tokens or tab.total_gen_tokens:
                tp = tab.total_prompt_tokens
                tg = tab.total_gen_tokens
                tok = f" · {tp // 1000}k in / {tg // 1000}k out" if (tp + tg) > 2000 else f" · {tp} in / {tg} out"
            if tab.is_generating:
                elapsed = int(time.time() - tab.run_started) if tab.run_started else 0
                queue = f" · queue {len(tab.pending_tasks)}" if tab.pending_tasks else ""
                dots = "." * (int(time.time() * 2) % 4)
                last = ""
                if tab.last_prompt_tokens or tab.last_gen_tokens:
                    last = f" · last {tab.last_prompt_tokens}+{tab.last_gen_tokens}"
                self.status_bar.configure(
                    text=f"● Running{dots} · {tab.name} · {tab.model} · {elapsed}s{queue}{last}{tok}",
                    text_color=GOLD)
            else:
                n_sess = len(tab.session_labels)
                self.status_bar.configure(
                    text=f"○ idle · {tab.name} · {tab.model}{tok}"
                         + (f" · {n_sess} session{'s' if n_sess != 1 else ''}" if n_sess else ""),
                    text_color=MUTED)
        self.after(900, self._status_tick)

    def _on_close(self):
        for tab in self.tabs:
            self._stop_tab(tab, silent=True)
        _save_geometry(self)
        self.destroy()


if __name__ == "__main__":
    app = MimoIDE()
    app.mainloop()
