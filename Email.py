import os
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from datetime import datetime
from string import Template
from config import Config
from email_utils import html_to_text
# --------- Templates ---------

def load_template(TEMPLATE_DIR:str, name: str) -> str:
    """Charge un template texte depuis le dossier templates/"""
    path = os.path.join(TEMPLATE_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

# --------- Create Email ---------

def compose_email(config: Config, context: dict) -> EmailMessage:
    """Construit un EmailMessage à partir des templates et du contexte"""

    TEMPLATE_DIR = config.template.TEMPLATE_DIR
    sender = config.identity.email
    recipient = config.identity.emailrec
    # ---- Sujet ----
    subject_tpl = load_template(TEMPLATE_DIR, config.template.subject_template_name)
    subject_tpl = subject_tpl.replace("\r", " ").replace("\n", " ").strip()
    subject = subject_tpl.format_map(context)

    # ---- Corps HTML ----
    body_html_tpl = load_template(TEMPLATE_DIR, config.template.body_html_template_name)
    body_html = Template(body_html_tpl).substitute(context)

        # ---- Corps TXT (obligatoire) ----
    body_txt = html_to_text(body_html)

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
    # Exemple de contexte pour test
    ctx = {
        "name": "Dupont Jeanne",
        "tri": 3,
        "year": 2025,
        "date": datetime.now().strftime("%d/%m/%Y"),
        "sender_name": "Christelle Drelangue",
        "sender_role": "Mandataire Judiciaire à la Protection des Majeurs",
    }

    cfg = Config.load()
    email = compose_email(cfg, ctx)

    print("==== SUBJECT ====")
    print(email["Subject"])

    print("\n==== BODY (plain) ====")
    print(email.get_body(preferencelist=("plain",)).get_content())  # type: ignore

    print("\n==== BODY (html) ====")
    html_part = email.get_body(preferencelist=("html",))
    if html_part is not None:
        print(html_part.get_content())  # type: ignore
    else:
        print("(pas de partie HTML)")