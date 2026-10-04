# planners/

## Qué es
Lógica de planificación de PAS.S: catálogo de objetos, búsqueda, tránsito/luna/noche astronómica, ranking de recomendaciones, encuadre/FOV, plan de captura y gestión de catálogo personal y sesiones planificadas.

## Estado actual
Todo implementado; **142 tests** en `tests/` son la verificación disponible.

### Catálogo y búsqueda
- `catalog_loader.py` — descarga y carga en SQLite: OpenNGC (`NGC.csv` + `addendum.csv`, ~13 372 objetos NGC/IC/Messier/Barnard/Caldwell), HYG (estrellas con magnitud ≤ 8, ~41 487) y **LDN** desde VizieR (`VII/7A/ldn`, **1 787** nebulosas oscuras). Ficheros cacheados en `data/downloads/`; refresco completo (DELETE+INSERT) y **`rollback` si algo falla a medias** (sin él, el próximo commit de otro módulo consignaba el borrado y el catálogo quedaba vacío). `ensure_catalog()` lo ejecuta `main.py` si las tablas están vacías (sin red: aviso y sigue); manual: `python -m planners.catalog_loader [--force]`.
- `celestial_search.py` — `search(SearchFilters, limit)` con SQL sobre `catalog`: catálogo por cross-reference (M31 = NGC 224), magnitud (las desconocidas van al final), grupos de tipo (`TYPE_GROUPS`), ventana RA/Dec, búsqueda libre y constelación. `get_object()`, `list_constellations()`. Anota en cada fila `max_altitude`, `transit_local` (HH:MM) y `hours_above_30` cuando hay latitud. `SearchFilters.utc_offset_hours` hace que esa columna sea hora de reloj y no solar.
- `sky_loader.py` — `load_stars()`/`load_objects()`: los datos que pinta el planetario visual (41 487 estrellas + 15 159 objetos). RA en horas → grados, magnitud NULL → 99, objetos sin coordenadas fuera. Vive aquí (no en `ui/`) por la regla «sin SQL en la interfaz».

### Tránsito, luna y noche
- `transit.py` — **astropy con IERS offline**. **Malla de 1 min** (`SAMPLE_MIN`): la misma serie de instantes alimenta la gráfica y las ventanas, así que los rangos de Captura Ideal/Posible salen a minuto exacto (21:22 y 3h 32min, no 21:20 y 3h 30min) y los bordes de las bandas casan con el texto. Subir el paso era solo más rápido (~0,1 s vs ~0,5 s) pero cuantizaba las horas visibles.
  - **Optimizaciones de `night_curve`** (medidas en la máquina de desarrollo, 961 muestras, antes → después):

    | Escenario | Antes | Después |
    |---|---|---|
    | Cambio de objeto (misma noche) | 844 ms | **107 ms** |
    | Fecha o ubicación nueva | 844 ms | **266 ms** |

    Tres palancas, ninguna toca la física de forma apreciable:
    1. **Caché de Luna/sol** (`_MOON_SUN_CACHE`, en memoria, acotada a 8 entradas y con candado): dependen de (fecha, ubicación, desfase) y **no del objeto**, así que al cambiar de objetivo solo se transforma el objeto. `_remember_moon_sun` descarta la entrada más vieja.
    2. **Luna/sol a paso grueso + interpolación** (`MOON_SUN_SAMPLE_MIN = 5`, `_moon_sun_series`): la parte más cara (efemérides, ~0,62 s) se calcula cada 5 min y se interpola a la malla de 1 min **en coordenadas rectangulares** — nunca en azimut+altitud, que da vueltas de 180° al pasar por el cenit. Error medido: 0,009° de altitud lunar, 0,006° de separación y **bordes de noche idénticos** (los umbrales se manejan en grados, así que no llega a notarse).
    3. **`Time` vectorizado**: `times.iso` y `times.mjd` en vez de `str(t.iso)`/`t.mjd` ~1000 veces (medido: 0,12 s en el perfil). Verificado bit a bit que la salida es idéntica.
  - **Paralelización descartada (medida)**: se probaron hilos con `ThreadPoolExecutor` y **no acelera** — `luna+sol` dio 636 ms sin hilos y 642 ms con 6: astropy no suelta el GIL dentro de `get_body("moon")`, luego los hilos se serializan. No volver a intentarlo sin cambiar de enfoque (procesos con `spawn` en Windows cuesta más que el propio cálculo). `night_info()` → horas de noche astronómica (sol < −18°), `astronomical_dusk/dawn` (el **tramo continuo más largo**: con el huso guardado la ventana puede contener dos noches y el día entre medias no cuenta como noche), `sunset`/`sunrise`, `moon_illumination`, `moon_age_days` y `waxing` (edad lunar desde la luna nueva JD 2451550.26). **Acepta `utc_offset_hours`** (M-07): la ventana se centra con el huso guardado igual que `night_curve`, y si la curva ya calculó esa noche, la iluminación lunar se reutiliza de `_MOON_SUN_CACHE` (M-09). `night_curve()` → `NightCurve` con `hours_local`, `altitudes`, **`moon_altitudes`** (altitud de la Luna para dibujar su curva), `moon_separations`, `astro_night` e `transit_index`: **fuente única** para la gráfica y para las ventanas. `transit_info()` → culminación y curva. Todo el cálculo en UTC; el eje horario sale de `local_utc_offset`.
- `analytical_transit.py` — **sin astropy**, rápido para tablas de 500 filas: `max_altitude`, `is_circumpolar`, `never_rises`, `gmst_0h_hours`, `transit_utc_hours`, `transit_local_hours`, `hours_above_altitude`.
  - **`local_utc_offset(longitude, utc_offset_hours)`** — única fuente de verdad para pasar de UTC a hora local: usa el desfase guardado de la ubicación (hora de reloj) o, si no hay, el huso **inferido de la longitud** (`round(lon/15)`). Nunca la hora del sistema: con un huso de otro continente la noche salía «invertida» (el usuario lo detectó con lon +85.4 y huso −6). Reexportado por `transit.py`.
- `moon_distance.py` — umbral `min_moon_distance(illumination_pct)` (polinomio de grado 3 ajustado a datos reales), `classify_instant`, `capture_windows`, `capture_window_summary` (horas totales + rangos por ventana) y `format_hour_range`.
  - **Regla de la Luna bajo el horizonte**: `classify_instant`/`capture_windows` reciben la altitud lunar; con la Luna hundida (≤ 0°) no contamina y la separación se da por cumplida — solo manda la altitud del objeto. En cuanto la Luna asoma (> 0°) vige el umbral. Sin esa regla un objeto a tiro quedaba bloqueado por una separación calculada contra una Luna invisible (caso M31 del 02/10/2026: la Posible no arrancaba hasta las 22:20 en vez de al cruzar los 30°).
  - **Sin banda de transición**: se probó una banda ±2° que marcara dónde se pasa de Posible a Ideal, pero cada caso de prueba abría una condición nueva (altura, umbral lunar, noche) y la lógica crecía sin control. Se retiró; la curva pinta solo noche, Ideal y Posible.
  - `unwrap_hours()` desenvuelve la medianoche **dentro** de `capture_window_summary`: sin eso, una ventana Ideal que cruza las 00:00 se perdía entera.
- `framing.py` — `calculate_fov(setup)` → FOV en grados desde focal + píxel + resolución. Si faltan datos devuelve `None` (la UI no activa el encuadre) y `_resolution_px` parsea `camera_resolution` ("6048x4032") como respaldo.
- `capture_plan.py` — `best_dates(...)`: ranking de fechas (malla gruesa 30 días ≈ 1,5-2 s) y, para el top N, ventanas de captura con `utc_offset_hours` para que los rangos sean hora de reloj. El factor «Altura» puntúa con **`night_altitude_deg` — la altura máxima de ESA noche dentro de su ventana** (la culminación si cae dentro del crepúsculo-alba; si no, el mejor extremo, vía `analytical_transit.altitude_at_utc`): la culminación es idéntica en las 30 noches y su peso no llegaba a reordenar nada (decisión D-2 / M-11). La tabla del plan muestra esa columna como «Alt. noche».
- `ranking.py` — `rank_objects()` ordena candidatos 0-100 con `reasons` en castellano. `RankingWeights` es **del usuario**: sin clima su peso se renormaliza.

### Datos del usuario y clima
- `personal_catalog.py` — CRUD con LEFT JOIN a `catalog`; admite **regiones de interés** (`kind='region'`) que no se pintan en el planetario.
- `planned_sessions.py` — CRUD de sesiones (`add`, `update_session(**params)`, `mark_completed`, `delete_session`, `list_sessions`).
- `weather/` — `ClearOutside` (clima) y `Meteoblue` (seeing) con mocks: sin API key devuelven `available=False` con `note`, **nunca lanzan excepción**. Exportados por `planners.weather`.

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
5. **Bajos de la auditoría de código** (refactors pequeños, sin cambio de comportamiento): 4 copias del formateador `HH:MM`; `_moon_score` con literal `10.0` en vez de `POSSIBLE_MOON_MARGIN`; motor de puntuación duplicado (`capture_plan` vs `ranking`) y `.total` sin llamantes; utilidades duplicadas entre `catalog_loader`/`ldn_loader` (`CACHE_DIR`, `_USER_AGENT`, `_float_or_none`); `hours_above_30` recalculado dentro del bucle de 30 noches (es constante; `transit_utc` ya se reutiliza); `NightInfo.moon_phase`/`moon_illumination` son el mismo número en dos campos; `min_separation_moon_deg` devuelve `0.0` cuando el objeto nunca sube (indistinguible de «0°»); sin llamantes: `window_hours`, `list_constellations`, `ldn_count`, `WEATHER_FACTORS`, `fov_to_arcmin`, `calculate_mosaic_extent`.
