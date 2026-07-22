#!/usr/bin/env bash
# =========================================================
# build_linux.sh
#
# Corré esto DENTRO de WSL2 (Ubuntu), parado en la carpeta raíz
# del proyecto (donde está main.py y asistente_linux.spec). Genera:
#
#   dist_paquete/AsistenteIA-linux.tar.gz
#       Binario compilado con PyInstaller + instalador/desinstalador.
#       Para distros tradicionales (Ubuntu, Arch, Fedora Workstation).
#
#   AsistenteIA-Bazzite-Instalar.sh
#       Autoextraíble con código fuente + instalador unificado.
#       Para distros atómicas (Bazzite, Silverblue, uBlue).
#
# El paquete "linux" incluye el script de instalación unificado
# (que ya sabe detectar ostree), así que técnicamente funciona en
# cualquier distro. La versión PyInstaller es más rápida de arrancar
# (no compila nada), mientras que la versión fuente+bazzite no
# necesita PyInstaller y es más portable entre versiones de Python.
#
# Uso:
#   chmod +x build_linux.sh
#   ./build_linux.sh
# =========================================================

set -e

NOMBRE_APP="AsistenteIA"
CARPETA_SALIDA="dist_paquete"

echo "== 1. Dependencias de sistema (Ubuntu/Debian) =="
sudo apt update
sudo apt install -y \
    python3 python3-venv python3-pip python3-dev python3-tk python3-gi \
    portaudio19-dev \
    wmctrl xdotool playerctl pulseaudio-utils \
    espeak-ng \
    gir1.2-appindicator3-0.1 gir1.2-gtk-3.0 \
    binutils \
    pkg-config libsdl2-dev libsdl2-image-dev libsdl2-mixer-dev \
    libsdl2-ttf-dev libfreetype6-dev libportmidi-dev libjpeg-dev libpng-dev

echo "== 2. Entorno virtual (con acceso a paquetes de sistema) =="
rm -rf .venv_build
python3 -m venv --system-site-packages .venv_build
source .venv_build/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

# =========================================================
# PAQUETE 1: binario PyInstaller (para distros tradicionales)
# =========================================================

echo "== 3. Construyendo binario con PyInstaller (modo carpeta) =="
pyinstaller asistente_linux.spec --noconfirm

echo "== 4. Armando el paquete .tar.gz =="
rm -rf "$CARPETA_SALIDA"
mkdir -p "$CARPETA_SALIDA"

cp -r "dist/$NOMBRE_APP" "$CARPETA_SALIDA/$NOMBRE_APP"
cp instalador_linux.sh "$CARPETA_SALIDA/$NOMBRE_APP/instalar.sh"
cp desinstalador_linux.sh "$CARPETA_SALIDA/$NOMBRE_APP/"

# El archivo .desktop genérico lo genera el instalador unificado
# en el momento, así que no hace falta copiarlo acá.

chmod +x "$CARPETA_SALIDA/$NOMBRE_APP/instalar.sh"
chmod +x "$CARPETA_SALIDA/$NOMBRE_APP/desinstalador_linux.sh"
chmod +x "$CARPETA_SALIDA/$NOMBRE_APP/$NOMBRE_APP"

cd "$CARPETA_SALIDA"
tar -czf "${NOMBRE_APP}-linux.tar.gz" "$NOMBRE_APP"
cd ..

echo "    -> $CARPETA_SALIDA/${NOMBRE_APP}-linux.tar.gz"

# =========================================================
# PAQUETE 2: autoextraíble fuente (para distros atómicas)
# =========================================================

echo "== 5. Armando el paquete autoextraíble para Bazzite =="
chmod +x armar_paquete_bazzite.sh
./armar_paquete_bazzite.sh

deactivate

echo ""
echo "===================================================="
echo "Listo. Entregables generados:"
echo "  1. $CARPETA_SALIDA/${NOMBRE_APP}-linux.tar.gz    (PyInstaller, distros normales)"
echo "  2. ${NOMBRE_APP}-Bazzite-Instalar.sh             (autoextraíble, distros atómicas)"
echo "===================================================="