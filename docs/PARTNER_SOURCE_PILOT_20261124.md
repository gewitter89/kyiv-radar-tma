# Partner source pilot — 2026-11-24

Status: research and integration acceptance criteria only; NOT authorization, deployment, or activation. No paid actions. No personal data or actual feed URLs in this public repository.

## Source matrix

| Source | Evidence | Direction | Gate / next action |
|---|---|---|---|
| Rieltor.ua | https://rieltor.ua/pages/terms/ | Partner XML distribution | Obtain written permission and a sandbox feed; no scraping |
| Apart CRM | https://apart.com.ua/ | Partner API for public catalog | Ask for read-only documented endpoint, agency opt-in and revocation |
| Relto | https://relto.pro/features/ ; https://relto.pro/legal/terms/ | Agency XML export | Agency owns data; obtain explicit agency consent and format from CRM |
| 100realty | https://100realty.ua/uk/rules | Contract-based cooperation | Ask for outbound data feed, rights and free pilot; no assumptions |
| Blagovist | https://blagovist.ua/uk/contacts | Direct agency | Request opt-in 10–30 items, not access to internal database |
| Park Lane | https://parklane.ua/uk/contacts | Direct agency | Same; use source links instead of copying contact data |
| Rent.ua | https://www.rent.ua/faq/RESTAPI | Inbound publication only documented | Ask whether outbound catalog feed is available |
| Agentiz | https://www.agentiz.com/uk/partnership/aggregation/ua | Inbound XML import documented | Potential distribution channel for separately consented first-party listings, not a confirmed data source |
| Prozorro.Sale | https://prozorro.sale/opendata/ | Open public auction data | Separate auction pilot; preserve source, verify status and data minimization |
| DIM.RIA | https://developers.ria.com/ | API | Exact display/cache permissions and limits unresolved; keep disabled |
| OLX | https://developer.olx.ua/ | Partner API | No approved outbound access established; keep disabled |

## Implementation sequence

1. Reuse existing private source-rights gate, XML/YRL staging, normalized metadata, reviewer and publication-receipt mechanism. Do not create an alternative public import path.
2. For each new provider, confirm exact allowed fields, purposes, retention, link attribution, status semantics, revocation SLA, quota, and ownership consent. Keep evidence and credentials private. No provider becomes active because a research row exists.
3. Ask for a synthetic/sandbox fixture first; test against existing importer. Add a narrow adapter only when schema differs. Require explicit stable external ID, source URL and currency; missing room count remains unknown. No phone/email, source descriptions or photos unless separately allowed under existing stricter rules.
4. Process full snapshots only when documented complete; never treat network failure, partial pages or quota exhaustion as deletion evidence. Expire unverifiable rows according to the approved policy. Reconcile genuine withdrawals promptly, including favorites, contacts and notifications.
5. Pilot 10–30 opt-in rental/sale listings; stay inside a verified zero-cost quota. No automatic paid renewal. Measure freshness, unique listings, broken links and duplicate candidates. Start with source-attributed outbound links rather than collecting leads.
6. Auctions: different product type, not ordinary rent/sale. Preserve bid/starting price, currency, VAT and period/unit where available, procedure status and bidding deadline. Never present starting bid as ordinary apartment price. Use only public metadata with explicit source link; do not download documents or publish contact details. Validate Kyiv city (not oblast or ambiguous address), property type, open bidding stage and date. Exclude land and other assets from residential results. Unknowns stay unpublished. Use a separate feature flag, namespace and UI section; do not route auction rows into ordinary comparables.
7. Before deployment: green current-head CI; staging end-to-end; verified private backups; coordinated API/bot upgrade with rollback; explicit owner approval. No main merge/deploy triggered by this document.

## Release acceptance matrix

- Unapproved provider / revoked rights => hidden; no credentials in browser or public Git.
- Incorrect or absent source URL => quarantine.
- Invalid/missing fields, room-count conflicts, unexpected currency => no invented values.
- Oversized/malformed input / unsafe XML => rejected with bounded memory and no partial publish.
- Repeated ID => idempotent upsert, no duplicate card.
- Partial feed / 429 / timeout => bounded backoff, no destructive withdrawal or paid retry.
- Withdrawn record => hidden through API, search, favorites and contact endpoints.
- Quota reached => pause; never silently switch to paid access.
- Cross-source similar listings => review candidates, not automatic irreversible merges.
- Auction with bid price => shown only in dedicated auction section with price meaning and end time.
- Public catalog never contains test fixtures; mock tests only until licensed pilot.
- Rollback restores code/config without overwriting live catalog or SQLite.
- No claim of live readiness until public site, API and Telegram bot are verified on the same release.

## Pilot metrics (proposed)
10–30 approved active listings, 100% source link coverage, zero unauthorized fields, zero stale rows beyond agreed freshness window, zero duplicate IDs, zero paid calls. Pilot success is measured against actual permissions and runtime evidence, not the number of PRs.
