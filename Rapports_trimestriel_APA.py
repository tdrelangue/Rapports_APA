# Rapports_trimestriel_APA.py

import os
import asyncio
import tempfile
import shutil
from typing import List, Optional
from datetime import datetime, date

from config import Config
from dotenv import load_dotenv
from send_email import send_email  # version modernisée qu'on vient de corriger


# ---------- Utilitaires ----------
def log_message(log_dir: str, txt: str) -> None:
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, "log.txt")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {txt}\n")
    print(txt)


def init_log_session(base_log_dir: str) -> str:
    run_dir = os.path.join(base_log_dir, datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


# def _env(key: str, default: str = "") -> str:
#     v = os.getenv(key)
#     return default if v is None else v.replace("\\n", "\n")


# def get_env() -> None:
#     """
#     Valide les variables d'environnement nécessaires.
#     Ne retourne rien, mais lève une erreur si une variable clé manque.
#     """
#     load_dotenv(override=True)
#     sender = _env("email")
#     pwd    = _env("email_pwd")
#     to     = _env("emailrec")

#     # Les templates APA sont utilisés par compose_email via send_email,
#     # donc on se contente de vérifier qu'ils existent ou qu'ils ont un défaut.
#     _ = _env("MAIL_SUBJECT", "Rapport trimestriel APA – {tri}{suffix} TR {year} – {name}")
#     _ = _env(
#         "MAIL_BODY",
#         "Bonjour,\n\nVeuillez trouver ci-joint le rapport trimestriel APA pour "
#         "{name} ({tri}{suffix} TR {year}).\n\nCordialement."
#     )

#     if not (sender and pwd and to):
#         raise RuntimeError("Variables manquantes: email, email_pwd, emailrec")


# def get_signature_txt(config: Config) -> str:
#     name = config.identity.name_sender
#     role = config.identity.role,
#     return (f"{name}\n{role}".strip() if role else name).strip()


def current_trimester(today: Optional[date] = None) -> tuple[int, int, str]:
    d = today or date.today()
    m, y = d.month, d.year
    if 1 <= m <= 3:
        tri, yr = 4, y - 1
    elif 4 <= m <= 6:
        tri, yr = 1, y
    elif 7 <= m <= 9:
        tri, yr = 2, y
    else:
        tri, yr = 3, y
    suffix = "er" if tri == 1 else "eme"
    return tri, yr, suffix


def _list_proteges(root: str) -> List[str]:
    try:
        return [
            os.path.join(root, n)
            for n in os.listdir(root)
            if os.path.isdir(os.path.join(root, n))
        ]
    except FileNotFoundError:
        return []


def _list_files(dir_path: str) -> List[str]:
    return [
        os.path.join(dir_path, n)
        for n in os.listdir(dir_path)
        if os.path.isfile(os.path.join(dir_path, n))
    ]


def attachments_size_mb(paths: List[str]) -> float:
    return sum(os.path.getsize(p) for p in paths if os.path.isfile(p)) / (1024 * 1024)


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


# ---------- Envoi 1 protégé via send_email ----------
async def _send_one(
    sem: asyncio.Semaphore,
    protege_name: str,
    tri: int,
    yr: int,
    suffix: str,
    files: List[str],
    log_dir: str,
    config: Config,
    move_after_ok: bool = True,
) -> bool:
    async with sem:
        # Contexte pour send_email (identique à ce qu'on a fait pour ASH)
        ctx = {
            "name": protege_name,
            "tri": tri,
            "year": yr,
            "suffix": suffix,
            "date": datetime.now().strftime("%d/%m/%Y"),
            "sender_name": config.identity.name_sender,
            "sender_role": config.identity.role,
            "attachments": files,
        }

        info_mb = attachments_size_mb(files) * config.smtp.b64_overhead
        log_message(
            log_dir,
            f"{protege_name}: tentative via send_email (APA), "
            f"taille SMTP≈{info_mb:.2f}MB (seuil info {config.smtp.max_mb}MB)"
        )

        try:
            # send_email est synchrone → on le pousse dans un thread
            success = await asyncio.to_thread(send_email, config, ctx, False)

            if success:
                log_message(log_dir, f"OK {protege_name} via send_email (APA)")
                if move_after_ok:
                    _archive_and_clear_files(log_dir, protege_name, files)
                return True
            else:
                log_message(log_dir, f"FAIL SMTP {protege_name} via send_email (APA, accepted=False)")
                return False

        except Exception as e:
            log_message(log_dir, f"FAIL {protege_name} via send_email (APA): {e}")
            return False


# ---------- Orchestrateur ----------
async def effectuer_rapport_async_limited(config: Config | None = None, status_callback=print) -> None:
    if config is None:
        config = Config.load(".env")

        # On force test mode (mais uniquement pour cette exécution !)
        config.paths.test_mode = True 

    run_dir = init_log_session(config.paths.log_dir)
    tri, yr, suffix = current_trimester()

    # TEST_MODE : 0 = prod (on déplace les fichiers), 1 = test (on laisse les fichiers en place)
    move_after_ok = (config.paths.test_mode == 0)

    status_callback("Préparation des envois…")
    proteges = _list_proteges(config.paths.proteges_dir)
    if not proteges:
        status_callback("Aucun dossier dans 'Protégés'.")
        return

    CONCURRENCY = max(1, config.smtp.concurrency)
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = []
    for p in sorted(proteges):
        protege_name = os.path.basename(p)
        files = _list_files(p)
        if not files:
            log_message(run_dir, f"No attachment found for {protege_name}, skipped.")
            continue

        tasks.append(
            _send_one(
                sem=sem,
                protege_name=protege_name,
                tri=tri,
                yr=yr,
                suffix=suffix,
                files=files,
                log_dir=run_dir,
                move_after_ok=move_after_ok,
                config=config,
            )
        )

    results = await asyncio.gather(*tasks)
    success = sum(1 for r in results if r)
    fail = len(results) - success
    status_callback(f"Envoi terminé: {success} succès, {fail} échecs.")
    log_message(run_dir, f"Résumé: {success} succès, {fail} échecs.")


if __name__ == "__main__":
    config = Config.load(".env",mode="APA")
    asyncio.run(effectuer_rapport_async_limited(config=config))

