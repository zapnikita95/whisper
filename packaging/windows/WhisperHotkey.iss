; Inno Setup 6 — из корня репозитория после PyInstaller: dist\WhisperHotkey\
; ISCC.exe WhisperHotkey.iss /DMyAppVersion=1.2.0

#define MyAppName "Whisper Hotkey"
#ifndef MyAppVersion
#define MyAppVersion "1.2.0"
#endif
#define MyAppPublisher "Whisper"
#define MyAppExeName "WhisperHotkey.exe"
#define MyAppGuid "B8C9D0E1-F2A3-4B5C-9D0E-1F2A3B4C5D6E"

[Setup]
AppId={{#MyAppGuid}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=..\..\dist\release
OutputBaseFilename=WhisperHotkeySetup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "Запускать при входе в Windows"; GroupDescription: "Автозагрузка:"; Flags: unchecked

[Files]
Source: "..\..\dist\WhisperHotkey\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "WhisperHotkey"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart
