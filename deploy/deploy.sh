#!/usr/bin/env bash
# One-command Cryonav deployment to a Debian/Ubuntu VPS.
#
#   ./deploy/deploy.sh user@host [domain]
#
# What it does (idempotent — safe to re-run for every update):
#   1. builds the frontend locally and rsyncs the tree (incl. dist/) to /opt/cryonav
#      — the VPS needs Python 3.9+ but NO Node and NO git credentials
#   2. bootstraps the VPS on first run: cryonav user, python venv, Caddy (official repo)
#   3. installs /etc/cryonav/env from the local .env if the VPS copy doesn't exist yet
#      (FORTYGUARD_API_KEY only; the file is root:root 0600)
#   4. installs systemd units + Caddyfile, enables the daily calibration timer
#   5. restarts services and smoke-checks /api/v1/health through Caddy
#
# With a domain argument Caddy obtains TLS automatically (point the A record first).
# Without one it serves plain HTTP on the VPS IP.
set -euo pipefail

TARGET="${1:?usage: deploy.sh user@host [domain]}"
DOMAIN="${2:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="${DOMAIN:-:80}"

echo "==> Building frontend locally"
( cd "$ROOT/frontend" && npm run build >/dev/null && rm -f tsconfig.tsbuildinfo )

echo "==> Rsyncing tree to $TARGET:/opt/cryonav"
ssh "$TARGET" 'sudo mkdir -p /opt/cryonav && sudo chown "$(id -un)": /opt/cryonav'
rsync -az --delete \
  --exclude '.git' --exclude 'backend/.venv' --exclude 'frontend/node_modules' \
  --exclude '.env' --exclude '__pycache__' --exclude '.pytest_cache' \
  "$ROOT/" "$TARGET:/opt/cryonav/"

echo "==> Shipping API key (only if /etc/cryonav/env is absent on the VPS)"
if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC2029
  ssh "$TARGET" '[ -f /etc/cryonav/env ]' 2>/dev/null \
    && echo "    /etc/cryonav/env exists — leaving it alone" \
    || scp -q "$ROOT/.env" "$TARGET:/tmp/cryonav.env" \
       && ssh "$TARGET" '[ -f /etc/cryonav/env ] || { sudo mkdir -p /etc/cryonav && sudo mv /tmp/cryonav.env /etc/cryonav/env && sudo chown root:root /etc/cryonav/env && sudo chmod 600 /etc/cryonav/env && echo "    installed /etc/cryonav/env"; }'
else
  ssh "$TARGET" 'sudo mkdir -p /etc/cryonav && sudo touch /etc/cryonav/env && sudo chmod 600 /etc/cryonav/env'
  echo "    no local .env — created empty /etc/cryonav/env (simulation mode)"
fi

echo "==> Remote bootstrap + service install"
# shellcheck disable=SC2029
ssh "$TARGET" CRYONAV_SITE_VALUE="$SITE" 'bash -s' <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# --- system deps (first run only, cheap afterwards)
command -v python3 >/dev/null || sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip rsync curl >/dev/null

# --- caddy from the official repo
if ! command -v caddy >/dev/null; then
  sudo apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq caddy >/dev/null
fi

# --- runtime user + permissions
id cryonav >/dev/null 2>&1 || sudo useradd --system --home /opt/cryonav --shell /usr/sbin/nologin cryonav
sudo chown -R cryonav:cryonav /opt/cryonav

# --- backend venv
sudo -u cryonav python3 -m venv /opt/cryonav/backend/.venv
sudo -u cryonav /opt/cryonav/backend/.venv/bin/pip install -q --upgrade pip
sudo -u cryonav /opt/cryonav/backend/.venv/bin/pip install -q -r /opt/cryonav/backend/requirements.txt

# --- systemd units
sudo cp /opt/cryonav/deploy/cryonav-api.service /etc/systemd/system/
sudo cp /opt/cryonav/deploy/cryonav-calibrate.service /etc/systemd/system/
sudo cp /opt/cryonav/deploy/cryonav-calibrate.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cryonav-api.service
sudo systemctl enable --now cryonav-calibrate.timer
sudo systemctl restart cryonav-api.service

# --- caddy site
sudo mkdir -p /etc/caddy
sudo cp /opt/cryonav/deploy/Caddyfile /etc/caddy/Caddyfile
echo "CRYONAV_SITE=${CRYONAV_SITE_VALUE}" | sudo tee /etc/caddy/cryonav.env >/dev/null
sudo mkdir -p /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironmentFile=/etc/caddy/cryonav.env\n' | sudo tee /etc/systemd/system/caddy.service.d/cryonav.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable caddy >/dev/null 2>&1 || true
sudo systemctl restart caddy

# --- wait + smoke check through the proxy
sleep 3
curl -fsS http://127.0.0.1/api/v1/health | head -c 200 && echo
echo "REMOTE OK"
REMOTE

echo
echo "==> Deployed."
if [[ -n "$DOMAIN" ]]; then
  echo "    landing:   https://$DOMAIN/"
  echo "    dashboard: https://$DOMAIN/app"
  echo "    api docs:  https://$DOMAIN/docs"
else
  HOST_ONLY="${TARGET#*@}"
  echo "    landing:   http://$HOST_ONLY/"
  echo "    dashboard: http://$HOST_ONLY/app"
  echo "    api docs:  http://$HOST_ONLY/docs"
fi
echo "    calibration refresh: daily 05:30 UTC (systemd timer) — run now with:"
echo "      ssh $TARGET sudo systemctl start cryonav-calibrate.service"
