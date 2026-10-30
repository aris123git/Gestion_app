"""Extraction du texte d'un PDF avec pypdf (présent dans requirements, fonctionne sous Windows)."""
from pypdf import PdfReader


def pdf_text(path) -> str:
    return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
