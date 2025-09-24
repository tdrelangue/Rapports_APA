# send_email.py
import os, smtplib, imaplib, zipfile, tempfile, shutil
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from datetime import datetime
import imaplib, os, time, re
from dotenv import load_dotenv
from Email import compose_email  # réutilisé

B64_OVERHEAD = float(os.getenv("B64_OVERHEAD", "1.37"))
MAX_MB = float(os.getenv("SMTP_MAX_MB", "19"))  # seuil avant zip
IMAP_COPY_SENT = os.getenv("IMAP_COPY_SENT", "0") == "1"
IMAP_SENT_FOLDER = os.getenv("IMAP_SENT_FOLDER", '"Sent"')

def guess_imap_host(email: str | None) -> str | None:
    if email is None:
        return None
    domain = email.split("@")[-1].lower()
    if domain == "gmail.com":
        return "imap.gmail.com"
    if any(k in domain for k in ("outlook","hotmail","live","office365")):
        return "outlook.office365.com"
    if "yahoo" in domain:
        return "imap.mail.yahoo.com"
    if "orange.fr" in domain:
        return "imap.orange.fr"
    return f"imap.{domain}"

def bytes_size(paths):
    return sum(os.path.getsize(p) for p in paths if os.path.isfile(p))

def est_smtp_mb(paths):
    return bytes_size(paths) * B64_OVERHEAD / (1024*1024)

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
            msg.add_attachment(f.read(), maintype="application", subtype="octet-stream",
                               filename=os.path.basename(p))

def smtp_connect():
    load_dotenv()
    host = os.getenv("SMTP_HOST", "smtp.orange.fr")
    port = int(os.getenv("SMTP_PORT", "465"))
    use_ssl = os.getenv("SMTP_SSL", "1") == "1"
    user = os.getenv("email")
    pwd  = os.getenv("email_pwd")
    if use_ssl:
        s = smtplib.SMTP_SSL(host, port, timeout=60)
        s.ehlo()
    else:
        s = smtplib.SMTP(host, port, timeout=60)
        s.ehlo()
        try: s.starttls(); s.ehlo()
        except smtplib.SMTPException: pass
    s.login(user, pwd) # pyright: ignore[reportArgumentType]
    return s

def smtp_send_verified(msg: EmailMessage):
    """Envoi SMTP avec DSN si (et seulement si) annoncé. Retourne un dict état."""
    

    want_dsn = os.getenv("SMTP_REQUEST_DSN", "1") == "1"
    res = {"accepted": False, "used_dsn": False, "message_id": msg["Message-ID"], "copied_sent": False}

    s = smtp_connect()  # doit créer SMTP/SMTP_SSL et faire login
    try:
        # S'assurer d'un EHLO après connexion ET après STARTTLS éventuel
        try:
            s.ehlo()
        except Exception:
            pass
        # Certains smtp_connect() encapsulent STARTTLS; sinon:
        if hasattr(s, "starttls") and getattr(s, "_tls_established", False) is False:
            try:
                s.starttls()
                s.ehlo()
            except Exception:
                pass

        feats = getattr(s, "esmtp_features", {}) or {}
        # has_extn gère les cas-insensibles si dispo
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
        try: s.quit()
        except Exception: s.close()
    return res


def _normalize_name(s: str) -> str:
    # retire quotes et guillemets
    return s.strip().strip('"').strip()

def _list_mailboxes(imap: imaplib.IMAP4_SSL) -> list[str]:
    typ, data = imap.list()
    if typ != "OK" or not data: return []
    boxes = []
    for raw in data:
        line = raw.decode(errors="ignore") # type: ignore
        # format typique: (* FLAGS) "DELIM" "NAME"
        m = re.search(r'".*"\s+"(.+)"$', line)
        boxes.append(_normalize_name(m.group(1) if m else line.split()[-1]))
    return boxes

def _guess_sent_folder(candidates: list[str]) -> str | None:
    # ordre de préférence
    prefs = ["Sent", "Envoyés", "Envoyes", "INBOX.Sent", "INBOX/Sent", "Boîte d’envoi", "Envoyati", "[Gmail]/Sent Mail"]
    low = {c.lower(): c for c in candidates}
    print(candidates)
    for p in prefs:
        if p.lower() in low: return low[p.lower()]
    # heuristique: mot-clé
    for c in candidates:
        if "sent" in c.lower() or "envoy" in c.lower():
            return c
    return None

def imap_append_sent(raw_msg: bytes) -> tuple[bool, str | None]:
    user = os.getenv("email"); pwd = os.getenv("email_pwd")
    host = guess_imap_host(user or "")
    if not (host and user and pwd):
        return False, "IMAP config incomplète"

    try:
        imap = imaplib.IMAP4_SSL(host)
        imap.login(user, pwd)

        boxes = _list_mailboxes(imap)
        print(boxes)
        folder = _guess_sent_folder(boxes) or os.getenv("IMAP_SENT_FOLDER", "Sent")

        # crée 'Sent' si inexistant
        if folder not in boxes and folder == "Sent":
            imap.create("Sent")

        date_str = imaplib.Time2Internaldate(time.time())
        typ, _ = imap.append(folder, '', date_str, raw_msg)
        imap.logout()
        return (typ == "OK"), (None if typ == "OK" else f"APPEND={typ} dossier={folder}")
    except Exception as e:
        return False, str(e)

def send_email(ctx=None, dev=False):
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
            "attachments": attachments
        }
    # 2) Compose le message (subject + corps depuis templates/.env)
    msg = compose_email(ctx)  # From/To/Subject/Body déjà posés
    mid = msg["Message-ID"]

    # 3) Pièces jointes + zip si trop gros
    
    tmpdir = None
    size_mb = est_smtp_mb(attachments)
    if size_mb > MAX_MB:
        attachments, tmpdir = zip_all(ctx["name"], attachments)
    attach_files(msg, attachments)

    # 4) Envoi SMTP vérifié
    result = smtp_send_verified(msg)

    # 5) Copie IMAP “Envoyés” optionnelle
    if IMAP_COPY_SENT and result["accepted"]:
        ok, err = imap_append_sent(msg.as_bytes())
        result["copied_sent"] = ok
        if not ok and err: print(f"[IMAP] Append échec: {err}")

    # 6) Nettoyage zip si créé
    if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True)

    # 7) Rapport console
    if not dev:
        print("=== ENVOI ===")
        print(f"Message-ID: {mid}")
        print(f"SMTP accepté: {result['accepted']}")
        print(f"DSN utilisé: {result['used_dsn']}")
        print(f"Copié 'Envoyés' IMAP: {result['copied_sent']}")
        print(f"Taille estimée SMTP avant envoi: {size_mb:.2f} MB (seuil {MAX_MB} MB)")
        if size_mb > MAX_MB: print("→ Fichiers zippés avant envoi.")

if __name__ == "__main__":
    send_email()
