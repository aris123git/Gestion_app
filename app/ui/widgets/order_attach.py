"""Commande en PDF pour WhatsApp : le PDF est copié, il suffit de le coller (Ctrl+V) dans la conversation."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication

from app.i18n import t
from app.ui.widgets.helpers import info


def send_with_pdf(parent, rows, supplier_name: str, whatsapp_url: str) -> None:
    """rows : (produit, unité, stock, quantité) déjà formatés. Ouvre WhatsApp, PDF copié dans le presse-papiers."""
    from app.printers.order_list import build_order_list

    path = Path(tempfile.gettempdir()) / "commande.pdf"
    build_order_list(rows, path, supplier=supplier_name)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    QGuiApplication.clipboard().setMimeData(mime)
    QDesktopServices.openUrl(QUrl(whatsapp_url))
    info(parent, t("Le PDF de la commande est copié.\n\nDans WhatsApp, collez-le dans la conversation (Ctrl+V), puis envoyez."))
