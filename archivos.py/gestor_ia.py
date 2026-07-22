"""
Router del modo híbrido de IA: decide si usar Groq (API en la nube,
gratuita, sin consumir GPU local) u Ollama (modelo local, sin
necesitar internet) según haya o no conectividad en este momento.

NUEVO: se agregó este módulo porque mantener Ollama corriendo todo
el tiempo (con keep_alive=-1, para evitar el delay de recarga del
modelo) reveló un bug real de Ollama donde el proceso llama-server
se queda consumiendo 40-70% de GPU de forma sostenida, incluso en
completo reposo. Con internet, no hay motivo para pagar ese costo —
Groq es gratuito (límites generosos, ver groq_cliente.py), rápido,
y no usa nada de la GPU local. Ollama queda como respaldo automático
para cuando no hay internet, manteniendo el asistente funcional
incluso offline (igual que siempre funcionó).

Responsabilidad de este módulo:
- Decidir, en cada llamada de IA, cuál motor usar.
- Mantener Ollama APAGADO mientras hay internet (para no consumir
  GPU de fondo) y encenderlo automáticamente si se necesita.
- Si Groq falla por cualquier motivo (límite de cuota, error de red
  puntual, etc.) mientras hay internet, cae a Ollama como respaldo
  en esa misma llamada, en vez de fallar directo.
"""

import time
from logger import log
from conectividad import hay_internet
from verificacion import iniciar_ollama, detener_ollama, ollama_ejecutandose
from config import obtener_groq_api_key
from groq_cliente import GROQ_DISPONIBLE

# FIX: cache del motor por 5 segundos para evitar repetir decisiones
# en transcripción + interpretación + TTS en el mismo turno.
_MOTOR_CACHE_TTL = 5
_ULTIMO_MOTOR = None
_ULTIMO_MOTOR_TS = 0

_ESTADO_DESCONOCIDO = "desconocido"
_ESTADO_APAGADO      = "apagado"
_ESTADO_ENCENDIDO    = "encendido"

_estado_ollama                   = _ESTADO_DESCONOCIDO
_ollama_gestionado_por_nosotros  = False


def _motor_cache_valido():
    """True si tenemos un cache de motor reciente que podemos reusar."""
    global _ULTIMO_MOTOR, _ULTIMO_MOTOR_TS
    if _ULTIMO_MOTOR is None:
        return False
    return (time.time() - _ULTIMO_MOTOR_TS) < _MOTOR_CACHE_TTL


def _invalidar_cache_motor():
    """Invalida el cache del motor. Llamar cuando cambia el estado real."""
    global _ULTIMO_MOTOR, _ULTIMO_MOTOR_TS
    _ULTIMO_MOTOR = None
    _ULTIMO_MOTOR_TS = 0


def _asegurar_ollama_apagado():
    """
    Detiene Ollama si está corriendo. Se usa cuando hay internet y
    no lo necesitamos — evita el consumo de GPU sostenido.

    Solo hace el trabajo real (verificar + taskkill + log) si el
    estado conocido NO es ya "apagado" — evita repetir esto en cada
    llamada de IA mientras la conectividad no cambie.
    """
    global _estado_ollama, _ollama_gestionado_por_nosotros

    if _estado_ollama == _ESTADO_APAGADO:
        return

    if ollama_ejecutandose():
        if detener_ollama():
            log.info("Ollama detenido (hay internet, usando Groq)")
        _ollama_gestionado_por_nosotros = False

    _estado_ollama = _ESTADO_APAGADO


def _asegurar_ollama_encendido():
    """
    Inicia Ollama si no está corriendo. Se usa cuando Ollama es el
    motor elegido (sin internet, o con internet pero sin Groq
    disponible).

    FIX: antes, _estado_ollama se marcaba "encendido" SIEMPRE al
    final de la función, sin importar si iniciar_ollama() había
    tenido éxito. Si Ollama no estaba instalado (o fallaba por
    cualquier motivo), el estado quedaba cacheado como "encendido"
    de todas formas — la siguiente llamada veía ese caché, asumía
    que ya estaba todo resuelto, y NUNCA volvía a intentar
    levantarlo en el resto de la sesión: el asistente se quedaba sin
    ningún motor de IA funcionando, sin reintentos, casi sin rastro
    más allá del primer log. Ahora el estado solo se marca
    "encendido" si Ollama de verdad está corriendo — si no, se deja
    tal cual estaba para que la próxima llamada lo vuelva a intentar.
    """
    global _estado_ollama, _ollama_gestionado_por_nosotros

    if _estado_ollama == _ESTADO_ENCENDIDO:
        return

    if ollama_ejecutandose():
        _estado_ollama = _ESTADO_ENCENDIDO
        return

    if iniciar_ollama():
        log.info("Ollama iniciado (respaldo local)")
        _ollama_gestionado_por_nosotros = True
        _estado_ollama = _ESTADO_ENCENDIDO
    else:
        # no se pudo iniciar (ej. no está instalado) — se deja el
        # estado tal cual en vez de mentir que quedó encendido, así
        # la próxima llamada a motor_a_usar() reintenta en vez de
        # darse por vencida para siempre en esta sesión.
        log.warning("No se pudo iniciar Ollama — se reintentará en la próxima llamada")


def _groq_disponible():
    """
    True si Groq es una opción REAL en este momento: el paquete
    'groq' está instalado Y hay una API key configurada (variable de
    entorno o config.json — ver obtener_groq_api_key()). Sin esto,
    motor_a_usar() no tiene forma de distinguir "hay internet" de
    "hay internet Y Groq realmente puede responder".
    """
    return GROQ_DISPONIBLE and bool(obtener_groq_api_key())


def motor_a_usar():
    """
    Devuelve "groq" o "ollama" según cuál esté REALMENTE disponible
    en este momento, y de paso asegura que Ollama esté en el estado
    correcto (apagado si se va a usar Groq, encendido si se va a
    usar Ollama).

    FIX/NUEVO: cache de 5 segundos para evitar repetir toda la
    decisión (hay_internet + ollama_ejecutandose + detener/iniciar)
    en cada llamada de IA dentro del mismo turno. La transcripción,
    interpretación y TTS pueden llamar a esto 2-3 veces por turno;
    con cache, solo la primera hace el trabajo real.
    """
    global _ULTIMO_MOTOR, _ULTIMO_MOTOR_TS

    if _motor_cache_valido():
        return _ULTIMO_MOTOR

    # Lógica real de decisión
    if hay_internet() and _groq_disponible():
        _asegurar_ollama_apagado()
        resultado = "groq"
    else:
        _asegurar_ollama_encendido()
        resultado = "ollama"

    _ULTIMO_MOTOR = resultado
    _ULTIMO_MOTOR_TS = time.time()
    return resultado


def forzar_ollama_como_respaldo():
    """
    Llamar cuando Groq falló A MITAD de una llamada (cuota agotada,
    error de red puntual, etc.) y hace falta Ollama YA, sin importar
    qué haya dicho motor_a_usar() al principio de este mismo turno.

    FIX/NUEVO: antes, ia.py llamaba directo a
    verificacion.iniciar_ollama() en este caso — eso prendía Ollama
    de verdad, pero SIN actualizar _estado_ollama acá, dejando el
    caché de este módulo desincronizado (ver el punto 1 del fix en
    motor_a_usar()). Ahora ia.py llama a ESTA función en su lugar,
    que hace lo mismo pero además deja el estado cacheado correcto
    — así la PRÓXIMA llamada a motor_a_usar() sabe que Ollama está
    realmente encendido y, si para entonces Groq ya está disponible
    de nuevo, lo apaga como corresponde en vez de dejarlo corriendo
    de fondo para siempre.
    """
    global _estado_ollama, _ollama_gestionado_por_nosotros

    _invalidar_cache_motor()

    if not ollama_ejecutandose():
        if iniciar_ollama():
            _ollama_gestionado_por_nosotros = True

    _estado_ollama = _ESTADO_ENCENDIDO if ollama_ejecutandose() else _ESTADO_DESCONOCIDO


def apagar_todo_al_salir():
    """
    Llamar al cerrar el asistente — si nosotros encendimos Ollama
    para el respaldo local, lo apagamos de nuevo para no dejar
    procesos huérfanos consumiendo recursos después de cerrar el
    asistente. Si Ollama ya estaba corriendo ANTES de que el
    asistente arrancara (ej. el usuario lo usa para otra cosa
    también), no lo tocamos — no es nuestro para apagarlo.
    """
    if _ollama_gestionado_por_nosotros:
        detener_ollama()