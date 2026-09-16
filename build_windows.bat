@echo off
REM ===================================================================
REM  Build Windows — un seul fichier GestionCommerciale.exe (onefile)
REM  Prérequis : Python 3 installé et dans le PATH.
REM ===================================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo [1/4] Preparation de l'environnement virtuel...
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

echo [2/4] Installation des dependances...
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

echo [3/4] Generation de l'EXE unique (onefile)...
python -m PyInstaller gestion_app.spec --noconfirm
if errorlevel 1 (
    echo ERREUR : PyInstaller a echoue.
    pause
    exit /b 1
)

echo [4/4] Verification de l'EXE...
python scripts\verify_exe_modules.py dist\GestionCommerciale.exe
if errorlevel 1 (
    echo ERREUR : EXE incomplet. Ne pas distribuer.
    pause
    exit /b 1
)

echo.
echo === TERMINE ===
echo Copiez UN SEUL fichier sur la cle / le PC :
echo   dist\GestionCommerciale.exe
echo.
echo Diagnostic (si fermeture immediate) :
echo   dist\GestionCommerciale_console.exe
echo   ou %%APPDATA%%\GestionCommerciale\startup_error.log
echo.
echo Astuce antivirus : ajoutez une exclusion sur le dossier / l'exe.
pause
endlocal
