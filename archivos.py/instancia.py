"""
Instancia única del asistente — evita que se abran dos procesos al
mismo tiempo (dos instancias peleando por el micrófono daría
comportamiento impredecible).

FIX/NUEVO: esto vivía inline en main.py, pero actualizador.py necesita
poder LIBERAR ese mismo mecanismo justo antes de lanzar el instalador
de una actualización — y main.py es quien importa a actualizador.py
(vía tools.py), nunca al revés, así que actualizador.py no puede
importar el handle directo de main.py sin crear un import circular.
Este módulo chico y sin dependencias resuelve eso: ambos lo importan
por igual.

NUEVO: soporte multiplataforma. El mecanismo es DISTINTO en cada
sistema operativo porque no hay una API común:

  - Windows: mutex nombrado del sistema (CreateMutexW) — igual que
    siempre funcionó. El instalador (instalador.iss, InitializeSetup)
    usa CheckForMutexes('AsistenteIA_Running') para avisar "el
    asistente parece estar corriendo" antes de instalar. Windows
    libera un mutex nombrado automáticamente cuando el proceso dueño
    termina — pero "terminar" para un .exe empaquetado con
    PyInstaller no es instantáneo, por eso liberar() se llama a mano
    justo antes de lanzar el instalador (ver actualizador.py) en vez
    de confiar en el timing de un Popen + sleep + exit.

  - Linux: no existe el concepto de "mutex nombrado del sistema" de
    la misma forma — el mecanismo estándar y ampliamente usado es un
    ARCHIVO DE LOCK con fcntl.flock(LOCK_EX | LOCK_NB): el sistema
    operativo mismo libera el lock automáticamente si el proceso
    muere (sin importar cómo — crash, kill -9, lo que sea), así que
    no hace falta ningún mecanismo adicional de limpieza. El archivo
    de lock vive en la misma carpeta de datos multiplataforma (ver
    rutas_datos.py). No hay flujo de auto-actualización con
    instalador en Linux (no hay instalador.iss ni actualizador.py
    aplicable ahí), así que el caso de "liberar antes de instalar"
    simplemente no se da en este sistema operativo — liberar() igual
    queda implementada por completitud/consistencia de la interfaz.
"""

from plataforma import es_windows
from rutas_datos import CARPETA_DATOS

NOMBRE_MUTEX  = "AsistenteIA_Running"
ARCHIVO_LOCK  = CARPETA_DATOS / "asistente.lock"

_handle           = None   # Windows: HANDLE del mutex
_archivo_lock_fd  = None   # Linux: descriptor de archivo con flock


def crear():
    """
    Reserva la instancia única. Llamar UNA sola vez, lo antes posible
    en main.py.

    Devuelve True si esta es la única instancia (arranque normal), o
    False si ya había otra instancia corriendo — en ese caso, quien
    llama debe cerrar este proceso de inmediato. El recurso ya queda
    liberado automáticamente en el caso False, no hace falta llamar a
    liberar() aparte.
    """
    if es_windows():
        return _crear_windows()
    return _crear_linux()


def liberar():
    """
    Libera la instancia única.

    En Windows: llamar SIEMPRE justo antes de lanzar el instalador de
    una actualización (ver actualizador.py) — el proceso está a punto
    de cerrarse de todas formas, así que liberar el mutex un poco
    antes no cambia nada del comportamiento normal, pero garantiza que
    el instalador nunca vea esta instancia como "corriendo".

    En Linux: no hay flujo de instalador que necesite esto, pero
    liberar el lock explícitamente (además de que el sistema operativo
    ya lo hace solo al morir el proceso) no tiene ningún costo ni
    efecto secundario negativo.
    """
    if es_windows():
        _liberar_windows()
    else:
        _liberar_linux()


# =========================================================
# WINDOWS — mutex nombrado del sistema
# =========================================================

def _crear_windows():
    global _handle

    import ctypes

    try:
        _handle = ctypes.windll.kernel32.CreateMutexW(None, False, NOMBRE_MUTEX)
    except Exception as e:
        print(f"[Instancia] No se pudo crear el mutex de instancia única: {e}")
        return True  # no bloquear el arranque por esto

    ya_existia_otra = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS

    if ya_existia_otra:
        _liberar_windows()
        return False

    return True


def _liberar_windows():
    global _handle

    if _handle:
        import ctypes
        try:
            ctypes.windll.kernel32.CloseHandle(_handle)
        except Exception:
            pass
        _handle = None


# =========================================================
# LINUX — archivo de lock con fcntl.flock
# =========================================================

def _crear_linux():
    global _archivo_lock_fd

    import fcntl

    try:
        # 'a+' en vez de 'w' — abrir en modo escritura ('w') truncaría
        # el archivo en cada intento (incluso el de una segunda
        # instancia que solo viene a CHEQUEAR el lock), lo cual no
        # importa para el lock en sí, pero 'a+' es más prolijo si
        # algún día se quisiera inspeccionar el contenido (guardamos
        # el PID) sin arriesgar perder esa info por una apertura
        # concurrente que no llegó a tomar el lock.
        f = open(ARCHIVO_LOCK, "a+")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # ya hay otra instancia con el lock tomado
        try:
            f.close()
        except Exception:
            pass
        return False
    except Exception as e:
        print(f"[Instancia] No se pudo crear el lock de instancia única: {e}")
        return True  # no bloquear el arranque por esto

    # se registra el PID actual — solo para diagnóstico manual (ej.
    # "¿qué proceso tiene este lock?"), el lock en sí no depende de
    # leer este contenido para funcionar.
    try:
        import os
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()))
        f.flush()
    except Exception:
        pass

    _archivo_lock_fd = f
    return True


def _liberar_linux():
    global _archivo_lock_fd

    if _archivo_lock_fd is not None:
        import fcntl
        try:
            fcntl.flock(_archivo_lock_fd.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            _archivo_lock_fd.close()
        except Exception:
            pass
        _archivo_lock_fd = None