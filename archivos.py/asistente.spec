# -*- mode: python ; coding: utf-8 -*-
#
# Spec de PyInstaller para AsistenteIA.
#
# Uso (desde la carpeta del proyecto, con el venv activado):
#     pyinstaller asistente.spec --noconfirm
#
# El resultado queda en dist/AsistenteIA/AsistenteIA.exe (modo carpeta,
# no "un solo archivo" — onefile arranca más lento porque descomprime
# todo en una carpeta temporal cada vez que abres el programa, y con
# tantas dependencias pesadas como pygame/pyaudio/win32 conviene más
# la carpeta normal).

import speech_recognition as sr
from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files

# speech_recognition trae internamente el archivo de credenciales por
# defecto para la API de reconocimiento de Google (pocketsphinx-data,
# flac.exe, etc.). Si no se copian, recognize_google() falla en el
# .exe aunque funcione perfecto al correr el .py directo.
RUTA_SR = Path(sr.__file__).resolve().parent

# faster-whisper corre sobre ctranslate2, que trae DLLs nativas
# (libctranslate2.dll, OpenMP, etc.) que PyInstaller no detecta solo
# por análisis de imports — hay que recolectarlas explícitamente, o
# el .exe truena con un error de DLL faltante apenas intenta cargar
# el modelo de Whisper.
binarios_ctranslate2 = collect_dynamic_libs("ctranslate2")

# tokenizers (dependencia de faster-whisper) a veces trae archivos
# de datos propios (vocabularios, etc.) que también hay que copiar.
datos_tokenizers = collect_data_files("tokenizers")

# faster_whisper trae su propio modelo VAD (detección de voz, Silero)
# como archivo de datos interno en faster_whisper/assets/*.onnx — se
# usa porque voice.py llama a transcribe(..., vad_filter=True). Sin
# esto, PyInstaller no lo copia (no es código Python, es un .onnx) y
# la transcripción falla con NO_SUCHFILE buscando silero_vad_v6.onnx.
datos_faster_whisper = collect_data_files("faster_whisper")

# NUEVO: certifi trae el archivo cacert.pem con la lista de
# autoridades certificadoras confiables — requests (actualizador.py,
# hablando con la API de GitHub) y el cliente de Groq (que usa httpx
# por debajo) lo necesitan para verificar certificados SSL en
# CUALQUIER petición HTTPS. Corriendo con "python main.py" esto
# funciona solo porque el certifi del entorno de desarrollo ya está
# instalado normalmente y Python lo encuentra sin ayuda — pero
# PyInstaller no copia archivos de datos por análisis de imports (el
# mismo motivo por el que hay que declarar datos_faster_whisper y
# datos_tokenizers arriba), así que sin esto el .exe empaquetado
# podía fallar con errores de verificación SSL ("certificate verify
# failed") en CUALQUIER cosa que hable HTTPS: buscar actualizaciones,
# o Groq si no fallaba antes por otro motivo — un problema muy
# conocido y común al empaquetar apps que usan requests/httpx con
# PyInstaller, fácil de pasar por alto porque nunca se nota en
# desarrollo, solo en el .exe ya armado.
datos_certifi = collect_data_files("certifi")

datas = [
    (str(RUTA_SR), "speech_recognition"),
    # NUEVO: ícono de la app como archivo suelto junto al .exe (no
    # solo embebido en el propio .exe vía icon= más abajo) — lo
    # necesita icono_app.py/splash.py para fijar el ícono de la
    # VENTANA en tiempo de ejecución (root.iconbitmap/iconphoto),
    # algo que el ícono embebido del .exe no cubre por sí solo. El
    # segundo elemento de la tupla ("." ) pone el archivo en la raíz
    # de la carpeta dist/AsistenteIA, junto a AsistenteIA.exe — mismo
    # nivel que sys.executable, que es justo donde icono_app.py busca
    # cuando sys.frozen es True.
    ("asistente-ia.ico", "."),
    ("asistente-ia.png", "."),
    # FIX: la carpeta web/ (panel.html, panel.css, panel.js) que usa
    # main_web.py vía pywebview NO se estaba copiando — PyInstaller
    # solo empaqueta código Python por análisis de imports, nunca
    # HTML/CSS/JS sueltos, así que hay que declararlos a mano igual
    # que los íconos de arriba. Sin esto, ARCHIVO_PANEL apunta a una
    # ruta que no existe dentro de dist/AsistenteIA y pywebview tira
    # 404 Not Found al intentar cargar panel.html (funciona en
    # desarrollo solo porque ahí la carpeta web/ sí está en disco
    # junto a main.py). El primer elemento es la carpeta de ORIGEN
    # relativa a este .spec, el segundo es el nombre de carpeta
    # DESTINO dentro de dist/AsistenteIA — deben coincidir con
    # os.path.join(BASE_DIR, "web", "panel.html") en main_web.py.
    ("web", "web"),
] + datos_tokenizers + datos_faster_whisper + datos_certifi

hiddenimports = [
    # winsdk usa imports dinámicos por namespace que PyInstaller no
    # detecta solo analizando el código — hay que declararlos a mano.
    "winsdk",
    "winsdk.windows.media.control",
    "winsdk.windows.foundation",
    "winsdk.windows.foundation.collections",

    # pycaw / comtypes generan código dinámicamente en tiempo de
    # ejecución (interfaces COM) — sin esto, el control de volumen
    # por app falla en el .exe.
    "comtypes.stream",
    "pycaw.pycaw",

    # win32com a veces hace falta explícito aunque no se importe
    # directo en el código, porque pywin32 lo usa internamente.
    "win32com",
    "win32timezone",

    # edge_tts / aiohttp usan resolución dinámica de protocolos
    "aiohttp",

    # pyttsx3 es el respaldo de voz local (SAPI5) si Edge TTS
    # falla — usa win32com.client por debajo, que con imports
    # dinámicos PyInstaller no siempre detecta solo.
    "pyttsx3",
    "pyttsx3.drivers",
    "pyttsx3.drivers.sapi5",

    # faster-whisper / ctranslate2 — el binding de Python carga
    # el motor nativo de forma indirecta.
    "faster_whisper",
    "ctranslate2",

    # tkinter — interfaz flotante (ui.py). Aunque tkinter es parte
    # de la librería estándar, en algunos entornos PyInstaller no
    # lo detecta automáticamente si no hay un import directo en el
    # entry point. Se declara explícitamente como capa de seguridad.
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "tkinter.simpledialog",

    # pystray / Pillow — ícono en la bandeja del sistema (bandeja.py).
    # pystray elige el backend según el sistema operativo con
    # imports dinámicos que PyInstaller no detecta solo — hay que
    # declarar explícitamente el backend de Windows.
    "pystray",
    "pystray._win32",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",

    # certifi — ver el comentario junto a datos_certifi más arriba.
    "certifi",
]

# NOTA/TROUBLESHOOTING: si al probar el .exe empaquetado ves un error
# de import relacionado con "httpx" (la librería HTTP que usa el
# cliente de groq por debajo), agregá "httpx" a hiddenimports acá
# arriba — httpx importa algunos de sus backends de transporte de
# forma condicional (try/except ImportError), un patrón que el
# análisis estático de PyInstaller puede no detectar como "esto se
# usa de verdad". No se agrega de entrada porque groq/httpx son
# imports directos y normales (`import groq`), que si análisis
# estático SÍ sigue correctamente en la gran mayoría de los casos —
# esto es solo la salida rápida si llegara a fallar igual.

block_cipher = None

# Módulos a excluir explícitamente — faster-whisper los arrastra
# como dependencias transitivas opcionales, pero con ctranslate2
# en CPU no los necesita para nada. Incluirlos infla la carpeta
# _internal de 400MB a ~4GB y multiplica el tiempo de arranque.
#
# NOTA IMPORTANTE: si este exclude no estaba siendo respetado y la
# carpeta _internal pesaba ~4GB de todas formas, la causa real (ya
# diagnosticada) era tener "openai-whisper" instalado en el entorno
# de empaquetado — un paquete DISTINTO de faster-whisper, que sí
# depende de PyTorch completo con soporte CUDA. PyInstaller detecta
# esa dependencia REAL y activa, y eso puede pesar más que el
# exclude declarado acá. La solución real es no tener openai-whisper
# instalado en el entorno donde se empaqueta (ver requirements.txt):
#   pip uninstall openai-whisper torch torchvision torchaudio -y
# Este EXCLUIR se deja como segunda capa de seguridad, no como la
# solución principal.
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
    # console=False — el .exe no muestra ventana de consola al usuario
    # final. Cuando desarrollás desde VS Code / terminal usás
    # `python main.py` directamente, así que la consola siempre está
    # visible ahí sin importar este flag (este flag solo afecta al
    # .exe empaquetado). Los logs siguen escribiéndose al archivo
    # %LOCALAPPDATA%\AsistenteIA\asistente.log como siempre.
    # Si necesitás ver la consola del .exe para diagnosticar algo,
    # temporalmente cambiá a console=True y reempaquetá.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # NUEVO: ícono del .exe compilado — se ve en el propio archivo
    # .exe (Explorador de Windows), en la barra de tareas mientras
    # corre, y es lo que heredan automáticamente los accesos directos
    # que instalador.iss crea apuntando a este mismo .exe (Inno Setup
    # no necesita ningún ícono declarado aparte para el menú
    # inicio/escritorio si el .exe ya lo trae embebido). Ruta
    # relativa a la carpeta del proyecto — asistente-ia.ico debe
    # copiarse junto a main.py antes de empaquetar (mismo lugar que
    # requirements.txt).
    icon="asistente-ia.ico",
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
