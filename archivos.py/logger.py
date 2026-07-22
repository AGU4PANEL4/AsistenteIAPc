"""
Logging persistente del asistente.

FIX/NUEVO: hasta ahora, todo el diagnóstico del proyecto vivía
exclusivamente en print() — útil mientras se está mirando la consola
en vivo, pero se pierde por completo si algo falla mientras nadie
está viendo (ej. un crash de un hilo de temporizador a las 3am, o un
error de Whisper/Ollama mientras el usuario está jugando con la
consola minimizada). Con todo lo que se agregó al proyecto (hilos de
recordatorios/temporizadores, barge-in, SMTC, Whisper), hay bastante
más superficie donde algo puede fallar en silencio.

Este módulo NO reemplaza los print() existentes — la consola en vivo
se queda exactamente igual. Es una capa ADICIONAL: cualquier archivo
puede hacer `from logger import log` y usar log.info(...)/
log.error(...)/log.exception(...) para que ese evento quede guardado
en disco, además de (o en vez de) imprimirse en consola.

Uso típico:
    from logger import log
    ...
    try:
        algo_riesgoso()
    except Exception:
        log.exception("Error haciendo algo_riesgoso")  # guarda el traceback completo
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rutas_datos import CARPETA_DATOS

# NUEVO: CARPETA_DATOS ahora viene de rutas_datos.py (multiplataforma).
ARCHIVO_LOG    = CARPETA_DATOS / "asistente.log"

# Rotación: cuando el archivo llega a ~2MB, se renombra a .log.1 y se
# empieza uno nuevo. Se mantienen hasta 3 archivos viejos (.log.1,
# .log.2, .log.3) antes de empezar a borrar los más antiguos — esto
# evita que el log crezca sin límite con meses de uso, sin necesitar
# ninguna limpieza manual.
_TAMANO_MAXIMO_BYTES = 2 * 1024 * 1024
_ARCHIVOS_RESPALDO   = 3


def _crear_logger():
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("asistente")
    logger.setLevel(logging.INFO)

    # evitar handlers duplicados si este módulo se importa más de
    # una vez (Python cachea módulos, pero por seguridad ante
    # recargas o imports circulares poco usuales)
    if logger.handlers:
        return logger

    handler = RotatingFileHandler(
        ARCHIVO_LOG,
        maxBytes=_TAMANO_MAXIMO_BYTES,
        backupCount=_ARCHIVOS_RESPALDO,
        encoding="utf-8",
    )

    formato = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formato)

    logger.addHandler(handler)

    # FIX: sin esto, si algún otro código del proyecto llama a
    # logging.basicConfig() (incluso indirectamente, vía alguna
    # librería externa), el logger raíz de Python podría propagar
    # estos mensajes también a la consola por duplicado — se
    # desactiva la propagación para que este logger SOLO escriba al
    # archivo, tal como se decidió (consola se queda igual que antes).
    logger.propagate = False

    return logger


log = _crear_logger()