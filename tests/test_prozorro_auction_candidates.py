"""Synthetic contract tests only: no network, fixtures or real auction payloads."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from scripts.prozorro_auction_candidates import candidate

NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)


def payload():
    return {
        "sellingMethod": "commercialSell-english",
        "auctionId": "CSE001-UA-20261124-00000",
        "status": "active_tendering",
        "tenderPeriod": {"startDate": "2026-11-23T00:00:00+02:00",
                         "endDate": "2026-11-25T00:00:00+02:00"},
        "items": [{"classification": {"scheme": "CAV", "id": "04111000-9"},
                   "address": {"countryName": "Україна", "locality": "Київ",
                               "region": "Київ", "streetAddress": "PRIVATE"},
                   "description": "PRIVATE"}],
        "value": {"amount": 123456.78, "currency": "UAH", "valueAddedTaxIncluded": False},
        "documents": ["PRIVATE"], "title": "PRIVATE", "contactPoint": "PRIVATE",
    }


def convert(p, observed=NOW):
    return candidate(p, observed_at=observed, now=NOW)


def test_whitelist_and_price_semantics():
    row = convert(payload())
    assert row["starting_bid_uah"] == "123456.78"
    assert row["vat_included"] is False
    assert row["kind"] == "sale_auction"
    assert row["review_status"] == "pending_review"
    assert row["publication_allowed"] is False
    assert "PRIVATE" not in repr(row)
    assert "price_uah" not in row
    assert row["source_url"] == "https://prozorro.sale/auction/CSE001-UA-20261124-00000/"


@pytest.mark.parametrize("key,value", [
    ("status", "complete"), ("status", "cancelled"), ("status", "active_auction"),
    ("sellingMethod", "commercialPropertyLease-english"),
    ("auctionId", "../../secret"), ("items", []), ("items", None),
    ("tenderPeriod", {"startDate": "2026-11-20", "endDate": "2026-11-25"}),
    ("tenderPeriod", {"startDate": "2026-11-20T00:00:00Z", "endDate": "2026-11-24T12:00:00Z"}),
    ("tenderPeriod", {"startDate": "2026-11-25T00:00:00Z", "endDate": "2026-11-27T00:00:00Z"}),
])
def test_ineligible_procedure(key, value):
    p = payload()
    p[key] = value
    assert convert(p) is None


@pytest.mark.parametrize("field,value", [
    ("amount", "NaN"), ("amount", "Infinity"), ("amount", True),
    ("amount", -1), ("amount", "10.001"), ("currency", "USD"),
    ("valueAddedTaxIncluded", None), ("valueAddedTaxIncluded", "false"),
])
def test_bad_value(field, value):
    p = payload()
    p["value"][field] = value
    assert convert(p) is None


@pytest.mark.parametrize("field,value", [
    ("locality", "Буча"), ("locality", "Київська область"), ("countryName", "Poland"),
    ("region", "Львівська область"),
])
def test_geography(field, value):
    p = payload()
    p["items"][0]["address"][field] = value
    assert convert(p) is None


def test_multiple_assets_and_non_residential_rejected():
    p = payload()
    p["items"].append(deepcopy(p["items"][0]))
    assert convert(p) is None
    p = payload()
    p["items"][0]["classification"]["id"] = "06000000-2"
    assert convert(p) is None


def test_freshness():
    assert convert(payload(), NOW - timedelta(hours=1, seconds=1)) is None
    assert convert(payload(), NOW + timedelta(seconds=1)) is None
    assert convert(payload(), NOW - timedelta(hours=1)) is not None


def test_malformed_record_and_naive_observation():
    assert convert(None) is None
    with pytest.raises(ValueError):
        convert(payload(), NOW.replace(tzinfo=None))
