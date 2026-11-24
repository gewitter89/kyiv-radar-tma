# Private auction pilot runbook

Status: experimental, non-public, no automatic activation.

## Verified prior evidence
- Single request: Actions run 45414598422, 3 observed procedures, 0 eligible.
- Three-page request: run 45415484622, 30 observed records, 0 eligible.
- SQLite and earlier unit tests: run 45415801380 succeeded.
- These results do NOT verify a real positive candidate, coverage of Kyiv, or deployment.

## Isolated command (after current-head CI, on authorized staging only)
Create a dedicated private directory outside the checkout with mode 0700. Run from repository root:
```
python3 -m scripts.prozorro_review_sync --live-private-review --private-dir /path/to/dedicated-private-directory
```
The command makes at most three official GET requests, reads at most ten procedures per page and limits each raw response to 4 MiB. A malformed later page prevents the batch write. Only normalized review candidates and necessary withdrawal markers for previously seen IDs are persisted. No source texts, images or contacts. All results remain pending review.

## Limits and NO-GO
- Recent rolling slice, not a full catalog, no durable pagination checkpoint or continuous refresh. Cursor collision/page budget may leave records unseen. Never infer deletion from absence. One-hour freshness hides unconfirmed records.
- Only narrow CSE001 sale and exact apartment classifier currently accepted. Other procedures (e.g. ALE/SPE) must be individually schema-verified before mapping. Do not broaden to mixed assets or treat a starting bid as a sale price.
- Do not use any output as a public JSON catalog or ordinary price comparison. No public endpoint/UI yet. Real positive candidate and its withdrawal behavior must be verified before release.
- Do not install timer or modify production until backfill/recheck strategy, retention/disk cap, overlap lock, network budget and failure recovery have passed staging QA. No provider fee or key.
- Current CI adds a temporary private database in the runner, destroyed at job end; no artifacts or raw response logs.
- Rollback: disable any future pilot schedule and remove only its dedicated cache after preserving required audit evidence. Never overwrite the running catalog or shared SQLite database.

## Next release gates
1. Verify at least one real eligible apartment and its official source URL, status and price semantics.
2. Confirm precise timestamp pagination/overlap contract and catch-up behavior after outage.
3. Add bounded cache retention, per-ID revalidation and independent review/publication authorization.
4. Test read-only UI in staging (auction price and deadline labels, empty/stale state).
5. Authorize deployment separately after backup and rollback rehearsal.


## Runtime guardrails added 2026-11-24
- Private directory must belong to the current Unix account; lock and DB reject symlinks, hardlinks and group/world access.
- Nonblocking process lock covers the entire network-to-cache cycle. A second process must exit before sending any GET.
- Main SQLite file capped at 16 MiB via max_page_count and an existing-file check; SQLite journal and other filesystem overhead are additional. Cache limited to 2,000 records; oversized batch rolls back.
- Successful refresh removes observations older than two days (including obsolete withdrawal markers). This exceeds the one-day permitted feed lookback; it is not a historical archive.
- Network failures release the lock. Next invocation retries a recent slice, not a guaranteed catch-up of all missing records.
- Live integrated CI run 45418333908: 30 procedures in three requests, 0 eligible, 0 publications, 0 raw records saved. Positive real auction persistence is still a release blocker.
- The pilot is Linux-only. No system timer is installed. Before activation, measure actual resource usage and confirm source-specific schema and positive sample.
