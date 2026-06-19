sesion = {
    "activa":    False,
    "cancelar":  False,  # se pone True cuando el usuario dice la palabra de cancelación
}

# =========================================================
# PALABRAS DE CANCELACIÓN
# =========================================================

PALABRAS_CANCELAR = {
    "cancela",
    "cancelar",
    "para",
    "parar",
    "detente",
    "stop",
    "olvídalo",
    "olvidalo",
    "no importa",
    "déjalo",
    "dejalo",
}

def es_cancelacion(texto):
    if not texto:
        return False
    texto = texto.lower().strip()
    return any(p in texto for p in PALABRAS_CANCELAR)

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