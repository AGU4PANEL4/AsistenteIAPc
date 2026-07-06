"""
Configuración de la API key de Groq al primer arranque — versión
con interfaz gráfica, en reemplazo del flujo por consola de
setup_groq.py.

FIX/NUEVO: setup_groq.py pedía la key con input() de consola. Eso
funciona perfecto corriendo "python main.py" directo desde una
terminal, pero el .exe empaquetado corre con console=False (ver
asistente.spec) — sin consola, sys.stdin es None, y ese input()
lanzaba una excepción que tumbaba el arranque completo antes de
mostrar nada (el "primer error" reportado al probar el .exe sin
config.json previo). Esta versión pide lo mismo con una ventanita
de Tkinter (mismo tema "aurora fría" del resto de la interfaz), que
sí funciona sin consola.

Se muestra SOLO si no hay ninguna key ya configurada (variable de
entorno o config.json) — si ya existe, no hace nada y retorna de
inmediato, igual que la versión de consola.
"""

import os
import threading
import tkinter as tk
import webbrowser

from config import cargar_config, guardar_groq_api_key
from splash import ejecutar_en_hilo_gui

URL_GROQ_KEYS = "https://console.groq.com/keys"

C_BG        = "#0b1a1f"
C_BG2       = "#10262c"
C_BORDE     = "#1c3a3f"
C_ACENTO    = "#2de6c0"
C_TEXTO     = "#7fb3ad"
C_TEXTO_DIM = "#3a5a5c"
C_ROJO      = "#ff5566"

ANCHO, ALTO = 380, 300


def asegurar_groq_configurado_gui():
    """
    Llamar UNA vez al arrancar, antes de preparar_ia(). Si ya hay
    una key configurada, no hace nada. Si no, muestra un diálogo y
    BLOQUEA (el hilo que llama a esto espera) hasta que el usuario
    la guarde o elija omitir el paso — mismo comportamiento
    bloqueante que tenía el input() de consola original, para que
    main.py no necesite cambiar su orden de arranque.

    FIX/NUEVO: el diálogo ahora se muestra como tk.Toplevel del root
    compartido del splash (ver splash.ejecutar_en_hilo_gui), en vez
    de crear su propio tk.Tk() en un hilo aparte — evita tener dos
    roots de Tkinter corriendo en hilos distintos al mismo tiempo.
    """
    config     = cargar_config()
    key_actual = os.environ.get("GROQ_API_KEY") or config.get("groq_api_key", "")

    if key_actual:
        return

    ejecutar_en_hilo_gui(_mostrar_dialogo)


def _mostrar_dialogo(root):
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

    tk.Label(dialogo, text="Configurar Groq (opcional)",
             font=("Segoe UI", 12, "bold"),
             fg=C_ACENTO, bg=C_BG).pack(pady=(18, 6))

    tk.Label(
        dialogo,
        text=("Groq hace que el asistente responda más rápido, sin\n"
              "usar tu GPU, cuando hay internet. Es gratis. Podés\n"
              "omitir este paso y usar solo el modelo local."),
        font=("Segoe UI", 9), fg=C_TEXTO, bg=C_BG, justify="center",
    ).pack(pady=(0, 14))

    btn_abrir = tk.Label(dialogo, text="Abrir página para crear una key gratis",
                        font=("Segoe UI", 9, "underline"),
                        fg=C_ACENTO, bg=C_BG, cursor="hand2")
    btn_abrir.pack(pady=(0, 10))
    btn_abrir.bind("<Button-1>", lambda e: webbrowser.open(URL_GROQ_KEYS))

    entry = tk.Entry(dialogo, font=("Consolas", 10), width=36,
                     bg=C_BG2, fg=C_TEXTO, insertbackground=C_TEXTO,
                     relief="flat")
    entry.pack(ipady=6, pady=(0, 8))
    entry.focus_set()

    lbl_estado = tk.Label(dialogo, text="", font=("Segoe UI", 8),
                          fg=C_TEXTO_DIM, bg=C_BG, wraplength=ANCHO - 40)
    lbl_estado.pack(pady=(0, 10))

    botones = tk.Frame(dialogo, bg=C_BG)
    botones.pack(pady=(4, 0))

    _validando = {"activo": False}

    def _guardar(_e=None):
        if _validando["activo"]:
            return

        key = entry.get().strip()
        if not key:
            lbl_estado.config(text="Pegá una key primero, o usá \"Omitir\".",
                              fg=C_ROJO)
            return

        _validando["activo"] = True
        btn_guardar.config(text="Validando...", bg=C_TEXTO_DIM)
        lbl_estado.config(text="Verificando la key con Groq...", fg=C_TEXTO_DIM)

        def _validar_en_hilo():
            os.environ["GROQ_API_KEY"] = key

            try:
                from groq_cliente import resetear_cliente, llamar_groq
                resetear_cliente()
                respuesta = llamar_groq(
                    "Responde únicamente con la palabra: ok",
                    timeout=10, num_predict=5,
                )
            except Exception:
                respuesta = None

            def _terminar():
                _validando["activo"] = False
                if respuesta:
                    guardar_groq_api_key(key)
                    dialogo.destroy()
                else:
                    os.environ.pop("GROQ_API_KEY", None)
                    btn_guardar.config(text="Guardar", bg=C_ACENTO)
                    lbl_estado.config(
                        text="No funcionó — revisá que esté bien copiada, "
                             "sin espacios de más.",
                        fg=C_ROJO,
                    )

            dialogo.after(0, _terminar)

        threading.Thread(target=_validar_en_hilo, daemon=True).start()

    def _omitir(_e=None):
        dialogo.destroy()

    btn_guardar = tk.Label(botones, text="Guardar", font=("Segoe UI", 9, "bold"),
                          fg=C_BG, bg=C_ACENTO, padx=16, pady=6, cursor="hand2")
    btn_guardar.pack(side="left", padx=6)
    btn_guardar.bind("<Button-1>", _guardar)

    btn_omitir = tk.Label(botones, text="Omitir por ahora", font=("Segoe UI", 9),
                         fg=C_TEXTO_DIM, bg=C_BG, padx=16, pady=6, cursor="hand2")
    btn_omitir.pack(side="left", padx=6)
    btn_omitir.bind("<Button-1>", _omitir)

    entry.bind("<Return>", _guardar)
    dialogo.protocol("WM_DELETE_WINDOW", _omitir)
    dialogo.focus_force()

    # bloquea (dentro del hilo de Tkinter, con un mini-loop anidado —
    # patrón estándar de Tkinter para diálogos modales) hasta que se
    # cierre este Toplevel — es lo que permite que
    # ejecutar_en_hilo_gui() en splash.py "espere" a este diálogo sin
    # necesitar su propio hilo ni su propio root.
    root.wait_window(dialogo)