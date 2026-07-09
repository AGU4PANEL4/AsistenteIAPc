"""
Estado compartido entre el loop principal del asistente (main.py)
y la interfaz gráfica (ui.py). Thread-safe — ambos lados leen y
escriben desde hilos distintos.

main.py escribe → ui.py lee (polling con after())
"""

import threading
from datetime import datetime

_lock = threading.Lock()

# =========================================================
# ESTADO ACTUAL
# =========================================================

ESTADOS = {
    "inactivo":    "Inactivo",
    "escuchando":  "Escuchando...",
    "procesando":  "Procesando...",
    "hablando":    "Hablando...",
    "buscando":    "Buscando app...",
    "dormido":     "Durmiendo...",
}

_estado = {
    "modo":        "inactivo",   # clave de ESTADOS
    "wake_word":   "jarvis",
    "motor_ia":    "—",          # "Groq" | "Ollama" | "—"
    # NUEVO: a diferencia de "modo" (mutuamente excluyente — el
    # asistente está escuchando O hablando O procesando, nunca dos a
    # la vez), no_molestar es una bandera INDEPENDIENTE: puede estar
    # activa al mismo tiempo que cualquier modo (ej. escuchando un
    # comando CON no molestar activo de fondo). Por eso se guarda
    # aparte en vez de como un valor más de "modo" — ui.py la dibuja
    # como un indicador superpuesto, no como una animación excluyente
    # del orbe. Ver no_molestar.py (activar/desactivar) para quién la
    # actualiza.
    "no_molestar": False,
}

_historial    = []   # lista de {"cmd": ..., "resp": ..., "ts": ...}
HISTORIAL_MAX = 12


# =========================================================
# LECTURA / ESCRITURA DE ESTADO
# =========================================================

def set_modo(modo):
    """Actualiza el estado actual del asistente."""
    with _lock:
        _estado["modo"] = modo


def get_estado():
    with _lock:
        return dict(_estado)


def set_motor_ia(motor):
    """'Groq' | 'Ollama' | '—'"""
    with _lock:
        _estado["motor_ia"] = motor


def set_wake_word(ww):
    with _lock:
        _estado["wake_word"] = ww


def set_no_molestar(activo):
    """Actualiza el indicador de no molestar mostrado en la UI —
    llamar desde no_molestar.py cada vez que se activa, desactiva, o
    expira por su cuenta."""
    with _lock:
        _estado["no_molestar"] = bool(activo)


# =========================================================
# HISTORIAL
# =========================================================

def agregar_historial(comando, respuesta=""):
    """Agrega una entrada al historial de comandos."""
    with _lock:
        _historial.insert(0, {
            "cmd":  comando,
            "resp": respuesta,
            "ts":   datetime.now().strftime("%H:%M"),
        })
        del _historial[HISTORIAL_MAX:]


def get_historial():
    with _lock:
        return list(_historial)