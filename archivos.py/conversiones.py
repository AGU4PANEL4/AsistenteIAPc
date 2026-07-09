"""
Conversión de unidades comunes (longitud, peso, volumen, temperatura)
— resuelto con matemática pura, SIN pasar por la IA.

Por qué esto NO usa el modelo de IA como el resto de "charla libre"
(ver responder_charla en ia.py): una conversión de unidades es un
dato FIJO y determinístico — 1 centímetro son siempre 10 milímetros,
no hay nada que "razonar" ni que un modelo pueda interpretar
distinto según el contexto. Resolverlo acá, con una cuenta directa
en Python, es instantáneo, funciona sin internet ni Ollama corriendo,
y tiene cero riesgo de que un modelo se equivoque en la cuenta (algo
que SÍ puede pasar, incluso con modelos grandes, en aritmética con
números feos — ver la conversación de diseño de responder_charla).

Uso desde intents.py:
    from conversiones import detectar_conversion
    resultado = detectar_conversion(texto)
    if resultado:
        return "conversion_unidades", resultado
"""

import re
import unicodedata

# =========================================================
# UNIDADES SOPORTADAS
# Cada categoría (salvo temperatura) usa una unidad BASE de factor
# 1.0, para poder convertir cualquier unidad de esa categoría a
# cualquier otra en dos pasos: origen -> base -> destino.
# =========================================================

LONGITUD = {
    "milimetro": 0.001, "milimetros": 0.001, "mm": 0.001,
    "centimetro": 0.01, "centimetros": 0.01, "cm": 0.01,
    "metro": 1.0, "metros": 1.0, "mts": 1.0,
    "kilometro": 1000.0, "kilometros": 1000.0, "km": 1000.0,
}

PESO = {
    "miligramo": 0.001, "miligramos": 0.001, "mg": 0.001,
    "gramo": 1.0, "gramos": 1.0,
    "kilogramo": 1000.0, "kilogramos": 1000.0, "kg": 1000.0,
    "kilo": 1000.0, "kilos": 1000.0,
}

VOLUMEN = {
    "mililitro": 0.001, "mililitros": 0.001, "ml": 0.001,
    "litro": 1.0, "litros": 1.0,
}

# temperatura no es una simple multiplicación (0°C no es "cero
# unidades base") — se resuelve aparte, este dict solo identifica el
# símbolo (C/F) de cada palabra reconocida
TEMPERATURA = {
    "celsius": "C", "centigrados": "C", "centígrados": "C",
    "fahrenheit": "F",
}

_TODAS_LAS_UNIDADES = {**LONGITUD, **PESO, **VOLUMEN, **TEMPERATURA}

# nombres para armar la respuesta hablada — singular si la cantidad
# es 1, plural en cualquier otro caso ("1 centímetro" vs "10
# centímetros"), y con tilde aunque el reconocimiento de voz/regex
# funcione sin ella
NOMBRE_SINGULAR = {
    "milimetro": "milímetro", "milimetros": "milímetro", "mm": "milímetro",
    "centimetro": "centímetro", "centimetros": "centímetro", "cm": "centímetro",
    "metro": "metro", "metros": "metro", "mts": "metro",
    "kilometro": "kilómetro", "kilometros": "kilómetro", "km": "kilómetro",
    "miligramo": "miligramo", "miligramos": "miligramo", "mg": "miligramo",
    "gramo": "gramo", "gramos": "gramo",
    "kilogramo": "kilogramo", "kilogramos": "kilogramo", "kg": "kilogramo",
    "kilo": "kilogramo", "kilos": "kilogramo",
    "mililitro": "mililitro", "mililitros": "mililitro", "ml": "mililitro",
    "litro": "litro", "litros": "litro",
    "celsius": "grado celsius", "centigrados": "grado celsius",
    "centígrados": "grado celsius",
    "fahrenheit": "grado fahrenheit",
}

NOMBRE_PLURAL = {
    "milimetro": "milímetros", "milimetros": "milímetros", "mm": "milímetros",
    "centimetro": "centímetros", "centimetros": "centímetros", "cm": "centímetros",
    "metro": "metros", "metros": "metros", "mts": "metros",
    "kilometro": "kilómetros", "kilometros": "kilómetros", "km": "kilómetros",
    "miligramo": "miligramos", "miligramos": "miligramos", "mg": "miligramos",
    "gramo": "gramos", "gramos": "gramos",
    "kilogramo": "kilogramos", "kilogramos": "kilogramos", "kg": "kilogramos",
    "kilo": "kilogramos", "kilos": "kilogramos",
    "mililitro": "mililitros", "mililitros": "mililitros", "ml": "mililitros",
    "litro": "litros", "litros": "litros",
    "celsius": "grados celsius", "centigrados": "grados celsius",
    "centígrados": "grados celsius",
    "fahrenheit": "grados fahrenheit",
}

_NUMEROS_PALABRA = {
    "un": 1, "uno": 1, "una": 1,
    "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
}

_PATRON_UNIDAD = r"[a-záéíóúñ]+"


def _quitar_tildes(texto):
    """
    Quita tildes (á->a, é->e, etc.) sin tocar la ñ. Necesario porque
    los diccionarios de arriba (LONGITUD, PESO, ...) usan formas SIN
    tilde como clave — el texto real que llega desde voz SÍ suele
    traer tildes ("centímetro", "kilómetros"), así que sin esto
    "centímetro" nunca hubiera matcheado contra la clave
    "centimetro" del diccionario. Los nombres CON tilde para la
    respuesta hablada (NOMBRE_SINGULAR/NOMBRE_PLURAL) no se tocan —
    esto solo se usa para la comparación, nunca para lo que se dice.
    """
    forma_nfkd = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(
        c for c in forma_nfkd
        if not unicodedata.combining(c) or c == "\u0303"  # preserva la ñ
    )
    # NFKD separa ñ -> n + combining tilde (\u0303); al filtrar
    # combining characters de más arriba se perdería la ñ si no se
    # la excluyera explícitamente — se recompone acá
    return unicodedata.normalize("NFC", sin_tildes)


def _categoria_de(unidad):
    if unidad in LONGITUD:
        return "longitud"
    if unidad in PESO:
        return "peso"
    if unidad in VOLUMEN:
        return "volumen"
    if unidad in TEMPERATURA:
        return "temperatura"
    return None


def _nombre(unidad, cantidad):
    tabla = NOMBRE_SINGULAR if abs(cantidad - 1) < 1e-9 else NOMBRE_PLURAL
    return tabla.get(unidad, unidad)


def _formatear_numero(n):
    """1.0 -> '1', 2.5 -> '2.5' — evita decimales espurios como
    '1.0' o '3.3300000000000005' en la respuesta hablada."""
    n = round(n, 4)
    if n == int(n):
        return str(int(n))
    texto = f"{n:.2f}".rstrip("0").rstrip(".")
    return texto


def _encontrar_numero(texto):
    """Devuelve (numero, posicion_donde_termina) o (None, None).
    Prueba dígitos primero (más común en voz transcrita); si no hay,
    cae a un número escrito en palabra ("un", "dos", ..., "diez")."""
    match = re.search(r"\d+(?:[.,]\d+)?", texto)
    if match:
        return float(match.group().replace(",", ".")), match.end()

    for palabra, valor in _NUMEROS_PALABRA.items():
        m = re.search(rf"\b{re.escape(palabra)}\b", texto)
        if m:
            return float(valor), m.end()

    return None, None


def detectar_conversion(texto):
    """
    Reconoce una pregunta de conversión de unidades ("cuántos
    milímetros hay en 1 centímetro", "convierte 5 km a metros",
    "cuánto es 20 celsius en fahrenheit") y devuelve el texto de la
    respuesta YA CALCULADO, listo para hablar.

    Devuelve None si el texto no parece una conversión reconocible —
    entre otros casos: no hay ningún número, no hay una unidad
    reconocida pegada a ese número, no hay una segunda unidad
    reconocida en el resto de la frase, o las dos unidades son de
    categorías distintas (ej. "cuántos gramos hay en un metro" no
    tiene sentido — se ignora en vez de inventar algo).
    """
    texto = (texto or "").lower().strip()
    if not texto:
        return None

    texto = _quitar_tildes(texto)

    numero, fin_numero = _encontrar_numero(texto)
    if numero is None:
        return None

    # todas las palabras del texto que son unidades reconocidas, con
    # su posición — para poder elegir cuál es "la unidad del número"
    # (origen) y cuál es la otra (destino), sin importar el orden en
    # que aparezcan en la frase
    candidatas = [
        (m.start(), m.group())
        for m in re.finditer(_PATRON_UNIDAD, texto)
        if m.group() in _TODAS_LAS_UNIDADES
    ]

    if len(candidatas) < 2:
        return None

    # la unidad de ORIGEN es la reconocida más cercana (y posterior)
    # al número — en cualquier frase natural de conversión, la
    # unidad que acompaña al número es siempre la de origen
    tras_numero = [c for c in candidatas if c[0] >= fin_numero]
    if not tras_numero:
        return None

    pos_origen, unidad_origen = min(tras_numero, key=lambda c: c[0])

    if pos_origen - fin_numero > 3:
        # más de un espacio de por medio — demasiado lejos del
        # número como para ser realmente "su" unidad (evita falsos
        # positivos con frases donde número y unidad no están
        # relacionados)
        return None

    # la unidad de DESTINO es cualquier otra unidad reconocida en el
    # texto, distinta de la de origen
    destino = next(
        (u for pos, u in candidatas if not (pos == pos_origen and u == unidad_origen)),
        None,
    )
    if not destino:
        return None

    unidad_destino = destino

    categoria = _categoria_de(unidad_origen)
    if categoria != _categoria_de(unidad_destino):
        return None

    # =====================================================
    # CALCULAR
    # =====================================================

    if categoria == "temperatura":
        simbolo_origen  = TEMPERATURA[unidad_origen]
        simbolo_destino = TEMPERATURA[unidad_destino]

        if simbolo_origen == simbolo_destino:
            resultado = numero
        elif simbolo_origen == "C":
            resultado = numero * 9 / 5 + 32
        else:
            resultado = (numero - 32) * 5 / 9
    else:
        tabla = {"longitud": LONGITUD, "peso": PESO, "volumen": VOLUMEN}[categoria]
        valor_base = numero * tabla[unidad_origen]
        resultado  = valor_base / tabla[unidad_destino]

    numero_fmt    = _formatear_numero(numero)
    resultado_fmt = _formatear_numero(resultado)

    nombre_origen  = _nombre(unidad_origen, numero)
    nombre_destino = _nombre(unidad_destino, resultado)

    return f"{numero_fmt} {nombre_origen} son {resultado_fmt} {nombre_destino}"