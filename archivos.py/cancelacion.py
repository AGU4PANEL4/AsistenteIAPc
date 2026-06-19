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
        except:
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
    """Llama esto cuando la operación larga termina."""
    global _activo
    _activo            = False
    sesion["cancelar"] = False


def fue_cancelado():
    """Verifica si el usuario pidió cancelar."""
    return sesion.get("cancelar", False)