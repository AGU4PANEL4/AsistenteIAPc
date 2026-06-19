from acciones import *
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
}