"""Tests del planificador: catálogo, carga, búsqueda, tránsito y ranking.

- Los tests de PARSING son offline (datos inline).
- Los tests contra la BD usan el catálogo sintético del sandbox, sin red.
"""
import gzip
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from planners import catalog_loader

# Cabecera real de OpenNGC (32 columnas separadas por ';')
NGC_HEADER = (
    "Name;Type;RA;Dec;Const;MajAx;MinAx;PosAng;B-Mag;V-Mag;J-Mag;H-Mag;K-Mag;"
    "SurfBr;Hubble;Pax;Pm-RA;Pm-Dec;RadVel;Redshift;Cstar U-Mag;Cstar B-Mag;"
    "Cstar V-Mag;M;NGC;IC;Cstar Names;Identifiers;Common names;NED notes;"
    "OpenNGC notes;Sources"
)


def _ngc_line(**values_by_index: str) -> str:
    """Construye una línea CSV de OpenNGC con las columnas indicadas por índice."""
    fields = [""] * 32
    for index, value in values_by_index.items():
        fields[int(index.removeprefix("c"))] = value
    return ";".join(fields)


@pytest.fixture(scope="module")
def loaded_db() -> dict[str, int]:
    """Consulta los datos sintéticos; nunca descarga ni omite por falta de red."""
    return catalog_loader.catalog_counts()


# ------------------------------------------------------------------ parsing
def test_parse_messier_primary_designation():
    """Un objeto con número Messier usa designación 'M31' y cross-refs."""
    line = _ngc_line(
        c0="NGC0224", c1="G", c2="00:42:44.33", c3="+41:16:09.4", c4="And",
        c5="177.83", c6="69.66", c8="4.36", c9="3.44", c23="031",
        c28="Andromeda Galaxy",
    )
    rows = catalog_loader.parse_ngc_rows(NGC_HEADER + "\n" + line + "\n")

    assert len(rows) == 1
    (object_id, catalog, messier, ngc, ic, name, obj_type,
     magnitude, ra, dec, major, minor, constellation) = rows[0]
    assert object_id == "M31" and catalog == "messier"
    assert messier == 31 and ngc == 224 and ic is None
    assert name == "Andromeda Galaxy" and obj_type == "G"
    assert magnitude == pytest.approx(3.44)          # prefiere V sobre B
    assert ra == pytest.approx(0 + 42 / 60 + 44.33 / 3600, abs=1e-9)
    assert dec == pytest.approx(41 + 16 / 60 + 9.4 / 3600, abs=1e-9)
    assert (major, minor) == (177.83, 69.66)
    assert constellation == "And"


def test_parse_ngc_primary_when_no_messier():
    """Sin número Messier, la designación sale del propio nombre NGC/IC."""
    ngc_line = _ngc_line(c0="NGC7000", c1="Neb", c2="20:59:00.0", c3="+44:31:00.0",
                         c4="Cyg", c8="7.0")
    ic_line = _ngc_line(c0="IC0001", c1="**", c2="00:08:27.05", c3="+27:43:03.6",
                        c4="Peg")
    rows = catalog_loader.parse_ngc_rows(
        NGC_HEADER + "\n" + ngc_line + "\n" + ic_line + "\n"
    )

    by_id = {row[0]: row for row in rows}
    assert by_id["NGC 7000"][1] == "ngc" and by_id["NGC 7000"][3] == 7000
    assert by_id["IC 1"][1] == "ic" and by_id["IC 1"][4] == 1
    assert by_id["IC 1"][7] is None                    # sin magnitud → None


def test_parse_skips_duplicate_and_nonexistent():
    """Los tipos Dup y NonEx no se cargan (evita objetos repetidos)."""
    dup = _ngc_line(c0="IC0011", c1="Dup", c2="00:52:59.35", c3="+56:37:18.8",
                    c4="Cas", c24="0281")
    nonex = _ngc_line(c0="NGC9999", c1="NonEx", c2="00:00:00.0", c3="+00:00:00.0",
                      c4="And")
    real = _ngc_line(c0="NGC0281", c1="Neb", c2="00:52:25.0", c3="+56:33:54.0",
                     c4="Cas")
    rows = catalog_loader.parse_ngc_rows(
        NGC_HEADER + "\n" + dup + "\n" + nonex + "\n" + real + "\n"
    )
    assert [row[0] for row in rows] == ["NGC 281"]


def test_parse_hyg_magnitude_limit():
    """HYG: filtra por magnitud, excluye al Sol y las filas incompletas."""
    csv_text = (
        '"id","proper","ra","dec","mag","spect","con"\n'
        '1,"Sirius",6.752481,-16.716116,-1.44,"A0m...","CMa"\n'
        '2,"Sol",0.0,0.0,-26.70,"G2V",""\n'
        '3,"Faint",12.3,45.0,9.50,"K0","Her"\n'
        '4,"NoMag",1.0,1.0,,"A1","Ori"\n'
        '5,"Vega",18.6156,38.7837,0.03,"A0V","Lyr"\n'
    )
    rows = catalog_loader.parse_hyg_rows(gzip.compress(csv_text.encode("utf-8")))

    names = [row[0] for row in rows]
    assert names == ["Sirius", "Vega"]
    sirius = rows[0]
    assert sirius[1] == pytest.approx(-1.44)
    assert sirius[2] == pytest.approx(6.752481)
    assert sirius[4] == "A0m..." and sirius[5] == "CMa"


# -------------------------------------------------------------- contra la BD
def test_catalog_counts(loaded_db):
    """Los contadores reflejan exactamente el catálogo sintético aislado."""
    counts = catalog_loader.catalog_counts()
    assert counts["catalog"] == 8
    assert counts["stars"] == 2


def test_search_text_m31(loaded_db):
    """Búsqueda libre: 'M31' encuentra la Galaxia de Andrómeda con cross-refs."""
    from planners.celestial_search import SearchFilters, search

    results = search(SearchFilters(text="M31"))
    assert results[0]["object_id"] == "M31"
    assert results[0]["ngc_num"] == 224
    assert results[0]["name"] == "Andromeda Galaxy"


def test_search_messier_catalog_sintetico(loaded_db):
    """El filtro Messier devuelve todos y solo los objetos de la fixture."""
    from planners.celestial_search import SearchFilters, search

    results = search(SearchFilters(catalogs=["messier"]), limit=200)
    ids = {row["object_id"] for row in results}
    assert len(results) == 5
    assert {"M31", "M42", "M45", "M13", "M102"} == ids
    assert all(row["messier_num"] is not None for row in results)


def test_search_magnitude_and_ordering(loaded_db):
    """Filtro de magnitud: respeta el límite y ordena desconocidas al final."""
    from planners.celestial_search import SearchFilters, search

    results = search(SearchFilters(max_magnitude=6.0), limit=500)
    assert results
    seen_unknown = False
    for row in results:
        if row["magnitude"] is None:
            seen_unknown = True
        else:
            assert row["magnitude"] <= 6.0
            assert not seen_unknown, "Objeto con magnitud tras uno sin magnitud"


def test_search_type_group(loaded_db):
    """Filtro por grupo de tipo: 'cúmulo globular' → solo código GCl."""
    from planners.celestial_search import SearchFilters, search

    results = search(SearchFilters(object_types=["cúmulo globular"]), limit=500)
    assert results
    assert all(row["type"] == "GCl" for row in results)
    assert any(row["object_id"] == "M13" for row in results)


def test_search_ra_dec_window(loaded_db):
    """Ventana de coordenadas: M42 cae dentro de su propia ventana."""
    from planners.celestial_search import SearchFilters, search

    results = search(SearchFilters(
        min_ra_hours=5.0, max_ra_hours=6.0,
        min_dec_deg=-10.0, max_dec_deg=0.0,
    ), limit=500)
    ids = {row["object_id"] for row in results}
    assert "M42" in ids
    for row in results:
        assert 5.0 <= row["ra_hours"] <= 6.0
        assert -10.0 <= row["dec_deg"] <= 0.0


def test_get_object_and_personal_catalog_roundtrip(memory_db):
    """El catálogo personal persiste con JOIN sin tocar entradas del usuario."""
    from planners import personal_catalog
    from planners.celestial_search import get_object

    memory_db.execute(
        "INSERT INTO catalog (object_id, catalog, messier_num, magnitude)"
        " VALUES (?, ?, ?, ?)", ("M31", "messier", 31, 3.44),
    )
    obj = get_object("M31")
    assert obj is not None and obj["messier_num"] == 31

    personal_catalog.add("M31", "messier", "test temporal")
    try:
        mine = [o for o in personal_catalog.list_objects()
                if o["object_id"] == "M31"]
        assert mine and mine[0]["notes"] == "test temporal"
        assert mine[0]["magnitude"] is not None       # el JOIN aporta datos
    finally:
        personal_catalog.remove("M31", "messier")
    assert all(o["object_id"] != "M31"
               for o in personal_catalog.list_objects())


def test_get_object_normaliza_alias_messier_ngc_ic(memory_db):
    """P-0007: los alias de designación resuelven, no solo la forma exacta.

    La designación canónica es 'M31'/'IC 1'; el usuario escribe 'm31',
    'ngc224' o con espacios sobrantes y debe encontrar el mismo objeto. El
    alias NGC busca por número, así que devuelve el objeto que lo usa.
    """
    from planners.celestial_search import get_object

    memory_db.executemany(
        "INSERT INTO catalog (object_id, catalog, messier_num, ngc_num,"
        " ic_num, magnitude) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("M31", "messier", 31, 224, None, 3.44),
            ("IC 1", "ic", None, None, 1, 9.0),
        ],
    )

    for alias in ("m31", "M 31", "  M31  "):
        assert (get_object(alias) or {}).get("object_id") == "M31"
    for alias in ("ngc224", "NGC 224", "NGC  0224"):   # cross-reference de M31
        assert (get_object(alias) or {}).get("object_id") == "M31"
    for alias in ("ic1", "IC 1", "Ic 001"):
        assert (get_object(alias) or {}).get("object_id") == "IC 1"
    assert get_object("M 999") is None       # número inexistente
    assert get_object("XYZ 1") is None       # prefijo desconocido no rompe


def test_personal_catalog_regions(memory_db):
    """Las regiones guardan centro/encuadre en una BD aislada."""
    from planners import personal_catalog

    name = "Mosaico test"
    personal_catalog.add_region(
        name, ra_hours=9.5, dec_deg=65.0,
        fov_major_arcmin=150.0, fov_minor_arcmin=100.0, tiles_x=3, tiles_y=2,
        notes="prueba",
    )
    try:
        regions = [o for o in personal_catalog.list_objects() if o["object_id"] == name]
        assert regions
        region = regions[0]
        assert region["kind"] == "region" and region["catalog"] == "region"
        assert region["ra_hours"] == pytest.approx(9.5)
        assert region["dec_deg"] == pytest.approx(65.0)
        assert region["fov_major_arcmin"] == pytest.approx(150.0)
        assert (region["tiles_x"], region["tiles_y"]) == (3, 2)
        assert region["name"] is None                  # no está en el catálogo global
    finally:
        personal_catalog.remove(name, "region")
    assert all(o["object_id"] != name for o in personal_catalog.list_objects())


def test_personal_catalog_object_and_region_same_name_do_not_clash(memory_db):
    """Objeto y región con el mismo nombre conviven en una BD aislada."""
    from planners import personal_catalog

    memory_db.execute(
        "INSERT INTO catalog (object_id, catalog, magnitude) VALUES (?, ?, ?)",
        ("M31", "messier", 3.44),
    )
    personal_catalog.add("M31", "messier", "objeto")
    personal_catalog.add_region("M31", ra_hours=1.0, dec_deg=2.0)
    try:
        mine = [o for o in personal_catalog.list_objects() if o["object_id"] == "M31"]
        assert len(mine) == 2
        by_catalog = {o["catalog"]: o for o in mine}
        assert by_catalog["messier"]["magnitude"] is not None   # JOIN resuelve
        assert by_catalog["region"]["kind"] == "region"
    finally:
        personal_catalog.remove("M31", "messier")
        personal_catalog.remove("M31", "region")


def test_migra_notes_en_personal_catalog():
    """M-21: una base antigua recibe la columna ``notes`` al abrir.

    El esquema la crea y el INSERT la usa, pero `_MIGRATIONS` no la
    traía: en una base creada antes, guardar notas fallaba lejos del
    origen del error.
    """
    import sqlite3

    from db import connection as db_conn

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE personal_catalog ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " object_id TEXT NOT NULL,"
        " catalog TEXT NOT NULL DEFAULT 'messier')"
    )

    db_conn.init_db(conn)  # schema (IF NOT EXISTS → no toca la tabla) + migración

    columnas = {row[1] for row in conn.execute("PRAGMA table_info(personal_catalog)")}
    assert "notes" in columnas
    assert "kind" in columnas          # la migración vieja sigue funcionando
    assert "fov_major_arcmin" in columnas
    conn.close()


def test_planned_session_parameters_roundtrip(memory_db):
    """Guarda y actualiza una sesión en memoria sin tocar planes del usuario."""
    from planners import planned_sessions

    session_id = planned_sessions.add(
        "M31", "M31 noche 1", "2026-10-15",
        planned_exposure_s=300, target_kind="region",
        ra_hours=9.5, dec_deg=65.0,
        fov_major_arcmin=150.0, fov_minor_arcmin=100.0,
        tiles_x=3, tiles_y=2, notes="primera prueba",
    )
    try:
        stored = [s for s in planned_sessions.list_sessions() if s["id"] == session_id][0]
        assert stored["target_kind"] == "region"
        assert stored["ra_hours"] == pytest.approx(9.5)
        assert stored["fov_major_arcmin"] == pytest.approx(150.0)
        assert (stored["tiles_x"], stored["tiles_y"]) == (3, 2)
        assert stored["notes"] == "primera prueba"
        assert stored["status"] == "planificada"

        planned_sessions.update_session(
            session_id, notes="revisada", planned_exposure_s=600,
            status="completada", no_existe="se ignora",
        )
        updated = [s for s in planned_sessions.list_sessions() if s["id"] == session_id][0]
        assert updated["notes"] == "revisada"
        assert updated["planned_exposure_s"] == 600
        assert updated["status"] == "completada"
        assert "no_existe" not in updated              # columna desconocida: fuera
    finally:
        planned_sessions.delete_session(session_id)
    assert all(s["id"] != session_id for s in planned_sessions.list_sessions())


def test_search_by_constellation_and_altitude(loaded_db):
    """Filtro por constelación (código IAU) y por altitud mínima de culminación."""
    from planners.celestial_search import CONSTELLATIONS, SearchFilters, search

    results = search(SearchFilters(constellation="Ori"), limit=100)
    assert results and all(r["constellation"] == "Ori" for r in results)
    assert any(r["object_id"] == "M42" for r in results)
    assert CONSTELLATIONS["Ori"] == "Orión"           # nombre en español para la UI

    # Altitud mínima → ventana de declinación: 90 - |lat - dec| >= 30
    latitude = 40.4
    limited = search(SearchFilters(min_altitude=30.0, latitude=latitude), limit=200)
    assert limited
    for row in limited:
        assert 90.0 - abs(latitude - row["dec_deg"]) >= 30.0


def test_search_annotates_analytical_transit(loaded_db):
    """Con latitud, cada fila trae altura máxima, tránsito local y horas >30°."""
    from planners.celestial_search import SearchFilters, search

    rows = search(SearchFilters(
        text="M42", latitude=40.4, longitude=-3.7, date_iso="2026-10-02",
    ))
    m42 = next(row for row in rows if row["object_id"] == "M42")
    assert m42["max_altitude"] == pytest.approx(44.2, abs=0.1)
    assert 0.0 <= m42["hours_above_30"] <= 24.0
    assert 0 <= int(m42["transit_local"].split(":")[0]) <= 23   # 'HH:MM'

    # Sin latitud no hay tránsito (la UI deja las columnas vacías)
    plain = search(SearchFilters(text="M42"))
    assert plain[0]["transit_local"] is None
    assert plain[0]["max_altitude"] is None


def test_search_transit_sin_fecha_y_sin_coordenadas():
    """M-24: sin ``date_iso`` no se inventa fecha; fila incompleta no revienta.

    Antes ``date_iso=None`` caía en «2026-01-01» (fecha mágica que
    devolvía horas de tránsito sin fundamento) y una fila sin ``ra_hours``
    lanzaba ``TypeError`` dentro de ``search()``.
    """
    from planners.celestial_search import SearchFilters, _annotate_transit

    filtros = SearchFilters(latitude=40.4, longitude=-3.7, utc_offset_hours=2.0)
    filas = [
        {"ra_hours": 5.588, "dec_deg": -5.39},   # completo
        {"ra_hours": None, "dec_deg": 20.0},     # sin RA
        {"ra_hours": 10.0, "dec_deg": None},     # sin dec
    ]

    _annotate_transit(filas, filtros)

    assert filas[0]["max_altitude"] is not None  # la altitud no necesita fecha
    assert filas[0]["transit_local"] is None     # …la hora local sí: sin fecha, vacía
    assert filas[0]["hours_above_30"] is not None
    assert filas[1]["max_altitude"] is None      # sin RA: nada es calculable
    assert filas[1]["transit_local"] is None
    assert filas[2]["max_altitude"] is None      # sin dec: idem

    filtros.date_iso = "2026-10-03"
    _annotate_transit(filas, filtros)

    assert filas[0]["transit_local"] is not None  # con fecha, calculada
    assert ":" in filas[0]["transit_local"]
    assert filas[1]["transit_local"] is None      # la fila sin RA sigue vacía


def test_search_transit_column_uses_the_location_offset(loaded_db):
    """La columna Tránsito es hora de reloj si la ubicación guarda desfase.

    Sin ``utc_offset_hours`` se infiere el huso de la longitud
    (round(lon/15)); con +2 guardado adelanta exactamente
    ``2 − round(longitud/15)``. Las horas >30° no cambian: son duración,
    no un instante.
    """
    from planners.celestial_search import SearchFilters, search

    base = dict(text="M42", latitude=40.4, longitude=-3.7, date_iso="2026-10-02")
    solar = next(r for r in search(SearchFilters(**base)) if r["object_id"] == "M42")
    clock = next(
        r for r in search(SearchFilters(**base, utc_offset_hours=2.0))
        if r["object_id"] == "M42"
    )

    delta = (_hhmm(clock["transit_local"]) - _hhmm(solar["transit_local"])) % 24.0
    expected = (2.0 - round(base["longitude"] / 15.0)) % 24.0
    assert delta == pytest.approx(expected, abs=0.02)
    assert clock["hours_above_30"] == solar["hours_above_30"]


def _hhmm(text: str) -> float:
    """'23:45' → 23.75 horas decimales."""
    hours, minutes = text.split(":")
    return int(hours) + int(minutes) / 60.0


def test_search_sort_by_size_and_name(loaded_db):
    """Orden por tamaño (de mayor a menor) y por designación alfabética."""
    from planners.celestial_search import SearchFilters, search

    by_size = search(SearchFilters(object_types=["galaxia"], sort_by="size"), limit=50)
    sizes = [r["size_major_arcmin"] for r in by_size if r["size_major_arcmin"]]
    assert sizes == sorted(sizes, reverse=True)

    by_name = search(SearchFilters(catalogs=["messier"], sort_by="name"), limit=200)
    names = [r["object_id"] for r in by_name]
    assert names == sorted(names)


def test_search_transit_limit_no_ventana_de_magnitud(memory_db):
    """P-0005: el límite se aplica tras ordenar por tránsito, no antes.

    El ``LIMIT`` corría en SQL sobre el orden por magnitud y el reordenado
    por tránsito llegaba tarde: con «Tránsito» y límite 2 se veían M31 y
    M42 (los dos más brillantes) en lugar de M31 y M1 (los dos cuya
    culminación cae antes). El tránsito local es el mismo para todos.
    """
    from planners.celestial_search import SearchFilters, search

    memory_db.executemany(
        "INSERT INTO catalog (object_id, catalog, messier_num, name, type,"
        " magnitude, ra_hours, dec_deg, constellation)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("M31", "messier", 31, "Andromeda Galaxy", "G", 3.44, 0.712, 41.27, "And"),
            ("M42", "messier", 42, "Orion Nebula", "Neb", 4.0, 8.76, -5.39, "Ori"),
            ("M1", "messier", 1, "Crab Nebula", "Neb", 8.4, 5.575, 22.02, "Tau"),
        ],
    )
    filtros = SearchFilters(
        catalogs=["messier"], sort_by="transit",
        latitude=40.4, longitude=-3.7, date_iso="2026-10-02", utc_offset_hours=2.0,
    )

    filas = search(filtros, limit=2)

    # M31 (02:14) y M1 (07:05) antes que M42 (10:16), pese a que M1 es la
    # más tenue de las tres y el orden por magnitud la dejaba fuera.
    assert [fila["object_id"] for fila in filas] == ["M31", "M1"]


# ------------------------------------------------------------------ tránsito
def test_night_info_winter_madrid():
    """Invierno en Madrid: noche astronómica larga y fase entre 0 y 1."""
    from planners.transit import night_info

    night = night_info(40.4, -3.7, "2026-01-01")
    assert night.astronomical_dusk is not None
    assert night.astronomical_dawn is not None
    assert 8.0 < night.astronomical_hours < 14.0
    assert 0.0 <= night.moon_illumination <= 1.0
    assert night.moon_phase == night.moon_illumination


def test_night_info_arctic_summer_has_no_astronomical_night():
    """Latitud 60° en junio: el sol no baja de -18° (noche blanca)."""
    from planners.transit import night_info

    night = night_info(60.0, 25.0, "2026-06-21")
    assert night.astronomical_hours == 0.0
    assert night.astronomical_dusk is None
    assert night.astronomical_dawn is None


def test_night_info_carries_sunset_sunrise_and_moon_age():
    """Puesta/salida de sol y edad lunar coherente con la iluminación."""
    from planners.transit import SYNODIC_PERIOD_DAYS, night_info

    night = night_info(40.4, -3.7, "2026-10-02")
    assert night.sunset is not None and night.sunrise is not None
    assert night.sunset < night.sunrise          # la noche empieza con la puesta

    # Edad dentro de un período sinódico y bandera de fase a partir de ella
    assert 0.0 <= night.moon_age_days < SYNODIC_PERIOD_DAYS
    assert night.waxing is (night.moon_age_days < SYNODIC_PERIOD_DAYS / 2.0)

    # Verificado a mano: Madrid, 2026-10-02 → luna menguante de ~56 % y ~21 d
    assert night.moon_age_days == pytest.approx(21.2, abs=0.3)
    assert night.moon_illumination == pytest.approx(0.56, abs=0.05)
    assert night.waxing is False


def test_night_curve_hour_axis_follows_the_location_offset():
    """El eje horario respeta ``utc_offset_hours``; la física no cambia.

    Sin desfase guardado se infiere el huso de la longitud (round(lon/15));
    con +2 guardado la misma culminación se lee a la hora de reloj. La
    ventana temporal también se desplaza (arranca a las 16:00 hora local),
    por eso se comprueba el pico de altitud contra la culminación analítica
    en vez de comparar instantes uno a uno.
    """
    from planners.analytical_transit import transit_local_hours
    from planners.transit import night_curve

    ra, dec, lat, lon = 5.588139, -5.391111, 40.4, -3.7
    clock = night_curve(ra, dec, lat, lon, "2026-10-02", utc_offset_hours=2.0)
    solar = night_curve(ra, dec, lat, lon, "2026-10-02")

    assert len(clock.hours_local) == len(solar.hours_local)
    assert len(clock.altitudes) == len(clock.hours_local)
    assert 0.0 <= clock.moon_illumination <= 1.0

    for curve, offset in ((clock, 2.0), (solar, None)):
        expected = transit_local_hours(ra, "2026-10-02", lon, utc_offset_hours=offset)
        peak = curve.hours_local[curve.transit_index]
        diff = abs((peak - expected + 12.0) % 24.0 - 12.0)
        # Culminación analítica (<10 min) + pico cuantizado a la malla
        assert diff < 0.15, f"pico {peak:.2f} vs esperado {expected:.2f}"


def test_night_curve_samples_every_minute():
    """La malla es de 1 min para que las ventanes no se redondeen.

    Las horas y duraciones de Captura Ideal/Posible salen de los
    instantes de esta malla (ver ``capture_window_summary``): con un
    paso de 10 min todo caía en múltiplos de 10 (21:20, 21:30, 3h 30min)
    en vez de minutos reales (21:22, 3h 32min). Regresión: si alguien
    vuelve a subir el paso, la UI vuelve a mostrar horas redondas.
    """
    from planners.transit import night_curve

    curve = night_curve(5.588139, -5.391111, 40.4, -3.7, "2026-10-02")
    deltas = [
        b - a
        for a, b in zip(curve.hours_local, curve.hours_local[1:], strict=False)
        if b > a  # el salto de medianoche da delta negativo
    ]
    assert min(deltas) == pytest.approx(1.0 / 60.0, abs=1e-9)


def test_night_curve_keeps_the_space_separated_iso_format():
    """``times_iso`` sigue en formato 'AAAA-MM-DD HH:MM:SS.mmm'.

    Se vectorizó con ``times.iso`` en vez de ``[str(t.iso) for t in
    times]`` (misma salida, verificado bit a bit) para no visitar el
    mecanismo de atributos de ``Time`` ~1000 veces. Si alguien lo cambia
    a ``.isot``, la fecha llevará «T» y la UI la leerá mal.
    """
    from planners.transit import night_curve

    curve = night_curve(0.677, 23.0, 10.0, -85.4, "2026-10-02", -6.0)
    # arranque de la malla: 16:00 local con huso −6 ⇒ 22:00 UTC
    assert curve.times_iso[0] == "2026-10-02 22:00:00.000"
    assert len(curve.times_iso) == len(curve.altitudes)


def test_moon_and_sun_are_cached_per_date_and_location():
    """La Luna y el sol se cachean por (fecha, ubicación, desfase).

    No dependen del objeto, así que al cambiar de objetivo se reutilizan
    (de 0,84 s a 0,11 s medido). Ojo: si la clave se quedara sin la
    fecha o la ubicación, daría lunas de otro día.
    """
    from planners import transit

    transit._MOON_SUN_CACHE.clear()
    base = transit.night_curve(5.588139, -5.391111, 40.4, -3.7, "2026-10-02", 2.0)
    assert len(transit._MOON_SUN_CACHE) == 1
    again = transit.night_curve(5.588139, -5.391111, 40.4, -3.7, "2026-10-02", 2.0)
    assert len(transit._MOON_SUN_CACHE) == 1  # reutiliza, no duplica
    assert again.moon_altitudes == base.moon_altitudes
    assert again.astro_night == base.astro_night
    assert again.moon_illumination == base.moon_illumination

    # otra fecha o desfase es otra entrada
    transit.night_curve(5.588139, -5.391111, 40.4, -3.7, "2026-10-02", 0.0)
    transit.night_curve(5.588139, -5.391111, 40.4, -3.7, "2026-10-03", 2.0)
    assert len(transit._MOON_SUN_CACHE) == 3


def test_moon_and_sun_cache_is_bounded():
    """La caché no crece sin límite: como mucho, las últimas 8 entradas."""
    from planners import transit

    transit._MOON_SUN_CACHE.clear()
    for index in range(transit._MOON_SUN_CACHE_MAX + 3):
        transit._remember_moon_sun((index,), (index,))
    assert len(transit._MOON_SUN_CACHE) == transit._MOON_SUN_CACHE_MAX
    assert (0,) not in transit._MOON_SUN_CACHE  # las más viejas se caen
    assert (transit._MOON_SUN_CACHE_MAX + 2,) in transit._MOON_SUN_CACHE


def test_moon_sun_coarse_sampling_stays_within_hundredths_of_a_degree():
    """La Luna/sol a paso grueso + interpolación no desvía el cálculo.

    La Luna y el sol se calculan cada ``MOON_SUN_SAMPLE_MIN`` minutos y
    se interpolan a la malla de 1 min en coordenadas rectangulares (4,5×
    más rápido: 0,62 s → 0,14 s). Aquí se fija el techo del error: si
    alguien sube el paso o interpola en azimut en vez de en x/y/z (el
    azimut da vueltas de 180° al pasar por el cenit), se dispara.
    """
    import astropy.units as u
    import numpy as np
    from astropy.coordinates import AltAz, SkyCoord, angular_separation

    from planners import transit

    loc = transit._location(40.4, -3.7)
    times = transit._night_times("2026-10-02", -3.7, utc_offset_hours=2.0)
    exact_az, exact_alt, exact_sun = transit._moon_sun_arrays(times, loc)
    coarse_az, coarse_alt, coarse_sun = transit._moon_sun_series(times, loc)

    assert np.max(np.abs(coarse_alt - exact_alt)) < 0.02
    assert np.max(np.abs(coarse_sun - exact_sun)) < 0.02

    frame = AltAz(obstime=times, location=loc)
    target = SkyCoord(
        ra=5.588139 * u.hourangle, dec=-5.391111 * u.deg, frame="icrs"
    ).transform_to(frame)
    sep_exact = angular_separation(
        target.az, target.alt, exact_az * u.deg, exact_alt * u.deg
    ).to_value(u.deg)
    sep_coarse = angular_separation(
        target.az, target.alt, coarse_az * u.deg, coarse_alt * u.deg
    ).to_value(u.deg)
    assert np.max(np.abs(sep_coarse - sep_exact)) < 0.02

    # los bordes de la noche astronómica no se mueven
    edges = lambda sun: np.flatnonzero(
        np.diff((sun < transit.ASTRO_TWILIGHT_DEG).astype(int))
    ).tolist()
    assert edges(coarse_sun) == edges(exact_sun)


def test_transit_m42_madrid():
    """M42 en Madrid en enero: culmina a ~44° (altura teórica máxima)."""
    from planners.transit import transit_info

    info = transit_info(5.588139, -5.391111, 40.4, -3.7, "2026-01-01")
    assert info.transit_time is not None
    assert 40.0 <= info.altitude_deg <= 45.0
    assert 0.0 <= info.separation_moon_deg <= 180.0
    assert len(info.hour_altitudes) > 50
    alts = [alt for _iso, alt in info.hour_altitudes]
    assert max(alts) == pytest.approx(info.altitude_deg, abs=0.1)


# ------------------------------------------------------------------ ranking
def test_rank_objects_orders_and_explains():
    """El ranking ordena de mayor a menor y explica cada puntuación."""
    from planners.ranking import rank_objects
    from planners.transit import NightInfo, TransitInfo

    night = NightInfo("2026-01-01 18:00", "2026-01-02 06:00", 10.5, 0.3, 0.3)
    candidates = [
        {"object_id": "Alto", "transit": TransitInfo("t", 80.0, 70.0, [])},
        {"object_id": "Bajo", "transit": TransitInfo("t", 20.0, 5.0, [])},
    ]
    ranked = rank_objects(candidates, night)

    assert [item.object_id for item in ranked] == ["Alto", "Bajo"]
    assert 0.0 <= ranked[0].score <= 100.0
    assert ranked[0].reasons
    assert all(item.astronomical_hours == 10.5 for item in ranked)
    # El objeto a 5° de la luna debe salir advertido
    assert any("Cerca de la luna" in reason
               for item in ranked for reason in item.reasons)


def test_rank_weights_are_user_configurable():
    """Cambiar los pesos cambia el orden: la métrica la decide el usuario."""
    from planners.ranking import RankingWeights, rank_objects
    from planners.transit import NightInfo, TransitInfo

    night = NightInfo(None, None, 10.0, 0.5, 0.5)
    candidates = [
        {"object_id": "A", "transit": TransitInfo("t", 85.0, 5.0, [])},
        {"object_id": "B", "transit": TransitInfo("t", 30.0, 80.0, [])},
    ]
    alt_weights = RankingWeights(altitude=90, moon_separation=5, weather=5)
    moon_weights = RankingWeights(altitude=5, moon_separation=90, weather=5)

    assert rank_objects(candidates, night, weights=alt_weights)[0].object_id == "A"
    assert rank_objects(candidates, night, weights=moon_weights)[0].object_id == "B"


def test_rank_includes_weather_when_available():
    """Con clima, el factor entra en la puntuación; sin él, se renormaliza."""
    from planners.ranking import rank_objects
    from planners.transit import NightInfo, TransitInfo

    night = NightInfo(None, None, 10.0, 0.5, 0.5)
    clear = [{"object_id": "X", "transit": TransitInfo("t", 50.0, 50.0, [])}]
    weather_clear = rank_objects(clear, night, weather={"cloud_cover": 0})
    weather_cloudy = rank_objects(clear, night, weather={"cloud_cover": 100})
    weather_none = rank_objects(clear, night, weather=None)

    assert weather_clear[0].score > weather_cloudy[0].score
    assert weather_none[0].score > weather_cloudy[0].score
    assert weather_none[0].score <= 100.0


# ---------------------------------------------------------------- night_info
def test_night_info_usa_el_huso_guardado():
    """M-07: ``night_info`` centra su ventana con el huso, como ``night_curve``.

    Caso del usuario (lon 85,4 con huso −6, muy distinto del inferido):
    las efemérides y la curva tienen que verse la misma noche astronómica.
    """
    from planners.transit import night_curve, night_info

    lat, lon, fecha, huso = 40.0, 85.4, "2026-10-02", -6.0
    info = night_info(lat, lon, fecha, utc_offset_hours=huso)
    curve = night_curve(6.0, 20.0, lat, lon, fecha, utc_offset_hours=huso)

    # Tramo continuo más largo de la curva (misma malla, mismo sol)
    tramos: list[int] = []
    actual = 0
    for esta in curve.astro_night:
        if esta:
            actual += 1
        elif actual:
            tramos.append(actual)
            actual = 0
    if actual:
        tramos.append(actual)

    assert tramos  # hay noche esa madrugada
    assert info.astronomical_hours == pytest.approx(max(tramos) / 60.0, abs=0.03)
    # Regresión: antes «cubrir el rango» contaba el día entre medias
    # (16,02 h) y dawn salía como final de la ventana (14:00).
    assert info.astronomical_hours < 5.0
    assert info.astronomical_dawn != "2026-10-03 14:00:00.000"


def test_night_info_reutiliza_iluminacion_cacheada(monkeypatch):
    """M-09: la iluminación que guardó ``night_curve`` no se recalcula."""
    from planners import transit

    monkeypatch.setattr(transit, "_MOON_SUN_CACHE", {})
    transit._remember_moon_sun(
        (40.4, -3.7, "2026-10-02", 2.0, ("legacy", "builtin")), (None, None, None, 0.42)
    )

    info = transit.night_info(40.4, -3.7, "2026-10-02", utc_offset_hours=2.0)

    assert info.moon_illumination == pytest.approx(0.42)


# ---------------------------------------------------------------- sky_loader
def _sky_connection() -> "object":
    """Conexión en memoria con las tablas que lee ``sky_loader``."""
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE stars (name TEXT, magnitude REAL, ra_hours REAL,"
        " dec_deg REAL, color TEXT, constellation TEXT);"
        "CREATE TABLE catalog (id INTEGER PRIMARY KEY, object_id TEXT, catalog TEXT, messier_num INTEGER,"
        " ngc_num INTEGER, name TEXT, type TEXT, magnitude REAL, ra_hours REAL,"
        " dec_deg REAL, size_major_arcmin REAL, size_minor_arcmin REAL,"
        " constellation TEXT);"
        "INSERT INTO stars VALUES ('Alfa', 1.5, 5.0, 20.0, 'A', 'Ori');"
        "INSERT INTO stars VALUES ('Beta', NULL, 6.0, -10.0, 'K', 'Ori');"
        "INSERT INTO catalog VALUES (NULL, 'M42', 'messier', 42, 42, 'Nebulosa',"
        " 'gas', 4.0, 5.5, -5.0, 85.0, 60.0, 'Ori');"
        "INSERT INTO catalog VALUES (NULL, 'SIN RA', 'ngc', NULL, 999, NULL,"
        " 'other', NULL, NULL, NULL, NULL, NULL, 'Ori');"
    )
    return conn


def test_sky_loader_convierte_y_filtra(monkeypatch):
    """Regresión M-13: los datos del planetario salen de ``planners/``.

    RA en horas → grados, magnitud desconocida → 99 y objetos sin
    coordenadas excluidos (mismo comportamiento que antes del traslado).
    """
    import numpy as np

    from planners import sky_loader

    conn = _sky_connection()
    monkeypatch.setattr(sky_loader, "get_connection", lambda: conn)

    stars = sky_loader.load_stars()
    # ORDER BY magnitude pone los NULL primero: Beta (mag NULL) va delante.
    assert len(stars["ra"]) == 2
    assert stars["ra"].tolist() == pytest.approx([90.0, 75.0])  # 6 h → 90°, 5 h → 75°
    assert stars["dec"].tolist() == pytest.approx([-10.0, 20.0])
    assert stars["mag"].tolist() == pytest.approx([99.0, 1.5])  # NULL → 99
    assert stars["spect"] == ["K", "A"]

    objects = sky_loader.load_objects()
    assert objects["ids"] == ["M42"]               # sin RA/Dec se excluye
    assert objects["ra"][0] == pytest.approx(82.5)  # 5,5 h → 82,5°
    assert objects["catalogs"] == ["messier"]
    assert isinstance(stars["ra"], np.ndarray)
    conn.close()


def test_sky_loader_tablas_vacias(monkeypatch):
    """Tablas vacías → arrays vacíos (la UI pinta el cielo sin datos)."""
    from planners import sky_loader

    conn = _sky_connection()
    conn.execute("DELETE FROM stars")
    conn.execute("DELETE FROM catalog")
    monkeypatch.setattr(sky_loader, "get_connection", lambda: conn)

    stars = sky_loader.load_stars()
    objects = sky_loader.load_objects()
    assert len(stars["ra"]) == 0 and len(stars["mag"]) == 0
    assert len(objects["ra"]) == 0 and objects["ids"] == []
    conn.close()


def test_ensure_catalog_revierte_el_delete_si_falla(monkeypatch):
    """M-10: un fallo tras el DELETE no deja la transacción abierta.

    Sin ``rollback``, el borrado quedaría pendiente y el próximo commit
    de cualquier otro módulo lo consignaría: catálogo vacío en la base.
    """
    import sqlite3

    from planners import catalog_loader

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE catalog (object_id TEXT, catalog TEXT, magnitude REAL,"
        " ra_hours REAL, dec_deg REAL);"
        "CREATE TABLE stars (name TEXT, magnitude REAL, ra_hours REAL,"
        " dec_deg REAL, color TEXT, constellation TEXT);"
        "INSERT INTO catalog VALUES ('M42', 'messier', 4.0, 5.5, -5.4);"
    )
    monkeypatch.setattr(catalog_loader, "get_connection", lambda: conn)

    def carga_rota():
        """Sustituto de `load_catalog`: empieza a escribir y luego falla (disco lleno)."""
        conn.execute("DELETE FROM catalog")
        raise OSError("disco lleno")

    monkeypatch.setattr(catalog_loader, "load_catalog", carga_rota)
    counts = catalog_loader.ensure_catalog(force=True)

    # El DELETE quedó sin consignar: la fila sigue viva…
    assert conn.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] == 1
    # …y un commit posterior de otro módulo tampoco la borra.
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM catalog").fetchone()[0] == 1
    assert counts["catalog"] == 1
    conn.close()


def test_phase_name_y_transparency_son_reglas_de_negocio():
    """Fases lunares y transparencia cualitativa viven en planners (A-31).

    Antes eran helpers de `ui/planner_tab/widgets.py`; la UI solo importa.
    """
    from planners.transit import phase_name
    from planners.weather.base import transparency

    assert phase_name(0.01, True) == "Luna nueva"
    assert phase_name(0.5, True) == "Cuarto creciente"
    assert phase_name(0.5, False) == "Cuarto menguante"
    assert phase_name(1.0, True) == "Luna llena"

    assert transparency(None) == "--"
    assert transparency(10) == "Excelente"
    assert transparency(20) == "Buena"
    assert transparency(45) == "Regular"
    assert transparency(90) == "Mala"
