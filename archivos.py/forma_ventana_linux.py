"""
Máscara de ventana circular para Linux (X11 / XWayland) — usada por
ui.py para recortar el orbe flotante a forma de círculo, el
equivalente conceptual de wm_attributes("-transparentcolor", ...) de
Windows (ver el comentario detallado en ui.py, al principio del
archivo).

FIX/NUEVO: este archivo se había perdido — el contenido que quedó
guardado bajo este nombre era en realidad una copia de
media_control_linux.py (control de reproducción/volumen, sin ninguna
relación con esto), probablemente por un error al copiar/pegar entre
archivos durante el desarrollo. Como consecuencia, ui.py SÍ podía
importar "forma_ventana_linux" sin error (el archivo existía), pero
al llamar a aplicar_mascara_circular()/quitar_mascara() explotaba con
AttributeError — silenciado por el try/except de ui.py, así que en
la práctica el orbe quedaba SIEMPRE cuadrado en Linux, en silencio,
sin ningún aviso de que la máscara nunca se estaba aplicando. Este
archivo repone la implementación real.

Usa la extensión SHAPE de X11 (soportada por cualquier servidor X11
moderno, y por lo tanto también bajo XWayland — la capa de
compatibilidad que la mayoría de sesiones Wayland usan automáticamente
para apps que hablan X11 nativo, como Tkinter) a través de
python-xlib (paquete "python-xlib", ya listado en requirements.txt
específicamente para esto).

La máscara se arma como una lista de rectángulos horizontales de 1
píxel de alto que aproximan un círculo (se calcula el ancho de cada
fila con el teorema de Pitágoras) — es la forma estándar de describir
una región no rectangular con la extensión SHAPE, que solo entiende
rectángulos, no curvas.

Si la extensión no está disponible (sesión Wayland pura sin XWayland,
python-xlib no instalado, o cualquier otro motivo), las funciones
lanzan una excepción — ui.py ya las llama dentro de un try/except
para exactamente este caso, así que el orbe se degrada solo a
cuadrado, tal como está documentado ahí. No hace falta manejar ese
caso acá también.
"""

import math

from logger import log

try:
    from Xlib.display import Display
    from Xlib.ext import shape
    XLIB_DISPONIBLE = True
except ImportError:
    XLIB_DISPONIBLE = False
    print("[Ventana] 'python-xlib' no está instalado — el orbe se verá "
          "cuadrado en vez de circular (puramente estético, el asistente "
          "funciona igual). Instalalo con 'pip install python-xlib' si "
          "querés la forma circular.")

# =========================================================
# CONEXIÓN X11
# Se abre UNA sola vez y se reutiliza — abrir una conexión nueva por
# cada llamada (aplicar/quitar máscara ocurre en cada colapso/
# expansión del orbe, varias veces por sesión) sería un costo
# innecesario. Es una conexión APARTE de la que usa Tkinter
# internamente — ambas hablan con el mismo servidor X y pueden operar
# sobre la misma ventana (identificada por su ID numérico) sin
# conflicto, técnica estándar para mezclar Xlib con un toolkit que no
# expone la extensión SHAPE por su cuenta.
# =========================================================

_display              = None
_extension_verificada = False
_extension_disponible = False


def _obtener_display():
    global _display
    if _display is None:
        _display = Display()
    return _display


def _shape_disponible():
    """
    True si el servidor X actual soporta la extensión SHAPE. Se
    verifica una sola vez (el resultado no cambia durante la sesión)
    y se cachea, igual que el patrón ya usado en
    media_control_linux.py/ventanas_linux.py para playerctl/wmctrl.
    """
    global _extension_verificada, _extension_disponible

    if not XLIB_DISPONIBLE:
        return False

    if _extension_verificada:
        return _extension_disponible

    try:
        _extension_disponible = _obtener_display().has_extension("SHAPE")
    except Exception:
        log.exception("Error verificando la extensión SHAPE de X11")
        _extension_disponible = False

    if not _extension_disponible:
        print("[Ventana] El servidor X no soporta la extensión SHAPE — "
              "el orbe se verá cuadrado en vez de circular.")

    _extension_verificada = True
    return _extension_disponible


def _ventana_xlib(root):
    """
    Convierte el ID de ventana que da Tkinter (root.winfo_id()) en un
    objeto Window de python-xlib, sobre el que sí se pueden llamar
    los métodos de la extensión SHAPE (shape_rectangles, etc. — se
    agregan automáticamente a la clase Window al importar
    Xlib.ext.shape, arriba).
    """
    window_id = root.winfo_id()
    return _obtener_display().create_resource_object("window", window_id)


def _rectangulos_circulo(cx, cy, radio):
    """
    Aproxima un círculo de centro (cx, cy) y radio `radio` como una
    lista de rectángulos (x, y, ancho, alto) de 1 píxel de alto cada
    uno — una fila por cada valor de y dentro del radio, con el ancho
    de esa fila calculado por Pitágoras (x = sqrt(r² - y²)). A los
    tamaños de orbe que usa este proyecto (unas pocas decenas de
    píxeles de radio) esto se ve perfectamente circular a simple
    vista, sin necesitar antialiasing — la extensión SHAPE solo
    soporta bordes duros de todas formas.
    """
    rectangulos = []
    for dy in range(-radio, radio + 1):
        # ancho de la fila a esta altura del círculo
        dx = int(math.sqrt(max(0, radio * radio - dy * dy)))
        x  = cx - dx
        y  = cy + dy
        ancho = dx * 2 + 1
        if ancho > 0:
            rectangulos.append((x, y, ancho, 1))
    return rectangulos


# =========================================================
# API PÚBLICA — usada por ui.py
# =========================================================

def aplicar_mascara_circular(root, ancho, alto, cx, cy, radio):
    """
    Recorta la ventana `root` (un root o Toplevel de Tkinter) a un
    círculo de centro (cx, cy) y radio `radio`, en coordenadas
    LOCALES de la ventana (0,0 es la esquina superior izquierda).
    `ancho`/`alto` no se usan para el cálculo en sí (el círculo ya
    queda totalmente definido por cx/cy/radio) — se reciben para
    mantener una firma simétrica con quitar_mascara() y por si en el
    futuro hiciera falta recortar también el resto del rectángulo
    (hoy no hace falta: todo lo que no está cubierto por los
    rectángulos del círculo queda automáticamente fuera de la
    máscara).

    Lanza una excepción si la extensión SHAPE o python-xlib no están
    disponibles — ui.py ya llama a esto dentro de un try/except
    (ver _aplicar_forma_orbe), así que el caller no necesita manejar
    nada especial acá; el orbe simplemente se ve cuadrado si esto
    falla.
    """
    if not _shape_disponible():
        raise RuntimeError("Extensión SHAPE no disponible")

    ventana     = _ventana_xlib(root)
    rectangulos = _rectangulos_circulo(cx, cy, radio)

    ventana.shape_rectangles(
        shape.SO.Set,       # reemplaza la máscara actual por esta
        shape.SK.Bounding,  # afecta la forma visible/clickeable de la ventana
        0,                  # ordering: 0 = Unsorted (no se pre-ordenan las filas)
        0, 0,               # sin desplazamiento adicional — cx/cy ya son absolutos dentro de la ventana
        rectangulos,
    )
    _obtener_display().sync()


def quitar_mascara(root):
    """
    Inverso de aplicar_mascara_circular() — vuelve la ventana a su
    forma rectangular completa (recorta con un único rectángulo que
    cubre toda la ventana, en vez de la silueta del círculo). Se usa
    antes de expandir el orbe al panel completo (ver
    _quitar_forma_orbe en ui.py), para que el panel expandido no
    quede recortado con la máscara circular del orbe chico.
    """
    if not _shape_disponible():
        raise RuntimeError("Extensión SHAPE no disponible")

    ventana = _ventana_xlib(root)

    geometria = ventana.get_geometry()
    ancho     = geometria.width
    alto      = geometria.height

    ventana.shape_rectangles(
        shape.SO.Set,
        shape.SK.Bounding,
        0,
        0, 0,
        [(0, 0, ancho, alto)],
    )
    _obtener_display().sync()