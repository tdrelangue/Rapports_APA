import os, asyncio, smtplib, imaplib, zipfile, tempfile, shutil, time
from html import escape
from typing import List, Optional, Tuple
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from datetime import datetime, date
from dotenv import load_dotenv

# ---------- Configuration ----------
B64_OVERHEAD   = 1.37
DEFAULT_MAX_MB = float(os.getenv("SMTP_MAX_MB", "19"))   # info log
CONCURRENCY    = int(os.getenv("SMTP_CONCURRENCY", "1")) # séquentiel par défaut
REQUEST_DSN    = os.getenv("SMTP_REQUEST_DSN", "1") == "1"
COPY_TO_SENT   = os.getenv("IMAP_COPY_SENT", "0") == "1"
IMAP_SENT_FOLDER = os.getenv("IMAP_SENT_FOLDER", '"Sent"')
PROTEGES_DIR   = os.getenv("PROTEGES_DIR", "Protégés")
LOG_DIR        = os.getenv("LOG_DIR", "logs")

# ---------- Utilitaires ----------
def log_message(log_dir: str, txt: str) -> None:
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "log.txt")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {txt}\n")
    print(txt)

def init_log_session() -> str:
    run_dir = os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    os.makedirs(run_dir, exist_ok=True)
    return run_dir

def _env(key: str, default: str = "") -> str:
    v = os.getenv(key)
    return default if v is None else v.replace("\\n", "\n")

def get_env() -> tuple[str, str, str, str, str]:
    load_dotenv()
    sender   = _env("email")
    pwd      = _env("email_pwd")
    to       = _env("emailrec")
    subj_tpl = _env("MAIL_SUBJECT", "Rapport trimestriel APA – {tri}{suffix} TR {year} – {name}")
    body_tpl = _env("MAIL_BODY",  "Bonjour,\n\nVeuillez trouver ci-joint le rapport trimestriel APA pour {name} ({tri}{suffix} TR {year}).\n\nCordialement.")
    if not (sender and pwd and to):
        raise RuntimeError("Variables manquantes: email, email_pwd, emailrec")
    return sender, pwd, to, subj_tpl, body_tpl

def get_signature_txt() -> str:
    name = _env("NameSender")
    role = _env("Role")
    return (f"{name}\n{role}".strip() if role else name).strip()

def current_trimester(today: Optional[date] = None) -> tuple[int, int, str]:
    d = today or date.today()
    m, y = d.month, d.year
    if 1 <= m <= 3:  tri, yr = 4, y - 1
    elif 4 <= m <= 6: tri, yr = 1, y
    elif 7 <= m <= 9: tri, yr = 2, y
    else:             tri, yr = 3, y
    suffix = "er" if tri == 1 else "eme"
    return tri, yr, suffix

def _list_proteges(root: str) -> List[str]:
    try:
        return [os.path.join(root, n) for n in os.listdir(root) if os.path.isdir(os.path.join(root, n))]
    except FileNotFoundError:
        return []

def _list_files(dir_path: str) -> List[str]:
    return [os.path.join(dir_path, n) for n in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, n))]

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
    env_host = os.getenv("SMTP_HOST"); env_port = os.getenv("SMTP_PORT")
    env_ssl  = os.getenv("SMTP_SSL");  env_imap = os.getenv("IMAP_HOST")
    if env_host and env_port:
        return env_host, int(env_port), (env_ssl or "1") == "1", env_imap
    domain = sender_email.split("@")[-1].lower()
    if domain == "gmail.com":
        return "smtp.gmail.com", 465, True, env_imap or "imap.gmail.com"
    if any(k in domain for k in ("outlook", "hotmail", "live", "office365")):
        return "smtp.office365.com", 587, False, env_imap or "outlook.office365.com"
    if "yahoo" in domain:
        return "smtp.mail.yahoo.com", 465, True, env_imap or "imap.mail.yahoo.com"
    if "orange.fr" in domain:
        return "smtp.orange.fr", 465, True, env_imap or "imap.orange.fr"
    return f"smtp.{domain}", 465, True, env_imap or f"imap.{domain}"

def build_message(sender: str, to: str, subject: str, body_txt: str, attachments: List[str]) -> EmailMessage:
    body_html = escape(body_txt).replace("\n", "<br>")
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"]   = to
    msg["Date"] = formatdate(localtime=True)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.set_content(body_txt)
    msg.add_alternative(body_html, subtype="html")
    for p in attachments:
        with open(p, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="octet-stream", filename=os.path.basename(p))
    return msg

def smtp_send_message(msg, smtp_host, smtp_port, use_ssl, user, pwd, request_dsn: bool) -> None:
    mail_opts = []
    if use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=60) as s:
            s.ehlo(); s.login(user, pwd)
            feats = getattr(s, "esmtp_features", {}) or {}
            rcpt_opts = ["NOTIFY=SUCCESS,FAILURE,DELAY"] if (request_dsn and "dsn" in feats) else None
            try:
                s.send_message(msg, mail_options=mail_opts, rcpt_options=rcpt_opts)
            except smtplib.SMTPRecipientsRefused as e:
                bad = next(iter(e.recipients.values()))
                if b"NOTIFY=" in bad[1] or "NOTIFY=" in str(bad[1]):
                    s.send_message(msg, mail_options=mail_opts)  # retry sans DSN
                else:
                    raise
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as s:
            s.ehlo(); s.starttls(); s.ehlo(); s.login(user, pwd)
            feats = getattr(s, "esmtp_features", {}) or {}
            rcpt_opts = ["NOTIFY=SUCCESS,FAILURE,DELAY"] if (request_dsn and "dsn" in feats) else None
            try:
                s.send_message(msg, mail_options=mail_opts, rcpt_options=rcpt_opts)
            except smtplib.SMTPRecipientsRefused as e:
                bad = next(iter(e.recipients.values()))
                if b"NOTIFY=" in bad[1] or "NOTIFY=" in str(bad[1]):
                    s.send_message(msg, mail_options=mail_opts)
                else:
                    raise

def imap_append_sent(imap_host: str, user: str, pwd: str, raw_msg: bytes) -> Optional[str]:
    try:
        imap = imaplib.IMAP4_SSL(imap_host)
        imap.login(user, pwd)
        date_str = imaplib.Time2Internaldate(time.time())
        typ, _ = imap.append(IMAP_SENT_FOLDER, '', date_str, raw_msg)
        imap.logout()
        return None if typ == "OK" else f"IMAP APPEND non OK: {typ}"
    except Exception as e:
        return str(e)

# ---------- Envoi 1 protégé avec fallback zip ----------
async def _send_one(
    sem: asyncio.Semaphore,
    protege_name: str,
    sender: str,
    pwd: str,
    recipient: str,
    subj_tpl: str,
    body_tpl: str,
    tri: int,
    yr: int,
    suffix: str,
    files: List[str],
    log_dir: str,
    move_after_ok: bool = True,
) -> bool:
    async with sem:
        smtp_host, smtp_port, use_ssl, imap_host = get_smtp_config(sender)
        sig_txt = get_signature_txt()
        ctx = {"name": protege_name, "tri": tri, "year": yr, "suffix": suffix, "date": datetime.now().strftime("%d/%m/%Y")}
        subject = subj_tpl.format_map(ctx)
        body_txt = (body_tpl.format_map(ctx).rstrip() + ("\n\n" + sig_txt if sig_txt else "")).strip()

        # Log info pré-envoi
        info_mb = attachments_size_mb(files) * B64_OVERHEAD
        log_message(log_dir, f"{protege_name}: tentative as-is, taille SMTP≈{info_mb:.2f}MB (seuil info {DEFAULT_MAX_MB}MB)")

        # Tentative 1: as-is
        try:
            msg = build_message(sender, recipient, subject, body_txt, files)
            mid = msg["Message-ID"]
            smtp_send_message(msg, smtp_host, smtp_port, use_ssl, sender, pwd, REQUEST_DSN)
            log_message(log_dir, f"OK(as-is) {protege_name} MID={mid} SMTP={smtp_host}:{smtp_port} size≈{info_mb:.2f}MB")
            if COPY_TO_SENT and imap_host:
                err = imap_append_sent(imap_host, sender, pwd, msg.as_bytes())
                if err: log_message(log_dir, f"IMAP APPEND échec {protege_name} MID={mid}: {err}")
                else:   log_message(log_dir, f"IMAP APPEND OK {protege_name} MID={mid}")
            if move_after_ok:
                _archive_and_clear_files(log_dir, protege_name, files)
            return True
        except smtplib.SMTPResponseException as e:
            code = getattr(e, "smtp_code", None)
            err  = getattr(e, "smtp_error", b"").decode(errors="ignore")
            log_message(log_dir, f"First attempt FAIL {protege_name} code={code} err={err}")
        except Exception as e:
            log_message(log_dir, f"First attempt FAIL {protege_name} err={e}")

        # Tentative 2: ZIP fallback
        tmpdir = None
        try:
            zipped, tmpdir = zip_attachments(protege_name, files)
            est_zip_mb = attachments_size_mb(zipped) * B64_OVERHEAD
            msg2 = build_message(sender, recipient, f"{subject} (ZIP)", body_txt, zipped)
            mid2 = msg2["Message-ID"]
            smtp_send_message(msg2, smtp_host, smtp_port, use_ssl, sender, pwd, REQUEST_DSN)
            log_message(log_dir, f"OK(fallback-zip) {protege_name} MID={mid2} SMTP={smtp_host}:{smtp_port} size≈{est_zip_mb:.2f}MB")
            if COPY_TO_SENT and imap_host:
                err2 = imap_append_sent(imap_host, sender, pwd, msg2.as_bytes())
                if err2: log_message(log_dir, f"IMAP APPEND échec {protege_name} MID={mid2}: {err2}")
                else:    log_message(log_dir, f"IMAP APPEND OK {protege_name} MID={mid2}")
            if move_after_ok:
                _archive_and_clear_files(log_dir, protege_name, files)
            return True
        except Exception as e:
            log_message(log_dir, f"Fallback zip FAIL {protege_name}: {e}")
            return False
        finally:
            if tmpdir: shutil.rmtree(tmpdir, ignore_errors=True)

def _archive_and_clear_files(run_dir: str, protege_name: str, files: List[str]) -> None:
    dest_dir = os.path.join(run_dir, "sent", protege_name)
    os.makedirs(dest_dir, exist_ok=True)
    for p in files:
        try:
            shutil.move(p, os.path.join(dest_dir, os.path.basename(p)))
        except Exception:
            # si move impossible (autres processus), on copie puis supprime
            try:
                shutil.copy2(p, dest_dir)
                os.remove(p)
            except Exception:
                pass

# ---------- Orchestrateur ----------
async def effectuer_rapport_APA_async_limited(status_callback=print) -> None:
    sender, pwd, recipient, subj_tpl, body_tpl = get_env()
    run_dir = init_log_session()
    tri, yr, suffix = current_trimester()

    status_callback("Préparation des envois…")
    proteges = _list_proteges(PROTEGES_DIR)
    if not proteges:
        status_callback("Aucun dossier dans 'Protégés'."); return

    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = []
    for p in sorted(proteges):
        protege_name = os.path.basename(p)
        files = _list_files(p)
        if not files:
            log_message(run_dir, f"No attachment found for {protege_name}, skipped."); continue
        tasks.append(
            _send_one(
                sem=sem,
                protege_name=protege_name,
                sender=sender,
                pwd=pwd,
                recipient=recipient,
                subj_tpl=subj_tpl,
                body_tpl=body_tpl,
                tri=tri, yr=yr, suffix=suffix,
                files=files,
                log_dir=run_dir,
                move_after_ok=True,
            )
        )

    results = await asyncio.gather(*tasks)
    success = sum(1 for r in results if r)
    fail    = len(results) - success
    status_callback(f"Envoi terminé: {success} succès, {fail} échecs.")
    log_message(run_dir, f"Résumé: {success} succès, {fail} échecs.")

if __name__ == "__main__":
    asyncio.run(effectuer_rapport_APA_async_limited())
