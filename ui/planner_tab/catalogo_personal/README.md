# ui/planner_tab/catalogo_personal/ — Subpestaña Catálogo Personal

## Qué es
La lista de deseos del usuario: objetos guardados desde Búsqueda («⭐ Añadir a Mi Lista») y regiones de interés creadas aquí mismo. Es el puente hacia Planificación, que toma su target de esta tabla.

## Estado actual
- `tab.py` — `CatalogoPersonalTab`. Señales `target_selected` (fila elegida → Planificación cambia de target) y `region_added` (región nueva → `PlannerPage` recarga los targets de Planificación).
- Constantes propias: `COLUMNS` (9 columnas). `CATALOG_LABELS` (catálogo → etiqueta; `region` → «Región») es **compartido de `../widgets.py`**.
- Tabla de 9 columnas con las mismas cabeceras formateadas que Búsqueda: el formato (`format_ra/dec/size`, `_type_label`) vive en `../widgets.py` compartido — **no se importa de `busqueda/`**.
- Datos vía `planners.personal_catalog` (CRUD con LEFT JOIN al catálogo; admite `kind='region'`).
- Las regiones **no se pintan en el planetario** (decisión del usuario): solo sirven como encuadre de referencia en Planificación.

### Esquema actual

```
┌────────────────────────────────────────────────────────────┐
│ Objetos guardados y regiones              3 elementos      │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ # │ Nombre │ Tipo │ Catálogo │ Mag │ RA │ Dec │ Tamaño │ │
│ │   │        │      │          │     │    │     │ Notas  │ │
│ │        (tabla: los objetos guardados y las regiones)   │ │
│ └────────────────────────────────────────────────────────┘ │
│ [Quitar seleccionado]  [Editar notas]  [＋ Añadir región]  │
└────────────────────────────────────────────────────────────┘
   «＋ Añadir región» abre RegionDialog (nombre, caja RA/Dec)
   Seleccionar fila → target_selected → Planificación (cableado
   en PlannerPage, ui/main_window.py — esta carpeta no importa
   de otras subpestañas)
```

## Qué hacer aquí
- Añadir objetos: solo desde Búsqueda (este panel no escribe en el catálogo base).
- Regiones: se crean aquí con `RegionDialog` y se guardan con `planners.personal_catalog`.
- Editar notas y quitar filas: CRUD de `planners.personal_catalog`.
- Nunca SQL directo ni cálculos astronómicos: solo composición y formato.

## Planes futuros
1. Dibujar la región como referencia de encuadre en el panel izquierdo de Planificación.
2. Reordenar/filtrar la lista personal (por fecha guardada, por tipo).
3. i18n de los textos (`i18n/es.ts`, `i18n/en.ts`).
