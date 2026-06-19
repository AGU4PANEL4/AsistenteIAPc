from tools import TOOLS
from memory import memoria, guardar_memoria
from aliases import *
from tts import hablar


def ejecutar(intent, valor):

    intent     = str(intent).lower().strip()
    valor      = str(valor).strip()
    valor_norm = valor.lower()

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
        }

        # FIX: activar_startup/desactivar_startup devuelven su propio
        # mensaje de error específico en la tupla (nombre_decir) en vez
        # de un nombre de app — si está presente, se usa tal cual.
        if intent in ("activar_startup", "desactivar_startup") and nombre_decir:
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
    }

    mensaje = mensajes_exito.get(intent)

    if mensaje:
        hablar(mensaje)

    return True