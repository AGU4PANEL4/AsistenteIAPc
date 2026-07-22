import ollama
import re
import concurrent.futures
import hashlib
import time
from config import MODELO_OLLAMA
from logger import log
from gestor_ia import motor_a_usar
from groq_cliente import llamar_groq

# =========================================================
# CACHE DE INTENTS
# =========================================================

_CACHE_INTENTS = {}
_CACHE_TTL_SEGUNDOS = 300
_CACHE_MAX_ENTRADAS = 50


def _cache_key(texto):
    normalizado = texto.lower().strip()
    normalizado = re.sub(r"\b(el|la|los|las|un|una|por favor|pls)\b", "", normalizado)
    normalizado = re.sub(r"\s+", " ", normalizado).strip()
    return hashlib.md5(normalizado.encode()).hexdigest()[:16]


def _obtener_cache(texto):
    clave = _cache_key(texto)
    entrada = _CACHE_INTENTS.get(clave)
    if entrada and (time.time() - entrada["ts"]) < _CACHE_TTL_SEGUNDOS:
        print(f"[IA] Cache hit: {texto!r}")
        return entrada["acciones"]
    return None


def _guardar_cache(texto, acciones):
    clave = _cache_key(texto)
    if len(_CACHE_INTENTS) >= _CACHE_MAX_ENTRADAS:
        mas_vieja = min(_CACHE_INTENTS, key=lambda k: _CACHE_INTENTS[k]["ts"])
        del _CACHE_INTENTS[mas_vieja]
    _CACHE_INTENTS[clave] = {"acciones": acciones, "ts": time.time()}


# =========================================================
# CLIENTE OLLAMA CON TIMEOUT
# =========================================================

_cliente_ollama = ollama.Client(timeout=15)
_executor_ia    = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def _llamar_ollama_directo(prompt, timeout=12, num_predict=40, temperature=0.2):
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
        print(f"[IA] Ollama tardó más de {timeout}s, se cancela la espera")
        log.warning(f"Ollama tardó más de {timeout}s, se canceló la espera")
        return None
    except Exception as e:
        print("[IA] Error llamando a Ollama:", e)
        log.exception("Error llamando a Ollama")
        return None


def _llamar_ollama(prompt, timeout=12, num_predict=40, temperature=0.2):
    motor = motor_a_usar()

    if motor == "groq":
        respuesta = llamar_groq(prompt, timeout=8, num_predict=num_predict, temperature=temperature)
        if respuesta is not None:
            return respuesta
        log.warning("Groq falló, cayendo a Ollama local como respaldo")
        from gestor_ia import forzar_ollama_como_respaldo
        forzar_ollama_como_respaldo()

    return _llamar_ollama_directo(prompt, timeout=timeout, num_predict=num_predict, temperature=temperature)


# =========================================================
# ACCIONES VÁLIDAS
# =========================================================

ACCIONES_VALIDAS = {
    "abrir_app", "cerrar_app", "buscar_google", "abrir_youtube", "abrir_url",
    "activar_startup", "desactivar_startup", "estado_startup", "recapturar_app",
    "eliminar_alias", "minimizar_app", "maximizar_app",
    "media_pausar", "media_reanudar", "media_siguiente", "media_anterior",
    "media_subir_volumen", "media_bajar_volumen", "media_silenciar", "media_volumen_exacto",
    "registrar_alias", "terminar_sesion",
    "crear_recordatorio", "listar_recordatorios", "cancelar_recordatorio", "crear_recordatorio_recurrente",
    "crear_temporizador", "listar_temporizadores", "cancelar_temporizador",
    "crear_macro", "listar_macros", "eliminar_macro", "ejecutar_macro",
    "activar_no_molestar", "desactivar_no_molestar", "estado_no_molestar",
    "buscar_actualizacion", "ayuda", "conversion_unidades",
}

NORMALIZAR_INTENT = {
    "open_app": "abrir_app", "close_app": "cerrar_app",
    "search_google": "buscar_google", "open_youtube": "abrir_youtube",
    "search_youtube": "abrir_youtube", "open_url": "abrir_url",
    "activate_startup": "activar_startup", "deactivate_startup": "desactivar_startup",
    "startup_status": "estado_startup", "recapture_app": "recapturar_app",
    "activar_inicio": "activar_startup", "desactivar_inicio": "desactivar_startup",
    "estado_inicio": "estado_startup", "minimize_app": "minimizar_app",
    "maximize_app": "maximizar_app", "bring_to_front": "maximizar_app",
    "show_app": "maximizar_app", "hide_app": "minimizar_app",
    "pause_media": "media_pausar", "play_media": "media_reanudar",
    "resume_media": "media_reanudar", "next_track": "media_siguiente",
    "prev_track": "media_anterior", "previous_track": "media_anterior",
    "volume_up": "media_subir_volumen", "volume_down": "media_bajar_volumen",
    "mute": "media_silenciar", "unmute": "media_silenciar",
    "set_volume": "media_volumen_exacto", "volume_set": "media_volumen_exacto",
    "register_alias": "registrar_alias", "create_reminder": "crear_recordatorio",
    "set_reminder": "crear_recordatorio", "list_reminders": "listar_recordatorios",
    "show_reminders": "listar_recordatorios", "cancel_reminder": "cancelar_recordatorio",
    "delete_reminder": "cancelar_recordatorio", "remove_reminder": "cancelar_recordatorio",
    "set_timer": "crear_temporizador", "create_timer": "crear_temporizador",
    "start_timer": "crear_temporizador", "list_timers": "listar_temporizadores",
    "show_timers": "listar_temporizadores", "cancel_timer": "cancelar_temporizador",
    "stop_timer": "cancelar_temporizador", "delete_timer": "cancelar_temporizador",
    "end_session": "terminar_sesion", "end_conversation": "terminar_sesion",
    "stop_session": "terminar_sesion", "goodbye": "terminar_sesion",
    "say_goodbye": "terminar_sesion", "finish": "terminar_sesion", "exit": "terminar_sesion",
}


# =========================================================
# LIMPIAR LÍNEA + PARSEAR
# =========================================================

def limpiar_linea(linea):
    linea = linea.replace("```", "").replace("`", "")
    linea = linea.replace('"', "").replace("'", "")
    linea = re.sub(
        r"^(respuesta|response|output|acción|accion|result)[:\s]+",
        "", linea, flags=re.IGNORECASE
    )
    linea = re.sub(r"^[\d\.\)\-\*\s]+", "", linea)
    return linea.strip()


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
            INTENTS_VALOR_VACIO_VALIDO = {"cancelar_temporizador", "eliminar_alias"}
            if intent in INTENTS_VALOR_VACIO_VALIDO:
                pass
            elif valor in ("ultima_app", "{ultima_app}", "last_app", ""):
                valor = ultima_app
            if not valor and intent not in INTENTS_VALOR_VACIO_VALIDO:
                continue
            acciones.append((intent, valor))
        except Exception as e:
            print("Error parseando línea:", e)
    return acciones


# =========================================================
# CONTEXTO DE MEMORIA
# =========================================================

def _construir_contexto_memoria():
    from memory import obtener_conversacion, obtener_hechos, CONVERSACION_MAX
    partes = []
    turnos = obtener_conversacion(ultimos_n=4)
    if turnos:
        partes.append("Conversación reciente:")
        for t in turnos:
            rol = "Usuario" if t["rol"] == "usuario" else "Asistente"
            partes.append(f"  {rol}: {t['mensaje']}")
        partes.append("")
    hechos = obtener_hechos()
    if hechos:
        partes.append("Datos sobre el usuario:")
        for k, v in hechos.items():
            partes.append(f"  - {k}: {v}")
        partes.append("")
    return "\n".join(partes) if partes else ""


# =========================================================
# INTERPRETAR CON IA — CON CACHE Y PROMPT CORTO
# =========================================================

def interpretar_con_ia(texto):
    cacheado = _obtener_cache(texto)
    if cacheado is not None:
        return cacheado

    from memory import memoria
    ultima_app    = memoria.get("ultima_app",    "")
    ultima_accion = memoria.get("ultima_accion", "")
    contexto_memoria = _construir_contexto_memoria()

    prompt = f"""Eres un parser de comandos en español.
Responde SOLO con líneas action|value. Una acción por línea.

Acciones:
abrir_app|app           abrir_url|url           media_pausar|
cerrar_app|app          activar_startup|       media_reanudar|
buscar_google|q         desactivar_startup|     media_siguiente|
abrir_youtube|q         estado_startup|        media_anterior|
recapturar_app|app      eliminar_alias|app      media_subir_volumen|
minimizar_app|app       registrar_alias|        media_bajar_volumen|
maximizar_app|app       crear_recordatorio|t|d media_silenciar|
                        listar_recordatorios|   media_volumen_exacto|n
                        cancelar_recordatorio|k crear_temporizador|d|n
                        listar_temporizadores|  cancelar_temporizador|n
                        crear_macro|name         listar_macros|
                        eliminar_macro|name      ejecutar_macro|name
                        activar_no_molestar|m    desactivar_no_molestar|
                        estado_no_molestar|      buscar_actualizacion|
                        ayuda|                   conversion_unidades|expr
                        terminar_sesion|

Reglas: "eso"/"eso"/"el otro" → usar contexto. Múltiples → múltiples líneas. Ninguna → ninguna
Recordatorios: "10 minutos" o "15:30". Temporizadores: duración. Volumen: número.

{contexto_memoria}
Última app: {ultima_app or "ninguna"}
Última acción: {ultima_accion or "ninguna"}

Usuario: {texto}"""

    salida = _llamar_ollama(prompt, timeout=10, num_predict=60, temperature=0.15)

    if salida is None:
        return None

    salida = salida.lower()
    print("IA cruda:", salida)

    if not salida or salida.strip() == "ninguna":
        _guardar_cache(texto, [])
        return []

    acciones = parsear_salida(salida, ultima_app)
    _guardar_cache(texto, acciones)
    return acciones


# =========================================================
# CALCULADORA PYTHON
# =========================================================

_PATRON_CALCULO = re.compile(
    r"^(?:cu[áa]nto\s+(?:es|da|son)|(?:calcula|resuelve|cuenta)\s+)?"
    r"([\d\s\+\-\*\/\(\)\.\,]+(?:\s*(?:m[áa]s|menos|por|dividido|entre|al\s+cuadrado|elevado\s+a)\s*[\d\s\+\-\*\/\(\)\.\,]+)*)"
    r"(?:\s*\?)?$",
    re.IGNORECASE
)


def _intentar_calculo_python(texto):
    texto_limpio = texto.lower()
    texto_limpio = texto_limpio.replace("más", "+").replace("mas", "+")
    texto_limpio = texto_limpio.replace("menos", "-")
    texto_limpio = texto_limpio.replace("por", "*")
    texto_limpio = texto_limpio.replace("dividido", "/").replace("entre", "/")
    texto_limpio = texto_limpio.replace("al cuadrado", "**2")
    texto_limpio = texto_limpio.replace("elevado a", "**")
    texto_limpio = texto_limpio.replace(",", ".")
    import re as re_local
    match = re_local.search(r"[\d\+\-\*\/\(\)\.\s]+", texto_limpio)
    if not match:
        return None, False
    expr = match.group().strip()
    if not expr:
        return None, False
    if not all(c in "0123456789+-*/(). " for c in expr):
        return None, False
    try:
        resultado = eval(expr, {"__builtins__": {}}, {})
        if resultado == int(resultado):
            return str(int(resultado)), True
        return f"{resultado:.4f}".rstrip("0").rstrip("."), True
    except Exception:
        return None, False


# =========================================================
# RESPONDER CHARLA
# =========================================================

def responder_charla(texto):
    from memory import memoria, obtener_conversacion, obtener_hechos, CONVERSACION_MAX
    ultima_app = memoria.get("ultima_app", "")

    resultado_calc, es_calculo = _intentar_calculo_python(texto)
    if es_calculo:
        expresion_limpia = texto.lower()
        expresion_limpia = expresion_limpia.replace("cuánto es ", "").replace("cuanto es ", "")
        expresion_limpia = expresion_limpia.replace("calcula ", "").replace("resuelve ", "")
        expresion_limpia = expresion_limpia.strip("?")
        return f"{expresion_limpia} es {resultado_calc}"

    turnos = obtener_conversacion(ultimos_n=CONVERSACION_MAX)
    contexto_conv = ""
    if turnos:
        lineas = []
        for t in turnos:
            rol_label = "usuario" if t["rol"] == "usuario" else "jarvis"
            lineas.append(f"{rol_label}: {t['mensaje']}")
        contexto_conv = "\n".join(lineas)

    hechos = obtener_hechos()
    contexto_hechos = ""
    if hechos:
        partes = [f"    - {k}: {v}" for k, v in hechos.items()]
        contexto_hechos = "\n".join(partes)

    prompt = f"""Eres Jarvis, el asistente personal de un usuario que te habla en español.
No eres un chatbot genérico — eres eficiente, amigable, y tienes un toque de humor seco.
Hablas como una persona real, no como un manual técnico. Tus respuestas son CORTAS
(1-2 frases máximo) porque te comunicás por voz — nadie quiere escuchar un párrafo.

REGLAS DE ESTILO:
- Sé natural: "dale", "listo", "perfecto", "ya está" son válidos.
- No uses emojis, markdown, comillas, ni listas numeradas.
- Si no sabés algo con certeza, admitilo en vez de inventar.
- Si el usuario te saluda, respondé con onda, no con "Hola, soy Jarvis, un asistente..."
- Si el texto del usuario viene mal transcrito (palabras sueltas sin sentido como
  "ya debes", "namas", "jerbys"), decile que no entendiste y que repita — pero
  hacelo con onda, no robótico.

REGLAS DE CIERRE DE CONVERSACIÓN:
- Si tu respuesta es un dato simple de 1-3 palabras (ej: "Tokio", "42", "sí", "de nada"),
  NO agregues ninguna pregunta de cierre. Respondé solo el dato.
- Si tu respuesta es una explicación, chiste, opinión, o tiene más de 5 palabras,
  terminá con UNA SOLA pregunta corta y natural de cierre como:
  "¿Algo más?", "¿Te ayudo en algo más?", "¿Querés que haga algo?", "¿Necesitás algo más?".
  Elegí la que suene más natural según el contexto.
- NUNCA repitas la pregunta de cierre si ya la dijiste en el turno anterior.
- NUNCA uses más de una pregunta de cierre por respuesta.

EJEMPLOS DE TONO:
usuario: hola jarvis → jarvis: hola, ¿qué necesitás?
usuario: gracias → jarvis: de nada
usuario: ya debes → jarvis: no te entendí bien, ¿podés repetirlo?
usuario: cuál es la capital de Japón → jarvis: Tokio
usuario: qué es la fotosíntesis → jarvis: es cómo las plantas hacen comida con luz solar. ¿Algo más?
usuario: contame un chiste → jarvis: ¿por qué los programadores confunden Halloween y Navidad? Porque 31 OCT = 25 DEC. ¿Te ayudo en algo más?
usuario: quién ganó el mundial 2022 → jarvis: Argentina, contra Francia en penales. Partidazo. ¿Querés que haga algo?
"""

    if contexto_hechos:
        prompt += f"""
Datos que sabés sobre el usuario (usalos si vienen al caso, ignorá los que no):
{contexto_hechos}

"""

    if contexto_conv:
        prompt += f"""Conversación reciente:
{contexto_conv}

"""

    prompt += f"""Contexto: la última app que usó fue "{ultima_app or 'ninguna'}".

Usuario: {texto}
Jarvis:"""

    salida = _llamar_ollama(prompt, timeout=10, num_predict=80, temperature=0.5)
    return salida or None