#!/usr/bin/env python3
"""Bounded, local-only XML/YML adapter for permissioned real-estate partner feeds.

No network requests, no personal data, no media and no approval/publication.
Every parsed record is passed into market_inventory.normalise() and its existing
private, transactional rights gate.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from xml.parsers import expat

MAX_DEPTH = 24
MAX_ATTRIBUTES = 20
MAX_SCALAR_LENGTH = 8192
ROOTS = {"realty-feed", "yml_catalog"}
FIELD_MAP = {
    "external_id": "external_id",
    "source_url": "source_url",
    "url": "source_url",
    "operation": "operation",
    "property_type": "property_type",
    "city": "city",
    "district": "district",
    "price_uah": "price_uah",
    "price": "price_uah",
    "rooms": "rooms",
    # Transient only: detect contradictory room claims then discard before DB.
    "title": "title",
    "description": "description",
    "area_m2": "area_m2",
    "unit_key": "unit_key",
    "currencyId": "_currency",
}


class UnsafePartnerXML(ValueError):
    """The partner document is unsafe or incompatible with this strict schema."""


def iter_partner_xml(path: Path):
    """Yield only whitelisted metadata plus transient room-claim text for validation.

    Supported paths (NOT a general-purpose YRL/Yandex Realty Language parser):
      realty-feed/offer with canonical field names;
      yml_catalog/shop/offers/offer with url, price (UAH) and explicit
      param name="operation", "property_type" and "city" (etc).

    Generic YML category IDs are intentionally never guessed into property
    classes. The feed owner must supply an explicitly approved field mapping.
    """
    parser = expat.ParserCreate()
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    stack: list[str] = []
    completed = deque()
    row = None
    offer_depth = 0
    current_field = None
    scalar_parts: list[str] = []
    scalar_length = 0
    seen_root = False
    used_price_alias = False

    def forbidden(*_args):
        raise UnsafePartnerXML("DTD, entity declarations and external references are forbidden")

    def xml_decl(_version, encoding, _standalone):
        if encoding and encoding.lower().replace("-", "") != "utf8":
            raise UnsafePartnerXML("Only UTF-8 XML partner feeds are supported")

    def start(name, attrs):
        nonlocal row, offer_depth, current_field, scalar_parts, scalar_length, seen_root, used_price_alias
        if len(stack) >= MAX_DEPTH or len(attrs) > MAX_ATTRIBUTES:
            raise UnsafePartnerXML("XML depth or attribute bound exceeded")
        if any(len(k) > 128 or len(v) > 4096 for k, v in attrs.items()):
            raise UnsafePartnerXML("Oversized XML attribute")
        stack.append(name)
        if not seen_root:
            seen_root = True
            if name not in ROOTS:
                raise UnsafePartnerXML("Unsupported partner feed root")
        if name == "offer":
            allowed = (stack == ["realty-feed", "offer"]
                       or stack == ["yml_catalog", "shop", "offers", "offer"])
            if row is not None or not allowed:
                raise UnsafePartnerXML("Unexpected or nested offer")
            row = {}
            used_price_alias = False
            offer_depth = len(stack)
            if "id" in attrs:
                row["external_id"] = attrs["id"]
        elif row is not None:
            if current_field is not None:
                raise UnsafePartnerXML("Nested values in scalar field are forbidden")
            if len(stack) == offer_depth + 1:
                candidate = attrs.get("name") if name == "param" else name
                mapped = FIELD_MAP.get(candidate)
                if mapped:
                    if candidate == "price":
                        used_price_alias = True
                    current_field = mapped
                    scalar_parts = []
                    scalar_length = 0

    def characters(value):
        nonlocal scalar_length
        if current_field is not None:
            scalar_length += len(value)
            if scalar_length > MAX_SCALAR_LENGTH:
                raise UnsafePartnerXML("Oversized scalar value")
            scalar_parts.append(value)

    def end(name):
        nonlocal row, offer_depth, current_field, scalar_parts, scalar_length
        if not stack or stack[-1] != name:
            raise UnsafePartnerXML("Mismatched XML element")
        if row is not None and current_field is not None and len(stack) == offer_depth + 1:
            value = "".join(scalar_parts).strip()
            if current_field in row:
                raise UnsafePartnerXML("Ambiguous duplicate partner field")
            row[current_field] = value
            current_field = None
            scalar_parts = []
            scalar_length = 0
        if name == "offer":
            if row is None or len(stack) != offer_depth:
                raise UnsafePartnerXML("Invalid offer structure")
            if used_price_alias and row.get("_currency") != "UAH":
                raise UnsafePartnerXML("Price alias requires explicit UAH currency")
            if "_currency" in row and row["_currency"] != "UAH":
                raise UnsafePartnerXML("Unconverted non-UAH price")
            if stack[0] == "yml_catalog" and "price_uah" in row and row.get("_currency") != "UAH":
                raise UnsafePartnerXML("YML price must declare UAH explicitly")
            row.pop("_currency", None)
            completed.append(row)
            row = None
            offer_depth = 0
        stack.pop()

    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.ProcessingInstructionHandler = forbidden
    parser.XmlDeclHandler = xml_decl
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = characters

    try:
        with path.open("rb") as stream:
            first = stream.read(65536)
            if first.startswith((bytes((0xff, 0xfe)), bytes((0xfe, 0xff)))):
                raise UnsafePartnerXML("UTF-16 XML is not accepted")
            part = first
            while part:
                parser.Parse(part, False)
                while completed:
                    yield completed.popleft()
                part = stream.read(65536)
            parser.Parse(b"", True)
            while completed:
                yield completed.popleft()
    except expat.ExpatError:
        # Do not include content-derived parser diagnostics in logs.
        raise UnsafePartnerXML("Malformed partner XML") from None
