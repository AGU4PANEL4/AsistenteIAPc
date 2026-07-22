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

def _instalar_y_cerrar(ruta_exe):
    """
    Ejecuta el instalador descargado, en modo SILENCIOSO y
    automático, y cierra el asistente. El instalador de Inno Setup
    corre de forma independiente, así que el asistente puede
    cerrarse sin esperar a que termine.

    FIX/NUEVO: antes esto lanzaba el instalador SIN ningún flag, lo
    que abría el wizard completo de Inno Setup (bienvenida, carpeta
    de destino, tareas, página de "listo para instalar", página de
    fin) — el usuario tenía que volver a pasar por TODO eso para lo
    que se suponía era una actualización automática ya confirmada
    antes (en el diálogo de preguntar_actualizar_gui). Ahora se usa:

      /VERYSILENT          -> sin ninguna ventana del wizard
      /SUPPRESSMSGBOXES     -> los MsgBox del script (ver
                               instalador.iss, InitializeSetup)
                               responden con su valor por defecto en
                               vez de esperar un clic que nunca va a
                               llegar
      /NORESTART            -> nunca reiniciar Windows solo
      /CLOSEAPPLICATIONS     -> cierra automáticamente cualquier app
                               que tenga abiertos los archivos a
                               reemplazar (ver AppMutex/
                               CloseApplications en instalador.iss)
      /RESTARTAPPLICATIONS  -> reabre el asistente solo al terminar
                               (ver el segundo [Run] en
                               instalador.iss, condicionado a
                               WizardSilent)

    FIX/NUEVO: además, justo antes de lanzar el instalador se libera
    el mutex de instancia única (ver instancia.py) en vez de confiar
    en que sys.exit(0) + el proceso muriendo del todo alcance a
    tiempo. Antes era una carrera: si el proceso (con pygame,
    faster-whisper, etc. cargados) tardaba más de lo esperado en
    terminar de cerrarse, el instalador arrancaba y su chequeo
    CheckForMutexes('AsistenteIA_Running') todavía encontraba el
    mutex vivo, mostrando "el asistente parece estar corriendo,
    ¿continuar de todas formas?" en medio de lo que debía ser 100%
    automático. Liberando el mutex nosotros mismos, de forma
    explícita, esto deja de depender de ningún timing.
    """
    try:
        print(f"[Actualizador] Ejecutando instalador (silencioso): {ruta_exe}")
        log.info(f"Ejecutando instalador de actualización (silencioso): {ruta_exe}")

        from instancia import liberar as _liberar_mutex
        _liberar_mutex()

        subprocess.Popen(
            [
                str(ruta_exe),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CLOSEAPPLICATIONS",
                "/RESTARTAPPLICATIONS",
            ],
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )

        # margen para que el instalador arranque y tome el control
        # antes de que el proceso del asistente se cierre — se
        # aumenta de 1s a 2s como colchón extra (el mutex ya se
        # liberó arriba, así que esto ya NO es lo único que evita el
        # falso aviso de "instancia corriendo", solo un margen extra
        # de cortesía)
        time.sleep(2)

        sys.exit(0)

    except Exception as e:
        print(f"[Actualizador] No pude ejecutar el instalador: {e}")
        log.exception("Error ejecutando el instalador de actualización")


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
               hizo sys.exit(0) antes de llegar a retornar esto; se
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

    # FIX: antes esto nunca se llamaba en el camino real de
    # actualización (solo en la rama de "primera ejecución" más
    # arriba) — config.json seguía con la versión VIEJA después de
    # instalar, así que el próximo arranque (ya con el .exe nuevo)
    # comparaba contra esa versión vieja, detectaba "hay una versión
    # nueva" otra vez, y volvía a ofrecer instalar lo que ya se
    # acababa de instalar — un bucle sin fin. Se guarda ACÁ, antes de
    # instalar (después de esto el proceso se cierra con
    # sys.exit(0), así que es el último punto posible para hacerlo).
    guardar_version_local(tag_remoto)

    _instalar_y_cerrar(ruta_exe)
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
    """
    from tts import hablar
    from voice import escuchar_confirmacion
    from voz_utils import interpretar_confirmacion

    ruta_exe = _descargar_exe(url_exe)

    if not ruta_exe:
        hablar("No pude descargar la actualización, intenta de nuevo más tarde")
        return

    respuesta = hablar(
        f"Ya descargué la actualización {tag_remoto}. ¿La instalo ahora?",
        permitir_interrupcion=True,
    )
    if respuesta is None:
        respuesta = escuchar_confirmacion(timeout=8)

    if interpretar_confirmacion(respuesta, contexto="¿Instalo la actualización?") is True:
        hablar("Instalando, el asistente se va a cerrar")
        # FIX: mismo motivo que en verificar_actualizacion_arranque —
        # sin esto, el próximo arranque (ya con la versión nueva
        # instalada) seguía comparando contra la versión vieja
        # guardada en config.json y volvía a ofrecer la misma
        # actualización que se acaba de instalar.
        guardar_version_local(tag_remoto)
        _instalar_y_cerrar(ruta_exe)
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

    # FIX/NUEVO: _hay_version_nueva() devuelve False cuando no hay
    # versión local registrada (tag_local == "") — ver su propio
    # comentario ("sin versión local registrada → siempre hay algo
    # nuevo... ver el manejo de primera vez en cada camino"). Ese
    # "manejo de primera vez" existía en
    # verificar_actualizacion_arranque() (más arriba en este mismo
    # archivo) pero NUNCA se agregó acá — así que este comando
    # respondía "Ya tienes la última versión instalada" sin ninguna
    # base real, y como tampoco registraba ninguna versión, el
    # problema se repetía CADA VEZ que se pedía "busca
    # actualizaciones", dejando el comando efectivamente roto para
    # siempre en cualquier instalación que llegara a este código
    # antes de que el chequeo automático del arranque llegara a
    # registrar una versión (ej. primer arranque sin internet, y
    # recién más tarde el usuario pide buscar actualizaciones por voz
    # una vez que la conexión volvió). Mismo criterio que en
    # verificar_actualizacion_arranque(): sin versión local, se
    # asume que el .exe que se está corriendo YA es la última
    # release (no hay forma de saber lo contrario), se registra, y
    # se informa como al día — pero ahora sí queda una versión
    # guardada, así que la PRÓXIMA vez que se compare, la comparación
    # ya es real.
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