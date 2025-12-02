import imaplib
from imap_tools.mailbox import MailBox
import os
import time
from difflib import SequenceMatcher
from Email import *

from dotenv import load_dotenv

# -----------------------------------------------------------
# UTILITAIRES
# -----------------------------------------------------------

def imap_login(server: str, username: str, password: str):
    """Connexion IMAP standard (IMAP4_SSL)."""
    imap = imaplib.IMAP4_SSL(server)
    imap.login(username, password)
    return imap


def imap_list_folders(server: str, username: str, password: str):
    """Retourne une liste propre des dossiers IMAP."""
    imap = imap_login(server, username, password)

    typ, data = imap.list()
    folders = []
    if typ == "OK":
        for d in data:
            try:
                parts = d.decode().split(' "/" ')
                if len(parts) == 2:
                    folders.append(parts[1].strip('"'))
            except:
                pass

    imap.logout()
    return folders


# -----------------------------------------------------------
# RECHERCHE DE DOSSIERS
# -----------------------------------------------------------

def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def find_closest_folder(target: str, folders: list[str]):
    """Retourne (best_folder, score)."""
    scores = [(f, similarity(f, target)) for f in folders]
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[0] if scores else (None, 0)


def find_best_folder(target_name: str, MAIL_PASSWORD: str, MAIL_USERNAME: str, IMAP_SERVER: str):
    """
    Return the folder name on the server that is closest to `target_name`
    based on string similarity.
    """
    best_folder = None
    best_score = 0.0
    target = target_name.lower()

    with Mailbox(IMAP_SERVER).login(MAIL_USERNAME, MAIL_PASSWORD) as mb:  # no need to specify "Inbox" here
        for folder in mb.folder.list():
            folder_name = folder.name
            score = SequenceMatcher(None, target, folder_name.lower()).ratio()

            if score > best_score:
                best_score = score
                best_folder = folder_name
    best_folder = "" if best_folder is None else best_folder
    return best_folder, best_score

def find_sent_folder(server: str, username: str, password: str):
    """
    Trouve le dossier 'Envoyés' / 'Sent' / 'Outbox' le plus probable.
    Retourne : (folder, score, alias_used)
    """
    candidates = [
        "Sent", "Envoyés", "Envoyes", "Envoye", "Envoyer",
        "Outbox", "Sent Items", "Boîte d'envoi", "Envoyé"
    ]

    folders = imap_list_folders(server, username, password)

    # recherche directe d'après alias
    for c in candidates:
        if c in folders:
            return c, 1.0, c

    # sinon, score sur tous
    scored = [(fold, max(similarity(fold, c) for c in candidates)) for fold in folders]
    scored.sort(key=lambda x: x[1], reverse=True)

    best, score = scored[0]
    return best, score, best


# -----------------------------------------------------------
# AJOUT MESSAGE
# -----------------------------------------------------------

def add_email_to_box(server: str, username: str, password: str, mailbox: str, raw_msg: bytes):
    """
    Ajoute un email dans un dossier IMAP.
    mailbox doit être un string (PAS tuple).
    """
    if isinstance(mailbox, tuple):
        mailbox = mailbox[0]

    imap = imap_login(server, username, password)

    try:
        date_time = imaplib.Time2Internaldate(time.time())
        typ, data = imap.append(mailbox, "", date_time, raw_msg)

        if typ != "OK":
            return f"IMAP append failed: {typ}"

    except Exception as e:
        return str(e)

    finally:
        try:
            imap.logout()
        except:
            pass

    return None


# -----------------------------------------------------------
# ATTTENTE D’UN EMAIL PARTICULIER
# -----------------------------------------------------------

def wait_for_email(server: str, username: str, password: str, box: str,
                    subject: str, timeout=20, interval=2):
    """
    Attend qu'un email avec un sujet donné apparaisse dans un dossier IMAP.
    Retourne True si trouvé, False sinon.
    """
    end = time.time() + timeout

    while time.time() < end:
        try:
            imap = imap_login(server, username, password)
            imap.select(box, readonly=True)

            typ, data = imap.search(None, 'UNSEEN')
            if typ == "OK":
                for msgid in data[0].split():
                    typ2, msg_data = imap.fetch(msgid, '(BODY.PEEK[HEADER.FIELDS (SUBJECT)])')
                    if typ2 == "OK":
                        header = msg_data[0][1].decode(errors="ignore")
                        if subject.lower() in header.lower():
                            imap.logout()
                            return True

            imap.logout()

        except:
            pass

        time.sleep(interval)

    return False


# -----------------------------------------------------------
# TESTS : if __main__
# -----------------------------------------------------------

if __name__ == "__main__":
    load_dotenv(override=True)

    print("=== TEST AUTOMATIQUE IMAP HANDLER ===")

    # Variables d'env
    MAIL_USERNAME = os.getenv("email")
    MAIL_PASSWORD = os.getenv("email_pwd")
    MAILBOX_NAME = os.getenv("Mailbox_name", "INBOX/ASH")
    SENTBOX_NAME = os.getenv("Sentbox_name", "INBOX/OUTBOX")

    # Trouver automatiquement le serveur IMAP
    IMAP_SERVER = "imap.orange.fr"

    print(f"\nIMAP SERVER : {IMAP_SERVER}")
    print(f"USERNAME    : {MAIL_USERNAME}")

    # --- Liste des dossiers ---
    print("\n---- Dossiers IMAP ----")
    folders = imap_list_folders(IMAP_SERVER, MAIL_USERNAME, MAIL_PASSWORD)
    for f in folders:
        print(" -", f)

    # --- Recherche dossier cible ---
    target = MAILBOX_NAME

    best, score = find_closest_folder(target, folders)
    print(f"Closest folder pour '{target}' → {best} (score {score:.2f})")

    # --- Détection “envoyés” ---
    sent_detected, score, alias = find_sent_folder(IMAP_SERVER, MAIL_USERNAME, MAIL_PASSWORD)
    print(f"\nDossier Envoyés détecté → {sent_detected} (alias {alias}, score {score:.2f})")

    # --- Append email test ---
    print("\n---- Test append ----")
    dest_box = target

    test_msg = EmailMessage()
    test_msg["From"] = MAIL_USERNAME
    test_msg["To"] = MAIL_USERNAME
    test_msg["Subject"] = "TEST_IMAP_HANDLER"
    test_msg.set_content("Ceci est un test IMAP handler.")

    raw = test_msg.as_bytes()
    err = add_email_to_box(IMAP_SERVER, MAIL_USERNAME, MAIL_PASSWORD, dest_box, raw)
    print("Résultat append :", "OK" if err is None else err)

    # --- Attente email ---
    print("\n---- Test attente email ----")

    box_wait = dest_box
    subject_wait = "TEST_IMAP_HANDLER"

    found = wait_for_email(IMAP_SERVER, MAIL_USERNAME, MAIL_PASSWORD, box_wait, subject_wait)
    print("Résultat attente :", "Trouvé" if found else "Non trouvé")