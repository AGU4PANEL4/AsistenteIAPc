import threading
import time
from session import sesion, es_cancelacion

# =========================================================
# HILO DE CANCELACIÓN
# Escucha en paralelo mientras el hilo principal trabaja.
# Si detecta una palabra de cancelación, pone
# sesion["cancelar"] = True y el hilo principal lo verifica.
# =========================================================

_hilo_cancelacion = None
_activo           = False

def _loop_cancelacion():
    from voice import escuchar_rapido
    global _activo

    while _activo:
        try:
            texto = escuchar_rapido(timeout=2, phrase_time_limit=3)
            if texto and es_cancelacion(texto):
                print(f"[Cancelación] Detectado: '{texto}'")
                sesion["cancelar"] = True
        except Exception:
            pass

def iniciar_cancelacion():
    """Llama esto antes de una operación larga."""
    global _hilo_cancelacion, _activo

    sesion["cancelar"] = False
    _activo            = True

    _hilo_cancelacion = threading.Thread(
        target=_loop_cancelacion,
        daemon=True
    )
    _hilo_cancelacion.start()


def detener_cancelacion():
    """
    Llama esto cuando la operación larga termina.

    FIX: antes esto solo ponía _activo = False y retornaba de
    inmediato. Pero el hilo de cancelación puede estar en ese
    momento bloqueado DENTRO de escuchar_rapido() (que abre
    sr.Microphone() y espera hasta ~2-3s), y solo revisa la
    bandera _activo cuando esa llamada termina. Eso dejaba una
    ventana de hasta ~3 segundos donde, después de "detener" la
    cancelación, el hilo principal podía intentar usar el
    micrófono (por ejemplo confirmar_apertura() en acciones.py,
    justo después de abrir_app()) mientras el hilo de cancelación
    todavía tenía el micrófono abierto — dos hilos usando
    sr.Microphone() al mismo tiempo, lo cual puede fallar según
    el backend de audio (y el error quedaba silenciado por el
    try/except de _loop_cancelacion, así que ni se notaba la
    causa).

    Ahora se espera (join) a que el hilo realmente termine antes
    de devolver el control, así cuando detener_cancelacion()
    regresa, el micrófono ya está libre con certeza. El timeout
    del join es un poco mayor al timeout interno de
    escuchar_rapido() para darle margen a terminar solo, nunca
    para forzar nada.
    """
    global _activo, _hilo_cancelacion

    _activo            = False
    sesion["cancelar"] = False

    if _hilo_cancelacion is not None and _hilo_cancelacion.is_alive():
        _hilo_cancelacion.join(timeout=4)

    _hilo_cancelacion = None


def fue_cancelado():
    """Verifica si el usuario pidió cancelar."""
    return sesion.get("cancelar", False)