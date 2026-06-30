import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from tts import hablar
from tiempo_utils import parsear_duracion

# =========================================================
# ARCHIVO
# Mismo patrón que recordatorios.py / memory.py / aliases.py.
# =========================================================

CARPETA_DATOS         = Path(os.environ["LOCALAPPDATA"]) / "AsistenteIA"
ARCHIVO_TEMPORIZADORES = CARPETA_DATOS / "temporizadores.json"

# =========================================================
# ESTADO EN MEMORIA
# Cada temporizador: {"momento": "2026-06-19T15:30:00",
#                     "nombre": "pasta" | None}
# nombre es None cuando el usuario no le dio uno explícito
# (ej: "pon un temporizador de 10 minutos").
# =========================================================

_lock_datos      = threading.Lock()
_temporizadores  = {}   # id (str) -> dict
_siguiente_id    = 1

# =========================================================
# CARGAR / GUARDAR
# =========================================================

def _cargar():
    global _temporizadores, _siguiente_id

    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

    if not ARCHIVO_TEMPORIZADORES.exists():
        _temporizadores = {}
        _siguiente_id   = 1
        return

    try:
        with open(ARCHIVO_TEMPORIZADORES, "r", encoding="utf-8") as f:
            data = json.load(f)

        _temporizadores = data.get("temporizadores", {})
        _siguiente_id   = data.get("siguiente_id", 1)

    except Exception as e:
        print("[Temporizadores] Error cargando, se empieza vacío:", e)
        _temporizadores = {}
        _siguiente_id   = 1


def _guardar():
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)

    # FIX: mismo problema (y misma solución) que en recordatorios.py —
    # ver el comentario detallado ahí. En resumen: antes la escritura
    # a disco quedaba FUERA del lock, así que dos llamadas a
    # _guardar() casi simultáneas (ej. crear un temporizador justo
    # cuando otro se dispara) podían entrelazarse y la más lenta en
    # escribir terminaba pisando en disco el cambio que la otra ya
    # había guardado, perdiéndolo silenciosamente. Ahora la escritura
    # ocurre DENTRO del lock, serializando completamente los guardados.
    with _lock_datos:
        data = {
            "temporizadores": _temporizadores,
            "siguiente_id":   _siguiente_id,
        }

        try:
            with open(ARCHIVO_TEMPORIZADORES, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print("[Temporizadores] Error guardando:", e)

# =========================================================
# PROGRAMAR
# =========================================================

def _mensaje_aviso(nombre):
    if nombre:
        return f"Se acabó el temporizador de {nombre}"
    return "Se acabó el temporizador"


def _hilo_temporizador(id_temporizador, momento, nombre):
    """
    Duerme hasta el momento exacto y luego avisa. Igual que
    _hilo_recordatorio en recordatorios.py: duerme en tramos cortos
    para poder revisar si fue cancelado mientras tanto.
    """

    while True:
        with _lock_datos:
            if str(id_temporizador) not in _temporizadores:
                return  # fue cancelado

        restante = (momento - datetime.now()).total_seconds()

        if restante <= 0:
            break

        time.sleep(min(restante, 30))

    with _lock_datos:
        existia = _temporizadores.pop(str(id_temporizador), None) is not None

    if not existia:
        return  # se canceló justo antes de dispararse

    _guardar()

    hablar(_mensaje_aviso(nombre))


def _programar_hilo(id_temporizador, momento, nombre):
    hilo = threading.Thread(
        target=_hilo_temporizador,
        args=(id_temporizador, momento, nombre),
        daemon=True
    )
    hilo.start()


def crear_temporizador(duracion_texto, nombre_texto=None):
    """
    Crea un temporizador nuevo. duracion_texto describe la duración
    ("10 minutos", "1 hora 30 minutos", etc — SOLO relativo, un
    temporizador no admite hora exacta como "a las 3pm"). nombre_texto
    es opcional ("pasta", "ejercicio", etc). Devuelve (éxito, mensaje).
    """

    segundos = parsear_duracion(duracion_texto)

    if not segundos:
        return False, None

    nombre  = (nombre_texto or "").strip() or None
    momento = datetime.now() + timedelta(seconds=segundos)

    global _siguiente_id

    with _lock_datos:
        id_temporizador = _siguiente_id
        _siguiente_id  += 1

        _temporizadores[str(id_temporizador)] = {
            "momento": momento.isoformat(),
            "nombre":  nombre,
        }

    _guardar()
    _programar_hilo(id_temporizador, momento, nombre)

    # mensaje natural de confirmación
    horas   = segundos // 3600
    minutos = (segundos % 3600) // 60
    segs    = segundos % 60

    partes_duracion = []
    if horas:
        partes_duracion.append(f"{horas} hora" if horas == 1 else f"{horas} horas")
    if minutos:
        partes_duracion.append(f"{minutos} minuto" if minutos == 1 else f"{minutos} minutos")
    if segs and not horas:
        # los segundos sueltos solo se dicen si la duración es corta;
        # con horas de por medio, decir "y 3 segundos" es ruido innecesario
        partes_duracion.append(f"{segs} segundo" if segs == 1 else f"{segs} segundos")

    duracion_decir = " y ".join(partes_duracion) if partes_duracion else "0 segundos"

    if nombre:
        return True, f"Temporizador de {nombre} puesto a {duracion_decir}"

    return True, f"Temporizador puesto a {duracion_decir}"

# =========================================================
# LISTAR / CANCELAR
# Mismo patrón que recordatorios.py: cancelar por palabra clave
# sobre el nombre, con manejo explícito de 0/1/varias coincidencias
# para nunca cancelar el equivocado por ambigüedad.
# =========================================================

def listar_temporizadores():
    with _lock_datos:
        return dict(_temporizadores)


def listar_temporizadores_texto():
    """Devuelve (hay_temporizadores, mensaje) listo para hablar()."""

    with _lock_datos:
        items = list(_temporizadores.items())

    if not items:
        return False, "No tienes temporizadores activos"

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

        restante = int((momento - ahora).total_seconds())
        restante = max(restante, 0)

        horas_r   = restante // 3600
        minutos_r = (restante % 3600) // 60
        segs_r    = restante % 60

        partes_falta = []
        if horas_r:
            partes_falta.append(f"{horas_r} hora" if horas_r == 1 else f"{horas_r} horas")
        if minutos_r:
            partes_falta.append(f"{minutos_r} minuto" if minutos_r == 1 else f"{minutos_r} minutos")
        if segs_r and not horas_r:
            partes_falta.append(f"{segs_r} segundo" if segs_r == 1 else f"{segs_r} segundos")

        falta = " y ".join(partes_falta) if partes_falta else "0 segundos"

        nombre = info.get("nombre")
        if nombre:
            partes.append(f"{nombre}, faltan {falta}")
        else:
            partes.append(f"faltan {falta}")

    if not partes:
        return False, "No tienes temporizadores activos"

    if len(partes) == 1:
        return True, f"Tienes un temporizador: {partes[0]}"

    cuerpo = "; ".join(partes)
    return True, f"Tienes {len(partes)} temporizadores: {cuerpo}"


def cancelar_temporizador(id_temporizador):
    with _lock_datos:
        existia = _temporizadores.pop(str(id_temporizador), None) is not None

    if existia:
        _guardar()

    return existia


def cancelar_por_palabra_clave(palabras_clave):
    """
    Busca temporizadores cuyo NOMBRE contenga la palabra clave dada.
    Si hay una sola coincidencia, la cancela. Si hay varias o ninguna,
    no cancela nada y explica la situación. Los temporizadores sin
    nombre no pueden buscarse por palabra clave (no hay texto contra
    el que comparar) — para esos, usar "cancela el temporizador" sin
    más cuando solo hay uno activo.
    """
    palabras_clave = (palabras_clave or "").strip().lower()

    if not palabras_clave:
        return False, "No entendí cuál temporizador quieres cancelar"

    with _lock_datos:
        items = list(_temporizadores.items())

    coincidencias = [
        (id_str, info) for id_str, info in items
        if info.get("nombre") and palabras_clave in info["nombre"].lower()
    ]

    if not coincidencias:
        # si solo hay UN temporizador activo en total (con o sin
        # nombre), cancelar ese — es lo más probable que el usuario
        # quiera, en vez de fallar por no tener nombre que comparar
        if len(items) == 1:
            id_str, info = items[0]
            cancelado = cancelar_temporizador(id_str)
            if cancelado:
                nombre = info.get("nombre")
                return True, _mensaje_cancelado(nombre)
            return False, "No pude cancelar el temporizador"

        return False, f"No encontré ningún temporizador sobre {palabras_clave}"

    if len(coincidencias) > 1:
        nombres = ", ".join(info["nombre"] for _, info in coincidencias)
        return False, (
            f"Encontré {len(coincidencias)} temporizadores que coinciden: "
            f"{nombres}. Sé más específico para cancelar uno"
        )

    id_str, info = coincidencias[0]
    cancelado = cancelar_temporizador(id_str)

    if cancelado:
        return True, _mensaje_cancelado(info.get("nombre"))

    return False, "No pude cancelar ese temporizador"


def _mensaje_cancelado(nombre):
    if nombre:
        return f"Cancelé el temporizador de {nombre}"
    return "Cancelé el temporizador"

# =========================================================
# REPROGRAMAR AL INICIAR
# Mismo patrón que recordatorios.py: si el asistente estuvo
# cerrado, los temporizadores pendientes con fecha futura se
# reprograman. Los que ya vencieron mientras estaba apagado se
# avisan apenas inicia.
# =========================================================

def reprogramar_pendientes():
    pendientes_vencidos = []

    with _lock_datos:
        items = list(_temporizadores.items())

    for id_str, info in items:
        try:
            momento = datetime.fromisoformat(info["momento"])
        except Exception:
            continue

        if momento <= datetime.now():
            pendientes_vencidos.append((id_str, info.get("nombre")))
        else:
            _programar_hilo(int(id_str), momento, info.get("nombre"))

    for id_str, _ in pendientes_vencidos:
        with _lock_datos:
            _temporizadores.pop(id_str, None)

    if pendientes_vencidos:
        _guardar()
        for _, nombre in pendientes_vencidos:
            hablar(f"Mientras estaba apagado, {_mensaje_aviso(nombre).lower()}")

# =========================================================
# CARGAR AL IMPORTAR
# =========================================================

_cargar()