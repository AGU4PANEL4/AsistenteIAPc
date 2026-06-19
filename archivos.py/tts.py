import asyncio
import io
import edge_tts
import pygame

# =========================================================
# VOZ
# es-CO-SalomeNeural = voz colombiana femenina
# es-CO-GonzaloNeural = voz colombiana masculina
# =========================================================

VOZ = "es-CO-SalomeNeural"

# =========================================================
# INICIALIZAR PYGAME MIXER UNA SOLA VEZ
# =========================================================

pygame.mixer.init()

# =========================================================
# RESPALDO SIN INTERNET (SAPI5 de Windows)
# Edge TTS depende de un servicio de Microsoft que de vez en
# cuando devuelve error 403 (problema conocido y reportado del
# lado de ellos, no de este código — ver github.com/rany2/edge-tts).
# Mientras eso pase (o si no hay internet), usar la voz local de
# Windows evita que el asistente se quede completamente mudo,
# aunque suene más robótica que la voz neuronal de Edge.
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
# HABLAR
# =========================================================

async def _hablar_async(texto):

    communicate = edge_tts.Communicate(texto, voice=VOZ)

    audio_data = b""

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]

    if not audio_data:
        raise RuntimeError("Edge TTS no devolvió audio")

    pygame.mixer.music.load(io.BytesIO(audio_data))
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        pygame.time.wait(50)


def hablar(texto):

    print("Asistente:", texto)

    try:
        asyncio.run(_hablar_async(texto))
    except Exception as e:
        print("[TTS] Error con Edge TTS, usando respaldo local:", e)
        _hablar_respaldo(texto)