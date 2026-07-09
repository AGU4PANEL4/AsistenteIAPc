# Tests automatizados — funciones puras

Cubre las funciones del proyecto que no dependen de micrófono, TTS,
Ollama/Groq, ni de una sesión real del asistente corriendo. Se
corren en segundos, sin necesitar nada más que Python + pytest.

## Cómo correrlos

```bash
pip install pytest requests
pytest
```

Corré `pytest` desde la carpeta raíz del proyecto (donde están
`main.py`, `session.py`, etc.) — `conftest.py` se encarga de que los
tests puedan importar esos módulos sueltos.

**Requiere Windows.** No es una limitación de los tests en sí, sino
del proyecto: varios módulos (`app_finder.py`, `startup.py`,
`main.py`) importan `winreg`/`ctypes.windll` o leen
`os.environ["LOCALAPPDATA"]` a nivel de módulo, y fallan al
importarse en Linux/Mac. `test_app_finder.py` se salta solo
(`pytest.importorskip`) si no puede importar `app_finder` — el resto
de la suite no tiene esa restricción, pero en la práctica todos
corren en la misma máquina de desarrollo (Windows).

## Qué se prueba

| Módulo | Funciones | Notas |
|---|---|---|
| `tiempo_utils.py` | `parsear_duracion` | 100% pura |
| `session.py` | `es_cancelacion`, `es_despedida` | 100% pura |
| `wakeword.py` | `detectar_wakeword`, `parecido` | 100% pura |
| `visual_utils.py` | `mezclar_hex` | 100% pura |
| `app_finder.py` | `limpiar_nombre`, `parecido` | 100% pura (se salta sin Windows) |
| `actualizador.py` | `_hay_version_nueva` | pura — no toca red ni disco |
| `voz_utils.py` | `es_afirmacion`, `es_negacion`, `elegir_de_lista`, `interpretar_confirmacion` | la rama de `interpretar_confirmacion` que llama a la IA queda **fuera** a propósito |
| `macros.py` | `obtener_macro`, `macro_existe`, `listar_macros` | estado real (`_macros`) reemplazado con `monkeypatch`, nunca toca `macros.json` |
| `aliases.py` | `traducir_alias`, `existe_alias`, `alias_por_app`, `listar_aliases` | mismo patrón — `aliases.aliases` reemplazado con `monkeypatch` |
| `memory.py` | `registrar_accion`, `obtener_historial`, `ultimo_de` | mismo patrón — `memory.memoria` reemplazado con `monkeypatch` |
| `no_molestar.py` | `modo_activo`, `tiempo_restante`, `registrar_aviso_diferido` | estado manipulado directo, sin lanzar el hilo real de expiración |

## Qué queda deliberadamente afuera

- **Voz/audio**: `voice.py`, `wakeword` en vivo, `cancelacion.py` — necesitan micrófono real.
- **TTS**: `tts.py` — necesita Edge TTS / red / pygame audio.
- **IA**: `ia.py`, `groq_cliente.py`, `gestor_ia.py` — necesitan Ollama corriendo o una API key de Groq válida. Si más adelante querés mockear esto (con `unittest.mock` o `responses` para las llamadas HTTP), es el siguiente paso lógico — avisame y armamos esa capa aparte.
- **Sistema de archivos real**: todo lo que lee/escribe `%LOCALAPPDATA%\AsistenteIA\*.json` de verdad (`recordatorios.py`, `temporizadores.py`, la persistencia de `aliases.py`/`macros.py`/`memory.py`). Se probó la LÓGICA de esos módulos contra estado en memoria: si querés además cubrir la parte de guardar/cargar de disco, esos tests usarían `tmp_path` de pytest para apuntar a una carpeta temporal en vez de la real — puedo armarlos como siguiente capa.
- **Windows real**: `startup.py` (tareas programadas, UAC), `bandeja.py` (pystray), `ui.py`/`splash.py` (Tkinter) — requieren el SO y una sesión gráfica.
- **Red real**: `_consultar_release`/`_descargar_exe` en `actualizador.py`, `verificacion.py` (instalar/iniciar Ollama) — necesitan GitHub/Ollama de verdad; son buenos candidatos para tests con `responses`/`unittest.mock` más adelante.
