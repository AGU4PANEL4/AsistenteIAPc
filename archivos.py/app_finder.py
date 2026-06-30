import os
import json
import sys
import re
import time
import shutil
import threading
import winreg
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher

# ==========================================
# CARPETA DE DATOS PERMANENTE
# ==========================================

CARPETA_DATOS = (
    Path(os.environ["LOCALAPPDATA"])
    / "AsistenteIA"
)

CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

# ==========================================
# MIGRAR DATOS ANTIGUOS
# ==========================================

if getattr(sys, "frozen", False):
    CARPETA_ANTIGUA = Path(sys.executable).parent / "datos"
else:
    CARPETA_ANTIGUA = Path(__file__).resolve().parent / "datos"

if CARPETA_ANTIGUA.exists():
    for archivo in CARPETA_ANTIGUA.iterdir():
        destino = CARPETA_DATOS / archivo.name
        if not destino.exists():
            try:
                shutil.copy2(archivo, destino)
                print(f"Migrado: {archivo.name}")
            except Exception as e:
                print(f"Error migrando {archivo.name}:", e)

# ==========================================
# ARCHIVOS
# ==========================================

ARCHIVO_CACHE          = CARPETA_DATOS / "cache.json"
ARCHIVO_INDEX          = CARPETA_DATOS / "apps_index.json"
ARCHIVO_GAMES          = CARPETA_DATOS / "games_index.json"
ARCHIVO_NO_ENCONTRADAS = CARPETA_DATOS / "apps_no_encontradas.txt"

# ==========================================
# CREAR SI NO EXISTEN
# ==========================================

def asegurar_archivos():
    for archivo in [ARCHIVO_CACHE, ARCHIVO_INDEX, ARCHIVO_GAMES]:
        if not archivo.exists():
            with open(archivo, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=4, ensure_ascii=False)
    if not ARCHIVO_NO_ENCONTRADAS.exists():
        ARCHIVO_NO_ENCONTRADAS.touch()

asegurar_archivos()

print("Datos guardados en:", CARPETA_DATOS)

# =========================================================
# NORMALIZAR
# =========================================================

def limpiar_nombre(texto):
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto)
    reemplazos = {
        "'": "", "\u2019": "", "\u00ae": "", "\u2122": "",
        ":": " ", "-": " ", "_": " "
    }
    for viejo, nuevo in reemplazos.items():
        texto = texto.replace(viejo, nuevo)
    texto = re.sub(r"[^a-z0-9 ]", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto

# =========================================================
# SIMILITUD
# =========================================================

def parecido(a, b):
    return SequenceMatcher(None, a, b).ratio()

# =========================================================
# RUTAS RÁPIDAS
# =========================================================

RUTAS_RAPIDAS = [
    Path(os.getenv("APPDATA", "")) /
    "Microsoft" / "Windows" / "Start Menu" / "Programs",
    Path("C:/ProgramData/Microsoft/Windows/Start Menu/Programs"),
    Path(os.getenv("PROGRAMFILES", "")),
    Path(os.getenv("PROGRAMFILES(X86)", "")),
    Path(os.getenv("LOCALAPPDATA", ""))
]

# =========================================================
# CARPETAS A SALTARSE EN BÚSQUEDA
# =========================================================

CARPETAS_SKIP = {
    "windows", "system32", "syswow64", "$recycle.bin",
    "programdata", "recovery", "perflogs",
    "node_modules", ".git", "__pycache__",
    "temp", "tmp", "cache", "logs", "crash",
    "crashreports", "crashpad", "download",
    "installer", "install", "update", "updater"
}

# =========================================================
# EXES A IGNORAR
# =========================================================

IGNORAR_EXE = [
    "overlay", "updater", "crash", "installer",
    "helper", "service", "bootstrap", "renderer",
    "clearthirdparty", "uninstall", "setup",
    "repair", "migrate", "prereq", "redist",
    "vcredist", "dxsetup", "vc_redist",
]

# =========================================================
# GUARDAR / CARGAR CACHE
# =========================================================

def cargar_cache():
    try:
        with open(ARCHIVO_CACHE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cambiado = False
        for clave, valor in list(data.items()):
            if isinstance(valor, str):
                data[clave] = {
                    "ruta": valor,
                    "procesos_cierre": [],
                    "pids": [],
                    "tipo": "normal"
                }
                cambiado = True
        if cambiado:
            guardar_cache(data)
        return data
    except:
        return {}


def guardar_cache(data=None):
    global cache
    if data is None:
        data = cache
    with open(ARCHIVO_CACHE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =========================================================
# GUARDAR / CARGAR INDEX APPS
# =========================================================

def cargar_index():
    try:
        with open(ARCHIVO_INDEX, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def guardar_index(data):
    with open(ARCHIVO_INDEX, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =========================================================
# GUARDAR / CARGAR INDEX JUEGOS
# =========================================================

def cargar_games_index():
    try:
        with open(ARCHIVO_GAMES, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}


def guardar_games_index():
    with open(ARCHIVO_GAMES, "w", encoding="utf-8") as f:
        json.dump(games_index, f, indent=4, ensure_ascii=False)

# =========================================================
# APPS NO ENCONTRADAS
# =========================================================

def registrar_no_encontrada(nombre):
    try:
        nombre     = nombre.lower().strip()
        existentes = cargar_no_encontradas()
        if nombre not in existentes:
            with open(ARCHIVO_NO_ENCONTRADAS, "a", encoding="utf-8") as f:
                f.write(nombre + "\n")
    except Exception as e:
        print("Error registrando no encontrada:", e)


def cargar_no_encontradas():
    try:
        with open(ARCHIVO_NO_ENCONTRADAS, "r", encoding="utf-8") as f:
            return set(
                linea.strip().lower()
                for linea in f
                if linea.strip()
            )
    except:
        return set()


def quitar_de_no_encontradas(nombre):
    try:
        apps = cargar_no_encontradas()
        if nombre in apps:
            apps.discard(nombre)
            with open(ARCHIVO_NO_ENCONTRADAS, "w", encoding="utf-8") as f:
                for app in apps:
                    f.write(app + "\n")
    except:
        pass

# =========================================================
# PREPARAR RESULTADO
# =========================================================

def preparar_resultado_busqueda(nombre_cache, resultado):
    data = {
        "ruta":            resultado,
        "procesos_cierre": [],
        "pids":            [],
        "tipo":            "normal"
    }
    print("App encontrada:", nombre_cache)
    return data

# =========================================================
# OBTENER NOMBRE PARA CACHE
# =========================================================

def obtener_nombre_cache(ruta):
    archivo        = Path(ruta)

    if archivo.suffix.lower() == ".lnk":
        return archivo.stem

    carpeta        = archivo.parent.name
    carpeta_abuela = archivo.parent.parent.name
    exe            = archivo.stem

    ignorar = [
        "win64", "bin", "app", "current",
        "shipping", "release", "programs", "launcher"
    ]

    # FIX: carpetas del sistema que no son nombres utiles
    carpetas_sistema = {
        "windowsapps", "system32", "syswow64",
        "windows", "microsoft", "localappdata",
        "appdata", "roaming", "local",
    }

    if (
        carpeta.lower().startswith("app-")
        or carpeta.lower() in ignorar
        or carpeta.lower() in carpetas_sistema
    ):
        return exe

    if any(c.isdigit() for c in carpeta):
        if (
            carpeta_abuela.lower() not in ignorar
            and carpeta_abuela.lower() not in carpetas_sistema
            and not any(c.isdigit() for c in carpeta_abuela)
        ):
            return carpeta_abuela
        return exe

    if len(carpeta) > 3:
        return carpeta

    return exe

# =========================================================
# SCORE DE NOMBRE
# =========================================================

def score_nombre(nombre_original):
    nombre = nombre_original.lower().strip()
    score  = 0
    score += len(nombre)
    score += nombre.count(" ") * 5
    if "(" in nombre or ")" in nombre:
        score += 4
    if "!" in nombre:
        score += 4
    nombre_limpio = limpiar_nombre(nombre)
    for mala in ["app", "launcher", "shipping", "release", "win64", "bin", "programs"]:
        if mala in nombre_limpio:
            score -= 15
    if len(nombre_limpio.split()) == 1 and len(nombre_limpio) < 6:
        score -= 10
    return score

# =========================================================
# LIMPIAR DUPLICADOS
# =========================================================

def limpiar_cache_duplicados():
    global cache
    nuevas     = {}
    eliminadas = []

    for clave, data in list(cache.items()):

        if isinstance(data, dict) and data.get("tipo") == "steam":
            nuevas[limpiar_nombre(clave)] = (clave, data.copy())
            continue

        if isinstance(data, dict):
            ruta       = data.get("ruta", "")
            data_nueva = data.copy()
        else:
            ruta       = str(data)
            data_nueva = {
                "ruta":            ruta,
                "procesos_cierre": [],
                "pids":            [],
                "tipo":            "normal"
            }

        # FIX: preservar clave original si ya tiene procesos
        if bool(data_nueva.get("procesos_cierre")):
            nombre_real = clave
        else:
            nombre_real = obtener_nombre_cache(ruta)

        nombre_real_limpio = limpiar_nombre(nombre_real)

        if nombre_real_limpio in nuevas:

            clave_existente  = nuevas[nombre_real_limpio][0]
            data_existente   = nuevas[nombre_real_limpio][1]

            tiene_procesos_nuevo     = bool(data_nueva.get("procesos_cierre"))
            tiene_procesos_existente = bool(data_existente.get("procesos_cierre"))

            # prioridad 1: preferir la que tenga procesos guardados
            if tiene_procesos_nuevo and not tiene_procesos_existente:
                eliminadas.append(clave_existente)
                nuevas[nombre_real_limpio] = (nombre_real, data_nueva)
            elif not tiene_procesos_nuevo and tiene_procesos_existente:
                eliminadas.append(clave)
            # prioridad 2: score del nombre
            elif score_nombre(nombre_real) > score_nombre(clave_existente):
                eliminadas.append(clave_existente)
                nuevas[nombre_real_limpio] = (nombre_real, data_nueva)
            else:
                eliminadas.append(clave)
        else:
            nuevas[nombre_real_limpio] = (nombre_real, data_nueva)

    cache = {
        clave: data
        for _, (clave, data) in nuevas.items()
    }

    guardar_cache()

    if eliminadas:
        print("Duplicados eliminados:")
        for x in eliminadas:
            print(" -", x)
    else:
        print("No había duplicados")

# =========================================================
# INDEXAR JUEGOS STEAM
# =========================================================

def indexar_juegos_steam():
    # FIX: antes esta función hacía games_index.clear() y luego lo
    # reconstruía entrada por entrada en el mismo diccionario global.
    # Como esto corre en un hilo daemon en background (ver main.py)
    # mientras el hilo principal puede estar buscando un juego al mismo
    # tiempo (buscar_app lee games_index), había una ventana de varios
    # segundos donde el índice estaba vacío o solo parcialmente lleno
    # — el usuario podía pedir abrir un juego que SÍ está instalado y
    # el asistente decir que no lo encuentra, solo por mala suerte de
    # timing con el reindexado.
    #
    # Ahora se construye todo en un diccionario temporal (nuevo_index)
    # y solo al final se reemplaza games_index de una sola asignación.
    # Esa asignación es atómica en Python, así que cualquier lectura
    # desde otro hilo siempre ve o el índice viejo completo, o el nuevo
    # completo — nunca un estado a medio construir.
    global games_index

    nuevo_index = {}

    steam_path = None
    try:
        clave      = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path = Path(winreg.QueryValueEx(clave, "SteamPath")[0])
    except Exception as e:
        print("No se encontró Steam:", e)
        return

    print("Steam encontrada:", steam_path)

    bibliotecas         = []
    steamapps_principal = steam_path / "steamapps"
    bibliotecas.append(steamapps_principal)

    library_file = steamapps_principal / "libraryfolders.vdf"
    try:
        if library_file.exists():
            contenido = library_file.read_text(encoding="utf-8", errors="ignore")
            rutas     = re.findall(r'"path"\s*"([^"]+)"', contenido, re.IGNORECASE)
            for ruta in rutas:
                ruta       = ruta.replace("\\\\", "\\")
                biblioteca = Path(ruta) / "steamapps"
                if biblioteca.exists():
                    bibliotecas.append(biblioteca)
    except Exception as e:
        print("Error leyendo libraryfolders:", e)

    bibliotecas = list(dict.fromkeys(bibliotecas))

    print("Bibliotecas encontradas:")
    for b in bibliotecas:
        print(" -", b)

    PALABRAS_EXCLUIDAS = [
        "redistributable", "steamworks", "steamruntime",
        "steam runtime", "steamlinuxruntime",
        "steam linux runtime", "proton"
    ]

    total = 0

    for steamapps in bibliotecas:
        try:
            for manifest in steamapps.glob("appmanifest_*.acf"):
                try:
                    texto        = manifest.read_text(encoding="utf-8", errors="ignore")
                    match_nombre = re.search(r'"name"\s*"([^"]+)"',      texto, re.IGNORECASE)
                    match_appid  = re.search(r'"appid"\s*"([^"]+)"',     texto, re.IGNORECASE)
                    match_exe    = re.search(r'"installdir"\s*"([^"]+)"', texto, re.IGNORECASE)

                    if not match_nombre:
                        continue

                    nombre = limpiar_nombre(match_nombre.group(1))

                    if any(p in nombre for p in PALABRAS_EXCLUIDAS):
                        print("Ignorado:", nombre)
                        continue

                    if nombre in nuevo_index:
                        continue

                    appid    = match_appid.group(1) if match_appid else ""
                    exe_path = match_exe.group(1)   if match_exe  else ""

                    nuevo_index[nombre] = {
                        "ruta":     str(manifest),
                        "appid":    appid,
                        "tipo":     "steam",
                        "exe_name": exe_path or nombre,
                        "oculto":   False
                    }

                    print("Juego encontrado:", nombre)
                    total += 1

                except Exception as e:
                    print("Error manifest:", e)
        except Exception as e:
            print("Error biblioteca:", e)

    games_index = nuevo_index
    guardar_games_index()
    print(f"Juegos Steam indexados: {total}")

# =========================================================
# INDEXAR APPS
# =========================================================

def indexar_apps():
    global apps_index
    total = 0

    PALABRAS_BASURA = [
        "uninstall", "uninstaller", "setup", "update", "updater",
        "updatetool", "crash", "reporter", "helper", "installer",
        "bootstrap", "launcherupdater", "service", "assistant",
        "telemetry", "repair", "diagnostic", "migration", "install",
        "elevation", "launcherhelper", "webview", "runtime",
        "redistributable", "vc_redist", "prerequisite"
    ]

    RUTAS_BASURA = [
        "\\edgeupdate\\", "\\download\\", "\\installer\\",
        "\\install\\", "\\cache\\", "\\temp\\", "\\updater\\",
        "\\crashreports\\", "\\crashpad\\", "\\logs\\",
        "\\crash", "\\update", "\\uninstall"
    ]

    for ruta_base in RUTAS_RAPIDAS:
        try:
            if not ruta_base.exists():
                continue
            for root, dirs, files in os.walk(ruta_base):
                for archivo in files:
                    try:
                        if not archivo.lower().endswith(".lnk"):
                            continue
                        nombre              = limpiar_nombre(Path(archivo).stem)
                        if len(nombre) < 3:
                            continue
                        ruta_completa       = os.path.join(root, archivo)
                        ruta_completa_lower = ruta_completa.lower()
                        if any(b in nombre             for b in PALABRAS_BASURA):
                            continue
                        if any(b in ruta_completa_lower for b in RUTAS_BASURA):
                            continue
                        if sum(c.isdigit() for c in nombre) > 8:
                            continue
                        if nombre in apps_index:
                            continue
                        apps_index[nombre] = {
                            "ruta":   ruta_completa,
                            "oculto": False
                        }
                        total += 1
                    except:
                        pass
        except:
            pass

    guardar_index(apps_index)
    print(f"Apps indexadas: {total}")

# =========================================================
# BUSCAR EN RUTA
# =========================================================

def buscar_en_ruta(nombre, ruta, fn_cancelado=None):

    nombre_limpio = limpiar_nombre(nombre)
    threshold     = 0.72 if len(nombre_limpio) <= 4 else 0.80
    mejor         = None
    mejor_score   = 0

    try:
        for root, dirs, files in os.walk(ruta):

            # FIX: verificar cancelación en cada carpeta
            if fn_cancelado and fn_cancelado():
                print("[Búsqueda] Cancelada")
                return None

            dirs[:] = [
                d for d in dirs
                if d.lower() not in CARPETAS_SKIP
                and not d.startswith(".")
            ]

            for archivo in files:
                ext = archivo.lower()
                if not (ext.endswith(".exe") or ext.endswith(".lnk")):
                    continue
                if any(x in archivo.lower() for x in IGNORAR_EXE):
                    continue

                base    = limpiar_nombre(Path(archivo).stem)
                carpeta = limpiar_nombre(Path(root).name)

                score = max(
                    parecido(nombre_limpio, base),
                    parecido(nombre_limpio, carpeta)
                )

                if nombre_limpio == base:
                    score += 1
                elif nombre_limpio in base:
                    score += 0.5

                if score > mejor_score:
                    mejor_score = score
                    mejor       = os.path.join(root, archivo)

                if mejor_score >= 1.5:
                    return mejor

    except Exception as e:
        print("Error búsqueda:", e)

    return mejor if mejor_score > threshold else None

# =========================================================
# BUSCAR CON LOADING EN CONSOLA
# =========================================================

def buscar_con_loading(nombre, disco, fn_cancelado=None):

    import itertools
    import sys as _sys

    spinner   = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])
    resultado = [None]
    terminado = [False]

    def buscar():
        resultado[0] = buscar_en_ruta(nombre, disco, fn_cancelado=fn_cancelado)
        terminado[0] = True

    hilo = threading.Thread(target=buscar, daemon=True)
    hilo.start()

    while not terminado[0]:

        # FIX: verificar cancelación en el spinner también
        if fn_cancelado and fn_cancelado():
            _sys.stdout.write("\r" + " " * 60 + "\r")
            _sys.stdout.flush()
            return None

        _sys.stdout.write(f"\r  {next(spinner)} Buscando en {disco}...")
        _sys.stdout.flush()
        time.sleep(0.1)

    _sys.stdout.write("\r" + " " * 60 + "\r")
    _sys.stdout.flush()

    return resultado[0]

# =========================================================
# OBTENER DISCOS
# =========================================================

def obtener_discos():
    discos = []
    for letra in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        ruta = f"{letra}:\\"
        if os.path.exists(ruta):
            discos.append(Path(ruta))
    return discos

# =========================================================
# BUSCAR APP
# =========================================================

def buscar_app(nombre, fn_confirmar_rebuscar=None, fn_cancelado=None):
    global cache

    nombre        = nombre.lower().strip()
    nombre_limpio = limpiar_nombre(nombre)

    # =====================================================
    # CACHE
    # FIX: indexar_apps() e indexar_juegos_steam() corren en hilos
    # daemon en background (ver main.py) y mutan apps_index/games_index
    # directamente (incluyendo un .clear() en games_index). Si justo
    # en ese momento el hilo principal está iterando con .items() para
    # buscar una app, Python puede lanzar "RuntimeError: dictionary
    # changed size during iteration". Iterar sobre list(...items()) /
    # dict(...) toma una copia atómica en el momento de la llamada, así
    # que ya no importa si el otro hilo sigue escribiendo el original
    # mientras este hilo recorre la copia.
    #
    # FIX/NUEVO: antes, si la ruta guardada en cache ya no existía
    # (la app se desinstaló, o se movió a otra carpeta/disco), esto
    # simplemente no consideraba esa entrada un match — pero la dejaba
    # intacta en el cache para siempre, y la búsqueda pasaba en
    # silencio a games_index/apps_index sin ningún aviso. Si esos
    # índices tampoco tenían la app (porque de verdad se desinstaló),
    # el usuario recibía un confuso "no encontré X" para una app que
    # ANTES sí funcionaba, sin entender por qué dejó de funcionar.
    #
    # Ahora, cuando se detecta una entrada de cache con ruta rota, se
    # ELIMINA del cache inmediatamente (ya no sirve, y dejarla solo
    # ensucia futuras búsquedas) y la ejecución sigue de largo hacia
    # games_index/apps_index/disco — exactamente el mismo camino que
    # ya existe para "esta app nunca estuvo en cache". Eso significa
    # que el comportamiento que ya tenía abrir_app() para apps nuevas
    # (rescanear, confirmar con el usuario, volver a guardar en cache)
    # se reutiliza automáticamente para apps que se movieron — sin
    # necesitar ningún flujo nuevo. Si tampoco se encuentra en disco,
    # el resto del código ya maneja ese "no encontrado" como siempre,
    # que es el comportamiento correcto para una app que de verdad se
    # desinstaló.
    # =====================================================

    claves_rotas = []

    for clave, data in list(cache.items()):
        clave_limpia = limpiar_nombre(clave)
        if (
            nombre_limpio == clave_limpia
            or nombre_limpio in clave_limpia
            or clave_limpia in nombre_limpio
        ):
            ruta = data.get("ruta", "") if isinstance(data, dict) else str(data)

            if ruta and os.path.exists(ruta):
                print("Cache:", clave)
                if isinstance(data, dict):
                    return data, True, clave
                return {
                    "ruta":            data,
                    "procesos_cierre": [],
                    "tipo":            "normal"
                }, True, clave

            # la ruta de esta entrada ya no existe — se marca para
            # eliminar (no se borra acá mismo para no mutar `cache`
            # mientras `list(cache.items())` todavía podría tener más
            # coincidencias que revisar en esta misma búsqueda)
            if ruta:
                print(f"[Cache] Ruta obsoleta para '{clave}': {ruta} (ya no existe, se eliminará del cache)")
                claves_rotas.append(clave)

    for clave in claves_rotas:
        cache.pop(clave, None)

    if claves_rotas:
        guardar_cache()

    # =====================================================
    # GAMES INDEX
    # =====================================================

    for clave, data in list(games_index.items()):
        try:
            clave_limpia = limpiar_nombre(clave)
            if (
                nombre_limpio == clave_limpia
                or nombre_limpio in clave_limpia
                or clave_limpia in nombre_limpio
            ):
                print("Game Index:", clave)
                return data, False, clave
        except:
            pass

    # =====================================================
    # APPS INDEX
    # =====================================================

    for clave, data in list(apps_index.items()):
        try:
            if data.get("oculto", False):
                continue
            clave_limpia = limpiar_nombre(clave)
            if (
                nombre_limpio == clave_limpia
                or nombre_limpio in clave_limpia
                or clave_limpia in nombre_limpio
            ):
                ruta = data.get("ruta", "")
                if ruta and os.path.exists(ruta):
                    print("Index:", clave)
                    return {
                        "ruta":            ruta,
                        "procesos_cierre": [],
                        "tipo":            "normal"
                    }, False, clave
        except:
            pass

    # =====================================================
    # APPS NO ENCONTRADAS
    # =====================================================

    no_encontradas = cargar_no_encontradas()

    if nombre in no_encontradas:
        print("App marcada como no encontrada anteriormente")
        if fn_confirmar_rebuscar:
            if not fn_confirmar_rebuscar(nombre):
                return None, False, None
        else:
            return None, False, None

    # =====================================================
    # BÚSQUEDA RÁPIDA
    # =====================================================

    for ruta_base in RUTAS_RAPIDAS:
        try:
            if fn_cancelado and fn_cancelado():
                return None, False, None

            if not ruta_base.exists():
                continue

            resultado = buscar_en_ruta(nombre, ruta_base, fn_cancelado=fn_cancelado)

            if fn_cancelado and fn_cancelado():
                return None, False, None

            if resultado:
                nombre_cache = obtener_nombre_cache(resultado).lower()
                data         = preparar_resultado_busqueda(nombre_cache, resultado)
                quitar_de_no_encontradas(nombre)
                return data, False, nombre_cache

        except Exception as e:
            print("Error búsqueda rápida:", e)

    # =====================================================
    # BÚSQUEDA EN TODOS LOS DISCOS
    # =====================================================

    print("Buscando en discos...")

    for disco in obtener_discos():
        try:
            if fn_cancelado and fn_cancelado():
                return None, False, None

            resultado = buscar_con_loading(nombre, disco, fn_cancelado=fn_cancelado)

            if fn_cancelado and fn_cancelado():
                return None, False, None

            if resultado:
                nombre_cache = obtener_nombre_cache(resultado).lower()
                data         = preparar_resultado_busqueda(nombre_cache, resultado)
                quitar_de_no_encontradas(nombre)
                return data, False, nombre_cache

        except Exception as e:
            print("Error búsqueda disco:", e)

    # =====================================================
    # NO ENCONTRADA
    # =====================================================

    registrar_no_encontrada(nombre)
    return None, False, None

# =========================================================
# CARGAR ARCHIVOS AL INICIO
# =========================================================

cache       = cargar_cache()
apps_index  = cargar_index()
games_index = cargar_games_index()