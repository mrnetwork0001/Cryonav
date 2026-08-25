#!/usr/bin/env bash
# Cryonav VPS preflight — READ-ONLY.
#
# Installs nothing, starts nothing, stops nothing, writes nothing outside /tmp. Every command
# below is an inspection. Its whole job is to answer one question before anything is
# installed: what is already running on this box, and would Cryonav collide with it?
#
# Paste it into Termius on the VPS and send me the output.

say()  { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$1"; }
info() { printf '  ·     %s\n' "$1"; }

# Ask for sudo ONCE, up front. Otherwise the password prompt appears somewhere in the middle
# of the output and is easy to miss in a terminal, and every sudo below silently fails.
if command -v sudo >/dev/null 2>&1 && ! sudo -n true 2>/dev/null; then
  echo "This preflight reads privileged information (listening sockets, containers)."
  echo "It changes nothing. Enter your sudo password once:"
  sudo -v || echo "  (continuing without sudo — some answers will read UNKNOWN)"
fi

say "Host"
info "$(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -a)"
info "kernel $(uname -r)  |  arch $(uname -m)"
info "uptime$(uptime -p 2>/dev/null | sed 's/^up/ /' || echo ' ?')"
info "public IP: $(curl -s --max-time 8 https://api.ipify.org || echo '(could not determine)')"

say "Resources"
info "RAM:  $(free -h 2>/dev/null | awk '/^Mem:/{print $3" used of "$2" ("$7" available)"}')"
info "Disk: $(df -h / | awk 'NR==2{print $3" used of "$2" ("$4" free, "$5" full)"}')"
info "CPU:  $(nproc) core(s)"
avail_mb=$(free -m 2>/dev/null | awk '/^Mem:/{print $7}')
[ -n "$avail_mb" ] && [ "$avail_mb" -lt 400 ] \
  && warn "under 400 MB available — the Python venv build may struggle" \
  || ok "enough memory headroom to build a venv"

say "What owns the web edge (the collision that matters most)"
# This is the one answer that must never be wrong. Reporting "free" when something is
# actually listening leads directly to installing Caddy on top of a running nginx and taking
# production down. So "I could not check" is tracked as its own outcome and NEVER collapses
# into "free" -- an absent tool, a denied sudo, or a non-systemd box all land in UNKNOWN.
PORTCHECK_TOOL=""
raw_listeners=""
# Gate on EXIT STATUS, never on whether output was produced. A host with genuinely nothing
# listening returns success and zero rows; treating that as "the tool failed" would report
# UNKNOWN for the one case where the honest answer is "free". Conversely a missing binary or
# a refused sudo is a non-zero exit, which is what must land in UNKNOWN.
if command -v ss >/dev/null 2>&1; then
  if raw_listeners=$(sudo -n ss -Htlnp 2>/dev/null); then
    PORTCHECK_TOOL="ss (root)"
  elif raw_listeners=$(ss -Htln 2>/dev/null); then
    # Without root the rows are all still there; only the process NAME column is lost.
    PORTCHECK_TOOL="ss (no sudo — process names hidden)"
  fi
fi
if [ -z "$PORTCHECK_TOOL" ] && command -v netstat >/dev/null 2>&1; then
  if raw_listeners=$(sudo -n netstat -tlnp 2>/dev/null); then
    PORTCHECK_TOOL="netstat (root)"
  elif raw_listeners=$(netstat -tln 2>/dev/null); then
    PORTCHECK_TOOL="netstat (no sudo — process names hidden)"
  fi
fi

if [ -z "$PORTCHECK_TOOL" ]; then
  warn "COULD NOT DETERMINE port ownership — neither ss nor netstat returned anything."
  warn "Treat this as UNKNOWN, never as free. Do NOT let any installer take ports 80/443"
  warn "until this is resolved. Try:  sudo ss -tlnp   and paste the output."
else
  info "checked with: $PORTCHECK_TOOL"
  # Match the LOCAL ADDRESS column exactly, so :8080 and pid=80 cannot masquerade as :80.
  # Field 4 for ss -H, field 4 for netstat; both render as ADDR:PORT, incl. [::]:443 and *:80.
  web=$(printf '%s\n' "$raw_listeners" | awk '{ for (i=1;i<=NF;i++) if ($i ~ /:(80|443)$/) { print; break } }')
  if [ -z "$web" ]; then
    ok "ports 80/443 are FREE — Cryonav may install and own Caddy"
    ok "  (both IPv4 and IPv6 checked; no listener on either)"
  else
    warn "ports 80/443 are ALREADY IN USE:"
    printf '%s\n' "$web" | sed 's/^/        /'
    printf '%s\n' "$web" | grep -qi nginx     && warn "  -> nginx owns the edge; publish Cryonav as an nginx vhost, NOT via Caddy"
    printf '%s\n' "$web" | grep -qi apache    && warn "  -> apache owns the edge; publish Cryonav as an apache vhost, NOT via Caddy"
    printf '%s\n' "$web" | grep -qi caddy     && info "  -> caddy already here; Cryonav stages a site block beside your Caddyfile"
    printf '%s\n' "$web" | grep -qiE 'docker|containerd' && warn "  -> a container owns the edge; identify it in the Docker section below"
    case "$PORTCHECK_TOOL" in
      *"no sudo"*) warn "  -> process names are hidden without sudo; re-run with sudo to identify the owner" ;;
    esac
  fi
fi

say "Is Cryonav's own port free?"
# Same rule as above: reuse the listener table already verified, so a missing tool reports
# UNKNOWN rather than a confident and wrong "free".
if [ -z "$PORTCHECK_TOOL" ]; then
  warn "UNKNOWN — could not enumerate listeners (see above)"
else
  for p in 8008 5180; do
    hit=$(printf '%s\n' "$raw_listeners" | awk -v pat=":$p\$" '{ for (i=1;i<=NF;i++) if ($i ~ pat) { print; break } }')
    if [ -n "$hit" ]; then
      warn "port $p is TAKEN:"
      printf '%s\n' "$hit" | sed 's/^/        /'
    else
      ok "port $p is free"
    fi
  done
fi

say "Existing web servers / proxies"
for svc in nginx apache2 httpd caddy traefik haproxy lighttpd; do
  if systemctl list-unit-files 2>/dev/null | grep -q "^${svc}\.service"; then
    state=$(systemctl is-active "$svc" 2>/dev/null)
    enabled=$(systemctl is-enabled "$svc" 2>/dev/null)
    warn "$svc is installed — $state / $enabled  ** DO NOT DISTURB **"
    [ "$svc" = "nginx" ] && info "     sites: $(ls /etc/nginx/sites-enabled 2>/dev/null | tr '\n' ' ')"
    [ "$svc" = "caddy" ] && info "     Caddyfile: $(wc -l < /etc/caddy/Caddyfile 2>/dev/null || echo '?') lines"
  fi
done

say "Container runtimes (a very common way to already own port 80)"
# `docker ps` is NOT read-only when the daemon is stopped. Both docker.io and docker-ce ship
# docker.socket enabled with docker.service Requires=docker.socket, so merely connecting to
# /run/docker.sock socket-activates dockerd -- which then restarts every container marked
# restart=always. An admin who deliberately stopped Docker would find it running again, and
# this script's promise to start nothing would be a lie. So: only probe a daemon that is
# already up, and check the CLI's presence separately from the daemon's state.
if command -v docker >/dev/null 2>&1; then
  if systemctl is-active --quiet docker 2>/dev/null; then
    warn "docker daemon is RUNNING — containers:"
    sudo -n docker ps --format '        {{.Names}}  |  {{.Image}}  |  {{.Ports}}' 2>/dev/null \
      || info "        (need sudo to list; re-run with sudo cached)"
  else
    info "docker CLI installed but the daemon is NOT running"
    info "  not probing the socket -- doing so would socket-activate dockerd and restart containers"
  fi
else
  ok "docker not installed"
fi
for rt in podman containerd nerdctl; do
  command -v "$rt" >/dev/null 2>&1 && warn "$rt is installed — it may be publishing ports; check the listener list above"
done

say "Other listening services (anything Cryonav might disturb)"
if [ -z "$PORTCHECK_TOOL" ]; then
  info "(could not enumerate)"
else
  printf '%s\n' "$raw_listeners" | awk '{print "        "$4"  "$NF}' | sort -u | head -25
fi

say "Running units that look like applications"
systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null \
  | awk '{print $1}' \
  | grep -vE '^(systemd-|dbus|cron|ssh|rsyslog|networkd|resolved|polkit|udev|getty|user@|accounts-daemon|unattended|snapd|multipathd|irqbalance|qemu-guest-agent|chrony|ntp)' \
  | sed 's/^/        /' | head -25

say "Python toolchain"
if command -v python3 >/dev/null; then
  v=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
  ok "python3 $v"
  python3 -c 'import sys;raise SystemExit(0 if sys.version_info>=(3,9) else 1)' \
    && ok "  >= 3.9, meets Cryonav's floor" \
    || warn "  older than 3.9 — Cryonav needs 3.9+"
  python3 -m venv --help >/dev/null 2>&1 && ok "  venv module present" || warn "  python3-venv MISSING (apt install python3-venv)"
  python3 -m pip --version >/dev/null 2>&1 && ok "  pip present" || warn "  pip missing (apt install python3-pip)"
else
  warn "python3 not installed"
fi

say "Node (only needed if you build the frontend on this box)"
command -v node >/dev/null && ok "node $(node -v)" || info "node not installed — fine if you build locally and upload dist/"
command -v git  >/dev/null && ok "git $(git --version | awk '{print $3}')" || warn "git not installed"
command -v curl >/dev/null && ok "curl present" || warn "curl missing"
command -v rsync >/dev/null && ok "rsync present" || info "rsync missing (only needed for the automated deploy path)"

say "Firewall"
if command -v ufw >/dev/null && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
  warn "ufw is ACTIVE:"
  sudo ufw status numbered 2>/dev/null | sed 's/^/        /'
  info "  80/tcp and 443/tcp must be allowed for Let's Encrypt to issue a certificate"
elif command -v firewall-cmd >/dev/null && sudo firewall-cmd --state 2>/dev/null | grep -q running; then
  warn "firewalld is ACTIVE: $(sudo firewall-cmd --list-ports 2>/dev/null)"
elif command -v nft >/dev/null 2>&1 && sudo -n nft list ruleset 2>/dev/null | grep -qE '^\s*(chain|table)'; then
  warn "raw nftables rules are present — inspect them before assuming 80/443 are reachable:"
  sudo -n nft list ruleset 2>/dev/null | grep -E 'dport|policy' | head -12 | sed 's/^/        /'
elif command -v iptables >/dev/null 2>&1 && sudo -n iptables -S 2>/dev/null | grep -qvE '^-P (INPUT|FORWARD|OUTPUT) ACCEPT$'; then
  warn "raw iptables rules are present — inspect them before assuming 80/443 are reachable:"
  sudo -n iptables -S 2>/dev/null | grep -E 'dport|^-P' | head -12 | sed 's/^/        /'
else
  # Only ufw, firewalld, nftables and iptables were examined. Anything else -- or a denied
  # sudo -- is UNKNOWN, not "clear". Claiming "no firewall" from four negative checks is the
  # same false-confidence mistake as calling an unreadable port free.
  info "no ufw/firewalld/nftables/iptables rules detected by these checks"
  info "  this is NOT proof the host is unfiltered, and it says nothing about your provider"
  info "  cloud firewall: 80/tcp and 443/tcp must be open there for Lets Encrypt to issue TLS"
fi

say "Prior Cryonav traces"
for p in /opt/cryonav /etc/cryonav/env /etc/systemd/system/cryonav-api.service; do
  [ -e "$p" ] && warn "$p already exists — this VPS has seen a Cryonav deploy" || ok "$p absent (clean install)"
done
id cryonav >/dev/null 2>&1 && warn "user 'cryonav' already exists" || ok "user 'cryonav' absent"

say "Verdict"
echo "  Send this entire output back. The lines that decide the install path are:"
echo "    · who owns ports 80/443  (UNKNOWN is not the same as free — never install over it)"
echo "    · whether docker/nginx/apache is running"
echo "    · the python3 version"
echo "  Nothing was installed, started, stopped or changed by this script."
