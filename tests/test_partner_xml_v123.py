# -*- coding: utf-8 -*-
"""v1.23 local-only permissioned XML/YRL feeds; never auto-publish."""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from scripts.market_inventory import ingest
from scripts.partner_xml import iter_partner_xml, UnsafePartnerXML

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def grant(tmp_path, **changes):
    d = {
        "source_key": "partner_a",
        "agreement_ref": "contract_2026",
        "operator_rights_reviewed": True,
        "metadata_display_permitted": True,
        "valid_until": "2027-06-30",
        "allowed_source_hosts": ["partner.example.ua"],
        "full_snapshot_allowed": True,
    }
    d.update(changes)
    p = tmp_path / "private-grant.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    return p


def offer(n, *, price="18000", notes=""):
    return (f'<offer id="external-{n}"><source_url>https://partner.example.ua/offer/{n}'
            f'?utm_source=partner</source_url><operation>rent</operation>'
            f'<property_type>apartment</property_type><city>Київ</city>'
            f'<district>Дарницький</district><rooms>2</rooms>'
            f'<price_uah>{price}</price_uah><area_m2>53.5</area_m2>{notes}</offer>')


def xml_file(tmp_path, body, *, name="partner.xml"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def count(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]


def test_permissioned_xml_imports_private_metadata_only(tmp_path):
    xml = xml_file(tmp_path,
        '<realty-feed>' + offer(1, notes=(
            '<description>Private note: +380501112233</description>'
            '<picture>https://partner.example.ua/photo-secret.jpg</picture>'
            '<owner_name>PRIVATE NAME</owner_name>')) + '</realty-feed>')
    db = tmp_path / "inventory.sqlite"
    result = ingest(xml, grant(tmp_path), db, now=NOW, full_snapshot=True)
    assert (result["accepted"], result["inserted"], result["publications"],
            result["contacts_copied"], result["media_copied"]) == (1, 1, 0, 0, 0)
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT external_id, source_url, city, price_uah, review_status FROM inventory"
        ).fetchone()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(inventory)")}
    assert row == ("external-1", "https://partner.example.ua/offer/1",
                   "Київ", 18000, "pending_review")
    assert {"description", "picture", "owner_name", "phone"}.isdisjoint(cols)


def test_yrl_requires_explicit_mapped_fields_and_uah(tmp_path):
    yrl = """<?xml version="1.0" encoding="UTF-8"?>
    <yml_catalog><shop><offers><offer id="A-2">
      <url>https://partner.example.ua/p/2</url>
      <price>22000</price><currencyId>UAH</currencyId>
      <param name="operation">sale</param>
      <param name="property_type">house</param>
      <param name="city">Львів</param>
    </offer></offers></shop></yml_catalog>"""
    db = tmp_path / "staging.db"
    report = ingest(xml_file(tmp_path, yrl, name="listing.yml"), grant(tmp_path), db, now=NOW)
    assert report["accepted"] == 1
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT operation, property_type, city, price_uah FROM inventory").fetchone()
    assert row == ("sale", "house", "Львів", 22000)


@pytest.mark.parametrize("bad", [
    '<!DOCTYPE realty-feed [<!ENTITY file SYSTEM "file:///etc/passwd">]>'
    '<realty-feed><offer id="1"><city>&file;</city></offer></realty-feed>',
    '<!DOCTYPE realty-feed [<!ENTITY a "bomb">]>'
    '<realty-feed><offer id="1"><city>&a;</city></offer></realty-feed>',
    '<realty-feed><offer id="1"><city><inner>Київ</inner></city></offer></realty-feed>',
    '<realty-feed>' + offer(1).replace(
        '<operation>rent</operation>', '<operation>rent</operation><operation>sale</operation>'
    ) + '</realty-feed>',
    '<offer id="1"><city>Київ</city></offer>',
    '<realty-feed><offers>' + offer(1) + '</offers></realty-feed>',
    '<realty-feed>' + offer(1)[:-8] + '</realty-feed>',
    '<realty-feed>' + offer(1, notes='<city>Львів</city>') + '</realty-feed>',
    '<realty-feed>' + offer(1, notes='<district>' + "X" * 9000 + '</district>') + '</realty-feed>',
])
def test_malicious_ambiguous_or_malformed_xml_rejected(bad, tmp_path):
    p = xml_file(tmp_path, bad)
    with pytest.raises((UnsafePartnerXML, ValueError)):
        list(iter_partner_xml(p))


@pytest.mark.parametrize("currency", ["USD", "EUR", ""])
def test_yrl_must_not_mislabel_foreign_currency_as_uah(tmp_path, currency):
    text = ('<yml_catalog><shop><offers><offer id="one">'
            '<url>https://partner.example.ua/p/1</url><price>100</price>'
            + (f'<currencyId>{currency}</currencyId>' if currency else "")
            + '<param name="operation">rent</param>'
              '<param name="property_type">apartment</param>'
              '<param name="city">Київ</param></offer></offers></shop></yml_catalog>')
    with pytest.raises(UnsafePartnerXML, match="UAH"):
        list(iter_partner_xml(xml_file(tmp_path, text)))


def test_xml_import_requires_valid_permission_and_expiry(tmp_path):
    xml = xml_file(tmp_path, '<realty-feed>' + offer(1) + '</realty-feed>')
    db = tmp_path / "data.sqlite"
    with pytest.raises(ValueError, match="rights review"):
        ingest(xml, grant(tmp_path, operator_rights_reviewed=False), db, now=NOW)
    with pytest.raises(ValueError, match="expired"):
        ingest(xml, grant(tmp_path, valid_until="2024-01-01"), db, now=NOW)
    assert not db.exists()


def test_broken_second_offer_rolls_back_first_offer(tmp_path):
    source = '<realty-feed>' + offer(1) + '<offer id="bad"><operation>rent</operation></realty-feed>'
    db = tmp_path / "data.sqlite"
    with pytest.raises(ValueError):
        ingest(xml_file(tmp_path, source), grant(tmp_path), db, now=NOW)
    assert count(db) == 0


def test_duplicate_external_ids_roll_back_entire_xml_batch(tmp_path):
    source = '<realty-feed>' + offer(1) + offer(1) + '</realty-feed>'
    db = tmp_path / "data.sqlite"
    with pytest.raises(ValueError, match="Repeated"):
        ingest(xml_file(tmp_path, source), grant(tmp_path), db, now=NOW)
    assert count(db) == 0


def test_xml_is_idempotent_and_price_change_requires_new_review(tmp_path):
    source = xml_file(tmp_path, '<realty-feed>' + offer(1) + '</realty-feed>')
    db = tmp_path / "data.sqlite"
    grant_file = grant(tmp_path)
    ingest(source, grant_file, db, now=NOW)
    report = ingest(source, grant_file, db, now=NOW)
    assert report["inserted"] == 0 and report["unchanged"] == 1
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE inventory SET review_status='approved'")
    source = xml_file(tmp_path, '<realty-feed>' + offer(1, price="19000") + '</realty-feed>')
    report = ingest(source, grant_file, db, now=NOW)
    assert report["changed"] == 1
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT review_status FROM inventory").fetchone()[0] == "needs_review"


def test_xml_streams_many_offers_without_approving_any(tmp_path):
    source = xml_file(tmp_path, '<realty-feed>' +
                      "".join(offer(i) for i in range(1, 1001)) + '</realty-feed>')
    db = tmp_path / "data.sqlite"
    report = ingest(source, grant(tmp_path), db, now=NOW, full_snapshot=True)
    assert report["inserted"] == 1000
    assert count(db) == 1000
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM inventory WHERE review_status='approved'").fetchone()[0] == 0


def test_xml_unsupported_encoding_and_bom_rejected(tmp_path):
    raw = '<?xml version="1.0" encoding="UTF-16"?><realty-feed></realty-feed>'
    path = tmp_path / "latin.xml"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(UnsafePartnerXML):
        list(iter_partner_xml(path))
    path.write_bytes(b"\xff\xfe" + '<realty-feed/>'.encode("utf-16-le"))
    with pytest.raises(UnsafePartnerXML):
        list(iter_partner_xml(path))


def test_unknown_yrl_category_never_guessed(tmp_path):
    yrl = ('<yml_catalog><shop><offers><offer id="1">'
           '<url>https://partner.example.ua/p/1</url>'
           '<categoryId>101</categoryId><price>5000</price><currencyId>UAH</currencyId>'
           '<param name="city">Київ</param>'
           '</offer></offers></shop></yml_catalog>')
    with pytest.raises(ValueError, match="Unsupported operation"):
        ingest(xml_file(tmp_path, yrl), grant(tmp_path), tmp_path / "data.db", now=NOW)
