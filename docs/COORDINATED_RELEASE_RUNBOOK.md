# Київ Радар v1.5.0 — coordinated release / rollback protocol

**Status: release candidate, not deployed.** This is a human-executed checklist, not a script that automatically switches production.

**Never use the old rollback snippet in Issue #3.** It stops only `kyiv-radar-api.service` and overwrites a live SQLite file while `agent-bot.service` may still hold the database open. In WAL mode that can lose committed transactions or corrupt the database. Do not promise a 30-second rollback.

Official references:
- SQLite Online Backup API: https://www.sqlite.org/backup.html
- SQLite WAL and persistent state: https://www.sqlite.org/wal.html
- GitHub Pages branch deployments: https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site

## Pre-release GO / NO-GO

1. [ ] Owner has explicitly approved a coordinated production release and a short maintenance window affecting `agent-bot.service` (which may serve **other** features, not just Kyiv Radar).
2. [ ] PR #2 latest SHA has green CI; `main` still points to the previous stable version before starting.
3. [ ] On the VPS, resolve the *actual* systemd `ExecStart`, `WorkingDirectory`, run-as account and Python environment for **both** `kyiv-radar-api.service` and `agent-bot.service`. Identify their common SQLite DB and all canonical imports of `bot_moderation.py`.
4. [ ] Confirm no other service or scheduled job writes to the same DB, including background workers. Coordinate stopping or pausing **every writer** before any restore.
5. [ ] Read-only preflight in Issue #3 passes: safe snapshot and dry-run migration, 150 protected contacts, media permissions/free space. Check that the public catalog and the **embedded inline catalog** contain no owner names and raw phone numbers.
6. [ ] Prepare a private backup of the current API code, bot module, service configs, data catalog, images, and vault; secure permissions 0700 and never upload backup bytes to GitHub. Record checksums, the currently running SHAs and service states privately.
7. [ ] Validate v1.5.0 module compatibility with the actual bot callback code in a **separate local environment**: pending photo → moderator preview → approval → approved API image. Include 1-photo and multi-photo cases.
8. [ ] Confirm how GitHub Pages is configured to publish (branch or Actions) and how to reverse a Pages deployment. Pages may update after the backend; never assume they switch at exactly the same time.
9. [ ] The known previous bot-token disclosure remains unresolved by owner's instruction. Explicitly assess the risk before inviting outside users.

**NO-GO** if any required check fails. A report of “37 tests green” is not sufficient to declare live E2E successful.

## Coordinated release — operator checklist

No commands below should be executed blindly or on a production database without confirming actual paths.

1. Agree on a low-traffic maintenance window. Temporarily block or pause new listing submissions, moderation callbacks, and background writes to the shared DB using verified service-specific controls; don't invent a maintenance flag.
2. Stop the API and Telegram bot *together* for the code and schema cutover, after verifying they are the only writers that must be paused. Beware of user-facing downtime for other functions served by `agent-bot`.
3. Take an **additional final, consistent SQLite backup** immediately before migration, with WAL included through SQLite Online Backup API, plus latest catalog and private contacts. Verify `PRAGMA integrity_check` and permissions. Keep the earlier preflight snapshot as a separate reference.
4. Deploy the checked exact PR #2 SHA to a controlled release directory, not by overwriting an untracked working tree; install pinned/tested dependencies. Deploy the matching `server/bot_moderation.py` to the actual import target used by the running bot; keep the old module in a protected backup.
5. Run `init_db()` once against the verified correct live DB while writers are paused. This is an explicit **production migration** and must not be confused with the previous dry run. Validate resulting schema and permissions.
6. Start API and bot only when both modules are ready. Verify API process identity, `/api/health` version 1.5.0, protected `/api/deals` response, private `/api/media/{id}` = 404 for nonapproved IDs, and actual bot callback import. Confirm `kyivpulse.service` and other unrelated services remain healthy.
7. Deploy/merge the frontend only after the matching backend and bot pass smoke tests. Track the **actual** GitHub Pages deployment; don't infer it from a successful `git push`.
8. Run two limited test-user E2E paths: (a) `Отримати контакт` delivers a genuine, permitted test listing contact to the requesting Telegram account; (b) test-owner photo upload → private moderator preview → approval → HTTPS image `200 image/webp`. Use only consented test data and remove/mark test entries when appropriate. Do not flood real users.
9. Monitor errors, disk, log redaction, and any shared-service regression during the initial pilot. Reenable submissions only after full compatibility is confirmed.
10. Record the production SHA, deployment status, actual checks completed and any remaining open risks in Issue #3 **without private values or backup locations**.

## Rollback decision tree — **never restore SQLite blindly**

**A. UI/backend regression, database intact:** first freeze new writes and moderation. Prefer **code-only rollback** to matching previous API + bot + frontend versions while preserving the database, vault, approved images, and all submissions. Stop services as required by the actual modules to prevent old code handling new events. Confirm that any new v1.5 photo URLs/records won't break after code-only rollback; if they would, temporarily hide/disable affected listings or provide a compatibility layer.

**B. Database corruption or truly incompatible migration:** escalate for an explicit **data restoration decision**. Identify and export any legitimate new requests since the final snapshot; a snapshot restore otherwise loses them. Halt *all* writers, including API, bot and background workers. After confirming no process holds the database, use an isolated restore workspace and SQLite's supported backup/restore procedure with WAL-aware handling. Validate integrity and permissions before switching the DB, carefully handle any `-wal`/`-shm` sidecars only while all connections are closed, then start compatible modules. Never `cp` a backup over a live database. Reconcile new submissions separately.

**C. GitHub Pages updated, API rollback needed:** assume frontend and backend contracts may differ. Coordinate reverting Pages to the compatible commit/workflow while keeping user submissions paused; a commit in `main` does not imply the Pages site has already switched. Confirm the actually served HTML.

There is **no guaranteed rollback duration**. The correct strategy depends on whether data was accepted since release and what services still hold SQLite.

## Launch gate

Public promotion only after successful real device checks (iPhone, Android, tablet and PC), real Telegram contact delivery, photo moderation E2E, legal/data provenance checks for imported ads, a privacy notice and a documented decision about the disclosed old token. Do not claim all listings are verified owners or commission-free.
