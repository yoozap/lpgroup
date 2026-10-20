# Public Market — procedural reconstruction of a reference render

A street view rebuilt from a single photograph: the camera is solved from the
image, the building is generated procedurally in Blender, and the whole thing is
rendered live in the browser with **three.js on WebGPU**.

```
blender/     python that builds and exports the scene
web/         the sales page, and the render lab behind it
serve.py     tiny static server (no-cache, so edits show up immediately)
```

## Run it

```bash
python3 serve.py          # http://127.0.0.1:8777/
```

| | |
|---|---|
| `/` | **the sales page** - LP Group's landing page, the scene live in its hero |
| `/lab.html` | **the render lab** - the same scene with the HUD, the wipe and developer mode |

Both load the same `web/app.js`. Every rig in `tools/` drives the lab.

Needs a browser with WebGPU: Chrome/Edge 113+, or Safari 18+. It has to be
served over http — ES modules and `fetch` do not work from `file://`.

Rebuild the model after editing anything under `blender/`:

```bash
/Applications/Blender.app/Contents/MacOS/Blender -b -P blender/build.py
# add --render for a quick EEVEE check into blender/preview.png
# (--out <path> to render elsewhere, --noexport to skip the GLB)
```

## The camera

Everything is anchored to a camera solved from the reference photograph rather
than eyeballed. The numbers live in `blender/fit.py` and are repeated at the top
of `web/index.html`.

| | |
|---|---|
| frame | 2048 × 1920 |
| focal length | 1431 px → 25.15 mm on a 36 mm sensor |
| principal point | 1660 px from the top — the lens is shifted **up** by 700 px |
| eye height | 1.65 m |
| sun | 58° elevation, behind the camera and to the right |

How it was solved:

1. The roofline was traced by segmenting sky from not-sky, giving two straight
   vanishing lines: one along the street facade, one along the west gable.
2. Those two directions are perpendicular in plan, so
   `(x_u − cx)(x_v − cx) = −f²` ties the focal length to the horizon height.
3. The horizon was read off the parked cars: roof and wheel of the same car
   bracket eye height, which puts it at y = 1660.
4. A column of balcony slab edges gives exactly 60 px per storey, fixing the
   scale at a 3.0 m floor-to-floor.

That closes the system. Everything else — a 55.6 m long block, 18.0 m deep,
36.05 m to the parapet, 11.73 m bay unit, a 17.2 m forward wing to the east —
falls out of the fit and lands within a few pixels of the photograph.

A second pass re-measured every opening against gridded crops of the
photograph (the pixel-to-metre helper and the overlay harness live outside
the repo): the arris sits at u = 797, which moved the frame origin to
(-11.10, 70.32) at a bearing of 53.07°; loggia openings are 1.85 m, not 2.62,
with a 0.6 m jamb on the corner side; the white of a window is 1.12 × 1.24 m
from 1.0 m above the slab, so the hole in the wall is 1.33 × 1.45 m around
the dark frame, the first one hugging its loggia; the punched windows carry
their own `glass_blind` material, the same glazing with every blind down,
because the photograph shows one uniform white rectangle per window while the
mixed blind states of `glass_window` made them read as different heights.
The gable slots carry `glass_slot` (plain sky-reflecting glass over the
whole pane, no blind and no room, because with the gable rendered dark the
flat-window shader left only a short bright dash of each 2.4 m slot) in pale
`frame_light` frames with a thin dark mullion. They are glazed almost flush
(a 6 cm reveal): the dark 0.34 m band beside each pane in the photograph is
built as a flush dark panel, not a deep reveal, because a deep reveal looked
the same from the street but hid half of every pane as soon as the camera
rose above it in Orbit or Fly. The gable
slots are 1.05 m wide, ten
per column, with two shopfronts cut into the gable's foot. The wing's return
wall is a pale pier, one 4.7 m loggia, a pier, a slot window, two 2.5/2.05 m
two-light windows, a pier and a 2.15 m loggia at the corner; its roof is at
35.6 m and the street gallery has three bays. The podium front is not on the
street line at all: a west face in the gable plane, a chamfer out toward the
crossing, then one long face closing on the wing corner (`POD_FRONT` in
`lib_city.py`), fascia top 5.9 m, glazing head 4.2 m. Vehicles and people are
no longer built.

The lens shift is applied straight to the projection matrix
(`projectionMatrix.elements[9] += LENS_RISE`) rather than through
`setViewOffset`, because TRAA jitters the view offset every frame and would wipe
it out. Verticals stay vertical; the horizon sits 86% of the way down the frame.

## What is generated

`blender/lib_building.py` builds the two residential blocks bay by bay. The bay
rhythm is the one read off the photograph: a loggia on the corner, a pair of
windows, then alternating pairs of loggias and pairs of windows.

Depth is what stops a facade looking like a sticker, so every opening is built
in layers: reveal → sill → frame → sash → glass, each set back a little further
than the last. Loggias are real recesses 1.5 m deep with slab edges, side
cheeks, a soffit, a glazed door, a window and a baluster railing. The parapet
has a coping that oversails both ways, the podium has a plinth at the ground,
and every architectural shell carries a 12 mm hardened bevel so each arris
catches the sun.

`blender/lib_city.py` adds the retail podium with its roof terrace, the street,
the classical blocks that close the view left and right, and the planting.
### Trees

The **branches** are grown rather than drawn. Three rules do the work, and all
three are standard practice:

* **apical dominance** — a limb does not fork into equals, it carries on as a
  leader and sheds thinner laterals. Forking into equals is what gives
  procedural trees their tell-tale broccoli look.
* **the pipe model** (da Vinci's rule) — a limb's cross-section equals the sum
  of its children's, so a child's radius is the parent's times its share to the
  power 1/2.49. Taper falls out of it instead of being a fudge factor.
* **gravitropism** — thin limbs turn back toward the sky, so the crown ends in
  upswept tips rather than straight spokes.

Every **leaf** is a real blade rather than a rectangle. A flat quad reads as a
green chip; what makes foliage read as leaves is the pointed tip, the shoulder
about a third of the way up, and the fold along the midrib that leaves the two
halves at different angles, so one side catches the sun while the other does
not. All three come for the price of the rectangle they replace: four verts
whose quad is deliberately **non-planar**, so triangulating it along the
base-to-tip diagonal puts the crease exactly on the midrib. Proportions are
taken off the foreground branch in the photograph — a broad lime leaf about
four fifths as wide as it is long — and the blade droops under its own weight.

Two things then sell it, and neither is the green:

* **a per-leaf tint, baked as a vertex colour.** Sun leaves lighter and
  yellower, shade leaves darker and bluer, by height and by distance out from
  the crown axis. A noise in world space cannot do this — it varies over
  centimetres, so neighbouring leaves come out the same shade and the canopy
  reads as one painted surface.
* **a different material underneath.** The abaxial face is paler, greyer and
  matt where the top has a waxy cuticle. Half the leaves in any canopy show you
  their backs, so that difference is most of what stops foliage reading as
  green card. The blades are wound so the geometric front face is the one
  turned to the sun, and `frontFacing` keys off it.

No alpha texture anywhere.

**What did not work.** Leaves really grow on shoots, in a golden-angle spiral,
not in a cloud around a twig, and that was tried: shoots off every tip, leaves
at 137.5° along each, blades turned to the light. The theory is right and it
looked wrong — at the leaf size geometry foliage has to use, a few hundred
leaves cannot describe a shoot and a crown at the same time, and the shoots
came out as spiky rosettes on bare branches. The cloud is the honest
compromise; density is what reads at 20 m. The real fix is the industry one,
a leaf *cluster* card with an alpha texture, which this project has so far
chosen not to use.

The roof terrace is planted the way the photograph shows it: slim ornamental
trees from the same kit standing in the planters, with a clipped hedge filling
them. Measured against the storeys behind, their crowns sit about 4 m above the
parapet, which is where these land.

Repeated parts are linked duplicates, so the GLB stores one mesh and many nodes.
Draco brings it to ~4.9 MB, most of which is leaves.

## What is shaded in the browser

The GLB carries geometry and a material *name* per surface. Everything you see
is built in TSL in `web/materials.js`:

- **renders and concretes** — fractal noise for grain and blotching, a derived
  bump, plus weathering: splash dirt along the bottom of every wall and slow
  rain streaks down it.
- **glazing** — from the street you do not see through a window, you see the
  pale blind behind it with the sky laid over the glass. A light diffuse under a
  tight clearcoat gives exactly that for the price of an opaque material. The
  gable slots get their own dark glass because they have no blind behind them.
- **asphalt** — a scanned 4 m tile (PolyHaven *asphalt pit lane*) mapped off
  world XZ, so the merged road needs no UVs. Two tile sizes cross-fade against a
  slow noise to kill the repeat, and the scan is lifted and desaturated because
  a fresh pit lane is far darker than a worn city carriageway.
- **the west gable** — the one big flat surface you look straight at. It carries
  the *same* asphalt scan as its actual albedo (triplanar, 2.6 m tile, lifted
  and warmed to a light render) plus that scan's roughness and normal.
  Modulating a flat colour never read at 80 m; the texture has to **be** the
  surface. Slot windows are measured off the photograph: 1.12 × 2.40 m, a
  0.34 m dark-lined reveal, two panes and a central mullion.
- **balcony balustrades** — the PolyHaven *worn shutter* scan, stood on end so
  its ribs run vertically. The rib pitch is deliberately left incommensurate
  with the 89 mm picket pitch, so no two balusters take their tone from the
  same part of a rib and the run gets the uneven glint a real railing has.
  The scan's linear channel ratios are already 1 : 0.84 : 0.67, exactly those
  of the railings in the photograph, so only the level is lifted, not the hue.
  Kept dielectric: at a metal 0.35 the sky reflection washed them neutral.
- **foliage** — double sided, with a transmission term so leaves glow when the
  sun is behind them.

The sky is a Preetham model evaluated on the CPU into an equirectangular float
texture (`web/sky.js`), used both as the visible background and, through PMREM,
as the image-based light for every material. Cirrus is projected onto a flat
shell above the viewer, and a warm haze band hugs the horizon.

Scanned maps live in `web/tex/` and are projected triplanar, blended by the
surface normal, so neither the merged road nor the merged walls need UVs or
tangents. All four sets are CC0 from PolyHaven (*asphalt pit lane*, *concrete wall 008*,
*worn shutter*, *herringbone parquet*); the EXRs are converted to linear 8-bit
via Blender's pixel buffer, not its display pipeline, which would gamma-encode
a normal map. The flat's floor is the exception to the triplanar rule: it is
one horizontal slab, so the parquet samples its 3.4 m tile straight off the
flat's own axes and builds its tangent frame from them.
The balustrade ships only colour and height: that scan's roughness is all but
flat (0.67-0.76), so its level is a constant and the variation comes off the
height instead - paint wears thin on the rib crests, dirt sits in the valleys.

## Render pipeline

```
pre-pass  (packed normals + velocity + depth)
   └─ GTAO ──────────────► fed back into the scene pass as its ambient term
scene pass (MRT: colour + velocity)
   └─ TRAA ──► bloom ──► chromatic aberration ──► vignette + grain ──► AgX
```

GTAO is temporally noisy by design, which is why TRAA resolves it. Chromatic
aberration is kept to a little over a pixel at the frame edge; any more and it
reads as an effect rather than a lens.

Draw calls are kept low by batching after load, and the rule is **not** the
obvious one. Instancing was the first choice for anything repeated four or
more times; measured, that is the wrong way round. An instanced geometry is
one draw call, but it is also its own **pipeline** in each of the three passes
it appears in - pre-pass, beauty and shadow - and compiling pipelines is what
the boot spends its time on. Welding merges across *geometries*, not just
across copies, so a whole material becomes one draw and one pipeline.

So the rule is: **weld whatever can be welded, instance only what cannot.**
The weld strips every attribute but position and normal, so the set that
still wants instancing is exactly the set that carries texture coordinates -
the downloaded furniture. Everything procedural, which is the whole city,
welds.

Against the old count rule, over four interleaved rounds:

| | four-or-more rule | weld-first rule |
|---|---|---|
| boot | 2097 ms | **1662 ms** |
| a drawn frame | 53.5 ms | **44.0 ms** |
| pipelines | 342 | **233** |
| draw calls, Scene 1 | 166 | **94** |
| draw calls, Scene 2 | 238 | **176** |
| JS heap | 469 MB | **403 MB** |
| geometry in VRAM | 49.7 MB | 102 MB |

Duplicated vertices are what it costs, and this frame barely notices: the
*drawn* triangle count is identical either way (3,034,578 - instancing was
already drawing every copy), so the only price is storage, and the JS heap
gives back more than the geometry takes. `?inst=4` restores the old rule
for an A/B.

## Performance

Everything below was measured with the rigs in `tools/`, in headless Chrome at
1600x900 and a device pixel ratio of 2 - a 3200x1800 frame - on an M4. The
scene is **fill bound, not geometry bound**: halving the triangles moved the
frame by 4 ms, halving the pixels halved it.

| | before | now |
|---|---|---|
| boot to the first frame | 11.1 s cold / ~5 s warm | **1.96 s** |
| a frame while the camera moves | 51.5 ms | **26.5 ms** |
| a frame while nothing moves | 51.5 ms, sixty times a second | **not drawn at all** |
| worst frame in the Scene 2 move | 18.7 s | **55 ms** |
| bytes before the first frame | ~30 MB | **12.5 MB** |
| `web/scene.glb` | 18.9 MB | **8.3 MB** |

(The boot figure is current; the rest of this table is the 2026-10-12 pass
and the sections below carry what has happened since. The page as it ships
today is **14.17 MB over 67 requests**, of which `scene.glb` is 9.3 MB on
the wire - the model has grown with the show flat and is gzipped now.)

Five things do that, and none of them change what a still frame looks like -
the hero shot after and before differs by 0.5/255 on average, which is the
same as two captures of the *same* build differ by, all of it on the edges
the temporal AA resolves differently from one run to the next.

**The page draws on demand.** A render is owed only when something changes the
image - the camera moved, a tween is running, a switch was flipped, a texture
landed - and each change buys `SETTLE` frames, enough for TRAA to resolve.
The canvas keeps the last frame in between, so a parked hero shot costs
nothing at all and the HUD reads `idle`. Anything new that alters the image
must call `invalidate()`, or it will not appear until something else does.

**A moving frame is a smaller frame.** While the camera is in motion the
renderer's pixel ratio drops below the solved density and the GTAO to half,
and both go back to full within six still frames, with frames in hand for the
resolve. The still frame - the one that gets held against the photograph - is
never the cheap one. It is the whole frame that is scaled: scaling the two
passes on their own leaves TRAA holding a full size history of a smaller
picture, and the copy between them fails WebGPU validation.

How far it drops is a fixed dial in the lab (`MOVE_SCALE`, 0.7; `?moveres=1`
turns it off for an A/B) and an **adaptive one on the sales page**, because
that page's hero camera never stops: the rail sweeps for ever, so the moving
frame is not an occasional cost there, it is the whole experience. A dial
fixed at 0.7 cannot be right on two machines - it leaves a fast one soft and
still misses on a slow one - so the page turns it by the clock instead. While
the shot moves it holds the largest frame that still lands inside a display
interval, steps down after ten misses in a row, and probes back up only after
ninety clean frames; a density it has already failed at is not retried for a
doubling interval, so it settles rather than breathing. The moment the shot
stands still it goes back to the full density and spends its `SETTLE` frames
resolving there, because a parked frame is drawn a handful of times and then
never again: quality there is free.

The ladder stops at **half the solved density** - one buffer pixel per CSS
pixel on a 2x display. Below that the hero stops looking like a photograph of
a building, and a machine that cannot hold 60 fps there is better off dropping
a frame. It starts partway down the ladder rather than at the top, so the
first seconds - which overlap the background compiles - are never slower than
the fixed dial was. `?ceil=` sets the frame time it aims at, `?moveres=` pins
it for an A/B, and `window.__density()` reports where it has settled.

On the sales hero that is **27.8 ms -> 17.3 ms, 36 fps -> 58 fps**, measured
over interleaved rounds.

**The frame is fill bound, and that is the only big dial.** Measured by
switching the output node, which drops every stage after it from the graph:

| | ms at 5.76 Mpx |
|---|---|
| pre-pass + GTAO | 16.7 |
| ... + the beauty pass | 51.2 |
| ... + TRAA | 53.0 |
| ... + bloom | 53.6 |
| ... + the aberration | 55.1 |
| ... + vignette, grain, AgX | 55.2 |

Two thirds of the frame is **the beauty pass** - 34.5 ms of 55 - and that is
`materials.js` evaluated per pixel. The grade is not a cost at all: an older
reading here put vignette, grain and AgX at 9.9 ms, which re-measuring on the
current build says is 0.1. Of the 16.7 ms before the beauty pass, the
occlusion is about 6 (its resolution dial buys 6.3 ms between full and
quarter) and the pre-pass about 10.

and against the pixel ratio it is very nearly a straight line - about
**9.7 ms per million pixels**, whatever happens to be in them:

> **Both tables above are superseded.** They were taken before the sky was
> baked and before the pre-pass stopped building lighting it cannot show.
> The frame is now **4.0 ms per megapixel plus 6.3 ms that is not pixels at
> all** - see **Measuring**, which also explains why a cost measured through
> rAF was never the frame's cost. They are kept because the *stage* ordering
> still holds and because the ratios between the stages are what the later
> work was reasoned from.

| pixelRatio | Mpx | ms | fps |
|---|---|---|---|
| 2.00 | 5.76 | 56 | 18 |
| 1.75 | 4.41 | 44.7 | 22 |
| 1.50 | 3.24 | 33.7 | 30 |
| 1.25 | 2.25 | 25.1 | 40 |
| 1.00 | 1.44 | 16.8 | 60 |

Two things that look like levers are not. **The occlusion is not where the
cost is** - halving its resolution buys 4 ms of 56, not the "nearly all of
the frame" an earlier note here claimed. And **the pre-pass cannot be made
cheaper by drawing it smaller**: it is bound by the 1.5 M triangles it
submits, not by the pixels it covers, so a quarter-size target measured
23.0 ms against 23.2 over five interleaved rounds. Routing TRAA off the
beauty pass so the pre-pass could shrink was built, measured and thrown
away with it - and it would have let a transparent surface write motion
over the wall behind it, which is why that pre-pass is opaque-only.

A third looks like a lever and is not: the pre-pass asks for `normalView`,
the SHADED normal, so in principle every material's normal-map chain runs a
second time there to feed an occlusion term too low frequency to show it.
Writing the geometry's own normal instead (`?prenorm=geo`) measured **0.3 ms**
over three interleaved boots. Three dead ends now, all measured - don't retry
any of them.

What is left is the beauty pass itself, which is **34.5 of the 55 ms** and is
`materials.js` - the procedural noise, the triplanar sampling and the
weathering, evaluated per pixel. That is the next real lever and it is a
look change, not an optimisation.

### The opening ten seconds

Everything above measures one frame. What a visitor actually meets is the
first ten seconds, and `tools/ridecost.cjs` measures those: it rides the
page's own frame loop without touching it and prints every drawn frame's
interval, second by second, beside the density it was drawn at. On the shipped
build it read 12-18 frames in each of the first seconds, p95 spikes of 220 to
330 ms, a worst frame of **1150 ms**, and a density ladder that took eight
seconds to find the rung the machine could hold. Four separate things, none of
them the frame cost:

**The first visible frame paid for the warm-up's pipelines.** The frame drawn
behind the veil submits every pipeline the shot needs, and returns before any
of them exists: the renderer hands them to the GPU process and Dawn compiles
them there. Whatever frame draws with them first is the one that waits - which
was the frame immediately after the veil lifted, measured at 1.1 s. The warm
now drains the queue (`drainGPU`, `?drain=0` to put it back) before it marks
itself done, so that second is spent behind the boot bar where it belongs.

**The hero stood still for 2.4 s before it moved.** The rail bounces at the
ends of its sweep: step, and if `railT` has crossed an end, clamp it, turn
round and hold for `RAIL_PAUSE`. But `railT <= 0` is also true at the START,
on the first frame, where `railT` is 0 and `clock.getDelta()` returns 0
because that call is what starts the clock. So the rail "arrived" at the end
it was standing on, held 1.2 s, turned round, stepped into the clamp, and
held again. The end test now asks which way the sweep was heading. Two and a
half seconds of a frozen hero at every load, and because nothing moved, every
one of those frames was drawn at the full still density.

**The ladder crawled.** It stepped down one rung per ten missed frames with a
24-frame hold between moves - 136 frames to cross four rungs. The frame is
fill bound, so a frame at 2.4x the interval wants about 1/1.55 of the density,
which is a rung the measurement can name outright: it now jumps straight
there. It also ignores frames over 200 ms, which are compiles and uploads
rather than evidence about density, and it treats the opening frames as
moving so it has something to calibrate from at all - `rate()` reads nothing
from a still frame, and the first seconds of this page are still ones. On a
1600x900 window at dpr 2 it now settles in about a second, and settles
**higher**: 2.07 Mpx where the crawl ended at 1.44.

**The show flat's warm was two long stalls.** Its 51 objects compile in
batches, and a batch holds the frame loop off, so the batch size is the size
of the hitch: six at a time measured 130 ms hitches, one at a time 35 ms for
the same total work. Its first DRAW was worse - the whole flat in one frame,
1.0 s - and was chunked two objects at a time with the queue drained between
chunks. The warm also stopped starting 300 ms after the page appears: it
waited for the visitor to move the pointer over the canvas, touch the wheel
or press a key, or for `?warm2after`, whichever came first. That last rule is
the one the next section takes back - see **Warming the flat in one pass**,
which is where the warm's 12 seconds went.

Together, on the same machine and window:

| the first 16 seconds | before | now |
|---|---|---|
| frames drawn | 690 (43 fps) | **803 (50 fps)** |
| first second | 12-18 frames at 31-40 ms | **54 frames at 17.3 ms** |
| worst frame | 1150 ms | **118 ms** |
| settles at | 1.44 Mpx, after ~9 s | **2.07 Mpx, after ~1 s** |

### Warming the flat in one pass

The hover was still dead for the first four seconds after a refresh, and the
complaint that found it was exactly that: *"after refresh i need too much time
to hover"*. The cause was not the hover - it was what the hover waits for. A
WebGPU pipeline that has not been built draws **nothing**, so a storey must
not open until the show flat can be drawn, and the flat was taking twelve
seconds to get there. Measured on the page, with `node tools/ridecost.cjs`
and the in-page timings described under **Measuring**:

| after the building appears | before | now |
|---|---|---|
| the flat's warm, end to end | 12.4 s | **1.8 s** |
| wall starts to part | 3.6 s | **1.8 s** |
| storey fully open | 4.3 s | **2.2 s** |
| and when it opens | part way through the warm | the whole flat is ready |

Four things, all of them in `prepareScene2` and `warmFlatDraw`:

**The warm was waiting, not working.** The old loop waited two frames before
each pass' compile and one after every object - five frames an object. At the
~32 fps the hero manages while a warm runs, that is 155 ms of waiting around
some 35 ms of work: 51 objects in 8.8 s, of which about seven seconds was the
page waiting for frames it had no reason to wait for. It is a time budget now
(`WARM_MS`, 8 ms, `?warmms=`): compile back to back until the budget is spent,
then yield exactly one frame. `?warmidle=1` restores the old pacing, which is
still the default in the lab - that page is a tool somebody drags, it is
render-on-demand, and `untilIdle()` costs nothing there while it sits still.

**Compiling and then drawing was the same work twice.** A pipeline is only
half the cost; the first frame that draws a thing pays again, which is why
`warmFlatDraw` existed at all. But the draw *is* a compile: it builds the
pipeline and pays the first-draw cost in one go, so the compile pass before it
bought nothing. The page now warms by drawing only (`?warm2=compile` restores
the two-phase warm, which the lab still uses - it has no hover to be ready
for, and it wants Scene 2 compiled whether or not anything is drawn).

**Waiting for the GPU between chunks only idled the page.** `drainGPU()` is
what a *compile* warm needs, because `compileAsync` asks the GPU process for a
pipeline and the next frame to draw with it pays. A draw submits the work and
Dawn builds the pipeline on its own threads, so the page can go on submitting
the next object meanwhile. The whole table, `?warmlog=1` printing every chunk:

| chunk | drained | total | between frames |
|---|---|---|---|
| 2 | yes | 3111 ms | 115 ms |
| 8 | yes | 1642 ms | 250-300 ms - a visible freeze |
| 8 | no | 1220 ms | 140-240 ms |
| 2 | no | 1332 ms | 51 ms mean |
| **1** | **no** | **1481 ms** | **29 ms mean, 73 worst** |

One object a frame, undrained, is the row that keeps the hero at ~34 fps while
it runs. `?drawchunk=` and `?warmdrain=1` reach the others.

**Half the warm was the twin.** `warmFlatDraw` drew both flats - the original
and the `clone( true )` that lets two storeys be open at once. A clone shares
three.js geometry and materials with its original, so every pipeline it would
build is already built: 51 objects of pure repetition. The clone is still
*made* during the warm, because allocating its nodes is a 291 ms stall the
first time a visitor crosses from one floor to another, but it is not drawn.
The cost of not drawing it is a 37 ms worst frame on the first open instead of
20 ms (`?warmtwin=1` to compare), against a second of hover latency.

With the warm down to 1.8 s there is no longer any point in waiting for the
visitor to arrive before starting it - the warm cannot both start when the
pointer arrives and be finished when it arrives - so it starts 250 ms after
the page appears (`?warm2after=`), and the intent listeners only bring that
forward. The flat's 24 maps start downloading at `ready` either way: they are
a download, not a compile, and they cost the GPU nothing.

**And the hover answers before it is armed.** The wall still may not part on a
room with no pipelines, but the ray is free: the cursor turns and the page's
floor tag names the flats on that storey the moment the pointer crosses a
band. Before, the whole hover was dead for as long as the warm took, which
reads as a broken page rather than a busy one. The arm itself now resolves on
the compiles rather than on the whole warm, and `FLOOR_ARM_MS` (2.5 s) is left
as what it was always meant to be - a backstop for a slow machine, not the
thing that releases the hover on every load.

**What the FIRST hover waits for, and what it is made of.** `tools/hoverwait.cjs`
boots on a cold profile, sweeps the pointer onto the facade the moment the veil
lifts and prints ready / armed / wall parting / fully open from navigation
start. At 1600x900 @2 the page appears at **1.85 s** and the hover arms at
**3.6 s**; everything between is the show flat's warm, and nothing else.

That second is not geometry. `groups.flat` is 51 objects carrying **45
distinct materials** and ~360k triangles: the cost is three.js turning 45 node
graphs into WGSL **twice, once per pass**, about 11 ms each, on the main
thread. Eight of the 45 are street materials already built at boot; the rest
are the procedural `int_*` chains. It can only be made shorter by building
fewer materials - a look change - or fewer passes.

Three things did shorten it, to **1.43 s** post-ready over interleaved rounds:
the warm sizes each chunk from what the last one measured (`DRAW_MS` 60,
`?drawms=`) rather than drawing one object a frame, because a presented frame
costs ~13 ms whether or not a piece of furniture rode along with it and 51 of
them was 0.7 s of wait with nothing of the flat in it; the twin flat is built
behind the arm instead of in front of it; and the hover is let go before the
flat's 24 maps are even asked for, since a map that has not landed is a 1x1
default swapped in with no pipeline rebuild.

**Moving that warm into the boot is worse at both ends, measured.**
`?warm2in=boot` carries the flat in the street's own warm frame: the page then
appears at 3.6 s instead of 1.9 AND the hover arms at 3.9 instead of 3.3. The
flat costs ~1.3 s inside that frame rather than the ~1.0 it costs in its own,
and the boot drains the GPU afterwards, so Dawn compiling the flat's 90
pipelines lands on the critical path instead of running on its own threads
while the hero sweeps. The knob is kept to show it; don't retry it.

**Two thirds of the page's opening is three.js writing WGSL, and the pre-pass
was paying half of it for nothing.** The page generates **6.9 MB of WGSL**
across 195 fragment programs, and generation time tracks that volume almost
exactly: with `renderer.lighting.enabled` off the boot's warm frame falls from
919 ms to 350 (`?nolight=1` - the picture is wrong, it only prices the chain).
Counting the programs by what they write into the first MRT target splits them
cleanly: 38 write the lit colour (the beauty pass), **38 write a packed normal
and are ALSO full PBR shaders** - BRDF, sixteen shadow taps, a PMREM lookup
and the fog - and 51 are the shadow pass. The pre-pass has two outputs, a
normal and a velocity, and neither of them can show any of that.

`renderer.lighting.enabled` is the flag `NodeMaterial.setupLighting` reads when
it decides whether to build a material's lighting at all, and the two passes
keep separate node builder states, so it is turned off around the pre-pass'
own render (`prePass.updateBefore`) and back on after it. Boot WGSL 3817 KB ->
2699, lit programs 76 -> 38. Interleaved, same machine:

| | warm frame | ready | show flat's warm | first open |
|---|---|---|---|---|
| before | 919 ms | 1626 ms | 1347 ms | 4.16 s |
| after | 646 ms | 1436 ms | 862 ms | 3.04 s |

The warm frame figure is repeatable to ±3 ms. **Scene 1 is byte identical** -
0.000/255 over four captures against a 0.000 noise floor. Scene 2 measures
1.10/255 against a 0.37 noise floor, on furniture surfaces rather than edges:
the lights' own per-frame update now runs once a frame instead of twice,
because the pre-pass no longer evaluates them. Cropped side by side at 1:1 the
two are indistinguishable. `?prelight=1` builds it the old way.

Scoping the flag to the two warms - the states are cached at first build, so
in principle that is all it needs - was tried and costs more than it saves:
three.js treats the flag as part of what a state was built for, so flipping it
back builds every pre-pass material a second time. The boot kept its 280 ms
and the show flat's warm went 1.1 s -> 2.9. **Don't retry it.**

**A second `pipeline.render()` in the same browser frame draws nothing.**
`PassNode.updateBeforeType` is `NodeUpdateType.FRAME` and the frame id only
advances inside the renderer's own animation loop, which is not running behind
the veil - the second call added one draw call and one triangle, the output
quad. The flat cannot be given a warm frame of its own before
`setAnimationLoop`.

**The storey fades as it parts.** The opening used to be a clean cut and
nothing else: a line across the floor travelling up and down from the middle
of the storey, with the wall either there or gone on either side of it. It now
also DISSOLVES, over the whole floor rather than over the band, so what a
visitor sees is a storey going translucent with its rooms and lamps rising
through it while the opening grows inside.

There is no alpha to turn down to do that. The shell is opaque and the cut is
a drop on the alpha test, which is exactly what keeps the opening off the
transparent pass and out of the sorting, so what fades is the FRACTION of
fragments dropped rather than the opacity of each: a fine screen-space
stipple - interleaved gradient noise, five ops - tested against the dial, and
the temporal filter resolves it. Measured mid-dissolve, consecutive frames
differ by 1.5/255 with 0.4% of pixels over 32: a smooth veil, not salt and
pepper. The pattern is turned by a golden-ratio step every frame
(`XRAY.seed`, bumped in `floorStep`) - a pattern that stands still is a
screen door and the eye reads it as grain.

The shader asks one footprint about two heights rather than testing two boxes
(`xrayFoot` / `xrayZ`): the parting line is `lo.z..hi.z` and the storey the
fade works over is `rlo.z..rhi.z`, which the room box already carried. Two
extra steps, not another twelve. `FLOOR_FADE` (1.15, `?fade=`) is how far
ahead of the line the fade runs, and `?fade=0` is the old hard cut on its own;
`?open=` stretches the 0.4 s, which is the only way to look at any of it,
because at speed the whole movement is six frames. At rest the dial is exactly
0 or exactly 1 and the cut is binary again, so the still render is untouched -
0.37/255 against the same shot taken before the change, which is capture
noise.

### Glass goes in where the wall was

A storey with its wall taken away is a hole in a building, and a hole reads as
damage - which is the opposite of what the hover is for. So the opening is
**glazed**: one blended quad per slot, the street front and the gable round
the corner from it, laid 8 cm proud of the facade and drawn over rooms that
are already in the frame. That is all it costs - its own fill, no
transmission pass and no second render of what stands behind it.

Three of the four things that make a pane read as glass are the ones
`materials.js` already puts on the building's own windows. The sky is
mirrored off it by Fresnel - weak face on, strong at the oblique angle a
street front is actually seen from - sampled from the same equirect the other
glazing reflects, so every pane in the frame agrees. The sun is put back
analytically, a tight lobe and its halo, because that sky is the *light* sky
and carries no disc. And the pane has a body: float green on the way through,
rain runs down from the head, dust along the foot.

The fourth is the one that did the work. A 47 m sheet of smooth sky has no
scale, and the eye files it as haze over a hole rather than as glazing, so the
pane is a **module**: a joint every 1.58 m (`?gmod=`, `?gjoint=`), and each
pane between two joints bowed its own way - a sealed unit is closed at the
factory and the one beside it was closed on a different day. The tilt goes on
the reflected ray rather than on the normal, which for a sheet this near a
mirror is the same picture for four sines instead of a bump map, and what it
buys is the step at every joint that a real glazed facade has. Over the top of
it the reflection is not all sky: a street front mirrors the sky above and the
far side of the avenue below, and because the reflected ray leaves at the same
small angle the eye came in at, the line between them falls *inside* the
floor. The per-pane tilt then lands panes on either side of it and the sheet
reads as a chequer of pale and dark rather than as one wash (`?gcity=`). The
mirrored city is the same haze at a low albedo, not a colour of its own, so it
stays in whatever palette the sky is in.

Where the glass *is* comes off the x-ray's own slot uniforms rather than off
anything written per frame: solid across the parting line `lo.z..hi.z` as it
travels, and at `fade` over the rest of the storey. The sheet therefore
arrives exactly as the wall leaves, and neither is ever seen through the
other. The panes run only as far as the opening does - to `row.end`, not to
the end of the block - because a sheet of glass standing on black plaster past
the last flat is the one thing that would give it away.

It rides in the boot's warm frame for the same reason the show flat does: an
unbuilt pipeline draws **nothing** in WebGPU, and the first storey to open
would open on an empty hole. One quad at alpha zero, in a frame that is being
drawn anyway. It has to hang off that frame rather than off the end of the
boot, because the page calls `setScene( 1 )` on its way there and that resets
the floor map.

Measured interleaved (`tools/hovercost.cjs`, 1600x900 @2), the glass is inside
the noise:

| | ms | p95 | draws |
|---|---|---|---|
| hovered, storey open | **36.3** | 39.9 | 216 |
| hovered, no glass in it | 37.1 | 72.5 | 212 |
| still, nothing hovered | 50.8 | 55.5 | 110 |

Four draw calls, no measurable time, and the parked hero is untouched: with
nothing hovered the panes are not in the frame at all, so the still shot draws
the same 110 calls it did before. `?glass=0` is the old opening, a hole with
nothing in it, and every dial is a uniform rather than a constant, so the
whole pane can be moved from `window.__glass.set({ ... })` over one boot.

### The floor view's head, and the line the storey stands on

The floor view is headed by **one line of small caps across the window**, and
the two halves of it sit on the things they name:

```
← BACK TO THE STREET  FLOOR 7 · 6 FLATS · 12 FLOORS     CHOOSE FLAT
[ the four cards ]                                     ┌────── the storey
```

**The way back is the first thing on that line.** Every step carries one -
the storey goes back to the street, the open flat back to the whole floor,
the show flat back to the street - and it is always at the LEFT END of the
step's own head line, in front of the name of the step. It is a **link**:
`.stepback` draws a rule under the type and nothing else. A bordered box the
size of `Book a viewing` read as a fourth thing to do, sitting under the
cards at the foot of the column, when all it does is undo the click that got
here. The show flat has no rail, so its line is the card's own head row -
the link, then the badge that names the step (`.stephead`).

The counts go over the cards they count - still the STOREY's, not the
building's, because a card over floor 6 quoting the whole block is answering
a question nobody asked. The view's own name goes on the **top corner of the
building**: `#floorlabel` is placed against the plate's own left edge and
dropped onto the counts' line, so it reads as a label on a drawing rather
than a heading over a panel. Both are 10.5 px - a display-size title was
tried over the rail first and turned the four cards into a footnote to it.

The label is placed from the numbers the scene is already framed to, so it
cannot drift off the corner it names: `tellInset` works out the plate's left
edge once and hands the same value to `LP.setInset` and to
`placeFloorLabel`. It is hidden below the rail's breakpoint, where the cards
lie across the top of the plate and there is no corner to write on.

The **margin over the counts** (12vh) is what stands the cards down off the
header instead of letting them run into it, which puts them about where the
street shot's own type begins. The line itself is lifted 4 px off it with
`top`, not by taking 4 px out of that margin: the margin is the number the
cards stand on and the scene frames the storey against (`uiTop`), so taking
it out there would have walked the building up the window with the type.
Everything else on the line - the name on the building's corner, the arrows
at the far end - is placed off the counts' own box, so the line moves as one
and the plate does not move at all. Measured: the counts and the name both
go from 244 to 240, the first card stays at 272.

...and the plate's own top edge sits `PLAN_SILL` under the line the first
card starts on. It is 3 px and it is not a fudge: what the fit measures is
the storey's outermost corner, which is a balcony rail, so a plate laid
flush on the line puts its WALL a few pixels above it. Thirty was tried
first and read as the building having slid down the window.

**`PLAN_NUDGE` is a different thing and has to be**: 6 px further down the
window, applied after the clamp and feeding nothing. The sill is not a
translation - it feeds the *fit* as well as the drop, because a bigger one
leaves a shorter band for the storey's depth, which flies the camera up and
shrinks the plate, which pulls its top edge back towards the line it was
being pushed off. Measured on 1x shots by cross-correlating a strip of the
plan: the first two pixels asked of the sill arrived exactly, the next two
came out as **nothing** and the match stopped being a translation at all
(residual 3.0 -> 6.0). On the nudge every pixel asked for arrives: 4 landed
as 4, and 2 more on top of that landed as 2, each on a sharp minimum (1.76
at +2 against 3.19 and 3.57 either side) with no change of scale. It moves the building and nothing else - not the fit, and not the
stops the arrows walk, which are read along the frame's right. The plan thumbnails came down from 118 px to
90 to pay for it: with the margin in and the old box, `Back to the street`
landed on the camera hints that used to run across the foot of the hero.

And the storey follows the cards. The page hands the scene the top of its
first card along with the inset - `LP.setTop( px )`, measured off the card
and not added up from the CSS - and `planFrame` lays the top edge of the
plate against it:

* `PLAN_FIT` (1.13) stands the shot a hair outside the fit rather than flush
  against it. At 1.02 the plate ran off the top and the bottom of the window
  at once and read as a texture rather than a cut-away storey.
* the **depth** is then fitted to the strip between that line and the foot
  of the window (`PLAN_FOOT`, 78 px), not to the whole window, so the near
  wall stands clear of the bottom edge instead of running off it. The strip
  was what the camera hints took off the foot and it is breathing room now
  that they are gone. Across the frame nothing changes - the row runs off
  the right either way and the arrows walk it along.
* the drop itself is along the frame's own up, which is square to its right,
  so it moves nothing the arrows' stops are read from.

`uiTop` of zero means *centre it*, which is what the narrow layout and the
render lab both want.

### Walking the floor view along the row

Clicking a hovered storey opens the **floor view**: the camera pitches
straight down over that floor and the page lays its four plan cards down the
left. The shot is framed to the whole row at a scale a plan can be *read* at
and then slid sideways until its left end clears the cards - which is the
right trade, and it leaves the far end of the storey off the right of the
window. The storey is **dragged** along the row, free-running, and two arrows
walk it flat by flat.

Those arrows sit on the **right end of the `Choose flat` line** - against the
page's own right gutter, which is the header's gutter too, so they come down
directly under its button, and `placePager` drops them onto the line the
label was just laid on so the view's name and its controls read as one line
across the top of the plate. They were on the foot of the hero with the
camera hints while those were there; the hints are gone and the foot with
them. Below the rail's breakpoint there is no label line to use and they
keep a CSS fallback under the header - though a narrow window frames the
whole storey anyway and the pair hides itself.

They are a **pan and nothing else**. The camera and its target move together
along the frame's own right, so the height, the roll and the scale never
change and nothing rotates under the visitor - only which flats are under the
window. Every frame of the slide is `planPose( pan )` recomputed rather than a
lerp between two remembered poses, so a window resized mid-slide, or the page
changing its inset, re-frames underneath the move instead of fighting it.

The stops are one per flat. `planFrame()` holds the arithmetic the shot and
the stops are both read off - a second copy of it is a copy that goes wrong
the first time the fov changes - and it reports `hidden`, how many metres of
the row the window cannot show. Each unit's near edge, measured in metres
right of the plan's own left edge, is exactly the pan that brings it flush
with the cards; those under `hidden`, plus `hidden` itself, are the stops. The
first is the corner unit the view already opens on and the last is wherever
the end of the row comes flush with the right of the window, so the arrows can
be held down without the plan wandering off into roof.

Where the units begin comes out of the build. `row.starts` is written into
`scene_meta.json` off block A's own bay table, because the page must not know
how wide a flat is - the bays move, and the four units are not even equal
(unit 0 is 11.84 m, the copies 11.54, with the difference taken out at
`ROW_SEAM`). Adding the field reproduced `scene.glb` byte for byte:

```
row: { n: 3, starts: [0.25, 12.09, 23.63, 35.17], end: 46.71 }
```

The stops are **sorted** rather than taken in unit order. `planUp` comes from
the heading the camera had on the street, not from the building, so the row
can run either way across the frame; left to right is left to right whichever
end the gable is at.

The scene owns all of it and the page only pushes: `LP.planStepBy( ±1 )`, and
an `lp:plan` event carrying `{ step, steps }` so the page can grey out an
arrow at an end and hide the pair altogether on a window wide enough to show
the storey whole. How many stops there are depends on how much of the window
the cards are covering, which is the scene's arithmetic and not the page's.
A resize or an inset change re-fits through `planClamp()`, keeping the step
and taking its new metres, so widening the window at the far end of the row
cannot leave a visitor looking past the end of it.

There is deliberately **no keyboard shortcut**. The obvious one is the arrow
keys and they are taken: the fly controls strafe the camera on left and right
wherever the canvas is live, the floor view included, so binding them here
would walk the camera and page the storey on one press.

**Dragging it is free-running, not stepped.** The arrows are the coarse
control; the plan itself follows the pointer one to one and comes to rest
wherever it is let go, with no snapping to a flat - and on release it carries
the speed it was let go at and runs down under friction (`PLAN_TAU`, 0.26 s to
lose 1/e of it, dead below 0.25 m/s). The velocity is a rolling estimate
rather than the last frame's: a pointer sampled at 240 Hz hands you a 4 ms gap
whose speed is mostly noise, and a flick that happened to end on one slow
sample would land dead.

Past either end the row does not stop against a wall it has no way of
drawing. It follows at a third of the pointer (`PLAN_PULL`) so the resistance
is visible, and springs home when the pointer lifts. The three callers of
`planSetPan` want three different clamps and so it does none of its own: the
drag takes the soft one, momentum the hard one, and the spring takes none at
all - clamping there is exactly what made the first version snap back in a
single frame instead of easing.

The drag is measured from **where it started**, not as a running sum of
per-move deltas, and that is what makes the band a band. Accumulating deltas
compresses an already-compressed value on every move, so the overshoot
converges on `PULL/(1-PULL)` times one mouse-step - measured at 0.61 m
however hard the row was pulled, a soft wall rather than something that gives
further the harder you pull. From the starting position it is linear in how
far past the end the pointer has gone: 5.7 m for the same drag.

The drag had to be **taken off the camera**. Looking straight down at a plan,
a pointer dragged across it does not mean "turn on the spot", so
`makeFlyControls` grew a `drag:` gate beside its `allow:` one and the page
closes it in the floor view. The keys stay with the camera; only the drag
moves. A `stopPropagation` from a later listener could not have done it -
both handlers sit on the canvas itself, where that stops nothing - and the
fly controls are built before the page's own handlers are bound, so
`stopImmediatePropagation` was not available either.

Free sliding also changes what the arrows mean. The plan is usually *between*
two stops, so `planStepBy` takes the next stop strictly ahead of where it
actually is rather than rounding to the nearest and adding one - which would
walk a forward arrow backwards whenever the plan had drifted a little past a
flat. For the same reason the greying out is driven by `atStart` / `atEnd` in
the `lp:plan` event and not by the step index: an index cannot say whether
there is any row left.

### Opening one flat

The third step. The floor view is eight plans with the one under the pointer
furnished; **clicking that flat opens it** - the camera comes down onto that
unit alone, the furniture it had under the pointer is pinned up, and the four
type cards down the left are replaced by that flat's own card. Clicking off
the plan closes it again, as do `Esc`, the `← The whole floor` link at the
left of the card's head line, and a click on a neighbouring flat, which goes
straight there.

**The name on the building's corner goes with the storey.** `#floorlabel`
used to be rewritten from `Choose flat` to `Flat 62` here; over one flat it
was a title across the picture saying what the head line beside it already
says, so `tellInset` takes the label off entirely while a flat is open and
the text never changes. The floor view is the only view that carries it.

**It is a pitch and nothing else.** The camera swings down from over the flat
about the *frame's* own right - the axis the picture's left and right already
lie on - so the roll and the heading it had looking straight down are exactly
what it keeps. The row still runs across the window, the depth still runs up
it, nothing turns under the visitor. `FOCUS_TILT` (32°) is the whole of the
difference between the two shots.

That lean is **the same for every flat on the storey**. It swung out over
whichever side of the block the unit stood on at first, which keeps each flat
clear of its neighbour's walls and is wrong anyway: the two rows then came out
facing opposite ways and the back line read as the plan turned upside down -
*"second line flats are rotated from top"*. A visitor stepping along a storey
is looking at one building from one place. So the lean is the street's,
always; the back line pays about a metre and a half of its corridor edge to
the front row's wall for it.

**Fitted by measuring, not by arithmetic.** There is no closed form for an
oblique box fitted to a band that is not the window, so the pose is built, the
unit's eight corners - floor *and* ceiling: at this tilt the walls standing up
are most of what has to fit - are projected through it, and the stand-off is
scaled by how far outside the band they land. Five passes; it lands inside a
pixel long before the fifth. `FOCUS_FIT` is **under 1** on purpose, because the
highest thing in that box is a strip of bare wall head and holding it inside
the band kept the rooms a size smaller than the window could carry.

The band it is fitted to is the glass the page is *not* using, and it is not
the storey's band. Across the frame the storey is fitted to the whole window
and only slid clear of the cards - a row fitted into the narrower band is a
plan nobody can read - where one flat fits the band easily and belongs in the
middle of it. Down the frame the storey lays its top edge on the line the
cards start on, because the plate and the cards read as one block; one flat
has nothing beside it to line up with, so it answers to the page's header
instead. Holding it under the cards' line threw away a third of the height it
could have had. The gutter between the two is cut to a third as well: it is
there to keep a storey off four cards it would crowd, and with one flat in the
window it is glass nobody is using.

On the **narrow layout** the card is a band across the window rather than a
column beside it, so it docks to the foot and the flat takes the whole of the
top. The page hands over `LP.setFoot` for that, the mirror of `setTop`, and
the card is cut to what cannot be left out - the type's plan thumbnail goes
first, being the one thing on the card that is already on the screen in 3D
right above it.

Which flat in the **inventory** a drawn unit is belongs to the page, not the
scene (`flatAt`): the scene says only which of the eight bays was clicked. The
two counts do not match and cannot be made to - the model's storey is the one
modelled flat repeated through the facade's bay rhythm, four bays on the
street and four behind, where the inventory carries six to a floor - so the
street bays are dealt the storey's street flats and the back bays the rest, in
the order they stand, wrapping when a row runs out of real flats before it
runs out of bays. The card then always names a flat that exists, with its own
number, price and status. Replace `LINE` and `ASPECT` in `content.js` with the
real floor plate and it comes right on its own; nothing in `flatAt` counts to
six.

**The storey stands back behind it.** The open flat was competing with eight
bays of brand amber, and at this tilt the neighbours' ink walls stand up and
read as teeth across the top of the frame. So `PL.dim` takes the drawing's own
tone down by 78% while a flat is open. It rides on `ink` - the weight the
drawing is mixed in by, which is **zero wherever a flat has been furnished** -
so it cannot touch the open flat however hard it is driven, and it is one
multiply in a shader that was already doing that multiply: no second pass over
anything, no extra draw. It has its own ramp, shorter than the reveal's,
because the camera takes 1.25 s to come down and this has to be finished by
the time it arrives. `?focusdim=` walks it.

**And the scrim comes off it.** The floor view's navy fades out 420 px past
the rail, which that view needs - the plate runs edge to edge and the fade has
to clear the type without a seam. One flat is framed in the glass *beside* the
card and starts where the gutter ends, so those 420 px were laid straight
across its near third: the balcony and the living room came out a stop darker
than the bedroom at the other end of the same flat, for nothing. With a flat
open the scrim falls off 120 px past the card, which has its own glass anyway,
and the lift off the foot comes down with it.

Nothing is done to the **density ladder** here, and nothing should be. This
machine measures 21 ms per megapixel at 4.6 Mpx, so `stillScale` already
returns 1 - the time budget says a supersampled still is not affordable - and
the open flat is drawn at the same full base density every other parked shot
gets. `__focus()` reports what the fit landed on instead: the stand-off, and
where the unit's box falls on the screen against the band it was fitted to. A
pose that has diverged and a pose that is right look identical from outside,
and the fit is five passes of measurement with nothing to read off the camera
afterwards.

**Leaving a room by clicking a neighbouring flat told nobody.** Every other
way out of a room - `Esc`, the step-back link, going back to the street -
runs through `setScene`, which announces the room on the way past;
`planFocusSet` dropped `roomFocus` to -1 by hand and did not. So the room
bar sat over the open flat with its prev / next / way-out buttons live and
`roomview` still on the body: the way back out of a room nobody was in any
more. It calls `roomTell` now, the way it already calls `planFocusTell`.

Two things this turned up. `floorReset` **hides the flat group** - the storey
hover borrows the real group rather than a copy - and the only path that gave
it back was the flight's own callback at the end of a full scene change, so
`Walk through it` from an open flat flew the tour into an empty storey (that
button has since gone from the card - the visitor is already looking at the
flat in 3D, and the tour opens the one modelled unit whichever flat was
clicked, so it offered to take them off their own flat - but the fix stands
for every other way in). And
scene 2 is *two* views: `openTour` tested only the scene number, so a visitor
already in the floor view stayed exactly where they were with the card under
the hero quietly renamed. Swapping the two views on the same storey is now its
own case in `setScene` - the building is already open and the cut is already
where it belongs, so it is a camera move and nothing else.

### Standing in a room, and the shell that puts the top back

The fourth step. Every room of the open flat carries a dot; clicking one
walks the camera in at eye height. The flat is modelled as a **dollhouse** -
every wall stops at `CUT_H` (1.45 m over the slab, 1.47 over the floor) so
the storey can be read from above - and a visitor standing inside a 1.47 m
room is looking over the top of it at the sky. So `roomShellGeo` in app.js
**rebuilds the top of that one unit** from the cut to the ceiling: the walls
with their openings left out, the lintels, the tiling, and the top of each
door - lining, architrave, leaf, lipping and the top hinge. It is built in
the flat's own metres and laid into the world with the frame's own basis, in
the flat's **own materials**, so the floor view's drawing carries it along
for free. It is on only while the camera is under its own ceiling.

Two things broke the seam, both fixed 2026-10-19 after *"door is brokes
sometimes ... and whole wall too ... it happend when my camera is near"*:

- **The leaf ignored the cut.** `lib_flat.door()` capped the frame at `ztop`
  and built the 2.05 m leaf anyway, so four white blades stood 0.6 m proud of
  every wall in the plan - obvious from above, and doubled with the shell's
  own leaf on top of it. The leaf, its lipping and its top hinge are cut at
  the same plane as everything else now, which is what the shell's 40 mm
  "grip" down into the wall was always written for.
- **The page's copy of the plan had gone stale.** `FM` in app.js mirrors the
  flat's plan by hand, and `Y_ENT` stayed at 8.20 when the two lines of flats
  were brought together at the middle of the block and it became 8.80. The
  shell therefore built the entrance wall 0.60 m thick instead of 0.20, with
  the front door's leaf 0.30 m out of its own opening: a door and a wall that
  broke in half at the cut line, visible only from inside a room and only
  close up. The build now **writes the plan into `scene_meta.json`**
  (`flat.plan`) and `adoptPlan` copies it over `FM` as the meta lands, so the
  two cannot drift again; the literals are the fallback.

The shell also carries the **blind at the back of the front door**. The two
lines of flats meet in the entrance wall, so `lib_flat` closes that opening
with a dark panel - without it you look through two front doors into the flat
behind - and the panel is cut at 1.47 with everything else. The shell rebuilds
it to the door head; otherwise the top half of the doorway is a hole straight
out over the storey.

### Walking it, and the doors that open

The fifth step, added 2026-10-19 for *"when i am walkin in flat ... i need u
walk like real human, and doors open like real, i need real physics of
walkin inside room"*. Up to here a visitor dropped into a room had the **fly
camera**: 11 m/s, which crosses this flat in a second and reads as a drone,
space and C to rise through the ceiling, and no wall in the place that
stops anything. Inside a flat the keys are a person's legs instead.

**The body** is a disc 0.48 m across whose eye is at the stance's own height
- `ROOMS[i].h`, not a nominal 1.65, so the first walking frame is exactly
the frame the dive ended on and nothing pops as the keys are handed over. It
answers to the keys the way legs do rather than the way a thruster does: a
fifth of a second to get going and a seventh to stop, 1.35 m/s at a walk and
2.45 with shift held. Space and C do nothing in there.

**The gait is clocked off the floor, not off the clock.** The phase advances
by the distance walked over the length of one pace (0.76 m), so the head
drops on a footfall at whatever frame rate the machine is managing and a
body edging forward still takes whole steps. On top of that the head rises
and falls twice a stride (19 mm), sways once (24 mm), and carries 0.7° of
roll with the sway and 0.2° of nod with the fall. Those four together are
the whole difference between a camera being slid along the floor and
somebody walking.

All of it scales with how fast the body is going and all of it **snaps to
zero** at the bottom, both the bob and the velocity under 0.02 m/s. The
exponential decay never actually arrives, and `viewMoved` cannot tell a
camera creeping by nanometres from a camera moving: without the snap the
page draws for ever. An idle breath would be lovely and would cost the whole
of render-on-demand, so there is not one.

**What it cannot walk through is read off the model**, not written down.
The flat arrives welded - one mesh per material for a whole row - so there
is nothing left in it that knows a bed from a bathroom; but every triangle
is still there, and a body does not care which piece it belongs to. When a
flat is walked into, every triangle of that unit between knee and chest
height (0.25 to 1.40 m over the slab) is rasterised into a 60 mm grid, and
the grid is turned into a **distance field** by two chamfer passes. A step
is legal if it ends further than a body's radius from anything solid.

That is the whole collision model and it costs nothing to keep in step: the
walls, the linings in them, the kitchen run, the beds, the bath, the balcony
glazing and the balcony rail all stop a body because they are all in the
model, and the rugs and the parquet do not because they are under the band.
The dark panel behind the front door stops a visitor walking out of the flat
into a corridor nobody modelled. Add a sofa in Blender and it stops a body
too, with nothing to change here. Writing the plan out by hand instead would
have been thirty numbers that drift the first time a partition moves - and
`FM` is exactly that mistake, already made once.

Two things fall out of the field rather than out of a plain solid-or-not:
**sliding**, because a step that fails is retried on each axis alone, so a
body walking into a wall at an angle runs along it instead of stopping dead;
and **getting out**, because a body already inside something may always move
the way that increases its distance. It has to be able to - the stances are
authored standing in corners, since a camera in the middle of a 3 m room
sees a wall, and several of them are closer to the plaster than a shoulder
is wide.

Triangles are filled by their **bounding box**, which sounds crude and is
exact for nearly all of this: the flat is built out of axis-aligned boxes,
and the two triangles of such a box's face have that face for their box.
What over-fills is the downloaded furniture, whose triangles are smaller
than a cell anyway.

**The sweep is 1.9 million triangles** - there is no rejecting seven eighths
of a welded row by object - and doing it the obvious way, through
`fromBufferAttribute` and `applyMatrix4`, took 280 ms. Reading the position
buffer straight, skipping the matrix for the welded meshes (which are
already in the group's own space, and are most of the geometry), and
throwing a triangle away on the cheapest test that can throw it away - the
height band first, which drops nine tenths, then across the row, which drops
seven eighths of the rest - brings it to **65-100 ms**. It runs on the frame
the dive LANDS rather than the frame it starts: at the start that is six
dropped frames off a camera moving at its fastest, at the end it is a stall
against a camera that has already stopped on a page that draws on demand.
The grid is then kept per unit, so closing a flat and opening it again, or
walking the same plan on another floor, is free. `?walklog=1` reports it, and `__walk()` from the console reports where the
body is standing, how much floor it has (`free`), and how much of that is
the plan rather than a door (`plan`). There is nothing to read off the
camera here: a walk sliding along a wall it should have stopped at and one
walking down the middle of the hall look identical from outside.

#### The doors swing

A door in this flat is **modelled open**, 68 to 84 degrees, because that is
the pose the dollhouse and the floor view are shot in. Walked into, it is
the one thing in the place that is obviously not real: every door stands
permanently ajar at the same angle and a visitor walks through four of them
without one of them moving.

So the half of a door that hangs on its hinges - the leaf, its lipping and
the two lever handles - is **its own object in the build**
(`flat_door_<room>_swing__*`, see `lib_flat.door`), and nothing else is: the
lining, the architrave, the hinge barrels standing on the axis and the
striking plate in the far jamb all stay where they are. The page welds the
flat per material, so without that split there is no way to turn a leaf
without taking its own doorframe round with it.

`doorRig` takes those four doors of the one open unit back out of the welded
mesh, re-welds the other seven units' worth without them, and hangs the four
on pivots at their own hinge lines. Then they are all shut, and each swings
open on a spring as a body comes within 1.55 m of the middle of its opening.
It **stays** open: doors that shut themselves behind a visitor would be four
rooms with the lights going out one after another, and the flat is
photographed with all four standing open anyway. On the way out every door
is let go of at once, so by the time the camera is back over the plan all
four stand at the angle the build modelled them at - which is the pose the
welded mesh has when the rig hands them back to it. Clearing the rig outright
instead snapped four shut doors open under a camera still rising through the
flat.

**An opening door moves you.** Everything else in the flat stands still, so
a body can only end up inside something two ways: a leaf has swung through
where it was standing, or it arrived there. Both happen, and the master is
both at once - its stance is authored *inside its own door's swing*, because
the door is modelled open and a camera put in the corner of that room lands
exactly where the leaf stands. So before the keys are read each frame, a
body with less than its radius of room is pushed uphill in the same field
the walk is tested against, a few centimetres a frame. It cannot be shoved
through a wall to get it clear of a door, because that would be downhill;
the worst it can do is stay put. Arriving in the master now reads as the
door opening and the visitor stepping aside, which is what a person does.

The rig carries the **leaf above the cut** as well. `lib_flat` stops the leaf
at 1.47 m with the walls and the shell used to carry it up with them, but a
leaf in two halves can only swing if one piece owns both, so `doorTop` keeps
the lining, the architrave and the top hinge - which stands on the axis and
does not move - and hands the leaf and its lipping over here.

Shut and open are derived as **world rotations off the plan headings**
(`doorHeading`, `doorYaw`) rather than written down, so the leaf the rig
turns and the leaf the body bumps into can never disagree, and the
handedness of `(ex, up, ey)` never has to be reasoned about: both ends go
through the same map, including the back line's mirror. The doors are also
the one thing the collision grid cannot hold, because they move - so each is
tested as a segment from its hinge along its own heading at whatever angle
it has got to. A shut door is a wall; an open one is a plank standing in the
room beside its opening.

**The cost** is three draw calls at rest - one per material, for all eight
units, in the *same* three materials as the frames they hang in, so no new
pipeline - and twelve more while a flat is being walked, where the shot is
parked and cheap. The dollhouse and the floor view are untouched: two
captures of `golden-s2` differ by 0.81/255 and this build differs from the
one before it by 0.73.

One thing that is deliberately NOT a door: the **balcony sliders**. Those
are a fixed pane of `int_glass` in the loggia's glazed back wall, not a
hung leaf, and they stop a body the way glass should. A visitor reaches
either balcony by its own dot and can walk about on it once there.

### The storey is drawn, not photographed

A visitor in the floor view is there to **read plans**, and a photograph of a
furnished flat seen from 60 m up is a bad plan: the eye has to find the walls
among the parquet, the rugs and the shadow of every partition. So the storey
stops being a render and becomes a drawing. Every wall goes to ink, every
floor to the brand's amber, the glazing is taken out and all the furniture
with it - eight flats in two colours, each with its area on a badge in the
middle of it.

**The furniture is parked, not thrown away.** Each piece sits at zero scale on
its own foot, so hovering a flat grows it back out of the floor it stands on,
and the pieces do not arrive together: the reveal is a wipe across that flat,
so the bed comes up, then the nightstand beside it, then the rug. One flat at
a time - the one under the pointer - and everything else stays a drawing.

**It is drawn FLAT.** The sun is still on the storey, and left alone it lays
the shadow of every wall across the floor below it, which is the one thing
that stops a plan reading as a plan. So the two tones go in as *emission*
rather than as colour and only `PLAN_LIT` (8%) of the lighting survives -
enough to tell the top of a wall from its side and no more. The furniture
arriving brings the whole of the real shading back with it.

The hex is **not** `--amber`. The tone map desaturates anything bright and the
grade pulls the frame towards the photograph's own contrast, so the brand's
own colour laid on flat comes back as sand, and driving it harder only blows
it to white. `#f2a500` at a gain of 0.70 is the one that *comes out* as the
amber on the badges standing on the same floor, found by walking a ladder of
them against those badges (`?amber=`, `?gain=`, `?flat=`, or `__plantone()`
from the console over one boot).

**Nothing is split into more objects.** The flat costs the same 52 draw calls
whether the storey is a drawing or a room, and the floor view's frame time is
the same to a tenth of a millisecond with the whole thing switched off
(`?plan2d=0`): 44.9 ms still against 45.2, 29.7 while moving against 30.5.
Four things carry it:

- **Which** of the eight units a fragment belongs to is read off its own world
  position against the row's own bay table - `row.starts` out of
  `scene_meta.json`, plus the line the front and back rows meet on - the same
  way the lamps inside an opened storey already are. The units are not equal
  (unit 0 is 11.84 m where its copies are 11.54), so it is a one-hot over the
  four bays and not a divide.
- **What** it is - wall, floor, furniture, glazing - belongs to the MATERIAL,
  not the fragment. Four of the flat's materials build both the shell and the
  furniture standing in it (`chrome` is a tap and a window catch, oak is a bed
  and a window sill); those four are copied so each copy has one job, which is
  the whole cost of the split: 98 draw objects become 102. The architecture
  always keeps the original, and every material the street shares with the
  flat is a shell material, so the city is never touched by construction.
- **Where** a piece's foot is rides in `apivot`, a vec3 baked into the
  furniture's geometry as it is welded. The merge puts a whole row of bedrooms
  into one mesh, and without it a bed could only be scaled about the
  building's origin. It is on the furniture only - about a fifth of the flat's
  vertices - because nothing else is ever moved. The furniture that keeps its
  own textures is instanced rather than welded, so it has no room for one: it
  is scaled from JS instead, each instance about its own origin, which the
  build already put on its footprint at floor level.
- **When** a piece arrives falls out of where it stands in its own flat, so
  the stagger needs no per-piece bookkeeping at all. The same expression gives
  the shader its delay and the JS its delay for the instanced furniture, and
  the two agree without being told to.

The fade is the **stipple dissolve** the storey's own x-ray already uses - the
fraction of a piece's fragments dropped rather than the alpha of each - so a
chair arriving costs no transparent pass and no sorting, and at rest the frame
is binary again. The shadow map is redrawn on every frame of a reveal
(`shadowDirty`), because a bed that has gone still casting its shadow on the
floor is the one thing that would give the whole trick away.

**The badges are DOM, not geometry.** The number has to be read at a glance at
whatever scale the row has been slid to, and a sprite in the scene would be
resampled by the temporal filter and the grade along with everything else. So
the scene says only where each one goes - the centre of each unit, projected
from 1.2 m over its own floor, announced as `lp:planbadge` and only when
something the page can *show* has changed - and the page draws them. Each is
two boxes: the outer one is moved, which happens on every frame of a drag, and
the inner one is what fades, so a transition on the fade never finds itself
easing the position as well and lagging the drag by four tenths of a second.
They are taken off the flat the pointer lands on **at once**, on their own
0.4 s ease, rather than over the second the furniture takes to arrive: the
point of the hover is to see the rooms, and a badge over the middle of them is
the one thing in the way.

Every flat in the row is the modelled one, so they all carry the same area -
the badge is the show flat's `tour.area`, not the inventory's.

Proved unchanged elsewhere: Scene 1 is **pixel identical** with the drawing
compiled in (`imgdiff` 0.000/255, no bbox), and the show flat's tour differs
by 1.77% of pixels over 8 against a run-to-run noise floor of 2.97% on the
same shot - all of it on edges, which is the temporal filter landing on a
different jitter, not a change in the look.

In developer mode the drawing is off: there the flat is left unbatched so
every piece can be picked and dragged, and none of the welding this is built
on has happened.

### The sky was a third of the frame

The background is the analytic sky: a Perez gradient, a cirrus deck built
from two domain-warped fbm evaluations, a cumulus band, the sun disc and its
aureole, and the haze. It ran **for every background pixel of every frame** -
and three draws the background across the whole frame, before any geometry
covers it up, in both passes. Priced by swapping it for a flat colour and
interleaving three boots each way:

| | pr 2 (5.76 Mpx) | pr 1.5 (3.24 Mpx) |
|---|---|---|
| analytic sky | 4.8 ms/Mpx | 4.9 ms/Mpx |
| baked equirect | ~0 (at the noise floor) | ~0 |
| saved | 25.5 ms, 27% of the frame | 19.1 ms, 30% |

It is also perfectly static - no time input anywhere in `sky.js` - so it is
baked once at boot into a 4096x2048 half-float equirectangular target and
sampled by direction, which is what the light and the haze already did at
1024 and 256. The dither stays on the sampled colour, because a 16-bit
texture of a smooth gradient bands exactly where the analytic one did.

The bake costs nothing: the sky step of the boot measured 39-41 ms with it
and 42-45 without, across sizes, because one 8 Mpx quad is nothing to this
GPU. It costs 67 MB of VRAM, which `?bgpx=2048` quarters.

**It is the same picture.** Against the analytic sky the whole frame differs
by 0.428/255 where two captures of the *same* build differ by 0.396 - the
bake is inside the capture noise. Pointed straight into the sun, where a
texture would be expected to soften the half-degree disc and its aureole, it
differs by a **maximum of 1/255** with no pixel over 8. 2048 and even 1024
measure the same; 4096 is the default only because it is free.
`?bg=live` evaluates it per pixel again, `?bg=flat` prices it.

### The hero was stuck at half density, and it was a boot transient

The adaptive ladder is supposed to find the densest frame a machine can hold.
It was ending every visit on its **floor** - 0.5, one buffer pixel per CSS
pixel - and the reason was not the machine:

* The frames right after the veil lifts are first draws: empty TRAA history,
  textures landing, every material seen for the first time. Three rungs of
  descent before the show flat's warm had even started.
* A descent sets `prCap` to the rung that missed and pushes `probeAt` out by
  a doubling `probeWait`, so after that opening the ladder was **locked out
  of climbing for twenty seconds, then forty**. The ride was over first.
* And the way back up asked for ninety frames in a row with none over the
  ceiling. At 60 Hz about one frame in twelve misses a flip for reasons of
  the display's own and comes back at 33 ms, so an unbroken run of ninety
  has a chance of about 0.2%. It was never going to happen.

So: the ladder still falls while the page is warming - those misses are real
and a visitor sees them - but it does not *conclude* anything from them, and
`endWarm` hands it a clean slate. The climb is on a clock (`TRY_MS`, 3 s)
and asks only that the recent miss window be nearly clean; a failed try costs
twelve frames at a density that stutters and then backs off, doubling, as
before.

**With the sky baked, it climbs to 3.07-3.78 Mpx** - two and a half times
the pixels it was stuck at - and holds 16.7 ms there. The two changes only
pay together: the ladder could not climb because a transient had locked it,
and there was nothing to climb into until the sky stopped costing a third of
the frame.

| 16 s of the hero | before | now |
|---|---|---|
| frames | 55.6 fps | **56-58 fps** |
| median | 17.6 ms | **16.7 ms** |
| frames over 20 ms | 13% | **3%** |
| **density the hero holds** | **1.44 Mpx** | **3.07-3.78 Mpx** |

*Measure these together.* The density figure above was wrong in an earlier
draft of this file: it was taken from a build where the sky bake had been
lost by a bad patch, so the frame could not afford a higher rung and the
ladder looked like it was refusing to climb. Check `?bg=` is doing what you
think before concluding anything about the ladder.

**What a frame costs cannot be measured on the page's own loop, only tried.**
`dt` reports the display, not the work: a frame that fits comes back at
16.7 ms whether it cost 4 ms or 16. Draining the queue after a frame and
timing it was built and thrown away - the drain's promise resolves on a main
thread parked waiting for the next rAF, so it timed the *scheduler*:
85-91 ms for a frame the rigs measure at 17. Per-pass GPU timestamps do not
work on Metal/Dawn either. Inside `rate()`, the ladder trying a rung and
watching for misses is still the only honest signal. (From OUTSIDE the loop
it can be measured, and `tools/fpsmax.cjs` does - see **Measuring**. That
rig is how the two faults below were found; the ladder itself still cannot
use it.)

#### A dead end: reading the miss as a bracket instead of a cost

Worth recording because the argument is seductive. The descent aims at
`STEPS[ prStep ] * sqrt( FRAME_CEIL / dt )`, and `dt` is the display - so if
the display is quantised, a frame that misses one flip comes back at two
intervals whether it cost 16.8 ms or 33, and every single miss looks like a
frame at 1.8x budget. A frame arriving at `k+1` intervals cost somewhere in
`( k, k+1 ]`, so `dt - iv` is its lower bound and the interval is what to
divide by.

It was built, and it made the hero **drift downward**: 3.07 Mpx to 2.51 to
2.07 over ten seconds, where the line it replaced holds 3.07 flat for a
whole ride.

**The premise is false here.** Pull every per-second median over the ceiling
out of the rides in the scratchpad and they come back 18.6, 19.1, 22.3,
24.6, 40.2, 54.8 - a continuous spread, and **not one of thirty-four within
2.5 ms of a clean 33.3**. This page is not hard-locked to the flip; `dt` is
an honest cost, and `dt - iv` understates it badly - a 22 ms frame reads as
5.3 ms of overrun and asks for one rung where it wants two.

There is a second reason it was wrong, which outlives the first: dropping to
*exactly* the rung that fits leaves the page sitting ON the cliff, missing a
few frames a second, which the ladder then reads as more evidence and walks
itself down. The overshoot the original line produces is the margin. Don't
retry it.

#### The opening is not over when the warm is

A second dead end first, because it is the obvious move and it is wrong.
`endWarm()` clears `prCap`, the probe clock and the miss window but leaves
`prStep` wherever the transient pushed it, which is the floor - so give the
**rung** back too, on the same argument that those frames were not evidence.
Built, measured, off by default (`?warmrung=1`): it is a blind jump, and it
lands at the one moment the page is least able to hold it. The instant the
window closes is the instant misses count as verdicts again, and the opening
is still noisy either side of any fixed deadline. The restored rung missed
within the second, the descent that followed pinned `prCap` to the floor and
doubled `probeWait` to forty seconds, and the hero spent the rest of the ride
at 1.44 Mpx - where simply climbing from where it stood reached 2.51 and held
it. Climbing is evidence-led and self-correcting; a jump is neither.

What does work is three things that leave the climbing alone. The window
ended on the flat's warm, at 2.4 s, and frames do not go
honest until about 5 - textures still landing, no temporal AA history, and
every surface the rail brings round the corner drawn for the first time.
Three descents in seconds 1 to 4, each a verdict, each doubling `probeWait`
to a minute. It ends on whichever is **later** now, the warm or
`WARM_FLOOR` (5 s). `?warmfloor=0` ends it with the warm.

And `STALL` - the ceiling above which a frame is a compile or an upload
rather than evidence - was **200 ms**, chosen when a frame cost 56. At the
rungs this page runs at, dropping from the top of the ladder to the floor
saves about 14 ms, so a frame 95 ms over budget *cannot* be a density
problem: no rung would have fixed it, and reading it as one sent the ladder
to the floor over a single texture landing. It is four display intervals
now, which keeps the genuine 25-33 ms misses and throws out the stalls.
`?stall=` pins it.

And the climb: one rung per `TRY_MS` is right once a rung has been ruled
out, but from the floor to the top is seven rungs, and twenty-one seconds of
a first impression spent climbing buys nothing but the certainty that each
rung held for three whole seconds. Until the first verdict it is `TRY_FAST`
(700 ms); after one, `TRY_MS` as before.

`?ladder=old` puts all three back at once, so the A/B is one flag rather
than three and cannot accidentally test two of them - which is how a dead
end survived two rounds of measurement here before being caught.

**What the three are worth, interleaved, five rounds of a 20 s ride** (four
usable - one round had the machine taken from it). On a quiet machine:
almost nothing, and that is the honest answer.

| 20 s of the hero | `?ladder=old` | now |
|---|---|---|
| fps | 58.1 | 57.7 |
| median frame | 16.7 ms | 16.7 ms |
| p95 | 19.0 ms | **18.8 ms** |
| frames over 20 ms | 2% | 2% |
| mean density over the ride | 2.55 Mpx | **2.85 Mpx** |

The fps difference is inside the noise and the density is worth about 12%.
One of the four rounds had the new arm end on the floor and one had the old
arm there, which is roughly what this ladder's variance looks like.

The **opening** is where they were aimed and where they read cleanest -
seconds 1 to 4, past the veil, median over five rounds:

| seconds 1-4 | `?ladder=old` | now |
|---|---|---|
| frames drawn | 240 | 240 |
| median frame | 16.8 ms | **16.6 ms** |
| p95 | 19.1 ms | **18.8 ms** |
| density | 1.74 Mpx | **1.94 Mpx** |

Higher in four rounds of five, and never lower by more than noise.

Where they pay is the machine that has something else to do - which is the
machine a visitor is actually on, and here was this one with another
session's headless browsers taking the load average to 26:

| the same ride, machine contended | `?ladder=old` | now |
|---|---|---|
| fps | 45.0 | **55.7** |
| median frame | 19.7 ms | **16.8 ms** |
| p95 | 34.5 ms | **22.4 ms** |
| frames over 20 ms | 47% | **11%** |

That is what these three are for: none of them makes a fast machine faster,
all of them stop a slow moment from being read as a verdict about the
machine. A fast machine has nothing to protect; a loaded one had 47% of its
frames outside the interval and now has 11%.

**What the still frame spends.** `msPerMpx` - the number the parked hero's
supersampling budget is divided by - was averaged over moving frames, which
are exactly the vsync-pinned ones: it read ~11.6 ms/Mpx on a frame costing
8.3, and budgeted the parked shot softer than the machine could draw it. It
is taken from STILL frames now, and only from ones that ran over the display
interval, because those are the only frames whose own clock is honest - and
they are also exactly the frame being predicted, AO at full resolution and
all. It reads 9.45 ms/Mpx. At 1600x900 on a 2x display that still leaves the
parked hero at its full 5.76 Mpx with no supersample on top, which is correct:
it already costs 54 ms. `?stillceil=` is the dial if a sharper parked shot is
worth a stickier first hover - the 107 ms frame that cost was a complaint once.

**Occlusion at half resolution while moving: checked, kept.** Full resolution
measured the same frame (17.7 vs 17.8 ms median, same settled rung) because
the page is vsync-bound at this density - but the two pictures differ by
0.488/255 against a 0.44 noise floor, so there is nothing to see for it, and
on a machine with less room it would cost a rung. `?aomove=1` for full.

### Getting the model onto the wire first

`scene.glb` is 10.6 MB and the page could not ask for it until three.js had
come down from the CDN and been parsed: about a second in which the only thing
on the wire was JavaScript, and then the library sat idle while the model
downloaded. The HTML now fetches it itself, in a plain inline script above the
import map, and hands the ArrayBuffer to `GLTFLoader.parse` - the boot bar
reads the stream's progress while it is in flight. On localhost the model is
now on the wire at **12 ms** instead of 1233, and a cold boot measured 3022 ms
-> 2491 ms back to back; over a throttled 12 Mbps link it is worth about
230 ms, consistently, over four interleaved runs. `?glbpre=0` loads it the
ordinary way.

Two other things ride on that: the Draco decoder is `preload()`ed rather than
being asked for after the model has landed - a round trip in the middle of the
boot where nothing else was happening - and `scene_meta.json` is requested
beside the model rather than after it. The CDN gets a `preconnect` and the two
big modules a `modulepreload`, which cannot be resolved against this machine's
run-to-run swing but can only start the handshake earlier.

**What a hovered storey costs.** `tools/hovercost.cjs` pins the density and
switches one thing at a time in a single boot. An open storey is 130 draws and
3.29 M triangles becoming 232 and 8.49 M - the show flat is 5.2 M triangles,
more than the whole city - and that measures **+4.3 ms at 1.93 Mpx, +6.3 at
7.7 Mpx**: a geometry cost, flat across densities. The blurred panels that sit
over the canvas (`#floortag`, `#flatcard`, the solid header) were measured at
the same time, because a css `backdrop-filter` over a live canvas is what cost
this project's sibling 35 ms a frame on the same GPU: here they measure
nothing, on or off.

**Per-pass GPU timestamps do not work on this path.** `tools/gputime.cjs`
turns on `trackTimestamp` (`?ts=1`) and reads the backend's per-uid timestamp
map, labelling each render call by the target it draws into. On Metal through
Dawn the three big passes come back plausible (pre-pass 4 ms, GTAO 8.7, beauty
36) but every small pass reports the same ~34 ms as the frame around it - a
100x56 bloom mip cannot take 34 ms. The rig is kept because the per-call list
and the labels are useful, but the numbers below the big passes are not
evidence. Use `costmap.cjs` for attribution.

**Quality is bought where it is free, not where it is dear.** Three things
were measured for it, and only two of them paid.

*The shadow map earns its resolution.* It is drawn once and kept, so its size
costs memory and one frame of boot rather than frame time - and at 2048 over a
420 m frustum the tree shadows on the facade were a soft blob. At 4096 the leaf
clusters and branches read. It costs **+529 ms of boot and 4 MB**, measured
interleaved, and nothing per frame. `?shadow=2048` goes back.

*A still frame is supersampled.* A parked frame is drawn a handful of times and
then never again, so it is rendered **above** the display's own resolution and
filtered down - real sampling, not sharpening - which the temporal AA then
accumulates. On the sales page a parked hero goes to 11 Mpx against the 1.7 it
sweeps at; window mullions and the neon lettering stop stepping. It waits
`SS_DWELL` still frames first, which is longer than the rail ever holds at the
end of a sweep: supersampling those would buy nothing the eye has time for
while making the frame that RESUMES the sweep four times the work. So it is
the visitor stopping, not the rail pausing, that spends it. The lab is left
at the plain solved density, because the goldens are measured there. `?ss=1`
turns it off.

*Anisotropy did not pay.* The furniture arrives with the glTF and nobody had
ever set a sampler on it, so it was at the loader's default of 1 against the
scanned maps' 8; it is now at the hardware maximum everywhere. Measured, it
changes the Scene 2 frame by **0.01/255** - the shot looks nearly straight
down, so there is no grazing angle to exploit, and the surfaces that are
grazing were already at 8. Kept because it is free and does matter in Fly,
but it is not the quality win it looks like.

*What is left is texture resolution.* In the Scene 2 shot the largest
furniture resolves at **0.7 texels per screen pixel** at 512 - the frame has
more pixels across a cushion than the texture has texels - so there the
texture, not the render, is the limit. `blender/build.py` now exports them at
1024 (2.8 texels per pixel, about +2 MB in the GLB); it takes a Blender
rebuild to land.

**The shadow map is drawn once.** The sun does not move and neither does the
city, so `sun.shadow.autoUpdate` is off and `shadowDirty()` asks for a new map
only when what casts changes - the cut sweeping down, a scene switch, a piece
dragged in developer mode. That alone took the frame from 314 draws and 6.1 M
triangles to 166 and 3.0 M.

**The boot compiles what it is about to draw.** Which pipeline a frame needs
depends on the target it draws into, and this page draws the scene twice, into
the prepass' normal/velocity targets and into the beauty target.
`renderer.compileAsync( scene, camera )` warms neither - it compiles for the
output state - so the old boot spent 7 s on pipelines it then did not use and
built the real ones inside the first frames anyway. Now Scene 1 is set up with
the flat hidden and one frame is drawn behind the veil; that frame is the
warm-up. `?warm=old` and `?warm=none` are kept for measuring.

**Scene 2 is warmed when nobody is watching.** The lab compiles it as soon as
the street is up - nothing is looking. The sales page cannot: its hero sweeps
for ever, so every compile is a stall in the one shot the visitor is certainly
watching, and the warm is long there precisely because a page that draws every
frame leaves `untilIdle()` no idle to find. The page therefore waits until the
hero scrolls off, when nothing draws at all and the compiles are free, with a
20 s fallback for a visitor who never scrolls; clicking the building still
warms on demand, because `setScene( 2 )` asks for it itself. Over the hero's
first fifteen seconds that is a median frame of **16.7 ms with 32 stutters in
824 frames** - which is what `?warm2=0`, doing no warm at all, also measures.

**Scene 2 is paid for in the background, out of sight.** `compileAsync` only
walks visible objects, so the show flat has to be shown to be compiled - and
it used to be shown for the whole warm. On the lab that is a few seconds; on
the sales page, where the rail draws every frame and `untilIdle()` rarely
finds any idle, it ran for tens of seconds, and every one of those frames drew
the furnished flat sealed inside the building where no pixel could reach it:
**266 draw calls and 8.2 M triangles instead of 166 and 3.0 M**. It is now
shown only inside the compile window, between `compiling = true` and the frame
loop being let go again, so no drawn frame ever contains it. The restore is
conditional on the scene not having changed underneath - restoring
unconditionally hid the whole flat if a visitor opened it mid-warm.

**Scene 2 is paid for in the background.** Once the street is up, the show
flat's 24 maps are fetched and its pipelines compiled a couple of objects at a
time, with `untilIdle()` between batches so nothing is ever compiled over a
frame somebody is waiting for. A compile borrows the renderer - it parks its
render context, target and MRT on it - so `compiling` holds the loop off while
one is in flight and compiles never overlap each other; a frame drawn through
a borrowed renderer kills the page with *"Color target has no corresponding
fragment stage output"*.

The maps follow the same idea: every texture is created empty and filled when
its image lands, so the material graphs - and the pipelines built from them -
do not depend on whether an image has arrived. The street's maps are awaited
before the first frame, the flat's are not fetched until Scene 2 is wanted,
and the 2.9 MB plan overlay only when its checkbox is first ticked.

### The first frame does not wait for the show flat

`scene.glb` was 12.52 MB on disk and 9.09 MB on the wire, and the first
frame waited for all of it. But the show flat is not in that frame: it
stands inside the block with `visible = false` until somebody hovers a
storey, and `prepareScene2()` spends the second after `ready` warming it
anyway. Its bytes were being paid for a second before they were wanted.

The partition turned out to be unusually clean, which is what made it safe:

| | |
|---|---|
| street geometry | 7.16 MB |
| flat geometry | 1.77 MB |
| flat images (33) | 2.50 MB — the street uses **none** of them |
| bufferViews shared between the two | **0** |
| materials shared | 8, duplicated as JSON into both files |

Nothing had to be cut in half. Every node is a direct child of
`BuildingRoot` and 1048 of the 2814 are named `flat*`, so
`tools/split_glb.py` walks the tree, keeps one side, and renumbers every
index space — nodes, meshes, materials, textures, images, samplers,
accessors, bufferViews — into a fresh binary chunk. `--check` verifies that
every node name and every primitive of the original turns up across the two
files: 2815 names, 1390 primitives, nothing missing and nothing duplicated
but the one carried root.

| | on disk | gzipped |
|---|---|---|
| `scene-street.glb` | 7.65 MB | **5.71 MB** |
| `scene-flat.glb` | 4.87 MB | 3.60 MB |
| (was `scene.glb`) | 12.52 MB | 9.31 MB |

The HTML asks for the flat only once the street's own fetch has **resolved**,
so the two are never on the link together and the first frame is as early as
it can be. `loadFlat()` then folds it in: `batchInto( root, { flat: 1 } )`,
which is the same weld, the same instancing rule and the same baked pivots
the street got — `optimise()` was split into the part that may only happen
once (making the groups, measuring the cut) and the part that can run again.

Two things follow from the flat being a second file. The Draco decoder is no
longer disposed when the street is done with it, because it has another file
to decode; and `planSetupMaterials()` runs again after the fold, because it
reads `groups.flat`. `scene.glb` is now an intermediate — `build.py` writes
it, `split_glb.py` cuts it, and `.dockerignore` keeps it out of the image.

**The render is unchanged**: Scene 1 differs by 0.464/255 against a 0.427
noise floor and Scene 2 — the flat itself — by **0.901 against its own
0.996**, i.e. below the difference between two captures of the same build.

The one thing this could cost is the hover, which cannot part a wall until
the flat can be drawn - and it does not cost it anything. On localhost the
page appears ~290 ms sooner and the hover arms at the same moment. Over a
throttled link, where the question actually means something (`MBPS=12 node
tools/hoverwait.cjs`, interleaved, medians of two rounds):

| 12 Mbps, from navigation | `?glbsplit=0` | now |
|---|---|---|
| page appears | 10.05 s | **7.52 s** |
| hover armed | 12.78 s | **10.14 s** |
| flat fully open | 14.85 s | **12.15 s** |

**It shipped broken, and the way it broke is the useful part.** The flat's
geometry used to be in the scene from boot, so the only thing that could be
missing was a pipeline - which is what `FLOOR_ARM_MS` is a backstop for:
arm the hover on the compiles, or after 2.5 s, whichever lands first. The
split made that geometry a DOWNLOAD, and opened a window in which
`groups.flat` is empty. At 4 Mbps it was still empty twenty seconds in. The
deadline fired at 2.5 s regardless and the wall parted onto a storey with
nothing in it.

There were two ways in and only one of them was found at first: the hover,
and the storey CLICK, which had no gate at all and does not need a hover -
the fallback cast opens the top floor from anywhere on the block. Both go
through `withFlat()` now, and `flatIn` answers *is the geometry here*
rather than *has it been asked for*. That distinction is the whole bug.

**Every rig here passed the broken build**, because every one of them waits
nine or fourteen seconds before it looks, by which time the flat is long
since in. `tools/flatwindow.cjs` is the one that does not: it throttles the
link, finds the facade by sweeping until the page reports a lit storey,
drives both routes, and shoots *through* the download window, failing on
any frame where the flat is on screen and empty. Two rules it follows that
the first round of checking did not:

* **Run it against the broken build first.** It returns exit 1 and flags
  five frames `EMPTY FLAT ON SCREEN`. A check that has never failed is not
  a check.
* **A vacuous run is a FAIL.** Its first version used a fixed pointer
  coordinate, missed the building entirely - `hot: 0` in every sample, both
  routes - and printed PASS while testing nothing.

The hover arms **earlier**, not later, which is the opposite of what this
file used to predict when it listed the split as "measured but not done".
The reason is that the warm was never waiting on the link: a smaller street
means the first frame, and therefore `prepareScene2`, start two and a half
seconds sooner, and the flat's 3.60 MB comes down during a warm that was
always going to spend a second and a half generating WGSL. The download was
not the hover's critical path - the compiles were.

### Nothing is fetched from anyone else

three.js came from cdn.jsdelivr.net: twenty cross-origin requests - a DNS
lookup, a TLS handshake and a round trip each - and they were FIRST in the
chain, so the page could not ask for the model until they were done.
Measured at **772 to 978 ms of every cold boot** before `starting webgpu`.

It is vendored now, in `web/vendor/three`: three@0.186.1, the two builds, the
eleven addons `app.js` imports, everything those import in turn, and the
Draco decoder's wasm pair - 22 files, 5.2 MB on disk, nothing else from the
16 MB package. `starting webgpu` is at **96-216 ms**, and the page has no
third-party dependency left at all; it works with the network unplugged.

three ships no minified WebGPU build, so vendoring it meant 3.74 MB of
unminified JavaScript. **It is minified here now** - `web/vendor/three-min`,
built by `tools/min_three.sh`, which runs esbuild over each module of
`web/vendor/three` one file at a time rather than bundling them, so every
import specifier survives and the import map is the only thing that
changed. The source tree stays beside it as what the minified one is cut
from, and as the recipe for cutting it again after a version bump.

| the vendored library | source | minified |
|---|---|---|
| on disk | 3.74 MB | **1.11 MB** |
| gzipped, whole tree | 818 KB | **359 KB** |
| `three.webgpu.js` on the wire | 444 KB | **199 KB** |

The bytes matter and the **parse matters more**: it is 2.6 MB less
JavaScript for the main thread to tokenise before a line of the page runs,
and in this browser it took `starting webgpu` from 177 ms to 77 and the
whole boot from 3.5 s to 1.96. The render is untouched, which is the thing
to check and was checked: Scene 1 differs by **0.283/255** against a
0.427 noise floor between two captures of the same build, and Scene 2 by
0.806 against its own 0.996 - both under the noise, i.e. the same picture.

It still **must be served compressed**: 1.11 MB minified is 359 KB
gzipped, and `serve.py` does it. `web/vendor/three/README.md` has the
recipe and the way back to the CDN.

| cold boot, same machine and window | before today | now |
|---|---|---|
| ready | 2.9-3.2 s | **1.88 s** |
| three.js on the wire | 30..474 ms, 20 requests, another host | 5..40 ms, same host |
| the model on the wire | 1233..1246 ms | **12..70 ms** |
| third-party requests | 20 | **0** |

### The fonts are a quarter of what they were

Three faces shipped as TTF and OTF - 375 KB that `serve.py` did not even
compress, because `.ttf` was never in its gzip list - and all of it on the
critical path: `font-display: swap` does not block the first paint, it
repaints when the face lands, and a Georgian headline reflowing a second in
is exactly what a visitor reads as slow.

`tools/slim_fonts.py` does two things before re-encoding as WOFF2:

* **Subsets to what `site.css` declares.** `unicode-range` tells the browser
  when to USE a face, not what to download. Noto Sans Georgian was carrying
  283 Latin glyphs that its own declaration can never reach - the Latin
  inside a Georgian line is picked per character and stays in Jost - so they
  were pure weight.
* **Pins the axes nothing varies.** Noto ships `wght` and `wdth`; the CSS
  asks for `font-weight: 100 900` and never touches `font-stretch`, so
  `wdth` is instanced out at 100.

| | TTF/OTF | WOFF2, subset |
|---|---|---|
| Jost | 134 KB | **39 KB** |
| Noto Sans Georgian | 224 KB | **41 KB** |
| BPG Nino Mtavruli | 16 KB | **12 KB** |
| total | 375 KB | **92 KB** |

The ranges are wider than the page's own copy on purpose, so adding a word
cannot silently fall off the font, and coverage is *checked* rather than
eyeballed: every character `i18n.js`, `content.js`, `site.js` and the markup
can put on screen, routed to the face `site.css` would pick for it, against
that face's cmap. Two glyphs the page sets are missing and always were,
before any subsetting - the back arrow U+2190 and the close cross U+2715 are
not in Jost at all and come from a system font either way.

### The dev server was the bottleneck it was measuring

`serve.py` used `socketserver.TCPServer`, which serves **one request at a
time**. The page's first act is to put the 12 MB `scene.glb` on the wire
(that is what the inline script in `index.html` is for), so single-threaded
it had three.js, `app.js`, the stylesheet, the fonts and all thirty textures
queued up BEHIND the model - the exact opposite of what fetching the model
early is for, and a serial chain no real host would impose. It is
`ThreadingTCPServer` now, with keep-alive, and it gzips `.glb` as well:
the glTF JSON chunk is 1.2 MB of the file, so the model goes **12.2 MB on
disk to 9.3 MB on the wire** for nothing but a header. `.woff2` is
deliberately not in that list - it is Brotli already.

Together with the minified library, the sales page is **18.06 MB over 67
requests down to 14.17 MB**, and the boot from 3.5 s to 1.96.

### The visitor does not wait for any of it

Measured in a real browser rather than a rig - which is the measurement that
counts, and the two are not the same number - the boot is **3.8 to 5.0 s on
the user's own machine** against 1.9 s headless, and ~3.5 s of it is three.js
building TSL graphs and generating WGSL on the main thread. That work is the
materials; it is not going away.

What was going away for free was the picture. The boot veil was a navy panel
with a line of text on it, so for those seconds the page showed nothing of
what it is for. It now carries **the hero's own first frame** as its
background: `web/hero-poster.webp`, 45 KB, captured from this page at the
pose the rail opens on (`node tools/poster.cjs`), under a wash light enough
to see the building through and dark enough to read the progress line on.
The veil lifting is a cross-fade from the building to the same building, now
live - not a reveal.

| in the user's own Chrome | before | now |
|---|---|---|
| first contentful paint | 3.8 s (the veil had nothing in it) | **508 ms** |
| the building on screen | 3.8 s | **508 ms** |
| ready (unchanged) | 3.8 s | 3.8 s |

**Re-run `tools/poster.cjs` whenever the model, the look or the opening pose
change.** The veil cross-fades into the live frame, so a stale poster shows
as a jump - which is exactly how the first attempt was caught: captured with
`?rail=0`, it was the *solved* shot, a different pose from the one the rail
starts on, and the hand-off jumped half a street.

### What is left of the boot, and why

Of the remaining 1.9 seconds, **1.3 is one frame**: the warm-up drawn behind
the veil. Measured apart (`?warmlog=1`), that frame is about **1.0 s of
JavaScript and 0.2 s of GPU** - it is three.js turning every visible
material's node graph into WGSL on the main thread, not Dawn compiling the
result. Two things it is not: the shadow map, whose 420 m frustum submits far
more than the camera can see but which measures out at nothing
(`?shadowwarm=0` prices it), and the pixels, which are a rounding error
against the shader build.

Shortening it means taking materials away, which is the look. Drawing it in
chunks so the boot bar could move was tried and is much worse - every chunk
is another full frame over hundreds of meshes, and one run took 22 seconds.

What can be done about a blocked main thread is to stop the bar looking
stuck: it used to stand at 88% for the longest part of the boot, because
nothing can run to move it. It is handed to the compositor instead - a CSS
transition from 88% to 99% started immediately before the blocking call -
which keeps animating while JavaScript does not.

### The asset pipeline

`build.py` runs `tools/slim_glb.py` after the export. Blender writes the
props' 1k maps back out as PNG - 12 MB of pictures of furniture - and its own
WEBP setting cannot be used, because it silently drops the occlusion/roughness
/metal maps it packs itself and leaves textures pointing at nothing. The
script re-encodes every image as WebP at 512 px, relays the binary chunk and
adds `EXT_texture_webp`, which three reads. Geometry is untouched.

`tools/slim_tex.py` did the same once for `web/tex` and the plan overlay:
colour maps at quality 82, normal and displacement maps at 92, keeping
whichever of the two files is actually smaller (a well packed JPEG sometimes
beats WebP on a noisy normal map, which is why two `.jpg` remain - and that
call was re-checked: WebP needs quality 85 to beat them, and the banding
that leaves in a normal map shows up as facets in the light).

`tools/slim_fonts.py` subsets and re-encodes `web/fonts` (above), and
`tools/min_three.sh` rebuilds `web/vendor/three-min` from
`web/vendor/three`. Both are re-run by hand, not by `build.py`: the fonts
change when the copy needs a character the subset does not carry, and the
library when it is replaced with a new version.

### Measuring

```bash
node tools/perf-rig.cjs --tag try --scene2 --shot   # boot, bytes, pipelines, Scene 2
node tools/fpsmax.cjs index.html                    # what a frame COSTS, off the vsync path
node tools/cputime.cjs index.html 10                # ...and what it costs the main thread
node tools/memcost.cjs index.html                   # ...and what it costs in MEMORY
node tools/flatwindow.cjs 4                         # can a visitor SEE the flat missing?
python3 tools/split_glb.py --check                  # re-cut the model, and verify the cut
node tools/costmap.cjs lab.html                     # where a frame goes, stage by stage
node tools/ridecost.cjs 20                          # the first 20 s as a visitor feels them
node tools/ridecost.cjs 20 1600 900 2 'hover=1'     # ...with a storey held open
node tools/hovercost.cjs                            # what the hover, the flat and the blur cost
node tools/gputime.cjs lab.html                     # per-pass GPU time (see the caveat above)
node tools/orbitcost.cjs 3                          # what a MOVING frame costs, A/B
node tools/gpucost.cjs "" "" 2                      # draw calls and triangles per frame
node tools/smoke.cjs                                # walk every control, report complaints
node tools/walkcheck.cjs 5                          # walk the flat on foot from room 5
node tools/glasstune.cjs /tmp/g '[{"name":"a"}]'    # the hover's glazing, a dial at a time
node tools/shot.cjs perf-shots/try-s1.png           # Scene 1, HUD and wipe out of the way
node tools/shot2.cjs perf-shots/try-s2.png          # the same for Scene 2
python3 tools/imgdiff.py perf-shots/golden-s1.png perf-shots/try-s1.png
```

**A frame's cost can be measured after all** - just not on the page's own
loop, which is what the note above about `dt` is really about. `rate()` sees
the DISPLAY: a frame that fits comes back at one interval whether it cost
4 ms or 16, so the ladder has to climb by trying. `tools/fpsmax.cjs` steps
outside the loop instead - it drives `pipeline.render()` in a tight batch
with no rAF between the calls, advancing the node frame by hand
(`renderer._nodes.nodeFrame.update()`, because `PassNode.updateBeforeType`
is FRAME and a second render inside one node frame draws nothing but the
output quad), then waits on `queue.onSubmittedWorkDone()` and divides. That
is throughput, fully pipelined, and it is free of the display's
quantisation. It is also what `costmap.cjs`'s pixel-ratio sweep has never
been: that one sets the ratio and then measures through rAF, where
`applyScale()` puts it back every frame and vsync flattens whatever is left.
Read `costmap` for its stage table and `fpsmax` for anything about density.

It also prints a stage table and a group A/B at the settled density, but
treat the stage table with suspicion: switching the output node rebuilds the
pipeline, and two batches are not always enough to warm it back up - a run
here read the bloom stage as costing more than the stage after it, which is
impossible. The pixel-ratio sweep is the part to trust; it is monotonic and
repeatable.

What it says, at 1600x900 on the M4:

| pixelRatio | Mpx | ms | fps |
|---|---|---|---|
| 2.00 | 5.76 | 29.3 | 34 |
| 1.50 | 3.24 | 19.8 | 50 |
| 1.25 | 2.25 | 15.8 | 63 |
| 1.00 | 1.44 | 12.1 | 83 |

**4.0 ms per megapixel plus 6.3 ms that is not pixels at all** - which is a
different page from the 9.7 ms/Mpx in the table further up. The sky bake and
the lightless pre-pass took the per-pixel cost down by more than half, and
in doing so they changed what the frame IS: at pr 2 the fixed term is a
fifth of it, but at the rungs the hero actually runs at it is **half**, and
the density ladder can only turn the other half. "The frame is fill bound"
was true when it was written and is now only half true. The fixed term is
the two passes' geometry - ~100 draws and 3 M triangles submitted twice -
and it is the next real lever.

`tools/cputime.cjs` answers the other half of "why 18 ms when the GPU says
12": it is a CDP sampling profile of the live page aggregated by self time.
The answer on this machine is that it is **not** the main thread - 87% idle,
2.2 ms a frame of actual work, with three.js's `updateByType` and
`_renderObjectDirect` at the top of what is left. Worth re-running before
blaming the page's own per-frame bookkeeping for anything.

**`tools/memcost.cjs` is the third of these, and the one that was missing
longest.** `perf-rig` reports `mem`, which is the JS heap - about 370 MB,
and a third of the story. What a visitor sees in Activity Monitor is the
renderer process plus the GPU process, and most of the latter is render
TARGETS, every one of them sized from the current pixel ratio. It walks the
page's states, forces a collection before each sample so the number is what
is HELD rather than what has not been collected yet, and prints the RSS of
every Chrome process beside the targets' own bytes. Measured at 1600x900:

| state | RSS |
|---|---|
| street, just booted | **2093 MB** (renderer 962, GPU 612, browser 198) |
| street, parked 12 s | 1432 MB |
| scene 2 | 730 MB |
| flat, parked 20 s | 639 MB |

The peak is the BOOT, not the steady state, and it is mostly garbage that
has not been collected: forcing a collection at 2560x1440 gives 1219 MB at
the same point. The supersample is not the culprit - it never engaged in
either run. What the boot holds is 12.5 MB of Draco decompressing into 1389
geometries and 3253 accessors before the weld takes them to ~120, with
three.js generating WGSL for 68 materials on top of it. Taking the show
flat out of that file (above) takes 1048 nodes and 832 meshes out of the
peak as well as off the wire.

**Interleave, or be lied to.** The wall clock here swings 30% between page
loads, which is wider than most of the differences worth chasing. Measuring
one build, then the other, said the pre-pass change was worth 38.2 ms against
21.3 - a 44% win that did not exist. Reloading the two alternately, three to
five rounds each, and comparing the median of the rounds said 23.0 against
23.2. `tools/costmap.cjs` boots once and switches configurations inside the
one page for the same reason.

The goldens were **re-baselined** when the shadow map went to 4096, which is a
deliberate look change and moves them by 0.89 on average; the previous pair is
kept beside them as `golden-*-pre-quality.png`.

`perf-shots/golden-s1.png` and `golden-s2.png` are the look as it was before
any of this; **a change that moves them by more than ~0.5/255 on average is a
change to the render, not an optimisation**. Two captures of one build differ
by 0.3, so anything under that is noise. The machine's wall clock swings 30%
between runs - take medians of several, and never judge a setting on one run.

## Scene 2 - the show flat

The second button in the HUD opens the top-floor corner flat: the unit the
bay rhythm puts on the corner, loggia - window - window - loggia, 11.5 m along
the street, with the building's own mass standing full height beside its party
wall. It is not alone up there: the same flat stands four times along the
street and four more times mirrored on the back elevation, and the two lines
meet in the middle of the plan. Block A is 18.00 m deep, so each flat is 9.00
m deep and the two entrance walls stand back to back as one 0.40 m party wall
- a flat 8.40 m deep left 1.20 m of dark fill between them, which from the Top
view read as a grey strip running the whole length of the floor. Its plan
follows the sales render it was built from (`~/Desktop/lpimages/2balcony.jpg`): hall, bathroom, a second
bedroom with its own loggia, the master bedroom, and a living room with the
kitchen along the party wall and the second loggia off it.

**The back line is mirrored, and its furniture turns by `pi - theta`.** Every
procedural mesh is reflected in y once and the linked duplicates go on
sharing it; the downloaded models are *not* reflected, because a reflected
chair is still a chair and reflecting it would cost a second mesh. What the
un-reflected model needs is the right heading, and that is `pi - theta`, not
`-theta`. Reflecting the whole object is the conjugation `My.Rz(t).My =
Rz(-t)`, but `Rz(-t)` is the angle that goes with a mesh that has been
reflected; writing `My = Rz(pi).Mx` and leaning on the one symmetry a seat
has - a chair is its own mirror image left to right - gives
`My.Rz(t).V = Rz(pi - t).Mx.V ~= Rz(pi - t).V`. With `-theta` every piece in
the back line stood a half-turn from where it belonged: the four chairs round
the dining table looked out of the room instead of across the table, the
armchair faced away from the TV and the cabinet faced into the gable wall.
The two chairs that flank the table on the x axis are the case that shows it,
because a reflection in y leaves which *side* of the table they stand on
alone while `-theta` swaps which way they look. Fixed 2026-10-19; Scene 1 is
byte-identical across the rebuild.

`blender/lib_flat.py` builds it in the same local frame as the block and in
the same style as everything else - floors, walls cut at 1.45 m, the loggias
and the gable slot in cut form, doors, furniture, curtains, pot plants - and
then **carves the cutaway**: the merged facade, gable, mass and slot meshes
are bisected on the box the flat occupies, and every face inside it moves to a
`*__cut` object; the loggia and window kit instances of that cell are renamed
the same way. Nothing in the building is modelled twice.

The page sorts GLB nodes into four groups before batching - `main`,
`tower` (block A's own pieces: `A_*`, `winA_*`, `winB_*` and its loggia kit),
`*__cut`, `flat*` - and a scene is largely just which of them are visible, so
Scene 1 stays pixel-identical (measured: the extra group costs 8 draw objects
of 97 and nothing on screen; `?tower=0` is the A/B). `web/scene_meta.json`, written by the build,
carries the flat's centre and axes in the browser's frame: the camera preset
is aimed from it, and the parquet (the PolyHaven *herringbone parquet* scan on
its real 3.4 m tile, with a procedural fallback if the maps fail to load) and
the tiles are laid along those axes rather than the world's, so the chevrons
run into the depth of the rooms and the boards stay square with the walls.
The shot is taken from above the street corner, front-left, so the two
loggias sit nearest and the rest of the building never blocks the view;
Orbit is live in that view. Switching scenes is one choreographed move,
about 4.8 s long. The camera flies from the street shot to the flat shot on
a quadratic Bezier through a high control point over the street, so it
cranes up first and then glides in; its orientation is slerped, and the
field of view and the shift lens ease between the two shots on the same
curve. The cut starts on the click, not when the camera gets there: the
`*__cut` nodes sit in a `ClippingGroup`, and a horizontal clipping plane
sweeps down from the roof to the flat's slab over 3.4 s, slicing the top of
the building away in place, shadow included. So the building begins to come
apart while the shot is still in the street, and the camera arrives into a
flat that is already open. Going back the building closes first and the
camera glides down to the street. Everything runs on small
tweens whose clock starts on the first frame that draws them, and a click
mid-move simply turns the move round from where it is.

### Clicking a storey

Scene 2 is not only the top floor. Every storey of the street front is
already a band the pointer can find - that is what lights a floor and what
the page's floor tag reads - and **clicking one opens the flat on that
storey**: the show flat drops to it, the camera frames it, and the floors
standing over it come off from the top, in the same movement and the same
seconds as the roof always did.

The top floor could do this with the pre-split `*__cut` cells alone, because
there is nothing above it. A fifth storey cannot: four more floors and a roof
stand in the way, and none of them are pre-split. So block A gets a second
clipping plane of its own. `groups.tower` is a `ClippingGroup` holding every
piece of the block, `groups.cut` hangs underneath it - nested clipping groups
union their planes, so the top-floor cells answer to either - and
`towerPlane` sweeps from above the parapet down to just under the clicked
storey's slab. Everything is measured from the top floor, which is where the
build fitted the flat and where `scene_meta.json` is written, so one offset
of whole storeys carries the flat, the camera and the plane together
(`floorDrop`, `towerCut`, `placeFlat` in `web/app.js`).

The top floor keeps its plane parked at 1e4 and is taken by `cutPlane` as it
always was, so that shot does not move: measured at 0.65/255 mean against the
same shot built without any of this, which is TRAA noise. A click that lands
on the block but on no storey - the podium, the shopfront, the roof - opens
the top floor, which is what every click on the building did before.

The page follows: `lp:scene` now carries the storey, and the hero's flat card
names the corner unit on it rather than the tour's own. `window.LP.setScene(
2, floor )` does it from outside, `window.__storey( n, view )` from the
console or a shot script (`n` of 0 goes back to the street, and `view` of
`'plan'` opens the floor view the way a click on a storey does - the only
way a headless browser can aim at one).

## The sales page

`web/index.html` is the landing page the building is actually sold from:
the hero, the key numbers, the project, the location, a live flat picker,
the 3D tour, the amenities, prices with a payment calculator, the gallery,
the developer, the FAQ, the enquiry form and the footer.

**The scene is the hero.** One fixed canvas sits behind the whole document;
the hero is the stretch of page that lets it through, every section below is
opaque and scrolls over it, and once the hero is gone the canvas is hidden
outright so it costs nothing to composite. There is no second renderer and no
iframe - `index.html` and `lab.html` load the same `app.js`, and the page
simply sets `data-embed="1"` on `<body>`.

Three things are different under that flag, and nothing else:

- **The shot is closer.** The lab holds the camera exactly where the
  photograph was taken. The page dollies it 34 m straight up the street and
  keeps 0.34 of the lens rise instead of the solved 0.729 - same eye height,
  same lens, same direction, so the framing is the solved one with the
  building filling it rather than sitting along the foot of a frame that is
  86% sky. `?push=0&rise=0.729` puts it back for an A/B.
- **You can walk.** The fly controls are live from the first frame: drag to
  look, `WASD` to move, `space`/`C` for height, *reset shot* to put it back.
  They are built with options the lab does not use - the wheel is left to the
  page, because a hero that swallowed the scroll would trap you in it; the
  keyboard is released whenever the focus is in a form field or the hero is
  scrolled away; and a soft bound keeps a walk from wandering off the
  modelled block.
- **A click on the building opens the show flat**, which is the same
  choreographed move as the lab's Scene 2 button.

With the console open the camera says where it is while you fly it - throttled
on the way, and once more the moment it stops:

```
fly      pos 0, 1.65, -36.89   look 0, 1.65, -46.89   yaw 0°  pitch 0°   fov 67.7  shift 0.34
settled  pos 0, 1.65, -43.99   look 0, 1.65, -53.99   yaw 0°  pitch 0°   fov 67.7  shift 0.34
```

That `settled` line is the one worth keeping: it is printed in the numbers
`heroPose()` and `flatPose()` are written in, so a shot found by flying can be
typed straight back into the source. `window.LP.pose()` returns the same thing
as an object, and `?flylog=0` silences it. It applies wherever the fly camera
is live, so the lab's **Fly** mode prints it too.

**The flat filter sits on the fold.** The rooms, availability, floor and price
controls are a band across the foot of the hero rather than a bar above the
grid, so the whole inventory is one slider away before the visitor has
scrolled anywhere. There is only one set of controls on the page - the picker
further down reads the same ids - and the legend above the grid carries a
*change filters* link back up to them. Below 1100 px the band becomes a single
row that scrolls sideways under a fixed end cap, so nothing is taken away from
a phone and the hero keeps its height.

**Neither file imports the other.** The scene announces what it is doing on
`window` - `lp:ready`, `lp:scene`, `lp:mode` - and takes instructions through
`window.LP`. The page carries none of the lab's chrome, so every control is
looked up through a stub that answers for a missing element and does nothing.

### Georgian, and the capitals

The page opens in **Georgian** - this is a building in Rustavi - with an
`ქარ / Eng` pair in the header. `?lang=en` overrides it, which is what the
shot rigs use, and whatever a visitor picks is remembered.

**The key is the English.** index.html still carries the prose and is still
the source of truth; `web/i18n.js` maps its markup, whitespace collapsed,
to the same markup in Georgian. No `data-t` attributes anywhere, nothing to
keep in step by hand, and a key that stops matching - because somebody
edited the English - falls back to the English, which is the safe way for a
translation to fail.

**Whole elements, not text nodes.** Half the sentences here have a fact in
the middle: *"\<project\> is a finished residential building by LP Group in
\<district\>"*. Translated a fragment at a time that comes out as Georgian
words in English order, because Georgian does not put the pieces where
English does. So the unit is any element with text of its own - its markup,
its `data-v` spans and all - its subtree belongs to it, and the Georgian
side is free to move the slots. `fill()` runs afterwards and drops the
facts into wherever the Georgian put them. Strings the page *builds* rather
than writes go through `t()` and `tf()`, where the template is the key and
`{n}` is a slot: `'Floor {n}'` is `'სართული {n}'`.

Order is the whole of it, and it is why `language()` runs **first**, before
anything else has written to the document: `fill()` stamps `data-ph="1"`
onto every fact that is still a guess, which changes the markup, so a key
captured afterwards never matches again. That cost an hour.

**Mtavruli is a font here, not a case change.** BPG Nino Mtavruli is a
legacy face: it draws capitals at the ordinary Mkhedruli code points and
has nothing at the Mtavruli block Unicode 11 added. That is what makes it
work without touching a character - the page keeps its Georgian in
lower-case Mkhedruli, which is what copy, search and a screen reader want,
and the font draws the capitals. `applyTitleFont` marks exactly the
elements whose computed style says `uppercase`, because the design has
already decided there what a title is; fifty-five rules set it and a
hand-written list of them goes stale.

Going the other way - `toUpperCase()` *does* map Mkhedruli to the Mtavruli
block - would push every title off this font and back onto Noto. And CSS
cannot do it at all: `text-transform:uppercase` leaves Georgian alone on
purpose, since the language has no running capitals.

Every face is picked **per character**, through `unicode-range`: Nino
claims the Georgian letters of a title and nothing else, so the Latin
beside it in the same line - LP GROUP, REHAU, m² - stays in Jost and a
mixed headline still reads as one headline. An English page downloads
neither Georgian face.

One thing a language switch turned up: `prices()` and `gallery()` **append**
rather than replace. That was invisible while they ran once; run again for
the other language and the old cards stood beside the new ones.

### What to edit

`web/content.js` is the only file that has to change to put the real project
on the page: names, contacts, distances, prices, the fabric and the inventory. `index.html` carries the prose; anything written
`data-v="key"` there is filled from `SITE`, so the phone number lives in one
place and appears in six.

Values that were not known when the page was built are wrapped `ph( ... )`.
They render normally, so the page always looks finished - but **`?ph=1` rings
every one of them in amber**, which is the checklist of what is still a guess
(30 of them at the time of writing). Replace the value, drop the wrapper.

The inventory is generated rather than typed: six flats to a floor over the
twelve the fit gives, with areas and prices seeded off each flat's own number
so the list is identical on every reload and a link to a flat still points at
that flat. The flat the 3D tour opens is pinned to the 77.7 m2 corner unit the
sales office advertises. `STATS` is derived from the list, so the page's "72
flats, 17 still available" can never disagree with the grid under it.

Gallery photographs go in `web/photos/`, named in `SITE.gallery`. A tile that
finds no file draws a captioned plate instead, so the grid is never a row of
broken images while the photographer is still out.

The enquiry form has no back end: it logs the enquiry and shows the thank-you.
`site.js` marks the one place to point at a CRM, a form endpoint or a webhook.

### The look

The palette is lifted off the brand's own post - cream paper, deep navy ink,
an amber accent, a sand gradient - and the type is the brand's Jost, with Noto
Sans Georgian beside it for the Georgian name. Both ship from `web/fonts/`
under the SIL OFL.

The layout is rectangular on purpose: nothing is rounded, nothing carries a
shadow, and blocks are ruled apart by hairlines rather than floated on cards.

Everything sits on **one twelve-column grid**. The faint rule behind the page
is that grid - drawn at each track's leading edge, gapped exactly like the
content - so a rule line only ever falls where a column starts, and the three,
four and six column blocks all land on it. A section head is two blocks on one
row of it (headline on columns 1-6, the paragraph set against 8-12) rather than
a stack down the left, which is what left the right half of every section
empty; `.split` is 1-5 and 7-12, and the flat picker is 1-8 with its sidebar on
9-12. Where a block already has rows of its own - the FAQ, the floors, the
tick list - it is opaque, so the rule does not read as an accidental table.

Two things to know if you move blocks around. The rule is an absolutely
positioned grid child, so it takes no track but **`:nth-child` still counts
it** - placement is written `.split>*:not(.rules)~*:not(.rules)` rather than
`:nth-child(2)`. And that sibling form out-specifies a plain stacking
override, so the narrow-screen rules repeat it.

```bash
node tools/sitecheck.cjs          # boot the page, shoot every section, report
node tools/sitecheck.cjs "?ph=1"  # ... with the placeholders ringed
```

## Controls

These are the lab's (`/lab.html`). The sales page has only the fly camera and
*reset shot*.

- **Hero** — the solved shot, locked to the reference framing.
- **Click a storey** — hovering the facade lights a floor; clicking it opens
  the flat on that floor and takes the storeys above it off from the top.
  Clicking the block anywhere else opens the top floor.
- **The floor view** — looking down on the opened storey, drag to slide along
  the row, and hover a flat to furnish it: the storey is drawn flat in ink and
  amber with its areas on badges, and the flat under the pointer comes back as
  a room, a piece of furniture at a time.
- **Orbit** — drag to orbit, wheel to zoom, right-drag to pan.
- **Fly** — drag to look, wheel to zoom, `WASD` to fly, `space`/`C` for height,
  `shift` to sprint.
- **Inside a flat** — click a room's dot and the same keys become legs:
  `WASD` walks at 1.35 m/s with `shift` for a brisk 2.45, the head bobs with
  the stride, walls and furniture stop you, and each of the four doors swings
  open as you come to it. `space`/`C` do nothing in there — you are standing
  on the floor.
- **Compare wipe** — drag the handle to wipe between the photograph and the
  render. The image is pinned to the same rect as the canvas, so the two line up
  pixel for pixel.

Orbit and Fly drop the lens shift, since a shifted lens is confusing once you
start pitching. *Reset shot* puts it back.

**On the sales page the street is not a camera.** The hero is the solved
shot - the photograph the whole model was built to match - riding its own
slow rail, so scene 1 takes the drag and `WASD` away entirely and the only
thing the pointer does there is click a storey: a pointer cursor over the
ones that open, nothing over the sky. Letting a visitor drag that framing
off the building was giving away the one picture the page sells with.
`flyApply` is the single place that decides it, and the rail only lets go
for somebody who can actually take the camera - otherwise a click that
missed a storey froze the sweep for the nine seconds of `RAIL_IDLE`.
Everything in scene 2 keeps both: the flat is something to look round, the
floor view slides under the drag, and inside a room they are legs.

## Matching the photograph

`index.html` and the reference are compared numerically, region by region,
after every change. Measure facades on the **median**, not the mean: the mean
of any facade box is dragged up by the windows, and that masked a gable that
had been painted the same near-black as the street wall (0.26) and a facade
running 1.76x bright.

Current state (render ÷ reference):

| region | ratio | |
|---|---|---|
| whole frame | 1.00 | |
| podium | 1.02 | |
| asphalt, mid | 1.04 | |
| west gable | 0.93 | |
| near tree | 0.91 | |
| sky, zenith | 0.88 | not blue enough; B 138 against 165 |
| asphalt, clean | 1.18 | still a little light and cool |
| sky, horizon | 1.18 | haze band too strong |
| far tree | 0.70 | partly haze in the photograph |
| dark facade | 1.66 | see below |

The roofline of the main facade sits within about 1 px of the photograph across
its whole length.

Two things are known to be out and are not colour problems:

**The facade is a pale grid where the photograph is dark plaster.** 33% of the
render's facade pixels fall below luminance 60 against 56% in the photograph,
while the bright end matches (p95 141 against 158). The light concrete is the
right tone - the loggia interiors measure 1.0 after correction - there is just
too much of it. That is bay proportion, not material.

**Dark surfaces floor at about luminance 46** where the photograph reaches 34,
and the floor does not move when the albedo does: dropping `plaster_dark` from
#241f1a to #18140f, a 40% cut in linear, moved the facade median by 2%. Suspect
the 0.04 specular against a bright sky, the GTAO ambient term, or AgX lifting
the shadows - worth isolating before any more albedo is spent on it.

The sky is deliberately left alone. It feeds the IBL through PMREM, so moving
it re-lights every surface and invalidates every number above.
