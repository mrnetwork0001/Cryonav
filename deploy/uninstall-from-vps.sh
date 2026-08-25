#!/usr/bin/env bash
# Remove Cryonav from a VPS, leaving every other service exactly as it was.
#
#   sudo bash /opt/cryonav/deploy/uninstall-from-vps.sh
#
# The point of this file is that installing Cryonav is not a one-way door. It removes only
# what the installer created, by name:
#
#   cryonav-api.service, cryonav-calibrate.{service,timer}
#   the 'cryonav' system user
#   /opt/cryonav, /etc/cryonav
#   the nginx vhost named 'cryonav' (only if it is ours)
#
# It deliberately does NOT: uninstall python3-venv/pip/curl (other things use them), touch
# any other nginx vhost, revoke or delete TLS certificates, remove Caddy, or restart any
# service other than the ones it is removing. nginx is RELOADED, never restarted, and only
# after `nginx -t` passes -- a reload keeps existing connections alive.
set -uo pipefail

KEEP_ENV="${KEEP_ENV:-0}"   # KEEP_ENV=1 preserves /etc/cryonav/env (your API keys)

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
did() { printf '  \033[32mremoved\033[0m  %s\n' "$1"; }
skip() { printf '  ·        %s\n' "$1"; }

say "Stopping Cryonav services"
for unit in cryonav-api.service cryonav-calibrate.timer cryonav-calibrate.service; do
  if systemctl list-unit-files 2>/dev/null | grep -q "^${unit}"; then
    sudo systemctl disable --now "$unit" >/dev/null 2>&1
    sudo rm -f "/etc/systemd/system/${unit}"
    did "$unit"
  else
    skip "$unit not installed"
  fi
done
sudo systemctl daemon-reload
sudo systemctl reset-failed 2>/dev/null || true

say "Removing the nginx vhost (only if it is ours)"
removed_vhost=0
for f in /etc/nginx/sites-enabled/cryonav /etc/nginx/sites-available/cryonav; do
  if [ -e "$f" ]; then
    # Only ever delete a file that identifies itself as ours. A vhost someone else wrote and
    # happened to name 'cryonav' must survive.
    if grep -q "Cryonav vhost" "$f" 2>/dev/null || [ -L "$f" ]; then
      sudo rm -f "$f"; did "$f"; removed_vhost=1
    else
      skip "$f exists but is not ours - left alone"
    fi
  fi
done
if [ "$removed_vhost" = "1" ] && command -v nginx >/dev/null 2>&1; then
  if sudo nginx -t >/dev/null 2>&1; then
    sudo systemctl reload nginx && did "nginx reloaded (graceful; connections preserved)"
  else
    echo "  WARNING: nginx -t failed AFTER removal. Not reloading. Inspect:" >&2
    sudo nginx -t
  fi
fi

say "Removing files"
if [ "$KEEP_ENV" = "1" ]; then
  skip "/etc/cryonav/env kept (KEEP_ENV=1)"
else
  [ -e /etc/cryonav ] && { sudo rm -rf /etc/cryonav; did "/etc/cryonav (including your API keys)"; }
fi
[ -e /opt/cryonav ] && { sudo rm -rf /opt/cryonav; did "/opt/cryonav"; }

say "Removing the runtime user"
if id cryonav >/dev/null 2>&1; then
  sudo userdel cryonav >/dev/null 2>&1 && did "user 'cryonav'" || skip "could not remove user 'cryonav'"
else
  skip "user 'cryonav' not present"
fi

say "Deliberately left in place"
skip "python3-venv / python3-pip / curl  (other software may depend on them)"
skip "every other nginx vhost, and nginx itself"
skip "all TLS certificates, including any issued for cryonav.xyz"
skip "docker, caddy, firewall rules, and every other service"

say "Done"
echo "  Cryonav is gone. Nothing else on this host was modified."
echo "  A certificate issued for cryonav.xyz still exists; remove it if you want with:"
echo "      sudo certbot delete --cert-name cryonav.xyz"
