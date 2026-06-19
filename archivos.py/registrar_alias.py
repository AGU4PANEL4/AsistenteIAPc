import time
from tts import hablar
from voice import escuchar
from aliases import agregar_alias, aliases, cargar_aliases
from session import sesion
import app_finder

# =========================================================
# REGISTRAR ALIAS MANUALMENTE
# Flujo:
# 1. Preguntar nombre de la app
# 2. Buscar en cache → si encuentra, pedir alias
# 3. Si no encuentra, buscar en disco → guardar en cache
# 4. Pedir los alias que se quieren registrar
# =========================================================

def escuchar_con_timeout(timeout=8):
    inicio = time.time()
    while True:
        respuesta = escuchar()
        if respuesta:
            return respuesta
        if time.time() - inicio > timeout:
            return ""


def buscar_en_cache(nombre):
    """Busca en cache por nombre aproximado."""
    nombre_limpio = app_finder.limpiar_nombre(nombre)

    for clave, data in app_finder.cache.items():
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

    SI = ["si", "sí", "dale", "ok", "claro", "sí quiero"]

    if not any(x in respuesta.lower() for x in SI):
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