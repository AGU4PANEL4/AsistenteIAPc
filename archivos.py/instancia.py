"""
Mutex de instancia única de Windows ("AsistenteIA_Running").

FIX/NUEVO: esto vivía inline en main.py, pero actualizador.py necesita
poder LIBERAR ese mismo mutex justo antes de lanzar el instalador de
una actualización — y main.py es quien importa a actualizador.py (vía
tools.py), nunca al revés, así que actualizador.py no puede importar
`_mutex_handle` directo de main.py sin crear un import circular. Este
módulo chico y sin dependencias resuelve eso: ambos lo importan por
igual.

Por qué hace falta liberar el mutex manualmente en vez de solo confiar
en que el proceso termine:

El instalador (instalador.iss, InitializeSetup) usa
CheckForMutexes('AsistenteIA_Running') para avisar "el asistente
parece estar corriendo" antes de instalar. Windows libera un mutex
nombrado automáticamente cuando el proceso dueño termina — pero
"terminar" para un .exe empaquetado con PyInstaller (pygame,
faster-whisper, hilos daemon, etc. cargados en memoria) no es
instantáneo. El flujo de auto-actualización hacía Popen(instalador) +
sleep(1) + sys.exit(0): un segundo no siempre alcanza a que el
proceso muera del todo ANTES de que el instalador arranque y chequee
el mutex — una carrera que producía, de forma intermitente, el aviso
"el asistente está abierto, ¿continuar de todas formas?" en medio de
lo que se suponía era una actualización 100% automática.

Liberando el mutex nosotros mismos, de forma explícita, justo antes
de lanzar el instalador (ver actualizador.py), el chequeo del
instalador deja de depender de ningún timing — el mutex ya no existe
para cuando el instalador pregunta, sin importar cuánto tarde el
proceso viejo en terminar de cerrarse del todo por detrás.
"""

import ctypes

NOMBRE_MUTEX = "AsistenteIA_Running"

_handle = None


def crear():
    """
    Crea el mutex de instancia única. Llamar UNA sola vez, lo antes
    posible en main.py.

    Devuelve True si esta es la única instancia (arranque normal), o
    False si ya había otra instancia corriendo — en ese caso, quien
    llama debe cerrar este proceso de inmediato (dos instancias
    peleando por el micrófono al mismo tiempo daría comportamiento
    impredecible). El mutex ya queda liberado automáticamente en el
    caso False, no hace falta llamar a liberar() aparte.
    """
    global _handle

    try:
        _handle = ctypes.windll.kernel32.CreateMutexW(None, False, NOMBRE_MUTEX)
    except Exception as e:
        print(f"[Instancia] No se pudo crear el mutex de instancia única: {e}")
        return True  # no bloquear el arranque por esto

    ya_existia_otra = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS

    if ya_existia_otra:
        liberar()
        return False

    return True


def liberar():
    """
    Libera el mutex de instancia única.

    Llamar SIEMPRE justo antes de lanzar el instalador de una
    actualización (ver actualizador.py) — el proceso está a punto de
    cerrarse de todas formas (sys.exit(0) justo después), así que
    liberar el mutex un poco antes no cambia nada del comportamiento
    normal, pero garantiza que el instalador nunca vea esta instancia
    como "corriendo".
    """
    global _handle

    if _handle:
        try:
            ctypes.windll.kernel32.CloseHandle(_handle)
        except Exception:
            pass
        _handle = None