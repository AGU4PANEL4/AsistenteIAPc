"""
Ventana de carga (splash) mostrada mientras el asistente prepara
todo lo necesario para arrancar: cargar módulos, configurar Groq,
preparar/arrancar Ollama, verificar conexión, etc.

FIX/NUEVO: antes, todo ese trabajo corría en la consola — invisible
en el .exe empaquetado (console=False, ver asistente.spec) — y recién
al final se llamaba a iniciar_ui() (ui.py). El usuario abría el .exe
y no veía nada durante varios segundos (más si Ollama tenía que
instalarse o arrancar en frío), sin ninguna señal de que el programa
sí estaba haciendo algo.

Este splash se muestra lo antes posible en main.py (antes incluso de
los imports pesados) con un texto de estado que main.py va
actualizando en cada etapa (ver splash_estado.py), y se cierra solo
cuando la interfaz principal (ui.py) ya está lista para mostrarse.

Mismo patrón que ui.py: la ventana corre en su propio hilo con su
propio mainloop de Tk, y la comunicación entre hilos pasa por un
estado compartido con lock (splash_estado.py) que se lee por
polling — nunca se llama a un método de tkinter desde otro hilo.
"""

import math
import threading
import tkinter as tk

from splash_estado import get_estado, set_estado, pedir_cierre, reset
from visual_utils import dibujar_puntos_spinner

# =========================================================
# PALETA
# Mismos colores que ui.py, para que el splash y la ventana
# principal se sientan como parte de la misma interfaz.
# =========================================================

C_BG        = "#0b1a1f"
C_BORDE     = "#1c3a3f"
C_ACENTO    = "#2de6c0"
C_TEXTO     = "#7fb3ad"

ANCHO = 300
ALTO  = 150


class SplashUI:

    def __init__(self, root):
        self.root   = root
        self._fase  = 0.0
        self._drag_x = self._drag_y = 0

        self._cfg_ventana()
        self._build()
        self._tick()

    def _cfg_ventana(self):
        r = self.root
        r.overrideredirect(True)
        r.attributes("-topmost", True)
        r.configure(bg=C_BG)
        r.resizable(False, False)

        sw = r.winfo_screenwidth()
        sh = r.winfo_screenheight()
        x  = (sw - ANCHO) // 2
        y  = (sh - ALTO) // 2
        r.geometry(f"{ANCHO}x{ALTO}+{x}+{y}")

    def _build(self):
        borde = tk.Frame(self.root, bg=C_BORDE, height=1)
        borde.pack(fill="x", side="top")

        titulo = tk.Label(self.root, text="ASISTENTE IA",
                          font=("Consolas", 12, "bold"),
                          fg=C_ACENTO, bg=C_BG)
        titulo.pack(pady=(26, 8))

        self.cv = tk.Canvas(self.root, width=60, height=60,
                            bg=C_BG, highlightthickness=0)
        self.cv.pack()

        self.lbl_estado = tk.Label(self.root, text="Iniciando...",
                                   font=("Consolas", 9),
                                   fg=C_TEXTO, bg=C_BG)
        self.lbl_estado.pack(pady=(8, 10))

        # NUEVO: arrastrable — se une el mismo par de handlers a la
        # ventana y a cada widget hijo, porque en Tkinter un clic
        # sobre un widget hijo NO propaga el evento al padre por sí
        # solo (haría falta bindear cada uno para poder tomar la
        # ventana desde cualquier punto visible, no solo el fondo).
        for widget in (self.root, borde, titulo, self.cv, self.lbl_estado):
            widget.bind("<ButtonPress-1>", self._drag_press)
            widget.bind("<B1-Motion>",     self._drag_motion)

    def _drag_press(self, e):
        self._drag_x, self._drag_y = e.x, e.y

    def _drag_motion(self, e):
        x = self.root.winfo_x() + (e.x - self._drag_x)
        y = self.root.winfo_y() + (e.y - self._drag_y)
        self.root.geometry(f"+{x}+{y}")

    def _tick(self):
        estado = get_estado()

        if estado["cerrar"]:
            self.root.destroy()
            return

        self.lbl_estado.config(text=estado["texto"])

        # NUEVO: spinner de varios puntos (estilo iOS/Android) en vez
        # de un solo punto orbitando — se borra y redibuja el anillo
        # completo en cada tick, con la fase avanzando para que el
        # brillo dé la vuelta.
        self.cv.delete("anim")
        self._fase = (self._fase + 0.16) % (2 * math.pi)
        dibujar_puntos_spinner(
            self.cv, cx=30, cy=30, radio=20, fase=self._fase,
            color=C_ACENTO, color_fondo=C_BG, n_puntos=10, radio_punto=3,
        )

        self.root.after(60, self._tick)


# =========================================================
# LANZAR
# =========================================================

_hilo_splash = None


def mostrar_splash():
    """
    Lanza el splash en su propio hilo. Llamar UNA vez, lo antes
    posible en main.py — antes de cualquier paso lento del arranque.
    """
    global _hilo_splash

    reset()

    def _run():
        try:
            root = tk.Tk()
            SplashUI(root)
            root.mainloop()
        except Exception as e:
            print(f"[Splash] Error: {e}")

    _hilo_splash = threading.Thread(target=_run, daemon=True, name="SplashUI")
    _hilo_splash.start()


def actualizar_splash(texto):
    """Actualiza el texto de estado mostrado en el splash."""
    set_estado(texto)


def cerrar_splash():
    """
    Pide que se cierre el splash y espera brevemente a que
    desaparezca antes de continuar — así no queda flotando encima
    de la interfaz principal ni un instante de más.
    """
    if _hilo_splash is None:
        return
    pedir_cierre()
    _hilo_splash.join(timeout=2)