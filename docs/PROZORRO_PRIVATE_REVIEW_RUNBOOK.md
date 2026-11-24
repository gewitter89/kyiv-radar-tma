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
- Only narrow CSE001 and ALE001 sales with the exact apartment classifier currently accepted. Other procedures (e.g. SPE) must be individually schema-verified before mapping. Do not broaden to mixed assets or treat a starting bid as a sale price.
- Do not use any output as a public JSON catalog or ordinary price comparison. No public endpoint/UI yet. Real positive candidate verified in disposable CI; real withdrawal behavior and release authorization still required.
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
- Live integrated CI run 45418333908: 30 procedures in three requests, 0 eligible, 0 publications, 0 raw records saved. Later positive real auction persistence was confirmed in run 45420132452.
- The pilot is Linux-only. No system timer is installed. Before activation, measure actual resource usage and confirm repeated direct revalidation.


## Current verified evidence and staged Linux units
- Run 45420132452: a real ALE001 apartment passed normalized geography and was saved in a disposable SQLite database.
- Run 45420924638: targeted discovery read 20 procedures in 2 requests and independently found 1 eligible private candidate. No public output. There were zero direct rechecks in that empty-cache run.
- Run 45420245127: Quality and security passed with the local HTML review module.
- New CI performs two consecutive targeted refreshes on the same temporary database. A second cycle with zero rechecks is inconclusive, not proof of direct revalidation.
- The staged units in `ops/prozorro-pilot/` are NOT installed or enabled. They use a dedicated non-login static account `kyiv-radar-auction` (user and group), read-only reviewed code under `/opt/kyiv-radar-auction-pilot`, and systemd-owned state `/var/lib/kyiv-radar-auction-pilot` with mode 0700. The service account must not own or be able to modify the checkout.
- On authorized isolated staging: provision that account and group, deploy an exact reviewed commit to the fixed code path, verify units with systemd-analyze, then install the units without enabling the timer. Start the one-shot service manually; verify exit status, aggregate logs, permissions, database size and actual peak resources. Run a second cycle and require a positive recheck count before considering timer activation.
- Timer is relative to completion, about 20 minutes, at most 7 GETs per successful targeted cycle. MemoryMax=128M, CPUQuota=25%, TimeoutStartSec=150, TasksMax=16. These are configured limits, not measured resource usage. Check systemd version and network/DNS compatibility on the actual host.
- No public data export, no public UI, no production deployment or enabling the timer until explicit release gate and rollback verification. Roll back by stopping/disabling only the dedicated pilot timer and service; preserve private evidence; do not touch the existing catalog or services.
- Targeted discovery still sees only one bounded page per method, not a complete inventory. A prolonged outage or large queue may cause incomplete coverage; never infer absence as withdrawal. 
