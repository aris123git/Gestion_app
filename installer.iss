; ===================================================================
;  Script Inno Setup pour créer l'installateur Windows.
;  Prérequis :
;    1. Générer l'EXE : build_windows.bat → dist\GestionCommerciale.exe
;    2. Installer Inno Setup (https://jrsoftware.org/isinfo.php)
;    3. Compiler ce fichier avec Inno Setup.
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
OutputDir=Output
OutputBaseFilename=GestionCommerciale_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer une icône sur le bureau"; GroupDescription: "Icônes supplémentaires:"

[Files]
; EXE onefile unique (+ variante console pour diagnostic).
Source: "dist\GestionCommerciale.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\GestionCommerciale_console.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer {#MyAppName}"; Flags: nowait postinstall skipifsilent
