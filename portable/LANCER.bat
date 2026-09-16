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
    echo  Windows peut alors demander d'ajouter un disque / des fichiers
    echo  manquants — c'est parce que le pack est INCOMPLET.
    echo.
    echo  Causes frequentes :
    echo   - Vous avez ouvert le ZIP et lance l'exe SANS « Extraire tout »
    echo   - Vous avez copie seulement GestionCommerciale.exe
    echo   - La copie USB s'est arretee avant la fin
    echo.
    echo  Sur un PC etranger : preferez GestionCommerciale_Setup.exe
    echo  ^(un seul fichier, pas d'extraction^).
    echo.
    echo  Sinon : Extraire tout le ZIP, puis verifier que _internal
    echo  est present a cote de LANCER.bat et de l'exe.
    echo.
    pause
    exit /b 1
)

REM Dossier _internal present mais quasi vide = copie tronquee / ZIP ouvert
dir /a-d /b "%~dp0_internal\" 2>nul | findstr /r "." >nul
if errorlevel 1 (
    echo ERREUR : le dossier _internal est vide. Recopiez / re-extrayez le pack.
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
