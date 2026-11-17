# -*- coding: utf-8 -*-
"""v1.26: independent publication consent, reviewer evidence and private-only output."""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("BOT_TOKEN", "123456789:TEST_BOT_TOKEN_FOR_HMAC_VALIDATION")

from scripts.market_inventory import ingest
from scripts.source_rights import revoke_source
from server import kyiv_radar_api as api
from server.partner_publication import (
    prepare_private_export, publication_receipt, read_private_export,
    stable_id, write_private_export,
)
from server.partner_visibility import enforce_partner_visibility

NOW = datetime(2026, 11, 17, 18, 0, tzinfo=timezone.utc)


def setup_source(tmp_path):
    agreement = tmp_path / "contract.json"
    agreement.write_text(json.dumps({
        "source_key": "agency_one", "agreement_ref": "contract_v1",
        "operator_rights_reviewed": True, "metadata_display_permitted": True,
        "allowed_source_hosts": ["agency.example.ua"],
        "valid_until": "2028-01-01", "full_snapshot_allowed": True,
    }))
    db = tmp_path / "inventory.sqlite"
    feed = tmp_path / "feed.jsonl"
    records = [
        {"external_id": "APT-11", "source_url": "https://agency.example.ua/p/11",
         "operation": "rent", "property_type": "apartment", "city": "Київ",
         "district": "Дарницький", "price_uah": 18000, "rooms": 2, "area_m2": 51.5,
         "phone": "+380555111222", "ownerName": "CONFIDENTIAL",
         "images": ["https://example/secret.jpg"], "description": "Secret"},
        {"external_id": "APT-12", "source_url": "https://agency.example.ua/p/12",
         "operation": "sale", "property_type": "apartment", "city": "Львів",
         "price_uah": 3000000},
    ]
    feed.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records))
    ingest(feed, agreement, db, now=NOW)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE inventory SET review_status='approved'")
    return db


def make_authorization(tmp_path, *, now=NOW, **updates):
    receipt = {
        "schema_version": 1, "publication_permitted": True,
        "source_key": "agency_one", "agreement_ref": "contract_v1",
        "valid_until": "2027-07-01",
        "reviewed_by": "operator-1", "evidence_ref": "private/agreement/2026",
        "reviewed_at": now.isoformat(timespec="seconds"),
        "permitted_fields": ["source_url", "operation", "property_type", "city",
                             "district", "price_uah", "rooms", "area_m2"],
    }
    receipt.update(updates)
    path = tmp_path / "publication_authorization.json"
    path.write_text(json.dumps(receipt))
    return path


def make_reviews(tmp_path, *, now=NOW, evidence=True):
    first_id = stable_id("agency_one", "APT-11")
    reviews = {"schema_version": 1, "listings": {
        str(first_id): {
            "state": "verified",
            "availability": {
                "reviewer": "operator-2",
                "evidence_ref": "private/availability/check-001",
                "checked_at": now.isoformat(timespec="seconds"),
                "available": bool(evidence),
            }
        }
    }}
    path = tmp_path / "private_reviews.json"
    path.write_text(json.dumps(reviews))
    return path


def test_private_preview_only_includes_approved_independently_available_kyiv_rent(tmp_path):
    db = setup_source(tmp_path)
    receipt = make_authorization(tmp_path)
    reviews = make_reviews(tmp_path)
    result = prepare_private_export(db, receipt, reviews, now=NOW)
    assert result["schema_version"] == 1
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["id"] == stable_id("agency_one", "APT-11")
    assert item["price"] == 18000 and item["district"] == "Дарницький"
    assert item["url"] == "https://agency.example.ua/p/11"
    assert item["images"] == []
    assert item["actualityConfirmed"] is False
    assert "phone" not in item and "ownerName" not in item and "description" not in item
    assert "CONFIDENTIAL" not in json.dumps(result)
    assert "private/availability/check-001" not in json.dumps(result)
    assert len({x["id"] for x in result["items"]}) == 1


def test_no_independent_availability_or_approval_means_no_publishable_rows(tmp_path):
    db = setup_source(tmp_path)
    receipt = make_authorization(tmp_path)
    no_evidence = make_reviews(tmp_path, evidence=False)
    assert prepare_private_export(db, receipt, no_evidence, now=NOW)["items"] == []
    good = make_reviews(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE inventory SET review_status='needs_review'")
    assert prepare_private_export(db, receipt, good, now=NOW)["items"] == []


@pytest.mark.parametrize("change", [
    {"publication_permitted": False},
    {"agreement_ref": "another_contract"},
    {"valid_until": "2025-01-01"},
    {"permitted_fields": ["source_url", "city"]},
    {"permitted_fields": ["source_url", "operation", "property_type", "city",
                           "price_uah", "phone"]},
    {"reviewed_by": ""},
    {"evidence_ref": ""},
    {"reviewed_at": "2000-01-01T00:00:00+00:00"},
])
def test_missing_stale_or_illegal_contract_rights_rejected(tmp_path, change):
    db = setup_source(tmp_path)
    receipt = make_authorization(tmp_path, **change)
    reviews = make_reviews(tmp_path)
    with pytest.raises(ValueError):
        prepare_private_export(db, receipt, reviews, now=NOW)


def test_optional_fields_not_licensed_are_not_published(tmp_path):
    db = setup_source(tmp_path)
    receipt = make_authorization(tmp_path,
        permitted_fields=["source_url","operation","property_type","city","price_uah"])
    reviews = make_reviews(tmp_path)
    [item] = prepare_private_export(db, receipt, reviews, now=NOW)["items"]
    assert item["district"] == "Район уточнюється"
    assert item["address"] == "Київ"
    assert "area" not in item and "rooms" not in item


def test_read_only_private_export_revokes_on_authorization_change_or_expiry(tmp_path):
    db = setup_source(tmp_path)
    receipt = make_authorization(tmp_path)
    reviews = make_reviews(tmp_path)
    data = prepare_private_export(db, receipt, reviews, now=NOW)
    path = tmp_path / "export-private.json"
    write_private_export(path, data)
    assert path.is_file()
    if os.name == "posix":
        assert (path.stat().st_mode & 0o777) == 0o600
    loaded = read_private_export(str(path), str(receipt), now=NOW)
    assert len(loaded) == 1
    assert read_private_export(str(path), str(receipt),
                               now=NOW+timedelta(hours=49)) == []
    changed = json.loads(receipt.read_text())
    changed["permitted_fields"].remove("rooms")
    receipt.write_text(json.dumps(changed))
    assert read_private_export(str(path), str(receipt), now=NOW) == []


def test_deleted_or_wrong_authorization_never_loads_old_export(tmp_path):
    db = setup_source(tmp_path)
    receipt = make_authorization(tmp_path)
    reviews = make_reviews(tmp_path)
    path = tmp_path / "export-private.json"
    write_private_export(path, prepare_private_export(db, receipt, reviews, now=NOW))
    receipt.unlink()
    assert read_private_export(str(path), str(receipt), now=NOW) == []
    assert read_private_export(str(path), "", now=NOW) == []


def test_tampered_private_export_fails_closed(tmp_path):
    db = setup_source(tmp_path)
    receipt = make_authorization(tmp_path)
    reviews = make_reviews(tmp_path)
    path = tmp_path / "export-private.json"
    original = prepare_private_export(db, receipt, reviews, now=NOW)
    for mutation in (
        lambda item: item.update({"phone": "+380123456789"}),
        lambda item: item.update({"images": ["https://unapproved.test/photo.jpg"]}),
        lambda item: item.update({"actualityConfirmed": True}),
    ):
        payload = json.loads(json.dumps(original))
        mutation(payload["items"][0])
        path.write_text(json.dumps(payload))
        assert read_private_export(str(path), str(receipt), now=NOW) == []


def test_revoke_hides_prepared_partner_without_mutating_export(tmp_path):
    db = setup_source(tmp_path)
    receipt = make_authorization(tmp_path)
    reviews = make_reviews(tmp_path)
    staged = prepare_private_export(db, receipt, reviews, now=NOW)["items"]
    # The runtime first verifies fresh availability from private reviewer.
    from server.listing_trust import load_private_register, public_listing_view
    verified = public_listing_view(staged, load_private_register(str(reviews)), now=NOW)
    assert len(enforce_partner_visibility(verified, str(db), now=NOW)) == 1
    revoke_source(db, "agency_one", "partner_request", now=NOW)
    assert enforce_partner_visibility(verified, str(db), now=NOW) == []


def test_api_opt_in_publishes_only_safely_reviewed_private_partner(tmp_path, monkeypatch):
    db = setup_source(tmp_path)
    receipt = make_authorization(tmp_path, now=datetime.now(timezone.utc))
    reviews = make_reviews(tmp_path, now=datetime.now(timezone.utc))
    prepared = prepare_private_export(db, receipt, reviews,
                                      now=datetime.now(timezone.utc))
    private_export = tmp_path / "private-export.json"
    write_private_export(private_export, prepared)
    monkeypatch.setattr(api, "DEALS_JSON_PATH", str(tmp_path / "no_legacy.json"))
    monkeypatch.setattr(api, "PARTNER_RIGHTS_DB_PATH", str(db))
    monkeypatch.setattr(api, "REVIEW_REGISTER_PATH", str(reviews))
    monkeypatch.setattr(api, "PARTNER_EXPORT_PATH", str(private_export))
    monkeypatch.setattr(api, "PARTNER_PUBLICATION_AUTH_PATH", str(receipt))
    client = TestClient(api.app)
    first = client.get("/api/deals")
    assert first.status_code == 200
    assert "no-store" in first.headers.get("cache-control", "")
    assert len(first.json()["deals"]) == 1
    item = first.json()["deals"][0]
    assert item["id"] == stable_id("agency_one", "APT-11")
    assert item["actualityConfirmed"] is True
    assert item["phone"] is None and "partnerSourceKey" not in item
    assert not item.get("isOwnerVerified")
    revoke_source(db, "agency_one", "partner_request")
    assert client.get("/api/deals").json()["deals"] == []
    assert client.get("/api/health").json()["deals_count"] == 0


def test_no_private_export_env_keeps_legacy_path_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DEALS_JSON_PATH", str(tmp_path / "missing.json"))
    monkeypatch.setattr(api, "PARTNER_EXPORT_PATH", "")
    monkeypatch.setattr(api, "PARTNER_PUBLICATION_AUTH_PATH", "")
    assert api.load_trusted_deals() == []
