; Inno Setup script: installer for PrivateDoc AI.
; Build: build_exe.bat (builds dist\PrivateDocAI first, then this installer into release\)
; Version: iscc /DAppVersion=0.2.0 installer\PrivateDocAI.iss   (default below)
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6F2D7C1E-4B8A-4E39-9C57-2A1D5E8B7F40}
AppName=PrivateDoc AI
AppVersion={#AppVersion}
AppPublisher=Signor P
DefaultDirName={autopf}\PrivateDoc AI
DefaultGroupName=PrivateDoc AI
DisableProgramGroupPage=yes
; the user chooses where to install, and whether for themselves only or for all users
DisableDirPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\release
OutputBaseFilename=PrivateDocAI-{#AppVersion}-Setup
SetupIconFile=..\assets\privatedoc.ico
UninstallDisplayIcon={app}\PrivateDocAI.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
CloseApplications=yes

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\PrivateDocAI\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\PrivateDoc AI"; Filename: "{app}\PrivateDocAI.exe"; IconFilename: "{app}\PrivateDocAI.exe"
Name: "{autodesktop}\PrivateDoc AI"; Filename: "{app}\PrivateDocAI.exe"; IconFilename: "{app}\PrivateDocAI.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PrivateDocAI.exe"; Description: "{cm:LaunchProgram,PrivateDoc AI}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\installed.flag"

[Code]
// Tells the program it was installed: working data then goes to %LOCALAPPDATA%\PrivateDocAI
// (the program folder, e.g. Program Files, is not writable by normal users).
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\installed.flag'), 'installed', False);
end;

// Saved cases and the downloaded model are NOT removed by default: they cannot be recovered.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  // never in a silent uninstall: suppressed message boxes are answered "Yes" automatically
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent()) then
  begin
    DataDir := ExpandConstant('{localappdata}\PrivateDocAI');
    if DirExists(DataDir) then
      if MsgBox('Vuoi eliminare anche le pratiche salvate, i profili del browser e il modello scaricato?' + #13#10 +
                'Non sarà possibile recuperarli.' + #13#10#13#10 + DataDir,
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
