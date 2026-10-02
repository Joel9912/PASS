# ui/summary_tab/ — Pestaña Resumen

## Qué es
Vista general del usuario: progreso de captura de su plan actual, en qué sesión se encuentra y estado de su equipo.

## Estado actual
- Carpeta sin código (placeholder en `ui/main_window.py`).

## Qué hacer aquí
- **Progreso de captura por objeto**: mostrar el tiempo de exposición total acumulado (dato que calcula `stacks/global_pool.py`) frente al tiempo planificado.
- **Sesión activa**: leer las sesiones planificadas (`planners/planned_sessions.py`) para mostrar en cuál está el usuario.
- **Equipo y planes**: resumen de setups (`equipment/manager.py`) y planes del usuario.
- Sin lógica propia: solo presenta datos que calculan otros módulos.

## Planes futuros
1. Vista de progreso de captura por objeto.
2. Indicador de sesión planificada activa.
3. Resumen de equipo y gráficas de evolución.
