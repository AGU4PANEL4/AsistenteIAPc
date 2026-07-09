import ollama
import re
import concurrent.futures
from memory import memoria
from config import MODELO_OLLAMA
from logger import log
from gestor_ia import motor_a_usar
from groq_cliente import llamar_groq

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


def _llamar_ollama_directo(prompt, timeout=12, num_predict=40, temperature=0.2):
    """
    Llama específicamente a Ollama local, sin pasar por el router
    del modo híbrido — usada como respaldo cuando Groq falla, y
    directamente cuando no hay internet (ver _llamar_ollama más
    abajo, que es el punto de entrada real usado por el resto de
    ia.py).
    """

    def _tarea():
        return _cliente_ollama.chat(
            model=MODELO_OLLAMA,
            messages=[{"role": "user", "content": prompt}],
            options={
                "num_predict": num_predict,
                "temperature": temperature,
            },
            keep_alive="10m",
        )

    futuro = _executor_ia.submit(_tarea)

    try:
        respuesta = futuro.result(timeout=timeout)
        return respuesta["message"]["content"].strip()

    except concurrent.futures.TimeoutError:
        print(f"[IA] Ollama tardó más de {timeout}s, se cancela la espera "
              f"(¿hay un juego usando la GPU en este momento?)")
        log.warning(f"Ollama tardó más de {timeout}s, se canceló la espera")
        return None

    except Exception as e:
        print("[IA] Error llamando a Ollama:", e)
        log.exception("Error llamando a Ollama")
        return None


def _llamar_ollama(prompt, timeout=12, num_predict=40, temperature=0.2):
    """
    Punto de entrada único para llamar a la IA — pese al nombre
    (que se mantiene por compatibilidad con el resto de ia.py, que
    ya llama a esta función en varios lugares), ahora decide
    INTERNAMENTE si usar Groq (con internet) u Ollama (sin internet)
    según el modo híbrido (ver gestor_ia.py).

    Devuelve el texto de la respuesta, o None si ambos motores
    fallaron o tardaron demasiado.

    NUEVO/HÍBRIDO: con internet se prueba Groq primero — es gratis,
    rápido, y no consume nada de la GPU local (a diferencia de
    Ollama, que además tenía un bug real de GPU sostenida, ver el
    historial de comentarios más abajo). Si Groq falla por cualquier
    motivo puntual (límite de cuota agotado, error de red, etc.) se
    cae a Ollama local automáticamente en esa misma llamada, en vez
    de simplemente fallar — el usuario nunca se queda sin respuesta
    solo porque la nube tuvo un problema momentáneo.

    Sin internet, se usa Ollama directo, igual que siempre funcionó.

    --- HISTORIAL DE FIXES DE TIMING/RECURSOS (contexto importante) ---

    FIX: el "se está demorando mucho" que aparecía SIN relación con
    juegos ni carga de GPU, en cualquier momento, sin patrón claro,
    no era un problema de timeout mal calibrado — era el
    comportamiento POR DEFECTO de Ollama: descarga el modelo de
    memoria tras 5 minutos sin uso. Como el asistente se usa con
    pausas naturales entre comandos, es fácil superar esos 5 minutos
    sin darse cuenta, y la SIGUIENTE petición paga el costo completo
    de recargar el modelo.

    FIX/V2: keep_alive=-1 (modelo cargado para SIEMPRE) eliminaba el
    costo de recarga, pero el proceso de Ollama (llama-server) se
    quedaba consumiendo 40-70% de GPU de forma SOSTENIDA incluso en
    reposo total — un bug real y reportado de Ollama, no el
    comportamiento esperado de keep_alive. Se mitigó bajando a
    keep_alive="10m" (finito, no infinito) en _llamar_ollama_directo.

    FIX/V3 (este cambio): la mitigación del V2 seguía dejando la GPU
    ocupada mientras el modelo estuviera cargado dentro de esos 10
    minutos. La solución real es no necesitar Ollama en absoluto
    mientras haya internet — de ahí el modo híbrido completo.
    """

    motor = motor_a_usar()

    if motor == "groq":
        respuesta = llamar_groq(prompt, timeout=8, num_predict=num_predict, temperature=temperature)
        if respuesta is not None:
            return respuesta

        # Groq falló (cuota, red puntual, etc.) — se cae a Ollama
        # local como respaldo en esta misma llamada, encendiéndolo
        # si no estaba corriendo (estaría apagado porque había
        # internet hace un momento).
        log.warning("Groq falló, cayendo a Ollama local como respaldo")
        from verificacion import iniciar_ollama
        iniciar_ollama()

    return _llamar_ollama_directo(prompt, timeout=timeout, num_predict=num_predict, temperature=temperature)

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
    "crear_recordatorio",
    "listar_recordatorios",
    "cancelar_recordatorio",
    "crear_recordatorio_recurrente",
    "crear_temporizador",
    "listar_temporizadores",
    "cancelar_temporizador",
    # FIX/NUEVO: estas se fueron agregando a TOOLS (tools.py) en
    # distintos momentos, pero nunca se sumaron acá — ACCIONES_VALIDAS
    # y el prompt de más abajo son la ÚNICA forma en que la IA sabe
    # qué puede hacer, así que cualquier cosa faltante acá es
    # invisible para la IA aunque exista en el asistente. En la
    # práctica esto no se notaba porque todas estas ya tienen sus
    # propias reglas rápidas en intents.py que las atrapan ANTES de
    # llegar a la IA — pero si alguna vez se le pide alguna con una
    # frase que esas reglas no reconocen, la IA fallaba en silencio
    # ("Intent ignorado") en vez de tener la más mínima chance de
    # reconocerla. Mantener esto sincronizado con TOOLS (tools.py)
    # cada vez que se agregue una acción nueva evita que se repita.
    "crear_macro",
    "listar_macros",
    "eliminar_macro",
    "ejecutar_macro",
    "activar_no_molestar",
    "desactivar_no_molestar",
    "estado_no_molestar",
    "buscar_actualizacion",
    "ayuda",
    # NUEVO: a diferencia de las demás, esta acción NUNCA la calcula
    # la IA — solo reconoce que es una conversión y reformula la
    # pregunta a un formato simple. El cálculo real siempre lo hace
    # conversiones.py con matemática pura (ver conversion_accion en
    # acciones_sistema.py) — así, aunque la regla rápida de
    # intents.py no reconozca la frase (por eso llegó hasta acá), la
    # precisión de la cuenta no depende de que la IA sepa aritmética.
    "conversion_unidades",
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
    "create_reminder":     "crear_recordatorio",
    "set_reminder":        "crear_recordatorio",
    "list_reminders":      "listar_recordatorios",
    "show_reminders":      "listar_recordatorios",
    "cancel_reminder":     "cancelar_recordatorio",
    "delete_reminder":     "cancelar_recordatorio",
    "remove_reminder":     "cancelar_recordatorio",
    "set_timer":           "crear_temporizador",
    "create_timer":        "crear_temporizador",
    "start_timer":         "crear_temporizador",
    "list_timers":         "listar_temporizadores",
    "show_timers":         "listar_temporizadores",
    "cancel_timer":        "cancelar_temporizador",
    "stop_timer":          "cancelar_temporizador",
    "delete_timer":        "cancelar_temporizador",
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

            # FIX: la sustitución de valor vacío -> ultima_app está
            # pensada para comandos tipo "ciérralo" (cerrar_app|) que
            # se refieren implícitamente a la última app abierta. Pero
            # para cancelar_temporizador y eliminar_alias, un valor
            # vacío es una respuesta VÁLIDA e intencional:
            # - cancelar_temporizador|: cancela el único activo si solo
            #   hay uno (ver cancelar_por_palabra_clave).
            # - eliminar_alias|: dispara el flujo guiado que PREGUNTA
            #   de qué app eliminar el alias, en vez de necesitar el
            #   nombre ya en el comando (ver eliminar_alias_guiado).
            # Sin esta excepción, "eliminar_alias|" se convertía en
            # "eliminar_alias|discord" (la última app usada), buscando
            # alias de una app que el usuario nunca mencionó.
            INTENTS_VALOR_VACIO_VALIDO = {"cancelar_temporizador", "eliminar_alias"}

            if intent in INTENTS_VALOR_VACIO_VALIDO:
                pass
            elif valor in ("ultima_app", "{ultima_app}", "last_app", ""):
                valor = ultima_app

            # FIX: este descarte de "valor vacío" es correcto para
            # casi todos los intents (un comando sin valor no tiene
            # sentido, ej: abrir_app sin saber qué app). Pero
            # cancelar_temporizador es la excepción: un valor vacío
            # ahí significa "cancela el timer sin nombre específico",
            # que es una intención completamente válida.
            if not valor and intent not in INTENTS_VALOR_VACIO_VALIDO:
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
eliminar_alias     → start a guided flow to forget/delete an alias.
                      value is the name of the APP if the user already
                      said it (e.g. "brawlhalla"), or empty string if
                      they didn't name one yet — the flow itself asks
                      and shows existing aliases to choose from, so
                      you don't need the exact alias text here
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
crear_recordatorio → create a reminder for later. value format is
                      "when|what" — exactly one "|" separating the
                      time (relative like "10 minutos"/"1 hora", or
                      exact like "15:30"/"3 pm"/"4 y media"/"450") from
                      what to be reminded of, in Spanish, as the user
                      said it. If the user gave a clear time but did
                      NOT say what to be reminded of, leave the part
                      after "|" EMPTY (e.g. "4 y media|") instead of
                      inventing something — the assistant will ask
                      the user for a name afterwards
listar_recordatorios → list the user's pending reminders
cancelar_recordatorio → cancel a reminder. value is the keyword(s)
                      identifying WHICH reminder, in Spanish, taken
                      from what the user said (e.g. "la pizza", "mamá")
crear_temporizador → start a countdown timer (NOT a reminder for a
                      specific time/date — only relative durations).
                      value format is "duration|name" — exactly one
                      "|" separating the duration ("10 minutos",
                      "1 hora 30 minutos") from an OPTIONAL name
                      ("pasta", "ejercicio"). If the user gave no
                      name, leave it empty after the "|" (e.g.
                      "10 minutos|")
listar_temporizadores → list the user's active timers and how much
                      time is left on each
cancelar_temporizador → cancel a timer. value is the keyword(s)
                      identifying WHICH timer (its name, e.g. "pasta"),
                      or empty string if the user didn't name one and
                      just said "cancel the timer"
crear_macro        → start a guided flow to record a new macro (a
                      saved sequence of actions run with one command).
                      value is the macro name if the user already
                      said it, or empty string otherwise
listar_macros      → list the user's saved macros
eliminar_macro     → delete a saved macro. value is the macro name if
                      the user said it, or empty string otherwise
ejecutar_macro     → run a macro the user already saved by name.
                      value is that macro's name, in Spanish, as the
                      user said it (e.g. "modo juego")
activar_no_molestar → silence reminder/timer announcements for a
                      while. value is the number of minutes as a
                      plain integer (e.g. "30" for half an hour,
                      default to "60" if the user didn't say a
                      duration)
desactivar_no_molestar → turn do-not-disturb mode off early
estado_no_molestar → check whether do-not-disturb mode is on and how
                      much time is left
buscar_actualizacion → check right now if there's a new version of
                      the assistant available
ayuda              → the user is asking what the assistant can do, or
                      how to use it (e.g. "what can you do?", "help")
conversion_unidades → the user is asking to convert a measurement
                      from one unit to another. Only these units are
                      supported — milímetros/centímetros/metros/
                      kilómetros (length), miligramos/gramos/
                      kilogramos (weight), mililitros/litros
                      (volume), celsius/fahrenheit (temperature). DO
                      NOT calculate the answer yourself and DO NOT
                      use any other unit (no libras, millas, pies,
                      etc — if the user asks for one of those, reply
                      "ninguna" instead). value must be the
                      conversion REPHRASED simply in Spanish as
                      "<number> <unit> a <unit>", e.g. "5 kilometros
                      a metros" or "20 celsius a fahrenheit"
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
olvida el alias de brawlhalla → eliminar_alias|brawlhalla
quiero eliminar un alias → eliminar_alias|
elimina un alias → eliminar_alias|
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
recuérdame en 10 minutos que saque la pizza → crear_recordatorio|10 minutos|saque la pizza
acuérdame en media hora de llamar a mamá → crear_recordatorio|30 minutos|llamar a mamá
avísame a las 3 pm que tengo reunión → crear_recordatorio|3 pm|tengo reunión
crea un recordatorio para las 4 y media → crear_recordatorio|4 y media|
ponme un recordatorio a las 450 → crear_recordatorio|450|
ponme un recordatorio para las 15:30 de revisar el horno → crear_recordatorio|15:30|revisar el horno
qué tengo pendiente de recordar → listar_recordatorios|recordatorios
tengo algún recordatorio activo → listar_recordatorios|recordatorios
ya no me recuerdes lo de la pizza → cancelar_recordatorio|la pizza
quita el recordatorio que puse de mamá → cancelar_recordatorio|mamá
pon un timer de 10 minutos → crear_temporizador|10 minutos|
pon un timer de pasta a 15 minutos → crear_temporizador|15 minutos|pasta
necesito un cronómetro de 5 minutos para el café → crear_temporizador|5 minutos|el café
cuánto le queda al timer → listar_temporizadores|temporizadores
cancela el timer → cancelar_temporizador|
cancela el timer de pasta → cancelar_temporizador|pasta
crea una macro → crear_macro|
crea una macro modo juego → crear_macro|modo juego
qué macros tengo → listar_macros|macros
elimina la macro modo juego → eliminar_macro|modo juego
ejecuta modo juego → ejecutar_macro|modo juego
activa el modo no molestar → activar_no_molestar|60
no me molestes por 30 minutos → activar_no_molestar|30
silencio por una hora → activar_no_molestar|60
desactiva el no molestar → desactivar_no_molestar|
quítame el no molestar → desactivar_no_molestar|
está activo el no molestar → estado_no_molestar|
busca actualizaciones → buscar_actualizacion|
hay alguna actualización → buscar_actualizacion|
qué puedes hacer → ayuda|
ayúdame → ayuda|
a cuántos metros equivalen 5 kilómetros → conversion_unidades|5 kilometros a metros
cuántos grados fahrenheit son 30 grados → conversion_unidades|30 celsius a fahrenheit
transforma 10 mililitros a litros → conversion_unidades|10 mililitros a litros
no, nada más → terminar_sesion|sesion
no, gracias → terminar_sesion|sesion
ya quedé así → terminar_sesion|sesion
eso sería todo → terminar_sesion|sesion
no necesito nada más → terminar_sesion|sesion
nos vemos → terminar_sesion|sesion
ya está bien, gracias → terminar_sesion|sesion
con eso está → terminar_sesion|sesion

Questions and general knowledge are NOT actions — reply "ninguna" for
those, even if they mention a number or a word that looks like a command:
cuánto es 47 por 12 → ninguna
cuál es la capital de Japón → ninguna
qué hora es → ninguna
qué es la fotosíntesis → ninguna

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
# CHARLA LIBRE (fallback conversacional Y preguntas directas)
# Se usa cuando ni las reglas de intents.py ni la extracción
# de acciones de arriba encontraron algo ejecutable. En vez de
# responder siempre "no entendí", el asistente le pide al
# modelo una respuesta corta y natural, como lo haría alguien
# real. Esto es lo que lo hace sentir "vivo" en vez de un
# parser de comandos.
#
# NUEVO: esta MISMA función es también el lugar donde caen las
# preguntas directas ("cuánto es 47 por 12", "cuál es la capital de
# Japón", "qué es la fotosíntesis") — no hizo falta agregar ningún
# mecanismo nuevo para "diferenciar pregunta de acción": ninguna
# pregunta de este tipo matchea ninguna regla de intents.py NI se
# reconoce como una acción en interpretar_con_ia() de más arriba
# (ambos le piden a la IA "ninguna" en esos casos), así que TODA
# pregunta que no sea una acción real termina, sola, exactamente acá
# — la arquitectura ya hacía esa diferenciación de antes, solo hacía
# falta que el prompt de acá supiera responder preguntas de verdad en
# vez de solo saludos.
# =========================================================

def responder_charla(texto):

    ultima_app = memoria.get("ultima_app", "")

    # FIX: antes el prompt SIEMPRE pedía una respuesta conversacional,
    # sin darle al modelo la opción de reconocer que el texto de
    # FIX/V2: la versión anterior de este prompt, con la estructura
    # "SI tiene sentido / SI NO tiene sentido" en mayúsculas, terminó
    # siendo literalmente REPETIDA por el modelo como si fuera su
    # respuesta — un usuario reportó que Jarvis dijo en voz alta
    # "SI NO tiene sentido", una frase sacada directo del prompt. Un
    # modelo de 3B parámetros puede "engancharse" con texto que tiene
    # forma de lista/instrucción y copiarlo en vez de seguirlo,
    # especialmente si el prompt es largo.
    #
    # Esta versión es más corta y usa EJEMPLOS concretos de
    # entrada->salida en vez de explicar la regla de forma abstracta
    # — los modelos chicos siguen mejor patrones de ejemplo que
    # instrucciones condicionales largas, y hay mucho menos texto
    # "con forma de regla" que el modelo pueda confundir con
    # contenido a repetir.
    #
    # NUEVO: se agregaron ejemplos de preguntas directas (cálculo,
    # capital, fecha, definición corta) junto a los de charla — por
    # el mismo motivo que el resto del prompt: mostrar con ejemplos
    # en vez de explicar con reglas. "Respondé DIRECTO" + los
    # ejemplos evita que el modelo se ponga a explicar el
    # razonamiento paso a paso (lo cual sonaría larguísimo dicho en
    # voz alta) — para un asistente de VOZ, "47 por 12 es 564" es lo
    # que hace falta, no el desarrollo de la cuenta.
    prompt = f"""Eres Jarvis, un asistente de voz que habla español de forma
natural, como una persona real, no como un narrador.

El texto del usuario viene de un reconocedor de voz que a veces transcribe
mal — puede llegar como palabras sueltas sin sentido. Si pasa eso, dile
brevemente que no entendió y que repita.

Si te hacen una pregunta real (una cuenta, un dato, una fecha, una
definición corta, algo que quieran saber), respondé la respuesta DIRECTO,
sin explicar el razonamiento ni dar vueltas — la persona quiere el dato,
no una clase. Si no sabés la respuesta con certeza, decilo en vez de
inventar algo.

Si es un saludo o charla informal, respondé normal y natural.

Ejemplos:
usuario: hola jarvis -> jarvis: hola, ¿en qué te ayudo?
usuario: ya debes -> jarvis: no te escuché bien, ¿puedes repetir?
usuario: namas -> jarvis: no entendí eso, dime otra vez
usuario: gracias -> jarvis: de nada, aquí estoy si necesitas algo más
usuario: ábrelo -> jarvis: ¿qué app quieres abrir?
usuario: cuánto es 47 por 12 -> jarvis: 47 por 12 es 564
usuario: cuánto es 200 dividido 8 -> jarvis: 200 dividido 8 es 25
usuario: cuál es la capital de Japón -> jarvis: la capital de Japón es Tokio
usuario: en qué año cayó el muro de Berlín -> jarvis: en 1989
usuario: qué es la fotosíntesis -> jarvis: es el proceso con el que las plantas convierten luz solar en energía

Responde en máximo 1 o 2 frases cortas, sin listas, sin emojis, sin
comillas, sin markdown.

Contexto: la última app que el usuario usó fue "{ultima_app or 'ninguna'}".

Usuario: {texto}
Jarvis:"""

    # NUEVO: temperature bajó de 0.45 a 0.35 — un poco menos de
    # libertad creativa que antes, a propósito: ahora esta función
    # también responde cálculos y datos, donde la prioridad es
    # precisión antes que variedad conversacional. Sigue siendo lo
    # bastante alto para no sonar robótico en saludos/charla normal.
    # num_predict subió de 60 a 90 — algunas respuestas factuales
    # cortas (ej. una definición de una frase) no entraban cómodas en
    # 60 tokens y se cortaban a mitad de frase; 90 da margen sin
    # dejar de ser "corto" para una respuesta de voz.
    salida = _llamar_ollama(prompt, timeout=10, num_predict=90, temperature=0.35)
    return salida or None