"""Thèmes clair et sombre de l'application (feuilles de style Qt).

L'interface s'inspire des logiciels de caisse professionnels : navigation
latérale, grandes cartes, coins arrondis, couleur d'accent bleue et bonne
lisibilité tactile.
"""

from __future__ import annotations

from typing import Optional

PRIMARY = "#2563eb"
PRIMARY_DARK = "#1d4ed8"
SUCCESS = "#16a34a"
DANGER = "#dc2626"
WARNING = "#f59e0b"

LIGHT = {
    "bg": "#f1f5f9",
    "surface": "#ffffff",
    "surface_alt": "#f8fafc",
    "text": "#0f172a",
    "muted": "#64748b",
    "border": "#e2e8f0",
    "sidebar": "#0f172a",
    "sidebar_text": "#cbd5e1",
    "sidebar_active": PRIMARY,
    "input": "#ffffff",
}

DARK = {
    "bg": "#0b1220",
    "surface": "#111827",
    "surface_alt": "#1f2937",
    "text": "#f1f5f9",
    "muted": "#94a3b8",
    "border": "#1f2937",
    "sidebar": "#020617",
    "sidebar_text": "#cbd5e1",
    "sidebar_active": PRIMARY,
    "input": "#1f2937",
}


def _clamp(value: float, min_v: float, max_v: float) -> float:
    return max(min_v, min(max_v, value))


def responsive_root_font_size(window_width: int, base: int = 14, min_pt: int = 12, max_pt: int = 18) -> int:
    """Retourne une taille de police racine (px) adaptée à la largeur fournie."""
    if window_width <= 0:
        return base
    scale = _clamp(window_width / 1200.0, 0.8, 1.5)
    size = int(round(base * scale))
    return max(min_pt, min(max_pt, size))


def build_stylesheet(dark: bool = False, root_font_size: int = 14) -> str:
    """Construit la QSS complète pour le thème demandé.

    root_font_size est la taille de police racine (en px) utilisée pour les
    éléments globaux. Cela permet d'ajuster la lisibilité selon la taille de la
    fenêtre sans toucher aux couleurs ou au branding.
    """
    c = DARK if dark else LIGHT
    return f"""
    QWidget {{
        background-color: {c['bg']};
        color: {c['text']};
        font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif;
        font-size: {root_font_size}px;
    }}
    QLabel {{ background: transparent; }}

    /* Barre latérale */
    #Sidebar {{ background-color: {c['sidebar']}; }}
    #Sidebar QLabel {{ color: {c['sidebar_text']}; }}
    #SidebarTitle {{
        color: #ffffff; font-size: {max(16, root_font_size+4)}px; font-weight: 700; padding: 4px;
    }}
    #SidebarSubtitle {{ color: {c['muted']}; font-size: {max(10, root_font_size-2)}px; }}
    QPushButton#NavButton {{
        color: {c['sidebar_text']};
        background: transparent;
        border: none;
        text-align: left;
        padding: 12px 16px;
        border-radius: 10px;
        font-size: {max(12, root_font_size)}px;
    }}
    QPushButton#NavButton:hover {{ background-color: rgba(255,255,255,0.08); }}
    QPushButton#NavButton:checked {{
        background-color: {c['sidebar_active']};
        color: #ffffff;
        font-weight: 600;
    }}

    /* Cartes */
    #Card, QFrame#Card {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 14px;
    }}
    #StatCard {{ border-radius: 14px; }}
    #StatValue {{ font-size: {max(18, int(root_font_size*1.8))}px; font-weight: 700; }}
    #StatTitle {{ font-size: {max(11, int(root_font_size*0.9))}px; }}
    #PageTitle {{ font-size: {max(18, int(root_font_size*1.6))}px; font-weight: 700; }}
    #SectionTitle {{ font-size: {max(12, int(root_font_size*1.2))}px; font-weight: 600; }}

    /* Champs de saisie */
    QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
        background-color: {c['input']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 8px 10px;
        selection-background-color: {PRIMARY};
        font-size: {max(12, root_font_size)}px;
    }}
    QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus,
    QDateEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border: 1px solid {PRIMARY};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        border: none;
        width: 24px;
    }}
    QComboBox::down-arrow {{
        width: 0;
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 6px solid {c['muted']};
        margin-right: 8px;
    }}

    /* Boutons */
    QPushButton {{
        background-color: {c['surface_alt']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 9px 16px;
        font-weight: 600;
        font-size: {max(12, root_font_size)}px;
    }}
    QPushButton:hover {{ border-color: {PRIMARY}; }}
    QPushButton#Primary {{
        background-color: {PRIMARY}; color: #ffffff; border: none;
    }}
    QPushButton#Primary:hover {{ background-color: {PRIMARY_DARK}; }}
    QPushButton#Success {{ background-color: {SUCCESS}; color: #ffffff; border: none; }}
    QPushButton#Danger {{ background-color: {DANGER}; color: #ffffff; border: none; }}
    QPushButton:disabled {{ color: {c['muted']}; }}

    /* Tables */
    QTableWidget, QTableView {{
        background-color: {c['surface']};
        border: 1px solid {c['border']};
        border-radius: 10px;
        gridline-color: {c['border']};
        selection-background-color: {PRIMARY};
        selection-color: #ffffff;
        font-size: {max(11, int(root_font_size*0.95))}px;
    }}
    QHeaderView::section {{
        background-color: {c['surface_alt']};
        color: {c['muted']};
        padding: 8px;
        border: none;
        border-bottom: 1px solid {c['border']};
        font-weight: 600;
    }}
    QTableWidget::item {{ padding: 6px; }}

    /* Onglets */
    QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 10px; }}
    QTabBar::tab {{
        background: {c['surface_alt']};
        padding: 9px 16px;
        border-top-left-radius: 8px;
        border-top-right-radius: 8px;
        margin-right: 2px;
        font-size: {max(12, root_font_size)}px;
    }}
    QTabBar::tab:selected {{ background: {PRIMARY}; color: #ffffff; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


def apply_theme(app, dark: bool = False, root_font_size: int = 14) -> None:
    """Applique le thème à l'application Qt (avec une taille de police racine)."""
    app.setStyleSheet(build_stylesheet(dark, root_font_size))


def apply_responsive_theme(app, window, dark: bool = False) -> None:
    """Calcule une taille de police racine à partir de la largeur de la fenêtre
    et applique le thème responsive.

    window peut être une QMainWindow/QWidget — nous lisons sa largeur actuelle.
    """
    try:
        width = window.width()
    except Exception:
        width = 1200
    root_size = responsive_root_font_size(width)
    apply_theme(app, dark=dark, root_font_size=root_size)
