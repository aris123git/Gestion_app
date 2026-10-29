"""Plan comptable simplifié inspiré du SYSCOHADA révisé (comptes utiles à un commerce)."""

from __future__ import annotations

CHART: dict[str, str] = {
    # Classe 1 — Capitaux
    "101": "Capital social / apport de l'exploitant",
    "108": "Compte de l'exploitant (prélèvements)",
    "110": "Report à nouveau créditeur",
    "119": "Report à nouveau débiteur",
    "162": "Emprunts et dettes auprès des établissements de crédit",
    # Classe 2 — Immobilisations
    "241": "Matériel et outillage",
    "244": "Matériel et mobilier de bureau",
    "245": "Matériel de transport",
    # Classe 3 — Stocks
    "311": "Stock de marchandises",
    # Classe 4 — Tiers
    "401": "Fournisseurs",
    "411": "Clients",
    "421": "Personnel — rémunérations dues",
    "4431": "TVA facturée sur ventes",
    "4452": "TVA récupérable sur achats",
    "471": "Comptes d'attente",
    # Classe 5 — Trésorerie
    "521": "Banque",
    "571": "Caisse",
    "585": "Mobile money (monnaie électronique)",
    # Classe 6 — Charges
    "601": "Achats de marchandises (coût des ventes)",
    "605": "Autres achats (eau, électricité, fournitures)",
    "613": "Loyers et charges locatives",
    "616": "Primes d'assurance",
    "618": "Transports et déplacements",
    "624": "Entretien et réparations",
    "628": "Télécommunications (internet, téléphone)",
    "631": "Frais bancaires",
    "661": "Rémunérations du personnel",
    "658": "Charges diverses",
    "659": "Pertes sur marchandises (évaporation, écarts d'enlèvement)",
    "671": "Intérêts des emprunts",
    # Classe 7 — Produits
    "701": "Ventes de marchandises",
    "758": "Produits divers de gestion courante",
}

# Comptes de trésorerie (classe 5) utilisés pour le suivi de caisse.
CASH_ACCOUNTS = ("571", "585", "521")

# Catégorie de dépense du logiciel → compte de charge.
EXPENSE_ACCOUNTS = {
    "loyer": "613", "salaire": "661", "transport": "618", "électricité": "605", "electricite": "605",
    "eau": "605", "internet": "628", "téléphone": "628", "telephone": "628", "assurance": "616",
    "entretien": "624", "réparation": "624", "banque": "631",
}

# Écritures types proposées pour la saisie manuelle : (libellé, débit, crédit).
PRESETS = [
    ("Apport en capital en caisse", "571", "101"),
    ("Apport en capital en banque", "521", "101"),
    ("Stock initial", "311", "101"),
    ("Matériel initial (apport)", "244", "101"),
    ("Dépôt de la caisse en banque", "521", "571"),
    ("Retrait bancaire vers la caisse", "571", "521"),
    ("Prélèvement de l'exploitant", "108", "571"),
    ("Frais bancaires", "631", "521"),
    ("TVA payée à l'administration", "4431", "571"),
]


def account_label(code: str) -> str:
    return CHART.get(code, code)


def expense_account(category: str) -> str:
    low = (category or "").lower()
    for key, code in EXPENSE_ACCOUNTS.items():
        if key in low:
            return code
    return "658"


def cash_account(method: str) -> str:
    low = (method or "").lower()
    if any(k in low for k in ("money", "wave", "mobile", "momo", "mtn")):
        return "585"
    if any(k in low for k in ("carte", "virement", "chèque", "cheque", "banque")):
        return "521"
    return "571"
