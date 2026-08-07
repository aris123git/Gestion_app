# Gestion Commerciale (POS)

A professional point-of-sale / business management desktop application for small and medium shops (boutiques, pharmacies, bakeries, superettes, etc.), designed to run **100% offline**.

## Stack

- **Language**: Python 3.12
- **GUI**: PySide6 (Qt)
- **Database**: SQLite via SQLAlchemy
- **Reports**: ReportLab, openpyxl
- **Printing**: python-escpos

## Project structure

```
app/
  main.py          # Entry point
  config.py        # App configuration
  database/        # DB init & models
  models/          # SQLAlchemy models
  controllers/     # Business logic
  ui/              # Qt UI components
  services/        # Service layer
  reports/         # Report generation
  printers/        # Receipt printing
  utils/           # Utilities
  resources/       # Assets (icons, etc.)
tests/             # Test suite
run.py             # Convenience launcher
```

## Running the app

On Linux (Replit), a virtual display is required because this is a Qt GUI app:

```bash
xvfb-run -a python -m app.main
```

Or simply:

```bash
xvfb-run -a python run.py
```

## Data storage

- **Linux**: `~/.local/share/GestionCommerciale`
- **Windows**: `%APPDATA%\GestionCommerciale`
- Override with `GESTION_DATA_DIR` environment variable (useful for tests)

## Building a Windows executable

```bat
build_windows.bat
```

or manually:

```bash
pyinstaller gestion_app.spec --noconfirm
```

## User preferences
