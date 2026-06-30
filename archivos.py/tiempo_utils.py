import re

# =========================================================
# PARSEO DE DURACIÓN RELATIVA
# Compartido entre recordatorios.py y temporizadores.py — ambos
# necesitan interpretar frases tipo "10 minutos", "1 hora 30
# minutos", "2 horas", "30 segundos".
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


def parsear_duracion(texto):
    """
    Busca patrones tipo '10 minutos', '1 hora 30 minutos', '2 horas'
    dentro del texto (puede venir acompañado de otras palabras, ej.
    "recuérdame en 10 minutos"). Devuelve segundos totales, o None
    si no encontró nada.
    """
    texto = (texto or "").lower().strip()

    patron = re.findall(r"(\d+)\s*(segundos?|minutos?|min|mins|horas?)", texto)

    if not patron:
        return None

    total_segundos = 0
    for cantidad, unidad in patron:
        total_segundos += int(cantidad) * _UNIDADES.get(unidad, 0)

    return total_segundos if total_segundos > 0 else None