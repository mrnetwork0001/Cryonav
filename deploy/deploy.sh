#!/usr/bin/env bash
# One-command Cryonav deployment to a Debian/Ubuntu VPS.
#
#   ./deploy/deploy.sh user@host [domain]
#
# What it does (idempotent - safe to re-run for every update):
#   1. builds the frontend locally and rsyncs the tree (incl. dist/) to /opt/cryonav
#      - the VPS needs Python 3.9+ but NO Node and NO git credentials
#   2. bootstraps the VPS on first run: cryonav user, python venv, Caddy (official repo)
#   3. installs /etc/cryonav/env from the local .env if the VPS copy doesn't exist yet,
#      and otherwise ADDS ONLY KEYS THAT ARE MISSING from it -- an existing value is never
#      rewritten, so a key rotated on the server survives a deploy from a stale checkout
#      (root:root 0600)
#   4. installs systemd units + Caddyfile, enables the daily calibration timer
#   5. restarts services and smoke-checks /api/v1/health through Caddy
#
# With a domain argument Caddy obtains TLS automatically (point the A record first).
# Without one it serves plain HTTP on the VPS IP -- and note that the Sentinel's live-GPS
# mode will then be dead on arrival, because browsers gate the Geolocation API on a secure
# context. Everything else works over HTTP; that one feature does not.
set -euo pipefail

TARGET="${1:?usage: deploy.sh user@host [domain]}"
DOMAIN="${2:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="${DOMAIN:-:80}"

if [ -z "$DOMAIN" ]; then
  echo "NOTE: no domain given, so Caddy will serve plain HTTP."
  echo "      The Sentinel's live-GPS mode needs a secure context and will not run."
  echo "      Re-run as: ./deploy/deploy.sh $TARGET your.domain to get automatic TLS."
fi

echo "==> Building frontend locally"
( cd "$ROOT/frontend" && npm run build >/dev/null && rm -f tsconfig.tsbuildinfo )

echo "==> Rsyncing tree to $TARGET:/opt/cryonav"
ssh "$TARGET" 'sudo mkdir -p /opt/cryonav && sudo chown "$(id -un)": /opt/cryonav'
rsync -az --delete \
  --exclude '.git' --exclude 'backend/.venv' --exclude 'frontend/node_modules' \
  --exclude '.env' --exclude '__pycache__' --exclude '.pytest_cache' \
  "$ROOT/" "$TARGET:/opt/cryonav/"

echo "==> Shipping secrets to /etc/cryonav/env (existing values are never overwritten)"
if [[ -f "$ROOT/.env" ]]; then
  scp -q "$ROOT/.env" "$TARGET:/tmp/cryonav.env"
  ssh "$TARGET" 'bash -s' <<'ENVMERGE'
set -euo pipefail
sudo mkdir -p /etc/cryonav
if [ ! -f /etc/cryonav/env ]; then
  sudo mv /tmp/cryonav.env /etc/cryonav/env
  echo "    installed /etc/cryonav/env"
else
  # Add only keys the server does not already have. A value already on the VPS is
  # authoritative -- it may have been rotated there, and clobbering it from a stale local
  # checkout is exactly the kind of silent breakage this deploy must never cause.
  added=0
  while IFS= read -r line; do
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"
    case "$key" in *[!A-Za-z0-9_]*|'') continue ;; esac
    if ! sudo grep -q "^${key}=" /etc/cryonav/env; then
      printf '%s\n' "$line" | sudo tee -a /etc/cryonav/env >/dev/null
      echo "    added missing key: ${key}"
      added=$((added+1))
    fi
  done < /tmp/cryonav.env
  [ "$added" -eq 0 ] && echo "    /etc/cryonav/env already has every key - unchanged"
  rm -f /tmp/cryonav.env
fi
sudo chown root:root /etc/cryonav/env
sudo chmod 600 /etc/cryonav/env
ENVMERGE
else
  ssh "$TARGET" 'sudo mkdir -p /etc/cryonav && sudo touch /etc/cryonav/env && sudo chmod 600 /etc/cryonav/env'
  echo "    no local .env - created empty /etc/cryonav/env (simulation mode)"
fi

echo "==> Remote bootstrap + service install"
# shellcheck disable=SC2029
ssh "$TARGET" CRYONAV_SITE_VALUE="$SITE" 'bash -s' <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# --- shared-host guards: this box may run other services; break nothing -----------------
listeners=$(ss -tlnp 2>/dev/null || true)
owner_of() { echo "$listeners" | awk -v p=":$1$" '$4 ~ p {print; exit}' | grep -oE 'users:\(\("[^"]+"' | head -1 | cut -d'"' -f2; }

if echo "$listeners" | awk '$4 ~ /:8008$/ {found=1} END {exit !found}'; then
  if [ "$(owner_of 8008)" != "uvicorn" ] && ! systemctl is-active --quiet cryonav-api 2>/dev/null; then
    echo "ABORT: port 8008 is in use by '$(owner_of 8008)' and it is not our service." >&2
    echo "Nothing was installed or changed. Free the port or change it in deploy/cryonav-api.service + deploy/Caddyfile." >&2
    exit 40
  fi
fi

WEB_OWNER=""
for port in 80 443; do
  o=$(owner_of "$port"); [ -n "$o" ] && WEB_OWNER="$o" && break
done
MANAGE_WEB=yes
if [ -n "$WEB_OWNER" ] && [ "$WEB_OWNER" != "caddy" ]; then
  # Another web server owns the edge. We must not install Caddy (its postinst tries to bind
  # :80 and fails or worse, races) and must not touch the existing server's config.
  MANAGE_WEB=no
elif [ "$WEB_OWNER" = "caddy" ] && [ -f /etc/caddy/Caddyfile ] && ! grep -q "Cryonav edge config" /etc/caddy/Caddyfile; then
  # Caddy exists but serves someone else's sites: stage our config, never overwrite.
  MANAGE_WEB=stage
fi
echo "web-edge strategy: ${MANAGE_WEB} (owner: ${WEB_OWNER:-none})"

# --- system deps (first run only, cheap afterwards)
command -v python3 >/dev/null || sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip rsync curl >/dev/null

# --- caddy from the official repo (only when this deploy owns the web edge)
if [ "$MANAGE_WEB" = "yes" ] && ! command -v caddy >/dev/null; then
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

# --- web edge, per strategy
case "$MANAGE_WEB" in
  yes)
    sudo mkdir -p /etc/caddy
    if [ -f /etc/caddy/Caddyfile ] && ! grep -q "Cryonav edge config" /etc/caddy/Caddyfile; then
      sudo cp /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.pre-cryonav.$(date +%s)"
      echo "backed up existing Caddyfile"
    fi
    sudo cp /opt/cryonav/deploy/Caddyfile /etc/caddy/Caddyfile
    echo "CRYONAV_SITE=${CRYONAV_SITE_VALUE}" | sudo tee /etc/caddy/cryonav.env >/dev/null
    sudo mkdir -p /etc/systemd/system/caddy.service.d
    printf '[Service]\nEnvironmentFile=/etc/caddy/cryonav.env\n' | sudo tee /etc/systemd/system/caddy.service.d/cryonav.conf >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable caddy >/dev/null 2>&1 || true
    sudo systemctl restart caddy
    sleep 3
    curl -fsS http://127.0.0.1/api/v1/health | head -c 200 && echo
    ;;
  stage)
    # Caddy runs someone else's sites: stage our block and let the operator import it.
    sudo cp /opt/cryonav/deploy/Caddyfile /etc/caddy/cryonav.caddy
    echo "CRYONAV_SITE=${CRYONAV_SITE_VALUE}" | sudo tee /etc/caddy/cryonav.env >/dev/null
    echo "STAGED: /etc/caddy/cryonav.caddy - your Caddyfile was NOT touched."
    echo "To publish Cryonav, add to /etc/caddy/Caddyfile:   import /etc/caddy/cryonav.caddy"
    echo "then set CRYONAV_SITE in caddy's environment (see /etc/caddy/cryonav.env) and reload caddy."
    ;;
  no)
    echo "SKIPPED web edge: ports 80/443 are owned by '${WEB_OWNER}'. Nothing web-related was changed."
    echo "The Cryonav API is up on 127.0.0.1:8008. To publish it through your existing ${WEB_OWNER}:"
    echo "  - proxy  /api/  ->  http://127.0.0.1:8008/api/"
    echo "  - proxy  /docs and /openapi.json  ->  http://127.0.0.1:8008"
    echo "  - serve  /opt/cryonav/frontend/dist  as static root with SPA fallback to /index.html"
    echo "An nginx example lives at /opt/cryonav/deploy/nginx-cryonav.conf.example"
    ;;
esac

# --- backend smoke check (always, directly against uvicorn)
sleep 2
curl -fsS http://127.0.0.1:8008/api/v1/health | head -c 200 && echo
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
echo "    calibration refresh: daily 05:30 UTC (systemd timer) - run now with:"
echo "      ssh $TARGET sudo systemctl start cryonav-calibrate.service"
