"""Seuils de largeur / hauteur pour le moteur responsive.

Calibré pour les PC de caisse réels (1366×768, 1280×720, 1024×768)
et les grands écrans 22″ / plein écran.
"""

from __future__ import annotations

# Largeur fenêtre (px).
# ≤799  → mobile (drawer)
# ≤1439 → compact (icônes)  — inclut 1024, 1280, 1366
# ≤1679 → desktop
# ≥1680 → large
WIDTH_MOBILE = 800
WIDTH_COMPACT = 1440
WIDTH_DESKTOP = 1680

# Hauteur fenêtre (px).
# 768 de hauteur → short (densité cozy), pas comfortable.
HEIGHT_VERY_SHORT = 560
HEIGHT_SHORT = 800
HEIGHT_TALL = 960

# Modes de barre latérale.
SIDEBAR_FULL = "full"
SIDEBAR_ICONS = "icons"
SIDEBAR_DRAWER = "drawer"

SIDEBAR_WIDTH_FULL = 220
SIDEBAR_WIDTH_ICONS = 64

# Densité visuelle (padding / polices).
DENSITY_COMFORTABLE = "comfortable"
DENSITY_COZY = "cozy"
DENSITY_COMPACT = "compact"

# Empiler catalogue / panier de caisse sous ce content_width.
# 1100 : empile aussi sur ~1180 utiles (laptop 1280 avec icônes).
STACK_PANELS_CONTENT_WIDTH = 1100
