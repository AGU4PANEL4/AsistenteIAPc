import os
import webbrowser
import psutil
import time
import subprocess
from pathlib import Path
from urllib.parse import quote
import win32gui
import win32con
import win32process
from voice import escuchar
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
import re
import threading
import winshell
from startup import (
    activar_inicio_automatico,
    desactivar_inicio_automatico,
    startup_activado
)

# =========================================================
# SIMULAR TECLA ALT (vía SendInput)
# Presionar y soltar ALT resetea una bandera interna de Windows
# (LockSetForegroundWindow) que bloquea que un proceso le robe el
# foco a otro — es el mismo truco que usan AutoHotkey y similares.
# Se usa SendInput en vez de keybd_event (API vieja) por ser el
# mismo mecanismo ya probado y funcionando en media_control.py.
# =========================================================

import ctypes as _ctypes

VK_MENU               = 0x12
_KEYEVENTF_KEYUP_ALT  = 0x0002

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
        inp.type    = INPUT_KEYBOARD
        inp.ki      = _KEYBDINPUT_ALT()
        inp.ki.wVk  = VK_MENU
        inp.ki.dwExtraInfo = _ctypes.pointer(extra)
        _ctypes.windll.user32.SendInput(1, _ctypes.byref(inp), _ctypes.sizeof(inp))

        inp.ki.dwFlags = _KEYEVENTF_KEYUP_ALT
        _ctypes.windll.user32.SendInput(1, _ctypes.byref(inp), _ctypes.sizeof(inp))
    except Exception as e:
        print("[FOCO] No pude simular ALT:", e)

# =========================================================
# STARTUP
# =========================================================

# FIX: antes estas funciones llamaban a hablar() Y devolvían True/False.
# executor.py también habla un mensaje fijo de éxito para estos intents
# (ver mensajes_exito en executor.py) → el resultado era que el usuario
# escuchaba DOS frases ("Inicio automático activado" dicho aquí, y otra
# vez "Inicio automático activado" dicho por executor.py).
#
# Ahora estas funciones NO hablan directamente. Devuelven una tupla
# (éxito, mensaje) con el texto específico para cada caso (ya estaba
# activado / se acaba de activar / no se pudo), y executor.py usa ese
# mensaje tal cual en vez de su propio texto fijo, sin volver a hablar
# dos veces.

def activar_startup(valor=None):
    if startup_activado():
        return True, "El inicio automático ya está activado"
    if activar_inicio_automatico():
        return True, "Inicio automático activado"
    return False, "No pude activar el inicio automático"


def desactivar_startup(valor=None):
    if not startup_activado():
        return True, "El inicio automático ya está desactivado"
    if desactivar_inicio_automatico():
        return True, "Inicio automático desactivado"
    return False, "No pude desactivar el inicio automático"


def estado_startup(valor=None):
    if startup_activado():
        return True, "El inicio automático está activado"
    return True, "El inicio automático está desactivado"

# =========================================================
# NORMALIZAR
# =========================================================

def normalizar(texto: str) -> str:
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9]", "", texto)
    return texto

# =========================================================
# SNAPSHOT DE PROCESOS
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
        except:
            pass

    data_cache   = app_finder.cache.get(nombre_cache, {})
    carpeta_raiz = data_cache.get("carpeta_raiz", "").lower()
    es_steam     = ruta_str.lower().endswith(".acf")

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
                por_carpeta_nueva = (
                    bool(exe)
                    and "windows\\"               not in carpeta_exe
                    and "program files\\windows"  not in carpeta_exe
                    and any(carpeta_exe.startswith(c[:25]) for c in carpetas)
                )

                if por_nombre or por_carpeta or por_steam or por_carpeta_nueva:
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
            except:
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
# =========================================================

def eliminar_alias_app(nombre):
    if eliminar_alias(nombre):
        hablar(f"Olvidé el alias {nombre}")
        return True
    hablar(f"No tenía ningún alias llamado {nombre}")
    return False

# =========================================================
# CONFIRMACIÓN APERTURA
# =========================================================

def confirmar_apertura(nombre, timeout=8):

    hablar(f"Encontré {nombre}. ¿Quieres abrirla?")

    inicio = time.time()

    while True:
        respuesta = escuchar()
        if respuesta:
            break
        if time.time() - inicio > timeout:
            hablar("No recibí respuesta")
            sesion["activa"] = False
            return False

    respuesta = respuesta.lower().strip()

    SI = ["si", "sí", "ci", "cí", "zi", "zí", "dale", "ok", "abrir", "hazlo"]
    NO = ["no", "cancelar", "cancela"]

    if any(x in respuesta for x in SI):
        sesion["activa"] = True
        return True

    if any(x in respuesta for x in NO):
        hablar("Cancelado")
        sesion["activa"] = False
        return False

    hablar("No entendí")
    sesion["activa"] = False
    return False

# =========================================================
# CONFIRMAR REBUSCAR
# =========================================================

def confirmar_rebuscar(nombre, timeout=8):

    hablar(f"Antes no encontré {nombre}. ¿Quieres que busque de nuevo?")

    inicio = time.time()

    while True:
        respuesta = escuchar()
        if respuesta:
            break
        if time.time() - inicio > timeout:
            return False

    respuesta = respuesta.lower().strip()
    SI = ["si", "sí", "dale", "ok", "busca", "intenta"]
    return any(x in respuesta for x in SI)

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
        except:
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
        except:
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
    except:
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

    for clave, valor in app_finder.cache.items():
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

    procesos_guardados  = {p.lower() for p in data.get("procesos_cierre", [])}
    carpetas_detectadas = [c.lower() for c in data.get("carpetas_detectadas", [])]

    print("CERRAR:", nombre_cache)
    print("PROCESOS:", procesos_guardados)
    print("CARPETAS:", carpetas_detectadas)

    cerrados = False

    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info["name"] or "").lower()
            exe  = (proc.info.get("exe") or "").lower()

            por_nombre  = name in procesos_guardados
            por_carpeta = any(c in exe for c in carpetas_detectadas)

            if not (por_nombre or por_carpeta):
                continue

            print(f"[CERRAR] {proc.info['pid']} {name}")

            try:
                proc.terminate()
                proc.wait(timeout=5)
                cerrados = True
                print(f"[CERRAR OK] {name}")
            except psutil.TimeoutExpired:
                try:
                    proc.kill()
                except psutil.NoSuchProcess:
                    pass
                cerrados = True
                print(f"[CERRAR KILL] {name}")
            except psutil.NoSuchProcess:
                cerrados = True
                print(f"[CERRAR YA MUERTO] {name}")
            except (psutil.AccessDenied, Exception) as e:
                # FIX: proceso con permisos elevados
                # taskkill normal primero
                try:
                    resultado_tk = subprocess.run(
                        ["taskkill", "/F", "/PID", str(proc.info["pid"])],
                        capture_output=True,
                        text=True
                    )
                    if resultado_tk.returncode == 0:
                        cerrados = True
                        print(f"[CERRAR TASKKILL] {name}")
                    else:
                        # taskkill elevado via PowerShell
                        subprocess.run(
                            [
                                "powershell", "-Command",
                                f"Stop-Process -Id {proc.info['pid']} -Force"
                            ],
                            capture_output=True
                        )
                        cerrados = True
                        print(f"[CERRAR POWERSHELL] {name}")
                except Exception as e2:
                    print(f"[CERRAR ERROR] {name}: {e2}")

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
    except:
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

    for clave, valor in app_finder.cache.items():
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
        except:
            pass

    # ---- 2. por cache (procesos_cierre + carpetas_detectadas) ----
    for clave, valor in app_finder.cache.items():
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
                except:
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
                        except:
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
        except:
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
        except:
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
        except:
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
            except:
                pass

        return True, nombre

    except Exception as e:
        print(f"[MAX] Error: {e}")
        return False, nombre