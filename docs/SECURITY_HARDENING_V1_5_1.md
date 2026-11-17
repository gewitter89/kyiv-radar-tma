# Kyiv Radar v1.5.1 security hardening — production rollout gate

This document describes *proposed* changes. A GitHub PR or passing CI does
**not** mean the VPS has been updated. Never publish a Telegram token, private
contact vault, actual backup location, or environment file to GitHub.

## Risk A — upload request size before multipart parsing

Facts in v1.5.0: 10 images maximum, 8 MiB/file, 32 MiB aggregate.
The FastAPI upload endpoint sees files only **after** the multipart parser.
The active Caddy is reported to be 2.6.2, which cannot use the built-in
`request_body` directive (experimental, Caddy 2.10+).

### Change in this PR

* Pure ASGI `UploadBodyLimitMiddleware` intercepts **POST
  /api/landlords/upload_photos** and caps the entire HTTP body at **33 MiB**
  (32 MiB images + 1 MiB multipart overhead).
* Rejects excessive declared `Content-Length` before form parsing.
* Counts actual bytes even when the request is chunked or the declared
  length is missing or understated. Returns JSON 413.
* Existing endpoint-level limits, user authentication, rate limiting, EXIF
  removal and photo moderation remain unchanged.
* This does **not** replace a reverse-proxy ingress cap. ASGI middleware runs
  after Caddy/Uvicorn have accepted the incoming connection.

### Production requirements

1. Read actual `systemctl cat kyiv-radar-api.service` and the effective import
   path. The v1.5.0 report says it imports `/opt/agent-bot/kyiv_radar_api.py`,
   not directly from this repository's `server/` folder.
2. Confirm the VPS matches the reviewed code; safely back up modules, services,
   configuration and production DB without posting private paths or contents.
3. Run full CI and isolated ASGI 413 tests before copying a candidate.
4. Deploy the **reviewed API module** only within a controlled maintenance
   window and confirm no unrelated service will be interrupted.
5. Confirm live `/api/health`, `/api/deals` privacy and one authorized small
   image upload through Telegram; test 413 at the staging ingress, not by
   saturating the live server with a 33+ MiB payload.

### Caddy edge hardening (separate coordinated change)

* Inventory all existing Caddy routes, certificates, plugins and the
  systemd unit. Replacing the full production Caddyfile blindly is forbidden.
* Back up Caddy binary, configuration and TLS state privately. Plan an
  independently tested revert route. Confirm upgrade compatibility across
  KyivPulse, Vudstoria and unrelated virtual hosts.
* Upgrade Caddy to a supported version **>= 2.10** using an approved source.
  The reference `server/Caddyfile.v2.10.example` is **not deployable as-is**.
* Merge the **route-scoped** `request_body @landlord_photo_upload { max_size
  33MiB }` directive into the *actual* production config, preserving other
  routes; run `caddy validate --config /etc/caddy/Caddyfile` on the target
  binary before a controlled reload.
* Validate both known `Content-Length` and streamed/unknown-length uploads
  in isolated staging. Confirm oversize uploads get 413, normal photos work,
  and other routes have no regressions.
* **NO-GO** if Caddy version/plugin compatibility or rollback is uncertain.

Caddy reference:
https://caddyserver.com/docs/caddyfile/directives/request_body

## Owner decision (17 November 2026): preserve the existing token

The owner has explicitly instructed **do not rotate, revoke, regenerate or replace the Telegram bot token**. No token action is part of the authorized v1.5.1 scope. Do not block independent upload hardening or QA work solely because this explicitly deferred item is unresolved. **The historic exposure risk remains open** and must be stated in release notes. Do not claim credential hygiene complete or promote the app as fully secure. Never print or publish the existing credential. Issue #7 stays open as a consciously deferred risk.

## Risk B — possibly exposed Telegram bot token

The existing Telegram token was intentionally left unchanged for the v1.5.0
release. The exposure risk remains until the old token is revoked.

**The bot owner must generate/revoke the token in the official @BotFather
conversation. Do not paste the new token in ChatGPT, GitHub, logs, PRs, or a
terminal command that is saved in shell history.**

1. Privately inventory *every* process / env file using this bot credential
   (at least `agent-bot.service`, `kyiv-radar-api.service`; verify other
   bot integrations and scheduled jobs too). Do not print their secret values.
2. Prepare a coordinated replacement and rollback for *configuration and
   services*, not for the revoked credential: revocation is irreversible.
3. In @BotFather choose the correct bot and use its revoke/regenerate-token
   action. The old token stops working immediately.
4. Update every consuming service's protected environment securely, preserving
   ownership and file mode 0600. Avoid printing values or leaving copies in
   the repository. Use an interactive editor or protected secret store.
5. Restart only affected services in the approved window; verify Bot API
   `getMe`, moderator callbacks, delivery of `/api/send_contact`, and
   a freshly opened Mini App (`initData` signatures change with the token).
6. Look for leaked token copies in repository history, logs and backups.
   Historical Git objects may still expose the **revoked** token. Clean up
   as a separately assessed operation; do not force-push shared history
   casually.
7. Keep the token issue OPEN until actual revocation and E2E checks are
   verified. No token values in completion evidence.

## Post-rollout acceptance (required for v1.5.1)

- [ ] No secrets committed. Existing Telegram token unchanged per explicit owner decision; historical token-exposure risk accepted for this phase and remains OPEN as Issue #7
- [ ] 413 for oversized known-length and streamed upload at Caddy *and* app
- [ ] Standard image upload, moderation, approved media and contact E2E pass
- [ ] `/api/deals` still has no raw phones, owner names or private data
- [ ] KyivPulse / Vudstoria remain healthy and unchanged
- [ ] Verified restorable backup and executable rollback for changed components
- [ ] Mobile checks: iOS Telegram WebApp, Android Telegram, responsive web
- [ ] Monitor API errors, upload 413s and bot failures after cutover

Until those boxes are checked, **do not claim both security risks closed**.
