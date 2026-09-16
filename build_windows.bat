@echo off
REM ===================================================================
REM  Script de génération de l'exécutable Windows (.exe)
REM  Prérequis : Python 3 installé et dans le PATH.
REM ===================================================================

echo [1/4] Creation de l'environnement virtuel...
python -m venv .venv

echo [2/4] Activation et installation des dependances...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [3/5] Generation de l'executable avec PyInstaller...
pyinstaller gestion_app.spec --noconfirm

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
