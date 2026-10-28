"""Zone recognition from the listing location text (research R10)."""
import pytest

from app import zones

# Location texts as they appear in the fixtures' title links, with the municipality each names.
FIXTURE_LOCATIONS = {
    "Carretera de Brunete a el Escorial s/n, Brunete": ("brunete", "Brunete"),
    "Calle Ajalvir, 2, Daganzo de Arriba": ("daganzo-de-arriba", "Daganzo de Arriba"),
    "Calle Cuenca, 24, Villalbilla": ("villalbilla", "Villalbilla"),
    "Valle Del Cabriel, 36, Suroeste, Torrejón de Ardoz": ("torrejon-de-ardoz", "Torrejón de Ardoz"),
    "Calle Brigadas Internacionales, 63, El Pilar - Bripac, Alcalá de Henares": ("alcala-de-henares", "Alcalá de Henares"),
    "Calle Toledo, Val, Alcalá de Henares": ("alcala-de-henares", "Alcalá de Henares"),
    "Calle del Pico de San Pedro, Zona Industrial, Tres Cantos": ("tres-cantos", "Tres Cantos"),
    "Calle Pablo Neruda, Algete": ("algete", "Algete"),
    "Sector 3, Getafe": ("getafe", "Getafe"),
    "Calle Quebrantarrejas, Altos de Jarama, Paracuellos de Jarama": ("paracuellos-de-jarama", "Paracuellos de Jarama"),
    "Mejorada del Campo": ("mejorada-del-campo", "Mejorada del Campo"),
}


@pytest.fixture
def aliases(tmp_path, monkeypatch):
    path = tmp_path / "zone_aliases.yaml"
    monkeypatch.setattr(zones, "ALIASES_PATH", path)
    return path


@pytest.mark.parametrize("text", sorted(FIXTURE_LOCATIONS))
def test_fixture_municipalities_resolve(text, aliases):
    zone_id, municipality = FIXTURE_LOCATIONS[text]
    assert zones.match_zone(text) == (zone_id, municipality, None)


def test_madrid_district_resolves(aliases):
    assert zones.match_zone("Calle de Fuencarral, Chamberí, Madrid") == ("madrid/chamberi", "Madrid", "Chamberí")


def test_madrid_barrio_is_not_recognised(aliases):
    assert zones.match_zone("alto de San Isidro, San Isidro, Madrid") == (None, None, None)


def test_alias_makes_it_resolve(aliases):
    aliases.write_text('"alto de San Isidro, San Isidro, Madrid": madrid/carabanchel\n', encoding="utf-8")
    assert zones.match_zone("alto de San Isidro, San Isidro, Madrid") == ("madrid/carabanchel", "Madrid", "Carabanchel")


def test_two_municipalities_is_not_recognised(aliases):
    assert zones.match_zone("Getafe, Alcalá de Henares") == (None, None, None)


def test_unknown_or_empty_is_not_recognised(aliases):
    assert zones.match_zone("Calle Mayor, Toledo") == (None, None, None)
    assert zones.match_zone(None) == (None, None, None)


def test_ine_article_suffix_is_matched_in_reading_order(aliases):
    # INE writes "Rozas de Madrid, Las"; a listing text says "Las Rozas de Madrid".
    assert zones.match_zone("Calle Real, Las Rozas de Madrid") == ("las-rozas-de-madrid", "Las Rozas de Madrid", None)


def test_match_creates_zone_row(conn, aliases):
    zones.match_zone("Sector 3, Getafe", conn)
    row = conn.execute("SELECT name, municipality, level FROM zones WHERE zone_id='getafe'").fetchone()
    assert tuple(row) == ("Getafe", "Getafe", "municipio")
