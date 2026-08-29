# Cryonav - voiceover sheet

**This is the read-aloud script.** Everything here is spoken. Nothing is a note.
For the evidence behind each figure, see [SCRIPT.md](SCRIPT.md) - do not read that one aloud;
its margin notes are verification, not narration.

Video: `~/Desktop/cryonav-demo-master.mp4`, 2:28.
Written to ~145 words per minute, which is a relaxed speaking pace. If you naturally run fast,
you will have room; if you run slow, drop the bracketed sentences first - they are the ones
the argument survives without.

---

### 0:00 - 0:20 · landing

Navigation apps optimise distance. On a Phoenix afternoon, that walks you across asphalt
past a hundred and fifty degrees.

Cryonav routes by the heat your body absorbs.

Two locations, a kilometre apart. The weather report puts them a fifth of a degree apart.
Measure radiant load, and it is more than twenty.

---

### 0:20 - 0:41 · the data

This is the FortyGuard heat raster - two thousand four hundred observed hundred-metre tiles
over Phoenix.

And this is Cryonav's exposure model on top: the radiant load a walker actually feels, street
by real street, on six measured layers.

[Canopy at one metre. Satellite surface temperature. The real pedestrian network.]

---

### 0:41 - 1:04 · routing

Every route is solved twice, on the real OpenStreetMap network.

Red is what any navigator gives you. Cyan more than doubles the shade.

For an elderly walker, the Sentinel adds a real cooling centre. It costs twenty-two minutes.
Cryonav shows you that - because the longest stretch without relief drops from sixty-six
minutes to three.

Continuous exposure is what hospitalises people. Not the average.

---

### 1:04 - 1:51 · the Sentinel

Now the part that matters. We cross to Abu Dhabi - a hundred and eleven degrees, eighty-four
per cent of the tile in the extreme band.

A delivery worker walks the route. Cryonav streams their position, dwell time and movement to
the Sentinel - the same endpoint a smart-city kiosk would call.

Exposure climbs. Advisory.

Ceiling exceeded. Divert to shelter.

Then they stop moving. Eleven minutes, motionless, in extreme heat.

The Sentinel alerts their nominated emergency contact - live position, GPS accuracy, nearest
refuge.

This is a replay, so it sends nothing. The code refuses to page a real person from a demo.
Switch to live GPS and the same escalation fires a real push - a hundred and sixteen
milliseconds out of the server.

That is the difference between a maps app and a safety system.

---

### 1:51 - 2:13 · mobile

It ships responsive and kiosk-ready.

It reads the device's own GPS, and estimates movement by median-of-thirds - because between
tall buildings, the naive method misses nine collapses in ten.

[The people who need this cannot choose when they go outside.]

---

### 2:13 - 2:28 · docs

All of it is documented and auditable. Every layer with its source and licence. Every
threshold with its citation.

And seven hundred and ninety-three remaining assumptions, declared and counted - not hidden.

Cryonav. On the FortyGuard Temperature API.

---

## Three things never to say

1. **"emergency services" or "responders."** It alerts a *nominated emergency contact*. No
   public API lets a civilian app file an emergency call.
2. **"that notification is real"** over the replay. The replay sends nothing, deliberately.
3. **"offline-capable"** as though the hardware ships. The Jetson tier is simulated.
