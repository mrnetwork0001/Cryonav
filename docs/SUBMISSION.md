# Cryonav - submission pack

Copy-paste material for the FortyGuard Global AI Hackathon '26 entry form. Every figure here
is either computed live or reproducible by a named command; re-check the drifting ones on the
day you submit with `curl -s https://cryonav.xyz/api/v1/facts` and
`python3 scripts/bench/corridor_sweep.py`.

| Field | Value |
|---|---|
| Project | **Cryonav** |
| Track | **Track 01 - Resilient Cities & Infrastructure** |
| Theme | Building the World's Temperature AI |
| Entry | Solo |
| Live demo | https://cryonav.xyz |
| Dashboard | https://cryonav.xyz/app |
| Documentation | https://cryonav.xyz/docs |
| API reference | https://cryonav.xyz/api/docs |
| Source | https://github.com/mrnetwork0001/Cryonav |
| Licence | MIT (code); data sources keep their own - see LICENSE |

---

## One-liner (≤ 120 chars)

> Cryonav routes pedestrians by the heat their body absorbs, not the distance they walk.

## Short pitch (≈ 50 words)

> Navigation apps optimise metres and minutes. In an extreme-heat city that hands you the
> hotter route. Cryonav fuses the FortyGuard Temperature API's observed 2 m field with measured
> canopy, satellite surface temperature and the real pedestrian network, then routes around the
> heat - with an Emergency Sentinel that breaks unsafe exposure at real cooling shelters.

## Description (≈ 250 words)

> **The problem.** At 15:00 in downtown Phoenix, two locations a kilometre apart sit more than
> 20 °F apart in the heat a body actually absorbs - while the weather report puts them within a
> fifth of a degree of each other, and sometimes gets the direction wrong. The 2 m air layer is
> well mixed and cannot separate a bare asphalt arterial from a shaded plaza. The radiant load
> streaming off the surface can, and that is where heat illness comes from.
>
> **What Cryonav does.** Given an origin, destination and user profile it returns two routes:
> the standard shortest path any navigator gives you, and a cool route that minimises thermal
> dose - minutes in the sun weighted by how punishing that sun is - inside a per-profile detour
> budget. Three agents cooperate over a shared blackboard, and the third can send the second
> back to re-solve: an Emergency Sentinel that checks the longest *unbroken* high-risk leg
> against NIOSH and OSHA exposure ceilings, trials real air-conditioned shelters as mandatory
> waypoints, and escalates advisory → reroute → dispatch. On immobility in extreme heat it
> sends a real push notification to a nominated emergency contact.
>
> **Where the numbers come from.** Six measured layers over four cities: the FortyGuard
> Temperature API for observed ambient, Meta/WRI canopy height at 1.19 m, Landsat and NASA
> ECOSTRESS surface temperature, OpenStreetMap for the walking network and urban form, and
> NIOSH/OSHA for the safety thresholds. Nothing is hand-authored. Where a value is still
> assumed it is flagged and counted - `/api/v1/facts` reports the running total rather than
> claiming zero.

## Why it fits Track 01

Heat is the deadliest climate hazard in most of these cities and it is unevenly distributed at
street scale - which is precisely the scale municipal infrastructure operates at. Cryonav turns
a temperature API into an operational tool for the people who cannot choose when they go
outside: outdoor workers, transit riders, the elderly. It routes on the real pedestrian network,
sends people to the city's own official cooling shelters (Phoenix uses the Maricopa Association
of Governments Heat Relief Network feed), and exposes the same solve through an edge endpoint
sized for a smart-city kiosk on a metered uplink.

## How the FortyGuard Temperature API is used

- `POST /v1/env_params` is the ambient source for all four cities: 24 hourly values across 15
  parameters, authenticated with the `api-key` header, collected asynchronously via
  `GET /v1/status/{activity_id}`. Pulled daily by a systemd timer into `data/calibration/`, so
  public traffic never burns quota; `prefer_live=true` calls it in-request.
- `POST /v1/heatmap` supplies the observed spatial 2 m air field for the two US tiles
  (2,407 cells over Phoenix, 1,920 over San Jose). Its coverage is US-only, so the Gulf tiles
  model that one layer and the response declares which per tile.
- The API has no dry-bulb series, so Cryonav inverts wet-bulb plus RH through a conserved daily
  dewpoint rather than misusing `apparent_temperature_celsius`, which already carries the
  humidity term.

## Verify any claim in one command

```bash
curl -s https://cryonav.xyz/api/v1/facts   | python3 -m json.tool   # every self-describing figure
curl -s https://cryonav.xyz/api/v1/meta    | python3 -m json.tool   # thresholds with citations
python3 scripts/bench/corridor_sweep.py                             # the savings table, live
cd backend && .venv/bin/pytest -q                                   # the test suite
```

## Known limitations, stated up front

The brief asked for a 35-50 % exposure reduction. Cryonav does not reach that and does not
round up to it. The README's "Honest limitations" section lists what is still assumed (793
shelter fields, counted not hidden), which layer is US-only, why live upstream calls are off by
default, and that the Jetson edge tier is simulated. The demo opens on a corridor that
demonstrates the routing; where a corridor's direct path is already the coolest one, the
interface says so rather than showing a phantom alternative.
