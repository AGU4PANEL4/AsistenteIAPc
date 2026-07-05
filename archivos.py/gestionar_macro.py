"""
Flujo guiado para crear y eliminar macros por voz (o confirmando
acciones dictadas). Mismo estilo que registrar_alias.py — el usuario
va indicando los pasos uno a uno y dice "listo" cuando termina.

Acciones disponibles que se pueden incluir en una macro:
  Cualquier intent válido del TOOLS de tools.py — abrir/cerrar app,
  media, volumen, startup, recordatorios, temporizadores, etc.
"""

import time

from tts import hablar
from voice import escuchar
from macros import guardar_macro, listar_macros, eliminar_macro, obtener_macro
from intents import detectar_intent
from voz_utils import elegir_de_lista, interpretar_confirmacion

# =========================================================
# HELPERS
# =========================================================

TERMINAR      = {"listo", "eso es todo", "ya", "terminar", "fin",
                 "no más", "no mas", "suficiente"}

PALABRAS_PASO = ["y también", "y luego", "luego", "después", "despues",
                 "también", "tambien", "y"]


def _escuchar_con_timeout(timeout=10):
    inicio = time.time()
    while True:
        respuesta = escuchar()
        if respuesta:
            return respuesta
        if time.time() - inicio > timeout:
            return ""


def _describir_paso(intent, valor):
    """Convierte (intent, valor) en una frase legible para hablarle al
    usuario mientras se construye la macro paso a paso."""
    descripciones = {
        "abrir_app":           f"abrir {valor}",
        "cerrar_app":          f"cerrar {valor}",
        "minimizar_app":       f"minimizar {valor}",
        "maximizar_app":       f"maximizar {valor}",
        "media_pausar":        "pausar",
        "media_reanudar":      "reanudar",
        "media_siguiente":     "siguiente canción",
        "media_anterior":      "canción anterior",
        "media_subir_volumen": "subir volumen",
        "media_bajar_volumen": "bajar volumen",
        "media_silenciar":     "silenciar",
        "media_volumen_exacto": f"volumen al {valor.split('|')[-1].strip()}",
        "buscar_google":       f"buscar en Google: {valor}",
        "abrir_youtube":       f"buscar en YouTube: {valor}",
        "abrir_url":           f"abrir {valor}",
        "activar_startup":     "activar inicio automático",
        "desactivar_startup":  "desactivar inicio automático",
    }
    return descripciones.get(intent, f"{intent} {valor}".strip())


# =========================================================
# CREAR MACRO
# =========================================================

def crear_macro_guiado(valor=None):
    """
    Flujo completo de creación de una macro:
    1. Pide el nombre de la macro.
    2. Pide los pasos uno a uno (usa detectar_intent para reconocer
       cada acción, igual que el loop principal de main.py).
    3. Confirma el resumen y guarda.
    """

    # ── PASO 1: nombre ────────────────────────────────────
    nombre = (valor or "").strip().lower()

    if not nombre:
        hablar("¿Cómo quieres llamar a esta macro?")
        nombre = _escuchar_con_timeout(timeout=10).lower().strip()

    if not nombre:
        hablar("No escuché ningún nombre.")
        return False, None

    # quitar prefijos de activación típicos si el usuario dice algo
    # como "crea la macro modo juego" y el valor llega como "modo juego"
    for prefijo in ("macro ", "la macro ", "nueva macro "):
        if nombre.startswith(prefijo):
            nombre = nombre[len(prefijo):]

    # ── PASO 2: pasos uno a uno ───────────────────────────
    pasos = []

    hablar(
        f"Entendido, macro \"{nombre}\". "
        "Dime las acciones una a una — por ejemplo: "
        "\"cierra discord\", \"volumen al 80\", \"abre steam\". "
        "Cuando termines di \"listo\"."
    )

    while True:
        respuesta = _escuchar_con_timeout(timeout=12)

        if not respuesta:
            if pasos:
                hablar("No escuché nada más. ¿Guardamos con los pasos que tenemos?")
                confirmacion = _escuchar_con_timeout(timeout=8)
                if interpretar_confirmacion(confirmacion, contexto="¿Guardamos la macro?") is True:
                    break
            hablar("No escuché nada, cancelando.")
            return False, None

        respuesta_lower = respuesta.lower().strip()

        if respuesta_lower in TERMINAR:
            break

        # intentar detectar el intent del paso dicho
        intent, valor_paso = detectar_intent(respuesta)

        if not intent:
            hablar(f"No reconocí \"{respuesta}\" como una acción. "
                   "Prueba decirla de otra forma, o di \"listo\" para terminar.")
            continue

        pasos.append({"intent": intent, "valor": valor_paso or ""})
        descripcion = _describir_paso(intent, valor_paso or "")
        hablar(f"Agregado: {descripcion}. ¿Siguiente acción?")

    if not pasos:
        hablar("No agregaste ninguna acción, macro cancelada.")
        return False, None

    # ── PASO 3: confirmar y guardar ───────────────────────
    resumen = ", ".join(_describir_paso(p["intent"], p["valor"]) for p in pasos)
    hablar(f"La macro \"{nombre}\" tiene {len(pasos)} pasos: {resumen}. ¿La guardo?")

    confirmacion = _escuchar_con_timeout(timeout=10)
    resultado = interpretar_confirmacion(
        confirmacion,
        contexto=f"¿Guardo la macro \"{nombre}\"?",
    )

    if resultado is not True:
        hablar("Macro cancelada, no se guardó nada.")
        return False, None

    guardar_macro(nombre, pasos)
    return True, f"Macro \"{nombre}\" guardada con {len(pasos)} pasos"


# =========================================================
# LISTAR MACROS
# =========================================================

def listar_macros_accion(valor=None):
    macros = listar_macros()

    if not macros:
        return False, "No tienes ninguna macro guardada"

    partes = []
    for nombre, pasos in macros.items():
        partes.append(f"{nombre}: {len(pasos)} pasos")

    cuerpo = "; ".join(partes)

    if len(macros) == 1:
        return True, f"Tienes una macro: {cuerpo}"

    return True, f"Tienes {len(macros)} macros: {cuerpo}"


# =========================================================
# ELIMINAR MACRO
# =========================================================

def eliminar_macro_guiado(valor=None):
    """
    Flujo guiado para eliminar una macro. Si `valor` ya trae el
    nombre (ej: "elimina la macro modo juego"), se usa directamente.
    """
    macros = listar_macros()

    if not macros:
        hablar("No tienes ninguna macro guardada.")
        return False, None

    nombre = (valor or "").strip().lower()

    # quitar prefijos de activación típicos
    for prefijo in ("macro ", "la macro "):
        if nombre.startswith(prefijo):
            nombre = nombre[len(prefijo):]

    # si ya llegó un nombre útil, buscar directamente
    if nombre:
        nombre_real, _ = obtener_macro(nombre)
        if nombre_real:
            return _confirmar_y_eliminar(nombre_real)
        # no encontró coincidencia suficiente — caer al flujo guiado

    # flujo guiado: mostrar lista y dejar elegir
    if len(macros) == 1:
        nombre_real = list(macros.keys())[0]
        hablar(f"Solo tienes una macro: \"{nombre_real}\". ¿La elimino?")
        confirmacion = _escuchar_con_timeout(timeout=8)
        if interpretar_confirmacion(confirmacion, contexto=f"¿Elimino la macro {nombre_real}?") is True:
            eliminar_macro(nombre_real)
            return True, f"Eliminé la macro \"{nombre_real}\""
        return True, "No se eliminó nada"

    nombres = list(macros.keys())
    texto   = "; ".join(f"{i+1}: {n}" for i, n in enumerate(nombres))
    hablar(f"Tienes estas macros: {texto}. ¿Cuál quieres eliminar?")

    respuesta = _escuchar_con_timeout(timeout=10)

    if not respuesta:
        hablar("No escuché nada.")
        return False, None

    indice = elegir_de_lista(respuesta, nombres)

    if indice is None:
        hablar("No identifiqué cuál quieres eliminar.")
        return False, None

    return _confirmar_y_eliminar(nombres[indice])


def _confirmar_y_eliminar(nombre_real):
    hablar(f"¿Elimino la macro \"{nombre_real}\"?")
    confirmacion = _escuchar_con_timeout(timeout=8)
    if interpretar_confirmacion(confirmacion, contexto=f"¿Elimino la macro {nombre_real}?") is True:
        eliminar_macro(nombre_real)
        return True, f"Eliminé la macro \"{nombre_real}\""
    return True, "No se eliminó nada"