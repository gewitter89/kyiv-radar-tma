# Київ Радар — product-first release v1.7

## Positioning / why anyone opens this instead of OLX or DIM.RIA

**Київ Радар — пошук оренди в Києві з акцентом на побут під час відключень.**
Show the terms the user actually cares about: rent, metro/district, gas, floor,
owner-stated generator and GPON, pets, and uncertainty.

**Do NOT market this as "more verified than DIM.RIA" or "more comprehensive than OLX".**
Those incumbents already offer maps, filters, alerts, saved searches, and
their own verification ecosystems. Kyiv Radar's legitimate differentiator
can be **focus, clarity and verified resilience data once available**.
Unverified imported claims must be clearly labelled.

The owner explicitly requested retaining the historic Telegram bot token.
Never rotate/revoke it in this release, never print it in GitHub or logs.
Issue #7 records a still-open security risk.

## First-use script (no tutorial maze)

1. First five seconds: the Kyiv Radar name, concrete value proposition,
   search field and "Знайти квартиру" are visible without scrolling.
2. Enter a metro/street/district, set budget and rooms; live result count
   updates, reset is one tap.
3. A choice of map **by district** or list. Never place imported listing
   markers on exact buildings without independent location verification.
4. Result card shows source and says whether owner/availability are unverified.
   Generator / GPON are **заявлено**, not proven resilience.
5. A detailed listing has photos, supplied facts, source, and report button.
   Avoid empty promises about "no commission" and fabricated location.
6. On the web, contact opens a persistent Telegram handoff with a real
   bot link and the listing number; it never claims to have delivered
   a private phone. Inside Telegram, a signed API request may deliver
   a contact, with persistent, actionable errors on failure.
7. Compare directly from a result card or save a search from visible
   "Мій радар". Data is local to device; no fake push/subscription promises.
8. A landlord entering via a browser sees Telegram entry instructions
   before filling the long form; native HEIC conversion is attempted when
   browser decoding allows it, else error recovery explains JPG usage.

## Trust/data blockers still requiring real work

- Source catalog: 150 imported records, 0 independently owner-verified.
- 8 address fields with scraped DOM text; 13 conservative room/title
  conflicts (heuristic); some metro mentions disagree with structured data.
- 142 records contain district-only addresses while presenting point coords.
  The map now groups by district; its center points are **area labels**,
  not apartment locations.
- Listing activity, source permission/photo rights, contact consent,
  commission and blackout utilities require actual checks.
- The UI quality gate **quarantines obvious conflicts** (no made-up fixes),
  but human moderation/source reconciliation is required in Issue #14.
- Do not activate paid promotion or send automated deal alerts based on
  stale or scraped data without validity/consent confirmation.

## UI design system

Mobile-first dark palette with restrained blue accents; genuine system
typefaces, strong hierarchy, 16px search, key touch targets >=44px,
visible focus and compact guidance. No flashing badges or fabricated
"verified" rankings. One prominent task per screen; secondary actions
discoverable but not obstructive.

Components: brand/header, one-sentence hero, fast filters,
live/backup data source status, area-level map/list switch,
result card, detail sheet, compare, Telegram handoff, report,
landlord form, Smart Radar.

## QA checklist

- [ ] 390 × 844 mobile: no horizontal overflow; search focused from CTA.
- [ ] 320 px narrow / 810 px tablet / 1440 px desktop screenshots reviewed.
- [ ] User can search, reset, choose district, compare two cards, save
      a search and return without being coached.
- [ ] No third-party map library: list view still loads all safe records.
- [ ] API unreachable: cached catalog is visible as unverified/stale;
      no "live" or "guaranteed available" claims.
- [ ] Browser outside Telegram: useful bot link and listing ID, without PII.
- [ ] Real signed Telegram: contact dispatch, auth expiration, 502
      recovery, privacy; moderator confirms uploaded photos.
- [ ] iPhone HEIC: native decoding path when available or clear JPG fallback;
      10 images, 8 MiB/file, 32 MiB total unchanged.
- [ ] Screen reader and keyboard audit: focus, modal close/ESC,
      interactive card semantics, forms, error announcement.
- [ ] All listings evaluated for rights, duplicates, age, coordinate
      precision, truthful rooms/metro/amenities before publicity.
- [ ] Backend deployed only with Caddy, schema and DB WAL backup gates
      in Issue #10 and Issue #8; never touch unrelated VPS services.

## Non-goals of this PR

No direct access to Contabo VPS; no credential changes; no claims that
an iOS/Android Telegram WebView has been manually reviewed, even if
Playwright screenshots pass. No payment provider, merchant account,
subscription or automatic advertising spend. The backend v1.6 source
may still not match the running VPS.

## After stable v1.7, full-platform route

1. **Dataset first**: lawful, consented inventory ingestion; provenance,
   moderation, source-change tracking, duplicate detection, timestamps,
   truthful address precision and blackout infrastructure verification.
2. **Cross-device experience**: authenticated saved searches with opt-in
   Telegram notifications and a real unsubscribe/delete path (#11).
3. **Landlord tools**: verified ownership/authorization and user analytics
   based on actual events, listing edit/archive and abuse control (#12).
4. **Monetization**: separately approved billing, receipts, refunds,
   transparent sponsored labels and tax/legal review (#13).
5. **Technical operations**: versioned API rollout, privacy/accessibility
   review, metrics and rollback; the old token remains the owner's
   explicit deferred risk (#7).

## Product acceptance metrics for a real 10–20-person pilot

**Targets, not measured results:**
- User can identify a first useful action without guidance.
- Time to first relevant listing and success of contact handoff.
- 0 actual private contacts shown in public API and 0 false delivery claims.
- 0 unsupported owner-verified labels.
- Real defect rate per listing checked; suppress bad records before scale.
- 0 critical mobile keyboard or tap blockers.
- No new user confusion between "заявлено" and "перевірено".

The correct product is not the one with the most screen elements; it is
the one where someone can make a reliable decision quickly.
