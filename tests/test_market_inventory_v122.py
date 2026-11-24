# -*- coding: utf-8 -*-
"""Bulk intake is large-scale, private and strictly non-publishing."""
import csv
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.market_inventory import ingest, load_agreement, canonical_url, normalise, ROOT

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def agreement(path: Path, *, source="agency_one", allowed=True, full=True):
    path.write_text(json.dumps({
        "source_key": source,
        "agreement_ref": "contract_v1",
        "operator_rights_reviewed": allowed,
        "metadata_display_permitted": True,
        "valid_until": "2027-01-01",
        "allowed_source_hosts": ["example-agency.ua"],
        "full_snapshot_allowed": full,
    }), encoding="utf-8")
    return path


def item(n, **kwargs):
    return {
        "external_id": str(n), "source_url": f"https://example-agency.ua/offer/{n}?utm_source=chat",
        "operation": "rent", "property_type": "apartment", "city": "Київ",
        "district": "Дарницький", "price_uah": 15000, "rooms": 2, "area_m2": 53,
        "phone": "+380501112233", "ownerName": "Private user", "images": ["https://photos"],
        "description": "Confidential partner text", **kwargs,
    }


def feed(path: Path, rows):
    with path.open("w", encoding="utf-8") as fd:
        for row in rows:
            fd.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def db_rows(path):
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT source, external_id, source_url, review_status, misses "
                            "FROM inventory ORDER BY source, external_id").fetchall()


def test_ten_thousand_realistic_synthetic_rows_are_ingested_without_publication(tmp_path):
    p = agreement(tmp_path / "grant.json")
    f = feed(tmp_path / "big.jsonl", (item(n) for n in range(1, 10001)))
    db = tmp_path / "private.db"
    result = ingest(f, p, db, now=NOW, full_snapshot=True)
    assert result["accepted"] == result["inserted"] == 10000
    assert result["publications"] == result["contacts_copied"] == result["media_copied"] == 0
    assert len(db_rows(db)) == 10000
    if os.name == "posix":
        assert (db.stat().st_mode & 0o777) == 0o600
    row = db_rows(db)[0]
    assert row[2].startswith("https://example-agency.ua/offer/")
    assert "utm_" not in row[2]
    assert row[3] == "pending_review"
    # No private raw data is persisted, even though a feed supplied it.
    with sqlite3.connect(db) as conn:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(inventory)").fetchall()}
    assert {"phone", "ownerName", "description", "images"}.isdisjoint(columns)
    second = ingest(f, p, db, now=NOW, full_snapshot=True)
    assert second["inserted"] == 0
    assert second["unchanged"] == 10000
    assert second["needs_withdrawal_review"] == 0


def test_repeated_ids_abort_entire_transaction(tmp_path):
    a = agreement(tmp_path / "agreement.json")
    f = feed(tmp_path / "f.jsonl", [item(1), item(1)])
    db = tmp_path / "safe.db"
    with pytest.raises(ValueError, match="Repeated"):
        ingest(f, a, db, now=NOW)
    assert not db_rows(db)


@pytest.mark.parametrize("bad", [
    {"source_url": "https://example-agency.ua.attacker.test/p/1"},
    {"source_url": "http://example-agency.ua/p/1"},
    {"source_url": "javascript:alert(1)"},
    {"source_url": "https://user:pass@example-agency.ua/p/1"},
    {"operation": "unknown"},
    {"property_type": "unlicensed"},
    {"price_uah": -10},
    {"rooms": "many"},
    {"area_m2": float("nan")},
    {"city": ""},
])
def test_invalid_records_rejected(bad, tmp_path):
    a = load_agreement(agreement(tmp_path / "a.json"), NOW)
    with pytest.raises(ValueError):
        normalise(item(4, **bad), a)


def test_license_gate_fail_closed_and_expires(tmp_path):
    f = feed(tmp_path / "stock.jsonl", [item(1)])
    db = tmp_path / "safe.db"
    a = agreement(tmp_path / "a.json", allowed=False)
    with pytest.raises(ValueError, match="rights review"):
        ingest(f, a, db, now=NOW)
    a = agreement(tmp_path / "a.json")
    obj = json.loads(a.read_text())
    obj["valid_until"] = "2025-01-01"
    a.write_text(json.dumps(obj))
    with pytest.raises(ValueError, match="expired"):
        ingest(f, a, db, now=NOW)
    assert not db.exists()


def test_permissions_do_not_allow_full_snapshot_without_explicit_grant(tmp_path):
    a = agreement(tmp_path / "grant.json", full=False)
    f = feed(tmp_path / "f.jsonl", [item(1)])
    with pytest.raises(ValueError, match="full snapshots"):
        ingest(f, a, tmp_path / "private.db", full_snapshot=True, now=NOW)


def test_two_missing_full_batches_flag_withdrawal_but_do_not_delete(tmp_path):
    a = agreement(tmp_path / "grant.json")
    f = tmp_path / "batch.jsonl"
    db = tmp_path / "private.db"
    ingest(feed(f, [item(1), item(2), item(3)]), a, db, full_snapshot=True, now=NOW)
    q = ingest(feed(f, [item(1), item(2)]), a, db, full_snapshot=True, now=NOW)
    assert q["needs_withdrawal_review"] == 0
    q = ingest(f, a, db, full_snapshot=True, now=NOW)
    assert q["needs_withdrawal_review"] == 1
    assert len(db_rows(db)) == 3
    assert [x for x in db_rows(db) if x[1] == "3"][0][3] == "possible_withdrawn"


def test_partial_feed_never_marks_missing_listings_withdrawn(tmp_path):
    a = agreement(tmp_path / "grant.json")
    f = tmp_path / "batch.jsonl"
    db = tmp_path / "private.db"
    ingest(feed(f, [item(1), item(2)]), a, db, full_snapshot=True, now=NOW)
    for _ in range(3):
        ingest(feed(f, [item(1)]), a, db, now=NOW, full_snapshot=False)
    assert all(x[3] != "possible_withdrawn" for x in db_rows(db))


def test_empty_or_truncated_full_snapshot_is_rejected(tmp_path):
    a = agreement(tmp_path / "grant.json")
    f = tmp_path / "batch.jsonl"
    db = tmp_path / "private.db"
    ingest(feed(f, [item(i) for i in range(1, 41)]), a, db, full_snapshot=True, now=NOW)
    with pytest.raises(ValueError, match="Incomplete"):
        ingest(feed(f, [item(1)]), a, db, full_snapshot=True, now=NOW)
    assert all(x[4] == 0 for x in db_rows(db))
    assert len(db_rows(db)) == 40


def test_detect_cross_source_url_duplicate_without_auto_merging(tmp_path):
    f = feed(tmp_path / "snapshot.jsonl", [item(1)])
    db = tmp_path / "private.db"
    a = agreement(tmp_path / "grant.json", source="agency_one")
    ingest(f, a, db, now=NOW)
    a = agreement(tmp_path / "grant.json", source="agency_two")
    report = ingest(f, a, db, now=NOW)
    assert report["possible_duplicates"] == 1
    assert len(db_rows(db)) == 2
    assert all(x[3] == "pending_review" for x in db_rows(db))


def test_empty_unit_keys_do_not_create_false_duplicates(tmp_path):
    a = agreement(tmp_path / "grant.json")
    f = feed(tmp_path / "f.jsonl", [item(1, unit_key=""), item(2, unit_key="")])
    q = ingest(f, a, tmp_path / "private.sqlite", now=NOW)
    assert q["inserted"] == 2
    assert q["possible_duplicates"] == 0


def test_unit_key_duplicate_is_candidate_only(tmp_path):
    a = agreement(tmp_path / "grant.json")
    db = tmp_path / "private.sqlite"
    f = feed(tmp_path / "f.jsonl", [item(1, unit_key="property_hash_123")])
    ingest(f, a, db, now=NOW)
    a = agreement(tmp_path / "grant.json", source="agency_two")
    q = ingest(feed(f, [item(99, unit_key="property_hash_123")]), a, db, now=NOW)
    assert q["possible_duplicates"] == 1
    assert len(db_rows(db)) == 2


def test_reappearing_previously_missing_listing_goes_back_to_review(tmp_path):
    a = agreement(tmp_path / "grant.json")
    db = tmp_path / "private.sqlite"
    f = tmp_path / "f.jsonl"
    ingest(feed(f, [item(1), item(2)]), a, db, now=NOW, full_snapshot=True)
    for _ in range(2):
        ingest(feed(f, [item(1)]), a, db, now=NOW, full_snapshot=True)
    assert next(x for x in db_rows(db) if x[1] == "2")[3] == "possible_withdrawn"
    ingest(feed(f, [item(1), item(2)]), a, db, now=NOW, full_snapshot=True)
    assert next(x for x in db_rows(db) if x[1] == "2")[3] == "pending_review"


def test_source_change_does_not_preserve_auto_approval(tmp_path):
    f = feed(tmp_path / "snapshot.jsonl", [item(1)])
    a = agreement(tmp_path / "grant.json")
    db = tmp_path / "private.db"
    ingest(f, a, db, now=NOW)
    # Simulate a human approval; the importer itself cannot issue this status.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE inventory SET review_status='approved'")
    q = ingest(feed(f, [item(1, price_uah=24000)]), a, db, now=NOW)
    assert q["changed"] == 1
    assert db_rows(db)[0][3] == "needs_review"


def test_refuse_public_storage_and_feeds(tmp_path):
    feed_path = feed(tmp_path / "stock.jsonl", [item(1)])
    a = agreement(tmp_path / "grant.json")
    with pytest.raises(ValueError, match="public repo"):
        ingest(feed_path, a, ROOT / "data" / "should-not-write.sqlite", now=NOW)


def test_csv_source_and_no_copied_contacts(tmp_path):
    path = tmp_path / "feeds.csv"
    with path.open("w", encoding="utf-8", newline="") as s:
        writer = csv.DictWriter(s, fieldnames=[
            "external_id", "source_url", "operation", "property_type",
            "city", "district", "price_uah", "rooms", "area_m2", "phone"])
        writer.writeheader()
        writer.writerow({key: value for key, value in item(1).items() if key in writer.fieldnames})
    a = agreement(tmp_path / "a.json")
    out = ingest(path, a, tmp_path / "private.db", now=NOW)
    assert out["accepted"] == 1
    assert out["contacts_copied"] == 0


@pytest.mark.parametrize("suffix", [
    "?id=123", "?listing=456&utm_source=test", "?token=secret",
    "#/offer/123", "?utm_source", "?%69d=123",
])
def test_ambiguous_permalink_is_rejected_not_rewritten(suffix):
    with pytest.raises(ValueError, match="Source URL"):
        canonical_url("https://example-agency.ua/offer" + suffix, ["example-agency.ua"])


def test_tracking_only_permalink_is_canonical():
    assert canonical_url(
        "https://example-agency.ua/offer/123?utm_source=test&gclid=xyz",
        ["example-agency.ua"],
    ) == "https://example-agency.ua/offer/123"


def test_ambiguous_second_permalink_rolls_back_first_row(tmp_path):
    a = agreement(tmp_path / "grant.json")
    db = tmp_path / "private.db"
    f = feed(tmp_path / "feed.jsonl", [item(1), item(2, source_url=
        "https://example-agency.ua/offer?id=2")])
    with pytest.raises(ValueError, match="Source URL"):
        ingest(f, a, db, now=NOW)
    assert not db_rows(db)
