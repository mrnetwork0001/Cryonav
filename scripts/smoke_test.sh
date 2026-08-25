#!/usr/bin/env bash
# End-to-end check against a running Cryonav backend. Exits non-zero on the first failure.
set -uo pipefail
API="${CRYONAV_API:-http://localhost:8008}/api/v1"
PY="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backend/.venv/bin/python"
pass=0; fail=0

check() { # name, curl-args...
  local name="$1"; shift
  local body; body="$(curl -sS --max-time 25 "$@" 2>&1)"
  if [[ $? -ne 0 || -z "$body" ]]; then
    printf '  \033[31mFAIL\033[0m %s (no response)\n' "$name"; fail=$((fail+1)); return
  fi
  local out; out="$($PY -c "$SCRIPT" <<<"$body" 2>&1)"
  if [[ $? -eq 0 ]]; then
    printf '  \033[32mPASS\033[0m %-34s %s\n' "$name" "$out"; pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m %-34s %s\n' "$name" "${out##*$'\n'}"; fail=$((fail+1))
  fi
}

echo "Cryonav smoke test -> $API"

SCRIPT='import json,sys;d=json.load(sys.stdin);assert d["status"]=="ok";print(d["fortyguard"]["mode"],"|",len(d["cities"]),"cities")'
check "health" "$API/health"

SCRIPT='import json,sys;d=json.load(sys.stdin);assert len(d["profiles"])==3 and len(d["agents"])==3;print(len(d["risk_levels"]),"risk bands")'
check "meta" "$API/meta"

SCRIPT='import json,sys;d=json.load(sys.stdin);assert d["count"]==3;print(", ".join(c["id"] for c in d["cities"]))'
check "cities" "$API/cities"

SCRIPT='import json,sys;d=json.load(sys.stdin);s=d["stats"];assert len(d["cells"])==24*24;assert s["max_exposure_f"]-s["min_exposure_f"]>8;print("%s-%sF over %s mi2" % (s["min_exposure_f"], s["max_exposure_f"], d["tile_area_mi2"]))'
check "thermal grid" "$API/cities/phoenix/grid?hour=15&resolution=24"

SCRIPT='import json,sys;d=json.load(sys.stdin);assert d["count"]==2;assert d["sensing"]["elevation_m"]==2.0;print(d["feed"]["source"],d["feed"]["status_code"],"| peak",d["summary"]["peak_risk_level"])'
check "heat-intelligence" -X POST "$API/fortyguard/heat-intelligence" -H 'content-type: application/json' \
  -d '{"locations":[{"lat":33.4520,"lon":-112.0825},{"lat":33.4560,"lon":-112.0740}],"city_id":"phoenix","hour":15}'

SCRIPT='import json,sys
d=json.load(sys.stdin);c=d["comparison"];sr=d["shelter_reroute"]
# A mandated shelter stop may trade mean exposure for a shorter unbroken high-risk leg,
# so non-negative savings are only guaranteed when the Sentinel did not rewrite the route.
if sr.get("applied"):
    assert sr["longest_leg_min_after"] < sr["longest_leg_min_before"], "shelter stop did not shorten exposure leg"
else:
    assert c["thermal_load_reduction_f"]>=0, "cool route hotter than direct"
    assert c["thermal_dose_reduction_pct"]>=0, "cool route raised heat-strain dose"
assert len({s["agent"] for s in d["agent_trace"]})==3, "not all agents ran"
assert d["safety"].get("longest_high_risk_leg_min") is not None
extra = " (shelter stop: leg %s->%s min)" % (sr.get("longest_leg_min_before"), sr.get("longest_leg_min_after")) if sr.get("applied") else ""
print("-%sF load, -%s%% stress, +%s min%s" % (c["thermal_load_reduction_f"], c["heat_stress_reduction_pct"], c["added_minutes"], extra))'
check "cool-route (3 agents)" -X POST "$API/navigate/cool-route" -H 'content-type: application/json' \
  -d '{"origin":{"lat":33.4485,"lon":-112.0962},"destination":{"lat":33.4576,"lon":-112.0705},"city_id":"phoenix","hour":15,"profile":"delivery_worker"}'

SCRIPT='import json,sys;d=json.load(sys.stdin);assert d["shelters"];print(d["shelters"][0]["name"], "(%s m)" % d["shelters"][0]["distance_m"])'
check "shelters/nearby" "$API/shelters/nearby?city_id=phoenix&lat=33.4520&lon=-112.0740&limit=3&require_ac=true"

SCRIPT='import json,sys;d=json.load(sys.stdin);e=d["edge"];assert e["payload_bytes"]<8192;assert "agent_trace" not in d;print("%s B, %s ms" % (e["payload_bytes"], e["inference_ms"]))'
check "edge/jetson-kiosk" -X POST "$API/edge/jetson-kiosk" -H 'content-type: application/json' \
  -d '{"origin":{"lat":33.4485,"lon":-112.0962},"destination":{"lat":33.4576,"lon":-112.0705},"city_id":"phoenix","hour":15,"max_polyline_points":16}'

SCRIPT='import json,sys
d=json.load(sys.stdin);n=d["notification"]
assert d["status"]=="dispatch"
# notify=false below, so the only correct answer is "nothing was sent, and here is why".
assert n is not None and n["sent"] is False and n["reason"]
print("dispatch | notification:", n["reason"][:48])'
check "sentinel immobility alert" -X POST "$API/sentinel/monitor" -H 'content-type: application/json' \
  -d '{"position":{"lat":33.4520,"lon":-112.0825},"city_id":"phoenix","hour":15,"dwell_minutes":25,"moved_m":3,"profile":"delivery_worker","accuracy_m":12,"notify":false}'

echo
echo "  $pass passed, $fail failed"
[[ $fail -eq 0 ]]
