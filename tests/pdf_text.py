"""Extraction du texte d'un PDF avec pypdf (présent dans requirements, fonctionne sous Windows)."""
from pypdf import PdfReader


def pdf_text(path) -> str:
    return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)


def page_count(path) -> int:
    return len(PdfReader(str(path)).pages)


def page_texts(path) -> list:
    return [(p.extract_text() or "") for p in PdfReader(str(path)).pages]


def lowest_y_ratio(path, words) -> float:
    """Position verticale (0 = bas, 1 = haut) la plus basse d'un des mots sur la dernière page."""
    page = PdfReader(str(path)).pages[-1]
    height = float(page.mediabox.height)
    found = []

    def visitor(text, cm, tm, font_dict, font_size):
        if any(w.lower() in text.lower() for w in words):
            found.append((tm[5] * cm[3] + cm[5]) if cm else tm[5])

    page.extract_text(visitor_text=visitor)
    return min(found) / height if found else 1.0


def content_size(path) -> int:
    """Taille du contenu dessiné de la première page (plus de lignes = plus grand)."""
    page = PdfReader(str(path)).pages[0]
    return len(page.get_contents().get_data())
