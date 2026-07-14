# Gestion Commerciale (POS) — V1

Logiciel professionnel de **gestion commerciale / point de vente (POS)** pour
petits et moyens commerces, fonctionnant **100 % hors ligne** sur Windows
(également exécutable sous Linux/macOS pour le développement).

Le type de commerce (boutique, poissonnerie, pharmacie, quincaillerie,
boucherie, boulangerie, supérette, magasin d'électronique, etc.) ne change pas
le logiciel : seuls changent les **produits**, **catégories** et **unités**.

---

## Fonctionnalités

- **Premier démarrage** : assistant de configuration du commerce (nom, logo,
  adresse, téléphone, devise, type de commerce), modifiable ensuite.
- **Tableau de bord** : CA du jour / du mois, nombre de ventes, produits les
  plus vendus, stock faible, ruptures, dépenses du jour, bénéfice estimé.
- **Produits** : nom, catégorie, code-barres, référence, prix d'achat / vente /
  minimum, quantité, stock minimum, unité.
- **Catégories & Unités** : création, modification, suppression, recherche
  (unités par défaut : kg, g, carton, pièce, boîte, sac, litre, bidon +
  unités personnalisées).
- **Stock** : entrées, sorties, inventaire, correction, historique, alertes de
  rupture.
- **Fournisseurs** et **Clients** (avec gestion des dettes).
- **Caisse (POS)** : interface rapide, ajout/modification/suppression d'articles,
  modification du prix directement dans le panier (avec choix « uniquement cette
  vente » ou « mise à jour définitive du prix »).
- **Paiement** : espèces, Orange Money, Moov Money, carte bancaire, virement, et
  **paiement mixte**. Calcul automatique de la **monnaie rendue** et message
  « Montant insuffisant » le cas échéant.
- **Ticket thermique** 58 mm / 80 mm (nom, logo, adresse, numéro, date, heure,
  caissier, produits, totaux, monnaie, mode de paiement, message de
  remerciement) + **réimpression**.
- **Dépenses** : loyer, salaire, transport, électricité, internet, autres.
- **Rapports** : journalier, hebdomadaire, mensuel, annuel — export **PDF** et
  **Excel**.
- **Utilisateurs** : administrateur / caissier, permissions, connexion
  sécurisée (mots de passe hachés PBKDF2).
- **Sauvegarde** : automatique, manuelle, restauration.
- **Paramètres** : logo, nom, adresse, téléphone, TVA, devise, format du ticket,
  imprimante.
- **Recherche instantanée** sur produits, clients, fournisseurs, ventes.
- **Interface moderne** : navigation latérale, grandes cartes, compatible écran
  tactile, **mode clair / sombre**.
- **Sécurité** : journal d'audit des actions importantes, suppression de vente
  réservée à l'administrateur.

---

## Technologies

- Python 3
- PySide6 (Qt)
- SQLite + SQLAlchemy
- python-escpos (impression thermique)
- ReportLab (PDF)
- openpyxl (Excel)
- PyInstaller (génération du `.exe`)

---

## Architecture du projet

```
app/
├── database/     # Connexion SQLite, session, initialisation, données par défaut
├── models/       # Modèles ORM (produits, ventes, stock, clients, etc.)
├── controllers/  # Logique métier (CRUD, ventes, stock, rapports, tableau de bord)
├── services/     # Authentification, audit, sauvegarde, paramètres
├── ui/           # Interface PySide6 (thème, fenêtres, pages, dialogues, widgets)
├── reports/      # Génération PDF / Excel
├── printers/     # Ticket thermique ESC/POS (58 mm / 80 mm)
├── resources/    # Ressources / configuration
├── utils/        # Utilitaires (formatage, sécurité)
└── assets/       # Icônes et images
```

---

## Installation (développement)

Prérequis : **Python 3.10+**.

```bash
# 1. Créer et activer un environnement virtuel
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Lancer l'application
python -m app.main
```

Au premier lancement, l'assistant de configuration s'ouvre, puis l'écran de
connexion. **Compte par défaut : `admin` / `admin`** (à modifier depuis la page
Utilisateurs / Paramètres).

### Exécution sans écran (serveur / CI)

L'application est graphique. Pour un test automatisé sur une machine sans
écran, utilisez un serveur X virtuel :

```bash
xvfb-run -a python -m app.main
```

---

## Génération de l'exécutable Windows (.exe)

```bat
build_windows.bat
```

ou manuellement :

```bash
pyinstaller gestion_app.spec --noconfirm
```

L'exécutable est généré dans `dist/GestionCommerciale.exe`.

## Génération de l'installateur Windows

1. Générer d'abord l'exécutable (voir ci-dessus).
2. Installer [Inno Setup](https://jrsoftware.org/isinfo.php).
3. Compiler `installer.iss` avec Inno Setup pour obtenir
   `GestionCommerciale_Setup.exe`.

---

## Stockage des données

Les données (base SQLite, sauvegardes, tickets, exports, logos) sont stockées
dans le dossier de données de l'utilisateur :

- **Windows** : `%APPDATA%\GestionCommerciale`
- **Linux** : `~/.local/share/GestionCommerciale`
- **macOS** : `~/Library/Application Support/GestionCommerciale`

Vous pouvez surcharger cet emplacement via la variable d'environnement
`GESTION_DATA_DIR` (utile pour les tests).

---

## Licence

Logiciel propriétaire destiné à la commercialisation. Tous droits réservés.
