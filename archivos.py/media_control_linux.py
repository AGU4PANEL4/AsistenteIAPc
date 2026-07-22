"""
Control de medios y volumen para Linux — equivalente de
media_control.py (que usa SMTC/pycaw/win32gui, todo específico de
Windows).

REPRODUCCIÓN (pausar/reanudar/siguiente/anterior): vía "playerctl",
la herramienta estándar de facto en el ecosistema Linux para esto —
construida sobre MPRIS2, el estándar abierto de freedesktop.org que
Spotify, VLC, mpv, Firefox, Chromium (y prácticamente cualquier
reproductor moderno en Linux) implementan. Es el equivalente
conceptual más directo a SMTC en Windows: no hace falta saber qué
app está sonando, MPRIS ya expone una interfaz uniforme para
cualquiera que la soporte.

VOLUMEN (sistema y por app): vía "pactl", la herramienta de control
de PulseAudio -- que también controla PipeWire a través de la capa
de compatibilidad pipewire-pulse (la que usan por defecto Fedora,
Ubuntu reciente, y la mayoría de distros que migraron a PipeWire), así
que el mismo comando sirve sin importar cuál de los dos esté
corriendo. Es el equivalente de pycaw/Core Audio del lado Windows.

Ninguna de las dos herramientas viene preinstalada en TODAS las
distros (aunque son comunes en instalaciones de escritorio) -- cada
función acá avisa con claridad si falta, en vez de fallar en
silencio o simular que funcionó.
"""

import re
import shutil
import subprocess

from logger import log

_AVISADO_SIN_PLAYERCTL = False
_AVISADO_SIN_PACTL     = False


def _playerctl_disponible():
    global _AVISADO_SIN_PLAYERCTL
    if shutil.which("playerctl"):
        return True
    if not _AVISADO_SIN_PLAYERCTL:
        print("[Media] 'playerctl' no está instalado — el control de "
              "reproducción (pausar/siguiente/anterior) no va a "
              "funcionar. Instalalo con tu gestor de paquetes (ej. "
              "'sudo apt install playerctl').")
        log.warning("playerctl no disponible — control de reproducción Linux deshabilitado")
        _AVISADO_SIN_PLAYERCTL = True
    return False


def _pactl_disponible():
    global _AVISADO_SIN_PACTL
    if shutil.which("pactl"):
        return True
    if not _AVISADO_SIN_PACTL:
        print("[Media] 'pactl' no está instalado — el control de "
              "volumen no va a funcionar. Viene con PulseAudio o con "
              "PipeWire (paquete pipewire-pulse), presentes por "
              "defecto en casi cualquier distro de escritorio moderna.")
        log.warning("pactl no disponible — control de volumen Linux deshabilitado")
        _AVISADO_SIN_PACTL = True
    return False


# =========================================================
# REPRODUCCIÓN — playerctl (MPRIS)
# =========================================================

def _listar_players():
    """Nombres de los reproductores MPRIS activos ahora mismo (ej.
    ['spotify', 'firefox']), o [] si no hay ninguno / playerctl no
    está disponible."""
    if not _playerctl_disponible():
        return []
    try:
        resultado = subprocess.run(
            ["playerctl", "-l"], capture_output=True, text=True, timeout=5
        )
        if resultado.returncode != 0:
            return []
        return [p.strip() for p in resultado.stdout.splitlines() if p.strip()]
    except Exception:
        log.exception("Error listando reproductores MPRIS")
        return []


def _resolver_player_objetivo(nombre_app):
    """
    Igual que _resolver_app_objetivo() del lado Windows: si se nombró
    una app explícita y no se encuentra su reproductor MPRIS, se
    devuelve None a propósito -- para que quien llama NO controle
    "lo que sea que esté sonando" como si fuera la app pedida (mismo
    principio de honestidad que ya documenta media_control.py: mejor
    fallar y decirlo, que controlar la app equivocada).
    """
    players = _listar_players()
    for p in players:
        if nombre_app in p.lower() or p.lower() in nombre_app:
            return p
    return None


def _extraer_app_de_valor(valor):
    if not valor or valor.strip().lower() in ("media", ""):
        return None
    return valor.strip().lower()


_ACCION_A_SUBCOMANDO = {
    "play_pause": "play-pause",
    "next":       "next",
    "prev":       "previous",
}

_ACCION_A_TECLA_XF86 = {
    "play_pause": "XF86AudioPlay",
    "next":       "XF86AudioNext",
    "prev":       "XF86AudioPrev",
}


def _tecla_multimedia_fallback(accion):
    """
    Último recurso si playerctl no está instalado o no encontró
    ningún reproductor -- manda la tecla multimedia XF86 global vía
    xdotool (equivalente conceptual al SendInput de VK_MEDIA_* del
    lado Windows). "A ciegas" en el mismo sentido que el fallback de
    Windows: no se sabe qué app la va a recibir, así que solo se usa
    cuando no se pidió una app explícita.
    """
    tecla = _ACCION_A_TECLA_XF86.get(accion)
    if not tecla or not shutil.which("xdotool"):
        return False
    try:
        resultado = subprocess.run(
            ["xdotool", "key", tecla], capture_output=True, timeout=5
        )
        return resultado.returncode == 0
    except Exception:
        log.exception(f"Error mandando tecla multimedia {tecla}")
        return False


def _control_reproduccion(accion, valor=None):
    app = _extraer_app_de_valor(valor)
    sub = _ACCION_A_SUBCOMANDO.get(accion)

    if app:
        # app explícita: si no se encuentra su reproductor, se falla
        # limpio en vez de controlar cualquier otro que esté sonando.
        if not _playerctl_disponible():
            return False
        player = _resolver_player_objetivo(app)
        if not player:
            return False
        try:
            resultado = subprocess.run(
                ["playerctl", "-p", player, sub], capture_output=True, timeout=5
            )
            return resultado.returncode == 0
        except Exception:
            log.exception(f"Error ejecutando playerctl -p {player} {sub}")
            return False

    # sin app explícita: dejar que playerctl controle el que considere
    # "activo" (su propio criterio, análogo a "lo que esté sonando")
    if _playerctl_disponible():
        try:
            resultado = subprocess.run(
                ["playerctl", sub], capture_output=True, timeout=5
            )
            if resultado.returncode == 0:
                return True
        except Exception:
            log.exception(f"Error ejecutando playerctl {sub}")

    # ni playerctl encontró nada -- tecla multimedia global como
    # último recurso, igual que el fallback final del lado Windows
    return _tecla_multimedia_fallback(accion)


def media_pausa_reanuda(valor=None):
    return _control_reproduccion("play_pause", valor)


def media_siguiente(valor=None):
    return _control_reproduccion("next", valor)


def media_anterior(valor=None):
    return _control_reproduccion("prev", valor)


# =========================================================
# VOLUMEN — pactl (PulseAudio / PipeWire)
# =========================================================

def _set_volumen_sistema(porcentaje):
    if not _pactl_disponible():
        return False
    try:
        porcentaje = max(0, min(100, int(porcentaje)))
        resultado = subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{porcentaje}%"],
            capture_output=True, timeout=5,
        )
        return resultado.returncode == 0
    except Exception:
        log.exception("Error seteando volumen del sistema (Linux)")
        return False


def _listar_sink_inputs():
    """
    Lista de (indice, nombre_app) para cada stream de audio individual
    activo ahora mismo -- el equivalente Linux de
    AudioUtilities.GetAllSessions() (pycaw) del lado Windows.
    """
    if not _pactl_disponible():
        return []

    try:
        resultado = subprocess.run(
            ["pactl", "list", "sink-inputs"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        log.exception("Error listando sink-inputs")
        return []

    entradas      = {}   # indice -> nombre (application.name tiene prioridad)
    indice_actual = None

    for linea in resultado.stdout.splitlines():
        m_indice = re.match(r"Sink Input #(\d+)", linea)
        if m_indice:
            indice_actual = int(m_indice.group(1))
            continue

        if indice_actual is None:
            continue

        linea_limpia = linea.strip()

        if linea_limpia.startswith("application.name"):
            m_nombre = re.search(r'=\s*"([^"]*)"', linea_limpia)
            if m_nombre:
                entradas[indice_actual] = m_nombre.group(1).lower()
        elif linea_limpia.startswith("media.name") and indice_actual not in entradas:
            # solo se usa como respaldo si esta sink input no tenía
            # application.name — algunos streams (ej. sonidos del
            # sistema) a veces solo traen media.name.
            m_nombre = re.search(r'=\s*"([^"]*)"', linea_limpia)
            if m_nombre:
                entradas[indice_actual] = m_nombre.group(1).lower()

    return list(entradas.items())


def _set_volumen_app(nombre_app, porcentaje):
    porcentaje = max(0, min(100, int(porcentaje)))
    nombre_app = nombre_app.lower()

    cambiados = 0
    for indice, nombre_stream in _listar_sink_inputs():
        if nombre_app in nombre_stream or nombre_stream in nombre_app:
            try:
                resultado = subprocess.run(
                    ["pactl", "set-sink-input-volume", str(indice), f"{porcentaje}%"],
                    capture_output=True, timeout=5,
                )
                if resultado.returncode == 0:
                    cambiados += 1
            except Exception:
                log.exception(f"Error seteando volumen de sink-input {indice}")

    return cambiados > 0


def media_subir_volumen(valor=None):
    if not _pactl_disponible():
        return False
    try:
        resultado = subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"],
            capture_output=True, timeout=5,
        )
        return resultado.returncode == 0
    except Exception:
        log.exception("Error subiendo volumen (Linux)")
        return False


def media_bajar_volumen(valor=None):
    if not _pactl_disponible():
        return False
    try:
        resultado = subprocess.run(
            ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"],
            capture_output=True, timeout=5,
        )
        return resultado.returncode == 0
    except Exception:
        log.exception("Error bajando volumen (Linux)")
        return False


def media_silenciar(valor=None):
    if not _pactl_disponible():
        return False
    try:
        resultado = subprocess.run(
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"],
            capture_output=True, timeout=5,
        )
        return resultado.returncode == 0
    except Exception:
        log.exception("Error alternando silencio (Linux)")
        return False


def media_volumen_exacto(valor=None):
    """
    Mismo formato de valor y mismo contrato de retorno que la versión
    Windows en media_control.py: (éxito, mensaje) -- valor puede ser
    "50", "spotify 50", o "50 spotify".
    """
    if not valor:
        return False, None

    valor_str = str(valor).strip().lower()

    numeros = re.findall(r"\d+", valor_str)
    if not numeros:
        return False, None

    porcentaje = int(numeros[0])

    nombre_app = re.sub(r"\d+", "", valor_str)
    nombre_app = re.sub(r"[^a-z\s]", "", nombre_app).strip()

    if nombre_app:
        from aliases import traducir_alias
        nombre_app = traducir_alias(nombre_app)

        if _set_volumen_app(nombre_app, porcentaje):
            return True, f"Volumen de {nombre_app} al {porcentaje} por ciento"

        print(f"[VOLUMEN] '{nombre_app}' no encontrada entre los streams de audio activos, ajustando sistema")

    if _set_volumen_sistema(porcentaje):
        return True, f"Volumen al {porcentaje} por ciento"

    return False, None