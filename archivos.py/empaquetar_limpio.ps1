# =========================================================
# SCRIPT DE EMPAQUETADO LIMPIO (DESDE CERO) — AsistenteIA
# Correr desde C:\AsistenteIA\archivos.py
#
# A diferencia de simplemente reusar el venv existente, este script
# lo RECREA desde cero cada vez. Esto es importante porque
# "pip install -r requirements.txt" nunca QUITA paquetes que ya
# estén instalados pero no estén en el archivo — si alguna vez se
# instala algo de más en el venv (a propósito o por error, como pasó
# con openai-whisper/torch, que infló el .exe final a ~4GB sin que
# requirements.txt lo pidiera en ningún momento), ese paquete de más
# se queda ahí PARA SIEMPRE en cada empaquetado futuro, hasta que se
# lo desinstale a mano o se recree el venv.
#
# Recrear el venv antes de cada empaquetado para distribuir garantiza
# que el .exe final tiene EXACTAMENTE lo que requirements.txt declara,
# sin sorpresas de instalaciones previas que quedaron pegadas.
# =========================================================

# 1. Limpiar builds anteriores
# FIX: a veces el .exe queda bloqueado un instante por el antivirus
# (Windows Defender u otro) escaneándolo justo después de generarse
# — esto causa un PermissionError al intentar borrar la carpeta
# "dist" en la siguiente corrida, aunque ningún proceso del propio
# asistente esté corriendo. Se reintenta varias veces con una pausa
# corta entre intentos, en vez de fallar a la primera.
function Remove-ItemConReintentos($ruta) {
    $intentos = 5
    for ($i = 1; $i -le $intentos; $i++) {
        try {
            Remove-Item $ruta -Recurse -Force -ErrorAction Stop
            return
        } catch {
            if ($i -eq $intentos) {
                Write-Host "No se pudo borrar '$ruta' después de $intentos intentos. Cerrá cualquier antivirus/escaneo en curso y volvé a intentar." -ForegroundColor Yellow
                return
            }
            Start-Sleep -Seconds 2
        }
    }
}

Remove-ItemConReintentos "dist"
Remove-ItemConReintentos "build"

# 2. Borrar el venv viejo y crear uno nuevo y limpio
# FIX: "deactivate" no es un comando nativo de PowerShell — solo
# existe como función dentro de una sesión donde Activate.ps1 ya se
# corrió antes. Si la terminal es nueva y nunca se activó ningún
# venv, PowerShell no lo reconoce y tira un error de "comando no
# encontrado", que -ErrorAction SilentlyContinue NO atrapa (ese
# parámetro es para comandos válidos que fallan en tiempo de
# ejecución, no para comandos que no existen). Se envuelve en un
# bloque try/catch en su lugar, que sí captura cualquier tipo de
# error sin importar la causa.
try { deactivate } catch { }

Remove-Item ..\venv -Recurse -Force -ErrorAction SilentlyContinue
python -m venv ..\venv

# 3. Activar el venv nuevo (vacío, sin nada instalado todavía)
..\venv\Scripts\activate

# 4. Instalar EXACTAMENTE lo declarado en requirements.txt — como el
#    venv es nuevo, esto es lo ÚNICO que va a tener instalado, sin
#    posibilidad de arrastrar nada de pruebas anteriores
pip install -r requirements.txt

# 5. Empaquetar
pyinstaller asistente.spec --noconfirm

# 6. Probar (solo si el build generó el .exe correctamente)
$rutaExe = "dist\AsistenteIA\AsistenteIA.exe"

if (Test-Path $rutaExe) {
    cd dist\AsistenteIA
    .\AsistenteIA.exe
} else {
    Write-Host "El build no generó '$rutaExe'. Revisá los mensajes de pyinstaller más arriba para ver qué falló." -ForegroundColor Red
}