"""
Utilidades pequeñas y compartidas para interacciones de voz guiadas
(preguntar algo, mostrar opciones numeradas, interpretar la elección
del usuario). Pensado para flujos como eliminar_alias_guiado
(registrar_alias.py) y cancelar_recordatorio_guiado (acciones.py),
que comparten el mismo patrón: listar opciones cortas y dejar elegir
por número o por texto aproximado, en vez de requerir el texto exacto
de una sola vez.
"""

NUMEROS_PALABRA = {
    "uno": 1, "primero": 1, "primer": 1,
    "dos": 2, "segundo": 2,
    "tres": 3, "tercero": 3, "tercer": 3,
    "cuatro": 4, "cuarto": 4,
    "cinco": 5, "quinto": 5,
}

# =========================================================
# UMBRAL DE SIMILITUD DIFUSA
# FIX/NUEVO: el mismo umbral (0.80) para considerar dos textos
# "suficientemente parecidos" vivía duplicado como número mágico en
# wakeword.py (detectar_wakeword) y en macros.py (obtener_macro) —
# fácil de olvidar ajustar en los dos lugares si algún día se decide
# afinarlo. Ahora vive en un solo sitio, y ambos módulos lo importan
# de acá en vez de repetir el literal 0.80 cada uno por su cuenta.
# =========================================================

UMBRAL_SIMILITUD_DIFUSA = 0.80

# =========================================================
# CONFIRMACIÓN SÍ/NO
# FIX: antes de esto, acciones.py tenía 4 listas SI distintas (y una
# NO) repartidas en distintas funciones de confirmación, cada una con
# variantes ligeramente distintas — algunas incluían "ci"/"cí"/"zi"/
# "zí" (variantes fonéticas comunes de cómo Whisper transcribe un
# "sí" corto dicho solo, ver voice.py y las pruebas con la wake word),
# otras no. Eso significaba que la MISMA respuesta del usuario podía
# reconocerse como afirmación en un flujo de confirmación y fallar en
# otro, solo por estar en un archivo distinto del proyecto.
#
# Ahora hay una base ÚNICA y compartida (PALABRAS_SI/PALABRAS_NO) con
# todas las variantes fonéticas conocidas. Cada función de
# confirmación puede seguir agregando sus propias palabras
# CONTEXTUALES además de la base (ej. "abrir"/"hazlo" tiene sentido
# específico para confirmar abrir una app, pero no para confirmar un
# recordatorio) — es_afirmacion() acepta extras opcionales para eso.
# =========================================================

PALABRAS_SI = {
    "si", "sí", "ci", "cí", "zi", "zí",
    "dale", "ok", "okay", "claro", "confirmo",
}

PALABRAS_NO = {
    "no", "nel", "cancela", "cancelar", "negativo",
}


def es_afirmacion(respuesta, extras_si=None):
    """
    True si `respuesta` contiene alguna palabra de afirmación
    (PALABRAS_SI + las palabras extra opcionales de `extras_si`,
    útiles para variantes específicas del contexto de la pregunta,
    ej. "ábrelo" al confirmar apertura de una app).
    """
    respuesta = (respuesta or "").lower()
    palabras  = PALABRAS_SI | set(extras_si or [])
    return any(palabra in respuesta for palabra in palabras)


def es_negacion(respuesta, extras_no=None):
    """Lo mismo que es_afirmacion(), pero para negaciones."""
    respuesta = (respuesta or "").lower()
    palabras  = PALABRAS_NO | set(extras_no or [])
    return any(palabra in respuesta for palabra in palabras)


# =========================================================
# CONFIRMACIÓN SÍ/NO CON RESPALDO DE IA
# NUEVO: es_afirmacion()/es_negacion() son rápidas, gratis, y
# funcionan sin internet — pero solo cubren las formas de decir
# sí/no que ya están en PALABRAS_SI/PALABRAS_NO. En uso real, la
# gente confirma de formas mucho más variadas ("obvio", "dale pues",
# "mejor no", "para qué preguntas") que ningún diccionario fijo
# alcanza a prever — y cuando eso pasaba, el asistente respondía
# "No te entendí" aunque la intención fuera perfectamente clara para
# cualquier persona escuchando.
#
# interpretar_confirmacion() agrega un respaldo: si el match local
# no encuentra nada, le pasa la respuesta a la IA híbrida (Groq con
# internet, Ollama local sin internet — ver ia.py/gestor_ia.py) para
# que la clasifique como sí/no/ambiguo. Esto cubre muchas más formas
# naturales de responder, sin perder la velocidad del match local
# para los casos obvios (que siguen siendo la gran mayoría).
# =========================================================

def interpretar_confirmacion(respuesta, extras_si=None, extras_no=None, contexto=""):
    """
    Interpreta una respuesta de confirmación sí/no.

    Devuelve:
      True  -> se interpretó como afirmación
      False -> se interpretó como negación
      None  -> ni el match local ni la IA pudieron determinarlo (la
               respuesta es realmente ambigua, vino vacía, o ambos
               motores de IA fallaron) — quien llama decide qué hacer
               en ese caso (normalmente: volver a preguntar, o usar
               False como respuesta segura por defecto).

    `contexto` es la pregunta que se le hizo al usuario (ej. "¿Quieres
    abrir Discord?") — se le pasa a la IA para que tenga en cuenta a
    qué está respondiendo, no solo el texto suelto de la respuesta.
    """
    if es_afirmacion(respuesta, extras_si):
        return True

    if es_negacion(respuesta, extras_no):
        return False

    if not respuesta:
        return None

    # import diferido: evita cargar todo ia.py (que a su vez importa
    # ollama, groq, etc.) en cada arranque del asistente para algo
    # que solo hace falta en el caso ambiguo, que es la minoría.
    try:
        from ia import _llamar_ollama
    except Exception:
        return None

    prompt = (
        "El usuario le está respondiendo sí o no a un asistente de "
        "voz en español. "
        + (f'La pregunta fue: "{contexto}". ' if contexto else "")
        + f'Su respuesta fue: "{respuesta}". '
        "¿Eso significa sí o no? Responde ÚNICAMENTE con una palabra: "
        "si, no, o ambiguo. Sin explicaciones, sin puntuación, sin "
        "nada más."
    )

    salida = _llamar_ollama(prompt, timeout=6, num_predict=5, temperature=0.0)

    if not salida:
        return None

    salida = salida.lower().strip()

    if salida.startswith("si") or salida.startswith("sí"):
        return True

    if salida.startswith("no"):
        return False

    return None


# =========================================================
# PEDIR UN DATO FALTANTE (sin reiniciar todo el flujo)
# FIX/NUEVO: varios flujos de creación por voz (recordatorios,
# temporizadores) fallaban directo y de forma genérica cuando algún
# dato no se entendía (la fecha, la duración) — el usuario tenía que
# repetir el comando COMPLETO desde cero, incluso las partes que sí
# había dicho bien. Esta función es el reemplazo: pregunta solo por
# el dato que falta, y si la respuesta es una palabra de cancelación
# (ver session.es_cancelacion) — o si no se escuchó nada — devuelve
# None para que quien llama pueda abandonar el flujo con elegancia
# en vez de tratarlo como "no entendí, todo mal".
# =========================================================

def preguntar_dato(pregunta):
    """
    Habla `pregunta` y escucha la respuesta.

    Devuelve:
      el texto de la respuesta (str) tal cual se escuchó, o
      None si el usuario canceló explícitamente (dijo una palabra
      de cancelación) o si no se escuchó nada — quien llama debe
      tratar ambos casos como "abandonar este dato/flujo", sin
      reintentar más ni tratarlo como un error genérico.
    """
    from tts import hablar
    from voice import escuchar
    from session import es_cancelacion

    hablar(pregunta)
    respuesta = escuchar()

    if not respuesta:
        return None

    if es_cancelacion(respuesta):
        return None

    return respuesta.strip()


def elegir_de_lista(respuesta, opciones):
    """
    Interpreta la respuesta del usuario como una elección dentro de
    `opciones` (lista de strings). Acepta:
    - Un número en palabra o dígito ("el primero", "el 2", "dos") →
      índice 1-based, convertido a 0-based.
    - Texto que coincide aproximadamente con una de las opciones.
    Devuelve el índice (0-based) elegido, o None si no se identificó
    una opción única.
    """
    respuesta = (respuesta or "").lower().strip()

    if not respuesta:
        return None

    for palabra, numero in NUMEROS_PALABRA.items():
        if palabra in respuesta and 1 <= numero <= len(opciones):
            return numero - 1

    for digito in range(1, len(opciones) + 1):
        if str(digito) in respuesta:
            return digito - 1

    # coincidencia de texto aproximada contra cada opción
    coincidencias = [
        i for i, opcion in enumerate(opciones)
        if respuesta in opcion.lower() or opcion.lower() in respuesta
    ]

    if len(coincidencias) == 1:
        return coincidencias[0]

    return None