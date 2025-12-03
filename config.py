# config.py
import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv
from regex import template


def guess_imap_host(email: str) -> str:
    domain = email.split("@")[-1].lower()
    if "orange" in domain:
        return "imap.orange.fr"
    if "gmail" in domain:
        return "imap.gmail.com"
    if any(k in domain for k in ("outlook", "hotmail", "live", "office365")):
        return "outlook.office365.com"
    if "yahoo" in domain:
        return "imap.mail.yahoo.com"
    return f"imap.{domain}"


@dataclass
class SMTPConfig:
    host:          str
    port:          int
    use_ssl:       bool
    request_dsn:   bool
    max_mb:        float
    concurrency:   int
    b64_overhead:  float   # <-- nouveau
    dsn_options:   str
    mdn_requested: bool


@dataclass
class IMAPConfig:
    host: str
    mailbox_name: str
    sentbox_name: Optional[str]
    copy_sent: bool

@dataclass
class TemplateConfig:
    TEMPLATE_DIR : str
    subject_template_name: str
    body_html_template_name: str

@dataclass
class PathsConfig:
    proteges_dir: str
    log_dir: str
    test_mode: int  # 0 = normal, 1 = test (ne déplace pas les fichiers)


@dataclass
class IdentityConfig:
    email: str
    email_pwd: str
    emailrec: str
    name_sender: str
    role: str


@dataclass
class Config:
    smtp: SMTPConfig
    imap: IMAPConfig
    paths: PathsConfig
    identity: IdentityConfig
    template: TemplateConfig

    @classmethod
    def load(cls, env_path: str = ".env", mode: Optional[str] = None) -> "Config":
        load_dotenv(env_path, override=True)

        email = os.getenv("email", "")
        email_pwd = os.getenv("email_pwd", "")
        emailrec = os.getenv("emailrec", "")

        if not (email and email_pwd and emailrec):
            raise RuntimeError("Variables manquantes: email, email_pwd, emailrec")

        # ---- SMTP ----
        smtp_host = os.getenv("SMTP_HOST", "smtp.orange.fr")
        smtp_port = int(os.getenv("SMTP_PORT", "465"))
        smtp_ssl = os.getenv("SMTP_SSL", "1") == "1"
        request_dsn = os.getenv("SMTP_REQUEST_DSN", "1") == "1"
        max_mb = float(os.getenv("SMTP_MAX_MB", "19"))
        concurrency = int(os.getenv("SMTP_CONCURRENCY", "1"))
        b64_overhead = float(os.getenv("B64_OVERHEAD", "1.37"))  # <-- ici
        dsn_options = os.getenv("SMTP_DSN_OPTIONS", "NOTIFY=SUCCESS,FAILURE,DELAY")
        mdn_requested = bool(os.getenv("SMTP_REQUEST_MDN", 0))

        # ---- IMAP ----
        imap_host = os.getenv("IMAP_HOST", guess_imap_host(email))
        mailbox_name = os.getenv("Mailbox_name", "INBOX/APA")
        sentbox_name = os.getenv("Sentbox_name")
        copy_sent = os.getenv("IMAP_COPY_SENT", "0") == "1"

        # ---- chemin / logs / mode test ----
        proteges_dir = os.getenv("PROTEGES_DIR", "Protégés")
        log_dir = os.getenv("LOG_DIR", "logs")
        test_mode = int(os.getenv("TEST_MODE", "0"))

        # ---- profil (APA / ASH) → templates
        template_cfg = cls.find_templates(mode)
        

        name_sender = os.getenv("NameSender", "")
        role = os.getenv("Role", "")

        return cls(
            smtp=SMTPConfig(
                host=smtp_host,
                port=smtp_port,
                use_ssl=smtp_ssl,
                request_dsn=request_dsn,
                max_mb=max_mb,
                concurrency=concurrency,
                b64_overhead=b64_overhead,
                dsn_options=dsn_options,
                mdn_requested=mdn_requested,
            ),
            imap=IMAPConfig(
                host=imap_host,
                mailbox_name=mailbox_name,
                sentbox_name=sentbox_name,
                copy_sent=copy_sent,
            ),
            paths=PathsConfig(
                proteges_dir=proteges_dir,
                log_dir=log_dir,
                test_mode=test_mode,
            ),
            identity=IdentityConfig(
                email=email,
                email_pwd=email_pwd,
                emailrec=emailrec,
                name_sender=name_sender,
                role=role,
            ),
            template=template_cfg,
        )

    # ------------------------------------------------------
    # Sélection des templates selon le "mode"
    # ------------------------------------------------------
    @staticmethod
    def find_templates(mode: Optional[str] = None) -> TemplateConfig:
        """
        Détermine:
        - le dossier de templates
        - le fichier de sujet
        - le fichier de corps HTML

        Priorités :
        1) Variable d'env spécifique au mode (APA/ASH)
        2) Variable d'env générique TEMPLATE_DIR
        3) Valeurs par défaut: "templates", "APA_subject.txt", "APA_body.html" ou "ASH_...".
        """
        if mode:
            mode = mode.strip().upper()

        # Dossier de base générique
        base_tpl_dir = os.getenv("TEMPLATE_DIR", "templates")

        # Dossier spécifique au mode (sinon on retombe sur le générique)
        mode_tpl_dir = os.getenv(f"{mode}_TEMPLATE_DIR", base_tpl_dir)

        # Noms de fichiers par défaut en fonction du mode
        default_subject = f"{mode}_subject.txt"   # APA_subject.txt, ASH_subject.txt…
        default_body    = f"{mode}_body.html"     # APA_body.html, ASH_body.html…

        subject_template_name = os.getenv(f"{mode}_SUBJECT_TEMPLATE", default_subject)
        body_html_template_name = os.getenv(f"{mode}_BODY_TEMPLATE", default_body)

        return TemplateConfig(
            TEMPLATE_DIR=mode_tpl_dir,
            subject_template_name=subject_template_name,
            body_html_template_name=body_html_template_name,
        )