"""
voice._es_frase_fantasma_conocida / _filtrar_resultado — filtro de
alucinaciones bien documentadas de Whisper (restos de subtítulos de
YouTube que el modelo a veces "transcribe" sobre silencio/ruido, sin
relación con lo que se dijo de verdad).

Se stubea todo lo que voice.py necesita para importar (habla de
hardware real: micrófono, modelos de Whisper) sin necesitar nada de
eso — solo interesa la lógica pura de estas dos funciones.
"""

import sys
import types

import pytest

# El stubbing tiene que pasar ANTES de `import voice` de más abajo —
# un fixture de pytest correría demasiado tarde (los fixtures se
# ejecutan al CORRER los tests, no al momento en que pytest importa
# el módulo del archivo de test, que es cuando ocurre este import).
mod_logger = types.ModuleType("logger")
class _FakeLog:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def exception(self, *a, **k): pass
mod_logger.log = _FakeLog()
sys.modules.setdefault("logger", mod_logger)

mod_sr = types.ModuleType("speech_recognition")

class _FakeRec:
    def adjust_for_ambient_noise(self, *a, **k):
        pass

class _FakeMic:
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False

mod_sr.Recognizer = lambda: _FakeRec()
mod_sr.Microphone = lambda: _FakeMic()
mod_sr.WaitTimeoutError = Exception
mod_sr.UnknownValueError = Exception
mod_sr.RequestError = Exception
sys.modules.setdefault("speech_recognition", mod_sr)

mod_fw = types.ModuleType("faster_whisper")
class _FakeWhisperModel:
    def __init__(self, *a, **k):
        pass
mod_fw.WhisperModel = _FakeWhisperModel
sys.modules.setdefault("faster_whisper", mod_fw)

import voice


@pytest.mark.parametrize("texto", [
    "subtítulos realizados por la comunidad de amara.org",
    "Subtítulos realizados por la comunidad de Amara.org",
    "gracias por ver el video",
    "gracias por ver este video",
    "suscríbete a mi canal",
    "suscríbete al canal",
    "dale like y suscríbete",
    "www.youtube.com",
])
def test_frases_fantasma_conocidas_se_detectan(texto):
    assert voice._es_frase_fantasma_conocida(texto) is True


@pytest.mark.parametrize("texto", [
    "",
    None,
    "abre discord",
    "cierra steam",
    "pon un recordatorio para mañana",
    "cuánto es 47 por 12",
    "activa el modo no molestar",
    "suscribo el documento",   # contiene "suscrib" pero no es la frase
    "dale al botón de guardar",
])
def test_comandos_reales_no_se_detectan_como_fantasma(texto):
    assert voice._es_frase_fantasma_conocida(texto) is False


def test_filtrar_resultado_convierte_fantasma_en_vacio():
    assert voice._filtrar_resultado("suscríbete a mi canal") == ""


def test_filtrar_resultado_deja_pasar_comandos_reales():
    assert voice._filtrar_resultado("abre discord") == "abre discord"


def test_deteccion_es_insensible_a_tildes_y_mayusculas():
    assert voice._es_frase_fantasma_conocida("GRACIAS POR VER EL VIDEO") is True
    assert voice._es_frase_fantasma_conocida("Suscribete Al Canal") is True


# =========================================================
# GIBBERISH ("letras al azar")
# =========================================================

@pytest.mark.parametrize("texto", [
    "", None, "k", "xz", "bcd", "kjh", "tqr", "psst", "z",
])
def test_gibberish_se_detecta(texto):
    assert voice._parece_gibberish(texto) is True


@pytest.mark.parametrize("texto", [
    "sí", "no", "ya", "eh", "ah",     # respuestas cortas legítimas
    "50", "12.5", "80",               # respuestas numéricas (ej. volumen)
    "abre discord", "cierra steam",
])
def test_gibberish_no_atrapa_respuestas_validas(texto):
    assert voice._parece_gibberish(texto) is False


def test_filtrar_resultado_descarta_gibberish():
    assert voice._filtrar_resultado("xz") == ""
    assert voice._filtrar_resultado("k") == ""


def test_filtrar_resultado_no_descarta_numeros():
    # importante: una respuesta de volumen exacto ("50") no debe
    # perderse por no tener vocales -- los dígitos son un caso
    # especial permitido a propósito
    assert voice._filtrar_resultado("50") == "50"