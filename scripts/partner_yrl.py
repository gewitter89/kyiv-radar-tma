#!/usr/bin/env python3
"""Strict subset of Yandex Realty Language for permissioned Ukrainian feeds.

Local UTF-8 file only. No network, media, personal information, exact address,
coordinates, DTD, external entities, arbitrary schema guessing or publication.

Operator explicitly selects --format yrl; this differs from our canonical XML
and YML subset parsers. The existing private importer owns all approval,
contract rights, host allowlist, deduplication and transactional rollback.
"""
from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from xml.parsers import expat

MAX_DEPTH = 24
MAX_ATTRS = 24
MAX_VALUE = 8192
FIELDS = {
    ("url",): "source_url",
    ("type",): "_deal_type",
    ("property-type",): "_property_group",
    ("category",): "_category",
    ("location", "country"): "_country",
    ("location", "locality-name"): "city",
    ("location", "sub-locality-name"): "district",
    ("location", "district"): "district",
    ("price", "value"): "_price",
    ("price", "currency"): "_currency",
    ("price", "period"): "_period",
    ("price", "unit"): "_price_unit",
    ("rooms",): "rooms",
    ("area", "value"): "_area",
    ("area", "unit"): "_area_unit",
}
OPERATIONS = {
    "продажа": "sale", "продаж": "sale", "sale": "sale",
    "аренда": "rent", "оренда": "rent", "rent": "rent",
    "посуточная аренда": "daily_rent",
    "подобова оренда": "daily_rent", "daily_rent": "daily_rent",
}
CATEGORIES = {
    "квартира": "apartment", "flat": "apartment", "apartment": "apartment",
    "комната": "room", "кімната": "room", "room": "room",
    "дом": "house", "будинок": "house", "house": "house",
    "дом с участком": "house", "house with lot": "house",
    "таунхаус": "townhouse", "townhouse": "townhouse",
    "участок": "land", "ділянка": "land", "земельна ділянка": "land",
    "lot": "land", "land": "land",
    "офис": "office", "офіс": "office", "office": "office",
    "коммерческая недвижимость": "commercial",
    "комерційна нерухомість": "commercial", "commercial": "commercial",
    "склад": "warehouse", "warehouse": "warehouse",
    "гараж": "garage", "garage": "garage",
    "паркинг": "parking", "паркінг": "parking", "parking": "parking",
}
RESIDENTIAL = {"apartment", "room", "house", "townhouse"}
COMMERCIAL = {"office", "warehouse", "commercial"}
GROUP_RESIDENTIAL = {"жилая", "жила", "житлова", "residential"}
GROUP_COMMERCIAL = {"коммерческая", "комерційна", "commercial"}
UAH = {"uah", "грн", "₴", "гривня", "гривні"}
MONTH = {"месяц", "місяць", "month", "monthly"}
DAY = {"день", "доба", "day", "daily"}
SQM = {"кв.м", "кв. м", "м²", "м2", "sqm", "sq.m", "square meter"}
COUNTRY_UA = {"украина", "україна", "ukraine", "ua"}
INTEGER = re.compile(r"^[1-9][0-9]*$")


class InvalidYRL(ValueError):
    """Unsupported or malformed licensed YRL data."""


def _canonical_row(data: dict) -> dict:
    operation = OPERATIONS.get(data.get("_deal_type", "").casefold().strip())
    category = CATEGORIES.get(data.get("_category", "").casefold().strip())
    if not operation or not category:
        raise InvalidYRL("Unsupported deal type or realty category")
    group = data.get("_property_group", "").casefold().strip()
    if group:
        if group in GROUP_RESIDENTIAL and category not in RESIDENTIAL:
            raise InvalidYRL("Conflicting residential category")
        if group in GROUP_COMMERCIAL and category not in COMMERCIAL:
            raise InvalidYRL("Conflicting commercial category")
        if group not in GROUP_RESIDENTIAL | GROUP_COMMERCIAL:
            raise InvalidYRL("Unknown property-type classification")
    country = data.get("_country", "").casefold().strip()
    if country and country not in COUNTRY_UA:
        raise InvalidYRL("Only explicitly Ukrainian partner data supported")
    if data.get("_currency", "").casefold().strip() not in UAH:
        raise InvalidYRL("Currency is not UAH")
    if "_price_unit" in data:
        raise InvalidYRL("Price per area is not a whole-property price")
    period = data.get("_period", "").casefold().strip()
    if operation == "rent" and period not in MONTH:
        raise InvalidYRL("Monthly rent needs explicit monthly price period")
    if operation == "daily_rent" and period not in DAY:
        raise InvalidYRL("Daily rent needs explicit daily price period")
    if operation == "sale" and period:
        raise InvalidYRL("Sale must not have a rent price period")
    raw_price = data.get("_price", "")
    if not INTEGER.fullmatch(raw_price):
        # Do not turn floating, currency-converted or per-metre values into UAH.
        raise InvalidYRL("A positive integer UAH whole-property price is required")
    row = {
        "external_id": data["external_id"],
        "source_url": data.get("source_url"),
        "operation": operation,
        "property_type": category,
        "city": data.get("city"),
        "district": data.get("district"),
        "price_uah": raw_price,
    }
    rooms = data.get("rooms")
    if rooms is not None:
        row["rooms"] = rooms
    area = data.get("_area")
    if area is not None:
        if data.get("_area_unit", "").casefold().strip() not in SQM:
            raise InvalidYRL("Area without a validated square-meter unit")
        area = area.replace(",", ".")
        if not re.fullmatch(r"[0-9]{1,8}(?:\.[0-9]{1,3})?", area):
            raise InvalidYRL("Invalid square-meter area")
        row["area_m2"] = area
    return row


def iter_yrl(path: Path):
    """Yield strict row dictionaries for market_inventory.normalise()."""
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    stack: list[str] = []
    rows = deque()
    current = None
    current_field = None
    pieces: list[str] = []
    size = 0

    def forbidden(*_):
        raise InvalidYRL("DTD, entity declarations, external entities and PI forbidden")

    def xml_decl(_version, encoding, _standalone):
        if encoding and encoding.lower().replace("-", "") != "utf8":
            raise InvalidYRL("YRL must use UTF-8")

    def start(name, attrs):
        nonlocal current, current_field, pieces, size
        if len(stack) >= MAX_DEPTH or len(attrs) > MAX_ATTRS:
            raise InvalidYRL("XML depth or attributes exceed limit")
        if len(name) > 128 or any(len(k) > 128 or len(v) > 4096 for k,v in attrs.items()):
            raise InvalidYRL("Oversized XML name or attribute")
        stack.append(name)
        if len(stack) == 1 and name != "realty-feed":
            raise InvalidYRL("Expected realty-feed root")
        if name == "offer":
            if stack != ["realty-feed", "offer"] or current is not None:
                raise InvalidYRL("Unexpected nested YRL offer")
            key = attrs.get("internal-id")
            if not isinstance(key, str) or not 1 <= len(key) <= 128:
                raise InvalidYRL("YRL internal-id required")
            current = {"external_id": key}
        elif current is not None:
            if current_field is not None:
                raise InvalidYRL("Nested content in scalar field")
            relative = tuple(stack[2:])
            mapped = FIELDS.get(relative)
            if mapped:
                current_field = mapped
                pieces = []
                size = 0

    def chars(piece):
        nonlocal size
        if current_field is not None:
            size += len(piece)
            if size > MAX_VALUE:
                raise InvalidYRL("Oversized YRL scalar")
            pieces.append(piece)

    def end(name):
        nonlocal current, current_field, pieces, size
        if not stack or stack[-1] != name:
            raise InvalidYRL("Unbalanced XML element")
        if current is not None and current_field is not None:
            relative = tuple(stack[2:])
            if FIELDS.get(relative) == current_field:
                if current_field in current:
                    raise InvalidYRL("Ambiguous duplicate YRL field")
                current[current_field] = "".join(pieces).strip()
                current_field = None
                pieces = []
                size = 0
        if name == "offer" and len(stack) == 2:
            if current is None:
                raise InvalidYRL("Missing YRL offer")
            rows.append(_canonical_row(current))
            current = None
        stack.pop()

    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.ProcessingInstructionHandler = forbidden
    parser.XmlDeclHandler = xml_decl
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars

    try:
        with path.open("rb") as stream:
            chunk = stream.read(65536)
            if chunk.startswith((bytes((0xff,0xfe)), bytes((0xfe,0xff)))):
                raise InvalidYRL("UTF-16 YRL is not supported")
            while chunk:
                parser.Parse(chunk, False)
                while rows:
                    yield rows.popleft()
                chunk = stream.read(65536)
            parser.Parse(b"", True)
            while rows:
                yield rows.popleft()
    except expat.ExpatError:
        # Never leak parser-derived feed contents or private paths in logs.
        raise InvalidYRL("Malformed YRL XML") from None
