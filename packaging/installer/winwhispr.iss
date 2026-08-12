; Inno Setup script for WinWhispr.
;
; Do not compile this directly -- use packaging\build.ps1 -Installer, which is
; the single entry point for building WinWhispr (venv, PyInstaller bundle, and
; this installer, in one command).
;
; Expects the PyInstaller bundle at ..\..\dist\WinWhispr\ (produced by
; packaging\winwhispr.spec, relative to this file in packaging\installer\).
;
; Per-user install (no admin required) so the post-install model download/
; optimization writes into the installing user's ~/.cache/winwhispr, and the
; global hotkey runs in that user's session.

#define AppName "WinWhispr"
; Supplied by build.ps1 from the VERSION file; the fallback only matters when
; ISCC is run by hand.
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppPublisher "WinWhispr"
#define AppExeName "WinWhispr.exe"

[Setup]
; New GUID for WinWhispr: reusing the old product's AppId would make this
; installer masquerade as an upgrade to a different application.
AppId={{7F3C9A24-51D8-4E6B-B0A7-2C94E6D31F58}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=Output
OutputBaseFilename=WinWhispr-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\assets\winwhispr.ico
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startupicon"; Description: "Start {#AppName} automatically at login (runs in the background tray)"; GroupDescription: "Startup:"
Name: "prepareModels"; Description: "Download and optimize models now (recommended; requires internet)"; GroupDescription: "First-run setup:"

[Files]
; Copy the entire PyInstaller one-directory bundle.
Source: "..\..\dist\WinWhispr\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startupicon
; Launch at login -> the app starts minimized to the system tray (background).
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startupicon

[Run]
; Download + device-specific optimization on the target machine (user context).
Filename: "{app}\{#AppExeName}"; Parameters: "setup"; Description: "Downloading and optimizing models"; StatusMsg: "Downloading and optimizing models (this can take a while)..."; Flags: runhidden waituntilterminated; Tasks: prepareModels
; Optionally launch the app right after install.
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
