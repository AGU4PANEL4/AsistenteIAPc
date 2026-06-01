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
from memory import memoria
from aliases import aliases
import app_finder
import re
import threading

def debug_lunar_java():

    for proc in psutil.process_iter(
        ["pid", "name", "exe", "cmdline"]
    ):
        try:

            name = proc.info["name"] or ""

            if "java" in name.lower():

                print("\n====================")
                print("PID:", proc.pid)
                print("NAME:", name)
                print("EXE:", proc.info["exe"])
                print("CMD:", proc.info["cmdline"])

        except:
            pass

# =========================================================
# CAPTURAR PROCESOS EN SEGUNDO PLANO
# =========================================================

def capturar_procesos_background(
    nombre_cache,
    ruta_str,
    procesos_antes
):
    import time
    import psutil
    from pathlib import Path
    import app_finder

    time.sleep(5)

    pids = []
    procesos = []

    nombre_base = normalizar(
        Path(ruta_str).stem
    )

    for p in psutil.process_iter(
        ["pid", "name"]
    ):
        try:

            if p.info["pid"] in procesos_antes:
                continue

            name = (
                p.info["name"] or ""
            ).lower()

            name_norm = normalizar(
                name.replace(".exe", "")
            )

            if (
                nombre_base in name_norm
                or name_norm in nombre_base
            ):
                pids.append(
                    p.info["pid"]
                )
                procesos.append(name)

        except:
            pass

    app_finder.cache[nombre_cache]["pids"] = list(set(pids))
    app_finder.cache[nombre_cache]["procesos_cierre"] = list(set(procesos))

    app_finder.guardar_cache()

    print(
        "Captura en background terminada"
    )

# =========================================================
# CAPTURAR PIDS
# =========================================================

def capturar_pids_por_nombre(nombre_cache, ruta_str, procesos_antes, espera=10):

    time.sleep(espera)

    if nombre_cache not in app_finder.cache:
        return

    pids = set()
    procesos = set()
    carpetas = set()

    nombre_base = normalizar(nombre_cache)

    # =====================================
    # DETECTAR PROCESOS CON VENTANA ABIERTA
    # =====================================

    def enum_windows_callback(hwnd, _):

        try:
            if win32gui.IsWindowVisible(hwnd):

                _, pid = win32process.GetWindowThreadProcessId(hwnd)

                if pid in procesos_antes:
                    return

                proc = psutil.Process(pid)
                name = proc.name().lower()

                name_norm = normalizar(name.replace(".exe", ""))

                if nombre_base in name_norm or name_norm in nombre_base:

                    print("WINDOW DETECTADA:", name, pid)

                    pids.add(pid)
                    procesos.add(name)

                    exe = proc.exe()
                    if exe:
                        carpeta = str(Path(exe).parent).lower()

                        if "windows" not in carpeta:
                            carpetas.add(carpeta)

        except:
            pass

    win32gui.EnumWindows(enum_windows_callback, None)

    # =====================================
    # GUARDAR SIEMPRE
    # =====================================

    data = app_finder.cache.setdefault(nombre_cache, {})

    data["pids"] = list(pids)
    data["procesos_cierre"] = list(procesos)
    data["carpetas_detectadas"] = list(carpetas)

    app_finder.guardar_cache()

    print("CAPTURADO REAL:", data)
    
# =========================================================
# CONFIRMACION DE VOLVER A REALIZAR LA BUSQUEDA
# =========================================================

def confirmar_rebuscar(nombre, timeout=8):

    hablar(
        f"{nombre} no fue encontrada antes. ¿Quieres buscarla otra vez?"
    )

    inicio = time.time()

    while True:

        respuesta = escuchar()

        if respuesta:
            break

        if time.time() - inicio > timeout:

            hablar("No buscaré la aplicación")

            return False

    respuesta = respuesta.lower().strip()

    SI = [
        "si",
        "sí",
        "dale",
        "ok",
        "buscar",
        "búscala"
    ]

    NO = [
        "no",
        "cancelar",
        "cancela"
    ]

    if respuesta in SI:
        return True

    return False

# =========================================================
# NORMALIZAR
# =========================================================

def normalizar(texto: str) -> str:
    texto = texto.lower().strip()

    # quitar símbolos raros
    texto = re.sub(r"[^a-z0-9]", "", texto)

    return texto

# =========================================================
# ALIASES
# =========================================================

def traducir_alias(nombre):

    nombre = str(nombre).lower().strip()


    for claves, real in aliases.items():

        # SI LA KEY ES TUPLA
        if isinstance(claves, tuple):

            for alias in claves:

                if (

                    str(alias)

                    .lower()

                    .strip()

                    ==

                    nombre

                ):

                    print(

                        f"[Alias] {nombre} -> {real}"

                    )

                    return real


        # SI LA KEY ES STRING
        else:

            if (

                str(claves)

                .lower()

                .strip()

                ==

                nombre

            ):

                print(

                    f"[Alias] {nombre} -> {real}"

                )

                return real


    return nombre

# =========================================================
# NOMBRE DETECTADO PARA IA (HABLAR)
# =========================================================

def obtener_nombre_hablante(ruta):

    archivo = Path(ruta)


    # =====================================================
    # .LNK
    # =====================================================

    if archivo.suffix.lower() == ".lnk":

        return (

            archivo.stem

            .replace("-", " ")

            .replace("_", " ")

        )


    exe = archivo.stem

    carpeta = archivo.parent.name

    carpeta_abuela = archivo.parent.parent.name


    ignorar = [

        "win64",
        "bin",
        "shipping",
        "release",
        "app",
        "programs",
        "current",
        "launcher"

    ]


    # =====================================================
    # IGNORAR CARPETAS BASURA
    # =====================================================

    if (

        carpeta.lower() in ignorar

        or

        carpeta.lower().startswith("app-")

    ):

        if (

            carpeta_abuela.lower() not in ignorar

            and

            not carpeta_abuela.lower().startswith("app-")

        ):

            nombre = carpeta_abuela

        else:

            nombre = exe

    else:

        nombre = carpeta


    return (

        nombre

        .replace("-", " ")

        .replace("_", " ")

    )

# =========================================================
# CONFIRMACIÓN
# =========================================================

def confirmar_apertura(nombre, timeout=8):

    hablar(
        f"Encontré {nombre}. ¿Quieres abrirla?"
    )

    inicio = time.time()

    while True:

        respuesta = escuchar()

        if respuesta:
            break

        if time.time() - inicio > timeout:

            hablar(
                "No recibí respuesta"
            )

            sesion["activa"] = False

            return False

    respuesta = respuesta.lower().strip()

    SI = [

        "si",
        "sí",
        "ci",
        "cí",
        "zi",
        "zí",
        "dale",
        "ok",
        "abrir",
        "hazlo"

    ]

    NO = [

        "no",
        "cancelar",
        "cancela"

    ]

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
# PROCESOS
# =========================================================

def obtener_procesos(nombre):

    nombre = normalizar(nombre)

    encontrados = []

    for p in psutil.process_iter(["name"]):

        try:

            pname = p.info["name"] or ""

            pname = pname.replace(".exe", "")

            pname = normalizar(pname)

            if (

                nombre == pname

                or

                nombre in pname

                or

                pname in nombre

            ):

                encontrados.append(p)

        except:
            pass

    return encontrados


def esta_abierta(nombre):

    return len(
        obtener_procesos(nombre)
    ) > 0

# =========================================================
# ENFOCAR
# =========================================================

def traer_al_frente(nombre):

    nombre = normalizar(nombre)

    ventanas = []

    def callback(hwnd, _):

        if not win32gui.IsWindowVisible(hwnd):
            return

        try:

            _, pid = (

                win32process
                .GetWindowThreadProcessId(hwnd)

            )

            proc = psutil.Process(pid)

            pname = proc.name()

            pname = pname.replace(".exe", "")

            pname = normalizar(pname)

            if (

                nombre == pname

                or

                nombre in pname

                or

                pname in nombre

            ):

                ventanas.append(hwnd)

        except:
            pass

    win32gui.EnumWindows(
        callback,
        None
    )

    if not ventanas:
        return False

    hwnd = ventanas[0]

    try:

        if win32gui.IsIconic(hwnd):

            win32gui.ShowWindow(
                hwnd,
                win32con.SW_RESTORE
            )

        else:

            win32gui.ShowWindow(
                hwnd,
                win32con.SW_SHOW
            )

        win32gui.SetForegroundWindow(hwnd)

        return True

    except:
        return False

# =========================================================
# CERRAR APP
# =========================================================

def cerrar_app(nombre):

    nombre = normalizar(nombre)

    nombre_limpio = normalizar(nombre)

    nombre_cache = None
    data = None

    for clave, valor in app_finder.cache.items():

        clave_norm = normalizar(clave)

        if (
            nombre_limpio == clave_norm
            or nombre_limpio in clave_norm
            or clave_norm in nombre_limpio
        ):

            nombre_cache = clave
            data = valor
            break

    if not data:

        resultado, _, nombre_cache = app_finder.buscar_app(nombre)

        if not resultado:
            return False, nombre

        data = app_finder.cache.get(
            nombre_cache,
            {}
        )

    print("CERRAR NOMBRE:", nombre)
    print("CACHE ENCONTRADA:", nombre_cache)
    print("DATA:", data)

    pids = data.get(
        "pids",
        []
    )

    procesos = data.get(
        "procesos_cierre",
        []
    )

    carpetas_detectadas = data.get(
        "carpetas_detectadas",
        []
    )

    cerrados = False

    # =====================================
    # 1) MATAR PIDS GUARDADOS
    # =====================================

    for pid in pids:

        try:

            proc = psutil.Process(pid)

            print(
                "Kill PID:",
                pid
            )

            proc.kill()

            cerrados = True

        except:
            pass

    # =====================================
    # 2) MATAR PROCESOS GUARDADOS
    # =====================================

    for proc in psutil.process_iter(
        ["pid", "name"]
    ):

        try:

            pname = normalizar(
                (proc.info["name"] or "")
                .replace(".exe", "")
            )

            for objetivo in procesos:

                objetivo = normalizar(
                    objetivo.replace(".exe", "")
                )

                if objetivo in pname:

                    print(
                        "Cerrando:",
                        pname
                    )

                    proc.kill()

                    cerrados = True

        except:
            pass

    # =====================================
    # 3) BARRIDO POR CARPETAS DETECTADAS
    # =====================================

    for carpeta in carpetas_detectadas:

        carpeta_norm = carpeta.lower()

        for proc in psutil.process_iter(
            ["pid", "name", "exe", "cmdline"]
        ):

            try:

                exe = (
                    proc.info.get("exe") or ""
                ).lower()

                cmd = " ".join(
                    proc.info.get("cmdline") or []
                ).lower()

                if (
                    carpeta_norm in exe
                    or
                    carpeta_norm in cmd
                ):

                    print(
                        "Cerrando por carpeta:",
                        proc.info["name"]
                    )

                    proc.kill()

                    cerrados = True

            except:
                pass

    return cerrados, nombre_cache

# =========================================================
# COINCIDENCIAS
# =========================================================

def coincide(proceso, objetivo):

    proceso = normalizar(proceso)
    objetivo = normalizar(objetivo)

    return proceso == objetivo

# =========================================================
# ABRIR APP
# =========================================================

def abrir_app(nombre):

    nombre = normalizar(traducir_alias(nombre))

    resultado, desde_cache, nombre_cache = app_finder.buscar_app(nombre)

    if not desde_cache:

        confirmar = confirmar_apertura(
            nombre_cache
        )

        if not confirmar:

            return False, nombre
        
    print("RESULTADO:", resultado)
    print("DESDE CACHE:", desde_cache)
    print("NOMBRE CACHE:", nombre_cache)

    if not resultado:
        return False, nombre

    ruta = resultado["ruta"] if isinstance(resultado, dict) else resultado
    ruta_str = str(ruta)

    tipo = resultado.get(
        "tipo",
        "normal"
    )

    if tipo == "steam":

        if not desde_cache:

            app_finder.cache[nombre_cache] = {

                "ruta": ruta_str,

                "appid": resultado.get("appid"),

                "tipo": "steam",

                "procesos_cierre": [],

                "pids": []

            }

            app_finder.guardar_cache()

            print(
                "Juego guardado en cache:",
                nombre_cache
            )

        appid = resultado.get("appid")

        if appid:

            procesos_antes = set()

            for p in psutil.process_iter(["pid"]):
                try:
                    procesos_antes.add(p.info["pid"])
                except:
                    pass

            os.startfile(
                f"steam://rungameid/{appid}"
            )

            def delayed_capture():
                time.sleep(15)  # Steam tarda más de lo que crees

                capturar_pids_por_nombre(
                    nombre_cache,
                    ruta_str,
                    procesos_antes,
                    0
                )

            threading.Thread(
                target=delayed_capture,
                daemon=True
            ).start()

            return True, nombre_cache

    carpeta_raiz = str(Path(ruta_str).parent)

    print("Ruta encontrada:", ruta_str)

    if not desde_cache:

        app_finder.cache[nombre_cache] = {
            "ruta": ruta_str,
            "carpeta_raiz": carpeta_raiz,
            "procesos_cierre": [],
            "pids": [],
            "tipo": "normal"
        }

        app_finder.guardar_cache()

        print(
            "Guardada en cache:",
            nombre_cache
        )

    # =========================
    # PROCESOS ANTES
    # =========================

    procesos_antes = set()

    for p in psutil.process_iter(["pid"]):

        try:
            procesos_antes.add(
                p.info["pid"]
            )
        except:
            pass

    # =========================
    # EJECUTAR
    # =========================

    ejecutado_por_steam = False

    try:

        if "steamapps" in ruta_str.lower():

            carpeta = os.path.dirname(ruta_str)

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

                carpeta_juego = (
                    os.path.basename(
                        os.path.dirname(ruta_str)
                    ).lower()
                )

                print("Carpeta juego:", carpeta_juego)

                for archivo in os.listdir(steamapps):

                    if not archivo.startswith("appmanifest_"):
                        continue

                    ruta_manifest = os.path.join(
                        steamapps,
                        archivo
                    )

                    try:

                        with open(
                            ruta_manifest,
                            encoding="utf-8",
                            errors="ignore"
                        ) as f:

                            contenido = f.read().lower()

                        if carpeta_juego in contenido:

                            appid = (
                                archivo
                                .replace("appmanifest_", "")
                                .replace(".acf", "")
                            )

                            print("Steam AppID:", appid)

                            procesos_antes = set()

                            for p in psutil.process_iter(["pid"]):
                                try:
                                    procesos_antes.add(p.info["pid"])
                                except:
                                    pass

                            os.startfile(f"steam://rungameid/{appid}")

                            threading.Thread(
                                target=capturar_pids_por_nombre,
                                args=(nombre_cache, ruta_str, procesos_antes, 10),
                                daemon=True
                            ).start()

                            ejecutado_por_steam = True

                            break

                    except Exception as e:

                        print(
                            "Error leyendo manifest:",
                            e
                        )

    except Exception as e:

        print("Error Steam:", e)

    # =========================
    # APERTURA NORMAL
    # =========================

    if not ejecutado_por_steam:

        if ruta_str.endswith(".lnk"):

            subprocess.Popen(
                f'start "" "{ruta_str}"',
                shell=True
            )

        else:

            subprocess.Popen(
                ruta_str,
                shell=True
            )

    # =========================
    # CAPTURA EN SEGUNDO PLANO
    # =========================

    espera = 10 if ejecutado_por_steam else 5

    threading.Thread(
        target=capturar_pids_por_nombre,
        args=(
            nombre_cache,
            ruta_str,
            procesos_antes,
            espera
        ),
        daemon=True
    ).start()

    return True, nombre_cache

# =========================================================
# REGISTRAR PROCESOS DE CIERRE
# =========================================================

def registrar_procesos_cierre(ruta_str, nombre_cache):

    time.sleep(3)

    procesos_detectados = []

    if app_finder.cache[nombre_cache].get("tipo") == "steam":
        nombre_base = normalizar(nombre_cache)
    else:
        nombre_base = normalizar(Path(ruta_str).stem)

    for proc in psutil.process_iter(["pid", "name"]):

        try:

            proc_name = normalizar(proc.info["name"] or "")

            if (
                nombre_base in proc_name
                or proc_name in nombre_base
            ):
                procesos_detectados.append(proc_name)

        except:
            pass


    procesos_detectados = list(set(procesos_detectados))

    if nombre_cache not in app_finder.cache:

        app_finder.cache[nombre_cache] = {

            "ruta": ruta_str,

            "procesos_cierre": [],

            "pids": [],

            "tipo": "normal"

        }

        app_finder.guardar_cache()

# =========================================================
# NAVEGADOR
# =========================================================

def buscar_browser(busqueda):

    url = (

        "https://www.google.com/search?q="

        +

        quote(busqueda)

    )

    webbrowser.open(url)

    return True


def abrir_url(url):

    if not url.startswith("http"):

        url = "https://" + url

    webbrowser.open(url)

    return True


def abrir_youtube(busqueda):

    url = (

        "https://www.youtube.com/results?search_query="

        +

        quote(busqueda)

    )

    webbrowser.open(url)

    return True