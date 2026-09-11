; Inno Setup script for Remote Transcribe.
;
; Build with the Inno Setup Compiler (ISCC.exe):
;
;   iscc /DAppVersion=1.0.0 windows\installer.iss
;
; Produces windows\output\RemoteTranscribe-Setup-<version>.exe, which you can
; attach to a GitHub Release. Running a newer installer over an older one is
; detected via AppId and performs an in-place upgrade; user data under
; {app}\data is preserved.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

[Setup]
; A stable GUID — do not change it, or updates will not detect older installs.
AppId={{5C0F14D8-2B0C-4E9C-8E4B-2C2AC13C4F1A}
AppName=Remote Transcribe
AppVersion={#AppVersion}
AppPublisher=Remote Transcribe
DefaultDirName={userpf}\RemoteTranscribe
DefaultGroupName=Remote Transcribe
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=RemoteTranscribe-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\windows\icon.ico
CloseApplications=force
RestartApplications=no
; Prompt on downgrade.
AppMutex=RemoteTranscribeInstallerMutex

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Ship everything the app needs. Excludes are important: never bundle the
; venv, git metadata, user data, or transient artefacts.
Source: "..\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; \
    Excludes: "\.git\*,\.git,\.venv\*,\.venv,data\*,windows\output\*,windows\last-startup.log,windows\uvicorn.log,windows\uvicorn.err.log,__pycache__\*,*.pyc,.env"

[Dirs]
; Keep the data directory across upgrades and uninstalls.
Name: "{app}\data"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\Remote Transcribe"; Filename: "{app}\windows\launcher.vbs"; \
    WorkingDir: "{app}"; IconFilename: "{app}\windows\icon.ico"; \
    Comment: "Start Remote Transcribe and open it in the browser."
Name: "{group}\Stop Remote Transcribe"; Filename: "{app}\windows\stop.vbs"; \
    WorkingDir: "{app}"; IconFilename: "{app}\windows\icon.ico"; \
    Comment: "Stop the Remote Transcribe server."
Name: "{group}\Uninstall Remote Transcribe"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Remote Transcribe"; Filename: "{app}\windows\launcher.vbs"; \
    WorkingDir: "{app}"; IconFilename: "{app}\windows\icon.ico"; \
    Tasks: desktopicon

[Run]
; Offer to launch the app at the end of install.
Filename: "{app}\windows\launcher.vbs"; Description: "Launch Remote Transcribe now"; \
    Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
; Clean up the venv and logs on uninstall — data/ is kept by [Dirs] above.
Type: filesandordirs; Name: "{app}\.venv"
Type: files; Name: "{app}\windows\last-startup.log"
Type: files; Name: "{app}\windows\uvicorn.log"
Type: files; Name: "{app}\windows\uvicorn.err.log"

[Code]
function InitializeSetup(): Boolean;
var
  PythonPath: String;
  ResultCode: Integer;
begin
  Result := True;
  // Warn (don't block) if Python isn't on PATH. Users often install it right
  // after and re-run; blocking here would be more annoying than helpful.
  if not Exec('cmd.exe', '/C where python >nul 2>nul', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    if MsgBox('Python 3.11+ was not detected on PATH.' + #13#10 +
              'Remote Transcribe needs it to run.' + #13#10 + #13#10 +
              'Install it from python.org (tick "Add Python to PATH") and then relaunch the app.' + #13#10 + #13#10 +
              'Continue installing anyway?', mbConfirmation, MB_YESNO) = IDNO then
      Result := False;
  end;
end;
