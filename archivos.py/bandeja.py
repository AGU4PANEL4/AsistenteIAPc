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

NUEVO: el ícono ya no es un círculo fijo — se regenera con PIL en
tiempo real reflejando el mismo estado que ya alimenta el orbe de
ui.py (ver ui_estado.py): cambia de color según el modo (escuchando/
procesando/hablando/dormido/inactivo), late suavemente mientras el
asistente está activo, respira lento en modo dormido, y muestra una
insignia roja superpuesta (mismo símbolo de "no molestar" que ya usa
el panel expandido) cuando ese modo está encendido — el mismo
lenguaje visual que un ícono de llamada o una insignia de
notificación en cualquier app de chat. Los cambios de modo no saltan
de golpe: se mezclan de a poco durante unos cuantos frames antes de
asentarse en el color nuevo.

Esto corre en un hilo aparte, propio de este módulo (no comparte
loop con ui.py) — solo LEE ui_estado.py por polling, igual que hace
ui.py, así que ambos quedan sincronizados automáticamente sin que
main.py ni ui.py necesiten saber que la bandeja existe.
"""

import math
import threading
import time

from plataforma import es_windows

# FIX: esta feature es exclusivamente de Windows (ver docstring del
# módulo) pero se venía importando/llamando también en Linux sin
# ningún chequeo de plataforma. Ahí, pystray necesita un backend real
# de bandeja (AppIndicator/GTK o D-Bus StatusNotifierItem) con su
# loop de eventos — en Bazzite corriendo dentro de Distrobox ese
# socket normalmente no está disponible o no está bien reenviado al
# contenedor, y pystray falla a nivel de C con "epoll_ctl: Invalid
# argument", lo cual tumba TODO el proceso sin que ningún try/except
# de Python pueda atraparlo (por eso ni siquiera se veía el mensaje
# "[Bandeja] Error: ..." que sí está protegido más abajo).
#
# Hasta que se implemente un backend de bandeja específico para Linux
# (probado y confiable en un entorno con contenedor), se desactiva
# directamente ahí — el asistente funciona igual, solo que minimizar
# no deja un ícono para recuperarlo (ver el mensaje que se imprime
# más abajo).
if es_windows():
    try:
        import pystray
        from PIL import Image, ImageDraw, ImageFilter
        BANDEJA_DISPONIBLE = True
    except ImportError:
        BANDEJA_DISPONIBLE = False
        print("[Bandeja] pystray/Pillow no están instalados — no habrá "
              "ícono en la bandeja del sistema. El asistente funciona "
              "igual, pero minimizar solo será recuperable reabriendo "
              "el asistente.")
else:
    BANDEJA_DISPONIBLE = False
    print("[Bandeja] Ícono de bandeja no disponible en Linux en esta "
          "versión (pystray necesita un backend de bandeja que no está "
          "garantizado en Distrobox/Bazzite y puede tumbar el proceso). "
          "El asistente funciona igual, solo que minimizar no deja un "
          "ícono para recuperarlo — para volver a mostrar la ventana, "
          "reabrí el asistente.")

# =========================================================
# ÍCONO — colores por modo
# Mismos que ui.py (paleta "aurora fría"), para que la bandeja hable
# el mismo lenguaje visual que el orbe y el panel expandido. Los
# nombres de modo son exactamente los que ya usa ui_estado.py — si
# algún día se agrega un modo nuevo ahí, alcanza con agregar su color
# acá (el fallback a "inactivo" evita que un modo no contemplado
# rompa el dibujo).
# =========================================================

C_BG        = (11, 26, 31, 255)
C_ACENTO    = (45, 230, 192, 255)
C_AMARILLO  = (230, 192, 45, 255)
C_DORMIDO   = (139, 154, 232, 255)
C_TEXTO_DIM = (58, 90, 92, 255)
C_ROJO      = (255, 85, 102, 255)

COLOR_POR_MODO = {
    "inactivo":   C_TEXTO_DIM,
    "escuchando": C_ACENTO,
    "procesando": C_AMARILLO,
    "hablando":   C_ACENTO,
    "buscando":   C_AMARILLO,
    "dormido":    C_DORMIDO,
}

TAMANO_ICONO = 64

# supersampling — se dibuja más grande de lo necesario y se reduce al
# final con LANCZOS, para que el círculo y el halo no se vean
# dentados al tamaño real (chico) de un ícono de bandeja.
_SS = 4


def _mezclar(c1, c2, factor):
    """Interpola entre dos colores RGBA — usado tanto para el
    mezclado de color entre modos como, si hiciera falta, cualquier
    otro degradado simple acá adentro."""
    factor = max(0.0, min(1.0, factor))
    return tuple(int(c1[i] + (c2[i] - c1[i]) * factor) for i in range(3)) + (255,)


def _dibujar_frame(color_rgb, intensidad_pulso, no_molestar):
    """
    Dibuja UN frame del ícono, ya en el tamaño final. `color_rgb` es
    el color del círculo central (puede venir a mitad de una
    transición entre dos modos, ver _loop_animacion); `intensidad_
    pulso` (0..1) controla qué tan presente está el resplandor de
    fondo en este instante — 0 lo apaga del todo (modo inactivo).
    `no_molestar` agrega la insignia roja característica (mismo
    símbolo que ya usa el panel expandido: círculo relleno con una
    línea horizontal) en la esquina inferior derecha.
    """
    S = TAMANO_ICONO * _SS
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cx, cy = S // 2, S // 2
    r = int(S * 0.30)

    if intensidad_pulso > 0.02:
        halo = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        hdraw = ImageDraw.Draw(halo)
        r_halo = int(r * (1.5 + 0.5 * intensidad_pulso))
        alpha = int(90 * intensidad_pulso)
        hdraw.ellipse([cx - r_halo, cy - r_halo, cx + r_halo, cy + r_halo],
                     fill=(*color_rgb[:3], alpha))
        halo = halo.filter(ImageFilter.GaussianBlur(S * 0.05))
        img = Image.alpha_composite(img, halo)

    draw = ImageDraw.Draw(img)
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=C_BG)

    r_relleno = int(r * 0.62)
    draw.ellipse([cx - r_relleno, cy - r_relleno, cx + r_relleno, cy + r_relleno],
                fill=color_rgb)

    if no_molestar:
        bx, by = cx + int(r * 0.75), cy + int(r * 0.75)
        br = int(S * 0.16)
        draw.ellipse([bx - br, by - br, bx + br, by + br],
                    fill=C_ROJO, outline=C_BG, width=int(S * 0.025))
        medio_largo = br * 0.5
        draw.line([bx - medio_largo, by, bx + medio_largo, by],
                 fill=C_BG, width=max(2, int(S * 0.03)))

    return img.resize((TAMANO_ICONO, TAMANO_ICONO), Image.LANCZOS)


# =========================================================
# HILO DE ANIMACIÓN
# Lee ui_estado.get_estado() por polling (mismo mecanismo que ya usa
# ui.py para su propio orbe) y va empujando frames nuevos al ícono de
# pystray con icon.icon = <nueva imagen> — la forma estándar de
# animar un ícono de bandeja con esta librería.
#
# FPS deliberadamente bajo (mucho menor al del orbe grande en ui.py):
# un ícono de 16-32px reales en la bandeja de Windows no se beneficia
# de la misma fluidez que una animación grande en pantalla, y cada
# actualización del ícono del sistema tiene un costo real de SO que
# no vale la pena pagar 16 veces por segundo para algo tan chico.
# =========================================================

FPS_BANDEJA       = 8
PASOS_TRANSICION  = 8   # cuadros que dura el mezclado al cambiar de modo

_hilo_animacion    = None
_animacion_activa  = False


def _loop_animacion():
    fase           = 0.0
    modo_anterior  = None
    color_mostrado = COLOR_POR_MODO["inactivo"]
    transicion     = None   # [color_desde, color_hasta, paso_actual, pasos_totales] o None

    while _animacion_activa:
        try:
            from ui_estado import get_estado
            estado = get_estado()
        except Exception:
            estado = {}

        modo        = estado.get("modo", "inactivo")
        no_molestar = estado.get("no_molestar", False)
        color_destino = COLOR_POR_MODO.get(modo, COLOR_POR_MODO["inactivo"])

        if modo != modo_anterior:
            # arranca (o reemplaza) una transición corta hacia el
            # color del modo nuevo en vez de saltar de golpe — es la
            # "pequeña animación entre cambios de modo" que se pidió;
            # si ya había una transición en curso cuando el modo
            # vuelve a cambiar, se parte del color que se estuviera
            # mostrando en ESE momento, no del color del modo viejo
            # completo, para que no se sienta un salto dentro del salto.
            transicion    = [color_mostrado, color_destino, 0, PASOS_TRANSICION]
            modo_anterior = modo

        if transicion is not None:
            c_desde, c_hasta, paso, total = transicion
            factor = min(1.0, (paso + 1) / total)
            color_mostrado = _mezclar(c_desde, c_hasta, factor)
            transicion[2] += 1
            if transicion[2] >= total:
                transicion = None
                color_mostrado = color_destino
        else:
            color_mostrado = color_destino

        # pulso: los modos "activos" laten con más presencia; dormido
        # respira lento y suave (mismo lenguaje que el halo del orbe
        # grande en modo dormido); inactivo se queda quieto del todo.
        if modo == "inactivo":
            intensidad = 0.0
        elif modo == "dormido":
            intensidad = 0.25 + 0.20 * (math.sin(fase * 0.25) + 1) / 2
        else:
            intensidad = 0.35 + 0.35 * (math.sin(fase * 1.6) + 1) / 2

        fase += 0.35

        try:
            if _icono is not None:
                _icono.icon = _dibujar_frame(color_mostrado, intensidad, no_molestar)
        except Exception:
            # un fallo puntual dibujando/actualizando un frame no
            # amerita tumbar el hilo de animación entero — se
            # reintenta en la próxima vuelta, como cualquier otro
            # polling del proyecto (mismo criterio que _tick_* en
            # ui.py, que también están dentro de un try/except amplio).
            pass

        time.sleep(1 / FPS_BANDEJA)


_icono       = None
_hilo_icono  = None


def iniciar_bandeja(al_mostrar, al_cerrar):
    """
    Crea y muestra el ícono en la bandeja, y arranca el hilo que lo
    mantiene animado según el estado actual del asistente (ver
    _loop_animacion más arriba). `al_mostrar` se llama cuando el
    usuario elige "Mostrar" (o hace doble clic); `al_cerrar` cuando
    elige "Cerrar" — quien llama decide qué significa cada uno (ver
    ui.py: mostrar_ui / cerrar_definitivo).

    El ícono corre en su propio hilo daemon, igual que iniciar_ui()
    en ui.py — pystray tiene su propio loop de eventos (usa la API
    nativa de Windows por debajo) que bloquea igual que
    root.mainloop(). La animación corre en un hilo aparte del de
    pystray — solo empuja imágenes nuevas al ícono ya creado, nunca
    toca su loop de eventos directamente.

    Si pystray/Pillow no están disponibles, no hace nada — el
    asistente sigue funcionando sin bandeja, simplemente sin esa
    comodidad extra.
    """
    global _icono, _hilo_icono, _hilo_animacion, _animacion_activa

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

    icono_inicial = _dibujar_frame(COLOR_POR_MODO["inactivo"], 0.0, False)
    _icono = pystray.Icon("AsistenteIA", icono_inicial, "AsistenteIA", menu)

    def _run():
        try:
            _icono.run()
        except Exception as e:
            print(f"[Bandeja] Error: {e}")

    _hilo_icono = threading.Thread(target=_run, daemon=True, name="BandejaIcono")
    _hilo_icono.start()

    _animacion_activa = True
    _hilo_animacion = threading.Thread(
        target=_loop_animacion, daemon=True, name="BandejaAnimacion"
    )
    _hilo_animacion.start()


def detener_bandeja():
    """Quita el ícono de la bandeja. Llamar justo antes de cerrar el asistente."""
    global _animacion_activa

    # se apaga la animación PRIMERO — si se detuviera el ícono antes,
    # el hilo de animación podría seguir intentando asignarle
    # _icono.icon a un ícono ya detenido durante hasta 1/FPS_BANDEJA
    # de más (inofensivo gracias al try/except de _loop_animacion,
    # pero innecesario).
    _animacion_activa = False

    if _icono is not None:
        try:
            _icono.stop()
        except Exception:
            pass