"""
Gestión de ventanas para Linux — equivalente de win32gui/win32con/
win32process (usados en acciones_apps.py en Windows), pero para X11
(y XWayland, la capa de compatibilidad que la mayoría de sesiones
Wayland usan automáticamente para apps que no hablan Wayland nativo
— Tkinter, y por lo tanto cualquier ventana de este mismo asistente,
es una de esas apps).

En vez de escribir bindings crudos de Xlib (mucho más código, mucho
más frágil ante distintas configuraciones), se usan dos utilidades
de línea de comandos ESTÁNDAR en el ecosistema Linux/X11:

  - wmctrl: listar ventanas (con su PID y título), activarlas,
    cerrarlas (vía el mensaje EWMH _NET_CLOSE_WINDOW — el mismo tipo
    de "pedido amable de cierre" que WM_CLOSE en Windows).
  - xdotool: acciones que wmctrl no cubre bien (minimizar
    específicamente, activar con foco real).

Ambas son paquetes estándar en los repositorios de cualquier distro
mayor (apt install wmctrl xdotool / dnf install wmctrl xdotool /
pacman -S wmctrl xdotool) — no vienen preinstaladas por defecto en
todas las distros, así que cada función acá reporta con claridad si
la herramienta no está disponible, en vez de fallar en silencio.

LIMITACIÓN CONOCIDA: esto funciona sobre X11 (nativo, o XWayland). En
una sesión Wayland PURA, sin XWayland, wmctrl/xdotool no ven nada —
Wayland restringe a propósito que una app cualquiera enumere/controle
ventanas de OTRAS apps, por diseño de seguridad, y no hay un
reemplazo estándar y universal para este caso todavía. En la práctica
esto rara vez es un problema porque casi todas las distros de
escritorio mantienen XWayland activo por compatibilidad.
"""

import shutil
import subprocess

from logger import log

_AVISADO_SIN_WMCTRL  = False
_AVISADO_SIN_XDOTOOL = False


def _wmctrl_disponible():
    global _AVISADO_SIN_WMCTRL
    if shutil.which("wmctrl"):
        return True
    if not _AVISADO_SIN_WMCTRL:
        print("[Ventanas] 'wmctrl' no está instalado — la gestión de "
              "ventanas (enfocar, cerrar, minimizar por título) no va "
              "a funcionar. Instalalo con el gestor de paquetes de tu "
              "distro (ej. 'sudo apt install wmctrl').")
        log.warning("wmctrl no disponible — gestión de ventanas Linux deshabilitada")
        _AVISADO_SIN_WMCTRL = True
    return False


def _xdotool_disponible():
    global _AVISADO_SIN_XDOTOOL
    if shutil.which("xdotool"):
        return True
    if not _AVISADO_SIN_XDOTOOL:
        print("[Ventanas] 'xdotool' no está instalado — minimizar/activar "
              "ventanas específicas no va a funcionar del todo. "
              "Instalalo con el gestor de paquetes de tu distro "
              "(ej. 'sudo apt install xdotool').")
        log.warning("xdotool no disponible — algunas acciones de ventana Linux deshabilitadas")
        _AVISADO_SIN_XDOTOOL = True
    return False


def listar_ventanas():
    """
    Devuelve una lista de (id_ventana, pid, titulo) para cada ventana
    visible en este momento — vía "wmctrl -lp". id_ventana es el
    identificador hexadecimal que wmctrl/xdotool esperan para
    referirse a esa ventana en cualquier otra llamada.

    Lista vacía si wmctrl no está disponible, o si algo falla — nunca
    lanza una excepción hacia quien llama.
    """
    if not _wmctrl_disponible():
        return []

    try:
        resultado = subprocess.run(
            ["wmctrl", "-lp"], capture_output=True, text=True, timeout=5
        )
    except Exception:
        log.exception("Error listando ventanas con wmctrl")
        return []

    ventanas = []
    for linea in resultado.stdout.splitlines():
        # formato: <id_ventana> <desktop> <pid> <host> <título...>
        partes = linea.split(None, 4)
        if len(partes) < 5:
            continue
        id_ventana, _desktop, pid_str, _host, titulo = partes
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        ventanas.append((id_ventana, pid, titulo))

    return ventanas


def pids_con_ventana_visible():
    """Devuelve el set de PIDs que tienen al menos una ventana listada
    por wmctrl en este momento — equivalente al filtro
    win32gui.IsWindowVisible() del lado Windows."""
    return {pid for _id, pid, _titulo in listar_ventanas()}


def ventanas_de_pid(pid):
    """Lista de id_ventana (strings) que pertenecen a ese PID."""
    return [id_ventana for id_ventana, p, _t in listar_ventanas() if p == pid]


def activar_ventana(id_ventana):
    """
    Trae la ventana al frente y le da foco — equivalente a
    IsIconic()+ShowWindow(SW_RESTORE)+SetForegroundWindow() del lado
    Windows. "wmctrl -a" ya des-minimiza y activa en un solo paso.
    """
    if not _wmctrl_disponible():
        return False
    try:
        resultado = subprocess.run(
            ["wmctrl", "-i", "-a", id_ventana], capture_output=True, timeout=5
        )
        return resultado.returncode == 0
    except Exception:
        log.exception(f"Error activando ventana {id_ventana}")
        return False


def minimizar_ventana(id_ventana):
    """
    wmctrl no tiene una acción directa de "minimizar" — xdotool sí
    (windowminimize). Se usa xdotool acá específicamente por eso.
    """
    if not _xdotool_disponible():
        return False
    try:
        resultado = subprocess.run(
            ["xdotool", "windowminimize", id_ventana], capture_output=True, timeout=5
        )
        return resultado.returncode == 0
    except Exception:
        log.exception(f"Error minimizando ventana {id_ventana}")
        return False


def cerrar_ventana(id_ventana):
    """
    Pide a la ventana que se cierre "amablemente" — "wmctrl -c" manda
    el mensaje EWMH _NET_CLOSE_WINDOW, el equivalente en X11 de
    WM_CLOSE en Windows: la app recibe el pedido y puede reaccionar
    (preguntar "¿guardar cambios?", etc.) en vez de morir en seco.
    """
    if not _wmctrl_disponible():
        return False
    try:
        resultado = subprocess.run(
            ["wmctrl", "-i", "-c", id_ventana], capture_output=True, timeout=5
        )
        return resultado.returncode == 0
    except Exception:
        log.exception(f"Error cerrando ventana {id_ventana}")
        return False


def traer_al_frente_por_nombre(predicado_nombre):
    """
    Busca, entre todas las ventanas visibles, la primera cuyo PID
    pertenezca a un proceso que matchee `predicado_nombre` (función
    que recibe el nombre normalizado del proceso y devuelve
    True/False) y la activa.

    `predicado_nombre` se pasa como función (en vez de un string a
    comparar acá mismo) para que quien llama decida el criterio
    exacto de coincidencia (substring en cualquier dirección, etc.)
    sin duplicar esa lógica acá — ver el uso real en
    acciones_apps._traer_al_frente_linux.

    Devuelve True si encontró y activó alguna, False si no.
    """
    import psutil

    for id_ventana, pid, _titulo in listar_ventanas():
        try:
            proc = psutil.Process(pid)
            if predicado_nombre(proc.name()):
                return activar_ventana(id_ventana)
        except Exception:
            continue

    return False