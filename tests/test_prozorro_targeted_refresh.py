import json
from datetime import timedelta
import pytest

from scripts.prozorro_targeted_refresh import discover, recheck, refresh, BASE
from scripts.prozorro_review_cache import apply_page, review_candidates
from test_prozorro_auction_candidates import payload, NOW


def row(**changes):
    p = payload()
    p["dateModified"] = NOW.isoformat()
    p.update(changes)
    return p


def test_discovery_uses_only_supported_methods():
    calls = []
    def fetch(url):
        calls.append(url)
        return json.dumps([row()] if "commercialSell-english" in url else []).encode()
    assert len(discover(now=NOW, request_fn=fetch)) == 1
    assert calls == [BASE+"bySellingMethod/commercialSell-english?limit=10",
                     BASE+"bySellingMethod/alienation-english?limit=10"]


def test_recheck_identity_and_invalid_id():
    with pytest.raises(ValueError):
        recheck("../bad", now=NOW, request_fn=lambda _: pytest.fail("network"))
    with pytest.raises(ValueError, match="identity"):
        recheck("ALE001-UA-20261124-00000", now=NOW,
                request_fn=lambda _: json.dumps(row()).encode())


def test_refresh_rechecks_known_object_and_withdraws(tmp_path):
    tmp_path.chmod(0o700)
    apply_page(tmp_path, [row()], observed_at=NOW, now=NOW)
    later = NOW + timedelta(minutes=1)
    def fetch(url):
        if "byAuctionId" in url:
            return json.dumps(row(status="complete", dateModified=later.isoformat())).encode()
        return b"[]"
    result = refresh(tmp_path, now=later, request_fn=fetch)
    assert result["recheck_requests"] == 1
    assert result["private_review_count"] == 0
    assert result["publications"] == 0


def test_failed_refresh_does_not_change_existing_observation(tmp_path):
    tmp_path.chmod(0o700)
    apply_page(tmp_path, [row()], observed_at=NOW, now=NOW)
    later = NOW + timedelta(minutes=1)
    def fetch(url):
        if "byAuctionId" in url:
            raise OSError("network failure")
        return b"[]"
    with pytest.raises(OSError):
        refresh(tmp_path, now=later, request_fn=fetch)
    assert review_candidates(tmp_path, now=later)[0]["observed_at"].startswith(NOW.isoformat()[:19])
    assert review_candidates(tmp_path, now=NOW+timedelta(hours=2)) == []


def test_wrong_selling_method_and_oversized_page():
    with pytest.raises(ValueError):
        discover(now=NOW, request_fn=lambda _: json.dumps([row()]*11).encode())
    with pytest.raises(ValueError, match="selling method"):
        discover(now=NOW, request_fn=lambda _: json.dumps([row(sellingMethod="alienation-english")]).encode())
