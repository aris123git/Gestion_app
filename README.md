# Gestion Commerciale (POS) — V1

Logiciel professionnel de **gestion commerciale / point de vente (POS)** pour
petits et moyens commerces, fonctionnant **100 % hors ligne** sur Windows
(également exécutable sous Linux/macOS pour le développement).

Le type de commerce (boutique, poissonnerie, pharmacie, quincaillerie,
boucherie, boulangerie, supérette, magasin d'électronique, etc.) ne change pas
le logiciel : seuls changent les **produits**, **catégories** et **unités**.

---

## Fonctionnalités

- **Premier démarrage** : assistant de configuration du commerce (nom, logo optionnel,
  adresse, téléphone, devise, type de commerce), modifiable ensuite.
- **Tableau de bord** : CA encaissé du jour / du mois, nombre de ventes, produits les
  plus vendus, stock faible, ruptures, dépenses du jour, bénéfice estimé.
- **Produits** : nom, catégorie, code-barres, référence, prix d'achat / vente /
  minimum, quantité, stock minimum, unité, activation/désactivation. Les produits
  déjà vendus sont désactivés plutôt que supprimés afin de préserver l'historique.
- **Catégories & Unités** : création, modification, suppression, recherche
  (unités par défaut : kg, g, carton, pièce, boîte, sac, litre, bidon +
  unités personnalisées).
- **Stock** : entrées, sorties, inventaire, correction, historique, alertes de
  rupture. Les achats fournisseur peuvent être annulés avec reprise du stock et
  annulation de la dette liée lorsque cela reste cohérent.
- **Fournisseurs** et **Clients** : dettes, règlements, historique et points de fidélité.
- **Caisse (POS)** : interface rapide, ajout/modification/suppression d'articles,
  modification du prix directement dans le panier (avec choix « uniquement cette
  vente » ou « mise à jour définitive du prix »).
- **Paiement** : espèces, Orange Money, Moov Money, carte bancaire, virement,
  **paiement mixte** et ventes à crédit client pour les rôles autorisés. Le
  caissier peut encaisser, appliquer une remise, vendre à crédit, consulter le
  stock et régler les dettes client selon la matrice de permissions. Calcul
  automatique de la **monnaie rendue** et message « Montant insuffisant » le cas échéant.
- **Annulations / retours** : l'application gère aujourd'hui l'annulation complète
  d'une vente depuis l'historique, avec restockage si possible. Les retours
  partiels ligne par ligne ne sont pas encore modélisés.
- **Ticket thermique** 58 mm / 80 mm (nom, logo si configuré, adresse, numéro, date, heure,
  caissier, produits, totaux, monnaie, mode de paiement, message de
  remerciement), archivage texte sans écrasement et **réimpression depuis
  l'historique des ventes**.
- **Dépenses** : loyer, salaire, transport, électricité, internet, autres.
- **Rapports** : journalier, hebdomadaire, mensuel, annuel, avec **CA encaissé**,
  ventes à crédit, dépenses, trésorerie, ventilation par mode de paiement,
  **Z de caisse journalier** — export **PDF**, **Excel** et texte pour le Z.
- **Utilisateurs** : administrateur / gestionnaire / caissier, permissions, connexion
  sécurisée (mots de passe hachés PBKDF2).
- **Sauvegarde** : automatique, manuelle, restauration.
- **Paramètres** : identité du commerce, devise, apparence, format du ticket,
  imprimante, options de sauvegarde. Un taux de TVA peut être renseigné pour les
  besoins de configuration, sans automatiser toute la fiscalité.
- **Recherche instantanée** sur produits, clients, fournisseurs, ventes.
- **Interface moderne** : navigation latérale, grandes cartes, compatible écran
  tactile, **mode clair / sombre**.
- **Sécurité** : journal d'audit des actions importantes, suppression de vente
  réservée à l'administrateur. L'activation est liée à la machine ; le fichier
  `activation.dat` peut être inclus dans les sauvegardes pour une restauration
  cohérente sur le même poste.

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

> Note multi-session : l'application est conçue pour un usage local hors ligne
> sur un poste principal. Plusieurs fenêtres ou postes pointant simultanément
> vers la même base SQLite ne constituent pas encore un mode supporté.

---

## Licence

Logiciel propriétaire destiné à la commercialisation. Tous droits réservés.
