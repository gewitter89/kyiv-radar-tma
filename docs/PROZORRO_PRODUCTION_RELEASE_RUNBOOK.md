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
- **VAT & Additional Fees Disclosure Copy:**
  - *«Prozorro.Продажі · Офіційні відкриті дані. Стартова ціна не є остаточною вартістю продажу. Можуть нараховуватись додаткові збори та ПДВ. Обов’язково перевіряйте оригінал лота за посиланням. Вибірка неповна, не відображає весь ринок.»*
  - Card notice: *«Стартова ціна · без ПДВ; умови ПДВ та зборів перевіряйте на джерелі»* (or *«Стартова ціна · з ПДВ»* when verified), and permanent note *«Додаткові збори сплачуються окремо»*.
- **Prohibited Data (Strictly Excluded):**
  - NO debtor or owner personal names, phone numbers, email addresses.
  - NO raw documents, property appraisal PDFs, or cadastral/registration deeds.
  - NO property photos or third-party platform watermarks.
  - NO market comparables or claims of complete market coverage.

---

## 2. Multi-Tier Identity Separation & Transport Security

```
[ System User: kyiv-radar-auction ]
  └─ systemd service (oneshot every 20m via kyiv-radar-auction-pilot.timer)
  └─ Writes private feed cache to /var/lib/kyiv-radar-auction-pilot/ (mode 0700)
  └─ SQLite cache: /var/lib/kyiv-radar-auction-pilot/auction-review.sqlite (mode 0600)
       │
       ▼ (Sanitized JSON export pipe, zero web access)
[ Trusted Reviewer / Moderator Boundary: kyiv-radar-reviewer ]
  └─ scripts.prozorro_moderation_cli: append-only ledger (auction-decisions.sqlite, mode 0600)
  └─ scripts.prozorro_continuous_publisher: periodically generates HMAC-SHA256 snapshot
       │ (Atomic temp file + fcntl lock + fsync + os.replace)
       ▼
[ Dedicated Transport Directory ]
  └─ Directory: /var/lib/kyiv-radar-transport/ (mode 0750, owner: kyiv-radar-reviewer, group: kyivradar, world: ---)
  └─ Files: /var/lib/kyiv-radar-transport/auction_snapshot.bin (mode 0640, group: kyivradar, world: ---)
  └─ Key: /var/lib/kyiv-radar-transport/auction.key (mode 0640, group: kyivradar, world: ---)
       │
       ▼ (Read-only unseal via auction_snapshot.py; W_OK forbidden)
[ Web Server: kyiv_radar_api (User: kyivradar, Group: kyivradar) ]
  └─ GET /api/auctions (In-memory read-only load, Cache-Control: no-store)
  └─ STRICT CORS: Access-Control-Allow-Origin: https://gewitter89.github.io
       │
       ▼ (Authoritative availability discovery, default-off)
[ Client: Kyiv Radar Web & Telegram Mini App (GitHub Pages) ]
```

### OS Security Boundary Matrix
| Tier | Linux Identity | Storage Location | File Permissions | Network Access | Access Rights |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Collector (Pilot)** | `kyiv-radar-auction` (nologin, non-root) | `/var/lib/kyiv-radar-auction-pilot/` | `0700` dir, `0600` db | Outbound HTTPS only (Prozorro CDB API) | **Private SQLite only** (`auction-review.sqlite`). Zero web access. |
| **Reviewer / Ledger** | `kyiv-radar-reviewer` / operator CLI | `/var/lib/kyiv-radar-auction-review/` | `0700` dir, `0600` ledger | Offline / local pipe only | Append-only SQLite decisions ledger (`auction-decisions.sqlite`). |
| **Atomic Transport** | `kyiv-radar-reviewer` (`scripts/prozorro_atomic_publish.py`) | `/var/lib/kyiv-radar-transport/` | `0750` dir, `0640` snapshot | None (local filesystem `.tmp` -> `os.replace`, fsync) | HMAC-SHA256 sealed binary snapshots (60s TTL), group-readable by `kyivradar`. |
| **Web Server (FastAPI)** | `kyivradar` in group `kyivradar` | Transport directory | Read-only to snapshot (`0640`) | Inbound HTTPS / loopback | **Read-only unseal**. Write permission strictly forbidden (`os.access(W_OK) == False`). ZERO access to collector DB or reviewer ledger. |

---

## 3. Production Configuration & Gating

In production environment:
```ini
# Production release switch (Default: unset/0 -> HTTP 404)
KYIV_RADAR_AUCTIONS_RELEASE=1

# Transport snapshot paths
KYIV_RADAR_AUCTION_SNAPSHOT=/var/lib/kyiv-radar-transport/auction_snapshot.bin
KYIV_RADAR_AUCTION_KEY=/var/lib/kyiv-radar-transport/auction.key
KYIV_RADAR_READER_GID=1000  # GID of kyivradar group
KYIV_RADAR_PUBLISHER_UID=1004  # UID of kyiv-radar-reviewer

# CORS Whitelist (server/kyiv_radar_api.py)
# Allowed origin: https://gewitter89.github.io
```

- **Default-Deny:** `APP_ENV=production` returns HTTP 404 unless `KYIV_RADAR_AUCTIONS_RELEASE=1`.
- Unknown `APP_ENV` values strictly default to `production` (fail-safe).
- Staging preview flags (`KYIV_RADAR_AUCTIONS_PREVIEW`) have NO effect in production.
- Client uses **authoritative availability discovery**: starts default-off without DOM injection; mounts `#krAuctionsNav` only when `/api/auctions` returns 200 OK with `available: true`. Query toggles (`?staging=1`, `?preview=1`) are strictly ignored.

---

## 4. Continuous Publisher & Emergency Dual Kill-Switch

### Continuous Publisher Handoff
Due to the 60-second TTL on HMAC-sealed snapshots, `scripts/prozorro_continuous_publisher.py` runs on the VPS under `kyiv-radar-reviewer` to refresh the snapshot every 30 seconds.
- **Zero Poll Rule:** It reuses verified local observations from the decisions ledger and cache. It **never** polls the external Prozorro API every minute. External fetches happen strictly via `kyiv-radar-auction-pilot.timer` every 20 minutes.

### Dual Kill-Switch
1. **Instant File Kill-Switch (< 1 second, no service restart):**
   ```bash
   touch /var/lib/kyiv-radar-transport/.kill_switch
   ```
   *Result:*
   - The publisher daemon detects `.kill_switch`, immediately stops regeneration, and unlinks `/var/lib/kyiv-radar-transport/auction_snapshot.bin`.
   - `/api/auctions` immediately returns HTTP 503 fallback (`{"available": false, "auctions": []}`).
   - The client hides auction items and displays graceful offline state.

2. **Configuration Route Kill-Switch:**
   ```bash
   # Remove release flag from service environment
   systemctl edit --drop-in kyiv-radar-api
   systemctl restart kyiv-radar-api
   ```
   *Result:* Route `/api/auctions` immediately returns HTTP 404 (default-deny).

---

## 5. Collector Service Rehearsal & Safe Rollback Drill

### Rehearsal Verification Evidence
An isolated rollback drill of the pilot service was executed on the VPS:
1. Deactivate timer:
   ```bash
   systemctl stop kyiv-radar-auction-pilot.timer
   systemctl disable kyiv-radar-auction-pilot.timer
   ```
2. Verify zero active collector processes:
   ```bash
   pgrep -u kyiv-radar-auction  # exited with code 1 (no residual processes)
   ```
3. Verify database integrity and backup:
   - Cache database `/var/lib/kyiv-radar-auction-pilot/auction-review.sqlite` verified intact.
   - Backup created to `/var/lib/kyiv-radar-auction-pilot/backup/auction-review.sqlite.bak`.
4. Restore and verify active service:
   - `systemctl enable --now kyiv-radar-auction-pilot.timer`
   - Verified 10 successful executions (2 manual + 8 scheduled timer cycles).
   - Peak RSS: 25.9 MiB, duration 1.24s per cycle, 0 грн cost.

### Complete Pilot Removal Procedure (If Rollback Needed)
```bash
systemctl stop kyiv-radar-auction-pilot.timer
systemctl disable kyiv-radar-auction-pilot.timer
systemctl stop kyiv-radar-auction-pilot.service
rm -f /etc/systemd/system/kyiv-radar-auction-pilot.service /etc/systemd/system/kyiv-radar-auction-pilot.timer
systemctl daemon-reload
# Completely isolated: existing services (kyivpulse, ballistic-interceptor, pavlogradpulse) remain untouched.
```

---

## 6. Pre-Release Checklist (Operator Authorization Gate)

- [x] All 122+ automated tests passing locally (`pytest tests/test_prozorro_*.py`).
- [x] JavaScript syntax verified (`node --check auction-tab.js telegram-shell.js kyiv-signal-theme.js`).
- [x] Real `index.html` verified with authoritative availability discovery and cache-busting (`?v=1.49.0`).
- [x] Origin mapping (`https://gewitter89.github.io` -> `https://vmi3445944.contaboserver.net/api/auctions`) and strict CORS headers verified.
- [x] Ukrainian open data legal disclaimers and VAT copy (`без ПДВ; умови ПДВ та зборів перевіряйте на джерелі`) aligned with `prozorro.sale/opendata`.
- [x] Production candidate pinned: `ALE001-UA-20261124-04958` (Kyiv apartment, starting bid 2,892,500 UAH).
- [ ] PR #91 merged into `main` on GitHub.
- [ ] Operator authorizes deployment and executes production environment release.
- [ ] Post-release manual check on physical mobile device (iOS/Android Telegram Mini App).
