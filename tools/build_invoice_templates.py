"""Outil de développement : prépare les fonds des modèles de facture « Services » et « Médical ».

À lancer une seule fois (les résultats sont versionnés dans app/assets/) :

    pip install pymupdf fonttools
    python tools/build_invoice_templates.py --services <modele.ai> --medical <modele.ai> \
        --fonts <dossier avec Lato-*.ttf et Montserrat[wght].ttf>

Ce que fait l'outil :
- retire tous les textes d'exemple, les logos / signatures d'exemple, les lignes
  de tableau figées (le tableau est redessiné dynamiquement) ;
- conserve le dessin vectoriel d'origine (vagues, hexagones, cadres…) ;
- fabrique une 2e variante de couleur par rotation de teinte (couleurs d'origine
  conservées pour la 1re variante) ;
- écrit les PDF de fond + palette.json dans app/assets/invoice_templates/ ;
- crée des sous-ensembles « latin » des polices (Lato, Montserrat — licence OFL)
  dans app/assets/fonts/.

Aucune dépendance à pymupdf / fonttools n'existe à l'exécution de l'application.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import re
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "assets" / "invoice_templates"
FONTS_OUT = ROOT / "app" / "assets" / "fonts"


def rotate_hue(rgb: tuple[float, float, float], degrees: float) -> tuple[float, float, float]:
    r, g, b = rgb
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.03:  # blanc / gris : inchangé
        return rgb
    h = (h + degrees / 360.0) % 1.0
    return colorsys.hsv_to_rgb(h, s, v)


def hex_of(rgb) -> str:
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in rgb)


def clean_background(src: Path, remove_rects: list[tuple[float, float, float, float]],
                     cover: list[tuple[tuple[float, float, float, float], tuple[float, float, float]]] = ()) -> fitz.Document:
    """Ouvre le .ai (PDF), enlève tout le texte et les éléments d'exemple."""
    doc = fitz.open(str(src))
    page = doc[0]
    # 1) tous les textes (les dessins sont conservés)
    page.add_redact_annot(page.rect, fill=False)
    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
        text=fitz.PDF_REDACT_TEXT_REMOVE,
    )
    # 2) éléments d'exemple (logo, signature, lignes figées…) entièrement dans ces zones
    if remove_rects:
        for r in remove_rects:
            page.add_redact_annot(fitz.Rect(*r), fill=False)
        page.apply_redactions(
            images=fitz.PDF_REDACT_IMAGE_NONE,
            graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
            text=fitz.PDF_REDACT_TEXT_NONE,
        )
    # 3) éléments qui ne peuvent pas être retirés proprement : recouverts par la couleur du fond
    for rect, rgb in cover:
        page.draw_rect(fitz.Rect(*rect), color=None, fill=rgb, width=0)
    return doc


def recolor(doc: fitz.Document, degrees: float) -> None:
    """Rotation de teinte sur toutes les couleurs du fond (contenu + dégradés)."""
    if not degrees:
        return
    page = doc[0]

    def sub(match: re.Match) -> str:
        vals = tuple(float(v) for v in match.group(1).split())
        new = rotate_hue(vals, degrees)
        return "%.4f %.4f %.4f %s" % (*new, match.group(2))

    for xref in page.get_contents():
        stream = doc.xref_stream(xref).decode("latin1")
        stream = re.sub(r"([\d.]+ [\d.]+ [\d.]+)\s+(scn|SCN|rg|RG)\b", sub, stream)
        doc.update_stream(xref, stream.encode("latin1"))
    # Dégradés (fonction exponentielle : /C0 /C1)
    for xref in range(1, doc.xref_length()):
        obj = doc.xref_object(xref, compressed=False)
        if "/FunctionType 2" in obj and "/C0" in obj:
            for key in ("C0", "C1"):
                m = re.search(r"/%s\s*\[\s*([\d.\s]+)\]" % key, obj)
                if m:
                    vals = tuple(float(v) for v in m.group(1).split())
                    new = rotate_hue(vals, degrees)
                    doc.xref_set_key(xref, key, "[%.5f %.5f %.5f]" % new)


def save_light(doc: fitz.Document, dest: Path) -> None:
    page = doc[0]
    for key in ("PieceInfo", "Thumb", "LastModified"):
        try:
            doc.xref_set_key(page.xref, key, "null")
        except Exception:
            pass
    doc.set_metadata({})
    doc.save(str(dest), garbage=4, deflate=True, clean=True)


TEMPLATES = {
    # nom : (rectangles d'éléments d'exemple à retirer (x0,y0,x1,y1 en coord. page), palette de base)
    "services": {
        "remove": [
            (478, 104, 506, 128),   # icône du logo d'exemple
            (120, 575, 205, 650),   # signature manuscrite d'exemple (la ligne est conservée)
        ],
        "palette": {"ink": "#13234c", "accent": "#7fc5ff", "dark": "#13234c"},
        "variants": {"bleu": 0, "vert": -66},
    },
    "medical": {
        "remove": [
            (62, 292, 550, 542),    # bandes de tableau figées (redessinées dynamiquement)
            (255, 794, 358, 816),   # pictos réseaux sociaux d'exemple
        ],
        # croix du logo d'exemple : recouverte par la couleur du fond
        "cover": [((350, 70, 412, 134), (0.94, 0.98837, 0.99994))],
        "palette": {"ink": "#19242e", "blue": "#0054ae", "band": "#cfeaf5", "footer": "#0056a5", "item": "#4f4f4f"},
        "variants": {"bleu": 0, "vert": -62},
    },
}


def build_fonts(fonts_dir: Path) -> None:
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    FONTS_OUT.mkdir(parents=True, exist_ok=True)
    unicodes = list(range(0x20, 0x7F)) + list(range(0xA0, 0x100)) + [0x152, 0x153, 0x2013, 0x2014, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2026, 0x20AC, 0x2192]

    def subset_font(font: TTFont, dest: Path) -> None:
        opts = subset.Options()
        opts.layout_features = ["kern", "liga"]
        opts.notdef_outline = True
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=unicodes)
        sub.subset(font)
        font.save(str(dest))

    for name in ("Lato-Regular", "Lato-Bold", "Lato-Black"):
        subset_font(TTFont(str(fonts_dir / f"{name}.ttf")), FONTS_OUT / f"{name}.ttf")
    variable = fonts_dir / "Montserrat.ttf"
    for name, weight in (("Medium", 500), ("SemiBold", 600), ("Bold", 700), ("ExtraBold", 800)):
        font = TTFont(str(variable))
        static = instancer.instantiateVariableFont(font, {"wght": weight}, inplace=False)
        subset_font(static, FONTS_OUT / f"Montserrat-{name}.ttf")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--services", required=True)
    ap.add_argument("--medical", required=True)
    ap.add_argument("--fonts", required=True)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    palettes: dict[str, dict] = {}
    for name, src in (("services", args.services), ("medical", args.medical)):
        spec = TEMPLATES[name]
        for variant, degrees in spec["variants"].items():
            doc = clean_background(Path(src), spec["remove"], spec.get("cover", ()))
            recolor(doc, degrees)
            save_light(doc, OUT / f"{name}_{variant}.pdf")
            pal = {}
            for key, value in spec["palette"].items():
                rgb = tuple(int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
                pal[key] = hex_of(rotate_hue(rgb, degrees))
            palettes[f"{name}_{variant}"] = pal
            print("ok", name, variant, (OUT / f"{name}_{variant}.pdf").stat().st_size, "octets")
    (OUT / "palette.json").write_text(json.dumps(palettes, indent=2), encoding="utf-8")
    build_fonts(Path(args.fonts))
    print("polices:", sorted(p.name for p in FONTS_OUT.glob("*.ttf")))


if __name__ == "__main__":
    main()
