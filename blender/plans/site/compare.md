# Real surroundings vs today's scene (plan frame, metres)

Plan frame: x runs SSE along Todria (a to J), +y runs toward Todria (WSW), and the site centre is (41.5, 18).
Real data: `site.json` (OSM, Esri 2025-11-06 imagery, shadow heights). Scene data: `blender/lib_city.py` (the `ROAD_*` bands) and `blender/lib_hood.py` (the perimeter-block grid).
Pictures: `preview_top.png` and `preview_overlay.png`.

## 1. The four streets round the site

| Scene band | Scene | Real | Difference |
|---|---|---|---|
| `ROAD_S` y 53..71 (18 m) | main street | **Pavle Todria St**, tertiary, 2 lanes plus a parked-car lane. Measured kerb to kerb **y 49.5..61.5 (12 m)**, centreline about y 55.5 (OSM line shifted −1.5 m to match the image). Dead straight for the whole 900 m circle. | North kerb is 3.5 m too far south and south kerb 9.5 m too far south. The street is 6 m too wide. |
| (north pavement) | shop pavement / forecourt | Forecourt and sidewalk y 36..45, then a **3–4 m tree verge y 45..49.5** with continuous canopy, then the kerb. Zebra at x ≈ 60. | Our lot's podium edge is at y 47.75, so in front of us only about 2 m of verge is left before the kerb. |
| (south pavement) | beds and benches every 12 m on y 72..74 | Sidewalk y 61.5..65, then a dense **tree belt / OSM wood 979754866 (x 58..114, y 68..86)** and loose trees. | There is no straight building line across the street (see section 2). |
| `ROAD_E` x 88..104 (16 m) | street | **Giorgi Kuchishvili St**, tertiary, about **7.5 m**. Centreline x 93.2 at Todria, drifting to 88.5 at y −430 (about 0.6° off plan y). Real kerbs about x 89.5..97 near the site. | Centre is about 3 m too far east and the street is 8.5 m too wide. It forms a T with Todria and does **not** continue south: the south side opposite it is the 5-storey slab 176663802 (x 58..156, y 75..124). |
| `ROAD_W` x −48..−32 (16 m) | street | **An unnamed asphalt lane**, OSM 37897676, about **6 m**, centreline x ≈ −31 (so x −34..−28). It runs from Todria to the rear lane at y ≈ 22, and has a T at Todria. | Centre is about 9 m too far west and the lane is 10 m too wide. Real lane is narrow, with no kerbed sidewalks. |
| `ROAD_N` x-wide band y −42..−26 (16 m) | street behind the site | **No street there.** There is a service yard (983347652) at y ≈ −26, and 1–2-storey sheds and annexes sit in the band (1306035078 x 34..50, y −46..−32; 1306035076 x −23..−10, y −42..−29). The first real streets behind are the gravel lane 176677015 at **y ≈ −88/−90** and **Konstantine Leselidze St at y ≈ −162..−170 (7 m asphalt, dirt shoulders, no kerbed walk)**. | The scene invents this whole street. |

Second ring:
- **`ROAD_S2` (y 181..197):** no such street. South of Todria, three **dead-end streets leave Todria at about 25° off plan y**:
  - 1st: from (234, 56) to (73, 409).
  - 2nd: from (49, 57), which is **straight opposite our frontage**, to (−120, 412).
  - 3rd: from (−144, 58) to (−269, 317).
  - A closing lane runs at y ≈ 385..412.
- **`ROAD_N2` (y −152..−136):** the nearest real street is Leselidze at y ≈ −165, which is 7 m wide, not 16.
- **`ROAD_W2` (x −178..−162):** north of Todria the real N–S streets are at x ≈ −122 and −252 (residential, 5–7 m). South of Todria it is the diagonal 3rd Dead End.
- **`ROAD_E2` (x 218..234):** north of Todria there is a residential street at x ≈ 222 and the Leselidze Dead End at x ≈ 183. South of Todria the diagonal 1st Dead End leaves Todria at x 234.

**Widths:** every scene street is 16 m (Todria 18 m). The real streets are:
- Todria: 12 m
- Kuchishvili: about 7.5 m
- Leselidze: 7 m
- residential: 5–7 m (6 m used)
- service and estate roads: about 4 m
- the secondary Kldiashvili St (x ≈ 479, east edge): 10.5 m (OSM default)

`site.json` holds 191 road centrelines (2 secondary, 15 tertiary, 49 residential, 81 service, 16 footway, 28 path), the merged carriageway polygons, and assumed sidewalk bands (OSM has no sidewalk tags).

## 2. Block pattern

The **scene** is a regular grid:
- Blocks x −320/−178/−162/−48/−32/88/104/218/234/440 and y −280/−152/−136/−42/−26/53/71/181/197/330.
- Blocks are 114–206 m by 79–133 m.
- Every block is a **closed perimeter of classical bars**, 15 m deep, on a building line 6 m from the kerb, with a lawn court.

The **real** town has three distinct fabrics:
1. **North and east of the site (y < 25): a grid of private houses.**
   - Plots are 1–2 storeys with pitched tin or tile roofs, standing free in gardens full of fruit trees.
   - E–W streets are at y ≈ −18 (west part only), −90, −165, −272, −310 and −390. N–S streets are at x ≈ −322, −252, −122, −90, −31, 90, 183, 222 and 326.
   - Blocks are about **75–110 m deep (y) by 90–200 m wide (x)**, and buildings cover 16–23% of a block, against about 45–50% for a scene perimeter block.
   - In the north-east there is a curved street of houses (x 355..480, y −250..−50).
2. **A row of Soviet slabs along Todria's north side, y ≈ 29..48, set about 8 m behind the kerb.**
   - West of us: Todria 15 (x −138..−48, **9 st**), then 9-storey slabs at x −257..−164 and x −380..−282.
   - East of us: Todria 7 (x 113..211, **8 st**), the next 8-storey slab at x 230..322, and a 9-storey slab perpendicular to Todria at x 331..346 (y −67..22).
   - Two more slabs run **perpendicular** to Todria and flank the site: **Todria 13 (x −61..−44, y −82..12, 8 st)** and **Todria 9 (x 111..125, y −83..12, 9 st)**.
   - In line behind those two, further back, are 8-storey slabs at x −67..−54 and x 112..125 (y −155..−95).
   - Service lanes run behind the slabs at y ≈ 22.
3. **South of Todria: a 1960s–80s microdistrict.**
   - Superblocks are about 150–200 m wide and 350 m deep, cut by the 25° dead-end streets.
   - Inside are **freestanding 5-storey slabs** (about 15–16 m, about 12 by 60–100 m, set at 25° to Todria) and a few 9-storey ones.
   - Between them are trees, 4 m service roads, pitches, a construction site (x −112..5, y 298..406) with two towers under construction (**47–50 m** as of 2025-11, final height unknown), and grassland and scrub at y 230..400.
   - At the east edge is the **Garden of Youth** park (x 365..476, y 57..424) along Kldiashvili.

**Directly around the lot:**
- **Behind it (y −90..0, x −32..88):** low annexes and sheds (2, 2, 1 and 3 storeys), the large fire-station yard (x −28..84, y −162..−95), and the new **10-storey Leselidze 30a** (x −14..20, y −72..−55; OSM says 10, its shadow reads about 12 m, so check it).
- **Across the street (y 62..150):** the tree belt, a 1-storey kiosk (x 14..23, y 83..92), a low U-shaped 2-storey block (x −27..5, y 80..106), and two 5-storey slabs (x 19..56, y 90..150 and x 58..156, y 75..124) set at 25°.
- **There is no building line facing us across Todria.** The scene's row of shopfront bars across the street on y ≈ 77 does not exist.
- The opening camera `HERO_EYE` (26, 75.5) stands, in reality, in the tree belt south of the sidewalk. The 2nd Dead End mouth is at x 49 and the zebra at x 60.

## 3. Heights

Scene (`lib_hood` bar types): the ground floor is 4.8 m, upper floors 3.3 m, all with hip roofs.

| Type | Storeys | Eaves |
|---|---|---|
| `low5` | 4 | about 14.7 m |
| `six` | 5 | 18.0 m |
| `grand7` | 6 | 21.3 m |
| `tower9` | 8 | 27.9 m, plus a 1 m roof rise |

Every scene block is 14.7–27.9 m, and there is nothing low.

Real, for the 451 buildings whose centroid is within 450 m of the site:

| Height | Count | Share of footprint | What |
|---|---|---|---|
| ≤ 5 m (1 storey) | 274 | 38% | houses, sheds, garages, kiosks |
| 5–8 m (2 st) | 76 | 12% | houses, small blocks |
| 8–14 m (3–4 st) | 64 | 18% | larger houses, school, fire station, a few 4-storey slabs |
| 14–20 m (5 st) | 17 | 16% | microdistrict slabs, 15.3–15.8 m |
| 20–31 m (8–10 st) | 18 | 14% | Todria slabs (8 st = 24 m, 9 st = 27.8 m), Leselidze 30a (10 st, 29.8 m) |
| > 31 m | 2 | 2% | towers under construction, 47–50 m |

- **Two-thirds of the real footprint is 14 m or lower**, while the scene has nothing under 14.7 m.
- The tall buildings (8–9 storeys) form **a single row along Todria plus the two perpendicular slabs either side of us**. That row is roughly as tall as our tower (37.8 m roof) minus 10–14 m.
- Real roofs are **flat** on every slab and **pitched (tin or tile)** on houses (249 pitched, 202 flat in `site.json`).
- Building cover within the circle is **21%** (133,600 m²).

Confidence on heights: 16 high (OSM levels confirmed by shadow), 337 medium (clean shadow), 98 low. Shadows cannot separate 8 storeys from 9.

## 4. Green, trees and ground

- **Scene:**
  - Avenues on the neighbours' side of each first-ring street, 13–16 m apart.
  - Corner beds with slat fences on eight corners.
  - Beds and benches on Todria's far pavement.
  - Lawns in the block courts.
- **Real:**
  - **2,495 tree canopies** picked from the imagery within 450 m, about 39 per hectare. They are densest in the house gardens north and east, along both Todria verges, and through the microdistrict.
  - Only 33 of those fall inside the scene's first ring (x −48..104, y −42..71). The verge right at our frontage is thin; the real mass of trees is across Todria (y 65..90).
  - OSM adds 40 green polygons: 11 wood, 9 grass, 7 scrub, 10 pitches, 2 parks, 1 playground. There are also 38 landuse outlines (garages, education, commercial, fire-station yard, construction).
  - Fences and walls are not in OSM, but in the image most house plots have walls or fences on the street line.
- **Ground:** flat. The relief is under 1 m across the lot and within 450 m is below the noise of the elevation data (342–343 m above sea level, at most about 0.8% grade falling east). Use z = 0. The river terrace drop (8–10 m) is 500–750 m east and south-east, and the hills to the south-west are a skyline from 1.5 km out. An optional 20 m grid relative to the site is in `site.json` under `terrain.grid`.

## 5. What the scene invents that is not there

1. The **north street `ROAD_N`**, and the whole second ring of straight 16 m streets (`ROAD_*2`).
2. **Perimeter blocks of classical bars**, with shop bases, cornices and hip roofs, on every side. There are none. The real neighbours are flat-roofed Soviet panel slabs (white or cream panel faces) and detached houses with pitched roofs.
3. **A building line facing us across Todria.** In reality that side is a tree belt and slabs set back at 25°.
4. **Uniform 15–28 m heights everywhere.** In reality 2-storey-and-lower dominates, the tall buildings line Todria only, and there is a 10-storey new block behind.
5. **Street widths of 16–18 m.** The real streets are 12 m (Todria) and 6–7.5 m (the rest).
6. **A crossing street east of us carrying on south of Todria.** Kuchishvili ends in a T.

Kept or confirmed: Todria is the straight main street on the +y side, and there is a street just east of the lot at x ≈ 90.

## 6. Notes for the builder

- `site.json` is in plan metres, with rings counter-clockwise and not closed.
  - It has 451 `buildings` (each with `height_m`, `levels`, `kind`, `roof` flat or pitched, `confidence`, and the roof `colour`), 191 `roads` (centreline and width), `carriageway`, `sidewalks`, `green`, `landuse`, `trees`, `terrain`, and `own_outlines`.
  - Our lot (the union of all plan.json outlines, which reaches y 47.75) has been removed from every layer. The old market (176675818) and the shop strip (1305820924) have been dropped. Lane 983347651 under the tower has been removed.
- The absolute position is good to a few metres, and the fit to the imagery to about 1 m. OSM outlines of tall slabs may sit 1–3 m off their base, because they were traced on the leaning roofs.
