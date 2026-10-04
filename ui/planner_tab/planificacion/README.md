# ui/planner_tab/planificacion/ — Subpestaña Planificación

## Qué es
El corazón de la subpestaña: mirar el target en el planetario, ajustar el encuadre, ver la ventana nocturna, calcular el plan de captura y guardar la sesión.

## Estado actual
- `tab.py` — `PlanificacionTab` (antes `ui/planner_tab/planificacion.py`; el módulo es `tab.py` dentro de esta carpeta). Señales `session_saved` (→ Sesiones recarga) y `target_changed`.
- `planetario_visual.py` — `PlanetarioVisual`: lienzo de cielo con QPainter (proyección gnomónica, norte arriba, 41 487 estrellas y 15 159 objetos; zoom con rueda y arrastre). Los datos los carga `planners/sky_loader` (**sin SQL en esta UI**). Expone `set_target`, `set_center`, `set_framing`, `clear_framing`, `view`, `reset_view` y las señales `object_clicked`, `region_clicked`, `view_changed`. Vive en esta carpeta porque solo lo usa Planificación; más adelante será la base de la pestaña Planetario.
- Compartidos de `../widgets.py`: `TransitCurve` y `window_lines`.
- Datos vía `planners/`: `night_curve`, `best_dates` (30 noches → top 5), `framing.calculate_fov` (si faltan focal/resolución/píxel **no se activa el encuadre** y lo dice), `planned_sessions`, `personal_catalog` y `equipment.manager.list_setups` (combo «Equipo»).
- Cursor de espera en «Calcular plan» (~1,5 s por cálculo) y **botón desactivado mientras calcula** (sin reentrada: el `processEvents` ya no admite un segundo clic, M-08).
- Combos de target y equipo se repoblan con señales bloqueadas: `_on_target_changed` corre **una sola vez** por recarga (M-04) y el equipo se reselecciona **por id**, no se salta al primero (M-19).

### Esquema actual (estado HOY — ver «Planes futuros» para el rediseño aprobado)

```
┌ Target [combo] ──── Fecha [date] ──── Equipo [combo] ───────────┐
├───────────────────────────────────┬─────────────────────────────┤
│ Visual del planetario [Reset vista]│ Curva de tránsito          │
│ ┌───────────────────────────────┐ │  (objeto azul · Luna gris · │
│ │      PlanetarioVisual         │ │   noche/Ideal/Possible)     │
│ │  clic → target · rueda zoom   │ ├─────────────────────────────┤
│ │  arrastre sigue al cursor     │ │ Plan de captura             │
│ └───────────────────────────────┘ │  [Calcular plan]            │
│ ┌─ Editor de encuadre ──────────┐ │  tabla de noches (top 5) +  │
│ │ RA · Dec · FOV · teselas ×/×  │ │  rangos de ventana          │
│ │ [Actualizar desde planetario] │ ├─────────────────────────────┤
│ └───────────────────────────────┘ │ Parámetros de sesión        │
│                                   │ nombre · fecha · equipo ·   │
│   (QSplitter: columna izquierda)  │ exposición · notas          │
│                                   │ [💾 Guardar sesión]         │
│                                   │   (columna derecha)         │
└───────────────────────────────────┴─────────────────────────────┘
```

## Qué hacer aquí
- **Clic en el planetario** → cambia el target solo si el objeto está en el Catálogo Personal.
- **Encuadre** desde el equipo seleccionado (`planners/framing.calculate_fov`); sin datos de la cámara, el editor lo indica y no se activa.
- **La región no aparece en el planetario**: aquí solo como encuadre de referencia.
- Una sola conversación UTC → hora local: `planners.analytical_transit.local_utc_offset`.
- «💾 Guardar sesión» escribe con `planners.planned_sessions` y avisa a Sesiones por señal (`session_saved`).

## Planes futuros
1. **Rediseño aprobado y pendiente** (especificación completa en
   `C:\Users\Usuario\.opencode\plan\plan-rediseno-planificacion.md`):
   izquierda = «Encuadre de sesión» (planetario con **FOV lectura + switch
   teselas**) y la **curva de tránsito debajo**; derecha = **Plan de captura
   amplio con opciones propias** (integración por tesela o total, slider de
   horas del usuario, suelo/obstrucciones, altura mínima 30° configurable,
   rango de fechas, multi-objeto, reparto por filtros); al pie de la derecha,
   **«Parámetros de Sesión» como consolidador** (nombre, datos y «Guardar plan»
   → borrador o plan creado). **Se elimina el «Editor de encuadre» actual.**
   Quedan 3 pendientes en su §7 (suelo dónde se guarda, tabla de planes,
   relación con `best_dates`).
2. Ranking de objetos en esta subpestaña con pesos editables (`planners/ranking.py`).
3. Editor de encuadre con mosaicos y vista previa de teselas reales.
4. i18n de todos los textos (`i18n/es.ts`, `i18n/en.ts`).
5. **Pintura del planetario (M-06, medido en la auditoría)**: `paintEvent` proyecta las 56k figuras en cada repinto → **48-55 ms/pintada (≈20 fps máx. durante el arrastre)**. Cachear la capa en `QPixmap`, invalidada solo con cambio de vista/zoom; `_find_object_index` (0,55 ms) no es el cuello de botella y puede quedarse como está.
