import shutil
import subprocess
import requests
import time
import tempfile
import os
import threading

from config import MODELO_OLLAMA
from logger import log

# =========================================================
# VERIFICAR
# =========================================================

def ollama_instalado():
    return shutil.which("ollama") is not None


def ollama_ejecutandose():
    try:
        requests.get("http://127.0.0.1:11434", timeout=2)
        return True
    except Exception:
        return False


def modelo_instalado():
    """
    Antes esto buscaba 'gemma3', pero ia.py llama a Ollama usando
    config.MODELO_OLLAMA (qwen2.5:3b) → nunca coincidían y la IA
    de verdad nunca quedaba instalada. Ahora se revisa el modelo
    correcto, el mismo que se usa en ia.py.
    """
    try:
        salida = subprocess.check_output(
            ["ollama", "list"],
            text=True,
            encoding="utf-8"
        )
        return MODELO_OLLAMA.lower() in salida.lower()
    except Exception:
        return False

# =========================================================
# INSTALAR OLLAMA
# FIX: progreso de descarga + timeout
# =========================================================

def instalar_ollama(callback_progreso=None):
    """
    Descarga el instalador de Ollama, lo ejecuta, y espera a que el
    usuario confirme que terminó de instalarlo.

    `callback_progreso`, si se da, se llama con un texto corto en
    cada etapa (ej. "Descargando Ollama... 42%") — pensado para
    conectarlo a actualizar_splash() y que el progreso sea visible
    en el .exe empaquetado, donde los print() de consola no se ven
    en ningún lado.

    FIX/NUEVO: antes esto terminaba con un input() de consola para
    esperar la confirmación manual del usuario — se rompía en el
    .exe empaquetado (console=False → sys.stdin es None → excepción
    que tumbaba el arranque completo). Ahora se usa un diálogo de
    Tkinter (ver setup_ollama_gui.py), mismo patrón ya usado para la
    key de Groq, que además verifica de verdad que Ollama quedó
    instalado antes de dejar continuar.
    """

    def _reportar(texto):
        print(texto)
        if callback_progreso:
            try:
                callback_progreso(texto)
            except Exception:
                pass

    try:
        _reportar("Descargando Ollama...")

        url              = "https://ollama.com/download/OllamaSetup.exe"
        ruta_instalador  = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")

        r = requests.get(url, stream=True, timeout=60)

        total    = int(r.headers.get("content-length", 0))
        descargado = 0

        with open(ruta_instalador, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    descargado += len(chunk)

                    if total:
                        pct = descargado * 100 // total
                        # FIX: se reemplazó el print con \r (invisible
                        # en el .exe empaquetado, sin consola) por
                        # _reportar(), que además de imprimir en
                        # consola (para quien corre desde terminal)
                        # actualiza el splash si se le pasó el callback.
                        _reportar(f"Descargando Ollama... {pct}%")

        _reportar("Ejecutando instalador de Ollama...")

        subprocess.Popen([ruta_instalador])

        _reportar("Esperando a que instales Ollama...")

        from setup_ollama_gui import esperar_confirmacion_instalacion_gui
        if not esperar_confirmacion_instalacion_gui():
            print("[Ollama] Instalación cancelada por el usuario.")
            log.warning("Usuario canceló la instalación de Ollama en el diálogo de confirmación")
            return False

        return True

    except requests.Timeout:
        print("Error: timeout descargando Ollama")
        log.error("Timeout descargando el instalador de Ollama")
        return False
    except Exception as e:
        print("Error instalando Ollama:", e)
        log.exception("Error instalando Ollama")
        return False

# =========================================================
# ESPERAR INSTALACIÓN
# FIX: feedback cada 10 segundos
# =========================================================

def esperar_instalacion_ollama():

    print("Esperando instalación de Ollama...")

    tiempo_maximo = 600
    inicio        = time.time()
    ultimo_aviso  = inicio

    while time.time() - inicio < tiempo_maximo:

        if ollama_instalado():
            print("Ollama detectado.")
            return True

        # FIX: avisar cada 10 segundos que sigue esperando
        if time.time() - ultimo_aviso >= 10:
            segundos = int(time.time() - inicio)
            print(f"  Esperando... ({segundos}s)")
            ultimo_aviso = time.time()

        time.sleep(2)

    print("Timeout esperando instalación.")
    log.error("Timeout esperando a que se completara la instalación de Ollama")
    return False

# =========================================================
# INICIAR OLLAMA
# =========================================================

def iniciar_ollama():

    if ollama_ejecutandose():
        return True

    try:
        print("Iniciando Ollama...")
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception as e:
        print("Error iniciando Ollama:", e)
        log.exception("Error iniciando Ollama (sin esto, no hay respaldo de IA sin internet)")
        return False

    for i in range(30):
        if ollama_ejecutandose():
            print("Ollama listo.")
            return True
        time.sleep(1)

    print("Timeout iniciando Ollama.")
    log.error("Timeout iniciando Ollama (sin esto, no hay respaldo de IA sin internet)")
    return False

# =========================================================
# DETENER OLLAMA
# NUEVO: parte del modo híbrido de IA (ver ia.py) — mientras hay
# internet, se usa Groq en la nube en vez de Ollama local, y Ollama
# se detiene por completo para no dejar el proceso "llama-server"
# consumiendo GPU de fondo (problema real reportado: 40-70% de GPU
# sostenido incluso con el modelo en reposo, sin generar nada — un
# bug conocido de Ollama, no el comportamiento esperado).
#
# "ollama serve" no tiene un comando de apagado en su propia CLI, así
# que se mata el proceso directamente por nombre — es el mecanismo
# estándar para detener este tipo de servicio en Windows cuando no
# hay una API de apagado expuesta.
# =========================================================

def ollama_detenido():
    """True si NINGÚN proceso de ollama está corriendo."""
    return not ollama_ejecutandose()


def detener_ollama():
    if ollama_detenido():
        return True

    try:
        print("Deteniendo Ollama...")
        # /IM ollama.exe cierra el proceso principal; /T también
        # cierra cualquier proceso hijo (como el propio llama-server,
        # que Ollama lanza como subproceso) — /F fuerza el cierre sin
        # pedir confirmación, necesario porque ollama.exe normalmente
        # no responde a un cierre "amable" al no tener ventana.
        subprocess.run(
            ["taskkill", "/IM", "ollama.exe", "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        # llama-server.exe puede quedar corriendo como proceso
        # separado incluso después de matar ollama.exe en algunas
        # versiones — se mata explícitamente también, por seguridad.
        subprocess.run(
            ["taskkill", "/IM", "llama-server.exe", "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:
        print("Error deteniendo Ollama:", e)
        log.exception("Error deteniendo Ollama (puede quedar consumiendo GPU de fondo)")
        return False

    for i in range(10):
        if ollama_detenido():
            print("Ollama detenido.")
            return True
        time.sleep(1)

    print("Timeout deteniendo Ollama.")
    log.error("Timeout deteniendo Ollama — el proceso puede haber quedado "
              "corriendo, consumiendo GPU de fondo sin necesidad")
    return False

# =========================================================
# INSTALAR GEMMA
# FIX: mostrar output en tiempo real para ver el progreso
# =========================================================

def instalar_modelo():

    print(f"Instalando {MODELO_OLLAMA} (puede tardar varios minutos)...")

    try:
        # FIX: sin Popen+wait, usar stdout directo para ver progreso
        proceso = subprocess.Popen(
            ["ollama", "pull", MODELO_OLLAMA],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )

        for linea in proceso.stdout:
            print(" ", linea.rstrip())

        proceso.wait()

    except Exception as e:
        print(f"Error instalando {MODELO_OLLAMA}:", e)
        log.exception(f"Error instalando el modelo {MODELO_OLLAMA} en Ollama")
        return False

    exito = modelo_instalado()

    if not exito:
        # FIX/NUEVO: el subprocess pudo terminar sin lanzar ninguna
        # excepción (returncode != 0 pero sin error de Python) y aun
        # así no haber instalado el modelo de verdad — sin este log,
        # ese caso pasaba completamente desapercibido en el archivo
        # de log (solo el texto del progreso quedaba en consola, y
        # nada indicaba que al final el modelo NO quedó instalado).
        log.error(f"ollama pull para {MODELO_OLLAMA} terminó sin errores de "
                  f"Python, pero el modelo no quedó instalado")

    return exito

# =========================================================
# PRECALENTAR MODELO
# NUEVO: aunque keep_alive=-1 (ver ia.py) evita que el modelo se
# descargue de memoria DESPUÉS de la primera vez que se usa, el
# costo de la PRIMERA carga sigue existiendo siempre — alguna vez
# hay que pagarlo. Sin esto, ese costo lo paga el primer comando
# real del usuario (el primer "abre discord" del día tarda varios
# segundos más de lo normal, sin razón aparente para quien no sabe
# de esto).
#
# La solución estándar es un "warm-up request": mandar una petición
# mínima al modelo apenas arranca el asistente, ANTES de que el
# usuario diga nada, para que cuando llegue el primer comando real,
# el modelo ya esté cargado en memoria.
#
# Esto corre en un hilo daemon aparte y NO bloquea el arranque del
# asistente — main.py puede decir "Asistente listo" y empezar a
# escuchar de inmediato, mientras el modelo se calienta en
# background. Si el precalentamiento tarda, el usuario simplemente
# no nota nada raro; si el primer comando real llega ANTES de que
# el precalentamiento termine, ese comando paga el costo de carga
# de todas formas (no hay forma de evitar eso sin bloquear el
# arranque, lo cual sería peor) — pero en la práctica, hay varios
# segundos de margen entre "Asistente listo" y que el usuario
# diga el wake word y luego un comando, así que casi siempre el
# precalentamiento ya terminó para entonces.
# =========================================================

def _precalentar_modelo():
    try:
        import ollama
        cliente = ollama.Client(timeout=60)

        print("[IA] Precalentando modelo en segundo plano...")
        inicio = time.time()

        cliente.chat(
            model=MODELO_OLLAMA,
            messages=[{"role": "user", "content": "hola"}],
            options={"num_predict": 1},
            keep_alive=-1,
        )

        print(f"[IA] Modelo precalentado en {time.time() - inicio:.1f}s")

    except Exception as e:
        # si esto falla, no es crítico — el modelo simplemente se
        # cargará en frío con el primer comando real, como pasaba
        # antes de este cambio. No vale la pena interrumpir el
        # arranque del asistente por esto.
        print("[IA] No se pudo precalentar el modelo:", e)


def precalentar_modelo_en_segundo_plano():
    """Llamar después de preparar_ia(), una sola vez al arrancar."""
    threading.Thread(target=_precalentar_modelo, daemon=True).start()

# =========================================================
# PREPARAR IA
# =========================================================

def preparar_ia(callback_progreso=None):
    """
    `callback_progreso`, si se da, se pasa a instalar_ollama() para
    que el progreso de descarga/instalación sea visible en el splash
    de arranque (ver main.py) en vez de solo en consola.
    """

    # ==================================
    # OLLAMA INSTALADO
    # ==================================

    if not ollama_instalado():
        print("Ollama no está instalado.")

        if not instalar_ollama(callback_progreso):
            return False

        if not esperar_instalacion_ollama():
            print("No se detectó la instalación.")
            return False

    # ==================================
    # OLLAMA CORRIENDO
    # ==================================

    if not iniciar_ollama():
        print("No pude iniciar Ollama.")
        return False

    # ==================================
    # MODELO INSTALADO
    # ==================================

    if not modelo_instalado():
        if not instalar_modelo():
            print(f"No pude instalar {MODELO_OLLAMA}.")
            return False

    print("IA lista.")
    return True