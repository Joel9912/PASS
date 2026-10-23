-- Esquema de PASS (SQLite 3, stdlib). Idempotente: CREATE ... IF NOT EXISTS.

-- Localizaciones del usuario (+ bloque de sitio de la pestaña Equipo)
CREATE TABLE IF NOT EXISTS locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    latitude    REAL NOT NULL,
    longitude   REAL NOT NULL,
    altitude    REAL,
    -- Desfase horario frente a UTC (horas). NULL = usar la longitud como
    -- hora solar local (aproximación) hasta que el usuario lo indique.
    utc_offset_hours REAL,
    timezone_id TEXT,
    -- Bloque de sitio: JSON con SIEMPRE las 8 direcciones (N, NE, E, SE, S,
    -- SO, O, NO). obstacles = {dir: grados 0/15/30/45/60}.
    obstacles   TEXT,
    lp          TEXT,               -- {dir: {fuente, km}} CL por dirección
    bortle      INTEGER,            -- 1-9 (obligatorio en el formulario, no en la columna)
    sqm         REAL,               -- SQM cenital en mag/arcsec² (opcional)
    seeing_arcsec REAL,             -- seeing típico FWHM en ″ (opcional; «—» = sin dato)
    -- «Usar CL y Obstáculos al Planificar»: de momento
    -- solo se guarda; el cableado a puntuación es el paso 6 (comparativa).
    consider_lp INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Componentes globales reutilizables (pestaña Equipo v2): varios setups
-- referencian la misma óptica/cámara con rol principal o de guía.
CREATE TABLE IF NOT EXISTS telescopes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    aperture_mm    REAL,             -- NULL = el usuario no lo sabe
    focal_mm       REAL,
    optical_type   TEXT,             -- ver equipment.models.OPTICAL_TYPES
    subtype        TEXT,             -- opciones por tipo (equipment.models.SUBTYPE_SUGGESTIONS)
    reducer        INTEGER NOT NULL DEFAULT 0,   -- ¿lleva aplanador/reductor?
    reducer_factor REAL,             -- p. ej. 0.8 (NULL = desconocido)
    price_eur      REAL,             -- precio de la pieza (NULL = no informado)
    weight_kg      REAL,             -- peso de la pieza sin el aplanador (+0,5 kg al sumar el equipo)
    notes          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cameras (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    cooled        INTEGER NOT NULL DEFAULT 0,
    pixel_size_um REAL,              -- → FOV y escala de muestreo
    width_px      INTEGER,           -- → FOV
    height_px     INTEGER,           -- → FOV
    bit_depth     INTEGER,
    mono          INTEGER NOT NULL DEFAULT 0,   -- monocromática vs color
    ampglow       INTEGER NOT NULL DEFAULT 0,
    price_eur     REAL,              -- precio de la pieza (NULL = no informado)
    weight_kg     REAL,              -- peso de la pieza (NULL = no informado)
    notes         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Sin columna `resolution`: la resolución se deriva de width×height en la
-- UI y `calculate_fov` solo la usaba de respaldo de esas dos columnas.

CREATE TABLE IF NOT EXISTS mounts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    mount_type TEXT,                 -- ver equipment.models.MOUNT_TYPES
    payload_kg REAL,                 -- capacidad / carga útil
    price_eur  REAL,                 -- precio de la pieza (NULL = no informado)
    weight_kg  REAL,                 -- peso de la pieza (NULL = no informado)
    notes      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS filters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    filter_type TEXT,                -- ver equipment.models.FILTER_TYPES
    price_eur   REAL,                -- precio del filtro (sin peso: 0 kg en los totales)
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Setups de equipo (datos fríos comparables): combinación de componentes
-- globales + ubicación + categoría. Las columnas embebidas de la v1
-- (telescope_name, camera_pixel_size_um, mount_name…) viven ahora en sus
-- tablas. La migración conserva las columnas legacy pobladas como originales.
CREATE TABLE IF NOT EXISTS equipment_setups (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    category            TEXT NOT NULL DEFAULT 'general',
        -- 'paisaje' | 'campo_amplio' | 'espacio_profundo' |
        -- 'espacio_profundo_largo' | 'planetario' | 'general'
        -- (catálogo completo: equipment.models.CATEGORIES)
    location_id         INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    telescope_id        INTEGER REFERENCES telescopes(id) ON DELETE SET NULL,
    guide_telescope_id  INTEGER REFERENCES telescopes(id) ON DELETE SET NULL,
    camera_id           INTEGER REFERENCES cameras(id) ON DELETE SET NULL,
    guide_camera_id     INTEGER REFERENCES cameras(id) ON DELETE SET NULL,
    mount_id            INTEGER REFERENCES mounts(id) ON DELETE SET NULL,
    legacy_components_migrated INTEGER NOT NULL DEFAULT 0,
    -- Precio y peso del setup: los exige la comparativa (paso 6); se
    -- añadieron ya (decisión D-3) para migrar el esquema una sola vez.
    price_eur           REAL,
    weight_kg           REAL,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- «Qué filtros lleva»: muchos a muchos entre setups y filtros globales.
CREATE TABLE IF NOT EXISTS setup_filters (
    setup_id   INTEGER NOT NULL REFERENCES equipment_setups(id) ON DELETE CASCADE,
    filter_id  INTEGER NOT NULL REFERENCES filters(id) ON DELETE CASCADE,
    PRIMARY KEY (setup_id, filter_id)
);

-- Imágenes adjuntas al equipo (spot, etc.): SOLO visuales, el programa no las compara
CREATE TABLE IF NOT EXISTS equipment_images (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id  INTEGER NOT NULL REFERENCES equipment_setups(id) ON DELETE CASCADE,
    path      TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'otra'
        -- 'spot' | 'otra'
);

-- Imágenes de componentes y ubicaciones: SOLO visuales igualmente; el
-- CASCADE nativo de cada FK las filas, los ficheros los purga el CRUD.
CREATE TABLE IF NOT EXISTS telescope_images (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telescope_id INTEGER NOT NULL REFERENCES telescopes(id) ON DELETE CASCADE,
    path         TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'chart'
);

CREATE TABLE IF NOT EXISTS camera_images (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id INTEGER NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    path      TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'ganancia'
);

CREATE TABLE IF NOT EXISTS location_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id INTEGER NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    path        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'mapa_lp'
);

-- Catálogo personal del usuario (objetos guardados desde el Planificador)
CREATE TABLE IF NOT EXISTS personal_catalog (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id  TEXT NOT NULL,          -- p. ej. 'M31', 'NGC 7000', 'Mosaico M81'
    catalog    TEXT NOT NULL,          -- 'messier' | 'ngc' | 'ic' | 'ldn' | 'region'
    pass_object_id TEXT,               -- vínculo aditivo a identidad de catálogo, sin FK entre bases
    kind       TEXT NOT NULL DEFAULT 'catalog',
        -- 'catalog' = objeto del catálogo global | 'region' = región del usuario
    ra_hours   REAL,                   -- centro (solo regiones)
    dec_deg    REAL,                   -- centro (solo regiones)
    fov_major_arcmin REAL,             -- encuadre (solo regiones)
    fov_minor_arcmin REAL,
    tiles_x    INTEGER,                -- teselas de mosaico
    tiles_y    INTEGER,
    notes      TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(object_id, catalog)
);

-- Sesiones planificadas (el Planificador las escribe; Resumen las lee)
CREATE TABLE IF NOT EXISTS planned_sessions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id         TEXT NOT NULL,
    pass_object_id    TEXT,            -- designación legacy se conserva incluso al resolver identidad
    target_name       TEXT,
    setup_id          INTEGER REFERENCES equipment_setups(id) ON DELETE SET NULL,
    session_date      TEXT NOT NULL,
    planned_exposure_s INTEGER,
    target_kind       TEXT NOT NULL DEFAULT 'catalog',
        -- 'catalog' | 'region' (los parámetros de abajo describen el encuadre)
    ra_hours          REAL,            -- centro del encuadre
    dec_deg           REAL,
    fov_major_arcmin  REAL,
    fov_minor_arcmin  REAL,
    tiles_x           INTEGER,
    tiles_y           INTEGER,
    notes             TEXT,
    status            TEXT NOT NULL DEFAULT 'planificada',
        -- 'planificada' | 'completada'
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Configuración general (ruta de SirIL, API keys, idioma, etc.)
-- Ediciones de catálogo externas; solo metadatos y activación viven en la base personal.
CREATE TABLE IF NOT EXISTS catalog_editions (
    edition_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    resource_manifest TEXT,
    relative_path TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    versions TEXT NOT NULL,
    previous_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Estado persistente del calibrado: originales solo como rutas, salida en working.
CREATE TABLE IF NOT EXISTS calibrated_sessions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_dir    TEXT NOT NULL UNIQUE,
    calibrated_dir TEXT NOT NULL,
    n_frames       INTEGER NOT NULL,
    exposure_s     REAL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS work_drafts (
    workflow TEXT PRIMARY KEY CHECK(workflow IN ('planner', 'stacker')),
    format_version INTEGER NOT NULL,
    revision TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Catálogo de objetos deep-sky (OpenNGC + addendum; se carga automáticamente)
-- UNA fila por objeto; los cross-references evitan duplicar M31 = NGC 224.
CREATE TABLE IF NOT EXISTS catalog (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id         TEXT NOT NULL,      -- designación principal ('M31', 'NGC 224', 'IC 1', 'Barnard 33')
    catalog           TEXT NOT NULL,      -- catálogo de object_id
                        -- 'messier'|'ngc'|'ic'|'barnard'|'caldwell'|'ldn'|'other'
    messier_num       INTEGER,            -- número Messier si lo tiene
    ngc_num           INTEGER,            -- número NGC si lo tiene
    ic_num            INTEGER,            -- número IC si lo tiene
    name              TEXT,               -- nombre común ('Andromeda Galaxy')
    type              TEXT,               -- código OpenNGC ('G', 'OCl', 'Neb'...; ver planners/README)
    magnitude         REAL,               -- magnitud aparente (V o B)
    ra_hours          REAL,               -- ascensión recta (horas, J2000)
    dec_deg           REAL,               -- declinación (grados, J2000)
    size_major_arcmin REAL,               -- eje mayor (o único si circular)
    size_minor_arcmin REAL,               -- eje menor (NULL si circular/desconocido)
    constellation     TEXT,               -- constelación (código, p. ej. 'And', 'Se1' Serpens Caput)
    UNIQUE(object_id, catalog)
);
CREATE INDEX IF NOT EXISTS idx_catalog_messier ON catalog(messier_num);
CREATE INDEX IF NOT EXISTS idx_catalog_ngc ON catalog(ngc_num);
CREATE INDEX IF NOT EXISTS idx_catalog_ic ON catalog(ic_num);
CREATE INDEX IF NOT EXISTS idx_catalog_magnitude ON catalog(magnitude);
CREATE INDEX IF NOT EXISTS idx_catalog_type ON catalog(type);

-- Estrellas brillantes (HYG, magnitud < 8; se carga automáticamente)
CREATE TABLE IF NOT EXISTS stars (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT,                     -- 'Sirius', 'Betelgeuse'
    magnitude     REAL NOT NULL,            -- magnitud aparente
    ra_hours      REAL NOT NULL,            -- ascensión recta (horas)
    dec_deg       REAL NOT NULL,            -- declinación (grados)
    color         TEXT,                     -- tipo espectral / color
    constellation TEXT,
    UNIQUE(name, ra_hours, dec_deg)
);
CREATE INDEX IF NOT EXISTS idx_stars_magnitude ON stars(magnitude);
