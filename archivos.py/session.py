from voz_utils import frase_coincide_difuso

sesion = {
    "activa":    False,
    "cancelar":  False,  # se pone True cuando el usuario dice la palabra de cancelación
    # NUEVO: True mientras el asistente está en "modo dormido" (ver
    # es_dormir() más abajo) — suspende la reacción a la wake word
    # normal hasta que se diga la palabra de despertar, para quien
    # quiera privacidad/silencio un rato sin cerrar el asistente del
    # todo. Ver el manejo completo en main.py.
    "dormido":   False,
    # NUEVO: True si fue "duérmete" quien activó no_molestar (no el
    # usuario por su cuenta) — ver el FIX detallado en main.py, en el
    # bloque de es_dormir()/despertar. Distingue "no_molestar está
    # activo porque me dormí" de "no_molestar ya estaba activo antes
    # de dormirme, con su propia duración" — para no pisar ni cortar
    # antes de tiempo una duración que el usuario eligió a propósito.
    "dormido_activo_no_molestar": False,
}

# =========================================================
# PALABRAS DE CANCELACIÓN
# FIX: antes "para" y "parar" estaban en esta lista y se
# comparaban con `in` (substring) contra el texto completo.
# Esto causaba que frases como "para la música" o "para el
# video" (que deberían pausar el reproductor, ver PAUSAR en
# intents.py) se interpretaran como cancelación de sesión,
# porque "para" aparecía dentro del texto sin importar el
# contexto. Se quitó "para" de esta lista por ser demasiado
# ambigua en español (normalmente es preposición, no el verbo
# "parar"), y además ahora se compara por PALABRA COMPLETA
# (split + intersección) en vez de substring, para que frases
# como "detente un momento" no disparen falsos positivos por
# contener una palabra parecida a otra de la lista.
# =========================================================

PALABRAS_CANCELAR = {
    "cancela",
    "cancelar",
    "detente",
    "stop",
    "olvídalo",
    "olvidalo",
    "déjalo",
    "dejalo",
}

FRASES_CANCELAR = {
    "no importa",
}

def es_cancelacion(texto):
    if not texto:
        return False
    texto = texto.lower().strip()

    if any(frase in texto for frase in FRASES_CANCELAR):
        return True

    palabras = set(texto.split())
    return bool(palabras & PALABRAS_CANCELAR)

# =========================================================
# DESPEDIDA / FIN DE SESIÓN
# FIX: antes main.py comparaba el comando EXACTO contra una
# lista ("nada más", "eso es todo", etc). Si el reconocedor de
# voz agregaba una muletilla como "mmm nada más", la comparación
# fallaba, el comando terminaba en la IA de charla, y el
# asistente respondía algo que no tenía nada que ver con que el
# usuario quería terminar. Ahora se quitan esas muletillas antes
# de comparar.
# =========================================================

FRASES_DESPEDIDA = {
    "termina", "terminar", "termínalo",
    "adiós", "adios",
    "gracias", "muchas gracias",
    "nada más", "nada mas",
    "eso es todo", "eso era todo", "es todo",
    "ya no necesito nada", "ya no más", "ya no mas",
    "listo", "listo gracias",
}

_FILLERS_DESPEDIDA = {
    "mmm", "mm", "eh", "ehh", "ah", "ahh",
    "emm", "em", "pues", "bueno", "oye",
}

def _quitar_fillers(texto):
    palabras = texto.split()
    while palabras and palabras[0] in _FILLERS_DESPEDIDA:
        palabras.pop(0)
    while palabras and palabras[-1] in _FILLERS_DESPEDIDA:
        palabras.pop()
    return " ".join(palabras)

def es_despedida(texto):
    if not texto:
        return False
    texto = _quitar_fillers(texto.lower().strip())
    return frase_coincide_difuso(texto, FRASES_DESPEDIDA)

# =========================================================
# REPETIR ÚLTIMO MENSAJE
# NUEVO: si el usuario no llegó a escuchar bien lo último que dijo
# el asistente (ruido de fondo, se distrajo, o lo cortó sin querer
# con el barge-in), puede pedir que lo repita en vez de tener que
# adivinar o repetir su propio comando desde cero.
# =========================================================

FRASES_REPETIR = {
    "repite", "repítelo", "repitelo",
    "qué dijiste", "que dijiste",
    "no te escuché", "no te escuche",
    "no escuché", "no escuche",
    "puedes repetir", "puedes repetirlo",
    "otra vez qué dijiste", "otra vez que dijiste",
    "cómo dijiste", "como dijiste",
}

def es_repetir(texto):
    if not texto:
        return False
    texto = _quitar_fillers(texto.lower().strip())
    return texto in FRASES_REPETIR

# =========================================================
# MODO DORMIDO
# NUEVO: suspende la reacción del asistente a la wake word normal
# hasta que se diga la palabra de despertar (ver DESPIERTA_WORD) —
# para quien quiera privacidad/apagar el micrófono lógicamente un
# rato sin cerrar el asistente del todo (y sin perder recordatorios/
# temporizadores en curso, que siguen corriendo igual). Se activa
# SOLO durante una sesión ya activa (después de la wake word normal),
# igual que despedida/cancelación.
# =========================================================

FRASES_DORMIR = {
    "duérmete", "duermete",
    "ponte a dormir", "vete a dormir",
    "modo silencioso", "silencio total",
    "deja de escuchar",
}

DESPIERTA_WORD = "despierta"

def es_dormir(texto):
    if not texto:
        return False
    texto = _quitar_fillers(texto.lower().strip())
    return frase_coincide_difuso(texto, FRASES_DORMIR)