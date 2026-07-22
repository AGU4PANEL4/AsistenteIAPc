# -*- mode: python ; coding: utf-8 -*-
#
# Spec de PyInstaller para AsistenteIA — versión LINUX.
# Hermano de asistente.spec (Windows): misma estructura, mismos
# datos recolectados (faster-whisper/tokenizers/certifi), pero con
# los hiddenimports específicos de Windows (winsdk, pycaw, comtypes,
# win32com, pyttsx3.drivers.sapi5, pystray._win32) cambiados por sus
# equivalentes de Linux.
#
# Se construye EN Linux (ver build_linux.sh) — PyInstaller no
# cross-compila, así que este .spec no sirve corriendo pyinstaller
# desde Windows, tiene que correr dentro de la Ubuntu de WSL2.
#
# Uso (desde la carpeta del proyecto, con el venv activado, en Linux):
#     pyinstaller asistente_linux.spec --noconfirm
#
# El resultado queda en dist/AsistenteIA/AsistenteIA (modo carpeta,
# igual que la versión Windows — más rápido de arrancar que onefile
# con dependencias tan pesadas como pygame/pyaudio/faster-whisper).

import speech_recognition as sr
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

# Igual que en Windows: speech_recognition necesita sus datos
# internos copiados a mano, o recognize_google() falla en el
# ejecutable aunque funcione perfecto corriendo el .py directo.
RUTA_SR = Path(sr.__file__).resolve().parent

# ctranslate2 (motor nativo de faster-whisper) trae binarios .so que
# PyInstaller no detecta solo por análisis de imports — en Linux es
# el mismo problema que las .dll en Windows, solo que acá son .so.
binarios_ctranslate2 = collect_dynamic_libs("ctranslate2")

# tokenizers trae archivos de datos propios (vocabularios) — igual
# que en Windows.
datos_tokenizers = collect_data_files("tokenizers")

# Modelo VAD (Silero) que trae faster_whisper como .onnx interno —
# igual que en Windows, sin esto la transcripción falla buscando
# silero_vad_v6.onnx.
datos_faster_whisper = collect_data_files("faster_whisper")

# certifi (cacert.pem) — igual que en Windows, necesario para que
# requests/httpx (actualizador.py NO aplica en Linux, pero
# groq_cliente.py sí) puedan verificar certificados SSL en HTTPS.
datos_certifi = collect_data_files("certifi")

datas = [
    (str(RUTA_SR), "speech_recognition"),
] + datos_tokenizers + datos_faster_whisper + datos_certifi

hiddenimports = [
    # edge_tts / aiohttp usan resolución dinámica de protocolos —
    # igual en Linux que en Windows.
    "aiohttp",

    # pyttsx3 es el respaldo de voz local si Edge TTS falla. En
    # Windows usa el driver "sapi5"; en Linux usa "espeak" (habla
    # con espeak-ng vía D-Bus o el binario, según lo que encuentre
    # instalado — ver espeak-ng en las dependencias de sistema).
    "pyttsx3",
    "pyttsx3.drivers",
    "pyttsx3.drivers.espeak",

    # faster-whisper / ctranslate2 — igual en ambos SO.
    "faster_whisper",
    "ctranslate2",

    # tkinter — igual en ambos SO, capa de seguridad por si el
    # análisis estático no lo detecta solo desde el entry point.
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "tkinter.simpledialog",

    # pystray / Pillow — ícono de bandeja (bandeja.py). En Windows
    # el backend es win32; en Linux, pystray elige entre appindicator
    # (GTK + AppIndicator3, lo más común en distros de escritorio) o
    # xorg (X11 puro, sin bandeja "de verdad" en muchos entornos
    # modernos) según qué encuentre disponible en tiempo de
    # ejecución — por eso se declaran ambos backends como hidden
    # import, para que el que corresponda esté disponible sin
    # importar en qué escritorio corra.
    "pystray",
    "pystray._appindicator",
    "pystray._gtk",
    "pystray._xorg",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",

    # gi (PyGObject) — lo que pystray._appindicator usa por debajo
    # para hablar con GTK/AppIndicator. Requiere python3-gi instalado
    # a nivel de SISTEMA (no es instalable con pip solo) — ver
    # dependencias de sistema en build_linux.sh/instalar.sh. Si el
    # entorno de build no tiene python3-gi, PyInstaller simplemente
    # no podrá recolectar este import y pystray caerá al backend
    # xorg en tiempo de ejecución (bandeja más limitada, pero el
    # asistente no se cae por esto).
    "gi",
    "gi.repository.Gtk",
    "gi.repository.AppIndicator3",
    "gi.repository.GLib",

    # certifi — ver el comentario junto a datos_certifi más arriba.
    "certifi",

    # python-xlib — usado indirectamente por algunas piezas de la
    # capa Linux (ventanas_linux.py se apoya en wmctrl/xdotool como
    # subprocess, pero python-xlib está en requirements.txt para
    # sys_platform == "linux" por si algún otro módulo lo necesita
    # directo) — declarado por seguridad, mismo criterio que el
    # resto de esta lista.
    "Xlib",
]

# NOTA/TROUBLESHOOTING (igual que en el spec de Windows): si al
# probar el ejecutable empaquetado ves un error de import relacionado
# con "httpx", agregá "httpx" a hiddenimports acá arriba — httpx
# importa algunos backends de transporte de forma condicional
# (try/except ImportError) que el análisis estático de PyInstaller
# puede no seguir bien. No se agrega de entrada por la misma razón
# que en Windows: groq/httpx son imports directos y normales que en
# la gran mayoría de los casos sí se detectan solos.
#
# NOTA (específica de Linux): si al abrir el ícono de bandeja no
# aparece nada (o pystray tira un error silencioso), lo más probable
# es que falte python3-gi/gir1.2-appindicator3 a nivel de SISTEMA en
# la máquina donde se construyó el paquete — reconstruir después de
# instalar esas dependencias (ver build_linux.sh).

block_cipher = None

# Mismo criterio que en Windows: excluir dependencias transitivas
# opcionales de faster-whisper que no hacen falta corriendo en CPU.
# Ver la nota del spec de Windows sobre openai-whisper — el mismo
# problema (y la misma solución: no tenerlo instalado en el entorno
# de build) aplica acá igual.
EXCLUIR = [
    "whisper",
    "torch",
    "torchvision",
    "torchaudio",
    "torch.utils.tensorboard",
    "tensorboard",
    "numba",
    "llvmlite",
    "IPython",
    "ipykernel",
    "jupyter",
    "matplotlib",
    "scipy",
    "sklearn",
    "sklearn.utils",
    "pandas",
    "onnx",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binarios_ctranslate2,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUIR,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AsistenteIA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # En Linux no existe la distinción console=True/False de Windows
    # (no hay "subsistema de ventanas" separado) — este flag no tiene
    # efecto real acá, se deja en False solo por paridad con el spec
    # de Windows. Los logs siguen yendo a
    # ~/.local/share/AsistenteIA/asistente.log como siempre
    # (ver rutas_datos.py).
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # PyInstaller en Linux ignora .ico de todas formas
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AsistenteIA",
)
