# equipment/

## Qué es
Modelos y persistencia del equipo del usuario: setups (componentes globales + ubicación + categoría + filtros), las piezas globales (telescopios, cámaras, monturas, filtros), ubicaciones geográficas con su sitio (horizonte y CL) y las imágenes adjuntas.

## Estado actual
- `models.py` — dataclasses `Location`, `Telescope`, `Camera`, `Mount`, `Filter`, `EquipmentSetup` (solo campos comparables) y los catálogos de etiquetas: **`CATEGORIES`** (6 categorías, `general` por defecto — dueño de la etiqueta, R2), `OPTICAL_TYPES`, `SUBTYPE_SUGGESTIONS`, `MOUNT_TYPES`, `FILTER_TYPES`, `OBSTACLE_TYPES`, `LP_LEVELS` y `DIRECTIONS` (8).
- `validaciones.py` — todas las reglas de alto en un sitio: nombre obligatorio, rangos (Bortle 1-9, SQM ≥ 0, factor de reductor > 0…), 8 direcciones obligatorias y enums de catálogo; `ValueError` con mensaje en castellano. Las llaman `manager`/`localizations`/`components` antes de tocar la base.
- `manager.py` — CRUD completo de setups (`create`/`update`/`delete`/`get`/`list_setups`): lecturas como **dict** (el contrato de la UI, C-2), SELECT con JOIN a componentes y ubicación, alias de FOV (`telescope_focal_mm` = **focal efectiva**, `camera_*`), `get()` expone también `filter_ids`, sincroniza `setup.images` (D-5) y `setup_filters`, y `count_sessions`/`count_setups_using` dan el número previo al aviso de borrado (M-20).
- `components.py` — CRUD explícito de las 4 piezas globales (`list_/get_/create_/update_/delete_` × telescopio, cámara, montura y filtro): lecturas como dict (C-2), escrituras con dataclass validada; al borrar, imágenes en cascada + `purge` de sus ficheros.
- `localizations.py` — CRUD de `locations`: bloque de sitio (obstáculos y CL de las 8 direcciones) en JSON con carga defensiva al listar, e imagen única de CL (`lp_map`).
- `images.py` — API generalizada por entidad (`setup`/`telescope`/`camera`/`location`, mapa cerrado de tablas): `attach` **copia** a `data/…` (D-1), `list`/`remove`/`sync` (D-5: la lista es la verdad al guardar) y `purge` al borrar el padre.
- `metrics.py` — funciones puras: `focal_efectiva` (única fuente de la regla del reductor), `escala_imagen` (206,265 × píxel µm / focal mm), `limite_dawes` (116 / apertura), `relacion_focal`, `veredicto_muestreo` (umbrales como parámetro) y `calculos()` del bloque «Cálculos»; dato faltante → `None`.

## Qué hacer aquí
- Aquí SOLO datos y persistencia: **sin PyQt6 ni cálculos de planificación**.
- Guardar solo "datos fríos" comparables; NO guardar gráficas de rendimiento para compararlas.
- Las imágenes se adjuntan y se muestran: el usuario las compara visualmente, el programa no.
- Acceso a datos siempre vía `db.connection.get_connection()`; nuevas columnas/tablas → migración en `_MIGRATIONS` (`db/connection.py`).
- Al modificar la carpeta: actualizar "Estado actual" aquí mismo en la misma tarea.

## Planes futuros
1. Exportar/importar setups (JSON) para compartir configuraciones.
2. Aplicar `consider_lp` a las decisiones de captura (hoy solo se guarda; el paso 6 lo cablea).
