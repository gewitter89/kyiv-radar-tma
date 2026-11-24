# Kyiv Radar — Production Architecture & Disaster Recovery Runbook

> **CRITICAL / 24 Nov 2026 — HISTORICAL BOOTSTRAP, NOT A LIVE DEPLOY SCRIPT.**
> The section titled "Fresh VPS Recovery from Scratch" is an archived
> starting point for a **brand-new empty host only**, not a valid upgrade,
> rollback, or restoration plan for the running Kyiv Radar VPS.
> **Never execute the commands in that section on an existing server.**
> It does not protect a WAL-mode SQLite database, approved owner photos,
> private contact vault, other shared service writers, or the verified
> listing catalogue. The repository's `data/deals.json` intentionally
> contains **[]** after P0 safety purge and MUST NOT overwrite live data.
>
> For any operational change use [the coordinated release runbook](../docs/COORDINATED_RELEASE_RUNBOOK.md),
> [the private backup-only preflight](../scripts/prepare_vps_release.py),
> and the current [source/rights release gates](../docs/DIM_RIA_20261124_SAFE_PILOT.md).
> **GitHub Pages success does not mean production VPS code is updated.**
> A new installation must independently review and adapt every path,
> service, package, database schema, security permission and token reference.

## Mandatory P0 safeguards for existing production

1. Read actual `systemctl cat` and process identities for **both**
   `kyiv-radar-api.service` and `agent-bot.service` plus any other SQLite
   writers; determine the real import paths, owner, database and catalog paths.
2. Capture private preflight backup with SQLite Online Backup API,
   WAL-consistent verification, catalogue, uploads, contacts, bot module,
   deployment configuration, permissions and exact deployed SHA. Keep private.
3. Never copy the repo's empty `data/deals.json` onto a live catalog,
   execute `schema.sql` against an existing database, or overwrite/restore a
   SQLite file while services/writers are active.
4. Test migration on a **disposable copy**. Change API and Telegram bot
   modules together only after explicit maintenance approval; avoid touching
   unrelated workloads.
5. Confirm current source permissions, stale/withdrawn property exclusion,
   media takedown (old URLs return 404 and no-store), user consent, no raw
   contacts in public API, and browser/API real-device E2E.
6. Stop/revert on any failed gate. A former release's rollback recipe may
   re-enable unsafe historical records: preserve private state, prefer a
   compatible code-only rollback and never blindly restore old catalog bytes.



## 1. System Architecture Overview

```
                      [ Client (TMA / Web Browser) ]
                                    |
                     HTTPS TLS 1.3 / HTTP/3 (Port 443)
                                    v
     [ Caddy 2 Reverse Proxy (vmi3445944.contaboserver.net) ]
                                    |
                         http://127.0.0.1:8000
                                    v
     [ FastAPI Daemon (kyiv-radar-api.service) ]
       * Runs under unprivileged system user `kyivradar:kyivradar` (Zero Root)
       * Strict CORS: https://gewitter89.github.io only (no wildcard '*')
       * Zero exposed staging/admin routes
              /             |                   \
             v              v                    v
  [ rent_deals.db ]  [ deals.json ]      [ Telegram Bot API ]
  (SQLite database)  (Live catalog)      (@prostov_shrink_bot)
```

- **Server Hostname**: `vmi3445944.contaboserver.net` (Static Contabo A-Record)
- **Public API Base**: `https://vmi3445944.contaboserver.net/api`
- **Reverse Proxy**: Caddy 2 (`caddy.service`), manages Let's Encrypt TLS certificates.
- **Application Server**: Uvicorn with 2 workers managed by `kyiv-radar-api.service` under user `kyivradar`.
- **Primary Data**:
  - Complaints & Landlord Submissions: `/opt/resell-radar-ukraine/data/rent_deals.db`
  - Apartment Catalog: `/opt/kyiv-radar-tma/data/deals.json`

---

## 2. Emergency Service Operations

Check status of backend services:
```bash
systemctl status caddy.service
systemctl status kyiv-radar-api.service
```

Inspect process ownership (MUST show `kyivradar` user, NOT `root`):
```bash
ps -u kyivradar -o pid,user,cmd
```

Restart backend after code updates:
```bash
systemctl restart kyiv-radar-api.service
```

Inspect live API logs:
```bash
journalctl -u kyiv-radar-api.service -f -n 100
```

Verify public HTTPS health check:
```bash
curl -I https://vmi3445944.contaboserver.net/api/health
curl -s https://vmi3445944.contaboserver.net/api/health | jq .
```

---

## 3. Historical fresh-install sketch — NOT FOR EXISTING HOSTS

### Step 1: Install Base Packages & Caddy
```bash
sudo apt update && sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl sqlite3 python3-pip python3-venv git jq

# Install Caddy
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

### Step 2: Create Unprivileged System User & Directories
```bash
useradd -r -s /usr/sbin/nologin -d /opt/agent-bot kyivradar || true
mkdir -p /opt/agent-bot /opt/kyiv-radar-tma/data /opt/resell-radar-ukraine/data /etc/caddy

python3 -m venv /opt/agent-bot/venv
/opt/agent-bot/venv/bin/pip install --upgrade pip
/opt/agent-bot/venv/bin/pip install fastapi uvicorn aiohttp pydantic python-multipart
```

### Step 3: Deploy Application Code & Set File Permissions
```bash
# Copy files into place
# This single-file copy is historical and insufficient for current modular imports.
# Deploy the full pinned compatible package/API+bot as verified by the release runbook.
# cp server/kyiv_radar_api.py /opt/agent-bot/kyiv_radar_api.py
cp server/schema.sql /opt/resell-radar-ukraine/data/
sqlite3 /opt/resell-radar-ukraine/data/rent_deals.db < server/schema.sql
# DO NOT copy the repo's deliberately empty data/deals.json over live data.
# For a new empty host only, initialize its own empty catalogue explicitly.
printf '[]\\n' > /opt/kyiv-radar-tma/data/deals.json

# Secure permissions
chown -R kyivradar:kyivradar /opt/resell-radar-ukraine/data
chmod 700 /opt/resell-radar-ukraine/data
chmod 600 /opt/resell-radar-ukraine/data/rent_deals.db
chown kyivradar:kyivradar /opt/kyiv-radar-tma/data/deals.json
chmod 600 /opt/kyiv-radar-tma/data/deals.json
# Only set ownership AFTER installing the full, compatible API/bot package:
# chown kyivradar:kyivradar /opt/agent-bot/kyiv_radar_api.py
```

### Step 4: Configure Secrets & Systemd
```bash
# Create .env with mode 600
# NEVER paste actual tokens into shared terminal logs.
cat << 'EOF' > /opt/agent-bot/.env
APP_ENV=production
BOT_TOKEN=YOUR_BOTFATHER_TOKEN
ADMIN_CHAT_ID=8531839081
KYIV_RADAR_DB_PATH=/opt/resell-radar-ukraine/data/rent_deals.db
KYIV_RADAR_DEALS_PATH=/opt/kyiv-radar-tma/data/deals.json
EOF
chmod 600 /opt/agent-bot/.env
chown kyivradar:kyivradar /opt/agent-bot/.env

# Enable service
cp server/kyiv-radar-api.service /etc/systemd/system/kyiv-radar-api.service
systemctl daemon-reload
systemctl enable --now kyiv-radar-api.service

# Configure Caddyfile
cp server/Caddyfile /etc/caddy/Caddyfile
systemctl restart caddy
```

---

## 4. Telegram Bot Token Rotation Guide

> [!IMPORTANT]
> Never post raw bot tokens in public chats, git commits, or unencrypted tickets.

To revoke and update the bot token:
1. Open Telegram and message `@BotFather`.
2. Send `/mybots`.
3. Select your bot.
4. Choose **API Token** -> **Revoke current token**.
5. Save the newly generated token directly into `/opt/agent-bot/.env` on the VPS:
   ```bash
   sed -i 's/^BOT_TOKEN=.*/BOT_TOKEN=NEW_TOKEN_HERE/' /opt/agent-bot/.env
   chmod 600 /opt/agent-bot/.env
   systemctl restart kyiv-radar-api.service
   systemctl restart agent-bot.service
   ```
6. Verify API health: `curl https://vmi3445944.contaboserver.net/api/health`.
