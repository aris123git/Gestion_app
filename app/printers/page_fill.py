"""Option « remplir la page » : le bloc final (totaux, signature, cachet) est poussé tout en bas de la page,
quel que soit le contenu du dessus."""
from __future__ import annotations

from io import BytesIO

from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable

SETTING_INVOICE = "invoice_pin_bottom"
SETTING_BON = "bon_pin_bottom"
SETTING_BL = "bl_pin_bottom"


class PushToBottom(Flowable):
    """Espace invisible qui occupe toute la hauteur restante moins celle du bloc qui le suit."""

    def __init__(self, block: Flowable, minimum: float = 0.0):
        super().__init__()
        self.block, self.minimum = block, minimum

    def _natural_height(self, avail_w) -> float:
        canv = getattr(self, "canv", None) or Canvas(BytesIO())
        content = getattr(self.block, "_content", None)       # KeepTogether annonce une hauteur géante : on mesure son contenu
        parts = content if content is not None else [self.block]
        total = 0.0
        for part in parts:
            part.canv = canv
            _, h = part.wrap(avail_w, 10 ** 6)
            total += h + getattr(part, "getSpaceBefore", lambda: 0)() + getattr(part, "getSpaceAfter", lambda: 0)()
        return total

    def wrap(self, avail_w, avail_h):
        return avail_w, max(self.minimum, avail_h - self._natural_height(avail_w) - 3)

    def draw(self):  # rien à dessiner
        pass
