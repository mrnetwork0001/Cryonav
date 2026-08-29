# Cryonav demo - narration script

Record voiceover against the segments in `demo/footage/` (regenerate with `npm run record`;
total runtime 2:28). Lines are timed to each segment's beats.

**Every figure below is checkable.** The sources are named in the margin notes, and the live
ones come from `https://cryonav.xyz/api/v1/facts`, which recomputes them per request. An
earlier draft of this script quoted a 21 °F saving, 180 °F asphalt and "dispatches emergency
response" - none of which the system produces or does. Re-verify before re-recording: the
contrast figures move with the weather.

---

## 01-landing - 0:00-0:20 (20.2 s)

> "During extreme heat events, navigation apps still optimize for distance - not for the
> asphalt under your feet, which on a Phoenix afternoon runs past 150 degrees.
> **Cryonav** routes pedestrians by the heat their body actually absorbs."
>
> *(problem cards)* "Two Phoenix locations, a kilometre apart. The weather report puts them
> within two tenths of a degree of each other - and gets the direction wrong. Measure the
> radiant load and they are more than twenty degrees apart."
>
> *(agents)* "Three agents - sensing, optimization, and an emergency sentinel that can
> overrule the optimizer and send it back to re-solve."
>
> *(live api)* "Everything here runs on live FortyGuard Temperature API data, refreshed
> daily, fused with five more measured layers - canopy, surface temperature, and the street
> network itself."

<sub>`/api/v1/facts`, Van Buren St × 7th Ave vs Virginia G. Piper Plaza at 15:00. **These two
figures move with the weather**, which is why the narration says "past 150" and "more than
twenty" rather than a decimal: on 2026-08-26 it was 159.2 °F surface and a 24.2 °F radiant gap,
on 2026-08-27 it was 153.5 °F and 22.8 °F. Both readings support both phrasings, and will keep
doing so while Phoenix is in an August afternoon - so the video does not go stale between
recording and judging. The air gap is −0.2 °F: the *shaded* site reads marginally hotter, which
is the point. Six layers: FortyGuard, Meta/WRI canopy, Landsat, ECOSTRESS, OpenStreetMap,
NIOSH/OSHA.</sub>

## 02-dashboard-raster - 0:20-0:41 (21.1 s)

> "This is the FortyGuard heat raster - 2,407 observed hundred-metre tiles over Phoenix. And
> this is Cryonav's exposure model on top: the radiant load a walker actually feels, street
> by real street."

<sub>2,407 tiles at 100 m: `data/calibration/phoenix_heatmap.json`, `tile_count`. That raster
is US-only, so Phoenix and San Jose carry it and the Gulf tiles model that layer - do not
claim it for Dubai.</sub>

## 03-routing - 0:41-1:04 (22.3 s)

> "Every route is solved twice on the real OpenStreetMap network - twenty-five thousand
> walkable nodes in Phoenix alone. The red path is what any navigator gives you. The cyan path
> more than doubles the shade, from twelve per cent to twenty-seven."
>
> *(the Sentinel engages)* "And for an elderly walker it does something a navigator never
> would: it routes them through a real cooling centre from the Maricopa Association of
> Governments' Heat Relief Network. Look at the cost - twenty-two minutes longer, and the
> total heat dose actually goes UP. Cryonav shows you that, because the thing it just fixed
> matters more: the longest stretch without relief drops from sixty-six minutes to under
> three. Continuous exposure is what puts people in hospital, not the average."

<sub>25,072 nodes / 34,387 edges: `data/streets/phoenix.json`. 27 active 2026 MAG sites:
`data/shelters/phoenix.json`. If you quote a saving, the reproducible figures from
`scripts/bench/corridor_sweep.py` on 2026-08-27 are **0.0-3.4 °F** for thermal routing alone
and up to **4.7 °F** once the Sentinel may insert a refuge - re-run it on the day you record.
Do not quote a single headline number as though it were universal: ten of the 36
corridor-profile combinations correctly return the direct route unchanged, and with a refuge
permitted some go deliberately negative on dose because breaking the longest unbroken
high-risk leg is worth more than average exposure.</sub>

## 04-sentinel-emergency - 1:04-1:51 (47.0 s)

> "Now the part that matters, and we cross to Abu Dhabi for it - a hundred and eleven degrees,
> eighty-four per cent of the tile in the extreme band. A delivery worker walks the route, and
> Cryonav streams their position, dwell time and movement to the Sentinel - the same endpoint a
> smart-city kiosk would call."
>
> *(escalations appear)* "Exposure climbs - advisory. Ceiling exceeded - divert to shelter."
>
> *(walker stops)* "Then they stop moving. Eleven minutes, motionless, in an extreme-heat
> zone."
>
> *(dispatch banner)* "The Sentinel alerts the walker's nominated emergency contact with
> their live position, their GPS accuracy, and the nearest air-conditioned refuge. This is a
> replay, so it deliberately sends nothing - the code refuses to page a real person from a
> demo. Switch it to live GPS and the same escalation fires a real push, measured at a hundred
> and sixteen milliseconds out of the server. That's the difference between a maps app and a
> safety system."

<sub>**This segment runs in ABU DHABI at 13:00, deliberately.** Dispatch needs the walker in
the EXTREME band, and on a cooler Phoenix day the Sentinel correctly does not escalate - the app
then prints "Sentinel did NOT escalate within the immobility window - safety gap", which is
honest behaviour and unusable footage. Subtler: Phoenix at 14:00 dispatches when the monitor
endpoint is probed at the corridor origin, yet the replay still only reaches "reroute", because
the walker collapses along the COOL route, which is by construction the shadier one. Abu Dhabi
at 13:00 walks the whole ladder - ok, advisory, reroute, dispatch, banner up at t=24s. Re-probe
on the day you record; override with CRYONAV_SENTINEL_CITY / CRYONAV_SENTINEL_HOUR.

**Do not say "that notification is real" over the replay.** TransitSim.tsx sends
`notify: false` on the replay path and `notify: true` only in live-GPS mode - the comment reads
"the replay must never fire a real push to a real contact". Narrating a real send over footage
that sends nothing is the same class of overclaim as "responders". 116 ms is the measured
server-side ntfy POST, not end-to-end delivery to a handset; say "out of the server".
Thresholds: 8 minutes, under 25 m of movement, air ≥110 °F or an extreme band
(`backend/agents.py`). The simulation holds 11 minutes (`IMMOBILE_SIM_MIN`). **Say "nominated
emergency contact", never "emergency services"** - no public API lets a civilian application
file an emergency call, and Twilio says so in writing. 116 ms is the measured ntfy delivery
from the deployed server.</sub>

## 05-mobile - 1:51-2:13 (22.6 s)

> "It ships responsive and kiosk-ready, and it can read the device's own GPS - estimating
> movement by median-of-thirds, because between tall buildings the naive method misses nine
> collapses in ten."

<sub>91.2 % missed at 40 m accuracy vs 0.0 %: `scripts/bench/displacement_montecarlo.mjs`,
20,000 runs, which imports the shipped estimator. **Do not say "offline-capable"** as though
the hardware ships - the Jetson edge tier is simulated, and the README says so.</sub>

## 06-docs - 2:13-2:28 (14.5 s)

> "And all of it is documented and auditable - every layer with its source, resolution and
> licence, every threshold with its citation, and seven hundred and ninety-three remaining
> assumptions declared and counted rather than hidden. Cryonav, on the FortyGuard Temperature
> API."

<sub>793: `/api/v1/facts`, `assumed_constants_remaining` - shelter fields flagged `ac_assumed`
or `indoor_temp_assumed` where OpenStreetMap carries no tag. It read 0 until an audit found
the counter was skipping them.</sub>

---

**Submission checklist:** trim/join segments (e.g. `ffmpeg -f concat`), record narration,
export ≤3 min. Keep the dispatch sequence intact - it is the demo's peak.

**Before re-recording:** the existing footage in `demo/footage/` predates the operations-console
redesign and the Cryonav wordmark, so it shows a UI that no longer exists. Re-record against
the deployed site with `CRYONAV_URL=https://cryonav.xyz npm run record`, which also proves the
demo is the real deployment rather than a laptop.
