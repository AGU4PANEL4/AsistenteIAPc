#!/usr/bin/env bash
#
# armar_paquete_bazzite.sh
#
# Corré esto VOS (no tu amigo) dentro de WSL2, parado en la carpeta
# raíz del proyecto (donde está main.py, instalador_bazzite.sh y
# desinstalador_bazzite.sh). Genera UN SOLO archivo:
#
#   AsistenteIA-Bazzite-Instalar.sh
#
# que es lo único que le mandás a tu amigo. Es un script
# "autoextraíble": lleva pegado adentro un .tar.gz con todo el
# código + los dos scripts de instalación/desinstalación. Al
# correrlo, se extrae solo a una carpeta temporal y ejecuta
# instalador_bazzite.sh automáticamente — el mismo concepto que un
# instalador de Inno Setup en Windows (un único .exe que trae todo
# adentro), pero con las herramientas estándar de Linux (tar/gzip,
# que están en cualquier distro) en vez de un programa aparte.
#
# Uso:
#   chmod +x armar_paquete_bazzite.sh
#   ./armar_paquete_bazzite.sh
#
# Cada vez que cambies el código del asistente, volvé a correr esto
# para generar una versión actualizada del paquete.

set -euo pipefail

ORIGEN="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SALIDA="$ORIGEN/AsistenteIA-Bazzite-Instalar.sh"

C_VERDE="\033[0;32m"
C_ROJO="\033[0;31m"
C_RESET="\033[0m"
info()  { echo -e "${C_VERDE}==>${C_RESET} $1"; }
error() { echo -e "${C_ROJO}xx${C_RESET} $1"; }

# =========================================================
# 0. VERIFICACIONES
# =========================================================

if [ ! -f "$ORIGEN/main.py" ]; then
    error "No encuentro main.py en '$ORIGEN'."
    error "Corré este script parado en la carpeta raíz del proyecto."
    exit 1
fi

if [ ! -f "$ORIGEN/instalador_bazzite.sh" ] || [ ! -f "$ORIGEN/desinstalador_bazzite.sh" ]; then
    error "Necesito instalador_bazzite.sh Y desinstalador_bazzite.sh en esta misma carpeta."
    exit 1
fi

# FIX: sin la carpeta web/ (panel.html, panel.css, panel.js) main.py
# arranca pero main_web.py no puede abrir la interfaz — pywebview tira
# 404 Not Found buscando panel.html, porque antes esta carpeta nunca se
# copiaba al paquete (mismo bug que tenía asistente.spec en Windows
# antes de declararla en datas). Se valida acá, temprano, para fallar
# con un mensaje claro en tu máquina en vez de que tu amigo instale todo
# y recién ahí, al abrir el panel, se encuentre con el error.
if [ ! -d "$ORIGEN/web" ]; then
    error "No encuentro la carpeta web/ (panel.html, panel.css, panel.js) en '$ORIGEN'."
    exit 1
fi

# =========================================================
# 1. ARMAR EL PAQUETE (.tar.gz) CON TODO LO NECESARIO
# =========================================================

info "Paso 1/2 — empaquetando el código fuente"

CARPETA_TMP="$(mktemp -d)"
trap 'rm -rf "$CARPETA_TMP"' EXIT

# todo el código .py del proyecto, salvo test.py (archivo suelto de
# prueba manual, no parte del asistente — mismo criterio que ya usa
# instalador_linux.sh)
cp "$ORIGEN"/*.py "$CARPETA_TMP/"
rm -f "$CARPETA_TMP/test.py"

cp "$ORIGEN/requirements.txt" "$CARPETA_TMP/"
cp "$ORIGEN/instalador_bazzite.sh" "$CARPETA_TMP/"
cp "$ORIGEN/desinstalador_bazzite.sh" "$CARPETA_TMP/"

# FIX/NUEVO: main.py arranca main_web.py sin importar si corre
# compilado o directo con Python — necesita la carpeta web/ completa
# (panel.html, panel.css, panel.js) para que pywebview tenga qué
# mostrar, y asistente-ia.ico/.png como ícono de ventana y de bandeja.
# Antes solo se copiaban los .py sueltos, así que del lado de tu amigo
# esto faltaba por completo y el panel tiraba 404 Not Found al
# expandirse — mismo bug que ya arreglamos en asistente.spec (Windows).
cp -r "$ORIGEN/web" "$CARPETA_TMP/"
cp "$ORIGEN/asistente-ia.ico" "$CARPETA_TMP/"
cp "$ORIGEN/asistente-ia.png" "$CARPETA_TMP/"

ARCHIVO_TAR="$CARPETA_TMP.tar.gz"
tar czf "$ARCHIVO_TAR" -C "$CARPETA_TMP" .

# =========================================================
# 2. ARMAR EL .sh AUTOEXTRAÍBLE
# El "header" (parte de arriba, texto) queda pegado directo antes
# del .tar.gz (parte de abajo, binario) en el MISMO archivo. Cuando
# se ejecuta, el header se lee a sí mismo con `tail` a partir de la
# línea siguiente al marcador, y extrae eso como el tar.gz.
# =========================================================

info "Paso 2/2 — armando el instalador autoextraíble"

cat > "$SALIDA" << 'HEADER'
#!/usr/bin/env bash
#
# AsistenteIA-Bazzite-Instalar.sh — instalador autoextraíble.
# Generado por armar_paquete_bazzite.sh — no editar a mano.
#
# Uso:
#   chmod +x AsistenteIA-Bazzite-Instalar.sh
#   ./AsistenteIA-Bazzite-Instalar.sh
#
# Si al correrlo ves "gzip: not in gzip format" o cualquier error de
# tar/gzip: el archivo se corrompió al transferirse (algo en el
# camino — WhatsApp, correo, Drive, etc. — lo trató como texto).
# Arreglalo así antes de reintentar:
#   sed -i 's/\r$//' AsistenteIA-Bazzite-Instalar.sh
# y si eso tampoco alcanza, pedí que te lo reenvíen comprimido en un
# .zip (evita que cualquier intermediario lo toque como texto).

set -euo pipefail

echo "Extrayendo AsistenteIA..."

# la línea siguiente al marcador es donde empieza el paquete en
# base64 pegado más abajo en este mismo archivo
LINEA_INICIO=$(awk '/^__ARCHIVO_TAR_ABAJO__$/{print NR + 1; exit 0}' "$0")

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

# FIX/NUEVO: el paquete va en BASE64, no en binario crudo pegado
# directo. Un .tar.gz binario pegado tal cual en un .sh es frágil
# ante cualquier paso de la transferencia que trate el archivo como
# texto y reinterprete su codificación (ej. la vista previa de una
# app de chat, o algún proxy/servicio intermedio) — eso corrompe
# silenciosamente los bytes binarios, y el destinatario ve "gzip: not
# in gzip format" al extraer, sin ninguna pista de qué pasó en el
# camino. Base64 usa solo un puñado de caracteres ASCII seguros que
# sobreviven intactos casi cualquier transformación de texto.
tail -n +"$LINEA_INICIO" "$0" | base64 -d | tar xz -C "$TMPDIR"

cd "$TMPDIR"
chmod +x instalador_bazzite.sh desinstalador_bazzite.sh

./instalador_bazzite.sh

# el desinstalador se deja guardado junto al código instalado, para
# que tu amigo lo encuentre fácil cuando lo necesite más adelante —
# instalador_bazzite.sh ya crea esta carpeta, así que solo hace
# falta copiar el script ahí.
DEST_DESINSTALADOR="$HOME/.local/opt/asistente-ia/desinstalador_bazzite.sh"
if [ -d "$HOME/.local/opt/asistente-ia" ]; then
    cp desinstalador_bazzite.sh "$DEST_DESINSTALADOR"
    chmod +x "$DEST_DESINSTALADOR"
    echo
    echo "Para desinstalar más adelante, corré:"
    echo "    $DEST_DESINSTALADOR"
fi

exit 0
__ARCHIVO_TAR_ABAJO__
HEADER

# el paquete se codifica en base64 (texto ASCII puro) en vez de
# pegarse como binario crudo — ver el comentario detallado arriba,
# en el header. base64 sin "-w 0" en algunos sistemas envuelve a 76
# columnas por defecto (GNU coreutils) o no envuelve en absoluto
# (BSD/macOS) — no importa cuál: base64 -d ignora los saltos de
# línea del propio formato, así que cualquiera de los dos formatos
# de salida se decodifica igual.
base64 "$ARCHIVO_TAR" >> "$SALIDA"

chmod +x "$SALIDA"

echo
info "Listo: $SALIDA"
echo "    Esto es lo ÚNICO que le tenés que mandar a tu amigo."
echo "    Él solo necesita:"
echo "        chmod +x AsistenteIA-Bazzite-Instalar.sh"
echo "        ./AsistenteIA-Bazzite-Instalar.sh"