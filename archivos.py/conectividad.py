"""
Detección simple de conectividad a internet, usada por ia.py para
decidir si usar la API en la nube (Groq) o el modelo local (Ollama).

NUEVO: parte del modo híbrido de IA — con internet se usa Groq (sin
consumir GPU local en absoluto, ver gestor_ollama.py), y sin internet
se cae a Ollama local como respaldo, igual que siempre funcionó.
"""

import socket
import time
from logger import log

# =========================================================
# CACHÉ DEL RESULTADO
# Chequear conectividad en CADA comando sería un costo innecesario
# (aunque el chequeo en sí es rápido, sumaría latencia a cada turno
# de conversación). Se cachea el resultado por unos segundos — lo
# suficiente para no chequear de más, pero corto para notar rápido
# si el internet se cortó o volvió.
# =========================================================

_DURACION_CACHE = 5  # segundos

_ultimo_resultado  = None
_ultimo_chequeo     = 0


def hay_internet(forzar=False):
    """
    Devuelve True/False según haya conectividad a internet en este
    momento. Usa un chequeo liviano (conexión TCP corta a un DNS
    público, sin descargar nada) con caché de unos segundos.

    forzar=True ignora el caché y chequea de nuevo ahora mismo —
    útil justo antes de decidir si encender/apagar Ollama, donde
    vale la pena pagar el costo de un chequeo fresco.
    """
    global _ultimo_resultado, _ultimo_chequeo

    ahora = time.time()

    if not forzar and _ultimo_resultado is not None:
        if ahora - _ultimo_chequeo < _DURACION_CACHE:
            return _ultimo_resultado

    resultado = _chequear_conexion()

    _ultimo_resultado = resultado
    _ultimo_chequeo    = ahora

    return resultado


def _chequear_conexion(timeout=1.5):
    """
    Intenta una conexión TCP corta a DNS públicos (Cloudflare y
    Google) en el puerto 53 — no descarga nada, solo confirma que
    se puede establecer una conexión de red real. Se prueban ambos
    servidores EN PARALELO (no uno tras otro) para que, si no hay
    internet, el chequeo completo tarde como máximo `timeout`
    segundos en vez de timeout*2 — importante porque este chequeo
    ocurre antes de cada decisión de qué motor de IA usar, y no
    queremos que la ausencia de internet se sienta más lenta que
    tenerlo.
    """
    import concurrent.futures

    servidores = [("1.1.1.1", 53), ("8.8.8.8", 53)]

    def _probar(servidor):
        try:
            socket.create_connection(servidor, timeout=timeout)
            return True
        except OSError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futuros = [executor.submit(_probar, s) for s in servidores]
        for futuro in concurrent.futures.as_completed(futuros, timeout=timeout + 0.5):
            try:
                if futuro.result():
                    return True
            except Exception:
                pass

    log.info("Sin conectividad a internet detectada")
    return False