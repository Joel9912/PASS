-- Esquema de PAS.S (SQLite 3, stdlib). Idempotente: CREATE ... IF NOT EXISTS.

-- Localizaciones del usuario
CREATE TABLE IF NOT EXISTS locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    latitude    REAL NOT NULL,
    longitude   REAL NOT NULL,
    altitude    REAL,
    -- Desfase horario frente a UTC (horas). NULL = usar la longitud como
    -- hora solar local (aproximación) hasta que el usuario lo indique.
    utc_offset_hours REAL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Setups de equipo (datos fríos comparables)
CREATE TABLE IF NOT EXISTS equipment_setups (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    category            TEXT NOT NULL DEFAULT 'campo_amplio',
        -- 'campo_amplio' | 'nebulosas' | 'galaxias' | 'planetario' (futuro)
    location_id         INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    telescope_name      TEXT,
    telescope_aperture_mm REAL,
    telescope_focal_mm  REAL,
    camera_name         TEXT,
    camera_cooled       INTEGER NOT NULL DEFAULT 0,
    camera_resolution   TEXT,
    camera_bit_depth    INTEGER,
    camera_pixel_size_um REAL,      -- tamaño de píxel (µm) → FOV
    camera_width_px     INTEGER,    -- resolución horizontal (px) → FOV
    camera_height_px    INTEGER,    -- resolución vertical (px) → FOV
    mount_name          TEXT,
    -- Precio y peso del setup: los exige la comparativa (paso 6); se
    -- añadieron ya (decisión D-3) para migrar el esquema una sola vez.
    price_eur           REAL,
    weight_kg           REAL,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Imágenes adjuntas al equipo (spot, etc.): SOLO visuales, el programa no las compara
CREATE TABLE IF NOT EXISTS equipment_images (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    setup_id  INTEGER NOT NULL REFERENCES equipment_setups(id) ON DELETE CASCADE,
    path      TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'otra'
        -- 'spot' | 'otra'
);

-- Catálogo personal del usuario (objetos guardados desde el Planificador)
CREATE TABLE IF NOT EXISTS personal_catalog (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id  TEXT NOT NULL,          -- p. ej. 'M31', 'NGC 7000', 'Mosaico M81'
    catalog    TEXT NOT NULL,          -- 'messier' | 'ngc' | 'ic' | 'ldn' | 'region'
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
