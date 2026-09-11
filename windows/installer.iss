; Remote Transcribe installer.
;
; One .exe. Prompts for API keys, downloads a private Python runtime and
; ffmpeg during install, writes .env, drops one shortcut on the Desktop and
; in the Start Menu. Re-running detects the existing install and pre-fills
; the fields, so "change your keys later" is just "run the installer again".
;
; Build with the Inno Setup Compiler (ISCC.exe), Inno Setup 6.1+:
;   iscc /DAppVersion=1.0.0 windows\installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

; Pinned upstream artefacts. Bump these to update the bundled runtime.
#define PythonVersion "3.11.9"
#define PythonZipName "python-3.11.9-embed-amd64.zip"
#define PythonUrl     "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
#define GetPipUrl     "https://bootstrap.pypa.io/pip/get-pip.py"
#define FfmpegZipName "ffmpeg-release-essentials.zip"
#define FfmpegUrl     "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

[Setup]
; Never change this — updates rely on it to find the previous install.
AppId={{7A8B9C2D-3E4F-5A6B-7C8D-9E0F1A2B3C4D}
AppName=Remote Transcribe
AppVersion={#AppVersion}
AppVerName=Remote Transcribe {#AppVersion}
AppPublisher=Remote Transcribe
DefaultDirName={autopf}\RemoteTranscribe
DefaultGroupName=Remote Transcribe
DisableProgramGroupPage=yes
DisableReadyPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=output
OutputBaseFilename=RemoteTranscribe-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UsePreviousAppDir=yes
UsePreviousTasks=yes
CloseApplications=force
RestartApplications=no
UninstallDisplayName=Remote Transcribe
UninstallDisplayIcon={app}\windows\icon.ico
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Remote Transcribe
VersionInfoProductVersion={#AppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checkedonce

[Files]
Source: "..\app\*";       DestDir: "{app}\app";     Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\static\*";    DestDir: "{app}\static";  Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\tests\*";     DestDir: "{app}\tests";   Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\.env.example";     DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md";        DestDir: "{app}"; Flags: ignoreversion
Source: "launcher.ps1";        DestDir: "{app}\windows"; Flags: ignoreversion
Source: "launcher.vbs";        DestDir: "{app}\windows"; Flags: ignoreversion
Source: "icon.ico";            DestDir: "{app}\windows"; Flags: ignoreversion skipifsourcedoesntexist

[Dirs]
Name: "{app}\data"; Flags: uninsneveruninstall

[Icons]
Name: "{group}\Remote Transcribe"; Filename: "{app}\windows\launcher.vbs"; \
    WorkingDir: "{app}"; IconFilename: "{app}\windows\icon.ico"; \
    Comment: "Start Remote Transcribe and open it in the browser."
Name: "{group}\Uninstall Remote Transcribe"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Remote Transcribe"; Filename: "{app}\windows\launcher.vbs"; \
    WorkingDir: "{app}"; IconFilename: "{app}\windows\icon.ico"; \
    Tasks: desktopicon

[Run]
; Offered as a checkbox on the finish page.
Filename: "{app}\windows\launcher.vbs"; Description: "Launch Remote Transcribe now"; \
    Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\ffmpeg"
Type: files; Name: "{app}\.env"
Type: files; Name: "{app}\windows\last-startup.log"
Type: files; Name: "{app}\windows\uvicorn.log"
Type: files; Name: "{app}\windows\uvicorn.err.log"

; ---------------------------------------------------------------------------
; Pascal Script: env-var wizard page, download + install of Python/ffmpeg,
; .env writer, and existing-install detection.
; ---------------------------------------------------------------------------
[Code]

var
  ConfigPage: TInputQueryWizardPage;
  IsUpgrade: Boolean;
  IsSameVersion: Boolean;
  IsDowngrade: Boolean;
  ExistingVersion: String;

function GetUninstallRegKey(): String;
begin
  Result := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1';
end;

function ReadInstalledVersion(): String;
var
  V: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, GetUninstallRegKey(), 'DisplayVersion', V) then
    Result := V
  else if RegQueryStringValue(HKLM, GetUninstallRegKey(), 'DisplayVersion', V) then
    Result := V;
end;

function ReadInstalledDir(): String;
var
  V: String;
begin
  Result := '';
  if RegQueryStringValue(HKCU, GetUninstallRegKey(), 'InstallLocation', V) then
    Result := RemoveBackslashUnlessRoot(V)
  else if RegQueryStringValue(HKLM, GetUninstallRegKey(), 'InstallLocation', V) then
    Result := RemoveBackslashUnlessRoot(V);
end;

function CompareVersions(A, B: String): Integer;
var
  I, PosA, PosB, NA, NB: Integer;
  PartA, PartB: String;
begin
  Result := 0;
  I := 0;
  while (Length(A) > 0) or (Length(B) > 0) do
  begin
    PosA := Pos('.', A);
    if PosA = 0 then begin PartA := A; A := ''; end
    else begin PartA := Copy(A, 1, PosA - 1); A := Copy(A, PosA + 1, MaxInt); end;

    PosB := Pos('.', B);
    if PosB = 0 then begin PartB := B; B := ''; end
    else begin PartB := Copy(B, 1, PosB - 1); B := Copy(B, PosB + 1, MaxInt); end;

    NA := StrToIntDef(PartA, 0);
    NB := StrToIntDef(PartB, 0);
    if NA > NB then begin Result := 1; Exit; end;
    if NA < NB then begin Result := -1; Exit; end;
    Inc(I);
    if I > 5 then Exit;
  end;
end;

function LoadEnvValue(FileName, Key: String): String;
var
  Lines: TArrayOfString;
  I, EqPos: Integer;
  Line, K, V: String;
begin
  Result := '';
  if not FileExists(FileName) then Exit;
  if not LoadStringsFromFile(FileName, Lines) then Exit;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    Line := Trim(Lines[I]);
    if (Length(Line) = 0) or (Line[1] = '#') then Continue;
    EqPos := Pos('=', Line);
    if EqPos = 0 then Continue;
    K := Trim(Copy(Line, 1, EqPos - 1));
    V := Copy(Line, EqPos + 1, MaxInt);
    if CompareText(K, Key) = 0 then
    begin
      // Strip surrounding quotes if present.
      if (Length(V) >= 2) and (V[1] = '"') and (V[Length(V)] = '"') then
        V := Copy(V, 2, Length(V) - 2);
      Result := V;
      Exit;
    end;
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  ExistingVersion := ReadInstalledVersion();
  IsUpgrade := False;
  IsSameVersion := False;
  IsDowngrade := False;
  if ExistingVersion <> '' then
  begin
    case CompareVersions('{#AppVersion}', ExistingVersion) of
      1:  IsUpgrade := True;
      0:  IsSameVersion := True;
     -1:  IsDowngrade := True;
    end;

    if IsDowngrade then
    begin
      if MsgBox(
          'A newer version of Remote Transcribe (' + ExistingVersion + ') is already installed.' + #13#10 +
          'You are about to install version {#AppVersion}, which is older.' + #13#10 + #13#10 +
          'Continue anyway?',
          mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

procedure InitializeWizard();
var
  Prompts, Descriptions: TArrayOfString;
  Existing: String;
  Intro: String;
begin
  if IsUpgrade then
    Intro := 'An older version (' + ExistingVersion + ') was detected. Your keys are pre-filled — change them or leave them as-is, then click Next.'
  else if IsSameVersion then
    Intro := 'Remote Transcribe {#AppVersion} is already installed. Change your keys here, or click through to repair the install.'
  else
    Intro := 'Enter your Groq API key. The other fields are optional. You can change these later by re-running this installer.';

  ConfigPage := CreateInputQueryPage(wpSelectDir,
    'Configuration',
    'API keys and password',
    Intro);

  ConfigPage.Add('Groq API key (required, from https://console.groq.com/keys):', False);
  ConfigPage.Add('ElevenLabs API key (optional — enables acoustic speaker separation):', False);
  ConfigPage.Add('App password (optional — leave blank to disable the login gate):', True);

  // Pre-fill from an existing .env if one is around.
  Existing := ReadInstalledDir();
  if (Existing <> '') and FileExists(Existing + '\.env') then
  begin
    ConfigPage.Values[0] := LoadEnvValue(Existing + '\.env', 'GROQ_API_KEY');
    ConfigPage.Values[1] := LoadEnvValue(Existing + '\.env', 'ELEVENLABS_API_KEY');
    ConfigPage.Values[2] := LoadEnvValue(Existing + '\.env', 'APP_PASSWORD');
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = ConfigPage.ID then
  begin
    if Trim(ConfigPage.Values[0]) = '' then
    begin
      if MsgBox(
          'No Groq API key entered. The app will install but will not be able to transcribe until you re-run this installer and add one.' + #13#10 + #13#10 +
          'Continue without a key?',
          mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

function PythonDllOverridePath(): String;
begin
  Result := ExpandConstant('{app}\python\python311._pth');
end;

procedure FixPythonPthFile();
var
  Lines: TArrayOfString;
  I: Integer;
  Modified: Boolean;
  Path: String;
begin
  Path := PythonDllOverridePath();
  if not FileExists(Path) then Exit;
  if not LoadStringsFromFile(Path, Lines) then Exit;
  Modified := False;
  for I := 0 to GetArrayLength(Lines) - 1 do
  begin
    if Trim(Lines[I]) = '#import site' then
    begin
      Lines[I] := 'import site';
      Modified := True;
    end;
  end;
  if Modified then SaveStringsToFile(Path, Lines, False);
end;

function RunHidden(Exe, Params, WorkingDir: String): Integer;
var
  Code: Integer;
begin
  if not Exec(Exe, Params, WorkingDir, SW_HIDE, ewWaitUntilTerminated, Code) then
    Code := -1;
  Result := Code;
end;

function ExtractZip(ZipPath, DestDir: String): Boolean;
var
  Code: Integer;
  Cmd: String;
begin
  ForceDirectories(DestDir);
  Cmd := '-NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath ''' +
         ZipPath + ''' -DestinationPath ''' + DestDir + ''' -Force"';
  Code := RunHidden('powershell.exe', Cmd, '');
  Result := Code = 0;
end;

procedure SetStatus(Msg: String);
begin
  WizardForm.StatusLabel.Caption := Msg;
  WizardForm.FilenameLabel.Caption := '';
end;

procedure WriteEnvFile();
var
  Lines: TArrayOfString;
  Path, Groq, Eleven, Pw: String;
begin
  Path := ExpandConstant('{app}\.env');
  Groq   := Trim(ConfigPage.Values[0]);
  Eleven := Trim(ConfigPage.Values[1]);
  Pw     := ConfigPage.Values[2];

  SetArrayLength(Lines, 4);
  Lines[0] := '# Written by the Remote Transcribe installer. Re-run the installer to change.';
  Lines[1] := 'GROQ_API_KEY=' + Groq;
  Lines[2] := 'ELEVENLABS_API_KEY=' + Eleven;
  Lines[3] := 'APP_PASSWORD=' + Pw;
  SaveStringsToFile(Path, Lines, False);
end;

function InstallRuntime(): Boolean;
var
  PyDir, FfDir, TmpDir, PyZip, FfZip, GetPip, Python: String;
  Code: Integer;
begin
  Result := False;
  TmpDir := ExpandConstant('{tmp}');
  PyDir  := ExpandConstant('{app}\python');
  FfDir  := ExpandConstant('{app}\ffmpeg');
  PyZip  := TmpDir + '\{#PythonZipName}';
  FfZip  := TmpDir + '\{#FfmpegZipName}';
  GetPip := TmpDir + '\get-pip.py';
  Python := PyDir + '\python.exe';

  // --- Python -----------------------------------------------------------
  if not FileExists(Python) then
  begin
    SetStatus('Downloading Python runtime...');
    try
      DownloadTemporaryFile('{#PythonUrl}', '{#PythonZipName}', '', nil);
    except
      MsgBox('Could not download the Python runtime.' + #13#10 + GetExceptionMessage(), mbError, MB_OK);
      Exit;
    end;
    SetStatus('Extracting Python runtime...');
    if not ExtractZip(PyZip, PyDir) then
    begin
      MsgBox('Could not extract the Python runtime.', mbError, MB_OK);
      Exit;
    end;
    FixPythonPthFile();
  end;

  // --- pip --------------------------------------------------------------
  SetStatus('Setting up pip...');
  try
    DownloadTemporaryFile('{#GetPipUrl}', 'get-pip.py', '', nil);
  except
    MsgBox('Could not download pip bootstrap.' + #13#10 + GetExceptionMessage(), mbError, MB_OK);
    Exit;
  end;
  Code := RunHidden(Python, '"' + GetPip + '" --no-warn-script-location', PyDir);
  if Code <> 0 then
  begin
    MsgBox('pip bootstrap failed (exit code ' + IntToStr(Code) + ').', mbError, MB_OK);
    Exit;
  end;

  // --- app dependencies -------------------------------------------------
  SetStatus('Installing Python dependencies (this may take a minute)...');
  Code := RunHidden(Python,
    '-m pip install --no-warn-script-location -r "' + ExpandConstant('{app}\requirements.txt') + '"',
    ExpandConstant('{app}'));
  if Code <> 0 then
  begin
    MsgBox('Installing Python dependencies failed (exit code ' + IntToStr(Code) + ').' + #13#10 +
           'Check your internet connection and re-run the installer.', mbError, MB_OK);
    Exit;
  end;

  // --- ffmpeg -----------------------------------------------------------
  if not FileExists(FfDir + '\bin\ffmpeg.exe') then
  begin
    SetStatus('Downloading ffmpeg...');
    try
      DownloadTemporaryFile('{#FfmpegUrl}', '{#FfmpegZipName}', '', nil);
    except
      MsgBox('Could not download ffmpeg.' + #13#10 + GetExceptionMessage(), mbError, MB_OK);
      Exit;
    end;
    SetStatus('Extracting ffmpeg...');
    if not ExtractZip(FfZip, ExpandConstant('{tmp}\ffmpeg-extract')) then
    begin
      MsgBox('Could not extract ffmpeg.', mbError, MB_OK);
      Exit;
    end;
    // The zip contains a single top-level folder like ffmpeg-*-essentials_build.
    // Flatten it via robocopy /E /MOVE from that folder into {app}\ffmpeg.
    Code := RunHidden('powershell.exe',
      '-NoProfile -ExecutionPolicy Bypass -Command "' +
      '$src = Get-ChildItem -Directory ''' + ExpandConstant('{tmp}\ffmpeg-extract') + ''' | Select-Object -First 1; ' +
      'if ($src) { Move-Item -Path ($src.FullName + ''\*'') -Destination ''' + FfDir + ''' -Force }"',
      '');
    if not FileExists(FfDir + '\bin\ffmpeg.exe') then
    begin
      MsgBox('Could not stage ffmpeg into ' + FfDir + '.', mbError, MB_OK);
      Exit;
    end;
  end;

  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    WriteEnvFile();
    if not InstallRuntime() then
    begin
      MsgBox('Runtime setup did not finish. You can re-run the installer and choose Repair to try again.',
             mbInformation, MB_OK);
    end;
  end;
end;

procedure CurUninstallStepChanged(CurStep: TUninstallStep);
begin
  if CurStep = usPostUninstall then
  begin
    // data/ is kept via [Dirs] uninsneveruninstall so history and audio survive.
  end;
end;
