import customtkinter as ctk
from tkinter import messagebox
import threading
import os
import subprocess
import sys
import platform
from dotenv import load_dotenv, set_key
from PIL import Image
from Rapports_trimestriel_APA import effectuer_rapport_APA

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS2
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

ENV_FILE = resource_path(".env")

load_dotenv()
class APAGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("APA Email Sender")
        self.geometry("400x350")
        self.grid_columnconfigure(0, weight=1)

        # Set window icon
        try:
            self.iconbitmap(resource_path(r"assets\\icon.ico"))
        except:
            pass

        # Display logo image
        try:
            logo_path = resource_path(r"assets\\APA.png")
            logo_img = ctk.CTkImage(Image.open(logo_path), size=(100, 100))
            ctk.CTkLabel(self, image=logo_img, text="").pack(pady=(10, 0))
        except:
            pass

        ctk.CTkLabel(self, text="Automated APA Email Sender", font=("Helvetica", 18)).pack(pady=10)

        self.status_label = ctk.CTkLabel(self, text="")
        self.status_label.pack(pady=5)

        os.makedirs("Protégés", exist_ok=True)

        ctk.CTkButton(self, text="Send Emails", command=self.threaded_launch_script).pack(pady=10)
        ctk.CTkButton(self, text="Open 'Protégés' Folder", command=self.open_proteges_folder).pack(pady=5)
        ctk.CTkButton(self, text="Settings", command=self.open_settings).pack(pady=5)

    def threaded_launch_script(self):
        threading.Thread(target=self.launch_script, daemon=True).start()

    def launch_script(self):
        self.status_label.configure(text="Sending emails...")
        try:
            effectuer_rapport_APA()
            self.status_label.configure(text="Emails sent successfully!")
            messagebox.showinfo("Success", "Emails sent successfully!")
        except Exception as e:
            self.status_label.configure(text="An error occurred.")
            messagebox.showerror("Error", f"An error occurred while sending emails:\n{e}")

    def open_proteges_folder(self):
        folder_path = os.path.abspath("Protégés")
        try:
            if platform.system() == "Windows":
                os.startfile(folder_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", folder_path])
            else:  # Linux
                subprocess.Popen(["xdg-open", folder_path])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder:\n{e}")

    def open_settings(self):
        SettingsWindow(self)


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Settings")
        self.geometry("400x300")
        self.grid_columnconfigure(1, weight=1)

        self.vars = {
            "email": ctk.StringVar(value=os.getenv("email")),
            "email_pwd": ctk.StringVar(value=os.getenv("email_pwd")),
            "NameSender": ctk.StringVar(value=os.getenv("NameSender")),
            "Role": ctk.StringVar(value=os.getenv("Role")),
        }

        for i, (key, var) in enumerate(self.vars.items()):
            ctk.CTkLabel(self, text=key).grid(row=i, column=0, padx=10, pady=5, sticky="e")
            ctk.CTkEntry(self, textvariable=var, show="*" if "pwd" in key else "").grid(row=i, column=1, padx=10, pady=5, sticky="ew")

        ctk.CTkButton(self, text="Save", command=self.save_settings).grid(row=len(self.vars), column=0, columnspan=2, pady=15)

    def save_settings(self):
        for key, var in self.vars.items():
            set_key(ENV_FILE, key, var.get())
        messagebox.showinfo("Saved", "Settings saved successfully!")
        self.destroy()


if __name__ == "__main__":
    ctk.set_appearance_mode("System")  # Options: "System", "Dark", "Light"
    ctk.set_default_color_theme("blue")
    app = APAGUI()
    app.mainloop()