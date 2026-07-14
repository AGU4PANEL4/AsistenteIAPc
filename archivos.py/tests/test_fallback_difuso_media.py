"""
intents.py — fallback difuso de verbos de media (pausa/reanuda/
siguiente/anterior/silencia). Caso real que motivó esto: el usuario
dijo "reanuda spotify", Whisper lo transcribió como "rganoda
spotify" — no matcheaba ninguna regla exacta, cayó en la IA, que lo
interpretó como "abre spotify" y REABRIÓ la app en vez de
reanudarla (peor que un simple "no entendí": ejecutó la acción
equivocada).

Se salta solo si no se puede importar app_finder (necesita winreg,
solo Windows) — mismo patrón que test_app_finder.py.
"""

import os
import sys
import types

import pytest

os.environ.setdefault("LOCALAPPDATA", "/tmp/localappdata_test_conftest")

app_finder = pytest.importorskip("app_finder")

import intents


@pytest.fixture(autouse=True)
def cache_de_prueba(monkeypatch):
    cache_falsa = {
        "spotify": {"ruta": "x", "tipo": "normal", "procesos_cierre": [],
                    "pids": [], "carpetas_detectadas": []},
        "discord": {"ruta": "x", "tipo": "normal", "procesos_cierre": [],
                    "pids": [], "carpetas_detectadas": []},
    }
    monkeypatch.setattr(app_finder, "cache", cache_falsa)


# =========================================================
# EL CASO REAL
# =========================================================

def test_caso_real_reanuda_transcrito_mal():
    resultado = intents.detectar_intent("rganoda spotify")
    assert resultado == ("media_reanudar", "spotify")


def test_transcripcion_correcta_sigue_funcionando():
    # el camino exacto (ya funcionaba antes de este fix) no debe
    # verse afectado por agregar el fallback difuso
    assert intents.detectar_intent("reanuda spotify") == ("media_reanudar", "spotify")
    assert intents.detectar_intent("pausa discord") == ("media_pausar", "discord")


@pytest.mark.parametrize("comando, verbo_esperado", [
    ("reanuda spotify", "media_reanudar"),
    ("pausa spotify", "media_pausar"),
])
def test_variantes_garbled_razonables(comando, verbo_esperado):
    # variantes con 1-2 letras cambiadas, del mismo estilo que el
    # caso real reportado
    garbled = comando.replace("reanuda", "rganoda").replace("pausa", "pauza")
    resultado = intents.detectar_intent(garbled)
    assert resultado[0] == verbo_esperado


# =========================================================
# FALSOS POSITIVOS — no debe dispararse con comandos reales
# de otras acciones que casualmente se parecen un poco
# =========================================================

def test_no_choca_con_recapturar_app():
    # "recapturar" vs "reanudar" da ~0.667 de similitud -- por debajo
    # del umbral usado (0.70), pero cerca; se confirma explícitamente
    # que el comando real de recapturar sigue intacto
    resultado = intents.detectar_intent("recaptura spotify")
    assert resultado[0] == "recapturar_app"
    assert resultado != ("media_reanudar", "spotify")


def test_no_choca_con_ayuda():
    assert intents.detectar_intent("ayuda") == ("ayuda", "")


def test_sin_app_conocida_exige_umbral_estricto():
    # sin nada reconocible después del verbo garabateado, no alcanza
    # con el umbral relajado (0.70) -- hace falta el estándar (0.80)
    resultado = intents.detectar_intent("rganoda")
    assert resultado != ("media_reanudar", "media")

    resultado2 = intents.detectar_intent("rganoda algo_no_registrado_como_app")
    assert resultado2[0] != "media_reanudar"


def test_comandos_normales_no_afectados():
    assert intents.detectar_intent("abre discord")[0] == "abrir_app"
    assert intents.detectar_intent("busca gatos en google")[0] == "buscar_google"