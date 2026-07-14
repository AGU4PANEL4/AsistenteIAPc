"""
Dos bugs reales reportados juntos ("no molestar no se activa, ni con
'activa el modo no molestar' ni con 'no me molestes por tanto
tiempo'"):

1. tools.py: activar_no_molestar/desactivar_no_molestar/
   estado_no_molestar estaban IMPORTADAS pero nunca agregadas al
   diccionario TOOLS — un bug preexistente del proyecto original.
   Aunque intents.py detectara perfecto el intent, executor.py no
   encontraba ninguna función que ejecutar y fallaba en silencio
   total (sin hablar ningún error).

2. intents.py: la detección de frases exigía que el comando
   EMPEZARA exactamente con un prefijo fijo — "activa el modo no
   molestar" (con "el modo" de más) no coincidía con ningún prefijo
   de la lista.
"""

import sys
import types

import pytest

# tools.py arrastra toda la cadena de imports del proyecto (acciones,
# media_control, voice, tts, win32...) — se stubea lo que depende de
# hardware/Windows real antes de importar, mismo patrón ya usado en
# otros archivos de tests de esta suite.
if "tts" not in sys.modules:
    mod_tts = types.ModuleType("tts")
    mod_tts.hablar = lambda *a, **k: None
    sys.modules["tts"] = mod_tts

if "voice" not in sys.modules:
    mod_voice = types.ModuleType("voice")
    mod_voice.escuchar = lambda *a, **k: ""
    mod_voice.escuchar_confirmacion = lambda *a, **k: "si"
    sys.modules["voice"] = mod_voice

for _m in ["winshell", "pystray", "PIL", "win32gui", "win32con", "win32process",
           "win32api", "pycaw", "comtypes", "winsdk", "pyautogui"]:
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)

sys.modules["win32con"].WM_CLOSE = 0x10
sys.modules["comtypes"].CLSCTX_ALL = 1

if "pycaw.pycaw" not in sys.modules:
    _mod_pycaw = types.ModuleType("pycaw.pycaw")
    _mod_pycaw.AudioUtilities = object()
    _mod_pycaw.IAudioEndpointVolume = object()
    _mod_pycaw.ISimpleAudioVolume = object()
    sys.modules["pycaw.pycaw"] = _mod_pycaw

import tools
import intents


# =========================================================
# FIX 1: tools.py — deben estar REALMENTE en el diccionario,
# no solo importadas en el archivo
# =========================================================

@pytest.mark.parametrize("intent", [
    "activar_no_molestar", "desactivar_no_molestar", "estado_no_molestar",
])
def test_no_molestar_esta_registrado_en_tools(intent):
    assert intent in tools.TOOLS
    assert callable(tools.TOOLS[intent])


# =========================================================
# FIX 2: intents.py — detección tolerante a variaciones naturales
# =========================================================

@pytest.mark.parametrize("texto", [
    "activa el modo no molestar",           # el caso real reportado
    "no me molestes por tanto tiempo",      # el otro caso reportado
    "por favor activa el modo no molestar",
    "quiero activar el modo no molestar",
    "puedes activar el no molestar",
])
def test_activar_no_molestar_frases_tolerantes(texto):
    intent, valor = intents.detectar_intent(texto)
    assert intent == "activar_no_molestar"


@pytest.mark.parametrize("texto", [
    "activa no molestar",
    "modo no molestar",
    "no me molestes",
    "silencia los avisos",
    "silencia las notificaciones",
    "no me interrumpas",
    "no me avises",
    "modo concentración",
    "modo silencio",
])
def test_activar_no_molestar_frases_que_ya_funcionaban(texto):
    intent, _ = intents.detectar_intent(texto)
    assert intent == "activar_no_molestar"


@pytest.mark.parametrize("texto", [
    "desactiva no molestar",
    "desactivar no molestar",
    "cancela no molestar",
    "ya puedes molestarme",
    "ya puedes avisarme",
    "reactiva los avisos",
    "sal del modo no molestar",
    "sal del modo silencio",
    "desactiva el modo no molestar",
    "ya puedes desactivar el modo no molestar",
])
def test_desactivar_no_molestar_no_se_confunde_con_activar(texto):
    """
    Crítico: "desactiva no molestar" CONTIENE literalmente el
    substring "activa no molestar" -- si el chequeo de ACTIVAR se
    revisara antes que el de DESACTIVAR, esto activaría el modo en
    vez de desactivarlo. Se verifica explícitamente que NINGUNA de
    estas frases de desactivar se confunda con activar.
    """
    intent, _ = intents.detectar_intent(texto)
    assert intent == "desactivar_no_molestar"
    assert intent != "activar_no_molestar"


@pytest.mark.parametrize("texto", [
    "estado no molestar",
    "tienes el modo no molestar",
    "está activo el modo no molestar",
    "estás en modo no molestar",
    "cuánto tiempo queda de no molestar",
])
def test_estado_no_molestar(texto):
    intent, _ = intents.detectar_intent(texto)
    assert intent == "estado_no_molestar"


def test_duracion_se_extrae_de_la_frase_completa():
    intent, valor = intents.detectar_intent(
        "quiero activar el modo no molestar por 30 minutos"
    )
    assert intent == "activar_no_molestar"
    assert valor == "30"


def test_sin_duracion_explicita_usa_default():
    intent, valor = intents.detectar_intent("activa el modo no molestar")
    assert intent == "activar_no_molestar"
    assert valor == "60"