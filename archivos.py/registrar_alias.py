import time
from tts import hablar
from voice import escuchar
from aliases import agregar_alias, aliases, cargar_aliases, alias_por_app, eliminar_alias, traducir_alias
from session import sesion
import app_finder
from voz_utils import elegir_de_lista, interpretar_confirmacion, escuchar_con_reintento

# =========================================================
# REGISTRAR ALIAS MANUALMENTE
# Flujo:
# 1. Preguntar nombre de la app
# 2. Buscar en cache → si encuentra, pedir alias
# 3. Si no encuentra, buscar en disco → guardar en cache
# 4. Pedir los alias que se quieren registrar
# =========================================================

# FIX/NUEVO: escuchar_con_timeout() vivía acá duplicada casi
# idéntica a la de gestionar_macro.py — se unificaron en
# escuchar_con_reintento() (voz_utils.py), que de paso agrega
# soporte para "espera"/"dame un segundo" (ver ese archivo). Se deja
# este alias con el nombre viejo para no tener que tocar cada
# llamada de este archivo.
def escuchar_con_timeout(timeout=8):
    return escuchar_con_reintento(timeout=timeout)


def buscar_en_cache(nombre):
    """
    Busca en cache por nombre aproximado.

    NUEVO: si `nombre` ya es un alias conocido (ej. el usuario dice
    "osu" y ya existe el alias "osu" -> "osu!(lazer)"), se traduce
    primero al nombre real antes de buscar. Esto hace que decir un
    alias ya guardado encuentre la app de inmediato, sin depender de
    que el texto del alias también coincida por casualidad con la
    clave de cache (que normalmente es el nombre real de la app, no
    el alias) — útil tanto para registrar un alias nuevo para una app
    que ya tiene otros, como para identificar la app al eliminar uno.
    """
    nombre_traducido = traducir_alias(nombre)
    nombre_limpio     = app_finder.limpiar_nombre(nombre_traducido)

    # FIX: capturar_pids_por_nombre() (acciones_apps.py) corre en un
    # hilo daemon en background después de abrir una app y puede
    # estar mutando app_finder.cache durante hasta 60 segundos. Si en
    # esa ventana se pide registrar/eliminar un alias para esa misma
    # app, iterar cache.items() directo (sin copia) podía lanzar
    # "RuntimeError: dictionary changed size during iteration" — mismo
    # problema ya arreglado en app_finder.buscar_app(). list(...) toma
    # una copia atómica, evitando el crash.
    for clave, data in list(app_finder.cache.items()):
        clave_limpia = app_finder.limpiar_nombre(clave)
        if (
            nombre_limpio == clave_limpia
            or nombre_limpio in clave_limpia
            or clave_limpia in nombre_limpio
        ):
            return clave, data

    return None, None


def pedir_aliases(nombre_app, clave_cache, timeout=10):
    """
    Pregunta al usuario qué aliases quiere registrar.
    Acepta múltiples aliases uno por uno hasta que diga 'listo' o 'eso es todo'.
    """
    TERMINAR = {"listo", "eso es todo", "ya", "terminar", "fin", "no más", "no mas"}

    aliases_guardados = []

    hablar(f"¿Qué alias quieres registrar para {nombre_app}? Di uno a la vez y cuando termines di 'listo'.")

    while True:
        respuesta = escuchar_con_timeout(timeout)

        if not respuesta:
            hablar("No escuché nada, terminando.")
            break

        respuesta = respuesta.lower().strip()

        if respuesta in TERMINAR:
            break

        # verificar que no sea vacío o muy corto
        if len(respuesta) < 2:
            hablar("Eso es muy corto, prueba con otro.")
            continue

        agregar_alias(respuesta, clave_cache)
        aliases_guardados.append(respuesta)
        hablar(f"Guardado. ¿Otro alias?")

    return aliases_guardados


def registrar_alias_manual(valor=None):
    """
    Función principal — llamada desde executor.
    """

    # =====================================================
    # PASO 1: PREGUNTAR NOMBRE DE LA APP
    # =====================================================

    hablar("¿Para qué app quieres registrar aliases?")

    nombre = escuchar_con_timeout(timeout=8)

    if not nombre:
        hablar("No escuché nada.")
        return False

    nombre = nombre.lower().strip()
    print(f"[ALIAS] Buscando: '{nombre}'")

    # =====================================================
    # PASO 2: BUSCAR EN CACHE
    # =====================================================

    clave_cache, data_cache = buscar_en_cache(nombre)

    if clave_cache:
        print(f"[ALIAS] Encontrado en cache: '{clave_cache}'")
        hablar(f"Encontré {clave_cache} en el registro.")

        aliases_guardados = pedir_aliases(clave_cache, clave_cache)

        if aliases_guardados:
            hablar(f"Registré {len(aliases_guardados)} alias para {clave_cache}.")
        else:
            hablar("No se registró ningún alias.")

        return True

    # =====================================================
    # PASO 3: NO ESTÁ EN CACHE — BUSCAR EN DISCO
    # =====================================================

    hablar(f"No encontré {nombre} en el registro. Voy a buscarlo, puede tardar un momento.")

    from cancelacion import iniciar_cancelacion, detener_cancelacion, fue_cancelado

    iniciar_cancelacion()

    try:
        resultado, desde_cache, nombre_encontrado = app_finder.buscar_app(
            nombre,
            fn_cancelado=fue_cancelado
        )
    finally:
        detener_cancelacion()

    if fue_cancelado():
        hablar("Búsqueda cancelada.")
        return False

    if not resultado:
        hablar(f"No pude encontrar {nombre}.")
        return False

    # =====================================================
    # PASO 4: ENCONTRADO EN DISCO — CONFIRMAR Y GUARDAR
    # =====================================================

    print(f"[ALIAS] Encontrado: '{nombre_encontrado}'")
    hablar(f"Encontré {nombre_encontrado}. ¿Quieres guardar aliases para esta app?")

    respuesta = escuchar_con_timeout(timeout=8)

    if not respuesta:
        hablar("No escuché respuesta.")
        return False

    # FIX/NUEVO: antes esto comparaba contra una lista fija de
    # palabras propia de esta función, distinta (e inconsistente) de
    # la usada en el resto del proyecto (es_afirmacion en voz_utils.py)
    # — la misma respuesta del usuario podía reconocerse como sí en un
    # flujo y no en otro, solo por estar en un archivo distinto. Ahora
    # usa interpretar_confirmacion() (ver voz_utils.py), que además
    # consulta a la IA si la respuesta no calza con ninguna palabra
    # conocida, antes de asumir que se canceló.
    resultado = interpretar_confirmacion(
        respuesta,
        contexto=f"¿Quieres guardar aliases para {nombre_encontrado}?",
    )

    if resultado is not True:
        hablar("Cancelado.")
        return False

    # guardar en cache si no estaba
    if not desde_cache:
        ruta_str     = resultado.get("ruta", "")
        carpeta_raiz = resultado.get("carpeta_raiz", "")

        app_finder.cache[nombre_encontrado] = {
            "ruta":               ruta_str,
            "carpeta_raiz":       carpeta_raiz,
            "procesos_cierre":    resultado.get("procesos_cierre", []),
            "pids":               [],
            "tipo":               resultado.get("tipo", "normal"),
            "carpetas_detectadas": []
        }
        app_finder.guardar_cache()
        print(f"[ALIAS] Guardado en cache: '{nombre_encontrado}'")

    # =====================================================
    # PASO 5: PEDIR ALIASES
    # =====================================================

    aliases_guardados = pedir_aliases(nombre_encontrado, nombre_encontrado)

    if aliases_guardados:
        hablar(f"Registré {len(aliases_guardados)} alias para {nombre_encontrado}.")
    else:
        hablar("No se registró ningún alias.")

    return True

# =========================================================
# ELIMINAR ALIAS — FLUJO GUIADO
# FIX: antes "olvida el alias X" pedía al usuario decir el alias
# EXACTO de una sola vez, y lo comparaba con coincidencia exacta
# contra lo guardado (ver eliminar_alias en aliases.py). Si Whisper
# transcribía el alias de forma distinta a como se guardó la vez
# anterior (algo frecuente con nombres de apps en inglés — ver
# voice.py), la búsqueda fallaba aunque el alias SÍ existiera,
# diciendo "no tenía ningún alias llamado X" de forma confusa.
#
# Ahora el flujo es guiado, igual al de registrar_alias_manual:
# 1. Preguntar de qué APP se quiere eliminar un alias (no el alias
#    en sí — el nombre de la app es más fácil de transcribir bien
#    porque suele repetirse y el usuario ya lo dijo otras veces).
# 2. Buscar esa app con tolerancia (cache, índice de apps/juegos).
# 3. Mostrar los alias EXISTENTES para esa app, numerados.
# 4. Dejar elegir por número o diciendo el alias aproximado — ya no
#    se necesita coincidencia exacta de texto, porque se compara
#    contra una lista corta y conocida, no contra todo el diccionario.
# =========================================================

def _buscar_app_para_alias(nombre):
    """
    Busca una app/juego ya conocido (cache, o índices de app_finder)
    por nombre aproximado — usado para identificar de qué app se
    quiere eliminar un alias. A diferencia de registrar_alias_manual,
    NO busca en disco si no se encuentra, porque para eliminar un
    alias la app casi seguro ya está indexada (si tiene alias
    guardados, es porque se encontró antes).

    NUEVO: también traduce primero si `nombre` ya es un alias
    conocido — mismo motivo que en buscar_en_cache.
    """
    clave_cache, _ = buscar_en_cache(nombre)
    if clave_cache:
        return clave_cache

    nombre_traducido = traducir_alias(nombre)
    nombre_limpio     = app_finder.limpiar_nombre(nombre_traducido)

    for indice in (app_finder.games_index, app_finder.apps_index):
        for clave in indice.keys():
            clave_limpia = app_finder.limpiar_nombre(clave)
            if (
                nombre_limpio == clave_limpia
                or nombre_limpio in clave_limpia
                or clave_limpia in nombre_limpio
            ):
                return clave

    return None


def _mensaje_aliases_existentes(app_encontrada, lista_alias):
    """Construye el texto numerado de alias existentes para una app."""
    return "; ".join(
        f"{i+1}: {alias}" for i, alias in enumerate(lista_alias)
    )


def eliminar_alias_guiado(valor=None):
    """
    Función principal del flujo guiado — llamada desde executor.

    Si `valor` ya trae un nombre (ej: el usuario dijo "olvida el
    alias de brawlhalla" en el mismo comando), se usa directo como
    punto de partida en el PASO 1, sin volver a preguntar algo que
    el usuario ya dijo. Si viene vacío, se pregunta normalmente.
    """

    # =====================================================
    # PASO 1: IDENTIFICAR DE QUÉ APP (preguntando si falta)
    # =====================================================

    nombre = (valor or "").strip()

    if not nombre:
        hablar("¿De qué app quieres eliminar un alias?")
        nombre = escuchar_con_timeout(timeout=8)

    if not nombre:
        hablar("No escuché nada.")
        return False

    nombre = nombre.lower().strip()
    print(f"[ALIAS] Buscando app para eliminar alias: '{nombre}'")

    # =====================================================
    # PASO 2: IDENTIFICAR LA APP
    # =====================================================

    app_encontrada = _buscar_app_para_alias(nombre)

    if not app_encontrada:
        hablar(f"No reconozco {nombre}. ¿Puedes decir el nombre de otra forma?")
        return False

    # =====================================================
    # PASO 3: LISTAR ALIAS EXISTENTES PARA ESA APP
    # =====================================================

    lista_alias = alias_por_app(app_encontrada)

    if not lista_alias:
        hablar(f"{app_encontrada} no tiene ningún alias guardado.")
        return False

    if len(lista_alias) == 1:
        # un solo alias — no hace falta preguntar cuál, se confirma
        # directo para no alargar la interacción sin necesidad
        unico = lista_alias[0]
        hablar(f"{app_encontrada} tiene un solo alias: {unico}. ¿Lo elimino?")

        respuesta = escuchar_con_timeout(timeout=8)

        # FIX/NUEVO: misma razón que en registrar_alias_manual — usa
        # interpretar_confirmacion() (voz_utils.py) en vez de una
        # lista de palabras fija y propia de esta función, que además
        # consulta a la IA si la respuesta no calza con nada conocido.
        resultado = interpretar_confirmacion(
            respuesta,
            contexto=f"¿Elimino el alias {unico} de {app_encontrada}?",
        )

        if resultado is True:
            eliminar_alias(unico)
            hablar(f"Listo, eliminé el alias {unico}.")
            return True

        # FIX: antes "no escuché nada" (timeout) y "el usuario dijo
        # que no" caían en el mismo mensaje genérico "No se eliminó
        # nada" — sin que el usuario supiera si su silencio se
        # interpretó como rechazo, o si de verdad dijo que no. Esto
        # generaba confusión: si el reconocimiento de voz no captó
        # nada a tiempo (timeout corto, o ruido), el usuario tenía
        # que repetir TODO el flujo desde el principio sin entender
        # bien por qué no funcionó la primera vez.
        #
        # Ahora se distingue: si no se escuchó nada, se avisa
        # explícitamente que no hubo respuesta (no que se decidió
        # cancelar), para que quede claro que fue un problema de
        # escucha, no de decisión.
        if not respuesta:
            hablar("No escuché tu respuesta, no se eliminó nada.")
        else:
            hablar("Entendido, no se eliminó nada.")

        return False

    # varios alias — se listan numerados para elegir
    texto_opciones = "; ".join(
        f"{i+1}: {alias}" for i, alias in enumerate(lista_alias)
    )
    hablar(f"{app_encontrada} tiene estos alias: {texto_opciones}. ¿Cuál quieres eliminar?")

    respuesta = escuchar_con_timeout(timeout=10)

    if not respuesta:
        hablar("No escuché nada.")
        return False

    # "todos" — eliminar todos los alias de esta app de una vez
    if respuesta.lower().strip() in ("todos", "todos los alias", "elimínalos todos", "eliminalos todos"):
        for alias in lista_alias:
            eliminar_alias(alias)
        hablar(f"Eliminé los {len(lista_alias)} alias de {app_encontrada}.")
        return True

    indice = elegir_de_lista(respuesta, lista_alias)

    if indice is None:
        hablar("No identifiqué cuál de esos quieres eliminar, intenta de nuevo.")
        return False

    alias_elegido = lista_alias[indice]
    eliminar_alias(alias_elegido)
    hablar(f"Listo, eliminé el alias {alias_elegido}.")
    return True