; Installateur Gestion Commerciale (Inno Setup). Compilé par GitHub Actions :
;   iscc /DAppVersion=1.2.3 installer\GestionCommerciale.iss
; Installation par utilisateur (sans droits administrateur). Les données (%APPDATA%) ne sont jamais supprimées.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1C7E52-3B7A-4C1D-9A55-2E4D7B0C9A11}
AppName=Gestion Commerciale
AppVersion={#AppVersion}
AppPublisher=NexaDigit
DefaultDirName={localappdata}\Programs\GestionCommerciale
DefaultGroupName=Gestion Commerciale
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=GestionCommerciale-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Gestion Commerciale
UninstallDisplayIcon={app}\GestionCommerciale.exe
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "..\dist\GestionCommerciale.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Gestion Commerciale"; Filename: "{app}\GestionCommerciale.exe"
Name: "{autodesktop}\Gestion Commerciale"; Filename: "{app}\GestionCommerciale.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GestionCommerciale.exe"; Description: "Lancer Gestion Commerciale"; Flags: nowait postinstall skipifsilent
Filename: "{app}\GestionCommerciale.exe"; Flags: nowait; Check: WizardSilent
