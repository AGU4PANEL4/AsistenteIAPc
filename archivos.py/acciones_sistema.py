"""
Acciones del asistente relacionadas con el SISTEMA y datos propios
del asistente: inicio automático con Windows, recordatorios,
temporizadores, y la utilidad de normalización de texto compartida.

Separado de acciones_apps.py (manejo de ventanas/procesos/apps de
Windows) y de acciones.py (que reexporta todo de ambos para mantener
compatibilidad con el resto del proyecto, ej. tools.py que hace
`from acciones import *`) — antes todo esto vivía junto en un solo
archivo de 1300+ líneas que mezclaba temas muy distintos entre sí.
"""

import re
from datetime import datetime

from voice import escuchar, escuchar_confirmacion
from tts import hablar
from startup import (
    activar_inicio_automatico,
    desactivar_inicio_automatico,
    startup_activado
)
from recordatorios import (
    crear_recordatorio,
    listar_recordatorios_texto,
    cancelar_por_palabra_clave,
    calcular_momento,
    listar_recordatorios_ordenados,
    cancelar_recordatorio as _cancelar_recordatorio_por_id,
)
from voz_utils import elegir_de_lista, interpretar_confirmacion
from temporizadores import (
    crear_temporizador,
    listar_temporizadores_texto,
    cancelar_por_palabra_clave as cancelar_temporizador_por_palabra_clave,
)

# =========================================================
# STARTUP
# =========================================================

# FIX: antes estas funciones llamaban a hablar() Y devolvían True/False.
# executor.py también habla un mensaje fijo de éxito para estos intents
# (ver mensajes_exito en executor.py) → el resultado era que el usuario
# escuchaba DOS frases ("Inicio automático activado" dicho aquí, y otra
# vez "Inicio automático activado" dicho por executor.py).
#
# Ahora estas funciones NO hablan directamente. Devuelven una tupla
# (éxito, mensaje) con el texto específico para cada caso (ya estaba
# activado / se acaba de activar / no se pudo), y executor.py usa ese
# mensaje tal cual en vez de su propio texto fijo, sin volver a hablar
# dos veces.

def activar_startup(valor=None):
    if startup_activado():
        return True, "El inicio automático ya está activado"
    if activar_inicio_automatico():
        return True, "Inicio automático activado"
    return False, "No pude activar el inicio automático"


def desactivar_startup(valor=None):
    if not startup_activado():
        return True, "El inicio automático ya está desactivado"
    if desactivar_inicio_automatico():
        return True, "Inicio automático desactivado"
    return False, "No pude desactivar el inicio automático"


def estado_startup(valor=None):
    if startup_activado():
        return True, "El inicio automático está activado"
    return True, "El inicio automático está desactivado"

# =========================================================
# RECORDATORIOS
# valor llega como "cuando|que" (mismo separador que usa
# ia.py para action|value). Se separa aquí y se delega a
# recordatorios.py, que hace el parseo real de tiempo y
# programa el aviso en un hilo aparte.
# =========================================================

def crear_recordatorio_accion(valor=None):
    """
    FIX/NUEVO: antes esto creaba el recordatorio DIRECTO, sin
    confirmar nada — si el wake word se activaba por accidente (ej.
    durante una llamada de voz, alguien dice algo parecido a "jarvis"
    sin querer) y la frase que seguía sonaba a un pedido de
    recordatorio, se guardaba sin que el usuario lo pidiera de
    verdad, y aparecía después con una hora "aleatoria" sin que
    nadie entendiera por qué.

    Ahora se PREGUNTA antes de guardar, con la hora ya calculada y
    el texto exacto que se va a recordar — el usuario tiene que
    confirmar explícitamente. Esto agrega un paso extra siempre
    (incluso cuando el pedido era real e intencional), a cambio de
    eliminar por completo el riesgo de crear recordatorios fantasma.
    """
    if not valor or "|" not in str(valor):
        return False, None

    cuando, que = str(valor).split("|", 1)
    cuando = cuando.strip()
    que    = que.strip()

    if not cuando:
        return False, None

    momento = calcular_momento(cuando)

    if not momento:
        return False, None

    # FIX/NUEVO: antes, si la IA detectaba que el usuario quería
    # crear un recordatorio con fecha/hora pero sin decir QUÉ
    # recordar (ej. "crea un recordatorio para las 4 y media", sin
    # especificar de qué), esto fallaba directo con un error genérico
    # — el usuario tenía que volver a decir todo el comando desde
    # cero, incluyendo la hora que ya había dicho bien. Ahora, si la
    # hora sí se entendió pero falta el nombre, se PREGUNTA en vez de
    # fallar, y solo si tampoco se obtiene un nombre ahí, recién se
    # cancela el recordatorio.
    if not que:
        hablar("¿Qué nombre quieres para tu recordatorio?")
        respuesta_nombre = escuchar()

        if not respuesta_nombre:
            return False, "No se creó el recordatorio, no escuché un nombre"

        que = respuesta_nombre.strip()

    ahora = datetime.now()
    if momento.date() == ahora.date():
        cuando_decir = f"hoy a las {momento.strftime('%H:%M')}"
    else:
        cuando_decir = f"mañana a las {momento.strftime('%H:%M')}"

    hablar(f"¿Confirmas el recordatorio de {que} {cuando_decir}?")

    respuesta = escuchar_confirmacion()

    # FIX/NUEVO: usa interpretar_confirmacion() (ver voz_utils.py) en
    # vez de solo es_afirmacion() — si la respuesta no calza con
    # ninguna palabra conocida de sí/no, se le pregunta a la IA qué
    # quiso decir antes de asumir que se canceló. Un resultado
    # ambiguo (None) se sigue tratando como "no se creó", igual que
    # antes — más vale no crear un recordatorio por error que crear
    # uno no deseado.
    resultado = interpretar_confirmacion(
        respuesta,
        contexto=f"¿Confirmas el recordatorio de {que} {cuando_decir}?",
    )

    if resultado is not True:
        return True, "No se creó el recordatorio"

    return crear_recordatorio(cuando, que)


def listar_recordatorios_accion(valor=None):
    return listar_recordatorios_texto()


def cancelar_recordatorio_accion(valor=None):
    """
    FIX/NUEVO: antes esto requería que el usuario dijera una palabra
    clave que coincidiera EXACTAMENTE (por substring) con el texto
    guardado del recordatorio — incómodo si no recordás las palabras
    exactas que usaste al crearlo.

    Ahora, si no hay palabra clave, o si la palabra clave no
    encuentra una coincidencia única (cero o varias coincidencias),
    se listan los recordatorios existentes NUMERADOS y se deja elegir
    por número o por texto aproximado — mismo patrón ya usado para
    eliminar alias (ver eliminar_alias_guiado en registrar_alias.py).
    """
    palabras_clave = (valor or "").strip()

    if palabras_clave:
        exito, mensaje = cancelar_por_palabra_clave(palabras_clave)
        # si encontró una coincidencia única (éxito) o el problema fue
        # ambigüedad real (varias coincidencias), se respeta ese
        # resultado tal cual — el flujo guiado solo entra cuando NO
        # hay pistas suficientes para identificar nada
        if exito or "Encontré" in (mensaje or ""):
            return exito, mensaje

    items = listar_recordatorios_ordenados()

    if not items:
        return False, "No tienes recordatorios pendientes"

    if len(items) == 1:
        id_str, info = items[0]
        hablar(f"Tienes un recordatorio: {info['texto']}. ¿Lo cancelo?")

        respuesta = escuchar_confirmacion()

        resultado = interpretar_confirmacion(
            respuesta,
            contexto=f"¿Cancelo el recordatorio de {info['texto']}?",
        )

        if resultado is True:
            _cancelar_recordatorio_por_id(id_str)
            return True, f"Cancelé el recordatorio de {info['texto']}"

        return True, "No se canceló nada"

    opciones_texto = [info["texto"] for _, info in items]
    texto_lista = "; ".join(
        f"{i+1}: {texto}" for i, texto in enumerate(opciones_texto)
    )
    hablar(f"Tienes estos recordatorios: {texto_lista}. ¿Cuál quieres cancelar?")

    respuesta = escuchar()

    if not respuesta:
        return False, "No escuché nada"

    if respuesta.lower().strip() in ("todos", "todos los recordatorios", "cancélalos todos", "cancelalos todos"):
        for id_str, _ in items:
            _cancelar_recordatorio_por_id(id_str)
        return True, f"Cancelé los {len(items)} recordatorios"

    indice = elegir_de_lista(respuesta, opciones_texto)

    if indice is None:
        return False, "No identifiqué cuál de esos quieres cancelar"

    id_str, info = items[indice]
    _cancelar_recordatorio_por_id(id_str)
    return True, f"Cancelé el recordatorio de {info['texto']}"

# =========================================================
# TEMPORIZADORES
# valor llega como "duracion|nombre" (mismo patrón que
# crear_recordatorio_accion). A diferencia de recordatorios, el
# nombre es OPCIONAL — puede llegar vacío si el usuario no le dio
# nombre al temporizador (ej. "pon un temporizador de 10 minutos").
# =========================================================

def crear_temporizador_accion(valor=None):
    if not valor or "|" not in str(valor):
        return False, None

    duracion, nombre = str(valor).split("|", 1)
    duracion = duracion.strip()
    nombre   = nombre.strip()

    if not duracion:
        return False, None

    return crear_temporizador(duracion, nombre or None)


def listar_temporizadores_accion(valor=None):
    return listar_temporizadores_texto()


def cancelar_temporizador_accion(valor=None):
    return cancelar_temporizador_por_palabra_clave(valor)

# =========================================================
# NORMALIZAR
# =========================================================

def normalizar(texto: str) -> str:
    texto = texto.lower().strip()
    texto = re.sub(r"[^a-z0-9]", "", texto)
    return texto