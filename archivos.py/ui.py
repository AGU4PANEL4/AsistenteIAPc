"""
Interfaz flotante del asistente — un orbe pequeño, arrastrable, que
al hacer clic se expande a un panel completo con navegación por
íconos a la izquierda (en vez de pestañas arriba). Tema "aurora fría".

FIX/NUEVO: versión anterior era un panel fijo de 300x440 siempre
visible, con pestañas horizontales y sin ninguna animación real por
estado (solo un punto que cambiaba de color). Ahora:
  - En reposo, solo se ve un orbe circular chico (arrastrable a
    cualquier parte de la pantalla).
  - Un clic simple (sin arrastrar) lo expande al panel completo,
    anclado por la misma esquina superior derecha donde estaba el
    orbe — otro clic (o el botón "─" del header) lo vuelve a
    contraer.
  - Cada estado (escuchando/procesando/hablando) tiene su propia
    animación dibujada en el Canvas del orbe, no solo un cambio de
    color: barras tipo ecualizador al escuchar, un spinner de puntos
    al procesar, anillos concéntricos expandiéndose al hablar.

El truco de la forma circular con esquinas transparentes usa
wm_attributes("-transparentcolor", ...), soportado por Tkinter en
Windows — cualquier píxel exactamente de ese color se vuelve
invisible. Por eso TRANSPARENTE es un color que no se usa en
ningún otro lugar de la paleta.
"""

import math
import threading
import tkinter as tk
from tkinter import messagebox
from datetime import datetime

from bandeja import iniciar_bandeja, detener_bandeja
from visual_utils import mezclar_hex as _mezclar_hex, dibujar_puntos_spinner

# =========================================================
# PALETA — "aurora fría"
# =========================================================

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
    "mono":       "Consolas",
    "ui":         "Segoe UI",
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

ANCHO       = 300
ALTO        = 440
SIDEBAR_W   = 34

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
# sin alterar el layout de la sidebar. Aparece con un pequeño retraso
# (ver _on_tab_enter en AsistenteUI) para no destellar en cada barrido
# rápido del mouse sobre la barra.
# =========================================================

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

        # NUEVO: tooltip compartido de la sidebar, ícono bajo el
        # mouse en este momento (o None), e ids de los after()
        # pendientes que muestran el tooltip con retraso — ver
        # _on_tab_enter/_on_tab_leave.
        self._tooltip            = _Tooltip(root)
        self._tab_hover           = None
        self._tooltip_after_ids   = {}

        # NUEVO: contador de vueltas de _polling — los badges de
        # conteo (aliases/macros/recordatorios) se recalculan cada
        # cierta cantidad de vueltas en vez de en cada tick, para no
        # relistar esos datos 16 veces por segundo sin necesidad.
        self._sidebar_tick_contador = 0

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
        r.configure(bg=TRANSPARENTE)
        try:
            r.wm_attributes("-transparentcolor", TRANSPARENTE)
        except tk.TclError:
            # plataforma sin soporte para transparentcolor (no debería
            # pasar en Windows) — el orbe se ve como un cuadrado en
            # vez de un círculo, pero todo lo demás sigue funcionando
            print("[UI] transparentcolor no soportado en esta plataforma")

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
        self.orb_canvas = tk.Canvas(
            self.root, width=ORBE_CANVAS, height=ORBE_CANVAS,
            bg=TRANSPARENTE, highlightthickness=0
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

        self.cv_dot = tk.Canvas(h, width=10, height=10,
                                bg=C["bg2"], highlightthickness=0)
        self.cv_dot.pack(side="left", padx=(12, 6), pady=0, anchor="center")
        self.dot_id = self.cv_dot.create_oval(1, 1, 9, 9,
                                              fill=C["acento"], outline="")

        tk.Label(h, text="ASISTENTE IA",
                 font=(C["mono"], 10, "bold"),
                 fg=C["acento_dim"], bg=C["bg2"]).pack(side="left", anchor="w")

        btn_x = tk.Label(h, text="×", font=(C["ui"], 15),
                         fg=C["borde"], bg=C["bg2"], cursor="hand2")
        btn_x.pack(side="right", padx=(0, 10))
        btn_x.bind("<Button-1>", lambda e: self._preguntar_cierre())
        btn_x.bind("<Enter>",    lambda e: btn_x.config(fg=C["rojo"]))
        btn_x.bind("<Leave>",    lambda e: btn_x.config(fg=C["borde"]))

        # NUEVO: "─" ahora contrae de vuelta al orbe (no oculta del
        # todo) — ocultar por completo se pide desde el diálogo de ×.
        btn_min = tk.Label(h, text="─", font=(C["ui"], 13),
                           fg=C["borde"], bg=C["bg2"], cursor="hand2")
        btn_min.pack(side="right", padx=(0, 2))
        btn_min.bind("<Button-1>", lambda e: self._colapsar())
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

    # ── cuerpo: sidebar de íconos + contenido ─────────────

    def _build_body(self, parent):
        body = tk.Frame(parent, bg=C["bg"])
        body.pack(fill="both", expand=True)

        self._build_sidebar(body)

        content_wrap = tk.Frame(body, bg=C["bg"])
        content_wrap.pack(side="left", fill="both", expand=True)

        self._tab_frames = [
            self._tab_historial(content_wrap),
            self._tab_aliases(content_wrap),
            self._tab_macros(content_wrap),
            self._tab_recs(content_wrap),
        ]
        self._tab_frames[0].pack(fill="both", expand=True)

    ALTURA_ITEM_SIDEBAR = 42

    def _build_sidebar(self, parent):
        self._tab_names  = ["Historial", "Aliases", "Macros", "Recordatorios"]
        self._tab_iconos = ["≡", "⇄", "▤", "◷"]
        self._tab_active = 0
        self._tab_btns   = []   # Canvas por cada ítem, uno por pestaña

        bar = tk.Frame(parent, bg=C["bg3"], width=SIDEBAR_W)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)

        for i, icono in enumerate(self._tab_iconos):
            cv = tk.Canvas(
                bar, width=SIDEBAR_W, height=self.ALTURA_ITEM_SIDEBAR,
                bg=C["bg3"], highlightthickness=0, cursor="hand2",
            )
            cv.pack(side="top", fill="x")

            cv.bind("<Button-1>", lambda e, idx=i: self._switch_tab(idx))
            cv.bind("<Enter>", lambda e, idx=i, w=cv: self._on_tab_enter(idx, w))
            cv.bind("<Leave>", lambda e, idx=i: self._on_tab_leave(idx))

            self._tab_btns.append(cv)

        self._switch_tab(0)

    # ── contadores de la sidebar ──────────────────────────
    # NUEVO: numerito chico sobre cada ícono con cuántos elementos
    # hay guardados (aliases, macros, recordatorios activos) — da
    # información útil de un vistazo, sin tener que entrar a la
    # pestaña para saber si hay algo o no. Historial no tiene
    # contador propio (no es algo que se "acumule" de forma útil de
    # ver de reojo, a diferencia de los otros tres).

    def _contar_para_tab(self, idx):
        # NOTA: Aliases (idx==1) a propósito NO tiene badge — a
        # diferencia de macros/recordatorios (donde saber "cuántos
        # tengo activos" de un vistazo es útil), la cantidad de alias
        # guardados no aporta la misma información accionable, y un
        # numerito ahí todo el tiempo termina siendo ruido visual
        # sin utilidad real.
        try:
            if idx == 2:
                from macros import listar_macros
                return len(listar_macros())
            if idx == 3:
                from recordatorios import listar_recordatorios
                return len(listar_recordatorios())
        except Exception:
            pass
        return 0

    def _redibujar_sidebar(self):
        """Redibuja los 4 íconos de la sidebar: ícono, barra
        indicadora de pestaña activa, y badge de conteo."""
        for i, cv in enumerate(self._tab_btns):
            cv.delete("all")

            activo = (i == self._tab_active)
            hover  = (i == self._tab_hover)
            w, h   = SIDEBAR_W, self.ALTURA_ITEM_SIDEBAR

            cv.config(bg=C["bg"] if activo else C["bg3"])

            # NUEVO: barrita de color a la izquierda del ícono activo
            # — antes la única señal de "cuál pestaña estás viendo"
            # era el color del texto del ícono, sutil y fácil de
            # pasar por alto de un vistazo rápido.
            if activo:
                cv.create_rectangle(0, 6, 3, h - 6, fill=C["acento"], outline="")

            if activo:
                color_icono = C["acento"]
            elif hover:
                color_icono = C["texto"]
            else:
                color_icono = C["texto_dim"]

            cv.create_text(w // 2 + 2, h // 2, text=self._tab_iconos[i],
                           fill=color_icono, font=(C["ui"], 13))

            conteo = self._contar_para_tab(i)
            if conteo > 0:
                bx, by = w - 9, 9
                r      = 7 if conteo < 10 else 9
                cv.create_oval(bx - r, by - r, bx + r, by + r,
                               fill=C["rojo"], outline=cv["bg"], width=1)
                texto_conteo = str(conteo) if conteo < 100 else "99+"
                cv.create_text(bx, by, text=texto_conteo,
                               fill="#ffffff", font=(C["ui"], 7, "bold"))

    # ── tooltips de la sidebar ────────────────────────────

    def _on_tab_enter(self, idx, widget):
        self._tab_hover = idx
        self._redibujar_sidebar()

        # se muestra con un pequeño retraso, no al instante, para
        # que un barrido rápido del mouse sobre la barra no haga
        # destellar varios tooltips seguidos
        self._tooltip_after_ids[idx] = self.root.after(
            450, lambda: self._tooltip.show(widget, self._tab_names[idx])
        )

    def _on_tab_leave(self, idx):
        if self._tab_hover == idx:
            self._tab_hover = None
            self._redibujar_sidebar()

        pendiente = self._tooltip_after_ids.pop(idx, None)
        if pendiente is not None:
            try:
                self.root.after_cancel(pendiente)
            except Exception:
                pass

        self._tooltip.hide()

    def _switch_tab(self, idx):
        self._tab_active = idx
        self._redibujar_sidebar()

        if hasattr(self, "_tab_frames"):
            for i, f in enumerate(self._tab_frames):
                if i == idx:
                    f.pack(fill="both", expand=True)
                else:
                    f.pack_forget()

            if idx == 1:
                self._recargar_aliases()
            elif idx == 2:
                self._recargar_macros()
            elif idx == 3:
                self._recargar_recs()
    # ── mensaje de estado vacío (envuelve texto largo) ───
    # FIX/NUEVO: los mensajes de "todavía no hay X — decí Y para
    # crear uno" se insertaban antes como filas normales del Listbox
    # — pero un Listbox NO envuelve texto (no hace salto de línea):
    # en esta ventana angosta (300px, menos la sidebar), un mensaje
    # de más de ~35 caracteres quedaba cortado a la mitad sin ningún
    # aviso, ilegible.
    #
    # Ahora se muestra en un Label aparte, superpuesto con place()
    # sobre el Listbox (vacío en ese momento), con wraplength —
    # Tkinter parte el texto en tantas líneas como haga falta para
    # que quepa en el ancho disponible, sin importar cuán largo sea
    # el mensaje ni tener que adivinar cuántos caracteres entran.

    def _crear_label_vacio(self, parent):
        return tk.Label(
            parent, text="", font=(C["ui"], 9),
            fg=C["texto_dim"], bg=C["bg"], justify="center",
            wraplength=ANCHO - SIDEBAR_W - 36,
        )

    def _mostrar_vacio(self, listbox, label_vacio, mensaje):
        listbox.delete(0, tk.END)
        label_vacio.config(text=mensaje)
        label_vacio.place(relx=0.5, rely=0.38, anchor="center",
                          width=ANCHO - SIDEBAR_W - 24)

    def _ocultar_vacio(self, label_vacio):
        label_vacio.place_forget()
# ── historial ───────────────────────────────────────

    def _tab_historial(self, parent):
        f = tk.Frame(parent, bg=C["bg"])

        self.hist_list = tk.Listbox(
            f, bg=C["bg"], fg=C["texto"],
            selectbackground=C["bg2"],
            font=(C["mono"], 9),
            borderwidth=0, highlightthickness=0,
            activestyle="none", relief="flat",
            selectforeground=C["acento"],
        )
        sb = tk.Scrollbar(f, orient="vertical", command=self.hist_list.yview,
                          bg=C["bg2"], troughcolor=C["bg"], width=6,
                          highlightthickness=0)
        self.hist_list.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=6)
        self.hist_list.pack(fill="both", expand=True, padx=10, pady=6)
        self.hist_vacio = self._crear_label_vacio(f)
        return f

    def _actualizar_historial(self):
        try:
            from ui_estado import get_historial
            items = get_historial()
            if not items:
                self._mostrar_vacio(
                    self.hist_list, self.hist_vacio,
                    'Todavía no hay comandos.\nDecí "jarvis" para empezar.'
                )
                return
            self._ocultar_vacio(self.hist_vacio)
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

    # ── aliases ─────────────────────────────────────────

    def _tab_aliases(self, parent):
        f = tk.Frame(parent, bg=C["bg"])

        self.alias_list = tk.Listbox(
            f, bg=C["bg"], fg=C["texto"],
            selectbackground=C["bg2"],
            font=(C["mono"], 9),
            borderwidth=0, highlightthickness=0,
            activestyle="none", relief="flat",
        )
        sb = tk.Scrollbar(f, orient="vertical", command=self.alias_list.yview,
                          bg=C["bg2"], troughcolor=C["bg"], width=6,
                          highlightthickness=0)
        self.alias_list.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=6)
        self.alias_list.pack(fill="both", expand=True, padx=10, pady=6)
        self.alias_vacio = self._crear_label_vacio(f)

        self._build_action_bar(f,
                               [("↺ Recargar", self._recargar_aliases),
                                ("✕ Eliminar", self._eliminar_alias, C["rojo"])])
        return f

    def _recargar_aliases(self):
        try:
            from aliases import listar_aliases
            data = listar_aliases()
            if not data:
                self._mostrar_vacio(
                    self.alias_list, self.alias_vacio,
                    'Todavía no creaste ningún alias.\nDecí "registra un alias" para empezar.'
                )
                return
            self._ocultar_vacio(self.alias_vacio)
            self.alias_list.delete(0, tk.END)
            for alias, real in sorted(data.items()):
                self.alias_list.insert(tk.END, f"  ⇀  {alias}")
                self.alias_list.itemconfig(tk.END, fg=C["acento_dim"])
                self.alias_list.insert(tk.END, f"       → {real}")
                self.alias_list.itemconfig(tk.END, fg=C["texto_dim"])
                self.alias_list.insert(tk.END, "")
                self.alias_list.itemconfig(tk.END, fg=C["bg"])
        except Exception as e:
            self._ocultar_vacio(self.alias_vacio)
            self.alias_list.delete(0, tk.END)
            self.alias_list.insert(tk.END, f"Error: {e}")

    def _eliminar_alias(self):
        sel = self.alias_list.curselection()
        if not sel:
            return
        txt = self.alias_list.get(sel[0])
        if "⇀" not in txt:
            return
        alias = txt.replace("⇀", "").strip()
        if messagebox.askyesno("Eliminar alias",
                               f"¿Eliminar el alias «{alias}»?",
                               parent=self.root):
            try:
                from aliases import eliminar_alias
                eliminar_alias(alias)
                self._recargar_aliases()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=self.root)

    # ── macros ──────────────────────────────────────────

    def _tab_macros(self, parent):
        f = tk.Frame(parent, bg=C["bg"])

        self.macro_list = tk.Listbox(
            f, bg=C["bg"], fg=C["texto"],
            selectbackground=C["bg2"],
            font=(C["mono"], 9),
            borderwidth=0, highlightthickness=0,
            activestyle="none", relief="flat",
        )
        sb = tk.Scrollbar(f, orient="vertical", command=self.macro_list.yview,
                          bg=C["bg2"], troughcolor=C["bg"], width=6,
                          highlightthickness=0)
        self.macro_list.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=6)
        self.macro_list.pack(fill="both", expand=True, padx=10, pady=6)
        self.macro_vacio = self._crear_label_vacio(f)

        self._build_action_bar(f,
                               [("↺ Recargar", self._recargar_macros),
                                ("✕ Eliminar", self._eliminar_macro, C["rojo"])])
        return f

    def _recargar_macros(self):
        try:
            from macros import listar_macros
            data = listar_macros()
            if not data:
                self._mostrar_vacio(
                    self.macro_list, self.macro_vacio,
                    'Todavía no creaste ninguna macro.\nDecí "crea una macro" para empezar.'
                )
                return
            self._ocultar_vacio(self.macro_vacio)
            self.macro_list.delete(0, tk.END)
            for nombre, pasos in sorted(data.items()):
                self.macro_list.insert(tk.END, f"  ▷  {nombre}")
                self.macro_list.itemconfig(tk.END, fg=C["acento_dim"])
                self.macro_list.insert(tk.END, f"       {len(pasos)} pasos")
                self.macro_list.itemconfig(tk.END, fg=C["texto_dim"])
                self.macro_list.insert(tk.END, "")
                self.macro_list.itemconfig(tk.END, fg=C["bg"])
        except Exception as e:
            self._ocultar_vacio(self.macro_vacio)
            self.macro_list.delete(0, tk.END)
            self.macro_list.insert(tk.END, f"Error: {e}")

    def _eliminar_macro(self):
        sel = self.macro_list.curselection()
        if not sel:
            return
        txt = self.macro_list.get(sel[0])
        if "▷" not in txt:
            return
        nombre = txt.replace("▷", "").strip()
        if messagebox.askyesno("Eliminar macro",
                               f"¿Eliminar la macro «{nombre}»?",
                               parent=self.root):
            try:
                from macros import eliminar_macro
                eliminar_macro(nombre)
                self._recargar_macros()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=self.root)

    # ── recordatorios ───────────────────────────────────

    def _tab_recs(self, parent):
        f = tk.Frame(parent, bg=C["bg"])

        self.rec_list = tk.Listbox(
            f, bg=C["bg"], fg=C["texto"],
            selectbackground=C["bg2"],
            font=(C["mono"], 9),
            borderwidth=0, highlightthickness=0,
            activestyle="none", relief="flat",
        )
        sb = tk.Scrollbar(f, orient="vertical", command=self.rec_list.yview,
                          bg=C["bg2"], troughcolor=C["bg"], width=6,
                          highlightthickness=0)
        self.rec_list.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", pady=6)
        self.rec_list.pack(fill="both", expand=True, padx=10, pady=6)
        self.rec_vacio = self._crear_label_vacio(f)

        self._rec_ids = []

        self._build_action_bar(f,
                               [("↺ Recargar", self._recargar_recs),
                                ("✕ Cancelar", self._cancelar_rec, C["rojo"])])
        return f

    def _recargar_recs(self):
        try:
            from recordatorios import listar_recordatorios_ordenados
            items = listar_recordatorios_ordenados()
            self._rec_ids = []
            if not items:
                self._mostrar_vacio(
                    self.rec_list, self.rec_vacio,
                    'Todavía no tenés recordatorios.\nDecí "recuérdame..." para crear uno.'
                )
                return
            self._ocultar_vacio(self.rec_vacio)
            self.rec_list.delete(0, tk.END)
            for id_str, info in items:
                try:
                    desde = datetime.fromisoformat(info["momento"])
                    cuando = desde.strftime("%d/%m %H:%M")
                except Exception:
                    cuando = "—"
                rec    = info.get("recurrencia")
                texto  = info.get("texto", "")
                sufijo = "  ↻" if rec else ""
                self.rec_list.insert(tk.END, f"  ◷  {texto}{sufijo}")
                self.rec_list.itemconfig(tk.END, fg=C["acento_dim"])
                self.rec_list.insert(tk.END, f"       {cuando}")
                self.rec_list.itemconfig(tk.END, fg=C["texto_dim"])
                self.rec_list.insert(tk.END, "")
                self.rec_list.itemconfig(tk.END, fg=C["bg"])
                self._rec_ids.append(id_str)
        except Exception as e:
            self._ocultar_vacio(self.rec_vacio)
            self.rec_list.delete(0, tk.END)
            self.rec_list.insert(tk.END, f"Error: {e}")
            self._rec_ids = []

    def _cancelar_rec(self):
        sel = self.rec_list.curselection()
        if not sel:
            return
        idx = sel[0]
        txt = self.rec_list.get(idx)
        if "◷" not in txt:
            return
        real_idx = idx // 3
        if real_idx >= len(self._rec_ids):
            return
        id_str = self._rec_ids[real_idx]
        nombre = txt.replace("◷", "").strip().rstrip("↻").strip()
        if messagebox.askyesno("Cancelar recordatorio",
                               f"¿Cancelar «{nombre}»?",
                               parent=self.root):
            try:
                from recordatorios import cancelar_recordatorio
                cancelar_recordatorio(id_str)
                self._recargar_recs()
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=self.root)

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

    # ── action bar (botonera inferior en pestañas) ───────

    def _build_action_bar(self, parent, botones):
        bar = tk.Frame(parent, bg=C["bg2"], pady=4)
        bar.pack(fill="x", side="bottom")
        for item in botones:
            texto  = item[0]
            cmd    = item[1]
            color  = item[2] if len(item) > 2 else C["texto_dim"]
            b = tk.Label(bar, text=texto,
                         font=(C["ui"], 8),
                         fg=color, bg=C["bg2"],
                         padx=10, pady=2, cursor="hand2")
            b.pack(side="left" if botones.index(item) == 0 else "right",
                   padx=4)
            b.bind("<Button-1>", lambda e, c=cmd: c())
            b.bind("<Enter>",    lambda e, btn=b: btn.config(bg=C["bg3"]))
            b.bind("<Leave>",    lambda e, btn=b: btn.config(bg=C["bg2"]))

    # ── polling ─────────────────────────────────────────

    def _polling(self):
        try:
            self._tick_clock()
            self._tick_estado()
            self._tick_orbe()
            if self.expandido:
                self._tick_dot_header()
                self._tick_header_accent()
                if self._tab_active == 0:
                    self._actualizar_historial()

                # NUEVO: los badges de conteo de la sidebar (aliases/
                # macros/recordatorios) se recalculan cada ~20 vueltas
                # de polling (~1.2s con el intervalo de 60ms de abajo)
                # en vez de en cada tick — son datos que cambian poco
                # de un momento a otro, así que no hace falta
                # relistarlos 16 veces por segundo.
                self._sidebar_tick_contador += 1
                if self._sidebar_tick_contador % 20 == 0:
                    self._redibujar_sidebar()
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
                self.cv_dot.itemconfig(self.dot_id, fill=C["borde2"])
            else:
                self._pulse = (self._pulse + 0.12) % (2 * math.pi)
                t = (math.sin(self._pulse) + 1) / 2
                blended = _mezclar_hex(info["dot"], C["bg2"], 0.3 + 0.7 * t)
                self.cv_dot.itemconfig(self.dot_id, fill=blended)
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

        if not self.expandido:
            self._dibujar_orbe(modo, no_molestar)


# =========================================================
# LANZAR
# =========================================================

_root_ui   = None
_ui_activa = False


def iniciar_ui():
    global _ui_activa
    if _ui_activa:
        return

    def _run():
        global _root_ui, _ui_activa
        try:
            root = tk.Tk()
            _root_ui  = root
            _ui_activa = True
            AsistenteUI(root)
            iniciar_bandeja(mostrar_ui, cerrar_definitivo)
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