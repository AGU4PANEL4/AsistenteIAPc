"""
app_finder._escanear_juegos_epic / indexar_juegos — escaneo de los
manifests locales de Epic Games Launcher (necesario para que juegos
como Fortnite, protegidos con anti-cheat, se lancen por el protocolo
del launcher en vez de ejecutando el .exe directo — ver el FIX
detallado en app_finder.py y acciones_apps.py).

Se salta solo (pytest.importorskip) si no se puede importar
app_finder en este SO — mismo patrón que test_app_finder.py.
"""

import json

import pytest

app_finder = pytest.importorskip("app_finder")


MANIFEST_FORTNITE = {
    "FormatVersion": 0,
    "bIsIncompleteInstall": False,
    "LaunchExecutable": "FortniteGame\\Binaries\\Win64\\FortniteClient-Win64-Shipping.exe",
    "InstallLocation": "C:\\Program Files\\Epic Games\\Fortnite",
    "bIsApplication": True,
    "bIsExecutable": True,
    "bRequiresAuth": True,
    "DisplayName": "Fortnite",
    "AppName": "Fortnite",
    "CatalogNamespace": "fn",
}

MANIFEST_NO_ES_JUEGO = {
    "DisplayName": "Unreal Engine Tool",
    "AppName": "UEBase",
    "InstallLocation": "C:\\Epic\\UE",
    "bIsApplication": False,
}


@pytest.fixture
def carpeta_manifests(tmp_path, monkeypatch):
    """Redirige CARPETA_MANIFESTS_EPIC a una carpeta temporal, para
    no depender de que exista Epic Games Launcher de verdad en la
    máquina donde corren los tests."""
    monkeypatch.setattr(app_finder, "CARPETA_MANIFESTS_EPIC", tmp_path)
    return tmp_path


def _escribir_manifest(carpeta, nombre_archivo, contenido):
    (carpeta / nombre_archivo).write_text(json.dumps(contenido), encoding="utf-8")


def test_escanea_un_juego_valido(carpeta_manifests):
    _escribir_manifest(carpeta_manifests, "fortnite.item", MANIFEST_FORTNITE)

    resultado = app_finder._escanear_juegos_epic()

    assert "fortnite" in resultado
    assert resultado["fortnite"]["tipo"] == "epic"
    assert resultado["fortnite"]["app_name"] == "Fortnite"


def test_excluye_manifests_que_no_son_aplicacion(carpeta_manifests):
    _escribir_manifest(carpeta_manifests, "fortnite.item", MANIFEST_FORTNITE)
    _escribir_manifest(carpeta_manifests, "engine.item", MANIFEST_NO_ES_JUEGO)

    resultado = app_finder._escanear_juegos_epic()

    assert "fortnite" in resultado
    assert "uebase" not in resultado
    assert not any("unreal engine" in k for k in resultado)


def test_manifest_corrupto_no_rompe_el_escaneo(carpeta_manifests):
    (carpeta_manifests / "corrupto.item").write_text("{ esto no es json", encoding="utf-8")
    _escribir_manifest(carpeta_manifests, "fortnite.item", MANIFEST_FORTNITE)

    resultado = app_finder._escanear_juegos_epic()

    assert "fortnite" in resultado


def test_sin_carpeta_manifests_devuelve_vacio(tmp_path, monkeypatch):
    monkeypatch.setattr(app_finder, "CARPETA_MANIFESTS_EPIC", tmp_path / "no_existe")

    resultado = app_finder._escanear_juegos_epic()

    assert resultado == {}


def test_manifest_sin_appname_o_displayname_se_ignora(carpeta_manifests):
    _escribir_manifest(carpeta_manifests, "incompleto.item", {
        "DisplayName": "Algo Incompleto",
        "bIsApplication": True,
        # sin AppName -> no se puede lanzar, no tiene sentido indexarlo
    })

    resultado = app_finder._escanear_juegos_epic()

    assert resultado == {}


def test_indexar_juegos_combina_steam_y_epic_sin_pisarse(carpeta_manifests, monkeypatch):
    _escribir_manifest(carpeta_manifests, "fortnite.item", MANIFEST_FORTNITE)

    # simular que Steam sí encontró un juego propio, para confirmar
    # que indexar_juegos() no lo pisa con el resultado de Epic
    monkeypatch.setattr(
        app_finder, "_escanear_juegos_steam",
        lambda: {"brawlhalla": {"tipo": "steam", "appid": "291550"}},
    )

    app_finder.indexar_juegos()

    assert "fortnite" in app_finder.games_index
    assert "brawlhalla" in app_finder.games_index
    assert app_finder.games_index["fortnite"]["tipo"] == "epic"
    assert app_finder.games_index["brawlhalla"]["tipo"] == "steam"


def test_limpiar_cache_duplicados_preserva_entradas_epic(monkeypatch):
    """
    FIX: limpiar_cache_duplicados() (se corre una vez al arrancar,
    ver main.py) tenía un caso especial que preservaba las entradas
    de Steam TAL CUAL, sin pasar por la lógica genérica de renombrado
    (pensada para apps encontradas en disco, no para las que se
    identifican por un campo confiable como appid/app_name) — pero
    ese caso especial no cubría "epic". Una entrada de Epic guardada
    de una sesión anterior con procesos_cierre todavía vacío (la
    captura de PID no había terminado) perdía su clave original al
    reiniciar el asistente -- terminaba guardada bajo la ruta
    completa del sistema de archivos en vez de "fortnite".
    """
    monkeypatch.setattr(app_finder, "guardar_cache", lambda: None)
    app_finder.cache.clear()
    app_finder.cache["fortnite"] = {
        "ruta": "C:\\Program Files\\Epic Games\\Fortnite",
        "app_name": "Fortnite",
        "tipo": "epic",
        "procesos_cierre": [],
        "pids": [],
        "carpetas_detectadas": [],
    }

    app_finder.limpiar_cache_duplicados()

    assert "fortnite" in app_finder.cache
    assert app_finder.cache["fortnite"]["tipo"] == "epic"
    assert app_finder.cache["fortnite"]["app_name"] == "Fortnite"