# The real-plan rebuild: who writes what

The building is rebuilt from the architect's plans (`plans.pdf` ->
`tools/plan_extract.py` -> `plan.json`). Several pieces of work meet at the
names and files below, so they are fixed here and nowhere else. If a piece of
work needs something this file does not give it, it adds a line HERE and says
so in its report - it does not invent a private convention.

## Frames

* **Plan frame** (everything in `plan.json`, `plan_meta.json`, `flats.js`):
  metres, origin = axis `a` x axis `1` at +0.000, `x` along the lettered axes
  (a -> J, 0 .. 82.5), `y` along the numbered axes (1 -> 10, +y = the street
  side the shopfronts face), `z` up = the level label (+8.100 -> 8.1).
* **Blender local frame under `BuildingRoot`**: `(x, -y, z)` of the plan frame.
* **Browser world frame**: whatever `BuildingRoot` + the glTF export make of
  it. `web/scene_meta.json -> frame {origin, ex, ey, up}` gives the plan
  frame in browser world coordinates: `world = origin + ex*x + ey*y + up*z`.
  The page converts plan metres with this and nothing else.

## Blocks, levels, cores

* **Block A** = everything west of the expansion joint (axes a..i, x < 44.4).
  **Block B** = everything east of it (axes k..J) *including the wing*.
  (The owner has been told this is the assumption; it is one constant to flip.)
* **Levels** use the ids in `plan.json`: `P-1` (-3.0), `L00` (0.0,
  commercial), `L01` (+4.8, offices + podium terrace), `L02`..`L10` (the nine
  residential floors, +8.1 .. +34.5, 3.3 m each; "floor 1".."floor 9" to a
  buyer is `L02`..`L10`), `ROOF` (+37.8; stair heads +40.2).
* **Cores** `C1` (block A, axes g-d), `C2` (block B bar, axes n-o), `C3`
  (wing). Their entrance halls at grade are part of the cores.
* **Flats** are identified by the plan's own number as a string: `"37"`,
  `"47-a"`. 191 units are drawn. Numbers the plan skips are not invented.

## Files

| file | written by | holds |
|---|---|---|
| `blender/plans/plan.json` | `tools/plan_extract.py` | the drawing, in plan metres |
| `blender/plans/rooms.json` | `tools/plan_rooms.py` | per flat: room types and the furniture the plan draws |
| `web/scene-street.glb` | `blender/build.py` | the exterior: both blocks' envelopes, podium, terrace, city. No interiors |
| `web/scene_meta.json` | `blender/build.py` | `frame`, `site {center, bbox, hero}`, `levels[]`, `blocks[]`, `facades[]` (+ legacy keys while the page still reads them) |
| `web/interior/<LEVEL>.glb` | `blender/build_interior.py` | one level's interior: walls, floors, doors, loggia floors, corridor (`L00`, `L01`, `L02`..`L10`) |
| `web/interior/cores.glb` | `blender/build_interior.py` | the three cores full height: stairs, landings, lift shafts and cars, entrance halls |
| `web/plan_meta.json` | `blender/build_interior.py` | per level: flats (polygon, label point, doors, rooms), corridor, nav (walk polygons, solids, stair ramps, lifts), cores - in plan metres |
| `web/flats.js` | `tools/gen_flats.py` | the sales inventory generated from `plan.json`: one record per real flat (`FLATS`), `OFFICES`, `BUILDING` counts, `ISSUES` (every table-vs-drawing decision) |
| `web/flatplans.json` | `tools/gen_flats.py` | (added by inventory) per flat number, a light 2D drawing for the flat's card: outline `o`, rooms `r`, balconies `b`, entrance `d`, windows `w`, plan metres |

**The page <-> scene seam (added by inventory).** A flat's polygon id is
`<LEVEL>-u<n>` (`L03-u37`, `L05-u74-a`; offices `L01-o7`), the same `u<n>` the
interior node names use. Events the scene sends the page carry `level`
(`'L03'`) and, for one flat, `n` (`'37'`) and/or `poly`; the page also accepts
the legacy `floor` storey number while the old scene is live. The page calls,
if present: `LP.openFlat(n)` (open flat n in 3D; returns truthy if it did),
`LP.openLevel(level)` (the floor view of a level), `LP.showFlat` (getter: the
number of the flat the 3D tour is standing in). All optional: the page works
without them.

## Node names

* Exterior envelope pieces start `A_` or `B_` by block (windows, loggias and
  their frames/glass/rails included); podium, terrace, street and city keep
  their present names. Nothing in the street file starts `flat` or `in_`.
* Interior pieces: `in_<LEVEL>_<kind>__<material>` for what belongs to the
  level (corridor, slab), `in_<LEVEL>_u<flat>_<kind>__<material>` for what
  belongs to one flat (`in_L03_u37_walls__int_wall`), cores
  `in_<CORE>_<kind>__<material>`. A hinged door leaf ends
  `_swing__<material>` and its hinge is in `plan_meta.json`.
* Materials: **only names `web/materials.js` already maps.** That file is the
  owner's and is not restyled. A genuinely new name is appended at the end of
  its `int_*` block and reported.

## Things that are not negotiable

* The owner's exterior look: black plaster body, white only inside the
  balconies, the existing glazing/frames, sky, sun and shadows. Geometry
  moves; the look does not.
* Never `gltf-transform dedup` (the page styles by material name).
* `build.py`'s parenting to `BuildingRoot` leaves `matrix_parent_inverse` at
  identity.
* No interior geometry is shown before its file has arrived ("is the geometry
  HERE", not "has it been asked for").

## Interior ↔ exterior seam (added by the interior build, `blender/build_interior.py`)

* **Who builds which wall.** `EXT` = the wall poche of a level within
  **0.25 m** of the outside or of a balcony / loggia / terrace polygon. The
  street file owns `EXT` (body, reveals, sills, heads, glazing, balcony
  backs and cheeks). The interior files build the rest of the poche, full
  storey height (z .. z+h), plus a **lining** of `EXT`: the part of it within
  0.06 m of a room / corridor / hall, grown 0.012 m into the room, so the
  street file can extrude all of `EXT` without z-fighting. In exterior
  openings the lining is cut at **sill +0.90 / head +2.40** above the level
  (balcony and loggia doors 0 / +2.40, street doors 0 / +2.10). The street
  file never builds a wall face that faces a room.
* **Heights.** Finished floor = the level's z. Room ceilings at
  z + h − 0.30 (residential/office 3.00 clear, L00 4.50). Interior balcony /
  loggia floor tiles have their top at **z + 0.02**; the street file keeps
  any balcony slab top it builds at or below z. Inside the outline the
  street file builds no floor slab or ceiling (the interior files carry
  floors 0.30 thick where they can be seen edge-on, at stairwells).
* **Owner token.** `in_<LEVEL>_<owner>_<kind>__<material>` with owner
  `u<flat>` (a flat), `o<n>` (an L01 office), `C1|C2|C3|podium` (an L00
  entrance hall / the podium stair hall, built in `L00.glb`). Level-owned
  pieces (corridor, party walls, commercial floor) carry no owner token.
* **Door leaves.** One node per leaf, `..._d<k>_swing__<material>`; the node's
  origin is the hinge at floor level and its rest rotation is the shut
  heading. `plan_meta.json` doors: `hinge [x,y]`, `w`, `shut` (plan-frame
  degrees from +x toward +y), `open` (signed degrees, same sense). The plan
  frame is a mirror of the Blender/browser frame, so a plan angle θ is −θ
  about Blender +z (= three.js +y). Balcony/loggia doors get a glazed leaf
  in the interior file.
  The street file builds each loggia's DOORS where those leaves are
  (`lib_building.BALC_DOORS`, read from `web/plan_meta.json`: back wall and
  cheeks) and makes the rest of the opening window - so run
  `build_interior.py` before `build.py` when a plan changes, then
  `python3 tools/lgdoorcheck.py` (expect 506 ok, 4 NO_OPENING).
* **Cores** (`cores.glb`): `in_<CORE>_stair_<LEVEL>_<kind>__<mat>` per storey
  (the storey that starts at LEVEL), `in_<CORE>_lift<k>_car__metal_dark`
  (one car per shaft, parked at L00, origin at the car floor),
  `in_<CORE>_lift<k>_<LEVEL>_door__chrome` and `..._door2__chrome` (the two leaves of a closed landing door; they part in the middle - build 5 lift kit, which also adds the static `_frame__`, `_call__`, `_ind__`, `_led__` nodes of every landing; the page does NOT draw `_led__` nor the car's display/arrow dots - app.js `liftKit` draws them live on the `_ind__` / car `int_black` glass, with the car's own doors and the call lamps),
  `in_<CORE>_head_<kind>__<mat>` (inside of the stair head, +37.8 .. +40.2).

## rooms.json conventions (added by the rooms pass)

* Furniture: `centre [x, y]` plan metres, `size [width across heading,
  depth along heading]`, `heading` = degrees of atan2(dy, dx) of the
  direction the piece FACES (bed head->foot; sofa/WC/basin/TV/worktop away
  from the wall behind it; chairs towards their table/desk). Corner
  bath/shower glyphs carry `box_axis_aligned: true` and `size = [dx, dy]`.
* Room `area` = its share of the flat fill (walls split down the middle,
  sums to the flat); `area_net` = free floor. `stance.eye` z is 1.6 above
  the level's floor - add the level z.

## Exterior node names and scene_meta (added by the exterior stage)

* Envelope, one storey of one block: `<B>_wall_<LEVEL>` (dark plaster,
  `plaster_dark`), `<B>_gable_<LEVEL>` (the light west gable, `plaster_light`),
  `<B>_lgfloor_L01` (pale floors under the lowest loggia row). `<B>` is `A`/`B`,
  `<LEVEL>` is `L01`..`L10` (`L01`, the office storey, is built from `L02`'s
  facade data - the renders show it wearing the residential facade).
* Windows and loggias are linked duplicates of hidden kit sources
  (`kit_wn<w>x<h>_*`, `kit_sl..` gable slots, `kit_lg<op>x<depth>[c][l|r]_*`),
  named `<B>_<LEVEL>_wn<NNN>_<part>`, `<B>_<LEVEL>_sl<NNN>_<part>`,
  `<B>_<LEVEL>_lg<NNN>_<part>`; NNN is a running index over the whole build,
  part is `glass|lit|frame|sill|mullion|reveal|shell|rail|parapet|louvre`.
  So `/^A_L03_/` is every opening of block A on L03, and `/^[AB]_(wall|gable)_L03$/`
  its walls.
* Whole-block pieces: `<B>_slab_L01`, (`<B>_mass`: gone since build 3, see below), `<B>_roof`, `<B>_parapet`,
  `<B>_gable_parapet`, `<B>_stairhead`. The 0.1 m shadow gap at the joint
  (x 44.35..44.45) is backed by a filler inside `B_wall_<LEVEL>`/`B_parapet`.
* Podium: `podium_shell`, `podium_fascia`, `podium_glass`, `podium_interior`,
  `podium_mullions`, `podium_lobby_glass|frame`, `podium_entrance_doors`
  (metal frames + shut glazed leaves), `podium_entrance_door_glass`,
  `podium_entrance_canopy`, `ramp`, `ramp_walls`. The podium's solid body
  leaves the three entrance halls (L00 `cores` C1, C2, C3) and the terrace
  stair empty for the interiors; the doors are at `scene_meta.cores[].entrance`.
* `web/scene_meta.json` (written by `blender/build.py`, only on an export
  run or with `--meta`): `frame {origin, ex, ey, up}`, `site {center (world),
  bbox {plan, z}, hero {eye, at, plan_eye, plan_at}, rail {a, b} (world),
  boundary (plan)}`, `levels[] {id, z, h, kind, res}` (`res` = 1..9 for
  L02..L10, else null), `blocks[] {id, footprint (plan), roof_z, parapet_z,
  levels}`, `facades[] {block, a, b, out, z0, z1}` (the tower's face lines =
  the roof outline's edges, split at the joint, plan frame; z0 4.8, z1 37.8),
  `cores[] {id, block, entrance {door [x,y] plan, z, out [nx,ny], heading
  (deg, the way IN, plan frame from +x towards +y), world, w, h}}`.
  Legacy, read by app.js until replaced: `block {corner, center, floors}`,
  `flat {...}` (see the exterior report for which of these are fiction).

## Furniture (added by the furnish pass, `blender/build_furnish.py`)

* `web/interior/furn/<LEVEL>.glb` (`L01` offices, `L02`..`L10`): the pieces the
  sheets draw, in the same frame as `web/interior/<LEVEL>.glb`. One node per
  piece, `in_<LEVEL>_<owner>_furn_<kind><k>__<material>` (owner `u<n>` / `o<n>`,
  kind = the rooms.json symbol kind, plus `sink` / `hob`, which are NOT on the
  sheets and come with the kitchen-run module). The node's origin is the
  piece's foot (footprint centre, floor level) and its rotation is the drawn
  heading (plan θ -> -θ about Blender z); pieces are instances of one mesh per
  (kind, 5 cm size class) and are never mirrored. A mesh may carry more than one
  primitive; the node is named after its main material, every primitive after
  its own (all mapped in materials.js; `dining_chair_02` is the only one with UVs).
* `web/interior/furn/index.json`: `levels[L].units[n] {token, type, layout_group,
  kit_group, pieces[{node, kind, room, room_index, box, at, rot, drawn, order}]}`
  (`room` = rooms.json room id; `order` = reveal order: by room, largest first).
* `vent_duct` is architecture, not furniture: never in these files.

## Street doors, terrace stair, wall depth (added by the exterior review, build 2)

* **Street doors** follow `plan_meta.json` `portals[]` (read by
  `lib_city.ENTRANCES` at build time). Each door's shut leaf is its own pair
  of nodes, `podium_door_<id>_leaf` (`metal_dark`) and
  `podium_door_<id>_leaf_glass` (`glass_window`), `<id>` = `C1|C2|C3|podium`;
  frames and canopies stay in `podium_entrance_doors` / `_canopy`. They are
  stand-ins: the page hides them once `interior/L00.glb` is in, and the
  hall's own leaf (C1, C2) or none (C3, podium: open runs) takes over.
  Door head +2.10, leaf plane 0.10 m in from the portal line.
* `scene_meta.site.entrances[]`: `{id, door [x,y], z, out, heading, world,
  w, h, interior_leaf, street_leaf [node names]}` for all four, the terrace
  stair included (`cores[]` keeps C1..C3 with the same `entrance` keys).
* `scene_meta.site.hero_candidates{name: {eye, at (world), plan_eye,
  plan_at, hfov (deg across 16:9), shift, pan}}`: alternative opening shots
  for the owner; nothing reads them yet.
* **Terrace stair house** (`terrace_stairhouse`, `_lining`): hollow, round
  the hole the street file leaves in the +4.8 deck over x 19.15..21.85,
  y 29.05..33.30; its door opening is L01 `d10` (x 19.40..20.79, head +2.10).
* **Wall depth.** The street's facade leaf is 0.19 m from the face line, loggia
  back walls 0.19 m, glass back face 0.215 m: all inside the plan's 0.206 m
  poche + the interior's 0.012 lining, so a room never sees the street wall.

## The page's side of the levels (added by the levels stage, web/app.js + web/levels.js)

* `web/rooms_lite.json` (`tools/gen_rooms_lite.py`, from `rooms.json`): per
  flat number (offices `o<n>`), per rooms.json room `id` = plan_meta
  `rooms_id`: `[label x, label y, eye x, eye y, eye z, look x, look y, look z,
  name_ka]`, z above the level floor. The page prefers `label` / `stance` /
  `name_ka` on a plan_meta room if the build ever writes them there.
* Interiors are welded by the page per level and material, with the owning
  unit's place in its level (plan_meta `flats` then `offices`, from 1; 0 =
  level-owned) baked per vertex as `aunit`. Swing leaves are welded apart
  and stashed with their plan_meta door record: `hooks.doorsOf( level )`.
* Seams for other web modules, all in `web/levels.js` `hooks`:
  `onFlatReveal( level, n, amount )`, `onLevelShown/onLevelHidden( level,
  group )`, `onRoom( level, n, room|null )`, `shown()`, `groupOf( level )`.
* The floor view cuts every level at `z + 1.45` and caps the cut with
  plan_meta `nav.solid` in ink - so `nav.solid` must keep covering the
  street file's outer walls (EXT) as it does now.

## Exterior, build 3 (added by exterior-polish)

* **No block mass.** `<B>_mass` is no longer in the street file. It stood
  inside every flat (a room's strip along the facade lay outside it, and its
  faces read as a black wall across the room from there). It hid nothing from
  the street, because all glass is opaque. `LP_MASS=1` builds it again.
  Nothing on the page addressed it.
* **L01 loggias that stand inside an office** (the L01 sheet draws office or
  corridor where L02's copied facade has a loggia) use a *one-way* kit,
  `kit_lg<op>x<d>[c][l|r]o[g<NNN>]`. Every face that only a room would see is
  left out: the back of the back wall, the glass and frames, and the outer sides
  of the cheeks. The page culls back faces, so seen from the office the loggia
  is a bay of the room, while from the street nothing changes. `g<NNN>` is an
  open doorway in the back wall where an L01 `common` door leads through it
  (today only `d9`, the wing's corridor door onto the terrace). Node names are
  unchanged: `<B>_L01_lg<NNN>_<part>`.
* **Windows added on L01's glazed runs** (where the sheet's run meets the
  copied facade's plain wall) are `<B>_L01_wn9NN_<part>`, numbered from 901 so
  that no other window's name moves. Their lit state comes from their own
  random sequence.
* **Entrances.** Each street door has a dark steel portal and a cantilevered
  canopy (inside `podium_entrance_canopy`), a pale plate over the door
  (`podium_entrance_plates`, `frame_light`) and its label in geometry
  (`sign_entrance_<id>`, `metal_dark`: "1", "2", "3", "TERRACE").
  `scene_meta.site.entrances[]` gains `label` and `sign`.
* **Terrace.** Kit placements are `terrace_planterNN_*`, `terrace_tubNN_*`,
  `terrace_cafeNN_*` and `terrace_pergolaNN_*` (parts per material), plus the
  merged `terrace_lawn`, `terrace_channel`, `terrace_channel_grate`,
  `terrace_sails` and `terrace_frames`. `terrace_planters` is now only the
  parapet hedge box. `scene_meta.site.terrace {z, solids [[x0,y0,x1,y1]..],
  trees}` gives, in the plan frame, every footprint standing on the +4.8 deck,
  for the walk to collide with. plan_meta's `nav` does not carry them. The
  promenade (y 23.8..28.6), the stair-house door's apron and the d9 forecourt
  (x 55..61.85, y 18.6..28.6) are kept clear.
* `fg_branch` / `fg_branch_leaves` are gone (no view had them in frame).
* New material names in the street file: `int_wood_oak` and `soil`. Both are
  already mapped in materials.js and are procedural (no maps).

## Build 3 interior fixes (added by interior-fix, `blender/lib_plan.py`, `tools/plan_extract.py`)

* **L00 hall walls drawn as outlines.** The +0.000 (and -3.000) sheets draw
  the cores' inner walls as pairs of 0.708 outlines with no poche fill.
  `plan_extract.hall_partitions` adds them to `walls.poche` of the open levels
  (inside the cores, clipped to the outline; `walls.from_outlines_m2` says how
  much). `facade` and `walls.segments` are still computed from the filled
  poche only, so the street file's reading of the facade is unchanged.
* **Doors drawn as one path with two swings** (the C2 lobby double door on
  every storey, a commercial street door at x 47.7..49.1) and the terrace
  stair's street door (drawn in the shopfront colour, read inside the cores
  only) are now in `plan.json` `levels[].doors`.
* **`plan_meta.json` `portals[]`** gain `doors` / `nodes` (every leaf of the
  portal: a double door has two), and `made: true` when the sheet draws no
  door there. `door` / `node` stay (the first leaf). One portal per hall.
  * `C3`: the sheet draws a WALL on the east face at +0.000 (the hall opens
    west onto the commercial floor). The stage-1 opening the street file
    builds its door on (x 82.548, y 19.26..21.748) is kept as a MADE double
    door, two glazed leaves `in_L00_C3_d4/_d7_swing__int_white_gloss` in the
    facade line, opening OUT (inside, they would close the way round under
    the half landing). So C3 now has an interior leaf.
  * `podium`: the drawn double door, `in_L00_podium_d1/_d2_swing__...`;
    portal x 19.453..21.796 at y 36.354.
* **Made doors** (`made: true` in plan_meta doors) also carry `made_from`
  when they copy a drawn door: the four +27.900 front doors are the doors
  of the same flats on +24.600 (`entrance of flat 108 on L07 ...`).
* **Skirting** is NOT a node of its own: it is an `int_white_gloss`
  primitive inside the owner's walls node (`in_<L>_<owner>_walls__int_wall`,
  the corridor's / halls' in theirs), 0.08 high, 12 mm off the wall, cut at
  every door throat, room-facing faces only. **Thresholds** where two floor
  finishes meet in a room door: `in_<L>_u<n>_threshold__int_marble`, the
  throat at z .. z+0.006.
* **`nav.furn`** per level (L01..L10), from `web/interior/furn/index.json`
  and the pieces' heights in `furn/<LEVEL>.glb`: `[{node, c [x, y], s [w
  across heading, d along it], hd (plan degrees), z [bottom, top] above the
  level floor}]`, one per index piece. The walker decides what is solid
  (e.g. z overlapping the nav band and not in a door throat).
* **Lift stops.** Every car stops at L00 on the side the sheet draws (C1-1
  and C2-2 south into the south lift hall, C1-2 east / C2-1 west into the
  lobby); the car's open side follows. -3.000 (not built yet): the sheet
  draws only C1-2 and C2-1 there (the other two shafts are rooms with doors).
* **Split meta, alongside the monolithic file (not read by anyone yet).**
  `web/plan_meta/index.json` = `plan_meta.json` without the levels' contents
  plus `levels[] {id, z, h, kind, clear, built, file, bytes}`;
  `web/plan_meta/<LEVEL>.json` = that level's record exactly as in
  `plan_meta.json`. Both are written by every build; a page can switch to
  them by loading index.json and then a level's file when it shows it.

## Walking (added by the integrate stage, build 3: web/app.js "walking the building", web/walk.js)

* **The gate.** The engine is told per level whether its geometry is on screen
  (`createWalker( { ready( id, why ) } )`): the level's interior welded and
  compiled, its furniture in or known absent, `cores.glb` in; `why === 'shaft'`
  (a car passing) needs the walls only. A body is never let onto a surface of
  a level that is not ready, a flight wants every storey visible from it
  (`nearFlights`), and a car with a visitor in it waits, doors shut, short of
  a storey whose walls are not in - its shaft IS those walls.
* **Furniture is solid** in the walk where `web/interior/furn/index.json` gives
  a piece a `box` and its mesh is taller than 0.4 m (`walk.js
  furnitureSolids`, heights off the GLB); a footprint within a body's radius
  of a door's throat is left out (the sheets draw a few: walk-in showers
  behind bathroom doors, the 33-stack's second bed). If the build ever writes
  footprints under `nav.furniture` / `nav.furn` / `nav.furniture_solid`
  (polygons or `{poly}`), the engine paints those solid as well.
* **Lift stops** whose landing door faces no floor a body can stand on (the
  soffit rule included) are not offered and not ridden to (`walk.js
  markDeadStops`); a plan that is put right gets its stop back.
* **Moving nodes** of the interior files - `_swing__` leaves, `_lift<k>_car__`,
  `_lift<k>_<LEVEL>_door__` - are welded per material only while at rest
  (`levels.js makeMovers`); their names and origins are the contract.
* **The street file, as the page splits it**: `podium_door_<id>_leaf*` is
  welded into its own group (hidden once `L00` is on screen in a walk), and
  `<B>_<LEVEL>_lg<NNN>_(glass|lit)` is welded per storey (hidden for the
  storeys a walk has on screen, the interior's glazed leaf taking over - seam
  (d)). Renaming either in Blender silently undoes that.

## Build 4 seams (added by model-fix)

* **Nothing of the street file hangs under an interior ceiling.** Room
  ceilings are at z + h − 0.30. The street's roof slab (`<B>_roof`) is
  +37.65 .. +37.81 (15 cm over the L10 ceilings at +37.50; at +37.50 the two
  were coplanar and the black roof won in jagged patches) and is cut out over
  the three stair heads, whose floors (`cores.glb`, +37.50 .. +37.80) are the
  roof there. Inside the L00 outline every street slab's underside is
  **+4.55** (`<B>_slab_L01`, the L01 storey's walls/piers/`lgfloor`, the
  terrace deck; L00 ceilings +4.50), and there is no street slab at all over
  the cores C1..C3 (halls, flights, shafts: the interior carries L01's floor).
  Outside the podium - the north cantilever - the soffit stays at +4.45.
  Checked by `tools/plan_ceilcheck.py`: rays up from 30
  room points per level L00 halls .. L10 must meet that level's own ceiling
  with nothing within 3 cm behind it, and rays up over every grade flight must
  meet the interior or the stair house, never a street slab.
* **The street's walls in front of an entrance hall** (`podium_shell` on the
  outline runs whose `behind` is `core`) are a 0.07 m skin OUTSIDE the outline:
  the hall's wall is the interior's. (At 0.40 deep inward they stood 0.39 m
  inside C1/C2's halls, over half the upper flight.) Glazing on a hall front
  with no door stands just outside the outline too.
* **Loggia floors: the interior owns the walking surface.** Tiles at z+0.02,
  an L01 office's parquet at z in a one-way bay. The street's `<B>_lgfloor_L01`
  is only the slab under it (for the street view before the interior is in and
  for the soffit seen from below); its top is z under an ordinary loggia and
  **z − 0.03** under a one-way bay (it was z − 0.006, inside Draco's ~5 mm
  position step: in places one floor over the other).
* **Terrace stair.** `lib_city.STAIR_HOLE` is read off plan_meta `cores`
  `podium` (hall north end .. far end of flights and half landing): x 19.15 ..
  21.85, y 29.05 .. 34.53. The stair house stands round it (walls 0.20, 2.75 m
  high), its door is L01 `d12` (`made`, x 19.40 .. 20.79; build 2 called it
  d10). The interior's L01 walls inside that house's footprint (+0.25) stop at
  z + 2.73 and it has no L01 ceiling there (`lib_plan.stair_house_zone`).
* **`site.entrances[].kind`** (new key): `core` (C1..C3), `terrace` (podium),
  `commercial` (`S1`, `S2`, `S3`: the shop doors the +0.000 sheet draws, real
  openings in the shopfronts with stand-in leaves `podium_door_S<k>_leaf` /
  `_leaf_glass`; `leaves` lists the interior's L00 door nodes; no portal, no
  label, no sign). C3 and podium are `interior_leaf: true`; the glazed look of
  their fronts is pinned by `lib_city.GLAZED_FRONTS`, not by the leaf.
* **Furniture.** A kitchen leg whose drawn zone runs over a column or duct is
  clipped to the room's free floor (`params.profile`, its own mesh class
  `kitchen_run_..._k<hash>`); the coffee table is procedural (node name and
  `int_coffee_top` unchanged). `furn/index.json -> omitted[]` lists drawn
  pieces deliberately not placed, with why (today: the 33-stack's nightstand
  drawn across the bedroom wall into the hall, 8 flats).
