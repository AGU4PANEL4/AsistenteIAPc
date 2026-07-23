import asyncio
import io
import os
import threading
import time
import hashlib
import edge_tts
import pygame
from pathlib import Path
from logger import log

# =========================================================
# CONFIGURACIÓN DE VOZ
# =========================================================

VOZ_DEFAULT = "es-CO-SalomeNeural"

VOCES_DISPONIBLES = {
    # Femeninas
    "salome": "es-CO-SalomeNeural",
    "elvira": "es-ES-ElviraNeural",
    "dalia": "es-MX-DaliaNeural",
    "karina": "es-ES-KarinaNeural",
    "lucia": "es-ES-LuciaNeural",
    "mexicanaf": "es-MX-LorenaNeural",
    # Masculinas
    "alvaro": "es-ES-AlvaroNeural",
    "jorge": "es-MX-JorgeNeural",
    "tomas": "es-AR-TomasNeural",
    "gerardo": "es-MX-GerardoNeural",
    "mexicanom": "es-MX-RaulNeural",
    "neerlandes": "es-NL-MaartenNeural",
}

try:
    from config import VOZ_ASISTENTE
    VOZ = VOZ_ASISTENTE
except ImportError:
    VOZ = VOZ_DEFAULT


# =========================================================
# CACHE DE AUDIO LOCAL
# =========================================================

_CARPETA_CACHE_TTS = Path.home() / ".asistente_ia" / "cache_tts"
_CARPETA_CACHE_TTS.mkdir(parents=True, exist_ok=True)

# FIX: frases comunes del sistema + flujos guiados (recordatorios, temporizadores, dormir)
_FRASES_PRECARGAR = [
    # Sistema general
    "Asistente listo",
    "¿En qué puedo ayudarte?",
    "¿Algo más?",
    "¿Necesitás algo más?",
    "Cancelado",
    "Hasta luego",
    "Sesión finalizada",
    "No entendí qué quieres que haga, ¿podés repetirlo?",
    "Te escucho, dime qué necesitas",
    "Ya estoy de vuelta",
    "Me quedo en silencio",
    # FIX: esta frase NUNCA hacía match — el texto real que dice
    # main.py incluye el motivo completo ("...: no hay internet y
    # Ollama no está disponible"), y _obtener_audio_cacheado() compara
    # por igualdad EXACTA de string. La entrada vieja generaba y
    # guardaba audio que jamás se usaba. Se corrige al texto completo
    # tal cual se habla.
    "No tengo forma de procesar eso ahora: no hay internet y Ollama no está disponible",
    "Se está demorando mucho en responder, intenta de nuevo en un momento",
    "Todavía no dije nada",
    "Tuve un error inesperado, sigamos",
    "¿Sigues ahí?",

    # Flujo de dormir (main.py)
    "Me quedo en silencio. Decí \"despierta\" cuando me necesites",

    # Recordatorios — frases fijas de error/éxito (recordatorios.py)
    "No entendí a qué hora quieres el recordatorio diario",
    "No entendí a qué hora quieres el recordatorio semanal",
    "No tienes recordatorios pendientes",
    "No entendí cuál recordatorio quieres cancelar",
    "No pude cancelar el recordatorio",
    # NUEVO: variante con "ese" en vez de "el" — cancelar_por_palabra_
    # clave() en recordatorios.py usa esta redacción distinta en su
    # último branch (cuando SÍ se identificó un recordatorio pero
    # cancelar_recordatorio() falla) — sin esto, ese caso puntual
    # nunca pegaba en cache pese a que el mensaje "hermano" ("...el
    # recordatorio") sí estaba precargado.
    "No pude cancelar ese recordatorio",

    # Temporizadores — frases fijas de error/éxito (temporizadores.py)
    "Se acabó el temporizador",
    "No tienes temporizadores activos",
    "No entendí cuál temporizador quieres cancelar",
    "No pude cancelar el temporizador",
    "Cancelé el temporizador",
    # NUEVO: mismo caso que con recordatorios — cancelar_por_palabra_
    # clave() en temporizadores.py también tiene una variante con
    # "ese" en su último branch.
    "No pude cancelar ese temporizador",

    # NUEVO: flujo guiado de crear recordatorio simple
    # (crear_recordatorio_accion, acciones_sistema.py) — las
    # preguntas de preguntar_dato() y los mensajes de abandono/error
    # son fijos y se dicen cada vez que falta un dato en el comando.
    "¿Para cuándo quieres el recordatorio?",
    "¿Qué nombre quieres para tu recordatorio?",
    "No se creó el recordatorio",
    "No entendí para cuándo quieres el recordatorio",
    "No entendí el nombre del recordatorio",

    # NUEVO: flujo guiado de recordatorio recurrente
    # (crear_recordatorio_recurrente_accion, acciones_sistema.py)
    "¿Qué quieres que te recuerde?",
    "No entendí el texto del recordatorio",
    "¿Cada cuánto tiempo quieres el recordatorio?",
    "No entendí cada cuánto quieres el recordatorio",
    "¿A qué hora quieres el recordatorio?",
    "No entendí a qué hora quieres el recordatorio",
    "¿Qué día de la semana?",

    # NUEVO: flujo guiado de temporizador
    # (crear_temporizador_accion, acciones_sistema.py)
    "¿De cuánto tiempo quieres el temporizador?",
    "No se creó el temporizador",
    "No entendí la duración del temporizador",

    # NUEVO: modo no molestar (no_molestar.py) — todas fijas, sin
    # interpolación (a diferencia de activar()/estado() con minutos
    # restantes, que sí varían y no se pueden precachear).
    "El modo no molestar terminó.",
    "Modo no molestar desactivado",
    "El modo no molestar no está activo",
    "El modo no molestar no estaba activo",

    # NUEVO: confirmar_apertura (acciones_apps.py) — se dice cada vez
    # que se abre una app que todavía no está en cache/índices, así
    # que en uso normal (sobre todo al principio, antes de tener
    # todo indexado) puede repetirse bastante.
    "No te entendí, ¿la abro sí o no?",
    "¿La abro sí o no?",
    "No logré entenderte, dejémoslo por ahora",
]

_cache_audio = {}  # texto normalizado -> bytes de audio


def _hash_frase(texto, voz):
    return hashlib.md5(f"{texto}|{voz}".encode()).hexdigest()[:16]


def _ruta_cache(texto, voz):
    return _CARPETA_CACHE_TTS / (_hash_frase(texto, voz) + ".mp3")


def _precargar_cache():
    global _cache_audio
    print(f"[TTS] Precargando cache de audio para voz '{VOZ}'...")
    
    for frase in _FRASES_PRECARGAR:
        ruta = _ruta_cache(frase, VOZ)
        if ruta.exists():
            with open(ruta, "rb") as f:
                _cache_audio[frase.lower()] = f.read()
            continue
        
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            audio = loop.run_until_complete(_generar_audio_edge(frase))
            loop.close()
            
            if audio:
                with open(ruta, "wb") as f:
                    f.write(audio)
                _cache_audio[frase.lower()] = audio
                print(f"[TTS]  ✓ Cacheado: {frase!r}")
            else:
                print(f"[TTS]  ✗ Falló: {frase!r}")
        except Exception as e:
            print(f"[TTS]  ✗ Error cacheando {frase!r}: {e}")
    
    print(f"[TTS] Cache listo: {len(_cache_audio)} frases precargadas")


def _obtener_audio_cacheado(texto):
    return _cache_audio.get(texto.lower().strip())


async def _generar_audio_edge(texto):
    try:
        communicate = edge_tts.Communicate(texto, voice=VOZ)
        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]
        return audio_data if audio_data else None
    except Exception as e:
        print(f"[TTS] Error generando audio con Edge: {e}")
        return None


# Precargar cache al importar el módulo
threading.Thread(target=_precargar_cache, daemon=True, name="TTSCache").start()


# =========================================================
# ENFRIAMIENTO POST-TTS
# =========================================================

RECALIBRAR_TRAS_HABLAR = True

_DEMORA_BASE_MS = 300
_DEMORA_CONVERSACION_MS = 500
_DEMORA_SUPERPOSICION_MS = 400


def _calcular_demora_eco(hubo_superposicion=False, modo_escucha=None):
    demora = _DEMORA_BASE_MS
    try:
        from voice import get_modo_escucha, ModoEscucha
        if modo_escucha is None:
            modo_escucha = get_modo_escucha()
        if modo_escucha == ModoEscucha.CONVERSACION:
            demora = max(demora, _DEMORA_CONVERSACION_MS)
    except Exception:
        pass
    if hubo_superposicion:
        demora += _DEMORA_SUPERPOSICION_MS
    return demora / 1000.0


# =========================================================
# INICIALIZAR PYGAME MIXER
# =========================================================

pygame.mixer.init()


# =========================================================
# LOCK DE VOZ + ÚLTIMO MENSAJE
# =========================================================

_lock_voz = threading.Lock()
_ultimo_mensaje = None


def ultimo_mensaje():
    return _ultimo_mensaje


# =========================================================
# RESPALDO LOCAL (SAPI5/pyttsx3) — SOLO EN ERRORES GRAVES
# =========================================================

def _hablar_respaldo(texto):
    try:
        import pyttsx3
        motor = pyttsx3.init()
        motor.say(texto)
        motor.runAndWait()
        return True
    except Exception as e:
        print("[TTS] Respaldo también falló:", e)
        return False


# =========================================================
# REPRODUCIR AUDIO DESDE BYTES
# =========================================================

def _reproducir_audio(audio_bytes):
    try:
        pygame.mixer.music.load(io.BytesIO(audio_bytes))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(50)
        return True
    except Exception as e:
        print(f"[TTS] Error reproduciendo audio: {e}")
        return False


# =========================================================
# ESCUCHA EN PARALELO (interrupciones)
# =========================================================

UMBRAL_VAD_SUPERPONER = 0.6
PHRASE_TIME_LIMIT_SUPERPOSICION = 10
INTENTO_POST_TTS = True


def _vigilar_interrupcion(evento_detener, resultado, info_superposicion):
    from voice import detectar_voz_breve, escuchar_rapido
    while not evento_detener.is_set():
        try:
            hay_voz = detectar_voz_breve(timeout=1, umbral=UMBRAL_VAD_SUPERPONER)
        except Exception:
            continue
        if evento_detener.is_set():
            return
        if hay_voz:
            info_superposicion["hubo"] = True
            info_superposicion["timestamp_inicio"] = time.time()
            try:
                texto = escuchar_rapido(
                    timeout=2,
                    phrase_time_limit=PHRASE_TIME_LIMIT_SUPERPOSICION
                )
            except Exception:
                texto = ""
            info_superposicion["texto"] = texto or None
            info_superposicion["timestamp_fin"] = time.time()
            resultado[0] = texto or None
            return


# =========================================================
# HABLAR PRINCIPAL — CACHE PRIMERO, EDGE TTS DESPUÉS
# =========================================================

async def _hablar_async(texto, permitir_interrupcion):
    # FIX: intentar cache primero (instantáneo, misma voz)
    audio_cacheado = _obtener_audio_cacheado(texto)
    if audio_cacheado:
        print(f"[TTS] Cache hit: {texto!r}")
        _reproducir_audio(audio_cacheado)
        if RECALIBRAR_TRAS_HABLAR:
            await asyncio.sleep(_calcular_demora_eco())
            try:
                from voice import recalibrar
                recalibrar()
            except Exception:
                pass
        return None

    # No está en cache → generar con Edge TTS
    audio_data = await _generar_audio_edge(texto)
    
    if not audio_data:
        raise RuntimeError("Edge TTS no devolvió audio")

    _reproducir_audio(audio_data)

    resultado_interrupcion = [None]
    info_superposicion = {"hubo": False}
    hilo_vigilancia = None
    evento_detener = threading.Event()

    if permitir_interrupcion:
        hilo_vigilancia = threading.Thread(
            target=_vigilar_interrupcion,
            args=(evento_detener, resultado_interrupcion, info_superposicion),
            daemon=True
        )
        hilo_vigilancia.start()

    while pygame.mixer.music.get_busy():
        pygame.time.wait(50)

    evento_detener.set()

    if hilo_vigilancia is not None and hilo_vigilancia.is_alive():
        hilo_vigilancia.join(timeout=3)

    if (INTENTO_POST_TTS
        and info_superposicion["hubo"]
        and not resultado_interrupcion[0]):
        try:
            from voice import escuchar_rapido
            print("[TTS] Superposición sin texto claro, intentando post-TTS...")
            texto_post = escuchar_rapido(timeout=2, phrase_time_limit=5)
            if texto_post:
                resultado_interrupcion[0] = texto_post
                print(f"[TTS] Segundo intento exitoso: {texto_post!r}")
        except Exception:
            pass

    if RECALIBRAR_TRAS_HABLAR:
        demora = _calcular_demora_eco(hubo_superposicion=info_superposicion["hubo"])
        await asyncio.sleep(demora)
        try:
            from voice import recalibrar
            recalibrar()
        except Exception as e:
            log.warning(f"No se pudo recalibrar: {e}")

    return resultado_interrupcion[0]


def hablar(texto, permitir_interrupcion=False):
    global _ultimo_mensaje
    _ultimo_mensaje = texto

    with _lock_voz:
        print("Asistente:", texto)

        try:
            return asyncio.run(_hablar_async(texto, permitir_interrupcion))
        except Exception as e:
            print("[TTS] Error con Edge TTS, usando respaldo:", e)
            log.warning(f"Edge TTS falló. Texto: '{texto}'. Motivo: {e}")
            # FIX: intentar cache de respaldo por error
            audio_cacheado = _obtener_audio_cacheado(texto)
            if audio_cacheado:
                print("[TTS] Usando cache de respaldo por error")
                _reproducir_audio(audio_cacheado)
                return None
            if not _hablar_respaldo(texto):
                log.error(f"El asistente quedó MUDO para: '{texto}'")
            return None