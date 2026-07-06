"""
Confirmación de instalación de Ollama al primer arranque — versión
con interfaz gráfica, en reemplazo del input() de consola que tenía
verificacion.py (instalar_ollama()).

FIX/NUEVO: instalar_ollama() descargaba el instalador, lo ejecutaba
con subprocess.Popen(...), y luego llamaba a input() para bloquear
hasta que el usuario terminara de instalarlo manualmente y presionara
Enter. Eso funciona perfecto corriendo "python main.py" desde una
terminal, pero el .exe empaquetado corre con console=False (ver
asistente.spec) — sin consola, sys.stdin es None, y ese input()
lanzaba una excepción que tumbaba el arranque completo apenas
Windows necesitaba instalar Ollama por primera vez (exactamente el
mismo problema que ya se resolvió para la key de Groq, ver
setup_groq_gui.py — esta es la misma solución aplicada acá).

FIX/NUEVO (segunda vuelta): la primera versión de este archivo creaba
su PROPIO tk.Tk() en su PROPIO hilo, igual que setup_groq_gui.py —
pero eso significaba que, durante el arranque, podían llegar a existir
DOS (o tres, contando el splash) roots de Tkinter corriendo en hilos
distintos AL MISMO TIEMPO. Tcl/Tk no está pensado para eso: aunque en
la práctica "funciona" casi siempre en Windows, es el tipo de cosa
que puede producir un crash raro y difícil de reproducir. Ahora este
diálogo se muestra como un tk.Toplevel del ÚNICO root compartido que
ya mantiene vivo el splash (ver splash.ejecutar_en_hilo_gui) — nunca
se crea un tk.Tk() nuevo acá.

El instalador real de Ollama sigue abriéndose normalmente en su
propia ventana externa (ver instalar_ollama() en verificacion.py);
esta ventana solo reemplaza la espera bloqueante de la consola.
"""

import tkinter as tk

from splash import ejecutar_en_hilo_gui

C_BG        = "#0b1a1f"
C_BORDE     = "#1c3a3f"
C_ACENTO    = "#2de6c0"
C_TEXTO     = "#7fb3ad"
C_TEXTO_DIM = "#3a5a5c"
C_ROJO      = "#ff5566"

ANCHO, ALTO = 380, 270


def esperar_confirmacion_instalacion_gui():
    """
    Muestra el diálogo de confirmación y BLOQUEA (el hilo que llama
    espera) hasta que el usuario haga clic en "Continuar" o en
    "Cancelar" — mismo comportamiento bloqueante que tenía el
    input() de consola original, para que verificacion.py no
    necesite cambiar su flujo de arranque.

    Devuelve True si el usuario confirmó que ya instaló Ollama
    (y se verificó que de verdad está instalado), o False si
    canceló / cerró la ventana.
    """
    resultado = ejecutar_en_hilo_gui(_mostrar_dialogo)
    return bool(resultado)


def _mostrar_dialogo(root):
    from verificacion import ollama_instalado

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

    tk.Label(dialogo, text="Instalando Ollama",
             font=("Segoe UI", 12, "bold"),
             fg=C_ACENTO, bg=C_BG).pack(pady=(18, 6))

    tk.Label(
        dialogo,
        text=("Se abrió el instalador de Ollama en otra ventana.\n"
              "Completalo con las opciones por defecto y, cuando\n"
              "termine, volvé acá y hacé clic en \"Continuar\"."),
        font=("Segoe UI", 9), fg=C_TEXTO, bg=C_BG, justify="center",
    ).pack(pady=(0, 14))

    lbl_estado = tk.Label(dialogo, text="", font=("Segoe UI", 8),
                          fg=C_ROJO, bg=C_BG, wraplength=ANCHO - 40)
    lbl_estado.pack(pady=(0, 8))

    botones = tk.Frame(dialogo, bg=C_BG)
    botones.pack(pady=(4, 0))

    resultado = {"continuar": False}

    def _continuar(_e=None):
        # FIX/NUEVO: se verifica de verdad que Ollama quedó instalado
        # antes de dejar avanzar — si el usuario hace clic en
        # "Continuar" por error (o antes de que el instalador termine
        # de verdad), sin esto el arranque seguiría igual y fallaría
        # más adelante de forma más confusa (en preparar_ia(), al
        # intentar iniciar un Ollama que no existe).
        if not ollama_instalado():
            lbl_estado.config(
                text="Todavía no detecto Ollama instalado — "
                     "asegurate de terminar el instalador primero."
            )
            return
        resultado["continuar"] = True
        dialogo.destroy()

    def _cancelar(_e=None):
        resultado["continuar"] = False
        dialogo.destroy()

    btn_continuar = tk.Label(botones, text="Continuar",
                             font=("Segoe UI", 9, "bold"),
                             fg=C_BG, bg=C_ACENTO, padx=16, pady=6,
                             cursor="hand2")
    btn_continuar.pack(side="left", padx=6)
    btn_continuar.bind("<Button-1>", _continuar)

    btn_cancelar = tk.Label(botones, text="Cancelar",
                            font=("Segoe UI", 9),
                            fg=C_TEXTO_DIM, bg=C_BG, padx=16, pady=6,
                            cursor="hand2")
    btn_cancelar.pack(side="left", padx=6)
    btn_cancelar.bind("<Button-1>", _cancelar)

    dialogo.protocol("WM_DELETE_WINDOW", _cancelar)
    dialogo.focus_force()

    # bloquea (dentro del hilo de Tkinter, con un mini-loop anidado —
    # patrón estándar de Tkinter para diálogos modales) hasta que se
    # cierre este Toplevel — es lo que permite que
    # ejecutar_en_hilo_gui() en splash.py "espere" a este diálogo sin
    # necesitar su propio hilo ni su propio root.
    root.wait_window(dialogo)

    return resultado["continuar"]