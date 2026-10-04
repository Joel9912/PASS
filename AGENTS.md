# AGENTS.md — PAS.S (Planning & Astronomical Stacking Suite)

Proyecto en fase inicial: existe `main.py` (ventana con 6 pestañas), carpetas de código con sus `README.md` y esta documentación. `planners/` está implementado con catálogo real (OpenNGC + HYG + LDN) y `ui/planner_tab/` con sus 4 subpestañas; el resto de módulos y pestañas aún son stubs (`NotImplementedError` a propósito).
No hay lint ni CI: `pytest` (136 tests en `tests/`) es la única verificación disponible. Sí hay migraciones de esquema (`_MIGRATIONS` en `db/connection.py`).

## Qué leer según la tarea

| Tarea | Leer primero |
|---|---|
| Primera vez en la sesión / cualquier tarea | Este archivo → `PROGRAM.md` |
| Crear o modificar una carpeta/pestaña | `STRUCTURE.md` + el `README.md` de la carpeta afectada |
| Saber el estado general, prioridades o roadmap | `MEMORY.md` |
| Cambiar arquitectura o convenciones | `STRUCTURE.md` (y actualizarlo en la misma tarea) |
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

## Reglas duras del proyecto
- **Prohibido** implementar motor propio de calibrado/apilado: solo integrar **SirIL** como herramienta externa (CLI).
- Prioridad: planificación de sesiones y planificación/comparativa de equipo; planetario y apilador son añadidos secundarios.
- Las métricas de comparación de equipo las define el usuario; nunca imponer valores por defecto como verdad.
- Mantener separación entre UI (`ui/`) y lógica backend (`planners/`, `stacks/`, etc.).
- Documentación en español: todos los `.md` del proyecto se escriben en español.
- Para cambios estructurales o decisiones ambiguas: proponer al usuario en lugar de imponer.
- **Al terminar una tarea con cambios que verificar**: lanzar la aplicación (`python main.py`, en segundo plano) para que el usuario la revise; si la tarea no tiene cambios visibles (p. ej. solo backend/tests), no hace falta.

## Entorno
- Windows + PowerShell; `.venv/` con Python 3.12.
  - Activar: `.venv\Scripts\Activate.ps1` → ejecutar: `python main.py` (ventana con 6 pestañas).
  - Tests: `pytest` (desde la raíz, con el venv activado).
- Instalado en el venv: **PyQt6** 6.11 (no PySide), astropy 8.0, numpy 2.5, PyYAML 6.0, pytest.
- Manifest: `requirements.txt` — si añades una dependencia, actualizarlo (con la versión exacta del venv).
