"""
Punto de entrada de compatibilidad: reexporta todo de
acciones_sistema.py y acciones_apps.py, que es donde realmente vive
el código ahora.

FIX: este archivo originalmente tenía 1300+ líneas mezclando temas
muy distintos (apps/ventanas de Windows, startup, recordatorios,
temporizadores) — costoso de navegar y mantener a ese tamaño. Se
dividió en dos módulos temáticos, pero tools.py (y potencialmente
otro código futuro) hace `from acciones import *`, así que este
archivo se deja como fachada para que NINGÚN import existente se
rompa por la reorganización — todo lo que antes vivía en
`acciones.py` sigue siendo accesible exactamente igual desde acá.

Si necesitas AGREGAR código nuevo de acciones, ponlo directamente en
acciones_sistema.py (datos propios del asistente: recordatorios,
temporizadores, startup) o acciones_apps.py (apps/ventanas de
Windows) según corresponda — no en este archivo.
"""

from acciones_sistema import *
from acciones_apps import *