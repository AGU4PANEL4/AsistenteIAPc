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

from logger import log
from conectividad import hay_internet
from verificacion import iniciar_ollama, detener_ollama, ollama_ejecutandose

# FIX: antes, motor_a_usar() llamaba a ollama_ejecutandose() (un
# request HTTP real) y, si correspondía, a detener_ollama() (un
# taskkill) en CADA llamada de IA — sin recordar que ya lo había
# hecho. Esto generaba: (1) el mensaje "Deteniendo Ollama... Ollama
# detenido." repitiéndose en consola en cada turno de conversación,
# incluso DOS veces en el mismo turno (interpretar_con_ia y
# responder_charla llaman ambas a esto), y (2) tiempo de ejecución
# real perdido en cada comando (el request HTTP de verificación)
# antes de poder hacer la acción que el usuario pidió.
#
# Ahora se mantiene un estado local (_estado_ollama) que recuerda en
# qué estado dejamos Ollama la ÚLTIMA vez que lo cambiamos — si ya
# está en el estado correcto, no se hace nada (ni verificación HTTP,
# ni taskkill, ni log). Los mensajes de "Deteniendo/Iniciando" solo
# se imprimen la PRIMERA vez que el estado realmente cambia.
_ESTADO_DESCONOCIDO = "desconocido"
_ESTADO_APAGADO      = "apagado"
_ESTADO_ENCENDIDO    = "encendido"

_estado_ollama                   = _ESTADO_DESCONOCIDO
_ollama_gestionado_por_nosotros  = False


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
    Inicia Ollama si no está corriendo. Se usa cuando no hay
    internet y necesitamos el respaldo local.

    Mismo principio que _asegurar_ollama_apagado(): solo hace el
    trabajo real si el estado conocido no es ya "encendido".
    """
    global _estado_ollama, _ollama_gestionado_por_nosotros

    if _estado_ollama == _ESTADO_ENCENDIDO:
        return

    if not ollama_ejecutandose():
        if iniciar_ollama():
            log.info("Ollama iniciado (sin internet, usando modelo local)")
            _ollama_gestionado_por_nosotros = True

    _estado_ollama = _ESTADO_ENCENDIDO


def motor_a_usar():
    """
    Devuelve "groq" o "ollama" según haya internet en este momento,
    y de paso asegura que Ollama esté en el estado correcto
    (apagado si se va a usar Groq, encendido si se va a usar Ollama).

    El chequeo de hay_internet() ya tiene su propio caché corto (ver
    conectividad.py), así que llamar a esto seguido no es costoso —
    y el trabajo de encender/apagar Ollama solo ocurre realmente
    cuando el estado necesita cambiar de verdad.
    """
    if hay_internet():
        _asegurar_ollama_apagado()
        return "groq"

    _asegurar_ollama_encendido()
    return "ollama"


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