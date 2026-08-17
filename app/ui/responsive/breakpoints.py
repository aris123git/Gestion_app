"""Seuils de largeur / hauteur pour le moteur responsive."""

from __future__ import annotations

# Largeur disponible (px) — aligné sur les recommandations métier.
WIDTH_MOBILE = 700
WIDTH_COMPACT = 1000
WIDTH_DESKTOP = 1400

# Hauteur disponible (px) — un 1920×600 n'est pas un 1920×1080.
HEIGHT_VERY_SHORT = 500
HEIGHT_SHORT = 650
HEIGHT_TALL = 900

# Modes de barre latérale.
SIDEBAR_FULL = "full"
SIDEBAR_ICONS = "icons"
SIDEBAR_DRAWER = "drawer"

SIDEBAR_WIDTH_FULL = 240
SIDEBAR_WIDTH_ICONS = 72

# Densité visuelle (padding / polices).
DENSITY_COMFORTABLE = "comfortable"
DENSITY_COZY = "cozy"
DENSITY_COMPACT = "compact"
