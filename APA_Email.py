import customtkinter as ctk
from tkinter import messagebox, PhotoImage
import threading
import os
import subprocess
import sys
import platform
from dotenv import load_dotenv, set_key
from PIL import Image
import asyncio
from Rapports_trimestriel_APA import effectuer_rapport_async_limited
from config import Config
from email_utils import html_to_text


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS2 #type:ignore
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

ENV_FILE = resource_path(".env")

load_dotenv()

class APAGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Envoi de Rapports APA")
        self.geometry("400x350")
        self.grid_columnconfigure(0, weight=1)
        self.ENV_FILE = ".env"
        system = platform.system()
        if system == "Windows":
            icon_path = resource_path("assets/icon.ico")
            if os.path.exists(icon_path):
                try:
                    self.iconbitmap(icon_path)
                except Exception as e:
                    print(f"Windows icon load failed: {e}")
        else:
            icon_path = resource_path("assets/icon_64x64.png")
            if os.path.exists(icon_path):
                try:
                    self.icon_img = PhotoImage(file=icon_path)
                    self.iconphoto(False, self.icon_img)
                except Exception as e:
                    print(f"Unix icon load failed: {e}")

        try:
            logo_path = resource_path(r"assets\\APA.png")
            logo_img = ctk.CTkImage(Image.open(logo_path), size=(100, 100))
            ctk.CTkLabel(self, image=logo_img, text="").pack(pady=(10, 0))
        except:
            pass

        ctk.CTkLabel(self, text="Envoi Automatisé des Rapports APA", font=("Helvetica", 18)).pack(pady=10)

        self.status_label = ctk.CTkLabel(self, text="")
        self.status_label.pack(pady=5)

        ctk.CTkButton(self, text="Envoyer les Rapports", command=self.threaded_launch_script).pack(pady=10)
        ctk.CTkButton(self, text="Ouvrir le Dossier 'Protégés'", command=self.open_proteges_folder).pack(pady=5)
        ctk.CTkButton(self, text="Paramètres", command=self.open_settings).pack(pady=5)

    def threaded_launch_script(self):
        threading.Thread(target=self.launch_script, daemon=True).start()

    def launch_script(self):
        def update_status(msg):
            self.status_label.configure(text=msg)

        self.status_label.configure(text="Envoi des rapports en cours...")
        try:
            config = Config.load(self.ENV_FILE, mode="APA")
            asyncio.run(effectuer_rapport_async_limited(config=config,status_callback=update_status))
            self.status_label.configure(text="Rapports envoyés avec succès !")
            messagebox.showinfo("Succès", "Les rapports ont été envoyés avec succès !")
        except Exception as e:
            self.status_label.configure(text="Une erreur est survenue.")
            messagebox.showerror("Erreur", f"Une erreur est survenue lors de l'envoi des rapports :\n{e}")

    def open_proteges_folder(self):
        folder_path = os.path.abspath("Protégés")
        try:
            if platform.system() == "Windows":
                os.startfile(folder_path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", folder_path])
            else:
                subprocess.Popen(["xdg-open", folder_path])
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir le dossier :\n{e}")

    def open_settings(self):
        SettingsWindow(self)

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Paramètres")
        self.geometry("400x300")
        self.grid_columnconfigure(1, weight=1)

        # Icon logic (unchanged)
        import platform
        if platform.system() == "Windows":
            self.iconbitmap(resource_path("assets/icon_32x32.ico"))
        else:
            self.icon_img = PhotoImage(file=resource_path("assets/icon_64x64.png"))
            self.iconphoto(False, self.icon_img)

        self.transient(parent)
        self.grab_set()
        self.lift()
        self.focus_force()

        # --- Fields ---
        self.vars = {
            "email": ctk.StringVar(value=os.getenv("email")),
            "email_pwd": ctk.StringVar(value=os.getenv("email_pwd")),
            "NameSender": ctk.StringVar(value=os.getenv("NameSender")),
            "Role": ctk.StringVar(value=os.getenv("Role")),
        }

        labels = {
            "email": "Email",
            "email_pwd": "Mot de passe Email",
            "NameSender": "Nom de l'expéditeur",
            "Role": "Rôle",
        }

        self.pwd_entry = None  # to store reference
        self.show_pwd = False  # toggle state

        for i, (key, var) in enumerate(self.vars.items()):
            ctk.CTkLabel(self, text=labels[key]).grid(row=i, column=0, padx=10, pady=5, sticky="e")

            if key == "email_pwd":
                self.pwd_entry = ctk.CTkEntry(self, textvariable=var, show="*")
                self.pwd_entry.grid(row=i, column=1, padx=(10, 0), pady=5, sticky="ew")

                toggle_btn = ctk.CTkButton(self, text="👁", width=30, command=self.toggle_password)
                toggle_btn.grid(row=i, column=2, padx=(5, 10), pady=5)
            else:
                ctk.CTkEntry(self, textvariable=var).grid(
                    row=i, column=1, columnspan=2, padx=10, pady=5, sticky="ew"
                )

        # Bouton pour modifier le template HTML APA
        ctk.CTkButton(
            self,
            text="Modifier le modèle d’e-mail",
            command=self.open_template_editor,
        ).grid(
            row=len(self.vars) + 1,
            column=0,
            columnspan=3,
            pady=(0, 15)
        )


        ctk.CTkButton(self, text="Enregistrer", command=self.save_settings).grid(
            row=len(self.vars), column=0, columnspan=3, pady=15
        )

    def toggle_password(self):
        if self.pwd_entry:
            self.show_pwd = not self.show_pwd
            self.pwd_entry.configure(show="" if self.show_pwd else "*")

    def save_settings(self):
        for key, var in self.vars.items():
            set_key(ENV_FILE, key, var.get())
        messagebox.showinfo("Enregistré", "Paramètres enregistrés avec succès !")
        self.destroy()
    
    def open_template_editor(self):

        try:
            cfg = Config.load(ENV_FILE)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de charger la configuration :\n{e}")
            return

        TemplateEditorWindow(self, cfg)


class TemplateEditorWindow(ctk.CTkToplevel):
    def __init__(self, parent, cfg: Config):
        super().__init__(parent)
        self.cfg = cfg
        self.title("Modèle d’e-mail APA")
        self.geometry("800x600")

        # Layout
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)

        base_dir = os.path.dirname(ENV_FILE) or "."
        tpl_dir = os.path.join(base_dir, cfg.template.TEMPLATE_DIR)

        self.subject_path = os.path.join(tpl_dir, cfg.template.subject_template_name)
        self.body_html_path = os.path.join(tpl_dir, cfg.template.body_html_template_name)

        # Chargement des fichiers (ou valeurs par défaut)
        subject_txt = ""
        body_html = ""

        try:
            with open(self.subject_path, "r", encoding="utf-8") as f:
                # on enlève juste les retours de ligne en fin, le reste on garde tel quel
                subject_txt = f.read().strip("\r\n")
        except FileNotFoundError:
            subject_txt = "Rapport APA Trimestre {tri} Année {year} – {name}"

        try:
            with open(self.body_html_path, "r", encoding="utf-8") as f:
                body_html = f.read()
        except FileNotFoundError:
            body_html = (
                "<p>Bonjour,</p>\n"
                "<p>Veuillez trouver ci-joint le rapport trimestriel APA pour "
                "<strong>{name}</strong><br>\n"
                "({tri} TR {year}, envoyé le {date}).</p>\n"
                "<p>Cordialement,<br>\n"
                "{sender_name}<br>\n"
                "{sender_role}</p>\n"
            )

        # Widgets
        ctk.CTkLabel(self, text="Objet du mail (template)").grid(
            row=0, column=0, columnspan=2, padx=10, pady=(10, 5), sticky="w"
        )
        self.subject_entry = ctk.CTkEntry(self)
        self.subject_entry.grid(
            row=1, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="ew"
        )
        self.subject_entry.insert(0, subject_txt)

        ctk.CTkLabel(self, text="Corps du mail (HTML)").grid(
            row=2, column=0, columnspan=2, padx=10, pady=(0, 5), sticky="w"
        )
        self.body_text = ctk.CTkTextbox(self, wrap="word")
        self.body_text.grid(
            row=3, column=0, columnspan=2, padx=10, pady=(0, 10), sticky="nsew"
        )
        self.body_text.insert("1.0", body_html)

        ctk.CTkButton(self, text="Enregistrer", command=self.save_templates).grid(
            row=4, column=0, padx=10, pady=(0, 10), sticky="w"
        )
        ctk.CTkButton(self, text="Fermer", command=self.destroy).grid(
            row=4, column=1, padx=10, pady=(0, 10), sticky="e"
        )

        self.transient(parent)
        self.grab_set()
        self.lift()
        self.focus_force()

    def save_templates(self):
        # Sujet : on force sur une seule ligne, sans \r/\n
        subject = self.subject_entry.get().replace("\r\n", " ").replace("\n", " ").strip()
        try:
            os.makedirs(os.path.dirname(self.subject_path), exist_ok=True)
            with open(self.subject_path, "w", encoding="utf-8") as f:
                f.write(subject)
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d’enregistrer le sujet :\n{e}")
            return

        # Corps HTML
        body_html = self.body_text.get("1.0", "end").rstrip()
        try:
            os.makedirs(os.path.dirname(self.body_html_path), exist_ok=True)
            with open(self.body_html_path, "w", encoding="utf-8") as f:
                f.write(body_html + "\n")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d’enregistrer le corps HTML :\n{e}")
            return

        messagebox.showinfo("Succès", "Modèle d’e-mail enregistré.")
        self.destroy()


if __name__ == "__main__":
    config = Config.load(".env", mode="APA")

    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = APAGUI()
    app.mainloop()
