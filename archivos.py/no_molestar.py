"""
Modo "no molestar" — silencia los avisos de recordatorios y
temporizadores por un tiempo determinado, sin cancelarlos.

Cuando el modo termina (o cuando el usuario lo desactiva antes),
los avisos que se acumularon mientras estaba activo se reproducen
todos de una vez, para que no se pierda ninguno.

Uso desde otros módulos:
    from no_molestar import modo_activo, registrar_aviso_diferido

    if modo_activo():
        registrar_aviso_diferido("Recordatorio: la pizza")
    else:
        hablar("Recordatorio: la pizza")
"""

import threading
import time
from datetime import datetime, timedelta

from logger import log

# =========================================================
# ESTADO
# =========================================================

_lock           = threading.Lock()
_activo_hasta   = None   # datetime hasta cuando está activo, o None
_avisos_diferidos = []   # mensajes acumulados mientras estuvo activo
_hilo_expiracion  = None


def modo_activo():
    """True si el modo no molestar está activo en este momento."""
    with _lock:
        if _activo_hasta is None:
            return False
        if datetime.now() >= _activo_hasta:
            # expiró — limpiar silenciosamente (el hilo de expiración
            # ya se encargará de reproducir los avisos)
            return False
        return True


def tiempo_restante():
    """
    Devuelve los minutos restantes del modo no molestar,
    o 0 si no está activo.
    """
    with _lock:
        if _activo_hasta is None or datetime.now() >= _activo_hasta:
            return 0
        restante = (_activo_hasta - datetime.now()).total_seconds()
        return max(0, int(restante // 60))


def registrar_aviso_diferido(mensaje):
    """
    Guarda un aviso para reproducirlo cuando termine el modo.
    Llamar en vez de hablar() cuando modo_activo() es True.
    """
    with _lock:
        _avisos_diferidos.append(mensaje)
    print(f"[No molestar] Aviso diferido: '{mensaje}'")
    log.info(f"Aviso diferido por modo no molestar: '{mensaje}'")


def _reproducir_diferidos():
    """Reproduce todos los avisos acumulados, si hay alguno."""
    with _lock:
        avisos = list(_avisos_diferidos)
        _avisos_diferidos.clear()

    if not avisos:
        return

    from tts import hablar

    if len(avisos) == 1:
        hablar(f"Mientras estabas ocupado: {avisos[0]}")
    else:
        hablar(f"Mientras estabas ocupado tuviste {len(avisos)} avisos:")
        for aviso in avisos:
            hablar(aviso)


def _hilo_esperar_expiracion(hasta):
    """
    Duerme hasta que el modo expira y luego reproduce los diferidos.
    Duerme en tramos de 30s para no quedar bloqueado si el modo se
    desactiva manualmente antes de tiempo.
    """
    while True:
        with _lock:
            # si el estado cambió (desactivado manualmente o nueva
            # activación con distinto hasta), este hilo ya no aplica
            if _activo_hasta != hasta:
                return

        restante = (hasta - datetime.now()).total_seconds()

        if restante <= 0:
            break

        time.sleep(min(restante, 30))

    # verificar una vez más que no fue reemplazado
    with _lock:
        if _activo_hasta != hasta:
            return
        _activo_hasta_ref = _activo_hasta

    # limpiar estado y reproducir diferidos
    with _lock:
        if _activo_hasta == _activo_hasta_ref:
            _activo_hasta = None

    print("[No molestar] Modo terminado, reproduciendo avisos diferidos...")
    from tts import hablar
    hablar("El modo no molestar terminó.")
    _reproducir_diferidos()


# =========================================================
# ACTIVAR / DESACTIVAR
# =========================================================

def activar(minutos):
    """
    Activa el modo no molestar por `minutos` minutos.
    Si ya estaba activo, lo extiende al nuevo tiempo.
    """
    global _activo_hasta, _hilo_expiracion

    hasta = datetime.now() + timedelta(minutes=minutos)

    with _lock:
        _activo_hasta = hasta

    # lanzar hilo de expiración — si ya había uno corriendo, se
    # detiene solo cuando note que _activo_hasta cambió
    _hilo_expiracion = threading.Thread(
        target=_hilo_esperar_expiracion,
        args=(hasta,),
        daemon=True,
    )
    _hilo_expiracion.start()

    print(f"[No molestar] Activado por {minutos} minutos (hasta {hasta.strftime('%H:%M')})")
    log.info(f"Modo no molestar activado por {minutos} minutos")

    return True, f"Modo no molestar activado por {minutos} minutos"


def desactivar():
    """
    Desactiva el modo no molestar antes de tiempo y reproduce
    inmediatamente los avisos acumulados.
    """
    global _activo_hasta

    with _lock:
        estaba_activo = _activo_hasta is not None
        _activo_hasta = None

    if not estaba_activo:
        return False, "El modo no molestar no estaba activo"

    print("[No molestar] Desactivado manualmente")
    log.info("Modo no molestar desactivado manualmente")

    _reproducir_diferidos()
    return True, "Modo no molestar desactivado"


def estado():
    """Devuelve (éxito, mensaje) con el estado actual."""
    if not modo_activo():
        return True, "El modo no molestar no está activo"

    mins = tiempo_restante()
    with _lock:
        n_diferidos = len(_avisos_diferidos)

    msg = f"El modo no molestar está activo, quedan {mins} minuto{'s' if mins != 1 else ''}"
    if n_diferidos:
        msg += f" y tenés {n_diferidos} aviso{'s' if n_diferidos != 1 else ''} pendiente{'s' if n_diferidos != 1 else ''}"
    return True, msg