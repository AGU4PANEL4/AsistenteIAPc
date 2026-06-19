import shutil
import subprocess
import requests
import time
import tempfile
import os

from config import MODELO_OLLAMA

# =========================================================
# VERIFICAR
# =========================================================

def ollama_instalado():
    return shutil.which("ollama") is not None


def ollama_ejecutandose():
    try:
        requests.get("http://127.0.0.1:11434", timeout=2)
        return True
    except:
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
    except:
        return False

# =========================================================
# INSTALAR OLLAMA
# FIX: progreso de descarga + timeout
# =========================================================

def instalar_ollama():

    try:
        print("Descargando Ollama...")

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

                    # FIX: mostrar progreso
                    if total:
                        pct = descargado * 100 // total
                        print(f"\r  Descargando... {pct}%", end="", flush=True)

        print("\nEjecutando instalador...")
        print("Instala Ollama y luego presiona Enter para continuar...")

        subprocess.Popen([ruta_instalador])

        input()  # esperar confirmación manual

        return True

    except requests.Timeout:
        print("Error: timeout descargando Ollama")
        return False
    except Exception as e:
        print("Error instalando Ollama:", e)
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
        return False

    for i in range(30):
        if ollama_ejecutandose():
            print("Ollama listo.")
            return True
        time.sleep(1)

    print("Timeout iniciando Ollama.")
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
        return False

    return modelo_instalado()

# =========================================================
# PREPARAR IA
# =========================================================

def preparar_ia():

    # ==================================
    # OLLAMA INSTALADO
    # ==================================

    if not ollama_instalado():
        print("Ollama no está instalado.")

        if not instalar_ollama():
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