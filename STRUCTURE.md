# Estructura de Carpetas y Archivos PAS.S

## 📁 Estructura actual

```
Planning-Stacking-Suite/
├── README.md / AGENTS.md / PROGRAM.md / MEMORY.md / STRUCTURE.md
├── LICENSE               # GPL-3.0
├── requirements.txt      # PyQt6, pyqtgraph, astropy, numpy, PyYAML, pytest
├── .gitignore
├── .opencode/skills/     # Skills de OpenCode: auditoria-pas, verificacion-fix
├── main.py               # Entry point: crea QApplication y la ventana principal
│
├── db/                   # Capa SQLite (stdlib sqlite3)
│   ├── connection.py     # Conexión única → data/pass.db
│   ├── schema.sql        # Tablas: locations, equipment_setups, equipment_images,
│   │                     #   personal_catalog, planned_sessions, settings,
│   │                     #   catalog (objetos) y stars (estrellas)
│   └── README.md
│
├── planners/             # Lógica de planificación (sin UI)
│   ├── catalog_loader.py     # Descarga OpenNGC + HYG + LDN → SQLite (auto al arrancar)
│   ├── celestial_search.py   # Filtros + tabla de resultados
│   ├── transit.py            # Tránsito, luna, noche astronómica (astropy)
│   ├── analytical_transit.py # Culminación/altitud sin astropy + local_utc_offset
│   ├── moon_distance.py      # Umbral lunar y ventanas Captura Ideal/Posible
│   ├── capture_plan.py       # Ranking de fechas (plan de captura)
│   ├── sky_loader.py         # Datos del planetario (estrellas/objetos → UI sin SQL)
│   ├── framing.py            # FOV del equipo (None si faltan datos)
│   ├── ldn_loader.py         # Nebulosas oscuras de Lynds (VizieR)
│   ├── ranking.py            # Ranking/recomendaciones (métricas del usuario)
│   ├── personal_catalog.py   # Catálogo personal + regiones (CRUD)
│   ├── planned_sessions.py   # Sesiones planificadas (CRUD)
│   ├── weather/              # Clear Outside (clima) + Meteoblue (seeing), mocks
│   └── README.md
│
├── stacks/               # Integración SirIL (CLI externa, sin motor propio)
│   ├── siril_finder.py       # PATH → ruta del usuario (settings.siril_path)
│   ├── session_parser.py     # Detecta lights/flats/darks/bias/dark_flats/masters
│   ├── calibrator.py         # Calibración automática → data/working/calibrados/
│   ├── global_pool.py        # Pool de REFERENCIAS (cero copias)
│   ├── registration.py       # Registro con SirIL
│   ├── metrics.py            # FWHM, redondez, transparencia, ranking, descarte
│   ├── stacker.py            # Todas las opciones de SirIL + multihilo
│   └── README.md
│
├── equipment/            # Datos de equipo (sin UI)
│   ├── models.py             # Location, Telescope, Camera, Mount, EquipmentSetup
│   ├── manager.py            # CRUD de setups
│   ├── localizations.py      # CRUD de localizaciones
│   ├── images.py             # Imágenes adjuntas (solo visuales)
│   └── README.md
│
├── planetary/            # Planetario: dos esferas, usuario al centro
│   ├── catalog.py            # Messier, NGC, IC, LDN
│   ├── dss2_sphere.py        # Esfera de fondo con imágenes DSS2 (caché)
│   ├── object_sphere.py      # Esfera de puntos de objetos
│   └── README.md
│
├── ui/                   # Interfaz PyQt6 (una carpeta por pestaña)
│   ├── main_window.py        # MainWindow: sidebar + contenido + pie (v0.1)
│   │                         #   PlannerPage = 4 subpestañas (LocationBar vive en
│   │                         #   Búsqueda, fila 3 izquierda, y se comparte por señal)
│   ├── style.py              # Tema oscuro azulado (QSS + fuente 13pt)
│   ├── config_tab/           # Diálogo «Configuración General» (modal: SirIL/clima)
│   │   ├── config_dialog.py
│   │   └── README.md
│   ├── planner_tab/          # ⭐ Implementado: 4 subpestañas (una carpeta
│   │   │                     #   por subpestaña, CADA UNA CON SU README)
│   │   ├── __init__.py           # Re-exporta las 4 clases (API pública intacta)
│   │   ├── widgets.py            # Compartidos: LocationBar, efemérides, curva,
│   │   │                         #   tarjetas y formato de catálogo (shared)
│   │   ├── README.md             # Índice del Planificador
│   │   ├── busqueda/             # Rejilla 3×2: filtros + tabla + efemérides +
│   │   │   ├── tab.py            #   curva + ubicación + clima
│   │   │   └── README.md         #   (con esquema ASCII del estado actual)
│   │   ├── catalogo_personal/    # Objetos y regiones guardados
│   │   │   ├── tab.py
│   │   │   └── README.md
│   │   ├── planificacion/        # Planetario + encuadre + plan + sesión
│   │   │   ├── tab.py
│   │   │   ├── planetario_visual.py  # Lienzo de cielo (QPainter, gnomónica)
│   │   │   └── README.md
│   │   └── sesiones/             # Sesiones: editar / completar / eliminar
│   │       ├── tab.py
│   │       └── README.md
│   ├── summary_tab/README.md     # Progreso de captura, sesión activa
│   ├── planetary_tab/README.md   # Renderizado de las dos esferas
│   ├── equipment_tab/README.md   # Gestión de setups/localizaciones
│   ├── planner_equip_tab/README.md  # Comparativas por métricas de usuario
│   ├── stacker_tab/README.md     # Sesiones, calibración, auditoría, apilado
│   └── README.md
│
├── i18n/                 # Traducciones Qt (sistema nativo)
│   ├── es.ts / en.ts
│   └── README.md
│
├── tests/                # pytest: 12 test_*.py + conftest.py (detalle en su README)
│   ├── test_smoke.py
│   ├── test_settings.py
│   ├── test_weather.py
│   ├── test_planners.py
│   ├── test_dialogos.py
│   ├── test_equipment.py
│   ├── test_analytical_transit.py
│   ├── test_capture_plan.py
│   ├── test_moon_distance.py
│   ├── test_framing.py
│   ├── test_ldn_loader.py
│   ├── conftest.py
│   └── README.md
│
├── data/                 # Datos locales (NO versionados)
│   ├── pass.db               # Base SQLite (se crea en runtime)
│   ├── equipment_images/     # Copias de imágenes adjuntas por setup (D-1)
│   ├── working/calibrados/   # Salida de calibración por sesión
│   └── dss2_cache/           # Imágenes DSS2 descargadas
│
└── .venv/                # Entorno virtual Python 3.12
```

## 📏 Convención de README por carpeta (obligatoria)

Cada carpeta con código tiene **un solo** `README.md` con 4 secciones fijas, creado y actualizado en la misma tarea. Plantilla y reglas completas: **ver `AGENTS.md`** (fuente única, R2).

## 🗂️ Reglas de separación por carpeta

| Carpeta | Contiene | No contiene |
|---|---|---|
| `ui/<pestaña>/` | Widgets, layouts, pantallas | SQL, cálculos astronómicos, lógica de negocio |
| `planners/` | Búsqueda, tránsito, ranking, sesiones planificadas | PyQt6, acceso directo a ficheros de sesión |
| `stacks/` | Llamadas a SirIL, pool, métricas | Motor propio de calibrado/apilado (prohibido) |
| `equipment/` | Modelos y persistencia de equipo | UI, recomendaciones de compra |
| `planetary/` | Catálogos y lógica de las esferas | Widgets de la pestaña |
| `db/` | Conexión, esquema, migraciones | Lógica de negocio |
| `data/` | Ficheros generados en runtime | Código (nunca) |

- Una carpeta = una responsabilidad. Si crece mucho: subcarpeta con su propio README.
- `stacks/` tiene reglas duras: originales solo lectura, cero copias en cadena, SirIL para todo (detalle en su README).

## 🔄 Flujo de datos

```
ui/ (PyQt6)  →  planners/ | stacks/ | planetary/ (lógica)  →  db/ (SQLite en data/)
      ↑                        |
      └───── señales/respuestas ←┘
```

- Planificador escribe `planned_sessions` → Resumen la lee.
- Apilador calcula tiempo de exposición total → Resumen lo muestra.
- Datos de `equipment/` alimentan Planificador y Planificador de Equipo.

## 📦 Dependencias y configuración
- Instaladas en `.venv`: PyQt6 6.11, **pyqtgraph 0.14.0** (gráficas del Planificador), astropy 8.0, numpy 2.5, PyYAML 6.0 (+ pytest).
- Cualquier cambio: actualizar `requirements.txt`.
- API keys (Clear Outside, Meteoblue), ruta de SirIL e idioma: tabla `settings` de SQLite — **nunca** en código.

## 📌 Cómo crecer la estructura
1. **Nueva pestaña** → `ui/<nombre_tab>/` + `README.md` + actualizar este archivo y `MEMORY.md`.
2. **Nueva lógica** → carpeta de categoría + `README.md`.
3. **Nueva tabla** → `db/schema.sql` (`IF NOT EXISTS`) + documentar en `db/README.md`.
4. **Nueva dependencia** → venv + `requirements.txt` + nota en `MEMORY.md`.
5. **Cualquier cambio estructural** → actualizar `STRUCTURE.md` en la misma tarea.
