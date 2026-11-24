# Prozorro Auction Integration — Production Release Runbook

Status: Stage 3 Final Production Release Gate (Issue #90). Default deny: disabled until explicit operator sign-off.

---

## 1. Legal Basis & Open Data Compliance

- **Source License:** Officially governed by [Prozorro.Продажі Open Data Terms](https://prozorro.sale/opendata/). Redistribution and commercial integration in information products are explicitly permitted with attribution.
- **Official Central Database API:** `https://procedure.prozorro.sale/api`
- **Permitted Scope of Public Fields:**
  - `auction_id`: public procedure identifier (e.g. `ALE001-UA-20261124-04958`)
  - `source_url`: canonical HTTPS lot link (`https://prozorro.sale/auction/<id>/`)
  - `city`: `Київ` (and classified asset category `apartment_classified`)
  - `starting_bid_uah`: initial starting price (not final sales price)
  - `vat_included`: boolean flag (clear indicator whether VAT is included or extra)
  - `bidding_ends_at`: deadline for submitting offers
  - `observed_at` & `valid_until`: freshness and snapshot validity timestamps
- **Prohibited Data (Strictly Excluded):**
  - NO debtor or owner personal names, phone numbers, email addresses.
  - NO raw documents, property appraisal PDFs, or cadastral/registration deeds.
  - NO property photos or third-party platform watermarks.
  - NO market comparables or claims of complete market coverage.

---

## 2. Multi-Tier Identity Separation & Transport Security

```
[ System User: kyiv-radar-auction ]
  └─ systemd service (oneshot every 20m)
  └─ Writes private feed cache to /var/lib/kyiv-radar-auction-pilot/ (mode 0700)
       │
       ▼ (Operator Sanitized Handoff stdout)
[ Trusted Reviewer / Moderator Boundary ]
  └─ scripts.prozorro_moderation_cli: append-only ledger (auction-decisions.sqlite)
  └─ scripts.prozorro_atomic_publish: HMAC-SHA256 sealed snapshot (60s TTL)
       │
       ▼ (Atomic file rename via .tmp)
[ Transport Directory ]
  └─ /var/lib/kyiv-radar-auction-pilot/transport/auction_snapshot.bin (mode 0600)
  └─ /var/lib/kyiv-radar-auction-pilot/transport/auction.key (mode 0600)
       │
       ▼ (Read-only snapshot load, 0 SQLite access)
[ Web Server: kyiv_radar_api ]
  └─ GET /api/auctions (Memory read only, Cache-Control: no-store)
       │
       ▼ (CORS: https://gewitter89.github.io)
[ Client: Kyiv Radar Web & Telegram Mini App ]
```

- **Database Protection:** The web process has ZERO access to the collector SQLite database (`auction-review.sqlite`) or reviewer ledger.
- **Fail-Closed Gate:** If snapshot is older than 60 seconds, signature is tampered, or file is missing, API returns HTTP 503 (`{"available": false, "auctions": []}`) without leaking paths.

---

## 3. Production Configuration & Gating

In production environment:
```ini
# Production release switch (Default: unset/0 -> HTTP 404)
KYIV_RADAR_AUCTIONS_RELEASE=1

# Transport snapshot paths
KYIV_RADAR_AUCTION_SNAPSHOT=/var/lib/kyiv-radar-auction-pilot/transport/auction_snapshot.bin
KYIV_RADAR_AUCTION_KEY=/var/lib/kyiv-radar-auction-pilot/transport/auction.key

# CORS Whitelist (Already active in server/kyiv_radar_api.py)
# Allowed origin: https://gewitter89.github.io
```

- **Default-Deny:** `APP_ENV=production` returns HTTP 404 unless `KYIV_RADAR_AUCTIONS_RELEASE=1`.
- Staging preview flags (`KYIV_RADAR_AUCTIONS_PREVIEW`) have NO effect in production.

---

## 4. Emergency Kill-Switch & Safe Rollback

1. **Instant Section Kill-Switch (< 1 second):**
   ```bash
   # Remove or zero the release flag, or remove the snapshot
   rm -f /var/lib/kyiv-radar-auction-pilot/transport/auction_snapshot.bin
   ```
   *Result:* `/api/auctions` immediately returns 503 / 404. Client hides auction list and shows graceful empty/offline state.

2. **Collector Service Deactivation:**
   ```bash
   systemctl stop kyiv-radar-auction-pilot.timer
   systemctl disable kyiv-radar-auction-pilot.timer
   systemctl stop kyiv-radar-auction-pilot.service
   ```

3. **Complete Removal (Zero Impact on Other Services):**
   ```bash
   rm -f /etc/systemd/system/kyiv-radar-auction-pilot.service /etc/systemd/system/kyiv-radar-auction-pilot.timer
   systemctl daemon-reload
   # Existing services (kyivpulse, ballistic-interceptor, pavlogradpulse) remain untouched.
   ```

---

## 5. Client Integration (GitHub Pages & Telegram Mini App)

- **CORS & Endpoint Resolution:**
  - On GitHub Pages (`https://gewitter89.github.io`), `auction-tab.js` resolves the API to `https://vmi3445944.contaboserver.net/api/auctions`.
  - On local or staging environments, relative `/api/auctions` is used.
  - Arbitrary URL or query flag parameter injection is prohibited.
- **Product Disclaimer Copy:**
  - Banner: *"Prozorro.Продажі · Офіційні відкриті дані. Стартова ціна не є остаточною вартістю продажу. Можуть нараховуватись додаткові збори та ПДВ. Обов’язково перевіряйте оригінал лота за посиланням. Вибірка неповна, не відображає весь ринок."*
  - Card: *"Стартова ціна · без ПДВ (ПДВ нараховується додатково)"* / *"з ПДВ"*, *"Додаткові збори сплачуються окремо"*.
- **Device Verification Disclosure:**
  - Automated headless Playwright testing verified responsive layouts across 320px, 390px, 768px, and 1280px viewports.
  - Physical testing in native iOS/Android Telegram Mini App clients remains an operational post-rollout validation step.
