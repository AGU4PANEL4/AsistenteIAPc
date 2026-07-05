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
}

_estado = {
    "modo":        "inactivo",   # clave de ESTADOS
    "wake_word":   "jarvis",
    "motor_ia":    "—",          # "Groq" | "Ollama" | "—"
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