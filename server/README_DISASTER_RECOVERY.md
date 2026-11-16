# Kyiv Radar — Production Architecture & Disaster Recovery Runbook

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

## 3. Fresh VPS Recovery from Scratch

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
cp server/kyiv_radar_api.py /opt/agent-bot/kyiv_radar_api.py
cp server/schema.sql /opt/resell-radar-ukraine/data/
sqlite3 /opt/resell-radar-ukraine/data/rent_deals.db < server/schema.sql
cp data/deals.json /opt/kyiv-radar-tma/data/deals.json

# Secure permissions
chown -R kyivradar:kyivradar /opt/resell-radar-ukraine/data
chmod 775 /opt/resell-radar-ukraine/data
chmod 664 /opt/resell-radar-ukraine/data/rent_deals.db
chown kyivradar:kyivradar /opt/kyiv-radar-tma/data/deals.json
chmod 664 /opt/kyiv-radar-tma/data/deals.json
chown kyivradar:kyivradar /opt/agent-bot/kyiv_radar_api.py
```

### Step 4: Configure Secrets & Systemd
```bash
# Create .env with mode 600
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
