# v1.46 — first-party landlord revocation must override stale catalog JSON

## P0 bug / user impact

The API loaded a JSON card with `source = "Київ Радар (Пряма заявка)"`,
`moderationStatus = "approved"` and a numeric `submission_id`.
It did not consult the actual `landlord_submissions.status` in SQLite at
read time. If an operator/owner withdrew the submission or a moderation
workflow marked it rejected/closed, that old JSON could keep serving
`/api/deals`, inflating `/api/health.deals_count` and enabling a contact
handoff even though the property's status was no longer published.

Photo revocation in v1.42 guarded image bytes independently, but not the
listing or contact itself.

## New read-time fail-closed gate

`server/owner_visibility.py` performs only SQLite `SELECT` reads using
URI `mode=ro`. Before every read-oriented public endpoint serializes data,
each first-party submission must have the exact status **`published`** in
the private database, matched by its integer `submission_id`.

- Withdrawn / rejected / pending / absent DB row: hide the listing.
- Missing / corrupt / inaccessible / symlinked SQLite file: hide owner
  rows; preserve unrelated partner candidates for their **separate**
  independent rights and reviewer checks.
- A malformed/boolean/missing `submission_id` never passes.
- No writes, schema migrations, external requests or new publication rights.
- Existing private backups/media stay intact; withdrawing from the database
  does not delete user history. HTTP `/api/deals` already sets `no-store`.
- `/api/health`, `/api/deals`, `/api/send_contact` share the same
  `load_effective_deals` gate, so status cannot diverge between routes.

Tests cover live withdrawal, deletion, missing/corrupt database, forged
submission IDs, contract isolation, and consistent public/contact behavior.
Older synthetic fixtures now seed an actual published status instead of
assuming a JSON flag was sufficient.

## Deployment and rollback

Source code/CI are not live deployment. Coordinate API and Telegram bot
VPS release with private WAL-consistent backup, real import-path checks and
a jointly controlled maintenance window. Validate an *authorized, consented*
test owner listing: published → 200 and contact permitted; withdrawn in
SQLite → disappears from catalog/count/contact and public photos return 404.

Do not restore the old 150 unlicensed listings or overwrite a live catalog
with repository fixture `data/deals.json`. External partner feeds still
require independent contractual republication authorization. Budget: 0 UAH.
