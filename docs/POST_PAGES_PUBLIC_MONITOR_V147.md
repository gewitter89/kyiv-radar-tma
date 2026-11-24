# v1.47 — Verify actual public assets after successful GitHub Pages deployment

## Why this exists
A green GitHub Pages build/deployment workflow is not evidence that the
public HTML, JSON and separate Contabo FastAPI actually serve permitted,
current inventory. Changes to `main` after PR #71–#76 can create a gap between
the code validated in CI and the pages/API observed by a user.

The existing `scripts/monitor_public_health.py` checks four real public
HTTPS URLs (Pages HTML, Pages `data/deals.json`, API health and API catalog).
It confirms empty static JSON, no leaked legacy inline inventory, explicit
source/PII rules and consistent counts. **Zero approved listings** is valid.

## New trigger and scope
`.github/workflows/public-health.yml` retains the scheduled daily read-only
run and manual `workflow_dispatch`, and adds `workflow_run` on successful
main-branch pages build and deployment events. Failed/cancelled deploys
do not start a successful-release audit. GitHub job permissions remain
`contents: read`; no secrets are passed. The script makes only HTTPS GETs,
does not import feeds, mutate a database, send Telegram messages or call
billable DIM.RIA APIs.

The workflow intentionally fails if actual public resources are missing,
stale, expose unauthorized partner/legacy rows, or mismatch health counts.
A failed check is a release blocker to investigate, never a signal to seed
fake apartments or blindly deploy new catalog files.

## Limits
- The monitor cannot establish contractual scope of DIM.RIA or OLX, prove
  owner property title or retract copies from third-party caches.
- GitHub Actions and Pages CDN timing are external dependencies; investigate
  a transient network check and safely repeat without modifying production.
- GitHub Pages publication is NOT a VPS rollout. The backend still needs
  an owner-approved WAL-safe coordinated release.
- The first post-Pages audit will only occur after this workflow is merged
  to the default branch and a subsequent matching Pages deployment finishes.
  Do not claim a successful live audit without its actual workflow result.

No new hosting, paid API keys, production writes or private data.

## v1.48 observed event behavior and fallback

On 24 Nov 2026, the GitHub Pages workflow for commit
`8d112b16a52d2fc8a9b341704c7441672f2821c1` completed successfully,
but the GitHub Actions run list contained **zero** `workflow_run` events
afterwards. The Pages job uses GitHub's generated `dynamic` event. We
must therefore treat the new `workflow_run` trigger as **unverified for this
repository**, not as proof of automatic live monitoring.

The v1.48 change adds a read-only `push` trigger on `main`, scoped to
published HTML, JS, CSS, static catalog, monitoring code and monitoring
workflow changes. It will run even if the Pages-generated dynamic event
does not invoke `workflow_run`. The daily check and manual run remain.

A push-triggered check is **not an atomic post-deploy attestation**: it may
run before the Pages CDN has served the new commit. A successful run
confirms only the public invariants observed at the time of that run.
A failed run may be caused by a real privacy/source violation, a stale
CDN response or temporary network/API unavailability. Investigate and
repeat after the Pages deployment; never overwrite production data merely
to make a green check.
