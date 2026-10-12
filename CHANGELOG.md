# Historial de cambios

Cambios relevantes para quienes usan PASS. Los detalles de implementación y cada corrección pequeña quedan en los commits. Las correcciones registradas citan su ID en [`BUGS.md`](BUGS.md), donde constan su severidad y estado. La documentación se mantiene en español.

## Sin publicar — preparación de v0.2

Cambios desde `v0.1-alpha`. Esta versión **aún no tiene tag ni se ha publicado**; se completará cuando se apruebe el lanzamiento.

### Corregido
- Guardar un equipo confirma juntos sus datos, filtros y adjuntos; un fallo revierte la BD y retira las copias nuevas sin borrar las anteriores. Los errores de copia y SQLite se muestran conservando el formulario (E-0002; decisión E-0012).
- Las descargas vacías o con CSV incompleto ya no sustituyen el catálogo válido; se comprueba la longitud HTTP cuando está disponible y los errores de inserción revierten el refresco (B-0003, protección parcial).
- Refrescar OpenNGC ya no elimina las nebulosas LDN previamente cargadas (B-0009).
- Los lights homónimos de filtros distintos conservan referencias independientes al calibrar (S-0004).
- Registro y debayer rechazan índices incompletos, duplicados o mal nombrados en lugar de atribuir datos a otro frame (S-0005).
- Los filtros que generan el mismo nombre de canal, incluso por mayúsculas en Windows, ya no sobrescriben sus pilas (S-0007).
- El Apilador detiene una corrida si no consigue limpiar por completo salidas temporales anteriores, en vez de mezclarlas con resultados nuevos.
- Un fallo de migración ya no deja una conexión SQLite incompleta reutilizable en el proceso.
- Un filtro inexistente impide guardar el equipo antes de crear adjuntos o confirmar cambios parciales.
- Dos adjuntos con el mismo nombre de archivo ya no se sobrescriben al guardarlos en una entidad de Equipo.
- La ejecución normal de `pytest` aísla la BD, descargas y carpeta de trabajo: las pruebas no migran ni escriben en los datos del usuario.
- Las tarjetas de clima ya no lanzan una excepción al recibir métricas numéricas de un proveedor.
- Una BD antigua con componentes embebidos de equipo ya no los pierde al abrir: se detiene la migración y conserva esos datos hasta acordar cómo trasladarlos.
- La calibración rechaza una sesión cuyo origen o cuyas tomas coincidan con la carpeta de salida, para evitar borrar originales al limpiar el área de trabajo.
- Cada sesión tiene carpeta de salida propia (`calibrados/<nombre>-<hash>` derivado de su ruta): dos sesiones homónimas de proyectos distintos ya no comparten calibrados ni se limpian la una a la otra.
- Las sesiones se identifican por su ruta de origen en todo el Apilador: una homónima ya no aparece como «calibrada» con la calibración de la otra, ni hereda sus exposiciones, fichas ni avisos, y el pool de lights no se queda solo con una de las dos.
- Un calibrado antiguo sin atribución se conserva intacto y no se migra por su cuenta: para generar la salida nueva hay que pulsar «Calibrar», y para borrarlo, confirmarlo en la limpieza.
- Las pruebas del Catálogo Personal y de Sesiones Planificadas ya no insertan ni borran datos en la base del usuario; se ejecutan sobre una base aislada.
- Las tarjetas de clima ya no provocan un error de SQLite al consultar el pronóstico desde un hilo secundario. Las claves se leen en el hilo principal y se pasan al trabajador; un fallo del proveedor se muestra como falta de datos.
- Corregidos detalles del Apilador y del Planificador detectados durante la revisión del código, con pruebas de regresión para evitar que reaparezcan.

### Cambiado
- Reorganizado internamente el Apilador en paneles por paso y separadas las pruebas por pestaña; el flujo de usuario sigue siendo el mismo.
- Los enlaces de registro de SirIL usan el nombre de la carpeta de la sesión, nunca su ruta completa.
- Unificadas utilidades compartidas de formato, cálculo y tablas; retirado código sin uso y aclarados los límites entre interfaz, lógica y base de datos.
- Actualizadas la documentación de carpetas y la información de versión mostrada por la aplicación.

### Pendiente
- Clear Outside y Meteoblue siguen sin consultar servicios reales: las tarjetas muestran «Sin datos» aunque haya claves guardadas.
- Resumen, Planetario y Planificador de Equipo siguen en construcción.

## v0.1-alpha — versión inicial

- Primera versión etiquetada de PASS, con Planificador, Equipo y asistente de Apilador mediante SirIL externo.

Las fechas y el enlace de `v0.2` se añadirán **solo cuando se publique**.
