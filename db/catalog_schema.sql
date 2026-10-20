-- Proyecciones compatibles con formato 1 y metadatos explícitos de formato 2.
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
-- Metadatos de procedencia; row_id solo vincula la proyección de esta edición.
CREATE TABLE objects (
    pass_id TEXT PRIMARY KEY,
    package_group TEXT NOT NULL,
    row_kind TEXT NOT NULL CHECK(row_kind IN ('catalog','stars')),
    row_id INTEGER NOT NULL,
    UNIQUE(row_kind,row_id)
);
CREATE TABLE source_records (
    source TEXT NOT NULL,
    source_key TEXT NOT NULL,
    pass_id TEXT NOT NULL REFERENCES objects(pass_id) ON DELETE CASCADE,
    payload TEXT NOT NULL,
    PRIMARY KEY(source,source_key)
);
CREATE TABLE designations (
    namespace TEXT NOT NULL,
    designation TEXT NOT NULL,
    pass_id TEXT NOT NULL REFERENCES objects(pass_id) ON DELETE CASCADE,
    PRIMARY KEY(namespace,designation,pass_id)
);
CREATE TABLE object_relations (
    source_id TEXT NOT NULL REFERENCES objects(pass_id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES objects(pass_id) DEFERRABLE INITIALLY DEFERRED,
    kind TEXT NOT NULL,
    evidence TEXT NOT NULL,
    PRIMARY KEY(source_id,target_id,kind)
);
CREATE INDEX designation_lookup ON designations(designation COLLATE NOCASE, namespace);
CREATE INDEX source_record_object ON source_records(pass_id);
CREATE INDEX relation_target ON object_relations(target_id);
