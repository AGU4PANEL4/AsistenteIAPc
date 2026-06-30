"""
Configuración guiada de la API key de Groq al primer arranque.

NUEVO: pensado para compartir el proyecto con otra persona que lo
prueba en una PC distinta (un entorno nuevo, sin ninguna configuración
previa) — sin esto, esa persona vería el asistente funcionando siempre
con Ollama local (sin saber por qué nunca usa Groq, ni que Groq existe
como opción) hasta que alguien le explicara manualmente cómo y dónde
conseguir y poner la key.

Si la key YA está configurada (por variable de entorno o en
config.json, de una ejecución anterior), asegurar_groq_configurado()
no hace nada y retorna de inmediato — esto NO se repite en cada
arranque, solo la primera vez que falta.
"""

import os
import webbrowser

from config import cargar_config, guardar_groq_api_key

URL_GROQ_KEYS = "https://console.groq.com/keys"

RESPUESTAS_OMITIR = {"omitir", "skip", "no", "saltar", "ninguna"}


def _validar_api_key(key):
    """
    Prueba la key haciendo una llamada REAL y mínima a la API de
    Groq (no solo revisa el formato del texto) — la única forma
    confiable de saber si una key copiada funciona de verdad es
    usarla. Devuelve True si Groq respondió correctamente, False si
    falló por cualquier motivo (key inválida/mal copiada, sin cuota,
    problema de red puntual, etc — groq_cliente.py ya distingue e
    imprime el motivo específico en consola).
    """
    # se prueba la key SIN guardarla todavía en config.json — solo
    # se persiste de verdad si la validación es exitosa. Se usa la
    # variable de entorno como medio temporal porque
    # obtener_groq_api_key() (config.py) la revisa primero.
    os.environ["GROQ_API_KEY"] = key

    from groq_cliente import resetear_cliente, llamar_groq
    resetear_cliente()

    respuesta = llamar_groq(
        "Responde únicamente con la palabra: ok",
        timeout=10,
        num_predict=5,
    )

    if respuesta is None:
        # se quita del entorno para no dejar puesta una key inválida
        # si el usuario decide omitir después de este intento
        os.environ.pop("GROQ_API_KEY", None)
        resetear_cliente()
        return False

    return True


def asegurar_groq_configurado():
    """
    Llamar una sola vez al arrancar el asistente, antes de que
    arranque el loop principal.

    Si falta la key, pide configurarla:
      1. Abre automáticamente la página donde se genera una key
         gratuita de Groq.
      2. La pide por consola.
      3. La valida con una llamada real a la API.
      4. Si responde bien, la guarda en config.json y continúa.
      5. Si falla, explica por qué y vuelve a pedirla — o permite
         omitir el paso (escribiendo "omitir"), en cuyo caso el
         asistente sigue funcionando normalmente, solo que sin el
         modo híbrido: usará Ollama local siempre, igual que antes
         de que existiera Groq en el proyecto.
    """
    config = cargar_config()

    key_actual = os.environ.get("GROQ_API_KEY") or config.get("groq_api_key", "")

    if key_actual:
        return

    print("\n[Groq] No encontré una API key de Groq configurada en esta PC.")
    print("[Groq] Groq es gratis y deja que el asistente responda mucho más")
    print("[Groq] rápido (y sin usar tu GPU) cada vez que haya internet.")
    print("[Groq] Abriendo la página para crear una key...")

    try:
        webbrowser.open(URL_GROQ_KEYS)
    except Exception:
        pass

    print(f"[Groq] Si no se abrió sola, entra a: {URL_GROQ_KEYS}")

    while True:
        key = input(
            "\nPega aquí tu GROQ_API_KEY (o escribe 'omitir' para seguir "
            "sin Groq, solo con Ollama local): "
        ).strip()

        if key.lower() in RESPUESTAS_OMITIR:
            print("[Groq] Ok, continuando sin Groq — se usará Ollama local.")
            return

        if not key:
            print("[Groq] No escribiste nada, intenta de nuevo.")
            continue

        print("[Groq] Verificando la key con una llamada de prueba...")

        if _validar_api_key(key):
            guardar_groq_api_key(key)
            print("[Groq] ¡Listo! La key funciona y quedó guardada.\n")
            return

        print("[Groq] La key no funcionó — revisa el motivo arriba (puede estar")
        print("[Groq] mal copiada, sin cuota, o un problema de red puntual).")
        print("[Groq] Intenta pegarla de nuevo, o escribe 'omitir' para seguir sin Groq.")