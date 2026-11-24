# -*- coding: utf-8 -*-
"""No historic/synthetic listing can be packaged in published HTML/JSON."""
import json
from pathlib import Path

import pytest

from scripts.check_public_distribution import verify

BASE_HTML = """
<script>
const KYIV_DEALS_INIT = [];
function approvedHostedListing(item) {
 return item.actualityConfirmed === true && item.reviewedByRadar === true;
}
window.KR_CATALOG_MODE = "unavailable";
</script>
"""


def public_root(tmp_path, html=BASE_HTML, rows=None):
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    (tmp_path / "data" / "deals.json").write_text(
        json.dumps([] if rows is None else rows, ensure_ascii=False), encoding="utf-8"
    )
    return tmp_path


def test_empty_public_catalog_passes(tmp_path):
    verify(public_root(tmp_path))


def test_one_archived_html_row_is_a_release_blocker(tmp_path):
    html = BASE_HTML.replace(
        "KYIV_DEALS_INIT = []", 'KYIV_DEALS_INIT = [{"source":"OLX","id":1}]'
    )
    with pytest.raises(AssertionError, match="zero inventory"):
        verify(public_root(tmp_path, html=html))


def test_one_old_public_json_row_is_a_release_blocker(tmp_path):
    with pytest.raises(AssertionError, match="static catalog"):
        verify(public_root(tmp_path, rows=[{"id":1,"source":"DOM.RIA"}]))


def test_synthetic_ci_fixture_in_public_html_is_a_release_blocker(tmp_path):
    html = BASE_HTML.replace(
        "KYIV_DEALS_INIT = []",
        'KYIV_DEALS_INIT = [{"id":1,"fixtureOnly":true}]',
    )
    with pytest.raises(AssertionError, match="zero inventory"):
        verify(public_root(tmp_path, html=html))


def test_no_fake_success_gate(tmp_path):
    html = BASE_HTML.replace(
        "item.actualityConfirmed === true && item.reviewedByRadar === true",
        "true",
    )
    with pytest.raises(AssertionError, match="eligibility"):
        verify(public_root(tmp_path, html=html))


def test_no_fallback_without_unavailable_state(tmp_path):
    html = BASE_HTML.replace('window.KR_CATALOG_MODE = "unavailable";', "")
    with pytest.raises(AssertionError, match="fail closed"):
        verify(public_root(tmp_path, html=html))


def test_root_js_asset_must_not_contain_source_photo_fingerprint(tmp_path):
    root = public_root(tmp_path)
    (root / "fake_catalog.js").write_text(
        'const image="https://ireland.apollo.olxcdn.com/v1/files/foo";',
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="JavaScript bundle"):
        verify(root)
