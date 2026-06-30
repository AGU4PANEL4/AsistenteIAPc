import json
import os
from pathlib import Path

# =========================================================
# ARCHIVO
# =========================================================

CARPETA_DATOS   = Path(os.environ["LOCALAPPDATA"]) / "AsistenteIA"
ARCHIVO_MEMORIA = CARPETA_DATOS / "memoria.json"

# NUEVO: historial corto por tipo de acción. Cada clave es una de
# las acciones que tiene sentido "recordar" (qué app se abrió, cuál
# se cerró, a cuál se le cambió el volumen, etc) y guarda hasta
# HISTORIAL_MAX entradas, la más reciente PRIMERO (índice 0). Esto
# permite responder a cosas como "ábrelo de nuevo" o "pausa el
# anterior" sin que el usuario tenga que repetir el nombre — y al
# guardar varias, no solo la última, "la anterior" sigue siendo
# recuperable si el usuario se refería a la app antepenúltima, no a
# la más reciente.
#
# ultima_app / ultima_accion (los valores que YA existían) se dejan
# intactos — siguen siendo usados por "ciérralo"/"ábrelo" tal cual
# funcionaban, sin ningún cambio de comportamiento. El historial es
# una capa NUEVA y adicional, no un reemplazo.
HISTORIAL_MAX = 5

ACCIONES_CON_HISTORIAL = [
    "abrir_app",
    "cerrar_app",
    "media_pausar",
    "media_reanudar",
    "media_volumen_exacto",
    "crear_recordatorio",
    "crear_temporizador",
]

VALORES_DEFECTO = {
    "ultima_app":    None,
    "ultima_accion": None,
    "historial":     {accion: [] for accion in ACCIONES_CON_HISTORIAL},
}

# =========================================================
# CARGAR
# =========================================================

def cargar_memoria():

    try:
        with open(ARCHIVO_MEMORIA, "r", encoding="utf-8") as f:
            data = json.load(f)

        # agregar claves nuevas si se añaden en el futuro
        cambiado = False
        for clave, valor in VALORES_DEFECTO.items():
            if clave not in data:
                # se copia el valor por defecto en vez de referenciarlo
                # directo, para que cada instalación tenga su propio
                # dict/list independiente y no comparta el mismo objeto
                # en memoria entre cargas
                data[clave] = (
                    dict(valor) if isinstance(valor, dict) else valor
                )
                cambiado = True

        # FIX: si VALORES_DEFECTO["historial"] ganó una acción nueva
        # en una actualización futura del asistente (ej. se agrega
        # "minimizar_app" a ACCIONES_CON_HISTORIAL más adelante),
        # instalaciones existentes con un archivo memoria.json viejo
        # no tendrían esa clave dentro de "historial" — sin esto,
        # registrar_accion() fallaría con KeyError la primera vez que
        # se intentara usar esa acción nueva.
        if "historial" in data:
            for accion in ACCIONES_CON_HISTORIAL:
                if accion not in data["historial"]:
                    data["historial"][accion] = []
                    cambiado = True

        if cambiado:
            _guardar(data)

        return data

    except:
        return json.loads(json.dumps(VALORES_DEFECTO))  # copia profunda

# =========================================================
# GUARDAR
# =========================================================

def _guardar(data):
    CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVO_MEMORIA, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def guardar_memoria():
    _guardar(memoria)

# =========================================================
# HISTORIAL POR ACCIÓN
# =========================================================

def registrar_accion(accion, valor):
    """
    Agrega `valor` al frente del historial de `accion` (la más
    reciente queda en el índice 0), recortando a HISTORIAL_MAX
    entradas. Si `valor` ya estaba en el historial, se mueve al
    frente en vez de duplicarse — así "ábrelo" después de abrir la
    misma app dos veces no llena el historial con copias idénticas,
    dejando lugar para apps realmente distintas.

    Si `accion` no es una de las que tiene historial configurado
    (ver ACCIONES_CON_HISTORIAL), no hace nada — no todas las
    acciones tienen sentido de recordar (ej. listar_recordatorios no
    necesita historial, solo refleja el estado actual).
    """
    if accion not in memoria.get("historial", {}):
        return

    if not valor:
        return

    lista = memoria["historial"][accion]

    if valor in lista:
        lista.remove(valor)

    lista.insert(0, valor)
    memoria["historial"][accion] = lista[:HISTORIAL_MAX]


def obtener_historial(accion):
    """Devuelve la lista de historial de `accion`, más reciente
    primero. Lista vacía si no hay nada registrado todavía."""
    return list(memoria.get("historial", {}).get(accion, []))


def ultimo_de(accion):
    """Devuelve el valor más reciente del historial de `accion`, o
    None si no hay ninguno todavía."""
    historial = obtener_historial(accion)
    return historial[0] if historial else None

# =========================================================
# CARGAR AL IMPORTAR
# =========================================================

memoria = cargar_memoria()