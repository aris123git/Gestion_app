"""Thèmes clair et sombre de l'application (feuilles de style Qt).

L'interface s'inspire des logiciels de caisse professionnels : navigation
latérale, grandes cartes, coins arrondis, couleur d'accent bleue et bonne
lisibilité tactile.
"""

from __future__ import annotations

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


def build_stylesheet(dark: bool = False) -> str:
    """Construit la QSS complète pour le thème demandé."""
    c = DARK if dark else LIGHT
    return f"""
    QWidget {{
        background-color: {c['bg']};
        color: {c['text']};
        font-family: 'Segoe UI', 'Noto Sans', Arial, sans-serif;
        font-size: 14px;
    }}
    QLabel {{ background: transparent; }}

    /* Barre latérale */
    #Sidebar {{ background-color: {c['sidebar']}; }}
    #Sidebar QLabel {{ color: {c['sidebar_text']}; }}
    #SidebarTitle {{
        color: #ffffff; font-size: 18px; font-weight: 700; padding: 4px;
    }}
    #SidebarSubtitle {{ color: {c['muted']}; font-size: 12px; }}
    QPushButton#NavButton {{
        color: {c['sidebar_text']};
        background: transparent;
        border: none;
        text-align: left;
        padding: 12px 16px;
        border-radius: 10px;
        font-size: 15px;
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
    #StatValue {{ font-size: 26px; font-weight: 700; }}
    #StatTitle {{ font-size: 13px; }}
    #PageTitle {{ font-size: 24px; font-weight: 700; }}
    #SectionTitle {{ font-size: 16px; font-weight: 600; }}

    /* Champs de saisie */
    QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
        background-color: {c['input']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 8px 10px;
        selection-background-color: {PRIMARY};
    }}
    QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus,
    QDateEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
        border: 1px solid {PRIMARY};
    }}
    QComboBox::drop-down {{ border: none; width: 22px; }}

    /* Boutons */
    QPushButton {{
        background-color: {c['surface_alt']};
        color: {c['text']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 9px 16px;
        font-weight: 600;
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
    }}
    QTabBar::tab:selected {{ background: {PRIMARY}; color: #ffffff; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 5px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
    """


def apply_theme(app, dark: bool = False) -> None:
    """Applique le thème à l'application Qt."""
    app.setStyleSheet(build_stylesheet(dark))
