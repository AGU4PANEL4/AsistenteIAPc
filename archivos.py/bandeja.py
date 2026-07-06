"""
Ícono en la bandeja del sistema de Windows (system tray) — permite
recuperar la ventana o cerrar el asistente de verdad cuando quedó
"en segundo plano" (ventana oculta, pero el proceso sigue vivo).

FIX/NUEVO: antes, el botón x de ui.py solo ocultaba la ventana
(root.withdraw()) y no había NINGUNA forma de volver a mostrarla ni
de cerrar el asistente de verdad sin matar el proceso a mano desde
el Administrador de tareas. Ahora, mientras el asistente está
corriendo, siempre hay un ícono en la bandeja (junto al reloj de
Windows) con dos opciones: "Mostrar" (recupera la ventana) y
"Cerrar" (apaga todo y termina el proceso).

El ícono se genera con PIL en tiempo de ejecución (un círculo simple
con los colores del proyecto) en vez de depender de un archivo .ico
externo — así no hay que empaquetar ni mantener ningún asset extra.
"""

import threading

try:
    import pystray
    from PIL import Image, ImageDraw
    BANDEJA_DISPONIBLE = True
except ImportError:
    BANDEJA_DISPONIBLE = False
    print("[Bandeja] pystray/Pillow no están instalados — no habrá "
          "ícono en la bandeja del sistema. El asistente funciona "
          "igual, pero minimizar solo será recuperable reabriendo "
          "el asistente.")

# =========================================================
# ÍCONO
# Círculo cian sobre fondo oscuro — mismos colores que ui.py
# (C["bg"] / C["acento"]) para que se sienta parte de la misma app.
# =========================================================

C_BG     = (11, 26, 31, 255)
C_ACENTO = (45, 230, 192, 255)


def _generar_icono():
    img  = Image.new("RGBA", (64, 64), C_BG)
    draw = ImageDraw.Draw(img)
    draw.ellipse((14, 14, 50, 50), fill=C_ACENTO)
    return img


_icono       = None
_hilo_icono  = None


def iniciar_bandeja(al_mostrar, al_cerrar):
    """
    Crea y muestra el ícono en la bandeja. `al_mostrar` se llama
    cuando el usuario elige "Mostrar" (o hace doble clic); `al_cerrar`
    cuando elige "Cerrar" — quien llama decide qué significa cada uno
    (ver ui.py: mostrar_ui / cerrar_definitivo).

    Corre en su propio hilo daemon, igual que iniciar_ui() en ui.py
    — pystray tiene su propio loop de eventos (usa la API nativa de
    Windows por debajo) que bloquea igual que root.mainloop().

    Si pystray/Pillow no están disponibles, no hace nada — el
    asistente sigue funcionando sin bandeja, simplemente sin esa
    comodidad extra.
    """
    global _icono, _hilo_icono

    if not BANDEJA_DISPONIBLE:
        return

    if _hilo_icono is not None:
        return  # ya está corriendo, no crear un segundo ícono

    def _accion_mostrar(icon, item):
        al_mostrar()

    def _accion_cerrar(icon, item):
        al_cerrar()

    menu = pystray.Menu(
        pystray.MenuItem("Mostrar", _accion_mostrar, default=True),
        pystray.MenuItem("Cerrar", _accion_cerrar),
    )

    _icono = pystray.Icon("AsistenteIA", _generar_icono(), "AsistenteIA", menu)

    def _run():
        try:
            _icono.run()
        except Exception as e:
            print(f"[Bandeja] Error: {e}")

    _hilo_icono = threading.Thread(target=_run, daemon=True, name="BandejaIcono")
    _hilo_icono.start()


def detener_bandeja():
    """Quita el ícono de la bandeja. Llamar justo antes de cerrar el asistente."""
    if _icono is not None:
        try:
            _icono.stop()
        except Exception:
            pass