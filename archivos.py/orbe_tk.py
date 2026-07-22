"""
Orbe circular flotante, en Tkinter — carita limpia.
Modo dormido: carita durmiendo (ojos cerrados + boca respirando + Z flotantes).
SIN animaciones geométricas duplicadas del halo de luna anterior.
"""

import math
import random
import threading
import tkinter as tk

from plataforma import es_windows

if not es_windows():
    import forma_ventana_linux

from visual_utils import mezclar_hex as _mezclar_hex

# ── paleta ──
C = {
    "bg":         "#0b1a1f",
    "bg2":        "#10262c",
    "borde":      "#1c3a3f",
    "borde2":     "#162c31",
    "acento":     "#2de6c0",
    "texto":      "#7fb3ad",
    "texto_dim":  "#3a5a5c",
    "rojo":       "#ff5566",
    "verde":      "#2de6c0",
    "amarillo":   "#e6c02d",
    "dormido":    "#8b9ae8",
}

ESTADOS = {
    "inactivo":   {"dot": C["borde2"]},
    "escuchando": {"dot": C["acento"]},
    "procesando": {"dot": C["amarillo"]},
    "hablando":   {"dot": C["verde"]},
    "buscando":   {"dot": C["amarillo"]},
    "dormido":    {"dot": C["dormido"]},
}

TRANSPARENTE     = "#ab29fe"
ORBE_CANVAS      = 96
ORBE_CENTRO      = 48
ORBE_RADIO       = 24
MARGEN_DERECHO   = 16
MARGEN_SUPERIOR  = 40


class OrbeFlotante:
    def __init__(self, on_expandir):
        self._on_expandir = on_expandir
        self.root = None
        self._listo = threading.Event()
        self._hilo = threading.Thread(target=self._correr, daemon=True)
        self._hilo.start()
        self._listo.wait(timeout=5)

    def _correr(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        if es_windows():
            self.root.configure(bg=TRANSPARENTE)
            try:
                self.root.wm_attributes("-transparentcolor", TRANSPARENTE)
            except tk.TclError:
                self.root.configure(bg=C["bg"])
        else:
            self.root.configure(bg=C["bg"])

        sw = self.root.winfo_screenwidth()
        x = sw - MARGEN_DERECHO - ORBE_CANVAS
        y = MARGEN_SUPERIOR
        self.root.geometry(f"{ORBE_CANVAS}x{ORBE_CANVAS}+{x}+{y}")

        self._orb_fase       = 0.0
        self._drag_x = self._drag_y = 0
        self._movido          = False
        self._parpadeo_cuenta = random.randint(30, 90)
        self._ojos_cerrados   = False
        self._z_fase          = 0.0
        self._pos = (x, y)

        self._build_orbe()
        if not es_windows():
            self.root.update_idletasks()
            try:
                forma_ventana_linux.aplicar_mascara_circular(
                    self.root, ORBE_CANVAS, ORBE_CANVAS,
                    ORBE_CENTRO, ORBE_CENTRO, ORBE_RADIO,
                )
            except Exception:
                pass

        self._tick()
        self._listo.set()
        self.root.mainloop()

    def _build_orbe(self):
        bg_canvas = TRANSPARENTE if es_windows() else C["bg"]
        self.orb_canvas = tk.Canvas(
            self.root, width=ORBE_CANVAS, height=ORBE_CANVAS,
            bg=bg_canvas, highlightthickness=0,
        )
        self.orb_canvas.pack()
        self.orb_circulo = self.orb_canvas.create_oval(
            ORBE_CENTRO - ORBE_RADIO, ORBE_CENTRO - ORBE_RADIO,
            ORBE_CENTRO + ORBE_RADIO, ORBE_CENTRO + ORBE_RADIO,
            fill=C["bg2"], outline=C["borde"], width=2,
        )
        self.orb_canvas.bind("<ButtonPress-1>", self._drag_press)
        self.orb_canvas.bind("<B1-Motion>", self._drag_motion)
        self.orb_canvas.bind("<ButtonRelease-1>", self._release)

    def _drag_press(self, e):
        self._drag_x, self._drag_y = e.x, e.y
        self._movido = False

    def _drag_motion(self, e):
        dx, dy = e.x - self._drag_x, e.y - self._drag_y
        if abs(dx) > 3 or abs(dy) > 3:
            self._movido = True
        x = self.root.winfo_x() + dx
        y = self.root.winfo_y() + dy
        self.root.geometry(f"+{x}+{y}")
        self._pos = (x, y)

    def _release(self, e):
        if not self._movido:
            try:
                self._on_expandir()
            except Exception:
                pass

    # ── carita del orbe ───────────────────────────────────
    def _dibujar_cara(self, cv, modo):
        cx, cy = ORBE_CENTRO, ORBE_CENTRO
        color = ESTADOS.get(modo, ESTADOS["inactivo"])["dot"]

        if modo == "dormido":
            # === MODO DORMIDO: carita durmiendo ===
            tono_dormido = _mezclar_hex(color, C["bg2"], 0.5)

            # Ojos cerrados (líneas suaves, siempre cerrados)
            sep_ojos, y_ojos = 9, cy - 3
            for dx in (-sep_ojos, sep_ojos):
                cv.create_line(cx + dx - 3, y_ojos, cx + dx + 3, y_ojos,
                               fill=tono_dormido, width=2, capstyle="round", tags="anim")

            # Boca: "o" pequeña que respira suavemente
            resp = (math.sin(self._orb_fase * 0.5) + 1) / 2
            r_boca = 1.5 + resp * 1.5
            cv.create_oval(cx - r_boca, cy + 7 - r_boca, cx + r_boca, cy + 7 + r_boca,
                           fill=tono_dormido, outline="", tags="anim")

            # "Z" flotantes animadas
            self._dibujar_z_durmiendo(cv, cx, cy, color)

        else:
            # === MODOS NORMALES: ojos que parpadean + boca según estado ===
            tono = color if modo != "inactivo" else _mezclar_hex(color, C["bg2"], 0.5)

            sep_ojos, y_ojos = 9, cy - 3
            if self._ojos_cerrados:
                for dx in (-sep_ojos, sep_ojos):
                    cv.create_line(cx + dx - 3, y_ojos, cx + dx + 3, y_ojos,
                                   fill=tono, width=2, capstyle="round", tags="anim")
            else:
                for dx in (-sep_ojos, sep_ojos):
                    cv.create_oval(cx + dx - 2, y_ojos - 3, cx + dx + 2, y_ojos + 3,
                                   fill=tono, outline="", tags="anim")

            y_boca = cy + 7
            if modo == "hablando":
                cv.create_arc(cx - 6, y_boca - 4, cx + 6, y_boca + 4,
                              start=200, extent=140, style="arc",
                              outline=tono, width=2, tags="anim")
            elif modo == "escuchando":
                cv.create_oval(cx - 3, y_boca - 3, cx + 3, y_boca + 3,
                               fill=tono, outline="", tags="anim")
            else:
                cv.create_line(cx - 4, y_boca, cx + 4, y_boca,
                               fill=tono, width=2, capstyle="round", tags="anim")

    # NUEVO: "Z" flotantes para modo dormido
    def _dibujar_z_durmiendo(self, cv, cx, cy, color):
        tono_z = _mezclar_hex(color, C["bg2"], 0.5)
        for i, offset in enumerate([0, math.pi]):
            fase = (self._z_fase + offset) % (2 * math.pi)
            progreso = (math.sin(fase) + 1) / 2  # 0..1
            y = cy - 18 - progreso * 18
            alpha = 1.0 - progreso * 0.8
            tono = _mezclar_hex(color, C["bg2"], 1 - alpha)
            x = cx + 16 + math.sin(fase * 1.3) * 5
            tam = 8 + progreso * 4
            cv.create_text(x, y, text="z", font=("Segoe UI", int(tam), "bold"),
                           fill=tono, anchor="center", tags="anim")

    # ── dibujo principal ──────────────────────────────────
    def _dibujar_orbe(self, modo, no_molestar_activo=False):
        cv = self.orb_canvas
        color = ESTADOS.get(modo, ESTADOS["inactivo"])["dot"]

        cv.delete("anim")

        # Contorno del círculo cambia de color según el modo
        cv.itemconfig(self.orb_circulo,
                      outline=color if modo != "inactivo" else C["borde"])

        # Carita (único elemento visual del estado)
        self._dibujar_cara(cv, modo)

        # Indicador de no molestar
        if no_molestar_activo:
            bx, by, br = ORBE_CENTRO + ORBE_RADIO - 7, ORBE_CENTRO - ORBE_RADIO + 7, 8
            cv.create_oval(bx - br, by - br, bx + br, by + br,
                           fill=C["rojo"], outline=C["bg"], width=2, tags="anim")
            mitad = br * 0.55
            cv.create_line(bx - mitad, by, bx + mitad, by,
                           fill=C["bg"], width=3, capstyle="round", tags="anim")

    # ── loop propio ───────────────────────────────────────
    def _tick(self):
        try:
            from ui_estado import get_estado
            estado = get_estado()
            modo = estado.get("modo", "inactivo")
            no_molestar = bool(estado.get("no_molestar", False))
        except Exception:
            modo, no_molestar = "inactivo", False

        self._orb_fase = (self._orb_fase + 0.18) % (2 * math.pi)
        self._z_fase = (self._z_fase + 0.03) % (2 * math.pi)

        if modo != "dormido":
            self._parpadeo_cuenta -= 1
            if self._parpadeo_cuenta <= -3:
                self._ojos_cerrados = False
                self._parpadeo_cuenta = random.randint(30, 90)
            elif self._parpadeo_cuenta <= 0:
                self._ojos_cerrados = True
        else:
            self._ojos_cerrados = True

        self._dibujar_orbe(modo, no_molestar)
        self._pos = (self.root.winfo_x(), self.root.winfo_y())
        self.root.after(60, self._tick)

    @property
    def posicion(self):
        return self._pos

    def mostrar(self):
        if self.root is not None:
            self.root.after(0, self.root.deiconify)

    def ocultar(self):
        if self.root is not None:
            self.root.after(0, self.root.withdraw)

    def mover_a(self, x, y):
        """Mueve el orbe a coordenadas absolutas de pantalla."""
        if self.root is not None:
            self.root.geometry(f"+{int(x)}+{int(y)}")
            self._pos = (int(x), int(y))