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
propio mainloop de Tk. La comunicación normal entre hilos (el texto
de estado) pasa por un estado compartido con lock (splash_estado.py)
que se lee por polling.

FIX/NUEVO: además, este módulo expone ejecutar_en_hilo_gui() para que
OTROS diálogos de arranque (setup_groq_gui.py, setup_ollama_gui.py)
puedan mostrarse como tk.Toplevel de ESTE MISMO root, en vez de crear
cada uno su propio tk.Tk() en su propio hilo — evita tener varios
roots de Tkinter corriendo en hilos distintos al mismo tiempo (algo
que Tcl/Tk no soporta de forma confiable). Para lograrlo, se agenda
trabajo en el hilo del root con root.after(...) llamado desde otro
hilo — el mismo patrón (no "oficialmente" garantizado por la
documentación de Tk, pero ampliamente usado en la práctica, y ya
usado en este mismo proyecto en setup_groq_gui.py) que actualizar
widgets desde un hilo de validación en background.
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
_root        = None
_root_listo  = threading.Event()


def mostrar_splash():
    """
    Lanza el splash en su propio hilo. Llamar UNA vez, lo antes
    posible en main.py — antes de cualquier paso lento del arranque.
    """
    global _hilo_splash, _root

    reset()
    _root_listo.clear()

    def _run():
        global _root
        try:
            root  = tk.Tk()
            _root = root
            _root_listo.set()
            SplashUI(root)
            root.mainloop()
        except Exception as e:
            print(f"[Splash] Error: {e}")
        finally:
            # FIX/NUEVO: se limpia la referencia acá, DESPUÉS de que
            # mainloop() ya retornó (es decir, después de que el root
            # ya fue destruido) — así obtener_root()/ejecutar_en_hilo_gui
            # nunca devuelven un root muerto a otro hilo que intente
            # usarlo justo mientras el splash está cerrando.
            _root = None

    _hilo_splash = threading.Thread(target=_run, daemon=True, name="SplashUI")
    _hilo_splash.start()

    # esperar a que el root exista de verdad antes de devolver el
    # control — así una llamada inmediata a ejecutar_en_hilo_gui()
    # (ej. asegurar_groq_configurado_gui() en main.py) nunca se
    # adelanta a la creación del root.
    _root_listo.wait(timeout=5)


def obtener_root():
    """
    Devuelve el root de Tkinter del hilo de arranque (el mismo hilo
    que muestra el splash), o None si el splash no está corriendo.

    FIX/NUEVO: antes, cada diálogo de arranque (setup_groq_gui.py,
    setup_ollama_gui.py) creaba su PROPIO tk.Tk() en su PROPIO hilo,
    mientras el splash seguía vivo con su propio root en otro hilo
    distinto — Tcl/Tk no está pensado para correr varios roots en
    hilos diferentes al mismo tiempo. En la práctica "funciona" casi
    siempre en Windows, pero es exactamente el tipo de cosa que
    puede producir un crash raro y difícil de reproducir bajo ciertas
    condiciones (temporización, versión de Tcl/Tk, etc). Ahora todos
    los diálogos de arranque comparten este ÚNICO root y su ÚNICO
    hilo de Tkinter — ver ejecutar_en_hilo_gui() más abajo.
    """
    return _root


def ejecutar_en_hilo_gui(funcion, timeout=90):
    """
    Ejecuta `funcion(root)` EN EL HILO DE TKINTER del splash (nunca
    en el hilo que llama a esta función) y bloquea al hilo que llama
    hasta que `funcion` termine, devolviendo lo que haya devuelto.

    Pensado para que setup_groq_gui.py y setup_ollama_gui.py muestren
    sus diálogos como tk.Toplevel(root) de este mismo root en vez de
    crear un tk.Tk() nuevo en un hilo aparte. El patrón esperado
    dentro de `funcion` es:

        def _mostrar_dialogo(root):
            dialogo = tk.Toplevel(root)
            ...armar widgets...
            root.wait_window(dialogo)  # bloquea (dentro del hilo de
                                        # Tkinter, con un mini-loop
                                        # anidado — patrón estándar y
                                        # seguro de Tkinter) hasta que
                                        # el usuario cierre `dialogo`
            return resultado

    Si el splash no está corriendo (ej. se llama fuera del flujo
    normal de arranque en main.py), se crea un root propio y aislado
    como respaldo — mismo comportamiento que tenían estos diálogos
    antes de este cambio, solo que ya no es el camino normal.
    """
    root = obtener_root()

    if root is None:
        root_temporal = tk.Tk()
        root_temporal.withdraw()
        try:
            return funcion(root_temporal)
        finally:
            try:
                root_temporal.destroy()
            except Exception:
                pass

    resultado = {}
    evento    = threading.Event()

    def _envoltura():
        try:
            resultado["valor"] = funcion(root)
        except Exception as e:
            print(f"[GUI] Error ejecutando diálogo: {e}")
            resultado["valor"] = None
        finally:
            evento.set()

    # se agenda con after(0, ...) en vez de llamar directo, porque
    # este código corre en el hilo que llamó a ejecutar_en_hilo_gui
    # (ej. el hilo principal de main.py) — cualquier operación de
    # Tkinter debe ejecutarse en el hilo dueño del root, nunca desde
    # otro hilo directamente.
    root.after(0, _envoltura)
    evento.wait(timeout)

    return resultado.get("valor")


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