@echo off
REM ===================================================================
REM  Build Windows onedir + Setup.exe (1 fichier a distribuer)
REM  onefile est abandonne : antivirus → ModuleNotFoundError main_window
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

echo [3/5] Generation du bundle onedir (PyInstaller)...
python -m PyInstaller gestion_app.spec --noconfirm
if errorlevel 1 (
    echo ERREUR : PyInstaller a echoue.
    pause
    exit /b 1
)

echo [4/5] Verification du bundle...
python scripts\verify_exe_modules.py dist\GestionCommerciale
if errorlevel 1 (
    echo ERREUR : bundle incomplet. Ne pas distribuer.
    pause
    exit /b 1
)

echo [4b/5] LANCER.bat + ZIP...
copy /Y "portable\LANCER.bat" "dist\GestionCommerciale\LANCER.bat" >nul
copy /Y "portable\LIRE_MOI_CLE_USB.txt" "dist\GestionCommerciale\LIRE_MOI_CLE_USB.txt" >nul
if exist "dist\GestionCommerciale_portable.zip" del /f /q "dist\GestionCommerciale_portable.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\GestionCommerciale' -DestinationPath 'dist\GestionCommerciale_portable.zip' -Force"

echo [4c/5] Setup.exe (si Inno Setup installe)...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%ISCC%" (
    "%ISCC%" installer.iss
    if not errorlevel 1 echo Setup.exe : Output\GestionCommerciale_Setup.exe
) else (
    echo Inno Setup absent — CI produit l'artefact GestionCommerciale-Setup.
)

echo [5/5] Termine.
echo.
echo === UN SEUL FICHIER A COPIER (RECOMMANDE) ===
echo   Output\GestionCommerciale_Setup.exe
echo   Sur le PC : double-clic → Installer → lancer.
echo.
echo Ne PAS utiliser un EXE onefile : Windows Defender casse
echo souvent l'extraction et affiche « main_window introuvable ».
echo.
pause
endlocal
