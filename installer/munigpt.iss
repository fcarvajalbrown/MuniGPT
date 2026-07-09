; MuniGPT - script de instalacion Inno Setup 6 (FR-14).
;
; SOLO SCRIPT. Requiere Inno Setup 6 (iscc.exe) para compilar; la compilacion del
; .exe y el empaquetado de los ~8 GB de modelos/binarios es tarea del pipeline de
; instalador (fuera del alcance del loop; ver docs/CHECKLIST_1.0.md, B3).
;
; Antes de compilar, generar la app de escritorio desde la raiz del repositorio:
;     npm run dist:dir      ->  electron\out\win-unpacked\MuniGPT.exe
; y colocar los modelos GGUF en backend\models\ (los espera main.py en runtime).
;
; Luego, desde esta carpeta:
;     iscc munigpt.iss      ->  installer\Output\MuniGPT-Setup-1.0.0.exe

#define MyAppName "MuniGPT"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Felipe Carvajal Brown"
#define MyAppExeName "MuniGPT.exe"

; Rutas relativas a la ubicacion de este .iss (installer\).
#define AppSrc "..\electron\out\win-unpacked"
#define BackendSrc "..\backend"

[Setup]
AppId={{7C9A4E1F-2B3D-4A6E-9F80-1D2C3B4A5E6F}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=MuniGPT-Setup-{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
; 1) La app de escritorio empaquetada por electron-builder (MuniGPT.exe + asar).
Source: "{#AppSrc}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; 2) El backend Python + assets. main.py se ejecuta con cwd = {app}\resources\backend
;    (process.resourcesPath\backend en electron), por lo que va exactamente ahi.
Source: "{#BackendSrc}\*"; DestDir: "{app}\resources\backend"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: ".venv\*,venv\*,__pycache__\*,*\__pycache__\*,.pytest_cache\*,*.pyc,tests\*,logs\*,*.log"
; 3) Configuracion inicial. main.py lee ../config.json respecto de su cwd, es decir
;    {app}\resources\config.json. No se sobrescribe si el operador ya la personalizo.
Source: "..\config.example.json"; DestDir: "{app}\resources"; DestName: "config.json"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
