; NCM 转换器 Inno Setup 安装包脚本
; 构建：在项目根目录运行 build_installer.ps1

#define MyAppName "MusicCat"
#define MyAppVersion "1.2.2"

[Setup]
AppId={{4C6A2E91-8B7D-4E3F-9A55-C2D10F7B8E44}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppName} Project
DefaultDirName={autopf}\{#MyAppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
DefaultGroupName={#MyAppName}
OutputDir=.
OutputBaseFilename=MusicCat-{#MyAppVersion}-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppName}.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; \
    Flags: recursesubdirs createallsubdirs ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppName}.exe"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppName}.exe"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppName}.exe"; \
    Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent
