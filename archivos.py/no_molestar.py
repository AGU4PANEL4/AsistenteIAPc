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

# NUEVO: refleja el estado en el indicador de la UI (ver ui.py,
# _dibujar_orbe) — import directo y a nivel de módulo porque
# ui_estado.py no tiene dependencias pesadas (solo threading/datetime,
# nada de Tkinter en sí), así que no hay riesgo de import circular ni
# de arrastrar la UI completa solo por importar esto.
from ui_estado import set_no_molestar as _set_no_molestar_ui

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

    FIX: a esta función le faltaba `global _activo_hasta` — como más
    abajo SÍ hay una asignación a esa variable (`_activo_hasta = None`
    en la limpieza de estado), Python trata `_activo_hasta` como
    LOCAL en TODA la función por esa sola asignación, incluida la
    lectura de la primera línea del while, que ocurre ANTES en el
    código pero no en el análisis de scope de Python (que es por
    función completa, no línea por línea). Resultado: el hilo se
    caía con UnboundLocalError casi apenas arrancaba, en la primera
    vuelta del while — silenciosamente, porque las excepciones de un
    hilo daemon no tumban el programa, solo imprimen un traceback en
    stderr que fácilmente pasa desapercibido en la consola.
    
    Esto significaba que la expiración automática de no molestar
    JAMÁS funcionaba de verdad — ni el aviso hablado "el modo no
    molestar terminó", ni la reproducción automática de los avisos
    diferidos al cumplirse el tiempo. Solo funcionaba si alguien
    llamaba a desactivar() a mano (esa función sí tiene su propio
    `global _activo_hasta` correcto). Con la wake word normal esto
    pasaba menos desapercibido (uno nota si el asistente no avisó
    algo en un rato), pero con el modo dormido (ver main.py) el
    problema se agravaba: si te quedabas dormido de verdad y no
    decías "despierta", los avisos acumulados durante el no molestar
    de 12 horas iban a quedar esperando para siempre.
    """
    global _activo_hasta

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

    _set_no_molestar_ui(False)

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

    _set_no_molestar_ui(True)

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

    _set_no_molestar_ui(False)

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