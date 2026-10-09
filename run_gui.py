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

        self.files_label = ctk.CTkLabel(self.sidebar, text="Workspace Files (Click to Open):")
        self.files_label.grid(row=3, column=0, padx=20, pady=(20, 0), sticky="nw")

        self.files_container = ctk.CTkScrollableFrame(self.sidebar, width=220)
        self.files_container.grid(row=4, column=0, padx=10, pady=10, sticky="nsew")
        self.update_files_list()

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

        self.send_button = ctk.CTkButton(self.input_frame, text="Execute Goal", width=120, height=50, command=self.send_request, font=ctk.CTkFont(weight="bold"))
        self.send_button.grid(row=0, column=2)

    def change_model(self, choice):
        for key, val in self.models_inventory.items():
            if val == choice:
                self.selected_model = key
                break
        self.append_chat(f"⚙️ System: Brain switched to {self.selected_model}\n", tag="system")

    def update_files_list(self):
        for widget in self.files_container.winfo_children():
            widget.destroy()
        files = [f for f in glob.glob("*") if os.path.isfile(f) and f not in ["run_gui.py", "run_agent.py"]]
        for file in sorted(files):
            btn = ctk.CTkButton(self.files_container, text=file, fg_color="transparent", text_color=("gray10", "gray90"), anchor="w", command=lambda f=file: self.open_file(f))
            btn.pack(fill="x", pady=2)

    def open_file(self, filename):
        self.current_open_file = filename
        try:
            with open(filename, 'r') as f:
                content = f.read()
            self.append_chat(f"\n📖 OPENING FILE: {filename}\n" + "-"*30 + f"\n{content}\n" + "-"*30 + "\n", tag="system")
            self.append_chat(f"💡 Context: The user is now focusing on {filename}.\n", tag="system")
        except Exception as e:
            self.append_chat(f"❌ Error opening file {filename}: {str(e)}\n", tag="system")

    def append_chat(self, text, tag=None):
        self.chat_display.configure(state="normal")
        if tag == "thought": formatted_text = f"💭 [THOUGHT]: {text}\n"
        elif tag == "action": formatted_text = f"🛠️ [ACTION]: {text}\n"
        elif tag == "observation": formatted_text = f"👁️ [OBSERVATION]: {text}\n"
        elif tag == "system": formatted_text = f"⚙️ [SYSTEM]: {text}\n"
        else: formatted_text = text
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
        payload = {
            "model": VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": "Describe this image in extreme technical detail. If it's a screenshot of code or an error, extract the exact text. If it's a design, describe the layout and components. Be precise.",
                    "images": [b64_image]
                }
            ],
            "stream": False
        }
        try:
            with httpx2.Client(timeout=120.0) as client:
                response = client.post(OLLAMA_URL, json=payload)
                response.raise_for_status()
                return response.json()["message"]["content"]
        except Exception as e:
            return f"Error describing image: {str(e)}"

    def send_request(self):
        if self.is_generating: return
        task = self.user_input.get()
        if not task.strip(): return

        self.user_input.delete(0, "end")
        self.append_chat(f"\n🎯 GOAL: {task}\n", tag="system")

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
            "You are an Autonomous AI Software Engineer with Vision capabilities. "
            "You solve tasks by cycling through: Thought, Action, and Observation.\n\n"
            "AVAILABLE TOOLS:\n"
            "1. read_file(path): Returns content of a file.\n"
            "2. write_file(path, content): Writes content to a file.\n"
            "3. execute_command(command): Runs a shell command and returns output.\n"
            "4. list_files(): Lists files in current directory.\n\n"
            "STRATEGY:\n"
            "- Use visual descriptions provided as 'Observations' to debug UI or fix errors from screenshots.\n"
            "- If you have enough info, go straight to 'Final Answer'.\n"
            "- Otherwise, use 'Thought -> Action'.\n\n"
            "CRITICAL FORMATTING:\n"
            "Thought: <reasoning>\n"
            "Action: <tool_name>(<args>)\n"
            "OR\n"
            "Final Answer: <result>"
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
            self.append_chat(f"\n--- Iteration {iteration} ---\n", tag="system")

            try:
                payload = {"model": self.selected_model, "messages": current_history, "stream": False, "options": {"temperature": 0.1}}
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
                with open(path, 'r') as f: return f.read()
            elif "write_file" in call:
                parts = call.split("(", 1)[1].rsplit(")", 1)[0].split(",", 1)
                path = parts[0].strip("'\"")
                content = parts[1].strip("'\"")
                with open(path, 'w') as f: f.write(content)
                self.update_files_list()
                return "File written successfully."
            elif "execute_command" in call:
                cmd = call.split("(")[1].split(")")[0].strip("'\"")
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
                return f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            elif "list_files" in call:
                return str([f for f in glob.glob("*") if os.path.isfile(f)])
            return "Unknown tool."
        except Exception as e:
            return f"Tool Error: {str(e)}"

if __name__ == "__main__":
    app = AgenticMimoIDE()
    app.mainloop()
