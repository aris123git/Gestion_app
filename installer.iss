; ===================================================================
;  Script Inno Setup pour créer l'installateur Windows.
;  Prérequis :
;    1. Générer l'exécutable : voir build_windows.bat (dist\GestionCommerciale.exe)
;    2. Installer Inno Setup (https://jrsoftware.org/isinfo.php)
;    3. Compiler ce fichier avec Inno Setup pour obtenir l'installateur.
; ===================================================================

#define MyAppName "Gestion Commerciale"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Gestion Commerciale"
#define MyAppExeName "GestionCommerciale.exe"

[Setup]
AppId={{A7F3C2E1-1D4B-4E9A-9C3D-000000000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\GestionCommerciale
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=GestionCommerciale_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le bureau"; GroupDescription: "Icônes supplémentaires:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent
