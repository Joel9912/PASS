"""Valida kernels planetarios SPK antes de activarlos; no calcula efemérides propias ni acredita precisión científica."""

from io import BytesIO
from struct import error as StructError

import numpy as np
from jplephem.daf import DAF
from jplephem.spk import SPK

# Margen técnico para noches locales, conversiones de tiempo y tiempo de luz;
# no es una tolerancia científica ni amplía las fechas admitidas por la UI.
START_JD = 2433279.5  # 1949-12-29
END_JD = 2488437.5  # 2101-01-04
REQUIRED_PAIRS = frozenset(
    [(0, number) for number in range(1, 9)]
    + [(0, 10), (1, 199), (2, 299), (3, 399), (3, 301)]
)


def _check_directory(daf: DAF, size: int) -> None:
    """Acota el directorio DAF antes del lector externo para rechazar ciclos, truncados e índices ajenos al archivo."""
    if (daf.locidw != b"DAF/SPK" or (daf.nd, daf.ni) != (2, 6)
            or not 385 <= daf.free <= size // 8 + 1):
        raise ValueError("Cabecera SPK no compatible o incompleta.")
    current, previous, seen = daf.fward, 0, set()
    while current:
        if current in seen or not 2 <= current < size // 1024:
            raise ValueError("Directorio SPK cíclico o fuera del archivo.")
        seen.add(current)
        record = daf.read_record(current)
        following, before, count = daf.summary_control_struct.unpack(record[:24])
        if (not all(np.isfinite(x) and x == int(x) for x in (following, before, count))
                or before != previous or not 1 <= count <= daf.summaries_per_record):
            raise ValueError("Directorio SPK inválido.")
        previous, current = current, int(following)
    if not seen or previous != daf.bward:
        raise ValueError("Directorio SPK incompleto.")


def validate_spk(data: bytes) -> None:
    """Exige cadenas planetarias J2000, polinomios finitos y cobertura local suficiente; nunca usa red ni modifica bytes."""
    try:
        with BytesIO(data) as stream:
            daf = DAF(stream)
            _check_directory(daf, len(data))
            kernel = SPK(daf)
            pairs = set()
            for segment in kernel.segments:
                pair = segment.center, segment.target
                if (pair in pairs or segment.frame != 1 or segment.data_type not in (2, 3)
                        or not np.isfinite([segment.start_jd, segment.end_jd]).all()
                        or segment.start_jd >= segment.end_jd
                        or not 385 <= segment.start_i <= segment.end_i < daf.free):
                    raise ValueError("Segmento SPK no compatible o ambiguo.")
                pairs.add(pair)
                values = daf.read_array(segment.start_i, segment.end_i)
                if len(values) < 9 or not np.isfinite(values).all():
                    raise ValueError("Coeficientes SPK ausentes o no finitos.")
                initial, interval, record_size, records = values[-4:]
                components = 3 if segment.data_type == 2 else 6
                if (interval <= 0 or record_size != int(record_size) or records != int(records)
                        or record_size < components + 2 or records < 1
                        or (record_size - 2) % components or record_size * records != len(values) - 4):
                    raise ValueError("Estructura polinómica SPK inválida.")
                rows = values[:-4].reshape(int(records), int(record_size))
                if (not np.all(rows[:, 1] == interval / 2)
                        or not np.all(rows[:, 0] == initial + (np.arange(int(records)) + 0.5) * interval)
                        or segment.start_second < initial
                        or segment.end_second > initial + records * interval):
                    raise ValueError("Intervalos SPK incoherentes con los registros.")
                if pair in REQUIRED_PAIRS and not segment.start_jd <= START_JD < END_JD <= segment.end_jd:
                    raise ValueError("Kernel SPK no cubre 1950–2100 con los márgenes de cálculo.")
                positions, velocities = segment.compute_and_differentiate(
                    np.array([segment.start_jd, (segment.start_jd + segment.end_jd) / 2, segment.end_jd])
                )
                if not np.isfinite(positions).all() or not np.isfinite(velocities).all():
                    raise ValueError("Evaluación SPK no finita.")
                position, velocity = segment.compute_and_differentiate(float((segment.start_jd + segment.end_jd) / 2))
                if not np.isfinite(position).all() or not np.isfinite(velocity).all():
                    raise ValueError("Evaluación escalar SPK no finita.")
            if not REQUIRED_PAIRS <= pairs:
                raise ValueError("Kernel SPK sin cadenas completas para Sol, Tierra, Luna y planetas.")
    except (OSError, StructError, IndexError, KeyError, TypeError, OverflowError) as error:
        raise ValueError("Kernel SPK ilegible o incompleto.") from error
