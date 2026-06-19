import ollama
import re
import concurrent.futures
from memory import memoria
from config import MODELO_OLLAMA

# =========================================================
# CLIENTE OLLAMA CON TIMEOUT
# FIX: antes se usaba ollama.chat() directo, sin ningún límite
# de tiempo. Si la GPU está ocupada (ej: un juego corriendo al
# mismo tiempo), la inferencia se vuelve lenta y el asistente se
# queda esperando indefinidamente, sin avisar nada. Ahora se usa
# un cliente con timeout, y ADEMÁS se envuelve la llamada en un
# hilo con su propio límite de tiempo, para garantizar que el
# asistente nunca se quede colgado más de unos segundos, pase lo
# que pase con Ollama.
# =========================================================

_cliente_ollama = ollama.Client(timeout=15)
_executor_ia    = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _llamar_ollama(prompt, timeout=12, num_predict=40, temperature=0.2):
    """
    Llama al modelo con un límite de tiempo real. Devuelve el texto
    de la respuesta, o None si Ollama tardó demasiado o falló.

    num_predict limita cuántos tokens puede generar como máximo —
    como nuestras respuestas son cortas ("action|value" o 1-2
    frases), esto evita que una generación que se desboca alargue
    aún más una GPU ya ocupada.
    """

    def _tarea():
        return _cliente_ollama.chat(
            model=MODELO_OLLAMA,
            messages=[{"role": "user", "content": prompt}],
            options={
                "num_predict": num_predict,
                "temperature": temperature,
            },
        )

    futuro = _executor_ia.submit(_tarea)

    try:
        respuesta = futuro.result(timeout=timeout)
        return respuesta["message"]["content"].strip()

    except concurrent.futures.TimeoutError:
        print(f"[IA] Ollama tardó más de {timeout}s, se cancela la espera "
              f"(¿hay un juego usando la GPU en este momento?)")
        return None

    except Exception as e:
        print("[IA] Error llamando a Ollama:", e)
        return None

# =========================================================
# ACCIONES VÁLIDAS
# =========================================================

ACCIONES_VALIDAS = {
    "abrir_app",
    "cerrar_app",
    "buscar_google",
    "abrir_youtube",
    "abrir_url",
    "activar_startup",
    "desactivar_startup",
    "estado_startup",
    "recapturar_app",
    "eliminar_alias",
    "minimizar_app",
    "maximizar_app",
    "media_pausar",
    "media_reanudar",
    "media_siguiente",
    "media_anterior",
    "media_subir_volumen",
    "media_bajar_volumen",
    "media_silenciar",
    "media_volumen_exacto",
    "registrar_alias",
    "terminar_sesion",
}

# =========================================================
# MAPEO DE VARIACIONES QUE GEMMA3 SUELE ESCRIBIR
# =========================================================

NORMALIZAR_INTENT = {
    "open_app":            "abrir_app",
    "close_app":           "cerrar_app",
    "search_google":       "buscar_google",
    "open_youtube":        "abrir_youtube",
    "search_youtube":      "abrir_youtube",
    "open_url":            "abrir_url",
    "activate_startup":    "activar_startup",
    "deactivate_startup":  "desactivar_startup",
    "startup_status":      "estado_startup",
    "recapture_app":       "recapturar_app",
    "activar_inicio":      "activar_startup",
    "desactivar_inicio":   "desactivar_startup",
    "estado_inicio":       "estado_startup",
    "minimize_app":        "minimizar_app",
    "maximize_app":        "maximizar_app",
    "bring_to_front":      "maximizar_app",
    "show_app":            "maximizar_app",
    "hide_app":            "minimizar_app",
    "pause_media":         "media_pausar",
    "play_media":          "media_reanudar",
    "resume_media":        "media_reanudar",
    "next_track":          "media_siguiente",
    "prev_track":          "media_anterior",
    "previous_track":      "media_anterior",
    "volume_up":           "media_subir_volumen",
    "volume_down":         "media_bajar_volumen",
    "mute":                "media_silenciar",
    "unmute":              "media_silenciar",
    "set_volume":          "media_volumen_exacto",
    "volume_set":          "media_volumen_exacto",
    "register_alias":      "registrar_alias",
    "end_session":         "terminar_sesion",
    "end_conversation":    "terminar_sesion",
    "stop_session":        "terminar_sesion",
    "goodbye":             "terminar_sesion",
    "say_goodbye":         "terminar_sesion",
    "finish":              "terminar_sesion",
    "exit":                "terminar_sesion",
}

# =========================================================
# LIMPIAR LÍNEA
# =========================================================

def limpiar_linea(linea):
    linea = linea.replace("```", "").replace("`", "")
    linea = linea.replace('"', "").replace("'", "")
    linea = re.sub(
        r"^(respuesta|response|output|acción|accion|result)[:\s]+",
        "",
        linea,
        flags=re.IGNORECASE
    )
    linea = re.sub(r"^[\d\.\)\-\*\s]+", "", linea)
    return linea.strip()

# =========================================================
# PARSEAR SALIDA
# =========================================================

def parsear_salida(salida, ultima_app):
    acciones = []

    for linea in salida.splitlines():
        linea = limpiar_linea(linea)

        if not linea or "|" not in linea:
            continue

        try:
            intent, valor = linea.split("|", 1)
            intent = intent.strip().lower()
            valor  = valor.strip().lower()

            intent = NORMALIZAR_INTENT.get(intent, intent)

            if intent not in ACCIONES_VALIDAS:
                print(f"[IA] Intent ignorado: {intent}")
                continue

            if valor in ("ultima_app", "{ultima_app}", "last_app", ""):
                valor = ultima_app

            if not valor:
                continue

            acciones.append((intent, valor))

        except Exception as e:
            print("Error parseando línea:", e)

    return acciones

# =========================================================
# INTERPRETAR CON IA
# =========================================================

def interpretar_con_ia(texto):

    ultima_app    = memoria.get("ultima_app",    "")
    ultima_accion = memoria.get("ultima_accion", "")

    prompt = f"""You are a command parser. Convert the user command to actions.
Reply ONLY with the format below. No explanations. No extra text.

Format:
action|value

Allowed actions:
abrir_app          → open an app or game
cerrar_app         → close an app or game
buscar_google      → search on Google
abrir_youtube      → search on YouTube
abrir_url          → open a URL
activar_startup    → enable autostart with Windows
desactivar_startup → disable autostart with Windows
estado_startup     → check if autostart is enabled
recapturar_app     → re-register app processes
eliminar_alias     → forget/delete an alias
minimizar_app      → minimize an app (send to taskbar)
maximizar_app      → bring an app to front / restore it
media_pausar       → pause music or video
media_reanudar     → resume/play music or video
media_siguiente    → next track or video
media_anterior     → previous track or video
media_subir_volumen → increase system volume
media_bajar_volumen → decrease system volume
media_silenciar    → mute or unmute system volume
media_volumen_exacto → set volume to exact percentage (e.g. 50, 70)
registrar_alias    → register new aliases for an app interactively
terminar_sesion    → the user is saying goodbye, has nothing else to ask,
                      or wants to end the conversation (in ANY phrasing,
                      not just literal "goodbye" — infer it from intent,
                      e.g. "that would be all", "I'm good, thanks",
                      "see you later", "nope, nothing else")

Context:
last_app: {ultima_app}
last_action: {ultima_accion}

Examples:
abre discord → abrir_app|discord
cierra opera → cerrar_app|opera
busca gatos → buscar_google|gatos
videos de gatos en youtube → abrir_youtube|gatos
abre twitch.tv → abrir_url|twitch.tv
activa inicio automático → activar_startup|startup
ciérralo → cerrar_app|{ultima_app or "app"}
ábrelo → abrir_app|{ultima_app or "app"}
vuelve a registrar cs2 → recapturar_app|cs2
olvida el alias osu → eliminar_alias|osu
minimiza el discord → minimizar_app|discord
minimízalo → minimizar_app|{ultima_app or "app"}
trae el chrome → maximizar_app|chrome
muestra el opera → maximizar_app|opera
pausa → media_pausar|media
pausa spotify → media_pausar|spotify
pausa youtube → media_pausar|youtube
reanuda → media_reanudar|media
reanuda spotify → media_reanudar|spotify
siguiente → media_siguiente|media
siguiente en spotify → media_siguiente|spotify
canción anterior → media_anterior|media
anterior en youtube → media_anterior|youtube
sube el volumen → media_subir_volumen|media
baja el volumen → media_bajar_volumen|media
silencia → media_silenciar|media
quita el silencio → media_silenciar|media
volumen al 50 → media_volumen_exacto|50
pon el volumen a 70 → media_volumen_exacto|70
volumen de spotify al 70 → media_volumen_exacto|spotify 70
sube el volumen de discord al 30 → media_volumen_exacto|discord 30
registra alias → registrar_alias|alias
asigna alias → registrar_alias|alias
no, nada más → terminar_sesion|sesion
no, gracias → terminar_sesion|sesion
ya quedé así → terminar_sesion|sesion
eso sería todo → terminar_sesion|sesion
no necesito nada más → terminar_sesion|sesion
nos vemos → terminar_sesion|sesion
ya está bien, gracias → terminar_sesion|sesion
con eso está → terminar_sesion|sesion

If you don't recognize any action reply exactly: ninguna

User: {texto}"""

    salida = _llamar_ollama(prompt, timeout=12, num_predict=20, temperature=0.1)

    # FIX: None significa "no se pudo consultar a la IA" (timeout o
    # error) — distinto de [] que significa "la IA respondió pero no
    # encontró ninguna acción". main.py necesita la diferencia para
    # no intentar una segunda llamada a Ollama (la charla libre) si
    # la GPU ya está saturada, porque solo agregaría otra espera larga.
    if salida is None:
        return None

    salida = salida.lower()
    print("IA cruda:", salida)

    if not salida or salida.strip() == "ninguna":
        return []

    return parsear_salida(salida, ultima_app)

# =========================================================
# CHARLA LIBRE (fallback conversacional)
# Se usa cuando ni las reglas de intents.py ni la extracción
# de acciones de arriba encontraron algo ejecutable. En vez de
# responder siempre "no entendí", el asistente le pide al
# modelo una respuesta corta y natural, como lo haría alguien
# real. Esto es lo que lo hace sentir "vivo" en vez de un
# parser de comandos.
# =========================================================

def responder_charla(texto):

    ultima_app = memoria.get("ultima_app", "")

    prompt = f"""Eres Jarvis, el asistente de voz de un computador. Hablas en
español, de forma natural y cercana, como alguien real conversando, no como
un narrador ni un robot que lee instrucciones.

Reglas:
- Máximo 1 o 2 frases cortas, pensadas para decirse en voz alta (esto se
  convierte directamente en audio).
- Si el usuario solo está saludando, charlando, agradeciendo o haciendo una
  pregunta general, respóndele de forma natural y breve.
- Si el comando suena a una orden pero está incompleta o ambigua (por
  ejemplo no dice qué app abrir, o dice "ábrelo" sin que haya una app
  reciente), pregúntale qué quiere específicamente.
- No uses listas, ni emojis, ni formato markdown, ni comillas.

Contexto: la última app que el usuario usó fue "{ultima_app or 'ninguna'}".

Usuario: {texto}
Jarvis:"""

    salida = _llamar_ollama(prompt, timeout=10, num_predict=60, temperature=0.6)
    return salida or None