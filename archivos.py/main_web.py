"""
Prototipo de la interfaz de AsistenteIA usando pywebview.
"""

import json
import os
import threading
import webview

import orbe_tk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_PANEL = os.path.join(BASE_DIR, "web", "panel.html")
ARCHIVO_ICONO = os.path.join(BASE_DIR, "asistente-ia.ico")


def _leer_estado():
    from ui_estado import get_estado
    return get_estado()


class Api:
    def __init__(self, window):
        self._window = window
        self._orbe = None

    def get_estado(self):
        try:
            estado = _leer_estado()
        except Exception:
            estado = {}
        modo = estado.get("modo", "inactivo")
        textos = {
            "inactivo":   'Inactivo — di "jarvis"',
            "escuchando": "Escuchando...",
            "procesando": "Procesando...",
            "buscando":   "Buscando app...",
            "hablando":   "Hablando...",
        }
        return {
            "modo": modo,
            "texto_modo": textos.get(modo, modo),
            "motor": estado.get("motor_ia", "—"),
            "wake_word": estado.get("wake_word", "jarvis"),
            "no_molestar": bool(estado.get("no_molestar", False)),
        }

    def resumen_categorias(self):
        return {
            "temporizadores": self._resumen_temporizadores(),
            "recordatorios":  self._resumen_recordatorios(),
            "alias":          self._resumen_alias(),
            "macros":         self._resumen_macros(),
        }

    def _resumen_temporizadores(self):
        try:
            from temporizadores import listar_temporizadores
            from datetime import datetime
            items = sorted(listar_temporizadores().items())
            lineas = []
            for _id, info in items[:2]:
                try:
                    cuando = datetime.fromisoformat(info["momento"]).strftime("%H:%M")
                except Exception:
                    cuando = "—"
                lineas.append(f"· {info.get('nombre') or 'sin nombre'} {cuando}")
            return {"conteo": len(items), "lineas": lineas}
        except Exception:
            return {"conteo": 0, "lineas": []}

    def _resumen_recordatorios(self):
        try:
            from recordatorios import listar_recordatorios_ordenados
            items = listar_recordatorios_ordenados()
            lineas = [f"· {info.get('texto', '')[:14]}" for _id, info in items[:2]]
            return {"conteo": len(items), "lineas": lineas}
        except Exception:
            return {"conteo": 0, "lineas": []}

    def _resumen_alias(self):
        try:
            from aliases import listar_aliases
            nombres = sorted(listar_aliases().keys())
            return {"conteo": len(nombres), "lineas": [f"· {n[:14]}" for n in nombres[:2]]}
        except Exception:
            return {"conteo": 0, "lineas": []}

    def _resumen_macros(self):
        try:
            from macros import listar_macros
            nombres = sorted(listar_macros().keys())
            return {"conteo": len(nombres), "lineas": [f"· {n[:14]}" for n in nombres[:2]]}
        except Exception:
            return {"conteo": 0, "lineas": []}

    def listar_categoria(self, cat):
        try:
            if cat == "temporizadores":
                from temporizadores import listar_temporizadores
                from datetime import datetime
                out = []
                for id_str, info in sorted(listar_temporizadores().items()):
                    try:
                        cuando = datetime.fromisoformat(info["momento"]).strftime("%H:%M")
                    except Exception:
                        cuando = "—"
                    out.append({"clave": id_str, "principal": info.get("nombre") or "sin nombre",
                                "secundario": f"suena a las {cuando}"})
                return out
            if cat == "recordatorios":
                from recordatorios import listar_recordatorios_ordenados
                from datetime import datetime
                out = []
                for id_str, info in listar_recordatorios_ordenados():
                    try:
                        cuando = datetime.fromisoformat(info["momento"]).strftime("%d/%m %H:%M")
                    except Exception:
                        cuando = "—"
                    out.append({"clave": id_str, "principal": info.get("texto", ""), "secundario": cuando})
                return out
            if cat == "alias":
                from aliases import listar_aliases
                out = [{"clave": a, "principal": a, "secundario": None}
                       for a in sorted(listar_aliases().keys())]
                return out
            if cat == "macros":
                from macros import listar_macros
                out = []
                for nombre, pasos in sorted(listar_macros().items()):
                    out.append({"clave": nombre, "principal": nombre, "secundario": f"{len(pasos)} pasos"})
                return out
        except Exception:
            pass
        return []

    def eliminar_item(self, cat, clave):
        try:
            if cat == "temporizadores":
                from temporizadores import cancelar_temporizador
                cancelar_temporizador(clave)
            elif cat == "recordatorios":
                from recordatorios import cancelar_recordatorio
                cancelar_recordatorio(clave)
            elif cat == "alias":
                from aliases import eliminar_alias
                eliminar_alias(clave)
            elif cat == "macros":
                from macros import eliminar_macro
                eliminar_macro(clave)
            return True
        except Exception:
            return False

    def historial(self):
        try:
            from ui_estado import get_historial
            items = get_historial()
            return list(items)[-40:] if items else []
        except Exception:
            return []

    def mover_ventana(self, dx, dy):
        try:
            x = self._window.x + int(dx)
            y = self._window.y + int(dy)
            self._window.move(x, y)
        except Exception:
            pass

    def minimizar(self):
        try:
            self._window.minimize()
        except Exception:
            pass

    def cerrar_app(self):
        try:
            self._window.destroy()
        except Exception:
            pass

    # FIX: colapsar mueve el orbe para que su esquina superior derecha
    # coincida con la esquina superior derecha del panel. Así al expandir,
    # el cálculo x = ox + ORBE_CANVAS - 340 da exactamente la posición
    # anterior del panel, sin saltos.
    def colapsar(self):
        print("[WebUI] colapsar() llamado — ocultando ventana y mostrando orbe")
        
        try:
            if self._orbe is not None:
                px, py = self._window.x, self._window.y
                # Orbe alineado por esquina superior derecha con el panel
                ox = px + 340 - orbe_tk.ORBE_CANVAS
                oy = py
                ox = max(0, ox)
                oy = max(0, oy)
                self._orbe.mover_a(ox, oy)
                print(f"[WebUI] Orbe movido a {ox},{oy} (alineado sup-derecha)")
        except Exception as e:
            print(f"[WebUI] Error moviendo orbe: {e}")
        
        try:
            self._window.hide()
            print("[WebUI] window.hide() OK")
        except Exception as e:
            print(f"[WebUI] window.hide() falló: {e}")
        
        if self._orbe is not None:
            try:
                self._orbe.mostrar()
                print("[WebUI] orbe mostrado")
            except Exception as e:
                print(f"[WebUI] Error mostrando orbe: {e}")

    def ocultar_ventana(self):
        print("[WebUI] ocultar_ventana() llamado — delegando a colapsar()")
        self.colapsar()

def _crear_ventana_y_arrancar(orbe_existente=None):
    window = webview.create_window(
        "AsistenteIA",
        ARCHIVO_PANEL,
        width=340, height=480,
        frameless=True,
        easy_drag=False,
        on_top=True,
        hidden=True,
    )
    api = Api(window)
    window.expose(
        api.get_estado, api.resumen_categorias, api.listar_categoria,
        api.eliminar_item, api.historial, api.mover_ventana,
        api.minimizar, api.cerrar_app, api.colapsar,
        api.ocultar_ventana,
    )

    def _al_expandir_orbe():
        print("[WebUI] Expandir orbe clickeado")
        try:
            ox, oy = orbe.posicion
            # La esquina superior derecha del orbe es (ox + ORBE_CANVAS, oy)
            # El panel debe posicionarse para que su esquina sup-derecha toque ahí
            x = ox + orbe_tk.ORBE_CANVAS - 340
            y = oy
            window.move(max(0, x), max(0, y))
            print(f"[WebUI] Ventana movida a {x},{y}")
        except Exception as e:
            print(f"[WebUI] Error moviendo ventana: {e}")
        try:
            orbe.ocultar()
            print("[WebUI] Orbe ocultado")
        except Exception as e:
            print(f"[WebUI] Error ocultando orbe: {e}")
        try:
            window.show()
            print("[WebUI] Ventana mostrada")
        except Exception as e:
            print(f"[WebUI] Error mostrando ventana: {e}")
        
        try:
            window.evaluate_js("""
                if (typeof expandirPanel === 'function') {
                    expandirPanel();
                    console.log('[JS] expandirPanel() llamado');
                } else {
                    console.log('[JS] expandirPanel NO encontrado');
                }
            """)
        except Exception as e:
            print(f"[WebUI] Error expandiendo panel: {e}")

    if orbe_existente is not None:
        orbe = orbe_existente
        api._orbe = orbe
        orbe._on_expandir = _al_expandir_orbe
    else:
        orbe = orbe_tk.OrbeFlotante(on_expandir=_al_expandir_orbe)
        api._orbe = orbe

    import inspect
    kwargs_start = {"debug": False}
    if "icon" in inspect.signature(webview.start).parameters:
        kwargs_start["icon"] = ARCHIVO_ICONO
    webview.start(**kwargs_start)


if __name__ == "__main__":
    _crear_ventana_y_arrancar()