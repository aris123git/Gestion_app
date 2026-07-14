"""Ressources et configuration de l'application.

Ce paquet ré-exporte la configuration centrale (chemins, constantes métier)
pour respecter l'arborescence demandée ``app/resources/``.
"""

from app import config

__all__ = ["config"]
