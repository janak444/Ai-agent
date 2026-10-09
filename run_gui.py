import os
import glob
import json
import httpx2
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Configuration
OLLAMA_URL = "http://localhost:11434/api/chat"

class MimoCodeIDE(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Mimo-Code IDE | Local AI Agent")
        self.geometry("1200x800")
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
        # Grid configuration
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # --- SIDEBAR ---
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(3, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar, text="MIMO-CODE", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=20)

        self.model_label = ctk.CTkLabel(self.sidebar, text="Select Brain:")
        self.model_label.grid(row=1, column=0, padx=20, pady=(10, 0))

        self.model_dropdown = ctk.CTkOptionMenu(
            self.sidebar,
            values=list(self.models_inventory.values()),
            command=self.change_model
        )
        self.model_dropdown.grid(row=2, column=0, padx=20, pady=10)

        self.files_label = ctk.CTkLabel(self.sidebar, text="Local Workspace:")
        self.files_label.grid(row=3, column=0, padx=20, pady=(20, 0), sticky="nw")

        self.files_list = ctk.CTkTextbox(self.sidebar, width=200, height=300)
        self.files_list.grid(row=4, column=0, padx=20, pady=10, sticky="nsew")
        self.update_files_list()

        # --- MAIN CHAT AREA ---
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

        self.user_input = ctk.CTkEntry(self.input_frame, placeholder_text="Enter your application requirements...", height=45)
        self.user_input.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.user_input.bind("<Return>", lambda e: self.send_request())

        self.send_button = ctk.CTkButton(self.input_frame, text="Run Agent", width=100, height=45, command=self.send_request)
        self.send_button.grid(row=0, column=1)

    def change_model(self, choice):
        # Get key from value
        for key, val in self.models_inventory.items():
            if val == choice:
                self.selected_model = key
                break
        self.append_chat(f"⚙️ System: Active Engine changed to {self.selected_model}\n")

    def update_files_list(self):
        files = [f for f in glob.glob("*") if os.path.isfile(f) and f != "run_agent.py" and f != "run_gui.py"]
        self.files_list.configure(state="normal")
        self.files_list.delete("1.0", "end")
        self.files_list.insert("end", "\n".join(files))
        self.files_list.configure(state="disabled")

    def append_chat(self, text):
        self.chat_display.configure(state="normal")
        self.chat_display.insert("end", text)
        self.chat_display.see("end")
        self.chat_display.configure(state="disabled")

    def send_request(self):
        if self.is_generating:
            return

        task = self.user_input.get()
        if not task.strip():
            return

        self.user_input.delete(0, "end")
        self.append_chat(f"\n👉 User: {task}\n")
        self.append_chat(f"🧠 Thinking (via {self.selected_model})...\n")

        # Start generation in a separate thread to keep GUI responsive
        self.is_generating = True
        self.send_button.configure(state="disabled")
        threading.Thread(target=self.run_agent_logic, args=(task,), daemon=True).start()

    def run_agent_logic(self, task):
        try:
            messages = [{"role": "system", "content": "You are an expert autonomous software engineer. Output code in ```python blocks."}]
            messages.extend(self.session_history)
            messages.append({"role": "user", "content": task})

            payload = {
                "model": self.selected_model,
                "messages": messages,
                "stream": True,
                "options": {"temperature": 0.2}
            }

            full_response = ""
            with httpx2.Client(timeout=900.0) as client:
                with client.stream("POST", OLLAMA_URL, json=payload) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line:
                            line_decoded = line.decode('utf-8') if isinstance(line, bytes) else line
                            chunk = json.loads(line_decoded)
                            if "message" in chunk:
                                content = chunk["message"].get("content", "")
                                self.append_chat(content)
                                full_response += content
                            if chunk.get("done"):
                                break

            self.append_chat("\n")
            self.session_history.append({"role": "user", "content": task})
            self.session_history.append({"role": "assistant", "content": full_response})

            if "```python" in full_response:
                # Use a popup to ask for saving
                self.after(0, lambda: self.ask_to_save(full_response))

        except Exception as e:
            self.append_chat(f"\n❌ Error: {str(e)}\n")
        finally:
            self.is_generating = False
            self.send_button.configure(state="normal")

    def ask_to_save(self, content):
        if messagebox.askyesno("Code Detected", "I detected Python code! Would you like to save it to a file?"):
            filename = filedialog.asksaveasfilename(defaultextension=".py",
                                                     filetypes=[("Python files", "*.py"), ("All files", "*.*")])
            if filename:
                try:
                    code_block = content.split("```python")[1].split("```")[0].strip()
                    with open(filename, 'w') as f:
                        f.write(code_block)
                    self.append_chat(f"\n✅ Saved as {os.path.basename(filename)}\n")
                    self.update_files_list()
                except Exception as e:
                    messagebox.showerror("Save Error", f"Could not save file: {e}")

if __name__ == "__main__":
    app = MimoCodeIDE()
    app.mainloop()
