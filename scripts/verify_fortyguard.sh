#!/usr/bin/env bash
# Probe the real FortyGuard Temperature API and report exactly what is confirmed.
# Safe to run without a key: it reports what it can reach and what it cannot.
#   FORTYGUARD_API_KEY=xxx ./scripts/verify_fortyguard.sh
set -uo pipefail
BASE="${FORTYGUARD_BASE_URL:-https://api.fortyguard.com}"
KEY="${FORTYGUARD_API_KEY:-}"
H_CT='content-type: application/json'

say() { printf '\n\033[1m%s\033[0m\n' "$1"; }
probe() { # method path [data]
  local m="$1"
  local p="$2"
  local d="${3:-}"
  local args
  args=(-s --max-time 15 -X "$m" -H "$H_CT" -w '\n  HTTP %{http_code}')
  [[ -n "$KEY" ]] && args+=(-H "api-key: $KEY")
  [[ -n "$d" ]] && args+=(-d "$d")
  printf '  %-6s %-26s ' "$m" "$p"
  curl "${args[@]}" "$BASE$p" 2>&1 | tr -d '\n' | cut -c1-260; echo
}

say "FortyGuard API reachability  ($BASE)"
[[ -n "$KEY" ]] && echo "  api-key: present (${#KEY} chars)" || echo "  api-key: NOT SET -- expect 401s below"

say "Unauthenticated health check"
probe GET /health

say "Auth scheme (proves the header name)"
printf '  no header                        '
curl -s --max-time 15 -X POST -H "$H_CT" -d '{}' "$BASE/v1/heat_intelligence" 2>&1 | cut -c1-200; echo
printf '  api-key: bogus                   '
curl -s --max-time 15 -X POST -H "$H_CT" -H 'api-key: bogus' -d '{}' "$BASE/v1/heat_intelligence" 2>&1 | cut -c1-200; echo
printf '  Authorization: Bearer bogus      '
curl -s --max-time 15 -X POST -H "$H_CT" -H 'Authorization: Bearer bogus' -d '{}' "$BASE/v1/heat_intelligence" 2>&1 | cut -c1-200; echo
echo "  -> 'Invalid or unknown API key' means the header NAME is right; 'Missing required' means it is not."

say "Documented endpoints (paths recovered from the docs bundle)"
for p in /v1/status/ /v1/env_params /v1/heat_intelligence /v1/heatmap /v1/satellite /v1/streetview; do
  probe GET "$p"
done

say "Phoenix probe against /v1/heat_intelligence (Van Buren x 7th Ave -- our hottest fixture)"
probe POST /v1/heat_intelligence '{"locations":[{"latitude":33.4520,"longitude":-112.0825}],"units":"imperial"}'
probe POST /v1/heat_intelligence '{"lat":33.4520,"lon":-112.0825}'
probe POST /v1/env_params        '{"lat":33.4520,"lon":-112.0825}'

say "Next step"
echo "  Copy any successful response body into backend/fortyguard_service.py::_reading_from_live"
echo "  so the real field names replace the current best-guess fallback chain."
