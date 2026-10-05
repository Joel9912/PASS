# AGENTS.md — PAS.S (Planning & Astronomical Stacking Suite)

Proyecto en fase inicial: existe `main.py` (ventana con 6 pestañas), carpetas de código con sus `README.md` y esta documentación. `planners/` está implementado con catálogo real (OpenNGC + HYG + LDN); también `ui/planner_tab/` (4 subpestañas), `ui/equipment_tab/` (Equipos y Ubicaciones), `equipment/` (CRUD + validaciones), `db/` y el diálogo de Configuración. Son stubs (`NotImplementedError` a propósito) las otras 4 pestañas, `stacks/` y `planetary/`.
Sin CI: la verificación es `pytest` (la suite de `tests/`; el recuento vive en su README) + `ruff check` (lint, sin configuración propia). Sí hay migraciones de esquema (`_MIGRATIONS` en `db/connection.py`).

## Qué leer según la tarea

| Tarea | Leer primero |
|---|---|
| Primera vez en la sesión / cualquier tarea | Este archivo → `PROGRAM.md` |
| Auditoría o fix con test de regresión | Skills `@auditoria-pas` (método) y `@verificacion-fix` (revert-verify) |
| Crear o modificar una carpeta/pestaña | `STRUCTURE.md` + el `README.md` de la carpeta afectada |
| Saber el estado general, prioridades o roadmap | `MEMORY.md` |
| Cambiar arquitectura o estructura de carpetas | `STRUCTURE.md` (y actualizarlo en la misma tarea) |
| Entender por qué existe el programa o cada pestaña | `PROGRAM.md` |

## Convención: un solo `README.md` por carpeta

Toda carpeta con código (p. ej. `ui/<pestaña>/`, `planners/`) tiene su propio `README.md` con estas 4 secciones fijas:

```markdown
# <nombre carpeta>
## Qué es              → propósito de la carpeta y nada más (evita mezclar responsabilidades)
## Estado actual        → archivos existentes y qué hacen hoy
## Qué hacer aquí       → tareas típicas en esta carpeta y reglas concretas aplicables
## Planes futuros       → próximas funcionalidades previstas
```

- Crear el `README.md` **en la misma tarea** en que se crea la carpeta.
- Actualizar la sección "Estado actual" **en la misma tarea** en que se modifique la carpeta.
- Un solo archivo por carpeta: no separar contexto/estado/planes en archivos distintos.
- **Fuente única (R2)**: un dato global (recuento de tests, totales de catálogo) solo en su fichero dueño (`tests/README.md`, `planners/README.md`); los demás docs no repiten cifras.
- **Brevedad y poda (R3)**: 5 palabras si bastan; nada obsoleto — lo completado se quita de los planes (la historia es git).

## Reglas duras del proyecto
- **Prohibido** implementar motor propio de calibrado/apilado: solo integrar **SirIL** como herramienta externa (CLI).
- Prioridad: planificación de sesiones y planificación/comparativa de equipo; planetario y apilador son añadidos secundarios.
- Las métricas de comparación de equipo las define el usuario; nunca imponer valores por defecto como verdad.
- Mantener separación entre UI (`ui/`) y lógica backend (`planners/`, `stacks/`, etc.).
- Documentación en español: todos los `.md` del proyecto se escriben en español.
- Docstrings en código (en español): toda clase, función y módulo explica **qué hace y por qué**; `Args/Returns` solo si la firma no basta. Comentarios `#` inline solo donde la lógica no se entienda sola. `ruff check` vigila los docstrings (D100-D104).
- Para cambios estructurales o decisiones ambiguas: proponer al usuario en lugar de imponer.
- **Al terminar una tarea con cambios que verificar**: lanzar la aplicación (`python main.py`, en segundo plano) para que el usuario la revise; si la tarea no tiene cambios visibles (p. ej. solo backend/tests), no hace falta.

## Entorno
- Windows + PowerShell; `.venv/` con Python 3.12.
  - Activar: `.venv\Scripts\Activate.ps1` → ejecutar: `python main.py` (ventana con 6 pestañas).
  - Tests: `pytest` (desde la raíz, con el venv activado); si la salida de PowerShell muestra acentos rotos (mojibake), ejecutar `python -X utf8 -m pytest -q` o `$env:PYTHONUTF8=1`.
- Instalado en el venv: **PyQt6** 6.11 (no PySide), astropy 8.0, numpy 2.5, PyYAML 6.0, pytest, ruff.
- Manifest: `requirements.txt` — si añades una dependencia, actualizarlo (con la versión exacta del venv).
