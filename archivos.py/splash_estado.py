"""
Estado compartido entre main.py (que va actualizando el texto según
la etapa de arranque en la que está) y splash.py (que lo muestra y
lo lee por polling). Mismo patrón thread-safe que ui_estado.py —
main.py escribe, splash.py lee desde su propio hilo con after().
"""

import threading

_lock = threading.Lock()

_estado = {
    "texto":  "Iniciando...",
    "cerrar": False,
}


def set_estado(texto):
    """Actualiza el texto de estado mostrado en el splash."""
    with _lock:
        _estado["texto"] = texto


def pedir_cierre():
    """
    Marca que el splash debe cerrarse. No destruye la ventana
    directamente — tkinter no es thread-safe entre hilos, así que
    solo se deja la bandera para que el propio hilo del splash la
    revise en su próximo tick y se destruya a sí mismo.
    """
    with _lock:
        _estado["cerrar"] = True


def reset():
    """Vuelve al estado inicial — llamar antes de mostrar_splash()."""
    with _lock:
        _estado["texto"]  = "Iniciando..."
        _estado["cerrar"] = False


def get_estado():
    with _lock:
        return dict(_estado)