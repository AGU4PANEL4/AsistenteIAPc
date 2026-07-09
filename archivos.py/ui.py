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
    "mono":       "Consolas",
    "ui":         "Segoe UI",
}

# color que se vuelve transparente en la ventana del orbe — no debe
# coincidir con NINGÚN otro color usado en la interfaz
TRANSPARENTE = "#ab29fe"

ANCHO       = 300
ALTO        = 440
SIDEBAR_W   = 34

ORBE_CANVAS = 96
ORBE_CENTRO = 48
ORBE_RADIO  = 24

MARGEN_DERECHO   = 16
MARGEN_SUPERIOR  = 40


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
        # mismos tonos apagados que "inactivo" (texto_dim/borde2), a
        # propósito: visualmente debe sentirse tan "en reposo" como
        # inactivo, solo que el texto aclara que hace falta la palabra
        # de despertar en vez de la wake word normal.
        "dormido":    {"txt": 'Durmiendo — di "despierta"', "color": C["texto_dim"], "dot": C["borde2"]},
    }

    def __init__(self, root):
        self.root       = root
        self.expandido  = False
        self._orb_fase  = 0.0
        self._pulse     = 0.0
        self._drag_x    = self._drag_y = 0
        self._movido    = False

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
            # La forma es una luna creciente simple: un círculo con
            # otro círculo del color de fondo superpuesto encima,
            # desplazado — la misma técnica que ya usa self.orb_circulo
            # (pintar con C["bg2"] para "recortar" contra la base).
            fase_lenta  = self._orb_fase * 0.12
            respiracion = (math.sin(fase_lenta) + 1) / 2  # 0..1 suave
            radio_luna  = 9 + 2 * respiracion
            tono        = _mezclar_hex(color, C["bg2"], 0.45 + 0.55 * respiracion)

            cx, cy = ORBE_CENTRO, ORBE_CENTRO
            cv.create_oval(
                cx - radio_luna, cy - radio_luna,
                cx + radio_luna, cy + radio_luna,
                fill=tono, outline="", tags="anim",
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
        # Un círculo con una línea diagonal (símbolo universal de
        # "silenciado"), quieto — a propósito sin animación, para no
        # competir visualmente con la animación del modo actual, y
        # en rojo (C["rojo"]) para que se note incluso a simple
        # vistazo, en una esquina del orbe.
        # =====================================================

        if no_molestar_activo:
            bx, by, br = ORBE_CENTRO + ORBE_RADIO - 6, ORBE_CENTRO - ORBE_RADIO + 6, 7
            cv.create_oval(
                bx - br, by - br, bx + br, by + br,
                fill=C["bg"], outline=C["rojo"], width=2, tags="anim",
            )
            d = br * 0.7
            cv.create_line(
                bx - d, by - d, bx + d, by + d,
                fill=C["rojo"], width=2, tags="anim",
            )

    # ── panel expandido ───────────────────────────────────

    def _build_panel(self):
        self.panel_frame = tk.Frame(self.root, bg=C["bg"])
        self._build_header(self.panel_frame)
        self._build_statusbar(self.panel_frame)
        self._build_body(self.panel_frame)
        self._build_footer(self.panel_frame)

    def _expandir(self):
        self._anchor_desde_geometria()
        self.orb_canvas.pack_forget()
        x = self._anchor_x_right - ANCHO
        y = self._anchor_y_top
        self.root.geometry(f"{ANCHO}x{ALTO}+{x}+{y}")
        self.panel_frame.pack(fill="both", expand=True)
        self.expandido = True

    def _colapsar(self, inicial=False):
        if not inicial:
            self._anchor_desde_geometria()
        self.panel_frame.pack_forget()
        x = self._anchor_x_right - ORBE_CANVAS
        y = self._anchor_y_top
        self.root.geometry(f"{ORBE_CANVAS}x{ORBE_CANVAS}+{x}+{y}")
        self.orb_canvas.pack(fill="both", expand=True)
        self.expandido = False

    # ── header ──────────────────────────────────────────

    def _build_header(self, parent):
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

    def _build_sidebar(self, parent):
        self._tab_names  = ["Historial", "Aliases", "Macros", "Recordatorios"]
        self._tab_iconos = ["≡", "⇄", "▤", "◷"]
        self._tab_active = 0
        self._tab_btns   = []

        bar = tk.Frame(parent, bg=C["bg3"], width=SIDEBAR_W)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)

        for i, icono in enumerate(self._tab_iconos):
            b = tk.Label(bar, text=icono, font=(C["ui"], 13),
                         fg=C["texto_dim"], bg=C["bg3"],
                         cursor="hand2", pady=10)
            b.pack(side="top", fill="x")
            b.bind("<Button-1>", lambda e, idx=i: self._switch_tab(idx))
            b.bind("<Enter>", lambda e, btn=b, idx=i: (
                btn.config(fg=C["texto"]) if idx != self._tab_active else None
            ))
            b.bind("<Leave>", lambda e, btn=b, idx=i: (
                btn.config(fg=C["texto_dim"]) if idx != self._tab_active else None
            ))
            self._tab_btns.append(b)

        self._switch_tab(0)

    def _switch_tab(self, idx):
        self._tab_active = idx
        for i, b in enumerate(self._tab_btns):
            if i == idx:
                b.config(fg=C["acento"], bg=C["bg"])
            else:
                b.config(fg=C["texto_dim"], bg=C["bg3"])

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
        return f

    def _actualizar_historial(self):
        try:
            from ui_estado import get_historial
            items = get_historial()
            self.hist_list.delete(0, tk.END)
            if not items:
                self.hist_list.insert(tk.END, "  (sin comandos aún)")
                self.hist_list.itemconfig(tk.END, fg=C["borde2"])
                return
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

        self._build_action_bar(f,
                               [("↺ Recargar", self._recargar_aliases),
                                ("✕ Eliminar", self._eliminar_alias, C["rojo"])])
        return f

    def _recargar_aliases(self):
        try:
            from aliases import listar_aliases
            data = listar_aliases()
            self.alias_list.delete(0, tk.END)
            for alias, real in sorted(data.items()):
                self.alias_list.insert(tk.END, f"  ⇀  {alias}")
                self.alias_list.itemconfig(tk.END, fg=C["acento_dim"])
                self.alias_list.insert(tk.END, f"       → {real}")
                self.alias_list.itemconfig(tk.END, fg=C["texto_dim"])
                self.alias_list.insert(tk.END, "")
                self.alias_list.itemconfig(tk.END, fg=C["bg"])
        except Exception as e:
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

        self._build_action_bar(f,
                               [("↺ Recargar", self._recargar_macros),
                                ("✕ Eliminar", self._eliminar_macro, C["rojo"])])
        return f

    def _recargar_macros(self):
        try:
            from macros import listar_macros
            data = listar_macros()
            self.macro_list.delete(0, tk.END)
            if not data:
                self.macro_list.insert(tk.END, "  (sin macros guardadas)")
                self.macro_list.itemconfig(tk.END, fg=C["borde2"])
                return
            for nombre, pasos in sorted(data.items()):
                self.macro_list.insert(tk.END, f"  ▷  {nombre}")
                self.macro_list.itemconfig(tk.END, fg=C["acento_dim"])
                self.macro_list.insert(tk.END, f"       {len(pasos)} pasos")
                self.macro_list.itemconfig(tk.END, fg=C["texto_dim"])
                self.macro_list.insert(tk.END, "")
                self.macro_list.itemconfig(tk.END, fg=C["bg"])
        except Exception as e:
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

        self._rec_ids = []

        self._build_action_bar(f,
                               [("↺ Recargar", self._recargar_recs),
                                ("✕ Cancelar", self._cancelar_rec, C["rojo"])])
        return f

    def _recargar_recs(self):
        try:
            from recordatorios import listar_recordatorios_ordenados
            items = listar_recordatorios_ordenados()
            self.rec_list.delete(0, tk.END)
            self._rec_ids = []
            if not items:
                self.rec_list.insert(tk.END, "  (sin recordatorios)")
                self.rec_list.itemconfig(tk.END, fg=C["borde2"])
                return
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
                if self._tab_active == 0:
                    self._actualizar_historial()
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