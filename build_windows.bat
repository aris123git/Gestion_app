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

echo [4b/5] Fichiers portable USB + ZIP...
copy /Y "portable\LANCER.bat" "dist\GestionCommerciale\LANCER.bat" >nul
copy /Y "portable\LIRE_MOI_CLE_USB.txt" "dist\GestionCommerciale\LIRE_MOI_CLE_USB.txt" >nul
if exist "dist\GestionCommerciale_portable.zip" del /f /q "dist\GestionCommerciale_portable.zip"
REM Le ZIP doit contenir le DOSSIER GestionCommerciale\ (pas seulement *),
REM pour qu'apres extraction on ait tout le dossier a copier sur la cle.
powershell -NoProfile -Command "Compress-Archive -Path 'dist\GestionCommerciale' -DestinationPath 'dist\GestionCommerciale_portable.zip' -Force"
if errorlevel 1 (
    echo Avertissement : ZIP non cree. Vous pouvez quand meme copier le dossier dist\GestionCommerciale\
) else (
    echo ZIP portable : dist\GestionCommerciale_portable.zip
)

echo [5/5] Termine.
echo.
echo === COPIE SUR CLE USB ===
echo 1. Preferez : copier dist\GestionCommerciale_portable.zip sur la cle puis Extraire.
echo 2. Ou copier TOUT le dossier dist\GestionCommerciale\ ^(exe + _internal^).
echo 3. Sur la cle : double-cliquer LANCER.bat ^(pas l'exe seul^).
echo.
echo Ne JAMAIS copier seulement GestionCommerciale.exe — ca ne marchera pas.
echo.
echo En cas de fermeture immediate : GestionCommerciale_console.exe ou
echo %%APPDATA%%\GestionCommerciale\startup_error.log
pause
endlocal
