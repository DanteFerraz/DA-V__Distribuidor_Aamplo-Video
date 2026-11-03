; ==============================================================================
; DA-V (Distribuidor Amplo de Vídeo) — Script do Instalador Oficial Windows
; Autor: Dante Ferraz (MonoTech)
; ==============================================================================

#define MyAppName "DA-V · Distribuidor Amplo de Vídeo"
#define MyAppVersion "3.0"
#define MyAppPublisher "Dante Ferraz (MonoTech)"
#define MyAppURL "https://github.com/DanteFerraz/DA-V__Distribuidor_Aamplo-Video"
#define MyAppExeName "DA-V.exe"

[Setup]
AppId={{D415759A-DAV3-4B07-A59B-MONOTECH2026}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\DA-V
DefaultGroupName=DA-V
AllowNoIcons=yes
OutputDir=..\..\dist_installer
OutputBaseFilename=DA-V_Setup_v3.0_Windows_x64
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
DisableWelcomePage=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "firewallrule"; Description: "Liberar portas UDP automaticamente no Windows Defender Firewall (Recomendado)"; GroupDescription: "Rede e Conectividade:"
Name: "registerprotocol"; Description: "Registrar protocolo de convite 'dav://' (Permite abrir conexões via link direto)"; GroupDescription: "Integração com o Sistema:"

[Files]
Source: "..\..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".git\*,.pytest_cache\*,__pycache__\*,dist_installer\*,*.pyc"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Registro do Protocolo de URI dav:// para Deep Linking
Root: HKA; Subkey: "Software\Classes\dav"; ValueType: string; ValueName: ""; ValueData: "URL:DA-V Protocol"; Flags: uninsdeletekey; Tasks: registerprotocol
Root: HKA; Subkey: "Software\Classes\dav"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Tasks: registerprotocol
Root: HKA; Subkey: "Software\Classes\dav\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: registerprotocol
Root: HKA; Subkey: "Software\Classes\dav\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: registerprotocol

[Run]
; Libera regras do Firewall do Windows para UDP (Streaming de Vídeo e LAN Beacon)
Filename: "netsh.exe"; Parameters: "advfirewall firewall add rule name=""DA-V Video Streaming"" dir=in action=allow protocol=UDP localport=19000-19010 profile=any"; Flags: runhidden; Tasks: firewallrule
Filename: "netsh.exe"; Parameters: "advfirewall firewall add rule name=""DA-V LAN Beacon"" dir=in action=allow protocol=UDP localport=9005 profile=any"; Flags: runhidden; Tasks: firewallrule
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Remove regras do Firewall ao desinstalar
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""DA-V Video Streaming"""; Flags: runhidden
Filename: "netsh.exe"; Parameters: "advfirewall firewall delete rule name=""DA-V LAN Beacon"""; Flags: runhidden

