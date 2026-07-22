#!/usr/bin/env bash
#
# instalador_linux.sh
#
# Instalador UNIFICADO de AsistenteIA para Linux.
#
# Detecta automáticamente el tipo de sistema y usa la estrategia
# correcta sin que tengas que saber de antemano:
#
#   - Distro tradicional (Ubuntu, Fedora Workstation, Arch, openSUSE):
#     instala dependencias de sistema con el gestor de paquetes
#     nativo (apt/dnf/pacman/zypper), crea un venv en el host,
#     lanzador directo — instalación clásica y liviana.
#
#   - Distro atómica (Bazzite, Silverblue, Kinoite, uBlue):
#     crea un contenedor Distrobox con Fedora, instala todo ahí
#     adentro SIN rpm-ostree y SIN necesidad de reiniciar. El
#     lanzador entra al contenedor automáticamente.
#
#   - Distro atómica sin Distrobox:
#     intenta instalarlo a nivel de host con rpm-ostree y te avisa
#     que vas a tener que reiniciar.
#
# Qué hace en cualquier caso:
#   1. Instala dependencias de sistema (el método varía según distro).
#   2. Copia el código fuente a ~/.local/opt/asistente-ia.
#   3. Crea un entorno virtual e instala dependencias Python.
#   4. Crea un lanzador en ~/.local/bin, ícono y entrada de menú.
#
# Uso: parado DENTRO de la carpeta del código fuente (donde está
# main.py):
#   chmod +x instalador_linux.sh && ./instalador_linux.sh
#
# AVISO: la ruta de distro atómica con Distrobox se armó a partir de
# la documentación de Bazzite/Distrobox pero NO se probó en una
# instalación real.

set -euo pipefail

NOMBRE_APP="AsistenteIA"
CONTENEDOR="asistente-ia"
IMAGEN="fedora:latest"

INSTALL_DIR="$HOME/.local/opt/asistente-ia"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
LAUNCHER="$BIN_DIR/asistente-ia"
DESKTOP_FILE="$DESKTOP_DIR/asistente-ia.desktop"
ICON_FILE="$ICON_DIR/asistente-ia.png"

ORIGEN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

C_VERDE="\033[0;32m"
C_AMARILLO="\033[0;33m"
C_ROJO="\033[0;31m"
C_RESET="\033[0m"

info()  { echo -e "${C_VERDE}==>${C_RESET} $1"; }
aviso() { echo -e "${C_AMARILLO}!!${C_RESET} $1"; }
error() { echo -e "${C_ROJO}xx${C_RESET} $1"; }

# =========================================================
# 0. VERIFICACIONES PREVIAS Y DETECCIÓN DE ESTRATEGIA
# =========================================================

if [ ! -f "$ORIGEN/main.py" ]; then
    error "No encuentro main.py en '$ORIGEN'."
    error "Corré este script parado dentro de la carpeta del código fuente del asistente."
    exit 1
fi

# Detecta si estamos en una distro atómica.
# /run/ostree-booted existe en CUALQUIER ostree (Silverblue, Kinoite,
# Bazzite, uBlue) — estándar de facto, sin depender de /etc/os-release.
if [ -f /run/ostree-booted ]; then
    MODO="atomico"

    if command -v distrobox &>/dev/null; then
        info "Sistema atómico detectado (ostree). Estrategia: Distrobox."
        ESTRATEGIA="distrobox"
    else
        aviso "Sistema atómico detectado (ostree) pero sin Distrobox."
        aviso "Instalar con rpm-ostree requiere reiniciar al terminar."
        read -rp "¿Querés intentar con rpm-ostree? [s/N] " respuesta
        respuesta="${respuesta:-n}"
        if [[ "$respuesta" =~ ^[sS] ]]; then
            ESTRATEGIA="rpm-ostree"
        else
            error "Instalá Distrobox primero y volvé a correr este script."
            exit 1
        fi
    fi
else
    MODO="tradicional"
    info "Sistema tradicional detectado. Estrategia: instalación directa."
    ESTRATEGIA="directa"
fi

# =========================================================
# 1. DEPENDENCIAS DE SISTEMA — según estrategia
# =========================================================

info "Paso 1/5 — dependencias de sistema"

if [ "$ESTRATEGIA" = "directa" ]; then
    GESTO=""
    PAQUETES=""

    if command -v apt-get &>/dev/null; then
        GESTO="apt-get"
        PAQUETES="python3-venv python3-pip python3-tk python3-dev portaudio19-dev wmctrl xdotool playerctl pulseaudio-utils"
    elif command -v dnf &>/dev/null; then
        GESTO="dnf"
        PAQUETES="python3-tkinter python3-devel portaudio-devel wmctrl xdotool playerctl pulseaudio-utils"
    elif command -v pacman &>/dev/null; then
        GESTO="pacman"
        PAQUETES="tk portaudio wmctrl xdotool playerctl libpulse"
    elif command -v zypper &>/dev/null; then
        GESTO="zypper"
        PAQUETES="python3-tk python3-devel portaudio-devel wmctrl xdotool playerctl pulseaudio-utils"
    else
        aviso "No reconozco tu gestor de paquetes (probé apt-get/dnf/pacman/zypper)."
        aviso "Instalá manualmente: entorno Tk para Python, portaudio (con headers),"
        aviso "wmctrl, xdotool, playerctl, y las utilidades de PulseAudio/PipeWire."
    fi

    if [ -n "$GESTO" ] && [ -n "$PAQUETES" ]; then
        info "Gestor de paquetes: $GESTO"
        echo "    Se van a instalar (necesita contraseña de admin):"
        echo "    $PAQUETES"
        read -rp "    ¿Continuar? [S/n] " respuesta
        respuesta="${respuesta:-s}"

        if [[ "$respuesta" =~ ^[sS] ]]; then
            case "$GESTO" in
                apt-get)
                    sudo apt-get update -qq
                    sudo apt-get install -y $PAQUETES
                    ;;
                dnf)
                    sudo dnf install -y $PAQUETES
                    ;;
                pacman)
                    sudo pacman -S --needed --noconfirm $PAQUETES
                    ;;
                zypper)
                    sudo zypper install -y $PAQUETES
                    ;;
            esac
        else
            aviso "Se omitió la instalación de dependencias de sistema."
        fi
    fi

elif [ "$ESTRATEGIA" = "distrobox" ]; then
    if ! command -v podman &>/dev/null; then
        error "No encuentro 'podman'. Las distros atómicas lo traen de fábrica."
        exit 1
    fi

    info "Creando contenedor Distrobox ('$CONTENEDOR')..."
    if distrobox list 2>/dev/null | grep -qE "(^|[[:space:]])$CONTENEDOR([[:space:]]|\$)"; then
        aviso "Ya existe el contenedor '$CONTENEDOR' — se reutiliza."
    else
        distrobox create --yes --name "$CONTENEDOR" --image "$IMAGEN"
    fi

    info "Instalando paquetes dentro del contenedor (sin reiniciar)..."
    distrobox enter --name "$CONTENEDOR" -- sudo dnf install -y \
        python3 python3-pip python3-virtualenv python3-tkinter python3-devel \
        portaudio-devel wmctrl xdotool playerctl pulseaudio-utils gcc redhat-rpm-config

elif [ "$ESTRATEGIA" = "rpm-ostree" ]; then
    info "Instalando dependencias con rpm-ostree (VA A PEDIR REINICIAR)..."
    sudo rpm-ostree install -y \
        python3 python3-pip python3-virtualenv python3-tkinter python3-devel \
        portaudio-devel wmctrl xdotool playerctl pulseaudio-utils gcc
    aviso "Reiniciá la PC antes de seguir usando el asistente."
fi

# =========================================================
# 2. COPIAR CÓDIGO FUENTE
# =========================================================

info "Paso 2/5 — copiando el código a $INSTALL_DIR"

if [ -d "$INSTALL_DIR" ]; then
    aviso "Ya existe una instalación anterior en $INSTALL_DIR — se actualiza el código,"
    aviso "conservando el entorno virtual si ya estaba creado."
fi

mkdir -p "$INSTALL_DIR"

cp "$ORIGEN"/*.py "$INSTALL_DIR/"
cp "$ORIGEN/requirements.txt" "$INSTALL_DIR/"

# se excluyen archivos que no son parte del asistente
rm -f "$INSTALL_DIR/test.py"
rm -rf "$INSTALL_DIR/tests"
rm -f "$INSTALL_DIR/install.sh"
rm -f "$INSTALL_DIR/asistente-ia.desktop"

# =========================================================
# 3. ENTORNO VIRTUAL + DEPENDENCIAS PYTHON
# =========================================================

info "Paso 3/5 — entorno virtual e instalación de dependencias Python (puede tardar)"

if [ "$ESTRATEGIA" = "distrobox" ]; then
    distrobox enter --name "$CONTENEDOR" -- bash -c "
        set -e
        cd '$INSTALL_DIR'
        if [ ! -d venv ]; then
            python3 -m venv venv
        fi
        source venv/bin/activate
        pip install --upgrade pip --quiet
        pip install -r requirements.txt
    "
else
    if [ ! -d "$INSTALL_DIR/venv" ]; then
        python3 -m venv "$INSTALL_DIR/venv"
    fi
    source "$INSTALL_DIR/venv/bin/activate"
    pip install --upgrade pip --quiet
    pip install -r "$INSTALL_DIR/requirements.txt"
    deactivate
fi

# =========================================================
# 4. LANZADOR
# =========================================================

info "Paso 4/5 — creando el lanzador en $LAUNCHER"

mkdir -p "$BIN_DIR"

if [ "$ESTRATEGIA" = "distrobox" ]; then
    cat > "$LAUNCHER" << LAUNCHER_EOF
#!/usr/bin/env bash
# Lanzador de AsistenteIA — genera ejecutado por instalador_linux.sh.
# Corre DENTRO del contenedor Distrobox '$CONTENEDOR'.
exec distrobox enter --name "$CONTENEDOR" -- bash -c "cd '$INSTALL_DIR' && source venv/bin/activate && exec python3 main.py"
"
LAUNCHER_EOF
else
    cat > "$LAUNCHER" << LAUNCHER_EOF
#!/usr/bin/env bash
# Lanzador de AsistenteIA — genera ejecutado por instalador_linux.sh.
cd "$INSTALL_DIR"
source "$INSTALL_DIR/venv/bin/activate"
exec python3 "$INSTALL_DIR/main.py" "\$@"
LAUNCHER_EOF
fi

chmod +x "$LAUNCHER"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    aviso "$BIN_DIR no está en tu PATH todavía."
    echo "    Agregá esto a ~/.bashrc (o ~/.zshrc):"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# =========================================================
# 5. ÍCONO + ENTRADA EN EL MENÚ DE APLICACIONES
# =========================================================

info "Paso 5/5 — ícono y entrada en el menú de aplicaciones"

mkdir -p "$ICON_DIR" "$DESKTOP_DIR"

_generar_icono() {
    "$@" - << 'ICON_EOF'
from PIL import Image, ImageDraw
img = Image.new("RGBA", (256, 256), (11, 26, 31, 255))
draw = ImageDraw.Draw(img)
draw.ellipse((56, 56, 200, 200), fill=(45, 230, 192, 255))
img.save(ICO_PATH)
ICON_EOF
}

if [ "$ESTRATEGIA" = "distrobox" ]; then
    ICO_PATH="$ICON_FILE" _generar_icono distrobox enter --name "$CONTENEDOR" -- "$INSTALL_DIR/venv/bin/python3"
else
    ICO_PATH="$ICON_FILE" _generar_icono "$INSTALL_DIR/venv/bin/python3"
fi

COMMENT_LINE=""
if [ "$ESTRATEGIA" = "distrobox" ]; then
    COMMENT_LINE="Comment=Asistente de voz con IA (corre en un contenedor Distrobox)"
else
    COMMENT_LINE="Comment=Asistente de voz con IA"
fi

cat > "$DESKTOP_FILE" << DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=$NOMBRE_APP
$COMMENT_LINE
Exec=$LAUNCHER
Icon=$ICON_FILE
Terminal=false
Categories=Utility;
DESKTOP_EOF

chmod +x "$DESKTOP_FILE"

# =========================================================
# LISTO
# =========================================================

echo
info "Instalación completa."
echo "    Corré el asistente con:  asistente-ia"
echo "    o buscá \"$NOMBRE_APP\" en el menú de aplicaciones."

if [ "$ESTRATEGIA" = "distrobox" ]; then
    echo
    echo "    El código y el entorno virtual viven ADENTRO del contenedor"
    echo "    Distrobox \"$CONTENEDOR\" (aunque los archivos .py están en"
    echo "    $INSTALL_DIR, visibles desde el host porque Distrobox"
    echo "    comparte tu \$HOME)."
    echo
    aviso "Nota sobre la ventana: el orbe necesita XWayland para forma"
    aviso "redonda — si XWayland no está activo, se ve cuadrado (sin"
    aviso "afectar ninguna función)."
elif [ "$ESTRATEGIA" = "rpm-ostree" ]; then
    echo
    aviso "Recordá REINICIAR la PC antes de usar el asistente, porque"
    aviso "se instalaron paquetes nuevos con rpm-ostree."
fi

echo
echo "    Tus datos (alias, macros, recordatorios, config) viven en"
echo "    ~/.local/share/AsistenteIA — reinstalar no los toca."
echo
echo "    El inicio automático con el sistema NO se activa acá —"
echo "    decile al asistente \"activa el inicio automático\" una vez"
echo "    que lo hayas probado, si querés que arranque solo."

# =========================================================
# SI ALGO FALLA
#
# Para ver los mensajes de consola en vivo:
#   DISTROBOX:
#     distrobox enter --name asistente-ia -- bash -c \
#       "cd ~/.local/opt/asistente-ia && source venv/bin/activate && python3 main.py"
#   DIRECTO / RPM-OSTREE:
#     cd ~/.local/opt/asistente-ia && source venv/bin/activate && python3 main.py
# =========================================================