import json
import threading
from datetime import datetime, timezone, timedelta

from rutas_datos import CARPETA_DATOS

# =========================================================
# ARCHIVO
# =========================================================

ARCHIVO_MEMORIA = CARPETA_DATOS / "memoria.json"

# =========================================================
# THREAD SAFETY
# =========================================================

_lock = threading.Lock()

# =========================================================
# CONFIGURACIÓN
# =========================================================

HISTORIAL_MAX = 8
CONVERSACION_MAX = 40
HECHOS_CONFIANZA_MINIMA = 0.5
HECHOS_EXPIRACION_DIAS = 90

ACCIONES_CON_HISTORIAL = [
    "abrir_app", "cerrar_app", "media_pausar", "media_reanudar",
    "media_volumen_exacto", "crear_recordatorio", "crear_temporizador",
]

VALORES_DEFECTO = {
    "ultima_app":    None,
    "ultima_accion": None,
    "historial":     {accion: [] for accion in ACCIONES_CON_HISTORIAL},
    "conversacion":  [],
    "hechos":        {},
    "memoria_trabajo": {},
}

# =========================================================
# CARGA PEREZOSA
# =========================================================

_memoria_cache = None
_cargado = False


def _cargar_memoria_interno():
    """Carga la memoria desde disco. Llamar solo bajo _lock."""
    global _memoria_cache, _cargado

    if _cargado:
        return _memoria_cache

    try:
        with open(ARCHIVO_MEMORIA, "r", encoding="utf-8") as f:
            data = json.load(f)

        cambiado = False
        for clave, valor in VALORES_DEFECTO.items():
            if clave not in data:
                data[clave] = (
                    dict(valor) if isinstance(valor, dict)
                    else list(valor) if isinstance(valor, list)
                    else valor
                )
                cambiado = True

        if "historial" in data:
            for accion in ACCIONES_CON_HISTORIAL:
                if accion not in data["historial"]:
                    data["historial"][accion] = []
                    cambiado = True

        # Migrar hechos de formato viejo y limpiar expirados
        if "hechos" in data:
            hechos_limpios = {}
            ahora = datetime.now(timezone.utc)
            for clave, info in data["hechos"].items():
                if isinstance(info, str):
                    hechos_limpios[clave] = {
                        "valor": info,
                        "confianza": 1.0,
                        "fuente": "migrado",
                        "timestamp": ahora.isoformat(),
                    }
                    cambiado = True
                    continue

                ts_str = info.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str)
                    dias = (ahora - ts).days
                    if dias < HECHOS_EXPIRACION_DIAS:
                        hechos_limpios[clave] = info
                    else:
                        cambiado = True
                except Exception:
                    hechos_limpios[clave] = info

            if len(hechos_limpios) != len(data["hechos"]):
                data["hechos"] = hechos_limpios
                cambiado = True

        if cambiado:
            _guardar_interno(data)

        _memoria_cache = data

    except Exception:
        _memoria_cache = json.loads(json.dumps(VALORES_DEFECTO))

    _cargado = True
    return _memoria_cache


def _guardar_interno(data):
    """Guarda la memoria en disco. Llamar solo bajo _lock."""
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVO_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# =========================================================
# DICT-LIKE WRAPPER (COMPATIBILIDAD TOTAL)
# =========================================================
# FIX CRÍTICO: en vez de hacer memoria una función o property,
# usamos una clase que se comporta EXACTAMENTE como un dict:
#   - memoria.get("clave") ✅
#   - memoria["clave"] ✅
#   - "clave" in memoria ✅
#   - len(memoria) ✅
#   - for k in memoria: ✅
#   - memoria.keys() ✅
#   - memoria.values() ✅
#   - memoria.items() ✅
# PERO carga los datos perezosamente la primera vez que se accede.
# =========================================================

class _MemoriaDict(dict):
    """Dict-like que carga la memoria desde disco perezosamente."""

    def __init__(self):
        super().__init__()
        self._cargado = False

    def _asegurar_cargado(self):
        if not self._cargado:
            with _lock:
                data = _cargar_memoria_interno()
            super().clear()
            super().update(data)
            self._cargado = True

    # --- Métodos dict que deben cargar primero ---
    def __getitem__(self, key):
        self._asegurar_cargado()
        return super().__getitem__(key)

    def __setitem__(self, key, value):
        self._asegurar_cargado()
        return super().__setitem__(key, value)

    def __delitem__(self, key):
        self._asegurar_cargado()
        return super().__delitem__(key)

    def __contains__(self, key):
        self._asegurar_cargado()
        return super().__contains__(key)

    def __len__(self):
        self._asegurar_cargado()
        return super().__len__()

    def __iter__(self):
        self._asegurar_cargado()
        return super().__iter__()

    def get(self, key, default=None):
        self._asegurar_cargado()
        return super().get(key, default)

    def keys(self):
        self._asegurar_cargado()
        return super().keys()

    def values(self):
        self._asegurar_cargado()
        return super().values()

    def items(self):
        self._asegurar_cargado()
        return super().items()

    def pop(self, key, *args):
        self._asegurar_cargado()
        return super().pop(key, *args)

    def popitem(self):
        self._asegurar_cargado()
        return super().popitem()

    def setdefault(self, key, default=None):
        self._asegurar_cargado()
        return super().setdefault(key, default)

    def update(self, *args, **kwargs):
        self._asegurar_cargado()
        return super().update(*args, **kwargs)

    def clear(self):
        self._asegurar_cargado()
        return super().clear()

    def __repr__(self):
        self._asegurar_cargado()
        return super().__repr__()

    def __str__(self):
        self._asegurar_cargado()
        return super().__str__()


# Instancia única — se comporta como un dict normal
memoria = _MemoriaDict()


# =========================================================
# GUARDAR
# =========================================================

def guardar_memoria():
    with _lock:
        data = dict(memoria)  # fuerza carga si no está cargada
        _guardar_interno(data)


# =========================================================
# HISTORIAL POR ACCIÓN
# =========================================================

def registrar_accion(accion, valor):
    if accion not in ACCIONES_CON_HISTORIAL:
        return
    if not valor:
        return

    with _lock:
        lista = memoria["historial"][accion]
        if valor in lista:
            lista.remove(valor)
        lista.insert(0, valor)
        memoria["historial"][accion] = lista[:HISTORIAL_MAX]


def obtener_historial(accion):
    return list(memoria["historial"].get(accion, []))


def ultimo_de(accion):
    historial = obtener_historial(accion)
    return historial[0] if historial else None


# =========================================================
# CONVERSACIÓN
# =========================================================

def registrar_turno(rol, mensaje):
    if not mensaje:
        return
    with _lock:
        memoria["conversacion"].append({
            "rol":     rol,
            "mensaje": mensaje,
            "ts":      datetime.now(timezone.utc).isoformat(),
        })
        if len(memoria["conversacion"]) > CONVERSACION_MAX:
            memoria["conversacion"] = memoria["conversacion"][-CONVERSACION_MAX:]


def obtener_conversacion(ultimos_n=None):
    turnos = list(memoria.get("conversacion", []))
    if ultimos_n is not None:
        return turnos[-ultimos_n:]
    return turnos


def limpiar_conversacion():
    with _lock:
        memoria["conversacion"] = []


# =========================================================
# HECHOS / MEMORIA SEMÁNTICA
# =========================================================

def recordar_hecho(clave, valor, confianza=1.0, fuente="usuario"):
    if not valor:
        olvidar_hecho(clave)
        return

    with _lock:
        memoria["hechos"][clave] = {
            "valor": valor,
            "confianza": max(0.0, min(1.0, confianza)),
            "fuente": fuente,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def recordar_hechos(mapping, confianza=1.0, fuente="usuario"):
    for clave, valor in mapping.items():
        recordar_hecho(clave, valor, confianza, fuente)


def obtener_hecho(clave):
    info = memoria.get("hechos", {}).get(clave)
    if info is None:
        return None
    if isinstance(info, str):
        return info
    if info.get("confianza", 1.0) < HECHOS_CONFIANZA_MINIMA:
        return None
    return info.get("valor")


def obtener_hechos(min_confianza=None):
    if min_confianza is None:
        min_confianza = HECHOS_CONFIANZA_MINIMA

    hechos_raw = dict(memoria.get("hechos", {}))
    resultado = {}
    for clave, info in hechos_raw.items():
        if isinstance(info, str):
            resultado[clave] = info
        elif info.get("confianza", 0) >= min_confianza:
            resultado[clave] = info.get("valor")
    return resultado


def obtener_hechos_completos():
    return dict(memoria.get("hechos", {}))


def olvidar_hecho(clave):
    with _lock:
        memoria.get("hechos", {}).pop(clave, None)


def limpiar_hechos_expirados():
    ahora = datetime.now(timezone.utc)
    with _lock:
        hechos = memoria.get("hechos", {})
        claves_borrar = []
        for clave, info in hechos.items():
            if isinstance(info, dict):
                try:
                    ts = datetime.fromisoformat(info.get("timestamp", ""))
                    if (ahora - ts).days >= HECHOS_EXPIRACION_DIAS:
                        claves_borrar.append(clave)
                except Exception:
                    pass
        for clave in claves_borrar:
            hechos.pop(clave, None)


# =========================================================
# MEMORIA DE TRABAJO
# =========================================================

def guardar_trabajo(clave, valor):
    with _lock:
        memoria["memoria_trabajo"][clave] = {
            "valor": valor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


def obtener_trabajo(clave):
    info = memoria.get("memoria_trabajo", {}).get(clave)
    return info["valor"] if info else None


def obtener_todo_trabajo():
    return {k: v["valor"] for k, v in memoria.get("memoria_trabajo", {}).items()}


def limpiar_trabajo():
    with _lock:
        memoria["memoria_trabajo"] = {}


def limpiar_trabajo_antiguo(minutos=30):
    ahora = datetime.now(timezone.utc)
    with _lock:
        trabajo = memoria.get("memoria_trabajo", {})
        claves_borrar = []
        for clave, info in trabajo.items():
            try:
                ts = datetime.fromisoformat(info.get("timestamp", ""))
                if (ahora - ts).total_seconds() > minutos * 60:
                    claves_borrar.append(clave)
            except Exception:
                pass
        for clave in claves_borrar:
            trabajo.pop(clave, None)