import re
from difflib import SequenceMatcher
from aliases import traducir_alias, existe_alias
from memory import memoria, obtener_historial
from voz_utils import frase_coincide_difuso

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
    # FIX/NUEVO: caso real reportado — Whisper transcribió "no
    # molestar" como "no molestad" (confusión r/d, común al final de
    # una frase dicha rápido). Como FRASES_NO_MOLESTAR más abajo
    # busca por substring EXACTO ("no molestar" dentro del comando),
    # "no molestad" no coincidía con nada y el comando caía
    # innecesariamente a la IA — que además devolvió un valor
    # inesperado ("Spotify") para un intent que ni siquiera lo usa.
    # Con esta corrección, "cancela el modo no molestad" se normaliza
    # a "...no molestar" ANTES de llegar a esa detección, y se
    # resuelve con la regla rápida, sin pasar por la IA para nada.
    "molestad":    "molestar",
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

def _extraer_minutos_no_molestar(texto):
    """
    Extrae la duración en minutos de frases como "por una hora",
    "30 minutos", "2 horas", etc. Si no hay duración explícita,
    devuelve 60 como valor por defecto razonable.
    """
    from tiempo_utils import parsear_duracion

    segundos = parsear_duracion(texto)
    if segundos:
        return max(1, segundos // 60)

    # valores en texto sin número explícito
    DURACIONES_TEXTO = {
        "un momento":     15,
        "un rato":        30,
        "media hora":     30,
        "una hora":       60,
        "dos horas":      120,
        "tres horas":     180,
        "toda la tarde":  180,
        "toda la noche":  480,
    }

    texto = texto.lower().strip()
    for frase, mins in DURACIONES_TEXTO.items():
        if frase in texto:
            return mins

    return 60  # default: una hora


def _es_app_conocida(nombre):
    """
    True si `nombre` es una app/juego/alias que el asistente ya
    conoce (está en la caché, en el índice de juegos, en el de apps,
    o es un alias registrado) — usado como segunda señal de confianza
    por el fallback difuso de verbos de media (ver más abajo): un
    verbo mal transcrito es más creíble como error de transcripción
    cuando lo que sigue SÍ es una app real y reconocida, en vez de
    cualquier palabra suelta.

    Import diferido de app_finder (evita el costo de cargarlo para
    cada llamada a detectar_intent si nunca hace falta esta rama) y
    tolerante a fallos (si algo no está inicializado todavía, se
    asume que no es una app conocida en vez de romper la detección
    de intents por completo).
    """
    if not nombre:
        return False

    if existe_alias(nombre):
        return True

    try:
        import app_finder
        clave = app_finder.limpiar_nombre(nombre)
        return (
            clave in app_finder.cache
            or clave in app_finder.games_index
            or clave in app_finder.apps_index
        )
    except Exception:
        return False


def detectar_intent(comando):

    comando = normalizar(comando)
    comando = quitar_muletillas(comando)
    ultima  = memoria.get("ultima_app", "")

    # =====================================================
    # CADENAS EN EL MOMENTO — detección TEMPRANA
    # Se hace AQUÍ, antes que cualquier otro intent, porque
    # los patrones de abrir/cerrar/media capturan el conector
    # como parte del nombre de app si llegan primero — ej:
    # "abre discord y spotify" se convertía en abrir_app con
    # valor "discord y spotify" en vez de detectarse como cadena.
    #
    # FIX: también soporta más de 2 partes (antes split(conector,1)
    # limitaba a 2) — normalizando todos los conectores a un
    # separador interno y dividiendo sin límite.
    # =====================================================

    _CONECTORES_CADENA = [
        " y luego ", " y después ", " y despues ",
        " luego ", " después ", " despues ", " y ",
    ]
    _SEP = "|||"

    comando_norm_cadena = comando
    tiene_conector      = False

    for conector in _CONECTORES_CADENA:
        if conector in comando_norm_cadena:
            comando_norm_cadena = comando_norm_cadena.replace(conector, _SEP)
            tiene_conector      = True

    if tiene_conector:
        partes = [p.strip() for p in comando_norm_cadena.split(_SEP) if p.strip()]

        if len(partes) >= 2:
            pasos_cadena    = []
            valido          = True
            ultimo_intent   = None
            ultimo_verbo    = None  # prefijo para heredar, ej. "abre "

            # prefijos de verbo que se pueden heredar a la siguiente parte
            # cuando una parte es solo un nombre sin verbo (ej. "spotify"
            # después de "abre discord y spotify")
            VERBOS_HEREDABLES = {
                "abrir_app":    "abre ",
                "cerrar_app":   "cierra ",
                "minimizar_app": "minimiza ",
                "maximizar_app": "maximiza ",
            }

            for parte in partes:
                intent_parte, valor_parte = detectar_intent(parte)

                # si la parte no tiene intent pero hay un verbo heredable
                # del paso anterior, intentar con el verbo prepuesto
                if (not intent_parte or intent_parte in ("cadena", "ejecutar_macro")) \
                        and ultimo_verbo:
                    intent_parte, valor_parte = detectar_intent(ultimo_verbo + parte)

                if not intent_parte or intent_parte in ("cadena", "ejecutar_macro"):
                    valido = False
                    break

                pasos_cadena.append({"intent": intent_parte, "valor": valor_parte or ""})
                ultimo_intent = intent_parte
                ultimo_verbo  = VERBOS_HEREDABLES.get(intent_parte)

            if valido and len(pasos_cadena) >= 2:
                import json
                return "cadena", json.dumps(pasos_cadena, ensure_ascii=False)
        # si la cadena no es válida (alguna parte no reconocida),
        # caer al resto del pipeline normalmente con el comando original

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
        "ábrela", "abrela",
        # FIX/NUEVO: "otra vez"/"de nuevo" sueltos (sin "ábrelo" antes)
        # ya estaban MENCIONADOS en el comentario de abajo como algo
        # que debía funcionar, pero nunca se habían agregado de
        # verdad a ninguna lista — decir solamente "otra vez" caía
        # sin reconocerse. Al vivir en ABRIR_ESTO, usan exactamente
        # el mismo dato (`ultima`) que "ábrelo".
        "otra vez", "de nuevo",
    ]

    # NOTA: MINIMIZAR_ESTO/MAXIMIZAR_ESTO (más abajo) se comparan con
    # IGUALDAD EXACTA a propósito, NO con frase_coincide_difuso() —
    # "minimízalo" y "maximízalo" dan un ratio de exactamente 0.80
    # entre sí (casi anagramas: solo cambian "in"/"ax"), justo en el
    # umbral. Con tolerancia difusa acá, un error de transcripción en
    # cualquiera de los dos podía ejecutar la acción CONTRARIA a la
    # pedida — minimizar en vez de maximizar, o viceversa — un caso
    # bastante peor que simplemente no reconocer el comando (que ya
    # pasa a la IA como respaldo). ABRIR_ESTO/CERRAR_ESTO SÍ quedan
    # con tolerancia difusa: se verificó que el ratio entre ambos
    # sets nunca supera 0.56, sin riesgo real de cruzarse.

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
        if frase_coincide_difuso(comando, CERRAR_ESTO):
            return "cerrar_app", ultima
        if frase_coincide_difuso(comando, ABRIR_ESTO):
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

    # NOTA: estos dos sets se comparan con IGUALDAD EXACTA a
    # propósito, NO con frase_coincide_difuso() como la mayoría de
    # los demás sets de frases fijas de este archivo — "el anterior"/
    # "la anterior" es demasiado parecido (ratio ~0.89) a la palabra
    # suelta "anterior" que SIGUIENTE_FIJAS/ANTERIOR_FIJAS usan más
    # abajo para "canción anterior"/"video anterior". Con tolerancia
    # difusa acá, decir solo "anterior" (para saltar a la canción
    # anterior) se interpretaba por error como "la app anterior del
    # historial" — un caso real encontrado al probar este mismo
    # archivo, ver el mismo problema documentado junto a
    # LISTAR_TEMPORIZADORES más abajo.

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

    # FIX: "busca actualizaciones" y variantes deben ir al actualizador,
    # no a Google — se detectan ANTES del bloque genérico de búsqueda
    # para que no caigan en buscar_google.
    BUSCAR_ACTUALIZACION_FRASES = {
        "busca actualizaciones", "buscar actualizaciones",
        "busca una actualización", "buscar actualización",
        "busca si hay actualizaciones",
    }
    if frase_coincide_difuso(comando, BUSCAR_ACTUALIZACION_FRASES):
        return "buscar_actualizacion", ""

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
    # RECORDATORIOS RECURRENTES
    # Patrones:
    #   "recuérdame cada día a las 8 que tome la pastilla"
    #   "recuérdame todos los lunes a las 9 la reunión"
    #   "recuérdame cada 2 horas revisar el correo"
    #   "recuérdame cada 30 minutos tomar agua"
    # Valor: "tipo|hora_o_segundos|dia|que"
    # =====================================================

    VERBOS_REC = (
        r"recu[ée]rdame|ponme\s+un\s+recordatorio\s+recurrente|"
        r"crea(?:r)?\s+un?\s+recordatorio\s+recurrente"
    )

    # diario: "recuérdame cada día a las 8 que X"
    m = re.match(
        rf"^(?:{VERBOS_REC})\s+cada\s+d[ií]a\s+a\s+las\s+(.+?)\s+que\s+(.+)$",
        comando
    )
    if m:
        return "crear_recordatorio_recurrente", f"diario|{m.group(1).strip()}||{m.group(2).strip()}"

    # diario sin "que": "recuérdame cada día a las 8 tomar pastilla"
    m = re.match(
        rf"^(?:{VERBOS_REC})\s+cada\s+d[ií]a\s+a\s+las\s+(\S+)\s+(.+)$",
        comando
    )
    if m:
        return "crear_recordatorio_recurrente", f"diario|{m.group(1).strip()}||{m.group(2).strip()}"

    # semanal: "recuérdame todos los lunes a las 9 que X"
    DIAS_PATRON = "lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo"
    m = re.match(
        rf"^(?:{VERBOS_REC})\s+todos\s+los\s+({DIAS_PATRON})\s+a\s+las\s+(.+?)\s+(?:que\s+)?(.+)$",
        comando
    )
    if m:
        return "crear_recordatorio_recurrente", f"semanal|{m.group(2).strip()}|{m.group(1).strip()}|{m.group(3).strip()}"

    # intervalo: "recuérdame cada 2 horas X" / "cada 30 minutos X"
    m = re.match(
        rf"^(?:{VERBOS_REC})\s+cada\s+(\d+)\s+(hora|horas|minuto|minutos|min)\s+(?:que\s+)?(.+)$",
        comando
    )
    if m:
        cantidad = int(m.group(1))
        unidad   = m.group(2)
        segundos = cantidad * (3600 if "hora" in unidad else 60)
        return "crear_recordatorio_recurrente", f"intervalo|{segundos}||{m.group(3).strip()}"

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

    if frase_coincide_difuso(comando, LISTAR_RECORDATORIOS):
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
    # NOTA: este set se compara con IGUALDAD EXACTA a propósito, NO
    # con frase_coincide_difuso() — "cuánto falta del temporizador"
    # da un ratio de 0.809 (por encima del umbral 0.80) contra
    # "cancela el temporizador", así que con tolerancia difusa acá
    # "cancela el temporizador" se interpretaba por error como
    # LISTAR en vez de CANCELAR (este set se revisa antes que
    # CANCELAR_TEMPORIZADOR_EXACTO más abajo) — un caso real
    # encontrado al probar este archivo. Comparten demasiado
    # vocabulario ("temporizador") entre sí como para tolerar
    # variaciones sin arriesgar cruzarse con el intent equivocado.
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

    if frase_coincide_difuso(comando, CANCELAR_TEMPORIZADOR_EXACTO):
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

    if frase_coincide_difuso(comando, ELIMINAR_ALIAS_SIN_NOMBRE):
        return "eliminar_alias", ""

    # =====================================================
    # MODO NO MOLESTAR
    # FIX: antes exigía que la frase EMPEZARA exactamente con uno de
    # unos pocos patrones fijos ("activa no molestar", "modo no
    # molestar", etc, vía comando.startswith(p)) — decir "activa EL
    # MODO no molestar" (con "el modo" de más en el medio) no
    # coincidía con NINGUNO de esos prefijos exactos, así que el
    # comando nunca se reconocía como esta acción.
    #
    # Ahora se busca por CONTENIDO (la frase clave en cualquier parte
    # del comando, no solo al principio) — mucho más tolerante a
    # variaciones naturales de cómo alguien pide lo mismo ("activa el
    # modo no molestar", "por favor activa el modo no molestar",
    # "quiero que actives el no molestar" ya funcionan; antes solo
    # "activa no molestar" a secas, textual, funcionaba).
    #
    # IMPORTANTE: por eso DESACTIVAR y ESTADO se revisan ANTES que
    # ACTIVAR acá abajo, no después como estaba antes — "desactiva no
    # molestar" CONTIENE literalmente el substring "activa no
    # molestar" (des+"activa no molestar"), así que con matching por
    # contenido, si ACTIVAR se revisara primero, "desactiva no
    # molestar" activaría el modo en vez de desactivarlo. Revisando
    # primero las palabras de desactivación/consulta, y solo cayendo
    # a "activar" como opción por descarte, se evita ese choque.
    # =====================================================

    FRASES_NO_MOLESTAR = (
        "no molestar", "modo concentracion", "modo concentración",
        "modo silencio", "silencia los avisos", "silencia las notificaciones",
        "silencia los recordatorios", "silencia los temporizadores",
        "no me interrumpas", "no me avises", "no me molestes",
    )

    # FIX: estas 3 frases de desactivar NO contienen literalmente "no
    # molestar" (ni ninguna de las otras frases de FRASES_NO_MOLESTAR),
    # así que el chequeo por contenido de más abajo nunca las
    # atraparía — se revisan aparte, explícitamente, ANTES.
    FRASES_DESACTIVAR_NM_EXPLICITAS = {
        "ya puedes molestarme", "ya puedes avisarme", "reactiva los avisos",
    }

    if frase_coincide_difuso(comando, FRASES_DESACTIVAR_NM_EXPLICITAS):
        return "desactivar_no_molestar", ""

    if any(frase in comando for frase in FRASES_NO_MOLESTAR):

        # FIX/NUEVO: "cancela" (stem con la 'a' final incluida) solo
        # matcheaba la conjugación singular ("cancela el no
        # molestar") — "cancelen" (plural, ej. "cancelen el modo no
        # molestar") o "cancelar" (infinitivo) NO contienen "cancela"
        # como substring exacto, así que ninguna de esas dos formas
        # activaba esta rama. El comando entonces "caía por descarte"
        # a activar_no_molestar más abajo — el resultado opuesto a lo
        # que el usuario pidió, en vez de simplemente fallar o pasar
        # a la IA. Se usa el stem sin la vocal final ("cancel"), que
        # es substring de cancela/cancelas/cancelo/cancelen/cancelar/
        # cancelamos por igual.
        PALABRAS_DESACTIVAR_NM = (
            "desactiv", "cancel", "sal del", "ya puedes",
            "reactiva", "quita el", "apaga el", "detén el", "detente",
        )
        PALABRAS_ESTADO_NM = (
            "estado", "tienes el", "esta activo", "está activo",
            "estas en", "estás en", "cuanto queda", "cuánto queda",
            "cuanto falta", "cuánto falta", "cuánto tiempo", "cuanto tiempo",
        )

        if any(p in comando for p in PALABRAS_DESACTIVAR_NM):
            return "desactivar_no_molestar", ""

        if any(p in comando for p in PALABRAS_ESTADO_NM):
            return "estado_no_molestar", ""

        # ni desactivar ni consultar estado -> se asume que se quiere
        # activar. _extraer_minutos_no_molestar ya busca el patrón de
        # duración con una búsqueda (no un prefijo anclado), así que
        # funciona igual sobre el comando completo sin necesitar
        # recortar la frase disparadora primero.
        minutos = _extraer_minutos_no_molestar(comando)
        return "activar_no_molestar", str(minutos)

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

    if frase_coincide_difuso(comando, SIGUIENTE_FIJAS):
        return "media_siguiente", "media"

    if frase_coincide_difuso(comando, ANTERIOR_FIJAS):
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
    # FALLBACK DIFUSO PARA VERBOS DE MEDIA
    # NUEVO: todo el matching de arriba (PAUSAR, REANUDAR, SIGUIENTE,
    # ANTERIOR, SILENCIAR) exige coincidencia EXACTA de texto — si
    # Whisper transcribe mal el verbo, nada de eso lo reconoce y el
    # comando cae en la IA, que puede adivinar mal. Caso real
    # reportado: "reanuda spotify" se transcribió como "rganoda
    # spotify" — no matcheaba nada de arriba, la IA lo interpretó
    # como "abre spotify", y terminó REABRIENDO la app en vez de
    # reanudarla (con Spotify ya abierto, esto es más disruptivo que
    # un simple "no entendí": ejecuta la acción EQUIVOCADA).
    #
    # Mismo mecanismo de tolerancia que la wake word (SequenceMatcher,
    # ver wakeword.py) pero aplicado a la PRIMERA PALABRA del comando
    # contra los verbos de media de una sola palabra — si Whisper
    # garabateó el verbo pero el resto del comando (ej. "spotify") se
    # transcribió bien y es una app conocida, se recupera sin
    # necesitar la IA.
    #
    # El umbral es MÁS BAJO que el estándar del proyecto (0.70 en vez
    # de 0.80, ver UMBRAL_SIMILITUD_DIFUSA en voz_utils.py) PERO SOLO
    # cuando el resto del comando es una app/alias reconocido — con
    # una app real de por medio como segunda señal de confianza, el
    # umbral puede relajarse sin disparar con cualquier palabra
    # suelta. Sin una app reconocida de por medio, se exige el umbral
    # estándar completo, más estricto.
    #
    # Calibrado contra medición real, no a ojo: "rganoda" vs
    # "reanuda" da 0.714 — por debajo del 0.80 estándar, así que hacía
    # falta bajarlo. Se probó un barrido de ~40 palabras reales del
    # proyecto (verbos de otras acciones: "abre", "activa", "busca",
    # "recapturar", "ayuda", etc.) contra los verbos de media — el
    # más cercano de todos ellos ("recapturar"/"ayuda" vs "reanudar")
    # da 0.667, así que 0.70 deja un margen limpio: atrapa el caso
    # real reportado sin acercarse a ningún otro comando real.
    # =====================================================

    VERBOS_MEDIA_DIFUSOS = {
        "pausa":     "media_pausar",
        "pausar":    "media_pausar",
        "reanuda":   "media_reanudar",
        "reanudar":  "media_reanudar",
        "siguiente": "media_siguiente",
        "anterior":  "media_anterior",
        "silencia":  "media_silenciar",
        "silenciar": "media_silenciar",
    }

    UMBRAL_DIFUSO_CON_APP = 0.70
    UMBRAL_DIFUSO_SIN_APP = 0.80

    palabras_comando = comando.split(" ", 1)
    primera_palabra  = palabras_comando[0] if palabras_comando else ""
    resto_comando    = palabras_comando[1].strip() if len(palabras_comando) > 1 else ""

    if primera_palabra:
        mejor_intent = None
        mejor_ratio  = 0.0

        for verbo, intent_candidato in VERBOS_MEDIA_DIFUSOS.items():
            ratio = SequenceMatcher(None, primera_palabra, verbo).ratio()
            if ratio > mejor_ratio:
                mejor_ratio  = ratio
                mejor_intent = intent_candidato

        app_reconocida = _es_app_conocida(resto_comando)
        umbral_efectivo = UMBRAL_DIFUSO_CON_APP if app_reconocida else UMBRAL_DIFUSO_SIN_APP

        if mejor_intent and mejor_ratio >= umbral_efectivo:
            if mejor_intent in ("media_siguiente", "media_anterior", "media_silenciar"):
                return mejor_intent, "media"
            app = traducir_alias(resto_comando) if resto_comando else "media"
            return mejor_intent, app or "media"

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
    # AYUDA
    # NUEVO: "¿qué puedes hacer?" y variantes — resumen de
    # capacidades del asistente (ver ayuda_accion en
    # acciones_sistema.py). Se revisa temprano, junto a los demás
    # intents de frase fija, antes de que cualquier regla más
    # genérica pueda malinterpretar alguna de estas frases.
    # =====================================================

    AYUDA = {
        "ayuda", "necesito ayuda",
        "qué puedes hacer", "que puedes hacer",
        "qué sabes hacer", "que sabes hacer",
        "qué comandos tienes", "que comandos tienes",
        "qué cosas puedes hacer", "que cosas puedes hacer",
        "cómo te uso", "como te uso",
        "cómo funcionas", "como funcionas",
        "qué puedo pedirte", "que puedo pedirte",
    }

    if frase_coincide_difuso(comando, AYUDA):
        return "ayuda", ""

    # =====================================================
    # CONVERSIÓN DE UNIDADES
    # NUEVO: se revisa temprano, junto a AYUDA — es una pregunta,
    # no una acción sobre una app, así que no tiene sentido que
    # compita con las reglas de ABRIR/CERRAR/MEDIA de más abajo. Se
    # resuelve con matemática pura en conversiones.py (sin pasar por
    # la IA — ver el comentario detallado ahí), y devuelve la
    # respuesta YA CALCULADA como valor, lista para hablar.
    # =====================================================

    from conversiones import detectar_conversion
    resultado_conversion = detectar_conversion(comando)
    if resultado_conversion:
        # NUEVO: se pasa el COMANDO tal cual (no el resultado ya
        # calculado) — ver el FIX en acciones_sistema.conversion_accion
        # para el motivo: ahora ese mismo cálculo también lo puede
        # disparar interpretar_con_ia() (ia.py) cuando la frase no
        # matchea acá pero la IA sí reconoce que es una conversión, y
        # las dos rutas deben calcular exactamente igual (con
        # matemática pura, nunca confiando en que la IA haga la
        # cuenta).
        return "conversion_unidades", comando

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
    # GESTIONAR MACROS
    # =====================================================

    CREAR_MACRO = [
        "crea una macro", "crear una macro", "crear macro",
        "crea macro", "nueva macro", "agrega una macro",
        "agrega macro", "añade macro", "nueva secuencia",
    ]

    for p in CREAR_MACRO:
        if comando == p or comando.startswith(p + " "):
            nombre = comando[len(p):].strip()
            return "crear_macro", nombre

    LISTAR_MACROS = [
        "mis macros", "listar macros", "lista de macros",
        "qué macros tengo", "que macros tengo",
        "ver macros", "muestra mis macros",
    ]

    if frase_coincide_difuso(comando, LISTAR_MACROS):
        return "listar_macros", "macros"

    ELIMINAR_MACRO = [
        "elimina la macro ", "elimina macro ", "borra la macro ",
        "borra macro ", "eliminar macro ", "borrar macro ",
        "olvida la macro ", "olvida macro ",
    ]

    for p in ELIMINAR_MACRO:
        if comando.startswith(p):
            nombre = comando[len(p):].strip()
            return "eliminar_macro", nombre

    ELIMINAR_MACRO_SIN_NOMBRE = {
        "elimina una macro", "elimina la macro", "elimina macro",
        "borra una macro", "borra la macro", "borra macro",
    }

    if frase_coincide_difuso(comando, ELIMINAR_MACRO_SIN_NOMBRE):
        return "eliminar_macro", ""

    # =====================================================
    # ACTUALIZACIONES
    # =====================================================

    BUSCAR_ACTUALIZACION = {
        "busca actualizaciones", "buscar actualizaciones",
        "hay actualizaciones", "hay alguna actualización",
        "hay alguna actualizacion", "comprueba actualizaciones",
        "revisa actualizaciones", "actualiza el asistente",
        "actualización disponible", "actualizacion disponible",
    }

    if frase_coincide_difuso(comando, BUSCAR_ACTUALIZACION):
        return "buscar_actualizacion", ""

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

    # =====================================================
    # MACROS GUARDADAS
    # Se comprueba DESPUÉS de los intents estándar — si el usuario
    # dice algo que coincide con una macro guardada, se activa.
    # Se hace como import diferido para no crear dependencia circular
    # (macros.py no importa intents.py, pero gestionar_macro.py sí).
    # =====================================================

    try:
        from macros import obtener_macro
        nombre_macro, pasos = obtener_macro(comando)
        if pasos:
            # se devuelve un intent especial con el nombre de la macro
            # como valor — executor.py lo detecta y ejecuta los pasos
            return "ejecutar_macro", nombre_macro
    except Exception:
        pass

    return None, None