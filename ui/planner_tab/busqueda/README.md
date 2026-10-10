# ui/planner_tab/busqueda/ — Subpestaña Búsqueda

## Qué es
Primer paso del flujo de PASS: filtrar el catálogo (OpenNGC + HYG + LDN) y ver, al seleccionar un objeto, sus efemérides del día y su curva de tránsito. Aquí vive también la `LocationBar`, única fuente de verdad de latitud, longitud y desfase horario para las 4 subpestañas.

## Estado actual
- `tab.py` — `BusquedaTab`. Señales `object_selected` (objeto elegido en la tabla) y `add_to_personal` (botón «⭐ Añadir a Mi Lista», escribe en Catálogo Personal desde `PlannerPage`, nunca directo en la base).
- Constantes y helpers propios: `COLUMNS` (10 columnas), `MAGNITUDE_OPTIONS`, `ALTITUDE_OPTIONS`, `_constellation_label`, `_number`. `CATALOG_LABELS` es **compartido de `../widgets.py`**.
- El formato de datos compartido (`format_ra/dec/size`, `_type_label`, `TYPE_LABELS`) vive en `../widgets.py` (también lo usa Catálogo Personal): así ninguna subpestaña importa de otra.
- Compartidos de `../widgets.py`: `LocationBar`, `EphemerisPanel` (+ `DayNightBar`), `TransitCurve`, `WeatherCards`.
- Rejilla 3×2 repartida 3:3:1; tabla con celdas centradas, filas a 42 px y ancho sobrante proporcional (`_spread_surplus`).
- `refresh()` corre la **búsqueda siempre**, pero efemérides, curva y clima **se saltan si su clave no cambió** (objeto/noche/ubicación/huso; M-01 de la auditoría): cambiar solo un filtro o pulsar Enter dos veces ya no repite ~1,1 s de astropy. `refresh_weather()` (API keys guardadas) fuerza el recálculo.

### Esquema actual (a 1280×800: filas 309 / 309 / 103 px)

```
┌────────────────────────┬──────────────────────────────────────┐
│ Filtros                │ Catálogo                             │
│ buscar · tipo ·        │ #│ID│Tipo│Constelación│Mag│RA│Dec│   │
│ catálogo ·             │ Tránsito│Horas >30°   (10 columnas,  │
│ constelación · mag ·   │ centradas, filas 42 px)              │
│ altitud · orden        │                    [⭐ Añadir a Mi   │
│      [Aplicar filtros] │                         Lista]       │
│ fila 0 · mín 264 px    │ fila 0 (misma celda)                │
├────────────────────────┼──────────────────────────────────────┤
│ PUESTA DE SOL Y NOCHE  │ Curva de tránsito                   │
│ ASTRONÓMICA            │ ★ Captura Ideal · ⚠ Captura Posible │
│ fecha ◀ ▶ (Hoy) ·      │ altitud objeto (azul) · Luna (gris) │
│ LUNA fase+44% ·        │ bandas noche/Ideal/Possible ·       │
│ barra día/noche 44 px  │ eje = 1 h antes de la puesta →      │
│ (eje dinámico HH:MM)   │ 1 h después de la salida            │
│ Puesta: … · Noche: …   │                                      │
│ fila 1 · mín 237 px    │ fila 1 (misma celda)                │
├────────────────────────┼──────────────────────────────────────┤
│ 📍 Ubicación           │ Condiciones meteorológicas          │
│ combo guardadas/Manual │ 6 tarjetas clima/seeing (mock →     │
│ Lat ◀▶ · Lon ◀▶ ·      │ «Sin datos» hasta que haya API key) │
│ Huso Auto              │                                      │
│ fila 2 · mín 99 px     │ fila 2 (misma celda)                │
└────────────────────────┴──────────────────────────────────────┘
   + 2×8 px de spacing → mínimos 264/237/99 = 616 px
   Ventana mínima 1024×640 (577 px): filas 0-1 se comprimen sin recortes
```

## Qué hacer aquí
- Filtros → tabla vía `planners.celestial_search.search(SearchFilters, limit=500)`.
- Seleccionar fila → `planners.transit.night_curve` (malla de 1 min) alimenta curva y ventanas.
- Cambios de fecha/ubicación/objeto refrescan efemérides y curva sin mover el resto de la rejilla.
- `LocationBar` solo **selecciona** ubicación: crear o editarlas corresponde a la pestaña Equipo (decisión aprobada: sin botón «+» en Búsqueda).
- El cuadro de Efemérides **llena su celda** (`addWidget(panel, 1)`, aire interior 1/3/3) y su `DayNightBar` es de **altura fija 44 px**: si hay que dejar sitio, se lo llevan los rótulos, no la barra.
- La línea «★ Captura Ideal / ⚠ Captura Posible» de la curva se reserva con texto en blanco desde el arranque: ocultarla cambiaba el mínimo del panel (+21 px) y refluía la rejilla entera.
- Sin datos → `--` / «Sin datos»; nunca inventar valores.

## Planes futuros
1. APIs reales de clima/seeing (Clear Outside + Meteoblue) para las 6 tarjetas.
2. i18n de los textos (`i18n/es.ts`, `i18n/en.ts`).
