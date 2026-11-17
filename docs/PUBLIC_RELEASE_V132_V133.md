# Київ Радар v1.32–1.33 — безпечне очищення та реліз

**Статус:** development candidate. Green CI is NOT proof of a verified production deploy or source license.

## Why
Old public HTML and data/deals.json contained 150 imported historical records without independently established current availability or redistribution rights. The previous UI error fallback also risked reviving stale cards. The API could expose the same records even when frontend hid them.

## Changes
- Committed index.html has an empty KYIV_DEALS_INIT array, and committed data/deals.json is an empty array.
- CI creates deterministic, clearly labelled synthetic records only inside a disposable test checkout. All checks first reject any populated public checkout.
- Hosted frontend uses live API only; stale imports and test fixtures are not displayed, and outages show a retry action.
- Server public eligibility accepts only approved direct-owner submissions and partners that already passed private contract/review/current-availability checks. It rejects old OLX/DIM.RIA imports, other unknown sources and synthetic fixtures before API, health counts and contact lookup.
- A valid empty API array means zero eligible offers; an HTTP/JSON/timeout error means unavailable service.

## Mandatory GO / NO-GO before public release
1. Latest-head Quality, Favorites and Partner workflows must all be green. Inspect screenshots of phone/tablet/desktop and confirm the fixture banner is test-only.
2. Validate deployed Pages source/branch, current API deployment, actual service imports, protected moderator/bot token, and rollback path.
3. On the VPS, privately back up the API, configs, contacts and media. Back up SQLite with WAL consistency through SQLite Online Backup API. Rehearse a restore on a disposable copy. Do not upload backups or token values to GitHub.
4. Do not overwrite live catalog/DB by copying the new public EMPTY data/deals.json. Reconcile actual approved private data separately.
5. Coordinate backend/API and frontend releases. Verify old unlicensed rows are absent from direct GET /api/deals and authenticated POST /api/send_contact and that approved first-party rows can still be contacted. Partner records must pass active rights and review gates.
6. Check current published HTML/JSON contents and CDN cache after deployment. Existing Git history and third-party archives cannot be removed by normal commits.
7. Manually inspect actual iPhone Telegram WebView, Android, desktop, map/list, one-tap favorites, empty/error cases, limited real verified contact flow, and rollback readiness.
8. Protect independent KyivPulse/Vudstoria services, and monitor shared agent-bot readers/writers.
9. Release/advertising only after a real consented approved listing exists and the old Telegram token risk has an explicit remediation decision.

## Limits
- Current branch removes historical rows from current static files, NOT Git history, prior downloads, external caches, or already-running VPS API.
- Any source prefix is insufficient evidence of content rights without the private reviewer and contract checks.
- Green unit tests do not prove current listing availability, actual landlord ownership, commission, image rights, or real-device delivery.
- Do not rotate the existing Telegram token or make paid calls as part of this change.
- Do not pass CI-generated synthetic listing data into production.

Related: #7, #14, #37, #52, #55, PR #50/#51/#53/#54/#56.
