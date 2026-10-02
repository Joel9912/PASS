# PAS.S — Planning & Astronomical Stacking Suite

**PAS.S** es un programa de escritorio para **planificar sesiones de astrofotografía** y tomar decisiones de equipo. Combina planificación de sesiones, planificación/comparativa de equipo y un planetario de apoyo, con integración de **SirIL** para el apilado.

> La base del programa es la planificación (sesiones y equipo). El planetario y el apilador son añadidos que lo completan.

## Pestañas

| Pestaña | Qué hace |
|---|---|
| **Resumen** | Progreso de captura por objeto (tiempo de exposición total), sesión planificada activa, estado del equipo |
| **Planetario** | Planetario con imágenes DSS2: esfera de fondo + esfera de objetos (Messier, NGC, IC, LDN) |
| **Equipo** | Setups y localizaciones del equipo con datos fríos y adjuntos visuales |
| **Planificador de Equipo** | Comparativas de equipo por características comparables y presupuesto |
| **Planificador** ⭐ | Búsqueda con filtros, tránsito/luna/noche astronómica, ranking de recomendaciones, catálogo personal y sesiones planificadas |
| **Apilador** | Calibración automática por sesión, pool global de referencias, auditoría con métricas SirIL y apilado con todas sus opciones |

## Requisitos

- Windows, PowerShell
- Python 3.12
- [SirIL](https://siril.org/) para la pestaña Apilador (se detecta desde el `PATH`; si no, el usuario indica la ruta)

## Instalación

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Ejecución

```powershell
python main.py
```

## Tests

```powershell
pytest
```

## Estructura

```
Planning-Stacking-Suite/
├── README.md / AGENTS.md / PROGRAM.md / MEMORY.md / STRUCTURE.md
├── main.py            # Entry point (PyQt6)
├── db/                # Capa SQLite (conexión y esquema)
├── planners/          # Búsqueda, tránsito, ranking, clima/seeing
├── stacks/            # Integración SirIL (calibrado, pool, auditoría, apilado)
├── equipment/         # Modelos y CRUD de equipo/localizaciones
├── planetary/         # Planetario (esferas DSS2 y de objetos)
├── ui/                # 6 pestañas PyQt6 (una carpeta por pestaña)
├── i18n/              # Traducciones Qt (es/en)
├── tests/             # Tests pytest
└── data/              # Base de datos local (no versionada)
```

Detalles de cada carpeta: ver `STRUCTURE.md`. Reglas de trabajo con agentes: ver `AGENTS.md`.

## Documentación

- `AGENTS.md` — reglas y qué leer según la tarea
- `PROGRAM.md` — filosofía y diseño de cada pestaña
- `MEMORY.md` — estado actual y roadmap
- `STRUCTURE.md` — árbol de carpetas y convenciones

## Licencia

[GPL-3.0](LICENSE)
