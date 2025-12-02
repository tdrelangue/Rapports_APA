# send_email.py

import os
import smtplib
import zipfile
import tempfile
import shutil
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from datetime import datetime
from dotenv import load_dotenv

from Email import compose_email  # ton composeur de message
from imap_handler import add_email_to_box, find_sent_folder, find_best_folder  # nouveau handler IMAP

# --------------------------------------------------------------------
# CONFIG DE BASE (lue une fois, rechargée ensuite dans les fonctions)
# --------------------------------------------------------------------

B64_OVERHEAD = float(os.getenv("B64_OVERHEAD", "1.37"))
MAX_MB = float(os.getenv("SMTP_MAX_MB", "19"))  # seuil avant zip
IMAP_COPY_SENT = os.getenv("IMAP_COPY_SENT", "0") == "1"


# --------------------------------------------------------------------
# OUTILS GÉNÉRAUX
# --------------------------------------------------------------------

def guess_imap_host(email: str | None) -> str | None:
    if email is None:
        return None
    domain = email.split("@")[-1].lower()
    if domain == "gmail.com":
        return "imap.gmail.com"
    if any(k in domain for k in ("outlook", "hotmail", "live", "office365")):
        return "outlook.office365.com"
    if "yahoo" in domain:
        return "imap.mail.yahoo.com"
    if "orange.fr" in domain:
        return "imap.orange.fr"
    return f"imap.{domain}"


def bytes_size(paths):
    return sum(os.path.getsize(p) for p in paths if os.path.isfile(p))


def est_smtp_mb(paths):
    return bytes_size(paths) * B64_OVERHEAD / (1024 * 1024)


def zip_all(label, paths):
    tmpdir = tempfile.mkdtemp(prefix=f"mailzip_{label}_")
    zpath = os.path.join(tmpdir, f"{label}.zip")
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=os.path.basename(p))
    return [zpath], tmpdir


def attach_files(msg: EmailMessage, paths):
    for p in paths:
        with open(p, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="application",
                subtype="octet-stream",
                filename=os.path.basename(p),
            )


# --------------------------------------------------------------------
# SMTP
# --------------------------------------------------------------------

def smtp_connect():
    # Important : on recharge l'env à chaque envoi pour prendre les
    # modifs de .env en compte
    load_dotenv(override=True)

    host = os.getenv("SMTP_HOST", "smtp.orange.fr")
    port = int(os.getenv("SMTP_PORT", "465"))
    use_ssl = os.getenv("SMTP_SSL", "1") == "1"
    user = os.getenv("email")
    pwd = os.getenv("email_pwd")

    if use_ssl:
        s = smtplib.SMTP_SSL(host, port, timeout=60)
        s.ehlo()
    else:
        s = smtplib.SMTP(host, port, timeout=60)
        s.ehlo()
        try:
            s.starttls()
            s.ehlo()
        except smtplib.SMTPException:
            pass

    s.login(user, pwd)  # pyright: ignore[reportArgumentType]
    return s


def smtp_send_verified(msg: EmailMessage):
    """
    Envoi SMTP avec DSN si (et seulement si) annoncé par le serveur
    et activé via SMTP_REQUEST_DSN.
    Retourne un dict {accepted, used_dsn, message_id, copied_sent}.
    """
    load_dotenv(override=True)

    want_dsn = os.getenv("SMTP_REQUEST_DSN", "1") == "1"
    res = {
        "accepted": False,
        "used_dsn": False,
        "message_id": msg["Message-ID"],
        "copied_sent": False,
    }

    s = smtp_connect()
    try:
        try:
            s.ehlo()
        except Exception:
            pass

        if hasattr(s, "starttls") and getattr(s, "_tls_established", False) is False:
            try:
                s.starttls()
                s.ehlo()
            except Exception:
                pass

        feats = getattr(s, "esmtp_features", {}) or {}
        support_dsn = (hasattr(s, "has_extn") and s.has_extn("dsn")) or ("dsn" in feats)

        rcpt_opts = ["NOTIFY=SUCCESS,FAILURE,DELAY"] if (want_dsn and support_dsn) else None
        res["used_dsn"] = bool(rcpt_opts)

        try:
            if rcpt_opts:
                s.send_message(msg, mail_options=[], rcpt_options=rcpt_opts)
            else:
                s.send_message(msg, mail_options=[])
            res["accepted"] = True
        except smtplib.SMTPRecipientsRefused as e:
            # Si le serveur a interprété NOTIFY comme partie de l'adresse, retente sans DSN
            err = next(iter(e.recipients.values()))
            if b"NOTIFY=" in err[1] or "NOTIFY=" in str(err[1]):
                s.send_message(msg, mail_options=[])
                res["accepted"] = True
                res["used_dsn"] = False
            else:
                raise
    finally:
        try:
            s.quit()
        except Exception:
            s.close()

    return res

# --------------------------------------------------------------------
# FONCTION PRINCIPALE D’ENVOI
# --------------------------------------------------------------------

def send_email(ctx=None, dev=False) -> bool:
    """
    ctx : dict contenant au minimum :
      - name
      - tri
      - year
      - date
      - sender_name
      - sender_role
      - attachments : liste de chemins

    Retourne True si SMTP a accepté le message.
    """
    load_dotenv(override=True)

    if ctx is None:
        attachments = [
            "Protégés/TEST test/COS Drelangue.pdf"
        ]
        ctx = {
            "name": "Dupont Jeanne",
            "tri": 3,
            "year": 2025,
            "date": datetime.now().strftime("%d/%m/%Y"),
            "sender_name": os.getenv("NameSender", ""),
            "sender_role": os.getenv("Role", ""),
            "attachments": attachments,
        }

    # 1) Compose le message (subject + corps depuis templates/.env)
    msg = compose_email(ctx)  # From/To/Subject/Body déjà posés
    mid = msg["Message-ID"]

    sender_env = os.getenv("email", "expediteur@example.com")
    # Demande d'accusé de lecture (MDN)
    msg["Disposition-Notification-To"] = sender_env
    # Variante ancienne encore utilisée
    msg["Return-Receipt-To"] = sender_env

    # 2) Pièces jointes + zip si trop gros
    attachments = ctx["attachments"]
    tmpdir = None

    size_mb = est_smtp_mb(attachments)
    if size_mb > MAX_MB:
        attachments, tmpdir = zip_all(ctx["name"], attachments)
        ctx["attachments"] = attachments

    attach_files(msg, attachments)

    # 3) Envoi SMTP vérifié
    result = smtp_send_verified(msg)

    # 4) Copie IMAP “Envoyés” via imap_handler (optionnelle)
    if IMAP_COPY_SENT and result["accepted"]:
        user = os.getenv("email")
        pwd = os.getenv("email_pwd")
        server = guess_imap_host(user)

        if server and user and pwd:
            sent_folder = find_sent_folder(server, user, pwd)
            APA_folder = os.getenv("email")
            if sent_folder:
                err = add_email_to_box(server, user, pwd, sent_folder, msg.as_bytes())
                result["copied_sent"] = (err is None)
                if not dev and err:
                    print(f"[IMAP] Append échec: {err}")
            else:
                if not dev:
                    print("[IMAP] Impossible de déterminer le dossier 'Envoyés'.")
            if APA_folder:
                APA_folder, _ = find_best_folder(APA_folder, server, user, pwd)
                err = add_email_to_box(server, user, pwd, APA_folder, msg.as_bytes())
                result["copied_sent"] = (err is None)
                if not dev and err:
                    print(f"[IMAP] Append échec: {err}")
            else:
                if not dev:
                    print(f"[IMAP] Impossible de déterminer le dossier '{APA_folder}'.")

    # 5) Nettoyage zip si créé
    if tmpdir:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # 6) Rapport console
    if not dev:
        print("=== ENVOI ===")
        print(f"Message-ID: {mid}")
        print(f"SMTP accepté: {result['accepted']}")
        print(f"DSN utilisé: {result['used_dsn']}")
        print(f"Copié 'Envoyés' IMAP: {result['copied_sent']}")
        print(f"Taille estimée SMTP avant envoi: {size_mb:.2f} MB (seuil {MAX_MB} MB)")
        if size_mb > MAX_MB:
            print("→ Fichiers zippés avant envoi.")

    return bool(result.get("accepted"))


# --------------------------------------------------------------------
# TEST LOCAL
# --------------------------------------------------------------------

if __name__ == "__main__":
    # Test simple : envoi d'un mail avec ctx par défaut
    ok = send_email()
    print("Résultat send_email() :", ok)
