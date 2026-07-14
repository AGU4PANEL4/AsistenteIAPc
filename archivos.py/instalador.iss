; ============================================================
; Instalador de AsistenteIA — Inno Setup 6
; ============================================================

#define MyAppName      "AsistenteIA"
#define MyAppVersion   "1.2.2"
#define MyAppPublisher "David"
#define MyAppExeName   "AsistenteIA.exe"
#define MyDistDir      "dist\AsistenteIA"

; ============================================================
[Setup]
; ── identidad ───────────────────────────────────────────────
; FIX: el AppId original terminaba en "ASISTENTE0001" — un GUID solo
; puede contener dígitos hexadecimales (0-9 y A-F), y letras como
; S, I, T, N no lo son. Eso hacía que el Compilador de Inno Setup
; rechazara el AppId directamente. Se reemplaza por un GUID válido
; — mismo valor de ahora en más, no lo cambies en próximas
; versiones: el AppId es lo que usa Windows para identificar
; instalaciones/actualizaciones de la MISMA app entre versiones.
AppId={{B6F2B6A0-6E6E-4B7B-9C9E-A55157E10001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppComments=Asistente de voz con IA para controlar tu PC
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} Installer
VersionInfoProductName={#MyAppName}

; ── instalación ─────────────────────────────────────────────
; Se instala en carpeta de usuario (no requiere admin para la
; instalación base). Solo el paso opcional de inicio automático
; pedirá UAC, una sola vez, por su cuenta.
DefaultDirName={userappdata}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; ── cierre/reapertura automática de la app ─────────────────
; FIX/NUEVO: AppMutex le dice a Inno Setup CUÁL es el mutex de
; nuestra propia app (ver instancia.py) para su mecanismo NATIVO de
; "cerrar aplicaciones en uso" — esto es una red de seguridad además
; de que actualizador.py ya libera este mismo mutex a mano justo
; antes de lanzar el instalador (ver _instalar_y_cerrar): si por
; algún motivo el mutex NO se liberó a tiempo (ej. se corrió el
; instalador manualmente con el asistente abierto), Setup lo detecta
; solo y lo cierra, en vez de solo avisar y dejar que el usuario
; decida "continuar de todas formas" con el riesgo de sobreescribir
; archivos en uso.
;
; CloseApplications=force -> cierra la app automáticamente sin
;   preguntar (fuerza el cierre si hace falta) en vez de mostrar la
;   página de "Files In Use" pidiendo confirmación — necesario para
;   que la actualización automática (/VERYSILENT) sea 100%
;   desatendida.
; RestartApplications=yes -> vuelve a abrir lo que cerró, una vez
;   termina de instalar.
AppMutex=AsistenteIA_Running
CloseApplications=force
RestartApplications=yes

; ── salida ──────────────────────────────────────────────────
OutputDir=Output
OutputBaseFilename=AsistenteIA_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes

; ── apariencia ──────────────────────────────────────────────
WizardStyle=modern
; Descomenta estas líneas si tenés imágenes de branding:
; WizardImageFile=installer_banner.bmp        ; 164x314 px
; WizardSmallImageFile=installer_logo.bmp     ; 55x55 px
; SetupIconFile=icono.ico

; ── comportamiento ──────────────────────────────────────────
; Muestra la licencia y el README si existen en el proyecto
; LicenseFile=LICENSE.txt
; InfoAfterFile=LEEME.txt
DisableWelcomePage=no
DisableReadyPage=no
ShowLanguageDialog=no
AlwaysShowDirOnReadyPage=yes
AlwaysShowGroupOnReadyPage=no

; ── menú inicio ─────────────────────────────────────────────
; Cámbialo si tienes un .ico para el instalador
; SetupIconFile=icono.ico

; ============================================================
[Languages]
; Default.isl siempre está presente en cualquier instalación
; de Inno Setup — no depende de paquetes de idioma opcionales.
Name: "english"; MessagesFile: "compiler:Default.isl"

; ============================================================
[CustomMessages]
; Textos personalizados en español para la UI del instalador

; página de bienvenida
english.WelcomeLabel1=Bienvenido al instalador de [name]
english.WelcomeLabel2=Este asistente instalará [name/ver] en tu PC.%n%nCierra otras aplicaciones antes de continuar.

; tareas
english.CreateDesktopIcon=Crear acceso directo en el &escritorio
english.StartupAutoLabel=Iniciar {#MyAppName} automáticamente al encender Windows
english.StartupAdminNote=(requiere confirmar permisos de administrador)
english.StartupGroupLabel=Inicio automático con Windows:
english.ShortcutsGroupLabel=Accesos directos:

; página de éxito
english.FinishedLabel=La instalación de [name] ha finalizado correctamente.%n%nEl asistente se activa diciendo su nombre en voz alta.

; ============================================================
[Tasks]
; ── accesos directos ────────────────────────────────────────
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:ShortcutsGroupLabel}"

; ── inicio automático ───────────────────────────────────────
; El ícono de escudo (🛡) en la descripción es la forma estándar
; en Windows de indicar visualmente que una acción requiere
; permisos de administrador — el mismo glifo que Windows usa en
; botones de UAC del Panel de control y Configuración.
Name: "startupauto"; Description: "{cm:StartupAutoLabel}  🛡  {cm:StartupAdminNote}"; GroupDescription: "{cm:StartupGroupLabel}"; Flags: unchecked

; ============================================================
[Files]
; Copia TODO lo que generó PyInstaller (exe + dependencias)
Source: "{#MyDistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; ============================================================
[Icons]
; Menú inicio
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"

; Escritorio (solo si se marcó la tarea)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

; ============================================================
[Run]
; ── activar inicio automático (solo si se marcó) ────────────
; El instalador hereda los permisos de admin cuando el usuario
; los otorga durante la instalación, así que schtasks puede
; crear la tarea con RunLevel HighestAvailable sin pedir UAC
; de nuevo. Si la instalación fue sin admin (carpeta de usuario),
; startup.py detecta la falta de permisos y eleva por su cuenta.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--activar-startup"; Tasks: startupauto; Flags: waituntilterminated; StatusMsg: "Configurando inicio automático con Windows..."

; ── ofrecer abrir al terminar (instalación interactiva) ─────
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} ahora"; Flags: nowait postinstall skipifsilent unchecked

; ── reabrir automáticamente (SOLO auto-actualización silenciosa) ──
; FIX/NUEVO: el Run de arriba usa "skipifsilent" — a propósito, para
; NO reabrir solo cuando alguien corre el instalador a mano en modo
; silencioso sin querer reabrir nada. Pero la auto-actualización
; (ver actualizador.py, /VERYSILENT /RESTARTAPPLICATIONS) SÍ necesita
; que el asistente vuelva a abrirse solo, sin que el usuario tenga
; que hacerlo manualmente después. Check: WizardSilent hace que esta
; línea EXISTA solo para el caso silencioso — nunca se ejecuta en una
; instalación interactiva normal (ahí ya está el Run de arriba, con
; su casilla opcional).
Filename: "{app}\{#MyAppExeName}"; Flags: nowait; Check: WizardSilent

; ============================================================
[UninstallRun]
; Elimina la tarea programada al desinstalar, usando el propio
; .exe con --desactivar-startup, que ya maneja los permisos
; necesarios internamente (ver startup.py).
Filename: "{app}\{#MyAppExeName}"; Parameters: "--desactivar-startup"; Flags: runhidden waituntilterminated; RunOnceId: "DelStartupTask"

; ============================================================
; FIX: antes acá había un [UninstallDelete] que borraba TODA
; %LOCALAPPDATA%\AsistenteIA sin preguntar (config.json con tus
; API keys de Groq/Spotify, aliases.json, macros.json, memoria.json,
; recordatorios.json, temporizadores.json, el log — todo). La
; sección [UninstallDelete] de Inno Setup no tiene forma de
; condicionar el borrado a una pregunta al usuario, así que se
; movió a [Code] (ver InitializeUninstall/CurUninstallStepChanged
; más abajo), que sí puede preguntar primero y decidir según la
; respuesta.
; ============================================================

; ============================================================
[Code]
{ Pascal Script — lógica adicional del instalador }

{ ── página de bienvenida personalizada ──────────────────────
  Agrega una nota de requisitos del sistema debajo del texto
  estándar de bienvenida, sin reemplazar nada de lo que ya hay. }

var
  ReqLabel: TLabel;

procedure InitializeWizard();
var
  WelcomePage: TWizardPage;
begin
  { nota de requisitos del sistema en la página de bienvenida }
  ReqLabel              := TLabel.Create(WizardForm);
  ReqLabel.Parent       := WizardForm.WelcomeLabel2.Parent;
  ReqLabel.Left         := WizardForm.WelcomeLabel2.Left;
  ReqLabel.Top          := WizardForm.WelcomeLabel2.Top + WizardForm.WelcomeLabel2.Height + 16;
  ReqLabel.Width        := WizardForm.WelcomeLabel2.Width;
  ReqLabel.AutoSize     := False;
  ReqLabel.WordWrap     := True;
  ReqLabel.Height       := 80;
  ReqLabel.Caption      :=
    'Requisitos:' + #13#10 +
    '  • Windows 10 / 11' + #13#10 +
    '  • Micrófono conectado y configurado' + #13#10 +
    '  • Conexión a internet para configuración inicial';
  ReqLabel.Font.Color   := $00888888;
  ReqLabel.Font.Size    := 8;
end;

{ ── validación antes de instalar ────────────────────────────
  Avisa si el asistente ya está corriendo para que el usuario
  lo cierre antes de que el instalador sobreescriba los archivos. }

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;

  { FIX/NUEVO: en una auto-actualización (/VERYSILENT), el mutex ya
    se libera a mano justo antes de lanzar este instalador (ver
    instancia.liberar() en actualizador.py._instalar_y_cerrar), así
    que en ese caso CheckForMutexes ya va a devolver False de todas
    formas. Pero si alguien corre el instalador manualmente en modo
    silencioso (ej. un script propio) con el asistente sí abierto de
    verdad, no tiene sentido mostrar un MsgBox que nadie va a ver —
    WizardSilent() evita preguntarle nada a un usuario que no está
    mirando; AppMutex + CloseApplications=force (ver [Setup] arriba)
    ya se encargan de cerrar la app de todas formas antes de instalar. }
  if WizardSilent() then
    Exit;

  { verificar si el proceso está corriendo (solo instalación interactiva) }
  if CheckForMutexes('AsistenteIA_Running') then
  begin
    if MsgBox(
      'El Asistente IA parece estar ejecutándose.' + #13#10 +
      'Por favor ciérralo antes de continuar con la instalación.' + #13#10#13#10 +
      '¿Deseas continuar de todas formas?',
      mbConfirmation, MB_YESNO
    ) = IDNO then
      Result := False;
  end;
end;

{ ── mensaje de éxito personalizado ──────────────────────────
  Reemplaza el texto genérico de "Setup was successful" con
  instrucciones concretas de cómo usar el asistente. }

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then
  begin
    WizardForm.FinishedLabel.Caption :=
      'La instalación de ' + '{#MyAppName}' + ' ha finalizado.' + #13#10#13#10 +
      'Para usar el asistente:' + #13#10 +
      '  1. Ábrelo desde el acceso directo o el menú Inicio' + #13#10 +
      '  2. Espera a que termine de cargar' + #13#10 +
      '  3. Di "Jarvis" para activarlo y empieza a dar comandos' + #13#10#13#10 +
      'La primera vez te pedirá configurar tu API key de Groq' + #13#10 +
      '(gratuita) para activar el modo con internet.';
  end;
end;

{ ── desinstalación: preguntar antes de borrar datos de usuario ──
  FIX/NUEVO: antes, [UninstallDelete] borraba SIEMPRE toda
  %LOCALAPPDATA%\AsistenteIA (config.json con tus API keys, alias,
  macros, recordatorios, temporizadores, memoria, el log) apenas se
  desinstalaba, sin ninguna forma de evitarlo desde la interfaz del
  desinstalador. Eso significa perder todo lo configurado solo por
  desinstalar (ej. para probar una versión distinta, o reinstalar en
  otra carpeta) — incluso si la intención era volver a instalar
  después y seguir donde uno había quedado.

  Ahora se pregunta ANTES de borrar nada, con "No" (conservar) como
  respuesta por defecto (MB_DEFBUTTON2) — más seguro que borrar por
  accidente al apretar Enter sin leer. Si el usuario elige "Sí", se
  borra todo recién en usPostUninstall (después de que el programa
  en sí ya se desinstaló), nunca antes. }

var
  BorrarDatosUsuario: Boolean;

function InitializeUninstall(): Boolean;
begin
  Result := True;

  BorrarDatosUsuario := MsgBox(
    'Además de ' + '{#MyAppName}' + ', ¿querés borrar también tus datos ' +
    'guardados (alias, macros, recordatorios, temporizadores, ' +
    'configuración y el log)?' + #13#10#13#10 +
    'Si elegís "No", esos datos quedan intactos por si volvés a ' +
    'instalar ' + '{#MyAppName}' + ' más adelante.',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2
  ) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and BorrarDatosUsuario then
    DelTree(ExpandConstant('{localappdata}\AsistenteIA'), True, True, True);
end;