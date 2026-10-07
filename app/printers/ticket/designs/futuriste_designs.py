"""Designs « Futuriste » : ticket dessiné en image (traits continus, formes).

Le texte retourné par ``render`` ne sert qu'à l'archive / l'aperçu texte ;
l'impression thermique utilise ``raster_style`` (voir thermal_printer).
"""

from __future__ import annotations

from app.printers.ticket.data import TicketData
from app.printers.ticket.designs.base import TicketDesign
from app.printers.ticket.options import TicketOptions
from app.printers.ticket.styled import StyledLine


class _FuturisteBase(TicketDesign):
    raster_style = "neo"
    preferred_feed = 3

    def render(self, data: TicketData, opts: TicketOptions, width: int) -> list[StyledLine]:
        # Repli texte : design « facture tableau (bords arrondis) ».
        from app.printers.ticket.designs.client_designs import FactureTableauArrondiDesign

        return FactureTableauArrondiDesign().render(data, opts, width)


class FuturisteNeoDesign(_FuturisteBase):
    id = "futuriste_neo"
    label = "Futuriste — Néo (coins biseautés)"
    description = "Image : cadre biseauté, bandeaux noirs, traits continus."
    raster_style = "neo"


class FuturisteArrondiDesign(_FuturisteBase):
    id = "futuriste_arrondi"
    label = "Futuriste — Arrondi"
    description = "Image : formes arrondies, pastilles, traits continus."
    raster_style = "arrondi"


class FuturisteTechDesign(_FuturisteBase):
    id = "futuriste_tech"
    label = "Futuriste — Tech (équerres)"
    description = "Image : traits fins, équerres aux coins, très net."
    raster_style = "tech"


FUTURISTE_DESIGN_CLASSES = (FuturisteNeoDesign, FuturisteArrondiDesign, FuturisteTechDesign)
