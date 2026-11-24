from datetime import timedelta
from copy import deepcopy
import pytest

from scripts.prozorro_auction_candidates import candidate
from scripts.prozorro_review_projection import project, fingerprint, SCOPE
from test_prozorro_auction_candidates import payload, NOW


def setup():
    row = candidate(payload(), observed_at=NOW, now=NOW)
    rights = {"status": "approved", "scope": SCOPE, "evidence_id": "synthetic-test",
              "valid_from": (NOW-timedelta(days=1)).isoformat(),
              "valid_until": (NOW+timedelta(days=1)).isoformat()}
    approval = {"status": "approved", "fingerprint": fingerprint(row),
                "rights_evidence_id": rights["evidence_id"],
                "approved_at": NOW.isoformat(),
                "valid_until": (NOW+timedelta(hours=2)).isoformat()}
    return row, {row["auction_id"]: approval}, rights


def test_disabled_and_missing_approval_are_empty():
    r, a, g = setup()
    assert project([r], a, g, now=NOW) == []
    assert project([r], {}, g, now=NOW, enabled=True) == []
    assert project([r], a, None, now=NOW, enabled=True) == []


def test_exact_approved_whitelist_and_expiry():
    r, a, g = setup()
    r["contactPoint"] = "PRIVATE"
    r["documents"] = ["PRIVATE"]
    out = project([r], a, g, now=NOW, enabled=True)
    assert len(out) == 1
    assert "PRIVATE" not in repr(out)
    assert "publication_allowed" not in out[0]
    assert out[0]["valid_until"] == (NOW+timedelta(hours=1)).isoformat()
    assert "price_uah" not in out[0]


@pytest.mark.parametrize("field,value", [
    ("starting_bid_uah", "1.00"), ("vat_included", True),
    ("source_url", "https://attacker.invalid"),
    ("bidding_ends_at", "2026-11-26T00:00:00Z"),
    ("city", "Буча"), ("review_status", "withdrawn"),
    ("publication_allowed", True), ("source", "other"),
])
def test_changed_or_withdrawn_record_never_passes(field, value):
    r, a, g = setup()
    r[field] = value
    assert project([r], a, g, now=NOW, enabled=True) == []


@pytest.mark.parametrize("field,value", [
    ("status", "revoked"), ("scope", "wrong"), ("evidence_id", "changed"),
    ("valid_until", NOW.isoformat()), ("valid_from", (NOW+timedelta(seconds=1)).isoformat()),
])
def test_rights_fail_closed(field, value):
    r, a, g = setup()
    g[field] = value
    assert project([r], a, g, now=NOW, enabled=True) == []


def test_refresh_does_not_reset_operator_approval():
    r, a, g = setup()
    later = NOW+timedelta(minutes=30)
    r["observed_at"] = later.isoformat()
    assert len(project([r], a, g, now=later, enabled=True)) == 1
    a[r["auction_id"]]["status"] = "revoked"
    assert project([r], a, g, now=later, enabled=True) == []


def test_stale_duplicate_or_future_observation():
    r, a, g = setup()
    assert project([r], a, g, now=NOW+timedelta(hours=1), enabled=True) == []
    assert project([r, deepcopy(r)], a, g, now=NOW, enabled=True) == []
    r["observed_at"] = (NOW+timedelta(seconds=1)).isoformat()
    assert project([r], a, g, now=NOW, enabled=True) == []
