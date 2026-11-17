# -*- coding: utf-8 -*-
"""v1.25: partner availability and rights must be checked at public read time."""
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("BOT_TOKEN", "123456789:TEST_BOT_TOKEN_FOR_HMAC_VALIDATION")

from scripts.market_inventory import ingest
from scripts.source_rights import revoke_source
from server import kyiv_radar_api as api
from server.listing_trust import public_listing_view
from server.partner_visibility import enforce_partner_visibility

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def private_inventory(tmp_path):
    grant = tmp_path / "grant.json"
    grant.write_text(json.dumps({
        "source_key": "agency_one", "agreement_ref": "agency_signed_a",
        "operator_rights_reviewed": True, "metadata_display_permitted": True,
        "allowed_source_hosts": ["agency.example.ua"],
        "valid_until": "2028-01-01", "full_snapshot_allowed": True,
    }))
    feed = tmp_path / "partner.jsonl"
    feed.write_text(json.dumps({
        "external_id": "P-11", "source_url": "https://agency.example.ua/p/11",
        "operation": "rent", "property_type": "apartment",
        "city": "Київ", "price_uah": 19000
    }, ensure_ascii=False) + "\n")
    db = tmp_path / "inventory.sqlite"
    ingest(feed, grant, db, now=NOW)
    return db


def partner(**overrides):
    return {
        "id": 711, "source": "partner:agency_one",
        "partnerSourceKey": "agency_one", "partnerExternalId": "P-11",
        "url": "https://agency.example.ua/p/11",
        "title": "Партнерський тестовий лот", "price": 19000,
        "actualityConfirmed": True, "contactVerified": True,
        "phone": "+380501112233", "ownerName": "Private owner",
        **overrides,
    }


def verified_at_review_time():
    return {"711": {"state": "verified", "availability": {
        "reviewer": "authorized_operator", "evidence_ref": "private/a-11",
        "checked_at": NOW.isoformat(), "available": True,
    }}}


def approved(db):
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE inventory SET review_status='approved' "
            "WHERE source='agency_one' AND external_id='P-11'"
        )


def viewed(offer, reviews=None):
    return public_listing_view([offer], reviews, now=NOW)


def test_partner_not_visible_without_active_private_rights(tmp_path):
    row = viewed(partner(), verified_at_review_time())[0]
    assert enforce_partner_visibility([row], "", now=NOW) == []
    assert enforce_partner_visibility([row], str(tmp_path / "missing.db"), now=NOW) == []
    bad = tmp_path / "garbage.db"
    bad.write_text("not a database")
    assert enforce_partner_visibility([row], str(bad), now=NOW) == []


def test_partner_requires_approval_and_recent_independent_availability(tmp_path):
    db = private_inventory(tmp_path)
    # A feed claim of actuality=true is removed by private reviewer gate.
    unreviewed = viewed(partner())
    assert unreviewed[0]["actualityConfirmed"] is False
    assert enforce_partner_visibility(unreviewed, str(db), now=NOW) == []
    reviewed = viewed(partner(), verified_at_review_time())
    assert reviewed[0]["actualityConfirmed"] is True
    assert enforce_partner_visibility(reviewed, str(db), now=NOW) == []
    approved(db)
    assert enforce_partner_visibility(reviewed, str(db), now=NOW) == reviewed


def test_revoked_or_expired_partner_disappears_without_delete_of_inventory(tmp_path):
    db = private_inventory(tmp_path)
    approved(db)
    row = viewed(partner(), verified_at_review_time())[0]
    assert len(enforce_partner_visibility([row], str(db), now=NOW)) == 1
    assert enforce_partner_visibility(
        [row], str(db), now=datetime(2029, 1, 1, tzinfo=timezone.utc)
    ) == []
    revoke_source(db, "agency_one", "partner_request", now=NOW)
    assert enforce_partner_visibility([row], str(db), now=NOW) == []
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 1


@pytest.mark.parametrize("broken", [
    {"partnerSourceKey": "another_partner"},
    {"partnerSourceKey": None},
    {"partnerExternalId": None},
    {"partnerExternalId": "../etc/passwd"},
    {"url": "https://agency.example.ua.evil.test/p/11"},
    {"url": "http://agency.example.ua/p/11"},
    {"url": "https://agency.example.ua/p/11?utm=untrusted"},
    {"source": "Київ Радар"},
])
def test_mismatched_partner_identity_never_bypasses_rights(tmp_path, broken):
    db = private_inventory(tmp_path)
    approved(db)
    # This crafted claim cannot bypass the server-side private source check.
    offer = viewed({**partner(), **broken}, verified_at_review_time())
    assert enforce_partner_visibility(offer, str(db), now=NOW) == []


def test_legacy_unrelated_catalog_remains_unchanged(tmp_path):
    db = private_inventory(tmp_path)
    olx = {"id": 10, "source": "OLX", "url": "https://www.olx.ua/d/uk/obyavlenie/example"}
    owner = {"id": 12, "source": "Київ Радар", "title": "Власний об'єкт"}
    bogus = partner()
    assert enforce_partner_visibility([olx, bogus, owner], str(db), now=NOW) == [olx, owner]


def test_source_error_does_not_hide_unrelated_owner_listing(tmp_path):
    db = tmp_path / "empty.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE unrelated(id INTEGER)")
    owner = {"id": 20, "source": "Київ Радар"}
    assert enforce_partner_visibility([partner(), owner], str(db), now=NOW) == [owner]


def test_api_catalog_health_and_contact_lookup_share_the_same_rights_gate(tmp_path, monkeypatch):
    db = private_inventory(tmp_path)
    approved(db)
    reg = tmp_path / "private-reviews.json"
    actual = verified_at_review_time()
    actual["711"]["availability"]["checked_at"] = datetime.now(timezone.utc).isoformat()
    reg.write_text(json.dumps({"schema_version": 1, "listings": actual}))
    monkeypatch.setattr(api, "REVIEW_REGISTER_PATH", str(reg))
    monkeypatch.setattr(api, "PARTNER_RIGHTS_DB_PATH", str(db))
    monkeypatch.setattr(api, "load_trusted_deals", lambda: [partner()])
    client = TestClient(api.app)

    # Partner can be served only with a private reviewer and current source rights.
    first = client.get("/api/deals")
    assert first.status_code == 200
    assert [x["id"] for x in first.json()["deals"]] == [711]
    item = first.json()["deals"][0]
    for private_key in ("partnerSourceKey", "partnerExternalId", "ownerName", "evidence_ref"):
        assert private_key not in item
    assert item["phone"] is None

    revoke_source(db, "agency_one", "partner_request", now=NOW)
    after = client.get("/api/deals")
    assert after.status_code == 200 and after.json()["deals"] == []
    health = client.get("/api/health")
    assert health.status_code == 200 and health.json()["deals_count"] == 0
    # /api/send_contact uses the same load_effective_deals() path.


def test_no_partner_data_may_be_embedded_in_public_offline_copies():
    repo = Path(__file__).resolve().parents[1]
    catalog = json.loads((repo / "data" / "deals.json").read_text(encoding="utf-8"))
    assert all("partnerSourceKey" not in item and
               "partnerExternalId" not in item and
               not str(item.get("source", "")).lower().startswith("partner:")
               for item in catalog)
    page = (repo / "index.html").read_text(encoding="utf-8")
    assert "staticCatalogWithoutPartners(KYIV_DEALS_INIT)" in page
    assert "staticCatalogWithoutPartners(dataJson)" in page
    assert "function staticCatalogWithoutPartners(records)" in page
    initial = re.search(r"const KYIV_DEALS_INIT\\s*=\\s*(\\[[^\\n]+\\]);", page)
    assert initial, "No embedded catalog found"
    embedded = json.loads(initial.group(1))
    assert all("partnerSourceKey" not in item and
               "partnerExternalId" not in item and
               not str(item.get("source", "")).lower().startswith("partner:")
               for item in embedded)

