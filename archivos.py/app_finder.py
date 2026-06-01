import os
import json
from pathlib import Path
from difflib import SequenceMatcher
import re
import winreg
import unicodedata

CARPETA_DATOS = Path("datos")

CARPETA_DATOS.mkdir(
    parents=True,
    exist_ok=True
)

ARCHIVO_CACHE = CARPETA_DATOS / "cache.json"
ARCHIVO_INDEX = CARPETA_DATOS / "apps_index.json"
ARCHIVO_GAMES = CARPETA_DATOS / "games_index.json"
ARCHIVO_NO_ENCONTRADAS = CARPETA_DATOS / "apps_no_encontradas.txt"

# =========================================================
# INDEXAR JUEGOS STEAM
# =========================================================

def indexar_juegos_steam():

    global games_index

    games_index.clear()

    # =====================================
    # ENCONTRAR STEAM AUTOMÁTICAMENTE
    # =====================================

    steam_path = None

    try:

        clave = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Valve\Steam"
        )

        steam_path = Path(
            winreg.QueryValueEx(
                clave,
                "SteamPath"
            )[0]
        )

    except Exception as e:

        print(
            "No se encontró Steam:",
            e
        )

        return

    print(
        "Steam encontrada:",
        steam_path
    )

    # =====================================
    # OBTENER BIBLIOTECAS
    # =====================================

    bibliotecas = []

    steamapps_principal = (
        steam_path / "steamapps"
    )

    bibliotecas.append(
        steamapps_principal
    )

    library_file = (
        steamapps_principal /
        "libraryfolders.vdf"
    )

    try:

        if library_file.exists():

            contenido = library_file.read_text(
                encoding="utf-8",
                errors="ignore"
            )

            rutas = re.findall(
                r'"path"\s*"([^"]+)"',
                contenido,
                re.IGNORECASE
            )

            for ruta in rutas:

                ruta = ruta.replace(
                    "\\\\",
                    "\\"
                )

                biblioteca = (
                    Path(ruta) /
                    "steamapps"
                )

                if biblioteca.exists():

                    bibliotecas.append(
                        biblioteca
                    )

    except Exception as e:

        print(
            "Error leyendo libraryfolders:",
            e
        )

    # =====================================
    # ELIMINAR DUPLICADOS
    # =====================================

    bibliotecas = list(
        dict.fromkeys(bibliotecas)
    )

    print(
        "Bibliotecas encontradas:"
    )

    for b in bibliotecas:

        print(" -", b)

    # =====================================
    # INDEXAR JUEGOS
    # =====================================

    total = 0

    for steamapps in bibliotecas:

        try:

            for manifest in steamapps.glob(
                "appmanifest_*.acf"
            ):

                try:

                    texto = manifest.read_text(
                        encoding="utf-8",
                        errors="ignore"
                    )

                    match_nombre = re.search(
                        r'"name"\s*"([^"]+)"',
                        texto,
                        re.IGNORECASE
                    )

                    match_appid = re.search(
                        r'"appid"\s*"([^"]+)"',
                        texto,
                        re.IGNORECASE
                    )

                    if not match_nombre:
                        continue

                    nombre = limpiar_nombre(
                        match_nombre.group(1)
                    )

                    # =====================================
                    # FILTRO DE COSAS QUE NO SON JUEGOS
                    # =====================================

                    PALABRAS_EXCLUIDAS = [

                        "redistributable",
                        "steamworks",
                        "steamruntime",
                        "steam runtime",
                        "steamlinuxruntime",
                        "steam linux runtime",
                        "proton"

                    ]

                    if any(
                        palabra in nombre
                        for palabra in PALABRAS_EXCLUIDAS
                    ):

                        print(
                            "Ignorado:",
                            nombre
                        )

                        continue

                    appid = ""

                    if match_appid:

                        appid = (
                            match_appid.group(1)
                        )

                    # =====================================
                    # EVITAR DUPLICADOS
                    # =====================================

                    if nombre in games_index:

                        continue

                    exe_path = ""

                    # intentar obtener nombre real del juego desde manifest
                    match_exe = re.search(r'"installdir"\s*"([^"]+)"', texto, re.IGNORECASE)

                    if match_exe:
                        exe_path = match_exe.group(1)

                    games_index[nombre] = {
                        "ruta": str(manifest),
                        "appid": appid,
                        "tipo": "steam",
                        "exe_name": exe_path,
                        "oculto": False
                    }

                    print(
                        "Juego encontrado:",
                        nombre
                    )

                    total += 1

                except Exception as e:

                    print(
                        "Error manifest:",
                        e
                    )

        except Exception as e:

            print(
                "Error biblioteca:",
                e
            )

    guardar_games_index()

    print(
        f"Juegos Steam indexados: {total}"
    )

# =========================================================
# GUARDAR INDEX JUEGOS
# =========================================================

def guardar_games_index():

    with open(
        ARCHIVO_GAMES,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            games_index,
            f,
            indent=4,
            ensure_ascii=False
        )

# =========================================================
# CARGAR INDEX JUEGOS
# =========================================================

def cargar_games_index():

    if os.path.exists(
        ARCHIVO_GAMES
    ):

        try:

            with open(
                ARCHIVO_GAMES,
                "r",
                encoding="utf-8"
            ) as f:

                return json.load(f)

        except:

            return {}

    return {}

# =========================================================
# INDEXAR APPS
# =========================================================

def indexar_apps():

    global apps_index

    total = 0

    PALABRAS_BASURA = [

        "uninstall",
        "uninstaller",
        "setup",
        "update",
        "updater",
        "updatetool",
        "crash",
        "reporter",
        "helper",
        "installer",
        "bootstrap",
        "launcherupdater",
        "service",
        "assistant",
        "telemetry",
        "repair",
        "diagnostic",
        "migration",
        "install",
        "elevation",
        "launcherhelper",
        "webview",
        "runtime",
        "redistributable",
        "vc_redist",
        "prerequisite"

    ]

    RUTAS_BASURA = [

        "\\edgeupdate\\",
        "\\download\\",
        "\\installer\\",
        "\\install\\",
        "\\cache\\",
        "\\temp\\",
        "\\updater\\",
        "\\crashreports\\",
        "\\crashpad\\",
        "\\logs\\",
        "\\crash",
        "\\update",
        "\\uninstall"

    ]

    for ruta_base in RUTAS_RAPIDAS:

        try:

            if not ruta_base.exists():
                continue

            for root, dirs, files in os.walk(ruta_base):

                for archivo in files:

                    try:

                        if not archivo.lower().endswith(
                            (".lnk")
                        ):
                            continue

                        nombre = limpiar_nombre(
                            Path(archivo).stem
                        )

                        if len(nombre) < 3:
                            continue

                        ruta_completa = os.path.join(
                            root,
                            archivo
                        )

                        ruta_completa_lower = (
                            ruta_completa.lower()
                        )

                        # =========================
                        # FILTRO POR NOMBRE
                        # =========================

                        if any(
                            basura in nombre
                            for basura in PALABRAS_BASURA
                        ):
                            continue

                        # =========================
                        # FILTRO POR RUTA
                        # =========================

                        if any(
                            basura in ruta_completa_lower
                            for basura in RUTAS_BASURA
                        ):
                            continue

                        # =========================
                        # FILTRO VERSIONES
                        # MicrosoftEdge_X64_148...
                        # =========================

                        numeros = sum(
                            c.isdigit()
                            for c in nombre
                        )

                        if numeros > 8:
                            continue

                        # =========================
                        # EVITAR DUPLICADOS
                        # =========================

                        if nombre in apps_index:
                            continue

                        apps_index[nombre] = {

                            "ruta": ruta_completa,

                            "oculto": False

                        }

                        total += 1

                    except:
                        pass

        except:
            pass

    guardar_index(apps_index)

    print(
        f"Apps indexadas: {total}"
    )

# =========================================================
# GUARDAR INDEX
# =========================================================

def guardar_index(data):

    with open(
        ARCHIVO_INDEX,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )

# =========================================================
# CARGAR INDEX
# =========================================================

def cargar_index():

    try:

        with open(
            ARCHIVO_INDEX,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    except:

        return {}

# =========================================================
# REGISTRAR APLICACION NO ENCONTRADA
# =========================================================

def registrar_no_encontrada(nombre):

    nombre = nombre.lower().strip()

    apps = cargar_no_encontradas()

    if nombre in apps:
        return

    with open(
        ARCHIVO_NO_ENCONTRADAS,
        "a",
        encoding="utf-8"
    ) as f:

        f.write(nombre + "\n")

# =========================================================
# CARGAR APLICACION NO ENCONTRADA
# =========================================================

def cargar_no_encontradas():

    try:

        with open(
            ARCHIVO_NO_ENCONTRADAS,
            "r",
            encoding="utf-8"
        ) as f:

            return set(

                linea.strip().lower()

                for linea in f

                if linea.strip()

            )

    except:

        return set()

# =========================================================
# CARGAR CACHE
# =========================================================

def cargar_cache():

    try:

        with open(
            ARCHIVO_CACHE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

            # MIGRACIÓN AUTOMÁTICA
            cambiado = False

            for clave, valor in list(data.items()):

                if isinstance(valor, str):

                    data[clave] = {
                        "ruta": valor,
                        "procesos_cierre": [],
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

    with open(
        ARCHIVO_CACHE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False
        )

# =========================================================
# NORMALIZAR
# =========================================================

def limpiar_nombre(texto):

    texto = texto.lower()

    texto = unicodedata.normalize(
        "NFKD",
        texto
    )

    reemplazos = {

        "’": "",
        "'": "",
        "®": "",
        "™": "",
        ":": " ",
        "-": " ",
        "_": " "

    }

    for viejo, nuevo in reemplazos.items():

        texto = texto.replace(
            viejo,
            nuevo
        )

    texto = re.sub(
        r"[^a-z0-9 ]",
        "",
        texto
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    ).strip()

    return texto


# =========================================================
# DUPLICADOS
# =========================================================

def score_nombre(nombre):

    nombre = nombre.lower().strip()

    score = 0


    # =====================================================
    # MÁS LARGO = MÁS PROBABLE QUE SEA CORRECTO
    # =====================================================

    score += len(nombre)


    # =====================================================
    # ESPACIOS = NOMBRE MÁS NATURAL
    # =====================================================

    score += nombre.count(" ") * 5


    # =====================================================
    # CARACTERES ESPECIALES ÚTILES
    # =====================================================

    if "(" in nombre or ")" in nombre:
        score += 4

    if "!" in nombre:
        score += 4


    # =====================================================
    # PENALIZAR NOMBRES ROTOS
    # =====================================================

    palabras_malas = [

        "app",
        "launcher",
        "shipping",
        "release",
        "win64",
        "bin",
        "programs"

    ]

    for mala in palabras_malas:

        if mala in nombre:
            score -= 15


    # =====================================================
    # PENALIZAR SI TERMINA CORTADO
    # =====================================================

    if len(nombre.split()) == 1 and len(nombre) < 6:
        score -= 10


    return score



def limpiar_cache_duplicados():

    global cache

    nuevas = {}

    eliminadas = []

    for clave, data in list(cache.items()):

        clave_limpia = limpiar_nombre(clave)

        # ==========================================
        # OBTENER RUTA
        # ==========================================

        if isinstance(data, dict):

            ruta = data.get("ruta", "")

            data_nueva = data.copy()

        else:

            ruta = str(data)

            data_nueva = {

                "ruta": ruta,
                "procesos_cierre": [],
                "pids": [],
                "tipo": "normal"

            }

        nombre_real = obtener_nombre_cache(ruta)

        nombre_real_limpio = limpiar_nombre(
            nombre_real
        )

        # ==========================================
        # DUPLICADOS
        # ==========================================

        if nombre_real_limpio in nuevas:

            clave_existente = nuevas[
                nombre_real_limpio
            ][0]

            actual_score = (

                len(clave_existente.split()),
                len(clave_existente)

            )

            nuevo_score = (

                len(nombre_real.split()),
                len(nombre_real)

            )

            if nuevo_score > actual_score:

                eliminadas.append(
                    clave_existente
                )

                nuevas[
                    nombre_real_limpio
                ] = (

                    nombre_real,
                    data_nueva

                )

            else:

                eliminadas.append(
                    clave
                )

        else:

            nuevas[
                nombre_real_limpio
            ] = (

                nombre_real,
                data_nueva

            )

    # ==========================================
    # RECONSTRUIR CACHE
    # ==========================================

    cache = {

        clave: data

        for _, (clave, data)

        in nuevas.items()

    }

    guardar_cache()

    # ==========================================
    # DEBUG
    # ==========================================

    if eliminadas:

        print(
            "Duplicados eliminados:"
        )

        for x in eliminadas:

            print("-", x)

    else:

        print(
            "No había duplicados"
        )

# =========================================================
# APPS NO ENCONTRADAS
# =========================================================

def registrar_no_encontrada(nombre):

    try:

        nombre = nombre.lower().strip()

        existentes = []

        if os.path.exists(ARCHIVO_NO_ENCONTRADAS):

            with open(
                ARCHIVO_NO_ENCONTRADAS,
                "r",
                encoding="utf-8"
            ) as f:

                existentes = [
                    x.strip()
                    for x in f.readlines()
                ]

        if nombre not in existentes:

            with open(
                ARCHIVO_NO_ENCONTRADAS,
                "a",
                encoding="utf-8"
            ) as f:

                f.write(nombre + "\n")

    except Exception as e:

        print(
            "Error registrando no encontrada:",
            e
        )


# =========================================================
# SIMILITUD
# =========================================================

def parecido(a, b):

    return SequenceMatcher(
        None,
        a,
        b
    ).ratio()


# =========================================================
# RUTAS RÁPIDAS
# =========================================================

RUTAS_RAPIDAS = [

    Path(os.getenv("APPDATA", "")) /
    "Microsoft" /
    "Windows" /
    "Start Menu" /
    "Programs",

    Path(
        "C:/ProgramData/Microsoft/Windows/Start Menu/Programs"
    ),

    Path(os.getenv("PROGRAMFILES", "")),

    Path(os.getenv("PROGRAMFILES(X86)", "")),

    Path(os.getenv("LOCALAPPDATA", ""))

]


# =========================================================
# BUSCAR EN RUTA
# =========================================================

def buscar_en_ruta(nombre, ruta):

    try:

        nombre_limpio = limpiar_nombre(nombre)

        mejor = None
        mejor_score = 0

        IGNORAR = [

            "overlay",
            "updater",
            "crash",
            "installer",
            "helper",
            "service",
            "bootstrap",
            "renderer"

        ]

        for archivo in ruta.rglob("*"):

            if not archivo.is_file():
                continue

            if not (

                archivo.name.lower().endswith(".exe")

                or

                archivo.name.lower().endswith(".lnk")

            ):

                continue

            if any(

                x in archivo.name.lower()

                for x in IGNORAR

            ):

                continue

            base = limpiar_nombre(
                archivo.stem
            )

            carpeta = limpiar_nombre(
                archivo.parent.name
            )

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
                mejor = archivo

        if mejor_score > 0.80:

            return str(mejor)

    except Exception as e:

        print(
            "Error búsqueda:",
            e
        )

    return None


# =========================================================
# BUSCAR EN DISCOS
# =========================================================

def obtener_discos():

    discos = []

    for letra in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":

        ruta = f"{letra}:\\"

        if os.path.exists(ruta):

            discos.append(
                Path(ruta)
            )

    return discos


# =========================================================
# OBTENER NOMBRE EN CACHE
# =========================================================

def obtener_nombre_cache(ruta):

    archivo = Path(ruta)

    # =====================================================
    # .LNK
    # =====================================================

    if archivo.suffix.lower() == ".lnk":

        return archivo.stem


    exe = archivo.stem

    carpeta = archivo.parent.name

    carpeta_abuela = archivo.parent.parent.name


    ignorar = [

        "win64",
        "bin",
        "app",
        "current",
        "shipping",
        "release",
        "programs",
        "launcher"

    ]


    # =====================================================
    # CARPETAS BASURA
    # =====================================================

    if (

        carpeta.lower().startswith("app-")

        or

        carpeta.lower() in ignorar

    ):

        if (

            carpeta_abuela.lower() not in ignorar

            and

            not carpeta_abuela.lower().startswith("app-")

        ):

            return carpeta_abuela

        return exe


    # =====================================================
    # VERSIONES NUMÉRICAS
    # =====================================================

    if any(c.isdigit() for c in carpeta):

        if (

            carpeta_abuela.lower() not in ignorar

            and

            not any(c.isdigit() for c in carpeta_abuela)

        ):

            return carpeta_abuela

        return exe


    # =====================================================
    # SI LA CARPETA PARECE MÁS REAL QUE EL EXE
    # =====================================================

    if len(carpeta) > 3:

        return carpeta


    return exe

# =========================================================
# BUSCAR APP
# =========================================================

def buscar_app(nombre):

    global cache

    limpiar_cache_duplicados()

    nombre = nombre.lower().strip()

    nombre_limpio = limpiar_nombre(nombre)


    # =====================================================
    # CACHE
    # =====================================================

    for clave, data in cache.items():

        clave_limpia = limpiar_nombre(clave)

        if (

            nombre_limpio == clave_limpia

            or

            nombre_limpio in clave_limpia

            or

            clave_limpia in nombre_limpio

        ):

            ruta = data.get("ruta", "")

            if ruta and os.path.exists(ruta):

                print("Cache:", clave)

                if isinstance(data, dict):

                    return data, True, clave

                return {

                    "ruta": data,
                    "procesos_cierre": [],
                    "tipo": "normal"

                }, True, clave

    # =====================================================
    # GAMES INDEX
    # =====================================================

    for clave, data in games_index.items():

        try:

            clave_limpia = limpiar_nombre(
                clave
            )

            if (

                nombre_limpio == clave_limpia

                or

                nombre_limpio in clave_limpia

                or

                clave_limpia in nombre_limpio

            ):

                print(
                    "Game Index:",
                    clave
                )

                return data, False, clave

        except:
            pass

    # =====================================================
    # INDEX
    # =====================================================

    for clave, data in apps_index.items():

        try:

            if data.get(
                "oculto",
                False
            ):
                continue

            clave_limpia = limpiar_nombre(
                clave
            )

            if (

                nombre_limpio == clave_limpia

                or

                nombre_limpio in clave_limpia

                or

                clave_limpia in nombre_limpio

            ):

                ruta = data.get(
                    "ruta",
                    ""
                )

                if ruta and os.path.exists(ruta):

                    print(
                        "Index:",
                        clave
                    )

                    return {

                        "ruta": ruta,
                        "procesos_cierre": [],
                        "tipo": "normal"

                    }, False, clave

        except:
            pass


    # =====================================================
    # APPS NO ENCONTRADAS
    # =====================================================

    no_encontradas = cargar_no_encontradas()

    if nombre in no_encontradas:

        print(
            "App marcada como no encontrada anteriormente"
        )

        from acciones import confirmar_rebuscar

        confirmar = confirmar_rebuscar(nombre)

        if not confirmar:

            return None, False, None


    # =====================================================
    # BÚSQUEDA RÁPIDA
    # =====================================================

    for ruta_base in RUTAS_RAPIDAS:

        try:

            if not ruta_base.exists():
                continue

            resultado = buscar_en_ruta(
                nombre,
                ruta_base
            )

            if resultado:

                nombre_cache = obtener_nombre_cache(
                    resultado
                ).lower()

                data = {

                    "ruta": resultado,
                    "procesos_cierre": [],
                    "tipo": "normal"

                }

                from acciones import confirmar_apertura

                if not confirmar_apertura(nombre_cache):

                    print(
                        "Usuario canceló la apertura"
                    )

                    return None, False, None

                cache[nombre_cache] = data

                guardar_cache()

                print("Guardando en cache:", nombre_cache)
                print("Ruta cache:", ARCHIVO_CACHE)

                print(
                    "Nueva app guardada:",
                    nombre_cache
                )


                # =================================================
                # QUITAR DEL TXT SI YA SE ENCONTRÓ
                # =================================================

                try:

                    apps = cargar_no_encontradas()

                    if nombre in apps:

                        apps.remove(nombre)

                        with open(
                            ARCHIVO_NO_ENCONTRADAS,
                            "w",
                            encoding="utf-8"
                        ) as f:

                            for app in apps:

                                f.write(app + "\n")

                except:
                    pass


                return data, False, nombre_cache

        except Exception as e:

            print(
                "Error búsqueda rápida:",
                e
            )


    # =====================================================
    # BÚSQUEDA EN TODOS LOS DISCOS
    # =====================================================

    for disco in obtener_discos():

        try:

            resultado = buscar_en_ruta(
                nombre,
                disco
            )

            if resultado:

                nombre_cache = obtener_nombre_cache(
                    resultado
                ).lower()

                data = {

                    "ruta": resultado,
                    "procesos_cierre": [],
                    "tipo": "normal"

                }

                from acciones import confirmar_apertura

                if not confirmar_apertura(nombre_cache):

                    print(
                        "Usuario canceló la apertura"
                    )

                    return None, False, None

                cache[nombre_cache] = data

                guardar_cache()

                print("Guardando en cache:", nombre_cache)
                print("Ruta cache:", ARCHIVO_CACHE)

                print(
                    "Nueva app guardada:",
                    nombre_cache
                )


                # =================================================
                # QUITAR DEL TXT SI YA SE ENCONTRÓ
                # =================================================

                try:

                    apps = cargar_no_encontradas()

                    if nombre in apps:

                        apps.remove(nombre)

                        with open(
                            ARCHIVO_NO_ENCONTRADAS,
                            "w",
                            encoding="utf-8"
                        ) as f:

                            for app in apps:

                                f.write(app + "\n")

                except:
                    pass


                return data, False, nombre_cache

        except Exception as e:

            print(
                "Error búsqueda disco:",
                e
            )


    # =====================================================
    # NO ENCONTRADA
    # =====================================================

    registrar_no_encontrada(nombre)

    return None, False, None

# =========================================================
# CARGAR ARCHIVOS
# =========================================================

cache = cargar_cache()

apps_index = cargar_index()

games_index = cargar_games_index()