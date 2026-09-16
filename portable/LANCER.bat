@echo off
REM Lance NexaGes / Gestion Commerciale depuis CE dossier (cle USB ou PC).
setlocal
cd /d "%~dp0"

if not exist "%~dp0_internal\" (
    echo.
    echo ============================================================
    echo  ERREUR : dossier _internal introuvable a cote de ce fichier.
    echo ============================================================
    echo.
    echo  Sur la cle USB, il faut copier TOUT le dossier
    echo  GestionCommerciale , pas seulement GestionCommerciale.exe
    echo.
    echo  Contenu attendu :
    echo    GestionCommerciale\
    echo      LANCER.bat
    echo      GestionCommerciale.exe
    echo      _internal\          ^<-- OBLIGATOIRE
    echo      LIRE_MOI_CLE_USB.txt
    echo.
    echo  Astuce : copiez le fichier ZIP puis extrayez-le sur la cle,
    echo  ou glissez le dossier entier GestionCommerciale sur la cle.
    echo.
    pause
    exit /b 1
)

if not exist "%~dp0GestionCommerciale.exe" (
    echo ERREUR : GestionCommerciale.exe manquant dans ce dossier.
    pause
    exit /b 1
)

start "" "%~dp0GestionCommerciale.exe"
endlocal
