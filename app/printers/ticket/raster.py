"""Tickets « image » (designs futuristes) pour imprimante thermique ESC/POS.

Une imprimante thermique en mode texte ne sait ni arrondir un coin, ni tracer
un trait continu entre deux lignes. On dessine donc le ticket en image
(Pillow) puis on l'envoie en raster (GS v 0) : les traits sont des pixels,
sans interligne, donc parfaitement continus.

Trois styles : ``neo`` (coins biseautés), ``arrondi`` (formes rondes),
``tech`` (traits fins, équerres). Module autonome (Pillow uniquement).
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

from PIL import Image, ImageDraw, ImageFont

BLACK, WHITE = 0, 255
STYLES = ("neo", "arrondi", "tech")

_BOLD = ("segoeuib.ttf", "arialbd.ttf", "calibrib.ttf", "DejaVuSans-Bold.ttf")
_REG = ("segoeui.ttf", "arial.ttf", "calibri.ttf", "DejaVuSans.ttf")


def _font(names: Iterable[str], size: int):
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _money(value: float, currency: str = "") -> str:
    text = f"{int(round(float(value or 0))):,}".replace(",", " ")
    return f"{text} {currency}".strip()


def _qty(value: float) -> str:
    v = float(value or 0)
    return str(int(v)) if abs(v - round(v)) < 1e-6 else f"{v:g}"


class _Canvas:
    def __init__(self, width: int, style: str, margin: int = 14):
        self.w, self.m, self.style = width, margin, style
        self.img = Image.new("L", (width, 6000), WHITE)
        self.d = ImageDraw.Draw(self.img)
        self.y = margin + 6

    @property
    def x0(self) -> int:
        return self.m + 8

    @property
    def x1(self) -> int:
        return self.w - self.m - 8

    def tw(self, text: str, font) -> int:
        return int(self.d.textlength(text, font=font))

    def center(self, text: str, font, gap: int = 4) -> None:
        self.d.text(((self.w - self.tw(text, font)) // 2, self.y), text, font=font, fill=BLACK)
        self.y += font.size + gap

    def lr(self, left: str, right: str, font, gap: int = 6, fill=BLACK) -> None:
        self.d.text((self.x0 + 6, self.y), left, font=font, fill=fill)
        self.d.text((self.x1 - 6 - self.tw(right, font), self.y), right, font=font, fill=fill)
        self.y += font.size + gap

    def wrap(self, text: str, font, max_w: int) -> list[str]:
        lines, cur = [], ""
        for word in (text or "").split():
            trial = f"{cur} {word}".strip()
            if self.tw(trial, font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines or [""]

    # --- formes -------------------------------------------------------
    def shape(self, box, *, fill=None, outline=BLACK, width: int = 3, d=None) -> None:
        """Rectangle selon le style : biseauté (neo), arrondi, ou droit (tech)."""
        d = d or self.d
        x0, y0, x1, y1 = box
        if self.style == "arrondi":
            d.rounded_rectangle(box, radius=min(22, (y1 - y0) // 2), fill=fill, outline=outline, width=width)
            return
        cut = 14 if self.style == "neo" else 6
        pts = [(x0 + cut, y0), (x1 - cut, y0), (x1, y0 + cut), (x1, y1 - cut),
               (x1 - cut, y1), (x0 + cut, y1), (x0, y1 - cut), (x0, y0 + cut)]
        if fill is not None:
            d.polygon(pts, fill=fill)
        if outline is not None:
            d.line(pts + [pts[0]], fill=outline, width=width, joint="curve")

    def deco(self) -> None:
        """Bandeau décoratif selon le style."""
        y, h = self.y + 6, 12
        if self.style == "neo":
            pts, x = [], self.x0
            while x <= self.x1:
                pts += [(x, y + h), (x + h // 2, y), (x + h, y + h)]
                x += h
            self.d.line(pts, fill=BLACK, width=3)
        elif self.style == "arrondi":
            x = self.x0 + 6
            while x < self.x1 - 4:
                self.d.ellipse([x, y + 2, x + 8, y + 10], fill=BLACK)
                x += 18
        else:  # tech : trait épais + trait fin + repères
            self.d.rectangle([self.x0, y, self.x1, y + 3], fill=BLACK)
            self.d.rectangle([self.x0, y + 8, self.x1, y + 8], fill=BLACK)
            for x in range(self.x0, self.x1, 36):
                self.d.rectangle([x, y + 4, x + 3, y + 12], fill=BLACK)
        self.y = y + h + 10

    def pill(self, text: str, font, dark: bool = False) -> None:
        w, h = self.tw(text, font) + 36, font.size + 16
        x0 = (self.w - w) // 2
        box = (x0, self.y, x0 + w, self.y + h)
        if self.style == "arrondi":
            self.d.rounded_rectangle(box, radius=h // 2, fill=BLACK if dark else WHITE, outline=BLACK, width=3)
        else:
            self.shape(box, fill=BLACK if dark else WHITE)
        self.d.text((x0 + 18, self.y + 7), text, font=font, fill=WHITE if dark else BLACK)
        self.y += h + 8

    def outer_frame(self, img: Image.Image, h: int) -> None:
        d, w = ImageDraw.Draw(img), self.w
        if self.style == "neo":
            self.shape((3, 3, w - 4, h - 4), outline=BLACK, width=4, d=d)
            self.shape((12, 12, w - 13, h - 13), outline=BLACK, width=1, d=d)
        elif self.style == "arrondi":
            d.rounded_rectangle((3, 3, w - 4, h - 4), radius=30, outline=BLACK, width=4)
        else:  # tech : équerres aux quatre coins + filet fin
            d.rectangle((8, 8, w - 9, h - 9), outline=BLACK, width=1)
            L, t = 34, 5
            for (cx, cy, sx, sy) in ((3, 3, 1, 1), (w - 4, 3, -1, 1), (3, h - 4, 1, -1), (w - 4, h - 4, -1, -1)):
                d.rectangle([min(cx, cx + sx * L), min(cy, cy + sy * t), max(cx, cx + sx * L), max(cy, cy + sy * t)], fill=BLACK)
                d.rectangle([min(cx, cx + sx * t), min(cy, cy + sy * L), max(cx, cx + sx * t), max(cy, cy + sy * L)], fill=BLACK)


def render_ticket_image(data, paper: str = "80mm", style: str = "neo",
                        logo: Optional[Image.Image] = None) -> Image.Image:
    """Dessine le ticket (TicketData) → image 1 bit prête à imprimer."""
    style = style if style in STYLES else "neo"
    width = 384 if "58" in str(paper) else 576
    narrow = width <= 384
    c = _Canvas(width, style)
    f_title = _font(_BOLD, 28 if narrow else 40)
    f_h = _font(_BOLD, 15 if narrow else 20)
    f_b = _font(_BOLD, 17 if narrow else 21)
    f_r = _font(_REG, 17 if narrow else 20)
    f_s = _font(_REG, 14 if narrow else 17)
    f_big = _font(_BOLD, 32 if narrow else 46)
    f_tot = _font(_BOLD, 20 if narrow else 24)

    # --- en-tête -------------------------------------------------------
    if logo is not None:
        ratio = min(1.0, (width * 0.45) / logo.width)
        lg = logo.convert("L").resize((max(1, int(logo.width * ratio)), max(1, int(logo.height * ratio))))
        c.img.paste(lg, ((width - lg.width) // 2, c.y))
        c.y += lg.height + 8
    c.center((data.shop_name or "COMMERCE").upper(), f_title, gap=6)
    for line in (data.shop_address, data.shop_phone and f"Tél : {data.shop_phone}", data.shop_email):
        if line:
            c.center(str(line), f_s, gap=2)
    c.y += 4
    c.deco()

    moment = data.moment if isinstance(data.moment, datetime) else datetime.now()
    c.pill(f"N° {data.ticket_number}", f_b, dark=(style != "tech"))
    c.center(moment.strftime("%d/%m/%Y   %H:%M"), f_r, gap=2)
    if data.cashier_name:
        c.center(f"Caissier : {data.cashier_name}", f_s, gap=2)
    if data.client_name:
        c.center(f"Client : {data.client_name}", f_s, gap=2)
    c.y += 8

    # --- tableau : PRODUIT | QTÉ | P.U. | MONTANT -------------------------
    qw, pw, mw = (46, 80, 94) if narrow else (62, 112, 134)
    xq = c.x1 - mw - pw - qw          # début colonne QTÉ
    xp = c.x1 - mw - pw               # début colonne P.U.
    xm = c.x1 - mw                    # début colonne MONTANT
    top = c.y
    head_h = f_h.size + 22
    dark_head = style != "tech"
    if dark_head:
        c.shape((c.x0, top, c.x1, top + head_h), fill=BLACK, outline=None)
    col = WHITE if dark_head else BLACK
    ty = top + 10
    c.d.text((c.x0 + 8, ty), "PRODUIT", font=f_h, fill=col)
    for label, x0_, x1_ in (("QTÉ", xq, xp), ("P.U.", xp, xm), ("MONTANT", xm, c.x1)):
        c.d.text((x1_ - 8 - c.tw(label, f_h), ty), label, font=f_h, fill=col)
    c.y = top + head_h
    body_top = c.y
    last = len(data.items) - 1
    for idx, it in enumerate(data.items):
        row_top, y = c.y, c.y + 8
        lines = c.wrap(str(it.name), f_b, xq - c.x0 - 16)
        for ln in lines:
            c.d.text((c.x0 + 8, y), ln, font=f_b, fill=BLACK)
            y += f_b.size + 2
        for text, x1_ in ((_qty(it.quantity), xp), (_money(it.unit_price), xm), (_money(it.line_total), c.x1)):
            fnt = f_b if x1_ == c.x1 else f_r
            c.d.text((x1_ - 8 - c.tw(text, fnt), row_top + 8), text, font=fnt, fill=BLACK)
        c.y = y + 8
        if idx != last:                                          # filet continu
            c.d.rectangle([c.x0, c.y, c.x1, c.y + 1], fill=BLACK)
            c.y += 2
    body_bot = c.y
    c.shape((c.x0, top, c.x1, body_bot), outline=BLACK, width=3)
    for x in (xq, xp, xm):                                    # séparateurs continus
        c.d.rectangle([x, top if not dark_head else body_top, x + 1, body_bot - 1], fill=BLACK)
    c.y += 12

    # --- totaux ----------------------------------------------------------
    cur = data.currency or ""
    if data.has_discount:
        c.lr("Sous-total", _money(data.subtotal), f_r)
        c.lr("Remise", "-" + _money(abs(data.discount)), f_r)
    if data.has_vat:
        c.lr("Total HT", _money(data.total_ht), f_s, gap=4)
        c.lr(f"TVA {data.vat_rate:g}%", _money(data.vat_amount), f_s, gap=4)
    c.y += 6
    box_h = f_big.size + f_tot.size + 30
    fill_total = BLACK if style != "tech" else None
    box = (c.x0, c.y, c.x1, c.y + box_h)
    c.shape(box, fill=fill_total, outline=BLACK, width=4)
    if style == "tech":
        c.shape((c.x0 + 6, c.y + 6, c.x1 - 6, c.y + box_h - 6), outline=BLACK, width=1)
    ink = WHITE if fill_total is not None else BLACK
    c.d.text((c.x0 + 18, c.y + 9), "TOTAL À PAYER", font=f_tot, fill=ink)
    amt = _money(data.total, cur)
    c.d.text((c.x1 - 18 - c.tw(amt, f_big), c.y + 9 + f_tot.size + 4), amt, font=f_big, fill=ink)
    c.y += box_h + 12

    for p in data.payments:
        c.lr(str(p.method), _money(p.amount, cur), f_r)
    if float(data.change_due or 0) > 0.01:
        c.y += 2
        c.pill(f"Monnaie rendue : {_money(data.change_due, cur)}", f_b)

    c.y += 4
    c.deco()
    for ln in c.wrap(data.footer or "Merci de votre visite", f_b, width - 60):
        c.center(ln, f_b, gap=2)
    c.y += 20

    h = c.y + c.m
    img = c.img.crop((0, 0, width, h))
    c.outer_frame(img, h)
    return img.point(lambda p: 0 if p < 140 else 255, mode="1")


def image_to_escpos(img: Image.Image, *, feed_lines: int = 4, cut: bool = True, strip: int = 128) -> bytes:
    """Image → commandes ESC/POS raster (GS v 0), envoyées par bandes."""
    bw = img.convert("1")
    if bw.width % 8:
        padded = Image.new("1", (bw.width + 8 - bw.width % 8, bw.height), 1)
        padded.paste(bw, (0, 0))
        bw = padded
    out = bytearray(b"\x1b\x40")
    bpr = bw.width // 8
    for top in range(0, bw.height, strip):
        part = bw.crop((0, top, bw.width, min(top + strip, bw.height)))
        raw = part.point(lambda p: 255 - p).convert("1").tobytes()
        out += b"\x1d\x76\x30\x00" + bytes([bpr & 0xFF, bpr >> 8, part.height & 0xFF, part.height >> 8]) + raw
    out += b"\x1b\x64" + bytes([max(0, min(int(feed_lines), 255))])
    if cut:
        out += b"\x1d\x56\x00"
    return bytes(out)
