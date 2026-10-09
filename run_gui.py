import os
import glob
import json
import httpx2
import threading
import subprocess
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import base64
from io import BytesIO
import whisper
import pyaudio
import numpy as np

# Configuration
OLLAMA_URL = "http://localhost:11434/api/chat"
VISION_MODEL = "llava" # Default vision model

class AgenticMimoIDE(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Mimo-Agentic IDE | Multimodal AI Engineer")
        self.geometry("1400x900")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # State
        self.selected_model = "qwen3-coder:30b"
        self.session_history = []
        self.is_generating = False
        self.current_open_file = None
        self.attached_image_path = None
        self.project_root = os.getcwd()
        self.whisper_model = None

        self.models_inventory = {
            "qwen3-coder:30b": "Qwen 3 Coder (30B)",
            "deepseek-r1:latest": "DeepSeek R1",
            "freebuff-mimo:latest": "FreeBuff Mimo",
            "llama3.2:latest": "Llama 3.2"
        }

        self.setup_ui()

    def setup_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self, width=280, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(3, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar, text="MIMO-AGENTIC", font=ctk.CTkFont(size=22, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=20)

        self.model_label = ctk.CTkLabel(self.sidebar, text="Active Brain:")
        self.model_label.grid(row=1, column=0, padx=20, pady=(10, 0))

        self.model_dropdown = ctk.CTkOptionMenu(
            self.sidebar,
            values=list(self.models_inventory.values()),
            command=self.change_model
        )
        self.model_dropdown.grid(row=2, column=0, padx=20, pady=10)

        self.files_label = ctk.CTkLabel(self.sidebar, text="Project Files (Click to Open):")
        self.files_label.grid(row=3, column=0, padx=20, pady=(20, 0), sticky="nw")

        self.project_btn = ctk.CTkButton(self.sidebar, text="📁 Open Project", fg_color="#3b3b3b", command=self.select_project_folder)
        self.project_btn.grid(row=4, column=0, padx=20, pady=10)

        self.files_container = ctk.CTkScrollableFrame(self.sidebar, width=220)
        self.files_container.grid(row=5, column=0, padx=10, pady=10, sticky="nsew")
        self.update_files_list()

        # Load Whisper model in background to avoid startup delay
        threading.Thread(target=self._load_whisper_model, daemon=True).start()

        # --- MAIN CONTENT AREA ---
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        self.chat_display = ctk.CTkTextbox(self.main_container, font=ctk.CTkFont(family="Consolas", size=13))
        self.chat_display.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 20))
        self.chat_display.configure(state="disabled")

        # --- INPUT AREA ---
        self.input_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.input_frame.grid(row=1, column=0, sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.user_input = ctk.CTkEntry(self.input_frame, placeholder_text="Describe the task or ask about the image...", height=50)
        self.user_input.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.user_input.bind("<Return>", lambda e: self.send_request())

        self.img_button = ctk.CTkButton(self.input_frame, text="🖼️ Image", width=80, height=50, fg_color="gray30", command=self.upload_image)
        self.img_button.grid(row=0, column=1, padx=(0, 10))

        self.voice_button = ctk.CTkButton(self.input_frame, text="🎙️ Voice", width=80, height=50, fg_color="gray30", command=self.capture_voice)
        self.voice_button.grid(row=0, column=2, padx=(0, 10))

        self.send_button = ctk.CTkButton(self.input_frame, text="Execute Goal", width=120, height=50, command=self.send_request, font=ctk.CTkFont(weight="bold"))
        self.send_button.grid(row=0, column=3)

    def resolve_path(self, path):
        """Resolves a path relative to the project root and validates it's within the root."""
        absolute_root = os.path.abspath(self.project_root)
        absolute_path = os.path.abspath(os.path.join(absolute_root, path))

        if os.path.commonpath([absolute_root, absolute_path]) != absolute_root:
            raise PermissionError(f"Access denied: {path} is outside the project root.")

        return absolute_path

    def select_project_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.project_root = path
            self.append_chat(f"⚙️ [SYSTEM]: Project root changed to {path}\n", tag="system")
            self.update_files_list()

    def _load_whisper_model(self):
        \"\"\"Loads the Whisper model in the background.\"\"\"
        try:
            self.whisper_model = whisper.load_model("base")
            self.after(0, lambda: self.append_chat("⚙️ [SYSTEM]: Voice model loaded and ready.", tag="system"))
        except Exception as e:
            self.after(0, lambda: self.append_chat(f"❌ Voice model failed to load: {str(e)}", tag="system"))

    def capture_voice(self):
        """Entry point for voice recording."""
        self.voice_button.configure(text="Listening...", fg_color="red")
        threading.Thread(target=self._voice_worker, daemon=True).start()

    def _voice_worker(self):
        """Background thread to handle audio capture and transcription."""
        try:
            # Audio Configuration
            CHUNK = 1024
            FORMAT = pyaudio.paInt16
            CHANNELS = 1
            RATE = 16000
            RECORD_SECONDS = 5

            p = pyaudio.PyAudio()
            stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

            frames = []
            for _ in range(0, int(RATE / CHUNK * RECORD_SECONDS)):
                data = stream.read(CHUNK)
                frames.append(data)

            stream.stop_stream()
            stream.close()
            p.terminate()

            # Convert audio bytes to float32 numpy array for Whisper
            audio_bytes = b''.join(frames)
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            # Local transcription using the pre-loaded Whisper model
            if self.whisper_model is None:
                # Fallback if model hasn't loaded yet
                model = whisper.load_model("base")
            else:
                model = self.whisper_model

            result = model.transcribe(audio_np)
            text = result.get("text", "").strip()

            if text:
                self.after(0, lambda: self.user_input.insert(0, text))
                self.after(0, self.send_request)
            else:
                self.after(0, lambda: self.append_chat("⚠️ No speech detected.", tag="system"))

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Voice Error", f"Could not capture voice: {str(e)}"))

        finally:
            self.after(0, lambda: self.voice_button.configure(text="🎙️ Voice", fg_color="gray30"))

    def change_model(self, choice):
        for key, val in self.models_inventory.items():
            if val == choice:
                self.selected_model = key
                break
        self.append_chat(f"⚙️ System: Brain switched to {self.selected_model}\n", tag="system")

    def update_files_list(self):
        for widget in self.files_container.winfo_children():
            widget.destroy()

        files_to_show = []
        # Skip common large/hidden directories
        skip_dirs = {'.git', '.vscode', '__pycache__', 'node_modules', 'venv', '.idea'}

        for root, dirs, files in os.walk(self.project_root):
            # Modify dirs in-place to skip them in recursive walk
            dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]

            for file in files:
                if file.startswith('.'): continue
                # Get path relative to project_root
                rel_path = os.path.relpath(os.path.join(root, file), self.project_root)
                if rel_path not in ["run_gui.py", "run_agent.py"]:
                    files_to_show.append(rel_path)

        for file in sorted(files_to_show):
            btn = ctk.CTkButton(self.files_container, text=file, fg_color="transparent", text_color=("gray10", "gray90"), anchor="w", command=lambda f=file: self.open_file(f))
            btn.pack(fill="x", pady=2)

    def open_file(self, filename):
        self.current_open_file = filename
        try:
            full_path = self.resolve_path(filename)
            with open(full_path, 'r') as f:
                content = f.read()
            self.append_chat(f"\n📖 OPENING FILE: {filename}\n" + "-"*30 + f"\n{content}\n" + "-"*30 + "\n", tag="system")
            self.append_chat(f"💡 Context: The user is now focusing on {filename}.\n", tag="system")
        except Exception as e:
            self.append_chat(f"❌ Error opening file {filename}: {str(e)}\n", tag="system")

    def append_chat(self, text, tag=None):
        self.chat_display.configure(state="normal")

        # Define styles for different tags
        styles = {
            "thought": ("💭 [THOUGHT]", "#707070"),
            "action": ("🛠️ [ACTION]", "#4a9eff"),
            "observation": ("👁️ [OBSERVATION]", "#a0a0a0"),
            "system": ("⚙️ [SYSTEM]", "#ffcc00"),
            "goal": ("🎯 [GOAL]", "#ffffff")
        }

        if tag in styles:
            prefix, color = styles[tag]
            formatted_text = f"{prefix}: {text}\n"
            # Note: CTkTextbox doesn't support per-line colors easily without tags
            # but we can use clear visual markers.
        else:
            formatted_text = f"{text}\n"

        self.chat_display.insert("end", formatted_text)
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def upload_image(self):
        path = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp")])
        if path:
            self.attached_image_path = path
            self.append_chat(f"🖼️ Image attached: {os.path.basename(path)}\n", tag="system")
            self.img_button.configure(fg_color="green")

    def image_to_base64(self, path):
        with open(path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def describe_image(self, path):
        """Uses a vision model to convert image to a detailed technical description."""
        b64_image = self.image_to_base64(path)
        # Vision models in Ollama typically use /api/generate instead of /api/chat
        payload = {
            "model": VISION_MODEL,
            "prompt": "Describe this image in extreme technical detail. If it's a screenshot of code or an error, extract the exact text. If it's a design, describe the layout and components. Be precise.",
            "images": [b64_image],
            "stream": False
        }
        try:
            with httpx2.Client(timeout=120.0) as client:
                response = client.post(f"{OLLAMA_URL.replace('/api/chat', '/api/generate')}", json=payload)
                response.raise_for_status()
                return response.json().get("response", "No description returned.")
        except Exception as e:
            return f"Error describing image: {str(e)}"

    def send_request(self):
        if self.is_generating: return
        task = self.user_input.get()
        if not task.strip(): return

        self.user_input.delete(0, "end")
        self.append_chat(task, tag="goal")

        self.is_generating = True
        self.send_button.configure(state="disabled")
        threading.Thread(target=self.agent_loop, args=(task,), daemon=True).start()

    def agent_loop(self, goal):
        max_iterations = 10
        iteration = 0

        # Handle Image Description first
        visual_context = ""
        if self.attached_image_path:
            self.append_chat("👁️ Analyzing image using Vision Model...", tag="system")
            visual_context = self.describe_image(self.attached_image_path)
            self.append_chat(f"🖼️ Visual Analysis: {visual_context}\n", tag="observation")
            self.attached_image_path = None # Clear after use
            self.after(0, lambda: self.img_button.configure(fg_color="gray30"))

        system_prompt = (
            f"You are an Autonomous AI Software Engineer. Your active brain is {self.selected_model}. "
            "You solve tasks by cycling through: Thought, Action, and Observation.\n\n"
            f"Your current project root is: {self.project_root}. All file paths provided to tools should be relative to this root.\n\n"
            "IMPORTANT: You are equipped with a Vision Assistant. While you cannot 'see' images directly, "
            "any text provided as a 'Visual Analysis' or 'Observation' is a factual description of an image "
            "you have been given. TRUST THIS INFORMATION as if you saw the image yourself.\n\n"
            "AVAILABLE TOOLS:\n"
            "1. read_file(path): Returns content of a file.\n"
            "2. write_file(path, content): Writes content to a file.\n"
            "3. execute_command(command): Runs a shell command and returns output.\n"
            "4. list_files(): Lists all files in the project recursively.\n\n"
            "STRATEGY:\n"
            "- If you have the answer in the provided Visual Analysis or history, use it immediately.\n"
            "- If you need to explore or verify, use the 'Thought -> Action' cycle.\n"
            "- Be concise in your thoughts.\n\n"
            "CRITICAL FORMATTING:\n"
            "You MUST use the following tags:\n"
            "Thought: <reasoning>\n"
            "Action: <tool_name>(<args>)\n\n"
            "If you have the answer or just want to talk to the user, use:\n"
            "Final Answer: <your response>\n\n"
            "If you do not provide a 'Thought' and 'Action', or a 'Final Answer', the system will fail."
        )

        current_history = [{"role": "system", "content": system_prompt}]
        if visual_context:
            current_history.append({"role": "system", "content": f"Visual Context from Image: {visual_context}"})

        current_history.extend(self.session_history)

        full_goal = goal
        if self.current_open_file:
            full_goal = f"Context: User has {self.current_open_file} open. Request: {goal}"

        current_history.append({"role": "user", "content": full_goal})

        while iteration < max_iterations:
            iteration += 1
            self.append_chat(f"--- Iteration {iteration} ---", tag="system")

            try:
                payload = {"model": self.selected_model, "messages": current_history, "stream": False, "options": {"temperature": 0.0}}
                with httpx2.Client(timeout=900.0) as client:
                    response = client.post(OLLAMA_URL, json=payload)
                    response.raise_for_status()
                    ai_msg = response.json()["message"]["content"]

                if "Thought:" in ai_msg:
                    parts = ai_msg.split("Action:")
                    thought_part = parts[0].replace("Thought:", "").strip()
                    self.append_chat(thought_part, tag="thought")
                    if len(parts) > 1:
                        action_part = parts[1].strip()
                        self.append_chat(action_part, tag="action")
                else:
                    self.append_chat(ai_msg, tag="system")

                current_history.append({"role": "assistant", "content": ai_msg})

                if "Final Answer:" in ai_msg:
                    self.append_chat("\n✅ Goal achieved!\n", tag="system")
                    break

                if "Action:" in ai_msg:
                    action_line = [line for line in ai_msg.split("\n") if "Action:" in line][0]
                    action_call = action_line.replace("Action:", "").strip()
                    self.append_chat(f"Executing {action_call}...", tag="system")
                    observation = self.handle_tool(action_call)
                    self.append_chat(observation, tag="observation")
                    current_history.append({"role": "user", "content": f"Observation: {observation}"})
                else:
                    self.append_chat("⚠️ No action found. Prompting for next step...", tag="system")

            except Exception as e:
                self.append_chat(f"Error: {str(e)}", tag="system")
                break

        self.is_generating = False
        self.send_button.configure(state="normal")

    def handle_tool(self, call):
        try:
            if "read_file" in call:
                path = call.split("(")[1].split(")")[0].strip("'\"")
                full_path = self.resolve_path(path)
                with open(full_path, 'r') as f: return f.read()
            elif "write_file" in call:
                parts = call.split("(", 1)[1].rsplit(")", 1)[0].split(",", 1)
                path = parts[0].strip("'\"")
                content = parts[1].strip("'\"")
                full_path = self.resolve_path(path)
                with open(full_path, 'w') as f: f.write(content)
                self.update_files_list()
                return "File written successfully."
            elif "execute_command" in call:
                cmd = call.split("(")[1].split(")")[0].strip("'\"")
                # Note: We use the current project_root as the CWD for the command
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60, cwd=self.project_root)
                return f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            elif "list_files" in call:
                files_to_list = []
                skip_dirs = {'.git', '.vscode', '__pycache__', 'node_modules', 'venv', '.idea'}
                for root, dirs, files in os.walk(self.project_root):
                    dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith('.')]
                    for file in files:
                        if file.startswith('.'): continue
                        files_to_list.append(os.path.relpath(os.path.join(root, file), self.project_root))
                return str(sorted(files_to_list))
            return "Unknown tool."
        except Exception as e:
            return f"Tool Error: {str(e)}"

if __name__ == "__main__":
    app = AgenticMimoIDE()
    app.mainloop()
