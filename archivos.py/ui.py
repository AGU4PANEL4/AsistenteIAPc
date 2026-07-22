"""
Interfaz flotante del asistente — un orbe pequeño, arrastrable, que
al hacer clic se expande a un panel completo con métricas arriba,
una fila de categorías en acordeón (Temporizadores/Recordatorios/
Alias/Macros) y el historial de comandos siempre visible debajo.
Tema "aurora fría".

FIX/NUEVO: versión anterior tenía una sidebar vertical de íconos a
la izquierda que reemplazaba TODO el contenido central al cambiar de
pestaña (Historial/Aliases/Macros/Recordatorios) — el historial
quedaba oculto en cuanto se miraba cualquier otra cosa. Ahora:
  - En reposo, solo se ve un orbe circular chico (arrastrable a
    cualquier parte de la pantalla).
  - Un clic simple (sin arrastrar) lo expande al panel completo,
    anclado por la misma esquina superior derecha donde estaba el
    orbe — un clic en el puntito/título del header (o en el propio
    orbe) lo vuelve a contraer; "─" manda la ventana a segundo plano
    directo, y "×" pregunta si dejarla en segundo plano o cerrar del
    todo.
  - Temporizadores/Recordatorios/Alias/Macros son una fila horizontal
    de categorías tipo acordeón: expandir una muestra su lista justo
    debajo de la fila, sin tapar nunca el historial de abajo. Cada
    fila de esas listas se elimina con confirmación en dos clics
    ("✕" → "¿Eliminar? ✓") y una animación corta de desvanecido antes
    de desaparecer. Alias se separa en dos columnas: los que ya están
    registrados (agrupados por app) y las apps en caché que todavía
    no tienen ninguno.
  - Cada estado (escuchando/procesando/hablando) tiene su propia
    animación dibujada en el Canvas del orbe, no solo un cambio de
    color: barras tipo ecualizador al escuchar, un spinner de puntos
    al procesar, anillos concéntricos expandiéndose al hablar.

El truco de la forma circular con esquinas transparentes usa
wm_attributes("-transparentcolor", ...), soportado por Tkinter SOLO
en Windows — cualquier píxel exactamente de ese color se vuelve
invisible. Por eso TRANSPARENTE es un color que no se usa en
ningún otro lugar de la paleta.

NUEVO: en Linux, "-transparentcolor" no existe en absoluto (Tcl/Tk
lanza TclError apenas se intenta) — antes esto se degradaba a un
cuadrado sólido del color TRANSPARENTE (un violeta chillón, pensado
para ser un marcador invisible, nunca para verse). Ahora se usa el
mecanismo nativo de X11 para esto: la extensión XShape, que recorta
la ventana a una máscara con forma de círculo (ver
forma_ventana_linux.py) — el equivalente conceptual de
"-transparentcolor" pero basado en máscara de región en vez de
transparencia por color. Si esa extensión no está disponible (sesión
Wayland pura sin XWayland, o falta el paquete python-xlib), se
degrada a un cuadrado con el color de fondo normal de la paleta
(nunca el violeta marcador) — sigue siendo perfectamente usable,
solo que sin la esquina redondeada.
"""

import math
import random
import threading
import tkinter as tk
from plataforma import es_windows

if not es_windows():
    import forma_ventana_linux
from datetime import datetime

from bandeja import iniciar_bandeja, detener_bandeja
from visual_utils import mezclar_hex as _mezclar_hex, dibujar_puntos_spinner

# =========================================================
# PALETA — "aurora fría"
# =========================================================

# FIX: "Consolas" y "Segoe UI" son fuentes EXCLUSIVAS de Windows — en
# Linux no existen, y Tkinter no avisa nada cuando eso pasa: cae en
# silencio a una fuente de reemplazo genérica del sistema, con
# métricas (ancho de carácter, alto de línea) distintas a las que se
# usó para calcular paddings/tamaños de tarjetas acá. El resultado es
# que todo puede verse un poco desalineado o con texto cortado donde
# en Windows entraba justo, sin que salte ningún error que avise por
# qué.
#
# Se elige la fuente según la plataforma real en vez de asumir
# Windows — mismo patrón que ya usa _cfg_ventana() con
# "-transparentcolor" (ver más abajo). "DejaVu Sans Mono"/"DejaVu
# Sans" vienen preinstaladas en prácticamente cualquier distro Linux
# de escritorio (incluida Bazzite) y tienen un espíritu visual similar
# (monoespaciada técnica + sans moderna legible).
if es_windows():
    _FUENTE_MONO = "Consolas"
    _FUENTE_UI   = "Segoe UI"
else:
    _FUENTE_MONO = "DejaVu Sans Mono"
    _FUENTE_UI   = "DejaVu Sans"

C = {
    "bg":         "#0b1a1f",
    "bg2":        "#10262c",
    "bg3":        "#0d2025",
    "borde":      "#1c3a3f",
    "borde2":     "#162c31",
    "acento":     "#2de6c0",
    "acento_dim": "#3a8c78",
    "texto":      "#7fb3ad",
    "texto_dim":  "#3a5a5c",
    "rojo":       "#ff5566",
    "verde":      "#2de6c0",
    "amarillo":   "#e6c02d",
    # NUEVO: color propio para el modo dormido — antes usaba los
    # mismos tonos apagados que "inactivo" (texto_dim/borde2), que es
    # justo por lo que se confundían a simple vista. Un azul lavanda
    # suave, con temática de "luz de luna" contra el fondo oscuro,
    # distinto del resto de la paleta (cian/verde/amarillo/rojo) sin
    # desentonar con ella.
    "dormido":    "#8b9ae8",
    "mono":       _FUENTE_MONO,
    "ui":         _FUENTE_UI,
}

# color que se vuelve transparente en la ventana del orbe — no debe
# coincidir con NINGÚN otro color usado en la interfaz
TRANSPARENTE = "#ab29fe"

# NUEVO: color de la franja de acento del header (ver _build_header /
# _tick_header_accent) según el modo actual — mismo lenguaje de color
# que ya usa el orbe chico en AsistenteUI.ESTADOS, para que la vista
# expandida "respire" igual que el orbe en vez de sentirse una
# interfaz aparte.
COLORES_ACCENT_MODO = {
    "inactivo":   C["borde"],
    "escuchando": C["acento"],
    "procesando": C["amarillo"],
    "hablando":   C["verde"],
    "buscando":   C["amarillo"],
    "dormido":    C["dormido"],
}

ANCHO       = 360
ALTO        = 480

# FIX/NUEVO: rediseño del panel expandido — antes había una sidebar
# vertical de íconos a la izquierda que reemplazaba TODO el contenido
# central al cambiar de pestaña (Historial/Aliases/Macros/
# Recordatorios), sin relación visual entre ellas. Ahora Historial
# queda SIEMPRE visible en la parte de abajo del panel, y arriba hay
# una fila horizontal de 4 categorías (Temporizadores/Recordatorios/
# Alias/Macros) que funcionan como acordeón: un clic expande su
# contenido justo debajo de la fila (empujando el historial hacia
# abajo, nunca tapándolo), otro clic en la misma categoría la vuelve
# a colapsar. SIDEBAR_W ya no se usa (no queda sidebar vertical), se
# deja declarada por si algún otro módulo llegara a importarla.
SIDEBAR_W   = 34

# NUEVO: color de fondo usado para el estado de "confirmar borrado" de
# una fila (ver _crear_fila_lista) — un rojo bien oscuro, apenas tinte,
# para que se note el cambio de estado sin gritar tanto como C["rojo"]
# puro usado en el texto/ícono.
CONFIRMAR_BORRADO_BG = "#3a1414"

# milisegundos que una fila se queda en "¿Eliminar? ✓" antes de volver
# sola al estado normal si el segundo clic nunca llega — evita que una
# fila quede "armada para borrar" indefinidamente si el usuario se
# distrae y vuelve mucho después.
CONFIRMAR_BORRADO_TIMEOUT_MS = 3500

ORBE_CANVAS = 96
ORBE_CENTRO = 48
ORBE_RADIO  = 24

MARGEN_DERECHO   = 16
MARGEN_SUPERIOR  = 40

# NUEVO: duración de la animación de expandir/contraer — ver
# _animar_geometria() más abajo.
ANIM_DURACION_MS = 220
ANIM_PASOS       = 10


# =========================================================
# TOOLTIP
# NUEVO: ventanita chica sin bordes que aparece junto a un ícono al
# pasar el mouse, mostrando su nombre — antes los íconos de la
# sidebar (≡ ⇄ ▤ ◷) eran solo símbolos sin ninguna pista de qué
# representa cada uno para alguien que los ve por primera vez.
#
# Se implementa como un tk.Toplevel propio (no un Label superpuesto)
# para poder posicionarlo libremente fuera del widget que lo activa,
# sin alterar el layout de la fila de categorías. Aparece con un
# pequeño retraso (ver _on_cat_enter en AsistenteUI) para no destellar
# en cada barrido rápido del mouse sobre la fila.
# =========================================================

class _BarraScroll(tk.Canvas):
    """
    NUEVO: reemplaza a ttk.Scrollbar (que en teoría, con tema "clam",
    debería respetar colores custom en Windows — pero en la práctica
    seguía saliendo con la apariencia nativa clara, según lo reportado).
    Esta es una scrollbar dibujada enteramente a mano sobre un Canvas:
    un solo rectángulo ("thumb") cuyo tamaño/posición se recalculan a
    partir de las fracciones que Tkinter le manda vía yscrollcommand
    (mismo mecanismo que usaría cualquier Scrollbar real). Al no
    depender de ningún widget nativo del sistema operativo, el color
    que se le pida en código es EXACTAMENTE el que se ve, en cualquier
    plataforma.
    """
    def __init__(self, parent, comando_scroll, ancho=6):
        super().__init__(parent, width=ancho, bg=C["bg"], highlightthickness=0)
        self._comando_scroll = comando_scroll
        self._frac0, self._frac1 = 0.0, 1.0
        self._thumb = self.create_rectangle(0, 0, ancho, 20, fill=C["bg2"], outline="")
        self.bind("<Configure>", lambda e: self._redibujar())
        self.bind("<Button-1>", self._ir_a)
        self.bind("<B1-Motion>", self._ir_a)
        self.bind("<Enter>", lambda e: self.itemconfig(self._thumb, fill=C["borde2"]))
        self.bind("<Leave>", lambda e: self.itemconfig(self._thumb, fill=C["bg2"]))

    def set(self, lo, hi):
        """Firma esperada por Tkinter para yscrollcommand — misma que
        usaría cualquier Scrollbar real."""
        self._frac0, self._frac1 = float(lo), float(hi)
        self._redibujar()

    def _redibujar(self):
        alto = self.winfo_height()
        ancho = self.winfo_width()
        # si el contenido entra completo (0.0 a 1.0), no hace falta
        # mostrar ningún thumb — se oculta en vez de dibujar una barra
        # que ocuparía toda la pista sin servir para nada.
        if self._frac1 - self._frac0 >= 0.999:
            self.itemconfig(self._thumb, state="hidden")
            return
        self.itemconfig(self._thumb, state="normal")
        y0 = alto * self._frac0
        y1 = alto * self._frac1
        self.coords(self._thumb, 1, y0, ancho - 1, y1)

    def _ir_a(self, event):
        alto = self.winfo_height()
        if alto <= 0:
            return
        frac = max(0.0, min(1.0, event.y / alto))
        self._comando_scroll("moveto", frac)


class _Tooltip:
    def __init__(self, root):
        self.root = root
        self.win  = None

    def show(self, widget, texto):
        self.hide()
        try:
            x = widget.winfo_rootx() + widget.winfo_width() + 6
            y = widget.winfo_rooty() + widget.winfo_height() // 2 - 10
        except Exception:
            return

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=C["borde"])

        tk.Label(
            win, text=texto, font=(C["ui"], 8),
            fg=C["texto"], bg=C["bg2"], padx=8, pady=3,
        ).pack(padx=1, pady=1)

        win.geometry(f"+{x}+{y}")
        self.win = win

    def hide(self):
        if self.win is not None:
            try:
                self.win.destroy()
            except Exception:
                pass
            self.win = None


# =========================================================
# VENTANA
# =========================================================

class AsistenteUI:

    ESTADOS = {
        "inactivo":   {"txt": 'Inactivo — di "jarvis"', "color": C["texto_dim"], "dot": C["borde2"]},
        "escuchando": {"txt": "Escuchando...",           "color": C["acento"],    "dot": C["acento"]},
        "procesando": {"txt": "Procesando...",           "color": C["amarillo"],  "dot": C["amarillo"]},
        "hablando":   {"txt": "Hablando...",             "color": C["verde"],     "dot": C["verde"]},
        "buscando":   {"txt": "Buscando app...",         "color": C["amarillo"],  "dot": C["amarillo"]},
        # NUEVO: modo dormido (ver es_dormir en session.py / main.py) —
        # FIX: antes usaba los mismos tonos apagados que "inactivo"
        # (texto_dim/borde2) a propósito para que se sintiera "en
        # reposo" — pero terminó siendo el problema: se confundía a
        # simple vista con inactivo. Ahora usa su propio color
        # (C["dormido"], un azul lavanda) — sigue siendo un tono
        # tranquilo/apagado, no tan vivo como el cian de "escuchando",
        # pero claramente distinguible de "inactivo" de un vistazo.
        "dormido":    {"txt": 'Durmiendo — di "despierta"', "color": C["dormido"], "dot": C["dormido"]},
    }

    def __init__(self, root):
        self.root       = root
        self.expandido  = False
        self._orb_fase  = 0.0
        self._pulse     = 0.0
        self._drag_x    = self._drag_y = 0
        self._movido    = False

        # NUEVO: tooltip compartido de la fila de categorías, ítem bajo
        # el mouse en este momento (o None), e ids de los after()
        # pendientes que muestran el tooltip con retraso — mismo
        # mecanismo que ya usaba la sidebar vertical, reutilizado acá
        # para la fila horizontal de categorías (ver _on_cat_enter/
        # _on_cat_leave).
        self._tooltip            = _Tooltip(root)
        self._cat_hover           = None
        self._tooltip_after_ids   = {}

        # NUEVO: contador de vueltas de _polling — los badges de
        # conteo (temporizadores/recordatorios/alias/macros) de la
        # grilla se recalculan cada cierta cantidad de vueltas en vez
        # de en cada tick, para no releer esos datos de disco 16 veces
        # por segundo sin necesidad.
        self._contadores_tick_contador = 0

        # NUEVO (rediseño "panel denso animado"): las 4 categorías ya
        # no son un acordeón que expande/colapsa DENTRO del panel —
        # las 4 tarjetas están siempre visibles a la vez, en grilla
        # 2x2 (ver _build_categorias_grid). Tocar una abre su lista
        # completa en una ventanita flotante aparte (ver
        # _abrir_categoria_flotante), así el panel principal nunca
        # cambia de tamaño ni reordena nada.
        #
        # self._firma_categorias: última firma conocida de cada
        # categoría (ver _firma_categoria) — se compara en cada
        # refresco para detectar si algo cambió de verdad antes de
        # releer conteos o repintar.
        # self._pulso_categoria: intensidad actual (0..1) del pulso de
        # color de cada tarjeta — sube a 1 cuando llega algo nuevo a
        # esa categoría (ver _pulsar_categoria) y decae solo, tick a
        # tick, en _tick_pulsos().
        # self._cat_flotante: cuál categoría tiene su ventana flotante
        # abierta ahora mismo (o None) — nunca más de una a la vez,
        # abrir otra cierra la anterior.
        self._firma_categorias  = {cat: None for cat in self.CATEGORIAS}
        self._pulso_categoria   = {cat: 0.0 for cat in self.CATEGORIAS}
        self._cat_flotante      = None
        self._win_flotante      = None

        # NUEVO: estado de parpadeo de la carita del orbe (ver
        # _dibujar_cara) — self._ojos_cerrados se pone en True durante
        # unos pocos frames cada tanto, en intervalos aleatorios (no
        # un parpadeo mecánico y perfectamente regular, que se ve
        # artificial) entre PARPADEO_MIN_TICKS y PARPADEO_MAX_TICKS.
        self._parpadeo_cuenta   = random.randint(30, 90)
        self._ojos_cerrados     = False

        # NUEVO: por fila de lista (temporizadores/recordatorios/
        # macros/alias) que está en su segundo estado ("¿Eliminar?"),
        # se guarda acá el id del after() pendiente que la revertiría
        # sola — para poder cancelarlo si el usuario confirma antes de
        # que se cumpla el timeout (ver _crear_fila_lista).
        self._confirmaciones_pendientes = {}

        # NUEVO: animación en curso al expandir/contraer — evita que
        # dos animaciones se pisen si el usuario hace doble clic
        # rápido durante la transición.
        self._animando = False

        # esquina superior derecha que ancla la ventana, sin importar
        # si está en modo orbe o modo panel — se actualiza cada vez
        # que el usuario arrastra la ventana a otro lugar
        sw = root.winfo_screenwidth()
        self._anchor_x_right = sw - MARGEN_DERECHO
        self._anchor_y_top   = MARGEN_SUPERIOR

        self._cfg_ventana()
        self._build_orbe()
        self._build_panel()
        self._colapsar(inicial=True)
        self._polling()

    # ── ventana base ──────────────────────────────────────

    def _cfg_ventana(self):
        r = self.root
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.resizable(False, False)

        if es_windows():
            r.configure(bg=TRANSPARENTE)
            try:
                r.wm_attributes("-transparentcolor", TRANSPARENTE)
            except tk.TclError:
                # no debería pasar en Windows, pero por las dudas —
                # mismo respaldo que el resto de esta función usa
                # para Linux, en vez de dejar el violeta marcador
                # visible como color de fondo real.
                print("[UI] transparentcolor no soportado, usando fondo sólido")
                r.configure(bg=C["bg"])
        else:
            # NUEVO: en Linux, "-transparentcolor" ni existe — se usa
            # el color de fondo NORMAL de la paleta (nunca el violeta
            # marcador, que solo tiene sentido si de verdad se vuelve
            # invisible). La forma circular se logra aparte, con la
            # máscara XShape (ver _aplicar_forma_orbe), no con este
            # color — así que si la máscara falla por cualquier
            # motivo, la ventana simplemente se ve como un cuadrado
            # con el fondo habitual de la app, en vez de un cuadrado
            # violeta que no combina con nada.
            r.configure(bg=C["bg"])

    def _aplicar_forma_orbe(self):
        """
        Recorta la ventana a la forma circular del orbe — solo hace
        falta en Linux (ver forma_ventana_linux.py); en Windows la
        forma circular ya la resuelve "-transparentcolor" en
        _cfg_ventana(), así que acá no hay nada que hacer. Se llama
        cada vez que la ventana vuelve a tamaño de orbe (_colapsar),
        DESPUÉS de que la geometría ya está fijada — aplicar la
        máscara antes de que la ventana tenga su tamaño final podría
        recortar con las coordenadas equivocadas.
        """
        if es_windows():
            return
        try:
            self.root.update_idletasks()
            forma_ventana_linux.aplicar_mascara_circular(
                self.root, ORBE_CANVAS, ORBE_CANVAS,
                ORBE_CENTRO, ORBE_CENTRO, ORBE_RADIO,
            )
        except Exception:
            pass

    def _quitar_forma_orbe(self):
        """Inverso de _aplicar_forma_orbe() — vuelve a ventana
        rectangular completa antes de expandir al panel. Solo aplica
        en Linux, por el mismo motivo que la función de arriba."""
        if es_windows():
            return
        try:
            forma_ventana_linux.quitar_mascara(self.root)
        except Exception:
            pass

    def _anchor_desde_geometria(self):
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        w = self.root.winfo_width()
        self._anchor_x_right = x + w
        self._anchor_y_top   = y

    # ── arrastrar / clic ──────────────────────────────────

    def _drag_press(self, e):
        self._drag_x, self._drag_y = e.x, e.y
        self._movido = False

    def _drag_motion(self, e):
        dx = e.x - self._drag_x
        dy = e.y - self._drag_y
        if abs(dx) > 3 or abs(dy) > 3:
            self._movido = True
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")

    def _release_orbe(self, e):
        self._anchor_desde_geometria()
        if not self._movido:
            self._expandir()

    def _release_arrastre(self, e):
        self._anchor_desde_geometria()

    # ── orbe ────────────────────────────────────────────

    def _build_orbe(self):
        # NUEVO: en Windows, el Canvas usa el color TRANSPARENTE (se
        # vuelve invisible vía -transparentcolor, ver _cfg_ventana) —
        # en Linux la forma circular se logra con la máscara XShape,
        # no por color, así que acá se usa el fondo normal de la
        # paleta (mismo que ya configuró _cfg_ventana en la ventana).
        bg_canvas = TRANSPARENTE if es_windows() else C["bg"]
        self.orb_canvas = tk.Canvas(
            self.root, width=ORBE_CANVAS, height=ORBE_CANVAS,
            bg=bg_canvas, highlightthickness=0
        )
        self.orb_circulo = self.orb_canvas.create_oval(
            ORBE_CENTRO - ORBE_RADIO, ORBE_CENTRO - ORBE_RADIO,
            ORBE_CENTRO + ORBE_RADIO, ORBE_CENTRO + ORBE_RADIO,
            fill=C["bg2"], outline=C["borde"], width=2,
        )
        self.orb_canvas.bind("<ButtonPress-1>", self._drag_press)
        self.orb_canvas.bind("<B1-Motion>",     self._drag_motion)
        self.orb_canvas.bind("<ButtonRelease-1>", self._release_orbe)

    def _dibujar_orbe(self, modo, no_molestar_activo=False):
        cv    = self.orb_canvas
        color = self.ESTADOS.get(modo, self.ESTADOS["inactivo"])["dot"]

        cv.delete("anim")
        cv.itemconfig(self.orb_circulo, outline=color if modo != "inactivo" else C["borde"])

        if modo == "escuchando":
            anchos, gap = 4, 4
            total = 3 * anchos + 2 * gap
            x0    = ORBE_CENTRO - total // 2
            for i in range(3):
                h = 8 + 9 * abs(math.sin(self._orb_fase * 2.2 + i * 1.3))
                x = x0 + i * (anchos + gap)
                cv.create_rectangle(
                    x, ORBE_CENTRO - h / 2, x + anchos, ORBE_CENTRO + h / 2,
                    fill=color, outline="", tags="anim",
                )

        elif modo == "procesando":
            # NUEVO: spinner de varios puntos (mismo estilo que el
            # splash) en vez de un solo punto orbitando.
            dibujar_puntos_spinner(
                cv, cx=ORBE_CENTRO, cy=ORBE_CENTRO, radio=ORBE_RADIO - 7,
                fase=self._orb_fase, color=color, color_fondo=C["bg2"],
                n_puntos=8, radio_punto=2, tags="anim",
            )

        elif modo in ("hablando", "buscando"):
            for i in range(2):
                fase_anillo = ((self._orb_fase * 0.5) + i * 0.5) % 1.0
                radio  = ORBE_RADIO + fase_anillo * 20
                tono   = _mezclar_hex(color, C["bg"], 1 - fase_anillo)
                cv.create_oval(
                    ORBE_CENTRO - radio, ORBE_CENTRO - radio,
                    ORBE_CENTRO + radio, ORBE_CENTRO + radio,
                    outline=tono, width=2, tags="anim",
                )

        elif modo == "dormido":
            # NUEVO: animación propia para el modo dormido — antes
            # cualquier estado sin animación específica (inactivo,
            # dormido, cualquier otro) caía en el mismo puntito
            # estático de "else" de más abajo, así que dormido se
            # veía IGUAL que inactivo — nada en el orbe avisaba que
            # el asistente no iba a reaccionar a la wake word normal.
            #
            # Acá se usa una fase mucho más lenta que self._orb_fase
            # (×0.12) a propósito — una "respiración" pausada en vez
            # del ritmo normal de las otras animaciones, para que se
            # sienta como algo que duerme, no como que está ocupado.
            #
            # FIX/NUEVO: la primera versión solo variaba 2px el radio
            # de la luna — muy sutil, seguía pareciéndose a "inactivo"
            # de reojo. Ahora hay un HALO de verdad: varios círculos
            # concéntricos rellenos (Tkinter no soporta transparencia
            # real ni blur, así que un degradado radial se simula
            # pintando círculos cada vez más chicos y brillantes por
            # ENCIMA de los más grandes y tenues) cuyo brillo GENERAL
            # sube y baja con la respiración — se nota incluso mirando
            # de reojo, no solo mirando fijo la luna.
            fase_lenta  = self._orb_fase * 0.12
            respiracion = (math.sin(fase_lenta) + 1) / 2  # 0..1 suave

            cx, cy = ORBE_CENTRO, ORBE_CENTRO

            for radio_base, intensidad_base in ((20, 0.14), (16, 0.22), (12, 0.32)):
                radio      = radio_base + respiracion * 2
                intensidad = intensidad_base * (0.35 + 0.65 * respiracion)
                tono       = _mezclar_hex(color, C["bg2"], intensidad)
                cv.create_oval(
                    cx - radio, cy - radio, cx + radio, cy + radio,
                    fill=tono, outline="", tags="anim",
                )

            # luna creciente encima del halo — mismo color dedicado,
            # ya no el tono apagado que compartía con "inactivo"
            radio_luna = 9 + 1.5 * respiracion
            tono_luna  = _mezclar_hex(color, C["bg2"], 0.55 + 0.45 * respiracion)
            cv.create_oval(
                cx - radio_luna, cy - radio_luna,
                cx + radio_luna, cy + radio_luna,
                fill=tono_luna, outline="", tags="anim",
            )
            desplazo = radio_luna * 0.55
            cv.create_oval(
                cx - radio_luna + desplazo, cy - radio_luna,
                cx + radio_luna + desplazo, cy + radio_luna,
                fill=C["bg2"], outline="", tags="anim",
            )

        else:  # inactivo
            cv.create_oval(ORBE_CENTRO - 4, ORBE_CENTRO - 4,
                           ORBE_CENTRO + 4, ORBE_CENTRO + 4,
                           fill=C["borde2"], outline="", tags="anim")

        # NUEVO (rediseño "lúdico/animado"): carita simple (ojos +
        # boca) por encima de la animación del modo — le da al orbe
        # personalidad de "criatura viva" en vez de ser solo un
        # indicador de estado abstracto. Ver _dibujar_cara().
        self._dibujar_cara(cv, modo)

        # =====================================================
        # INDICADOR DE NO MOLESTAR
        # NUEVO: a diferencia de los estados de arriba (mutuamente
        # excluyentes — el asistente está en UNO solo a la vez), no
        # molestar puede estar activo AL MISMO TIEMPO que cualquier
        # otro modo (ej. escuchando un comando con no molestar de
        # fondo) — por eso se dibuja acá, DESPUÉS y ENCIMA de
        # cualquier animación de arriba, en vez de ser un "modo" más.
        #
        # FIX/NUEVO: rediseñado — antes era un círculo con contorno y
        # una línea DIAGONAL cruzándolo (símbolo genérico de
        # "silenciado/prohibido"). Ahora es un círculo RELLENO con una
        # línea HORIZONTAL de puntas redondeadas en el medio — el
        # ícono clásico de "No molestar" de iOS/macOS, mucho más
        # reconocible a primera vista para ese significado específico
        # (silenciado diagonal se confunde fácil con "prohibido/
        # bloqueado" en general). capstyle="round" es lo que redondea
        # las puntas de la línea en vez de dejarlas cuadradas.
        #
        # Sigue quieto, a propósito, sin animación — no debe competir
        # visualmente con la animación del modo actual, y en rojo
        # (C["rojo"]) para que se note incluso a simple vistazo, en
        # una esquina del orbe.
        # =====================================================

        if no_molestar_activo:
            bx, by, br = ORBE_CENTRO + ORBE_RADIO - 7, ORBE_CENTRO - ORBE_RADIO + 7, 8
            cv.create_oval(
                bx - br, by - br, bx + br, by + br,
                fill=C["rojo"], outline=C["bg"], width=2, tags="anim",
            )
            mitad_linea = br * 0.55
            cv.create_line(
                bx - mitad_linea, by, bx + mitad_linea, by,
                fill=C["bg"], width=3, capstyle="round", tags="anim",
            )

    # ── carita del orbe (parpadeo + expresión por modo) ────
    # NUEVO: le da al orbe una cara mínima — dos ojos y una boca,
    # nada de detalle realista, en el mismo espíritu que el resto de
    # la interfaz (formas simples, sin degradados ni sombras que
    # Tkinter no puede dibujar bien). La expresión cambia con el modo
    # actual y los ojos parpadean solos cada tanto (ver
    # self._parpadeo_cuenta / self._ojos_cerrados, actualizados en
    # _tick_orbe) — ese parpadeo es lo que hace que se sienta "vivo"
    # incluso en reposo, no solo cuando está animando por estado.

    def _dibujar_cara(self, cv, modo, cx=None, cy=None, escala=1.0, tag="anim"):
        cx = ORBE_CENTRO if cx is None else cx
        cy = ORBE_CENTRO if cy is None else cy
        color  = self.ESTADOS.get(modo, self.ESTADOS["inactivo"])["dot"]
        # en reposo la cara es más tenue (mezclada con el fondo) para
        # no competir con el punto de "inactivo" del centro; en
        # cualquier otro modo se usa el color pleno del estado.
        tono = color if modo != "inactivo" else _mezclar_hex(color, C["bg2"], 0.5)

        sep_ojos = 9 * escala
        y_ojos   = cy - 3 * escala
        r_ojo    = max(1, 2 * escala)

        if self._ojos_cerrados:
            for dx in (-sep_ojos, sep_ojos):
                cv.create_line(
                    cx + dx - r_ojo * 1.5, y_ojos, cx + dx + r_ojo * 1.5, y_ojos,
                    fill=tono, width=max(1, int(2 * escala)), capstyle="round", tags=tag,
                )
        else:
            for dx in (-sep_ojos, sep_ojos):
                cv.create_oval(
                    cx + dx - r_ojo, y_ojos - r_ojo * 1.5, cx + dx + r_ojo, y_ojos + r_ojo * 1.5,
                    fill=tono, outline="", tags=tag,
                )

        # boca: la forma cambia según el modo — sonríe al hablar
        # (tarea terminada / respondiendo), se abre redonda al
        # escuchar, queda como una rayita neutra en cualquier otro
        # estado (procesando/buscando/dormido/inactivo) para no
        # sugerir una emoción que no corresponde.
        y_boca = cy + 7 * escala
        r_boca = 6 * escala
        if modo == "hablando":
            cv.create_arc(
                cx - r_boca, y_boca - 4 * escala, cx + r_boca, y_boca + 4 * escala,
                start=200, extent=140, style="arc",
                outline=tono, width=max(1, int(2 * escala)), tags=tag,
            )
        elif modo == "escuchando":
            cv.create_oval(
                cx - 3 * escala, y_boca - 3 * escala, cx + 3 * escala, y_boca + 3 * escala,
                fill=tono, outline="", tags=tag,
            )
        else:
            cv.create_line(
                cx - 4 * escala, y_boca, cx + 4 * escala, y_boca,
                fill=tono, width=max(1, int(2 * escala)), capstyle="round", tags=tag,
            )

    # ── panel expandido ───────────────────────────────────

    def _build_panel(self):
        self.panel_frame = tk.Frame(self.root, bg=C["bg"])
        self._build_header(self.panel_frame)
        self._build_statusbar(self.panel_frame)
        self._build_body(self.panel_frame)
        self._build_footer(self.panel_frame)

        # NUEVO: rectángulo liso, sin hijos, usado SOLO mientras dura
        # la animación de expandir/contraer (ver _expandir/_colapsar).
        #
        # FIX: la primera versión de la animación mantenía el panel
        # COMPLETO (con sidebar, listas, botones) visible durante todo
        # el resize — pero Tkinter no reacomoda ni "escala" el
        # contenido en cada frame intermedio, así que a mitad de la
        # animación se veía el panel recortado de forma abrupta por
        # el borde de la ventana (texto cortado a la mitad, sidebar
        # aplastada), en vez de una transición prolija. Esto es lo
        # que se sentía "raro" en la animación.
        #
        # Ahora, mientras el tamaño cambia, se muestra este rectángulo
        # sin contenido (mismo color de fondo) — al no tener hijos que
        # reacomodar, se ve como un simple crecimiento/achique de un
        # bloque de color sólido, sin nada que recortar. El panel real
        # (o el orbe) recién se muestra de un swap instantáneo cuando
        # la animación ya terminó del todo.
        self.placeholder_frame = tk.Frame(self.root, bg=C["bg"])

    # ── transición animada entre orbe y panel ─────────────
    # NUEVO: antes _expandir()/_colapsar() ponían el tamaño final de
    # la ventana de un solo golpe con root.geometry(...) — un cambio
    # brusco e instantáneo. Ahora se interpola el ancho/alto en
    # varios pasos cortos (con ease-out, más rápido al empezar y
    # suave al llegar) durante ANIM_DURACION_MS — la esquina superior
    # derecha (self._anchor_x_right/_anchor_y_top) se mantiene fija
    # como referencia, así la ventana crece/achica "desde" esa
    # esquina en vez de desde el centro.

    def _animar_geometria(self, ancho_ini, alto_ini, ancho_fin, alto_fin,
                          al_terminar=None):
        self._animando = True

        def _ease_out(t):
            return 1 - (1 - t) ** 3

        def _paso(i):
            t     = _ease_out(i / ANIM_PASOS)
            ancho = int(ancho_ini + (ancho_fin - ancho_ini) * t)
            alto  = int(alto_ini + (alto_fin - alto_ini) * t)
            x     = self._anchor_x_right - ancho
            y     = self._anchor_y_top
            try:
                self.root.geometry(f"{ancho}x{alto}+{x}+{y}")
            except Exception:
                pass

            if i < ANIM_PASOS:
                self.root.after(ANIM_DURACION_MS // ANIM_PASOS, lambda: _paso(i + 1))
            else:
                self._animando = False
                if al_terminar:
                    al_terminar()

        _paso(0)

    def _expandir(self):
        if self._animando:
            return
        self._anchor_desde_geometria()

        # NUEVO: la máscara circular (Linux) está pensada para el
        # tamaño del orbe (96x96) — hay que quitarla ANTES de crecer,
        # si no el panel completo quedaría recortado con esa forma
        # chica. En Windows esto no hace nada (ver _quitar_forma_orbe).
        self._quitar_forma_orbe()

        # swap instantáneo: orbe fuera, placeholder liso adentro — el
        # panel real (con todo su contenido) recién se muestra cuando
        # la animación de tamaño ya terminó (ver _al_terminar).
        self.orb_canvas.pack_forget()
        self.placeholder_frame.pack(fill="both", expand=True)
        self.expandido = True

        def _al_terminar():
            self.placeholder_frame.pack_forget()
            self.panel_frame.pack(fill="both", expand=True)

        self._animar_geometria(ORBE_CANVAS, ORBE_CANVAS, ANCHO, ALTO,
                               al_terminar=_al_terminar)

    def _colapsar(self, inicial=False):
        if inicial:
            # sin animación al arrancar — no hay nada que "contraer"
            # todavía, la ventana nunca estuvo expandida antes de esto
            self.panel_frame.pack_forget()
            self.placeholder_frame.pack_forget()
            x = self._anchor_x_right - ORBE_CANVAS
            y = self._anchor_y_top
            self.root.geometry(f"{ORBE_CANVAS}x{ORBE_CANVAS}+{x}+{y}")
            self.orb_canvas.pack(fill="both", expand=True)
            self.expandido = False
            self._aplicar_forma_orbe()
            return

        if self._animando:
            return

        self._anchor_desde_geometria()
        self.expandido = False

        # swap instantáneo: panel real fuera, placeholder liso adentro
        # — se oculta el contenido completo ANTES de que la ventana
        # empiece a achicarse, así nunca se ve recortado a mitad de
        # camino.
        self.panel_frame.pack_forget()
        self.placeholder_frame.pack(fill="both", expand=True)

        def _al_terminar():
            self.placeholder_frame.pack_forget()
            self.orb_canvas.pack(fill="both", expand=True)
            self._aplicar_forma_orbe()

        self._animar_geometria(ANCHO, ALTO, ORBE_CANVAS, ORBE_CANVAS,
                               al_terminar=_al_terminar)

    # ── header ──────────────────────────────────────────

    def _build_header(self, parent):
        # NUEVO: barrita de acento arriba del todo del header, que
        # cambia de color según el modo actual (cian escuchando,
        # amarillo procesando, verde hablando, lavanda dormido) —
        # ver _tick_header_accent(). Con no molestar activo, el rojo
        # tiene prioridad sobre cualquier modo, para que se note
        # incluso mirando de reojo el panel expandido, con el mismo
        # lenguaje visual que ya usa el orbe chico (ver
        # _dibujar_orbe, indicador de no molestar).
        self.header_accent = tk.Frame(parent, bg=C["borde"], height=3)
        self.header_accent.pack(fill="x")

        h = tk.Frame(parent, bg=C["bg2"], height=44)
        h.pack(fill="x")
        h.pack_propagate(False)

        # FIX/NUEVO: este punto ahora es un botón de verdad ("volver
        # al orbe"), no solo el indicador de pulso — antes esa función
        # solo la cumplía el botón "─" del header (ver más abajo, que
        # ahora hace otra cosa).
        #
        # NUEVO: ya no es un puntito de 10x10 — es una mini versión
        # del orbe, con la misma carita (ver _dibujar_cara) dibujada a
        # escala reducida, para que el header "respire" con la misma
        # personalidad que el orbe chico en reposo, no solo un color
        # de estado sin cara (ver _tick_dot_header).
        self.cv_dot = tk.Canvas(h, width=24, height=24,
                                bg=C["bg2"], highlightthickness=0, cursor="hand2")
        self.cv_dot.pack(side="left", padx=(10, 6), pady=0, anchor="center")
        self.dot_id = self.cv_dot.create_oval(2, 2, 22, 22,
                                              fill=C["bg"], outline=C["acento"], width=1.5)
        self.cv_dot.bind("<Button-1>", lambda e: self._colapsar())

        lbl_titulo = tk.Label(h, text="ASISTENTE IA",
                              font=(C["mono"], 10, "bold"),
                              fg=C["acento_dim"], bg=C["bg2"], cursor="hand2")
        lbl_titulo.pack(side="left", anchor="w")
        # el título también colapsa al orbe — un blanco de clic más
        # grande que el puntito solo, para no depender de acertarle a
        # 10x10px exactos.
        lbl_titulo.bind("<Button-1>", lambda e: self._colapsar())

        btn_x = tk.Label(h, text="×", font=(C["ui"], 15),
                         fg=C["borde"], bg=C["bg2"], cursor="hand2")
        btn_x.pack(side="right", padx=(0, 10))
        btn_x.bind("<Button-1>", lambda e: self._preguntar_cierre())
        btn_x.bind("<Enter>",    lambda e: btn_x.config(fg=C["rojo"]))
        btn_x.bind("<Leave>",    lambda e: btn_x.config(fg=C["borde"]))

        # FIX/NUEVO: "─" antes contraía de vuelta al orbe — ahora esa
        # función la cumple el punto/título de arriba (ver más arriba),
        # así que "─" queda libre para lo que su símbolo siempre
        # sugirió: mandar la ventana a segundo plano DIRECTO, sin
        # ningún diálogo de por medio — no es una acción destructiva
        # (nada se pierde, la wake word sigue escuchando igual, ver
        # bandeja.py), así que no amerita la misma fricción que ×. El
        # diálogo con la elección explícita "segundo plano vs cerrar
        # del todo" sigue viviendo únicamente en _preguntar_cierre().
        btn_min = tk.Label(h, text="─", font=(C["ui"], 13),
                           fg=C["borde"], bg=C["bg2"], cursor="hand2")
        btn_min.pack(side="right", padx=(0, 2))
        btn_min.bind("<Button-1>", lambda e: self.root.withdraw())
        btn_min.bind("<Enter>",    lambda e: btn_min.config(fg=C["acento"]))
        btn_min.bind("<Leave>",    lambda e: btn_min.config(fg=C["borde"]))

        self.lbl_motor = tk.Label(h, text="Groq",
                                  font=(C["mono"], 8),
                                  fg=C["acento_dim"],
                                  bg=C["bg3"],
                                  padx=6, pady=1,
                                  relief="flat")
        self.lbl_motor.pack(side="right", padx=4)

        # arrastrar desde el header también mueve la ventana (mismo
        # patrón que el orbe, pero sin el toggle de expandir/contraer)
        h.bind("<ButtonPress-1>", self._drag_press)
        h.bind("<B1-Motion>",     self._drag_motion)
        h.bind("<ButtonRelease-1>", self._release_arrastre)

    # ── cierre ──────────────────────────────────────────

    def _preguntar_cierre(self):
        dialogo = tk.Toplevel(self.root)
        dialogo.overrideredirect(True)
        dialogo.attributes("-topmost", True)
        dialogo.configure(bg=C["bg2"])

        ancho, alto = 260, 140
        x = self.root.winfo_x() + (ANCHO - ancho) // 2
        y = self.root.winfo_y() + (ALTO - alto) // 2
        dialogo.geometry(f"{ancho}x{alto}+{x}+{y}")

        tk.Frame(dialogo, bg=C["borde"], height=1).pack(fill="x")

        tk.Label(dialogo, text="¿Qué quieres hacer?",
                 font=(C["ui"], 10, "bold"),
                 fg=C["texto"], bg=C["bg2"]).pack(pady=(14, 10))

        def _fondo():
            dialogo.destroy()
            self.root.withdraw()

        def _cerrar():
            dialogo.destroy()
            cerrar_definitivo()

        b1 = tk.Label(dialogo, text="Dejar en segundo plano",
                     font=(C["ui"], 9), fg=C["acento"], bg=C["bg3"],
                     padx=10, pady=6, cursor="hand2")
        b1.pack(fill="x", padx=16, pady=(0, 6))
        b1.bind("<Button-1>", lambda e: _fondo())
        b1.bind("<Enter>",    lambda e: b1.config(bg=C["borde2"]))
        b1.bind("<Leave>",    lambda e: b1.config(bg=C["bg3"]))

        b2 = tk.Label(dialogo, text="Cerrar definitivamente",
                     font=(C["ui"], 9), fg=C["rojo"], bg=C["bg3"],
                     padx=10, pady=6, cursor="hand2")
        b2.pack(fill="x", padx=16)
        b2.bind("<Button-1>", lambda e: _cerrar())
        b2.bind("<Enter>",    lambda e: b2.config(bg=C["borde2"]))
        b2.bind("<Leave>",    lambda e: b2.config(bg=C["bg3"]))

        dialogo.bind("<Escape>", lambda e: dialogo.destroy())
        dialogo.focus_force()

    # ── status bar ──────────────────────────────────────

    def _build_statusbar(self, parent):
        sb = tk.Frame(parent, bg=C["bg"], pady=0)
        sb.pack(fill="x", padx=12, pady=(5, 4))

        self.lbl_estado = tk.Label(sb, text='Inactivo — di "jarvis"',
                                   font=(C["mono"], 9),
                                   fg=C["texto_dim"], bg=C["bg"], anchor="w")
        self.lbl_estado.pack(side="left")

        self.lbl_clock = tk.Label(sb, text="",
                                  font=(C["mono"], 9),
                                  fg=C["borde2"], bg=C["bg"])
        self.lbl_clock.pack(side="right")

        tk.Frame(parent, bg=C["borde"], height=1).pack(fill="x", padx=0, pady=0)

    # ── cuerpo: métricas + grilla de categorías + historial ──
    # NUEVO (rediseño "panel denso animado"): reemplaza el acordeón
    # horizontal anterior (y, antes de eso, la sidebar vertical de
    # íconos — ver el comentario junto a SIDEBAR_W). Ahora el cuerpo
    # tiene tres bloques apilados, NINGUNO de los cuales cambia de
    # tamaño ni tapa a otro al interactuar:
    #   1. Métricas (wake word / motor / no molestar) — de un vistazo.
    #   2. Grilla 2x2 de categorías (Temporizadores/Recordatorios/
    #      Alias/Macros) — todas visibles siempre, con conteo y un
    #      adelanto de contenido; un clic abre la lista completa en
    #      una ventanita flotante aparte (ver _abrir_categoria_flotante).
    #   3. Historial — SIEMPRE visible, ocupa el espacio restante.

    def _build_body(self, parent):
        body = tk.Frame(parent, bg=C["bg"])
        body.pack(fill="both", expand=True)

        self._build_metricas(body)
        self._build_categorias_grid(body)

        tk.Frame(body, bg=C["borde2"], height=1).pack(fill="x")

        self._build_historial(body)

    # ── métricas (wake word / motor / no molestar) ────────

    def _build_metricas(self, parent):
        fila = tk.Frame(parent, bg=C["bg"])
        fila.pack(fill="x", padx=10, pady=(8, 6))

        def _tarjeta(texto_label):
            card = tk.Frame(fila, bg=C["bg2"])
            card.pack(side="left", fill="both", expand=True, padx=2)
            tk.Label(card, text=texto_label, font=(C["ui"], 7),
                     fg=C["texto_dim"], bg=C["bg2"]).pack(pady=(6, 0))
            valor = tk.Label(card, text="—", font=(C["mono"], 9, "bold"),
                             fg=C["texto"], bg=C["bg2"])
            valor.pack(pady=(1, 6))
            return valor

        self.lbl_ww_card = _tarjeta("WAKE WORD")
        self.lbl_motor_card = _tarjeta("MOTOR")
        self.lbl_nomolestar_card = _tarjeta("NO MOLESTAR")

    # ── fila de categorías (acordeón) ──────────────────────

    CATEGORIAS = ("temporizadores", "recordatorios", "alias", "macros")
    CATEGORIA_ICONO = {
        "temporizadores": "◷",
        "recordatorios":  "⏰",
        "alias":          "⇄",
        "macros":         "▶",
    }
    CATEGORIA_NOMBRE = {
        "temporizadores": "Temporizadores",
        "recordatorios":  "Recordatorios",
        "alias":          "Alias",
        "macros":         "Macros",
    }

    def _contar_categoria(self, cat):
        try:
            if cat == "temporizadores":
                from temporizadores import listar_temporizadores
                return len(listar_temporizadores())
            if cat == "recordatorios":
                from recordatorios import listar_recordatorios
                return len(listar_recordatorios())
            if cat == "alias":
                from aliases import listar_aliases
                return len(listar_aliases())
            if cat == "macros":
                from macros import listar_macros
                return len(listar_macros())
        except Exception:
            pass
        return 0

    # NUEVO: cada línea del resumen se trunca a un largo fijo — antes
    # un alias o texto de recordatorio largo terminaba envolviéndose
    # solo en el wraplength angosto de la tarjeta, y como las 2
    # entradas separadas por "\n" se envolvían de la misma manera,
    # visualmente se veían todas amontonadas sin distinguirse una de
    # otra. Con esto cada línea entra siempre en un solo renglón, y el
    # "· " al inicio marca claramente dónde empieza cada entrada.
    RESUMEN_LARGO_MAX = 15

    def _truncar_resumen(self, texto):
        texto = texto.strip()
        if len(texto) > self.RESUMEN_LARGO_MAX:
            texto = texto[: self.RESUMEN_LARGO_MAX - 1].rstrip() + "…"
        return f"· {texto}"

    # NUEVO (rediseño "panel denso animado"): resumen de hasta 2
    # líneas para mostrar directamente en la tarjeta de la grilla, sin
    # necesidad de abrir nada — lee los mismos datos que ya usan
    # _renderizar_lista_simple/_renderizar_alias, solo que recortados.
    def _resumen_categoria(self, cat):
        try:
            if cat == "temporizadores":
                from temporizadores import listar_temporizadores
                items = sorted(listar_temporizadores().items())
                out = []
                for id_str, info in items[:2]:
                    try:
                        cuando = datetime.fromisoformat(info["momento"]).strftime("%H:%M")
                    except Exception:
                        cuando = "—"
                    nombre = info.get("nombre") or "sin nombre"
                    out.append(self._truncar_resumen(f"{nombre} {cuando}"))
                return out
            if cat == "recordatorios":
                from recordatorios import listar_recordatorios_ordenados
                items = listar_recordatorios_ordenados()
                out = []
                for _id, info in items[:2]:
                    out.append(self._truncar_resumen(info.get("texto", "")))
                return out
            if cat == "alias":
                from aliases import listar_aliases
                nombres = sorted(listar_aliases().keys())
                return [self._truncar_resumen(n) for n in nombres[:2]]
            if cat == "macros":
                from macros import listar_macros
                nombres = sorted(listar_macros().keys())
                return [self._truncar_resumen(n) for n in nombres[:2]]
        except Exception:
            pass
        return []

    def _build_categorias_grid(self, parent):
        """
        Grilla 2x2 SIEMPRE visible, reemplaza el acordeón anterior —
        las 4 categorías se ven todas a la vez, cada una con su
        conteo y un adelanto de hasta 2 entradas, sin necesidad de
        tocar nada. Un clic no expande nada DENTRO del panel (eso
        tapaba a las tarjetas vecinas) — abre la lista completa en una
        ventanita flotante aparte (ver _abrir_categoria_flotante), así
        el panel principal nunca cambia de tamaño ni reordena nada.
        """
        grid = tk.Frame(parent, bg=C["bg"])
        grid.pack(fill="x", padx=10, pady=(0, 6))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        self._cat_btns = {}   # cat -> (card, lbl_ic, lbl_nombre, lbl_conteo, lbl_resumen, accent)

        for i, cat in enumerate(self.CATEGORIAS):
            fila_i, col_i = divmod(i, 2)

            card = tk.Frame(grid, bg=C["bg2"], cursor="hand2")
            card.grid(row=fila_i, column=col_i, sticky="nsew", padx=2, pady=2)

            accent = tk.Frame(card, bg=C["bg2"], height=2)
            accent.pack(fill="x", side="top")

            interior = tk.Frame(card, bg=C["bg2"])
            interior.pack(fill="both", expand=True, padx=8, pady=6)

            cabecera = tk.Frame(interior, bg=C["bg2"])
            cabecera.pack(fill="x")
            lbl_ic = tk.Label(cabecera, text=self.CATEGORIA_ICONO[cat],
                              font=(C["ui"], 10), fg=C["texto_dim"], bg=C["bg2"])
            lbl_ic.pack(side="left")
            lbl_nombre = tk.Label(cabecera, text=self.CATEGORIA_NOMBRE[cat],
                                  font=(C["ui"], 8), fg=C["texto_dim"], bg=C["bg2"])
            lbl_nombre.pack(side="left", padx=(4, 0))
            lbl_conteo = tk.Label(cabecera, text="0", font=(C["mono"], 8),
                                  fg=C["texto_dim"], bg=C["bg2"])
            lbl_conteo.pack(side="right")

            lbl_resumen = tk.Label(interior, text="", font=(C["mono"], 7),
                                   fg=C["texto_dim"], bg=C["bg2"], anchor="w",
                                   justify="left", wraplength=130)
            lbl_resumen.pack(fill="x", pady=(3, 0))

            widgets = (card, accent, interior, cabecera, lbl_ic, lbl_nombre, lbl_conteo, lbl_resumen)
            for w in widgets:
                w.bind("<Button-1>", lambda e, c=cat: self._abrir_categoria_flotante(c))
                w.bind("<Enter>", lambda e, c=cat, wd=card: self._on_cat_enter(c, wd))
                w.bind("<Leave>", lambda e, c=cat: self._on_cat_leave(c))

            self._cat_btns[cat] = (card, lbl_ic, lbl_nombre, lbl_conteo, lbl_resumen, accent)

        self._redibujar_categorias_grid()

    def _redibujar_categorias_grid(self):
        for cat, (card, lbl_ic, lbl_nombre, lbl_conteo, lbl_resumen, accent) in self._cat_btns.items():
            abierta = (cat == self._cat_flotante)
            hover   = (cat == self._cat_hover)

            # NUEVO: cada categoría tiene un color de identidad
            # PERMANENTE (ver CATEGORIA_COLOR_BASE) — antes el color
            # solo aparecía al pasar el mouse o al abrir, y en reposo
            # todo quedaba en el mismo gris apagado. Ahora, en reposo,
            # ícono/nombre/conteo ya usan ese color propio (más tenue
            # que a pleno brillo); hover lo aclara, abrir la ventana
            # flotante lo lleva a su versión más brillante, y el pulso
            # de actividad reciente (ver _pulsar_categoria/_tick_pulsos)
            # puede pisar momentáneamente cualquiera de los anteriores.
            pulso     = self._pulso_categoria.get(cat, 0.0)
            color_cat = self.CATEGORIA_COLOR_BASE[cat]

            if abierta:
                color_texto = color_cat
            elif hover:
                color_texto = _mezclar_hex(color_cat, C["texto"], 0.3)
            else:
                color_texto = _mezclar_hex(color_cat, C["texto_dim"], 0.45)

            bg_base = C["bg"] if abierta else C["bg2"]
            if pulso > 0.01:
                bg_final = _mezclar_hex(color_cat, bg_base, 1 - pulso * 0.6)
                accent.config(bg=_mezclar_hex(color_cat, C["bg"], 1 - pulso))
            else:
                bg_final = bg_base
                accent.config(bg=_mezclar_hex(color_cat, bg_base, 0.6))

            for w in (card, lbl_ic, lbl_nombre, lbl_conteo, lbl_resumen):
                w.config(bg=bg_final)
            lbl_ic.config(fg=color_texto)
            lbl_nombre.config(fg=color_texto)
            lbl_conteo.config(fg=color_texto)

            conteo = self._contar_categoria(cat)
            lbl_conteo.config(text=str(conteo) if conteo < 100 else "99+")

            resumen = self._resumen_categoria(cat)
            lbl_resumen.config(text="\n".join(resumen) if resumen else "—")

    def _on_cat_enter(self, cat, widget):
        self._cat_hover = cat
        self._redibujar_categorias_grid()
        self._tooltip_after_ids[cat] = self.root.after(
            450, lambda: self._tooltip.show(widget, self.CATEGORIA_NOMBRE[cat])
        )

    def _on_cat_leave(self, cat):
        if self._cat_hover == cat:
            self._cat_hover = None
            self._redibujar_categorias_grid()
        pendiente = self._tooltip_after_ids.pop(cat, None)
        if pendiente is not None:
            try:
                self.root.after_cancel(pendiente)
            except Exception:
                pass
        self._tooltip.hide()

    # NUEVO: color de identidad PERMANENTE de cada categoría — mismo
    # que usa siempre esa tarjeta en reposo (ver
    # _redibujar_categorias_grid) y también el que toma el pulso de
    # actividad reciente (ver _pulsar_categoria/_tick_pulsos). Sigue
    # la misma convención de color que ya usaba cada lista individual
    # (temporizadores/alias en cian, recordatorios en amarillo);
    # macros usa el tono neutro de texto para no competir tanto.
    CATEGORIA_COLOR_BASE = {
        "temporizadores": C["acento"],
        "recordatorios":  C["amarillo"],
        "alias":          C["acento"],
        "macros":         C["texto"],
    }

    def _pulsar_categoria(self, cat):
        self._pulso_categoria[cat] = 1.0

    def _tick_pulsos(self):
        cambio = False
        for cat, valor in self._pulso_categoria.items():
            if valor > 0.01:
                self._pulso_categoria[cat] = max(0.0, valor - 0.06)
                cambio = True
        if cambio:
            self._redibujar_categorias_grid()

    # FIX/NUEVO: snapshot liviano de los datos de una categoría, sin
    # tocar la UI — se usa para detectar si de verdad cambió algo en
    # disco antes de repintar la grilla o la ventana flotante (ver
    # _polling), y para decidir cuándo disparar el pulso de "algo
    # nuevo llegó" en la tarjeta correspondiente (ver _pulsar_categoria).
    def _firma_categoria(self, cat):
        try:
            if cat == "temporizadores":
                from temporizadores import listar_temporizadores
                d = listar_temporizadores()
                return tuple(sorted(
                    (k, v.get("momento"), v.get("nombre")) for k, v in d.items()
                ))
            if cat == "recordatorios":
                from recordatorios import listar_recordatorios
                d = listar_recordatorios()
                return tuple(sorted(
                    (k, v.get("momento"), v.get("texto"), v.get("recurrencia"))
                    for k, v in d.items()
                ))
            if cat == "alias":
                from aliases import listar_aliases
                return tuple(sorted(listar_aliases().items()))
            if cat == "macros":
                from macros import listar_macros
                d = listar_macros()
                return tuple(sorted((k, len(v)) for k, v in d.items()))
        except Exception:
            return None
        return None

    # NUEVO (rediseño "panel denso animado"): ventana flotante con la
    # lista completa de una categoría — reemplaza el contenido
    # expandido in-place que antes empujaba/tapaba al historial. Vive
    # anclada al lado IZQUIERDO del panel (que a su vez está anclado
    # arriba a la derecha de la pantalla, ver _anchor_x_right), así
    # nunca se superpone con el panel principal. Solo una a la vez:
    # abrir otra categoría, o volver a tocar la misma, la cierra.
    FLOTANTE_ANCHO       = 260
    FLOTANTE_ALTO_MAXIMO = 260

    def _abrir_categoria_flotante(self, cat):
        if self._cat_flotante == cat:
            self._cerrar_categoria_flotante()
            return

        self._cerrar_categoria_flotante()
        self._cat_flotante = cat
        self._firma_categorias[cat] = self._firma_categoria(cat)

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=C["borde"])
        self._win_flotante = win

        x = self.root.winfo_x() - self.FLOTANTE_ANCHO - 8
        y = self.root.winfo_y() + 90
        win.geometry(f"{self.FLOTANTE_ANCHO}x{self.FLOTANTE_ALTO_MAXIMO}+{x}+{y}")

        cabecera = tk.Frame(win, bg=C["bg2"])
        cabecera.pack(fill="x", padx=1, pady=(1, 0))
        tk.Label(cabecera, text=f"{self.CATEGORIA_ICONO[cat]}  {self.CATEGORIA_NOMBRE[cat]}",
                 font=(C["ui"], 9, "bold"), fg=C["acento"], bg=C["bg2"]
                 ).pack(side="left", padx=8, pady=6)
        btn_cerrar = tk.Label(cabecera, text="×", font=(C["ui"], 13),
                              fg=C["texto_dim"], bg=C["bg2"], cursor="hand2")
        btn_cerrar.pack(side="right", padx=6)
        btn_cerrar.bind("<Button-1>", lambda e: self._cerrar_categoria_flotante())

        cuerpo = tk.Frame(win, bg=C["bg"])
        cuerpo.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        self._contenido_flotante = cuerpo
        self._poblar_categoria_flotante()

        # se cierra sola si pierde el foco (clic afuera) — mismo
        # comportamiento esperable de cualquier popup/menú flotante.
        win.bind("<FocusOut>", lambda e: self._cerrar_categoria_flotante())
        win.focus_force()

        self._redibujar_categorias_grid()

    def _poblar_categoria_flotante(self):
        cat = self._cat_flotante
        if cat is None or self._win_flotante is None:
            return
        for w in self._contenido_flotante.winfo_children():
            w.destroy()
        contenedor = self._crear_area_scrollable(
            self._contenido_flotante, alto=self.FLOTANTE_ALTO_MAXIMO - 34
        )
        if cat == "alias":
            self._renderizar_alias(contenedor, cat=cat)
        else:
            self._renderizar_lista_simple(contenedor, cat)

    def _cerrar_categoria_flotante(self):
        if self._win_flotante is not None:
            try:
                self._win_flotante.destroy()
            except Exception:
                pass
        self._win_flotante   = None
        self._cat_flotante   = None
        self._contenido_flotante = None
        self._redibujar_categorias_grid()

    def _crear_area_scrollable(self, parent, alto=FLOTANTE_ALTO_MAXIMO):
        wrap = tk.Frame(parent, bg=C["bg"])
        wrap.pack(fill="both", expand=True)

        canvas = tk.Canvas(wrap, bg=C["bg"], highlightthickness=0, height=alto)
        scrollbar = _BarraScroll(wrap, canvas.yview)
        inner = tk.Frame(canvas, bg=C["bg"])

        item_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        # el frame interno sigue el ANCHO del canvas (no su alto) —
        # así las columnas de alias (o cualquier fila) usan todo el
        # ancho disponible en vez de encogerse a su contenido mínimo.
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(item_id, width=e.width))

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # NUEVO: rueda del mouse para scrollear — Windows manda un
        # solo evento <MouseWheel> con event.delta (+/-120 por paso);
        # X11 (Linux) no tiene ese evento en absoluto, manda en cambio
        # <Button-4>/<Button-5> como si fueran clics de mouse — se
        # atienden los tres, cada plataforma dispara solo el que le
        # corresponde. bind_all/unbind_all (no bind directo al canvas)
        # porque la rueda del mouse no siempre llega al widget exacto
        # bajo el cursor en Tkinter; se activa solo mientras el mouse
        # está DENTRO de este canvas (Enter/Leave) para no capturar la
        # rueda de otras partes del panel mientras tanto.
        def _rueda_windows(event):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        def _rueda_linux(event):
            canvas.yview_scroll(-1 if event.num == 4 else 1, "units")

        def _activar_rueda(_e=None):
            canvas.bind_all("<MouseWheel>", _rueda_windows)
            canvas.bind_all("<Button-4>", _rueda_linux)
            canvas.bind_all("<Button-5>", _rueda_linux)

        def _desactivar_rueda(_e=None):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", _activar_rueda)
        canvas.bind("<Leave>", _desactivar_rueda)

        return inner

    # ── fila genérica con confirmación de borrado + animación ──
    # FIX/NUEVO: reemplaza los messagebox.askyesno(...) que usaban
    # antes eliminar_alias/eliminar_macro/cancelar_rec — una ventana
    # modal del sistema aparte, que corta el flujo y no combina en
    # nada con el resto del panel. Ahora cada fila tiene su propia
    # confirmación inline: un primer clic en "✕" la pone en modo
    # "¿Eliminar? ✓" (fondo rojo tenue); un segundo clic ahí confirma
    # de verdad y dispara una animación corta de desvanecido (mezcla
    # de color hacia el fondo, en pasos) antes de sacarla de la lista
    # — Tkinter no tiene opacidad real, así que el desvanecido se
    # simula interpolando el color de fondo con _mezclar_hex, el mismo
    # helper que ya usa el pulso del puntito del header.
    #
    # Si el segundo clic nunca llega, la fila vuelve sola al estado
    # normal después de CONFIRMAR_BORRADO_TIMEOUT_MS (ver
    # _confirmaciones_pendientes en __init__).

    def _crear_fila_lista(self, parent, clave, texto_principal,
                          texto_secundario, on_eliminar, cat=None):
        row = tk.Frame(parent, bg=C["bg2"])
        row.pack(fill="x", pady=1)

        izq = tk.Frame(row, bg=C["bg2"])
        izq.pack(side="left", fill="both", expand=True, padx=(8, 4), pady=4)

        lbl_principal = tk.Label(izq, text=texto_principal, font=(C["mono"], 9),
                                 fg=C["texto"], bg=C["bg2"], anchor="w")
        lbl_principal.pack(fill="x")

        lbl_secundario = None
        if texto_secundario:
            lbl_secundario = tk.Label(izq, text=texto_secundario, font=(C["mono"], 8),
                                      fg=C["texto_dim"], bg=C["bg2"], anchor="w")
            lbl_secundario.pack(fill="x")

        btn = tk.Label(row, text="✕", font=(C["ui"], 10),
                       fg=C["texto_dim"], bg=C["bg2"], cursor="hand2", padx=8)
        btn.pack(side="right")

        widgets_fondo = [row, izq, lbl_principal, btn] + ([lbl_secundario] if lbl_secundario else [])

        def _pintar(bg, fg_principal, fg_secundario, texto_btn, fg_btn):
            for w in widgets_fondo:
                w.config(bg=bg)
            lbl_principal.config(fg=fg_principal)
            if lbl_secundario:
                lbl_secundario.config(fg=fg_secundario)
            btn.config(text=texto_btn, fg=fg_btn)

        def _revertir():
            self._confirmaciones_pendientes.pop(clave, None)
            _pintar(C["bg2"], C["texto"], C["texto_dim"], "✕", C["texto_dim"])

        def _fundir_y_eliminar(paso=0, pasos=6):
            if paso > pasos:
                try:
                    on_eliminar()
                finally:
                    # FIX/NUEVO: antes esto destruía TODO el contenido
                    # de la categoría y lo reconstruía entero -- por
                    # más que se preservara altura y scroll, ese
                    # tear-down/rebuild masivo de golpe se sentía como
                    # un parpadeo, y encima pisaba visualmente el
                    # desvanecido que la fila ya venía haciendo.
                    #
                    # Ahora se destruye SOLO esta fila (para este
                    # punto ya terminó de desvanecerse hasta el color
                    # de fondo, así que sacarla no se nota como un
                    # cambio) -- pack() reacomoda automáticamente el
                    # resto de las filas para llenar el hueco, sin
                    # tocar nada más. Ya no hace falta reconstruir el
                    # canvas ni restaurar altura/scroll: como nada más
                    # se destruye, ninguno de los dos se pierde.
                    try:
                        row.destroy()
                    except Exception:
                        pass
                    self._on_lista_cambiada(cat)
                return
            factor = 1 - (paso / pasos)
            tono   = _mezclar_hex(CONFIRMAR_BORRADO_BG, C["bg"], factor)
            for w in widgets_fondo:
                w.config(bg=tono)
            self.root.after(28, lambda: _fundir_y_eliminar(paso + 1, pasos))

        def _click(_e=None):
            if clave in self._confirmaciones_pendientes:
                after_id = self._confirmaciones_pendientes.pop(clave, None)
                if after_id is not None:
                    try:
                        self.root.after_cancel(after_id)
                    except Exception:
                        pass
                _fundir_y_eliminar()
            else:
                _pintar(CONFIRMAR_BORRADO_BG, "#ff8a8a", "#a85a5a", "✓", "#ff8a8a")
                self._confirmaciones_pendientes[clave] = self.root.after(
                    CONFIRMAR_BORRADO_TIMEOUT_MS, _revertir
                )

        for w in widgets_fondo:
            w.bind("<Button-1>", _click)

        return row

    def _label_vacio_categoria(self, parent, mensaje):
        tk.Label(parent, text=mensaje, font=(C["ui"], 9),
                 fg=C["texto_dim"], bg=C["bg"], justify="center",
                 wraplength=self.FLOTANTE_ANCHO - 24).pack(pady=14)

    # NUEVO: se llama después de borrar una fila desde la ventana
    # flotante — actualiza la firma guardada de esa categoría (para
    # que el polling no la confunda con un cambio "externo" y dispare
    # un pulso de más) y repinta la grilla del panel principal, cuyo
    # conteo/resumen quedaron desactualizados.
    def _on_lista_cambiada(self, cat):
        if cat is not None:
            self._firma_categorias[cat] = self._firma_categoria(cat)
        self._redibujar_categorias_grid()

    # ── temporizadores / recordatorios / macros (mismo patrón) ──

    def _renderizar_lista_simple(self, parent, cat):
        try:
            if cat == "temporizadores":
                from temporizadores import listar_temporizadores, cancelar_temporizador
                items = sorted(listar_temporizadores().items())
                if not items:
                    self._label_vacio_categoria(
                        parent, 'Sin temporizadores activos.\nDecí "pon un temporizador de..." para crear uno.')
                    return
                for id_str, info in items:
                    try:
                        momento = datetime.fromisoformat(info["momento"])
                        cuando  = momento.strftime("%H:%M")
                    except Exception:
                        cuando = "—"
                    nombre = info.get("nombre") or "sin nombre"
                    self._crear_fila_lista(
                        parent, f"temp:{id_str}", nombre, f"suena a las {cuando}",
                        lambda i=id_str: cancelar_temporizador(i), cat=cat,
                    )
                return

            if cat == "recordatorios":
                from recordatorios import listar_recordatorios_ordenados, cancelar_recordatorio
                items = listar_recordatorios_ordenados()
                if not items:
                    self._label_vacio_categoria(
                        parent, 'Todavía no tenés recordatorios.\nDecí "recuérdame..." para crear uno.')
                    return
                for id_str, info in items:
                    try:
                        desde  = datetime.fromisoformat(info["momento"])
                        cuando = desde.strftime("%d/%m %H:%M")
                    except Exception:
                        cuando = "—"
                    if info.get("recurrencia"):
                        cuando += "  ↻"
                    self._crear_fila_lista(
                        parent, f"rec:{id_str}", info.get("texto", ""), cuando,
                        lambda i=id_str: cancelar_recordatorio(i), cat=cat,
                    )
                return

            if cat == "macros":
                from macros import listar_macros, eliminar_macro
                items = sorted(listar_macros().items())
                if not items:
                    self._label_vacio_categoria(
                        parent, 'Todavía no creaste ninguna macro.\nDecí "crea una macro" para empezar.')
                    return
                for nombre, pasos in items:
                    self._crear_fila_lista(
                        parent, f"macro:{nombre}", nombre, f"{len(pasos)} pasos",
                        lambda n=nombre: eliminar_macro(n), cat=cat,
                    )
                return
        except Exception as e:
            self._label_vacio_categoria(parent, f"Error: {e}")

    # ── alias — dos columnas: con alias / sin alias (cache) ──
    # NUEVO: a pedido, separadas en dos columnas en vez de una sola
    # lista mezclada — a la izquierda los alias YA registrados,
    # agrupados por app real (mismo agrupamiento que ya hace
    # alias_por_app() en aliases.py); a la derecha las apps que están
    # en app_finder.cache pero todavía no tienen ningún alias, con un
    # "+" para arrancar el flujo de registrar uno.

    def _renderizar_alias(self, parent, cat="alias"):
        try:
            from aliases import listar_aliases, eliminar_alias, alias_por_app
            import app_finder
        except Exception as e:
            self._label_vacio_categoria(parent, f"Error: {e}")
            return

        cols = tk.Frame(parent, bg=C["bg"])
        cols.pack(fill="x")

        col_con    = tk.Frame(cols, bg=C["bg"])
        col_sin    = tk.Frame(cols, bg=C["bg"])
        col_con.pack(side="left", fill="both", expand=True, padx=(0, 4))
        col_sin.pack(side="left", fill="both", expand=True, padx=(4, 0))

        tk.Label(col_con, text="CON ALIAS", font=(C["ui"], 7),
                 fg=C["texto_dim"], bg=C["bg"]).pack(anchor="w", pady=(0, 3))
        tk.Label(col_sin, text="SIN ALIAS", font=(C["ui"], 7),
                 fg=C["texto_dim"], bg=C["bg"]).pack(anchor="w", pady=(0, 3))

        try:
            data = listar_aliases()
        except Exception:
            data = {}

        # agrupar alias por app real (misma app puede tener varios)
        por_app = {}
        for alias, real in sorted(data.items()):
            por_app.setdefault(real, []).append(alias)

        if not por_app:
            self._label_vacio_categoria(
                col_con, 'Sin alias todavía.\nDecí "registra un alias".')
        else:
            for real, lista_alias in sorted(por_app.items()):
                tk.Label(col_con, text=real, font=(C["mono"], 8),
                         fg=C["texto_dim"], bg=C["bg"], anchor="w").pack(fill="x", pady=(4, 1))
                for alias in lista_alias:
                    self._crear_fila_lista(
                        col_con, f"alias:{alias}", alias, None,
                        lambda a=alias: eliminar_alias(a), cat=cat,
                    )

        # apps en cache sin ningún alias registrado todavía
        try:
            nombres_cache = list(app_finder.cache.keys())
        except Exception:
            nombres_cache = []

        sin_alias = [n for n in nombres_cache if not alias_por_app(n)]

        if not sin_alias:
            self._label_vacio_categoria(col_sin, "Nada pendiente por acá.")
        else:
            for nombre_app in sorted(sin_alias):
                fila = tk.Frame(col_sin, bg=C["bg2"])
                fila.pack(fill="x", pady=1)
                tk.Label(fila, text=nombre_app, font=(C["mono"], 8),
                         fg=C["texto"], bg=C["bg2"], anchor="w").pack(
                             side="left", fill="both", expand=True, padx=(8, 4), pady=4)
                btn_mas = tk.Label(fila, text="+", font=(C["ui"], 11, "bold"),
                                   fg=C["acento"], bg=C["bg2"], cursor="hand2", padx=8)
                btn_mas.pack(side="right")
                # NOTA: registrar_alias_manual() es un flujo por VOZ
                # (pregunta la app y los alias hablando) — acá solo se
                # dispara en un hilo aparte para no bloquear el
                # mainloop de Tkinter mientras dura la conversación;
                # no pre-completa el nombre de la app todavía (ver
                # registrar_alias.py, que ignora su parámetro `valor`
                # de momento), así que el asistente igual va a
                # preguntar de viva voz para cuál app es.
                btn_mas.bind("<Button-1>", lambda e, n=nombre_app: self._registrar_alias_para(n))

    def _registrar_alias_para(self, nombre_app):
        try:
            from registrar_alias import registrar_alias_manual
        except Exception:
            return
        threading.Thread(
            target=registrar_alias_manual, args=(nombre_app,), daemon=True
        ).start()

    # ── historial (siempre visible) ────────────────────────

    def _build_historial(self, parent):
        tk.Label(parent, text="HISTORIAL", font=(C["ui"], 7),
                 fg=C["texto_dim"], bg=C["bg"]).pack(anchor="w", padx=12, pady=(6, 2))

        f = tk.Frame(parent, bg=C["bg"])
        f.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        self.hist_list = tk.Listbox(
            f, bg=C["bg"], fg=C["texto"],
            selectbackground=C["bg2"],
            font=(C["mono"], 9),
            borderwidth=0, highlightthickness=0,
            activestyle="none", relief="flat",
            selectforeground=C["acento"],
        )
        sb = _BarraScroll(f, self.hist_list.yview)
        self.hist_list.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.hist_list.pack(fill="both", expand=True)
        self.hist_vacio = tk.Label(
            f, text="", font=(C["ui"], 9), fg=C["texto_dim"], bg=C["bg"],
            justify="center", wraplength=ANCHO - 36,
        )

    def _actualizar_historial(self):
        try:
            from ui_estado import get_historial
            items = get_historial()
            if not items:
                self.hist_list.delete(0, tk.END)
                self.hist_vacio.config(text='Todavía no hay comandos.\nDecí "jarvis" para empezar.')
                self.hist_vacio.place(relx=0.5, rely=0.3, anchor="center", width=ANCHO - 40)
                return
            self.hist_vacio.place_forget()
            self.hist_list.delete(0, tk.END)
            for item in items:
                ts   = item.get("ts", "")
                cmd  = item.get("cmd", "")
                resp = item.get("resp", "")
                self.hist_list.insert(tk.END, f"  {ts}  ›  {cmd}")
                self.hist_list.itemconfig(tk.END, fg=C["acento_dim"])
                if resp:
                    r_short = resp[:38] + "…" if len(resp) > 38 else resp
                    self.hist_list.insert(tk.END, f"      {r_short}")
                    self.hist_list.itemconfig(tk.END, fg=C["texto_dim"])
                self.hist_list.insert(tk.END, "")
                self.hist_list.itemconfig(tk.END, fg=C["bg"])
        except Exception:
            pass

    # ── footer ──────────────────────────────────────────

    def _build_footer(self, parent):
        tk.Frame(parent, bg=C["borde2"], height=1).pack(fill="x")
        f = tk.Frame(parent, bg=C["bg3"], pady=5)
        f.pack(fill="x")

        self.lbl_ww = tk.Label(f, text='wake word: jarvis',
                               font=(C["mono"], 8),
                               fg=C["borde"], bg=C["bg3"])
        self.lbl_ww.pack(side="left", padx=10)

        self.cv_fdot = tk.Canvas(f, width=6, height=6,
                                 bg=C["bg3"], highlightthickness=0)
        self.cv_fdot.pack(side="right", padx=10)
        self.fdot_id = self.cv_fdot.create_oval(1, 1, 5, 5,
                                                fill=C["borde2"], outline="")

    # ── polling ─────────────────────────────────────────

    def _polling(self):
        try:
            self._tick_clock()
            self._tick_estado()
            self._tick_orbe()
            if self.expandido:
                self._tick_dot_header()
                self._tick_header_accent()
                # FIX/NUEVO: el historial ahora se ve siempre (ya no
                # depende de qué pestaña esté activa, ver el rediseño
                # del cuerpo del panel), así que se actualiza siempre
                # que el panel está expandido, sin condición.
                self._actualizar_historial()

                # NUEVO (rediseño "panel denso animado"): la grilla de
                # categorías, y la ventana flotante si hay una abierta,
                # se recalculan cada ~20 vueltas de polling (~1.2s con
                # el intervalo de 60ms de abajo) en vez de en cada tick
                # — son datos que cambian poco de un momento a otro,
                # así que no hace falta releerlos 16 veces por
                # segundo. Se compara una firma liviana de cada
                # categoría (ver _firma_categoria): si cambió, se
                # dispara el pulso de color de esa tarjeta (ver
                # _pulsar_categoria) para que se note de un vistazo qué
                # categoría tuvo actividad nueva, además de repintar.
                self._contadores_tick_contador += 1
                if self._contadores_tick_contador % 20 == 0:
                    for cat in self.CATEGORIAS:
                        nueva_firma = self._firma_categoria(cat)
                        if nueva_firma != self._firma_categorias[cat]:
                            self._firma_categorias[cat] = nueva_firma
                            self._pulsar_categoria(cat)
                    self._redibujar_categorias_grid()
                    if self._cat_flotante is not None:
                        self._poblar_categoria_flotante()

                # el decaimiento del pulso sí corre en cada tick (no
                # solo cada 20 vueltas) para que la animación de
                # apagado se vea suave en vez de a saltos.
                self._tick_pulsos()
        except Exception:
            pass
        self.root.after(60, self._polling)

    def _tick_clock(self):
        now = datetime.now()
        self.lbl_clock.config(text=now.strftime("%H:%M:%S"))

    def _tick_estado(self):
        try:
            from ui_estado import get_estado
            estado = get_estado()
            modo   = estado.get("modo", "inactivo")
            motor  = estado.get("motor_ia", "—")
            ww     = estado.get("wake_word", "jarvis")

            info = self.ESTADOS.get(modo, self.ESTADOS["inactivo"])
            self.lbl_estado.config(text=info["txt"], fg=info["color"])
            self.lbl_motor.config(text=motor)
            self.lbl_ww.config(text=f"wake word: {ww}")

            # NUEVO: mismas fuentes de datos (motor/wake word), ahora
            # también reflejadas en las tarjetas de métricas de arriba
            # del panel — ver _build_metricas(). no_molestar se lee
            # acá también para no agregar un tercer get_estado() extra
            # por tick.
            no_molestar = estado.get("no_molestar", False)
            self.lbl_ww_card.config(text=ww)
            self.lbl_motor_card.config(text=motor,
                                       fg=(C["acento"] if motor == "Groq" else C["texto"]))
            self.lbl_nomolestar_card.config(
                text=("On" if no_molestar else "Off"),
                fg=(C["rojo"] if no_molestar else C["texto_dim"]),
            )

            fd_colors = {
                "escuchando": "#123b33",
                "procesando": "#3a3312",
                "hablando":   "#0f3129",
            }
            fd = fd_colors.get(modo, C["borde2"])
            self.cv_fdot.itemconfig(self.fdot_id, fill=fd)
        except Exception:
            pass

    def _tick_header_accent(self):
        """
        Actualiza el color de la franja superior del header según el
        modo actual — no molestar tiene prioridad sobre cualquier
        modo (rojo), igual que en el orbe chico (ver _dibujar_orbe).
        """
        try:
            from ui_estado import get_estado
            estado      = get_estado()
            modo        = estado.get("modo", "inactivo")
            no_molestar = estado.get("no_molestar", False)

            color = C["rojo"] if no_molestar else COLORES_ACCENT_MODO.get(modo, C["borde"])
            self.header_accent.config(bg=color)
        except Exception:
            pass

    def _tick_dot_header(self):
        try:
            from ui_estado import get_estado
            modo = get_estado().get("modo", "inactivo")
            info = self.ESTADOS.get(modo, self.ESTADOS["inactivo"])
            if modo == "inactivo":
                self.cv_dot.itemconfig(self.dot_id, outline=C["borde2"])
            else:
                self._pulse = (self._pulse + 0.12) % (2 * math.pi)
                t = (math.sin(self._pulse) + 1) / 2
                blended = _mezclar_hex(info["dot"], C["bg2"], 0.3 + 0.7 * t)
                self.cv_dot.itemconfig(self.dot_id, outline=blended)

            # NUEVO: la mini-carita del header se redibuja cada tick,
            # igual que la del orbe chico (ver _dibujar_orbe) — mismo
            # parpadeo (self._ojos_cerrados) y misma expresión por modo,
            # solo que a escala reducida (radio ~10 en vez de 24).
            self.cv_dot.delete("cara")
            self._dibujar_cara(self.cv_dot, modo, cx=12, cy=12, escala=0.42, tag="cara")
        except Exception:
            pass

    def _tick_orbe(self):
        try:
            from ui_estado import get_estado
            estado       = get_estado()
            modo         = estado.get("modo", "inactivo")
            no_molestar  = estado.get("no_molestar", False)
        except Exception:
            modo        = "inactivo"
            no_molestar = False

        self._orb_fase = (self._orb_fase + 0.18) % (2 * math.pi)
        self._tick_parpadeo()

        if not self.expandido:
            self._dibujar_orbe(modo, no_molestar)

    # NUEVO: cuenta regresiva hasta el próximo parpadeo — al llegar a
    # 0 cierra los ojos por PARPADEO_DURACION_TICKS y elige un próximo
    # intervalo aleatorio, para que no se sienta mecánico/perfectamente
    # regular. _tick_orbe corre cada ~60ms (ver _polling), así que
    # estos números son "ticks", no milisegundos exactos.
    PARPADEO_DURACION_TICKS = 3

    def _tick_parpadeo(self):
        self._parpadeo_cuenta -= 1
        if self._parpadeo_cuenta <= -self.PARPADEO_DURACION_TICKS:
            self._ojos_cerrados   = False
            self._parpadeo_cuenta = random.randint(30, 90)
        elif self._parpadeo_cuenta <= 0:
            self._ojos_cerrados = True


# =========================================================
# LANZAR
# =========================================================

_root_ui   = None
_ui_activa = False


def iniciar_ui():
    global _ui_activa
    if _ui_activa:
        return

    # FIX: antes esto creaba un tk.Tk() PROPIO en un hilo NUEVO
    # ("AsistenteUI"), separado del hilo del splash ("SplashUI").
    # Aunque para este momento el splash ya había "cerrado", crear un
    # SEGUNDO intérprete de Tcl en un SEGUNDO hilo distinto -- para
    # abrir la conexión con el servidor X11 -- hace que el notifier de
    # eventos de Tcl 9 (basado en epoll, ver TIP 458) falle con
    # "epoll_ctl: Invalid argument" en el sandbox de Distrobox/Bazzite,
    # y Tcl aborta TODO el proceso con Tcl_Panic sin que Python pueda
    # atraparlo (confirmado con PYTHONFAULTHANDLER=1 — el stack cae
    # justo en TkpOpenDisplay, al hacer tk.Tk() acá).
    #
    # Ahora se reutiliza el MISMO root/hilo de Tcl que el splash ya
    # usó con éxito (splash.py ya NO destruye su root al "cerrarlo",
    # solo lo oculta — ver cerrar_splash()/SplashUI._tick) — así, en
    # toda la vida del proceso, un único hilo abre un único notifier
    # de Tcl. Se usa el mismo mecanismo (ejecutar_en_hilo_gui) que ya
    # usan los diálogos de arranque (setup_groq_gui.py) para compartir
    # ese root entre hilos de forma segura.
    from splash import obtener_root, ejecutar_en_hilo_gui

    def _construir(root):
        global _root_ui, _ui_activa
        _root_ui   = root
        _ui_activa = True
        AsistenteUI(root)
        # FIX: este root viene OCULTO -- splash.py lo dejó con
        # withdraw() al "cerrar" el splash (ver SplashUI._tick), en
        # vez de destruirlo, justamente para poder reutilizarlo acá.
        # Con un tk.Tk() nuevo esto nunca hacía falta (una ventana
        # arranca visible por defecto), pero ahora hay que pedirle
        # explícitamente que se vuelva a mostrar, o el orbe queda
        # construido pero invisible para siempre.
        root.deiconify()
        iniciar_bandeja(mostrar_ui, cerrar_definitivo)

    root_compartido = obtener_root()

    if root_compartido is not None:
        ejecutar_en_hilo_gui(_construir)
        return

    # Respaldo: si por algún motivo no hay un root de splash
    # disponible (ej. el splash falló al arrancar), se cae al
    # comportamiento anterior — root propio en un hilo propio — que
    # sigue funcionando en Windows y en la mayoría de entornos Linux
    # fuera de un contenedor.
    def _run():
        global _ui_activa
        try:
            root = tk.Tk()
            _construir(root)
            root.mainloop()
        except Exception as e:
            print(f"[UI] Error: {e}")
        finally:
            _ui_activa = False

    threading.Thread(target=_run, daemon=True, name="AsistenteUI").start()


def mostrar_ui():
    if _root_ui:
        _root_ui.deiconify()
        _root_ui.attributes("-topmost", True)


def ocultar_ui():
    if _root_ui:
        _root_ui.withdraw()


def cerrar_definitivo():
    """
    Cierra el asistente por completo — a diferencia de ocultar_ui()
    (que solo esconde la ventana y deja todo corriendo en segundo
    plano), esto quita el ícono de la bandeja, apaga Ollama si el
    asistente lo había encendido (ver gestor_ia.apagar_todo_al_salir)
    y termina el proceso entero de inmediato.

    Se usa os._exit(0) en vez de sys.exit()/root.destroy() porque
    esto puede llamarse desde un hilo que NO es el principal (el
    hilo de la ventana, o el de la bandeja del sistema) — sys.exit()
    en un hilo secundario solo termina ESE hilo, no el proceso
    completo, y el asistente seguiría corriendo (mic, wake word, todo)
    con la ventana ya cerrada — exactamente el bug que esto arregla.
    """
    try:
        detener_bandeja()
    except Exception:
        pass

    try:
        from gestor_ia import apagar_todo_al_salir
        apagar_todo_al_salir()
    except Exception:
        pass

    import os
    os._exit(0)