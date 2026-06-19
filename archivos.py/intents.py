import re
from aliases import traducir_alias
from memory import memoria

# =========================================================
# NORMALIZAR
# corrige errores comunes del reconocedor + fonética inglés
# =========================================================

CORRECCIONES = {
    "sierra":      "cierra",
    "cierra lo":   "ciérralo",
    "abre lo":     "ábrelo",
    "estrike":     "strike",
    "esteam":      "steam",
    "espider":     "spider",
    "udering":     "wuthering",
    "utering":     "wuthering",
    "withering":   "wuthering",
    "buttering":   "wuthering",
    "fasmofobia":  "phasmophobia",
    "phasmofobia": "phasmophobia",
}

def normalizar(comando):
    comando = comando.lower().strip()
    for error, correcto in CORRECCIONES.items():
        if error in comando:
            comando = comando.replace(error, correcto)
    return comando

# =========================================================
# MULETILLAS / FRASES DE CORTESÍA
# FIX: antes "me gustaría abrir spotify" no calzaba con nada
# porque las reglas solo reconocían "abre spotify", "abrir
# spotify", etc. Esto quita esos prefijos conversacionales
# antes de intentar reconocer el comando, así que frases más
# naturales también funcionan con las reglas rápidas (sin
# tener que pasar siempre por la IA).
# =========================================================

MULETILLAS = [
    "oye jarvis",
    "oye",
    "por favor",
    "porfa",
    "podrías",
    "podrias",
    "puedes",
    "podes",
    "me gustaría",
    "me gustaria",
    "quisiera",
    "necesito que",
    "quiero que",
    "necesito",
    "quiero",
    "ayúdame a",
    "ayudame a",
]

def quitar_muletillas(comando):
    cambiado = True
    while cambiado:
        cambiado = False
        for muletilla in MULETILLAS:
            if comando == muletilla:
                comando = ""
                cambiado = True
                break
            if comando.startswith(muletilla + " "):
                comando = comando[len(muletilla):].strip()
                cambiado = True
                break
        for sufijo in (" por favor", " porfa"):
            if comando.endswith(sufijo):
                comando = comando[: -len(sufijo)].strip()
                cambiado = True
    return comando

# =========================================================
# REFERENCIAS GENÉRICAS A LA ÚLTIMA APP
# "ábrelo" ya se manejaba como frase completa, pero "abrir
# esto" / "cierra eso" (verbo + nombre suelto) no. Si después
# de quitar el verbo el "nombre" es en realidad una referencia
# como "esto"/"eso"/"lo", se reemplaza por la última app usada.
# =========================================================

REFERENCIAS_ULTIMA_APP = {
    "esto", "eso", "ello", "esta", "ésta",
    "esa", "ese", "lo", "la",
}

# =========================================================
# DETECTAR INTENT
# =========================================================

def detectar_intent(comando):

    comando = normalizar(comando)
    comando = quitar_muletillas(comando)
    ultima  = memoria.get("ultima_app", "")

    # =====================================================
    # REFERENCIAS A ÚLTIMA APP
    # =====================================================

    CERRAR_ESTO = [
        "ciérralo", "cierralo", "cerralo",
        "cierra eso", "cierra esto",
        "cierra la app", "ciérrala"
    ]

    ABRIR_ESTO = [
        "ábrelo", "abrelo",
        "abre eso", "abre esto",
        "ábrela", "abrela"
    ]

    MINIMIZAR_ESTO = [
        "minimízalo", "minimizalo",
        "minimízala", "minimizala",
        "ocúltalo", "ocultalo",
        "ocúltala", "ocultala",
    ]

    MAXIMIZAR_ESTO = [
        "maximízalo", "maximizalo",
        "maximízala", "maximizala",
        "tráelo", "traelo",
        "muéstralo", "muestralo",
        "tráela", "traela",
    ]

    if ultima:
        if comando in CERRAR_ESTO:
            return "cerrar_app", ultima
        if comando in ABRIR_ESTO:
            return "abrir_app", ultima
        if comando in MINIMIZAR_ESTO:
            return "minimizar_app", ultima
        if comando in MAXIMIZAR_ESTO:
            return "maximizar_app", ultima

    # =====================================================
    # YOUTUBE
    # =====================================================

    YOUTUBE_PALABRAS = [
        "en youtube", "youtube", "en you tube"
    ]

    if comando.startswith(("busca ", "buscar ")):
        busqueda = re.sub(r"^buscar?\s+", "", comando).strip()

        if any(p in busqueda for p in YOUTUBE_PALABRAS):
            for p in YOUTUBE_PALABRAS:
                busqueda = busqueda.replace(p, "").strip()
            if busqueda:
                return "abrir_youtube", busqueda

        if busqueda:
            return "buscar_google", busqueda

    # =====================================================
    # URL
    # =====================================================

    if (
        "http://"  in comando
        or "https://" in comando
        or "www."     in comando
        or re.search(r"\.\w{2,3}(/|$)", comando)
    ):
        return "abrir_url", comando

    # =====================================================
    # STARTUP
    # =====================================================

    ACTIVAR_STARTUP = [
        "activa el inicio automático",
        "activa inicio automático",
        "activa el inicio",
        "activar inicio automático",
        "activar inicio",
    ]

    DESACTIVAR_STARTUP = [
        "desactiva el inicio automático",
        "desactiva inicio automático",
        "desactiva el inicio",
        "desactivar inicio automático",
        "desactivar inicio",
    ]

    ESTADO_STARTUP = [
        "el inicio automático está activado",
        "está activado el inicio",
        "inicio automático activado",
        "estado del inicio",
        "cómo está el inicio",
    ]

    if any(comando == p or comando.startswith(p) for p in ACTIVAR_STARTUP):
        return "activar_startup", "startup"

    if any(comando == p or comando.startswith(p) for p in DESACTIVAR_STARTUP):
        return "desactivar_startup", "startup"

    if any(comando == p or comando.startswith(p) for p in ESTADO_STARTUP):
        return "estado_startup", "startup"

    # =====================================================
    # RECAPTURAR APP
    # =====================================================

    RECAPTURAR = [
        "recaptura ", "vuelve a registrar ",
        "registra de nuevo ", "re registra ",
        "recapturar "
    ]

    for palabra in RECAPTURAR:
        if comando.startswith(palabra):
            nombre = comando.replace(palabra, "", 1).strip()
            nombre = traducir_alias(nombre)
            if nombre:
                return "recapturar_app", nombre

    # =====================================================
    # ELIMINAR ALIAS
    # =====================================================

    ELIMINAR_ALIAS = [
        "olvida ",
        "elimina el alias ",
        "borra el alias ",
        "elimina alias ",
        "borra alias ",
    ]

    for palabra in ELIMINAR_ALIAS:
        if comando.startswith(palabra):
            nombre = comando.replace(palabra, "", 1).strip()
            if nombre:
                return "eliminar_alias", nombre

    # =====================================================
    # MEDIA / REPRODUCCIÓN
    # =====================================================

    PAUSAR = [
        "pausa", "pausar", "detén", "deten",
        "detener", "para la música", "para la musica",
        "para el video", "stop music", "stop video",
    ]

    REANUDAR = [
        "reanuda", "reanudar", "continúa", "continua",
        "play", "reproduce", "resumir", "sigue la música",
        "sigue la musica", "sigue el video",
    ]

    SIGUIENTE = [
        "siguiente", "siguiente canción", "siguiente cancion",
        "skip", "salta", "salta la canción", "salta la cancion",
        "siguiente video", "siguiente track",
    ]

    ANTERIOR = [
        "anterior", "canción anterior", "cancion anterior",
        "atrás", "atras", "volver", "video anterior",
        "track anterior", "la anterior",
    ]

    SUBIR_VOLUMEN = [
        "sube el volumen", "sube volumen", "más volumen",
        "mas volumen", "volumen arriba", "volumen más alto",
        "volumen mas alto", "aumenta el volumen",
    ]

    BAJAR_VOLUMEN = [
        "baja el volumen", "baja volumen", "menos volumen",
        "volumen abajo", "volumen más bajo", "volumen mas bajo",
        "disminuye el volumen", "reduce el volumen",
    ]

    SILENCIAR = [
        "silencia", "silenciar", "mute", "sin sonido",
        "quita el sonido", "mutea",
    ]

    DESSILENCIAR = [
        "quita el silencio", "desmutea", "activa el sonido",
        "sube el mute", "quita el mute", "unmute",
    ]

    # pausar — detectar nombre de app si viene explícito
    # ej: "pausa spotify" → ("media_pausar", "spotify")
    # ej: "pausa" → ("media_pausar", "media")
    for p in PAUSAR:
        if comando == p:
            return "media_pausar", "media"
        if comando.startswith(p + " "):
            app = comando[len(p):].strip()
            app = traducir_alias(app) if app else "media"
            return "media_pausar", app or "media"

    for p in REANUDAR:
        if comando == p:
            return "media_reanudar", "media"
        if comando.startswith(p + " "):
            app = comando[len(p):].strip()
            app = traducir_alias(app) if app else "media"
            return "media_reanudar", app or "media"

    for p in SIGUIENTE:
        if comando == p:
            return "media_siguiente", "media"
        if comando.startswith(p + " "):
            app = comando[len(p):].strip()
            app = traducir_alias(app) if app else "media"
            return "media_siguiente", app or "media"

    for p in ANTERIOR:
        if comando == p:
            return "media_anterior", "media"
        if comando.startswith(p + " "):
            app = comando[len(p):].strip()
            app = traducir_alias(app) if app else "media"
            return "media_anterior", app or "media"

    if comando in SUBIR_VOLUMEN or any(comando.startswith(p + " ") for p in SUBIR_VOLUMEN):
        return "media_subir_volumen", "media"

    if comando in BAJAR_VOLUMEN or any(comando.startswith(p + " ") for p in BAJAR_VOLUMEN):
        return "media_bajar_volumen", "media"

    if comando in SILENCIAR or any(comando.startswith(p + " ") for p in SILENCIAR):
        return "media_silenciar", "media"

    if comando in DESSILENCIAR or any(comando.startswith(p + " ") for p in DESSILENCIAR):
        return "media_silenciar", "media"  # toggle

    # =====================================================
    # VOLUMEN EXACTO
    # =====================================================

    import re as _re

    VOLUMEN_EXACTO_SISTEMA = [
        "volumen al ", "pon el volumen al ", "pon el volumen a ",
        "volumen a ", "ponlo al ",
    ]

    # "volumen de spotify al 50" → app + porcentaje
    VOLUMEN_EXACTO_APP = [
        "volumen de ", "sube el volumen de ", "baja el volumen de ",
        "pon el volumen de ", "ponle el volumen a ",
    ]

    # primero intentar con nombre de app explícito
    for palabra in VOLUMEN_EXACTO_APP:
        if comando.startswith(palabra):
            resto = comando.replace(palabra, "", 1).strip()
            # buscar "al X" o "a X" al final
            match = _re.search(r"\bal?\s+(\d+)", resto)
            if match:
                porcentaje = match.group(1)
                # nombre es todo lo que está antes del "al X"
                nombre_app = resto[:match.start()].strip()
                nombre_app = traducir_alias(nombre_app)
                return "media_volumen_exacto", f"{nombre_app} {porcentaje}"
            # si solo hay número sin "al"
            numeros = _re.findall(r"\d+", resto)
            if numeros:
                nombre_app = _re.sub(r"\d+", "", resto).strip()
                nombre_app = traducir_alias(nombre_app)
                return "media_volumen_exacto", f"{nombre_app} {numeros[0]}"

    # volumen del sistema sin nombre de app
    for palabra in VOLUMEN_EXACTO_SISTEMA:
        if comando.startswith(palabra):
            resto = comando.replace(palabra, "", 1).strip()
            numeros = _re.findall(r"\d+", resto)
            if numeros:
                return "media_volumen_exacto", numeros[0]

    # si dice "volumen cincuenta" o "volumen setenta"
    NUMEROS_TEXTO = {
        "cero": "0", "diez": "10", "veinte": "20",
        "treinta": "30", "cuarenta": "40", "cincuenta": "50",
        "sesenta": "60", "setenta": "70", "ochenta": "80",
        "noventa": "90", "cien": "100",
    }

    if comando.startswith("volumen "):
        resto = comando.replace("volumen ", "", 1).strip()
        if resto in NUMEROS_TEXTO:
            return "media_volumen_exacto", NUMEROS_TEXTO[resto]

    # =====================================================
    # REGISTRAR ALIAS
    # =====================================================

    REGISTRAR_ALIAS = [
        "registra alias",
        "registrar alias",
        "añade alias",
        "agrega alias",
        "nuevo alias",
        "crear alias",
        "crea alias",
        "asignar alias",
        "asigna alias",
    ]

    if any(comando == p or comando.startswith(p) for p in REGISTRAR_ALIAS):
        return "registrar_alias", "alias"

    # =====================================================
    # MINIMIZAR APP
    # =====================================================

    MINIMIZAR = [
        "minimiza ", "minimizar ",
        "oculta ", "ocultar ",
        "esconde ", "esconder ",
    ]

    for palabra in MINIMIZAR:
        if comando.startswith(palabra):
            nombre = comando.replace(palabra, "", 1).strip()
            if nombre in REFERENCIAS_ULTIMA_APP and ultima:
                nombre = ultima
            nombre = traducir_alias(nombre)
            if nombre:
                return "minimizar_app", nombre

    # =====================================================
    # MAXIMIZAR / TRAER AL FRENTE
    # =====================================================

    MAXIMIZAR = [
        "maximiza ", "maximizar ",
        "trae ", "traer ",
        "muestra ", "mostrar ",
        "pon en frente ",
        "al frente ",
        "enfoca ",
    ]

    for palabra in MAXIMIZAR:
        if comando.startswith(palabra):
            nombre = comando.replace(palabra, "", 1).strip()
            if nombre in REFERENCIAS_ULTIMA_APP and ultima:
                nombre = ultima
            nombre = traducir_alias(nombre)
            if nombre:
                return "maximizar_app", nombre

    # =====================================================
    # ABRIR APP
    # =====================================================

    ABRIR = [
        "abre ", "abrir ", "inicia ",
        "ejecuta ", "lanza ", "pon "
    ]

    for palabra in ABRIR:
        if comando.startswith(palabra):
            nombre = comando.replace(palabra, "", 1).strip()
            if nombre in REFERENCIAS_ULTIMA_APP and ultima:
                nombre = ultima
            nombre = traducir_alias(nombre)
            if nombre:
                return "abrir_app", nombre

    # =====================================================
    # CERRAR APP
    # =====================================================

    CERRAR = [
        "cierra ", "cerrar ", "termina ",
        "apaga ", "mata ", "ciérralo "
    ]

    for palabra in CERRAR:
        if comando.startswith(palabra):
            nombre = comando.replace(palabra, "", 1).strip()
            if nombre in REFERENCIAS_ULTIMA_APP and ultima:
                nombre = ultima
            nombre = traducir_alias(nombre)
            if nombre:
                return "cerrar_app", nombre

    return None, None