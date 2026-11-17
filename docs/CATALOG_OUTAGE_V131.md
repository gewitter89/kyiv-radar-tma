# Київ Радар v1.31 — fail-closed public catalog on API outage

**Scope:** public frontend loading behavior and isolated browser regression tests. No backend, production VPS, bot, Telegram token, API key, imports, partner feeds, paid services, or direct deployment.

## Problem

Before this patch, `loadDeals()` seeded 150 historic (unverified) entries from `KYIV_DEALS_INIT` and fetched `data/deals.json` on API error. This silently resurrected a static snapshot that may be stale, withdrawn, or lack partner republication rights. A successful `deals: []` was technically valid but could look exactly like an outage.

## New behavior

| Situation | User view | Source of truth |
|---|---|---|
| Hosted website (HTTP/S), request pending | No bundled historic entries are shown while loading | Empty until API |
| 200 success true + array of public deals | Live list; none means explicit `Зараз немає доступних оголошень` | Public API only; still subject to existing rights/actuality verification |
| HTTP 4xx/5xx, timeout, invalid JSON, success false, missing array | No displayed listings + `Не вдалося завантажити оголошення`, explanation and `Спробувати знову` | Never cached historic entries |
| User taps retry | Re-fetch live API only | Not silently repopulated with archival fallback |
| `file://` local browser fixtures / offline QA | Existing static historical synthetic-like *preview* works for development | NOT a source of current/republication rights |

`window.KR_CATALOG_MODE` is `loading`, `live`, `error` or legacy local fixture `cached/static`. No fake availability status is inferred from a 200 response alone. The remaining 150 legacy records are not independently verified; issue #14 remains a launch blocker even when API responds.

## Validation

- Browser tests start a loopback HTTP server and intercept all catalog API calls with synthetic 503, malformed JSON, invalid schema, negative `success`, valid empty 200 and retry.
- Tests ensure `data/deals.json` is **not requested** in the hosted error scenario and no old cards remain visible after failure.
- Separate `file://` test maintains the local preview needed for many existing Playwright tests; no live feed or private data fetched.
- Full quality/security regression must pass before merge. Real iOS Telegram and Android checks, plus GitHub Pages smoke, are release requirements separate from CI.
- If the live API is unavailable, do **not** override this failure by pushing the historic records or weakening rights checks.

## Further outstanding work

- Stable user-specific favorites, currently PR #50, may require rebase of different `index.html` sections after merging; resolve changes without losing the fail-closed behavior.
- #37: revocation must invalidate every surface, caches and Telegram alerts; this PR covers only hosted frontend fallback.
- #40/#43: nationwide categories, sale/rent, currency and rental period; this PR keeps existing Kyiv rental UI.
- #14: review actual source rights, actual availability and historical listing claims; none certified by this PR.
- User-facing body uses existing UI components and remains in Ukrainian, without imitating testimonials, verified ratings or human provenance claims.

**Rollback:** restore `index.html` from the previous frontend release if a verified critical regression occurs, while preventing historic fallback from being presented as current by any released version.
