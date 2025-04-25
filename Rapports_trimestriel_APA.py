from logging import raiseExceptions
import smtplib
from email.message import EmailMessage
import os
import smtplib
import argparse
from datetime import date
import os
import shutil
from datetime import datetime
from dotenv import load_dotenv
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

class NoAttachmentError(Exception):
    """Raised when no attachment is found or attachment is missing."""
    pass

class EmailSendError(Exception):
    """Raised when email fails to send."""
    pass
def lister_proteges():
    chemin_proteges = "Protégés"
    try:
        return [os.path.join(chemin_proteges, nom) for nom in os.listdir(chemin_proteges) if os.path.isdir(os.path.join(chemin_proteges, nom))]
    except FileNotFoundError:
        print("Le dossier 'Protégés' n'existe pas au chemin donné.")
        return []


def CollectEmailCreds():
    from tkinter import messagebox

    parser = argparse.ArgumentParser(description='Collects access to the email')
    parser.add_argument('-email', dest='email', default=None, type=str,
                        help='Sender email')
    parser.add_argument('-pwd', dest='password', default=None, type=str,
                        help='Sender email password')
    args, _ = parser.parse_known_args()

    if args.password:
        password = args.password
    else:
        load_dotenv()
        password = os.getenv('email_pwd')
        if not password:
            messagebox.showwarning("Information manquante", "Aucun mot de passe trouvé. Merci de le renseigner dans les paramètres.")
            password = ""

    if args.email:
        email = args.email
    else:
        load_dotenv()
        email = os.getenv('email')
        if not email:
            messagebox.showwarning("Information manquante", "Aucune adresse email trouvée. Merci de la renseigner dans les paramètres.")
            email = ""

    return email, password


def CollectReceiverEmail():
    from tkinter import messagebox
    parser = argparse.ArgumentParser(description='Collects access to the email')
    parser.add_argument('-emailrec', dest='emailrec', default=None, type=str,
                        help='Receiver email')
    args, _ = parser.parse_known_args()

    if args.emailrec:
        emailrec = args.emailrec
    else:
        load_dotenv()
        emailrec = os.getenv('emailrec')
        if not emailrec:
            messagebox.showwarning("Information manquante", "Aucune adresse email de réception trouvée. Merci de la renseigner dans les paramètres.")
            emailrec = ""

    return emailrec


def CollectWorkerInfo():
    from tkinter import messagebox
    parser = argparse.ArgumentParser(description='Collects access to the email')
    parser.add_argument('-NameSender', dest='NameSender', default=None, type=str,
                        help='Sender Name')
    parser.add_argument('-Role', dest='Role', default=None, type=str,
                        help='Sender Role')
    args, _ = parser.parse_known_args()

    if args.Role:
        Role = args.Role
    else:
        load_dotenv()
        Role = os.getenv('Role')
        if not Role:
            messagebox.showwarning("Information manquante", "Aucun rôle trouvé. Merci de le renseigner dans les paramètres.")
            Role = ""

    if args.NameSender:
        NameSender = args.NameSender
    else:
        load_dotenv()
        NameSender = os.getenv('NameSender')
        if not NameSender:
            messagebox.showwarning("Information manquante", "Aucun nom trouvé. Merci de le renseigner dans les paramètres.")
            NameSender = ""

    return NameSender, Role


def trouver_trimestre_actuel(aujourdhui=None):
    if aujourdhui is None:
        aujourdhui = date.today()
    mois = aujourdhui.month
    annee = aujourdhui.year

    if 1 <= mois <= 3:
        return (4, annee -1)
    elif 4 <= mois <= 6:
        return (1, annee)
    elif 7 <= mois <= 9:
        return (2, annee)
    else:  # 10 <= mois <= 12
        return (3, annee)


def effectuer_rapport_APA():
    trimestre= trouver_trimestre_actuel()
    # ---------- CONFIGURATION ----------
    counter ="er" if trimestre[0]==1 else "eme"
    body = f"Bonjour, \n \n Veuillez trouver ci-joint les justificatifs pour le  {trimestre[0]}{counter} TR {trimestre[1]} dans le dossier de " 
    WorkerName, WorkerRole= CollectWorkerInfo()
    signature=f"{WorkerName} \n{WorkerRole}"
    log_dir = init_log_session()

    # OVH Exchange credentials
    sender_email, sender_password = CollectEmailCreds()
    receiver_email = CollectReceiverEmail()

    # ----------- Find Proteges ---------
    proteges = lister_proteges()
    
    for protege in proteges:
        protege_name = os.path.basename(protege)
        full_body = body + f"{protege_name}.\n \n" +signature
        subject = f"Justificatifs APA {protege_name} {trimestre[0]}{counter} TR {trimestre[1]}"
        attachements = [os.path.join(protege, nom) for nom in os.listdir(protege) if os.path.isfile(os.path.join(protege, nom))]

        if not attachements:
            log_message(log_dir, f"No attachment found for {protege_name}, skipped.")
            continue

        try:
            send_email(
                sender_email=sender_email, 
                sender_password=sender_password, 
                receiver_email=receiver_email, 
                subject=subject, 
                body=full_body, 
                attachements=attachements
            )
            log_message(log_dir, f"Email sent successfully for {protege_name}")
            log_successful_protege(log_dir, protege_name, attachements)
        except NoAttachmentError:
            pass
        except EmailSendError as e:
            log_message(log_dir, f"Failed to send email for {protege_name}: {e}")


def get_smtp_config(email):
    """Return SMTP server and port based on sender's email domain."""
    domain = email.split('@')[-1].lower()
    extension = domain.split('.')[-1].lower()

    if "gmail.com" in domain:
        return ("smtp.gmail.com", 587, "starttls")
    elif "yahoo.com" in domain:
        return ("smtp.mail.yahoo.com", 587, "starttls")
    elif "outlook.com" in domain or "hotmail.com" in domain or "live.com" in domain:
        return ("smtp.office365.com", 587, "starttls")
    elif "ovh" in extension or "ovh.net" in domain :
        return ("ssl0.ovh.net", 465, "ssl")
    else:
        # Fallback to standard STARTTLS
        return ("smtp." + domain, 587, "starttls")

def send_email(sender_email, sender_password, receiver_email, subject, body, attachements: list):
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender_email
    msg['To'] = receiver_email
    msg.set_content(body)

    if not attachements:
        raise NoAttachmentError("Attachment path is invalid or file not found.")

    for attachement in attachements:
        if os.path.isfile(attachement):
            with open(attachement, 'rb') as f:
                file_data = f.read()
                file_name = os.path.basename(attachement)
                msg.add_attachment(file_data, maintype='application', subtype='octet-stream', filename=file_name)

    smtp_server, port, method = get_smtp_config(sender_email)

    try:
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

        print("Email sent successfully!")

    except Exception as e:
        raise EmailSendError(f"Failed to send email: {e}")


if __name__ == "__main__":
    effectuer_rapport_APA()