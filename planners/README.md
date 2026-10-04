# planners/

## Qué es
Lógica de planificación de PAS.S: catálogo, búsqueda, tránsito/luna/noche, ranking, encuadre/FOV, plan de captura y gestión del catálogo personal y de sesiones.

## Estado actual
Todo implementado; la suite de `tests/` es la verificación disponible.

### Catálogo y búsqueda
- `catalog_loader.py` — descarga y carga en SQLite: OpenNGC (`NGC.csv` + `addendum.csv`, ~13 372 objetos NGC/IC/Messier/Barnard/Caldwell), HYG (estrellas con magnitud ≤ 8, ~41 487) y **LDN** desde VizieR (`VII/7A/ldn`, **1 787** nebulosas oscuras). Ficheros en `data/downloads/`; refresco (DELETE+INSERT) con **`rollback` si algo falla a medias**. `ensure_catalog()` lo ejecuta `main.py` con las tablas vacías (sin red: aviso y sigue); manual: `python -m planners.catalog_loader [--force]`.
- `celestial_search.py` — `search(SearchFilters, limit)` con SQL sobre `catalog`: cross-reference (M31 = NGC 224), magnitud (desconocidas al final), grupos de tipo (`TYPE_GROUPS`), ventana RA/Dec, búsqueda libre y constelación. `get_object()`, `list_constellations()`. Anota `max_altitude`, `transit_local` (HH:MM) y `hours_above_30` si hay latitud. Con `SearchFilters.utc_offset_hours`, `transit_local` es hora de reloj.
- `sky_loader.py` — `load_stars()`/`load_objects()`: lo que pinta el planetario (41 487 estrellas + 15 159 objetos). RA en horas → grados, magnitud NULL → 99, sin coordenadas fuera. Vive aquí por la regla «sin SQL en la interfaz».

### Tránsito, luna y noche
- `transit.py` — **astropy con IERS offline**. **Malla de 1 min** (`SAMPLE_MIN`): una sola serie de instantes alimenta gráfica y ventanas, así que los rangos de Captura Ideal/Posible salen a minuto exacto (21:22 y 3h 32min) y los bordes de las bandas casan con el texto.
  - **Optimizaciones de `night_curve`** (medidas en la máquina de desarrollo, 961 muestras, antes → después):

    | Escenario | Antes | Después |
    |---|---|---|
    | Cambio de objeto (misma noche) | 844 ms | **107 ms** |
    | Fecha o ubicación nueva | 844 ms | **266 ms** |

    Tres palancas, ninguna toca la física de forma apreciable:
    1. **Caché de Luna/sol** (`_MOON_SUN_CACHE`, en memoria, acotada a 8 entradas y con candado): dependen de (fecha, ubicación, desfase), **no del objeto**; al cambiar de objetivo solo se transforma el objeto. `_remember_moon_sun` descarta la entrada más vieja.
    2. **Luna/sol a paso grueso + interpolación** (`MOON_SUN_SAMPLE_MIN = 5`, `_moon_sun_series`): la parte más cara (efemérides, ~0,62 s) se calcula cada 5 min y se interpola a la malla de 1 min **en coordenadas rectangulares** — nunca en azimut+altitud, que da vueltas de 180° en el cenit. Error: 0,009° de altitud lunar, 0,006° de separación y **bordes de noche idénticos**.
    3. **`Time` vectorizado**: `times.iso`/`times.mjd` en vez de `str(t.iso)`/`t.mjd` ~1000 veces (0,12 s en el perfil); salida idéntica bit a bit.
  - **Paralelización descartada (medida)**: `ThreadPoolExecutor` no acelera — `luna+sol` dio 636 ms sin hilos y 642 ms con 6, astropy no suelta el GIL en `get_body("moon")`. No reintentar sin cambiar de enfoque.
  - `night_info()` → horas de noche astronómica (sol < −18°), `astronomical_dusk/dawn` (**tramo continuo más largo**: con el huso guardado la ventana puede abarcar dos noches), `sunset`/`sunrise`, `moon_illumination`, `moon_age_days` y `waxing` (luna nueva JD 2451550.26). Acepta `utc_offset_hours` (M-07) y reutiliza `_MOON_SUN_CACHE` si `night_curve` ya corrió esa noche (M-09).
  - `night_curve()` → `NightCurve` con `hours_local`, `altitudes`, `moon_altitudes`, `moon_separations`, `astro_night` y `transit_index`: **fuente única** de gráfica y ventanas.
  - `transit_info()` → culminación y curva. Todo en UTC; el eje horario sale de `local_utc_offset`.
- `analytical_transit.py` — **sin astropy**, rápido para tablas de 500 filas: `max_altitude`, `is_circumpolar`, `never_rises`, `gmst_0h_hours`, `transit_utc_hours`, `transit_local_hours`, `hours_above_altitude`.
  - **`local_utc_offset(longitude, utc_offset_hours)`** — única fuente de UTC → hora local: desfase guardado de la ubicación o, si no hay, huso **inferido de la longitud** (`round(lon/15)`); **nunca la hora del sistema** (con huso ajeno la noche sale invertida). Reexportado por `transit.py`.
- `moon_distance.py` — umbral `min_moon_distance(illumination_pct)` (polinomio de grado 3 ajustado a datos reales), `classify_instant`, `capture_windows`, `capture_window_summary` (totales + rangos) y `format_hour_range`.
  - **Regla de la Luna bajo el horizonte**: `classify_instant`/`capture_windows` reciben la altitud lunar; con la Luna hundida (≤ 0°) no contamina y la separación se da por cumplida — solo manda la altitud del objeto; con la Luna asomando (> 0°) vige el umbral. Si no, un objeto visible quedaba bloqueado contra una Luna invisible.
  - **Sin banda de transición**: la banda ±2° probada abría una condición nueva por caso y crecía sin control; retirada. La curva pinta solo noche, Ideal y Posible.
  - `unwrap_hours()` desenvuelve la medianoche dentro de `capture_window_summary` (sin eso, una ventana Ideal que cruza las 00:00 se perdería).
- `framing.py` — `calculate_fov(setup)` → FOV en grados desde focal + píxel + resolución; `None` si faltan datos (la UI no activa el encuadre). `_resolution_px` parsea `camera_resolution` ("6048x4032") de respaldo.
- `capture_plan.py` — `best_dates(...)`: ranking de fechas (malla gruesa 30 días ≈ 1,5-2 s) y, para el top N, ventanas con `utc_offset_hours` para rangos en hora de reloj. El factor «Altura» puntúa con **`night_altitude_deg` — la altura máxima de ESA noche dentro de su ventana** (la culminación si cae dentro, si no el mejor extremo; D-2/M-11: la culminación es igual en las 30 noches y no reordenaba nada); la tabla la muestra como «Alt. noche».
- `ranking.py` — `rank_objects()` ordena candidatos 0-100 con `reasons` en castellano. `RankingWeights` es **del usuario**; sin clima su peso se renormaliza.

### Datos del usuario y clima
- `personal_catalog.py` — CRUD con LEFT JOIN a `catalog`; admite **regiones de interés** (`kind='region'`) que no se pintan en el planetario.
- `planned_sessions.py` — CRUD de sesiones (`add`, `update_session(**params)`, `mark_completed`, `delete_session`, `list_sessions`).
- `weather/` — `ClearOutside` (clima) y `Meteoblue` (seeing) con mocks: sin API key devuelven `available=False` con `note` y **nunca lanzan**. Exportados por `planners.weather`.

## Qué hacer aquí
- Aquí SOLO lógica de planificación pura: **sin PyQt6 ni imports de UI**.
- Los pesos/métricas del ranking y del plan de captura los define el usuario; no imponer valores por defecto como verdad.
- Toda conversión UTC → hora local pasa por `analytical_transit.local_utc_offset`; no duplicar la fórmula en otro sitio.
- Al añadir un filtro o métrica: documentarlo aquí mismo.
- Integraciones de clima: respetar la interfaz `WeatherProvider` y el modo mock sin keys.
- Códigos de tipo OpenNGC (guía oficial): `*` estrella, `**` doble, `*Ass` asoc., `OCl` cúmulo abierto, `GCl` cúmulo globular, `Cl+N` cúmulo+nebulosa, `G`/`GPair`/`GTrpl`/`GGroup` galaxias, `PN` nebulosa planetaria, `HII` región HII, `DrkN` nebulosa oscura, `EmN` emisión, `Neb` nebulosa, `RfN` reflexión, `SNR` resto de SN, `Nova`; `NonEx`/`Dup` se excluyen del cargador.
- Parseo de nombres de OpenNGC: `NGC`+4 dígitos, `IC`+4 dígitos, con sufijos de componente (`IC0186A` → `IC 186A`); ojo al prefijo IC de 2 caracteres.

## Planes futuros
1. Llamadas reales a Clear Outside y Meteoblue cuando el usuario añada API keys (la UI ya las consume).
2. Ranking de objetos en la UI de Planificación con controles para `RankingWeights`.
3. Pesos de `CaptureWeights` expuestos en la UI.
4. Completar el CRUD pendiente de `equipment/` que consume esta lógica (`manager.create/update/delete`).
5. **Bajos de la auditoría de código** (refactors sin cambio de comportamiento): formateador `HH:MM` copiado ×4; literal `10.0` en `_moon_score` en vez de `POSSIBLE_MOON_MARGIN`; motor de puntuación duplicado (`capture_plan` vs `ranking`); utilidades duplicadas en `catalog_loader`/`ldn_loader` (`CACHE_DIR`, `_USER_AGENT`, `_float_or_none`); `hours_above_30` recalculado cada noche en el bucle de 30 (es constante); `moon_phase`/`moon_illumination`, el mismo número en dos campos; `min_separation_moon_deg` → `0.0` indistinguible de «0°»; sin llamantes: `window_hours`, `list_constellations`, `ldn_count`, `WEATHER_FACTORS`, `fov_to_arcmin`, `calculate_mosaic_extent`.
