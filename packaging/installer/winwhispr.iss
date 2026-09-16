; Inno Setup script for WinWhispr.
;
; Do not compile this directly -- use packaging\build.ps1 -Installer, which is
; the single entry point for building WinWhispr (venv, PyInstaller bundle, and
; this installer, in one command).
;
; Expects the PyInstaller bundle at ..\..\dist\WinWhispr\ (produced by
; packaging\winwhispr.spec, relative to this file in packaging\installer\).
;
; Per-user install, no administrator needed. The global hotkey runs in the
; installing user's session and the settings live in that user's profile, so
; there is nothing a machine-wide install would buy.

#define AppName "WinWhispr"
; Supplied by build.ps1 from the VERSION file; the fallback only matters when
; ISCC is run by hand.
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppPublisher "WinWhispr"
#define AppExeName "WinWhispr.exe"
#define AppUrl "https://github.com/Vatsa10/WindowWhispr"

[Setup]
; New GUID for WinWhispr: reusing another product's AppId would make this
; installer masquerade as an upgrade to a different application.
AppId={{7F3C9A24-51D8-4E6B-B0A7-2C94E6D31F58}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
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
UninstallDisplayName={#AppName}
ArchitecturesInstallIn64BitMode=x64compatible

; WinWhispr lives in the tray and can be running during an install or an
; upgrade, holding its own executable open. Without this the installer either
; fails on a locked file or leaves the old one behind. It also spawns a second
; copy of itself for the recognizer window, so both have to go.
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Separate tasks, because they are separate decisions. Bundling the desktop
; icon into the startup option meant you could not have one without the other.
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "startupicon"; Description: "Start {#AppName} when I sign in (it waits in the tray)"; GroupDescription: "Startup:"

[Files]
; The whole PyInstaller one-directory bundle.
Source: "..\..\dist\WinWhispr\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; The Start Menu entry is what makes the app findable by typing its name, which
; for most people is the only way they ever launch anything.
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Comment: "Hold a key and speak"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Inno removes only what it installed. The app writes into its own folder at
; runtime -- PyInstaller unpacks there, and logs and generated bindings can
; land there too -- so without this an "uninstalled" app leaves a folder full
; of files behind.
Type: filesandordirs; Name: "{app}"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';
  RunValue = 'WinWhispr';

function DataDir: String;
begin
  Result := ExpandConstant('{%USERPROFILE}') + '\.cache\winwhispr';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dir: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;

  { The app writes this itself when "Start with Windows" is switched on in
    settings, so the installer never created it and Inno will not remove it.
    Left behind, it points Windows at a deleted executable on every sign-in. }
  RegDeleteValue(HKEY_CURRENT_USER, RunKey, RunValue);

  { Settings, dictionary, history and the recognizer's browser profile. Asked
    about rather than assumed in either direction: deleting someone's
    dictionary without asking is rude, and leaving it behind after they said
    "uninstall" is untidy. Reinstalling later picks it back up. }
  Dir := DataDir;
  if DirExists(Dir) then
  begin
    if MsgBox('Also delete your WinWhispr settings, dictionary and history?'
              + #13#10 + #13#10 + Dir + #13#10 + #13#10
              + 'Choose No to keep them for a future reinstall.',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(Dir, True, True, True);
  end;
end;
