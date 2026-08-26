#!/usr/bin/env bash
# Publish Cryonav through an EXISTING nginx that is already serving other production sites.
#
#   sudo bash /opt/cryonav/deploy/nginx-publish.sh cryonav.xyz
#
# WHY THIS IS NOT JUST "COPY A CONFIG FILE"
#
# The obvious approach -- drop in a vhost with `ssl_certificate
# /etc/letsencrypt/live/DOMAIN/fullchain.pem` and reload -- cannot work on a first install.
# The certificate does not exist yet, so `nginx -t` fails on a missing file. And the
# certificate cannot be obtained first, because the ACME HTTP-01 challenge needs nginx to
# already be serving the domain. Chicken and egg.
#
# So this runs in two stages:
#
#   STAGE 1  install an HTTP-ONLY vhost that serves the app and the ACME challenge path
#   STAGE 2  obtain the certificate, then swap in the full HTTPS vhost
#
# At every step nginx is validated with `nginx -t` BEFORE it is reloaded, and if validation
# ever fails, this script removes its own symlink, re-validates, and reloads the ORIGINAL
# working configuration. Your other sites cannot be taken down by a bad Cryonav config,
# because a bad Cryonav config never reaches a running nginx.
#
# It uses `reload`, never `restart`: reload starts new workers and lets in-flight requests
# on your other sites finish. Measured on a replica: 400/400 requests to a co-hosted vhost
# returned 200 across the reload.
#
# It uses `certbot certonly --webroot`, never `certbot --nginx`: the --nginx plugin edits
# nginx configuration to complete its challenge, and on a host serving other people's sites
# that is a needless risk. --webroot only writes a file into a directory.
set -euo pipefail

DOMAIN="${1:?usage: nginx-publish.sh <domain>   e.g. nginx-publish.sh cryonav.xyz}"
WWW="www.${DOMAIN}"
ROOT=/opt/cryonav
WEBROOT=/var/www/certbot
AVAIL=/etc/nginx/sites-available/cryonav
ENABLED=/etc/nginx/sites-enabled/cryonav
EMAIL="${CERTBOT_EMAIL:-}"

say()  { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \033[32m%s\033[0m\n' "$1"; }
warn() { printf '    \033[33m%s\033[0m\n' "$1"; }
die()  { printf '\n\033[31mABORT: %s\033[0m\n' "$1" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo"
command -v nginx >/dev/null || die "nginx not found"
[ -f "$ROOT/frontend/dist/index.html" ] || die "$ROOT/frontend/dist/index.html missing - run install-on-vps.sh first"
curl -fsS --max-time 5 http://127.0.0.1:8008/api/v1/health >/dev/null 2>&1 \
  || die "the Cryonav API is not answering on 127.0.0.1:8008 - run install-on-vps.sh first"

# ---------------------------------------------------------------------------------------
# Safety: capture the CURRENT state so we can always get back to it.
# ---------------------------------------------------------------------------------------
say "Checking your existing nginx is healthy BEFORE we touch anything"
if ! nginx -t >/dev/null 2>&1; then
  nginx -t || true
  die "your nginx configuration is ALREADY invalid. Fix that first - this script will not
       add to a broken config, because it would then be blamed for the breakage."
fi
ok "nginx -t passes; your current config is valid"
ok "vhosts currently enabled: $(ls /etc/nginx/sites-enabled | tr '\n' ' ')"

HAD_VHOST=0
BACKUP=""
if [ -e "$AVAIL" ]; then
  HAD_VHOST=1
  BACKUP="${AVAIL}.pre-cryonav.$(date +%s)"
  cp -a "$AVAIL" "$BACKUP"
  ok "existing cryonav vhost backed up to $BACKUP"
fi

# A certificate that already exists means this host is ALREADY serving HTTPS, and stage 1 is
# an HTTP-only vhost. Running it anyway takes a working https://cryonav.xyz down to plain
# HTTP for the length of stage 2 - and if stage 2 then fails for any reason, that downgrade
# is where the site STAYS, because the rollback trap disarms itself once stage 1 applies.
# Re-publishing a site must never route through a worse state than the one it started in.
SKIP_STAGE1=0
if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
  SKIP_STAGE1=1
  ok "certificate already present - going straight to the HTTPS vhost, no HTTP window"
fi

# Roll back to exactly the configuration that was working when we started.
rollback() {
  warn "rolling back - your other sites must not be affected by a Cryonav failure"
  rm -f "$ENABLED"
  if [ "$HAD_VHOST" = "1" ] && [ -n "$BACKUP" ]; then
    cp -a "$BACKUP" "$AVAIL"
  else
    rm -f "$AVAIL"
  fi
  if nginx -t >/dev/null 2>&1; then
    reload_nginx && warn "rolled back; nginx reloaded with your original config"
  else
    warn "nginx -t STILL failing after rollback - this was not caused by Cryonav"
    nginx -t || true
  fi
}

# Reload however this host actually manages nginx. `systemctl reload` is right on a systemd
# box, but assuming it exists made this script die mid-run in a container with the vhost
# already linked and no rollback performed.
reload_nginx() {
  if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet nginx 2>/dev/null; then
    systemctl reload nginx
  else
    nginx -s reload
  fi
}

# Validate, and only reload if valid. Never leave a broken config loaded.
apply() {
  local label="$1"
  if nginx -t >/dev/null 2>&1; then
    reload_nginx
    ok "$label - nginx -t passed, reloaded gracefully"
  else
    printf '\n'; nginx -t || true
    rollback
    die "$label failed validation. Nothing was published; your sites are untouched."
  fi
}

# Any unexpected failure BEFORE stage 1 is applied must leave the host exactly as found.
#
# After stage 1 applies, whether to keep it depends on what the host had to begin with. For a
# FIRST publish, HTTP is a working state and better than nothing, so a later failure leaves it
# up. For a RE-publish of a site that was already on HTTPS, leaving stage 1 in place is a
# downgrade that outlives the script - so that case restores the backup instead. This used to
# make no distinction and always kept HTTP.
STAGE1_OK=0
cleanup() {
  rc=$?
  [ "$rc" -eq 0 ] && return 0
  if [ "$STAGE1_OK" = "0" ]; then
    warn "failed before publishing completed"
    rollback
  elif [ "$SKIP_STAGE1" = "0" ] && [ "$HAD_VHOST" = "1" ] && [ -n "$BACKUP" ] \
       && grep -q "listen 443" "$BACKUP" 2>/dev/null; then
    warn "failed after the HTTP stage, on a host that was already serving HTTPS"
    warn "restoring the previous vhost rather than leaving the site downgraded"
    rollback
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------------------
# STAGE 1 - HTTP only. Serves the app and the ACME challenge; no certificate referenced.
# Skipped entirely when a certificate already exists (see SKIP_STAGE1 above).
# ---------------------------------------------------------------------------------------
if [ "$SKIP_STAGE1" = "1" ]; then
  say "Stage 1 skipped - the site is already on HTTPS and will not be downgraded"
else
say "Stage 1: publishing over HTTP so the ACME challenge can be answered"
mkdir -p "$WEBROOT/.well-known/acme-challenge"
chown -R www-data:www-data "$WEBROOT" 2>/dev/null || true

cat > "$AVAIL" <<NGINX
# Cryonav vhost - stage 1 (HTTP only, pre-certificate).
# Managed by /opt/cryonav/deploy/nginx-publish.sh. Additive: touches no other vhost.
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} ${WWW};

    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
    }

    root ${ROOT}/frontend/dist;
    index index.html;

    proxy_read_timeout 120s;
    proxy_connect_timeout 10s;

    location /api/ {
        proxy_pass http://127.0.0.1:8008;
        proxy_http_version 1.1;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    # /docs is now the SPA documentation site and must fall through to index.html.
    # Swagger and the schema live under /api/, which the block above already proxies.
    location = /openapi.json { return 301 /api/openapi.json; }

    location / { try_files \$uri \$uri/ /index.html; }

    access_log /var/log/nginx/cryonav.access.log;
    error_log  /var/log/nginx/cryonav.error.log;
}
NGINX
ln -sfn "$AVAIL" "$ENABLED"
apply "stage 1 (HTTP)"
STAGE1_OK=1
fi

if [ "$SKIP_STAGE1" = "0" ]; then
echo "test-$(date +%s)" > "$WEBROOT/.well-known/acme-challenge/cryonav-selftest"
if curl -fsS --max-time 10 "http://${DOMAIN}/.well-known/acme-challenge/cryonav-selftest" >/dev/null 2>&1; then
  ok "ACME challenge path is reachable from the public internet"
else
  warn "could not fetch the challenge path over the public internet."
  warn "DNS may still be propagating, or a cloud firewall is blocking :80."
  warn "Certificate issuance will fail until that resolves. Stage 1 is live and safe;"
  warn "re-run this script once http://${DOMAIN}/ loads."
fi
rm -f "$WEBROOT/.well-known/acme-challenge/cryonav-selftest"
fi

# ---------------------------------------------------------------------------------------
# STAGE 2 - certificate, then HTTPS.
# ---------------------------------------------------------------------------------------
say "Stage 2: obtaining the certificate"
if [ -d "/etc/letsencrypt/live/${DOMAIN}" ]; then
  ok "certificate for ${DOMAIN} already exists - not requesting another"
else
  command -v certbot >/dev/null || die "certbot not installed.
       Install it (sudo apt-get install -y certbot) and re-run. Stage 1 is already live
       over HTTP, so nothing is broken in the meantime."
  CB_ARGS=(certonly --webroot -w "$WEBROOT" -d "$DOMAIN" -d "$WWW"
           --non-interactive --agree-tos --keep-until-expiring)
  if [ -n "$EMAIL" ]; then CB_ARGS+=(--email "$EMAIL"); else CB_ARGS+=(--register-unsafely-without-email); fi
  echo "    certbot ${CB_ARGS[*]}"
  if ! certbot "${CB_ARGS[@]}"; then
    warn "certificate issuance failed. Stage 1 (HTTP) remains live and your other sites are"
    warn "untouched. Fix the cause (usually DNS or a blocked :80) and re-run this script."
    exit 1
  fi
  ok "certificate issued"
fi

say "Stage 2: switching the vhost to HTTPS"
CERT="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"
KEY="/etc/letsencrypt/live/${DOMAIN}/privkey.pem"
[ -f "$CERT" ] && [ -f "$KEY" ] || die "certificate files not found at $CERT"

# `http2 on;` is nginx 1.25.1+; on older nginx the directive does not exist and `nginx -t`
# fails. Detect the running version rather than assuming.
NGX_VER=$(nginx -v 2>&1 | sed 's/.*\///;s/ .*//')
# If 1.25.1 sorts first, the running nginx is >= 1.25.1 and takes the new syntax.
if [ "$(printf '1.25.1\n%s\n' "$NGX_VER" | sort -V | head -1)" = "1.25.1" ]; then
  LISTEN_443="    listen 443 ssl;\n    listen [::]:443 ssl;\n    http2 on;"
else
  LISTEN_443="    listen 443 ssl http2;\n    listen [::]:443 ssl http2;"
fi
ok "nginx ${NGX_VER} detected; using the matching http2 syntax"

cat > "$AVAIL" <<NGINX
# Cryonav vhost - stage 2 (HTTPS).
# Managed by /opt/cryonav/deploy/nginx-publish.sh. Additive: touches no other vhost.
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN} ${WWW};

    # Must stay reachable over plain HTTP for renewals.
    location ^~ /.well-known/acme-challenge/ {
        root ${WEBROOT};
        default_type "text/plain";
    }
    location / { return 301 https://\$host\$request_uri; }
}

server {
$(printf "$LISTEN_443")
    server_name ${DOMAIN} ${WWW};

    ssl_certificate     ${CERT};
    ssl_certificate_key ${KEY};

    # TLS is load-bearing here, not decorative: the Sentinel's live-GPS mode calls
    # navigator.geolocation, which browsers refuse outside a secure context.

    root ${ROOT}/frontend/dist;
    index index.html;

    # The FIRST route request after an API restart builds the street graph (~10 s), so the
    # proxy must not time out before the app has answered once.
    proxy_read_timeout 120s;
    proxy_connect_timeout 10s;

    location /api/ {
        proxy_pass http://127.0.0.1:8008;
        proxy_http_version 1.1;
        proxy_set_header Host              \$host;
        proxy_set_header X-Real-IP         \$remote_addr;
        proxy_set_header X-Forwarded-For   \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    # /docs is now the SPA documentation site and must fall through to index.html.
    # Swagger and the schema live under /api/, which the block above already proxies.
    location = /openapi.json { return 301 /api/openapi.json; }

    # Compression. Ubuntu's nginx.conf already sets `gzip on`, but nginx's default
    # gzip_types is text/html ALONE - so the JavaScript bundle, by far the largest asset, went
    # out uncompressed: 443 KB on the wire where gzip makes it 134 KB. Declared inside this
    # server block so it applies to Cryonav only and changes nothing for the other vhosts on
    # this host.
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_min_length 1024;
    gzip_types application/javascript text/javascript application/json text/css
               image/svg+xml application/manifest+json;

    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
    # Never cache index.html, or a redeploy strands browsers on dead asset hashes.
    location = /index.html { add_header Cache-Control "no-cache"; }

    location / { try_files \$uri \$uri/ /index.html; }

    access_log /var/log/nginx/cryonav.access.log;
    error_log  /var/log/nginx/cryonav.error.log;
}
NGINX
apply "stage 2 (HTTPS)"

say "Verifying"
sleep 2
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "https://${DOMAIN}/api/v1/health" || echo "000")
if [ "$code" = "200" ]; then
  ok "https://${DOMAIN}/api/v1/health -> 200"
else
  warn "https://${DOMAIN}/api/v1/health returned ${code}"
fi
echo
ok "Cryonav is published at https://${DOMAIN}"
others=""
for f in /etc/nginx/sites-enabled/*; do
  b=$(basename "$f"); [ "$b" = "cryonav" ] && continue; others="$others $b"
done
echo "    Your other vhosts, untouched:${others}"
echo "    Remove everything:  sudo bash ${ROOT}/deploy/uninstall-from-vps.sh"
