from datetime import timedelta
from scripts.prozorro_auction_preview import render
from test_prozorro_review_projection import setup, NOW


def test_preview_default_off():
    r, a, g = setup()
    out = render([r], a, g, now=NOW)
    assert "Розділ вимкнено" in out
    assert r["auction_id"] not in out


def test_preview_approved_card_is_truthful_and_safe():
    r, a, g = setup()
    r["documents"] = ["<script>PRIVATE</script>"]
    out = render([r], a, g, now=NOW, enabled=True)
    assert "123 456,78 ₴" in out
    assert "Стартова ціна не є кінцевою вартістю" in out
    assert "без ПДВ" in out
    assert "Перевірено (Київ)" in out
    assert r["source_url"] in out
    assert "PRIVATE" not in out
    assert "<script" not in out


def test_preview_expired_or_revoked_uses_honest_empty_state():
    r, a, g = setup()
    out = render([r], a, g, now=NOW+timedelta(hours=1), enabled=True)
    assert "Це не повний перелік аукціонів" in out
    assert r["auction_id"] not in out
    a[r["auction_id"]]["status"] = "revoked"
    assert r["auction_id"] not in render([r], a, g, now=NOW, enabled=True)
