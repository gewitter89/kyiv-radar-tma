# -*- coding: utf-8 -*-
"""Evidence, privacy, publication and monitoring regression tests for 1.8."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "123456789:TEST_BOT_TOKEN_FOR_HMAC_VALIDATION")
os.environ.setdefault("APP_ENV", "test")

from server import kyiv_radar_api as api
from server.listing_trust import load_private_register, public_listing_view
from scripts.audit_catalog import audit_catalog
from scripts.monitor_public_health import verify_pages_html, verify_public_api

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def proof(*, days=0, available=None, confirmed=None):
    record = {
        "reviewer": "staff-7",
        "evidence_ref": "private/case-24",
        "checked_at": (NOW-timedelta(days=days)).isoformat(),
    }
    if available is not None:
        record["available"] = available
    if confirmed is not None:
        record["confirmed"] = confirmed
    return record


def imported(id_=42):
    return {"id": id_, "title": "2 кімнати", "source": "OLX", "price": 11000,
            "phone": None, "isOwnerVerified": True, "actualityConfirmed": True,
            "commissionVerified": True, "locationVerified": True,
            "verifiedAt": "2026-11-01", "contactVerified": True,
            "status": "Опубліковано"}


def test_imported_claims_are_not_automatically_trusted():
    [row] = public_listing_view([imported()], now=NOW)
    for key in ("actualityConfirmed", "isOwnerVerified", "commissionVerified",
                "locationVerified", "contactVerified"):
        assert row[key] is False
    assert row["statusLabel"] == "Актуальність не перевірено"
    assert row["verificationStatus"] == "unverified"
    assert "verifiedAt" not in row


def test_availability_proof_only_confirms_availability_and_keeps_evidence_private():
    reviewed = {
        "42": {
            "state": "verified",
            "availability": proof(available=True),
        }
    }
    [row] = public_listing_view([imported()], reviewed, now=NOW)
    assert row["actualityConfirmed"] is True
    assert row["isOwnerVerified"] is False
    assert row["commissionVerified"] is False
    assert row["locationVerified"] is False
    assert row["contactVerified"] is False
    assert row["verifiedAt"].startswith("2026-11-17")
    assert "evidence_ref" not in row
    assert "reviewer" not in row


@pytest.mark.parametrize("claim", [
    {"availability": {"available": True, "reviewer": "staff-7", "checked_at": NOW.isoformat()}},
    {"availability": {"available": True, "evidence_ref": "case-4", "checked_at": NOW.isoformat()}},
    {"availability": {"available": True, "reviewer": "staff-7", "evidence_ref": "case-4",
                      "checked_at": "2020-01-01T00:00:00+00:00"}},
    {"availability": {"available": True, "reviewer": "staff-7", "evidence_ref": "case-4",
                      "checked_at": "yesterday"}},
    {"availability": {"available": False, "reviewer": "staff-7", "evidence_ref": "case-4",
                      "checked_at": NOW.isoformat()}},
])
def test_expired_or_incomplete_claims_fail_closed(claim):
    [row] = public_listing_view([imported()], {"42": {"state": "verified", **claim}}, now=NOW)
    assert row["actualityConfirmed"] is False


def test_independent_evidence_for_each_claim():
    checks = {
        "42": {"state": "verified", "availability": proof(available=True),
               "ownership": proof(confirmed=True), "contact": proof(confirmed=True),
               "zero_commission": proof(days=20, confirmed=True),
               "location": proof(confirmed=False)},
    }
    [row] = public_listing_view([imported()], checks, now=NOW)
    assert row["actualityConfirmed"] and row["isOwnerVerified"] and row["contactVerified"]
    assert not row["commissionVerified"] and not row["locationVerified"]


@pytest.mark.parametrize("state", ["hidden", "removed", "withdrawn", "archived"])
def test_moderator_can_withdraw_listing_from_catalog(state):
    assert public_listing_view([imported()], {"42": {"state": state}}, now=NOW) == []
    row = {**imported(), "status": state}
    assert public_listing_view([row], now=NOW) == []


def test_first_party_fixtures_remain_supported_without_imported_claim_reset():
    row = {"id": 53, "source": "Київ Радар", "isOwnerVerified": True}
    assert public_listing_view([row], now=NOW)[0]["isOwnerVerified"] is True


def test_review_registry_only_reads_schema_and_never_falls_back_to_untrusted_data(tmp_path):
    doc = tmp_path / "registry.json"
    doc.write_text('{"schema_version":1,"listings":{"42":{"state":"hidden"}}}', encoding="utf-8")
    assert load_private_register(str(doc)) == {"42": {"state": "hidden"}}
    doc.write_text('{"schema_version":0,"listings":{"42":{"state":"verified"}}}')
    assert load_private_register(str(doc)) == {}
    doc.write_text('not json')
    assert load_private_register(str(doc)) == {}
    assert load_private_register(str(doc.parent / "missing.json")) == {}


def test_api_hides_withdrawn_and_does_not_export_moderator_evidence(monkeypatch, tmp_path):
    doc = tmp_path / "reviews.json"
    doc.write_text(json.dumps({
        "schema_version": 1,
        "listings": {"7": {"state": "hidden"}, "8": {"state": "verified",
            "availability": {"reviewer": "operator", "evidence_ref": "private/case-8",
              "checked_at": datetime.now(timezone.utc).isoformat(), "available": True}}}
    }), encoding="utf-8")
    monkeypatch.setattr(api, "REVIEW_REGISTER_PATH", str(doc))
    monkeypatch.setattr(api, "load_trusted_deals", lambda: [
        {**imported(7), "phone": "+380123456789", "ownerName": "private"},
        {**imported(8), "source": "Київ Радар (Пряма заявка)",
         "submission_id": 8, "moderationStatus": "approved",
         "actualityConfirmed": False, "phone": "+380123456789",
         "ownerName": "private"},
    ])
    resp = TestClient(api.app).get("/api/deals")
    assert resp.status_code == 200
    payload = resp.json()
    assert [deal["id"] for deal in payload["deals"]] == [8]
    row = payload["deals"][0]
    assert row["phone"] is None
    assert "ownerName" not in row
    assert row["actualityConfirmed"] is True
    assert "evidence_ref" not in str(row)


def test_catalog_audit_detects_problems_without_fake_verification():
    report = audit_catalog([{
        "id": 2, "source": "OLX", "title": "Test listing", "price": 10000,
        "address": "грнДодати в обране", "lat": 50.0, "lng": 30.0,
        "images": ["https://example.invalid/photo.jpg"], "url": "https://www.olx.ua/example"
    }])
    assert report["counts"]["imported_unverified_actuality"] == 1
    assert report["flagged_ids"]["scraped_address_noise"] == [2]
    assert report["flagged_ids"]["unverified_exact_coordinates"] == [2]
    assert not report["ready_for_public_claims"]
    assert report["counts"]["eligible_for_verified_new_listing_alerts"] == 0


def test_catalog_audit_rejects_duplicates_and_private_contacts():
    records = [{"id": 9, "source": "OLX", "phone": "+380501111111"},
               {"id": 9, "source": "OLX"}]
    report = audit_catalog(records)
    assert len(report["fatal"]) >= 2


def test_monitor_accepts_actual_product_title_with_empty_static_catalog():
    page = (
        "<!doctype html><html><head><title>Київ Радар — оренда з урахуванням автономності</title></head>"
        "<body><script>const KYIV_DEALS_INIT = []; "
        "function approvedHostedListing(item){}</script></body></html>"
    )
    verify_pages_html(page)
    with pytest.raises(AssertionError):
        verify_pages_html(page.replace("Київ Радар", "Unrelated site"))


def test_monitor_catches_public_data_exposure_and_malformed_api():
    health = {"status": "healthy", "version": "1.6.0", "deals_count": 1}
    row = {"id": 1, "source": "Київ Радар (Пряма заявка)", "phone": None}
    assert verify_public_api(health, {"success": True, "deals": [row]}) == 1
    with pytest.raises(AssertionError):
        verify_public_api(health, {"success": True, "deals": [
            dict(row, phone="+380501111111")
        ]})
    with pytest.raises(AssertionError):
        verify_public_api(dict(health, deals_count=2), {"success": True,
                                                        "deals": [row, row]})
    with pytest.raises(AssertionError):
        verify_public_api(health, {"success": True, "deals": [
            {"id": 1, "source": "OLX", "phone": None}
        ]})


def test_hidden_listing_contact_is_rejected_even_with_valid_telegram_auth(monkeypatch, tmp_path):
    doc = tmp_path / "private_reviews.json"
    doc.write_text(json.dumps({
        "schema_version": 1, "listings": {"42": {"state": "hidden"}}
    }), encoding="utf-8")
    monkeypatch.setattr(api, "REVIEW_REGISTER_PATH", str(doc))
    monkeypatch.setattr(api, "load_trusted_deals", lambda: [imported()])
    monkeypatch.setattr(api, "validate_telegram_init_data", lambda _data: {"id": 998877})
    monkeypatch.setattr(api, "check_rate_limit", lambda *a, **kw: True)
    def reject_contact_lookup(*args):
        raise AssertionError("Hidden listing must not reach private contact lookup")
    monkeypatch.setattr(api, "get_private_contact", reject_contact_lookup)
    response = TestClient(api.app).post("/api/send_contact",
                                        json={"dealId": 42, "initData": "signed-mock"})
    assert response.status_code == 404


def test_verified_availability_has_a_public_evidence_gated_marker():
    records = {"42": {"state": "verified", "availability": proof(available=True)}}
    [row] = public_listing_view([imported()], records, now=NOW)
    assert row["reviewedByRadar"] is True
    assert "reviewer" not in row and "evidence_ref" not in row
