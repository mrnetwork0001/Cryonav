#!/usr/bin/env python
"""Fetch a real 24 h ambient profile from the FortyGuard Temperature API and cache it.

    FORTYGUARD_API_KEY=... python scripts/calibrate.py [city ...] [--date YYYY-MM-DD]

Writes data/calibration/<city>.json, which the service loads on startup. Without it the stack
runs on the synthetic diurnal model; with it, ambient truth comes from FortyGuard and only the
urban-form microclimate structure is modelled locally.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Load .env without adding a dependency.
env_path = ROOT / ".env"
if env_path.is_file():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

from fortyguard_service import FortyGuardService, FortyGuardUpstreamError  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cities", nargs="*", help="city ids (default: all)")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today UTC)")
    args = ap.parse_args()

    svc = FortyGuardService()
    if not svc.live:
        print("FORTYGUARD_API_KEY is not set — nothing to calibrate.", file=sys.stderr)
        return 1

    targets = args.cities or svc.city_ids()
    failures = 0
    for city_id in targets:
        print(f"→ {city_id}: submitting env_params …", flush=True)
        try:
            cal = svc.calibrate_city(city_id, date=args.date)
        except (FortyGuardUpstreamError, KeyError) as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            failures += 1
            continue
        print(
            f"  {cal['air_temp_min_f']:.1f}–{cal['air_temp_max_f']:.1f} °F, "
            f"peak {cal['peak_hour']:.0f}:00, elevation {cal['elevation_m']} m, "
            f"tz {cal['timezone']}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
