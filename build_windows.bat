@echo off
REM ===================================================================
REM  Script de génération du bundle Windows (onedir)
REM  Prérequis : Python 3 installé et dans le PATH.
REM ===================================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo [1/5] Preparation de l'environnement virtuel...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import pip" 1>nul 2>nul
    if errorlevel 1 (
        echo Venv corrompu detecte — recreation...
        rmdir /s /q .venv
    )
)
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 (
        echo ERREUR : impossible de creer .venv
        pause
        exit /b 1
    )
)

echo [2/5] Installation des dependances...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 (
    echo ERREUR : pip casse dans le venv. Suppression et nouvel essai...
    call deactivate 2>nul
    rmdir /s /q .venv
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m ensurepip --upgrade
    python -m pip install --upgrade pip
    if errorlevel 1 (
        echo ERREUR : pip toujours inutilisable. Reinstallez Python 3.
        pause
        exit /b 1
    )
)
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERREUR : echec pip install -r requirements.txt
    pause
    exit /b 1
)
python -c "import PyInstaller; import PySide6; print('deps OK', PyInstaller.__version__)"
if errorlevel 1 (
    echo ERREUR : PyInstaller / PySide6 absents apres install.
    pause
    exit /b 1
)

echo [3/5] Generation du bundle avec PyInstaller...
python -m PyInstaller gestion_app.spec --noconfirm
if errorlevel 1 (
    echo ERREUR : PyInstaller a echoue.
    pause
    exit /b 1
)

echo [4/5] Verification du bundle (modules + plugins Qt)...
python scripts\verify_exe_modules.py dist\GestionCommerciale
if errorlevel 1 (
    echo ERREUR : bundle incomplet. Ne pas distribuer ce dossier.
    pause
    exit /b 1
)

echo [5/5] Termine.
echo Le bundle se trouve dans : dist\GestionCommerciale\
echo Lancez GestionCommerciale.exe depuis CE dossier entier ^(_internal obligatoire^).
echo En cas de fermeture immediate : GestionCommerciale_console.exe ou
echo %%APPDATA%%\GestionCommerciale\startup_error.log
pause
endlocal
