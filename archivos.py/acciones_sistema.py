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
import subprocess

from logger import log
from plataforma import es_linux
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
    crear_recordatorio_recurrente,
    hora_recurrente_valida,
    dia_semana_valido,
)
from voz_utils import elegir_de_lista, interpretar_confirmacion, preguntar_dato

# =========================================================
# MODO NO MOLESTAR
# =========================================================

def activar_no_molestar(valor=None):
    """
    valor llega como string de minutos (ej: "60") — parseado por
    intents.py a partir de frases como "no me molestes por una hora"
    o "silencia los avisos 30 minutos".
    """
    from no_molestar import activar
    try:
        minutos = int(str(valor).strip()) if valor else 60
    except ValueError:
        minutos = 60
    return activar(minutos)


def desactivar_no_molestar(valor=None):
    from no_molestar import desactivar
    return desactivar()


def estado_no_molestar(valor=None):
    from no_molestar import estado
    return estado()
from temporizadores import (
    crear_temporizador,
    listar_temporizadores_texto,
    cancelar_por_palabra_clave as cancelar_temporizador_por_palabra_clave,
)
from tiempo_utils import parsear_duracion

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
    FIX/NUEVO: esta función pasó por dos problemas reales de uso:

    1. Si intents.py no llegaba a detectar una fecha/hora válida en
       absoluto (valor sin "|", o calcular_momento() no entendía la
       frase), esto fallaba directo con un error genérico — el
       usuario tenía que repetir el comando COMPLETO desde cero,
       incluso el nombre del recordatorio si ya lo había dicho bien.
       Solo el caso de "falta el nombre" tenía un manejo especial
       (preguntar y esperar). Ahora "falta o no se entendió la
       fecha" tiene el mismo trato: se pregunta puntualmente por
       ESE dato (hasta 2 veces) en vez de tirar todo por la borda.

    2. Se pedía SIEMPRE una confirmación por voz antes de crear el
       recordatorio, incluso cuando el usuario dijo todo bien a la
       primera — un paso extra en cada pedido. Se quita ese paso: el
       recordatorio se crea directo. El riesgo original que esa
       confirmación buscaba evitar (un recordatorio "fantasma" por
       una activación accidental del wake word) sigue existiendo en
       teoría, pero ahora se puede cancelar con un simple "cancela
       el recordatorio de X" si llega a pasar.

    En ambos pasos pendientes (fecha, nombre), si el usuario responde
    con una palabra de cancelación (o no dice nada), se abandona el
    flujo sin crear nada — ver preguntar_dato() en voz_utils.py.
    """
    cuando, que = "", ""
    if valor and "|" in str(valor):
        cuando, que = str(valor).split("|", 1)
        cuando = cuando.strip()
        que    = que.strip()

    momento = calcular_momento(cuando) if cuando else None

    intentos = 0
    while momento is None and intentos < 2:
        respuesta = preguntar_dato("¿Para cuándo quieres el recordatorio?")
        if respuesta is None:
            return True, "No se creó el recordatorio"
        cuando  = respuesta
        momento = calcular_momento(cuando)
        intentos += 1

    if momento is None:
        return False, "No entendí para cuándo quieres el recordatorio"

    intentos = 0
    while not que and intentos < 2:
        respuesta = preguntar_dato("¿Qué nombre quieres para tu recordatorio?")
        if respuesta is None:
            return True, "No se creó el recordatorio"
        que = respuesta
        intentos += 1

    if not que:
        return False, "No entendí el nombre del recordatorio"

    return crear_recordatorio(cuando, que)



def crear_recordatorio_recurrente_accion(valor=None):
    """
    valor llega como "tipo|hora_o_segundos|dia|que" separado por pipes.
    Formatos según tipo:
      diario|08:00||tomar pastilla
      semanal|08:00|lunes|reunión
      intervalo|3600||revisar correo   (segundos)

    FIX/NUEVO: mismo patrón que crear_recordatorio_accion y
    crear_temporizador_accion — si falta o no se entendió alguno de
    los datos (la hora, el día, el intervalo, o el texto), se
    pregunta puntualmente por ESE dato en vez de fallar directo y
    obligar a repetir todo el comando desde cero. El tipo de
    recurrencia en sí (diario/semanal/intervalo) es la excepción: si
    no viene reconocible desde intents.py no hay ninguna pregunta
    puntual sensata que hacer al respecto, así que ahí sí se falla.
    """
    if not valor or "|" not in str(valor):
        return False, None

    partes = str(valor).split("|", 3)
    if len(partes) < 4:
        return False, None

    tipo, hora_o_seg, dia, que = partes
    tipo       = tipo.strip()
    hora_o_seg = hora_o_seg.strip()
    dia        = dia.strip()
    que        = que.strip()

    if tipo not in ("diario", "semanal", "intervalo"):
        return False, "Tipo de recurrencia no reconocido"

    # ── texto del recordatorio ────────────────────────────
    intentos = 0
    while not que and intentos < 2:
        respuesta = preguntar_dato("¿Qué quieres que te recuerde?")
        if respuesta is None:
            return True, "No se creó el recordatorio"
        que = respuesta
        intentos += 1

    if not que:
        return False, "No entendí el texto del recordatorio"

    # ── intervalo: cada cuánto ────────────────────────────
    if tipo == "intervalo":
        try:
            segundos = int(hora_o_seg)
            if segundos <= 0:
                segundos = None
        except ValueError:
            segundos = None

        intentos = 0
        while segundos is None and intentos < 2:
            # a diferencia del valor que llega de intents.py (segundos
            # en crudo), lo que dice el usuario en voz alta acá es una
            # frase de duración natural ("cada 10 minutos") — se
            # interpreta con parsear_duracion(), igual que en
            # crear_temporizador_accion, no como un número directo.
            respuesta = preguntar_dato("¿Cada cuánto tiempo quieres el recordatorio?")
            if respuesta is None:
                return True, "No se creó el recordatorio"
            segundos = parsear_duracion(respuesta) or None
            intentos += 1

        if segundos is None:
            return False, "No entendí cada cuánto quieres el recordatorio"

        return crear_recordatorio_recurrente("intervalo", que, segundos=segundos)

    # ── diario / semanal: a qué hora ──────────────────────
    intentos = 0
    while not hora_recurrente_valida(hora_o_seg) and intentos < 2:
        respuesta = preguntar_dato("¿A qué hora quieres el recordatorio?")
        if respuesta is None:
            return True, "No se creó el recordatorio"
        hora_o_seg = respuesta
        intentos += 1

    if not hora_recurrente_valida(hora_o_seg):
        return False, "No entendí a qué hora quieres el recordatorio"

    if tipo == "diario":
        return crear_recordatorio_recurrente("diario", que, hora_texto=hora_o_seg)

    # ── semanal: qué día ───────────────────────────────────
    intentos = 0
    while not dia_semana_valido(dia) and intentos < 2:
        respuesta = preguntar_dato("¿Qué día de la semana?")
        if respuesta is None:
            return True, "No se creó el recordatorio"
        dia = respuesta
        intentos += 1

    if not dia_semana_valido(dia):
        return False, f"No reconocí el día «{dia}»"

    return crear_recordatorio_recurrente(
        "semanal", que, hora_texto=hora_o_seg, dia_semana=dia
    )


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
    """
    FIX/NUEVO: mismo problema (y misma solución) que
    crear_recordatorio_accion — si la duración no se entendía o
    llegaba vacía, esto fallaba directo con un error genérico y el
    usuario tenía que repetir todo el comando desde cero, incluso el
    nombre si ya lo había dicho. Ahora se pregunta puntualmente por
    la duración (hasta 2 veces) en vez de descartar todo.
    """
    duracion, nombre = "", ""
    if valor and "|" in str(valor):
        duracion, nombre = str(valor).split("|", 1)
        duracion = duracion.strip()
        nombre   = nombre.strip()

    intentos = 0
    while (not duracion or parsear_duracion(duracion) is None) and intentos < 2:
        respuesta = preguntar_dato("¿De cuánto tiempo quieres el temporizador?")
        if respuesta is None:
            return True, "No se creó el temporizador"
        duracion = respuesta
        intentos += 1

    if not duracion or parsear_duracion(duracion) is None:
        return False, "No entendí la duración del temporizador"

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

# =========================================================
# AYUDA
# NUEVO: con todo lo que fue acumulando el asistente (apps, media,
# recordatorios, temporizadores, macros, alias, no molestar,
# actualizaciones, inicio automático), no había ninguna forma de
# preguntarle "¿qué puedes hacer?" — si alguien más lo usa, o si vos
# mismo te olvidás de un comando puntual, no quedaba otra que
# adivinar o revisar el código. Esto da un resumen corto por
# categoría en vez de listar cada comando exacto uno por uno (sería
# demasiado largo para escuchar de corrido) — sirve como punto de
# partida, no como referencia exhaustiva.
# =========================================================

def ayuda_accion(valor=None):
    mensaje = (
        "Puedo ayudarte con varias cosas: "
        "abrir, cerrar, minimizar o maximizar apps y juegos; "
        "cerrar todos los juegos abiertos de una vez, o activar el "
        "modo estudio para eso mismo más no molestar juntos; "
        "controlar música y video (pausar, siguiente, volumen); "
        "recordatorios y temporizadores; "
        "macros para encadenar varias acciones con un solo comando; "
        "alias para que reconozca mejor los nombres que uses; "
        "modo no molestar; "
        "inicio automático con Windows; "
        "apagar, reiniciar, suspender o bloquear la PC; "
        "y buscar actualizaciones del asistente. "
        "También podés preguntarme cosas y charlar normalmente. "
        "Decime, por ejemplo, \"crea una macro\" o \"registra un alias\" "
        "si querés que te guíe paso a paso con alguna de esas."
    )
    return True, mensaje

# =========================================================
# CONVERSIÓN DE UNIDADES
# FIX/NUEVO: antes este era un pass-through simple — asumía que
# `valor` YA era el texto de respuesta calculado por intents.py. Eso
# funcionaba mientras el ÚNICO camino para llegar acá fuera la regla
# rápida de intents.py (que sí calcula todo antes de devolver el
# intent) — pero ahora interpretar_con_ia() (ia.py) también puede
# reconocer una conversión que esa regla rápida no matcheó (una frase
# rara, por ejemplo "a cuántos metros equivalen 5 kilómetros"), y en
# ESE camino la IA solo reformula la pregunta a un formato simple
# ("5 kilometros a metros"), nunca hace la cuenta ella misma — la
# cuenta la sigue haciendo SIEMPRE conversiones.py, con matemática
# pura, sin importar por cuál de los dos caminos se llegó acá. Esta
# función ahora corre detectar_conversion() de verdad sobre `valor`
# en vez de asumir que ya viene resuelto.
# =========================================================

def conversion_accion(valor=None):
    from conversiones import detectar_conversion

    resultado = detectar_conversion(valor)

    if not resultado:
        return False, "No entendí esa conversión"

    return True, resultado

# =========================================================
# COMANDOS DE SISTEMA — apagar, reiniciar, suspender, bloquear
# NUEVO: control básico de energía de Windows por voz.
#
# Apagar y reiniciar son ACCIONES DESTRUCTIVAS (se pierde cualquier
# trabajo sin guardar) — en vez de un flujo de confirmación por voz
# (que depende de que el reconocimiento de "sí"/"no" acierte, algo
# que este mismo proyecto documentó fallando en varios lugares — ver
# session.py/voz_utils.py), se usa el mecanismo NATIVO de Windows:
# "shutdown /s /t N" programa el apagado con N segundos de margen
# ANTES de ejecutarse de verdad, cancelable con "shutdown /a". El
# asistente avisa el margen en voz alta y da una ventana real para
# arrepentirse ("cancela el apagado"), sin necesitar un segundo turno
# de escucha que podría fallar o malinterpretarse.
#
# Suspender y bloquear NO se consideran destructivos de la misma
# forma (no se pierde nada, la sesión de Windows sigue intacta al
# volver) — se ejecutan directo, sin margen de cancelación.
#
# A propósito, ninguna de las frases reconocidas para suspender usa
# "dormir"/"duerme" — esas palabras ya están tomadas por el modo
# dormido DEL ASISTENTE (ver es_dormir/DESPIERTA_WORD en session.py),
# que es algo completamente distinto (silenciar la wake word, no
# tocar el hardware) — mezclar el mismo vocabulario para dos cosas
# distintas sería confuso y, peor, arriesgaría que uno de los dos
# matchee por error el comando del otro.
# =========================================================

# =========================================================
# COMANDOS DE SISTEMA — apagar, reiniciar, suspender, bloquear
# NUEVO: control básico de energía por voz, multiplataforma.
#
# Apagar y reiniciar son ACCIONES DESTRUCTIVAS (se pierde cualquier
# trabajo sin guardar) — en vez de un flujo de confirmación por voz
# (que depende de que el reconocimiento de "sí"/"no" acierte, algo
# que este mismo proyecto documentó fallando en varios lugares — ver
# session.py/voz_utils.py), se usa el mecanismo NATIVO de cada
# sistema operativo para programar la acción con un margen de
# segundos ANTES de ejecutarse de verdad, cancelable durante ese
# margen. El asistente avisa el margen en voz alta y da una ventana
# real para arrepentirse ("cancela el apagado"), sin necesitar un
# segundo turno de escucha que podría fallar o malinterpretarse.
#
# Suspender y bloquear NO se consideran destructivos de la misma
# forma (no se pierde nada, la sesión sigue intacta al volver) — se
# ejecutan directo, sin margen de cancelación.
#
# A propósito, ninguna de las frases reconocidas para suspender usa
# "dormir"/"duerme" — esas palabras ya están tomadas por el modo
# dormido DEL ASISTENTE (ver es_dormir/DESPIERTA_WORD en session.py),
# que es algo completamente distinto (silenciar la wake word, no
# tocar el hardware) — mezclar el mismo vocabulario para dos cosas
# distintas sería confuso y, peor, arriesgaría que uno de los dos
# matchee por error el comando del otro.
# =========================================================

DEMORA_APAGADO_SEGUNDOS = 10

# Nombre fijo de la unidad systemd transitoria usada en Linux para
# programar el apagado/reinicio — necesario para poder CANCELARLA
# después por nombre (ver _cancelar_apagado_linux), el equivalente
# de "shutdown /a" en Windows.
_UNIDAD_APAGADO_LINUX = "asistente-apagado"


def apagar_pc(valor=None):
    if es_linux():
        return _programar_apagado_linux("poweroff")
    return _apagar_pc_windows()


def reiniciar_pc(valor=None):
    if es_linux():
        return _programar_apagado_linux("reboot")
    return _reiniciar_pc_windows()


def cancelar_apagado(valor=None):
    if es_linux():
        return _cancelar_apagado_linux()
    return _cancelar_apagado_windows()


def suspender_pc(valor=None):
    if es_linux():
        return _suspender_pc_linux()
    return _suspender_pc_windows()


def bloquear_pc(valor=None):
    if es_linux():
        return _bloquear_pc_linux()
    return _bloquear_pc_windows()


# =========================================================
# WINDOWS
# =========================================================

def _apagar_pc_windows():
    try:
        subprocess.run(
            ["shutdown", "/s", "/t", str(DEMORA_APAGADO_SEGUNDOS)],
            capture_output=True,
        )
        return True, (
            f"Apagando la PC en {DEMORA_APAGADO_SEGUNDOS} segundos. "
            "Decí \"cancela el apagado\" si fue un error"
        )
    except Exception:
        log.exception("Error apagando la PC")
        return False, "No pude apagar la PC"


def _reiniciar_pc_windows():
    try:
        subprocess.run(
            ["shutdown", "/r", "/t", str(DEMORA_APAGADO_SEGUNDOS)],
            capture_output=True,
        )
        return True, (
            f"Reiniciando la PC en {DEMORA_APAGADO_SEGUNDOS} segundos. "
            "Decí \"cancela el apagado\" si fue un error"
        )
    except Exception:
        log.exception("Error reiniciando la PC")
        return False, "No pude reiniciar la PC"


def _cancelar_apagado_windows():
    """
    "shutdown /a" devuelve código de salida distinto de 0 si no había
    ningún apagado pendiente que cancelar — se usa eso para
    distinguir "cancelado con éxito" de "no había nada que cancelar"
    (ej. alguien dice esto sin haber pedido apagar antes), en vez de
    reportar éxito en ambos casos por igual.
    """
    resultado = subprocess.run(["shutdown", "/a"], capture_output=True)
    if resultado.returncode == 0:
        return True, "Cancelé el apagado"
    return False, "No había ningún apagado pendiente para cancelar"


def _suspender_pc_windows():
    try:
        subprocess.run(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            capture_output=True,
        )
        return True, "Suspendiendo la PC"
    except Exception:
        log.exception("Error suspendiendo la PC")
        return False, "No pude suspender la PC"


def _bloquear_pc_windows():
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return True, "Bloqueando la PC"
    except Exception:
        log.exception("Error bloqueando la PC")
        return False, "No pude bloquear la PC"


# =========================================================
# LINUX
# NUEVO: requiere systemd (la inmensa mayoría de distros de
# escritorio modernas — Ubuntu, Fedora, Debian, Arch, Mint, etc. —
# lo usan por defecto). En una distro sin systemd (ej. Void Linux con
# runit), estas funciones fallan de forma controlada y devuelven
# (False, mensaje) en vez de romper el asistente.
# =========================================================

def _programar_apagado_linux(accion):
    """
    accion: "poweroff" o "reboot". Usa systemd-run para programar la
    acción DEMORA_APAGADO_SEGUNDOS en el futuro, con un nombre de
    unidad FIJO — así se puede cancelar después por nombre (ver
    _cancelar_apagado_linux), igual que "shutdown /a" hace en
    Windows.

    "systemd-run --on-active=Ns" crea un timer transitorio que
    dispara el comando dado UNA sola vez, N segundos después de
    creado — el equivalente más directo en systemd al margen de
    "shutdown /t N" de Windows. El propio comando `shutdown` de
    Linux (de util-linux) solo admite MINUTOS como unidad mínima de
    margen, insuficiente para los ~10 segundos que queremos acá.
    """
    try:
        resultado = subprocess.run(
            [
                "systemd-run", f"--unit={_UNIDAD_APAGADO_LINUX}",
                f"--on-active={DEMORA_APAGADO_SEGUNDOS}",
                "systemctl", accion,
            ],
            capture_output=True, text=True,
        )

        if resultado.returncode != 0:
            log.error(f"systemd-run para {accion} falló: {resultado.stderr.strip()}")
            verbo = "apagar" if accion == "poweroff" else "reiniciar"
            return False, f"No pude {verbo} la PC"

        verbo = "Apagando" if accion == "poweroff" else "Reiniciando"
        return True, (
            f"{verbo} la PC en {DEMORA_APAGADO_SEGUNDOS} segundos. "
            "Decí \"cancela el apagado\" si fue un error"
        )
    except Exception:
        log.exception(f"Error programando {accion} en Linux")
        verbo = "apagar" if accion == "poweroff" else "reiniciar"
        return False, f"No pude {verbo} la PC"


def _cancelar_apagado_linux():
    resultado = subprocess.run(
        ["systemctl", "stop", f"{_UNIDAD_APAGADO_LINUX}.timer"],
        capture_output=True,
    )
    if resultado.returncode == 0:
        return True, "Cancelé el apagado"
    return False, "No había ningún apagado pendiente para cancelar"


def _suspender_pc_linux():
    try:
        resultado = subprocess.run(["systemctl", "suspend"], capture_output=True)
        if resultado.returncode != 0:
            return False, "No pude suspender la PC"
        return True, "Suspendiendo la PC"
    except Exception:
        log.exception("Error suspendiendo la PC")
        return False, "No pude suspender la PC"


def _bloquear_pc_linux():
    """
    No hay UN comando universal para bloquear la pantalla en Linux —
    depende del entorno de escritorio. Se prueba una cascada de
    mecanismos estándar, del más ampliamente soportado al más
    específico, deteniéndose en el primero que funcione:

      1. "loginctl lock-session" — estándar de systemd-logind, lo
         escuchan GNOME y KDE modernos por defecto.
      2. "xdg-screensaver lock" — herramienta de freedesktop.org
         pensada específicamente para ser agnóstica del entorno de
         escritorio.
      3. Interfaz D-Bus estándar org.freedesktop.ScreenSaver — usada
         por entornos que no atienden ninguno de los dos anteriores.

    Si ninguno funciona (entorno de escritorio no estándar, o los
    binarios no están instalados), se reporta el fallo en vez de
    fingir éxito.
    """
    intentos = [
        ["loginctl", "lock-session"],
        ["xdg-screensaver", "lock"],
    ]

    for comando in intentos:
        try:
            resultado = subprocess.run(comando, capture_output=True, timeout=5)
            if resultado.returncode == 0:
                return True, "Bloqueando la PC"
        except Exception:
            continue

    try:
        resultado = subprocess.run(
            [
                "dbus-send", "--type=method_call",
                "--dest=org.freedesktop.ScreenSaver",
                "/org/freedesktop/ScreenSaver",
                "org.freedesktop.ScreenSaver.Lock",
            ],
            capture_output=True, timeout=5,
        )
        if resultado.returncode == 0:
            return True, "Bloqueando la PC"
    except Exception:
        pass

    log.error("No se pudo bloquear la pantalla — ningún mecanismo conocido funcionó")
    return False, "No pude bloquear la PC"