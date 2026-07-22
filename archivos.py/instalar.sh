#!/usr/bin/env bash
# =========================================================
# instalar.sh
#
# Esto lo corre tu AMIGO, una vez que descomprime el .tar.gz que
# le mandaste. Deja el asistente instalado y accesible desde el
# menú de aplicaciones, como cualquier programa normal.
#
# Uso:
#   tar -xzf AsistenteIA-linux.tar.gz
#   cd AsistenteIA
#   chmod +x instalar.sh
#   ./instalar.sh
# =========================================================

set -e

NOMBRE_APP="AsistenteIA"
# IMPORTANTE: el asistente YA usa ~/.local/share/AsistenteIA para
# GUARDAR SUS DATOS (config.json, aliases.json, macros.json, el log,
# etc — ver rutas_datos.py, estándar XDG). Por eso el PROGRAMA en sí
# (el binario + sus dependencias empaquetadas) se instala en una
# carpeta DISTINTA, ~/.local/lib — si usáramos la misma carpeta,
# reinstalar o actualizar borraría por accidente los datos guardados
# del usuario cada vez.
CARPETA_INSTALACION="$HOME/.local/lib/$NOMBRE_APP"
CARPETA_BIN="$HOME/.local/bin"
CARPETA_LANZADORES="$HOME/.local/share/applications"

echo "== Instalando $NOMBRE_APP =="

echo ""
echo "Este asistente necesita algunas herramientas del sistema para"
echo "funcionar del todo (control de ventanas, medios, voz, ícono de"
echo "bandeja). ¿Instalarlas ahora con apt? Puede pedir tu contraseña. (s/n)"
read -r RESPUESTA

if [[ "$RESPUESTA" == "s" || "$RESPUESTA" == "S" ]]; then
    sudo apt update
    sudo apt install -y \
        wmctrl xdotool playerctl pulseaudio-utils \
        espeak-ng \
        gir1.2-appindicator3-0.1 gir1.2-gtk-3.0 \
        portaudio19-dev
else
    echo "Ok, salteado — podés instalarlas después con:"
    echo "  sudo apt install wmctrl xdotool playerctl pulseaudio-utils espeak-ng gir1.2-appindicator3-0.1 gir1.2-gtk-3.0 portaudio19-dev"
fi

echo "== Copiando archivos =="
# se copia la carpeta ENTERA (el ejecutable + su carpeta interna de
# dependencias que armó PyInstaller) — no es un solo archivo suelto.
rm -rf "$CARPETA_INSTALACION"
mkdir -p "$CARPETA_INSTALACION"
cp -r ./_internal "$CARPETA_INSTALACION/" 2>/dev/null || true
cp "$NOMBRE_APP" "$CARPETA_INSTALACION/"
chmod +x "$CARPETA_INSTALACION/$NOMBRE_APP"

mkdir -p "$CARPETA_BIN"
ln -sf "$CARPETA_INSTALACION/$NOMBRE_APP" "$CARPETA_BIN/asistente-ia"

echo "== Instalando lanzador (menú de aplicaciones) =="
mkdir -p "$CARPETA_LANZADORES"
sed "s|__RUTA_BINARIO__|$CARPETA_INSTALACION/$NOMBRE_APP|g" asistente-ia.desktop \
    > "$CARPETA_LANZADORES/asistente-ia.desktop"
chmod +x "$CARPETA_LANZADORES/asistente-ia.desktop"

echo ""
echo "===================================================="
echo "Listo. Podés:"
echo "  - Buscar 'Asistente IA' en el menú de aplicaciones, o"
echo "  - Correr 'asistente-ia' desde una terminal"
echo "    (puede que necesites abrir una terminal nueva, o correr"
echo "     'source ~/.bashrc', para que el PATH se actualice)"
echo ""
echo "Datos del asistente (config, alias, macros, log) van en:"
echo "  ${XDG_DATA_HOME:-$HOME/.local/share}/AsistenteIA"
echo "===================================================="
