# -*- coding: utf-8 -*-
"""Catalog integrity: reviewer leads, NOT automatic scam labels or source rights."""
import json
from pathlib import Path

from scripts.catalog_integrity import (
    analyze_integrity, canonical_url, photo_key, has_publication_time, has_last_seen
)


def row(id, **kwargs):
    return {
        "id": id, "source": "OLX", "url": f"https://www.olx.ua/d/uk/obyavlenie/apartment-IDabc{id}77.html",
        "images": [f"https://cdn.example.org/photo_{id}.jpg"],
        "title": "Оренда квартири", "district": "Дарницький",
        "price": 12000, "rooms": 1, "area": 43,
        "actualityConfirmed": False, "isOwnerVerified": False,
        "commissionVerified": False, **kwargs
    }


def test_tracking_query_does_not_hide_same_source_duplicate():
    records = [
        row(1, url="https://www.olx.ua/d/uk/obyavlenie/nova-ID11abCd.html?utm_source=tg"),
        row(2, url="https://olx.ua/d/uk/obyavlenie/nova-ID11abcd.html?gclid=abc")
    ]
    result = analyze_integrity(records)
    assert result["candidate_pair_count"] == 1
    entry = result["candidate_pairs"][0]
    assert entry["ids"] == [1, 2]
    assert entry["same_source_identity"] is True
    assert entry["priority"] == "high_review"
    assert entry["is_duplicate"] is None and entry["is_fraud"] is None
    assert "gclid" not in json.dumps(result)


def test_one_shared_photo_is_only_review_not_automatic_duplicate():
    records = [
        row(1, images=["https://ireland.apollo.olxcdn.com:443/v1/files/w8czvguqdtva2-UA/image;s=1000x750"]),
        row(2, source="DOM.RIA", images=["https://ireland.apollo.olxcdn.com/v1/files/w8czvguqdtva2-UA/image;s=200x150"]),
    ]
    result = analyze_integrity(records)
    assert result["candidate_pair_count"] == 1
    entry = result["candidate_pairs"][0]
    assert entry["priority"] == "review"
    assert entry["shared_photo_count"] == 1
    assert not entry["same_source_identity"]
    assert entry["is_duplicate"] is None
    assert "ireland.apollo" not in json.dumps(result)


def test_two_shared_photo_assets_escalate_human_review():
    photos = ["https://example.org/media/one.jpg", "https://example.org/media/two.jpg"]
    result = analyze_integrity([
        row(1, images=photos),
        row(2, images=photos[::-1]),
    ])
    assert result["candidate_pair_count"] == 1
    assert result["high_review_count"] == 1
    assert result["candidate_pairs"][0]["shared_photo_count"] == 2


def test_identical_price_and_district_never_prove_duplicate():
    result = analyze_integrity([row(1), row(2)])
    assert result["candidate_pair_count"] == 0
    assert result["high_review_count"] == 0


def test_invalid_and_private_data_are_never_leaked():
    raw = {
        "id": 1, "url": "http://somewhere.test", "source": "OLX",
        "images": [], "phone": "+380501112233", "ownerName": "Test Person",
        "desc": "This description is private", "verifiedAt": "Імпортовано (16.11.2026)",
    }
    result = analyze_integrity([raw])
    txt = json.dumps(result)
    for secret in ("+380501112233", "Test Person", "This description"):
        assert secret not in txt
    assert result["missing_source_publication_timestamp"] == 1
    assert result["missing_source_last_seen_timestamp"] == 1
    assert result["unconfirmed_owner"] == 1
    assert result["unconfirmed_zero_commission"] == 1


def test_iso_timestamp_is_not_inferred_from_import_label():
    assert not has_publication_time({"verifiedAt": "Імпортовано з OLX (16.11.2026)"})
    assert not has_last_seen({"verifiedAt": "2026-11-16"})
    assert has_publication_time({"publishedAt": "2026-11-17T14:20:00+02:00"})
    assert has_last_seen({"sourceLastSeenAt": "2026-11-17T12:20:00Z"})


def test_url_rules_ignore_query_and_normalize_olx_photo_identity():
    assert canonical_url("https://www.OLX.ua/d/uk/offer-ID7hGkT.html?source=tg") \
           == canonical_url("https://olx.ua/d/uk/offer-ID7hGkT.html")
    assert photo_key("https://ireland.apollo.olxcdn.com:443/v1/files/abc12345-UA/image;s=1000x750") \
           == photo_key("https://ireland.apollo.olxcdn.com/v1/files/abc12345-UA/image;s=300x200")


def test_actual_kyiv_catalog_has_honest_provenance_and_no_fake_verification():
    root = Path(__file__).resolve().parents[1]
    records = json.loads((root / "data" / "deals.json").read_text(encoding="utf-8"))
    report = analyze_integrity(records)
    assert report["total"] == len(records)
    assert report["total"] == 150  # update only with a separately reviewed catalog change
    assert report["source_distribution"] == {"DOM.RIA": 61, "OLX": 89}
    assert report["missing_source_publication_timestamp"] == 150
    assert report["missing_source_last_seen_timestamp"] == 150
    assert report["unconfirmed_owner"] == 150
    assert report["unconfirmed_zero_commission"] == 150
    assert report["candidate_pair_count"] >= 1
    assert all(pair["is_duplicate"] is None and pair["is_fraud"] is None
               for pair in report["candidate_pairs"])


def test_invalid_input_returns_explicit_error_instead_of_silent_empty_dataset():
    for value in (None, "not-a-list", {}):
        try:
            analyze_integrity(value)
            assert False, "must reject malformed records"
        except ValueError:
            pass
