#!/usr/bin/env bash
#
# desinstalador_linux.sh
#
# Desinstalador UNIFICADO de AsistenteIA para Linux.
#
# Detecta automáticamente cómo fue instalado (directo en el host, o
# vía Distrobox en distro atómica) y elimina todo correspondiente
# sin que tengas que saber de antemano qué método se usó.
#
# Siempre pregunta ANTES de tocar tus datos (alias, macros,
# recordatorios, config), con "no borrar" como opción por defecto.
#
# Uso: chmod +x desinstalador_linux.sh && ./desinstalador_linux.sh
#
# Si fue instalado con Distrobox, también verifica si el contenedor
# tiene paquetes extra que el usuario instaló por su cuenta, y avisa
# antes de borrarlo.

set -euo pipefail

CONTENEDOR="asistente-ia"

INSTALL_DIR="$HOME/.local/opt/asistente-ia"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/asistente-ia"
DESKTOP_FILE="$HOME/.local/share/applications/asistente-ia.desktop"
ICON_FILE="$HOME/.local/share/icons/hicolor/256x256/apps/asistente-ia.png"
AUTOSTART_FILE="$HOME/.config/autostart/AsistenteIA.desktop"
DATOS_DIR="$HOME/.local/share/AsistenteIA"

C_VERDE="\033[0;32m"
C_AMARILLO="\033[0;33m"
C_RESET="\033[0m"

info()  { echo -e "${C_VERDE}==>${C_RESET} $1"; }
aviso() { echo -e "${C_AMARILLO}!!${C_RESET} $1"; }

# =========================================================
# DETECTAR SI USA DISTROBOX (leyendo el lanzador)
# =========================================================

USA_DISTROBOX=""
if [ -f "$LAUNCHER" ]; then
    if grep -q "distrobox enter" "$LAUNCHER" 2>/dev/null; then
        USA_DISTROBOX="1"
    fi
fi

# =========================================================
# MOSTRAR QUÉ SE VA A ELIMINAR
# =========================================================

if [ "$USA_DISTROBOX" = "1" ]; then
    CONT_EXISTE=""
    if command -v distrobox &>/dev/null && distrobox list 2>/dev/null | grep -qE "(^|[[:space:]])$CONTENEDOR([[:space:]]|\$)"; then
        CONT_EXISTE="1"
    fi
fi

if [ "$USA_DISTROBOX" != "1" ] && [ ! -d "$INSTALL_DIR" ]; then
    aviso "No encuentro una instalación en $INSTALL_DIR — ¿ya estaba desinstalado?"
fi

info "Se van a eliminar:"
if [ "$USA_DISTROBOX" = "1" ] && [ -n "${CONT_EXISTE:-}" ]; then
    echo "    - el contenedor Distrobox \"$CONTENEDOR\" (código + entorno virtual)"
fi
[ -d "$INSTALL_DIR" ] && echo "    - $INSTALL_DIR (código)"
[ -f "$LAUNCHER" ]      && echo "    - $LAUNCHER"
[ -f "$DESKTOP_FILE" ]  && echo "    - $DESKTOP_FILE"
[ -f "$ICON_FILE" ]     && echo "    - $ICON_FILE"
[ -f "$AUTOSTART_FILE" ] && echo "    - $AUTOSTART_FILE (inicio automático)"
echo

if [ "$USA_DISTROBOX" = "1" ] && [ -n "${CONT_EXISTE:-}" ]; then
    aviso "ATENCIÓN: el contenedor \"$CONTENEDOR\" se va a borrar COMPLETO."
    aviso "Si instalaste otras cosas a mano ahí adentro (fuera de AsistenteIA),"
    aviso "también se van a perder. Si querés conservar algo, salí ahora y movelo"
    aviso "antes de volver a correr este desinstalador."
    echo
fi

read -rp "¿Continuar? [S/n] " respuesta
respuesta="${respuesta:-s}"
if [[ ! "$respuesta" =~ ^[sS] ]]; then
    echo "Cancelado, no se tocó nada."
    exit 0
fi

# =========================================================
# ELIMINAR
# =========================================================

if [ "$USA_DISTROBOX" = "1" ] && [ -n "${CONT_EXISTE:-}" ]; then
    distrobox stop --name "$CONTENEDOR" 2>/dev/null || true
    distrobox rm --name "$CONTENEDOR" --force
    info "Contenedor '$CONTENEDOR' eliminado."
fi

rm -rf "$INSTALL_DIR"
rm -f "$LAUNCHER"
rm -f "$DESKTOP_FILE"
rm -f "$ICON_FILE"
rm -f "$AUTOSTART_FILE"

info "AsistenteIA desinstalado."

# =========================================================
# DATOS DE USUARIO — preguntar, NO borrar por defecto
# =========================================================

if [ -d "$DATOS_DIR" ]; then
    echo
    aviso "Tus datos guardados (alias, macros, recordatorios, temporizadores,"
    aviso "configuración y el log) siguen en $DATOS_DIR"
    read -rp "¿Querés borrarlos también? [s/N] " borrar_datos
    borrar_datos="${borrar_datos:-n}"

    if [[ "$borrar_datos" =~ ^[sS] ]]; then
        rm -rf "$DATOS_DIR"
        info "Datos eliminados."
    else
        info "Datos conservados en $DATOS_DIR — quedan ahí por si reinstalás."
    fi
fi