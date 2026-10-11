# PASS — Planning & Astronomical Stacking Suite

**PASS** es un programa de escritorio para **planificar sesiones de astrofotografía** y tomar decisiones de equipo. Combina planificación de sesiones, planificación/comparativa de equipo y un planetario de apoyo, con integración de **SirIL** para el apilado.

> La base del programa es la planificación (sesiones y equipo). El planetario y el apilador son añadidos que lo completan.

**Estado: `v0.2` (alpha).** Es software libre en desarrollo activo: funciona sobre capturas reales, pero algunas pestañas siguen en construcción (indicadas abajo).

## Pestañas

| Pestaña | Qué hace | Estado |
|---|---|---|
| **Resumen** | Progreso de captura por objeto, sesión planificada activa, estado del equipo | 🔶 placeholder |
| **Planetario** | Planetario con imágenes DSS2: esfera de fondo + esfera de objetos (Messier, NGC, IC, LDN) | 🔶 placeholder |
| **Equipo** | Setups y localizaciones del equipo con datos fríos y adjuntos visuales | ✅ |
| **Planificador de Equipo** | Comparativas de equipo por características comparables y presupuesto | 🔶 placeholder |
| **Planificador** ⭐ | Búsqueda con filtros, tránsito/luna/noche astronómica, selección de fechas para captura, catálogo personal y sesiones planificadas | ✅ |
| **Apilador** | Escaneo de sesiones, calibración automática, auditoría con métricas de SirIL y apilado (drizzle, rechazo, ponderación, RGB) | ✅ |

## Requisitos

- Windows, PowerShell
- Python 3.12
- [SirIL](https://siril.org/) para la pestaña Apilador (se detecta desde el `PATH`; si no, el usuario indica la ruta en Configuración)

## Instalación

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Primer arranque

- **La primera ejecución descarga los catálogos astronómicos** (~18 MB: OpenNGC, HYG y LDN) desde internet. Sin conexión el programa abre igualmente, pero la búsqueda del Planificador no tendrá catálogo hasta completar la descarga; Planetario sigue en construcción.
- **SirIL solo es necesario para la pestaña Apilador.** El resto del programa (Planificador, Equipo, etc.) funciona sin él.

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
Planning Stacking Suite/
├── README.md / CHANGELOG.md / PROGRAM.md / MEMORY.md / STRUCTURE.md
├── main.py            # Punto de entrada (PyQt6)
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

Detalles de cada carpeta: ver `STRUCTURE.md`.

## Documentación

- `CHANGELOG.md` — cambios entre versiones (v0.2 todavía sin publicar)
- `PROGRAM.md` — filosofía y diseño de cada pestaña
- `MEMORY.md` — estado actual y roadmap
- `STRUCTURE.md` — árbol de carpetas y convenciones

## Licencia

[GPL-3.0](LICENSE) — se permite usar, modificar, distribuir y **vender copias**. Quien distribuya una versión derivada debe cumplir las condiciones de la GPL, incluido facilitar el código fuente correspondiente y conservar las libertades de sus destinatarios; no puede convertir esa versión distribuida en software privativo.
