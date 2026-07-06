"""
Diálogo de "hay una actualización disponible" mostrado durante el
splash de arranque — en reemplazo del aviso por voz que interrumpía
la conversación normal (ver actualizador.py).

FIX/NUEVO: antes, la verificación de actualizaciones corría en
background durante TODA la sesión y, cuando terminaba de descargar,
avisaba por VOZ en medio de la conversación — justo después de que
el asistente respondiera algo, antes de preguntar "¿Algo más?". Esto
era una interrupción rara y fuera de contexto: el usuario podía estar
pidiendo cualquier cosa (abrir un juego, poner un recordatorio) y de
repente el asistente le preguntaba si quería instalar una actualización,
sin relación con lo que estaba haciendo.

Ahora la verificación se hace ANTES de que la sesión de voz siquiera
empiece, mientras el splash de carga está visible (ver
verificar_actualizacion_arranque() en actualizador.py) — y si hay una
versión nueva, se pregunta con una ventana, mismo patrón ya usado
para Groq (setup_groq_gui.py) y Ollama (setup_ollama_gui.py): un
Toplevel del root compartido del splash, nunca un tk.Tk() propio.
"""

import tkinter as tk

from splash import ejecutar_en_hilo_gui

C_BG        = "#0b1a1f"
C_BORDE     = "#1c3a3f"
C_ACENTO    = "#2de6c0"
C_TEXTO     = "#7fb3ad"
C_TEXTO_DIM = "#3a5a5c"

ANCHO, ALTO = 380, 250


def preguntar_actualizar_gui(tag_nuevo):
    """
    Muestra el diálogo preguntando si se quiere instalar la versión
    `tag_nuevo` ahora mismo, y BLOQUEA (el hilo que llama espera)
    hasta que el usuario elija una opción.

    Devuelve True si eligió "Actualizar ahora", False si eligió
    "Ahora no" o cerró la ventana.
    """
    resultado = ejecutar_en_hilo_gui(lambda root: _mostrar_dialogo(root, tag_nuevo))
    return bool(resultado)


def _mostrar_dialogo(root, tag_nuevo):
    dialogo = tk.Toplevel(root)
    dialogo.overrideredirect(True)
    dialogo.attributes("-topmost", True)
    dialogo.configure(bg=C_BG)
    dialogo.resizable(False, False)

    sw = dialogo.winfo_screenwidth()
    sh = dialogo.winfo_screenheight()
    x = (sw - ANCHO) // 2
    y = (sh - ALTO) // 2
    dialogo.geometry(f"{ANCHO}x{ALTO}+{x}+{y}")

    tk.Frame(dialogo, bg=C_BORDE, height=1).pack(fill="x")

    tk.Label(dialogo, text="Actualización disponible",
             font=("Segoe UI", 12, "bold"),
             fg=C_ACENTO, bg=C_BG).pack(pady=(18, 6))

    tk.Label(
        dialogo,
        text=(f"Hay una versión nueva del asistente: {tag_nuevo}.\n"
              "Se descargará e instalará automáticamente, y el\n"
              "asistente se reiniciará al terminar."),
        font=("Segoe UI", 9), fg=C_TEXTO, bg=C_BG, justify="center",
    ).pack(pady=(0, 18))

    resultado = {"actualizar": False}

    def _actualizar(_e=None):
        resultado["actualizar"] = True
        dialogo.destroy()

    def _ahora_no(_e=None):
        resultado["actualizar"] = False
        dialogo.destroy()

    botones = tk.Frame(dialogo, bg=C_BG)
    botones.pack(pady=(4, 0))

    btn_actualizar = tk.Label(botones, text="Actualizar ahora",
                              font=("Segoe UI", 9, "bold"),
                              fg=C_BG, bg=C_ACENTO, padx=16, pady=6,
                              cursor="hand2")
    btn_actualizar.pack(side="left", padx=6)
    btn_actualizar.bind("<Button-1>", _actualizar)

    btn_ahora_no = tk.Label(botones, text="Ahora no",
                            font=("Segoe UI", 9),
                            fg=C_TEXTO_DIM, bg=C_BG, padx=16, pady=6,
                            cursor="hand2")
    btn_ahora_no.pack(side="left", padx=6)
    btn_ahora_no.bind("<Button-1>", _ahora_no)

    dialogo.protocol("WM_DELETE_WINDOW", _ahora_no)
    dialogo.focus_force()

    # bloquea (dentro del hilo de Tkinter, con un mini-loop anidado —
    # patrón estándar de Tkinter para diálogos modales) hasta que se
    # cierre este Toplevel.
    root.wait_window(dialogo)

    return resultado["actualizar"]