import re

# =========================================================
# PARSEO DE DURACIÓN RELATIVA
# Compartido entre recordatorios.py, temporizadores.py, y
# _extraer_minutos_no_molestar() en intents.py — todos necesitan
# interpretar frases tipo "10 minutos", "1 hora 30 minutos", "2
# horas", "30 segundos".
# =========================================================

_UNIDADES = {
    "segundo":  1,
    "segundos": 1,
    "minuto":   60,
    "minutos":  60,
    "min":      60,
    "mins":     60,
    "hora":     3600,
    "horas":    3600,
}

# =========================================================
# NÚMEROS EN PALABRA
# FIX/NUEVO: el regex de abajo solo reconoce dígitos ("10 minutos",
# "2 horas") — un número dicho en palabra pegado a la unidad ("un
# minuto", "una hora", "dos minutos") no matcheaba NADA, y
# parsear_duracion() devolvía None como si no hubiera ninguna
# duración en el texto.
#
# Caso real reportado: "no me molestes por un minuto" → como
# parsear_duracion() no reconocía "un minuto", el fallback de
# _extraer_minutos_no_molestar() en intents.py caía al default de
# 60 minutos (una hora) en vez de activar no molestar por el minuto
# que el usuario pidió — el mismo problema aplica a recordatorios.py
# ("recuérdame en un minuto que...") y temporizadores.py ("pon un
# temporizador de un minuto"), que también usan esta función.
#
# Se normalizan los números en palabra a dígitos ANTES del regex
# (mismo patrón ya usado en recordatorios.py._normalizar_numeros_palabra
# y conversiones.py._NUMEROS_PALABRA, pero centralizado acá porque
# es exactamente el punto de entrada que comparten los tres módulos)
# — así "un minuto" se convierte en "1 minuto" antes de buscar el
# patrón, sin duplicar la lógica de parseo para dígitos vs palabras.
# =========================================================

_NUMEROS_PALABRA_DURACION = {
    "un": 1, "una": 1, "uno": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "quince": 15,
    "veinte": 20, "treinta": 30, "cuarenta": 40,
    "cincuenta": 50, "sesenta": 60,
}


def _normalizar_numeros_palabra(texto):
    palabras  = texto.split()
    resultado = []
    for palabra in palabras:
        clave = palabra.strip(",.;:")
        if clave in _NUMEROS_PALABRA_DURACION:
            resultado.append(str(_NUMEROS_PALABRA_DURACION[clave]))
        else:
            resultado.append(palabra)
    return " ".join(resultado)


def parsear_duracion(texto):
    """
    Busca patrones tipo '10 minutos', '1 hora 30 minutos', '2 horas',
    'un minuto', 'una hora' dentro del texto (puede venir acompañado
    de otras palabras, ej. "recuérdame en 10 minutos"). Devuelve
    segundos totales, o None si no encontró nada.
    """
    texto = (texto or "").lower().strip()
    texto = _normalizar_numeros_palabra(texto)

    patron = re.findall(r"(\d+)\s*(segundos?|minutos?|min|mins|horas?)", texto)

    if not patron:
        return None

    total_segundos = 0
    for cantidad, unidad in patron:
        total_segundos += int(cantidad) * _UNIDADES.get(unidad, 0)

    return total_segundos if total_segundos > 0 else None