from acciones import *
from acciones_sistema import (
    activar_startup, desactivar_startup, estado_startup,
    crear_recordatorio_accion, listar_recordatorios_accion,
    cancelar_recordatorio_accion, crear_temporizador_accion,
    listar_temporizadores_accion, cancelar_temporizador_accion,
    activar_no_molestar, desactivar_no_molestar, estado_no_molestar,
    crear_recordatorio_recurrente_accion, ayuda_accion, conversion_accion,
    apagar_pc, reiniciar_pc, cancelar_apagado, suspender_pc, bloquear_pc,
)
from plataforma import es_windows

# NUEVO: media_control.py habla directo con APIs de Windows (SMTC,
# pycaw, win32gui) — en Linux se usa media_control_linux.py en su
# lugar (playerctl/MPRIS + pactl/PulseAudio-PipeWire, ver ese
# archivo). Ambos exponen exactamente las mismas 7 funciones públicas
# con la misma firma, así que el resto de este archivo (el dict
# TOOLS de más abajo) no necesita saber cuál de las dos está
# activa — usa los nombres tal cual, sin importar la plataforma.
if es_windows():
    from media_control import (
        media_pausa_reanuda,
        media_siguiente,
        media_anterior,
        media_subir_volumen,
        media_bajar_volumen,
        media_silenciar,
        media_volumen_exacto,
    )
else:
    from media_control_linux import (
        media_pausa_reanuda,
        media_siguiente,
        media_anterior,
        media_subir_volumen,
        media_bajar_volumen,
        media_silenciar,
        media_volumen_exacto,
    )
from registrar_alias import registrar_alias_manual
from gestionar_macro import crear_macro_guiado, listar_macros_accion, eliminar_macro_guiado
from actualizador import buscar_actualizacion_ahora

TOOLS = {
    "abrir_app":           abrir_app,
    "cerrar_app":          cerrar_app,
    "buscar_google":       buscar_google,
    "abrir_youtube":       abrir_youtube,
    "abrir_url":           abrir_url,
    "activar_startup":     activar_startup,
    "desactivar_startup":  desactivar_startup,
    "estado_startup":      estado_startup,
    "recapturar_app":      recapturar_app,
    "eliminar_alias":      eliminar_alias_app,
    "minimizar_app":       minimizar_app,
    "maximizar_app":       maximizar_app,
    "crear_recordatorio":  crear_recordatorio_accion,
    "listar_recordatorios": listar_recordatorios_accion,
    "cancelar_recordatorio": cancelar_recordatorio_accion,
    "crear_recordatorio_recurrente": crear_recordatorio_recurrente_accion,
    "crear_temporizador":   crear_temporizador_accion,
    "listar_temporizadores": listar_temporizadores_accion,
    "cancelar_temporizador": cancelar_temporizador_accion,
    # media
    "media_pausar":        media_pausa_reanuda,
    "media_reanudar":      media_pausa_reanuda,
    "media_siguiente":     media_siguiente,
    "media_anterior":      media_anterior,
    "media_subir_volumen": media_subir_volumen,
    "media_bajar_volumen": media_bajar_volumen,
    "media_silenciar":     media_silenciar,
    "media_volumen_exacto": media_volumen_exacto,
    # alias
    "registrar_alias":     registrar_alias_manual,
    # macros
    "crear_macro":         crear_macro_guiado,
    "listar_macros":       listar_macros_accion,
    "eliminar_macro":      eliminar_macro_guiado,
    # actualizaciones
    "buscar_actualizacion": buscar_actualizacion_ahora,
    # ayuda
    "ayuda":                ayuda_accion,
    # conversión de unidades
    "conversion_unidades":  conversion_accion,
    # FIX: estaban importadas arriba (from acciones_sistema import
    # ..., activar_no_molestar, desactivar_no_molestar,
    # estado_no_molestar, ...) pero NUNCA se habían agregado acá al
    # diccionario TOOLS — un bug preexistente del proyecto original,
    # anterior a cualquier cambio de esta sesión. Aunque intents.py
    # reconociera perfecto la frase ("no me molestes por una hora",
    # "activa no molestar", etc.) y devolviera el intent correcto,
    # executor.py hacía `if intent not in TOOLS: return False` ANTES
    # de llegar a la sección que habla algún mensaje de error — el
    # comando fallaba en silencio total, sin ninguna respuesta
    # hablada, sin ningún indicio de qué salió mal. Por eso "no
    # molestar" nunca funcionó, sin importar qué tan bien dicha
    # estuviera la frase.
    "activar_no_molestar":    activar_no_molestar,
    "desactivar_no_molestar": desactivar_no_molestar,
    "estado_no_molestar":     estado_no_molestar,
    # NUEVO: cerrar todos los juegos abiertos (detectados por carpeta
    # de instalación real, ver app_finder.procesos_de_juegos_en_ejecucion)
    # — cerrar_juegos_abiertos vive en acciones_apps.py, disponible acá
    # vía el `from acciones import *` de arriba (mismo mecanismo que
    # ya trae abrir_app/cerrar_app/etc, sin necesitar un import
    # explícito aparte). Usado standalone ("cierra todos los juegos")
    # y como parte del modo estudio/enfoque (ver la "cadena" que arma
    # intents.py, que combina esto con activar_no_molestar).
    "cerrar_juegos":          cerrar_juegos_abiertos,
    # NUEVO: comandos de sistema — apagar/reiniciar con margen
    # cancelable, suspender y bloquear directos (ver el comentario
    # detallado junto a cada función en acciones_sistema.py).
    "apagar_pc":              apagar_pc,
    "reiniciar_pc":           reiniciar_pc,
    "cancelar_apagado":       cancelar_apagado,
    "suspender_pc":           suspender_pc,
    "bloquear_pc":            bloquear_pc,
}