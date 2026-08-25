# Cryonav demo - narration script

Record voiceover against the segments in `demo/footage/` (regenerate anytime with
`npm run record`; total runtime ≈ 2:10). Lines are timed to each segment's beats.

---

## 01-landing (≈20 s)

> "During extreme heat events, navigation apps still optimize for distance - not for the
> 180-degree asphalt under your feet. **Cryonav** routes pedestrians by the heat their body
> actually absorbs."
>
> *(problem cards)* "Two Phoenix streets, 500 meters apart: same weather report, a
> 21-degree difference in what a body absorbs."
>
> *(agents)* "Three agents - sensing, optimization, and an emergency sentinel that can
> overrule them both."
>
> *(live api)* "Everything here runs on live FortyGuard Temperature API data - verified
> against production, refreshed daily."

## 02-dashboard-raster (≈17 s)

> "This is the FortyGuard heat raster - 2,400 observed hundred-meter tiles over Phoenix.
> And this is Cryonav's exposure model on top: the radiant load a walker actually feels,
> street by real street."

## 03-routing (≈17 s)

> "Every route is solved twice on the real OpenStreetMap network. The red path is what any
> navigator gives you. The cyan path trades a few minutes for shade - and for a vulnerable
> walker, the Sentinel inserts a real cooling center from Maricopa County's official Heat
> Relief Network."

## 04-sentinel-emergency (≈45 s)

> "Now the part that matters. A delivery worker walks the route - Cryonav streams their
> position, dwell time, and movement to the Sentinel, the same endpoint a smart-city kiosk
> would call."
>
> *(escalations appear)* "Exposure climbs - advisory. Ceiling exceeded - divert to shelter."
>
> *(walker stops)* "Then they stop moving. Eleven minutes, motionless, in 114-degree heat."
>
> *(dispatch banner)* "The Sentinel detects immobility and dispatches emergency response
> with the walker's live position and the nearest cooling refuge. That's the difference
> between a maps app and a safety system."

## 05-mobile (≈12 s)

> "It ships responsive, kiosk-ready, and offline-capable - built for the people who can't
> choose when they go outside. Cryonav, on the FortyGuard Temperature API."

---

**Submission checklist:** trim/join segments (e.g. `ffmpeg -f concat`), record narration,
export ≤3 min. Keep the dispatch sequence intact - it is the demo's peak.
