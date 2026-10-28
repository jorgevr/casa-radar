"""Idealista alert reader against the 12 anonymised fixtures (contracts/alert-reader.md, research R9).

Expected values were read by hand from each fixture's HTML (subject, title link, card price,
struck-through previous price, "ha bajado de … a …" sentence, attribute line, description).
"""
import email
from dataclasses import asdict
from email import policy
from pathlib import Path

import pytest

from app.providers import idealista_alert as reader

EMAILS = Path(__file__).parent / "fixtures" / "emails"
NO_ATTRS = {"area_m2": None, "bedrooms": None, "floor": None, "exterior": None, "elevator": None, "garage": None}


def _msg(code: str):
    path = next(EMAILS.glob(f"*_{code}.eml"))
    return email.message_from_bytes(path.read_bytes(), policy=policy.default)


def _resale(code, type_text, property_type, location, price, area, bedrooms, previous_price=None, **attrs):
    return {
        "listing_code": code, "price": price, "previous_price": previous_price,
        **NO_ATTRS, "area_m2": area, "bedrooms": bedrooms, **attrs,
        "type_text": type_text, "property_type": property_type, "development": False,
        "unit_description": None, "new_build_stated": None, "location_text": location,
        "link_direct": f"https://www.idealista.com/inmueble/{code}/",
    }


def _development(code, location, price, description):
    return {
        "listing_code": code, "price": price, "previous_price": None, **NO_ATTRS,
        "type_text": "Promoción", "property_type": None, "development": True,
        "unit_description": description, "new_build_stated": True, "location_text": location,
        "link_direct": f"https://www.idealista.com/obra-nueva/{code}/",
    }


FLAT_ATTRS = {"exterior": True, "elevator": True, "garage": True}
VIVIENDAS = "Viviendas en tu zona personalizada"
CHALETS = "chalets en tu zona personalizada"
OBRA_NUEVA = "Obra nueva en tu zona personalizada"

EXPECTED = {
    "112038902": ("new_listing", OBRA_NUEVA, _development(
        "112038902", "Calle Ajalvir, 2, Daganzo de Arriba", 270_000,
        "Alcala Inmobiliaria se complace en presentar esta exclusiva promoción de obra nueva compuesta "
        "por 31 viviendas únicas (10 acogedores bajos, 5 espectaculares chalets, 4 amplios átic...")),
    "112882173": ("new_listing", OBRA_NUEVA, _development(
        "112882173", "Carretera de Brunete a el Escorial s/n, Brunete", 481_844,
        "BRUNETE FUTURO Una nueva forma de vivir en Brunete: 6 viviendas unifamiliares con jardín privado "
        "Te presentamos el nuevo proyecto de 6 viviendas unifamiliares en régimen de coope...")),
    "112658090": ("price_drop", VIVIENDAS, _resale(
        "112658090", "Piso", "piso", "Calle del Pico de San Pedro, Zona Industrial, Tres Cantos",
        650_000, 166, 4, previous_price=680_000, floor=1, **FLAT_ATTRS)),
    "112692121": ("price_drop", VIVIENDAS, _resale(
        "112692121", "Chalet adosado", "adosado",
        "Calle Brigadas Internacionales, 63, El Pilar - Bripac, Alcalá de Henares",
        640_000, 296, 6, previous_price=650_000)),
    "112887282": ("new_listing", VIVIENDAS, _resale(
        "112887282", "Casa o chalet independiente", "chalet", "Calle Cuenca, 24, Villalbilla", 595_000, 365, 6)),
    "112890492": ("new_listing", VIVIENDAS, _resale(
        "112890492", "Chalet pareado", "pareado", "Calle Pablo Neruda, Algete", 505_000, 249, 4)),
    "112842548": ("price_drop", CHALETS, _resale(
        "112842548", "Chalet adosado", "adosado", "Valle Del Cabriel, 36, Suroeste, Torrejón de Ardoz",
        645_000, 219, 4, previous_price=670_000)),
    "112899473": ("new_listing", CHALETS, _resale(
        "112899473", "Casa o chalet independiente", "chalet",
        "Calle Quebrantarrejas, Altos de Jarama, Paracuellos de Jarama", 649_900, 240, 6)),
    "112923327": ("new_listing", CHALETS, _resale(
        "112923327", "Chalet pareado", "pareado", "Sector 3, Getafe", 560_000, 175, 4)),
    "112921923": ("new_listing", "apartamentos en tu zona personalizada", _resale(
        "112921923", "Piso", "piso", "Calle Toledo, Val, Alcalá de Henares", 509_990, 150, 4, floor=2, **FLAT_ATTRS)),
    "112477754": ("new_listing", CHALETS, _resale(
        "112477754", "Casa o chalet independiente", "chalet", "Mejorada del Campo", 359_000, 220, 4)),
}


@pytest.mark.parametrize("code", sorted(EXPECTED))
def test_reads_fixture_exactly(code, no_network):
    alert_type, search_name, block = EXPECTED[code]
    r = reader.read(_msg(code))
    assert (r.alert_type, r.search_name, r.problems, r.notices) == (alert_type, search_name, [], [])
    assert r.reader_version == "idealista-2026.10"
    assert len(r.listings) == 1
    got = asdict(r.listings[0])
    raw_block, tracking = got.pop("raw_block"), got.pop("link_tracking")
    assert got == block
    assert code in raw_block
    campaign = "express_priceDrop_sale_" if alert_type == "price_drop" else "express_newAd_sale_"
    assert tracking.startswith(block["link_direct"] + "?") and f"utm_campaign={campaign}" in tracking


def test_2021_layout_is_unsupported(no_network):
    r = reader.read(_msg("93231141"))
    assert (r.alert_type, r.search_name, r.listings, r.problems) == (
        "unsupported", "Viviendas, tu zona personalizada", [], [])


def test_every_fixture_is_covered(fixture_emails):
    codes = {p.stem.rsplit("_", 1)[1] for p in fixture_emails}
    assert codes == set(EXPECTED) | {"93231141"}


# ── negative cases, built by editing a fixture in memory ─────────────────────
def _edited(code, old, new, count=1):
    msg = _msg(code)
    part = next(p for p in msg.walk() if p.get_content_type() == "text/html")
    html = part.get_content()
    assert old in html
    part.set_content(html.replace(old, new, count), subtype="html")
    return msg


def test_two_distinct_listing_codes_is_a_problem():
    msg = _edited("112887282", "/inmueble/112887282/", "/inmueble/999999/")
    r = reader.read(msg)
    assert r.alert_type == "new_listing" and r.listings == []
    assert [p.where for p in r.problems] == ["enlace del anuncio"]
    assert "112887282" in r.problems[0].found and "999999" in r.problems[0].found


def test_price_drop_card_price_must_match_sentence():
    msg = _edited("112692121", ">640.000 €<", ">645.000 €<")
    r = reader.read(msg)
    assert r.alert_type == "price_drop" and r.listings == []
    assert [(p.where, p.expected, p.found) for p in r.problems] == [
        ("precio de la tarjeta", '"a 640.000€"', "645.000 €")]


def test_price_drop_without_sentence_is_a_problem():
    msg = _edited("112692121", "ha bajado de 650.000€ a 640.000€", "ha cambiado")
    r = reader.read(msg)
    assert r.listings == [] and [p.where for p in r.problems] == ["frase de bajada de precio"]


def test_unrecognised_attribute_is_a_notice_not_a_problem():
    msg = _edited("112692121", "6 hab.", "6 hab.     2 baños")
    r = reader.read(msg)
    assert r.problems == [] and r.notices == ['atributo no reconocido: "2 baños"']
    assert (r.listings[0].bedrooms, r.listings[0].area_m2) == (6, 296)


def test_other_sender_is_not_an_alert():
    msg = _msg("112887282")
    msg.replace_header("From", "Alguien <someone@example.org>")
    r = reader.read(msg)
    assert (r.alert_type, r.listings, r.problems) == ("not_alert", [], [])


def test_subject_and_campaign_disagree_is_unsupported():
    msg = _msg("112887282")
    msg.replace_header("Subject", "¡Bajada de precio en tu búsqueda: Viviendas en tu zona personalizada!")
    assert reader.read(msg).alert_type == "unsupported"
