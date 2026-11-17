# -*- coding: utf-8 -*-
"""Only rights-gated partner and moderated first-party rows may be exported."""
from server.public_eligibility import eligible_public_row, public_eligible_rows


def row(source, **attrs):
    return {"id": 123, "source": source, "title": "synthetic example",
            "price": 10000, **attrs}


def test_historical_imports_fail_closed_even_with_provider_claims():
    for source in ("OLX", "DOM.RIA", "olx", "DOM.ria", "", None, "unknown"):
        assert not eligible_public_row(row(source, actualityConfirmed=True,
                                          contactVerified=True, isOwnerVerified=True))


def test_first_party_must_be_moderator_approved():
    for source in ("Київ Радар", "Київ Радар (Пряма заявка)"):
        assert not eligible_public_row(row(source))
        assert not eligible_public_row(row(source, moderationStatus="pending_review"))
        assert not eligible_public_row(row(source, moderationStatus="withdrawn"))
        assert eligible_public_row(row(source, moderationStatus="approved"))


def test_fixtures_always_rejected():
    assert not eligible_public_row(row("Київ Радар", moderationStatus="approved",
                                      fixtureOnly=True))
    assert not eligible_public_row(row("partner:agency", partnerSourceKey="agency",
                                      partnerExternalId="X1", fixtureOnly=True))


def test_partner_needs_consistent_trusted_source_identifiers():
    assert not eligible_public_row(row("partner:agency"))
    assert not eligible_public_row(row("partner:agency", partnerSourceKey="other",
                                      partnerExternalId="X1"))
    assert not eligible_public_row(row("partner:agency", partnerSourceKey="agency"))
    assert eligible_public_row(row("partner:agency", partnerSourceKey="agency",
                                   partnerExternalId="X1"))


def test_filter_is_nonmutating_and_protects_empty_or_malformed_rows():
    original = [
        row("OLX"),
        row("Київ Радар (Пряма заявка)", moderationStatus="approved"),
        row("partner:agency", partnerSourceKey="agency", partnerExternalId="A1"),
        row("partner:agency", partnerSourceKey="agency", partnerExternalId=""),
        {"id": 2, "source": "OLX", "phone": "+380501112233"},
        "bad"
    ]
    actual = public_eligible_rows(original)
    assert [r["source"] for r in actual] == ["Київ Радар (Пряма заявка)", "partner:agency"]
    assert len(original) == 6
    assert public_eligible_rows(None) == []


def test_live_api_all_surfaces_use_same_public_gate(monkeypatch):
    import os
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("BOT_TOKEN", "123456789:TEST_BOT_TOKEN_FOR_HMAC_VALIDATION")
    from fastapi.testclient import TestClient
    from server import kyiv_radar_api as api
    from unittest.mock import patch
    raw = [
        row("OLX", phone="+380501112233"),
        row("Київ Радар (Пряма заявка)", moderationStatus="approved"),
    ]
    with patch.object(api, "load_trusted_deals", return_value=raw), \
         patch.object(api, "load_private_register", return_value={}), \
         patch.object(api, "enforce_partner_visibility", side_effect=lambda x, _: x):
        client = TestClient(api.app)
        catalog = client.get("/api/deals")
        health = client.get("/api/health")
        assert catalog.status_code == 200
        assert [x["id"] for x in catalog.json()["deals"]] == [123]
        assert health.json()["deals_count"] == 1
        # Contact lookup uses load_effective_deals too. In this simple fixture
        # both IDs overlap (123); independent deny test below uses distinct IDs.


def test_hidden_legacy_contact_is_404_before_phone_delivery(monkeypatch):
    import os
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("BOT_TOKEN", "123456789:TEST_BOT_TOKEN_FOR_HMAC_VALIDATION")
    from fastapi.testclient import TestClient
    from server import kyiv_radar_api as api
    from unittest.mock import patch
    old = row("OLX", phone="+380501112233")
    old["id"] = 700
    with patch.object(api, "load_trusted_deals", return_value=[old]), \
         patch.object(api, "load_private_register", return_value={}), \
         patch.object(api, "enforce_partner_visibility", side_effect=lambda x, _: x), \
         patch.object(api, "validate_telegram_init_data", return_value={"id": 9876}), \
         patch.object(api, "check_rate_limit", return_value=True):
        response = TestClient(api.app).post("/api/send_contact",
            json={"dealId": 700, "initData": "synthetic-test-signature-only"})
        assert response.status_code == 404
