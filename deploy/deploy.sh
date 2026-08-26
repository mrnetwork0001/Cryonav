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
# Recursive, not just the top directory. The end of this script hands the whole tree to the
# cryonav service user, so on every deploy AFTER the first, rsync arrives as the SSH user and
# finds subdirectories owned by cryonav - and fails on the first write. Chowning only
# /opt/cryonav made the first deploy work and every later one fail.
ssh "$TARGET" 'sudo mkdir -p /opt/cryonav && sudo chown -R "$(id -un)": /opt/cryonav'
rsync -az --delete \
  --exclude '.git' --exclude 'backend/.venv' --exclude 'frontend/node_modules' \
  --exclude '.env' --exclude '__pycache__' --exclude '.pytest_cache' \
  --exclude 'demo/node_modules' --exclude 'demo/footage' \
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
# Ask for the listener table WITH ROOT. Without it, `ss -tlnp` still prints the listening
# rows but silently drops the process column - so a box where nginx owns :80 looks exactly
# like a box where nothing does. preflight-inline.sh already knew this and says so
# ("process names are hidden without sudo"); these two scripts did not, and every mutating
# command below is sudo-prefixed, meaning the documented invocation is NON-root. That is the
# case where the owner is invisible.
OWNERS_HIDDEN=0
if listeners=$(sudo -n ss -Htlnp 2>/dev/null); then
  :
else
  listeners=$(ss -Htln 2>/dev/null || true)
  OWNERS_HIDDEN=1
fi

port_in_use() { echo "$listeners" | awk -v p=":$1$" '$4 ~ p {found=1} END {exit !found}'; }

# The trailing `|| true` is load-bearing. grep exits 1 when the process column is absent, and
# under `set -euo pipefail` that status propagates out of the pipeline, out of the function,
# and out of `o=$(owner_of ...)` - which killed the whole script at that line with no message
# at all. Verified: with a non-root ss table this block used to exit 1 before printing
# anything, leaving the operator with a deploy that stopped for no stated reason.
owner_of() {
  echo "$listeners" | awk -v p=":$1$" '$4 ~ p {print; exit}' \
    | grep -oE 'users:\(\("[^"]+"' | head -1 | cut -d'"' -f2 || true
}

if port_in_use 8008; then
  if [ "$(owner_of 8008)" != "uvicorn" ] && ! systemctl is-active --quiet cryonav-api 2>/dev/null; then
    holder=$(owner_of 8008)
    if [ -z "$holder" ]; then
      echo "ABORT: port 8008 is held by a process this script cannot identify, and" >&2
      echo "cryonav-api is not running - so it is not ours." >&2
      echo "(ss needs root to show process names; try 'sudo ss -tlnp | grep :8008'.)" >&2
    else
      echo "ABORT: port 8008 is in use by '$holder' and it is not our service." >&2
    fi
    echo "Nothing was installed or changed. Free the port or change it in" >&2
    echo "deploy/cryonav-api.service and the web edge's proxy target." >&2
    exit 40
  fi
fi

WEB_OWNER=""
WEB_PORT_BUSY=0
for port in 80 443; do
  if port_in_use "$port"; then
    WEB_PORT_BUSY=1
    o=$(owner_of "$port")
    if [ -n "$o" ]; then WEB_OWNER="$o"; break; fi
  fi
done

MANAGE_WEB=yes
if [ "$WEB_PORT_BUSY" = "1" ] && [ -z "$WEB_OWNER" ]; then
  # OCCUPIED BUT UNIDENTIFIED IS NOT FREE. Defaulting to yes here would install and, worse,
  # `systemctl enable` Caddy on a host whose web edge already belongs to something else. The
  # restart fails immediately (the ports are taken) so it reads as a mere failed step - but
  # caddy.service stays enabled at boot, with no ordering against nginx.service, and the next
  # reboot is a race for :80/:443 that the existing server can lose.
  MANAGE_WEB=no
  echo "WARNING: port 80/443 is in use, but the owning process could not be identified." >&2
  if [ "$OWNERS_HIDDEN" = "1" ]; then
    echo "         (ss cannot show process names without root; 'sudo -n' was refused here.)" >&2
  fi
  echo "         Treating the web edge as OWNED and leaving it alone. Nothing will be" >&2
  echo "         installed on :80/:443. Publish the site with deploy/nginx-publish.sh." >&2
elif [ -n "$WEB_OWNER" ] && [ "$WEB_OWNER" != "caddy" ]; then
  # Another web server owns the edge. We must not install Caddy (its postinst tries to bind
  # :80 and fails or worse, races) and must not touch the existing server's config.
  MANAGE_WEB=no
elif [ "$WEB_OWNER" = "caddy" ] && [ -f /etc/caddy/Caddyfile ] && ! grep -q "Cryonav edge config" /etc/caddy/Caddyfile; then
  # Caddy exists but serves someone else's sites: stage our config, never overwrite.
  MANAGE_WEB=stage
fi
echo "web-edge strategy: ${MANAGE_WEB} (owner: ${WEB_OWNER:-none})"

# --- system deps -----------------------------------------------------------------------
# This ran `apt-get install` unconditionally on EVERY deploy, with no needrestart guard - the
# exact hazard install-on-vps.sh documents at length and defends against. apt-get install on
# an already-present package still upgrades it to the candidate version and pulls dependency
# upgrades with it, and Ubuntu 22.04+ hooks needrestart into apt so that non-interactive runs
# RESTART daemons whose libraries changed. On a host running the operator's other production
# services, a Cryonav deploy could therefore bounce nginx or a database mid-request.
#
# Same two defences as the installer: work out what is genuinely missing and skip apt
# entirely when nothing is, and pass the needrestart suppression ACROSS the sudo boundary
# (sudo's env_reset drops exported NEEDRESTART_* before apt ever sees them).
APT_ENV="DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l NEEDRESTART_SUSPEND=1"

missing=""
command -v rsync >/dev/null 2>&1 || missing="$missing rsync"
command -v curl  >/dev/null 2>&1 || missing="$missing curl"
command -v pip3  >/dev/null 2>&1 || missing="$missing python3-pip"
# venv's stdlib module exists even where the bundled wheels do not, so build one to find out.
_probe=$(mktemp -d)
python3 -m venv "$_probe/v" >/dev/null 2>&1 || missing="$missing python3-venv"
rm -rf "$_probe"

if [ -n "$missing" ]; then
  echo "==> Installing missing system packages:$missing"
  echo "    (needrestart suppressed - apt will restart no running service)"
  # shellcheck disable=SC2086
  sudo $APT_ENV apt-get update -qq
  # shellcheck disable=SC2086
  sudo $APT_ENV apt-get install -y -qq $missing >/dev/null
else
  echo "==> All required system packages already present - apt not touched"
fi

# --- caddy from the official repo (only when this deploy owns the web edge)
if [ "$MANAGE_WEB" = "yes" ] && ! command -v caddy >/dev/null; then
  # shellcheck disable=SC2086
  sudo $APT_ENV apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  # shellcheck disable=SC2086
  sudo $APT_ENV apt-get update -qq && sudo $APT_ENV apt-get install -y -qq caddy >/dev/null
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
