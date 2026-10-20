# PASS — Planning & Astronomical Stacking Suite

**PASS** es un programa de escritorio para **planificar sesiones de astrofotografía** y tomar decisiones de equipo. Combina planificación de sesiones, planificación/comparativa de equipo y un planetario de apoyo, con integración de **SirIL** para el apilado.

> La base del programa es la planificación (sesiones y equipo). El planetario y el apilador son añadidos que lo completan.

**Estado: `v0.2-alpha` en preparación, todavía sin publicar.** Es software libre en desarrollo activo. La base de Equipo, Planificador y Apilador está implementada, pero eso no significa que todas sus funciones previstas estén terminadas. Los paquetes de datos definitivos y su cobertura/licencias siguen en preparación.

## Pestañas

| Pestaña | Qué hace | Estado |
|---|---|---|
| **Resumen** | Progreso de captura por objeto, sesión planificada activa, estado del equipo | 🔶 placeholder |
| **Planetario** | Planetario con imágenes DSS2: esfera de fondo + esfera de objetos (Messier, NGC, IC, LDN) | 🔶 placeholder |
| **Equipo** | Setups y localizaciones del equipo con datos fríos y adjuntos visuales | ✅ |
| **Planificador de Equipo** | Comparativas de equipo por características comparables y presupuesto | 🔶 placeholder |
| **Planificador** ⭐ | Búsqueda, tránsito/luna/noche, catálogo personal y sesiones planificadas | Base implementada; rediseño previsto para v0.3-alpha |
| **Apilador** | Sesiones y FOV, calibración, métricas de SirIL y apilado con drizzle, rechazo, ponderación y RGB | Flujo implementado; diagnóstico avanzado y nuevos modos pendientes |

## Requisitos

- Windows, PowerShell
- Python 3.12
- [SirIL](https://siril.org/) para el Apilador: la ruta elegida en Configuración tiene prioridad; `PATH` solo se usa sin una elección. Una ruta elegida inválida avisa y no cambia de instalación automáticamente.

## Instalación

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Primer arranque

- **El arranque no espera descargas.** Los paquetes incluidos en la distribución se importan en segundo plano si faltan catálogos. En **Configuración → Catálogos** puedes consultar versiones, comprobar paquetes publicados por PASS y autorizar su actualización. Si no hay paquete incluido ni una release con los adjuntos publicados, la búsqueda permanece sin esos datos; los catálogos existentes se conservan.
- **SirIL solo es necesario para la pestaña Apilador.** El resto del programa (Planificador, Equipo, etc.) funciona sin él.

## Ejecución

```powershell
python main.py
```

## Registros locales
Los registros locales están en `data/logs/pass.log` (acciones y errores generales) y `data/logs/apilador.log` (Apilador y salida completa de SirIL). Se crean automáticamente y se continúa el historial al reabrir; no se borran automáticamente. Pueden contener rutas y datos de tu equipo: revísalos antes de compartirlos. La terminal muestra solo los mensajes recientes.

## Tests

```powershell
pytest
```

## Estructura

```
Planning Stacking Suite/
├── README.md / CHANGELOG.md / BUGS.md / LICENSE
├── main.py            # Punto de entrada (PyQt6)
├── db/                # Capa SQLite (conexión, esquema y migraciones)
├── planners/          # Búsqueda, tránsito, ranking, clima/seeing
├── stacks/            # Integración SirIL (calibrado, pool, auditoría, apilado)
├── equipment/         # Modelos y CRUD de equipo/localizaciones
├── planetary/         # Planetario (esferas DSS2 y de objetos)
├── ui/                # 6 pestañas PyQt6 (una carpeta por pestaña)
├── i18n/              # Plantillas Qt es/en, todavía sin integrar
├── scripts/           # Herramientas de mantenimiento
├── tests/             # Tests pytest
└── data/              # Base de datos local (no versionada)
```

## Documentación

- `CHANGELOG.md` — cambios entre versiones (v0.2 todavía sin publicar)
- `BUGS.md` — bugs conocidos, con su severidad y estado

## Licencia

[GPL-3.0](LICENSE) — se permite usar, modificar, distribuir y **vender copias**. Quien distribuya una versión derivada debe cumplir las condiciones de la GPL, incluido facilitar el código fuente correspondiente y conservar las libertades de sus destinatarios; no puede convertir esa versión distribuida en software privativo.
