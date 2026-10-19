import os
import json
import re
import shutil
import sys
import time
import threading
import subprocess
import base64

import customtkinter as ctk
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

BG = "#171717"
PANEL = "#1F1F1F"
CARD = "#262626"
ACTIVE = "#2F2F2F"
GOLD = "#F9A825"
TEXT = "#EAEAEA"
MUTED = "#9E9E9E"
GREEN = "#66BB6A"
RED = "#EF5350"

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
        self.editor_text = ""
        self.editor_widget = None
        self.raw_log = []
        self.changed_files = {}
        self.git_root = None
        self.git_branch = ""
        self.git_dirty = 0
        self.git_log = []


# --------------------------------------------------------------------- app --
class MimoIDE(ctk.CTk):
    MAX_READ_CHARS = 8000

    def __init__(self):
        super().__init__()
        self.title("Mimo-Agentic IDE | Multimodal AI Engineer")
        self.geometry("1440x920")
        self.configure(fg_color=BG)
        self.lift()
        self.focus_force()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.tabs = []
        self.active_index = 0
        self.models_inventory = {
            "qwen3-coder:30b": "Qwen 3 Coder (30B)",
            "deepseek-r1:latest": "DeepSeek R1",
            "freebuff-mimo:latest": "FreeBuff Mimo",
            "llama3.2:latest": "Llama 3.2",
        }

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.add_project_tab(self._initial_project())
        self.refresh_available_models()
        self._status_tick()

    # ---------------------------------------------------------- helpers --
    def _initial_project(self):
        cwd = os.getcwd()
        return cwd

    def active_tab(self):
        if 0 <= self.active_index < len(self.tabs):
            return self.tabs[self.active_index]
        return None

    # ------------------------------------------------------------- layout --
    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # --- project tab bar (row 0, spans both columns) ---
        self.tab_bar = ctk.CTkFrame(self, height=44, corner_radius=0, fg_color=PANEL)
        self.tab_bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.tab_bar_inner = ctk.CTkFrame(self.tab_bar, fg_color="transparent")
        self.tab_bar_inner.pack(side="left", fill="x", expand=True, padx=8, pady=6)
        self.add_tab_btn = ctk.CTkButton(self.tab_bar, text="＋", width=36, height=30,
                                         fg_color=CARD, hover_color=ACTIVE, text_color=GOLD,
                                         font=ctk.CTkFont(size=16, weight="bold"),
                                         command=self._add_project_dialog)
        self.add_tab_btn.pack(side="right", padx=(4, 12), pady=6)

        # --- sidebar (row 1, col 0) — contextual to active tab ---
        self.sidebar = ctk.CTkFrame(self, width=270, corner_radius=0, fg_color=PANEL)
        self.sidebar.grid(row=1, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(6, weight=1)
        self.sidebar.grid_rowconfigure(11, weight=1)
        self.sidebar.grid_columnconfigure(0, weight=1)

        self.project_label = ctk.CTkLabel(self.sidebar, text="PROJECT", text_color=GOLD,
                                          font=ctk.CTkFont(size=11, weight="bold"))
        self.project_label.grid(row=0, column=0, padx=16, pady=(14, 2), sticky="w")

        self.model_label = ctk.CTkLabel(self.sidebar, text="Active Brain", text_color=MUTED,
                                        font=ctk.CTkFont(size=11))
        self.model_label.grid(row=1, column=0, padx=16, pady=(10, 0), sticky="w")
        self.model_dropdown = ctk.CTkOptionMenu(
            self.sidebar, values=list(self.models_inventory.values()),
            command=self.change_model, fg_color=ACTIVE, button_color=GOLD,
            button_hover_color="#FFB300", text_color=TEXT, dropdown_fg_color=CARD,
            dropdown_text_color=TEXT, height=32)
        self.model_dropdown.grid(row=2, column=0, padx=16, pady=(4, 8), sticky="ew")

        self.sessions_label = ctk.CTkLabel(self.sidebar, text="Sessions", text_color=MUTED,
                                           font=ctk.CTkFont(size=11))
        self.sessions_label.grid(row=3, column=0, padx=16, pady=(8, 0), sticky="w")
        row4 = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        row4.grid(row=4, column=0, padx=16, pady=(4, 8), sticky="ew")
        row4.grid_columnconfigure(0, weight=1)
        self.sessions_dropdown = ctk.CTkOptionMenu(
            row4, values=["(new chat)"], command=self.on_session_selected,
            fg_color=ACTIVE, button_color=GOLD, button_hover_color="#FFB300",
            text_color=TEXT, dropdown_fg_color=CARD, dropdown_text_color=TEXT,
            height=32, dynamic_resizing=False, width=170)
        self.sessions_dropdown.grid(row=0, column=0, sticky="ew")
        self.new_chat_btn = ctk.CTkButton(row4, text="＋", width=32, height=32,
                                          fg_color=CARD, hover_color=ACTIVE, text_color=GOLD,
                                          font=ctk.CTkFont(size=15, weight="bold"),
                                          command=self.new_chat)
        self.new_chat_btn.grid(row=0, column=1, padx=(6, 0))

        tasks_hdr = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        tasks_hdr.grid(row=5, column=0, padx=16, pady=(8, 0), sticky="ew")
        tasks_hdr.grid_columnconfigure(0, weight=1)
        self.tasks_label = ctk.CTkLabel(tasks_hdr, text="Tasks", text_color=MUTED,
                                        font=ctk.CTkFont(size=11))
        self.tasks_label.grid(row=0, column=0, sticky="w")
        self.tasks_expand_btn = ctk.CTkButton(tasks_hdr, text="⤢", width=30, height=22,
                                              fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                              font=ctk.CTkFont(size=13),
                                              command=self._open_tasks_expanded)
        self.tasks_expand_btn.grid(row=0, column=1, padx=(6, 0))
        self.tasks_container = ctk.CTkScrollableFrame(self.sidebar, width=230,
                                                      fg_color=PANEL, label_text="")
        self.tasks_container.grid(row=6, column=0, padx=8, pady=(4, 4), sticky="nsew")

        self.files_label = ctk.CTkLabel(self.sidebar, text="Files", text_color=MUTED,
                                        font=ctk.CTkFont(size=11))
        self.files_label.grid(row=7, column=0, padx=16, pady=(10, 0), sticky="w")
        self.project_btn = ctk.CTkButton(self.sidebar, text="📁 Open Project", height=30,
                                         fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                         command=self._add_project_dialog)
        self.project_btn.grid(row=8, column=0, padx=16, pady=(6, 2), sticky="ew")
        self.files_container = ctk.CTkScrollableFrame(self.sidebar, width=230, fg_color=PANEL)
        self.files_container.grid(row=9, column=0, rowspan=3, padx=8, pady=(4, 8), sticky="nsew")

        # --- main area (row 1, col 1) ---
        self.main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.main.grid(row=1, column=1, sticky="nsew", padx=0, pady=0)
        self.main.grid_rowconfigure(0, weight=1)
        self.main.grid_columnconfigure(0, weight=1)

        self.main_tabs = ctk.CTkTabview(self.main, fg_color=BG, segmented_button_fg_color=CARD,
                                        segmented_button_selected_color=ACTIVE,
                                        segmented_button_selected_hover_color=ACTIVE,
                                        text_color=TEXT)
        self.main_tabs.grid(row=0, column=0, sticky="nsew", padx=14, pady=(12, 8))
        self.chat_tab = self.main_tabs.add("Chat")
        self.editor_tab = self.main_tabs.add("Editor")
        self.terminal_tab = self.main_tabs.add("Terminal")
        self.changes_tab = self.main_tabs.add("Changes")
        self.git_tab = self.main_tabs.add("Git")

        # Chat tab
        self.chat_tab.grid_columnconfigure(0, weight=1)
        self.chat_tab.grid_rowconfigure(0, weight=1)
        self.chat_display = ctk.CTkTextbox(self.chat_tab, fg_color="#121212", text_color=TEXT,
                                           wrap="word", font=ctk.CTkFont(size=13))
        self.chat_display.grid(row=0, column=0, sticky="nsew")
        self.chat_display.configure(state="disabled")
        self._setup_chat_tags()

        # Editor tab
        self.editor_tab.grid_columnconfigure(0, weight=1)
        self.editor_tab.grid_rowconfigure(1, weight=1)
        ebar = ctk.CTkFrame(self.editor_tab, fg_color="transparent")
        ebar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ebar.grid_columnconfigure(0, weight=1)
        self.editor_path_label = ctk.CTkLabel(ebar, text="No file open", text_color=MUTED,
                                              font=ctk.CTkFont(family="Menlo", size=12))
        self.editor_path_label.grid(row=0, column=0, sticky="w")
        self.editor_save_btn = ctk.CTkButton(ebar, text="💾 Save", width=90, height=28,
                                             fg_color=GOLD, text_color="#000",
                                             hover_color="#FFB300", command=self.save_editor)
        self.editor_save_btn.grid(row=0, column=1, padx=(8, 0))
        self.editor_box = ctk.CTkTextbox(self.editor_tab, fg_color="#121212", text_color="#D4D4D4",
                                         font=ctk.CTkFont(family="Menlo", size=13),
                                         wrap="none")
        self.editor_box.grid(row=1, column=0, sticky="nsew")

        # Terminal tab — raw engine stream
        self.terminal_tab.grid_columnconfigure(0, weight=1)
        self.terminal_tab.grid_rowconfigure(0, weight=1)
        self.terminal_box = ctk.CTkTextbox(self.terminal_tab, fg_color="#0D0D0D",
                                           text_color="#B8B8B8",
                                           font=ctk.CTkFont(family="Menlo", size=12),
                                           wrap="char")
        self.terminal_box.grid(row=0, column=0, sticky="nsew")
        self.terminal_box.configure(state="disabled")

        # Changes tab — recent file changes with diffs
        self.changes_tab.grid_columnconfigure(0, weight=1)
        self.changes_tab.grid_rowconfigure(1, weight=1)
        cbar = ctk.CTkFrame(self.changes_tab, fg_color="transparent")
        cbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        cbar.grid_columnconfigure(0, weight=1)
        self.changes_title = ctk.CTkLabel(cbar, text="Recent changes", text_color=MUTED,
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
        self.changes_list = ctk.CTkScrollableFrame(changes_split, width=250, fg_color=PANEL)
        self.changes_list.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.diff_box = ctk.CTkTextbox(changes_split, fg_color="#0D0D0D", text_color="#D4D4D4",
                                       font=ctk.CTkFont(family="Menlo", size=12), wrap="none")
        self.diff_box.grid(row=0, column=1, sticky="nsew")
        self.diff_box.configure(state="disabled")

        # Git tab — repo status, log, quick actions
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
        for text, cmd in [("Commit all", self.git_commit_all),
                          ("Pull", self.git_pull),
                          ("Push", self.git_push)]:
            b = ctk.CTkButton(git_actions, text=text, width=110, height=30,
                              fg_color=CARD, hover_color=ACTIVE, text_color=TEXT, command=cmd)
            b.pack(side="left", padx=(0, 6))
        self.git_commit_msg = ctk.CTkEntry(git_actions, height=30, fg_color=CARD,
                                           placeholder_text="Commit message…",
                                           placeholder_text_color=MUTED, border_color=ACTIVE)
        self.git_commit_msg.pack(side="left", fill="x", expand=True, padx=(6, 0))
        git_log_wrap = ctk.CTkFrame(self.git_tab, fg_color="transparent")
        git_log_wrap.grid(row=3, column=0, sticky="nsew")
        git_log_wrap.grid_columnconfigure(0, weight=1)
        git_log_wrap.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(git_log_wrap, text="Recent commits", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        self.git_log_box = ctk.CTkTextbox(git_log_wrap, fg_color="#0D0D0D", text_color="#D4D4D4",
                                          font=ctk.CTkFont(family="Menlo", size=12))
        self.git_log_box.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.git_log_box.configure(state="disabled")

        # Input area
        self.input_frame = ctk.CTkFrame(self.main, fg_color=BG, corner_radius=0)
        self.input_frame.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))
        self.input_frame.grid_columnconfigure(0, weight=1)
        self.user_input = ctk.CTkEntry(self.input_frame, height=48, fg_color=CARD,
                                       text_color=TEXT, placeholder_text="Describe the task or ask about the image...",
                                       placeholder_text_color=MUTED, border_color=ACTIVE)
        self.user_input.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.user_input.bind("<Return>", lambda e: self.send_request())
        self.img_button = ctk.CTkButton(self.input_frame, text="🖼️", width=48, height=48,
                                        fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                        command=self.upload_image)
        self.img_button.grid(row=0, column=1, padx=(0, 10))
        self.send_button = ctk.CTkButton(self.input_frame, text="▶ Run", width=130, height=48,
                                         fg_color=GOLD, text_color="#000", hover_color="#FFB300",
                                         font=ctk.CTkFont(weight="bold"), command=self.send_request)
        self.send_button.grid(row=0, column=2)

        # Status bar
        self.status_bar = ctk.CTkLabel(self, text="○ idle", height=26, anchor="w",
                                       fg_color=PANEL, text_color=MUTED,
                                       font=ctk.CTkFont(size=11), padx=12)
        self.status_bar.grid(row=2, column=0, columnspan=2, sticky="ew")

    # ---------------------------------------------------------- tab bar --
    def render_tab_bar(self):
        for w in self.tab_bar_inner.winfo_children():
            w.destroy()
        for i, tab in enumerate(self.tabs):
            active = (i == self.active_index)
            run_dot = " ●" if tab.is_generating else ""
            btn = ctk.CTkButton(
                self.tab_bar_inner, text=f"  {tab.name}{run_dot}  ", height=30,
                corner_radius=6,
                fg_color=GOLD if active else CARD,
                text_color="#000" if active else TEXT,
                hover_color="#FFB300" if active else ACTIVE,
                font=ctk.CTkFont(size=12, weight="bold" if active else "normal"),
                command=lambda idx=i: self.select_tab(idx))
            btn.pack(side="left", padx=(0, 4))
            if len(self.tabs) > 1:
                x = ctk.CTkButton(self.tab_bar_inner, text="×", width=24, height=30,
                                  corner_radius=6, fg_color=CARD, hover_color="#4A1A1A",
                                  text_color=MUTED, font=ctk.CTkFont(size=12),
                                  command=lambda idx=i: self.close_tab(idx))
                x.pack(side="left", padx=(0, 8))

    def add_project_tab(self, path):
        if not path:
            return
        path = os.path.abspath(path)
        for i, t in enumerate(self.tabs):
            if t.root == path:
                self.select_tab(i)
                return
        tab = ProjectTab(path)
        self.tabs.append(tab)
        self.active_index = len(self.tabs) - 1
        self._activate_tab()
        self._scan_files(tab)
        self.refresh_sessions(tab)
        self.render_tab_bar()
        self._remember_project(path)

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
        win.geometry("520x440")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()
        ctk.CTkLabel(win, text="Recent projects", text_color=GOLD,
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=16, pady=(14, 4))
        box = ctk.CTkScrollableFrame(win, fg_color=PANEL)
        box.pack(fill="both", expand=True, padx=12, pady=4)
        for p in recents:
            btn = ctk.CTkButton(box, text=p, anchor="w", height=30, fg_color="transparent",
                                hover_color=ACTIVE, text_color=TEXT,
                                font=ctk.CTkFont(size=12),
                                command=lambda path=p: (win.destroy(), self.add_project_tab(path)))
            btn.pack(fill="x", padx=4, pady=2)
        ctk.CTkButton(win, text="📁 Browse…", height=32, fg_color=CARD, hover_color=ACTIVE,
                      text_color=TEXT,
                      command=lambda: (win.destroy(), self._browse_folder())).pack(
            fill="x", padx=12, pady=(6, 14))

    def _browse_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.add_project_tab(path)

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
        self.title(f"Mimo-Agentic IDE — {tab.name}")
        # model
        display = self.models_inventory.get(tab.model, tab.model)
        if display in list(self.model_dropdown.cget("values")):
            self.model_dropdown.set(display)
        else:
            self.model_dropdown.configure(values=list(self.models_inventory.values()))
            self.model_dropdown.set(self.models_inventory.get(tab.model, tab.model))
        # sessions
        self.refresh_sessions(tab, keep_selection=True)
        # tasks
        self.refresh_tasks_panel()
        # files
        self._render_files(tab)
        # editor
        self._restore_editor(tab)
        # transcript
        self._render_transcript(tab)
        # terminal
        self._render_terminal(tab)
        # changes + git (lightweight refresh on switch)
        self.refresh_changes_panel(silent=True)
        self.refresh_git_panel(silent=True)
        # input state
        self._sync_send_button()
        self.img_button.configure(fg_color="green" if tab.attached_image else CARD)

    # -------------------------------------------------------- chat tags --
    def _setup_chat_tags(self):
        tb = self.chat_display._textbox
        tb.tag_configure("goal", foreground="#FFE082", background="#3E3300",
                         font=ctk.CTkFont(size=13, weight="bold"),
                         lmargin1=280, lmargin2=280, rmargin=16, spacing3=8)
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
        tb.tag_configure("bullet", foreground=TEXT, font=ctk.CTkFont(size=13),
                         lmargin1=40, lmargin2=40, spacing3=2)
        tb.tag_configure("code", foreground="#D4D4D4", background="#0D0D0D",
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

        while i < len(lines):
            line = lines[i]
            s = line.strip()
            if s.startswith("```"):
                if in_code:
                    flush_code()
                    in_code = False
                else:
                    flush_para()
                    in_code = True
                i += 1
                continue
            if in_code:
                code_buf.append(line)
                i += 1
                continue
            if s.startswith("#"):
                flush_para()
                lvl = len(s) - len(s.lstrip("#"))
                tb.insert("end", s.lstrip("#").strip() + "\n", "h1" if lvl <= 1 else "h2")
                i += 1
                continue
            if s.startswith(("- ", "* ", "• ")):
                flush_para()
                tb.insert("end", "• " + s[2:] + "\n", "bullet")
                i += 1
                continue
            if not s:
                flush_para()
                i += 1
                continue
            para.append(s)
            i += 1
        flush_para()
        if in_code:
            flush_code()

    def _render_entry(self, tag, text):
        tb = self.chat_display._textbox
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

    def _render_transcript(self, tab):
        self.chat_display.configure(state="normal")
        self.chat_display.delete("1.0", "end")
        self.chat_display.configure(state="disabled")
        for tag, text in tab.transcript[-MAX_TRANSCRIPT:]:
            self._render_entry(tag, text)

    def append_chat(self, text, tag=None, tab=None):
        tab = tab or self.active_tab()
        if tab is None:
            return
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
                with httpx2.Client(timeout=5.0) as client:
                    resp = client.get(OLLAMA_URL.replace("/api/chat", "/api/tags"))
                    resp.raise_for_status()
                    installed = {m["name"].split(":")[0] for m in resp.json().get("models", [])}
                keep = {k: v for k, v in self.models_inventory.items()
                        if k.split(":")[0] in installed}
                if keep and keep != self.models_inventory:
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

    def change_model(self, display):
        tab = self.active_tab()
        if not tab:
            return
        for key, val in self.models_inventory.items():
            if val == display:
                tab.model = key
                self.append_chat(f"🧠 Brain for {tab.name}: {display}", tag="system")
                return

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
        if keep_selection:
            self.sessions_dropdown.set(current or "(new chat)")
        else:
            self.sessions_dropdown.set(current or "(new chat)")

    def on_session_selected(self, label):
        tab = self.active_tab()
        if not tab:
            return
        if label == "(new chat)":
            tab.session_id = None
            return
        sid = tab.session_labels.get(label)
        if sid:
            tab.session_id = sid
            self.append_chat(f"↩ Next message resumes session {sid}", tag="system")
            self._load_session_tasks(tab, sid)

    def _load_session_tasks(self, tab, sid):
        try:
            with open(os.path.join(tab.root, ".agent_sessions", f"{sid}.json"),
                      encoding="utf-8") as f:
                tab.tasks_data = list(json.load(f).get("tasks") or [])
        except (OSError, json.JSONDecodeError):
            tab.tasks_data = []
        if tab is self.active_tab():
            self.after(0, self.refresh_tasks_panel)

    def refresh_tasks_panel(self):
        tab = self.active_tab()
        for w in self.tasks_container.winfo_children():
            w.destroy()
        tasks = tab.tasks_data if tab else []
        done = sum(1 for t in tasks if t.get("status") == "done")
        self.tasks_label.configure(text=f"Tasks · {done}/{len(tasks)} done" if tasks else "Tasks")
        if not tasks:
            ctk.CTkLabel(self.tasks_container, text="No tasks yet", text_color="#6A6A6A",
                         font=ctk.CTkFont(size=12)).pack(anchor="w", padx=8, pady=6)
            return
        colors = {"done": GREEN, "in_progress": GOLD, "pending": MUTED}
        marks = {"done": "☑", "in_progress": "◐", "pending": "☐"}
        for t in tasks:
            status = str(t.get("status") or "pending")
            row = ctk.CTkLabel(self.tasks_container,
                               text=f"{marks.get(status, '☐')} {t.get('title', '')}",
                               anchor="w", justify="left", wraplength=200,
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
            ctk.CTkLabel(box, text="No tasks yet", text_color="#6A6A6A",
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
        self.append_chat(f"🆕 New chat for {tab.name} (old chats saved — pick any to resume).",
                         tag="system")

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

    def _render_files(self, tab):
        for w in self.files_container.winfo_children():
            w.destroy()
        self._scan_files(tab)
        for rel in tab.files:
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
            tab.editor_text = self.editor_box.get("1.0", "end-1c")
        except Exception:
            pass

    def _restore_editor(self, tab):
        self.editor_box.delete("1.0", "end")
        self.editor_box.insert("1.0", tab.editor_text or "")
        self.editor_path_label.configure(text=tab.editor_path or "No file open")

    def open_file(self, rel):
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
        self._restore_editor(tab)
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

    def _render_terminal(self, tab):
        self.terminal_box.configure(state="normal")
        self.terminal_box.delete("1.0", "end")
        if tab.raw_log:
            self.terminal_box.insert("1.0", "\n".join(tab.raw_log[-3000:]) + "\n")
        else:
            self.terminal_box.insert("1.0", "— terminal idle · raw agent output streams here —\n")
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
            self.changes_title.configure(text="Recent changes · not a git repo")
            lbl = ctk.CTkLabel(self.changes_list, text="Run 'Initialize' in Git tab\nto track changes",
                               text_color="#6A6A6A", font=ctk.CTkFont(size=12),
                               justify="left")
            lbl.pack(anchor="w", padx=8, pady=8)
            tab.changed_files = {}
            self._show_diff(None, "")
            return
        entries = [l for l in out.splitlines() if l.strip()]
        self.changes_title.configure(
            text=f"Recent changes · {len(entries)} file{'s' if len(entries) != 1 else ''}")
        tab.changed_files = {}
        if not entries:
            lbl = ctk.CTkLabel(self.changes_list, text="Working tree clean ✓",
                               text_color=GREEN, font=ctk.CTkFont(size=12))
            lbl.pack(anchor="w", padx=8, pady=8)
            self._show_diff(None, "")
            return
        status_colors = {"M": GOLD, "A": GREEN, "D": RED, "??": "#64B5F6", "R": GREEN}
        for e in entries:
            st, path = e[:2], e[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            path = path.strip('"')
            key = st.strip()[0] if st.strip() else "?"
            color = status_colors.get(key, MUTED)
            btn = ctk.CTkButton(self.changes_list, text=f"{st.strip():2} {path}", anchor="w",
                                height=24, fg_color="transparent", hover_color=ACTIVE,
                                text_color=color, font=ctk.CTkFont(family="Menlo", size=11),
                                command=lambda p=path, s=key: self._select_change(p, s))
            btn.pack(fill="x", padx=4, pady=0)
            tab.changed_files[path] = key
        if not silent:
            first = next(iter(tab.changed_files))
            self._select_change(first, tab.changed_files[first])

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
        _c3, log = self._git(tab, "log", "--oneline", "-15")
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
            self.img_button.configure(fg_color="green")

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

    # -------------------------------------------------------- send/stop --
    def send_request(self):
        task = self.user_input.get()
        if not task.strip():
            return
        self.user_input.delete(0, "end")
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
        self._sync_send_button()
        self.render_tab_bar()
        threading.Thread(target=self.agent_loop, args=(tab, task), daemon=True).start()

    def _sync_send_button(self):
        tab = self.active_tab()
        if tab and tab.is_generating:
            self.send_button.configure(text="■ Stop", fg_color=RED, hover_color="#D32F2F",
                                       text_color="#FFF", command=self.stop_generation)
        else:
            self.send_button.configure(text="▶ Run", fg_color=GOLD, text_color="#000",
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
        if stripped.startswith("OK:") or stripped.startswith("exit code: 0"):
            return "observation", stripped
        if stripped.startswith(("plan saved", "Stopped:", "Use /model", "Say 'continue'",
                                "No saved session")):
            return "system", stripped
        return None, line

    def agent_loop(self, tab, goal):
        visual_context = ""
        if tab.attached_image:
            image_path = tab.attached_image
            self.append_chat("👁️ Analyzing image with vision model…", tag="system", tab=tab)
            visual_context = self.describe_image(image_path)
            self.append_chat(f"🖼️ {visual_context}", tag="observation", tab=tab)
            tab.attached_image = None
            if tab is self.active_tab():
                self.after(0, lambda: self.img_button.configure(fg_color=CARD))

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

        self.append_chat(f"◆ Engine ready · {tab.model} · plan → execute → verify → summarize",
                         tag="system", tab=tab)
        cmd = [py, "-u", AGENT_SCRIPT, tab.root, "--model", tab.model, "--yolo", "--plan"]
        if tab.session_id:
            self.append_chat(f"↩ Resuming session {tab.session_id}", tag="system", tab=tab)
            cmd += ["--resume", tab.session_id]
        cmd += ["-p", full_goal]
        try:
            tab.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=tab.root,
                env={**os.environ, "PYTHONUNBUFFERED": "1"})
            for raw in tab.proc.stdout:
                if tab.stop_requested:
                    break
                line = re.sub(r"\x1b\[[0-9;]*m", "", raw).rstrip()
                if not line:
                    continue
                self.append_terminal(line, tab)
                if line.startswith("@@TASKS@@"):
                    display = self._handle_tasks_line(line, tab)
                    if display:
                        self.append_chat(display, tag="activity", tab=tab)
                    continue
                tag, text = self._classify_engine_line(line)
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
        if tab is self.active_tab():
            self.after(0, self._sync_send_button)
        self.after(0, self.render_tab_bar)

    # -------------------------------------------------------- status --
    def _status_tick(self):
        tab = self.active_tab()
        if tab:
            if tab.is_generating:
                queue = f" · queue {len(tab.pending_tasks)}" if tab.pending_tasks else ""
                self.status_bar.configure(text=f"● running · {tab.name} · {tab.model}{queue}",
                                          text_color=GOLD)
            else:
                self.status_bar.configure(text=f"○ idle · {tab.name} · {tab.model}",
                                          text_color=MUTED)
        self.after(1500, self._status_tick)

    def _on_close(self):
        for tab in self.tabs:
            self._stop_tab(tab, silent=True)
        self.destroy()


if __name__ == "__main__":
    app = MimoIDE()
    app.mainloop()
