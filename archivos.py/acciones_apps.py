"""
Acciones del asistente relacionadas con APPS y VENTANAS de Windows:
abrir/cerrar/minimizar/maximizar apps, captura y seguimiento de
procesos, alt-tab, alias automático al encontrar una app nueva,
confirmaciones de apertura/rebúsqueda, y navegación (Google/URL/
YouTube).

Separado de acciones_sistema.py (recordatorios, temporizadores,
startup) y de acciones.py (que reexporta todo de ambos para mantener
compatibilidad con el resto del proyecto) — ver el docstring de
acciones_sistema.py para más contexto de por qué se dividió.
"""

import os
import webbrowser
import psutil
import time
import subprocess
import ctypes as _ctypes
from pathlib import Path
from urllib.parse import quote
import win32gui
import win32con
import win32process
import re
import threading
import winshell

from voice import escuchar, escuchar_confirmacion
from tts import hablar
from session import sesion
from memory import memoria, guardar_memoria
from aliases import (
    aliases,
    agregar_alias,
    existe_alias,
    traducir_alias,
    eliminar_alias,
)
from cancelacion import iniciar_cancelacion, detener_cancelacion, fue_cancelado
import app_finder
from voz_utils import elegir_de_lista, interpretar_confirmacion, UMBRAL_SIMILITUD_DIFUSA
from acciones_sistema import normalizar

# =========================================================
# SIMULAR TECLA ALT (vía SendInput)
# Presionar y soltar ALT resetea una bandera interna de Windows
# (LockSetForegroundWindow) que bloquea que un proceso le robe el
# foco a otro — es el mismo truco que usan AutoHotkey y similares.
# Se usa SendInput en vez de keybd_event (API vieja) por ser el
# mismo mecanismo ya probado y funcionando en media_control.py.
#
# FIX: esta función se PERDIÓ al dividir el acciones.py original en
# acciones_sistema.py / acciones_apps.py — vivía en una sección de
# encabezado (antes de la primera marca de sección "# === STARTUP
# ===") que no quedó incluida en ninguno de los dos archivos nuevos.
# Como tiene guion bajo al inicio, tampoco se reexportaba con
# `from acciones_sistema import *`, así que la llamada que sigue
# usándola en _traer_al_frente() más abajo fallaría con NameError en
# tiempo de ejecución. Se recupera acá, en el archivo donde
# realmente se usa.
# =========================================================

VK_MENU              = 0x12
_KEYEVENTF_KEYUP_ALT = 0x0002


class _KEYBDINPUT_ALT(_ctypes.Structure):
    _fields_ = [
        ("wVk",         _ctypes.c_ushort),
        ("wScan",       _ctypes.c_ushort),
        ("dwFlags",     _ctypes.c_ulong),
        ("time",        _ctypes.c_ulong),
        ("dwExtraInfo", _ctypes.POINTER(_ctypes.c_ulong)),
    ]


class _INPUT_ALT(_ctypes.Structure):
    class _U(_ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT_ALT)]
    _anonymous_ = ("_u",)
    _fields_    = [("type", _ctypes.c_ulong), ("_u", _U)]


def _simular_tecla_alt():
    try:
        INPUT_KEYBOARD = 1
        extra = _ctypes.c_ulong(0)

        inp = _INPUT_ALT()
        inp.type   = INPUT_KEYBOARD
        inp.ki     = _KEYBDINPUT_ALT()
        inp.ki.wVk = VK_MENU
        inp.ki.dwExtraInfo = _ctypes.pointer(extra)
        _ctypes.windll.user32.SendInput(1, _ctypes.byref(inp), _ctypes.sizeof(inp))

        inp.ki.dwFlags = _KEYEVENTF_KEYUP_ALT
        _ctypes.windll.user32.SendInput(1, _ctypes.byref(inp), _ctypes.sizeof(inp))
    except Exception as e:
        print("[FOCO] No pude simular ALT:", e)

# =========================================================

def obtener_snapshot():
    snapshot = {}
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            snapshot[proc.info["pid"]] = {
                "name": (proc.info["name"] or "").lower(),
                "exe":  (proc.info.get("exe") or "").lower()
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return snapshot

# =========================================================
# PROCESOS DE SISTEMA / LAUNCHERS A IGNORAR
# =========================================================

PROCESOS_SISTEMA = {
    "cmd.exe", "conhost.exe", "svchost.exe",
    "runtimebroker.exe", "searchhost.exe",
    "opera_crashreporter.exe", "plugins_nms.exe",
    "werfault.exe", "dllhost.exe", "taskhostw.exe",
    "backgroundtaskhost.exe", "sihost.exe",
    "ctfmon.exe", "textinputhost.exe",
}

PROCESOS_LAUNCHERS = {
    "steam.exe", "steamservice.exe", "steamwebhelper.exe",
    "epicgameslauncher.exe", "eosoverlayrenderer-win64-shipping.exe",
    "galaxyclient.exe", "upc.exe", "bethesdanetlauncher.exe",
    "origin.exe", "easteambridge.exe",
}

# =========================================================
# CAPTURAR PIDS
# =========================================================

def capturar_pids_por_nombre(
    nombre_cache,
    ruta_str,
    snapshot_antes,
    espera=10,
    timeout_captura=60
):
    print("=" * 50)
    print("CAPTURA INICIADA:", nombre_cache)
    print("=" * 50)

    time.sleep(espera)

    pids     = set()
    procesos = set()
    carpetas = set()

    if isinstance(snapshot_antes, dict):
        pids_antes    = set(snapshot_antes.keys())
        exes_antes    = {v["exe"]  for v in snapshot_antes.values() if v["exe"]}
        nombres_antes = {v["name"] for v in snapshot_antes.values() if v["name"]}
    else:
        pids_antes    = set(snapshot_antes)
        exes_antes    = set()
        nombres_antes = set()

    nombre_original = normalizar(nombre_cache)
    nombre_base     = nombre_original
    nombre_launcher = nombre_original

    if ruta_str.lower().endswith(".lnk"):
        try:
            acceso          = winshell.shortcut(ruta_str)
            destino         = acceso.path
            nombre_base     = normalizar(Path(destino).stem)
            nombre_launcher = nombre_base
            print("DESTINO:", destino)
        except Exception:
            pass

    data_cache   = app_finder.cache.get(nombre_cache, {})
    carpeta_raiz = data_cache.get("carpeta_raiz", "").lower()
    es_steam     = ruta_str.lower().endswith(".acf")
    # NUEVO: mismo motivo que es_steam — un juego de Epic Games
    # (ver app_finder._escanear_juegos_epic / el tipo "epic" en
    # abrir_app) puede arrancar con un .exe de nombre completamente
    # distinto al título del juego (ej. Fortnite arranca
    # "FortniteClient-Win64-Shipping.exe", pero otros juegos de Epic
    # pueden usar nombres internos sin ningún parecido al nombre que
    # el usuario dijo) — sin este catch-all equivalente al de Steam,
    # capturar_pids_por_nombre() podía no encontrar el proceso real
    # y guardar una entrada de caché sin PIDs ni carpetas detectadas,
    # dejando que un futuro "ciérralo" dependiera por completo del
    # fallback de búsqueda directa entre procesos en ejecución (ver
    # _procesos_en_ejecucion_que_coinciden en este mismo archivo) en
    # vez de tener el dato ya guardado de antes.
    #
    # Se usa el campo "tipo" que abrir_app() ya guardó en la caché
    # (ver TIPO EPIC ahí) en vez de adivinar por el texto de la ruta
    # — es la señal más directa y confiable de que se trata de un
    # juego de Epic. Para Epic, a diferencia de Steam (donde ruta_str
    # es el .acf del manifest, no una carpeta), ruta_str YA ES la
    # carpeta de instalación exacta que el propio Epic Games Launcher
    # reportó para ESTE juego (ver InstallLocation en
    # _escanear_juegos_epic) — más preciso que un substring genérico
    # de marca, que fallaría si el usuario eligió una carpeta de
    # instalación personalizada.
    es_epic      = data_cache.get("tipo") == "epic"
    carpeta_epic = ruta_str.lower() if es_epic else ""

    def es_proceso_ruido(name):
        n = name.lower()
        return n in PROCESOS_SISTEMA or n in PROCESOS_LAUNCHERS

    def es_contaminacion(name, exe):
        exe_lower  = exe.lower()  if exe  else ""
        name_lower = name.lower() if name else ""

        # FIX: si el nombre o exe coincide con la app que estamos abriendo
        # NO lo consideres contaminacion aunque estuviera antes
        # Esto resuelve el caso de Discord que ya estaba corriendo
        # y el snapshot lo filtraba como "ya existia"
        name_norm = normalizar(name.replace(".exe", "")) if name else ""
        es_la_app = (
            nombre_original in name_norm
            or name_norm in nombre_original
            or nombre_base in name_norm
            or name_norm in nombre_base
        )
        if es_la_app:
            return False

        return (
            exe_lower  in exes_antes
            or name_lower in nombres_antes
        )

    def agregar_proceso(pid, name, exe):
        if not name or es_proceso_ruido(name):
            return
        pids.add(pid)
        procesos.add(name)
        if exe:
            carpeta = str(Path(exe).parent).lower()
            if (
                "windows\\system32"          not in carpeta
                and "windows\\syswow64"      not in carpeta
                and "program files\\windows" not in carpeta
            ):
                carpetas.add(carpeta)

    for intento in range(timeout_captura):
        candidatos = []
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                pid  = proc.info["pid"]
                name = proc.info["name"] or ""
                exe  = (proc.info.get("exe") or "").lower()

                if pid in pids_antes:
                    continue
                if es_proceso_ruido(name):
                    continue
                if es_contaminacion(name, exe):
                    continue

                name_norm   = normalizar(name.replace(".exe", ""))
                exe_norm    = normalizar(exe)
                carpeta_exe = str(Path(exe).parent).lower() if exe else ""

                por_nombre = (
                    nombre_original in name_norm
                    or name_norm     in nombre_original
                    or nombre_base   in name_norm
                    or name_norm     in nombre_base
                    or nombre_original in exe_norm
                    or nombre_base     in exe_norm
                )
                por_carpeta       = bool(carpeta_raiz) and carpeta_raiz in exe
                por_steam         = es_steam and "steamapps\\common" in exe
                por_epic          = bool(carpeta_epic) and carpeta_epic in exe
                por_carpeta_nueva = (
                    bool(exe)
                    and "windows\\"               not in carpeta_exe
                    and "program files\\windows"  not in carpeta_exe
                    and any(carpeta_exe.startswith(c[:25]) for c in carpetas)
                )

                if por_nombre or por_carpeta or por_steam or por_epic or por_carpeta_nueva:
                    candidatos.append((pid, name, exe))

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        for pid, name, exe in candidatos:
            if pid not in pids:
                print(f"[NUEVO] {pid} {name}")
                agregar_proceso(pid, name, exe)

        if intento == 30 and not pids:
            print("[ADVERTENCIA] Sin procesos capturados después de 30s")

        time.sleep(1)

    def enum_windows(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc   = psutil.Process(pid)
            name   = proc.name()
            exe    = ""
            try:
                exe = proc.exe()
            except Exception:
                pass
            if es_contaminacion(name, exe):
                return
            name_norm = normalizar(name.replace(".exe", ""))
            exe_norm  = normalizar(exe)
            if (
                nombre_base in name_norm
                or name_norm in nombre_base
                or nombre_base in exe_norm
                or any(c in exe.lower() for c in carpetas)
            ):
                print(f"[VENTANA] {pid} {name}")
                agregar_proceso(pid, name, exe)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    win32gui.EnumWindows(enum_windows, None)

    encontrados = set(pids)
    for _ in range(10):
        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                pid  = proc.pid
                ppid = proc.ppid()
                if pid in encontrados:
                    continue
                if ppid not in encontrados:
                    continue
                name = proc.info["name"] or ""
                exe  = proc.info.get("exe") or ""
                print(f"[HIJO] {pid} {name}")
                encontrados.add(pid)
                agregar_proceso(pid, name, exe)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    clave_real = None
    for clave in app_finder.cache:
        if normalizar(clave) == normalizar(nombre_cache):
            clave_real = clave
            break

    if clave_real is None:
        app_finder.cache[nombre_cache] = {}
        clave_real = nombre_cache

    app_finder.cache[clave_real]["pids"]                = list(pids)
    app_finder.cache[clave_real]["procesos_cierre"]     = list(procesos)
    app_finder.cache[clave_real]["carpetas_detectadas"] = list(carpetas)

    app_finder.guardar_cache()

    print("[CAPTURA TERMINADA]")
    print("PIDS:",     list(pids))
    print("PROCESOS:", list(procesos))
    print("CARPETAS:", list(carpetas))

# =========================================================
# GUARDAR ALIAS SILENCIOSO
# =========================================================

def guardar_alias_silencioso(texto_original, nombre_encontrado):
    texto_norm  = texto_original.lower().strip()
    nombre_norm = nombre_encontrado.lower().strip()
    if texto_norm == nombre_norm:
        return
    if existe_alias(texto_norm):
        return
    agregar_alias(texto_norm, nombre_encontrado)
    print(f"[Alias] Guardado automáticamente: '{texto_norm}' → '{nombre_encontrado}'")

# =========================================================
# ELIMINAR ALIAS
# FIX: antes esto comparaba el nombre recibido contra el diccionario
# de alias con coincidencia EXACTA de texto (ver eliminar_alias en
# aliases.py) — si Whisper transcribía el alias de forma distinta a
# como se guardó, fallaba diciendo "no tenía ningún alias llamado X"
# aunque sí existiera. Ahora delega al flujo GUIADO (ver
# eliminar_alias_guiado en registrar_alias.py): identifica la app,
# muestra sus alias existentes, y deja elegir de esa lista corta en
# vez de requerir el texto exacto de una sola vez.
# =========================================================

def eliminar_alias_app(nombre=None):
    from registrar_alias import eliminar_alias_guiado
    return eliminar_alias_guiado(nombre)

# =========================================================
# CONFIRMACIÓN APERTURA
# =========================================================

def confirmar_apertura(nombre, timeout=8, intentos=3):
    """
    FIX: antes, si la respuesta no era CLARAMENTE sí o no (algo
    frecuente cuando Whisper transcribe mal una confirmación corta —
    ver escuchar_confirmacion en voice.py), el código terminaba TODA
    la sesión directamente ("No entendí" + sesion["activa"] = False).
    Eso significaba que un simple error de transcripción te obligaba
    a decir la wake word de nuevo, en vez de simplemente preguntar
    otra vez. Ahora se reintenta la pregunta hasta `intentos` veces
    antes de rendirse — y solo en ese caso extremo (varias respuestas
    ambiguas seguidas, o ninguna respuesta) se cierra la sesión.

    FIX/NUEVO: antes, cada reintento volvía a decir la pregunta
    COMPLETA ("Encontré {nombre}. ¿Quieres abrirla?") de nuevo,
    incluso justo después de avisar "No te entendí" — el usuario
    terminaba escuchando "Encontré {nombre}" dos veces seguidas para
    la misma confirmación. Ahora esa frase completa se dice UNA sola
    vez, al principio; los reintentos solo repiten la parte de
    sí/no, sin repetir el nombre de la app de nuevo.

    FIX/NUEVO: la respuesta ya no se compara solo contra una lista
    fija de palabras — ver interpretar_confirmacion() en voz_utils.py,
    que además intenta resolver respuestas ambiguas con la IA híbrida
    antes de darse por vencido, cubriendo formas más naturales de
    confirmar o rechazar que cualquier diccionario fijo no alcanzaría
    a prever.
    """

    hablar(f"Encontré {nombre}. ¿Quieres abrirla?")

    for intento in range(intentos):
        inicio = time.time()

        while True:
            respuesta = escuchar_confirmacion(timeout=timeout)
            if respuesta:
                break
            if time.time() - inicio > timeout:
                respuesta = ""
                break

        respuesta = respuesta.lower().strip()

        resultado = interpretar_confirmacion(
            respuesta,
            extras_si=["abrir", "hazlo"],
            contexto=f"¿Quieres abrir {nombre}?",
        )

        if resultado is True:
            sesion["activa"] = True
            return True

        if resultado is False:
            hablar("Cancelado")
            sesion["activa"] = True
            return False

        # ambiguo (ni el match local ni la IA lo resolvieron) o
        # vacío — reintentar, salvo que ya sea el último intento
        # permitido. Ya NO se repite "Encontré {nombre}..." de
        # nuevo, solo se pide aclarar sí/no.
        if intento < intentos - 1:
            if respuesta:
                hablar("No te entendí, ¿la abro sí o no?")
            else:
                hablar("¿La abro sí o no?")

    hablar("No logré entenderte, dejémoslo por ahora")
    sesion["activa"] = True
    return False

# =========================================================
# CONFIRMAR REBUSCAR
# =========================================================

def confirmar_rebuscar(nombre, timeout=8):

    hablar(f"Antes no encontré {nombre}. ¿Quieres que busque de nuevo?")

    inicio = time.time()

    while True:
        respuesta = escuchar_confirmacion(timeout=timeout)
        if respuesta:
            break
        if time.time() - inicio > timeout:
            return False

    respuesta = respuesta.lower().strip()

    # FIX/NUEVO: usa interpretar_confirmacion() (ver voz_utils.py) en
    # vez de solo es_afirmacion() — si la respuesta no calza con
    # ninguna palabra conocida, se le pregunta a la IA qué quiso decir
    # antes de asumir que fue un "no". Un resultado ambiguo (None,
    # ni el match local ni la IA lo resolvieron) se sigue tratando
    # como "no" — mismo comportamiento seguro de antes para el caso
    # en que de verdad no se pudo entender nada.
    resultado = interpretar_confirmacion(
        respuesta,
        extras_si=["busca", "intenta"],
        contexto=f"¿Busco de nuevo {nombre}?",
    )
    return resultado is True

# =========================================================
# PROCESOS
# =========================================================

def obtener_procesos(nombre):
    nombre      = normalizar(nombre)
    encontrados = []
    for p in psutil.process_iter(["name"]):
        try:
            pname = normalizar((p.info["name"] or "").replace(".exe", ""))
            if nombre == pname or nombre in pname or pname in nombre:
                encontrados.append(p)
        except Exception:
            pass
    return encontrados


def esta_abierta(nombre):
    return len(obtener_procesos(nombre)) > 0

# =========================================================
# ENFOCAR
# =========================================================

def traer_al_frente(nombre):
    nombre   = normalizar(nombre)
    ventanas = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc   = psutil.Process(pid)
            pname  = normalizar(proc.name().replace(".exe", ""))
            if nombre == pname or nombre in pname or pname in nombre:
                ventanas.append(hwnd)
        except Exception:
            pass

    win32gui.EnumWindows(callback, None)

    if not ventanas:
        return False

    hwnd = ventanas[0]
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False

# =========================================================
# CERRAR APP — MATCH DIRECTO CONTRA PROCESOS EN EJECUCIÓN
# FIX/NUEVO: cerrar_app() dependía SIEMPRE de que la app estuviera
# en app_finder.cache (quedó ahí por haberse abierto antes con el
# asistente) o de que app_finder.buscar_app() la encontrara
# buscando en disco/registro — si ninguna de las dos cosas pasaba
# (ej. el usuario abrió Chrome a mano con un acceso directo, nunca
# le pidió al asistente que lo abriera, y Chrome tampoco quedó
# indexado en el registro de la forma que buscar_app() espera), la
# función directamente devolvía False sin siquiera revisar si había
# un proceso con ese nombre corriendo ahora mismo — algo que
# Windows sabe al instante, sin necesitar ningún índice propio.
#
# Esta función busca DIRECTO entre los procesos vivos en este
# momento (psutil.process_iter), sin importar quién los abrió ni si
# el asistente los conoce de antes. cerrar_app() la usa PRIMERO,
# antes de tocar caché o disco — si encuentra algo y logra cerrarlo,
# ya está, nunca hace falta la búsqueda lenta en disco. Si no
# encuentra nada (ej. el nombre dicho es un alias que no se parece
# en nada al nombre real del proceso, como "oso" -> "osu!(lazer)"),
# se cae al flujo de siempre sin ningún cambio de comportamiento.
# =========================================================

def _limpiar_nombre_proceso(nombre_proceso):
    """
    Igual que app_finder.limpiar_nombre(), pero primero quita la
    extensión .exe -- si no, "chrome.exe" se limpiaría a "chromeexe"
    (el punto se borra como cualquier símbolo, no se vuelve espacio)
    y nunca matchearía contra "chrome".
    """
    if nombre_proceso.lower().endswith(".exe"):
        nombre_proceso = nombre_proceso[:-4]
    return app_finder.limpiar_nombre(nombre_proceso)


def _procesos_en_ejecucion_que_coinciden(nombre_limpio):
    """
    Devuelve una lista de (pid, nombre_proceso_original) de TODOS los
    procesos actualmente corriendo cuyo nombre coincide con
    `nombre_limpio` -- mismo criterio de coincidencia (exacto o
    substring en cualquier dirección) ya usado en el resto del
    proyecto para este tipo de matching aproximado (ver
    buscar_en_cache en registrar_alias.py, por ejemplo), más un
    respaldo de similitud difusa para variantes con errores menores
    de transcripción.

    Puede devolver varias coincidencias para una sola app (ej. Chrome
    corre con varios procesos "chrome.exe" al mismo tiempo, uno por
    pestaña/proceso hijo) -- cerrar_app() las cierra todas.

    Nunca incluye el propio proceso del asistente, para que este
    mecanismo no pueda terminar cerrándose a sí mismo por un
    matching demasiado amplio.
    """
    if not nombre_limpio or len(nombre_limpio) < 2:
        return []

    propio_pid    = os.getpid()
    coincidencias = []

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["pid"] == propio_pid:
                continue

            nombre_proc = proc.info["name"] or ""
            if not nombre_proc:
                continue

            limpio = _limpiar_nombre_proceso(nombre_proc)
            if not limpio:
                continue

            coincide_directo = (
                nombre_limpio == limpio
                or nombre_limpio in limpio
                or limpio in nombre_limpio
            )
            coincide_difuso = (
                not coincide_directo
                and app_finder.parecido(nombre_limpio, limpio) >= UMBRAL_SIMILITUD_DIFUSA
            )

            if coincide_directo or coincide_difuso:
                coincidencias.append((proc.info["pid"], nombre_proc))

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return coincidencias


def _cerrar_ventanas_de_proceso(pid, timeout=4):
    """
    Manda WM_CLOSE a todas las ventanas visibles de nivel superior que
    pertenezcan a `pid` -- el mismo cierre "amable" que un Alt+F4, que
    le da a la app oportunidad de preguntar "¿guardar cambios?" antes
    de cerrarse, en vez de matarla en seco de una.

    FIX/NUEVO: antes, cerrar_app() iba DIRECTO a proc.terminate() (un
    cierre forzado real en Windows, sin ningún aviso a la app) para
    todo lo que cerraba -- si tenías un Word o Notepad con cambios
    sin guardar y decías "cierra word", los perdías sin ningún aviso,
    ni siquiera la oportunidad de decir que no. Ahora se intenta esto
    PRIMERO; solo si la app no responde sola dentro de `timeout`
    segundos (ver _terminar_pid) se recién se fuerza el cierre.

    Devuelve True si el proceso terminó solo dentro de `timeout`
    segundos. Si el proceso no tiene ninguna ventana visible (típico
    de procesos de fondo/helpers sin UI, ej. steamwebhelper.exe), no
    tiene sentido "cerrar amablemente" -- devuelve False de inmediato
    para que _terminar_pid pase directo al cierre forzado, sin
    esperar nada de más.
    """
    hwnds = []

    def _enum_callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            try:
                _, pid_ventana = win32process.GetWindowThreadProcessId(hwnd)
                if pid_ventana == pid:
                    hwnds.append(hwnd)
            except Exception:
                pass
        return True

    try:
        win32gui.EnumWindows(_enum_callback, None)
    except Exception:
        return False

    if not hwnds:
        return False

    for hwnd in hwnds:
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        except Exception:
            pass

    inicio = time.time()
    while time.time() - inicio < timeout:
        if not psutil.pid_exists(pid):
            return True
        time.sleep(0.2)

    return False


def _terminar_pid(pid):
    """
    Intenta cerrar un proceso por PID, con esta cadena de respaldo:

      1. Cierre AMABLE (WM_CLOSE a sus ventanas, ver
         _cerrar_ventanas_de_proceso) -- le da a la app oportunidad
         de guardar cambios pendientes antes de cerrarse. Solo aplica
         si tiene ventanas visibles; los procesos sin UI pasan de
         largo a este paso sin ninguna espera de más.
      2. terminate() normal (señal de cierre estándar de Windows).
      3. kill() si no respondió a tiempo.
      4. taskkill si hay permisos insuficientes.
      5. PowerShell elevado como último recurso.

    Devuelve True si el proceso quedó cerrado (o ya no existía),
    False si ningún método funcionó.
    """
    if _cerrar_ventanas_de_proceso(pid):
        return True

    try:
        proc = psutil.Process(pid)
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
        return True
    except psutil.NoSuchProcess:
        return True  # ya no existe, considerar éxito
    except (psutil.AccessDenied, Exception):
        try:
            resultado_tk = subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
            )
            if resultado_tk.returncode == 0:
                return True
        except Exception:
            pass

        try:
            subprocess.run(
                ["powershell", "-Command", f"Stop-Process -Id {pid} -Force"],
                capture_output=True,
            )
            return True
        except Exception:
            return False


# =========================================================
# CERRAR APP
# =========================================================

def cerrar_app(nombre):

    nombre_original = nombre

    # FIX: solo lowercase y strip, NO normalizar
    nombre        = nombre.lower().strip()
    nombre_cache  = None
    data          = None

    from app_finder import limpiar_nombre as _limpiar
    nombre_limpio_cache = _limpiar(nombre)

    # =====================================================
    # NUEVO: intentar cerrar DIRECTO por lo que esté corriendo ahora
    # mismo, ANTES de tocar caché o disco — cubre el caso de apps
    # que el usuario abrió por su cuenta (no vía el asistente) y que
    # tampoco quedaron indexadas por una búsqueda anterior. Si esto
    # encuentra y cierra algo, listo — nunca hace falta la búsqueda
    # lenta en disco de más abajo. Ver el comentario detallado en
    # _procesos_en_ejecucion_que_coinciden() más arriba.
    # =====================================================

    coincidencias_directas = _procesos_en_ejecucion_que_coinciden(nombre_limpio_cache)

    if coincidencias_directas:
        print(f"[CERRAR DIRECTO] {nombre_original} -> {coincidencias_directas}")

        cerrado_directo = False
        for pid, nombre_proceso in coincidencias_directas:
            if _terminar_pid(pid):
                cerrado_directo = True
                print(f"[CERRAR DIRECTO OK] {nombre_proceso} (pid {pid})")

        if cerrado_directo:
            # se guarda el alias con el nombre de proceso real (sin
            # .exe) como referencia — no es tan preciso como el
            # nombre_cache que arma buscar_app() (no sabemos la
            # carpeta de instalación ni los demás procesos
            # relacionados), pero acelera la PRÓXIMA vez que se pida
            # abrir/cerrar esta misma app por el mismo nombre hablado
            nombre_referencia = coincidencias_directas[0][1]
            if nombre_referencia.lower().endswith(".exe"):
                nombre_referencia = nombre_referencia[:-4]
            guardar_alias_silencioso(nombre_original, nombre_referencia)

            return True, nombre_original

        # se encontró un proceso con ese nombre pero no se pudo
        # cerrar ninguno (raro — ej. permisos) -> caer al flujo de
        # siempre por si acaso, en vez de rendirse acá directamente

    # FIX: capturar_pids_por_nombre() corre en un hilo daemon en
    # background después de abrir_app() y puede estar agregando o
    # modificando claves de app_finder.cache (incluyendo crear una
    # clave NUEVA) durante hasta 60 segundos. Si en esa ventana se
    # pide cerrar esa misma app, iterar cache.items() directo (sin
    # copia) podía lanzar "RuntimeError: dictionary changed size
    # during iteration" y crashear el comando — mismo problema que
    # ya se arregló en app_finder.buscar_app(). list(...) toma una
    # copia atómica, así que ya no importa si el hilo de captura
    # sigue escribiendo el original mientras este hilo recorre la
    # copia.
    for clave, valor in list(app_finder.cache.items()):
        clave_norm = _limpiar(clave)
        if (
            nombre_limpio_cache == clave_norm
            or nombre_limpio_cache in clave_norm
            or clave_norm in nombre_limpio_cache
        ):
            nombre_cache = clave
            data         = valor
            break

    if not data:
        resultado, _, nombre_cache = app_finder.buscar_app(
            nombre,
            fn_confirmar_rebuscar=confirmar_rebuscar,
            fn_cancelado=fue_cancelado
        )
        if not resultado:
            return False, nombre

        # FIX: usar data de buscar_app directamente
        # antes hacía cache.get(nombre_cache) que devolvía {}
        # porque la app se encontró por disco, no por cache
        data = resultado

        # si tiene procesos en cache, usar esos
        data_cache = app_finder.cache.get(nombre_cache, {})
        if data_cache.get("procesos_cierre"):
            data = data_cache

    # FIX: guardar alias si el nombre original es diferente
    guardar_alias_silencioso(nombre_original, nombre_cache)

    # FIX/NUEVO: bug real — cuando se pide cerrar una app justo después
    # de abrirla, capturar_pids_por_nombre() puede seguir corriendo en
    # background (hasta 60s) y aún no haber guardado nada en
    # "procesos_cierre". En ese caso, data.get("procesos_cierre")
    # devuelve [] vacío, el loop de psutil no matchea nada, cerrados
    # queda False y se reporta "no pude cerrar" — aunque la app SÍ
    # está corriendo. La segunda vez ya funciona porque la captura ya
    # terminó y los procesos ya están guardados.
    #
    # Solución: si procesos_cierre está vacío, construir la lista de
    # procesos a cerrar de otras fuentes disponibles:
    # 1. PIDs guardados en cache (si los hay) → cerrar por PID directo
    # 2. Nombre del ejecutable de la ruta guardada → cerrar por nombre
    # 3. Carpetas detectadas → cerrar por exe path (ya existía)
    #
    # Esto cubre el caso de la primera vez, y también el caso donde
    # la app nunca tuvo captura de procesos (apps simples que se
    # abrieron por ruta directa sin hilo de captura).

    procesos_guardados  = {p.lower() for p in data.get("procesos_cierre", [])}
    carpetas_detectadas = [c.lower() for c in data.get("carpetas_detectadas", [])]
    pids_guardados      = set(data.get("pids", []))

    # si no hay procesos guardados, inferir del ejecutable de la ruta
    if not procesos_guardados and not pids_guardados:
        ruta_str = data.get("ruta", "")
        if ruta_str:
            nombre_exe = Path(ruta_str).name.lower()
            if nombre_exe:
                procesos_guardados.add(nombre_exe)
                print(f"[CERRAR] Sin procesos en cache, usando ejecutable: {nombre_exe}")

    print("CERRAR:", nombre_cache)
    print("PROCESOS:", procesos_guardados)
    print("CARPETAS:", carpetas_detectadas)
    print("PIDs:", pids_guardados)

    cerrados = False

    # primero intentar por PIDs guardados (más preciso que por nombre)
    if pids_guardados:
        for pid in list(pids_guardados):
            if _terminar_pid(pid):
                cerrados = True
                print(f"[CERRAR PID] {pid}")

    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info["name"] or "").lower()
            exe  = (proc.info.get("exe") or "").lower()

            por_nombre  = name in procesos_guardados
            por_carpeta = any(c in exe for c in carpetas_detectadas)

            if not (por_nombre or por_carpeta):
                continue

            print(f"[CERRAR] {proc.info['pid']} {name}")

            if _terminar_pid(proc.info["pid"]):
                cerrados = True
                print(f"[CERRAR OK] {name}")
            else:
                print(f"[CERRAR ERROR] {name}")

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return cerrados, nombre_cache

# =========================================================
# COINCIDENCIAS
# =========================================================

def coincide(proceso, objetivo):
    return normalizar(proceso) == normalizar(objetivo)

# =========================================================
# ABRIR APP
# =========================================================

def abrir_app(nombre):

    nombre_original = nombre

    # FIX: solo lowercase y strip, NO normalizar
    # normalizar() borra espacios y rompe la búsqueda en cache
    # buscar_app ya usa limpiar_nombre internamente
    nombre = traducir_alias(nombre).lower().strip()

    # iniciar escucha de cancelación durante la búsqueda
    iniciar_cancelacion()

    try:
        resultado, desde_cache, nombre_cache = app_finder.buscar_app(
            nombre,
            fn_confirmar_rebuscar=confirmar_rebuscar,
            fn_cancelado=fue_cancelado
        )
    finally:
        detener_cancelacion()

    # verificar si fue cancelado durante la búsqueda
    if fue_cancelado():
        hablar("Cancelado")
        return False, nombre

    if not desde_cache and resultado:
        confirmar = confirmar_apertura(nombre_cache)
        if not confirmar:
            return False, nombre
        guardar_alias_silencioso(nombre_original, nombre_cache)

    if not resultado:
        return False, nombre

    ruta     = resultado["ruta"] if isinstance(resultado, dict) else resultado
    ruta_str = str(ruta)
    tipo     = resultado.get("tipo", "normal")

    # =====================================
    # TIPO STEAM
    # =====================================

    if tipo == "steam":

        if not desde_cache:
            app_finder.cache[nombre_cache] = {
                "ruta":                ruta_str,
                "appid":               resultado.get("appid"),
                "exe_name":            resultado.get("exe_name"),
                "tipo":                "steam",
                "procesos_cierre":     [],
                "pids":                [],
                "carpetas_detectadas": []
            }
            app_finder.guardar_cache()

        appid = resultado.get("appid")

        if appid:
            snapshot = obtener_snapshot()
            os.startfile(f"steam://rungameid/{appid}")

            threading.Thread(
                target=capturar_pids_por_nombre,
                args=(nombre_cache, ruta_str, snapshot),
                kwargs={"espera": 15, "timeout_captura": 60},
                daemon=True
            ).start()

            return True, nombre_cache

    # =====================================
    # TIPO EPIC
    # NUEVO: mismo patrón que TIPO STEAM de arriba — juegos de Epic
    # Games Store (Fortnite, etc, ver _escanear_juegos_epic en
    # app_finder.py) se lanzan por el protocolo propio de Epic en vez
    # de ejecutar el .exe del juego directamente. Varios juegos de
    # Epic (Fortnite incluido) usan Easy Anti-Cheat u otras
    # protecciones que EXIGEN iniciarse a través del launcher —
    # ejecutar el .exe directo lo abre un instante y lo cierra con un
    # error de anti-cheat en vez de jugarlo de verdad, que era
    # justamente el problema reportado.
    # =====================================

    if tipo == "epic":

        if not desde_cache:
            app_finder.cache[nombre_cache] = {
                "ruta":                ruta_str,
                "app_name":            resultado.get("app_name"),
                "exe_name":            resultado.get("exe_name"),
                "tipo":                "epic",
                "procesos_cierre":     [],
                "pids":                [],
                "carpetas_detectadas": []
            }
            app_finder.guardar_cache()

        app_name = resultado.get("app_name")

        if app_name:
            snapshot = obtener_snapshot()
            os.startfile(f"com.epicgames.launcher://apps/{app_name}?action=launch&silent=true")

            threading.Thread(
                target=capturar_pids_por_nombre,
                args=(nombre_cache, ruta_str, snapshot),
                # NUEVO: espera más larga que Steam (15s/60s) — Epic
                # Games Launcher, si no estaba ya abierto, tarda más
                # en arrancar y autenticar antes de lanzar el juego
                # de verdad; capturar_pids_por_nombre reintenta en un
                # rango, así que solo hace falta darle más margen
                # total para no dejar de capturar el PID real por
                # cortar la búsqueda demasiado pronto.
                kwargs={"espera": 25, "timeout_captura": 90},
                daemon=True
            ).start()

            return True, nombre_cache

    # =====================================
    # carpeta_raiz = carpeta del exe real
    # =====================================

    carpeta_real = ""
    try:
        if ruta_str.lower().endswith(".lnk"):
            acceso       = winshell.shortcut(ruta_str)
            destino      = acceso.path
            carpeta_real = str(Path(destino).parent).lower()
        else:
            carpeta_real = str(Path(ruta_str).parent).lower()
    except Exception:
        carpeta_real = str(Path(ruta_str).parent).lower()

    if not desde_cache:
        from app_finder import limpiar_nombre as _limpiar

        # FIX: buscar si ya existe una entrada con datos útiles
        # para no sobreescribir procesos_cierre guardados
        clave_existente = None
        for clave in app_finder.cache:
            if _limpiar(clave) == _limpiar(nombre_cache):
                clave_existente = clave
                break

        if clave_existente:
            data_existente = app_finder.cache[clave_existente]
            # solo actualizar ruta si no tiene procesos guardados
            if not data_existente.get("procesos_cierre"):
                app_finder.cache[clave_existente]["ruta"]         = ruta_str
                app_finder.cache[clave_existente]["carpeta_raiz"] = carpeta_real
            nombre_cache = clave_existente
            print("Cache existente preservado:", nombre_cache)
        else:
            app_finder.cache[nombre_cache] = {
                "ruta":               ruta_str,
                "carpeta_raiz":       carpeta_real,
                "procesos_cierre":    [],
                "pids":               [],
                "tipo":               "normal"
            }
            print("Guardada en cache:", nombre_cache)

        app_finder.guardar_cache()
        app_finder.quitar_de_no_encontradas(nombre)

    print("Ruta encontrada:", ruta_str)

    snapshot = obtener_snapshot()

    # =====================================
    # EJECUTAR
    # =====================================

    ejecutado_por_steam = False

    try:
        if "steamapps" in ruta_str.lower():
            carpeta   = os.path.dirname(ruta_str)
            steamapps = None

            while True:
                posible = os.path.dirname(carpeta)
                if os.path.basename(posible).lower() == "steamapps":
                    steamapps = posible
                    break
                if posible == carpeta:
                    break
                carpeta = posible

            if steamapps:
                carpeta_juego = os.path.basename(
                    os.path.dirname(ruta_str)
                ).lower()

                for archivo in os.listdir(steamapps):
                    if not archivo.startswith("appmanifest_"):
                        continue
                    ruta_manifest = os.path.join(steamapps, archivo)
                    try:
                        with open(ruta_manifest, encoding="utf-8", errors="ignore") as f:
                            contenido = f.read().lower()
                        if carpeta_juego in contenido:
                            appid = (
                                archivo
                                .replace("appmanifest_", "")
                                .replace(".acf", "")
                            )
                            print("Steam AppID:", appid)
                            os.startfile(f"steam://rungameid/{appid}")
                            ejecutado_por_steam = True

                            threading.Thread(
                                target=capturar_pids_por_nombre,
                                args=(nombre_cache, ruta_str, snapshot),
                                kwargs={"espera": 25, "timeout_captura": 60},
                                daemon=True
                            ).start()

                            return True, nombre_cache

                    except Exception as e:
                        print("Error leyendo manifest:", e)

    except Exception as e:
        print("Error Steam:", e)

    # =====================================
    # APERTURA NORMAL
    # =====================================

    if not ejecutado_por_steam:
        if ruta_str.endswith(".lnk"):
            subprocess.Popen(f'start "" "{ruta_str}"', shell=True)
        else:
            subprocess.Popen(ruta_str, shell=True)

        threading.Thread(
            target=capturar_pids_por_nombre,
            args=(nombre_cache, ruta_str, snapshot),
            kwargs={"espera": 20, "timeout_captura": 60},
            daemon=True
        ).start()

    return True, nombre_cache

# =========================================================
# RECAPTURAR APP
# =========================================================

def recapturar_app(nombre_cache):

    clave_real = None
    data       = None

    # FIX: misma razón que en cerrar_app() — ver ese comentario para
    # el detalle completo. list(...) evita un posible crash si el
    # hilo de captura en background está mutando el cache al mismo
    # tiempo que esta función lo recorre.
    for clave, valor in list(app_finder.cache.items()):
        if normalizar(clave) == normalizar(nombre_cache):
            clave_real = clave
            data       = valor
            break

    if not data:
        print(f"[RECAPTURA] No se encontró '{nombre_cache}' en cache")
        return False

    app_finder.cache[clave_real]["pids"]                = []
    app_finder.cache[clave_real]["procesos_cierre"]     = []
    app_finder.cache[clave_real]["carpetas_detectadas"] = []
    app_finder.guardar_cache()

    print(f"[RECAPTURA] Cache limpiado para '{clave_real}'")
    return abrir_app(clave_real)

# =========================================================
# NAVEGADOR
# =========================================================

def buscar_google(busqueda):
    url = "https://www.google.com/search?q=" + quote(busqueda)
    webbrowser.open(url)
    return True


def abrir_url(url):
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    return True


def abrir_youtube(busqueda):
    url = "https://www.youtube.com/results?search_query=" + quote(busqueda)
    webbrowser.open(url)
    return True


# =========================================================
# MINIMIZAR APP
# =========================================================

def _obtener_pids_app(nombre):
    """
    Obtiene PIDs de una app por:
    1. Nombre de proceso directo
    2. procesos_cierre y carpetas_detectadas en cache
    3. carpeta_raiz del cache como último recurso
    """
    from app_finder import limpiar_nombre as _limpiar
    from aliases import traducir_alias

    # resolver alias antes de buscar
    nombre_real   = traducir_alias(nombre)
    nombre_limpio = _limpiar(nombre_real)
    pids_app      = set()

    # snapshot único para no iterar procesos múltiples veces
    todos_procs = list(psutil.process_iter(["pid", "name", "exe"]))

    # ---- 1. por nombre de proceso directo ----
    for proc in todos_procs:
        try:
            pname = _limpiar((proc.info["name"] or "").replace(".exe", ""))
            if (
                nombre_limpio == pname
                or nombre_limpio in pname
                or pname in nombre_limpio
            ):
                pids_app.add(proc.info["pid"])
        except Exception:
            pass

    # ---- 2. por cache (procesos_cierre + carpetas_detectadas) ----
    # FIX: misma razón que en cerrar_app() — list(...) evita un
    # posible crash si el hilo de captura en background está
    # mutando el cache al mismo tiempo que esta función lo recorre
    # (ej. minimizar/maximizar una app justo después de abrirla).
    for clave, valor in list(app_finder.cache.items()):
        clave_limpia = _limpiar(clave)
        if (
            clave_limpia == nombre_limpio
            or nombre_limpio in clave_limpia
            or clave_limpia in nombre_limpio
        ):
            procesos = {p.lower() for p in valor.get("procesos_cierre", [])}
            carpetas = [c.lower() for c in valor.get("carpetas_detectadas", [])]

            for proc in todos_procs:
                try:
                    name = (proc.info["name"] or "").lower()
                    exe  = (proc.info.get("exe") or "").lower()
                    if name in procesos or any(c in exe for c in carpetas):
                        pids_app.add(proc.info["pid"])
                except Exception:
                    pass

            # ---- 3. carpeta_raiz como fallback ----
            if not pids_app:
                carpeta_raiz = valor.get("carpeta_raiz", "").lower()
                if carpeta_raiz:
                    for proc in todos_procs:
                        try:
                            exe = (proc.info.get("exe") or "").lower()
                            if carpeta_raiz in exe:
                                pids_app.add(proc.info["pid"])
                        except Exception:
                            pass

            break

    return pids_app


def _buscar_ventanas_por_nombre(nombre, incluir_ocultas=False):
    """Helper: busca ventanas por nombre de proceso o procesos en cache."""
    pids_app = _obtener_pids_app(nombre)
    ventanas = []

    if not pids_app:
        return ventanas

    TITULOS_IGNORAR = {
        "default ime", "msctfime ui", "discord overlay",
        "discord overlay input trap", ""
    }

    def callback(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid not in pids_app:
                return

            titulo  = win32gui.GetWindowText(hwnd).lower().strip()
            visible = win32gui.IsWindowVisible(hwnd)

            if titulo in TITULOS_IGNORAR:
                return

            if visible or (incluir_ocultas and titulo):
                ventanas.append((hwnd, visible))
        except Exception:
            pass

    win32gui.EnumWindows(callback, None)

    ventanas.sort(key=lambda x: not x[1])

    return [hwnd for hwnd, _ in ventanas]


def minimizar_app(nombre):

    nombre  = nombre.lower().strip()
    ventanas = _buscar_ventanas_por_nombre(nombre)

    if not ventanas:
        return False, nombre

    for hwnd in ventanas:
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        except Exception:
            pass

    return True, nombre


# =========================================================
# MAXIMIZAR / TRAER AL FRENTE
# =========================================================

def maximizar_app(nombre):

    nombre = nombre.lower().strip()

    for intento in range(3):

        ventanas = _buscar_ventanas_por_nombre(nombre, incluir_ocultas=False)

        if not ventanas:
            ventanas = _buscar_ventanas_por_nombre(nombre, incluir_ocultas=True)

        if ventanas:
            break

        if intento < 2:
            time.sleep(1)

    if not ventanas:
        return False, nombre

    hwnd = ventanas[0]

    try:
        import ctypes
        import subprocess

        user32  = ctypes.windll.user32

        # obtener PID de la ventana
        _, pid_ventana = win32process.GetWindowThreadProcessId(hwnd)

        # restaurar si estaba minimizado
        if win32gui.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5)   # SW_SHOW

        # FIX: el AttachThreadInput de antes pegaba el hilo de NUESTRO
        # script con el de la ventana objetivo. Eso no sirve de nada —
        # lo que Windows necesita es que el hilo de la ventana objetivo
        # quede "pegado" al hilo de la ventana que TIENE el foco en ese
        # momento (el juego), porque así Windows lo trata como si la
        # propia ventana en foco estuviera cediendo el control, en vez
        # de un proceso externo robándolo. Por eso antes solo parpadeaba
        # el ícono en la barra de tareas en vez de traer la ventana.
        hwnd_en_foco          = win32gui.GetForegroundWindow()
        hilo_en_foco, _       = win32process.GetWindowThreadProcessId(hwnd_en_foco)
        hilo_destino, _       = win32process.GetWindowThreadProcessId(hwnd)

        adjunto = False
        if hilo_en_foco != hilo_destino:
            adjunto = user32.AttachThreadInput(hilo_destino, hilo_en_foco, True)

        # truco del ALT: simular esta tecla resetea una bandera interna
        # de Windows (LockSetForegroundWindow) que bloquea el robo de
        # foco — es lo que usan herramientas como AutoHotkey para esto.
        # FIX: keybd_event es la API vieja y menos confiable; se usa
        # SendInput, el mismo mecanismo que ya funciona en el control
        # de medios, para simular la tecla a nivel de sistema.
        _simular_tecla_alt()

        user32.BringWindowToTop(hwnd)

        try:
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

        user32.SetFocus(hwnd)

        # FIX: el truco de TOPMOST/NOTOPMOST fuerza un cambio de orden Z
        # que Windows anima con un destello en la barra de tareas — eso
        # es justo el parpadeo que se notaba incluso cuando la ventana
        # SÍ pasaba al frente. Ahora solo se usa como respaldo, y nada
        # más si SetForegroundWindow no lo logró por su cuenta.
        if win32gui.GetForegroundWindow() != hwnd:
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
            )
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
            )

        if adjunto:
            user32.AttachThreadInput(hilo_destino, hilo_en_foco, False)

        # para procesos elevados (juegos), AppActivate via PowerShell como
        # refuerzo — solo si los métodos de arriba no lo lograron, para
        # no generar otro cambio de foco redundante (y otro destello) si
        # la ventana ya quedó al frente.
        if win32gui.GetForegroundWindow() != hwnd:
            try:
                subprocess.Popen(
                    [
                        "powershell", "-WindowStyle", "Hidden", "-Command",
                        f"Add-Type -AssemblyName microsoft.visualbasic; "
                        f"[Microsoft.VisualBasic.Interaction]::AppActivate({pid_ventana})"
                    ],
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                pass

        return True, nombre

    except Exception as e:
        print(f"[MAX] Error: {e}")