; ============================================================
; C盘利刃 · 安装器脚本（Inno Setup 6）
; 编译：ISCC.exe "C盘利刃_安装器.iss"
; 产出：setup_output\C盘利刃_安装器_V2.2.exe
; 效果：双击 → 选安装位置 → 装好，桌面/开始菜单可选快捷方式，带卸载
; ============================================================

#define MyAppName      "C盘利刃"
#define MyAppVersion   "2.9"
#define MyAppPublisher "狗托儿"
#define MyAppURL       "https://goutuo4588.github.io/tools/"
#define MyAppExeName   "C盘利刃.exe"

[Setup]
; AppId 用固定 GUID：升级时 Inno 靠它识别是同一个软件，不会装出两份
AppId={{A7F3C1E8-5B42-4D96-9C10-8E3A7D21F904}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; no = 显示「选择目标位置」页面，让用户自己挑装到哪（这就是你要的那个界面）
DisableDirPage=no
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DirExistsWarning=yes
DisableProgramGroupPage=yes

OutputDir=setup_output
OutputBaseFilename=C盘利刃_安装器_V{#MyAppVersion}
SetupIconFile=icon.ico
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}

; C盘利刃 要动 C 盘、建计划任务，必须管理员权限
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
WizardStyle=modern

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
; PyInstaller 打出来的是单文件 exe，背景图/图标已烘进去，这里只需要本体
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "安装完成后立即运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent
