sesion = {
    "activa":    False,
    "cancelar":  False,  # se pone True cuando el usuario dice la palabra de cancelación
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
    return texto in FRASES_DESPEDIDA