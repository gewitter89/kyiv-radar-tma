"""Local operator-only auction review HTML, stdout only. Never a public catalog."""
import argparse
import html
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from .prozorro_auction_candidates import AUCTION_ID, _utc, _aware
from .prozorro_review_cache import review_candidates

KYIV = ZoneInfo("Europe/Kyiv")


def render(rows, *, now):
    now = _aware(now)
    cards = []
    for row in rows:
        try:
            key = row["auction_id"]
            if not isinstance(key, str) or not AUCTION_ID.fullmatch(key):
                continue
            if row.get("publication_allowed") is not False or row.get("review_status") != "pending_review":
                continue
            end = _utc(row["bidding_ends_at"])
            observed = _utc(row["observed_at"])
            if not 0 <= (now-observed).total_seconds() <= 3600 or end <= now:
                continue
            amount = Decimal(row["starting_bid_uah"])
            if (not amount.is_finite() or not 0 < amount <= Decimal("1000000000000")
                    or amount != amount.quantize(Decimal("0.01"))):
                continue
            vat = row["vat_included"]
            if type(vat) is not bool:
                continue
            price = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
            deadline = end.astimezone(KYIV).strftime("%d.%m.%Y %H:%M")
            url = "https://prozorro.sale/auction/" + key + "/"
            cards.append(
                '<article><p class="tag">Очікує перевірки · Київ</p>'
                '<h2>Квартира — аукціон продажу</h2>'
                '<p class="price">' + html.escape(price) + ' грн</p>'
                '<p>Стартова ціна, не кінцева вартість · '
                + ("з ПДВ" if vat else "без ПДВ") + '</p>'
                '<p>Подати заявку до: ' + html.escape(deadline) + ' (Київ)</p>'
                '<p class="id">' + html.escape(key) + '</p>'
                '<a href="' + html.escape(url, quote=True) + '" rel="noopener noreferrer">Оригінал на Prozorro.Продажі</a></article>')
        except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation, OverflowError):
            continue
    content = "".join(cards) or '<p class="empty">Немає актуальних кандидатів у перевіреній вибірці. Це не означає, що на ринку немає аукціонів.</p>'
    return """<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="robots" content="noindex,nofollow"><title>Київ Радар — приватна перевірка аукціонів</title>
<style>body{font:16px/1.5 system-ui,sans-serif;margin:0;background:#f5f6f8;color:#182333}main{max-width:760px;margin:auto;padding:24px}header{border-bottom:1px solid #cbd5e1;padding-bottom:12px}article,.empty{padding:20px;margin:16px 0;background:white;border:1px solid #d9e1e8;border-radius:16px}h1,h2,p{margin:0 0 10px}h1{font-size:24px}h2{font-size:20px}.price{font-size:28px;font-weight:700}.tag,.id{font-size:14px;color:#475569;overflow-wrap:anywhere}a{color:#0753b0;font-weight:600}a:focus-visible{outline:3px solid #0753b0;outline-offset:4px}</style>
</head><body><main><header><h1>Київ Радар · Аукціони</h1><p>Приватна перевірка. Не публічний каталог. Дані з обмеженої вибірки, джерело: Prozorro.Продажі.</p></header>""" + content + "</main></body></html>"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--operator-only", action="store_true")
    args = parser.parse_args()
    if not args.operator_only:
        parser.error("Explicit private operator opt-in required")
    now = datetime.now(timezone.utc)
    print(render(review_candidates(args.private_dir, now=now), now=now))


if __name__ == "__main__":
    main()
