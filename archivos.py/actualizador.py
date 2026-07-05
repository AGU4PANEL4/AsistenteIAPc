"""
Sistema de actualización automática via GitHub Releases.

Flujo:
1. Al arrancar, consulta la API de GitHub para obtener la última
   release disponible (sin bloquear el arranque — corre en un hilo).
2. Compara el tag de la release con la versión guardada en config.json.
3. Si hay versión nueva, descarga el instalador .exe en background.
4. Cuando termina la descarga, avisa por voz y espera confirmación
   del usuario antes de ejecutar el instalador y cerrar el asistente.

El asistente sigue funcionando normalmente mientras descarga en
background — la notificación llega recién cuando el .exe ya está
listo, no mientras todavía está bajando.
"""

import os
import sys
import threading
import tempfile
import subprocess
from pathlib import Path

import requests

from config import cargar_config, guardar_config
from logger import log

# =========================================================
# CONFIGURACIÓN
# =========================================================

GITHUB_REPO    = "AGU4PANEL4/AsistenteIAPc"
API_URL        = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
TIMEOUT_API    = 8    # segundos para consultar la API de GitHub
TIMEOUT_DL     = 120  # segundos de timeout por chunk de descarga

# clave en config.json donde guardamos la versión instalada actualmente
CLAVE_VERSION  = "version"

# =========================================================
# VERSIÓN LOCAL
# =========================================================

def obtener_version_local():
    """
    Lee la versión instalada actualmente desde config.json.
    Devuelve el string del tag (ej. "v1.2.0") o "" si no se conoce
    (instalación sin versión registrada — ej. antes de agregar este
    sistema, o instalación manual del .py sin pasar por el instalador).
    """
    return cargar_config().get(CLAVE_VERSION, "")


def guardar_version_local(tag):
    """Persiste la versión instalada en config.json."""
    data = cargar_config()
    data[CLAVE_VERSION] = tag
    guardar_config(data)
    print(f"[Actualizador] Versión guardada: {tag}")


# =========================================================
# CONSULTAR GITHUB
# =========================================================

def _consultar_release():
    """
    Consulta la API de GitHub y devuelve (tag, url_exe) de la
    última release, o (None, None) si no hay internet, falla la
    API, o la release no tiene ningún .exe como asset.
    """
    try:
        r = requests.get(API_URL, timeout=TIMEOUT_API)
        r.raise_for_status()
        data = r.json()

        tag    = data.get("tag_name", "").strip()
        assets = data.get("assets", [])

        # buscar el primer asset .exe en la release
        url_exe = None
        for asset in assets:
            nombre = asset.get("name", "")
            if nombre.lower().endswith(".exe"):
                url_exe = asset.get("browser_download_url")
                break

        if not tag or not url_exe:
            log.warning(f"Release de GitHub sin tag o sin .exe: tag='{tag}' assets={[a.get('name') for a in assets]}")
            return None, None

        return tag, url_exe

    except requests.exceptions.ConnectionError:
        # sin internet — comportamiento esperado y silencioso
        return None, None
    except Exception as e:
        print(f"[Actualizador] Error consultando GitHub: {e}")
        log.exception("Error consultando la API de GitHub Releases")
        return None, None


def _hay_version_nueva(tag_remoto, tag_local):
    """
    Compara dos tags de versión semántica (v1.2.3).
    Devuelve True si el tag remoto es más nuevo que el local.

    Si alguno no sigue el formato vX.Y.Z (ej. primer arranque sin
    versión local registrada), se compara como strings — menos preciso
    pero funciona para el caso más común de "sin versión local → hay
    algo nuevo".
    """
    if not tag_local:
        # sin versión local registrada → siempre hay "algo nuevo"
        # para poder guardar la versión actual sin ofrecer actualizar
        return False  # ver _verificar_primera_vez

    if tag_remoto == tag_local:
        return False

    def _partes(tag):
        try:
            return tuple(int(x) for x in tag.lstrip("v").split("."))
        except ValueError:
            return None

    partes_remoto = _partes(tag_remoto)
    partes_local  = _partes(tag_local)

    if partes_remoto and partes_local:
        return partes_remoto > partes_local

    # fallback: comparación de strings — no es perfecta pero mejor
    # que nada para tags no semánticos
    return tag_remoto != tag_local


# =========================================================
# DESCARGA
# =========================================================

def _descargar_exe(url, callback_listo, callback_error):
    """
    Descarga el .exe a una carpeta temporal y llama a `callback_listo`
    con la ruta cuando termina, o `callback_error` si algo falla.
    Corre en un hilo aparte — no bloquea el asistente.
    """
    try:
        print(f"[Actualizador] Descargando actualización desde {url}...")
        log.info(f"Descargando actualización: {url}")

        r = requests.get(url, stream=True, timeout=TIMEOUT_DL)
        r.raise_for_status()

        total      = int(r.headers.get("content-length", 0))
        descargado = 0

        tmp_dir  = tempfile.mkdtemp(prefix="asistente_update_")
        ruta_exe = Path(tmp_dir) / "AsistenteIA_Setup.exe"

        with open(ruta_exe, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    descargado += len(chunk)
                    if total:
                        pct = descargado * 100 // total
                        print(f"\r[Actualizador] Descargando... {pct}%", end="", flush=True)

        print()  # nueva línea después del progreso
        print(f"[Actualizador] Descarga completa: {ruta_exe}")
        log.info(f"Actualización descargada en {ruta_exe}")
        callback_listo(ruta_exe)

    except Exception as e:
        print(f"[Actualizador] Error descargando la actualización: {e}")
        log.exception("Error descargando la actualización")
        callback_error()


# =========================================================
# INSTALAR
# =========================================================

def _instalar_y_cerrar(ruta_exe):
    """
    Ejecuta el instalador descargado y cierra el asistente.
    El instalador de Inno Setup corre de forma independiente, así
    que el asistente puede cerrarse sin esperar a que termine.
    """
    try:
        print(f"[Actualizador] Ejecutando instalador: {ruta_exe}")
        log.info(f"Ejecutando instalador de actualización: {ruta_exe}")

        subprocess.Popen(
            [str(ruta_exe)],
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )

        # pequeña pausa para que el instalador arranque antes de que
        # el proceso del asistente se cierre
        import time
        time.sleep(1)

        sys.exit(0)

    except Exception as e:
        print(f"[Actualizador] No pude ejecutar el instalador: {e}")
        log.exception("Error ejecutando el instalador de actualización")


# =========================================================
# FLUJO PRINCIPAL
# =========================================================

# estado compartido entre el hilo de descarga y el loop principal
_estado = {
    "tag_nuevo":  None,   # tag de la versión disponible
    "ruta_exe":   None,   # ruta local del .exe descargado (None si aún no llegó)
    "error":      False,  # True si la descarga falló
    "pendiente":  False,  # True si hay una actualización esperando confirmación
}
_lock_estado = threading.Lock()


def _on_descarga_lista(ruta_exe):
    with _lock_estado:
        _estado["ruta_exe"]  = ruta_exe
        _estado["pendiente"] = True


def _on_descarga_error():
    with _lock_estado:
        _estado["error"] = True


def _verificar_y_descargar():
    """
    Corre en un hilo daemon al arrancar. Consulta GitHub, y si hay
    versión nueva, arranca la descarga en background.
    """
    tag_remoto, url_exe = _consultar_release()

    if not tag_remoto:
        return  # sin internet o sin release válida

    tag_local = obtener_version_local()

    # primera vez sin versión registrada: solo guardar la versión
    # actual sin ofrecer actualizar (el usuario ya tiene esta versión
    # instalada, no tiene sentido ofrecerle descargar lo mismo)
    if not tag_local:
        print(f"[Actualizador] Primera ejecución — registrando versión: {tag_remoto}")
        guardar_version_local(tag_remoto)
        return

    if not _hay_version_nueva(tag_remoto, tag_local):
        print(f"[Actualizador] Ya tienes la última versión ({tag_local})")
        return

    print(f"[Actualizador] Nueva versión disponible: {tag_remoto} (instalada: {tag_local})")
    log.info(f"Nueva versión disponible: {tag_remoto} (actual: {tag_local})")

    with _lock_estado:
        _estado["tag_nuevo"] = tag_remoto

    # descarga en hilo aparte para no bloquear nada
    hilo = threading.Thread(
        target=_descargar_exe,
        args=(url_exe, _on_descarga_lista, _on_descarga_error),
        daemon=True,
    )
    hilo.start()


def iniciar_verificacion():
    """
    Llamar UNA vez al arrancar el asistente (desde main.py).
    Lanza la verificación en background — no bloquea el arranque.
    """
    threading.Thread(target=_verificar_y_descargar, daemon=True).start()


def hay_actualizacion_pendiente():
    """
    Devuelve True si hay una actualización descargada y lista para
    instalar. Llamar desde el loop principal de main.py para saber
    cuándo avisar al usuario.
    """
    with _lock_estado:
        return _estado["pendiente"]


def obtener_tag_nuevo():
    with _lock_estado:
        return _estado["tag_nuevo"]


def aplicar_actualizacion():
    """
    Ejecuta el instalador descargado. Llamar desde main.py después
    de que el usuario confirmó por voz que quiere actualizar.
    """
    with _lock_estado:
        ruta = _estado["ruta_exe"]

    if ruta:
        _instalar_y_cerrar(ruta)


def buscar_actualizacion_ahora(valor=None):
    """
    Acción de tool para buscar actualizaciones por voz de forma
    inmediata (sin esperar al background del arranque).
    Devuelve (éxito, mensaje) — mismo patrón que el resto de tools.
    """
    from tts import hablar as _hablar

    _hablar("Buscando actualizaciones...")

    tag_remoto, url_exe = _consultar_release()

    if not tag_remoto:
        return False, "No pude conectarme a GitHub para buscar actualizaciones"

    tag_local = obtener_version_local()

    if not _hay_version_nueva(tag_remoto, tag_local):
        return True, f"Ya tienes la última versión instalada"

    # hay versión nueva — actualizar el estado y arrancar descarga
    with _lock_estado:
        _estado["tag_nuevo"]  = tag_remoto
        _estado["pendiente"]  = False  # se reseteará cuando termine la descarga
        _estado["ruta_exe"]   = None
        _estado["error"]      = False

    _hablar(f"Hay una versión nueva disponible: {tag_remoto}. Descargando en background, te aviso cuando esté lista.")

    hilo = threading.Thread(
        target=_descargar_exe,
        args=(url_exe, _on_descarga_lista, _on_descarga_error),
        daemon=True,
    )
    hilo.start()

    return True, None  # el mensaje ya se habló directamente arriba