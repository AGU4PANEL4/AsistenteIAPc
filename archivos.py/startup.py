import os
import sys
import subprocess
import tempfile
from pathlib import Path

NOMBRE_ASISTENTE = "AsistenteIA"

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

        # registrar la tarea (requiere admin UNA sola vez)
        resultado = subprocess.run(
            ["schtasks", "/Create", "/TN", nombre_tarea,
             "/XML", str(ruta_xml), "/F"],
            capture_output=True,
            text=True
        )

        ruta_xml.unlink(missing_ok=True)

        if resultado.returncode == 0:
            print(f"[Startup] Tarea programada creada: {nombre_tarea}")
            return True
        else:
            print("[Startup] Error:", resultado.stderr)
            return False

    except Exception as e:
        print("Error activando startup:", e)
        return False

# =========================================================
# DESACTIVAR
# =========================================================

def desactivar_inicio_automatico():
    try:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", "AsistenteIA", "/F"],
            capture_output=True
        )
        print("[Startup] Tarea programada eliminada")
        return True
    except Exception as e:
        print("Error desactivando startup:", e)
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