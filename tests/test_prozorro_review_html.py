from datetime import timedelta
from scripts.prozorro_review_html import render
from scripts.prozorro_auction_candidates import candidate
from test_prozorro_auction_candidates import payload, NOW


def test_local_view_has_clear_auction_semantics():
    p = payload()
    r = candidate(p, observed_at=NOW, now=NOW)
    out = render([r], now=NOW)
    assert "Стартова ціна, не кінцева вартість" in out
    assert "123 456,78 грн" in out
    assert r["source_url"] in out
    assert "PRIVATE" not in out
    assert "Приватна перевірка" in out


def test_stale_or_invalid_candidates_never_render():
    r = candidate(payload(), observed_at=NOW, now=NOW)
    assert r["auction_id"] not in render([r], now=NOW+timedelta(hours=2))
    r["auction_id"] = "<script>alert(1)</script>"
    out = render([r], now=NOW)
    assert "<script>" not in out and "Немає актуальних кандидатів" in out


def test_unsafe_stored_link_is_ignored():
    r = candidate(payload(), observed_at=NOW, now=NOW)
    r["source_url"] = "https://attacker.example"
    out = render([r], now=NOW)
    assert "attacker.example" not in out
    assert "https://prozorro.sale/auction/" in out
