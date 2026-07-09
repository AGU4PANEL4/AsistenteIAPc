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
ARCHIVO_NO_ENCONTRADAS = CARPETA_DATOS / "apps_no_encontradas.json"

# ==========================================
# CREAR SI NO EXISTEN
# ==========================================

def asegurar_archivos():
    for archivo in [ARCHIVO_CACHE, ARCHIVO_INDEX, ARCHIVO_GAMES]:
        if not archivo.exists():
            with open(archivo, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=4, ensure_ascii=False)
    # ARCHIVO_NO_ENCONTRADAS no se crea en el arranque — se crea
    # la primera vez que se registra una app no encontrada, en
    # _guardar_no_encontradas_raw(). Crearlo vacío acá generaba
    # un archivo .txt vacío en el formato antiguo.

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
    except Exception:
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
    except Exception:
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
    except Exception:
        return {}


def guardar_games_index():
    with open(ARCHIVO_GAMES, "w", encoding="utf-8") as f:
        json.dump(games_index, f, indent=4, ensure_ascii=False)

# =========================================================
# APPS NO ENCONTRADAS
# =========================================================
#
# FIX/NUEVO: antes se guardaba solo el nombre de la app, sin ninguna
# fecha — no había forma de saber cuándo se marcó como no encontrada.
# Esto causaba que una app que falló en indexarse una vez (ej. Steam
# estaba cerrando justo en ese momento, o el disco externo no estaba
# conectado) quedara bloqueada para siempre, sin que el usuario supiera
# por qué "Jarvis" nunca la encontraba aunque estuviera instalada.
#
# Ahora se usa JSON con timestamps. Las entradas expiran
# automáticamente después de DIAS_EXPIRACION_NO_ENCONTRADAS días —
# al expirar, la app se vuelve a buscar normalmente en el próximo
# intento, sin que el usuario tenga que hacer nada.
#
# Compatibilidad: si el archivo viejo (formato .txt, una app por línea)
# existe, se migra automáticamente al nuevo formato JSON, asignando
# la fecha de hoy como timestamp de registro (conservador — empieza
# a contar desde la migración, no asume que llevan mucho tiempo).

DIAS_EXPIRACION_NO_ENCONTRADAS = 7  # días hasta que una entrada expira


def _migrar_txt_a_json_si_existe():
    """
    Migración one-shot del formato viejo (txt) al nuevo (json).
    Si el archivo .txt existe y el .json no, lo convierte y borra el txt.
    """
    ruta_txt = ARCHIVO_NO_ENCONTRADAS.with_suffix(".txt")
    if not ruta_txt.exists():
        return

    try:
        from datetime import datetime
        hoy = datetime.now().isoformat()

        lineas = ruta_txt.read_text(encoding="utf-8").splitlines()
        data   = {
            linea.strip().lower(): hoy
            for linea in lineas
            if linea.strip()
        }

        if data:
            CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
            with open(ARCHIVO_NO_ENCONTRADAS, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

        ruta_txt.unlink(missing_ok=True)
        print(f"[AppFinder] Migradas {len(data)} apps no encontradas al nuevo formato")

    except Exception as e:
        print("[AppFinder] Error migrando apps no encontradas:", e)


def registrar_no_encontrada(nombre):
    from datetime import datetime
    try:
        nombre = nombre.lower().strip()
        data   = _cargar_no_encontradas_raw()
        if nombre not in data:
            data[nombre] = datetime.now().isoformat()
            _guardar_no_encontradas_raw(data)
    except Exception as e:
        print("Error registrando no encontrada:", e)


def cargar_no_encontradas():
    """
    Devuelve el SET de nombres que siguen siendo no encontradas
    (sin expirar). Las entradas expiradas se eliminan en este mismo
    paso — así el archivo se limpia solo con el tiempo, sin necesitar
    ningún proceso de mantenimiento manual.
    """
    from datetime import datetime, timedelta

    data     = _cargar_no_encontradas_raw()
    limite   = datetime.now() - timedelta(days=DIAS_EXPIRACION_NO_ENCONTRADAS)
    vigentes = {}
    cambio   = False

    for nombre, timestamp_str in data.items():
        try:
            ts = datetime.fromisoformat(timestamp_str)
            if ts >= limite:
                vigentes[nombre] = timestamp_str
            else:
                cambio = True
                print(f"[AppFinder] '{nombre}' expiró de no-encontradas "
                      f"(registrada hace más de {DIAS_EXPIRACION_NO_ENCONTRADAS} días)")
        except Exception:
            # timestamp inválido → descartar la entrada por seguridad
            cambio = True

    if cambio:
        _guardar_no_encontradas_raw(vigentes)

    return set(vigentes.keys())


def quitar_de_no_encontradas(nombre):
    try:
        data = _cargar_no_encontradas_raw()
        if nombre in data:
            del data[nombre]
            _guardar_no_encontradas_raw(data)
    except Exception:
        pass


def _cargar_no_encontradas_raw():
    """Carga el dict crudo {nombre: timestamp_iso} del JSON."""
    try:
        if not ARCHIVO_NO_ENCONTRADAS.exists():
            return {}
        with open(ARCHIVO_NO_ENCONTRADAS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _guardar_no_encontradas_raw(data):
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVO_NO_ENCONTRADAS, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

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

def _escanear_juegos_steam():
    """
    Escanea las bibliotecas de Steam y devuelve un dict {nombre:
    data} con lo encontrado — función PURA, no toca games_index
    directamente (ver indexar_juegos() más abajo, que combina esto
    con _escanear_juegos_epic() en una sola asignación atómica).

    FIX/NUEVO: esto era antes el cuerpo completo de
    indexar_juegos_steam(), que mutaba games_index directamente al
    final. Se separó en una función pura porque ahora hay una
    segunda fuente (Epic Games, ver _escanear_juegos_epic) que
    también aporta entradas a games_index — si cada una siguiera
    reemplazando la variable global por su cuenta, dos hilos
    indexando en paralelo (ver main.py) podrían pisarse uno al otro
    (el que termine último borraría lo que el otro ya había
    encontrado). Manteniendo cada scanner puro y combinando recién al
    final en UNA sola asignación, se preserva la misma garantía que
    ya tenía esto: cualquier lectura desde otro hilo ve siempre el
    índice viejo completo o el nuevo completo, nunca una mezcla a
    medio construir ni el resultado de una fuente pisando a la otra.
    """
    nuevo_index = {}

    steam_path = None
    try:
        clave      = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path = Path(winreg.QueryValueEx(clave, "SteamPath")[0])
    except Exception as e:
        print("No se encontró Steam:", e)
        return nuevo_index

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

                    print("Juego Steam encontrado:", nombre)
                    total += 1

                except Exception as e:
                    print("Error manifest:", e)
        except Exception as e:
            print("Error biblioteca:", e)

    print(f"Juegos Steam encontrados: {total}")
    return nuevo_index

# =========================================================
# INDEXAR JUEGOS EPIC GAMES
# NUEVO: hasta ahora solo se indexaban juegos de Steam — cualquier
# juego de Epic Games Store (Fortnite el caso más conocido, pero
# aplica a cualquier otro) dependía por completo de la búsqueda
# genérica en disco (buscar_en_ruta/buscar_con_loading), que:
#
#   1. Puede no encontrarlo si está instalado fuera de las rutas
#      "rápidas" (Epic deja elegir cualquier carpeta/disco al
#      instalar, y muchos juegos de Epic no crean acceso directo en
#      el menú Inicio, a diferencia de la mayoría de instaladores
#      tradicionales).
#   2. Aunque lo encuentre, terminaría ejecutando el .exe del juego
#      DIRECTAMENTE (ej. FortniteClient-Win64-Shipping.exe) — varios
#      juegos de Epic (Fortnite incluido) usan Easy Anti-Cheat u
#      otras protecciones que EXIGEN iniciarse a través del Epic
#      Games Launcher. Ejecutar el .exe directo lo abre un instante
#      y lo cierra con un error de anti-cheat, en vez de jugarlo de
#      verdad — probablemente la causa real de "abrir fortnite no
#      funciona".
#
# La solución es la misma que ya existía para Steam: en vez de
# buscar el .exe en disco, se lee el catálogo local de manifests que
# el propio Epic Games Launcher mantiene (un archivo .item en
# formato JSON por juego instalado) y se lanza por su protocolo
# propio (com.epicgames.launcher://apps/...), exactamente como
# steam://rungameid/... resuelve el mismo problema para Steam — es
# el LAUNCHER quien arranca el juego, con todo lo que necesita
# (autenticación, anti-cheat) ya inicializado.
# =========================================================

CARPETA_MANIFESTS_EPIC = Path("C:/ProgramData/Epic/EpicGamesLauncher/Data/Manifests")


def _escanear_juegos_epic():
    """
    Escanea los manifests locales de Epic Games Launcher y devuelve
    un dict {nombre: data} con lo encontrado — función PURA, mismo
    motivo que _escanear_juegos_steam() (ver ese comentario).

    Cada archivo .item es un JSON con (entre otros) DisplayName
    (nombre para mostrar), AppName (identificador interno que usa el
    protocolo de lanzamiento) e InstallLocation (carpeta de
    instalación) — no hace falta ni encontrar ni ejecutar ningún
    .exe directamente, el AppName alcanza para que el propio Epic
    Games Launcher se encargue de todo.
    """
    nuevo_index = {}

    if not CARPETA_MANIFESTS_EPIC.exists():
        print("No se encontró Epic Games Launcher (o no tiene juegos instalados)")
        return nuevo_index

    print("Epic Games Launcher encontrado:", CARPETA_MANIFESTS_EPIC)

    total = 0

    for manifest in CARPETA_MANIFESTS_EPIC.glob("*.item"):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8", errors="ignore"))

            nombre_mostrado  = data.get("DisplayName", "")
            app_name         = data.get("AppName", "")
            ruta_instalacion = data.get("InstallLocation", "")

            # bIsApplication distingue juegos/apps reales de
            # herramientas internas del motor (ej. el propio Unreal
            # Engine se instala también como una entrada de manifest
            # cuando se usa como base de otro juego) — si el campo no
            # está presente, se asume True (mejor mostrar de más que
            # perderse un juego real por un campo ausente)
            if data.get("bIsApplication") is False:
                continue

            if not nombre_mostrado or not app_name:
                continue

            nombre = limpiar_nombre(nombre_mostrado)

            if nombre in nuevo_index:
                continue

            nuevo_index[nombre] = {
                "ruta":     ruta_instalacion or str(manifest),
                "app_name": app_name,
                "tipo":     "epic",
                "exe_name": nombre_mostrado,
                "oculto":   False,
            }

            print("Juego Epic encontrado:", nombre)
            total += 1

        except Exception as e:
            print("Error manifest Epic:", manifest.name, e)

    print(f"Juegos Epic encontrados: {total}")
    return nuevo_index

# =========================================================
# INDEXAR JUEGOS (STEAM + EPIC)
# =========================================================

def indexar_juegos():
    """
    Indexa juegos de todas las plataformas soportadas (Steam, Epic
    Games) en un solo games_index combinado.

    FIX/NUEVO: ambos scanners son funciones puras que devuelven su
    propio dict sin tocar games_index — se combinan acá y recién al
    final se hace UNA sola asignación atómica, preservando la misma
    garantía que ya tenía el indexado de Steam (ver el comentario
    detallado en _escanear_juegos_steam): cualquier lectura desde
    otro hilo (buscar_app corriendo mientras esto todavía está
    indexando) ve siempre el índice viejo completo o el nuevo
    completo, nunca una mezcla a medio construir.
    """
    global games_index

    nuevo_index = {}
    nuevo_index.update(_escanear_juegos_steam())
    nuevo_index.update(_escanear_juegos_epic())

    games_index = nuevo_index
    guardar_games_index()

    print(f"Total juegos indexados: {len(games_index)}")


# alias por compatibilidad — el nombre viejo indexaba solo Steam;
# ahora indexa todas las plataformas soportadas desde la misma
# llamada, sin que main.py necesite saber que se agregó Epic.
indexar_juegos_steam = indexar_juegos

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
                    except Exception:
                        pass
        except Exception:
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

def guardar_alias_silencioso(alias, nombre_real):
    """
    Guarda un alias automáticamente sin interacción del usuario.
    Se usa cuando la IA resuelve un nombre mal transcripto — así
    la próxima vez que el usuario diga lo mismo se resuelve
    directamente desde cache de aliases sin necesitar la IA.
    """
    try:
        from aliases import agregar_alias
        alias_limpio = alias.lower().strip()
        nombre_real  = nombre_real.lower().strip()
        if alias_limpio != nombre_real:
            agregar_alias(alias_limpio, nombre_real)
            print(f"[Alias] Guardado automáticamente: '{alias_limpio}' → '{nombre_real}'")
    except Exception as e:
        print(f"[Alias] Error guardando alias automático: {e}")


def _resolver_nombre_con_ia(nombre):
    """
    Usa la IA híbrida (Groq/Ollama) para intentar identificar el
    nombre real de una app a partir de cómo la dijo el usuario.

    Útil cuando la transcripción de Whisper falla parcialmente:
    "guttering waves" → "Wuthering Waves"
    "es creem"        → "Steam"
    "cromo"           → "Google Chrome"
    "bloc de nota"    → "Notepad"

    Devuelve el nombre sugerido en minúsculas, o None si la IA
    no puede identificarlo o si no hay motores disponibles.

    Se limita a 6 tokens de respuesta (solo el nombre) y usa
    temperatura 0 para minimizar alucinaciones — preferimos que
    devuelva None a que invente una app que no existe.
    """
    try:
        from ia import _llamar_ollama

        # se construye un listado de las apps conocidas en cache e
        # índices para darle contexto a la IA — así puede comparar
        # contra apps reales instaladas en vez de adivinar cualquier
        # cosa. Se limita a 60 nombres para no saturar el contexto.
        apps_conocidas = []
        for clave in list(cache.keys())[:30]:
            apps_conocidas.append(clave)
        for clave in list(games_index.keys())[:15]:
            if clave not in apps_conocidas:
                apps_conocidas.append(clave)
        for clave in list(apps_index.keys())[:15]:
            if clave not in apps_conocidas:
                apps_conocidas.append(clave)

        contexto_apps = ", ".join(apps_conocidas[:60]) if apps_conocidas else ""

        prompt = (
            f"El usuario de un asistente de voz dijo el nombre de una app o "
            f"videojuego, pero puede estar mal pronunciado o transcripto por "
            f"reconocimiento de voz. "
            f"Nombre dicho: \"{nombre}\". "
            + (f"Apps instaladas conocidas: {contexto_apps}. " if contexto_apps else "")
            + "¿Cuál es el nombre real más probable de esa app o juego? "
            "Responde ÚNICAMENTE con el nombre, en minúsculas, sin explicaciones "
            "ni puntuación. Si no podés identificarlo con certeza, responde: no sé"
        )

        respuesta = _llamar_ollama(prompt, timeout=6, num_predict=8, temperature=0.0)

        if not respuesta:
            return None

        respuesta = respuesta.lower().strip().strip(".,;\"'")

        # descartar respuestas de "no sé" o demasiado largas (la IA
        # empezó a explicar en vez de dar solo el nombre)
        if not respuesta or "no sé" in respuesta or "no se" in respuesta:
            return None
        if len(respuesta.split()) > 5:
            return None
        if respuesta == nombre.lower().strip():
            return None  # la IA devolvió lo mismo, no ayuda

        return respuesta

    except Exception as e:
        print(f"[IA] Error resolviendo nombre de app: {e}")
        return None


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
        except Exception:
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
        except Exception:
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
    # FALLBACK DE IA — antes de buscar en disco
    # NUEVO: si no se encontró nada en cache ni en los índices
    # (que es instantáneo), la IA intenta interpretar el nombre
    # que dijo el usuario y sugerir el nombre real de la app.
    # Si la IA lo reconoce, se hace una segunda pasada por cache
    # e índices con el nombre corregido — evitando la búsqueda
    # lenta en disco en la mayoría de casos donde el problema era
    # solo cómo se pronunció o transcribió el nombre.
    #
    # Ejemplos donde esto ayuda:
    #   "guttering waves" → "wuthering waves"
    #   "es creem" → "steam"
    #   "bloc de nota" → "notepad"
    #   "cromo" → "google chrome"
    #
    # Si la IA no lo reconoce o falla, se sigue con la búsqueda
    # en disco normalmente — es un fallback, no un reemplazo.
    # =====================================================

    nombre_ia = _resolver_nombre_con_ia(nombre)

    if nombre_ia and nombre_ia != nombre:
        print(f"[IA] Nombre sugerido: '{nombre}' → '{nombre_ia}'")
        nombre_ia_limpio = limpiar_nombre(nombre_ia)

        # segunda pasada por cache con el nombre de la IA
        for clave, data in list(cache.items()):
            clave_limpia = limpiar_nombre(clave)
            if (
                nombre_ia_limpio == clave_limpia
                or nombre_ia_limpio in clave_limpia
                or clave_limpia in nombre_ia_limpio
            ):
                ruta = data.get("ruta", "") if isinstance(data, dict) else str(data)
                if ruta and os.path.exists(ruta):
                    print(f"[IA] Encontrado en cache con nombre sugerido: {clave}")
                    guardar_alias_silencioso(nombre, clave)
                    if isinstance(data, dict):
                        return data, True, clave
                    return {"ruta": data, "procesos_cierre": [], "tipo": "normal"}, True, clave

        # segunda pasada por games_index
        for clave, data in list(games_index.items()):
            try:
                clave_limpia = limpiar_nombre(clave)
                if (
                    nombre_ia_limpio == clave_limpia
                    or nombre_ia_limpio in clave_limpia
                    or clave_limpia in nombre_ia_limpio
                ):
                    print(f"[IA] Encontrado en games index con nombre sugerido: {clave}")
                    guardar_alias_silencioso(nombre, clave)
                    return data, False, clave
            except Exception:
                pass

        # segunda pasada por apps_index
        for clave, data in list(apps_index.items()):
            try:
                if data.get("oculto", False):
                    continue
                clave_limpia = limpiar_nombre(clave)
                if (
                    nombre_ia_limpio == clave_limpia
                    or nombre_ia_limpio in clave_limpia
                    or clave_limpia in nombre_ia_limpio
                ):
                    ruta = data.get("ruta", "")
                    if ruta and os.path.exists(ruta):
                        print(f"[IA] Encontrado en apps index con nombre sugerido: {clave}")
                        guardar_alias_silencioso(nombre, clave)
                        return {"ruta": ruta, "procesos_cierre": [], "tipo": "normal"}, False, clave
            except Exception:
                pass

        # si la IA sugirió algo pero no se encontró en índices,
        # usar el nombre sugerido para la búsqueda en disco — puede
        # ser más exacto que el original mal transcripto
        nombre = nombre_ia

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

_migrar_txt_a_json_si_existe()  # one-shot: txt → json con timestamps
cache       = cargar_cache()
apps_index  = cargar_index()
games_index = cargar_games_index()