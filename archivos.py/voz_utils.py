"""
Utilidades pequeñas y compartidas para interacciones de voz guiadas
(preguntar algo, mostrar opciones numeradas, interpretar la elección
del usuario). Pensado para flujos como eliminar_alias_guiado
(registrar_alias.py) y cancelar_recordatorio_guiado (acciones.py),
que comparten el mismo patrón: listar opciones cortas y dejar elegir
por número o por texto aproximado, en vez de requerir el texto exacto
de una sola vez.
"""

import time

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
# "ESPERA" / DAME UN MOMENTO
# NUEVO: los flujos guiados por voz (registrar alias, crear macro,
# etc.) solo tenían dos desenlaces posibles si el usuario tardaba en
# responder: contestar a tiempo, o que el flujo se diera por vencido
# (timeout) o lo tomara como cancelación. Si el usuario solo
# necesitaba un segundo para pensar y lo decía en voz alta ("espera",
# "dame un segundo"), eso no calzaba con ninguna palabra de
# confirmación NI de cancelación — en la práctica se comportaba como
# silencio, y el flujo terminaba fallando de todas formas.
#
# es_espera() reconoce esas frases; escuchar_con_reintento() es el
# helper compartido que las usa para dar más tiempo en vez de
# fallar — reemplaza las copias casi idénticas de "escuchar con
# timeout en loop" que había repetidas en registrar_alias.py y
# gestionar_macro.py.
# =========================================================

PALABRAS_ESPERA = {
    "espera", "esperate", "espérate",
    "un momento", "un segundo",
    "dame un segundo", "dame un momento",
    "aguanta", "aguántame", "aguantame",
    "ya voy", "dame tiempo",
}


def es_espera(texto):
    """True si `texto` es un pedido de más tiempo, no una respuesta
    real ni una cancelación."""
    texto = (texto or "").lower().strip()
    return texto in PALABRAS_ESPERA


def escuchar_con_reintento(timeout=8, max_esperas=3):
    """
    Escucha una respuesta, con el mismo comportamiento de timeout que
    ya tenían registrar_alias.py/gestionar_macro.py (reintentar
    escuchar() hasta que pase `timeout` segundos en total sin nada),
    PERO si lo que se escucha es un pedido de más tiempo (ver
    es_espera), no cuenta como fallo ni como respuesta — se reinicia
    el reloj y se sigue escuchando, hasta `max_esperas` veces (para
    no quedar esperando para siempre si alguien dice "espera" sin
    parar).

    Devuelve el texto de la respuesta real, o "" si se acabó el
    tiempo sin conseguir ninguna.
    """
    from voice import escuchar

    esperas_usadas = 0

    while True:
        inicio = time.time()

        while True:
            respuesta = escuchar()
            if respuesta:
                break
            if time.time() - inicio > timeout:
                return ""

        if es_espera(respuesta) and esperas_usadas < max_esperas:
            esperas_usadas += 1
            continue

        return respuesta


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
# DESCRIBIR UN PASO (intent, valor) → FRASE LEGIBLE
# FIX/NUEVO: vivía como _describir_paso() dentro de gestionar_macro.py
# (privada, solo para narrar los pasos mientras se arma una macro por
# voz) — pero executor.py también la necesita ahora, para armar UN
# resumen final de una cadena/macro en vez de que cada paso hable su
# propio mensaje por separado (ver el FIX en executor.py). Se mueve
# acá, pública, para que ambos módulos la compartan sin duplicarla ni
# crear un import circular (executor.py no puede importar de
# gestionar_macro.py: tools.py importa gestionar_macro, y executor.py
# importa tools).
# =========================================================

def describir_paso(intent, valor):
    """Convierte (intent, valor) en una frase legible en español,
    usada tanto al construir una macro por voz (gestionar_macro.py)
    como al resumir una cadena/macro ya ejecutada (executor.py)."""
    descripciones = {
        "abrir_app":           f"abrir {valor}",
        "cerrar_app":          f"cerrar {valor}",
        "minimizar_app":       f"minimizar {valor}",
        "maximizar_app":       f"maximizar {valor}",
        "media_pausar":        "pausar",
        "media_reanudar":      "reanudar",
        "media_siguiente":     "siguiente canción",
        "media_anterior":      "canción anterior",
        "media_subir_volumen": "subir volumen",
        "media_bajar_volumen": "bajar volumen",
        "media_silenciar":     "silenciar",
        "media_volumen_exacto": f"volumen al {valor.split('|')[-1].strip()}" if valor else "cambiar volumen",
        "buscar_google":       f"buscar en Google: {valor}",
        "abrir_youtube":       f"buscar en YouTube: {valor}",
        "abrir_url":           f"abrir {valor}",
        "activar_startup":     "activar inicio automático",
        "desactivar_startup":  "desactivar inicio automático",
    }
    return descripciones.get(intent, f"{intent} {valor}".strip())


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

    FIX/NUEVO: usa escuchar_con_reintento() en vez de una sola
    llamada a escuchar() — si la respuesta es un pedido de más
    tiempo ("espera", "dame un segundo"), se le da margen extra en
    vez de tratarlo como "no escuché nada" y abandonar el dato.
    """
    from tts import hablar
    from session import es_cancelacion

    hablar(pregunta)
    respuesta = escuchar_con_reintento(timeout=8)

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