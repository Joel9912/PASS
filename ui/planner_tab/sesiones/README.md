# ui/planner_tab/sesiones/ — Subpestaña Sesiones Planificadas

## Qué es
Las sesiones ya concretadas: la tabla de lo que el usuario guardó desde Planificación y su edición. La pestaña Resumen la leerá para saber en qué sesión está el usuario.

## Estado actual
- `tab.py` — `SesionesTab` (antes `ui/planner_tab/sesiones.py`; el módulo es `tab.py` dentro de esta carpeta). Señal `sessions_changed` (una sesión cambió → Resumen se entera en el futuro).
- Tabla de 7 columnas: `#`, Nombre, Target, Fecha, Equipo, Exp, Estado — con colores por estado (`STATUS_COLORS`: planificada azul, completada verde).
- Botones: **Editar** (abre `EditSessionDialog`: nombre, fecha, equipo, exposición, teselas ×/×, notas), **Marcar completada** y **Eliminar** (con confirmación).
- `refresh()` relee la tabla y renueva `_setup_names()` (id → nombre de `equipment.manager.list_setups()`): por eso las sesiones muestran el nombre del equipo aunque se haya editado después.
- Datos vía `planners.planned_sessions` (`add`, `update_session`, `mark_completed`, `delete_session`, `list_sessions`).

### Esquema actual

```
┌──────────────────────────────────────────────────────────────┐
│ Sesiones planificadas                        3 sesiones      │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │ # │ Nombre │ Target │ Fecha │ Equipo │ Exp │ Estado      │ │
│ │ 1 │ …      │ M31    │ …     │ …      │ …   │ planificada │ │
│ │        (una fila por sesión guardada)                    │ │
│ └──────────────────────────────────────────────────────────┘ │
│            [Editar] [Marcar completada] [Eliminar]          │
└──────────────────────────────────────────────────────────────┘
   Editar → EditSessionDialog
   ┌──────────────────────────────────────┐
   │ Nombre · Fecha · Equipo [combo]      │
   │ Exposición (s) · Teselas × × · Notas │
   │              [Guardar] [Cancelar]    │
   └──────────────────────────────────────┘
   Llega nueva sesión por señal session_saved (Planificación →
   PlannerPage → refresh()); esta carpeta no importa otras
   subpestañas.
```

## Qué hacer aquí
- CRUD exclusivamente vía `planners/planned_sessions` — sin SQL directo.
- El combo «Equipo» del diálogo sale de `equipment.manager.list_setups()`; sin setups muestra «(sin equipo)».
- Estados: `planificada` → `completada` (marcar) y borrado con confirmación.

## Planes futuros
1. Refiltro y búsqueda en la tabla (por fecha, estado, objeto).
2. Exportar una sesión (CSV/JSON) para llevarla a campo.
3. i18n de los textos (`i18n/es.ts`, `i18n/en.ts`).
