# -*- coding: utf-8 -*-
"""v1.24 rights lifecycle: fail closed, private-only, no public export."""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from scripts.market_inventory import ingest, SCHEMA
from scripts.source_rights import revoke_source, assess_source

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def make_grant(tmp_path, *, source="agency_one", ref="contract_v1",
               end="2027-01-01", full=True):
    p = tmp_path / f"grant_{source}.json"
    p.write_text(json.dumps({
        "source_key": source, "agreement_ref": ref,
        "valid_until": end, "operator_rights_reviewed": True,
        "metadata_display_permitted": True,
        "allowed_source_hosts": ["agency.example.ua"],
        "full_snapshot_allowed": full,
    }), encoding="utf8")
    return p


def make_feed(tmp_path, *, n=1, malformed=False):
    p = tmp_path / "batch.jsonl"
    d = {
        "external_id": str(n), "source_url": f"https://agency.example.ua/p/{n}",
        "operation": "rent", "property_type": "apartment", "city": "Київ",
        "price_uah": 12000
    }
    p.write_text(json.dumps(d, ensure_ascii=False) + "\n" +
                 ("not json\n" if malformed else ""), encoding="utf8")
    return p


def get_rights(db):
    with sqlite3.connect(db) as conn:
        return conn.execute(
            "SELECT source,agreement_ref,valid_until,status FROM source_rights ORDER BY source"
        ).fetchall()


def get_status(db, source):
    with sqlite3.connect(db) as conn:
        return conn.execute(
            "SELECT review_status FROM inventory WHERE source=?", (source,)
        ).fetchone()[0]


def audit_count(db):
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM source_rights_audit").fetchone()[0]


def test_registration_is_private_and_fails_publication_closed(tmp_path):
    db = tmp_path / "private.sqlite"
    report = ingest(make_feed(tmp_path), make_grant(tmp_path), db, now=NOW)
    assert report["accepted"] == 1 and report["publications"] == 0
    assert get_rights(db) == [("agency_one", "contract_v1", "2027-01-01", "active")]
    assert assess_source(db, "agency_one", now=NOW) == {
        "source": "agency_one", "rights_state": "active",
        "ingestion_authorized": True, "inventory_records": 1,
        "reviewed_records": 0, "publications": 0,
        "public_listing_verified": False}
    assert audit_count(db) == 1
    ingest(make_feed(tmp_path), make_grant(tmp_path), db, now=NOW)
    assert audit_count(db) == 1


def test_revocation_resets_previous_approvals_and_blocks_reuse(tmp_path):
    db = tmp_path / "private.sqlite"
    f = make_feed(tmp_path)
    grant = make_grant(tmp_path)
    ingest(f, grant, db, now=NOW)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE inventory SET review_status='approved'")
    result = revoke_source(db, "agency_one", "partner_request", now=NOW)
    assert result["revoked"] and result["approvals_reset"] == 1
    assert get_status(db, "agency_one") == "needs_review"
    assert not assess_source(db, "agency_one", now=NOW)["ingestion_authorized"]
    with pytest.raises(ValueError, match="Source disabled"):
        ingest(f, grant, db, now=NOW)
    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="Source rights"):
            conn.execute("UPDATE inventory SET review_status='approved'")
    assert get_status(db, "agency_one") == "needs_review"
    assert get_rights(db)[0][-1] == "revoked"


def test_revocation_is_idempotent_and_audited_once(tmp_path):
    db = tmp_path / "private.sqlite"
    ingest(make_feed(tmp_path), make_grant(tmp_path), db, now=NOW)
    first = revoke_source(db, "agency_one", "operator_hold", now=NOW)
    second = revoke_source(db, "agency_one", "partner_request", now=NOW)
    assert first["already_revoked"] is False
    assert second["already_revoked"] is True and second["approvals_reset"] == 0
    assert audit_count(db) == 2  # registration + first revocation
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT reason_code FROM source_rights_audit WHERE event='revoked'"
        ).fetchone()[0] == "operator_hold"


def test_no_silent_extension_or_agreement_replacement(tmp_path):
    db = tmp_path / "private.sqlite"
    f = make_feed(tmp_path)
    ingest(f, make_grant(tmp_path, end="2027-01-01"), db, now=NOW)
    with pytest.raises(ValueError, match="extension"):
        ingest(f, make_grant(tmp_path, end="2028-01-01"), db, now=NOW)
    with pytest.raises(ValueError, match="replacement"):
        ingest(f, make_grant(tmp_path, ref="contract_v2"), db, now=NOW)
    assert get_rights(db)[0][1:3] == ("contract_v1", "2027-01-01")


def test_shortening_expiry_is_allowed_but_reextension_is_not(tmp_path):
    db = tmp_path / "private.sqlite"
    f = make_feed(tmp_path)
    ingest(f, make_grant(tmp_path), db, now=NOW)
    ingest(f, make_grant(tmp_path, end="2026-12-01"), db, now=NOW)
    assert get_rights(db)[0][2] == "2026-12-01"
    assert audit_count(db) == 2
    with pytest.raises(ValueError, match="extension"):
        ingest(f, make_grant(tmp_path, end="2027-01-01"), db, now=NOW)


def test_expiry_masks_source_regardless_of_review_status(tmp_path):
    db = tmp_path / "private.sqlite"
    ingest(make_feed(tmp_path), make_grant(tmp_path), db, now=NOW)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE inventory SET review_status='approved'")
    future = datetime(2027, 2, 1, tzinfo=timezone.utc)
    result = assess_source(db, "agency_one", now=future)
    assert result["rights_state"] == "expired"
    assert result["ingestion_authorized"] is False
    assert result["reviewed_records"] == 1
    assert result["publications"] == 0


def test_malformed_feed_does_not_register_source(tmp_path):
    db = tmp_path / "private.sqlite"
    with pytest.raises(json.JSONDecodeError):
        ingest(make_feed(tmp_path, malformed=True), make_grant(tmp_path), db, now=NOW)
    assert get_rights(db) == []
    assert audit_count(db) == 0


def test_revocation_requires_existing_private_database_and_known_source(tmp_path):
    db = tmp_path / "missing.sqlite"
    with pytest.raises(ValueError, match="Existing private"):
        revoke_source(db, "agency_one", "operator_hold", now=NOW)
    assert not db.exists()
    ingest(make_feed(tmp_path), make_grant(tmp_path), db, now=NOW)
    with pytest.raises(ValueError, match="Unknown source"):
        revoke_source(db, "agency_other", "operator_hold", now=NOW)
    with pytest.raises(ValueError, match="reason"):
        revoke_source(db, "agency_one", "some_personal_note", now=NOW)
    with pytest.raises(ValueError, match="Invalid source"):
        revoke_source(db, "../agency_one", "operator_hold", now=NOW)
    assert get_rights(db)[0][-1] == "active"


def test_source_revoke_does_not_affect_other_partners(tmp_path):
    db = tmp_path / "private.sqlite"
    f = make_feed(tmp_path)
    ingest(f, make_grant(tmp_path, source="agency_one"), db, now=NOW)
    ingest(f, make_grant(tmp_path, source="agency_two"), db, now=NOW)
    revoke_source(db, "agency_one", "compliance_hold", now=NOW)
    assert assess_source(db, "agency_one", now=NOW)["rights_state"] == "revoked"
    assert assess_source(db, "agency_two", now=NOW)["rights_state"] == "active"
    assert get_rights(db)[-1][-1] == "active"


def test_legacy_approved_inventory_is_demoted_on_first_rights_registration(tmp_path):
    db = tmp_path / "legacy.sqlite"
    # Simulates a legacy row written before source_rights existed.
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE inventory (
          source TEXT NOT NULL, external_id TEXT NOT NULL, source_url TEXT NOT NULL,
          operation TEXT NOT NULL, property_type TEXT NOT NULL, city TEXT NOT NULL,
          district TEXT, price_uah INTEGER, rooms INTEGER, area_m2 REAL, unit_key TEXT,
          imported_first_at TEXT NOT NULL, imported_last_at TEXT NOT NULL,
          last_batch TEXT NOT NULL, misses INTEGER NOT NULL DEFAULT 0,
          review_status TEXT NOT NULL DEFAULT 'pending_review',
          PRIMARY KEY(source,external_id)
        );
        """)
        conn.execute(
            "INSERT INTO inventory(source,external_id,source_url,operation,property_type,city,"
            "imported_first_at,imported_last_at,last_batch,review_status) VALUES"
            "('agency_one','old','https://agency.example.ua/p/old','rent','apartment','Київ',"
            "'2026-11-01','2026-11-01','oldbatch','approved')")
    ingest(make_feed(tmp_path, n=2), make_grant(tmp_path), db, now=NOW)
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            "SELECT review_status FROM inventory WHERE external_id='old'"
        ).fetchone()[0] == "needs_review"
    assert get_rights(db)[0][-1] == "active"


def test_sql_accidental_rights_reopen_deletion_and_audit_tampering_blocked(tmp_path):
    db = tmp_path / "private.sqlite"
    ingest(make_feed(tmp_path), make_grant(tmp_path), db, now=NOW)
    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="extension"):
            conn.execute("UPDATE source_rights SET valid_until='2099-01-01'")
        with pytest.raises(sqlite3.IntegrityError, match="deletion"):
            conn.execute("DELETE FROM source_rights WHERE source='agency_one'")
    revoke_source(db, "agency_one", "partner_request", now=NOW)
    with sqlite3.connect(db) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="reactivated"):
            conn.execute("UPDATE source_rights SET status='active' WHERE source='agency_one'")
        with pytest.raises(sqlite3.IntegrityError, match="deletion"):
            conn.execute("DELETE FROM source_rights_audit")
        with pytest.raises(sqlite3.IntegrityError, match="modification"):
            conn.execute("UPDATE source_rights_audit SET reason_code='changed'")
    assert get_rights(db)[0][-1] == "revoked"
    assert audit_count(db) == 2
