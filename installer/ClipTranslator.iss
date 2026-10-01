#define AppName "ClipTranslator"
#define AppExe "{app}\.venv\Scripts\cliptranslator-app.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8C3F2A51-6D4E-4B7A-9E21-3F5B7C9D1A2E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=SebastianCotrina16
AppPublisherURL=https://github.com/SebastianCotrina16/ClipTranslator
DefaultDirName={localappdata}\Programs\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ClipTranslator-Setup-{#AppVersion}
SetupIconFile=..\build\icon.ico
UninstallDisplayIcon={app}\icon.ico
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Files]
Source: "..\app\*"; DestDir: "{app}\app"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs ignoreversion
Source: "..\pyproject.toml"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uv.lock"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "install.cmd"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\uv.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\python\*"; DestDir: "{app}\python"; Excludes: "__pycache__,*.pyc"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\build\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\build\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[InstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\.venv"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{#AppExe}"; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{#AppExe}"; Description: "Open {#AppName}"; WorkingDir: "{app}"; Flags: nowait postinstall skipifsilent
Filename: "{#AppExe}"; WorkingDir: "{app}"; Flags: nowait; Check: ReopenAfterUpdate

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\python"
Type: files; Name: "{app}\install.log"

[Code]
const
  RuntimeKey = 'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64';
  MinimumRuntimeMinor = 40;
  RebootRequired = 3010;
  NewerRuntimeInstalled = 1638;

function VisualCppRuntimeReady(): Boolean;
var
  Installed, Major, Minor: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM64, RuntimeKey, 'Installed', Installed)
    and RegQueryDWordValue(HKLM64, RuntimeKey, 'Major', Major)
    and RegQueryDWordValue(HKLM64, RuntimeKey, 'Minor', Minor)
    and (Installed = 1)
    and ((Major > 14) or ((Major = 14) and (Minor >= MinimumRuntimeMinor)));
end;

procedure InstallVisualCppRuntime();
var
  ResultCode: Integer;
begin
  if VisualCppRuntimeReady() then
    Exit;
  WizardForm.StatusLabel.Caption := 'Installing the Microsoft Visual C++ runtime...';
  if not ShellExec('runas', ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart', '', SW_SHOW, ewWaitUntilTerminated, ResultCode)
    or not ((ResultCode = 0) or (ResultCode = RebootRequired) or (ResultCode = NewerRuntimeInstalled)) then
    MsgBox('The Microsoft Visual C++ runtime could not be installed. Transcription may not work until it is installed from microsoft.com (search "Visual C++ Redistributable x64").', mbError, MB_OK);
end;

procedure InstallComponents();
var
  ResultCode: Integer;
begin
  WizardForm.StatusLabel.Caption := 'Downloading and installing components. This can take several minutes...';
  WizardForm.ProgressGauge.Style := npbstMarquee;
  try
    if not Exec(ExpandConstant('{cmd}'), '/C "' + ExpandConstant('{app}\install.cmd') + '"', ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      MsgBox('Some components could not be installed. Check your internet connection and run the installer again.' + #13#10#13#10 + 'Details: ' + ExpandConstant('{app}\install.log'), mbError, MB_OK);
  finally
    WizardForm.ProgressGauge.Style := npbstNormal;
  end;
end;

function RunningAppProcesses(): Variant;
var
  Locator, Service: Variant;
begin
  Locator := CreateOleObject('WbemScripting.SWbemLocator');
  Service := Locator.ConnectServer('.', 'root\CIMV2');
  Result := Service.ExecQuery('SELECT * FROM Win32_Process WHERE Name = ''cliptranslator-app.exe'' OR Name = ''cliptranslator.exe'' OR Name = ''python.exe'' OR Name = ''pythonw.exe''');
end;

function IsInsideApp(Process: Variant): Boolean;
var
  Value: Variant;
  Path: String;
begin
  Result := False;
  Value := Process.ExecutablePath;
  if VarIsNull(Value) or VarIsEmpty(Value) then
    Exit;
  Path := Value;
  Path := Lowercase(Path);
  Result := Pos(Lowercase(AddBackslash(ExpandConstant('{app}'))), Path) = 1;
end;

function CountRunningApp(): Integer;
var
  Processes, Process: Variant;
  Index: Integer;
begin
  Result := 0;
  try
    Processes := RunningAppProcesses();
    for Index := 0 to Processes.Count - 1 do
    begin
      Process := Processes.ItemIndex(Index);
      if IsInsideApp(Process) then
        Result := Result + 1;
    end;
  except
    Result := 0;
  end;
end;

procedure CloseRunningApp();
var
  Processes, Process: Variant;
  Index: Integer;
begin
  try
    Processes := RunningAppProcesses();
    for Index := 0 to Processes.Count - 1 do
    begin
      Process := Processes.ItemIndex(Index);
      if IsInsideApp(Process) then
        Process.Terminate();
    end;
  except
  end;
  Sleep(1500);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if CountRunningApp() = 0 then
    Exit;
  if SuppressibleMsgBox('ClipTranslator is open and will be closed to install the update.' + #13#10#13#10 + 'Subtitle edits are saved automatically, but a clip that is still being processed or exported will stop and has to be started again.', mbConfirmation, MB_OKCANCEL, IDOK) <> IDOK then
  begin
    Result := 'Close ClipTranslator and run the installer again.';
    Exit;
  end;
  CloseRunningApp();
  if CountRunningApp() > 0 then
    Result := 'ClipTranslator could not be closed. Close it and run the installer again.';
end;

function ReopenAfterUpdate(): Boolean;
begin
  Result := WizardSilent() and (ExpandConstant('{param:RESTARTAPP|0}') = '1');
end;

function InitializeUninstall(): Boolean;
begin
  CloseRunningApp();
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    InstallVisualCppRuntime();
    InstallComponents();
  end;
end;
