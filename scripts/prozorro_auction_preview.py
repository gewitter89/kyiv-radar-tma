"""Render a local, read-only auction staging preview from trusted gate inputs.

No server, network, public route, browser-supplied approvals or automatic export.
"""
import html
from decimal import Decimal
from zoneinfo import ZoneInfo
from .prozorro_review_projection import project
from .prozorro_auction_candidates import _utc

KYIV = ZoneInfo("Europe/Kyiv")


def render(candidates, approvals, rights, *, now, enabled=False):
    rows = project(candidates, approvals, rights, now=now, enabled=enabled)
    cards = []
    for r in sorted(rows, key=lambda r: (r["bidding_ends_at"], r["auction_id"])):
        price = f'{Decimal(r["starting_bid_uah"]):,.2f}'.replace(",", " ").replace(".", ",")
        deadline = _utc(r["bidding_ends_at"]).astimezone(KYIV).strftime("%d.%m.%Y, %H:%M")
        observed = _utc(r["observed_at"]).astimezone(KYIV).strftime("%d.%m.%Y, %H:%M")
        cards.append(f"""<article><p class="eyebrow">Prozorro.Продажі · Київ</p>
<h2>Квартира · Аукціон продажу</h2><p class="price">{html.escape(price)} ₴</p>
<p class="muted">Стартова ціна · {'з ПДВ' if r["vat_included"] else 'без ПДВ'}</p>
<dl><dt>Заявки до (Київ)</dt><dd>{html.escape(deadline)}</dd>
<dt>Перевірено (Київ)</dt><dd>{html.escape(observed)}</dd></dl>
<p class="muted code">{html.escape(r["auction_id"])}</p>
<a href="{html.escape(r["source_url"], quote=True)}" rel="noopener noreferrer">Переглянути оригінал</a></article>""")
    if enabled is not True:
        body = '<p class="notice">Розділ вимкнено. Публічний доступ не надано.</p>'
    elif not cards:
        body = '<p class="notice">Немає підтверджених актуальних об’єктів у цій вибірці. Це не повний перелік аукціонів.</p>'
    else:
        body = '<p class="notice">Стартова ціна не є кінцевою вартістю купівлі. Перевіряйте умови на джерелі.</p><section aria-label="Аукціони">' + "".join(cards) + '</section>'
    return """<!doctype html><html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Київ Радар — Аукціони · Попередній перегляд</title>
<style>
:root{color-scheme:dark;--bg:#101113;--card:#1c1d20;--muted:#a6a9b2;--border:#34363b;--blue:#98c4ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#f3f4f6;font:16px/1.5 system-ui,sans-serif}
main{max-width:960px;padding:24px 16px;margin:auto}header{border-bottom:1px solid var(--border);padding-bottom:16px}
.brand{font-size:14px;font-weight:750;letter-spacing:.12em;color:var(--blue)}h1{font-size:28px;line-height:1.15;margin:10px 0}h2{font-size:19px;margin:8px 0}
p{margin:0 0 10px}.muted,.eyebrow{color:var(--muted);font-size:14px}.notice{font-size:14px;padding:14px;background:var(--card);border:1px solid var(--border);border-radius:12px;margin:18px 0}
section{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr))}
article{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:18px;min-width:0}
.price{font-size:clamp(23px,6vw,30px);font-weight:750;letter-spacing:-.04em;overflow-wrap:anywhere;font-variant-numeric:tabular-nums}
dl{display:grid;grid-template-columns:1fr;gap:3px;border-block:1px solid var(--border);padding:12px 0}dt{font-size:13px;color:var(--muted)}dd{margin:0 0 6px}.code{overflow-wrap:anywhere}
a{display:block;text-align:center;background:#a7caff;color:#101827;font-weight:700;text-decoration:none;padding:12px;border-radius:10px;min-height:44px}a:focus-visible{outline:3px solid white;outline-offset:4px}
</style></head><body><main><header><p class="brand">КИЇВ РАДАР</p><h1>Аукціони</h1><p class="muted">Приватний попередній перегляд · Не публічний каталог</p></header>""" + body + "</main></body></html>"
