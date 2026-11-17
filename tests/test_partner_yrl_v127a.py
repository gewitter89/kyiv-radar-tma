# -*- coding: utf-8 -*-
"""Strict YRL intake tests: real partner schema, synthetic listings only."""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from scripts.market_inventory import ingest
from scripts.partner_yrl import InvalidYRL, iter_yrl

NOW = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)


def grant(tmp_path, **changes):
    obj = {
        "source_key": "agency_a", "agreement_ref": "contract_ua",
        "valid_until": "2027-12-31", "operator_rights_reviewed": True,
        "metadata_display_permitted": True,
        "allowed_source_hosts": ["agency.example.ua"],
        "full_snapshot_allowed": True,
    }
    obj.update(changes)
    path = tmp_path / "grant.json"
    path.write_text(json.dumps(obj))
    return path


def offer(n, *, currency="UAH", typ="оренда", category="квартира",
          price="18000", period="<period>місяць</period>", city="Київ",
          url=None, extra=""):
    url = url or f"https://agency.example.ua/offers/{n}"
    return f"""<offer internal-id="A-{n}">
        <type>{typ}</type>
        <property-type>житлова</property-type>
        <category>{category}</category>
        <url>{url}</url>
        <location>
            <country>Україна</country>
            <locality-name>{city}</locality-name>
            <district>Дарницький</district>
            <address>Secret Street, 18</address>
            <latitude>50.1234</latitude>
        </location>
        <price><value>{price}</value><currency>{currency}</currency>{period}</price>
        <area><value>51.5</value><unit>кв.м</unit></area>
        <rooms>2</rooms>
        <sales-agent><name>Private name</name>
          <phone>+380991112233</phone><category>агентство</category></sales-agent>
        <description>Confidential partner text</description>
        <image>https://agency.example.ua/unlicensed.jpg</image>
        {extra}
    </offer>"""


def write_yrl(tmp_path, offers, *, name="partner.xml", namespace=True):
    xmlns = (' xmlns="http://webmaster.yandex.ru/schemas/feed/realty/2010-06"'
             if namespace else "")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           f'<realty-feed{xmlns}><generation-date>2026-11-17T08:00:00Z</generation-date>'
           + "".join(offers) + '</realty-feed>')
    path = tmp_path / name
    path.write_text(xml, encoding="utf8")
    return path


def count(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]


def test_realty_feed_nested_yrl_maps_only_safe_metadata(tmp_path):
    path = write_yrl(tmp_path, [offer(1)])
    db = tmp_path / "private.sqlite"
    report = ingest(path, grant(tmp_path), db, now=NOW,
                    full_snapshot=True, feed_format="yrl")
    assert report["accepted"] == 1 and report["publications"] == 0
    assert report["contacts_copied"] == report["media_copied"] == 0
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT external_id,source_url,operation,property_type,city,"
            "district,price_uah,rooms,area_m2,review_status FROM inventory"
        ).fetchone()
        columns = {x[1] for x in conn.execute("PRAGMA table_info(inventory)")}
    assert row == ("A-1", "https://agency.example.ua/offers/1",
                   "rent", "apartment", "Київ", "Дарницький", 18000,
                   2, 51.5, "pending_review")
    assert {"address","latitude","image","description","name","phone"}.isdisjoint(columns)


def test_ukrainian_sale_maps_but_no_monthly_price_claim(tmp_path):
    source = offer(2, typ="продаж", period="")
    rows = list(iter_yrl(write_yrl(tmp_path, [source], namespace=False)))
    assert rows[0]["operation"] == "sale"
    assert rows[0]["property_type"] == "apartment"
    assert rows[0]["price_uah"] == "18000"


def test_large_yrl_intake_and_idempotence_no_auto_publication(tmp_path):
    path = write_yrl(tmp_path, (offer(i) for i in range(1, 501)))
    db = tmp_path / "private.db"
    a = grant(tmp_path)
    result = ingest(path, a, db, now=NOW, feed_format="yrl")
    assert result["inserted"] == 500 and count(db) == 500
    second = ingest(path, a, db, now=NOW, feed_format="yrl")
    assert second["unchanged"] == 500 and second["publications"] == 0


@pytest.mark.parametrize("kwargs", [
    {"currency": "USD"},
    {"currency": "EUR"},
    {"currency": "RUB"},
    {"currency": ""},
    {"price": "15000.49"},
    {"price": "0"},
    {"period": ""},
    {"period": "<period>день</period>"},
    {"period": "<unit>кв.м</unit><period>місяць</period>"},
    {"typ": "невідомий"},
    {"category": "квартира біля метро"},
    {"city": ""},
    {"url": "https://agency.example.ua.evil.test/p/1"},
    {"url": "http://agency.example.ua/p/1"},
])
def test_invalid_yrl_never_inserts_partial_data(tmp_path, kwargs):
    path = write_yrl(tmp_path, [offer(1, **kwargs)])
    db = tmp_path / "private.db"
    with pytest.raises(ValueError):
        ingest(path, grant(tmp_path), db, now=NOW, feed_format="yrl")
    assert count(db) == 0


@pytest.mark.parametrize("extra", [
    "<price><value>20000</value><currency>UAH</currency><period>місяць</period></price>",
    "<location><locality-name>Львів</locality-name></location>",
    "<rooms>4</rooms>",
    "<area><value>92</value><unit>кв.м</unit></area>",
    "<category>будинок</category>",
    "<price><value>1</value><currency>UAH</currency><unit></unit></price>",
])
def test_repeated_ambiguous_yrl_fields_rejected(tmp_path, extra):
    path = write_yrl(tmp_path, [offer(1, extra=extra)])
    with pytest.raises(InvalidYRL):
        list(iter_yrl(path))


def test_duplicate_internal_ids_abort_full_sql_transaction(tmp_path):
    path = write_yrl(tmp_path, [offer(1), offer(1)])
    db = tmp_path / "inventory.sqlite"
    with pytest.raises(ValueError, match="Repeated"):
        ingest(path, grant(tmp_path), db, now=NOW, feed_format="yrl")
    assert count(db) == 0


def test_truncated_second_offer_rolls_back_first(tmp_path):
    path = write_yrl(tmp_path, [offer(1)])
    text = path.read_text()
    path.write_text(text.replace("</realty-feed>", "<offer internal-id='2'><type>оренда</type></realty-feed>"))
    db = tmp_path / "inventory.sqlite"
    with pytest.raises(ValueError):
        ingest(path, grant(tmp_path), db, now=NOW, feed_format="yrl")
    assert count(db) == 0


@pytest.mark.parametrize("danger", [
    '<!DOCTYPE realty-feed [<!ENTITY secret SYSTEM "file:///etc/passwd">]>',
    '<!DOCTYPE realty-feed [<!ENTITY bomb "long-content">]>',
    '<?unsafe value?>',
])
def test_unsafe_xml_constructs_rejected(tmp_path, danger):
    path = write_yrl(tmp_path, [offer(1)])
    txt = path.read_text().replace("<realty-feed", danger + "<realty-feed", 1)
    path.write_text(txt)
    with pytest.raises(InvalidYRL):
        list(iter_yrl(path))


def test_unauthorized_source_cannot_be_imported(tmp_path):
    path = write_yrl(tmp_path, [offer(1)])
    db = tmp_path / "private.db"
    with pytest.raises(ValueError, match="rights review"):
        ingest(path, grant(tmp_path, operator_rights_reviewed=False), db,
               now=NOW, feed_format="yrl")
    assert not db.exists()


def test_format_is_explicit_not_automatically_guessed(tmp_path):
    path = write_yrl(tmp_path, [offer(1)])
    db = tmp_path / "private.db"
    with pytest.raises(ValueError):
        ingest(path, grant(tmp_path), db, now=NOW)
    assert count(db) == 0


def test_arbitrary_new_location_or_agent_tags_are_never_copied(tmp_path):
    extra = "<sales-agent><email>secret@example.test</email></sales-agent>"
    path = write_yrl(tmp_path, [offer(1, extra=extra)])
    assert list(iter_yrl(path))[0]["city"] == "Київ"
    db = tmp_path / "private.db"
    ingest(path, grant(tmp_path), db, now=NOW, feed_format="yrl")
    with sqlite3.connect(db) as conn:
        assert "private" not in str(conn.execute("SELECT * FROM inventory").fetchone())
