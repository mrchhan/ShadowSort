; Inno Setup script - ShadowSort by Shadow Creative Studio  (https://jrsoftware.org/isinfo.php)
#define AppName "ShadowSort"
#ifndef AppVersion
  #define AppVersion "1.5.0"
#endif
#define AppPublisher "Shadow Creative Studio"

[Setup]
AppId={{6C1E4A57-3F8B-4C8E-9A51-5D2B7F0A9E31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=installer
OutputBaseFilename=ShadowSort-Setup-{#AppVersion}
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\ShadowSort.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "dist\ShadowSort\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\ShadowSort.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\ShadowSort.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ShadowSort.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
