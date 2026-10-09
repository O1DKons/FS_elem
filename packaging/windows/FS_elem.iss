#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
[Setup]
AppId={{1253D5F8-57BA-4DEA-A660-E93AD4B94E39}
AppName=FS_elem
AppVersion=0.2.3
AppPublisher=FS_elem
DefaultDirName={localappdata}\Programs\FS_elem
DefaultGroupName=FS_elem
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
DisableDirPage=auto
OutputDir={#OutputDir}
OutputBaseFilename=FS_elem-Setup-0.2.3-x64
Compression=lzma2/normal
SolidCompression=yes
UninstallDisplayIcon={app}\FS_elem.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Ярлыки:"; Flags: unchecked

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\FS_elem"; Filename: "{app}\FS_elem.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\FS_elem"; Filename: "{app}\FS_elem.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\FS_elem.exe"; Description: "Запустить FS_elem"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := (GetEnv('PROCESSOR_ARCHITECTURE') = 'AMD64') or
    (GetEnv('PROCESSOR_ARCHITEW6432') = 'AMD64');
  if not Result then
    MsgBox('FS_elem требует Windows 10/11 x64.', mbError, MB_OK);
end;

