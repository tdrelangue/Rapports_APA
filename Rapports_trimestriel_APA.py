import os
import asyncio
import smtplib
import imaplib
import zipfile
import tempfile
import shutil
import time
from typing import List, Optional, Tuple
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from datetime import datetime
from dotenv import load_dotenv

# ---------- Configuration ----------
B64_OVERHEAD = 1.37
DEFAULT_MAX_MB = float(os.getenv("SMTP_MAX_MB", "19"))   # info log uniquement
CONCURRENCY = int(os.getenv("SMTP_CONCURRENCY", "3"))
REQUEST_DSN = os.getenv("SMTP_REQUEST_DSN", "1") == "1"
COPY_TO_SENT = os.getenv("IMAP_COPY_SENT", "0") == "1"
IMAP_SENT_FOLDER = os.getenv("IMAP_SENT_FOLDER", '"Sent"')
PROTEGES_DIR = os.getenv("PROTEGES_DIR", "Protégés")
LOG_DIR = os.getenv("LOG_DIR", "logs")

# ---------- Utilitaires ----------
def log_message(log_dir: str, txt: str) -> None:
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "log.txt")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {txt}\n")
    print(txt)

def attachments_size_mb(paths: List[str]) -> float:
    return sum(os.path.getsize(p) for p in paths if os.path.isfile(p)) / (1024 * 1024)

def zip_attachments(label: str, attachments: List[str]) -> Tuple[List[str], str]:
    tmpdir = tempfile.mkdtemp(prefix=f"apa_{label}_")
    zip_path = os.path.join(tmpdir, f"{label}.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in attachments:
            zf.write(p, arcname=os.path.basename(p))
    return [zip_path], tmpdir

def get_smtp_config(sender_email: str) -> Tuple[str, int, bool, Optional[str]]:
    env_host = os.getenv("SMTP_HOST")
    env_port = os.getenv("SMTP_PORT")
    env_ssl = os.getenv("SMTP_SSL")
    env_imap = os.getenv("IMAP_HOST")
    if env_host and env_port:
        return env_host, int(env_port), (env_ssl or "1") == "1", env_imap

    domain = sender_email.split("@")[-1].lower()
    if domain == "gmail.com":
        return "smtp.gmail.com", 465, True, env_imap or "imap.gmail.com"
    if any(k in domain for k in ("outlook", "hotmail", "live", "office365")):
        return "smtp.office365.com", 587, False, env_imap or "outlook.office365.com"
    if "yahoo" in domain:
        return "smtp.mail.yahoo.com", 465, True, env_imap or "imap.mail.yahoo.com"
    return f"smtp.{domain}", 465, True, env_imap or f"imap.{domain}"

def build_message(
    sender: str,
    recipient: str,
    subject: str,
    body: str,
    attachments: List[str],
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Date"] = formatdate(localtime=True)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.set_content(body)
    for p in attachments:
        with open(p, "rb") as f:
            data = f.read()
        filename = os.path.basename(p)
        msg.add_attachment(
            data,
            maintype="application",
            subtype="octet-stream",
            filename=filename,
        )
    return msg

def smtp_send_message(
    msg, smtp_host, smtp_port, use_ssl, user, pwd, request_dsn: bool
) -> None:
    mail_opts = []  # ex: ["RET=HDRS"] si tu veux
    if use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=60) as s:
            s.ehlo()
            s.login(user, pwd)
            # DSN seulement si annoncé
            support_dsn = "dsn" in (s.esmtp_features or {})
            rcpt_opts = ["NOTIFY=SUCCESS,FAILURE,DELAY"] if (request_dsn and support_dsn) else []
            s.send_message(msg, mail_options=mail_opts, rcpt_options=rcpt_opts)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()  # renégociation des features
            s.login(user, pwd)
            support_dsn = "dsn" in (s.esmtp_features or {})
            rcpt_opts = ["NOTIFY=SUCCESS,FAILURE,DELAY"] if (request_dsn and support_dsn) else []
            s.send_message(msg, mail_options=mail_opts, rcpt_options=rcpt_opts)


def imap_append_sent(imap_host: str, user: str, pwd: str, raw_msg: bytes) -> Optional[str]:
    try:
        imap = imaplib.IMAP4_SSL(imap_host)
        imap.login(user, pwd)

        date_str = imaplib.Time2Internaldate(time.time())
        typ, _ = imap.append(IMAP_SENT_FOLDER,  '', date_str, raw_msg)
        imap.logout()
        if typ != "OK":
            return f"IMAP APPEND non OK: {typ}"
        return None
    except Exception as e:
        return str(e)

def _collect_env() -> Tuple[str, str, str]:
    load_dotenv()
    sender = os.getenv("email", "")
    pwd = os.getenv("email_pwd", "")
    recipient = os.getenv("emailrec", "")
    return sender, pwd, recipient

def _list_proteges(root: str) -> List[str]:
    try:
        return [os.path.join(root, n) for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    except FileNotFoundError:
        return []

def _list_files(dir_path: str) -> List[str]:
    return [os.path.join(dir_path, n) for n in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, n))]

# ---------- Envoi avec fallback zip ----------
async def _send_one(
    sem: asyncio.Semaphore,
    protege_name: str,
    recipient: str,
    subject: str,
    body: str,
    files: List[str],
    sender: str,
    pwd: str,
    log_dir: str,
) -> bool:
    async with sem:
        smtp_host, smtp_port, use_ssl, imap_host = get_smtp_config(sender)

        # Tentative 1: en l'état
        try:
            est_total_mb = attachments_size_mb(files) * B64_OVERHEAD
            msg = build_message(sender, recipient, subject, body, files)
            mid = msg["Message-ID"]
            smtp_send_message(msg, smtp_host, smtp_port, use_ssl, sender, pwd, REQUEST_DSN)
            log_message(log_dir, f"OK(as-is) {protege_name} MID={mid} SMTP={smtp_host}:{smtp_port} size≈{est_total_mb:.2f}MB")

            if COPY_TO_SENT and imap_host:
                err = imap_append_sent(imap_host, sender, pwd, msg.as_bytes())
                if err:
                    log_message(log_dir, f"IMAP APPEND échec {protege_name} MID={mid}: {err}")
                else:
                    log_message(log_dir, f"IMAP APPEND OK {protege_name} MID={mid}")
            return True

        except smtplib.SMTPResponseException as e:
            code = getattr(e, "smtp_code", None)
            err = getattr(e, "smtp_error", b"").decode(errors="ignore")
            log_message(log_dir, f"First attempt FAIL {protege_name} code={code} err={err}")

        except Exception as e:
            log_message(log_dir, f"First attempt FAIL {protege_name} err={e}")

        # Tentative 2: fallback zip
        tmpdir = None
        try:
            atts, tmpdir = zip_attachments(protege_name, files)
            est_zip_mb = attachments_size_mb(atts) * B64_OVERHEAD
            msg2 = build_message(sender, recipient, f"{subject} (ZIP)", body, atts)
            mid2 = msg2["Message-ID"]
            smtp_send_message(msg2, smtp_host, smtp_port, use_ssl, sender, pwd, REQUEST_DSN)
            log_message(log_dir, f"OK(fallback-zip) {protege_name} MID={mid2} SMTP={smtp_host}:{smtp_port} size≈{est_zip_mb:.2f}MB")

            if COPY_TO_SENT and imap_host:
                err2 = imap_append_sent(imap_host, sender, pwd, msg2.as_bytes())
                if err2:
                    log_message(log_dir, f"IMAP APPEND échec {protege_name} MID={mid2}: {err2}")
                else:
                    log_message(log_dir, f"IMAP APPEND OK {protege_name} MID={mid2}")
            return True

        except Exception as e:
            log_message(log_dir, f"Fallback zip FAIL {protege_name}: {e}")
            return False

        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)

# ---------- Orchestrateur ----------
async def effectuer_rapport_APA_async_limited(status_callback=print) -> None:
    sender, pwd, recipient = _collect_env()
    if not (sender and pwd and recipient):
        raise RuntimeError("Variables d'environnement manquantes: email, email_pwd, emailrec")

    os.makedirs(LOG_DIR, exist_ok=True)
    run_dir = os.path.join(LOG_DIR, datetime.now().strftime("run_%Y%m%d_%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)

    status_callback("Préparation des envois…")
    proteges = _list_proteges(PROTEGES_DIR)
    if not proteges:
        status_callback("Aucun dossier dans 'Protégés'.")
        return

    subject = os.getenv("MAIL_SUBJECT", "Rapport trimestriel APA")
    body = os.getenv("MAIL_BODY", "Bonjour,\n\nVeuillez trouver ci-joint le rapport trimestriel APA.\n\nCordialement.")

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = []
    for p in proteges:
        protege_name = os.path.basename(p)
        files = _list_files(p)
        if not files:
            log_message(run_dir, f"No attachment found for {protege_name}, skipped.")
            continue
        # Log d’info taille “théorique”
        info_mb = attachments_size_mb(files) * B64_OVERHEAD
        log_message(run_dir, f"{protege_name}: tentative as-is, taille SMTP≈{info_mb:.2f}MB (seuil info {DEFAULT_MAX_MB}MB)")
        tasks.append(
            _send_one(
                sem, protege_name, recipient, subject, body, files, sender, pwd, run_dir
            )
        )

    results = await asyncio.gather(*tasks)
    success = sum(1 for r in results if r)
    fail = len(results) - success
    status_callback(f"Envoi terminé: {success} succès, {fail} échecs.")
    log_message(run_dir, f"Résumé: {success} succès, {fail} échecs.")

if __name__ == "__main__":
    asyncio.run(effectuer_rapport_APA_async_limited())
