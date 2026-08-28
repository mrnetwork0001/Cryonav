#!/usr/bin/env python3
"""Sweep every demo corridor x profile and report the range of savings Cryonav achieves.

WHY THIS EXISTS. The README quoted a results table - "thermal load reduction 0-6.7 F" and four
other ranges - that no committed script produced. It was measured once by hand, written down,
and dated. Every other figure the project publishes is computed at request time precisely
because written-down figures go stale, and this table was the last one that did not follow its
own rule. Three days after it was written the calibration had moved twice.

Run it against the deployed API (default) or a local one:

    python3 scripts/bench/corridor_sweep.py
    python3 scripts/bench/corridor_sweep.py --base http://127.0.0.1:8008 --hour 15

It prints a markdown table ready to paste, plus the per-combination detail behind it, so the
range is auditable rather than asserted. Savings are reported as the cool route measured
against the standard route on the SAME request - not against a remembered baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

# The five metrics the README quotes, mapped to the comparison fields that produce them.
METRICS = [
    ("Thermal load reduction", "thermal_load_reduction_f", "°F"),
    ("Heat-stress reduction", "heat_stress_reduction_pct", "%"),
    ("Heat-strain dose reduction", "thermal_dose_reduction_pct", "%"),
    ("Shade coverage gained", "shade_coverage_gain_pct", "%"),
    ("Added walking time", "added_minutes", "min"),
]


def post(base: str, path: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return json.load(fh)


def get(base: str, path: str, timeout: float) -> dict:
    with urllib.request.urlopen(base.rstrip("/") + path, timeout=timeout) as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="https://cryonav.xyz/api/v1")
    ap.add_argument("--hour", type=float, default=15.0)
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument(
        "--no-shelter",
        action="store_true",
        help="disable the Sentinel's shelter reroute; isolates pure thermal routing",
    )
    args = ap.parse_args()

    cities = get(args.base, "/cities", args.timeout)
    cities = cities.get("cities", cities)
    profiles = [p["id"] for p in get(args.base, "/meta", args.timeout)["profiles"]]

    rows: list[dict] = []
    for city in cities:
        for preset in city.get("presets", []):
            for profile in profiles:
                body = {
                    "origin": {
                        "lat": preset["origin"]["coords"][0],
                        "lon": preset["origin"]["coords"][1],
                    },
                    "destination": {
                        "lat": preset["destination"]["coords"][0],
                        "lon": preset["destination"]["coords"][1],
                    },
                    "city_id": city["id"],
                    "hour": args.hour,
                    "profile": profile,
                    "allow_shelter_reroute": not args.no_shelter,
                }
                try:
                    d = post(args.base, "/navigate/cool-route", body, args.timeout)
                except (urllib.error.URLError, TimeoutError) as exc:
                    print(f"  ! {city['id']}/{preset['id']}/{profile}: {exc}", file=sys.stderr)
                    continue
                c = d["comparison"]
                identical = d["routes"]["standard"]["geometry"] == d["routes"]["cool"]["geometry"]
                rows.append(
                    {
                        "city": city["id"],
                        "corridor": preset["label"],
                        "profile": profile,
                        "identical": identical,
                        **{key: c.get(key) for _, key, _ in METRICS},
                    }
                )
                print(".", end="", flush=True, file=sys.stderr)
    print(file=sys.stderr)

    if not rows:
        print("no results - is the API reachable?", file=sys.stderr)
        return 1

    feed = get(args.base, "/health", args.timeout)
    dates = sorted({v.get("date", "")[:10] for v in (feed.get("calibration") or {}).values() if v})

    print()
    print(f"Measured across {len(rows)} combinations "
          f"({len(rows)//len(profiles)} corridors x {len(profiles)} profiles), "
          f"{args.hour:g}:00 local, calibration {', '.join(d for d in dates if d) or 'unknown'}"
          + (", shelter reroute OFF" if args.no_shelter else "") + ".")
    print()
    print("| Metric | Range across demo corridors |")
    print("|---|---|")
    for label, key, unit in METRICS:
        vals = [r[key] for r in rows if r.get(key) is not None]
        if not vals:
            continue
        lo, hi = min(vals), max(vals)
        if unit == "min":
            print(f"| {label} | **{lo:+.1f} to {hi:+.1f} {unit}** |")
        else:
            print(f"| {label} | **{lo:.1f} – {hi:.1f} {unit}** |")

    same = sum(1 for r in rows if r["identical"])
    print()
    print(f"{same} of {len(rows)} combinations return the direct route unchanged - on those the "
          f"direct path already is the coolest admissible one, and Cryonav reports zero rather "
          f"than manufacturing a detour.")

    print()
    print("<details><summary>Per-combination detail</summary>")
    print()
    print("| City | Corridor | Profile | Load °F | Stress % | Dose % | Shade % | Time min |")
    print("|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda x: -(x["thermal_load_reduction_f"] or 0)):
        print(f"| {r['city']} | {r['corridor']} | {r['profile']} | "
              f"{r['thermal_load_reduction_f']:.1f} | {r['heat_stress_reduction_pct']:.1f} | "
              f"{r['thermal_dose_reduction_pct']:.1f} | {r['shade_coverage_gain_pct']:.1f} | "
              f"{r['added_minutes']:+.1f} |")
    print()
    print("</details>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
