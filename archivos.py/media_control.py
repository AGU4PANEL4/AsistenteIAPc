import ctypes
import time
import re
import win32gui
import win32con
import win32process
import win32api
import psutil
import pyautogui
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume, ISimpleAudioVolume

# =========================================================
# TECLAS MULTIMEDIA
# =========================================================

VK_MEDIA_PLAY_PAUSE  = 0xB3
VK_MEDIA_NEXT_TRACK  = 0xB0
VK_MEDIA_PREV_TRACK  = 0xB1
VK_VOLUME_MUTE       = 0xAD
VK_VOLUME_DOWN       = 0xAE
VK_VOLUME_UP         = 0xAF

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP       = 0x0002

# =========================================================
# SMTC — API MODERNA DE WINDOWS PARA CONTROL MULTIMEDIA
# Es la misma API que usan los botones de medios del teclado
# y el centro multimedia de Windows. A diferencia de simular
# teclas o mandar mensajes a una ventana, esto NO depende del
# foco ni de encontrar la ventana correcta, así que funciona
# aunque haya un juego en pantalla completa exclusiva o
# corriendo como administrador (que es justo donde fallaban
# las teclas multimedia simuladas, por las restricciones de
# UIPI de Windows entre procesos con distintos privilegios).
#
# Requiere: pip install winsdk
# =========================================================

try:
    import asyncio
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _SmtcManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as _SmtcStatus,
    )
    SMTC_DISPONIBLE = True
except ImportError:
    SMTC_DISPONIBLE = False
    print("[MEDIA] winsdk no está instalado (pip install winsdk). "
          "Usando solo el método de respaldo con teclas multimedia.")

# YouTube no tiene su propio AppUserModelId — corre adentro del
# navegador, así que para reconocer "youtube" hay que buscar entre
# las sesiones que vienen de un navegador, no por nombre exacto.
# FIX: antes este set tenía nombres de archivo .exe ("operagx.exe",
# "chrome.exe"...), pero el AppUserModelId (AUMID) que reporta SMTC
# para navegadores NO es el nombre del .exe — es un identificador
# estructurado distinto. Por ejemplo, Opera GX se reporta como
# "OperaSoftware.OperaGXWebBrowser.<algo>", nunca como "operagx.exe".
# Con la comparación exacta anterior, _smtc_es_navegador() devolvía
# SIEMPRE False para Opera GX (y probablemente para otros navegadores
# reales también), así que nunca se encontraba la sesión de YouTube
# por esta vía — quedaba oculto porque antes el código caía a "la
# sesión activa del sistema" como fallback (causando el bug de
# reanudar Spotify en vez de YouTube). Al arreglar ESE bug, este quedó
# expuesto: ya no había fallback, pero la detección de navegador
# tampoco funcionaba, entonces no encontraba YouTube de ninguna forma.
#
# Ahora se compara por SUBSTRING de fragmentos típicos del AUMID real
# de cada navegador, que sí aparecen sin importar el formato exacto
# del identificador completo.
NAVEGADORES_AUMID_FRAGMENTOS = (
    "chrome", "msedge", "edge", "opera", "firefox",
    "brave", "vivaldi", "chromium",
)


def _smtc_es_navegador(sesion):
    try:
        aumid = (sesion.source_app_user_model_id or "").lower()
        return any(frag in aumid for frag in NAVEGADORES_AUMID_FRAGMENTOS)
    except Exception:
        return False


async def _smtc_buscar_sesion_navegador(sesiones):
    """
    Entre las sesiones de navegador, prioriza la que esté
    reproduciendo en este momento (puede haber varias pestañas
    con video pausado). Si ninguna está reproduciendo, usa la
    primera sesión de navegador que encuentre.
    """
    candidatos = [s for s in sesiones if _smtc_es_navegador(s)]

    if not candidatos:
        return None

    for s in candidatos:
        try:
            info = s.get_playback_info()
            if info and info.playback_status == _SmtcStatus.PLAYING:
                return s
        except Exception:
            pass

    return candidatos[0]


async def _smtc_accion_async(accion, nombre_app=None):

    manager  = await _SmtcManager.request_async()
    sesiones = list(manager.get_sessions())

    # DIAGNÓSTICO: si se pidió una app específica, mostrar qué
    # sesiones detecta Windows en este momento. Esto es clave para
    # saber si el problema es que no hay ninguna sesión (el video
    # nunca se reprodujo) o que hay varias y se está agarrando la
    # que no es (ej: TikTok en vez de YouTube, mismo navegador).
    if nombre_app:
        try:
            resumen = []
            for s in sesiones:
                aumid = s.source_app_user_model_id or "?"
                try:
                    info   = s.get_playback_info()
                    estado = info.playback_status if info else "?"
                except Exception:
                    estado = "?"
                resumen.append(f"{aumid}={estado}")
            print(f"[SMTC] Buscando '{nombre_app}' — {len(sesiones)} sesión(es): {resumen}")
        except Exception as e:
            print("[SMTC] No pude listar sesiones:", e)

    sesion_obj  = None
    app_pedida_no_encontrada = False

    if nombre_app:
        nombre_limpio = nombre_app.lower()

        if "youtube" in nombre_limpio:
            sesion_obj = await _smtc_buscar_sesion_navegador(sesiones)
        else:
            # buscar la sesión por AppUserModelId (ej: spotify.exe)
            for s in sesiones:
                try:
                    aumid = (s.source_app_user_model_id or "").lower()
                    if nombre_limpio in aumid:
                        sesion_obj = s
                        break
                except Exception:
                    pass

        # FIX: el bug real era acá. Si el usuario pidió una app
        # EXPLÍCITA (ej: "reanuda youtube") y no se encontró su sesión
        # SMTC específica, el código antes caía a "usar la sesión
        # activa del sistema" (manager.get_current_session()) sin
        # importar qué app era esa sesión. Si en ese momento la
        # sesión activa reportada por Windows era Spotify (ej: porque
        # fue la última en sonar, o tiene el foco de medios), SMTC
        # "tenía éxito" pausando/reanudando SPOTIFY en vez de YouTube,
        # y _control_reproduccion nunca llegaba a intentar el método
        # de respaldo correcto (_controlar_youtube), porque el método
        # SMTC ya había devuelto True.
        #
        # Ahora, si se pidió una app explícita y no se encontró su
        # sesión, se marca como "no encontrada" y NO se usa ningún
        # fallback de sesión genérica — se deja que SMTC falle limpio,
        # para que _control_reproduccion pase al siguiente método
        # (_controlar_spotify / _controlar_youtube /
        # _controlar_cualquier_reproductor), que sí busca
        # específicamente esa app y no otra.
        if not sesion_obj:
            app_pedida_no_encontrada = True

    # si no se especificó ninguna app, usar la sesión activa del
    # sistema como antes — ahí sí es correcto ser permisivo
    if not sesion_obj and not nombre_app:
        try:
            sesion_obj = manager.get_current_session()
        except Exception:
            sesion_obj = None

        if not sesion_obj and sesiones:
            sesion_obj = sesiones[0]

    if not sesion_obj or app_pedida_no_encontrada:
        return False

    try:
        if accion == "play_pause":
            return bool(await sesion_obj.try_toggle_play_pause_async())
        if accion == "next":
            return bool(await sesion_obj.try_skip_next_async())
        if accion == "prev":
            return bool(await sesion_obj.try_skip_previous_async())
    except Exception as e:
        print("[SMTC] Error controlando sesión:", e)

    return False


def _smtc_controlar(accion, nombre_app=None):
    """Intenta controlar la reproducción vía SMTC. False si no se pudo."""
    if not SMTC_DISPONIBLE:
        return False
    try:
        return asyncio.run(_smtc_accion_async(accion, nombre_app))
    except Exception as e:
        print("[SMTC] Error:", e)
        return False

def _enviar_tecla_multimedia(vk):
    """
    Envía tecla multimedia a nivel de sistema usando SendInput.
    Funciona incluso con juegos en pantalla completa porque
    opera al mismo nivel que el hardware del teclado.
    """
    import ctypes

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk",         ctypes.c_ushort),
            ("wScan",       ctypes.c_ushort),
            ("dwFlags",     ctypes.c_ulong),
            ("time",        ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        class _INPUT(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT)]
        _anonymous_ = ("_input",)
        _fields_    = [("type", ctypes.c_ulong), ("_input", _INPUT)]

    INPUT_KEYBOARD     = 1
    KEYEVENTF_KEYUP_SI = 0x0002
    KEYEVENTF_EXT_SI   = 0x0001

    def _send(vk_code, flags):
        inp        = INPUT()
        inp.type   = INPUT_KEYBOARD
        inp.ki     = KEYBDINPUT()
        inp.ki.wVk = vk_code
        inp.ki.dwFlags = flags
        ctypes.windll.user32.SendInput(
            1,
            ctypes.byref(inp),
            ctypes.sizeof(INPUT)
        )

    _send(vk, KEYEVENTF_EXT_SI)
    time.sleep(0.05)
    _send(vk, KEYEVENTF_EXT_SI | KEYEVENTF_KEYUP_SI)

# =========================================================
# VOLUMEN DEL SISTEMA
# =========================================================

def _set_volumen_sistema(porcentaje):
    """
    Controla el volumen del sistema usando ctypes puro.
    Sin dependencias externas — funciona en .exe compilado.
    """
    try:
        porcentaje = max(0, min(100, int(porcentaje)))

        import ctypes
        import ctypes.wintypes
        import comtypes
        import comtypes.client

        # GUIDs de la API de Windows (constantes fijas, nunca cambian)
        CLSID_MMDeviceEnumerator = comtypes.GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
        IID_IMMDeviceEnumerator  = comtypes.GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
        IID_IAudioEndpointVolume = comtypes.GUID("{5CDF2C82-841E-4546-9722-0CF74078229A}")

        # definir interfaces minimas con comtypes
        class IMMDevice(comtypes.IUnknown):
            _iid_ = comtypes.GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
            _methods_ = [
                comtypes.STDMETHOD(comtypes.HRESULT, "Activate", [
                    ctypes.POINTER(comtypes.GUID),
                    ctypes.wintypes.DWORD,
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_void_p)
                ]),
            ]

        class IMMDeviceEnumerator(comtypes.IUnknown):
            _iid_ = IID_IMMDeviceEnumerator
            _methods_ = [
                comtypes.STDMETHOD(comtypes.HRESULT, "EnumAudioEndpoints"),
                comtypes.STDMETHOD(comtypes.HRESULT, "GetDefaultAudioEndpoint", [
                    ctypes.wintypes.DWORD,
                    ctypes.wintypes.DWORD,
                    ctypes.POINTER(ctypes.POINTER(IMMDevice))
                ]),
            ]

        # FIX: si antes se llamó a _set_volumen_app() (usa pycaw,
        # que inicializa COM por su cuenta), una segunda llamada a
        # CoInitialize() en el mismo hilo podía lanzar una excepción
        # que terminaba en el except de abajo y abortaba todo el
        # cambio de volumen sin avisar. La ignoramos: si COM ya
        # estaba inicializado, podemos seguir usándolo igual.
        try:
            comtypes.CoInitialize()
        except Exception:
            pass

        enumerator = comtypes.client.CreateObject(
            CLSID_MMDeviceEnumerator,
            interface=IMMDeviceEnumerator
        )

        device_ptr = ctypes.POINTER(IMMDevice)()
        enumerator.GetDefaultAudioEndpoint(0, 1, ctypes.byref(device_ptr))

        # usar pycaw solo para IAudioEndpointVolume que si funciona
        from pycaw.pycaw import IAudioEndpointVolume
        iface = ctypes.c_void_p()
        device_ptr.contents.Activate(
            ctypes.byref(IAudioEndpointVolume._iid_),
            CLSCTX_ALL,
            None,
            ctypes.byref(iface)
        )
        volume = cast(iface, POINTER(IAudioEndpointVolume))
        volume.SetMasterVolumeLevelScalar(porcentaje / 100.0, None)
        return True

    except Exception as e:
        print("[VOLUMEN] Error sistema:", e)
        return False

# =========================================================
# VOLUMEN POR APP
# Usa pycaw AudioSessions para controlar el volumen
# de una app específica en el mezclador de Windows
# =========================================================

def _obtener_pids_por_nombre(nombre_app):
    """Obtiene PIDs de una app por nombre o por cache."""
    import app_finder
    from app_finder import limpiar_nombre as _limpiar

    nombre_limpio = _limpiar(nombre_app)
    pids          = set()

    # por nombre de proceso
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pname = _limpiar((proc.info["name"] or "").replace(".exe", ""))
            if nombre_limpio == pname or nombre_limpio in pname or pname in nombre_limpio:
                pids.add(proc.info["pid"])
        except Exception:
            pass

    # por cache (procesos_cierre y carpetas)
    # FIX: capturar_pids_por_nombre() (acciones_apps.py) corre en un
    # hilo daemon en background después de abrir_app() y puede estar
    # mutando app_finder.cache durante hasta 60 segundos. Si en esa
    # ventana se pide ajustar el volumen de esa misma app, iterar
    # cache.items() directo (sin copia) podía lanzar "RuntimeError:
    # dictionary changed size during iteration" — mismo problema ya
    # arreglado en app_finder.buscar_app(). list(...) toma una copia
    # atómica, evitando el crash sin importar qué esté escribiendo
    # el otro hilo al mismo tiempo.
    for clave, valor in list(app_finder.cache.items()):
        clave_limpia = _limpiar(clave)
        if (
            clave_limpia == nombre_limpio
            or nombre_limpio in clave_limpia
            or clave_limpia in nombre_limpio
        ):
            procesos = {p.lower() for p in valor.get("procesos_cierre", [])}
            carpetas = [c.lower() for c in valor.get("carpetas_detectadas", [])]
            for proc in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    name = (proc.info["name"] or "").lower()
                    exe  = (proc.info.get("exe") or "").lower()
                    if name in procesos or any(c in exe for c in carpetas):
                        pids.add(proc.info["pid"])
                except Exception:
                    pass
            break

    return pids


def _set_volumen_app(nombre_app, porcentaje):
    """
    Pone el volumen de una app específica en el mezclador de Windows.
    porcentaje: 0-100
    """
    try:
        porcentaje = max(0, min(100, int(porcentaje)))
        pids_app   = _obtener_pids_por_nombre(nombre_app)

        if not pids_app:
            print(f"[VOLUMEN APP] No se encontraron procesos para '{nombre_app}'")
            return False

        sesiones   = AudioUtilities.GetAllSessions()
        cambiados  = 0

        for sesion in sesiones:
            if sesion.Process and sesion.Process.pid in pids_app:
                volume = sesion._ctl.QueryInterface(ISimpleAudioVolume)
                volume.SetMasterVolume(porcentaje / 100.0, None)
                print(f"[VOLUMEN APP] {sesion.Process.name()} → {porcentaje}%")
                cambiados += 1

        return cambiados > 0

    except Exception as e:
        print("[VOLUMEN APP] Error:", e)
        return False

# =========================================================
# BUSCAR VENTANA DE YOUTUBE
# =========================================================

NAVEGADORES = {
    "chrome.exe", "opera.exe", "msedge.exe",
    "firefox.exe", "brave.exe", "vivaldi.exe",
    "chromium.exe", "operagx.exe"
}

def _buscar_ventana_youtube():
    resultado = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        titulo = win32gui.GetWindowText(hwnd).lower()
        if "youtube" not in titulo:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc   = psutil.Process(pid)
            if proc.name().lower() in NAVEGADORES:
                resultado.append(hwnd)
        except Exception:
            pass

    win32gui.EnumWindows(callback, None)
    return resultado[0] if resultado else None


def _enfocar_ventana(hwnd):
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        try:
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.BringWindowToTop(hwnd)
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
    time.sleep(0.6)


def _enviar_tecla_a_ventana(hwnd, vk):
    """
    Manda una tecla directamente a una ventana sin necesitar
    que esté en primer plano — funciona con pantalla completa.
    Usa PostMessage que es asíncrono y no requiere foco.
    """
    WM_KEYDOWN = 0x0100
    WM_KEYUP   = 0x0101

    win32api.PostMessage(hwnd, WM_KEYDOWN, vk, 0)
    time.sleep(0.05)
    win32api.PostMessage(hwnd, WM_KEYUP, vk, 0)


def _buscar_ventanas_reproductor(nombre_app):
    """
    Busca ventanas de un reproductor por nombre de app.
    Retorna lista de hwnd incluyendo ventanas no visibles con título.
    """
    from app_finder import limpiar_nombre as _limpiar
    from aliases import traducir_alias

    nombre_real   = traducir_alias(nombre_app)
    nombre_limpio = _limpiar(nombre_real)
    ventanas      = []

    TITULOS_IGNORAR = {
        "default ime", "msctfime ui", "discord overlay",
        "discord overlay input trap", ""
    }

    # obtener PIDs del reproductor
    pids_app = set()

    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            pname = _limpiar((proc.info["name"] or "").replace(".exe", ""))
            if nombre_limpio == pname or nombre_limpio in pname or pname in nombre_limpio:
                pids_app.add(proc.info["pid"])
        except Exception:
            pass

    if not pids_app:
        return []

    def callback(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid not in pids_app:
                return
            titulo = win32gui.GetWindowText(hwnd).lower().strip()
            if titulo in TITULOS_IGNORAR:
                return
            ventanas.append(hwnd)
        except Exception:
            pass

    win32gui.EnumWindows(callback, None)

    # ordenar: visibles primero
    ventanas.sort(key=lambda h: not win32gui.IsWindowVisible(h))
    return ventanas

# =========================================================
# HELPERS PARA DETECTAR APP OBJETIVO
# =========================================================

APPS_YOUTUBE = {"youtube"}
APPS_SPOTIFY = {"spotify"}

def _extraer_app_de_valor(valor):
    """
    Extrae el nombre de app del valor si viene explícito.
    Ej: "spotify" → "spotify", "media" → None
    """
    if not valor or valor.strip().lower() in ("media", ""):
        return None
    v = valor.strip().lower()
    if v == "media":
        return None
    return v


def _es_youtube(nombre_app):
    from app_finder import limpiar_nombre as _limpiar
    if not nombre_app:
        return False
    return any(yt in _limpiar(nombre_app) for yt in APPS_YOUTUBE)


def _es_spotify(nombre_app):
    from app_finder import limpiar_nombre as _limpiar
    if not nombre_app:
        return False
    return any(sp in _limpiar(nombre_app) for sp in APPS_SPOTIFY)


def _resolver_app_objetivo(valor):
    """
    Devuelve (nombre_app, explicito):
      - nombre_app: la app a controlar, o None si no hay ninguna pista.
      - explicito: True si el usuario nombró la app en este mismo
        comando (ej: "reanuda spotify"). En ese caso, si no se logra
        encontrar/controlar esa app, hay que decirlo en vez de caer
        a una tecla multimedia "a ciegas" fingiendo que funcionó.
        False si la app se infirió de la última app usada — ahí sí
        tiene sentido ser más permisivo y probar otras alternativas.
    """
    from memory import memoria
    from aliases import traducir_alias

    nombre = _extraer_app_de_valor(valor)

    if nombre:
        return nombre, True

    ultima = memoria.get("ultima_app", "")
    if ultima:
        return traducir_alias(ultima).lower().strip(), False

    return None, False


def _enfocar_spotify():
    """Busca y enfoca la ventana de Spotify."""
    ventanas = _buscar_ventanas_reproductor("spotify")
    if ventanas:
        _enfocar_ventana(ventanas[0])
        return True
    return False


def _controlar_spotify(accion):
    """
    Controla Spotify usando teclas multimedia a nivel de sistema.
    SendInput funciona aunque haya un juego en pantalla completa.
    Spotify siempre intercepta las teclas multimedia globales,
    pero solo tiene sentido enviarlas si Spotify de verdad está
    corriendo — si no, devolver True sería mentir.
    """
    if not _buscar_ventanas_reproductor("spotify"):
        return False

    VK_MAP = {
        "play_pause": VK_MEDIA_PLAY_PAUSE,
        "next":       VK_MEDIA_NEXT_TRACK,
        "prev":       VK_MEDIA_PREV_TRACK,
    }
    vk = VK_MAP.get(accion)
    if vk:
        _enviar_tecla_multimedia(vk)
    return True


def _controlar_youtube(accion):
    """
    Controla YouTube usando WM_APPCOMMAND al proceso del navegador.
    WM_APPCOMMAND funciona sin necesitar foco y atraviesa pantalla completa.
    """
    hwnd_yt = _buscar_ventana_youtube()
    if not hwnd_yt:
        return False

    WM_APPCOMMAND = 0x0319
    APPCOMMAND_MAP = {
        "play_pause": 0x000E0000,  # APPCOMMAND_MEDIA_PLAY_PAUSE
        "next":       0x000B0000,  # APPCOMMAND_MEDIA_NEXTTRACK
        "prev":       0x000C0000,  # APPCOMMAND_MEDIA_PREVIOUSTRACK
    }

    cmd = APPCOMMAND_MAP.get(accion)
    if cmd:
        win32api.PostMessage(hwnd_yt, WM_APPCOMMAND, hwnd_yt, cmd)
        return True

    return False


def _controlar_cualquier_reproductor(accion, nombre_app=None, permitir_global=True):
    """
    Controla cualquier reproductor usando WM_APPCOMMAND.
    Funciona con VLC, Windows Media Player, etc.

    permitir_global: si es True y no se encuentra ninguna ventana
    de esa app, manda una tecla multimedia global como último
    recurso. Cuando el usuario nombró una app explícita y no se
    encontró, esto debe ser False para no fingir éxito.
    """
    if not nombre_app:
        return False

    ventanas = _buscar_ventanas_reproductor(nombre_app)
    if not ventanas:
        if not permitir_global:
            return False

        # fallback: tecla multimedia global
        VK_MAP = {
            "play_pause": VK_MEDIA_PLAY_PAUSE,
            "next":       VK_MEDIA_NEXT_TRACK,
            "prev":       VK_MEDIA_PREV_TRACK,
        }
        vk = VK_MAP.get(accion)
        if vk:
            _enviar_tecla_multimedia(vk)
        return True

    hwnd = ventanas[0]

    WM_APPCOMMAND = 0x0319
    APPCOMMAND_MAP = {
        "play_pause": 0x000E0000,
        "next":       0x000B0000,
        "prev":       0x000C0000,
    }

    cmd = APPCOMMAND_MAP.get(accion)
    if cmd:
        win32api.PostMessage(hwnd, WM_APPCOMMAND, hwnd, cmd)
        return True

    return False


# =========================================================
# PAUSAR / REANUDAR / SIGUIENTE / ANTERIOR
# Punto único para las cuatro acciones. Si el usuario nombró
# una app explícita (ej: "reanuda spotify", "pausa youtube"),
# SOLO se reporta éxito si de verdad se encontró y se controló
# esa app — si no, se devuelve False para que el asistente lo
# diga, en vez de fingir que funcionó con una tecla a ciegas.
# Si no se nombró ninguna app (solo "pausa"/"siguiente"), se usa
# lo que esté sonando: YouTube > Spotify > tecla multimedia global.
# =========================================================

_VK_POR_ACCION = {
    "play_pause": VK_MEDIA_PLAY_PAUSE,
    "next":       VK_MEDIA_NEXT_TRACK,
    "prev":       VK_MEDIA_PREV_TRACK,
}


def _hay_alguna_sesion_navegador_smtc():
    """
    Verifica si CUALQUIER navegador tiene una sesión SMTC activa en
    este momento — sin importar de qué app se trate. Usado como
    verificación de seguridad antes de confiar en _controlar_youtube
    (ver _controlar_youtube_seguro): si SMTC no reporta NINGUNA
    sesión de navegador, es una señal confiable de que no hay nada
    de media real reproduciéndose en ningún navegador ahora mismo,
    así que mandar una tecla multimedia a una ventana de navegador
    "por si acaso" es más riesgo (puede afectar a otra app) que
    beneficio.
    """
    if not SMTC_DISPONIBLE:
        # sin SMTC disponible no hay forma de verificar — se asume
        # que sí podría haber algo, para no bloquear el método de
        # respaldo en sistemas donde SMTC simplemente no es accesible
        return True

    async def _verificar():
        manager  = await _SmtcManager.request_async()
        sesiones = list(manager.get_sessions())
        return any(_smtc_es_navegador(s) for s in sesiones)

    try:
        return asyncio.run(_verificar())
    except Exception:
        return True


def _controlar_youtube_seguro(accion):
    """
    Como _controlar_youtube, pero solo actúa si hay evidencia de que
    realmente hay una sesión de media activa en algún navegador (vía
    SMTC). Si no hay ninguna sesión SMTC de navegador, se asume que
    la ventana encontrada por título ("...youtube...") no tiene nada
    reproduciéndose de verdad, y se falla limpio en vez de mandar
    WM_APPCOMMAND a ciegas — ver el FIX en _control_reproduccion
    para el caso real que esto evita (la tecla terminando afectando
    a otra app, como Spotify, en vez de no hacer nada).
    """
    if not _hay_alguna_sesion_navegador_smtc():
        return False

    return _controlar_youtube(accion)


def _control_reproduccion(accion, valor=None):

    app, explicito = _resolver_app_objetivo(valor)

    # 1) método moderno (SMTC) — funciona con pantalla completa / admin
    if _smtc_controlar(accion, app):
        return True

    # 2) el usuario nombró una app concreta: ser honestos si no se
    #    encuentra, en vez de caer a una tecla global "a ciegas"
    if explicito:
        if _es_spotify(app):
            return _controlar_spotify(accion)
        if _es_youtube(app):
            # FIX: antes esto llamaba _controlar_youtube() a ciegas en
            # cuanto encontraba una VENTANA con "youtube" en el título
            # — pero una pestaña abierta sin nada reproduciéndose
            # también tiene ese título, y WM_APPCOMMAND mandado a una
            # ventana SIN sesión de media propia puede terminar
            # redirigiéndose al foco de media ACTIVO del sistema (otra
            # app, ej Spotify), en vez de simplemente no hacer nada.
            # Resultado real observado: "reanuda youtube" con una
            # pestaña de YouTube abierta pero pausada/sin cargar nada
            # terminaba reanudando Spotify.
            #
            # Ya pasamos por el paso 1 (SMTC) arriba y NO encontró
            # ninguna sesión de navegador — eso es justamente la señal
            # confiable de "no hay nada de YouTube sonando realmente"
            # (SMTC solo reporta sesiones con metadata real de media).
            # Por eso, si llegamos hasta aquí, ya sabemos que no hay
            # sesión activa — se intenta _controlar_youtube() de todas
            # formas (por si SMTC falló por otro motivo, ej. el
            # navegador no integra con SMTC en esa versión), pero ya
            # no se confía en su resultado a ojos cerrados: si la
            # ventana encontrada no tiene una sesión SMTC propia
            # asociada, no se reporta éxito.
            return _controlar_youtube_seguro(accion)
        return _controlar_cualquier_reproductor(accion, app, permitir_global=False)

    # 3) sin app explícita (o inferida de memoria): comportamiento
    #    permisivo, probando lo más probable que esté sonando
    if _es_spotify(app) and _controlar_spotify(accion):
        return True
    if _es_youtube(app) and _controlar_youtube(accion):
        return True
    if _buscar_ventana_youtube():
        return _controlar_youtube(accion)
    if _buscar_ventanas_reproductor("spotify"):
        return _controlar_spotify(accion)

    _enviar_tecla_multimedia(_VK_POR_ACCION[accion])
    return True


def media_pausa_reanuda(valor=None):
    return _control_reproduccion("play_pause", valor)


def media_siguiente(valor=None):
    return _control_reproduccion("next", valor)


def media_anterior(valor=None):
    return _control_reproduccion("prev", valor)

# =========================================================
# VOLUMEN SISTEMA — SUBIR / BAJAR / SILENCIAR
# =========================================================

def media_subir_volumen(valor=None):
    for _ in range(5):
        _enviar_tecla_multimedia(VK_VOLUME_UP)
        time.sleep(0.03)
    return True


def media_bajar_volumen(valor=None):
    for _ in range(5):
        _enviar_tecla_multimedia(VK_VOLUME_DOWN)
        time.sleep(0.03)
    return True


def media_silenciar(valor=None):
    _enviar_tecla_multimedia(VK_VOLUME_MUTE)
    return True

# =========================================================
# VOLUMEN EXACTO
# valor puede ser:
#   "50"              → sistema al 50%
#   "spotify 50"      → spotify al 50%
#   "50 spotify"      → spotify al 50%
# =========================================================

# =========================================================
# VOLUMEN EXACTO
# valor puede ser:
#   "50"              → sistema al 50%
#   "spotify 50"      → spotify al 50%
#   "50 spotify"      → spotify al 50%
#
# FIX: antes esta función llamaba a hablar() directamente y
# devolvía solo True/False. Ese era exactamente el mismo patrón
# que causó el bug de doble mensaje en activar_startup/
# desactivar_startup (acciones.py): mezclar "quién habla" entre
# la tool y executor.py es frágil — basta que alguien agregue
# este intent a mensajes_exito en executor.py en el futuro (algo
# fácil de hacer sin darse cuenta, ya que la mayoría de tools sí
# están ahí) para que el mensaje se vuelva a duplicar.
#
# Ahora esta función no habla: devuelve (éxito, mensaje) con el
# texto específico de cada caso (volumen de app / volumen del
# sistema / sin número válido), igual que abrir_app, cerrar_app,
# etc. executor.py es el único lugar que llama a hablar() con
# ese mensaje.
# =========================================================

def media_volumen_exacto(valor=None):
    from memory import memoria
    from aliases import traducir_alias

    if not valor:
        return False, None

    valor_str = str(valor).strip().lower()

    # extraer número
    numeros = re.findall(r"\d+", valor_str)
    if not numeros:
        return False, None

    porcentaje = int(numeros[0])

    # extraer nombre de app si viene explícitamente en el valor
    # el intent manda "spotify 70" o solo "70"
    nombre_app = re.sub(r"\d+", "", valor_str).strip()
    nombre_app = re.sub(r"[^a-z\s]", "", nombre_app).strip()
    nombre_app = nombre_app.strip()

    # si no viene nombre explícito, usar última app de memoria
    if not nombre_app:
        ultima = memoria.get("ultima_app", "")
        if ultima:
            nombre_app = traducir_alias(ultima)
            print(f"[VOLUMEN] Usando ultima_app: '{nombre_app}'")

    if nombre_app:
        nombre_app = traducir_alias(nombre_app)
        print(f"[VOLUMEN] App: '{nombre_app}' → {porcentaje}%")

        exito = _set_volumen_app(nombre_app, porcentaje)
        if exito:
            return True, f"Volumen de {nombre_app} al {porcentaje} por ciento"

        # app no encontrada o no tiene sesión de audio → sistema
        print(f"[VOLUMEN] App no encontrada en mixer, ajustando sistema")

    # sin app o app sin sesión → volumen del sistema
    exito = _set_volumen_sistema(porcentaje)
    if exito:
        return True, f"Volumen al {porcentaje} por ciento"

    return False, None