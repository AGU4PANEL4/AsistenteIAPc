from tools import TOOLS
from memory import memoria, guardar_memoria, registrar_accion
from aliases import *
from tts import hablar
from logger import log


def _ejecutar_pasos(pasos, origen="cadena"):
    """
    Ejecuta una lista de pasos [{intent, valor}, ...] en orden,
    hablando un resumen al final. Compartido entre cadenas en el
    momento y macros guardadas — la única diferencia es el texto
    de logging.

    Devuelve (exitos, fallos) para que quien llame decida qué decir.
    """
    exitos = 0
    fallos = 0

    for paso in pasos:
        ok = ejecutar(paso["intent"], paso["valor"])
        if ok:
            exitos += 1
        else:
            fallos += 1

    return exitos, fallos


def ejecutar(intent, valor):

    intent     = str(intent).lower().strip()
    valor      = str(valor).strip()
    valor_norm = valor.lower()

    # =====================================================
    # CADENA EN EL MOMENTO
    # intents.py devuelve "cadena" con los pasos serializados
    # como JSON cuando detecta "abre X y Y" etc.
    # =====================================================

    if intent == "cadena":
        import json
        try:
            pasos = json.loads(valor)
        except Exception:
            hablar("No pude entender la secuencia de acciones")
            return False

        exitos, fallos = _ejecutar_pasos(pasos, origen="cadena")

        if fallos > 0 and exitos == 0:
            hablar("No pude realizar ninguna de las acciones")
            return False

        return True

    # =====================================================
    # MACRO GUARDADA
    # intents.py devuelve "ejecutar_macro" con el nombre de la
    # macro como valor cuando detecta una coincidencia.
    # =====================================================

    if intent == "ejecutar_macro":
        from macros import obtener_macro
        nombre_macro, pasos = obtener_macro(valor)

        if not pasos:
            hablar(f"No encontré ninguna macro llamada {valor}")
            return False

        hablar(f"Ejecutando macro {nombre_macro}")
        exitos, fallos = _ejecutar_pasos(pasos, origen=f"macro:{nombre_macro}")

        if fallos > 0 and exitos == 0:
            hablar("La macro no pudo completarse")
            return False

        if fallos > 0:
            hablar(f"Macro completada con {fallos} paso{'s' if fallos > 1 else ''} fallido{'s' if fallos > 1 else ''}")

        return True

    # =====================================================
    # ALIAS
    # =====================================================

    nombre_real = traducir_alias(valor_norm)

    # =====================================================
    # MEMORIA
    # =====================================================

    memoria["ultima_accion"] = intent

    if intent in ("abrir_app", "cerrar_app", "minimizar_app", "maximizar_app"):
        memoria["ultima_app"] = nombre_real

    guardar_memoria()

    # =====================================================
    # VALIDAR TOOL
    # =====================================================

    if intent not in TOOLS:
        print(f"[Executor] Intent desconocido: {intent}")
        return False

    # =====================================================
    # EJECUTAR
    # =====================================================

    try:
        resultado = TOOLS[intent](nombre_real)
    except Exception as e:
        print("Error ejecutando tool:", e)
        # FIX/NUEVO: este catch-all es el punto donde un crash real
        # dentro de CUALQUIER tool (abrir una app, un recordatorio, un
        # control de media, etc.) termina — antes solo se imprimía en
        # consola, así que si nadie estaba mirando la ventana en ese
        # momento, el error se perdía por completo sin dejar ningún
        # rastro de qué pasó ni por qué. Esto es justamente el tipo de
        # fallo "importante" que vale la pena que quede en el log: una
        # acción que el usuario pidió y que el código no pudo
        # completar por una excepción real, no un simple "no
        # encontrado" (esos ya se manejan y se le explican al usuario
        # por voz más abajo, sin necesitar quedar en el log de errores).
        log.exception(
            f"Crash ejecutando intent '{intent}' con valor '{nombre_real}'"
        )
        hablar("Hubo un error ejecutando la acción")
        return False

    # =====================================================
    # SOPORTE PARA TUPLAS
    # =====================================================

    if isinstance(resultado, tuple):
        exito, nombre_decir = resultado
    else:
        exito        = resultado
        nombre_decir = nombre_real

    # nombre de la app a mencionar en los mensajes de media, o None
    # si el comando no especificó una app concreta (valor genérico "media")
    objetivo_media = (
        nombre_decir
        if nombre_decir and nombre_decir.lower() != "media"
        else None
    )

    # =====================================================
    # RESPUESTAS ERROR
    # =====================================================

    if not exito:

        mensajes_error = {
            "abrir_app":     f"No encontré {nombre_decir}",
            "cerrar_app":    f"No pude cerrar {nombre_decir}",
            "buscar_google": f"No pude buscar {nombre_decir}",
            "abrir_youtube": f"No pude buscar {nombre_decir} en YouTube",
            "minimizar_app": f"No encontré {nombre_decir} abierto",
            "maximizar_app": f"No encontré {nombre_decir} abierto",
            "media_pausar":    "No encontré nada para pausar" + (f" en {objetivo_media}" if objetivo_media else ""),
            "media_reanudar":  "No encontré nada para reanudar" + (f" en {objetivo_media}" if objetivo_media else ""),
            "media_siguiente": "No pude pasar de canción" + (f" en {objetivo_media}" if objetivo_media else ""),
            "media_anterior":  "No pude retroceder la canción" + (f" en {objetivo_media}" if objetivo_media else ""),
            "crear_recordatorio": "No entendí para cuándo quieres el recordatorio",
            "cancelar_recordatorio": "No pude cancelar ese recordatorio",
            "crear_temporizador": "No entendí la duración del temporizador",
            "cancelar_temporizador": "No pude cancelar ese temporizador",
        }

        # FIX: activar_startup/desactivar_startup/media_volumen_exacto/
        # crear_recordatorio/listar_recordatorios/cancelar_recordatorio/
        # crear_temporizador/listar_temporizadores/cancelar_temporizador
        # devuelven su propio mensaje específico en la tupla
        # (nombre_decir) en vez de un nombre de app — si está presente,
        # se usa tal cual en vez del texto genérico de abajo.
        intents_con_mensaje_propio = (
            "activar_startup", "desactivar_startup", "media_volumen_exacto",
            "crear_recordatorio", "listar_recordatorios", "cancelar_recordatorio",
            "crear_temporizador", "listar_temporizadores", "cancelar_temporizador",
            "crear_macro", "listar_macros", "eliminar_macro",
            "activar_no_molestar", "desactivar_no_molestar", "estado_no_molestar",
            "crear_recordatorio_recurrente",
        )

        # FIX: eliminar_alias ahora usa un flujo guiado completo (ver
        # eliminar_alias_guiado en registrar_alias.py) que ya habla
        # TODOS sus propios mensajes en cada paso, incluyendo los de
        # fallo ("no reconozco esa app", "no tiene alias guardados",
        # etc) — agregar el genérico "no pude realizar esa acción"
        # encima solo suena redundante y confuso.
        #
        # A diferencia de recapturar_app (que en su propio código NO
        # habla nada si falla, solo hace un print interno) — para ese
        # caso SÍ se necesita que executor.py hable el mensaje
        # genérico, o el usuario se quedaría sin ningún aviso. Por eso
        # esta excepción es específica de eliminar_alias, no general.
        if intent == "eliminar_alias":
            pass
        elif intent in intents_con_mensaje_propio and nombre_decir:
            hablar(nombre_decir)
        else:
            hablar(
                mensajes_error.get(intent, "No pude realizar esa acción")
            )

        return False

    # =====================================================
    # RESPUESTAS ÉXITO
    # =====================================================

    mensajes_exito = {
        "abrir_app":           f"Abriendo {nombre_decir}",
        "cerrar_app":          f"Cerrando {nombre_decir}",
        "buscar_google":       f"Buscando {nombre_decir} en Google",
        "abrir_youtube":       f"Buscando {nombre_decir} en YouTube",
        "abrir_url":           "Abriendo enlace",
        # FIX: antes acciones.py YA hablaba estos mensajes directamente
        # (ver activar_startup/desactivar_startup/estado_startup en
        # acciones.py) y luego este diccionario hacía hablar() otra vez
        # con un texto fijo → el usuario escuchaba el mensaje dos veces.
        # Ahora esas funciones devuelven (éxito, mensaje) sin hablar, y
        # aquí se usa ese mensaje (nombre_decir) directamente, una sola
        # vez, respetando los 3 textos distintos posibles (ya estaba
        # activado / se activó ahora / estado actual).
        "activar_startup":     nombre_decir,
        "desactivar_startup":  nombre_decir,
        "estado_startup":      nombre_decir,
        "minimizar_app":       f"Minimizando {nombre_decir}",
        "maximizar_app":       f"Trayendo {nombre_decir} al frente",
        "eliminar_alias":      None,
        "recapturar_app":      None,
        "media_pausar":        "Pausando" + (f" {objetivo_media}" if objetivo_media else ""),
        "media_reanudar":      "Reanudando" + (f" {objetivo_media}" if objetivo_media else ""),
        "media_siguiente":     "Siguiente",
        "media_anterior":      "Anterior",
        "media_subir_volumen": "Subiendo volumen",
        "media_bajar_volumen": "Bajando volumen",
        "media_silenciar":     "Silenciando",
        # FIX: media_volumen_exacto ahora también sigue el patrón de
        # tupla (éxito, mensaje) en vez de hablar directamente desde
        # media_control.py (ver el FIX en esa función) — se usa el
        # mensaje que ya viene calculado en nombre_decir.
        "media_volumen_exacto": nombre_decir,
        # FIX/NUEVO: crear_recordatorio también devuelve su propio
        # mensaje de confirmación (con la hora calculada y el texto
        # del recordatorio), igual que startup y volumen exacto.
        "crear_recordatorio":  nombre_decir,
        "crear_recordatorio_recurrente": nombre_decir,
        # NUEVO: listar y cancelar recordatorios también traen su
        # mensaje ya armado (la lista hablada, o la confirmación de
        # cuál se canceló).
        "listar_recordatorios":   nombre_decir,
        "cancelar_recordatorio":  nombre_decir,
        # NUEVO: temporizadores siguen el mismo patrón que recordatorios.
        "crear_temporizador":     nombre_decir,
        "listar_temporizadores":  nombre_decir,
        "cancelar_temporizador":  nombre_decir,
        # macros
        "crear_macro":            nombre_decir,
        "listar_macros":          nombre_decir,
        "eliminar_macro":         nombre_decir,
        # actualizaciones
        "buscar_actualizacion":   nombre_decir,
        # no molestar
        "activar_no_molestar":    nombre_decir,
        "desactivar_no_molestar": nombre_decir,
        "estado_no_molestar":     nombre_decir,
    }

    mensaje = mensajes_exito.get(intent)

    # NUEVO: registrar la acción en el historial corto de memory.py,
    # SOLO cuando tuvo éxito (si "abre algo que no existe" falló, no
    # tiene sentido que el historial diga que se abrió). El valor
    # guardado es el dato puro relevante para cada acción, no
    # necesariamente nombre_decir — por ejemplo, para
    # crear_recordatorio/crear_temporizador, nombre_decir ya es el
    # mensaje completo de confirmación ("Listo, te recordaré..."),
    # que no sirve para un historial corto; ahí se guarda `valor`
    # (el dato original "duración|texto") en su lugar.
    #
    # FIX: crear_recordatorio ahora pide confirmación antes de crear
    # de verdad (ver crear_recordatorio_accion en acciones.py). Si el
    # usuario dice que no, la función devuelve éxito=True (no es un
    # error, es una decisión válida) pero NO debe registrarse en el
    # historial como si se hubiera creado algo — se distingue por el
    # mensaje específico que devuelve ese caso.
    if intent in ("abrir_app", "cerrar_app"):
        registrar_accion(intent, nombre_real)
    elif intent in ("media_pausar", "media_reanudar", "media_volumen_exacto"):
        if objetivo_media:
            registrar_accion(intent, objetivo_media)
    elif intent == "crear_recordatorio":
        if nombre_decir != "No se creó el recordatorio":
            registrar_accion(intent, valor)
    elif intent == "crear_temporizador":
        registrar_accion(intent, valor)

    if mensaje:
        hablar(mensaje)

    return True