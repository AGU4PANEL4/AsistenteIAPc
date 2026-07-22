#!/usr/bin/env bash
#
# desinstalador_bazzite.sh
#
# Desinstalador de AsistenteIA para Bazzite — pareja de
# instalador_bazzite.sh. Elimina el contenedor Distrobox completo
# (código + entorno virtual, todo lo que vive adentro), el lanzador,
# el ícono y la entrada del menú, y el autostart si estaba activado.
#
# Igual que desisntalador_linux.sh (la versión para distros
# tradicionales): pregunta ANTES de tocar tus datos (alias, macros,
# recordatorios, config) — con "no borrar" como opción por defecto.
#
# Uso: chmod +x desinstalador_bazzite.sh && ./desinstalador_bazzite.sh

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

CONTENEDOR_EXISTE=""
if command -v distrobox &>/dev/null && distrobox list 2>/dev/null | grep -qE "(^|[[:space:]])$CONTENEDOR([[:space:]]|\$)"; then
    CONTENEDOR_EXISTE="1"
fi

if [ -z "$CONTENEDOR_EXISTE" ] && [ ! -d "$INSTALL_DIR" ]; then
    aviso "No encuentro ni el contenedor '$CONTENEDOR' ni $INSTALL_DIR — ¿ya estaba desinstalado?"
fi

info "Se van a eliminar:"
if [ -n "$CONTENEDOR_EXISTE" ]; then
    echo "    - el contenedor Distrobox \"$CONTENEDOR\" (código + entorno virtual)"
fi
echo "    - $INSTALL_DIR (si quedó algo suelto en el host)"
echo "    - $LAUNCHER"
echo "    - $DESKTOP_FILE"
echo "    - $ICON_FILE"
[ -f "$AUTOSTART_FILE" ] && echo "    - $AUTOSTART_FILE (inicio automático estaba activado)"

read -rp "¿Continuar? [S/n] " respuesta
respuesta="${respuesta:-s}"
if [[ ! "$respuesta" =~ ^[sS] ]]; then
    echo "Cancelado, no se tocó nada."
    exit 0
fi

if [ -n "$CONTENEDOR_EXISTE" ]; then
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
# Mismo criterio que instalador.iss (Windows) y desisntalador_linux.sh:
# MB_DEFBUTTON2 / "n" por defecto, más seguro ante un Enter sin pensar.
# Esta carpeta vive en el HOST vía XDG (rutas_datos.py) — nunca
# estuvo adentro del contenedor, así que sobrevive intacta a la
# eliminación del contenedor de arriba, tal como se espera.
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
        info "Datos conservados en $DATOS_DIR — quedan ahí por si reinstalás más adelante."
    fi
fi
