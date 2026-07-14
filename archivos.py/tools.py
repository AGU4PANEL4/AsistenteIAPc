from acciones import *
from acciones_sistema import (
    activar_startup, desactivar_startup, estado_startup,
    crear_recordatorio_accion, listar_recordatorios_accion,
    cancelar_recordatorio_accion, crear_temporizador_accion,
    listar_temporizadores_accion, cancelar_temporizador_accion,
    activar_no_molestar, desactivar_no_molestar, estado_no_molestar,
    crear_recordatorio_recurrente_accion, ayuda_accion, conversion_accion,
)
from media_control import (
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
}