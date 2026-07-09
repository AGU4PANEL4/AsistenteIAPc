"""
Conftest de la RAÍZ del proyecto.

Este archivo va en la misma carpeta que main.py, session.py, etc.
(no dentro de tests/) — su único trabajo es asegurar que esa carpeta
esté en sys.path, para que los archivos de tests/ puedan hacer
`import session`, `import macros`, etc. sin importar desde dónde se
invoque `pytest`.

Por qué hace falta: el proyecto no es un paquete Python instalado
(no hay setup.py/pyproject con un paquete), es una carpeta de
scripts sueltos — así que sin esto, `import session` fallaría al
correr pytest desde otra carpeta, o con algunos runners de CI/editor
que no agregan el directorio actual a sys.path automáticamente.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
