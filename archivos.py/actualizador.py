"""
Sistema de actualización automática vía GitHub Releases.

Hay DOS caminos distintos para llegar a una actualización, cada uno
con la forma de avisar que tiene sentido para su contexto:

1. VERIFICACIÓN AUTOMÁTICA AL ARRANCAR (verificar_actualizacion_arranque)
   Se ejecuta UNA vez, de forma síncrona, mientras el splash de carga
   está visible (ver main.py) — consulta GitHub (un solo request,
   rápido) y, si hay una versión nueva, muestra un diálogo visual
   preguntando si se quiere actualizar ahora mismo (ver
   setup_actualizacion_gui.py). Si el usuario confirma, descarga el
   instalador (con el progreso visible en el splash) y lo ejecuta,
   cerrando el asistente ANTES de terminar de arrancar el resto (IA,
   UI, etc.) — no tiene sentido cargar todo eso si el proceso se va
   a cerrar de todas formas para actualizarse.

   FIX/NUEVO: antes esto corría en background durante TODA la sesión
   y avisaba por VOZ, interrumpiendo la conversación normal justo
   después de que el asistente respondiera algo, antes de preguntar
   "¿Algo más?" — una interrupción fuera de contexto para algo que
   no tiene nada que ver con lo que el usuario le pidió. Ahora se
   resuelve ANTES de que la sesión de voz siquiera empiece, con una
   ventana visual, igual que las otras decisiones de arranque (Groq,
   Ollama).

2. BÚSQUEDA MANUAL POR VOZ (buscar_actualizacion_ahora)
   El usuario pide explícitamente "busca actualizaciones" en medio
   de una sesión — acá SÍ tiene sentido responder por voz, porque el
   usuario mismo inició el pedido por voz. Descarga en background
   (para no dejar al asistente "mudo" mientras se descarga el
   instalador) y, cuando termina, el propio hilo de descarga habla
   directamente para avisar y pedir confirmación — mismo patrón ya
   usado por recordatorios.py/temporizadores.py para avisos que
   surgen desde un hilo en background, sin necesitar que main.py
   esté revisando ningún estado compartido en su loop principal.
"""

import os
import sys
import time
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
        return False  # ver el manejo de "primera vez" en cada camino

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
# Síncrona — quien la llama decide si esperarla desde el hilo
# principal (arranque, ve verificar_actualizacion_arranque) o desde
# un hilo aparte (búsqueda manual, ver _flujo_manual_en_hilo).
# =========================================================

def _descargar_exe(url, callback_progreso=None):
    """
    Descarga el .exe a una carpeta temporal y devuelve la ruta local,
    o None si algo falló.

    `callback_progreso`, si se da, se llama con un texto corto en
    cada etapa (ej. "Descargando actualización... 42%") — pensado
    para conectarlo a actualizar_splash() durante el arranque, igual
    que el mismo patrón ya usado en verificacion.py para instalar
    Ollama.
    """

    def _reportar(texto):
        print(texto)
        if callback_progreso:
            try:
                callback_progreso(texto)
            except Exception:
                pass

    try:
        _reportar("Descargando actualización...")
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
                        _reportar(f"Descargando actualización... {pct}%")

        print(f"[Actualizador] Descarga completa: {ruta_exe}")
        log.info(f"Actualización descargada en {ruta_exe}")
        return ruta_exe

    except Exception as e:
        print(f"[Actualizador] Error descargando la actualización: {e}")
        log.exception("Error descargando la actualización")
        return None


# =========================================================
# INSTALAR
# =========================================================

def _instalar_y_cerrar(ruta_exe, tag_nuevo=None):
    """
    FIX CRÍTICO (histórico): antes el flujo era:
      1. subprocess.Popen(instalador)   → lanza el instalador async
      2. time.sleep(2)                  → espera arbitraria
      3. sys.exit(0)                    → MATA EL PROCESO

    El problema: sys.exit(0) cierra el proceso del asistente ANTES
    de que el instalador de Inno Setup termine de reemplazar los
    archivos. Como el asistente mismo es el proceso que tiene los
    archivos .exe abiertos (está corriendo), el instalador necesita
    que el proceso se cierre por su cuenta para poder reemplazarlos.
    Con /CLOSEAPPLICATIONS, Inno Setup intenta cerrar el asistente
    amablemente (WM_CLOSE), pero si el proceso se mata con sys.exit(0)
    antes de que el instalador llegue a esa etapa, la instalación se
    aborta o queda incompleta.

    Además, /CLOSEAPPLICATIONS + /SUPPRESSMSGBOXES es peligroso: si
    el asistente no responde al cierre amable en el tiempo que Inno
    Setup espera, el MsgBox de "no se pudo cerrar la aplicación"
    responde con "Abort" por defecto (comportamiento de
    SUPPRESSMSGBOXES), CANCELANDO la instalación completamente.

    El flujo correcto es:
      1. Liberar mutex (para que el instalador no vea "instancia corriendo")
      2. Apagar TODOS los subsistemas del asistente de forma ordenada
         (TTS, micrófono, hilos, etc.) via apagar_todo_al_salir()
      3. Lanzar el instalador SIN /CLOSEAPPLICATIONS (ya no hace falta,
         porque nos cerramos nosotros) y SIN /RESTARTAPPLICATIONS (no
         funciona si el instalador no fue quien nos cerró)
      4. Guardar la versión instalada (recién ahora que estamos
         seguros de que el instalador se lanzó correctamente)
      5. Cerrar el proceso del asistente INMEDIATAMENTE con os._exit(0)
         (más rápido y limpio que sys.exit, no ejecuta finally/atexit)

    El instalador de Inno Setup, al no encontrar el .exe en ejecución
    (porque ya nos cerramos), puede reemplazar los archivos
    directamente sin necesidad de CloseApplications ni Restart Manager.

    FIX (este cambio): faltaba `import os` a nivel de módulo — la
    llamada a os._exit(0) al final de esta función lanzaba
    NameError: name 'os' is not defined, capturado en silencio por
    el except Exception de más abajo (solo un print/log, nunca
    propagado). Resultado real observado: el instalador SÍ se
    lanzaba (el subprocess.Popen de más abajo se ejecuta antes del
    error), pero el asistente NUNCA se cerraba con os._exit(0) —
    seguía vivo con los .exe/DLLs abiertos, así que Inno Setup no
    podía reemplazarlos: la actualización se "descargaba e instalaba"
    en apariencia, pero nada cambiaba nunca. Se agrega `import os`
    al principio del archivo.

    FIX (este cambio, 2/2): el docstring de
    verificar_actualizacion_arranque() ya decía que la versión debía
    guardarse "DENTRO de _instalar_y_cerrar(), justo antes de
    os._exit(0)" — pero esa llamada a guardar_version_local() nunca
    se había agregado de verdad acá. Se agrega el parámetro opcional
    `tag_nuevo`: si se pasa, se guarda la versión ANTES de salir,
    solo después de confirmar que el Popen del instalador no lanzó
    ninguna excepción. Si _instalar_y_cerrar() falla antes de llegar
    ahí, la versión NO se guarda y la próxima vez que arranque
    volverá a ofrecer la actualización — igual que documentaba el
    comentario original.
    """
    try:
        print(f"[Actualizador] Ejecutando instalador (silencioso): {ruta_exe}")
        log.info(f"Ejecutando instalador de actualización (silencioso): {ruta_exe}")

        # 1. Liberar mutex para que el instalador no vea "instancia corriendo"
        from instancia import liberar as _liberar_mutex
        _liberar_mutex()

        # 2. Apagar subsistemas ordenadamente (TTS, micrófono, modelos, etc.)
        #    Esto libera todos los recursos que el instalador podría
        #    necesitar reemplazar.
        from gestor_ia import apagar_todo_al_salir
        apagar_todo_al_salir()

        # 3. Lanzar el instalador. SIN /CLOSEAPPLICATIONS (ya nos cerramos
        #    nosotros), SIN /RESTARTAPPLICATIONS (no funciona si no nos
        #    cerró el instalador). Se agrega /LOG para debug.
        #    Se usa startupinfo para ocultar la ventana del instalador
        #    completamente (incluso el flash inicial).
        startupinfo = None
        if hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        flags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            flags = subprocess.CREATE_NO_WINDOW

        subprocess.Popen(
            [
                str(ruta_exe),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/LOG",  # Genera log en %TEMP% para debug si falla
            ],
            startupinfo=startupinfo,
            creationflags=flags,
        )

        # 4. Guardar la versión instalada — recién ahora que el
        #    instalador se lanzó sin excepciones. Si algo de lo de
        #    arriba hubiera fallado, no llegaríamos hasta acá y la
        #    versión local seguiría siendo la vieja.
        if tag_nuevo:
            guardar_version_local(tag_nuevo)

        # 5. Cerrar el proceso AHORA. os._exit() es más rápido que
        #    sys.exit() porque no ejecuta finally blocks ni atexit
        #    handlers — justo lo que queremos, porque
        #    apagar_todo_al_salir() YA se ejecutó arriba y no
        #    queremos que se ejecute de nuevo.
        print("[Actualizador] Cerrando asistente para completar la instalación...")
        os._exit(0)

    except Exception as e:
        print(f"[Actualizador] No pude ejecutar el instalador: {e}")
        log.exception("Error ejecutando el instalador de actualización")
        return False


# =========================================================
# 1. VERIFICACIÓN AUTOMÁTICA AL ARRANCAR (con GUI)
# =========================================================

def verificar_actualizacion_arranque(callback_progreso=None):
    """
    Llamar UNA vez durante el arranque, mientras el splash está
    visible (ver main.py) — consulta GitHub, y si hay una versión
    nueva, pregunta con una ventana (ver setup_actualizacion_gui.py)
    si se quiere instalar ahora.

    `callback_progreso`, si se da, se llama con textos cortos de
    estado (pensado para conectarlo a actualizar_splash()).

    Devuelve:
      True  -> el arranque debe CONTINUAR normalmente (no había
               actualización, falló la consulta/descarga, o el
               usuario prefirió posponerla).
      False -> el asistente se está cerrando para instalar la
               actualización — quien llama debe detener el arranque
               de inmediato (en la práctica, _instalar_y_cerrar() ya
               hizo os._exit(0) antes de llegar a retornar esto; se
               deja como resguardo por si esa llamada no llegara a
               cerrar el proceso por algún motivo).
    """
    tag_remoto, url_exe = _consultar_release()

    if not tag_remoto:
        return True  # sin internet o sin release válida — seguir normal

    tag_local = obtener_version_local()

    if not tag_local:
        # primera ejecución sin versión registrada: solo guardar la
        # versión actual, sin ofrecer "actualizar" a lo mismo que ya
        # se tiene instalado
        print(f"[Actualizador] Primera ejecución — registrando versión: {tag_remoto}")
        guardar_version_local(tag_remoto)
        return True

    if not _hay_version_nueva(tag_remoto, tag_local):
        print(f"[Actualizador] Ya tienes la última versión ({tag_local})")
        return True

    print(f"[Actualizador] Nueva versión disponible: {tag_remoto} (instalada: {tag_local})")
    log.info(f"Nueva versión disponible: {tag_remoto} (actual: {tag_local})")

    from setup_actualizacion_gui import preguntar_actualizar_gui
    if not preguntar_actualizar_gui(tag_remoto):
        print("[Actualizador] Usuario prefirió no actualizar ahora.")
        return True

    ruta_exe = _descargar_exe(url_exe, callback_progreso)

    if not ruta_exe:
        if callback_progreso:
            callback_progreso("No se pudo descargar la actualización, continuando...")
        return True  # la descarga falló — seguir arrancando normal

    if callback_progreso:
        callback_progreso("Instalando actualización...")

    # La versión se guarda DENTRO de _instalar_y_cerrar(), justo
    # antes de os._exit(0), solo si el instalador se lanzó sin
    # errores — ver el FIX documentado en esa función.
    _instalar_y_cerrar(ruta_exe, tag_nuevo=tag_remoto)
    return False


# =========================================================
# 2. BÚSQUEDA MANUAL POR VOZ
# =========================================================

def _flujo_manual_en_hilo(tag_remoto, url_exe):
    """
    Corre en un hilo daemon — descarga, y cuando termina, habla
    directamente para avisar y pedir confirmación. El asistente
    sigue respondiendo normalmente a otros comandos mientras esto
    descarga en background.

    FIX: antes hablar() se usaba como si devolviera la respuesta del
    usuario (respuesta = hablar(..., permitir_interrupcion=True)), pero
    hablar() es TTS — solo habla, no escucha. El valor siempre era None,
    así que caía al fallback de escuchar_confirmacion(). Esto funcionaba
    por accidente pero era confuso. Ahora se habla primero y se escucha
    después, de forma explícita.
    """
    from tts import hablar
    from voice import escuchar_confirmacion
    from voz_utils import interpretar_confirmacion

    ruta_exe = _descargar_exe(url_exe)

    if not ruta_exe:
        hablar("No pude descargar la actualización, intenta de nuevo más tarde")
        return

    # hablar() solo habla, no escucha. Separar en dos pasos explícitos.
    hablar(f"Ya descargué la actualización {tag_remoto}. ¿La instalo ahora?")
    respuesta = escuchar_confirmacion(timeout=8)

    if interpretar_confirmacion(respuesta, contexto="¿Instalo la actualización?") is True:
        hablar("Instalando, el asistente se va a cerrar")
        # La versión se guarda DENTRO de _instalar_y_cerrar(), justo
        # antes de os._exit(0) — ver el FIX documentado ahí. Ya no
        # hace falta llamar a guardar_version_local() acá aparte.
        _instalar_y_cerrar(ruta_exe, tag_nuevo=tag_remoto)
        # Si _instalar_y_cerrar retorna (no debería, hace os._exit),
        # avisar que algo falló:
        hablar("Hubo un problema con la instalación")
    else:
        hablar("Entendido, la instalaré en otro momento")


def buscar_actualizacion_ahora(valor=None):
    """
    Acción de tool para buscar actualizaciones por voz de forma
    inmediata (sin esperar a la próxima vez que se abra el
    asistente). Devuelve (éxito, mensaje) — mismo patrón que el
    resto de tools.

    Descarga en background (el asistente sigue disponible para otros
    comandos mientras tanto) y, cuando termina, el propio hilo avisa
    por voz y pide confirmación — el usuario inició este pedido por
    voz, así que responder por voz acá tiene sentido (a diferencia de
    la verificación automática al arrancar, que ahora es visual —
    ver verificar_actualizacion_arranque más arriba).
    """
    from tts import hablar as _hablar

    _hablar("Buscando actualizaciones...")

    tag_remoto, url_exe = _consultar_release()

    if not tag_remoto:
        return False, "No pude conectarme a GitHub para buscar actualizaciones"

    tag_local = obtener_version_local()

    # _hay_version_nueva() devuelve False cuando no hay versión local
    # registrada (tag_local == "") — ver su propio comentario ("sin
    # versión local registrada → siempre hay algo nuevo... ver el
    # manejo de primera vez en cada camino"). Ese "manejo de primera
    # vez" existe en verificar_actualizacion_arranque() (más arriba
    # en este mismo archivo) y también acá: sin versión local, se
    # asume que el .exe que se está corriendo YA es la última
    # release (no hay forma de saber lo contrario), se registra, y
    # se informa como al día — así la PRÓXIMA vez que se compare, la
    # comparación ya es real.
    if not tag_local:
        print(f"[Actualizador] Sin versión local registrada — registrando versión actual: {tag_remoto}")
        guardar_version_local(tag_remoto)
        return True, "Ya tienes la última versión instalada"

    if not _hay_version_nueva(tag_remoto, tag_local):
        return True, "Ya tienes la última versión instalada"

    _hablar(f"Hay una versión nueva disponible: {tag_remoto}. Descargando en background, te aviso cuando esté lista.")

    threading.Thread(
        target=_flujo_manual_en_hilo,
        args=(tag_remoto, url_exe),
        daemon=True,
    ).start()

    return True, None  # el mensaje ya se habló directamente arriba