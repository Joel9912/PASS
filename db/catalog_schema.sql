-- Esquema de compatibilidad para ediciones de los paquetes formato 1.
-- Solo datos astronómicos: nunca tablas ni columnas personales de pass.db.
CREATE TABLE catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id TEXT NOT NULL,
    catalog TEXT NOT NULL,
    messier_num INTEGER,
    ngc_num INTEGER,
    ic_num INTEGER,
    name TEXT,
    type TEXT,
    magnitude REAL,
    ra_hours REAL,
    dec_deg REAL,
    size_major_arcmin REAL,
    size_minor_arcmin REAL,
    constellation TEXT,
    UNIQUE(object_id, catalog)
);
CREATE TABLE stars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    magnitude REAL,
    ra_hours REAL,
    dec_deg REAL,
    color TEXT,
    constellation TEXT,
    UNIQUE(name, ra_hours, dec_deg)
);
