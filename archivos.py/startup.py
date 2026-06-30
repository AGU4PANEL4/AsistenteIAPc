import os
import sys
import subprocess
import tempfile
import ctypes
from pathlib import Path
from logger import log

NOMBRE_ASISTENTE = "AsistenteIA"

# =========================================================
# PERMISOS DE ADMINISTRADOR
# FIX/NUEVO: la tarea programada se crea con
# <RunLevel>HighestAvailable</RunLevel> (necesario para que el
# asistente pueda cerrar procesos elevados). Windows EXIGE que quien
# registre una tarea con privilegios elevados sea, a su vez, un
# proceso elevado — si el asistente corre como usuario normal (el
# caso de uso típico, sin "Ejecutar como administrador"), schtasks
# /Create devuelve literalmente "ERROR: Acceso denegado." y antes
# esto se traducía en el mensaje genérico "No pude activar el inicio
# automático", sin que el usuario entendiera por qué.
#
# _es_admin() detecta esta situación, y _ejecutar_elevado() dispara
# el cuadro de UAC de Windows SOLO para el comando puntual de
# schtasks (no para todo el asistente) — el usuario ve el típico
# "¿Permitir que esta app haga cambios?", lo acepta una vez, y la
# tarea queda registrada sin tener que cerrar y reabrir el asistente
# como administrador.
# =========================================================

def _es_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _ejecutar_elevado(comando, argumentos_lista, timeout_segundos=90):
    """
    Ejecuta `comando` con privilegios de administrador (vía el cuadro
    de UAC de Windows) y espera a que termine. Devuelve True si el
    proceso terminó con código de salida 0 (éxito), False si el
    usuario rechazó el UAC, no respondió a tiempo, o el comando falló
    por cualquier otro motivo.

    Se usa Start-Process -Verb RunAs de PowerShell (el mecanismo
    estándar para elevar un comando puntual sin elevar el proceso
    que lo invoca) en vez de re-lanzar el asistente completo como
    administrador, que sería mucho más invasivo para algo que el
    usuario solo necesita confirmar una vez.

    FIX/NUEVO: la primera versión de esto usaba "-Wait" (espera
    indefinida) — si el cuadro de UAC quedaba oculto detrás de otra
    ventana o nadie lo confirmaba, este comando (y por lo tanto la
    acción de voz completa, ej. "activa el inicio automático") se
    quedaba colgado para siempre, sin ningún aviso de que el
    asistente seguía "vivo" esperando una confirmación invisible.
    Ahora se usa WaitForExit(ms) con un timeout explícito — si nadie
    confirma a tiempo, se intenta matar el proceso elevado y se
    devuelve False, dejando que quien llama lo reporte como un fallo
    normal en vez de quedarse esperando indefinidamente.
    """
    try:
        # cada argumento se pasa entre comillas simples para que
        # PowerShell no los separe en espacios — necesario porque la
        # ruta del XML temporal casi siempre tiene espacios
        # (ej. "C:\Users\Nombre Con Espacio\...")
        argumentos_ps  = ",".join(f"'{a}'" for a in argumentos_lista)
        timeout_ms     = int(timeout_segundos * 1000)

        resultado = subprocess.run(
            [
                "powershell", "-WindowStyle", "Hidden", "-Command",
                f"$p = Start-Process -FilePath '{comando}' "
                f"-ArgumentList {argumentos_ps} -Verb RunAs -PassThru; "
                f"if (-not $p.WaitForExit({timeout_ms})) {{ "
                f"try {{ $p.Kill() }} catch {{}}; exit 1 }}; "
                f"exit $p.ExitCode"
            ],
            capture_output=True,
            text=True,
            # margen extra sobre el timeout interno de PowerShell,
            # por si quedara colgado por algún motivo ajeno a la
            # lógica de WaitForExit (ej. el propio powershell.exe)
            timeout=timeout_segundos + 10,
        )
        return resultado.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[Startup] No se confirmó el permiso de administrador "
              f"en {timeout_segundos}s, se cancela la acción.")
        # warning, no error: rechazar o ignorar el UAC es una decisión
        # válida del usuario, no un bug — pero vale la pena que quede
        # registrado, porque explica por qué una acción (activar o
        # desactivar el inicio automático) no se completó, sin que
        # haya ningún traceback ni error de Python de por medio.
        log.warning(f"UAC no confirmado en {timeout_segundos}s para "
                    f"'{comando} {' '.join(argumentos_lista)}'")
        return False
    except Exception as e:
        print("[Startup] Error ejecutando elevado:", e)
        log.exception(f"Error ejecutando elevado: {comando} {argumentos_lista}")
        return False

# =========================================================
# RUTAS
# =========================================================

def ruta_inicio_windows():

    ruta = (
        Path(os.getenv("APPDATA"))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )

    ruta.mkdir(parents=True, exist_ok=True)

    return ruta


def ruta_archivo_startup():
    return ruta_inicio_windows() / f"{NOMBRE_ASISTENTE}.bat"

# =========================================================
# ACTIVAR
# FIX: lanza el asistente como administrador via PowerShell
#      así psutil puede cerrar procesos elevados directamente
# =========================================================

def activar_inicio_automatico():
    try:
        if getattr(sys, "frozen", False):
            ruta_exe   = Path(sys.executable).resolve()
            directorio = ruta_exe.parent
            comando    = str(ruta_exe)
            argumentos = ""
        else:
            ruta_python = Path(sys.executable).resolve()
            ruta_main   = Path(__file__).resolve().parent / "main.py"
            directorio  = ruta_main.parent
            comando     = str(ruta_python)
            argumentos  = f'"{ruta_main}"'

        # FIX: usar tarea programada en vez de .bat con RunAs
        # Las tareas programadas pueden correr como admin sin UAC
        nombre_tarea = "AsistenteIA"

        # FIX: antes se armaba un solo string `"exe" "main.py"` y se
        # le hacía .strip('"') a los EXTREMOS — eso solo quitaba la
        # comilla de apertura del exe y la de cierre del script,
        # dejando las dos comillas internas sueltas en medio
        # (...python.exe" "C:\...\main.py...), lo cual rompía el
        # comando que Task Scheduler intentaba ejecutar.
        # Ahora se usan los campos <Command> y <Arguments> por
        # separado, como espera el formato de Task Scheduler, sin
        # necesidad de armar y luego recortar comillas a mano.
        xml_tarea = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions>
    <Exec>
      <Command>{comando}</Command>
      <Arguments>{argumentos}</Arguments>
      <WorkingDirectory>{directorio}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

        # guardar xml temporal
        ruta_xml = Path(tempfile.gettempdir()) / "AsistenteIA_tarea.xml"
        ruta_xml.write_text(xml_tarea, encoding="utf-16")

        # registrar la tarea (requiere admin)
        # FIX: antes esto llamaba a schtasks DIRECTO sin importar si
        # el proceso actual tenía permisos de admin — si no los
        # tenía (el caso normal), fallaba con "Acceso denegado" en
        # silencio (solo visible en consola) y nunca se lograba
        # activar el inicio automático. Ahora, si no hay permisos de
        # admin, se ejecuta el mismo comando pero elevado vía UAC
        # (ver _ejecutar_elevado arriba) — el usuario ve el cuadro de
        # Windows, lo acepta, y listo, sin tener que reabrir todo el
        # asistente como administrador.
        argumentos_schtasks = ["/Create", "/TN", nombre_tarea, "/XML", str(ruta_xml), "/F"]

        if _es_admin():
            resultado = subprocess.run(
                ["schtasks", *argumentos_schtasks],
                capture_output=True,
                text=True
            )
            exito = resultado.returncode == 0
            if not exito:
                print("[Startup] Error:", resultado.stderr)
                # FIX/NUEVO: este es exactamente el caso de "Acceso
                # denegado" que antes no quedaba en ningún lado fuera
                # de la consola — registrar el stderr real de schtasks
                # (no solo "no se pudo") es justamente "el fallo y la
                # causa", útil para diagnosticar sin tener que pedirle
                # al usuario que vuelva a reproducirlo con la consola
                # abierta.
                log.error(f"schtasks /Create falló (corriendo ya como "
                          f"admin): {resultado.stderr.strip()}")
        else:
            print("[Startup] Se necesitan permisos de administrador — "
                  "debería aparecer un cuadro de Windows para confirmarlo.")
            exito = _ejecutar_elevado("schtasks", argumentos_schtasks)
            if not exito:
                print("[Startup] No se completó la elevación (¿se rechazó "
                      "el cuadro de Windows, o tardó más de lo esperado?)")
                log.error("No se pudo crear la tarea programada de inicio "
                          "automático: la elevación por UAC no se completó "
                          "(rechazada, o tardó más de lo esperado)")

        ruta_xml.unlink(missing_ok=True)

        if exito:
            print(f"[Startup] Tarea programada creada: {nombre_tarea}")
            return True
        else:
            return False

    except Exception as e:
        print("Error activando startup:", e)
        log.exception("Error activando el inicio automático")
        return False

# =========================================================
# DESACTIVAR
# =========================================================

def desactivar_inicio_automatico():
    try:
        # FIX: misma razón que en activar_inicio_automatico() — borrar
        # una tarea registrada con privilegios elevados también puede
        # requerir permisos de admin. Si no los hay, se eleva igual
        # vía UAC en vez de fallar en silencio.
        argumentos = ["/Delete", "/TN", "AsistenteIA", "/F"]

        if _es_admin():
            subprocess.run(["schtasks", *argumentos], capture_output=True)
        else:
            _ejecutar_elevado("schtasks", argumentos)

        print("[Startup] Tarea programada eliminada")
        return True
    except Exception as e:
        print("Error desactivando startup:", e)
        log.exception("Error desactivando el inicio automático")
        return False

# =========================================================
# ESTADO
# FIX: activar_inicio_automatico() crea una tarea programada
# (schtasks), no el .bat de la carpeta Startup. Revisar el .bat
# aquí siempre devolvía False aunque el inicio automático
# estuviera activo. Ahora se consulta la tarea programada real.
# =========================================================

def startup_activado():
    resultado = subprocess.run(
        ["schtasks", "/Query", "/TN", "AsistenteIA"],
        capture_output=True
    )
    return resultado.returncode == 0