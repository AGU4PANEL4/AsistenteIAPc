; ============================================================
; Instalador de AsistenteIA — Inno Setup
;
; Cómo usarlo:
; 1. Compila primero con PyInstaller (ver asistente.spec) para
;    generar la carpeta dist\AsistenteIA con el .exe adentro.
; 2. Abre este archivo con Inno Setup Compiler (o usa ISCC.exe
;    desde la terminal) y dale a "Compile" / "Build".
; 3. El instalador queda en la carpeta Output\ de este script.
;
; NOTA SOBRE PERMISOS:
; El instalador en sí NO pide admin para instalarse (PrivilegesRequired
; = lowest), así que cualquier usuario puede instalarlo en su carpeta
; de usuario sin UAC. Pero la app usa schtasks para el inicio
; automático, lo cual SÍ necesita admin — ese permiso se pide aparte,
; una sola vez, justo en el paso donde se crea la tarea programada
; (ver la sección [Run] más abajo, con Flags: runascurrentuser
; postinstall y el script de tareas con verb "runas").
; ============================================================

#define MyAppName "AsistenteIA"
#define MyAppVersion "1.0.2"
#define MyAppPublisher "David"
#define MyAppExeName "AsistenteIA.exe"

; Carpeta donde PyInstaller dejó el resultado (modo carpeta, no onefile)
#define MyDistDir "dist\AsistenteIA"

[Setup]
AppId={{B6F2B6A0-6E6E-4B7B-9C9E-ASISTENTE0001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

; El instalador en sí no requiere admin — solo el paso opcional
; de inicio automático lo pedirá, una vez, por separado.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

OutputDir=Output
OutputBaseFilename=AsistenteIA_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

; Cámbialo si tienes un .ico para el instalador
; SetupIconFile=icono.ico

[Languages]
; FIX: Spanish.isl solo existe si Inno Setup se instaló con el paquete
; de idiomas adicionales — en instalaciones mínimas (la más común al
; descargar el instalador oficial) no viene, y Inno Setup tiraba un
; error en esta línea. Se usa el inglés por defecto (Default.isl),
; que siempre está presente en cualquier instalación de Inno Setup.
; Los mensajes del instalador son genéricos (Next, Install, Finish)
; y no afectan el funcionamiento del asistente en sí.
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Accesos directos — el usuario puede destildarlos en el asistente
Name: "desktopicon"; Description: "Crear acceso directo en el &escritorio"; GroupDescription: "Accesos directos:"
Name: "startupauto"; Description: "Iniciar {#MyAppName} automáticamente con Windows"; GroupDescription: "Inicio automático:"; Flags: unchecked

[Files]
; Copia TODO lo que generó PyInstaller (el .exe + sus dependencias)
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Ofrece abrir el asistente justo al terminar de instalar
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} ahora"; Flags: nowait postinstall skipifsilent unchecked

; Si el usuario marcó la casilla de inicio automático, se registra
; la tarea programada de Windows. Esto SÍ requiere admin (schtasks
; con RunLevel HighestAvailable, igual que ya hace startup.py), por
; eso lleva el verbo "runas" — Windows pedirá confirmación de UAC
; en este único paso, no para el resto de la instalación.
;
; FIX: el flag usado acá era "runascurrentuser", que en Inno Setup
; significa exactamente lo CONTRARIO de lo que dice el comentario de
; FIX: el instalador de Inno Setup ya corre elevado (requiere admin
; para instalar en Program Files). En [Run], la ausencia del flag
; "runascurrentuser" hace que el proceso hijo HEREDE esa elevación —
; es exactamente lo que necesitamos para que schtasks pueda crear
; la tarea con RunLevel HighestAvailable sin "Acceso denegado".
; "runas" no es un flag válido en [Run] de Inno Setup (error de
; compilación en línea 99). "runascurrentuser" hace lo contrario:
; fuerza a correr SIN elevación, que era el bug original.
; Sin ninguno de los dos flags, la elevación se hereda sola.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--activar-startup"; \
    Tasks: startupauto; Flags: waituntilterminated; \
    StatusMsg: "Configurando inicio automático..."

[UninstallRun]
; Al desinstalar, quita también la tarea programada si existía,
; para no dejar basura en el Programador de tareas de Windows.
;
; FIX: antes esto llamaba a "schtasks /Delete" directamente. Borrar
; una tarea registrada con privilegios elevados (RunLevel
; HighestAvailable) puede requerir permisos de administrador, igual
; que crearla — y no hay garantía de que el flag de elevación de
; [Run] ("runas") esté soportado en esta sección [UninstallRun] de
; Inno Setup. En vez de arriesgar ese supuesto, se llama al propio
; .exe con "--desactivar-startup" (ver main.py), que internamente ya
; sabe detectar la falta de permisos y elevar por su cuenta vía UAC
; (ver _es_admin()/_ejecutar_elevado() en startup.py) — el mismo
; mecanismo ya usado y probado para activar el inicio automático.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--desactivar-startup"; \
    Flags: runhidden waituntilterminated; RunOnceId: "DelStartupTask"

[UninstallDelete]
; Borra archivos generados en uso (config.json, memoria.json, etc.)
; OJO: esto borra los datos guardados del usuario (aliases, memoria)
; al desinstalar. Si prefieres conservarlos, quita este bloque.
Type: filesandordirs; Name: "{localappdata}\AsistenteIA"
