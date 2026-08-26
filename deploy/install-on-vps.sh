#!/usr/bin/env bash
# Cryonav installer that runs ON the VPS, for a manual deploy (Termius, console, whatever).
#
#   sudo -v                                   # cache credentials once, so nothing prompts mid-run
#   bash /opt/cryonav/deploy/install-on-vps.sh [domain]
#
# Use this when you cannot run deploy/deploy.sh from your laptop -- because the repo is
# private, or you have no rsync, or you just prefer typing on the server. It assumes
# /opt/cryonav is ALREADY populated (extract the bundle there first) and that the frontend
# was built before bundling, so this box needs no Node and no git credentials.
#
# With a domain argument Caddy gets a real certificate. Without one it serves plain HTTP on
# the IP, and the Sentinel's live-GPS mode will not run -- browsers gate the Geolocation API
# on a secure context.
#
# CO-HOSTING SAFETY. This box may already be serving other people's sites. The script:
#   * ABORTS if port 8008 is held by anything that is not Cryonav
#   * NEVER installs Caddy when nginx/apache/anything else already owns 80/443
#   * NEVER overwrites an existing Caddyfile -- it backs up, or stages alongside
#   * touches no configuration belonging to another service
# The worst case is that it declines to publish and tells you how to do it by hand.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

DOMAIN="${1:-}"
SITE="${DOMAIN:-:80}"
ROOT=/opt/cryonav

if [ ! -f "$ROOT/backend/main.py" ]; then
  echo "ABORT: $ROOT/backend/main.py not found. Extract the bundle to $ROOT first." >&2
  exit 2
fi
if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "ABORT: $ROOT/frontend/dist/index.html not found." >&2
  echo "The bundle must contain a BUILT frontend; this server has no Node toolchain." >&2
  exit 2
fi

if [ -z "$DOMAIN" ]; then
  echo "NOTE: no domain given -- serving plain HTTP."
  echo "      The Sentinel's live-GPS mode needs HTTPS and will not run."
  echo "      Re-run as: bash $0 your.domain"
  echo
fi

# --- shared-host guards ------------------------------------------------------------------
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
      echo "ABORT: port 8008 is held by '$holder', which is not Cryonav." >&2
    fi
    echo "Nothing was installed or changed. Free the port, or change it in" >&2
    echo "deploy/cryonav-api.service and the nginx proxy_pass target." >&2
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
echo "==> web-edge strategy: ${MANAGE_WEB} (current owner: ${WEB_OWNER:-none})"

# --- state the blast radius, then ask ------------------------------------------------------
cat <<PLAN

This installer is about to change the following, and NOTHING else:

  CREATE  /opt/cryonav                     (already extracted; ownership set to cryonav)
  CREATE  system user 'cryonav'            (no login shell, no password)
  CREATE  /etc/cryonav/env                 (root-only, 0600)
  CREATE  /etc/systemd/system/cryonav-api.service
  CREATE  /etc/systemd/system/cryonav-calibrate.{service,timer}
  START   cryonav-api on 127.0.0.1:8008    (loopback only - not exposed directly)
  APT     only packages genuinely missing, with needrestart suppressed so that
          apt cannot restart any running daemon

  Web edge strategy for THIS host: ${MANAGE_WEB}$([ "$MANAGE_WEB" = "no" ] && echo "  <- nothing web-related will be touched")

It does NOT modify nginx, apache, docker, existing systemd units, existing
certificates, firewall rules, or any file outside the paths listed above.
To undo everything: sudo bash $ROOT/deploy/uninstall-from-vps.sh

PLAN
if [ -t 0 ]; then
  printf "Proceed? [y/N] "
  read -r reply
  case "$reply" in [yY]*) ;; *) echo "Aborted. Nothing was changed."; exit 0 ;; esac
fi

# --- secrets -----------------------------------------------------------------------------
sudo mkdir -p /etc/cryonav
sudo touch /etc/cryonav/env
sudo chown root:root /etc/cryonav/env
sudo chmod 600 /etc/cryonav/env
if ! sudo grep -q '^FORTYGUARD_API_KEY=' /etc/cryonav/env 2>/dev/null; then
  echo "==> NOTE: /etc/cryonav/env has no FORTYGUARD_API_KEY."
  echo "    The stack will start and run on its deterministic simulation until you add one:"
  echo "      sudo nano /etc/cryonav/env"
  echo "      sudo systemctl restart cryonav-api"
fi

# --- system deps -------------------------------------------------------------------------
# Two dangers here, on a box running other people's services.
#
# 1. needrestart. Ubuntu 22.04+ ships it hooked into apt, and in non-interactive mode it
#    RESTARTS running daemons whose libraries changed. Installing a Python package could
#    therefore bounce nginx, a database, or anything else mid-request. NEEDRESTART_MODE=l
#    makes it list what it would restart and restart nothing. These MUST be passed on the
#    sudo command line, not exported: sudo defaults to env_reset, and NEEDRESTART_* is not in
#    its env_keep list, so an exported value is dropped on the way to apt and the suppression
#    silently does nothing. APT_ENV below carries them across the privilege boundary.
# 2. Touching apt at all. Every apt run takes the dpkg lock and can pull dependency updates.
#    So: work out what is actually missing first, and if nothing is, never invoke apt.
APT_ENV="DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l NEEDRESTART_SUSPEND=1"

missing=""
# Debian and Ubuntu ship the `venv` MODULE in the stdlib but move the bundled wheels into the
# python3-venv PACKAGE. So `import venv` and even `python3 -m venv --help` both succeed on a
# box where `python3 -m venv foo` then dies with "ensurepip is not available". The only
# honest test is to actually build one.
_probe=$(mktemp -d)
if ! python3 -m venv "$_probe/v" >/dev/null 2>&1; then
  missing="$missing python3-venv"
fi
rm -rf "$_probe"
command -v curl >/dev/null 2>&1 || missing="$missing curl"

if [ -n "$missing" ]; then
  echo "==> Installing missing system packages:$missing"
  echo "    (needrestart suppressed - no running service will be restarted by apt)"
  # shellcheck disable=SC2086
  sudo $APT_ENV apt-get update -qq
  # shellcheck disable=SC2086
  sudo $APT_ENV apt-get install -y -qq $missing >/dev/null
else
  echo "==> All required system packages already present - apt not touched"
fi

# --- caddy, only when this deploy owns the edge -------------------------------------------
if [ "$MANAGE_WEB" = "yes" ] && ! command -v caddy >/dev/null; then
  echo "==> Installing Caddy from the official repository"
  # shellcheck disable=SC2086
  sudo $APT_ENV apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https gnupg >/dev/null
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  # shellcheck disable=SC2086
  sudo $APT_ENV apt-get update -qq && sudo $APT_ENV apt-get install -y -qq caddy >/dev/null
fi

# --- runtime user + venv -------------------------------------------------------------------
echo "==> Creating runtime user and virtualenv"
id cryonav >/dev/null 2>&1 \
  || sudo useradd --system --home "$ROOT" --shell /usr/sbin/nologin cryonav
sudo chown -R cryonav:cryonav "$ROOT"
sudo -u cryonav python3 -m venv "$ROOT/backend/.venv"
sudo -u cryonav "$ROOT/backend/.venv/bin/pip" install -q --upgrade pip
# requirements.txt only. requirements-data.txt (rasterio, GDAL, pystac) is for preparing the
# satellite datasets on a workstation; the server just reads the JSON that produced.
sudo -u cryonav "$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"

# --- systemd -------------------------------------------------------------------------------
echo "==> Installing systemd units"
sudo cp "$ROOT/deploy/cryonav-api.service" /etc/systemd/system/
sudo cp "$ROOT/deploy/cryonav-calibrate.service" /etc/systemd/system/
sudo cp "$ROOT/deploy/cryonav-calibrate.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cryonav-api.service
sudo systemctl enable --now cryonav-calibrate.timer
sudo systemctl restart cryonav-api.service

echo "==> Waiting for the API to answer on 127.0.0.1:8008"
for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8008/api/v1/health >/dev/null 2>&1 && break
  sleep 1
done
if curl -fsS http://127.0.0.1:8008/api/v1/health >/dev/null 2>&1; then
  echo "    API is up."
else
  echo "    API did NOT come up. Logs:" >&2
  sudo journalctl -u cryonav-api -n 40 --no-pager >&2
  exit 41
fi

# --- web edge --------------------------------------------------------------------------------
case "$MANAGE_WEB" in
  yes)
    echo "==> Publishing through Caddy (site: ${SITE})"
    sudo mkdir -p /etc/caddy
    if [ -f /etc/caddy/Caddyfile ] && ! grep -q "Cryonav edge config" /etc/caddy/Caddyfile; then
      backup="/etc/caddy/Caddyfile.pre-cryonav.$(date +%s)"
      sudo cp /etc/caddy/Caddyfile "$backup"
      echo "    backed up your existing Caddyfile to $backup"
    fi
    sudo cp "$ROOT/deploy/Caddyfile" /etc/caddy/Caddyfile
    echo "CRYONAV_SITE=${SITE}" | sudo tee /etc/caddy/cryonav.env >/dev/null
    sudo mkdir -p /etc/systemd/system/caddy.service.d
    printf '[Service]\nEnvironmentFile=/etc/caddy/cryonav.env\n' \
      | sudo tee /etc/systemd/system/caddy.service.d/cryonav.conf >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable caddy >/dev/null 2>&1 || true
    sudo systemctl restart caddy
    sleep 3
    echo -n "    through Caddy: "
    curl -fsS http://127.0.0.1/api/v1/health | head -c 160 && echo
    ;;
  stage)
    sudo cp "$ROOT/deploy/Caddyfile" /etc/caddy/cryonav.caddy
    echo "CRYONAV_SITE=${SITE}" | sudo tee /etc/caddy/cryonav.env >/dev/null
    echo "==> STAGED. Your Caddyfile was NOT modified."
    echo "    To publish, add this line to /etc/caddy/Caddyfile:"
    echo "        import /etc/caddy/cryonav.caddy"
    echo "    then set CRYONAV_SITE (see /etc/caddy/cryonav.env) and: sudo systemctl reload caddy"
    ;;
  no)
    echo "==> SKIPPED the web edge: ports 80/443 belong to '${WEB_OWNER}'."
    echo "    Nothing web-related was touched. The API is live on 127.0.0.1:8008."
    echo "    To publish it through your existing ${WEB_OWNER}:"
    echo "      - proxy /api/  ->  http://127.0.0.1:8008/api/"
    echo "      - proxy /docs and /openapi.json -> http://127.0.0.1:8008"
    echo "      - serve /opt/cryonav/frontend/dist as static root, SPA fallback to /index.html"
    echo "    A ready-made nginx server block is at $ROOT/deploy/nginx-cryonav.conf.example"
    ;;
esac

echo
echo "==> Done."
echo "    service:  sudo systemctl status cryonav-api"
echo "    logs:     sudo journalctl -u cryonav-api -f"
echo "    secrets:  sudo nano /etc/cryonav/env   (then: sudo systemctl restart cryonav-api)"
[ -n "$DOMAIN" ] && echo "    site:     https://${DOMAIN}"
