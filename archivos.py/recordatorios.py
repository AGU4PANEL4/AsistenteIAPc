import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from tts import hablar
from tiempo_utils import parsear_duracion
from logger import log

# =========================================================
# ARCHIVO
# Mismo patrón que memory.py / aliases.py: JSON en la carpeta
# de datos del asistente.
# =========================================================

CARPETA_DATOS        = Path(os.environ["LOCALAPPDATA"]) / "AsistenteIA"
ARCHIVO_RECORDATORIOS = CARPETA_DATOS / "recordatorios.json"

# =========================================================
# ESTADO EN MEMORIA
# Cada recordatorio: {"id": int, "momento": "2026-06-19T15:30:00",
#                     "texto": "llamar a mamá"}
# =========================================================

_lock_datos    = threading.Lock()
_recordatorios = {}   # id (str) -> dict
_siguiente_id  = 1

# =========================================================
# CARGAR / GUARDAR
# =========================================================

def _cargar():
    global _recordatorios, _siguiente_id

    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

    if not ARCHIVO_RECORDATORIOS.exists():
        _recordatorios = {}
        _siguiente_id  = 1
        return

    try:
        with open(ARCHIVO_RECORDATORIOS, "r", encoding="utf-8") as f:
            data = json.load(f)

        _recordatorios = data.get("recordatorios", {})
        _siguiente_id  = data.get("siguiente_id", 1)

    except Exception as e:
        print("[Recordatorios] Error cargando, se empieza vacío:", e)
        _recordatorios = {}
        _siguiente_id  = 1


def _guardar():
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

    # FIX: antes el snapshot de `data` se tomaba DENTRO del lock,
    # pero la escritura a disco (open/json.dump) quedaba FUERA — el
    # lock solo protegía la lectura en memoria, no la escritura real.
    # Si dos hilos llamaban a _guardar() casi al mismo tiempo (ej. se
    # crea un recordatorio justo cuando otro se dispara y se borra a
    # sí mismo), podían entrelazarse: hilo A toma snapshot viejo,
    # hilo B toma snapshot nuevo y escribe primero, hilo A escribe
    # después con su snapshot viejo — pisando en disco el cambio que
    # B acababa de guardar, aunque en memoria todo estuviera bien.
    # Si el asistente se cerraba justo en esa ventana, ese cambio se
    # perdía para siempre sin ningún aviso.
    #
    # Ahora la escritura a disco también ocurre DENTRO del lock, así
    # que dos llamadas a _guardar() quedan totalmente serializadas:
    # la segunda siempre escribe un estado que ya incluye lo que la
    # primera guardó, nunca al revés.
    with _lock_datos:
        data = {
            "recordatorios": _recordatorios,
            "siguiente_id":  _siguiente_id,
        }

        try:
            with open(ARCHIVO_RECORDATORIOS, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print("[Recordatorios] Error guardando:", e)
            log.exception("Error guardando recordatorios a disco")

# =========================================================
# PARSEO DE TIEMPO
# Acepta dos formatos en el valor que llega del intent:
#
#   RELATIVO:    "10 minutos", "2 horas", "1 hora 30 minutos"
#   HORA EXACTA: "15:30", "3:00 pm", "3 pm", "15"
#
# La parte RELATIVA usa parsear_duracion() de tiempo_utils.py
# (compartida con temporizadores.py). La HORA EXACTA es específica
# de recordatorios — un temporizador no tiene sentido "a las 3pm".
#
# Devuelve un datetime en el futuro, o None si no se pudo
# interpretar.
# =========================================================


# =========================================================
# NÚMEROS EN PALABRAS → DÍGITOS
# NUEVO: necesario para reconocer horas dichas completamente en
# palabras ("cuatro y cincuenta", "las tres y media") — antes el
# parser solo entendía dígitos.
# =========================================================

_NUMEROS_PALABRA = {
    "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
    "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10,
    "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciséis": 16, "dieciseis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiuno": 21, "veintidós": 22, "veintidos": 22,
    "veintitrés": 23, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiséis": 26, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29,
    "treinta": 30, "cuarenta": 40, "cincuenta": 50,
}


def _normalizar_numeros_palabra(texto):
    """
    Reemplaza números escritos en palabras por sus dígitos
    equivalentes, dentro del texto — ej: "cuatro y cincuenta" se
    convierte en "4 y 50" antes de aplicar el resto de los patrones,
    así no hace falta duplicar toda la lógica de parseo para
    palabras vs dígitos.
    """
    palabras = texto.split()
    resultado = []
    for palabra in palabras:
        # se compara sin signos de puntuación pegados (ej "cuatro,")
        clave = palabra.strip(",.;:")
        if clave in _NUMEROS_PALABRA:
            resultado.append(str(_NUMEROS_PALABRA[clave]))
        else:
            resultado.append(palabra)
    return " ".join(resultado)


def _parsear_hora_exacta(texto):
    """
    Busca patrones de hora exacta en español, en este orden:

      1. "faltando/faltan X para las Y" → Y menos X minutos
         ej: "faltando 15 para las 4" → 3:45
             "10 para las 5" → 4:50
      2. HH:MM o "H y MM" con am/pm opcional
         ej: "15:30", "3:30 pm", "4 y 50", "450"
      3. Fracciones comunes: "y media" (30), "y cuarto" (15)
         ej: "4 y media" → 4:30, "4 y cuarto" → 4:15
      4. Solo hora con am/pm/de la tarde/etc
         ej: "3 pm", "7 am", "3 de la tarde"

    Devuelve (hora, minuto) en formato 24h, o None si no encontró
    nada reconocible.
    """
    texto = _normalizar_numeros_palabra(texto)

    # 1. "faltando/faltan X (minutos) para las Y" — la hora en punto
    # mencionada es la SIGUIENTE, y se resta X minutos de esa hora.
    match = re.search(
        r"(?:faltando|faltan)?\s*(\d{1,2})\s*(?:minutos?)?\s*pa(?:ra)?\s*las?\s*(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.|de la tarde|de la noche|de la mañana)?",
        texto
    )
    if match:
        minutos_faltantes = int(match.group(1))
        hora_objetivo      = int(match.group(2))
        sufijo             = (match.group(3) or "").replace(".", "")

        es_pm = sufijo in ("pm", "de la tarde", "de la noche")
        es_am = sufijo in ("am", "de la mañana")

        if es_pm and hora_objetivo < 12:
            hora_objetivo += 12
        elif es_am and hora_objetivo == 12:
            hora_objetivo = 0

        if 0 <= hora_objetivo <= 23 and 0 <= minutos_faltantes < 60:
            # restar los minutos faltantes de la hora objetivo,
            # usando un datetime de referencia neutro para que el
            # cálculo de "hora menos minutos" maneje bien el
            # cruce de hora (ej. "10 para las 5" -> 4:50)
            referencia = datetime(2000, 1, 1, hora_objetivo, 0)
            resultado  = referencia - timedelta(minutes=minutos_faltantes)
            return resultado.hour, resultado.minute

    # 2. HH:MM, o "H y MM" (con "y" en vez de ":"), con am/pm opcional
    # ej: "15:30", "3:30 pm", "4 y 50", "4 y 50 de la tarde"
    match = re.search(
        r"(\d{1,2})\s*(?::|y)\s*(\d{2})\s*(am|pm|a\.m\.|p\.m\.|de la tarde|de la noche|de la mañana)?",
        texto
    )
    if match:
        hora   = int(match.group(1))
        minuto = int(match.group(2))
        sufijo = (match.group(3) or "").replace(".", "")

        es_pm = sufijo in ("pm", "de la tarde", "de la noche")
        es_am = sufijo in ("am", "de la mañana")

        if es_pm and hora < 12:
            hora += 12
        elif es_am and hora == 12:
            hora = 0

        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            return hora, minuto

    # 2b. "HHMM" pegado sin separador, ej "450" → 4:50, "1630" → 16:30
    # Solo se interpreta así si el número tiene exactamente 3 o 4
    # cifras Y los dos últimos dígitos son un minuto válido (<60) —
    # esto evita interpretar mal otros números de 3-4 cifras que
    # aparezcan en el texto por otro motivo.
    match = re.search(r"\b(\d{3,4})\b", texto)
    if match:
        digitos = match.group(1)
        if len(digitos) == 3:
            hora, minuto = int(digitos[0]), int(digitos[1:])
        else:
            hora, minuto = int(digitos[:2]), int(digitos[2:])

        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            return hora, minuto

    # 3. Fracciones comunes: "H y media" (30), "H y cuarto" (15)
    match = re.search(
        r"(\d{1,2})\s*y\s*(media|cuarto)\s*(am|pm|a\.m\.|p\.m\.|de la tarde|de la noche|de la mañana)?",
        texto
    )
    if match:
        hora     = int(match.group(1))
        fraccion = match.group(2)
        sufijo   = (match.group(3) or "").replace(".", "")

        minuto = 30 if fraccion == "media" else 15

        es_pm = sufijo in ("pm", "de la tarde", "de la noche")
        es_am = sufijo in ("am", "de la mañana")

        if es_pm and hora < 12:
            hora += 12
        elif es_am and hora == 12:
            hora = 0

        if 0 <= hora <= 23:
            return hora, minuto

    # 4. Solo hora, con am/pm → "3 pm", "7 am", "3 de la tarde"
    match = re.search(
        r"\b(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.|de la tarde|de la noche|de la mañana)\b",
        texto
    )
    if match:
        hora   = int(match.group(1))
        sufijo = match.group(2).replace(".", "")

        es_pm = sufijo in ("pm", "de la tarde", "de la noche")
        es_am = sufijo in ("am", "de la mañana")

        if es_pm and hora < 12:
            hora += 12
        elif es_am and hora == 12:
            hora = 0

        if 0 <= hora <= 23:
            return hora, 0

    return None


def calcular_momento(texto):
    """
    Convierte el texto del recordatorio (lo que dijo el usuario sobre
    CUÁNDO) en un datetime futuro. Devuelve None si no se entendió.
    """
    texto = texto.lower().strip()

    segundos = parsear_duracion(texto)
    if segundos:
        return datetime.now() + timedelta(seconds=segundos)

    hora_exacta = _parsear_hora_exacta(texto)
    if hora_exacta:
        hora, minuto = hora_exacta
        ahora    = datetime.now()
        objetivo = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)

        # si esa hora ya pasó hoy, se asume que es para mañana
        if objetivo <= ahora:
            objetivo += timedelta(days=1)

        return objetivo

    return None

# =========================================================
# PROGRAMAR
# =========================================================




def _siguiente_momento_recurrente(recurrencia):
    """
    Calcula el próximo momento de disparo para un recordatorio
    recurrente, a partir de ahora.
    Tipos: "diario" | "semanal" | "intervalo"
    """
    ahora = datetime.now()
    tipo  = recurrencia.get("tipo")

    if tipo == "diario":
        h, m      = map(int, recurrencia["hora"].split(":"))
        candidato = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidato <= ahora:
            candidato += timedelta(days=1)
        return candidato

    if tipo == "semanal":
        h, m      = map(int, recurrencia["hora"].split(":"))
        dia_obj   = recurrencia["dia"]
        hoy       = ahora.weekday()
        dias_diff = (dia_obj - hoy) % 7
        if dias_diff == 0:
            candidato = ahora.replace(hour=h, minute=m, second=0, microsecond=0)
            if candidato <= ahora:
                dias_diff = 7
            else:
                return candidato
        return (ahora + timedelta(days=dias_diff)).replace(
            hour=h, minute=m, second=0, microsecond=0
        )

    if tipo == "intervalo":
        return ahora + timedelta(seconds=int(recurrencia["segundos"]))

    return None


def _hilo_recordatorio(id_recordatorio, momento, texto, recurrencia=None):
    """
    Duerme hasta el momento exacto y luego avisa. Si el recordatorio
    es recurrente, calcula el siguiente momento y reprograma en vez
    de eliminarse.
    """
    try:
        while True:
            with _lock_datos:
                if str(id_recordatorio) not in _recordatorios:
                    return

            restante = (momento - datetime.now()).total_seconds()
            if restante <= 0:
                break
            time.sleep(min(restante, 30))

        with _lock_datos:
            existia = str(id_recordatorio) in _recordatorios
            if not existia:
                return

            if recurrencia:
                proximo = _siguiente_momento_recurrente(recurrencia)
                if proximo:
                    _recordatorios[str(id_recordatorio)]["momento"] = proximo.isoformat()
                else:
                    _recordatorios.pop(str(id_recordatorio), None)
                    recurrencia = None
            else:
                _recordatorios.pop(str(id_recordatorio), None)

        _guardar()

        from no_molestar import modo_activo, registrar_aviso_diferido
        mensaje_aviso = f"Recordatorio: {texto}"
        if modo_activo():
            registrar_aviso_diferido(mensaje_aviso)
        else:
            hablar(mensaje_aviso)

        if recurrencia:
            with _lock_datos:
                info = _recordatorios.get(str(id_recordatorio))
            if info:
                proximo = datetime.fromisoformat(info["momento"])
                _programar_hilo(id_recordatorio, proximo, texto, recurrencia)

    except Exception:
        log.exception(f"Error en el hilo del recordatorio '{texto}' (id={id_recordatorio})")


def _programar_hilo(id_recordatorio, momento, texto, recurrencia=None):
    hilo = threading.Thread(
        target=_hilo_recordatorio,
        args=(id_recordatorio, momento, texto, recurrencia),
        daemon=True
    )
    hilo.start()


def crear_recordatorio(cuando_texto, que_texto):
    """Crea un recordatorio simple (una sola vez)."""
    momento = calcular_momento(cuando_texto)
    if not momento:
        return False, None

    global _siguiente_id

    with _lock_datos:
        id_recordatorio = _siguiente_id
        _siguiente_id  += 1
        _recordatorios[str(id_recordatorio)] = {
            "momento": momento.isoformat(),
            "texto":   que_texto,
        }

    _guardar()
    _programar_hilo(id_recordatorio, momento, que_texto)

    ahora = datetime.now()
    cuando_decir = (
        f"hoy a las {momento.strftime('%H:%M')}"
        if momento.date() == ahora.date()
        else f"mañana a las {momento.strftime('%H:%M')}"
    )
    return True, f"Listo, te recordaré {que_texto} {cuando_decir}"


_DIAS_SEMANA = {
    "lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2,
    "jueves": 3, "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6,
}


def _parsear_hora_recurrente(texto):
    """Extrae la hora en formato HH:MM de un texto libre."""
    import re
    texto = texto.lower().strip()
    media  = "y media" in texto
    cuarto = "y cuarto" in texto
    texto  = texto.replace("y media", "").replace("y cuarto", "").strip()

    m = re.search(r"\b(\d{1,2}):(\d{2})\b", texto)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if media: mn = (mn + 30) % 60
        return f"{h:02d}:{mn:02d}"

    m = re.search(r"\b(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)?\b", texto)
    if m:
        h  = int(m.group(1))
        pm = m.group(2) and "p" in m.group(2)
        am = m.group(2) and "a" in m.group(2)
        if pm and h < 12: h += 12
        if am and h == 12: h = 0
        mn = 30 if media else (15 if cuarto else 0)
        return f"{h:02d}:{mn:02d}"

    return None


# FIX/NUEVO: envoltorios públicos de _parsear_hora_recurrente() y
# _DIAS_SEMANA — acciones_sistema.py necesita validar estos mismos
# datos para poder preguntar de nuevo solo por lo que falta (ver
# crear_recordatorio_recurrente_accion) sin duplicar la lógica de
# parseo acá. Se agregan estas dos funciones en vez de que ese
# módulo importe directamente los nombres con "_" (pensados como
# detalle interno de este archivo), manteniendo una sola fuente de
# verdad para qué cuenta como hora/día válido.

def hora_recurrente_valida(texto):
    """True si `texto` se puede interpretar como una hora válida
    para un recordatorio diario o semanal."""
    return _parsear_hora_recurrente(texto or "") is not None


def dia_semana_valido(texto):
    """True si `texto` es un día de la semana reconocido."""
    return (texto or "").lower().strip() in _DIAS_SEMANA


def crear_recordatorio_recurrente(tipo_rec, que_texto, hora_texto=None,
                                   dia_semana=None, segundos=None):
    """Crea un recordatorio recurrente."""
    global _siguiente_id

    recurrencia = {"tipo": tipo_rec}

    if tipo_rec == "diario":
        hora = _parsear_hora_recurrente(hora_texto or "")
        if not hora:
            return False, "No entendí a qué hora quieres el recordatorio diario"
        recurrencia["hora"] = hora

    elif tipo_rec == "semanal":
        hora = _parsear_hora_recurrente(hora_texto or "")
        if not hora:
            return False, "No entendí a qué hora quieres el recordatorio semanal"
        dia = _DIAS_SEMANA.get((dia_semana or "").lower().strip())
        if dia is None:
            return False, f"No reconocí el día '{dia_semana}'"
        recurrencia["hora"] = hora
        recurrencia["dia"]  = dia

    elif tipo_rec == "intervalo":
        if not segundos or segundos <= 0:
            return False, "No entendí cada cuánto quieres el recordatorio"
        recurrencia["segundos"] = segundos
    else:
        return False, "Tipo de recurrencia no reconocido"

    proximo = _siguiente_momento_recurrente(recurrencia)
    if not proximo:
        return False, "No pude calcular el próximo momento del recordatorio"

    with _lock_datos:
        id_rec        = _siguiente_id
        _siguiente_id += 1
        _recordatorios[str(id_rec)] = {
            "momento":     proximo.isoformat(),
            "texto":       que_texto,
            "recurrencia": recurrencia,
        }

    _guardar()
    _programar_hilo(id_rec, proximo, que_texto, recurrencia)

    if tipo_rec == "diario":
        desc = f"todos los días a las {recurrencia['hora']}"
    elif tipo_rec == "semanal":
        nombre_dia = [k for k, v in _DIAS_SEMANA.items() if v == recurrencia["dia"]][0]
        desc = f"todos los {nombre_dia} a las {recurrencia['hora']}"
    else:
        segs = recurrencia["segundos"]
        if segs >= 3600 and segs % 3600 == 0:
            n = segs // 3600
            desc = f"cada {n} hora" + ("s" if n > 1 else "")
        else:
            n = segs // 60
            desc = f"cada {n} minuto" + ("s" if n > 1 else "")

    return True, f"Listo, te recordaré {que_texto} {desc}"


def listar_recordatorios():
    with _lock_datos:
        return dict(_recordatorios)


def cancelar_recordatorio(id_recordatorio):
    with _lock_datos:
        existia = _recordatorios.pop(str(id_recordatorio), None) is not None

    if existia:
        _guardar()

    return existia

# =========================================================
# LISTAR EN VOZ
# Convierte los recordatorios pendientes en una frase natural
# para decir en voz alta, ordenados por proximidad.
# =========================================================

def listar_recordatorios_texto():
    """Devuelve (hay_recordatorios, mensaje) listo para hablar()."""

    with _lock_datos:
        items = list(_recordatorios.items())

    if not items:
        return False, "No tienes recordatorios pendientes"

    def _momento(item):
        try:
            return datetime.fromisoformat(item[1]["momento"])
        except Exception:
            return datetime.max

    items.sort(key=_momento)

    ahora  = datetime.now()
    partes = []

    for _, info in items:
        try:
            momento = datetime.fromisoformat(info["momento"])
        except Exception:
            continue

        if momento.date() == ahora.date():
            cuando = f"hoy a las {momento.strftime('%H:%M')}"
        else:
            cuando = f"el {momento.strftime('%d/%m')} a las {momento.strftime('%H:%M')}"

        partes.append(f"{info['texto']} {cuando}")

    if not partes:
        return False, "No tienes recordatorios pendientes"

    if len(partes) == 1:
        return True, f"Tienes un recordatorio: {partes[0]}"

    cuerpo = "; ".join(partes)
    return True, f"Tienes {len(partes)} recordatorios: {cuerpo}"

# =========================================================
# CANCELAR POR PALABRA CLAVE
# Busca recordatorios cuyo texto contenga la palabra clave dada
# (substring, sin distinguir mayúsculas/acentos exactos). Si hay
# una sola coincidencia, la cancela. Si hay varias o ninguna,
# devuelve (False, mensaje) explicando la situación, sin cancelar
# nada — así nunca se borra el recordatorio equivocado por
# ambigüedad.
# =========================================================

def listar_recordatorios_ordenados():
    """
    Devuelve una lista de (id_str, info) ordenada por cercanía
    (el más próximo primero) — usada por el flujo guiado de
    cancelación para poder numerar las opciones y luego identificar
    cuál id corresponde al número elegido por el usuario.
    """
    with _lock_datos:
        items = list(_recordatorios.items())

    def _momento(item):
        try:
            return datetime.fromisoformat(item[1]["momento"])
        except Exception:
            return datetime.max

    items.sort(key=_momento)
    return items


def cancelar_por_palabra_clave(palabras_clave):
    palabras_clave = (palabras_clave or "").strip().lower()

    if not palabras_clave:
        return False, "No entendí cuál recordatorio quieres cancelar"

    with _lock_datos:
        items = list(_recordatorios.items())

    coincidencias = [
        (id_str, info) for id_str, info in items
        if palabras_clave in info.get("texto", "").lower()
    ]

    if not coincidencias:
        return False, f"No encontré ningún recordatorio sobre {palabras_clave}"

    if len(coincidencias) > 1:
        textos = ", ".join(info["texto"] for _, info in coincidencias)
        return False, (
            f"Encontré {len(coincidencias)} recordatorios que coinciden: "
            f"{textos}. Sé más específico para cancelar uno"
        )

    id_str, info = coincidencias[0]
    cancelado = cancelar_recordatorio(id_str)

    if cancelado:
        return True, f"Cancelé el recordatorio de {info['texto']}"

    return False, "No pude cancelar ese recordatorio"

# =========================================================
# REPROGRAMAR AL INICIAR
# Si el asistente estuvo cerrado y había recordatorios
# pendientes con fecha futura, se vuelven a programar. Si la
# hora ya pasó mientras estaba cerrado, se avisa apenas inicia
# en vez de perderlo silenciosamente.
# =========================================================

def reprogramar_pendientes():
    pendientes_vencidos   = []
    pendientes_recurrentes_vencidos = []

    with _lock_datos:
        items = list(_recordatorios.items())

    for id_str, info in items:
        try:
            momento     = datetime.fromisoformat(info["momento"])
            recurrencia = info.get("recurrencia")
        except Exception:
            continue

        if momento <= datetime.now():
            if recurrencia:
                # recurrente vencido — avisa que se perdió y reprograma
                pendientes_recurrentes_vencidos.append((id_str, info["texto"], recurrencia))
            else:
                # simple vencido — avisa y elimina
                pendientes_vencidos.append((id_str, info["texto"]))
        else:
            # futuro — reprogramar hilo normalmente
            _programar_hilo(int(id_str), momento, info["texto"], recurrencia)

    # simples vencidos: eliminar y avisar
    for id_str, texto in pendientes_vencidos:
        with _lock_datos:
            _recordatorios.pop(id_str, None)

    if pendientes_vencidos:
        _guardar()
        for _, texto in pendientes_vencidos:
            hablar(f"Mientras estaba apagado, tenía que recordarte: {texto}")

    # recurrentes vencidos: avisar, reprogramar al siguiente momento
    for id_str, texto, recurrencia in pendientes_recurrentes_vencidos:
        proximo = _siguiente_momento_recurrente(recurrencia)
        if proximo:
            with _lock_datos:
                _recordatorios[id_str]["momento"] = proximo.isoformat()
            _guardar()
            _programar_hilo(int(id_str), proximo, texto, recurrencia)
            hablar(f"Mientras estaba apagado, me perdí el recordatorio de {texto}. "
                   f"El próximo será a las {proximo.strftime('%H:%M')}")
        else:
            with _lock_datos:
                _recordatorios.pop(id_str, None)
            _guardar()

# =========================================================
# CARGAR AL IMPORTAR
# =========================================================

_cargar()
            
