"""
Utilidades de dibujo compartidas entre las distintas ventanas de
Tkinter del proyecto (splash.py, ui.py) — mezclar colores para
simular desvanecido/transparencia (Canvas no lo soporta de forma
nativa por ítem), y el spinner de puntos usado tanto en la pantalla
de carga como en el estado "procesando" del orbe.
"""

import math


def mezclar_hex(color_hex, fondo_hex, factor):
    """
    Interpola entre `fondo_hex` (factor=0) y `color_hex` (factor=1).
    """
    def _rgb(h):
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

    r1, g1, b1 = _rgb(color_hex)
    r2, g2, b2 = _rgb(fondo_hex)
    factor = max(0.0, min(1.0, factor))
    r = int(r2 + (r1 - r2) * factor)
    g = int(g2 + (g1 - g2) * factor)
    b = int(b2 + (b1 - b2) * factor)
    return f"#{r:02x}{g:02x}{b:02x}"


def dibujar_puntos_spinner(canvas, cx, cy, radio, fase, color, color_fondo,
                           n_puntos=8, radio_punto=3, tags="anim"):
    """
    Dibuja un anillo de `n_puntos` puntos alrededor de (cx, cy), con
    el brillo de cada uno decreciendo según qué tan lejos está de
    `fase` (el punto "más nuevo" de la animación) — el spinner de
    puntos clásico (iOS/Android), en vez de un solo punto orbitando.

    Llamar en cada tick con una `fase` creciente (ej. +0.15 por
    llamada) para que el brillo dé la vuelta al anillo con el tiempo.
    Los ítems se crean con `tags` para poder borrarlos todos juntos
    (canvas.delete(tags)) antes del siguiente redibujado.
    """
    for i in range(n_puntos):
        angulo = 2 * math.pi * i / n_puntos
        x = cx + radio * math.cos(angulo)
        y = cy + radio * math.sin(angulo)

        # distancia angular normalizada a [0, 1) entre este punto y
        # la fase actual — 0 significa "es la cabeza", más brillante
        dist   = ((angulo - fase) / (2 * math.pi)) % 1.0
        brillo = max(0.12, (1.0 - dist) ** 2)

        tono = mezclar_hex(color, color_fondo, brillo)

        canvas.create_oval(
            x - radio_punto, y - radio_punto, x + radio_punto, y + radio_punto,
            fill=tono, outline="", tags=tags,
        )