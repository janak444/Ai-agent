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
import collections

try:
    import customtkinter as ctk
except ImportError:
    _here = os.path.dirname(os.path.abspath(__file__))
    _venv_py = os.path.join(_here, "agent-env", "bin", "python3")
    if not os.path.exists(_venv_py):
        _venv_py = os.path.join(_here, "agent-env", "Scripts", "python.exe")
    if os.path.exists(_venv_py) and os.path.abspath(sys.executable) != os.path.abspath(_venv_py):
        os.execv(_venv_py, [_venv_py] + sys.argv)
    print("❌ Error: 'customtkinter' is not installed in the active environment.")
    print("👉 Activate the virtual environment: source agent-env/bin/activate")
    print("👉 Or install dependencies: pip install customtkinter httpx2 pillow ollama")
    sys.exit(1)
import tkinter as tk
from tkinter import filedialog, TclError as _TclError
import httpx2

# CustomTkinter binds <Configure> on every widget; when panels rebuild their
# button lists (for w in children: w.destroy()), a queued Configure event can
# arrive after destroy and TclError on the dead canvas. Swallow it once here.
_orig_ctk_configure = ctk.CTkBaseClass._update_dimensions_event


def _safe_ctk_configure(self, event):
    try:
        _orig_ctk_configure(self, event)
    except _TclError:
        pass


ctk.CTkBaseClass._update_dimensions_event = _safe_ctk_configure

# ------------------------------------------------------------------ config --
AGENT_SCRIPT = os.environ.get("DEVSOFT_AGENT_SCRIPT",
                              os.environ.get("MIMO_AGENT_SCRIPT",
                                             "/Users/user/Desktop/ai-agent/agent.py"))
OLLAMA_URL = "http://localhost:11434/api/chat"
VISION_MODEL = "llava"
PROJECT_SKIP_DIRS = {'.git', '.vscode', '__pycache__', 'node_modules', 'venv', '.venv',
                     'agent-env', '.idea', '.mypy_cache', '.pytest_cache', '.ruff_cache'}
MAX_TRANSCRIPT = 600
RECENT_PROJECTS_FILE = os.path.expanduser("~/.devsoft_ide_projects.json")
GEOM_FILE = os.path.expanduser("~/.devsoft_ide_geometry.json")
SETTINGS_FILE = os.path.expanduser("~/.devsoft_ide_settings.json")
_LEGACY_FILES = {RECENT_PROJECTS_FILE: "~/.mimo_ide_projects.json",
                 GEOM_FILE: "~/.mimo_ide_geometry.json",
                 SETTINGS_FILE: "~/.mimo_ide_settings.json"}


def _migrate_legacy_files():
    for new_path, old_rel in _LEGACY_FILES.items():
        if os.path.exists(new_path):
            continue
        old_path = os.path.expanduser(old_rel)
        if os.path.exists(old_path):
            try:
                shutil.copy2(old_path, new_path)
            except OSError:
                pass


_migrate_legacy_files()

FREE_CLOUD_MODELS = {
    # Groq (Free Tier: 300 - 500+ tok/s, ultra-fast LPU inference, 0 cost)
    "groq:qwen/qwen3.8-27b": "⚡ Groq: Qwen 3.8 27B (Free · Ultra Fast)",
    "groq:openai/gpt-oss-120b": "⚡ Groq: GPT-OSS 120B (Free · Reasoning)",
    "groq:openai/gpt-oss-20b": "⚡ Groq: GPT-OSS 20B (Free · Fast)",
    # OpenRouter (Permanent Free Tier Models)
    "openrouter:meta-llama/llama-3.3-70b-instruct:free": "⚡ OpenRouter: Llama 3.3 70B (Free)",
    "openrouter:qwen/qwen-2.5-coder-32b-instruct:free": "⚡ OpenRouter: Qwen 2.5 Coder (Free)",
    "openrouter:deepseek/deepseek-r1:free": "⚡ OpenRouter: DeepSeek R1 (Free)",
    # Google Gemini (Google AI Studio Free Tier: 15 RPM, 1M context window)
    "gemini:gemini-2.0-flash": "⚡ Gemini 2.0 Flash (Free · Google AI)",
    "gemini:gemini-1.5-flash": "⚡ Gemini 1.5 Flash (Free · Google AI)",
    # Cerebras (Free Tier: 1M tokens/day at 1000+ tok/s)
    "cerebras:llama3.1-70b": "⚡ Cerebras: Llama 3.1 70B (Free · 1000 tok/s)",
}

CLOUD_PRESETS = {
    "groq": {
        "label": "⚡ Groq (Free · Ultra Fast LPU)",
        "provider": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "key_setting": "groq_api_key",
        "env_var": "GROQ_API_KEY",
        "portal_url": "https://console.groq.com/keys",
    },
    "openrouter": {
        "label": "⚡ OpenRouter (Free Models)",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_setting": "openrouter_api_key",
        "env_var": "OPENROUTER_API_KEY",
        "portal_url": "https://openrouter.ai/keys",
    },
    "gemini": {
        "label": "⚡ Google Gemini (Free AI Studio)",
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_setting": "gemini_api_key",
        "env_var": "GEMINI_API_KEY",
        "portal_url": "https://aistudio.google.com/apikey",
    },
    "cerebras": {
        "label": "⚡ Cerebras (Free 1M tok/day)",
        "provider": "cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "key_setting": "cerebras_api_key",
        "env_var": "CEREBRAS_API_KEY",
        "portal_url": "https://cloud.cerebras.ai",
    },
    "ollama": {
        "label": "💻 Ollama (Local Offline)",
        "provider": "ollama",
        "base_url": "http://127.0.0.1:11434",
        "key_setting": "",
        "env_var": "",
        "portal_url": "https://ollama.com",
    },
}

DEFAULT_SETTINGS = {
    "ollama_host": "http://127.0.0.1:11434",
    "provider": "groq",
    "cloud_base_url": "https://api.groq.com/openai/v1",
    "api_key": "",
    "groq_api_key": "",
    "openrouter_api_key": "",
    "gemini_api_key": "",
    "cerebras_api_key": "",
    "num_ctx": 16384,
    "temperature": 0.2,
    "keep_alive": "60m",
    "auto_approve": True,
    "num_predict": -1,
    "think": False,
    "execution_mode": "fast",
}

BG = "#0D1117"
PANEL = "#161B22"
CARD = "#21262D"
ACTIVE = "#30363D"
GOLD = "#58A6FF"
GOLD_DIM = "#162032"
TEXT = "#E6EDF3"
MUTED = "#8B949E"
GREEN = "#3FB950"
RED = "#F85149"
BLUE = "#58A6FF"
PURPLE = "#BC8CFF"

MAIN_TAB_NAMES = ("Chat", "Editor", "Terminal", "Changes", "Git")

STARTERS = (
    ("⚡  Quick Feature / Edit", "/fast Add a new helper function and test it in this project"),
    ("🧪  Run Tests & Auto-Fix", "/fix Run project tests and resolve any failures"),
    ("📖  Explain Codebase", "/fast Explain the architecture, main modules, and entrypoints"),
    ("🧠  Deep Plan & Build", "/plan Architect and implement a complete feature with step-by-step verification"),
)

_agent_py_cache = {"value": None}
_agent_py_lock = threading.Lock()


def _find_agent_python():
    candidates = [
        os.environ.get("DEVSOFT_AGENT_PY"),
        os.environ.get("MIMO_AGENT_PY"),
        os.path.join(os.getcwd(), "agent-env", "bin", "python3"),
        sys.executable,
        shutil.which("python3"),
        shutil.which("python"),
    ]
    # Priority 1: has httpx (required for Cloud and OmniRoute)
    for cand in candidates:
        if not cand:
            continue
        cand = os.path.expanduser(cand)
        if not os.path.isfile(cand):
            continue
        try:
            r = subprocess.run([cand, "-c", "import httpx"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return cand
        except Exception:
            pass

    # Priority 2: has ollama
    for cand in candidates:
        if not cand:
            continue
        cand = os.path.expanduser(cand)
        if not os.path.isfile(cand):
            continue
        try:
            r = subprocess.run([cand, "-c", "import ollama"], capture_output=True, timeout=5)
            if r.returncode == 0:
                return cand
        except Exception:
            pass

    # Fallback to working python interpreter
    for cand in candidates:
        if not cand:
            continue
        cand = os.path.expanduser(cand)
        if os.path.isfile(cand):
            return cand
    return sys.executable or shutil.which("python3")


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
    return os.path.expanduser(f"~/.devsoft_ide_proj_{h}.json")


def _legacy_project_prefs_path(root):
    h = hashlib.sha256(os.path.abspath(root).encode("utf-8", "replace")).hexdigest()[:16]
    return os.path.expanduser(f"~/.mimo_ide_proj_{h}.json")


def _load_project_prefs(root):
    try:
        with open(_project_prefs_path(root), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        pass
    try:
        with open(_legacy_project_prefs_path(root), encoding="utf-8") as f:
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
        self.model = "groq:qwen/qwen3.8-27b"
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
        self.open_files = []           # open file paths in editor
        self.editor_path = None
        self.editor_text = ""          # content on disk / last saved
        self.editor_buf = None          # live editor buffer (unsaved edits)
        self.editor_widget = None
        self.editor_dirty = False
        self.editor_cursor = "1.0"
        self.inline_preview = None      # ⌘K before-snapshot for diff review
        self.raw_log = []
        self.changed_files = {}
        self.git_root = None
        self.git_branch = ""
        self.git_dirty = 0
        self.git_log = []
        self.shell_history = []
        self.shell_history_idx = -1
        self.shell_running_proc = None
        self.run_started = 0.0
        self.cur_phase = ""
        self.cur_step = ""
        self.cur_action = ""
        self.last_prompt_tokens = 0
        self.last_gen_tokens = 0
        self.total_prompt_tokens = 0
        self.total_gen_tokens = 0
        self.context_files = []
        self.execution_mode = "fast"   # "fast" (direct tool execution) or "architect" (full mission)
        self.prompt_history = []
        self.history_index = -1
        self.expanded_dirs = set()
        self._initial_dirs_expanded = False
        self.sidebar_view = "files"
        self.recent_tool_calls = []
        self.thinking_buf = []
        # live assistant streaming (JSONL delta events from the engine)
        self.stream_buf = None
        self.stream_idx = None
        self.stream_anchor = None
        self.stream_pending = False
        self.render_seq = 0


# --------------------------------------------------------------------- app --
class DevsoftIDE(ctk.CTk):
    MAX_READ_CHARS = 8000

    def __init__(self):
        super().__init__()
        self.title("Devsoft-Agentic IDE")
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
            **FREE_CLOUD_MODELS,
            "qwen3.8:27b-mtp-q4_K_M": "Qwen 3.8 27B (local)",
            "qwen3.8:27b": "Qwen 3.8 (27B local)",
            "qwen3-coder:30b": "Qwen 3 Coder (30B local)",
            "llava:latest": "LLaVA (vision)",
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
        brand = ctk.CTkLabel(self.tab_bar, text="◈ DEVSOFT", text_color=GOLD,
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
        self.sidebar.grid_rowconfigure(3, weight=1)
        self.sidebar.grid_columnconfigure(0, weight=1)

        # Row 0: Project header
        self.project_label = ctk.CTkLabel(self.sidebar, text="PROJECT", text_color=GOLD,
                                          font=ctk.CTkFont(size=13, weight="bold"))
        self.project_label.grid(row=0, column=0, padx=16, pady=(14, 0), sticky="w")
        self.project_path_label = ctk.CTkLabel(self.sidebar, text="", text_color="#666",
                                               font=ctk.CTkFont(size=10), anchor="w")
        self.project_path_label.grid(row=0, column=0, padx=16, pady=(32, 0), sticky="w")

        # Row 1: Brain selector
        brain_bar = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brain_bar.grid(row=1, column=0, padx=12, pady=(10, 4), sticky="ew")
        brain_bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(brain_bar, text="◈ Brain:", text_color=MUTED,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, padx=(4, 6), sticky="w")
        self.model_dropdown = ctk.CTkOptionMenu(
            brain_bar, values=list(self.models_inventory.values()),
            command=self.change_model, fg_color=ACTIVE, button_color=GOLD,
            button_hover_color="#FFB300", text_color=TEXT, dropdown_fg_color=CARD,
            dropdown_text_color=TEXT, height=28)
        self.model_dropdown.grid(row=0, column=1, sticky="ew")

        # Row 2: Segmented View Switcher: Files | Chats | Tasks
        self.sidebar_view_bar = ctk.CTkSegmentedButton(
            self.sidebar,
            values=["📁 Files", "💬 Chats", "✓ Tasks"],
            command=self._on_sidebar_view_change,
            fg_color="#0D1117",
            selected_color=ACTIVE,
            selected_hover_color="#1F2E47",
            unselected_color="#0D1117",
            unselected_hover_color=CARD,
            text_color=TEXT,
            height=28
        )
        self.sidebar_view_bar.grid(row=2, column=0, padx=12, pady=(6, 4), sticky="ew")
        self.sidebar_view_bar.set("📁 Files")

        # Hidden backwards-compatibility dropdown for sessions
        self.sessions_dropdown = ctk.CTkOptionMenu(
            self.sidebar, values=["(new chat)"], command=self.on_session_selected,
            height=0, width=0)

        # Row 3 container: 3 view frames (Files, Chats, Tasks)

        # 1. Files frame (VS Code Explorer)
        self.sidebar_files_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_files_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(2, 6))
        self.sidebar_files_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_files_frame.grid_rowconfigure(2, weight=1)

        files_hdr = ctk.CTkFrame(self.sidebar_files_frame, fg_color="transparent")
        files_hdr.grid(row=0, column=0, sticky="ew", pady=(2, 2))
        files_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(files_hdr, text="◈ EXPLORER", text_color=GOLD,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, sticky="w")
        self.new_file_btn = ctk.CTkButton(files_hdr, text="+", width=22, height=22,
                                          fg_color=CARD, hover_color=ACTIVE, text_color=GOLD,
                                          font=ctk.CTkFont(size=13, weight="bold"),
                                          command=self._new_file_dialog)
        self.new_file_btn.grid(row=0, column=1, padx=(2, 0))
        Tooltip(self.new_file_btn, "New File")
        self.new_folder_btn = ctk.CTkButton(files_hdr, text="📁+", width=26, height=22,
                                            fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
                                            font=ctk.CTkFont(size=10),
                                            command=self._new_folder_dialog)
        self.new_folder_btn.grid(row=0, column=2, padx=(2, 0))
        Tooltip(self.new_folder_btn, "New Folder")
        self.expand_all_btn = ctk.CTkButton(files_hdr, text="⤢", width=22, height=22,
                                            fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
                                            font=ctk.CTkFont(size=11),
                                            command=lambda: self._expand_all_dirs(self.active_tab()))
        self.expand_all_btn.grid(row=0, column=3, padx=(2, 0))
        Tooltip(self.expand_all_btn, "Expand All")
        self.collapse_all_btn = ctk.CTkButton(files_hdr, text="⤡", width=22, height=22,
                                              fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
                                              font=ctk.CTkFont(size=11),
                                              command=lambda: self._collapse_all_dirs(self.active_tab()))
        self.collapse_all_btn.grid(row=0, column=4, padx=(2, 0))
        Tooltip(self.collapse_all_btn, "Collapse All")
        self.search_btn = ctk.CTkButton(files_hdr, text="⌕", width=22, height=22,
                                        fg_color=CARD, hover_color=ACTIVE, text_color=GOLD,
                                        font=ctk.CTkFont(size=12, weight="bold"),
                                        command=self._open_search_panel)
        self.search_btn.grid(row=0, column=5, padx=(2, 0))
        Tooltip(self.search_btn, "Search in Project")
        self.refresh_files_btn = ctk.CTkButton(files_hdr, text="⟳", width=22, height=22,
                                               fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
                                               font=ctk.CTkFont(size=11),
                                               command=lambda: self._render_files(self.active_tab()))
        self.refresh_files_btn.grid(row=0, column=6, padx=(2, 0))
        Tooltip(self.refresh_files_btn, "Refresh")

        self.files_filter = ctk.CTkEntry(self.sidebar_files_frame, height=26, fg_color=CARD,
                                         placeholder_text="Filter files…",
                                         placeholder_text_color="#666", border_color=ACTIVE,
                                         text_color=TEXT)
        self.files_filter.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        self.files_filter.bind("<KeyRelease>", self._on_files_filter)

        self.files_container = ctk.CTkScrollableFrame(self.sidebar_files_frame, fg_color=PANEL)
        self.files_container.grid(row=2, column=0, sticky="nsew", pady=(0, 2))

        # 2. Sessions frame (Antigravity Chat Sessions)
        self.sidebar_sessions_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_sessions_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_sessions_frame.grid_rowconfigure(2, weight=1)

        sess_hdr = ctk.CTkFrame(self.sidebar_sessions_frame, fg_color="transparent")
        sess_hdr.grid(row=0, column=0, sticky="ew", pady=(2, 2))
        sess_hdr.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(sess_hdr, text="◈ CHAT SESSIONS", text_color=GOLD,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, sticky="w")
        self.new_chat_btn = ctk.CTkButton(sess_hdr, text="＋ New", width=64, height=22,
                                          fg_color=GOLD, hover_color="#FFB300", text_color="#000",
                                          font=ctk.CTkFont(size=11, weight="bold"),
                                          command=self.new_chat)
        self.new_chat_btn.grid(row=0, column=1)
        Tooltip(self.new_chat_btn, "Start New Chat (⌘N)")

        self.sessions_filter = ctk.CTkEntry(self.sidebar_sessions_frame, height=26, fg_color=CARD,
                                            placeholder_text="Search chats…",
                                            placeholder_text_color="#666", border_color=ACTIVE,
                                            text_color=TEXT)
        self.sessions_filter.grid(row=1, column=0, sticky="ew", pady=(4, 4))
        self.sessions_filter.bind("<KeyRelease>", lambda _e: self._render_sessions_list(self.active_tab()))

        self.sessions_container = ctk.CTkScrollableFrame(self.sidebar_sessions_frame, fg_color=PANEL)
        self.sessions_container.grid(row=2, column=0, sticky="nsew", pady=(0, 2))

        # 3. Tasks frame
        self.sidebar_tasks_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.sidebar_tasks_frame.grid_columnconfigure(0, weight=1)
        self.sidebar_tasks_frame.grid_rowconfigure(1, weight=1)

        tasks_hdr = ctk.CTkFrame(self.sidebar_tasks_frame, fg_color="transparent")
        tasks_hdr.grid(row=0, column=0, sticky="ew", pady=(2, 2))
        tasks_hdr.grid_columnconfigure(0, weight=1)
        self.tasks_label = ctk.CTkLabel(tasks_hdr, text="◈ TASKS", text_color=GOLD,
                                        font=ctk.CTkFont(size=11, weight="bold"))
        self.tasks_label.grid(row=0, column=0, sticky="w")
        self.tasks_expand_btn = ctk.CTkButton(tasks_hdr, text="⤢", width=30, height=22,
                                              fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                              font=ctk.CTkFont(size=13),
                                              command=self._open_tasks_expanded)
        self.tasks_expand_btn.grid(row=0, column=1, padx=(6, 0))

        self.tasks_container = ctk.CTkScrollableFrame(self.sidebar_tasks_frame, fg_color=PANEL)
        self.tasks_container.grid(row=1, column=0, sticky="nsew", pady=(0, 2))

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
        self.model_badge = ctk.CTkLabel(chat_hdr, text="qwen3.8:27b-mtp-q4_K_M", text_color="#000",
                                        fg_color=GOLD, corner_radius=10, padx=10, pady=2,
                                        font=ctk.CTkFont(size=10, weight="bold"))
        self.model_badge.grid(row=0, column=1, padx=(8, 0))
        self.mode_badge = ctk.CTkLabel(chat_hdr, text="⚡ FAST", text_color="#58A6FF",
                                       fg_color="#162032", corner_radius=10, padx=10, pady=2,
                                       font=ctk.CTkFont(size=10, weight="bold"))
        self.mode_badge.grid(row=0, column=2, padx=(6, 0))
        self.tools_badge = ctk.CTkLabel(chat_hdr, text="", text_color=MUTED,
                                        corner_radius=10, padx=8, pady=2,
                                        font=ctk.CTkFont(size=9, weight="bold"))
        self.tools_badge.grid(row=0, column=3, padx=(4, 0))
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
        self.editor_tab.grid_rowconfigure(2, weight=1)
        ebar = ctk.CTkFrame(self.editor_tab, fg_color="transparent")
        ebar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
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

        # Open file tabs bar
        self.editor_tabs_frame = ctk.CTkScrollableFrame(self.editor_tab, height=34,
                                                        orientation="horizontal", fg_color=PANEL)
        self.editor_tabs_frame.grid(row=1, column=0, sticky="ew", pady=(0, 4))

        # Editor content
        editor_wrap = ctk.CTkFrame(self.editor_tab, fg_color="#0D1117", corner_radius=0)
        editor_wrap.grid(row=2, column=0, sticky="nsew")
        editor_wrap.grid_columnconfigure(1, weight=1)
        editor_wrap.grid_rowconfigure(0, weight=1)
        self.editor_gutter = ctk.CTkTextbox(editor_wrap, width=52, fg_color="#080C10",
                                            text_color="#555", wrap="none",
                                            font=ctk.CTkFont(family="Menlo", size=13),
                                            state="disabled", activate_scrollbars=False)
        self.editor_gutter.grid(row=0, column=0, sticky="nsw")
        self.editor_box = ctk.CTkTextbox(editor_wrap, fg_color="#0D1117", text_color="#E6EDF3",
                                         font=ctk.CTkFont(family="Menlo", size=13),
                                         wrap="none")
        self.editor_box.grid(row=0, column=1, sticky="nsew")
        self.editor_box.bind("<KeyRelease>", self._on_editor_changed, add="+")
        self.editor_box.bind("<ButtonRelease-1>", self._on_editor_cursor_moved, add="+")
        self.editor_box.bind("<MouseWheel>", self._on_editor_scroll, add="+")
        self.editor_box.bind("<Button-4>", self._on_editor_scroll, add="+")
        self.editor_box.bind("<Button-5>", self._on_editor_scroll, add="+")
        self.editor_box._textbox.configure(tabs=())
        self._setup_editor_tags()

        # Editor status bar
        self.editor_status_bar = ctk.CTkFrame(self.editor_tab, height=24, fg_color="#080C10", corner_radius=0)
        self.editor_status_bar.grid(row=3, column=0, sticky="ew", pady=(2, 0))
        self.editor_pos_label = ctk.CTkLabel(self.editor_status_bar, text="Ln 1, Col 1", text_color=MUTED,
                                             font=ctk.CTkFont(family="Menlo", size=10))
        self.editor_pos_label.pack(side="left", padx=(10, 16), pady=2)
        self.editor_lang_label = ctk.CTkLabel(self.editor_status_bar, text="Plain Text", text_color=GOLD,
                                              font=ctk.CTkFont(family="Menlo", size=10))
        self.editor_lang_label.pack(side="right", padx=(0, 12), pady=2)
        self.editor_enc_label = ctk.CTkLabel(self.editor_status_bar, text="UTF-8", text_color=MUTED,
                                             font=ctk.CTkFont(family="Menlo", size=10))
        self.editor_enc_label.pack(side="right", padx=(0, 16), pady=2)
        self.editor_spaces_label = ctk.CTkLabel(self.editor_status_bar, text="Spaces: 4", text_color=MUTED,
                                                font=ctk.CTkFont(family="Menlo", size=10))
        self.editor_spaces_label.pack(side="right", padx=(0, 16), pady=2)

        # find/replace bar (hidden until ⌘F)
        self.find_bar = ctk.CTkFrame(self.editor_tab, fg_color=CARD, corner_radius=8)
        self.find_bar.grid(row=4, column=0, sticky="ew", pady=(4, 0))
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
        self.goto_bar.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        ctk.CTkLabel(self.goto_bar, text="Go to line", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(10, 6))
        self.goto_entry = ctk.CTkEntry(self.goto_bar, width=80, height=28, fg_color=BG,
                                       border_color=ACTIVE, text_color=TEXT)
        self.goto_entry.pack(side="left", pady=6)
        self.goto_entry.bind("<Return>", lambda _e: self.goto_line())
        self.goto_bar.grid_remove()

        # inline edit bar (⌘K) — select code, ask for a change
        self.inline_bar = ctk.CTkFrame(self.editor_tab, fg_color=CARD, corner_radius=8)
        self.inline_bar.grid(row=6, column=0, sticky="ew", pady=(4, 0))
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
        ctk.CTkLabel(tbar, text="◈ DIAGNOSTICS & LOG STREAM", text_color=GOLD,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, sticky="w")
        self.terminal_lines_lbl = ctk.CTkLabel(tbar, text="0 lines", text_color=MUTED,
                                               font=ctk.CTkFont(size=11))
        self.terminal_lines_lbl.grid(row=0, column=1, padx=(6, 8), sticky="w")
        self.terminal_filter = ctk.CTkEntry(tbar, width=140, height=26, fg_color=CARD,
                                            placeholder_text="Filter logs…",
                                            placeholder_text_color="#666", border_color=ACTIVE,
                                            text_color=TEXT)
        self.terminal_filter.grid(row=0, column=2, padx=(0, 8))
        self.terminal_filter.bind("<KeyRelease>", self._on_terminal_filter)
        self.terminal_copy_btn = ctk.CTkButton(tbar, text="📋 Copy", width=70, height=26,
                                               fg_color=CARD, hover_color=ACTIVE,
                                               text_color=TEXT, command=self._copy_terminal_output)
        self.terminal_copy_btn.grid(row=0, column=3, padx=(0, 6))
        Tooltip(self.terminal_copy_btn, "Copy all terminal logs to clipboard")
        self.run_tests_btn = ctk.CTkButton(tbar, text="🧪 Run tests", width=100, height=26,
                                           fg_color=CARD, hover_color=ACTIVE,
                                           text_color=TEXT, command=self.run_tests)
        self.run_tests_btn.grid(row=0, column=4, padx=(0, 6))
        Tooltip(self.run_tests_btn, "Auto-detect and run the project's test suite")
        self.terminal_clear_btn = ctk.CTkButton(tbar, text="Clear", width=70, height=26,
                                                fg_color=CARD, hover_color=ACTIVE,
                                                text_color=TEXT, command=self._clear_terminal)
        self.terminal_clear_btn.grid(row=0, column=5)
        self.terminal_box = ctk.CTkTextbox(self.terminal_tab, fg_color="#0D1117",
                                           text_color="#C9D1D9",
                                           font=ctk.CTkFont(family="Menlo", size=12),
                                           wrap="char")
        self.terminal_box.grid(row=1, column=0, sticky="nsew")
        self.terminal_box.configure(state="disabled")

        # Shell tab — interactive command console with live subprocess streaming
        self.shell_tab.grid_columnconfigure(0, weight=1)
        self.shell_tab.grid_rowconfigure(1, weight=1)
        sbar = ctk.CTkFrame(self.shell_tab, fg_color="transparent")
        sbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        sbar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(sbar, text="◈ INTERACTIVE CONSOLE", text_color=GOLD,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, sticky="w")
        self.shell_cwd_label = ctk.CTkLabel(sbar, text="", text_color=MUTED,
                                            font=ctk.CTkFont(family="Menlo", size=11), anchor="w")
        self.shell_cwd_label.grid(row=0, column=1, padx=(10, 8), sticky="w")
        self.shell_status_badge = ctk.CTkLabel(sbar, text="● IDLE", text_color=GREEN,
                                               fg_color="#122619", corner_radius=6,
                                               padx=8, pady=2,
                                               font=ctk.CTkFont(size=10, weight="bold"))
        self.shell_status_badge.grid(row=0, column=2, padx=(0, 8))
        self.shell_clear_btn = ctk.CTkButton(sbar, text="Clear", width=70, height=26,
                                             fg_color=CARD, hover_color=ACTIVE,
                                             text_color=TEXT, command=self._shell_clear)
        self.shell_clear_btn.grid(row=0, column=3)
        self.shell_box = ctk.CTkTextbox(self.shell_tab, fg_color="#0A0D12",
                                        text_color="#D4D4D4",
                                        font=ctk.CTkFont(family="Menlo", size=12),
                                        wrap="char")
        self.shell_box.grid(row=1, column=0, sticky="nsew")
        self._setup_shell_tags()

        # Shell command input row
        self.shell_cmd_bar = ctk.CTkFrame(self.shell_tab, fg_color=CARD, corner_radius=8, height=38)
        self.shell_cmd_bar.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.shell_cmd_bar.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.shell_cmd_bar, text="➜ $", text_color=GOLD,
                     font=ctk.CTkFont(family="Menlo", size=13, weight="bold")).grid(row=0, column=0, padx=(10, 6), pady=6)
        self.shell_entry = ctk.CTkEntry(self.shell_cmd_bar, height=30, fg_color=BG,
                                        border_color=ACTIVE, text_color=TEXT,
                                        placeholder_text="Enter shell command (e.g. ls, git status, pytest)...")
        self.shell_entry.grid(row=0, column=1, sticky="ew", pady=6)
        self.shell_entry.bind("<Return>", lambda _e: self.run_shell_command())
        self.shell_entry.bind("<Up>", self.on_shell_history_up)
        self.shell_entry.bind("<Down>", self.on_shell_history_down)
        self.shell_run_btn = ctk.CTkButton(self.shell_cmd_bar, text="▶ Run", width=70, height=30,
                                           fg_color=GOLD, hover_color="#FFB300", text_color="#000",
                                           font=ctk.CTkFont(size=12, weight="bold"),
                                           command=self.run_shell_command)
        self.shell_run_btn.grid(row=0, column=2, padx=(6, 4), pady=6)
        self.shell_kill_btn = ctk.CTkButton(self.shell_cmd_bar, text="■ Stop", width=70, height=30,
                                            fg_color="#4A1A1A", hover_color="#5C2222", text_color=RED,
                                            font=ctk.CTkFont(size=12, weight="bold"),
                                            command=self.shell_kill_running)
        self.shell_kill_btn.grid(row=0, column=3, padx=(0, 8), pady=6)
        self.shell_proc = None

        # Changes tab
        self.changes_tab.grid_columnconfigure(0, weight=1)
        self.changes_tab.grid_rowconfigure(1, weight=1)
        cbar = ctk.CTkFrame(self.changes_tab, fg_color="transparent")
        cbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        cbar.grid_columnconfigure(0, weight=1)
        self.changes_title = ctk.CTkLabel(cbar, text="Working tree", text_color=GOLD,
                                          font=ctk.CTkFont(size=12, weight="bold"))
        self.changes_title.grid(row=0, column=0, sticky="w")
        self.changes_stage_all_btn = ctk.CTkButton(cbar, text="+ Stage all", width=90, height=26,
                                                   fg_color=CARD, hover_color=ACTIVE,
                                                   text_color=TEXT, command=self.git_stage_all)
        self.changes_stage_all_btn.grid(row=0, column=1, padx=(8, 0))
        self.changes_revert_all_btn = ctk.CTkButton(cbar, text="↩ Revert all", width=90, height=26,
                                                    fg_color="#4A1A1A", hover_color="#5C2222",
                                                    text_color=RED, command=self._revert_all_changes)
        self.changes_revert_all_btn.grid(row=0, column=2, padx=(6, 0))
        self.changes_refresh_btn = ctk.CTkButton(cbar, text="⟳ Refresh", width=90, height=26,
                                                 fg_color=CARD, hover_color=ACTIVE,
                                                 text_color=TEXT, command=self.refresh_changes_panel)
        self.changes_refresh_btn.grid(row=0, column=3, padx=(6, 0))
        changes_split = ctk.CTkFrame(self.changes_tab, fg_color="transparent")
        changes_split.grid(row=1, column=0, sticky="nsew")
        changes_split.grid_columnconfigure(1, weight=1)
        changes_split.grid_rowconfigure(0, weight=1)
        self.changes_list = ctk.CTkScrollableFrame(changes_split, width=280, fg_color=PANEL)
        self.changes_list.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.diff_box = ctk.CTkTextbox(changes_split, fg_color="#0D1117", text_color="#E6EDF3",
                                       font=ctk.CTkFont(family="Menlo", size=12), wrap="none")
        self.diff_box.grid(row=0, column=1, sticky="nsew")
        self.diff_box.configure(state="disabled")

        # Git tab
        self.git_tab.grid_columnconfigure(0, weight=1)
        self.git_tab.grid_rowconfigure(4, weight=1)
        gbar = ctk.CTkFrame(self.git_tab, fg_color="transparent")
        gbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        gbar.grid_columnconfigure(0, weight=1)
        self.git_status_label = ctk.CTkLabel(gbar, text="No git repository connected",
                                             text_color=MUTED, font=ctk.CTkFont(size=12),
                                             anchor="w")
        self.git_status_label.grid(row=0, column=0, sticky="w")
        self.git_branch_var = ctk.StringVar(value="")
        self.git_branch_menu = ctk.CTkOptionMenu(gbar, values=["(branch)"],
                                                 variable=self.git_branch_var,
                                                 command=self._on_branch_select,
                                                 fg_color=ACTIVE, button_color=GOLD,
                                                 button_hover_color="#FFB300",
                                                 text_color=TEXT, dropdown_fg_color=CARD,
                                                 dropdown_text_color=TEXT, height=28, width=130)
        self.git_branch_menu.grid(row=0, column=1, padx=(6, 0))
        self.git_new_branch_btn = ctk.CTkButton(gbar, text="＋ Branch", width=74, height=28,
                                                fg_color=CARD, hover_color=ACTIVE, text_color=GOLD,
                                                font=ctk.CTkFont(size=11, weight="bold"),
                                                command=self._new_branch_dialog)
        self.git_new_branch_btn.grid(row=0, column=2, padx=(6, 0))
        self.git_refresh_btn = ctk.CTkButton(gbar, text="⟳ Sync", width=74, height=28,
                                             fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                             command=self.refresh_git_panel)
        self.git_refresh_btn.grid(row=0, column=3, padx=(6, 0))
        self.git_init_btn = ctk.CTkButton(gbar, text="Initialize", width=86, height=28,
                                          fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                          command=self.git_init_repo)
        self.git_init_btn.grid(row=0, column=4, padx=(6, 0))

        # Git quick prefix bar
        self.git_prefix_bar = ctk.CTkFrame(self.git_tab, fg_color="transparent")
        self.git_prefix_bar.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkLabel(self.git_prefix_bar, text="Type:", text_color=MUTED,
                     font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))
        for pfx in ["feat:", "fix:", "docs:", "style:", "refactor:", "test:", "chore:"]:
            b = ctk.CTkButton(self.git_prefix_bar, text=pfx, width=48, height=22,
                              fg_color=CARD, hover_color=ACTIVE, text_color=GOLD,
                              font=ctk.CTkFont(family="Menlo", size=10),
                              command=lambda p=pfx: self._apply_git_prefix(p))
            b.pack(side="left", padx=(0, 4))

        # Git actions row (commit message + action buttons)
        git_actions = ctk.CTkFrame(self.git_tab, fg_color="transparent")
        git_actions.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        git_actions.grid_columnconfigure(0, weight=1)
        self.git_commit_msg = ctk.CTkEntry(git_actions, height=32, fg_color=CARD,
                                           placeholder_text="Commit message… (⌘Enter to commit)",
                                           placeholder_text_color=MUTED, border_color=ACTIVE,
                                           text_color=TEXT)
        self.git_commit_msg.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.git_commit_msg.bind("<Return>", lambda _e: self.git_commit_all())
        self.git_commit_btn = ctk.CTkButton(git_actions, text="✓ Commit", width=90, height=32,
                                            fg_color=GOLD, hover_color="#FFB300", text_color="#000",
                                            font=ctk.CTkFont(size=12, weight="bold"),
                                            command=self.git_commit_all)
        self.git_commit_btn.grid(row=0, column=1, padx=(0, 6))
        for idx, (text, cmd, tip) in enumerate([("Stage all", self.git_stage_all, "git add -A"),
                                                ("Pull", self.git_pull, "git pull"),
                                                ("Push", self.git_push, "git push")]):
            b = ctk.CTkButton(git_actions, text=text, width=80, height=32,
                              fg_color=CARD, hover_color=ACTIVE, text_color=TEXT, command=cmd)
            b.grid(row=0, column=2 + idx, padx=(0, 4))
            Tooltip(b, tip)

        # Git commit history log
        git_log_wrap = ctk.CTkFrame(self.git_tab, fg_color="transparent")
        git_log_wrap.grid(row=4, column=0, sticky="nsew")
        git_log_wrap.grid_columnconfigure(0, weight=1)
        git_log_wrap.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(git_log_wrap, text="◈ RECENT COMMITS", text_color=GOLD,
                     font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, sticky="w")
        self.git_log_box = ctk.CTkTextbox(git_log_wrap, fg_color="#0D1117", text_color="#E6EDF3",
                                          font=ctk.CTkFont(family="Menlo", size=12))
        self.git_log_box.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.git_log_box.configure(state="disabled")

        # --- input area ---
        self.input_frame = ctk.CTkFrame(self.main, fg_color=BG, corner_radius=0)
        self.input_frame.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))
        self.input_frame.grid_columnconfigure(0, weight=1)

        # live work card — in-place status while the agent runs (hidden when idle)
        self.work_card = ctk.CTkFrame(self.input_frame, fg_color=CARD, corner_radius=10)
        self.work_card.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 6))
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
        self.chip_frame.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(0, 6))
        self.chip_frame.grid_remove()
        self.chip_label = ctk.CTkLabel(self.chip_frame, text="", text_color=TEXT,
                                       font=ctk.CTkFont(size=11))
        self.chip_label.pack(side="left", padx=(10, 4), pady=4)
        self.chip_clear_btn = ctk.CTkButton(self.chip_frame, text="✕", width=24, height=20,
                                            fg_color="transparent", hover_color="#4A1A1A",
                                            text_color=MUTED, command=self._clear_attachment)
        self.chip_clear_btn.pack(side="left", padx=(0, 8), pady=4)

        # Quick Actions Bar
        self.action_bar = ctk.CTkFrame(self.input_frame, fg_color="transparent", height=28)
        self.action_bar.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(0, 6))

        self.mode_toggle_btn = ctk.CTkButton(
            self.action_bar, text="⚡ Fast Mode", width=110, height=26,
            fg_color="#162032", hover_color="#1F2E47", text_color="#58A6FF",
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.toggle_execution_mode)
        self.mode_toggle_btn.pack(side="left", padx=(0, 6))
        Tooltip(self.mode_toggle_btn, "Switch mode: ⚡ Fast (direct execution) ⟷ 🧠 Architect (deep mission plan)")

        self.active_file_btn = ctk.CTkButton(
            self.action_bar, text="📎 No file open", width=120, height=26,
            fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
            font=ctk.CTkFont(family="Menlo", size=10),
            command=self._insert_active_file_mention)
        self.active_file_btn.pack(side="left", padx=(0, 6))
        Tooltip(self.active_file_btn, "Attach currently open editor file to your prompt (@file)")

        self.clear_chat_btn = ctk.CTkButton(
            self.action_bar, text="🧹 Clear", width=60, height=26,
            fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
            font=ctk.CTkFont(size=11), command=self.clear_current_chat)
        self.clear_chat_btn.pack(side="right", padx=(4, 0))
        Tooltip(self.clear_chat_btn, "Clear chat conversation (/clear)")

        self.quick_diff_btn = ctk.CTkButton(
            self.action_bar, text="⎇ Changes", width=75, height=26,
            fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
            font=ctk.CTkFont(size=11),
            command=lambda: (self.main_tabs.set("Changes"), self.refresh_changes_panel()))
        self.quick_diff_btn.pack(side="right", padx=(4, 0))
        Tooltip(self.quick_diff_btn, "View project changes and git diff (/diff)")

        self.quick_test_btn = ctk.CTkButton(
            self.action_bar, text="🧪 Run Tests", width=85, height=26,
            fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
            font=ctk.CTkFont(size=11), command=self.run_tests)
        self.quick_test_btn.pack(side="right", padx=(4, 0))
        Tooltip(self.quick_test_btn, "Run project test suite (/test)")

        self.think_toggle_btn = ctk.CTkButton(
            self.action_bar, text="💭 Think: Off", width=85, height=26,
            fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
            font=ctk.CTkFont(size=10), command=self.toggle_think_mode)
        self.think_toggle_btn.pack(side="right", padx=(4, 0))
        Tooltip(self.think_toggle_btn, "Toggle model thinking reasoning mode (off = fastest)")

        input_wrap = ctk.CTkFrame(self.input_frame, fg_color=CARD, corner_radius=10)
        input_wrap.grid(row=3, column=0, sticky="ew", padx=(0, 8))
        input_wrap.grid_columnconfigure(0, weight=1)
        self.user_input = ctk.CTkTextbox(input_wrap, height=52, fg_color="transparent",
                                         text_color=TEXT, wrap="word",
                                         font=ctk.CTkFont(size=13), corner_radius=10)
        self.user_input.grid(row=0, column=0, sticky="nsew", padx=(12, 4), pady=6)
        input_wrap.grid_rowconfigure(0, weight=1)
        self.user_input.bind("<Return>", self._on_input_return)
        self.user_input.bind("<Shift-Return>", self._on_input_shift_return)
        self.user_input.bind("<KeyRelease>", self._on_input_keyrelease, add="+")
        self.user_input.bind("<Up>", self._on_input_up)
        self.user_input.bind("<Down>", self._on_input_down)
        self.user_input.bind("<FocusIn>", self._on_input_focus_in, add="+")
        self.user_input.bind("<FocusOut>", self._on_input_focus_out, add="+")
        self.user_input._textbox.bind("<Button-1>", self._on_input_click, add="+")
        self.user_input.bind("<Command-v>", self._on_input_paste, add="+")
        input_wrap.bind("<Button-1>", lambda _e: self.user_input.focus_set())
        self.input_hint = ctk.CTkLabel(input_wrap,
                                       text="Ask Antigravity to build, edit, or fix…   "
                                            "⏎ run  ·  ⇧⏎ newline  ·  ↑ history  ·  / commands",
                                       text_color="#666", font=ctk.CTkFont(size=12),
                                       anchor="w")
        self.input_hint.place(relx=0, rely=0.5, anchor="w", x=14)
        self.input_hint.lower()
        self.input_hint.bind("<Button-1>", lambda _e: self._focus_input())

        self.undo_button = ctk.CTkButton(self.input_frame, text="↩", width=38, height=48,
                                         fg_color=CARD, hover_color=ACTIVE, text_color=MUTED,
                                         command=self.gui_undo)
        self.undo_button.grid(row=3, column=1, padx=(0, 6))
        Tooltip(self.undo_button, "Undo last agent file change")

        self.img_button = ctk.CTkButton(self.input_frame, text="🖼", width=38, height=48,
                                        fg_color=CARD, hover_color=ACTIVE, text_color=TEXT,
                                        command=self.upload_image)
        self.img_button.grid(row=3, column=2, padx=(0, 6))
        Tooltip(self.img_button, "Attach an image for vision model  (⌘V paste)")

        self.send_button = ctk.CTkButton(self.input_frame, text="⚡  Run", width=110, height=48,
                                         fg_color=GOLD, text_color="#000", hover_color="#388BFD",
                                         font=ctk.CTkFont(weight="bold"), command=self.send_request)
        self.send_button.grid(row=3, column=3)
        Tooltip(self.send_button, "Send to agent  (⏎ or ⌘⏎)")

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
        self._show_sidebar_files()

    def _build_welcome(self):
        inner = ctk.CTkFrame(self.welcome_frame, fg_color="transparent")
        inner.place(relx=0.5, rely=0.4, anchor="center")
        ctk.CTkLabel(inner, text="◈ Devsoft-Agentic IDE", text_color=GOLD,
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
        import webbrowser
        win = ctk.CTkToplevel(self)
        win.title("Settings")
        win.geometry("560x680")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()
        ctk.CTkLabel(win, text="⚙ Devsoft Settings", text_color=GOLD,
                     font=ctk.CTkFont(size=17, weight="bold")).pack(anchor="w", padx=18, pady=(16, 10))
        form = ctk.CTkScrollableFrame(win, fg_color=PANEL)
        form.pack(fill="both", expand=True, padx=14, pady=4)

        s = self.settings
        entries = {}

        # --- Section 1: Cloud Providers (Free & Fast) ---
        cloud_card = ctk.CTkFrame(form, fg_color=CARD, corner_radius=8)
        cloud_card.pack(fill="x", padx=6, pady=8)
        ctk.CTkLabel(cloud_card, text="☁ Cloud AI Providers (Free & Ultra Fast)",
                     text_color=GOLD, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(cloud_card,
                     text="Free cloud models respond in milliseconds with no local GPU/RAM required.",
                     text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=(0, 8))

        preset_labels = [
            "⚡ Groq (Free · Ultra Fast 300-500 tok/s)",
            "⚡ OpenRouter (Free Tier Models)",
            "⚡ Google Gemini (Free AI Studio)",
            "⚡ Cerebras (Free 1M tok/day)",
            "💻 Ollama (Local Offline)",
            "🌐 Custom OpenAI-compatible",
        ]
        preset_map = {
            "⚡ Groq (Free · Ultra Fast 300-500 tok/s)": "groq",
            "⚡ OpenRouter (Free Tier Models)": "openrouter",
            "⚡ Google Gemini (Free AI Studio)": "gemini",
            "⚡ Cerebras (Free 1M tok/day)": "cerebras",
            "💻 Ollama (Local Offline)": "ollama",
            "🌐 Custom OpenAI-compatible": "cloud",
        }
        rev_preset_map = {v: k for k, v in preset_map.items()}

        current_prov = s.get("provider", "groq")
        curr_preset_label = rev_preset_map.get(current_prov, preset_labels[0])

        p_row = ctk.CTkFrame(cloud_card, fg_color="transparent")
        p_row.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(p_row, text="Active Provider:", text_color=TEXT,
                     font=ctk.CTkFont(size=11, weight="bold")).pack(side="left")

        url_entry = ctk.CTkEntry(cloud_card, height=28, fg_color="#10141A", border_color=ACTIVE, text_color=TEXT)

        def on_preset_select(choice):
            prov = preset_map.get(choice, "groq")
            if prov in CLOUD_PRESETS:
                url_entry.delete(0, "end")
                url_entry.insert(0, CLOUD_PRESETS[prov]["base_url"])

        preset_menu = ctk.CTkOptionMenu(
            p_row, values=preset_labels, command=on_preset_select,
            fg_color=ACTIVE, button_color=GOLD, text_color=TEXT, dropdown_fg_color=CARD,
            height=28, width=280)
        preset_menu.set(curr_preset_label)
        preset_menu.pack(side="right")

        u_row = ctk.CTkFrame(cloud_card, fg_color="transparent")
        u_row.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(u_row, text="Cloud Base URL:", text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w")
        url_entry.insert(0, str(s.get("cloud_base_url", "https://api.groq.com/openai/v1")))
        url_entry.pack(fill="x", padx=12, pady=(2, 8))
        entries["cloud_base_url"] = ("entry", url_entry)

        # Provider API Key fields with clickable links
        def add_key_field(parent, label, key_name, portal_url):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=3)
            hdr = ctk.CTkFrame(row, fg_color="transparent")
            hdr.pack(fill="x")
            ctk.CTkLabel(hdr, text=label, text_color=TEXT, font=ctk.CTkFont(size=11)).pack(side="left")
            if portal_url:
                link_btn = ctk.CTkButton(
                    hdr, text="Get Free Key ↗", width=85, height=20, fg_color="#1E2A3A",
                    hover_color=ACTIVE, text_color=GOLD, font=ctk.CTkFont(size=10, weight="bold"),
                    command=lambda: webbrowser.open(portal_url))
                link_btn.pack(side="right")
            e = ctk.CTkEntry(row, height=28, fg_color="#10141A", border_color=ACTIVE, text_color=TEXT, show="*")
            val = s.get(key_name, "")
            if val:
                e.insert(0, str(val))
            e.pack(fill="x", pady=(2, 4))
            entries[key_name] = ("entry", e)

        add_key_field(cloud_card, "Groq API Key (300+ tok/s free)", "groq_api_key", "https://console.groq.com/keys")
        add_key_field(cloud_card, "OpenRouter API Key (Free tier models)", "openrouter_api_key", "https://openrouter.ai/keys")
        add_key_field(cloud_card, "Google Gemini API Key (AI Studio 15 RPM)", "gemini_api_key", "https://aistudio.google.com/apikey")
        add_key_field(cloud_card, "Cerebras API Key (1,000 tok/s free)", "cerebras_api_key", "https://cloud.cerebras.ai")
        add_key_field(cloud_card, "Custom / Other API Key", "api_key", "")

        # --- Section 2: Local & Engine Options ---
        eng_card = ctk.CTkFrame(form, fg_color=CARD, corner_radius=8)
        eng_card.pack(fill="x", padx=6, pady=8)
        ctk.CTkLabel(eng_card, text="⚙ Engine & Execution Options",
                     text_color=GOLD, font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=12, pady=(10, 6))

        def add_row(parent, label, key, tip=""):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=5)
            ctk.CTkLabel(row, text=label, text_color=TEXT,
                         font=ctk.CTkFont(size=11), anchor="w").pack(anchor="w")
            if tip:
                ctk.CTkLabel(row, text=tip, text_color=MUTED,
                             font=ctk.CTkFont(size=10), anchor="w").pack(anchor="w")
            val = s.get(key, DEFAULT_SETTINGS.get(key, ""))
            if isinstance(val, bool):
                w = ctk.CTkSwitch(row, text="enabled" if val else "disabled",
                                  variable=ctk.BooleanVar(value=val),
                                  fg_color=ACTIVE, progress_color=GOLD, text_color=TEXT)
                w.pack(anchor="w", pady=(2, 0))
                entries[key] = ("switch", w)
            else:
                e = ctk.CTkEntry(row, height=28, fg_color="#10141A", border_color=ACTIVE,
                                 text_color=TEXT)
                e.insert(0, str(val))
                e.pack(fill="x", pady=(2, 0))
                entries[key] = ("entry", e)

        add_row(eng_card, "Ollama host (Local)", "ollama_host", "Where your Ollama server runs (default: http://127.0.0.1:11434)")
        add_row(eng_card, "Context window (num_ctx)", "num_ctx", "Larger = more memory, better long files (e.g. 16384)")
        add_row(eng_card, "Temperature", "temperature", "Lower = more deterministic code (default: 0.2)")
        add_row(eng_card, "Model thinking mode", "think",
                "Deep reasoning before answering (off = fastest answers)")
        add_row(eng_card, "Auto-approve actions", "auto_approve", "Skip per-tool confirmation")

        if self.ram_gb:
            ctk.CTkLabel(eng_card, text=f"Detected RAM: {self.ram_gb:.0f} GB",
                         text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=(6, 0))
            tip = self._ram_model_tip(self.ram_gb)
            if tip:
                ctk.CTkLabel(eng_card, text=tip, text_color=BLUE, font=ctk.CTkFont(size=11),
                             wraplength=440, justify="left").pack(anchor="w", padx=12, pady=(2, 10))

        def save():
            selected_choice = preset_menu.get()
            chosen_prov = preset_map.get(selected_choice, "groq")
            s["provider"] = chosen_prov
            for key, (kind, w) in entries.items():
                if kind == "switch":
                    s[key] = bool(w.get())
                else:
                    raw = w.get().strip()
                    old = s.get(key, DEFAULT_SETTINGS.get(key, ""))
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
            self.append_chat(f"⚙ Settings saved · Active provider: {chosen_prov.title()}", tag="success")
            self.refresh_available_models()

        ctk.CTkButton(win, text="Save Settings", height=36, fg_color=GOLD, text_color="#000",
                      hover_color="#FFB300", font=ctk.CTkFont(weight="bold"),
                      command=save).pack(fill="x", padx=14, pady=(8, 14))

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
        self.title(f"Devsoft-Agentic IDE — {tab.name}")
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
        self._render_editor_tabs(tab)
        self._render_transcript(tab)
        self._render_terminal(tab)
        self._update_shell_cwd()
        self.refresh_changes_panel(silent=True)
        self.refresh_git_panel(silent=True)
        self._sync_send_button()
        self._sync_attachment_ui()
        self._update_mode_ui()
        self._update_active_file_ui()
        v = getattr(tab, "sidebar_view", "files")
        if v == "sessions":
            self.sidebar_view_bar.set("💬 Chats")
            self._show_sidebar_sessions()
        elif v == "tasks":
            self.sidebar_view_bar.set("✓ Tasks")
            self._show_sidebar_tasks()
        else:
            self.sidebar_view_bar.set("📁 Files")
            self._show_sidebar_files()
        # keep the live work card in sync with this tab's run state
        if tab.is_generating:
            self._work_card_render(tab)
        else:
            self.work_card.grid_remove()

    # -------------------------------------------------------- chat tags --
    def _setup_chat_tags(self):
        tb = self.chat_display._textbox
        tb.tag_configure("goal", foreground="#F0F6FC", background="#162032",
                         font=ctk.CTkFont(size=13),
                         lmargin1=18, lmargin2=18, rmargin=24, spacing3=8, spacing1=4)
        tb.tag_configure("user_hdr", foreground="#79C0FF",
                         font=ctk.CTkFont(size=11, weight="bold"),
                         lmargin1=18, spacing1=10, spacing3=3)
        tb.tag_configure("assistant", foreground="#E6EDF3", font=ctk.CTkFont(size=13),
                         lmargin1=18, lmargin2=18, rmargin=24, spacing3=8, spacing1=2)
        tb.tag_configure("asst_hdr", foreground=GOLD,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         lmargin1=18, spacing1=12, spacing3=3)
        tb.tag_configure("system", foreground=MUTED, font=ctk.CTkFont(size=11),
                         lmargin1=18, spacing3=4)
        tb.tag_configure("activity", foreground=GREEN, font=ctk.CTkFont(size=12, weight="bold"),
                         lmargin1=18, spacing3=2)
        tb.tag_configure("tool_start", foreground="#79C0FF", background="#161B22",
                         font=ctk.CTkFont(family="Menlo", size=11, weight="bold"),
                         lmargin1=24, lmargin2=24, rmargin=24, spacing1=4, spacing3=2)
        tb.tag_configure("tool_success", foreground="#7EE787", background="#122619",
                         font=ctk.CTkFont(family="Menlo", size=11),
                         lmargin1=24, lmargin2=24, rmargin=24, spacing3=4)
        tb.tag_configure("tool_fail", foreground="#FF7B72", background="#2B1416",
                         font=ctk.CTkFont(family="Menlo", size=11),
                         lmargin1=24, lmargin2=24, rmargin=24, spacing3=4)
        tb.tag_configure("thinking", foreground="#8B949E", background="#161B22",
                         font=ctk.CTkFont(size=11, slant="italic"),
                         lmargin1=24, lmargin2=24, rmargin=24, spacing1=3, spacing3=4)
        tb.tag_configure("code_hdr", foreground="#8B949E", background="#0D1117",
                         font=ctk.CTkFont(family="Menlo", size=10),
                         lmargin1=18, lmargin2=18, spacing1=4)
        tb.tag_configure("copy_btn", foreground="#79C0FF", underline=1,
                         font=ctk.CTkFont(family="Menlo", size=10, weight="bold"))
        tb.tag_configure("observation", foreground="#9A9A9A", background="#11161D",
                         font=ctk.CTkFont(family="Menlo", size=11),
                         lmargin1=24, lmargin2=24, rmargin=24, spacing3=4)
        tb.tag_configure("error", foreground="#FF7B72", background="#2B1416",
                         font=ctk.CTkFont(family="Menlo", size=11),
                         lmargin1=18, lmargin2=18, rmargin=18, spacing3=4)
        tb.tag_configure("success", foreground="#7EE787", font=ctk.CTkFont(size=13, weight="bold"),
                         lmargin1=18, spacing3=6)
        tb.tag_configure("summary", foreground="#7EE787", background="#0B1320",
                         font=ctk.CTkFont(family="Menlo", size=11),
                         lmargin1=18, lmargin2=18, rmargin=24, spacing1=6, spacing3=8)
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
        tb.tag_configure("code", foreground="#D4D4D4", background="#0D1117",
                         font=ctk.CTkFont(family="Menlo", size=12),
                         lmargin1=16, lmargin2=16, rmargin=16, spacing1=2, spacing3=2)
        tb.tag_configure("bold", foreground=TEXT, font=ctk.CTkFont(size=13, weight="bold"))
        tb.tag_configure("icode", foreground="#79C0FF", font=ctk.CTkFont(family="Menlo", size=12))

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
            full_code = "\n".join(code_buf)
            code_id = f"c_{abs(hash(full_code)) % 10000000}"
            tb.insert("end", "┌── Code ────────────────────────────────────────── ", "code_hdr")
            tb.insert("end", "[📋 Copy]\n", ("copy_btn", code_id))
            try:
                tb.tag_bind(code_id, "<Button-1>", lambda _e, c=full_code: self._copy_to_clipboard(c))
            except Exception:
                pass
            for n, l in enumerate(code_buf):
                tb.insert("end", f"{n + 1:3} │ {l}\n", "code")
            tb.insert("end", "└──\n\n", "code_hdr")
            code_buf = []

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

    def _render_entry(self, tag, text, show_header=True):
        tb = self.chat_display._textbox
        self._show_chat()
        self.chat_display.configure(state="normal")
        try:
            if tag == "goal":
                if show_header:
                    tb.insert("end", "\n👤 You\n", "user_hdr")
                self._insert_markdown(text, "goal")
                tb.insert("end", "\n")
            elif tag in ("assistant", None):
                if show_header and not (tb.get("end-2c linestart", "end-1c").startswith("◈")):
                    tb.insert("end", "\n◈ Devsoft Agent\n", "asst_hdr")
                self._insert_markdown(text, "assistant")
                tb.insert("end", "\n")
            elif tag == "tool_start":
                tb.insert("end", f"  ⚙ {text.strip()}\n", "tool_start")
            elif tag == "tool_success":
                tb.insert("end", f"  ✓ {text.strip()}\n", "tool_success")
            elif tag == "tool_fail":
                tb.insert("end", f"  ✗ {text.strip()}\n", "tool_fail")
            elif tag == "thinking":
                tb.insert("end", f"  💭 {text.strip()}\n", "thinking")
            elif tag == "system":
                tb.insert("end", f"  • {text.strip()}\n", "system")
            elif tag == "activity":
                tb.insert("end", f"  ⚡ {text.strip()}\n", "activity")
            elif tag == "observation":
                tb.insert("end", f"{text.strip()}\n", "observation")
            elif tag == "error":
                tb.insert("end", f"  ❌ {text.strip()}\n", "error")
            elif tag == "success":
                tb.insert("end", f"  ✓ {text.strip()}\n", "success")
            elif tag == "summary":
                tb.insert("end", text + "\n", "summary")
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
                        if k.startswith(("groq:", "openrouter:", "gemini:", "cerebras:", "cloud:"))
                        or k.split(":")[0] in installed}
                for k, v in FREE_CLOUD_MODELS.items():
                    if k not in keep:
                        keep[k] = v
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

    _TOOL_CAPABLE = ("qwen", "llama3.1", "llama3.2", "llama-3.3", "llama3.3", "mistral", "gemma2", "command-r",
                     "firefunction", "nexusrouter", "glm", "kimi", "minicpm", "phi3", "phi4",
                     "groq", "gemini", "openrouter", "cerebras")

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

    def _on_sidebar_view_change(self, value):
        tab = self.active_tab()
        if value == "📁 Files":
            if tab:
                tab.sidebar_view = "files"
            self._show_sidebar_files()
        elif value == "💬 Chats":
            if tab:
                tab.sidebar_view = "sessions"
            self._show_sidebar_sessions()
        elif value == "✓ Tasks":
            if tab:
                tab.sidebar_view = "tasks"
            self._show_sidebar_tasks()

    def _show_sidebar_files(self):
        if hasattr(self, "sidebar_sessions_frame"):
            self.sidebar_sessions_frame.grid_remove()
        if hasattr(self, "sidebar_tasks_frame"):
            self.sidebar_tasks_frame.grid_remove()
        if hasattr(self, "sidebar_files_frame"):
            self.sidebar_files_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(2, 6))
        tab = self.active_tab()
        if tab:
            self._render_files(tab)

    def _show_sidebar_sessions(self):
        if hasattr(self, "sidebar_files_frame"):
            self.sidebar_files_frame.grid_remove()
        if hasattr(self, "sidebar_tasks_frame"):
            self.sidebar_tasks_frame.grid_remove()
        if hasattr(self, "sidebar_sessions_frame"):
            self.sidebar_sessions_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(2, 6))
        tab = self.active_tab()
        if tab:
            self._render_sessions_list(tab)

    def _show_sidebar_tasks(self):
        if hasattr(self, "sidebar_files_frame"):
            self.sidebar_files_frame.grid_remove()
        if hasattr(self, "sidebar_sessions_frame"):
            self.sidebar_sessions_frame.grid_remove()
        if hasattr(self, "sidebar_tasks_frame"):
            self.sidebar_tasks_frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(2, 6))
        self.refresh_tasks_panel()

    @staticmethod
    def _format_relative_time(ts):
        if not ts:
            return "recently"
        diff = time.time() - ts
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{int(diff // 60)}m ago"
        if diff < 86400:
            return f"{int(diff // 3600)}h ago"
        return f"{int(diff // 86400)}d ago"

    def _render_sessions_list(self, tab):
        if not hasattr(self, "sessions_container"):
            return
        for w in self.sessions_container.winfo_children():
            w.destroy()
        if not tab:
            return
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
                    entries.append((
                        data.get("updated") or 0,
                        sid,
                        data.get("name") or "New conversation",
                        len(data.get("messages") or []),
                        data.get("model") or tab.model
                    ))
                except (OSError, json.JSONDecodeError):
                    continue

        if not entries:
            ctk.CTkLabel(self.sessions_container, text="No previous chats yet.\nClick '＋ New' to start one.",
                         text_color="#666", font=ctk.CTkFont(size=12), justify="center").pack(padx=16, pady=24)
            return

        q = self.sessions_filter.get().strip().lower() if hasattr(self, "sessions_filter") else ""
        sorted_entries = sorted(entries, reverse=True)
        if q:
            sorted_entries = [e for e in sorted_entries if q in e[2].lower() or q in e[1].lower()]

        for updated, sid, name, nmsg, mod in sorted_entries:
            is_active = (sid == tab.session_id)
            card = ctk.CTkFrame(
                self.sessions_container,
                fg_color="#141D2B" if is_active else CARD,
                corner_radius=8,
                border_width=1 if is_active else 0,
                border_color=GOLD if is_active else ACTIVE
            )
            card.pack(fill="x", padx=4, pady=3)

            top_row = ctk.CTkFrame(card, fg_color="transparent")
            top_row.pack(fill="x", padx=10, pady=(6, 2))
            top_row.grid_columnconfigure(0, weight=1)

            disp_name = name[:22] + ("…" if len(name) > 22 else "")
            title_lbl = ctk.CTkLabel(
                top_row,
                text=disp_name,
                anchor="w",
                text_color=GOLD if is_active else TEXT,
                font=ctk.CTkFont(size=11, weight="bold")
            )
            title_lbl.grid(row=0, column=0, sticky="w")
            title_lbl.bind("<Button-1>", lambda _e, s=sid: self._switch_to_session(tab, s))

            ren_btn = ctk.CTkButton(
                top_row, text="✏️", width=20, height=20,
                fg_color="transparent", hover_color=ACTIVE, text_color=MUTED,
                font=ctk.CTkFont(size=10),
                command=lambda s=sid: self._rename_session_dialog(tab, s)
            )
            ren_btn.grid(row=0, column=1, padx=(2, 0))
            Tooltip(ren_btn, "Rename chat")

            del_btn = ctk.CTkButton(
                top_row, text="🗑️", width=20, height=20,
                fg_color="transparent", hover_color="#4A1A1A", text_color=MUTED,
                font=ctk.CTkFont(size=10),
                command=lambda s=sid: self._delete_session_dialog(tab, s)
            )
            del_btn.grid(row=0, column=2, padx=(2, 0))
            Tooltip(del_btn, "Delete chat")

            meta_row = ctk.CTkFrame(card, fg_color="transparent")
            meta_row.pack(fill="x", padx=10, pady=(0, 6))
            rel_time = self._format_relative_time(updated)
            m_short = mod.split(":")[0]
            meta_lbl = ctk.CTkLabel(
                meta_row,
                text=f"{rel_time} · {nmsg} msgs · {m_short}",
                text_color=MUTED,
                font=ctk.CTkFont(size=10)
            )
            meta_lbl.pack(side="left")
            meta_lbl.bind("<Button-1>", lambda _e, s=sid: self._switch_to_session(tab, s))
            card.bind("<Button-1>", lambda _e, s=sid: self._switch_to_session(tab, s))

    def _switch_to_session(self, tab, sid):
        if not tab:
            return
        tab.session_id = sid
        _save_project_prefs(tab.root, {"model": tab.model, "session_id": sid})
        self._load_session_tasks(tab, sid)
        self._load_session_transcript(tab, sid)
        self.refresh_sessions(tab, keep_selection=True)
        self.main_tabs.set("Chat")

    def _rename_session_dialog(self, tab, sid):
        path = os.path.join(tab.root, ".agent_sessions", f"{sid}.json")
        cur_name = sid
        try:
            with open(path, encoding="utf-8") as f:
                cur_name = json.load(f).get("name") or sid
        except Exception:
            pass

        win = ctk.CTkToplevel(self)
        win.title("Rename Chat")
        win.geometry("380x170")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()

        ctk.CTkLabel(win, text="Chat Title:", text_color=TEXT,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(16, 6))
        entry = ctk.CTkEntry(win, height=32, fg_color=CARD, border_color=ACTIVE, text_color=TEXT)
        entry.pack(fill="x", padx=20, pady=(0, 14))
        entry.insert(0, cur_name)
        entry.focus()

        def do_rename():
            new_name = entry.get().strip()
            if new_name and os.path.exists(path):
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    data["name"] = new_name
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    self.refresh_sessions(tab)
                except Exception as e:
                    self.append_chat(f"❌ Rename failed: {e}", tag="error")
            win.destroy()

        entry.bind("<Return>", lambda _e: do_rename())
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=4)
        ctk.CTkButton(btns, text="Cancel", width=80, height=28, fg_color=CARD,
                      hover_color=ACTIVE, text_color=TEXT, command=win.destroy).pack(side="left")
        ctk.CTkButton(btns, text="Save", width=80, height=28, fg_color=GOLD,
                      text_color="#000", hover_color="#FFB300", font=ctk.CTkFont(weight="bold"),
                      command=do_rename).pack(side="right")

    def _delete_session_dialog(self, tab, sid):
        path = os.path.join(tab.root, ".agent_sessions", f"{sid}.json")
        if os.path.exists(path):
            try:
                os.remove(path)
                if tab.session_id == sid:
                    tab.session_id = None
                    tab.transcript.clear()
                    tab.tasks_data = []
                    self._render_transcript(tab)
                    self.refresh_tasks_panel()
                self.refresh_sessions(tab)
                self.append_chat(f"🗑 Deleted chat {sid[-6:]}", tag="system")
            except Exception as e:
                self.append_chat(f"❌ Delete failed: {e}", tag="error")

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
        self._render_sessions_list(tab)

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

    def _toggle_dir_expansion(self, tab, rel_dir):
        if not tab:
            return
        if not hasattr(tab, "expanded_dirs"):
            tab.expanded_dirs = set()
        if rel_dir in tab.expanded_dirs:
            tab.expanded_dirs.remove(rel_dir)
        else:
            tab.expanded_dirs.add(rel_dir)
        self._render_files(tab)

    def _expand_all_dirs(self, tab):
        if not tab:
            return
        if not hasattr(tab, "expanded_dirs"):
            tab.expanded_dirs = set()
        for rel in tab.files:
            parts = rel.split(os.sep)
            for i in range(1, len(parts)):
                tab.expanded_dirs.add(os.path.join(*parts[:i]))
        self._render_files(tab)

    def _collapse_all_dirs(self, tab):
        if not tab:
            return
        if not hasattr(tab, "expanded_dirs"):
            tab.expanded_dirs = set()
        tab.expanded_dirs.clear()
        self._render_files(tab)

    def _render_files(self, tab):
        if not hasattr(self, "files_container"):
            return
        for w in self.files_container.winfo_children():
            w.destroy()
        if not tab:
            return
        self._scan_files(tab)
        if not tab.files:
            ctk.CTkLabel(self.files_container, text="No files found",
                         text_color="#666", font=ctk.CTkFont(size=11)).pack(anchor="w", padx=12, pady=8)
            return

        if not hasattr(tab, "expanded_dirs"):
            tab.expanded_dirs = set()

        # On initial project load, auto-expand top-level directories
        if not getattr(tab, "_initial_dirs_expanded", False):
            for rel in tab.files:
                parts = rel.split(os.sep)
                if len(parts) > 1:
                    tab.expanded_dirs.add(parts[0])
            tab._initial_dirs_expanded = True

        q = self.files_filter.get().strip().lower() if hasattr(self, "files_filter") else ""

        # Build directory structure
        dir_subdirs = collections.defaultdict(set)
        dir_files = collections.defaultdict(list)

        filtered_files = [f for f in tab.files if q in f.lower()] if q else tab.files
        if q:
            # Auto-expand all parent folders of matching files
            for rel in filtered_files:
                parts = rel.split(os.sep)
                for i in range(1, len(parts)):
                    tab.expanded_dirs.add(os.path.join(*parts[:i]))

        for rel in filtered_files:
            parts = rel.split(os.sep)
            if len(parts) == 1:
                dir_files[""].append(parts[0])
            else:
                for i in range(len(parts) - 1):
                    parent = os.path.join(*parts[:i]) if i > 0 else ""
                    sub = parts[i]
                    dir_subdirs[parent].add(sub)
                parent_dir = os.path.join(*parts[:-1])
                dir_files[parent_dir].append(parts[-1])

        # Icon mapping
        ext_icons = {
            ".py": "🐍", ".pyw": "🐍",
            ".js": "⚡", ".ts": "⚡", ".jsx": "⚡", ".tsx": "⚡",
            ".json": "{}", ".jsonc": "{}",
            ".html": "🌐", ".htm": "🌐", ".css": "🎨", ".scss": "🎨",
            ".md": "📝", ".txt": "📄", ".rst": "📝",
            ".sh": "🐚", ".bash": "🐚", ".zsh": "🐚",
            ".yml": "⚙", ".yaml": "⚙", ".toml": "⚙", ".ini": "⚙",
            ".png": "🖼", ".jpg": "🖼", ".jpeg": "🖼", ".svg": "🖼",
            ".lock": "🔒", ".gitignore": "⎇",
        }

        def render_level(curr_dir, level):
            # Render immediate subdirectories first
            for sub in sorted(dir_subdirs.get(curr_dir, [])):
                rel_dir = os.path.join(curr_dir, sub) if curr_dir else sub
                is_expanded = (rel_dir in tab.expanded_dirs)
                arrow = "▾" if is_expanded else "▸"
                f_icon = "📂" if is_expanded else "📁"

                row = ctk.CTkFrame(self.files_container, fg_color="transparent", height=24)
                row.pack(fill="x", padx=2, pady=1)

                pad_left = level * 14 + 4
                btn = ctk.CTkButton(
                    row,
                    text=f"{arrow} {f_icon} {sub}",
                    anchor="w",
                    height=22,
                    fg_color="transparent",
                    hover_color=ACTIVE,
                    text_color="#D8DEE9",
                    font=ctk.CTkFont(family="Menlo", size=11, weight="bold"),
                    command=lambda d=rel_dir: self._toggle_dir_expansion(tab, d)
                )
                btn.pack(side="left", fill="x", expand=True, padx=(pad_left, 2))

                if is_expanded:
                    render_level(rel_dir, level + 1)

            # Render immediate files
            for fn in sorted(dir_files.get(curr_dir, [])):
                rel_file = os.path.join(curr_dir, fn) if curr_dir else fn
                ext = os.path.splitext(fn)[1].lower()
                icon = ext_icons.get(ext, "📄")

                is_active = (tab.editor_path == rel_file)
                dirty_mark = ""
                file_color = TEXT
                if hasattr(tab, "changed_files") and rel_file in tab.changed_files:
                    st = tab.changed_files[rel_file]
                    dirty_mark = " ●"
                    file_color = GOLD if st == "M" else (GREEN if st == "A" else BLUE)

                row = ctk.CTkFrame(self.files_container, fg_color="#162032" if is_active else "transparent", height=24, corner_radius=4)
                row.pack(fill="x", padx=2, pady=1)

                pad_left = level * 14 + 18
                btn = ctk.CTkButton(
                    row,
                    text=f"{icon}  {fn}{dirty_mark}",
                    anchor="w",
                    height=22,
                    fg_color="transparent",
                    hover_color=ACTIVE,
                    text_color=GOLD if is_active else file_color,
                    font=ctk.CTkFont(family="Menlo", size=11, weight="bold" if is_active else "normal"),
                    command=lambda r=rel_file: self.open_file(r)
                )
                btn.pack(side="left", fill="x", expand=True, padx=(pad_left, 2))

        render_level("", 0)

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
        self._render_editor_tabs(tab)
        self._on_editor_cursor_moved()

    def _update_editor_status(self, tab):
        if not tab.editor_path:
            self.editor_path_label.configure(text="No file open", text_color=MUTED)
            self.editor_save_btn.configure(fg_color=CARD, text_color=TEXT)
            self.editor_lang_label.configure(text="Plain Text")
            return
        mark = "  ● unsaved" if tab.editor_dirty else ""
        self.editor_path_label.configure(text=f"{tab.editor_path}{mark}",
                                         text_color=GOLD if tab.editor_dirty else MUTED)
        self.editor_save_btn.configure(fg_color=GOLD if tab.editor_dirty else CARD,
                                       text_color="#000" if tab.editor_dirty else TEXT)
        lang = self._lang_for_path(tab.editor_path) or "Plain Text"
        self.editor_lang_label.configure(text=lang.capitalize())

    def _on_editor_cursor_moved(self, event=None):
        try:
            idx = self.editor_box.index("insert")
            line, col = idx.split(".")
            self.editor_pos_label.configure(text=f"Ln {line}, Col {int(col)+1}")
        except Exception:
            pass

    def _render_editor_tabs(self, tab):
        if not hasattr(self, "editor_tabs_frame"):
            return
        for w in self.editor_tabs_frame.winfo_children():
            w.destroy()
        if not getattr(tab, "open_files", None):
            ctk.CTkLabel(self.editor_tabs_frame, text="No open files", text_color="#555",
                         font=ctk.CTkFont(size=11)).pack(side="left", padx=10, pady=4)
            return
        for rel in tab.open_files:
            is_active = (rel == tab.editor_path)
            base = os.path.basename(rel)
            dirty_mark = " ●" if (is_active and tab.editor_dirty) else ""
            chip = ctk.CTkFrame(
                self.editor_tabs_frame,
                fg_color="#1F242C" if is_active else CARD,
                corner_radius=6,
                border_width=1 if is_active else 0,
                border_color=GOLD if is_active else ACTIVE
            )
            chip.pack(side="left", padx=(0, 6), pady=2)
            lbl = ctk.CTkButton(
                chip,
                text=f"{base}{dirty_mark}",
                width=max(len(base) * 7 + 16, 40),
                height=24,
                fg_color="transparent",
                text_color=GOLD if is_active else TEXT,
                font=ctk.CTkFont(family="Menlo", size=11, weight="bold" if is_active else "normal"),
                command=lambda r=rel: self.open_file(r)
            )
            lbl.pack(side="left", padx=(4, 0))
            close_btn = ctk.CTkButton(
                chip,
                text="×",
                width=18,
                height=20,
                fg_color="transparent",
                hover_color="#4A1A1A",
                text_color=RED if is_active else MUTED,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda r=rel: self.close_editor_file(r)
            )
            close_btn.pack(side="left", padx=(0, 4))

    def close_editor_file(self, rel):
        tab = self.active_tab()
        if not tab:
            return
        if hasattr(tab, "open_files") and rel in tab.open_files:
            tab.open_files.remove(rel)
        if tab.editor_path == rel:
            if getattr(tab, "open_files", None):
                next_file = tab.open_files[-1]
                self.open_file(next_file)
            else:
                tab.editor_path = None
                tab.editor_text = ""
                tab.editor_buf = ""
                tab.editor_dirty = False
                self.editor_box.delete("1.0", "end")
                self._update_editor_status(tab)
                self._render_editor_tabs(tab)
        else:
            self._render_editor_tabs(tab)

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
        self._render_editor_tabs(tab)

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
        if not hasattr(tab, "open_files"):
            tab.open_files = []
        if rel not in tab.open_files:
            tab.open_files.append(rel)
        tab.editor_path = rel
        tab.editor_text = content
        tab.editor_buf = content
        self._restore_editor(tab)
        self._update_active_file_ui()
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
        self._render_editor_tabs(tab)
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
        self.terminal_lines_lbl.configure(text=f"{total} lines")
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
        self.terminal_lines_lbl.configure(text="0 lines")

    def _copy_terminal_output(self):
        tab = self.active_tab()
        if tab and tab.raw_log:
            text = "\n".join(tab.raw_log)
        else:
            text = self.terminal_box.get("1.0", "end-1c")
        self._copy_to_clipboard(text)
        self.append_chat("📋 Copied terminal logs to clipboard.", tag="system")

    def _on_terminal_filter(self, event=None):
        tab = self.active_tab()
        if not tab:
            return
        q = self.terminal_filter.get().strip().lower()
        self.terminal_box.configure(state="normal")
        self.terminal_box.delete("1.0", "end")
        if not q:
            lines = tab.raw_log[-3000:]
        else:
            lines = [l for l in tab.raw_log if q in l.lower()][-3000:]
        self.terminal_box.insert("1.0", "\n".join(lines) + "\n")
        self.terminal_lines_lbl.configure(text=f"{len(lines)} lines")
        self.terminal_box.configure(state="disabled")
        try:
            self.terminal_box.see("end")
        except Exception:
            pass

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
            self.terminal_lines_lbl.configure(text=f"{len(tab.raw_log)} lines")
        else:
            self.terminal_box.insert(
                "1.0", "— terminal idle —\nraw agent output (plans, tool calls, command results)\n"
                       "streams here while a run is active.\n")
            self.terminal_lines_lbl.configure(text="0 lines")
        self.terminal_box.configure(state="disabled")
        try:
            self.terminal_box.see("end")
        except Exception:
            pass

    # -------------------------------------------------------- shell console --
    def _setup_shell_tags(self):
        tb = self.shell_box._textbox
        tb.tag_configure("prompt", foreground=GOLD, font=ctk.CTkFont(family="Menlo", size=12, weight="bold"))
        tb.tag_configure("normal", foreground="#D4D4D4", font=ctk.CTkFont(family="Menlo", size=12))
        tb.tag_configure("error", foreground="#FF7B72", font=ctk.CTkFont(family="Menlo", size=12))
        tb.tag_configure("info", foreground="#79C0FF", font=ctk.CTkFont(family="Menlo", size=12))

    def _update_shell_cwd(self):
        tab = self.active_tab()
        if not tab:
            return
        rel = os.path.basename(tab.root) or tab.root
        self.shell_cwd_label.configure(text=f"📁 {rel}")

    def run_shell_command(self):
        tab = self.active_tab()
        if not tab:
            return
        cmd = self.shell_entry.get().strip()
        if not cmd:
            return
        self.shell_entry.delete(0, "end")
        if not getattr(tab, "shell_history", None):
            tab.shell_history = []
        if not tab.shell_history or tab.shell_history[-1] != cmd:
            tab.shell_history.append(cmd)
        tab.shell_history_idx = len(tab.shell_history)

        self._append_shell_output(f"\n➜ [{tab.name}]$ {cmd}\n", "prompt")

        if cmd.startswith("cd "):
            target = cmd[3:].strip()
            new_cwd = os.path.abspath(os.path.join(tab.root, target))
            if os.path.isdir(new_cwd):
                tab.root = new_cwd
                self._update_shell_cwd()
                self._render_files(tab)
                self._append_shell_output(f"Changed working directory to {new_cwd}\n", "info")
                return
            else:
                self._append_shell_output(f"cd: no such directory: {target}\n", "error")
                return

        self.shell_status_badge.configure(text="● RUNNING", text_color=GOLD, fg_color="#2E2412")

        def worker():
            try:
                proc = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=tab.root,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                tab.shell_running_proc = proc
                for line in iter(proc.stdout.readline, ''):
                    if not line:
                        break
                    self.after(0, self._append_shell_output, line, "normal")
                proc.stdout.close()
                ret = proc.wait()
                tab.shell_running_proc = None
                code_msg = f"[Process completed with exit code {ret}]\n"
                tag = "info" if ret == 0 else "error"
                self.after(0, self._append_shell_output, code_msg, tag)
                self.after(0, lambda: self.shell_status_badge.configure(text="● IDLE", text_color=GREEN, fg_color="#122619"))
            except Exception as e:
                tab.shell_running_proc = None
                self.after(0, self._append_shell_output, f"[Error: {e}]\n", "error")
                self.after(0, lambda: self.shell_status_badge.configure(text="● ERROR", text_color=RED, fg_color="#2F1517"))

        threading.Thread(target=worker, daemon=True).start()

    def _append_shell_output(self, text, tag="normal"):
        self.shell_box.configure(state="normal")
        self.shell_box.insert("end", text, tag)
        total = int(self.shell_box.index("end-1c").split(".")[0])
        if total > 4000:
            self.shell_box.delete("1.0", f"{total - 3000}.0")
        self.shell_box.configure(state="disabled")
        try:
            self.shell_box.see("end")
        except Exception:
            pass

    def shell_kill_running(self):
        tab = self.active_tab()
        if tab and getattr(tab, "shell_running_proc", None):
            try:
                tab.shell_running_proc.terminate()
                self._append_shell_output("\n[Process terminated by user]\n", "error")
            except Exception:
                pass
            tab.shell_running_proc = None
            self.shell_status_badge.configure(text="● IDLE", text_color=GREEN, fg_color="#122619")

    def _shell_clear(self):
        self.shell_box.configure(state="normal")
        self.shell_box.delete("1.0", "end")
        self.shell_box.configure(state="disabled")

    def on_shell_history_up(self, event=None):
        tab = self.active_tab()
        if not tab or not getattr(tab, "shell_history", None):
            return "break"
        if tab.shell_history_idx > 0:
            tab.shell_history_idx -= 1
            cmd = tab.shell_history[tab.shell_history_idx]
            self.shell_entry.delete(0, "end")
            self.shell_entry.insert(0, cmd)
        return "break"

    def on_shell_history_down(self, event=None):
        tab = self.active_tab()
        if not tab or not getattr(tab, "shell_history", None):
            return "break"
        if tab.shell_history_idx < len(tab.shell_history) - 1:
            tab.shell_history_idx += 1
            cmd = tab.shell_history[tab.shell_history_idx]
            self.shell_entry.delete(0, "end")
            self.shell_entry.insert(0, cmd)
        else:
            tab.shell_history_idx = len(tab.shell_history)
            self.shell_entry.delete(0, "end")
        return "break"

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
        status_colors = {"M": GOLD, "A": GREEN, "D": RED, "?": BLUE, "R": GREEN}
        for e in entries:
            st, path = e[:2], e[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            path = path.strip('"')
            key = st.strip()[0] if st.strip() else "?"
            color = status_colors.get(key, MUTED)
            row = ctk.CTkFrame(self.changes_list, fg_color="transparent")
            row.pack(fill="x", padx=4, pady=1)
            
            # Status pill
            pill = ctk.CTkLabel(row, text=key, width=20, height=20, fg_color=CARD,
                                text_color=color, corner_radius=4,
                                font=ctk.CTkFont(family="Menlo", size=10, weight="bold"))
            pill.pack(side="left", padx=(0, 4))
            
            btn = ctk.CTkButton(row, text=path, anchor="w",
                                height=24, fg_color="transparent", hover_color=ACTIVE,
                                text_color=TEXT, font=ctk.CTkFont(family="Menlo", size=11),
                                command=lambda p=path, s=key: self._select_change(p, s))
            btn.pack(side="left", fill="x", expand=True)
            rev = ctk.CTkButton(row, text="↩", width=24, height=22,
                                fg_color="transparent", hover_color="#4A1A1A",
                                text_color="#888", font=ctk.CTkFont(size=11),
                                command=lambda p=path: self._revert_file(p))
            rev.pack(side="right", padx=(2, 0))
            Tooltip(rev, f"Revert changes in {path}")
            openb = ctk.CTkButton(row, text="↗", width=24, height=22,
                                  fg_color="transparent", hover_color=ACTIVE,
                                  text_color="#888", font=ctk.CTkFont(size=11),
                                  command=lambda p=path: self.open_file(p))
            openb.pack(side="right", padx=(2, 0))
            Tooltip(openb, f"Open {path} in Editor")
            tab.changed_files[path] = key
        if not silent and tab.changed_files:
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
        self._render_files(tab)

    def _revert_all_changes(self):
        tab = self.active_tab()
        if not tab:
            return
        code, out = self._git(tab, "checkout", "--", ".")
        self._git(tab, "clean", "-fd")
        self.refresh_changes_panel()
        self.refresh_git_panel()
        self._render_files(tab)
        self.append_chat("↩ Reverted all working tree changes.", tag="system")

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
        for tag, color, bg in (
            ("add", "#7EE787", "#122619"),
            ("del", "#FF7B72", "#2B1416"),
            ("meta", "#D29922", "#161B22"),
            ("hunk", "#79C0FF", "#162032"),
            ("hdr", "#8B949E", "#0D1117")
        ):
            tb.tag_configure(tag, foreground=color, background=bg)
        if path is None:
            tb.insert("end", "Select a changed file from the left to view its diff.\n")
        else:
            tb.insert("end", f"── Diff: {path} ──────────────────────────────────────\n", "hdr")
            for line in diff.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    tb.insert("end", line + "\n", "add")
                elif line.startswith("-") and not line.startswith("---"):
                    tb.insert("end", line + "\n", "del")
                elif line.startswith("@@"):
                    tb.insert("end", line + "\n", "hunk")
                elif line.startswith("diff ") or line.startswith("index ") or line.startswith("---") or line.startswith("+++"):
                    tb.insert("end", line + "\n", "meta")
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
        tb = self.git_log_box._textbox
        tb.tag_configure("hash", foreground=GOLD, font=ctk.CTkFont(family="Menlo", size=11, weight="bold"))
        tb.tag_configure("msg", foreground=TEXT, font=ctk.CTkFont(family="Menlo", size=11))
        if not log:
            tb.insert("1.0", "— no commits yet —\n")
        else:
            for line in log.splitlines():
                parts = line.split(" ", 1)
                if len(parts) == 2:
                    sha, msg = parts
                    tb.insert("end", f" {sha} ", "hash")
                    tb.insert("end", f" {msg}\n", "msg")
                else:
                    tb.insert("end", line + "\n")
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
        msg = self.git_commit_msg.get().strip() or "Update via Devsoft-Agentic IDE"
        self._git_action("add", ["add", "-A"])
        self._git_action("commit", ["commit", "-m", msg])
        self.git_commit_msg.delete(0, "end")

    def git_pull(self):
        self._git_action("pull", ["pull"])

    def git_push(self):
        self._git_action("push", ["push"])

    def _apply_git_prefix(self, prefix):
        current = self.git_commit_msg.get().strip()
        match = re.match(r"^(feat|fix|docs|style|refactor|test|chore):\s*(.*)", current)
        if match:
            rest = match.group(2)
            new_text = f"{prefix} {rest}"
        elif current:
            new_text = f"{prefix} {current}"
        else:
            new_text = f"{prefix} "
        self.git_commit_msg.delete(0, "end")
        self.git_commit_msg.insert(0, new_text)
        self.git_commit_msg.focus()
        self.git_commit_msg.icursor(len(new_text))

    def _new_branch_dialog(self):
        tab = self.active_tab()
        if not tab:
            return
        win = ctk.CTkToplevel(self)
        win.title("Create New Branch")
        win.geometry("380x180")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()

        ctk.CTkLabel(win, text="Branch Name:", text_color=TEXT,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(16, 6))
        entry = ctk.CTkEntry(win, height=32, placeholder_text="e.g. feature/fast-response",
                             fg_color=CARD, border_color=ACTIVE, text_color=TEXT)
        entry.pack(fill="x", padx=20, pady=(0, 14))
        entry.focus()

        def create():
            name = entry.get().strip()
            if not name:
                return
            code, out = self._git(tab, "checkout", "-b", name)
            win.destroy()
            if code == 0:
                self.append_chat(f"🌿 Created and switched to branch '{name}'", tag="success")
            else:
                self.append_chat(f"❌ Failed to create branch: {out.strip()}", tag="error")
            self.refresh_git_panel()

        entry.bind("<Return>", lambda _e: create())
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=4)
        ctk.CTkButton(btns, text="Cancel", width=80, height=28, fg_color=CARD,
                      hover_color=ACTIVE, text_color=TEXT, command=win.destroy).pack(side="left")
        ctk.CTkButton(btns, text="Create", width=90, height=28, fg_color=GOLD,
                      text_color="#000", hover_color="#FFB300", font=ctk.CTkFont(weight="bold"),
                      command=create).pack(side="right")

    # -------------------------------------------------------- file operations --
    def _new_file_dialog(self):
        tab = self.active_tab()
        if not tab:
            return
        win = ctk.CTkToplevel(self)
        win.title("Create New File")
        win.geometry("380x180")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()

        ctk.CTkLabel(win, text="File Path (relative to project root):", text_color=TEXT,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(16, 6))
        entry = ctk.CTkEntry(win, height=32, placeholder_text="e.g. src/index.py",
                             fg_color=CARD, border_color=ACTIVE, text_color=TEXT)
        entry.pack(fill="x", padx=20, pady=(0, 14))
        entry.focus()

        def create():
            rel = entry.get().strip().lstrip("/")
            if not rel:
                return
            path = os.path.join(tab.root, rel)
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                if not os.path.exists(path):
                    with open(path, "w", encoding="utf-8") as f:
                        f.write("")
                win.destroy()
                self._scan_files(tab)
                self._render_files(tab)
                self.open_file(rel)
            except OSError as e:
                self.append_chat(f"❌ Failed to create file: {e}", tag="error")

        entry.bind("<Return>", lambda _e: create())
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=4)
        ctk.CTkButton(btns, text="Cancel", width=80, height=28, fg_color=CARD,
                      hover_color=ACTIVE, text_color=TEXT, command=win.destroy).pack(side="left")
        ctk.CTkButton(btns, text="Create File", width=100, height=28, fg_color=GOLD,
                      text_color="#000", hover_color="#FFB300", font=ctk.CTkFont(weight="bold"),
                      command=create).pack(side="right")

    def _new_folder_dialog(self):
        tab = self.active_tab()
        if not tab:
            return
        win = ctk.CTkToplevel(self)
        win.title("Create New Folder")
        win.geometry("380x180")
        win.configure(fg_color=BG)
        win.transient(self)
        win.lift()
        win.focus_force()

        ctk.CTkLabel(win, text="Folder Path (relative to project root):", text_color=TEXT,
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=20, pady=(16, 6))
        entry = ctk.CTkEntry(win, height=32, placeholder_text="e.g. src/components",
                             fg_color=CARD, border_color=ACTIVE, text_color=TEXT)
        entry.pack(fill="x", padx=20, pady=(0, 14))
        entry.focus()

        def create():
            rel = entry.get().strip().lstrip("/")
            if not rel:
                return
            path = os.path.join(tab.root, rel)
            try:
                os.makedirs(path, exist_ok=True)
                win.destroy()
                self._scan_files(tab)
                self._render_files(tab)
            except OSError as e:
                self.append_chat(f"❌ Failed to create folder: {e}", tag="error")

        entry.bind("<Return>", lambda _e: create())
        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=4)
        ctk.CTkButton(btns, text="Cancel", width=80, height=28, fg_color=CARD,
                      hover_color=ACTIVE, text_color=TEXT, command=win.destroy).pack(side="left")
        ctk.CTkButton(btns, text="Create Folder", width=110, height=28, fg_color=GOLD,
                      text_color="#000", hover_color="#FFB300", font=ctk.CTkFont(weight="bold"),
                      command=create).pack(side="right")

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
        tmp = os.path.join(tab.root, ".devsoft_paste.png")
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
        if t == "error":
            msg = ev.get("msg") or ev.get("message") or ev.get("error") or "Engine error"
            clean_msg = msg.strip().lstrip("❌ ").strip()
            self.append_chat(clean_msg, tag="error", tab=tab)
            return
        if t == "intent":
            it = ev.get("intent") or ""
            labels = {"trivial": "💬 Greeting",
                      "fast": "⚡ Quick answer",
                      "fast_build": "⚡ Fast Mode · Direct tool execution",
                      "plan": "🧭 Plan · analysis only (read-only)",
                      "build": "🔨 Build · plan → execute → verify"}
            self.append_terminal(labels.get(it, f"Mode: {it}"), tab)
            if it in ("plan", "build") and getattr(tab, "execution_mode", "fast") == "architect":
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
                if not hasattr(tab, "thinking_buf"):
                    tab.thinking_buf = []
                tab.thinking_buf.append(txt)
            return
        if t == "tool_start":
            name = ev.get("name") or "?"
            if not hasattr(tab, "recent_tool_calls"):
                tab.recent_tool_calls = []
            tab.recent_tool_calls.append(name)
            args = (ev.get("args") or "").strip()
            step, total = ev.get("step"), ev.get("total")
            icon = {
                "write_file": "✍️",
                "edit_file": "🛠️",
                "read_file": "📖",
                "run_command": "💻",
                "list_files": "📂",
                "search": "🔍",
                "git_status": "⎇",
                "git_diff": "⎇",
                "git_commit": "⎇",
                "undo": "↩",
                "http_check": "🌐",
            }.get(name, "⚙️")

            arg_summary = args
            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict):
                    if "path" in parsed:
                        arg_summary = parsed["path"]
                    elif "command" in parsed:
                        arg_summary = parsed["command"]
                    elif "query" in parsed:
                        arg_summary = f'"{parsed["query"]}"'
            except Exception:
                pass

            step_str = f"[{step}/{total}] " if step and total else ""
            line = f"{name} {args}".strip()
            self.append_terminal(line, tab)
            self._work_card_update(tab, action=f"{name} {arg_summary}")
            card = f"┌─ {icon} {step_str}{name} · {arg_summary}\n│  Status: ⏳ Executing…"
            self.append_chat(card, tag="tool_start", tab=tab)
            return
        if t == "tool_end":
            preview = (ev.get("preview") or "").strip()
            ok = ev.get("ok", True)
            mark = "✓ Finished" if ok else "✗ Failed"
            tag = "tool_success" if ok else "tool_fail"
            first = preview.splitlines()[0][:140] if preview else ""
            if not preview:
                self.append_chat(f"└─ {mark}", tag=tag, tab=tab)
            else:
                for ln in preview.splitlines()[:6]:
                    self.append_terminal(ln, tab)
                self.append_chat(f"└─ {mark} · {first}", tag=tag, tab=tab)
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
            stats_text = f"⚡ {tab.model} · {_fmt(pt)} prompt / {_fmt(gt)} gen · {dur:.1f}s"
            if hasattr(self, "status_bar"):
                self.after(0, lambda: self.status_bar.configure(text=f"● Ready · {stats_text}"))
            self.append_terminal(f"📊 {stats_text} · {calls} tool calls", tab)
            # Only display metrics pill in chat when multi-step tools were executed
            if calls > 0:
                self.append_chat(
                    f"📊 {_fmt(pt)} prompt + {_fmt(gt)} gen tokens · {calls} tool calls · {dur:.1f}s",
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
        if getattr(tab, "thinking_buf", None):
            full_thinking = " ".join(tab.thinking_buf).strip()
            tab.thinking_buf = []
            if full_thinking:
                words = len(full_thinking.split())
                preview = full_thinking[:260] + ("…" if len(full_thinking) > 260 else "")
                self.append_chat(f"💭 Thought Process ({words} words)\n   {preview}\n", tag="thinking", tab=tab)
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

    # -------------------------------------------------------- send/stop & modes --
    def toggle_execution_mode(self):
        tab = self.active_tab()
        if not tab:
            return
        cur = getattr(tab, "execution_mode", "fast")
        tab.execution_mode = "architect" if cur == "fast" else "fast"
        self._update_mode_ui()
        self.settings["execution_mode"] = tab.execution_mode
        _save_settings(self.settings)

    def _update_mode_ui(self):
        tab = self.active_tab()
        mode = getattr(tab, "execution_mode", "fast") if tab else "fast"
        if mode == "fast":
            if hasattr(self, "mode_toggle_btn"):
                self.mode_toggle_btn.configure(
                    text="⚡ Fast Mode", fg_color="#162032",
                    text_color="#58A6FF", hover_color="#1F2E47")
            if hasattr(self, "mode_badge"):
                self.mode_badge.configure(text="⚡ FAST", fg_color="#162032", text_color="#58A6FF")
        else:
            if hasattr(self, "mode_toggle_btn"):
                self.mode_toggle_btn.configure(
                    text="🧠 Architect Mode", fg_color="#2D1F38",
                    text_color="#BC8CFF", hover_color="#3D294C")
            if hasattr(self, "mode_badge"):
                self.mode_badge.configure(text="🧠 ARCHITECT", fg_color="#2D1F38", text_color="#BC8CFF")
        self._sync_send_button()

    def toggle_think_mode(self):
        cur = self.settings.get("think", False)
        self.settings["think"] = not cur
        _save_settings(self.settings)
        if hasattr(self, "think_toggle_btn"):
            if self.settings["think"]:
                self.think_toggle_btn.configure(text="💭 Think: On", fg_color="#2D1F38", text_color="#BC8CFF")
                self.append_chat("💭 Model thinking mode enabled (deeper reasoning, slower).", tag="system")
            else:
                self.think_toggle_btn.configure(text="💭 Think: Off", fg_color=CARD, text_color=MUTED)
                self.append_chat("⚡ Model thinking mode disabled (fastest direct answers).", tag="system")

    def _insert_active_file_mention(self):
        tab = self.active_tab()
        if not tab or not tab.editor_path:
            return
        cur = self.user_input.get("1.0", "end-1c")
        mention = f"@{tab.editor_path} "
        if mention not in cur:
            self.user_input.insert("insert", mention)
        self.user_input.focus_set()
        self._refresh_input_hint()
        self._grow_input()

    def _update_active_file_ui(self):
        tab = self.active_tab()
        if hasattr(self, "active_file_btn"):
            if tab and tab.editor_path:
                base = os.path.basename(tab.editor_path)
                self.active_file_btn.configure(
                    text=f"📎 @{base}", fg_color="#162032", text_color="#58A6FF")
            else:
                self.active_file_btn.configure(
                    text="📎 No file open", fg_color=CARD, text_color=MUTED)

    def clear_current_chat(self):
        tab = self.active_tab()
        if not tab:
            return
        tab.transcript.clear()
        tab.tasks_data = []
        tab.context_files = []
        self._render_transcript(tab)
        self.refresh_tasks_panel()
        self._update_context_bar()
        self.append_chat("🧹 Chat transcript cleared.", tag="system", tab=tab)

    def _on_input_up(self, _event):
        tab = self.active_tab()
        if not tab or not tab.prompt_history:
            return None
        pos = self.user_input.index("insert")
        line, _col = map(int, pos.split("."))
        if line == 1:
            if tab.history_index > 0:
                tab.history_index -= 1
                prompt = tab.prompt_history[tab.history_index]
                self.user_input.delete("1.0", "end")
                self.user_input.insert("1.0", prompt)
                self._refresh_input_hint()
                self._grow_input()
                return "break"
        return None

    def _on_input_down(self, _event):
        tab = self.active_tab()
        if not tab or not tab.prompt_history:
            return None
        pos = self.user_input.index("insert")
        line, _col = map(int, pos.split("."))
        total_lines = int(self.user_input.index("end-1c").split(".")[0])
        if line >= total_lines:
            if tab.history_index < len(tab.prompt_history) - 1:
                tab.history_index += 1
                prompt = tab.prompt_history[tab.history_index]
                self.user_input.delete("1.0", "end")
                self.user_input.insert("1.0", prompt)
                self._refresh_input_hint()
                self._grow_input()
                return "break"
            elif tab.history_index == len(tab.prompt_history) - 1:
                tab.history_index = len(tab.prompt_history)
                self.user_input.delete("1.0", "end")
                self._refresh_input_hint()
                self._grow_input()
                return "break"
        return None

    def _copy_to_clipboard(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            self.status_bar.configure(text="✓ Copied code block to clipboard!", text_color=GREEN)
            self.after(2000, self._status_tick)
        except Exception:
            pass

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

        # Prompt history tracking
        if not tab.prompt_history or tab.prompt_history[-1] != task:
            tab.prompt_history.append(task)
        tab.history_index = len(tab.prompt_history)

        display_task = task
        full_task = task

        # Slash command dispatch
        if task.startswith("/"):
            parts = task.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""
            if cmd == "/clear":
                self.clear_current_chat()
                return
            elif cmd == "/diff":
                self.main_tabs.set("Changes")
                self.refresh_changes_panel()
                return
            elif cmd == "/test":
                self.main_tabs.set("Terminal")
                self.run_tests()
                return
            elif cmd in ("/fast", "/quick"):
                tab.execution_mode = "fast"
                self._update_mode_ui()
                if not arg:
                    self.append_chat("⚡ Switched to Fast Mode (Direct Tool Execution).", tag="system", tab=tab)
                    return
                display_task = arg
                full_task = arg
            elif cmd in ("/plan", "/architect", "/deep"):
                tab.execution_mode = "architect"
                self._update_mode_ui()
                if not arg:
                    self.append_chat("🧠 Switched to Architect Mode (Multi-Step Mission Pipeline).", tag="system", tab=tab)
                    return
                display_task = arg
                full_task = arg
            elif cmd == "/fix":
                display_task = f"/fix {arg}".strip()
                full_task = f"Inspect project tests, linter, or errors and apply fixes to code: {arg}".strip()
            elif cmd == "/help":
                help_msg = (
                    "### ◈ Antigravity Devsoft Slash Commands\n\n"
                    "- `/fast <task>` — Ultra-fast direct execution (edits files & tests without long planning)\n"
                    "- `/plan <task>` — Deep architect mission (brief → plan → execute → verify → review)\n"
                    "- `/fix <error>` — Auto-fix failing test or syntax error\n"
                    "- `/test` — Auto-detect and run project test suite\n"
                    "- `/diff` — View git & working tree changes\n"
                    "- `/clear` — Clear chat transcript\n"
                    "- `@<filename>` — Injects file contents directly into prompt context"
                )
                self.append_chat(help_msg, tag="assistant", tab=tab)
                return

        # Handle @filename context injection
        file_refs = re.findall(r"@([\w\.\-\/]+)", full_task)
        context_injected = []
        for file_ref in file_refs:
            full_p = os.path.join(tab.root, file_ref)
            if os.path.exists(full_p) and os.path.isfile(full_p):
                try:
                    with open(full_p, "r", encoding="utf-8", errors="replace") as f:
                        file_content = f.read(12000)
                    context_injected.append(f"--- Context for {file_ref} ---\n{file_content}\n--- End {file_ref} ---")
                except OSError:
                    pass
        if context_injected:
            full_task = "\n\n".join(context_injected) + f"\n\nTask: {full_task}"

        if tab.is_generating:
            tab.pending_tasks.append(full_task)
            self.append_chat(f"⏳ Queued ({len(tab.pending_tasks)} waiting): {display_task}", tag="system")
            return
        self._start_agent_thread(tab, full_task, display_task=display_task)

    def _start_agent_thread(self, tab, task, display_task=None):
        self.append_chat(display_task or task, tag="goal", tab=tab)
        tab.is_generating = True
        tab.stop_requested = False
        tab.run_started = time.time()
        self._show_work_card(tab)
        self._sync_send_button()
        self.render_tab_bar()

        env_update = {
            "CLOUD_BASE_URL": self.settings.get("cloud_base_url", ""),
            "CLOUD_API_KEY": self.settings.get("api_key", ""),
        }

        threading.Thread(target=self.agent_loop, args=(tab, task), daemon=True).start()

    def _sync_send_button(self):
        tab = self.active_tab()
        if tab and tab.is_generating:
            self.send_button.configure(text="■  Stop", fg_color=RED, hover_color="#D32F2F",
                                       text_color="#FFF", command=self.stop_generation)
        else:
            mode = getattr(tab, "execution_mode", "fast") if tab else "fast"
            btn_text = "⚡  Run" if mode == "fast" else "▶  Plan"
            btn_fg = BLUE if mode == "fast" else "#D29922"
            btn_hover = "#388BFD" if mode == "fast" else "#FFB300"
            self.send_button.configure(text=btn_text, fg_color=btn_fg, text_color="#000",
                                       hover_color=btn_hover, command=self.send_request)

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
                             "(set DEVSOFT_AGENT_PY).", tag="error", tab=tab)
            self._finish_tab_run(tab)
            return

        # Determine model and cloud provider
        raw_model = tab.model
        cloud_provider = None
        if raw_model.startswith("groq:"):
            cloud_provider = "groq"
            actual_model = raw_model[len("groq:"):]
        elif raw_model.startswith("openrouter:"):
            cloud_provider = "openrouter"
            actual_model = raw_model[len("openrouter:"):]
        elif raw_model.startswith("gemini:"):
            cloud_provider = "gemini"
            actual_model = raw_model[len("gemini:"):]
        elif raw_model.startswith("cerebras:"):
            cloud_provider = "cerebras"
            actual_model = raw_model[len("cerebras:"):]
        elif raw_model.startswith("cloud:"):
            cloud_provider = "cloud"
            actual_model = raw_model[len("cloud:"):]
        else:
            actual_model = raw_model
            configured_provider = self.settings.get("provider", "ollama")
            if configured_provider in ("groq", "openrouter", "gemini", "cerebras", "cloud", "generic_cloud"):
                cloud_provider = "cloud" if configured_provider == "generic_cloud" else configured_provider

        # Check API key if cloud provider is active
        api_key = ""
        if cloud_provider:
            key_setting = f"{cloud_provider}_api_key"
            api_key = (self.settings.get(key_setting) or self.settings.get("api_key") or
                       os.environ.get(f"{cloud_provider.upper()}_API_KEY") or
                       os.environ.get("CLOUD_API_KEY") or "")
            if not api_key:
                preset = CLOUD_PRESETS.get(cloud_provider, {})
                hint_url = preset.get("portal_url") or "https://console.groq.com/keys"
                self.append_chat(
                    f"⚠️ Free API Key Needed for {cloud_provider.title()}:\n"
                    f"1. Get your free key (no credit card required) at: {hint_url}\n"
                    f"2. Paste it in the Settings window that just opened, and click Save Settings.\n"
                    f"💡 Or switch the ◈ Brain dropdown to a local model (e.g. Qwen 3.8) to run offline without any API key.",
                    tag="error", tab=tab)
                self.after(150, self._open_settings)
                self._finish_tab_run(tab)
                return
        else:
            if not self._wait_for_ollama(tab):
                self._finish_tab_run(tab)
                return

        s = self.settings
        mode = getattr(tab, "execution_mode", "fast")
        mode_label = "⚡ Fast Mode (Direct Execution)" if mode == "fast" else "🧠 Architect Mode (Plan → Execute → Verify)"
        tab.recent_tool_calls = []
        prov_label = f"⚡ {cloud_provider.title()} Cloud" if cloud_provider else "💻 Local Ollama"
        self.append_terminal(f"◆ Engine ready · {prov_label} · {actual_model} · {mode_label}", tab)
        if hasattr(self, "status_bar"):
            self.after(0, lambda: self.status_bar.configure(text=f"● Running · {prov_label} · {actual_model}"))
        cmd = [py, "-u", AGENT_SCRIPT, tab.root, "--model", actual_model, "--yolo", "--events"]

        if mode == "fast":
            cmd += ["--fast", "--no-plan", "--no-mission"]
        else:
            cmd += ["--mission", "--plan"]

        if cloud_provider:
            cmd += ["--provider", cloud_provider]
            if api_key:
                cmd += ["--api-key", api_key]
            if cloud_provider == "cloud" and s.get("cloud_base_url"):
                cmd += ["--base-url", s["cloud_base_url"]]
        else:
            provider = s.get("provider", "ollama")
            if provider:
                cmd += ["--provider", provider]

        if s.get("num_ctx"):
            cmd += ["--num-ctx", str(int(s["num_ctx"]))]
        if s.get("temperature") is not None:
            cmd += ["--temperature", str(s["temperature"])]
        if s.get("keep_alive"):
            cmd += ["--keep-alive", str(s["keep_alive"])]
        if s.get("num_predict") and int(s["num_predict"]) > 0:
            cmd += ["--num-predict", str(int(s["num_predict"]))]
        if s.get("think"):
            cmd += ["--think"]
        else:
            cmd += ["--no-think"]
        if tab.session_id:
            self.append_terminal(f"↩ Resuming session {tab.session_id}", tab)
            cmd += ["--resume", tab.session_id]
        cmd += ["-p", full_goal]
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if api_key and cloud_provider:
            env[f"{cloud_provider.upper()}_API_KEY"] = api_key
            env["CLOUD_API_KEY"] = api_key
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
                elapsed = time.time() - getattr(tab, "run_started", time.time())
                self._render_run_summary(tab, elapsed=elapsed)
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

    def _render_run_summary(self, tab, elapsed=0.0):
        # Gather changed files from git
        _code, out = self._git(tab, "status", "--porcelain")
        changed = []
        if _code == 0:
            for l in out.splitlines():
                if l.strip():
                    st, path = l[:2].strip(), l[3:].strip().strip('"')
                    changed.append((st, path))

        pt = getattr(tab, "last_prompt_tokens", 0)
        gt = getattr(tab, "last_gen_tokens", 0)
        mode = getattr(tab, "execution_mode", "fast")
        mode_str = "⚡ Fast Mode" if mode == "fast" else "🧠 Architect Mode"
        tasks = list(getattr(tab, "tasks_data", []))
        tools = list(getattr(tab, "recent_tool_calls", []))

        # Update status bar quietly
        def _fmt(n):
            return f"{n / 1000:.1f}k" if n >= 1000 else str(n)
        status_msg = f"○ Ready · {tab.model} · {elapsed:.1f}s"
        if pt or gt:
            status_msg += f" · {_fmt(pt)} prompt / {_fmt(gt)} gen"
        if changed:
            status_msg += f" · {len(changed)} files modified"
        if hasattr(self, "status_bar"):
            self.after(0, lambda: self.status_bar.configure(text=status_msg))

        # The summary card is ONLY necessary when there are tasks to report,
        # tools were executed, files modified, or in Architect mode!
        # For simple chats/greetings without tasks or modifications, skip it completely.
        has_tasks = len(tasks) > 0
        has_tools = len(tools) > 0
        has_changes = len(changed) > 0
        is_architect = (mode == "architect")

        if not (has_tasks or has_tools or has_changes or is_architect):
            return

        lines = [
            "╔══════════════════════════════════════════════════════════════════════╗",
            f"║  ✦ ANTIGRAVITY EXECUTION SUMMARY · {mode_str:<32} ║",
            "╠══════════════════════════════════════════════════════════════════════╣",
            f"║  Status:    ✅ Task Execution Complete",
            f"║  Model:     {tab.model}",
            f"║  Duration:  {elapsed:.1f}s · Tokens: {pt} prompt / {gt} gen",
        ]

        if tasks:
            lines.append("║")
            lines.append(f"║  📋 Tasks Executed ({len(tasks)}):")
            for tsk in tasks[:8]:
                title = tsk.get("title", "") if isinstance(tsk, dict) else str(tsk)
                st = tsk.get("status", "done") if isinstance(tsk, dict) else "done"
                icon = "✅" if st == "done" else ("⏳" if st == "in_progress" else "○")
                lines.append(f"║    {icon} {title}")
            if len(tasks) > 8:
                lines.append(f"║    … and {len(tasks) - 8} more tasks")

        if changed:
            lines.append("║")
            lines.append(f"║  📁 Modified / Created Files ({len(changed)}):")
            for st, path in changed[:10]:
                icon = "📝" if st == "M" else ("📄" if st in ("A", "??") else "🗑️")
                lines.append(f"║    {icon} [{st}] {path}")
            if len(changed) > 10:
                lines.append(f"║    … and {len(changed) - 10} more files")
        elif has_tools:
            lines.append("║")
            lines.append("║  📁 Workspace: Clean (tools executed without dirty working tree)")

        lines.extend([
            "║",
            "║  💡 Next Steps:",
            "║    • Review changes in 'Changes' tab or diff viewer",
            "║    • Run automated test suite with '🧪 Run tests'",
            "║    • Commit changes with '✓ Commit' in the Git tab",
            "╚══════════════════════════════════════════════════════════════════════╝"
        ])

        summary_text = "\n".join(lines)
        self.append_chat(summary_text, tag="summary", tab=tab)

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
            mode = getattr(tab, "execution_mode", "fast")
            mode_str = "⚡ Fast" if mode == "fast" else "🧠 Architect"
            if tab.is_generating:
                elapsed = max(1, int(time.time() - tab.run_started)) if tab.run_started else 1
                queue = f" · queue {len(tab.pending_tasks)}" if tab.pending_tasks else ""
                dots = "." * (int(time.time() * 2) % 4)
                last = ""
                speed = ""
                if tab.last_gen_tokens:
                    tok_per_sec = tab.last_gen_tokens / elapsed
                    speed = f" · {tok_per_sec:.1f} tok/s"
                if tab.last_prompt_tokens or tab.last_gen_tokens:
                    last = f" · {tab.last_prompt_tokens}+{tab.last_gen_tokens} toks"
                self.status_bar.configure(
                    text=f"● Running{dots} · {mode_str} · {tab.name} · {tab.model} · {elapsed}s{speed}{queue}{last}{tok}",
                    text_color=GOLD)
            else:
                n_sess = len(tab.session_labels)
                self.status_bar.configure(
                    text=f"○ Ready · {mode_str} · {tab.name} · {tab.model}{tok}"
                         + (f" · {n_sess} session{'s' if n_sess != 1 else ''}" if n_sess else ""),
                    text_color=MUTED)
        self.after(900, self._status_tick)

    def _on_close(self):
        for tab in self.tabs:
            self._stop_tab(tab, silent=True)
        _save_geometry(self)
        self.destroy()


if __name__ == "__main__":
    app = DevsoftIDE()
    app.mainloop()
