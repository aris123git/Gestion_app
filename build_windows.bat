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

echo [3/4] Generation de l'executable avec PyInstaller...
pyinstaller gestion_app.spec --noconfirm

echo [4/4] Termine.
echo L'executable se trouve dans : dist\GestionCommerciale.exe
pause
