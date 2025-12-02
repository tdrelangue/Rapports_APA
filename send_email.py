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
import config
from imap_handler import add_email_to_box, find_sent_folder, find_best_folder  # nouveau handler IMAP
from config import Config  # config centralisée


# --------------------------------------------------------------------
# OUTILS GÉNÉRAUX
# --------------------------------------------------------------------


def bytes_size(paths):
    return sum(os.path.getsize(p) for p in paths if os.path.isfile(p))


def est_smtp_mb(paths, config: Config):
    return bytes_size(paths) * config.smtp.b64_overhead / (1024 * 1024)


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

def smtp_connect(config: Config):

    host = config.smtp.host
    port = config.smtp.port
    use_ssl = config.smtp.use_ssl
    user = config.identity.email
    pwd = config.identity.email_pwd

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


def smtp_send_verified(msg: EmailMessage, config: Config):
    """
    Envoi SMTP avec DSN si (et seulement si) annoncé par le serveur
    et activé via SMTP_REQUEST_DSN.
    Retourne un dict {accepted, used_dsn, message_id, copied_sent}.
    """

    res = {
        "accepted": False,
        "used_dsn": False,
        "message_id": msg["Message-ID"],
        "copied_sent": False,
    }

    s = smtp_connect(config)
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

        rcpt_opts = [config.smtp.dsn_options] if (config.smtp.request_dsn and support_dsn) else None
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

def send_email(config: Config, ctx=None, dev=False ) -> bool:
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

    if ctx is None:
        attachments = [
            "Protégés/TEST test/COS Drelangue.pdf"
        ]
        ctx = {
            "name": "Dupont Jeanne",
            "tri": 3,
            "year": 2025,
            "date": datetime.now().strftime("%d/%m/%Y"),
            "sender_name": config.identity.name_sender,
            "sender_role": config.identity.role,
            "attachments": attachments,
        }

    # 1) Compose le message (subject + corps depuis templates/.env)
    msg = compose_email(config=config, context=ctx)  # From/To/Subject/Body déjà posés
    mid = msg["Message-ID"]

    sender_env = config.identity.email
    if config.smtp.request_dsn:
        # Demande d'accusé de lecture (MDN)
        msg["Disposition-Notification-To"] = sender_env
        # Variante ancienne encore utilisée
        msg["Return-Receipt-To"] = sender_env

    # 2) Pièces jointes + zip si trop gros
    attachments = ctx["attachments"]
    tmpdir = None

    size_mb = est_smtp_mb(attachments, config=config)
    if size_mb > config.smtp.max_mb:
        attachments, tmpdir = zip_all(ctx["name"], attachments)
        ctx["attachments"] = attachments

    attach_files(msg, attachments)


    # 3) Envoi SMTP vérifié
    result = smtp_send_verified(msg, config)

    # 4) Copie IMAP “Envoyés” via imap_handler (optionnelle)
    if config.imap.copy_sent and result["accepted"]:
        user = config.identity.email
        pwd = config.identity.email_pwd
        server = config.imap.host

        if server and user and pwd:
            sent_folder, _, _ = find_sent_folder(server, user, pwd, config.imap.sentbox_name)
            APA_folder = config.imap.mailbox_name
            if sent_folder:
                err = add_email_to_box(server, user, pwd, sent_folder, msg.as_bytes())
                result["copied_sent"] = (err is None)
                if not dev and err:
                    print(f"[IMAP] Append échec: {err}")
            else:
                if not dev:
                    print("[IMAP] Impossible de déterminer le dossier 'Envoyés'.")
            if APA_folder:
                APA_folder, _ = find_best_folder(
                                    target_name=APA_folder, 
                                    IMAP_SERVER=server, 
                                    MAIL_USERNAME=user, 
                                    MAIL_PASSWORD=pwd)
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
    if config.smtp.request_dsn:
        result['used_dsn']=True

    # 6) Rapport console
    if not dev:
        print("=== ENVOI ===")
        print(f"Message-ID: {mid}")
        print(f"SMTP accepté: {result['accepted']}")
        print(f"DSN utilisé: {result['used_dsn']}")
        print(f"Copié 'Envoyés' IMAP: {result['copied_sent']}")
        print(f"Taille estimée SMTP avant envoi: {size_mb:.2f} MB (seuil {config.smtp.max_mb} MB)")
        if size_mb > config.smtp.max_mb:
            print("→ Fichiers zippés avant envoi.")

    return bool(result.get("accepted")) # TODO : change to full result and correct subsequent functions


# --------------------------------------------------------------------
# TEST LOCAL
# --------------------------------------------------------------------

if __name__ == "__main__":
    # Test simple : envoi d'un mail avec ctx par défaut
    ok = send_email(config=Config.load())
    print("Résultat send_email() :", ok)
