#!/usr/bin/env bash
#
# instalador_bazzite.sh
#
# Instalador de AsistenteIA para Bazzite (y en general cualquier
# distro "atómica" basada en rpm-ostree: Silverblue, Kinoite, uBlue,
# etc). En estas distros el filesystem raíz es de SOLO LECTURA y no
# se puede hacer "dnf install" directo como en una distro tradicional
# (ver instalador_linux.sh) — instalar algo a nivel de sistema con
# rpm-ostree exige reiniciar, y encima Bazzite lo desaconseja para no
# arriesgar romper las actualizaciones atómicas.
#
# La forma estándar de instalar herramientas con dependencias de
# sistema en una distro atómica es adentro de un contenedor de
# Distrobox — que Bazzite trae PREINSTALADO de fábrica. Un contenedor
# de Distrobox comparte automáticamente con el sistema anfitrión:
#   - tu carpeta $HOME completa (mismas rutas adentro y afuera)
#   - el servidor gráfico (X11 / XWayland — Tkinter funciona igual)
#   - el audio (PipeWire/PulseAudio — el micrófono funciona igual)
#   - D-Bus y systemd (apagar/reiniciar/suspender desde el asistente
#     sigue funcionando, porque esas llamadas viajan al systemd del
#     anfitrión, no a uno propio del contenedor)
# así que, aunque el asistente corra "adentro" del contenedor, se
# siente exactamente igual que corriendo instalado directo.
#
# Qué hace este script:
#   1. Verifica que estás en una distro atómica y que Distrobox existe.
#   2. Crea un contenedor Fedora normal ("asistente-ia") si no existe.
#   3. Instala ADENTRO del contenedor las dependencias de sistema
#      (dnf normal, SIN rpm-ostree, SIN reiniciar — la ventaja real
#      de hacerlo así).
#   4. Copia el código fuente a ~/.local/opt/asistente-ia (en el
#      HOST — Distrobox ya lo hace visible adentro del contenedor
#      con la misma ruta, sin duplicar nada).
#   5. Crea el entorno virtual e instala las dependencias de Python
#      ADENTRO del contenedor (necesita el compilador/portaudio-devel
#      recién instalados para compilar PyAudio).
#   6. Crea un lanzador en ~/.local/bin, un ícono, y una entrada en
#      el menú de aplicaciones — igual que instalador_linux.sh, pero
#      el lanzador entra al contenedor antes de correr el asistente.
#
# Uso: parado DENTRO de la carpeta del código fuente (donde está
# main.py):
#   chmod +x instalador_bazzite.sh && ./instalador_bazzite.sh
#
# AVISO IMPORTANTE: este script se armó a partir de cómo funcionan
# Distrobox/rpm-ostree/Bazzite documentados, pero NO se probó en una
# instalación real (no hay una máquina Linux disponible para probarlo
# del lado de quien lo escribió). Si algo falla, el mensaje debería
# indicar en qué paso — mandalo de vuelta con el error exacto para
# poder ajustarlo. Para diagnosticar a mano, ver la sección
# "SI ALGO FALLA" al final de este archivo.

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
# 0. VERIFICACIONES PREVIAS
# =========================================================

if [ ! -f "$ORIGEN/main.py" ]; then
    error "No encuentro main.py en '$ORIGEN'."
    error "Corré este script parado dentro de la carpeta del código fuente del asistente."
    exit 1
fi

# /run/ostree-booted existe en CUALQUIER sistema basado en ostree
# (Silverblue, Kinoite, Bazzite, uBlue en general) — es la forma
# estándar de detectar "estoy en una distro atómica" sin depender
# de adivinar el nombre exacto de la distro.
if [ ! -f /run/ostree-booted ]; then
    aviso "Este sistema no parece ser una distro atómica (rpm-ostree/ostree)."
    aviso "Si estás en Ubuntu, Fedora Workstation, Arch, etc. usá instalador_linux.sh en cambio — es más directo y no necesita Distrobox."
    read -rp "¿Continuar de todas formas con el instalador de Bazzite? [s/N] " respuesta
    respuesta="${respuesta:-n}"
    if [[ ! "$respuesta" =~ ^[sS] ]]; then
        exit 0
    fi
fi

if ! command -v podman &>/dev/null; then
    error "No encuentro 'podman' — Bazzite lo trae de fábrica, así que si falta algo raro pasó con esta instalación del sistema."
    exit 1
fi

if ! command -v distrobox &>/dev/null; then
    error "No encuentro 'distrobox'. Bazzite lo trae preinstalado normalmente."
    error "Si por algún motivo falta, instalalo con:"
    error "    rpm-ostree install distrobox"
    error "y reiniciá la PC antes de volver a correr este script."
    exit 1
fi

PYTHON_CONTENEDOR_OK=""  # se completa más abajo, informativo al final

# =========================================================
# 1. CONTENEDOR DISTROBOX
# =========================================================

info "Paso 1/6 — contenedor Distrobox ('$CONTENEDOR')"

if distrobox list 2>/dev/null | grep -qE "(^|[[:space:]])$CONTENEDOR([[:space:]]|\$)"; then
    aviso "Ya existe el contenedor '$CONTENEDOR' — se reutiliza (no se recrea desde cero)."
else
    distrobox create --yes --name "$CONTENEDOR" --image "$IMAGEN"
fi

# =========================================================
# 2. DEPENDENCIAS DE SISTEMA — DENTRO del contenedor
# dnf normal, sin rpm-ostree, sin reiniciar: esa es la ventaja real
# de hacer todo esto adentro de Distrobox en vez de en el host.
# =========================================================

info "Paso 2/6 — dependencias de sistema dentro del contenedor (puede pedir tu contraseña)"

distrobox enter --name "$CONTENEDOR" -- sudo dnf install -y \
    python3 python3-pip python3-virtualenv python3-tkinter python3-devel \
    portaudio-devel wmctrl xdotool playerctl pulseaudio-utils gcc redhat-rpm-config \
    pkgconf-pkg-config SDL2-devel SDL2_image-devel SDL2_mixer-devel SDL2_ttf-devel \
    freetype-devel libjpeg-turbo-devel libpng-devel portmidi-devel

# FIX/NUEVO: las últimas ocho (pkgconf-pkg-config/SDL2-devel/.../
# portmidi-devel) faltaban en la versión original de este script.
# El paquete "fedora:latest" usado para el contenedor trae la versión
# de Python más reciente de Fedora en cada momento (ej. 3.14 a mediados
# de 2026) — y pygame suele tardar en publicar wheels precompilados
# para versiones de Python recién salidas, así que pip cae a compilar
# pygame desde el código fuente, lo cual necesita las cabeceras de
# desarrollo de SDL2/freetype/etc para funcionar (si faltan, falla con
# "Unable to run sdl-config" o errores de pkg-config sobre freetype2).
# Es EXACTAMENTE el mismo problema (y la misma lista de paquetes,
# traducida de apt a dnf) que requirements.txt y build_linux.sh ya
# documentan para la instalación normal de Linux — solo que acá no se
# había trasladado a la versión de Bazzite.

# =========================================================
# 3. COPIAR CÓDIGO FUENTE — en el HOST
# Distrobox comparte $HOME automáticamente, así que lo que se copia
# acá ya es visible adentro del contenedor con la MISMA ruta, sin
# ningún paso extra de sincronización.
# =========================================================

info "Paso 3/6 — copiando el código a $INSTALL_DIR"

if [ -d "$INSTALL_DIR" ]; then
    aviso "Ya existe una instalación anterior en $INSTALL_DIR — se actualiza el código, conservando el entorno virtual si ya estaba creado."
fi

mkdir -p "$INSTALL_DIR"
cp "$ORIGEN"/*.py "$INSTALL_DIR/"
cp "$ORIGEN/requirements.txt" "$INSTALL_DIR/"

# test.py es un archivo suelto de prueba manual, no parte del
# asistente en sí — se excluye si existe.
rm -f "$INSTALL_DIR/test.py"

# =========================================================
# 4. ENTORNO VIRTUAL + DEPENDENCIAS DE PYTHON — DENTRO del contenedor
# =========================================================

info "Paso 4/6 — entorno virtual e instalación de dependencias (puede tardar varios minutos)"

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

# =========================================================
# 5. LANZADOR
# El lanzador vive en el HOST, pero su único trabajo es entrar al
# contenedor y correr el asistente ahí adentro — 'distrobox enter'
# ya se encarga de exponerle X11/audio/D-Bus del host automáticamente.
# =========================================================

info "Paso 5/6 — creando el lanzador en $LAUNCHER"

mkdir -p "$BIN_DIR"

cat > "$LAUNCHER" << EOF
#!/usr/bin/env bash
# Lanzador de AsistenteIA — generado por instalador_bazzite.sh.
# Arranca DENTRO del contenedor Distrobox '$CONTENEDOR'.
exec distrobox enter --name "$CONTENEDOR" -- bash -c "cd '$INSTALL_DIR' && source venv/bin/activate && exec python3 main.py"
EOF

chmod +x "$LAUNCHER"

if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    aviso "$BIN_DIR no está en tu PATH todavía."
    aviso "Agregá esta línea a tu ~/.bashrc (o ~/.zshrc) y abrí una terminal nueva:"
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# =========================================================
# 6. ÍCONO + ENTRADA EN EL MENÚ DE APLICACIONES
# =========================================================

info "Paso 6/6 — ícono y entrada en el menú de aplicaciones"

mkdir -p "$ICON_DIR" "$DESKTOP_DIR"

# se genera con el Python del VENV DENTRO del contenedor (ya tiene
# Pillow instalado vía requirements.txt) — se corre con
# 'distrobox enter' en vez de invocar el binario directo desde el
# host, porque un ejecutable compilado/enlazado adentro del
# contenedor puede depender de una versión de glibc distinta a la
# del host; entrar al contenedor asegura que corre en su propio
# entorno consistente.
distrobox enter --name "$CONTENEDOR" -- "$INSTALL_DIR/venv/bin/python3" - << EOF
from PIL import Image, ImageDraw
img = Image.new("RGBA", (256, 256), (11, 26, 31, 255))
draw = ImageDraw.Draw(img)
draw.ellipse((56, 56, 200, 200), fill=(45, 230, 192, 255))
img.save("$ICON_FILE")
EOF

cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=$NOMBRE_APP
Comment=Asistente de voz con IA (corre en un contenedor Distrobox)
Exec=$LAUNCHER
Icon=$ICON_FILE
Terminal=false
Categories=Utility;
EOF

chmod +x "$DESKTOP_FILE"

# =========================================================
# LISTO
# =========================================================

echo
info "Instalación completa."
echo "    Corré el asistente con:  asistente-ia"
echo "    o buscá \"$NOMBRE_APP\" en el menú de aplicaciones."
echo
echo "    El código y el entorno virtual viven ADENTRO del contenedor"
echo "    Distrobox \"$CONTENEDOR\" (aunque los archivos .py están en"
echo "    $INSTALL_DIR, visibles desde el host porque Distrobox"
echo "    comparte tu \$HOME)."
echo
echo "    Tus datos (alias, macros, recordatorios, config) viven en"
echo "    ~/.local/share/AsistenteIA — separados del código/contenedor,"
echo "    así que desinstalar o reinstalar nunca los toca."
echo
aviso "Nota sobre la ventana: el truco de esquinas redondeadas del"
aviso "orbe necesita X11 (vía XWayland) — Bazzite corre Wayland por"
aviso "defecto, pero XWayland suele estar activo igual (Steam y la"
aviso "mayoría de juegos lo necesitan). Si por algún motivo no está,"
aviso "el asistente sigue funcionando perfecto, solo que el orbe se"
aviso "ve como un cuadrado en vez de un círculo — puramente estético."
echo
echo "    El inicio automático con el sistema NO se activa acá —"
echo "    decile al asistente \"activa el inicio automático\" una vez"
echo "    que lo hayas probado, si querés que arranque solo."

# =========================================================
# SI ALGO FALLA
#
# Para ver los mensajes de consola del asistente en vivo (útil para
# diagnosticar cualquier error, ya que el lanzador normal no muestra
# una terminal), corré esto a mano:
#
#   distrobox enter --name asistente-ia -- bash -c \
#     "cd ~/.local/opt/asistente-ia && source venv/bin/activate && python3 main.py"
#
# Eso corre el asistente igual que el lanzador, pero con la consola
# a la vista — cualquier traceback de Python o mensaje de
# [Bandeja]/[TTS]/[Groq]/etc. va a aparecer ahí en texto plano.
# =========================================================