"""Idealista alert email reader (contracts/alert-reader.md, research R9).

Built only from the anonymised samples in tests/fixtures/emails/. No network, no inference: a value
not literally in the email is None, and anything unexpected is returned as a Problem with evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import parseaddr
from html.parser import HTMLParser

from ..util import to_money

READER_VERSION = "idealista-2026.10"
SENDER = "noresponder@idealista.com"
OLD_SENDERS = {"noresponder.avisos@idealista.com"}  # 2021 template: recognised, not supported

SUBJECT_RE = re.compile(r"^¡(?P<kind>.+?) en tu búsqueda: (?P<search>.+)!$")
LINK_RE = re.compile(r"^https?://www\.idealista\.com/(?P<kind>inmueble|obra-nueva)/(?P<code>\d+)/")
CAMPAIGN_RE = re.compile(r"[?&]utm_campaign=(?P<campaign>[^&]+)")
CARD_RE = re.compile(r"<!--\s*inicio inmueble\s*-->(?P<card>.*?)<!--\s*link contactar\s*-->", re.S)
PRICE_RE = re.compile(r"^\s*(?P<amount>\d{1,3}(?:\.\d{3})*)\s*€\s*$")
DROP_RE = re.compile(r"ha bajado de\s*(?P<old>\d{1,3}(?:\.\d{3})*)\s*€\s*a\s*(?P<new>\d{1,3}(?:\.\d{3})*)\s*€")

TYPE_MAP = {
    "Piso": "piso",
    "Casa o chalet independiente": "chalet",
    "Chalet adosado": "adosado",
    "Chalet pareado": "pareado",
    "Promoción": None,
}
DEVELOPMENT_TYPE = "Promoción"
# Attribute tokens seen in the samples; each pattern may appear at most once.
ATTRIBUTES = {
    "bedrooms": re.compile(r"(?<!\S)(\d+) hab\.(?!\S)"),
    "area_m2": re.compile(r"(?<!\S)(\d{1,3}(?:\.\d{3})*|\d+) m²(?!\S)"),
    "floor": re.compile(r"(?<!\S)(\d+)ª planta(?!\S)"),
    "exterior": re.compile(r"(?<!\S)exterior(?!\S)"),
    "elevator": re.compile(r"(?<!\S)con ascensor(?!\S)"),
    "garage": re.compile(r"(?<!\S)Garaje incluido(?!\S)"),
}


@dataclass
class Problem:
    where: str
    expected: str
    found: str


@dataclass
class ListingBlock:
    listing_code: str
    price: int | None
    previous_price: int | None
    area_m2: int | None
    bedrooms: int | None
    floor: int | None
    exterior: bool | None
    elevator: bool | None
    garage: bool | None
    type_text: str | None
    property_type: str | None
    development: bool
    unit_description: str | None
    new_build_stated: bool | None
    location_text: str | None
    link_tracking: str
    link_direct: str
    raw_block: str


@dataclass
class ReadResult:
    alert_type: str
    search_name: str | None = None
    listings: list[ListingBlock] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    reader_version: str = READER_VERSION


def _amount(text: str) -> int:
    return int(to_money(text))


def _excerpt(text: str, n: int = 80) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


class _Links(HTMLParser):
    """All <a href> in the email, with their title attribute."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.anchors.append((a["href"], a.get("title")))


class _Card(HTMLParser):
    """Texts of the listing card: prices (struck-through or not), attribute line, description."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.spans: list[bool] = []  # one entry per open <span>: is it struck through?
        self.mj_raw = 0
        self.prices: list[str] = []
        self.struck: list[str] = []
        self.attributes: list[str] = []
        self.description: list[str] = []
        self.in_description = False

    def handle_starttag(self, tag, attrs):
        if tag == "span":
            self.spans.append("line-through" in (dict(attrs).get("style") or ""))
        elif tag == "mj-raw":
            self.mj_raw += 1

    def handle_endtag(self, tag):
        if tag == "span" and self.spans:
            self.spans.pop()
        elif tag == "mj-raw" and self.mj_raw:
            self.mj_raw -= 1

    def handle_comment(self, data):
        if data.strip() == "comentario":
            self.in_description = True

    def handle_data(self, data):
        if not data.strip():
            return
        if self.in_description:
            self.description.append(data)
        elif PRICE_RE.match(data):
            (self.struck if any(self.spans) else self.prices).append(data.strip())
        elif self.mj_raw and self.prices:  # the attribute line follows the card price
            self.attributes.append(data)


def _read_attributes(text: str):
    values, problems, leftovers = {}, [], text
    for name, pattern in ATTRIBUTES.items():
        found = pattern.findall(text)
        if len(found) > 1:
            problems.append(Problem("línea de atributos", f"un solo valor de {name}", _excerpt(text)))
        elif found:
            values[name] = True if pattern.groups == 0 else _amount(found[0])
        leftovers = pattern.sub("|", leftovers)
    unknown = [" ".join(t.split()) for t in leftovers.split("|") if t.strip()]
    return values, problems, unknown


def _html(msg: EmailMessage) -> str | None:
    part = msg.get_body(preferencelist=("html",))
    return part.get_content() if part is not None and part.get_content_type() == "text/html" else None


def read(msg: EmailMessage) -> ReadResult:
    sender = parseaddr(str(msg.get("From", "")))[1].lower()
    if sender != SENDER and sender not in OLD_SENDERS:
        return ReadResult("not_alert")
    subject = SUBJECT_RE.match(" ".join(str(msg.get("Subject", "")).split()))
    search_name = subject["search"] if subject else None
    if sender in OLD_SENDERS or not subject:
        return ReadResult("unsupported", search_name)

    kind = subject["kind"]
    if kind == "Bajada de precio":
        alert_type, campaign_prefix = "price_drop", "express_priceDrop_sale_"
    elif kind.startswith("Nuevo ") or kind == "Nueva obra nueva":
        alert_type, campaign_prefix = "new_listing", "express_newAd_sale_"
    else:
        return ReadResult("unsupported", search_name)

    result = ReadResult(alert_type, search_name)
    html = _html(msg)
    if html is None:
        result.problems.append(Problem("cuerpo del email", "una parte HTML", "sin parte HTML"))
        return result

    links = _Links()
    links.feed(html)
    listing_links = [(href, title) for href, title in links.anchors if LINK_RE.match(href)]
    codes = sorted({LINK_RE.match(href)["code"] for href, _ in listing_links})
    campaigns = {m["campaign"] for href, _ in listing_links if (m := CAMPAIGN_RE.search(href))}
    if campaigns and not all(c.startswith(campaign_prefix) for c in campaigns):
        return ReadResult("unsupported", search_name)
    if len(codes) != 1:
        result.problems.append(Problem("enlace del anuncio", "un único código de anuncio", ", ".join(codes) or "ninguno"))
        return result
    if not campaigns:
        result.problems.append(Problem("enlace del anuncio", f"utm_campaign={campaign_prefix}…", "sin utm_campaign"))
        return result
    code = codes[0]

    titled = [(href, title) for href, title in listing_links if title]
    titles = {" ".join(title.split()) for _, title in titled}
    if len(titles) != 1:
        result.problems.append(Problem("título del anuncio", "un título en el enlace", " | ".join(sorted(titles)) or "ninguno"))
        return result
    title = titles.pop()
    link_tracking = titled[0][0]
    link_kind = LINK_RE.match(link_tracking)["kind"]
    type_text, sep, location_text = title.partition(" en ")
    if not sep:
        result.problems.append(Problem("título del anuncio", '"<tipo> en <ubicación>"', _excerpt(title)))
        return result

    cards = CARD_RE.findall(html)
    if len(cards) != 1:
        result.problems.append(Problem("tarjeta del anuncio", "una tarjeta", f"{len(cards)} tarjetas"))
        return result
    raw_block = cards[0]
    card = _Card()
    card.feed(raw_block)

    if len(card.prices) != 1:
        result.problems.append(Problem("precio de la tarjeta", "un precio", " | ".join(card.prices) or "ninguno"))
        return result
    price = _amount(card.prices[0])
    previous_price = None
    if alert_type == "price_drop":
        drop = DROP_RE.search(" ".join(html.split()))
        if not drop:
            result.problems.append(Problem("frase de bajada de precio", '"ha bajado de <anterior>€ a <nuevo>€"', "no encontrada"))
            return result
        if _amount(drop["new"]) != price:
            result.problems.append(Problem("precio de la tarjeta", f'"a {drop["new"]}€"', card.prices[0]))
            return result
        previous_price = _amount(drop["old"])
        if card.struck and [_amount(s) for s in card.struck] != [previous_price]:
            result.problems.append(Problem("precio anterior tachado", f'"{drop["old"]}€"', " | ".join(card.struck)))
            return result
    elif card.struck:
        result.problems.append(Problem("precio de la tarjeta", "sin precio anterior en un anuncio nuevo", " | ".join(card.struck)))
        return result

    development = link_kind == "obra-nueva"
    if development != (type_text == DEVELOPMENT_TYPE):
        result.problems.append(Problem("tipo de anuncio", f"enlace /obra-nueva/ y tipo {DEVELOPMENT_TYPE} a la vez",
                                       f"/{link_kind}/ y {type_text}"))
        return result

    values, problems, unknown = _read_attributes(" ".join(card.attributes))
    if problems:
        result.problems.extend(problems)
        return result
    result.notices.extend(f'atributo no reconocido: "{token}"' for token in unknown)

    description = " ".join(" ".join(card.description).split()) or None
    result.listings.append(ListingBlock(
        listing_code=code,
        price=price,
        previous_price=previous_price,
        area_m2=values.get("area_m2"),
        bedrooms=values.get("bedrooms"),
        floor=values.get("floor"),
        exterior=values.get("exterior"),
        elevator=values.get("elevator"),
        garage=values.get("garage"),
        type_text=type_text,
        property_type=TYPE_MAP.get(type_text, "otro"),
        development=development,
        unit_description=description if development else None,
        new_build_stated=True if development or kind == "Nueva obra nueva" else None,
        location_text=location_text,
        link_tracking=link_tracking,
        link_direct=f"https://www.idealista.com/{link_kind}/{code}/",
        raw_block=raw_block,
    ))
    return result
