from html import unescape
import re 

def html_to_text(html: str) -> str:
    """
    Convertit un petit HTML de mail en texte lisible :
    - <br> → \n
    - </p> → \n\n
    - <li> → "- "
    - suppression des balises restantes
    - unescape des entités (&eacute; -> é)
    """

    # Normalise les retours à la ligne dans le HTML lui-même
    text = html.replace("\r", "")

    # Les blocs "visuels"
    text = re.sub(r"<\s*br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<\s*p\s*>", "", text, flags=re.I)

    # Listes
    text = re.sub(r"<\s*li\s*>", "- ", text, flags=re.I)
    text = re.sub(r"</\s*li\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*ul\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</\s*ol\s*>", "\n", text, flags=re.I)

    # On vire toutes les autres balises
    text = re.sub(r"<[^>]+>", "", text)

    # Decode &eacute;, &amp;, etc.
    text = unescape(text)

    # Nettoyage espaces & sauts de ligne
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
