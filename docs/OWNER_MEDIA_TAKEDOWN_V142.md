# Owner-photo withdrawal gate (v1.42, 24 Nov 2026)

## What was unsafe
The old `GET /api/media/{photo_id}` handler returned an upload whenever
`landlord_uploads.status == "approved"`. Deleting a listing from `deals.json`,
withdrawing it in private moderation, or taking down the whole catalog did not
revoke previously shared photo URLs. It also returned a **public one-day cache
header** that could extend exposure after withdrawal.

This was a rights/privacy problem. Approval of one image is not permanent
approval to publish it independently of its listing.

## New read-time authorization
Every request now requires all conditions:

1. Strict 32-hex photo ID, approved upload linked to a real submission.
2. Submission is currently `published`, not rejected/withdrawn/archived.
3. Its own private submission photo list still explicitly contains that ID.
4. The same current `load_effective_deals()` gate used by catalog/health/contact
   retains that specific **first-party direct submission** (source + submission ID).
5. That eligible listing explicitly includes this exact public media URL.
6. The private image file exists on disk.

Any missing/invalid DB, review register, withdrawn listing, link mismatch or
other gate failure returns 404 without disclosing private records. A successful
response sets `Cache-Control: private, no-store, max-age=0` and `nosniff`.

Existing approved image files are **not erased**, so the operator can preserve
private consent evidence/backups, but a bookmark no longer bypasses takedown.
This endpoint does not publish partner photos.

## Compatibility and deployment
This requires the original `landlord_submissions.photos`, upload ownership
row and current private/public catalog to stay in sync. Old orphaned or
unlinked images intentionally disappear (fail closed). A previously published
listing must remain in both private DB and the moderated live catalog.

PR green tests do **not** update VPS. The release owner must separately:
- take a private SQLite/media/catalog backup;
- deploy API and moderation components together, not just GitHub Pages;
- run read-only E2E: submitted photo 404; published own photo 200 with
  `no-store`; withdrawn/removed photo 404; unrelated photo 404;
- verify reverse proxy/CDN does not cache `/api/media` and old cached images
  are invalidated where technically possible;
- check existing public image/Telegram cache copies and process removal
  requests; HTTP response headers cannot retroactively erase other caches.

No provider data, API keys, tokens, production DB, paid calls or user records
were changed by this code-only release.
