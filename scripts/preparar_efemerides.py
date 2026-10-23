"""Prepara DE442s oficial intacto y avisos offline desde archivos revisados, sin descargas, instalación ni publicación."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from db.data_resources import validate_content

EXPECTED_KERNEL_SHA256 = "54d97562a5b094d298b1b8eafa5a2e17e3e010ce85e1a366d07f003ad159323c"
EXPECTED_RULES_SHA256 = "ae85f851646e7c4f0a762db852907bc090a2ab50c815eb2a6cd8639e96b7e047"
KERNEL_VERSION = "DE442s.2024-05-13"
NOTICE_VERSION = "PASS.DE442s.notice-1"
MAX_RULES_BYTES = 128 * 1024
KERNEL_URL = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de442s.bsp"
RULES_URL = "https://naif.jpl.nasa.gov/naif/rules.html"
NOTICE = """Efemérides JPL DE442s — NASA/JPL/NAIF.

PASS utiliza el kernel oficial intacto, sin recortarlo ni modificar sus comentarios o coeficientes.
Origen: https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/de442s.bsp
Condiciones originales: https://naif.jpl.nasa.gov/naif/rules.html
Se incluye una copia original de esas condiciones como naif-rules-original.html.txt; se presenta como texto, sin ejecutar HTML.
El uso y la redistribución del kernel están sujetos a dichas condiciones. No se distribuye aquí el Toolkit ni se atribuye patrocinio a NASA/JPL/NAIF.

PASS admite noches de 1950 a 2100; la cobertura adicional del archivo no amplía ese rango.
Las posiciones locales dependen también de transformaciones, muestreo y orientación terrestre: los avisos IERS distinguen datos, predicciones y fechas fuera de tabla. No se garantiza precisión uniforme en todo el intervalo.
DE442s no aporta por sí solo brillo o diámetro de objetos ni aplica automáticamente el movimiento propio conservado en los catálogos estelares.
Un recurso seleccionado ausente o inválido impide el cálculo; no se sustituye silenciosamente por otro modelo ni se descarga al buscar.

Este texto es una explicación de PASS, no una modificación de las condiciones originales ni una licencia nueva para los datos.
"""


def _bounded(path, limit):
    """Lee una entrada local acotada; no modifica el original ni intenta completar una transferencia truncada."""
    with Path(path).open("rb") as stream:
        data = stream.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("Archivo vacío o demasiado grande para preparar el componente.")
    return data


def prepare(kernel, rules, output, *, release_tag):
    """Fija bytes aprobados, verifica SPK y crea adjuntos/metadata nuevos; una huella distinta exige revisión explícita."""
    if not isinstance(release_tag, str) or not re.fullmatch(r"[A-Za-z0-9._-]+", release_tag):
        raise ValueError("Destino de release inválido; no se crea ninguna release con este comando.")
    output = Path(output)
    if output.exists() or output.is_symlink() or output.is_junction():
        raise ValueError("El destino debe ser nuevo; no se sobrescriben adjuntos existentes.")
    kernel_data = _bounded(kernel, 64 * 1024 * 1024)
    rules_data = _bounded(rules, MAX_RULES_BYTES)
    if hashlib.sha256(kernel_data).hexdigest() != EXPECTED_KERNEL_SHA256:
        raise ValueError("El archivo no coincide con el DE442s oficial intacto aprobado.")
    if hashlib.sha256(rules_data).hexdigest() != EXPECTED_RULES_SHA256:
        raise ValueError("Las reglas NAIF no coinciden con la instantánea revisada; verifica sus cambios antes de actualizarla.")
    rules_version = f"NAIF.rules-{EXPECTED_RULES_SHA256[:12]}"
    payloads = {"ephemeris": ("de442s.bsp", kernel_data),
                "naif_rules": ("naif-rules-original.html.txt", rules_data),
                "naif_notice": ("naif-notice.txt", NOTICE.encode("utf-8"))}
    metadata = {
        "ephemeris": (KERNEL_VERSION, "spk-planets-v1", "NAIF rules: kernel original intacto", KERNEL_URL,
                      "NASA/JPL/NAIF, DE442s", {"naif_notice": NOTICE_VERSION, "naif_rules": rules_version}),
        "naif_rules": (rules_version, "utf8-v1", "Condiciones originales NAIF; copia informativa sin relicenciar", RULES_URL,
                       "NASA/JPL/NAIF", {}),
        "naif_notice": (NOTICE_VERSION, "utf8-v1", "GPL-3.0 para esta explicación de PASS; no relicencia el kernel",
                        "https://github.com/Joel9912/PASS", "PASS; reconocimiento NASA/JPL/NAIF", {}),
    }
    resources = {}
    for name, (filename, data) in payloads.items():
        version, format_name, license_name, source, attribution, requires = metadata[name]
        item = {"version": version, "format": format_name, "optional": False, "license": license_name,
                "attribution": attribution, "source": source, "revision": version, "requires": requires,
                "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "url": f"https://github.com/Joel9912/PASS/releases/download/{release_tag}/{filename}"}
        validate_content(data, item)
        resources[name] = item
    output.mkdir(parents=True)
    for filename, data in payloads.values():
        with (output / filename).open("xb") as stream:
            stream.write(data)
    with (output / "resources-manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(resources, stream, ensure_ascii=False, indent=2)
    return resources


def main():
    """Prepara los archivos locales indicados y declara el destino futuro de adjuntos, sin crear tag ni release."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--rules", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-tag", required=True)
    args = parser.parse_args()
    prepare(args.kernel, args.rules, args.output, release_tag=args.release_tag)
    print(f"Recursos DE442s preparados en {args.output}; no se han instalado ni publicado.")


if __name__ == "__main__":
    main()
