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


SETTING_FILL_BON = "bon_fill_empty"
SETTING_FILL_BL = "bl_fill_empty"


def _height(flowable, canv, width) -> float:
    flowable.canv = canv
    content = getattr(flowable, "_content", None)       # KeepTogether annonce une hauteur géante : on mesure son contenu
    parts = content if content is not None else [flowable]
    total = 0.0
    for part in parts:
        part.canv = canv
        _, h = part.wrap(width, 10 ** 6)
        total += h + getattr(part, "getSpaceBefore", lambda: 0)() + getattr(part, "getSpaceAfter", lambda: 0)()
    return total


def free_space(story: list, frame_w: float, frame_h: float, before: list | None = None) -> tuple[float, float]:
    """Pour une histoire [tableau, espaces…, bloc final] : (hauteur libre sur la page, hauteur d'une ligne du tableau)."""
    canv = Canvas(BytesIO())
    table, block = story[0], story[-1]
    used = sum(_height(f, canv, frame_w) for f in (before or [])) + _height(table, canv, frame_w) + sum(_height(f, canv, frame_w) for f in story[1:-1]) + _height(block, canv, frame_w)
    heights = getattr(table, "_rowHeights", None) or [0]
    return frame_h - used - 4, (heights[-1] if len(heights) > 1 else 0) or 1


def fit_blank_rows(make_story, frame_w: float, frame_h: float, before: list | None = None) -> int:
    """Nombre de lignes vides qui complètent le tableau jusqu'au bas de la page (0 si le contenu remplit déjà la page)."""
    free, row_h = free_space(make_story(0), frame_w, frame_h, before)
    n = max(0, int(free // row_h))
    while n > 0:
        free_after, _ = free_space(make_story(n), frame_w, frame_h, before)
        if free_after >= 0 and len(make_story(n)) == len(make_story(0)):
            break
        n -= 1
    return n
