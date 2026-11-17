# Київ Радар — staged roadmap v1.6 → v2.0

## Scope and facts
At 17 November 2026, the GitHub repo contains v1.5.1 upload-stream
protection, but **a GitHub commit is not evidence the Contabo VPS was
updated**. Existing bot token is explicitly to stay unchanged. Issue #7
records its unresolved potential historic exposure; do not represent this
risk as closed.

The base catalog has 150 imported listings with **zero independently
owner-verified** entries. The older text contained 150 instances each of
two unsupported generic claims about direct owners and amenities; PR #9
removes them from public JSON, embedded fallback and API responses.
Source content, true availability and permission to republish must still
be assessed before marketing.

## Phase A — trust, security, pilot (before public promotion)

- Complete **Issue #8**: validate deployment's Caddy version and
  route map. On Caddy >=2.10, set a 33 MiB body cap on the photo upload
  endpoint. Apply only after local staging validation, backup, config
  validation and coordinated reload. The 1.5.1 ASGI gate is not a
  substitute for edge protection.
- Inspect actual VPS API module import location; back up, then deploy
  1.5.1 and test 413 in staging and safe small upload in real Telegram.
- Check API and bot health, contact message delivery, moderator photo
  approval and private media access. Do not touch KyivPulse/Vudstoria.
- Review provenance and republication rights of imported photos and
  claims. Remove listings without appropriate rights/actuality. Provide
  easy user report/takedown, clear privacy/terms pages and contact route.
- Test actual iOS Telegram WebView (including older iPhones), Android,
  desktop browser, keyboard and screen readers. Never claim visual
  screenshots are equivalent to independent manual device testing.
- Closed pilot with 10–20 invitation-only participants, including 3–5
  actual landlords with consent. Keep outreach manual and respectful.
- Collect only real metrics: successful contact delivery, legitimate
  submissions, moderation time, error rate, reports of stale listings.

## Phase B1 — local-first intelligent search (PR #9)

- Save up to eight text-and-filter searches on the current device.
- Surface newly observed matching IDs next time the app is opened.
- Compare up to three apartments, only with actual public data and
  qualification that imported amenities are *claimed*, not verified.
- Existing map, favorites, filter sorting and Telegram contact flow
  must keep working.
- **No device sync, background checks or Telegram alerts** in this phase.

## Phase B2 — opt-in Telegram notifications (separate future PR)

Before offering notifications, first ensure a reliable, rights-compliant
source of genuinely new approved listings, with immutable IDs, publish
timestamps, availability and source provenance. Do not label a scraped
historical listing "new" merely because it first appears locally.

Proposed server workflow:
1. Telegram user opens Mini App and uses signed, fresh `initData`.
2. User opts in to a saved search. Server stores user_id, normalized
   non-sensitive criteria, consent timestamp, digest frequency, cursor,
   active flag and retention timestamp in protected SQLite/Postgres.
3. A dedicated single-writer job matches only newly approved, legitimate
   listings. Dedupe (user_id, deal_id, search_id) with a unique key.
4. Deliver a **rate-limited**, no-phone, no-tracking, no-fake-urgency
   Telegram digest (e.g. at most one digest per day by default).
5. Bot provides `/stop`, unsubscribe per search, delete search data,
   and persistent failure/retry bounds. No spam and no notification
   unless explicit consent.
6. Tests must cover duplicate jobs, revoked consent, expired `initData`,
   failed Telegram delivery, stale/removed listings and privacy.

The owner explicitly instructed **no bot-token rotation**. Existing
bot services can continue using their configured credential if the
operator accepts that documented risk; **do not copy its value into GitHub**.

## Phase C — landlord workspace and ethical monetization

First deliver free owner workspace for **real consented landlords**:
- Telegram-verified sign-in and ownership/authorization review.
- Edit listing, upload new photos, pause/archive, fix contact, and
  moderate changes before publishing.
- Aggregate accurate views/contact requests; no fake traffic.
- Data minimization, export/delete account options, moderator abuse
  controls, clear audit history.

Only after product-market validation add paid offerings through a
regulated supported payment provider and a legal/tax review:
- Clearly labeled sponsored placements, marked **Реклама** in every
  relevant view; never disguise paid ranking as organic quality.
- Published price, duration, refund policy and receipts before purchase.
- Server-authoritative payment webhooks, idempotency, entitlements,
  cancellation/refund handling and a financial ledger.
- No access to private contact lists for ad targeting. No sale of
  user telephone numbers. No automatic billing or paid ads without
  explicit owner approval.
- Separate permissions for admins, verified landlords and end users;
  audit every paid promotion.
- A/B test *truthful* benefits with real users before pricing.

## Engineering release gates

Every PR: isolated CI, security/privacy tests, screenshots and review.
Every backend migration: snapshot+WAL consistency, schema dry run,
import-path validation, coordinated stop of all writers, smoke/rollback.
Every public feature: manual iOS/Android tests, source/rights review,
no PII leaks, localized Ukrainian UX and fail-closed failure modes.

**Do not claim production completion from this document.**
