# =========================================================
# SCRIPT DE EMPAQUETADO LIMPIO — AsistenteIA
# Correr desde C:\AsistenteIA\archivos.py
# =========================================================

# 1. Limpiar builds anteriores de PyInstaller
Remove-Item dist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item build -Recurse -Force -ErrorAction SilentlyContinue

# 2. Activar el venv
..\venv\Scripts\activate

# 3. Instalar dependencias declaradas (no quita lo que sobra, solo
#    agrega/actualiza lo que falta — ver más abajo el porqué)
pip install -r requirements.txt

# 4. Empaquetar
pyinstaller asistente.spec --noconfirm

# 5. Probar
cd dist\AsistenteIA
.\AsistenteIA.exe
