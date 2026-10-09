import os
import glob
import json
import httpx2
import threading
import subprocess
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Configuration
OLLAMA_URL = "http://localhost:11434/api/chat"

class AgenticMimoIDE(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Mimo-Agentic IDE | Autonomous AI Engineer")
        self.geometry("1400x900")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # State
        self.selected_model = "qwen3-coder:30b"
        self.session_history = []
        self.is_generating = False

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

        self.files_label = ctk.CTkLabel(self.sidebar, text="Workspace Files:")
        self.files_label.grid(row=3, column=0, padx=20, pady=(20, 0), sticky="nw")

        self.files_list = ctk.CTkTextbox(self.sidebar, width=220, height=400)
        self.files_list.grid(row=4, column=0, padx=20, pady=10, sticky="nsew")
        self.update_files_list()

        # --- MAIN CONTENT AREA ---
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        self.main_container.grid_columnconfigure(0, weight=1)
        self.main_container.grid_rowconfigure(0, weight=1)

        # Chat / Reasoning Log
        self.chat_display = ctk.CTkTextbox(self.main_container, font=ctk.CTkFont(family="Consolas", size=13))
        self.chat_display.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 20))
        self.chat_display.configure(state="disabled")

        # Input Area
        self.input_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.input_frame.grid(row=1, column=0, sticky="ew")
        self.input_frame.grid_columnconfigure(0, weight=1)

        self.user_input = ctk.CTkEntry(self.input_frame, placeholder_text="Give the agent a goal (e.g., 'Create a calculator and test it')...", height=50)
        self.user_input.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.user_input.bind("<Return>", lambda e: self.send_request())

        self.send_button = ctk.CTkButton(self.input_frame, text="Execute Goal", width=120, height=50, command=self.send_request, font=ctk.CTkFont(weight="bold"))
        self.send_button.grid(row=0, column=1)

    def change_model(self, choice):
        for key, val in self.models_inventory.items():
            if val == choice:
                self.selected_model = key
                break
        self.append_chat(f"⚙️ System: Brain switched to {self.selected_model}\n")

    def update_files_list(self):
        files = [f for f in glob.glob("*") if os.path.isfile(f) and f not in ["run_gui.py", "run_agent.py"]]
        self.files_list.configure(state="normal")
        self.files_list.delete("1.0", "end")
        self.files_list.insert("end", "\n".join(files))
        self.files_list.configure(state="disabled")

    def append_chat(self, text, color=None):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", text)
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def send_request(self):
        if self.is_generating: return
        task = self.user_input.get()
        if not task.strip(): return

        self.user_input.delete(0, "end")
        self.append_chat(f"\n🎯 GOAL: {task}\n")

        self.is_generating = True
        self.send_button.configure(state="disabled")
        threading.Thread(target=self.agent_loop, args=(task,), daemon=True).start()

    def agent_loop(self, goal):
        """The Core Agentic Reasoning Loop: Thought -> Action -> Observation"""
        max_iterations = 10
        iteration = 0

        # System Prompt defining the tools
        system_prompt = (
            "You are an Autonomous AI Software Engineer. You solve tasks by cycling through: Thought, Action, and Observation.\n\n"
            "AVAILABLE TOOLS:\n"
            "1. read_file(path): Returns content of a file.\n"
            "2. write_file(path, content): Writes content to a file.\n"
            "3. execute_command(command): Runs a shell command and returns output.\n"
            "4. list_files(): Lists files in current directory.\n\n"
            "FORMAT YOUR RESPONSE AS:\n"
            "Thought: <your reasoning>\n"
            "Action: <tool_name>(<args>)\n\n"
            "When the task is complete, respond with: Final Answer: <summary of work>"
        )

        current_history = [{"role": "system", "content": system_prompt}]
        current_history.extend(self.session_history)
        current_history.append({"role": "user", "content": goal})

        while iteration < max_iterations:
            iteration += 1
            self.append_chat(f"\n--- Iteration {iteration} ---\n")

            try:
                # 1. Get AI Response
                payload = {"model": self.selected_model, "messages": current_history, "stream": False, "options": {"temperature": 0.1}}
                with httpx2.Client(timeout=900.0) as client:
                    response = client.post(OLLAMA_URL, json=payload)
                    response.raise_for_status()
                    ai_msg = response.json()["message"]["content"]

                self.append_chat(f"🤖 {ai_msg}\n")
                current_history.append({"role": "assistant", "content": ai_msg})

                if "Final Answer:" in ai_msg:
                    self.append_chat("\n✅ Goal achieved successfully!\n")
                    break

                # 2. Parse Action
                if "Action:" in ai_msg:
                    action_line = [line for line in ai_msg.split("\n") if "Action:" in line][0]
                    action_call = action_line.replace("Action:", "").strip()

                    self.append_chat(f"🛠️ Executing: {action_call}...\n")
                    observation = self.handle_tool(action_call)

                    self.append_chat(f"👁️ Observation: {observation}\n")
                    current_history.append({"role": "user", "content": f"Observation: {observation}"})
                else:
                    self.append_chat("⚠️ Agent provided no action. Prompting for next step...\n")

            except Exception as e:
                self.append_chat(f"❌ Error in loop: {str(e)}\n")
                break

        self.is_generating = False
        self.send_button.configure(state="normal")

    def handle_tool(self, call):
        """Simple parser and executor for tool calls"""
        try:
            if "read_file" in call:
                path = call.split("(")[1].split(")")[0].strip("'\"")
                with open(path, 'r') as f: return f.read()

            elif "write_file" in call:
                # format: write_file("path", "content")
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

            return "Unknown tool or invalid format."
        except Exception as e:
            return f"Tool Error: {str(e)}"

if __name__ == "__main__":
    app = AgenticMimoIDE()
    app.mainloop()
