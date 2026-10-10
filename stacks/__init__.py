"""Integración de PASS con SirIL: calibrado, auditoría y apilado.

REGLAS DUAS de esta carpeta:
- Los archivos originales de sesión son de SOLO LECTURA: jamás se modifican ni eliminan.
- Trabajo por referencias/rutas: prohibido copiar archivos en cadena; la única
  escritura controlada es la salida de calibración en la carpeta de trabajo.
- Todo el procesamiento (calibrado, registro, apilado) lo hace SirIL.
"""
