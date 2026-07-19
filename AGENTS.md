# AGENTS.md

Application de bureau **Gestion Commerciale (POS)** — Python 3 + PySide6 (Qt),
SQLite/SQLAlchemy, ReportLab (PDF), openpyxl (Excel), python-escpos (tickets),
PyInstaller (packaging Windows).

Architecture et commandes standard : voir `README.md`. Point d'entrée :
`python -m app.main` (compte par défaut `admin` / `admin`). Le code métier est
séparé de l'UI : `models/` (ORM) → `controllers/` (logique) → `ui/` (PySide6).

## Cursor Cloud specific instructions

- **Application graphique (Qt).** Il n'y a pas de serveur web : l'app s'exécute
  dans une fenêtre. Pour la lancer/tester dans le VM cloud, utiliser l'affichage
  VNC déjà présent (`DISPLAY=:1`) **et** définir `XAUTHORITY=/home/ubuntu/.Xauthority`,
  sinon le plugin Qt `xcb` échoue avec « Could not load the Qt platform plugin xcb »
  (l'erreur ne mentionne pas l'authority manquant). Exemple :
  `DISPLAY=:1 XAUTHORITY=/home/ubuntu/.Xauthority python -m app.main`.
  Pour un test purement sans écran (import/logique), utiliser
  `QT_QPA_PLATFORM=offscreen`.
- **Données isolées pour les tests.** L'app stocke sa base SQLite dans le dossier
  de données de l'utilisateur. Définir `GESTION_DATA_DIR=/tmp/qqchose` pour partir
  d'un état vierge (déclenche l'assistant de premier démarrage) sans toucher aux
  données réelles.
- **Dépendances système Qt** (déjà installées par l'update script au niveau apt,
  hors dépôt) : les bibliothèques `libxcb-*`, `libxkbcommon-x11-0`, `libegl1`,
  `libgl1` sont nécessaires au rendu `xcb`. Si le rendu échoue après un nouveau
  pod, réinstaller ces paquets via apt.
- **Le venv est à `.venv/`** ; l'activer avant toute commande Python
  (`source .venv/bin/activate`).
- **Packaging Windows** (`pyinstaller gestion_app.spec`, `installer.iss`) est
  prévu pour être exécuté **sous Windows**, pas dans le VM Linux.
- Pas de suite de tests automatisés pour l'instant ; la validation se fait en
  lançant l'app et en déroulant un flux caisse (créer un produit, encaisser une
  vente, vérifier le tableau de bord).
- **Activation au premier démarrage** : l'app exige un code d'activation maître
  (voir `app/services/activation_service.py`, constante `MASTER_KEY`, surchargée
  par la variable d'env `NEXAPOS_ACTIVATION_KEY`). Un fichier `activation.dat`
  est écrit dans `DATA_DIR` après activation. Pour les tests automatisés /
  headless, définir `NEXAPOS_SKIP_ACTIVATION=1` pour contourner l'écran
  d'activation.
