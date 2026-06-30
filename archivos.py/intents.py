import re
from aliases import traducir_alias
from memory import memoria, obtener_historial

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

    # FIX: Whisper a veces inserta una coma cuando el usuario hace una
    # pausa breve y natural entre la acción y el nombre de la app (ej.
    # "abre... discord" se transcribe como "abre, discord"). Esa coma
    # rompía TODAS las reglas de coincidencia por prefijo de este
    # archivo (comando.startswith("abre ") falla si después de "abre"
    # viene una coma en vez de un espacio directo), mandando el
    # comando a la IA innecesariamente — más lento y menos confiable
    # para algo tan simple como una app conocida.
    #
    # Se quitan también signos de exclamación/interrogación de
    # apertura y cierre por el mismo motivo (ya vistos en
    # transcripciones reales como "¡habré bravujala!"). No se toca
    # nada más de la puntuación a propósito, para no arriesgar romper
    # texto legítimo dentro de nombres de apps o alias.
    # FIX: la coma se reemplaza por un ESPACIO, no se elimina sin
    # reemplazo — si no, "abre,discord" (sin espacio después de la
    # coma, que también puede pasar) quedaría pegado como
    # "abrediscord" en vez de separarse correctamente en "abre
    # discord". Los signos de exclamación/interrogación sí se pueden
    # eliminar sin reemplazo porque nunca actúan como separador de
    # palabras en el texto transcrito.
    comando = comando.replace(",", " ")
    comando = re.sub(r"[¡!¿?]", "", comando)
    comando = re.sub(r"\s+", " ", comando).strip()

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
    # "LA ANTERIOR" / "OTRA VEZ" — usando el historial corto
    # NUEVO: a diferencia de ÁBRELO/CIÉRRALO (que se refieren a la
    # app MÁS reciente, índice 0 del historial — mismo dato que
    # ultima_app), "la anterior" se refiere a la PREVIA a esa, índice
    # 1. Por ejemplo: abriste Discord, luego Brawlhalla, y decís
    # "abre la anterior" — te referís a Discord, no a Brawlhalla (que
    # ya está abierta y sería redundante volver a pedirla así).
    #
    # "otra vez" / "de nuevo" (sin "ábrelo" antes) también se manejan
    # acá como sinónimos de abrir/cerrar la MÁS reciente del
    # historial — funcionan igual que ÁBRELO/CIÉRRALO arriba, pero
    # cubren frases que el usuario diría de forma más natural en
    # una conversación ya en curso ("vuelve a abrirlo" ya estaba
    # cubierto por normalizar(), pero "ábrelo otra vez" o "otra vez
    # brawlhalla" no necesariamente).
    # =====================================================

    ABRIR_LA_ANTERIOR = {
        "abre la anterior", "abre el anterior",
        "la anterior", "el anterior",
        "abre la app anterior",
    }

    CERRAR_LA_ANTERIOR = {
        "cierra la anterior", "cierra el anterior",
        "cierra la app anterior",
    }

    if comando in ABRIR_LA_ANTERIOR:
        historial_abrir = obtener_historial("abrir_app")
        if len(historial_abrir) >= 2:
            return "abrir_app", historial_abrir[1]
        # FIX: sin esto, si no hay suficiente historial, el flujo
        # seguía de largo y una regla genérica más abajo ("abre " +
        # resto del texto) trataba "la anterior" como si fuera el
        # nombre literal de una app, terminando en un confuso "no
        # encontré la anterior". Como ya sabemos que esta frase es
        # una referencia al historial, no un nombre de app, se corta
        # acá explícitamente — la IA puede manejar mejor explicarle
        # al usuario que no hay una app anterior registrada todavía.
        return None, None

    if comando in CERRAR_LA_ANTERIOR:
        historial_cerrar = obtener_historial("cerrar_app")
        if len(historial_cerrar) >= 2:
            return "cerrar_app", historial_cerrar[1]
        return None, None

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
    # RECORDATORIOS
    # Tres formas de decirlo (orden del tiempo flexible):
    #   "recuérdame en 10 minutos que llame a mamá"
    #   "recuérdame a las 3 pm que llame a mamá"
    #   "recuérdame que llame a mamá a las 3 pm"      (orden inverso)
    # Se empaqueta como "cuando|que" porque detectar_intent solo
    # puede devolver un valor — acciones.py lo separa de nuevo.
    #
    # FIX: la versión anterior solo reconocía "recuérdame [tiempo]
    # que [texto]" — si el usuario decía la hora DESPUÉS del texto
    # ("recuérdame que llame a mamá a las 3 pm", un orden igual de
    # natural en español), no matcheaba ningún prefijo y cAía a la
    # IA innecesariamente, que no siempre lo armaba bien tampoco.
    # Ahora se usa un patrón con regex que reconoce el "que" como
    # separador en cualquier posición relativa al tiempo.
    # =====================================================

    VERBOS_RECORDATORIO = (
        r"recu[ée]rdame|ponme\s+un\s+recordatorio|"
        r"crea(?:r)?\s+un?\s+recordatorio|crea(?:r)?\s+recordatorio"
    )

    PATRON_TIEMPO = r"(?:en|a\s+las)\s+([^,]+?)"

    # caso 1: tiempo ANTES del "que" — "recuérdame a las 3 pm que..."
    m = re.match(
        rf"^(?:{VERBOS_RECORDATORIO})\s+{PATRON_TIEMPO}\s+que\s+(.+)$",
        comando
    )

    # caso 2: tiempo DESPUÉS del "que" — "recuérdame que... a las 3 pm"
    if not m:
        m = re.match(
            rf"^(?:{VERBOS_RECORDATORIO})\s+que\s+(.+?)\s+{PATRON_TIEMPO}$",
            comando
        )
        if m:
            # en este patrón los grupos vienen invertidos (texto,
            # tiempo) — se reordenan para que siempre sea (tiempo, texto)
            que, cuando = m.group(1), m.group(2)
            m = None
        else:
            que = cuando = None
    else:
        cuando, que = m.group(1), m.group(2)

    if cuando and que:
        cuando = cuando.strip()
        que    = que.strip()
        if cuando and que:
            return "crear_recordatorio", f"{cuando}|{que}"

    # caso 3: sin tiempo explícito — "recuérdame que llame a mamá"
    # (sin info de cuándo en este patrón; se deja caer a la IA, que
    # puede preguntar o inferir mejor frases libres ambiguas)

    # =====================================================
    # LISTAR RECORDATORIOS
    # Frases fijas, sin parámetro — no necesitan prefijo +
    # resto como las demás reglas.
    # =====================================================

    LISTAR_RECORDATORIOS = {
        "qué recordatorios tengo",
        "que recordatorios tengo",
        "cuáles son mis recordatorios",
        "cuales son mis recordatorios",
        "mis recordatorios",
        "lista de recordatorios",
        "tengo algún recordatorio",
        "tengo algun recordatorio",
    }

    if comando in LISTAR_RECORDATORIOS:
        return "listar_recordatorios", "recordatorios"

    # =====================================================
    # CANCELAR RECORDATORIO
    # "cancela el recordatorio de la pizza" → palabra_clave="la pizza"
    # El "de"/"sobre" inicial se quita porque es parte de la
    # gramática de la frase, no de las palabras clave a buscar.
    # =====================================================

    CANCELAR_RECORDATORIO_PREFIJOS = [
        "cancela el recordatorio de ",
        "cancela el recordatorio sobre ",
        "cancela mi recordatorio de ",
        "elimina el recordatorio de ",
        "borra el recordatorio de ",
        "quita el recordatorio de ",
    ]

    for prefijo in CANCELAR_RECORDATORIO_PREFIJOS:
        if comando.startswith(prefijo):
            palabra_clave = comando[len(prefijo):].strip()
            if palabra_clave:
                return "cancelar_recordatorio", palabra_clave

    # =====================================================
    # TEMPORIZADORES
    # Tres formas de decirlo, con o sin nombre:
    #   "pon un temporizador de 10 minutos"
    #   "pon un temporizador de pasta a 10 minutos"
    #   "pon un temporizador de 10 minutos para la pasta"
    # Se empaqueta como "duración|nombre" (mismo separador que
    # crear_recordatorio usa "cuando|que") — acciones.py lo separa.
    # Si no hay nombre, la parte derecha queda vacía.
    # =====================================================

    TEMPORIZADOR_PREFIJOS = [
        "pon un temporizador de ", "pon un temporizador a ",
        "ponme un temporizador de ", "ponme un temporizador a ",
        "crea un temporizador de ", "crea un temporizador a ",
        "inicia un temporizador de ", "inicia un temporizador a ",
        "temporizador de ", "temporizador a ",
    ]

    for prefijo in TEMPORIZADOR_PREFIJOS:
        if comando.startswith(prefijo):
            resto = comando[len(prefijo):].strip()

            if not resto:
                continue

            duracion = resto
            nombre   = ""

            # "10 minutos para la pasta" / "10 minutos para pasta"
            if " para " in resto:
                duracion, nombre = resto.split(" para ", 1)
                duracion = duracion.strip()
                nombre   = nombre.strip()

            # "pasta a 10 minutos" — el nombre viene ANTES, separado
            # por " a ", y lo que sigue a " a " es la duración. Solo
            # aplica si "duracion" (== resto completo en este punto)
            # no tiene ya un número, porque si lo tiene es porque ya
            # se resolvió arriba con " para ".
            elif " a " in resto and not re.search(r"\d", resto.split(" a ", 1)[0]):
                nombre, duracion = resto.split(" a ", 1)
                nombre   = nombre.strip()
                duracion = duracion.strip()

            if duracion:
                return "crear_temporizador", f"{duracion}|{nombre}"

    # =====================================================
    # LISTAR TEMPORIZADORES
    # =====================================================

    LISTAR_TEMPORIZADORES = {
        "qué temporizadores tengo",
        "que temporizadores tengo",
        "cuáles son mis temporizadores",
        "cuales son mis temporizadores",
        "mis temporizadores",
        "lista de temporizadores",
        "tengo algún temporizador",
        "tengo algun temporizador",
        "cuánto falta del temporizador",
        "cuanto falta del temporizador",
    }

    if comando in LISTAR_TEMPORIZADORES:
        return "listar_temporizadores", "temporizadores"

    # =====================================================
    # CANCELAR TEMPORIZADOR
    # =====================================================

    CANCELAR_TEMPORIZADOR_EXACTO = {
        "cancela el temporizador",
        "cancela mi temporizador",
        "elimina el temporizador",
        "borra el temporizador",
        "para el temporizador",
        "detén el temporizador",
        "deten el temporizador",
    }

    if comando in CANCELAR_TEMPORIZADOR_EXACTO:
        return "cancelar_temporizador", ""

    CANCELAR_TEMPORIZADOR_PREFIJOS = [
        "cancela el temporizador de ",
        "cancela mi temporizador de ",
        "elimina el temporizador de ",
        "borra el temporizador de ",
        "quita el temporizador de ",
    ]

    for prefijo in CANCELAR_TEMPORIZADOR_PREFIJOS:
        if comando.startswith(prefijo):
            palabra_clave = comando[len(prefijo):].strip()
            if palabra_clave:
                return "cancelar_temporizador", palabra_clave

    # =====================================================
    # ELIMINAR ALIAS
    # FIX: antes esto exigía que el usuario dijera el alias EXACTO
    # en el mismo comando ("olvida el alias braulhalla"), comparado
    # con coincidencia exacta de texto contra lo guardado — si
    # Whisper transcribía el alias distinto a como se guardó, la
    # búsqueda fallaba aunque el alias sí existiera.
    #
    # Ahora "olvida un alias" / "elimina un alias" dispara un flujo
    # GUIADO (ver eliminar_alias_guiado en registrar_alias.py): pide
    # la app, busca con tolerancia, y muestra los alias existentes
    # para elegir — mucho más resistente a errores de transcripción
    # porque ya no depende de decir un texto exacto de una sola vez.
    #
    # Si el usuario YA dice un nombre después del comando ("olvida
    # el alias de brawlhalla"), ese nombre se usa como punto de
    # partida para identificar la app directamente, sin tener que
    # preguntarlo de nuevo.
    # =====================================================

    ELIMINAR_ALIAS = [
        "olvida el alias de ",
        "elimina el alias de ",
        "borra el alias de ",
        "quita el alias de ",
        "olvida un alias de ",
        "elimina un alias de ",
        "olvida el alias ",
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

    ELIMINAR_ALIAS_SIN_NOMBRE = {
        "olvida un alias", "elimina un alias", "borra un alias",
        "quita un alias", "elimina alias", "borra alias",
        "eliminar un alias", "borrar un alias", "olvidar un alias",
        "eliminar alias", "borrar alias", "olvidar alias",
        "quitar un alias", "quitar alias", "olvida alias",
        "elimina aliases", "elimina los alias",
    }

    if comando in ELIMINAR_ALIAS_SIN_NOMBRE:
        return "eliminar_alias", ""

    # =====================================================
    # MEDIA / REPRODUCCIÓN
    # =====================================================

    # FIX: definida ACÁ, antes de cualquier uso — la necesitan tanto
    # PAUSAR/REANUDAR como SIGUIENTE/ANTERIOR más abajo, para filtrar
    # palabras descriptivas genéricas ("canción", "video", "música")
    # que NO deben tratarse como nombre de una app real cuando
    # aparecen después de un verbo de acción corto (ver el FIX
    # detallado más abajo, junto a SIGUIENTE_FIJAS).
    PALABRAS_GENERICAS_MEDIA = {
        "canción", "cancion", "video", "track", "pista",
        "música", "musica", "la canción", "la cancion",
        "el video", "la pista", "la música", "la musica",
    }

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

    # FIX: antes SIGUIENTE/ANTERIOR mezclaban en una sola lista tanto
    # frases FIJAS sin app ("siguiente canción", "siguiente video")
    # como el prefijo corto que sí puede llevar un nombre de app real
    # ("siguiente spotify"). Como el loop usaba comando.startswith(p)
    # para CADA entrada de la lista en el orden en que estaba escrita,
    # y "siguiente" (sin más) aparecía ANTES que "siguiente canción"
    # en la lista, cualquier comando que empezara con "siguiente "
    # nunca llegaba a compararse contra las frases más específicas —
    # se interpretaba "canción"/"video"/"track" como si fueran el
    # NOMBRE DE LA APP a la que aplicar la acción, resultando en
    # "No pude pasar de canción en canción".
    #
    # Ahora las frases fijas (sin app) se comparan PRIMERO con
    # igualdad exacta, y solo si ninguna coincide se prueba el
    # prefijo corto + lo que siga como posible nombre de app — y
    # ESE resultado se filtra contra PALABRAS_GENERICAS_MEDIA, para
    # que aunque alguien diga una variante no listada explícitamente
    # ("siguiente cancion", con o sin tilde, "siguiente pista"), no
    # termine tratándose como nombre de app de todas formas.

    SIGUIENTE_FIJAS = {
        "siguiente", "siguiente canción", "siguiente cancion",
        "skip", "salta", "salta la canción", "salta la cancion",
        "siguiente video", "siguiente track", "siguiente pista",
    }

    ANTERIOR_FIJAS = {
        "anterior", "canción anterior", "cancion anterior",
        "atrás", "atras", "volver", "video anterior",
        "track anterior", "la anterior", "pista anterior",
    }

    if comando in SIGUIENTE_FIJAS:
        return "media_siguiente", "media"

    if comando in ANTERIOR_FIJAS:
        return "media_anterior", "media"

    PREFIJOS_SIGUIENTE_CORTOS = ["siguiente", "skip", "salta"]
    PREFIJOS_ANTERIOR_CORTOS  = ["anterior", "atrás", "atras"]

    for p in PREFIJOS_SIGUIENTE_CORTOS:
        if comando.startswith(p + " "):
            app = comando[len(p):].strip()
            if app in PALABRAS_GENERICAS_MEDIA:
                return "media_siguiente", "media"
            app = traducir_alias(app) if app else "media"
            return "media_siguiente", app or "media"

    for p in PREFIJOS_ANTERIOR_CORTOS:
        if comando.startswith(p + " "):
            app = comando[len(p):].strip()
            if app in PALABRAS_GENERICAS_MEDIA:
                return "media_anterior", "media"
            app = traducir_alias(app) if app else "media"
            return "media_anterior", app or "media"

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
    # FIX: mismo problema que tenían SIGUIENTE/ANTERIOR (ver el
    # comentario más arriba) — "detén la música" capturaba "la
    # música" como si fuera el nombre de una app. Se filtra contra
    # PALABRAS_GENERICAS_MEDIA antes de tratar el resto como app.
    for p in PAUSAR:
        if comando == p:
            return "media_pausar", "media"
        if comando.startswith(p + " "):
            app = comando[len(p):].strip()
            if app in PALABRAS_GENERICAS_MEDIA:
                return "media_pausar", "media"
            app = traducir_alias(app) if app else "media"
            return "media_pausar", app or "media"

    for p in REANUDAR:
        if comando == p:
            return "media_reanudar", "media"
        if comando.startswith(p + " "):
            app = comando[len(p):].strip()
            if app in PALABRAS_GENERICAS_MEDIA:
                return "media_reanudar", "media"
            app = traducir_alias(app) if app else "media"
            return "media_reanudar", app or "media"

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