import asyncio
import os
from typing import List, Tuple
from email.message import EmailMessage
import smtplib
from datetime import date, datetime
import shutil
from dotenv import load_dotenv

class EmailSendError(Exception):
    pass

def get_smtp_config(email):
    domain = email.split('@')[-1].lower()
    extension = domain.split('.')[-1].lower()
    if "gmail.com" in domain:
        return ("smtp.gmail.com", 587, "starttls")
    elif "yahoo.com" in domain:
        return ("smtp.mail.yahoo.com", 587, "starttls")
    elif "outlook.com" in domain or "hotmail.com" in domain or "live.com" in domain:
        return ("smtp.office365.com", 587, "starttls")
    elif "ovh" in extension or "ovh.net" in domain:
        return ("ssl0.ovh.net", 465, "ssl")
    else:
        return ("smtp." + domain, 587, "starttls")

def init_log_session():
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_dir = os.path.join("logs", now)
    os.makedirs(log_dir, exist_ok=True)
    return log_dir

def log_message(log_dir, message):
    log_path = os.path.join(log_dir, "log.txt")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(message + "\n")

def log_successful_protege(log_dir, protege_name, attachments):
    protege_log_dir = os.path.join(log_dir, protege_name)
    os.makedirs(protege_log_dir, exist_ok=True)
    for filepath in attachments:
        filename = os.path.basename(filepath)
        new_path = os.path.join(protege_log_dir, filename)
        shutil.move(filepath, new_path)

async def async_send_email(sender_email: str, sender_password: str, receiver_email: str,
                           subject: str, body: str, attachments: List[str]) -> Tuple[bool, str]:
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg.set_content(body)

    for attachment in attachments:
        if os.path.isfile(attachment):
            with open(attachment, 'rb') as f:
                msg.add_attachment(f.read(), maintype='application', subtype='octet-stream',
                                   filename=os.path.basename(attachment))

    smtp_server, port, method = get_smtp_config(sender_email)

    try:
        def send():
            if method == "ssl":
                with smtplib.SMTP_SSL(smtp_server, port) as smtp:
                    smtp.login(sender_email, sender_password)
                    smtp.send_message(msg)
            elif method == "starttls":
                with smtplib.SMTP(smtp_server, port) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.login(sender_email, sender_password)
                    smtp.send_message(msg)
            else:
                raise EmailSendError("Unsupported SMTP method")

        await asyncio.to_thread(send)
        return True, ""
    except Exception as e:
        return False, str(e)

async def effectuer_rapport_APA_async_limited(status_callback=lambda msg: None):
    def trouver_trimestre_actuel(aujourdhui=None):
        if aujourdhui is None:
            aujourdhui = date.today()
        mois = aujourdhui.month
        annee = aujourdhui.year
        if 1 <= mois <= 3:
            return (4, annee - 1)
        elif 4 <= mois <= 6:
            return (1, annee)
        elif 7 <= mois <= 9:
            return (2, annee)
        else:
            return (3, annee)

    def lister_proteges():
        chemin_proteges = "Protégés"
        try:
            return [os.path.join(chemin_proteges, nom) for nom in os.listdir(chemin_proteges)
                    if os.path.isdir(os.path.join(chemin_proteges, nom))]
        except FileNotFoundError:
            status_callback("Le dossier 'Protégés' n'existe pas.")
            return []

    def CollectEmailCreds():
        load_dotenv()
        return os.getenv('email', ''), os.getenv('email_pwd', '')

    def CollectReceiverEmail():
        load_dotenv()
        return os.getenv('emailrec', '')

    def CollectWorkerInfo():
        load_dotenv()
        return os.getenv('NameSender', ''), os.getenv('Role', '')

    trimestre = trouver_trimestre_actuel()
    counter = "er" if trimestre[0] == 1 else "eme"
    body = f"Bonjour, \n \n Veuillez trouver ci-joint les justificatifs pour le {trimestre[0]}{counter} TR {trimestre[1]} dans le dossier de "
    WorkerName, WorkerRole = CollectWorkerInfo()
    signature = f"{WorkerName} \n{WorkerRole}"
    log_dir = init_log_session()

    sender_email, sender_password = CollectEmailCreds()
    receiver_email = CollectReceiverEmail()

    proteges = lister_proteges()
    semaphore = asyncio.Semaphore(1)

    async def wrapped_send(protege_name, attachments, subject, full_body):
        async with semaphore:
            status_callback(f"Envoi en cours pour {protege_name}...")
            success, error = await async_send_email(sender_email, sender_password, receiver_email,
                                                    subject, full_body, attachments)
            if success:
                status_callback(f"Envoi réussi pour {protege_name}")
                log_message(log_dir, f"Email sent successfully for {protege_name}")
                log_successful_protege(log_dir, protege_name, attachments)
                return True
            else:
                status_callback(f"Envoi échoué pour {protege_name} : {error}")
                log_message(log_dir, f"Failed to send email for {protege_name}: {error}")
                return False

    tasks = []
    for protege in proteges:
        protege_name = os.path.basename(protege)
        full_body = body + f"{protege_name}.\n \n" + signature
        subject = f"Justificatifs APA {protege_name} {trimestre[0]}{counter} TR {trimestre[1]}"
        attachments = [os.path.join(protege, nom) for nom in os.listdir(protege)
                       if os.path.isfile(os.path.join(protege, nom))]

        if not attachments:
            log_message(log_dir, f"No attachment found for {protege_name}, skipped.")
            continue

        tasks.append(wrapped_send(protege_name, attachments, subject, full_body))

    results = await asyncio.gather(*tasks)
    success_count = sum(results)
    failure_count = len(results) - success_count
    status_callback(f"\nEnvoi terminé: {success_count} succès, {failure_count} échecs.")

if __name__ == "__main__":
    asyncio.run(effectuer_rapport_APA_async_limited())
