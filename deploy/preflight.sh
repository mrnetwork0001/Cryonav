#!/usr/bin/env bash
# Cryonav VPS preflight — STRICTLY READ-ONLY. Installs nothing, writes nothing,
# restarts nothing. Run it on the VPS (or: ssh user@host 'bash -s' < deploy/preflight.sh)
# and read the verdicts at the bottom before deploying to a machine that hosts
# other services.
set -uo pipefail

PASS=0; WARN=0; FAIL=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$1"; }

hdr "System"
if [ -r /etc/os-release ]; then
  . /etc/os-release
  echo "  os: ${PRETTY_NAME:-unknown}  arch: $(uname -m)  kernel: $(uname -r)"
  case "${ID:-}:${ID_LIKE:-}" in
    debian:*|ubuntu:*|*:*debian*) ok "Debian-family distro — deploy.sh apt steps compatible" ;;
    *) bad "not Debian/Ubuntu (${ID:-?}) — deploy.sh uses apt and would need adapting" ;;
  esac
else
  bad "cannot read /etc/os-release"
fi
command -v systemctl >/dev/null 2>&1 && ok "systemd present" || bad "no systemd — the unit files cannot be used"
if sudo -n true 2>/dev/null; then ok "passwordless sudo"; else warn "sudo will prompt for a password (fine interactively, breaks unattended deploys)"; fi

hdr "Resources"
echo "  cpu: $(nproc 2>/dev/null || echo '?') cores"
mem_kb=$(awk '/MemTotal/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
mem_avail_kb=$(awk '/MemAvailable/{print $2}' /proc/meminfo 2>/dev/null || echo 0)
echo "  ram: total $((mem_kb/1024)) MB, available $((mem_avail_kb/1024)) MB"
# Cryonav footprint measured locally: 2 uvicorn workers ~90 MB each, calibrate spike ~120 MB.
if [ "$mem_avail_kb" -ge 409600 ]; then ok "RAM: >=400 MB available (Cryonav needs ~250 MB peak)";
elif [ "$mem_avail_kb" -ge 262144 ]; then warn "RAM: tight ($((mem_avail_kb/1024)) MB available) — drop to --workers 1 in cryonav-api.service";
else bad "RAM: only $((mem_avail_kb/1024)) MB available — will squeeze co-hosted services"; fi

for mount in / /opt /var; do
  df -P "$mount" >/dev/null 2>&1 || continue
  read -r _ _ used avail pct _ < <(df -Pk "$mount" | tail -1)
  echo "  disk $mount: $((avail/1024)) MB free (${pct} used)"
done
avail_opt_kb=$(df -Pk /opt 2>/dev/null | awk 'NR==2{print $4}'); avail_opt_kb=${avail_opt_kb:-0}
# App tree ~12 MB + venv ~120 MB + caddy ~40 MB + headroom.
if [ "$avail_opt_kb" -ge 1048576 ]; then ok "disk: >=1 GB free on /opt (need ~250 MB)";
elif [ "$avail_opt_kb" -ge 358400 ]; then warn "disk: under 1 GB free on /opt — enough (~250 MB needed) but little headroom";
else bad "disk: <350 MB free on /opt — not enough"; fi

hdr "Python"
if command -v python3 >/dev/null 2>&1; then
  pv=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
  echo "  python3: $pv"
  python3 -c 'import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)' && ok "python >= 3.9" || bad "python $pv < 3.9 — backend needs 3.9+"
  python3 -m venv --help >/dev/null 2>&1 && ok "venv module available" || warn "python3-venv missing — deploy.sh will apt-install it"
else
  warn "python3 not installed — deploy.sh will apt-install it"
fi

hdr "Ports & existing web servers (the part that can break co-hosted apps)"
listeners=$(ss -tlnp 2>/dev/null || ss -tln 2>/dev/null || netstat -tlnp 2>/dev/null || true)
show_port() { # port label
  local line
  line=$(echo "$listeners" | awk -v p=":$1$" '$4 ~ p {print; exit}')
  if [ -n "$line" ]; then
    local owner
    owner=$(echo "$line" | grep -oE 'users:\(\("[^"]+"' | head -1 | cut -d'"' -f2)
    echo "  port $1: IN USE${owner:+ by ${owner}}"
    return 0
  fi
  echo "  port $1: free"
  return 1
}
p80_owner=""; p443_owner=""
if show_port 80; then p80_owner=$(echo "$listeners" | awk '$4 ~ /:80$/ {print; exit}' | grep -oE 'users:\(\("[^"]+"' | head -1 | cut -d'"' -f2); fi
if show_port 443; then p443_owner=$(echo "$listeners" | awk '$4 ~ /:443$/ {print; exit}' | grep -oE 'users:\(\("[^"]+"' | head -1 | cut -d'"' -f2); fi
if show_port 8008; then bad "port 8008 (Cryonav API) already in use — pick another port before deploying"; else ok "port 8008 free for the Cryonav API"; fi

web_owner="${p80_owner:-$p443_owner}"
if [ -z "$web_owner" ]; then
  ok "ports 80/443 free — Caddy can own the web edge (deploy.sh default path)"
elif [ "$web_owner" = "caddy" ]; then
  if [ -f /etc/caddy/Caddyfile ] && grep -q "Cryonav edge config" /etc/caddy/Caddyfile 2>/dev/null; then
    ok "Caddy already serving OUR config — redeploy is safe"
  else
    warn "Caddy is running with a FOREIGN Caddyfile — deploy.sh will NOT overwrite it; it stages a snippet and prints manual import instructions"
  fi
else
  warn "ports 80/443 owned by '$web_owner' — deploy.sh will NOT install/start Caddy; Cryonav must be published as a vhost/location in your existing $web_owner (instructions printed at deploy time)"
fi

for unit in nginx apache2 httpd caddy traefik; do
  state=$(systemctl is-active "$unit" 2>/dev/null || true)
  [ "$state" = "active" ] && echo "  running web service: $unit"
done

hdr "Collision check on paths deploy.sh writes"
for path in /opt/cryonav /etc/cryonav /etc/systemd/system/cryonav-api.service; do
  if [ -e "$path" ]; then warn "$path already exists (previous Cryonav deploy? will be updated in place)"; else echo "  $path: absent (will be created)"; fi
done
id cryonav >/dev/null 2>&1 && warn "user 'cryonav' already exists (reused)" || echo "  user 'cryonav': absent (will be created)"

hdr "Outbound reachability (needed only by the daily calibration timer)"
if command -v curl >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://api.fortyguard.com/health || echo 000)
  [ "$code" = "200" ] && ok "api.fortyguard.com reachable (health 200)" || warn "api.fortyguard.com not reachable (got $code) — calibration timer would fail; app still serves cached data"
else
  warn "curl missing — deploy.sh will apt-install it"
fi

hdr "Verdict"
echo "  $PASS pass, $WARN warn, $FAIL fail"
if [ "$FAIL" -gt 0 ]; then
  echo "  DO NOT deploy yet — resolve the FAIL items above."
  exit 1
elif [ "$WARN" -gt 0 ]; then
  echo "  Deployable with care — read each WARN; none of them will break existing services,"
  echo "  because deploy.sh refuses the web-edge takeover when 80/443 are owned by another server."
  exit 0
else
  echo "  Clean — deploy.sh can run its default path."
  exit 0
fi
