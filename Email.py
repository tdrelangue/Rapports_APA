import os
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from datetime import datetime
from string import Template
from dotenv import load_dotenv

# --------- CONFIGURATION ---------
TEMPLATE_DIR = "templates"

def load_template(name: str) -> str:
    """Charge un template texte depuis le dossier templates/"""
    path = os.path.join(TEMPLATE_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def compose_email(context: dict) -> EmailMessage:
    """Construit un EmailMessage à partir des templates et du contexte"""
    load_dotenv()
    sender = os.getenv("email", "expediteur@example.com")
    recipient = os.getenv("emailrec", "destinataire@example.com")
    subject_tpl =  "Rapport APA Timestre {tri} Année {year} – {name}"

    # Lecture templates
    body_txt_tpl = load_template("body.txt")
    try:
        body_html_tpl = load_template("body.html")
    except FileNotFoundError:
        body_html_tpl = None

    # Substitution variables
    subject = subject_tpl.format_map(context)
    body_txt = Template(body_txt_tpl).substitute(context)
    body_html = Template(body_html_tpl).substitute(context) if body_html_tpl else None

    # Construction message
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Date"] = formatdate(localtime=True)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.set_content(body_txt)

    if body_html:
        msg.add_alternative(body_html, subtype="html")

    return msg

if __name__ == "__main__":
    # Exemple de contexte
    ctx = {
        "name": "Dupont Jeanne",
        "tri": 3,
        "year": 2025,
        "date": datetime.now().strftime("%d/%m/%Y"),
        "sender_name": "Christelle Drelangue",
        "sender_role": "Mandataire Judiciaire à la Protection des Majeurs"
    }

    email = compose_email(ctx)

    try:
        # Impression console
        print("==== SUBJECT ====")
        print(email["Subject"])
        print("\n==== BODY TEXT ====")
        print(email.get_body(preferencelist=("plain",)).get_content()) # type: ignore
        print("\n==== BODY HTML ====")
        if email.get_body(preferencelist=("html",)):
            print(email.get_body(preferencelist=("html",)).get_content()) # type: ignore
    except:
        pass