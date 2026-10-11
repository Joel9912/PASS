# Historial de cambios

Cambios relevantes para quienes usan PASS. Los detalles de implementación y cada corrección pequeña quedan en los commits. La documentación se mantiene en español.

## Sin publicar — preparación de v0.2

Cambios desde `v0.1-alpha`. Esta versión **aún no tiene tag ni se ha publicado**; se completará cuando se apruebe el lanzamiento.

### Corregido
- Las tarjetas de clima ya no lanzan una excepción al recibir métricas numéricas de un proveedor.
- Una BD antigua con componentes embebidos de equipo ya no los pierde al abrir: se detiene la migración y conserva esos datos hasta acordar cómo trasladarlos.
- La calibración rechaza una sesión cuyo origen o cuyas tomas coincidan con la carpeta de salida, para evitar borrar originales al limpiar el área de trabajo.
- Las pruebas del Catálogo Personal y de Sesiones Planificadas ya no insertan ni borran datos en la base del usuario; se ejecutan sobre una base aislada.
- Las tarjetas de clima ya no provocan un error de SQLite al consultar el pronóstico desde un hilo secundario. Las claves se leen en el hilo principal y se pasan al trabajador; un fallo del proveedor se muestra como falta de datos.
- Corregidos detalles del Apilador y del Planificador detectados durante la revisión del código, con pruebas de regresión para evitar que reaparezcan.

### Cambiado
- Reorganizado internamente el Apilador en paneles por paso y separadas las pruebas por pestaña; el flujo de usuario sigue siendo el mismo.
- Unificadas utilidades compartidas de formato, cálculo y tablas; retirado código sin uso y aclarados los límites entre interfaz, lógica y base de datos.
- Actualizadas la documentación de carpetas y la información de versión mostrada por la aplicación.

### Pendiente
- Clear Outside y Meteoblue siguen sin consultar servicios reales: las tarjetas muestran «Sin datos» aunque haya claves guardadas.
- Resumen, Planetario y Planificador de Equipo siguen en construcción.

## v0.1-alpha — versión inicial

- Primera versión etiquetada de PASS, con Planificador, Equipo y asistente de Apilador mediante SirIL externo.

Las fechas y el enlace de `v0.2` se añadirán **solo cuando se publique**.
