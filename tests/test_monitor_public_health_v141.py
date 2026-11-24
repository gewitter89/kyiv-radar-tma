# -*- coding: utf-8 -*-
"""Offline-only tests for daily public release monitor: source, privacy, zero stock."""
import pytest

from scripts.monitor_public_health import (
    verify_pages_html, verify_public_static_catalog, verify_public_api,
)

HTML = ('<!doctype html><html><head><title>Київ Радар</title></head>'
        '<body><script>const KYIV_DEALS_INIT = []; '
        'function approvedHostedListing(item){}</script></body></html>')
HEALTH = {"status": "healthy", "version": "1.8.0", "deals_count": 0}
EMPTY = {"success": True, "deals": []}


def test_honest_zero_is_healthy():
    verify_pages_html(HTML)
    verify_public_static_catalog([])
    assert verify_public_api(HEALTH, EMPTY) == 0


@pytest.mark.parametrize("bad", [
    [{"id": 1, "source": "OLX"}],
    [{"id": 2, "source": "DOM.RIA"}],
    [{"id": 3, "source": "partner:demo"}],
])
def test_static_archive_or_demo_never_permitted(bad):
    with pytest.raises(AssertionError, match="static"):
        verify_public_static_catalog(bad)


def test_page_must_not_embed_historical_or_synthetic_inventory():
    with pytest.raises(AssertionError, match="embeds"):
        verify_pages_html(HTML.replace("KYIV_DEALS_INIT = []",
                                       'KYIV_DEALS_INIT = [{"id":1,"source":"OLX"}]'))
    with pytest.raises(AssertionError, match="image"):
        verify_pages_html(HTML + "https://ireland.apollo.olxcdn.com/sample.jpg")


@pytest.mark.parametrize("source", ["OLX", "DOM.RIA", "DIM.RIA", "KyivBot", ""])
def test_legacy_source_cannot_pass_api_200_even_if_verified(source):
    item = {"id": 1, "source": source, "phone": None,
            "actualityConfirmed": True, "reviewedByRadar": True}
    with pytest.raises(AssertionError, match="Unlicensed"):
        verify_public_api(
            dict(HEALTH, deals_count=1), {"success": True, "deals": [item]}
        )


def test_synthetic_and_unapproved_partner_url_rejected():
    bad = {"id": 5, "source": "partner:agency", "fixtureOnly": True,
           "url": "https://agency.example.ua/p/5", "phone": None}
    with pytest.raises(AssertionError, match="Synthetic"):
        verify_public_api(dict(HEALTH, deals_count=1),
                          {"success": True, "deals": [bad]})
    bad["fixtureOnly"] = False
    bad["url"] = "http://agency.example.ua/p/5"
    with pytest.raises(AssertionError, match="HTTPS"):
        verify_public_api(dict(HEALTH, deals_count=1),
                          {"success": True, "deals": [bad]})


def test_private_fields_and_duplicated_ids_rejected():
    a = {"id": 7, "source": "Київ Радар (Пряма заявка)", "phone": None}
    b = dict(a, ownerName="private person")
    with pytest.raises(AssertionError, match="Sensitive"):
        verify_public_api(dict(HEALTH, deals_count=1), {"success": True, "deals": [b]})
    with pytest.raises(AssertionError, match="duplicate"):
        verify_public_api(dict(HEALTH, deals_count=2), {"success": True, "deals": [a, a]})


def test_distinct_approved_sources_pass_without_sensitive_fields():
    allowed = [{"id": 10, "source": "Київ Радар (Пряма заявка)", "phone": None},
               {"id": 11, "source": "partner:agency",
                "url": "https://agency.example.ua/p/11", "phone": None}]
    assert verify_public_api(dict(HEALTH, deals_count=2),
                             {"success": True, "deals": allowed}) == 2


def test_catalog_and_health_must_agree():
    with pytest.raises(AssertionError, match="disagree"):
        verify_public_api(dict(HEALTH, deals_count=3), EMPTY)
    with pytest.raises(AssertionError, match="array"):
        verify_public_api(HEALTH, {"success": True, "deals": None})
