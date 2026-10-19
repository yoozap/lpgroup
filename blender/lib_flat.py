# -*- coding: utf-8 -*-
"""The show flat: the corner unit on the top floor of block A, opened up as a
dollhouse cutaway the way the sales render is.

The unit is the one the bay rhythm gives the corner: loggia, window, window,
loggia - 11.5 m along the street, the gable on its west side, the building's
own mass standing full height behind its entrance wall and beside its party
wall. Everything in here is authored in block A's local frame (x along
the street from the gable, y into the plan, z up) at the top floor slab.

Two things come out of `build_flat`:

  * the flat itself: floors, walls cut at CUT_H, the loggias and the gable
    slot in their cut form, doors, furniture, curtains, plants. Every object
    is named `flat_*` (bevelled) or `flatx_*` (thin things: no bevel).
  * the cutaway: the pieces of the real building that stand where the flat is
    - the top-floor facade and gable, the parapet, the mass, the loggia and
    window kits of that cell - split off into objects named `*__cut`.

The browser shows `*__cut` and hides `flat*` for the street shot, and swaps
them for the flat shot. Scene 1 is therefore pixel-identical to the building
without the flat in it.
"""
import bpy, bmesh, math, re, random, os
from mathutils import Vector, Matrix
from lib_build import MB, mat, srgb, link_dup, frame_for, frame_for_yz, collection
import lib_building as LB
import lib_city as LC

M = LB.M
rnd = random.Random(20261009)

# ------------------------------------------------------------------ where
FL     = LB.N_FLOORS - 1                        # top floor
CUT_H  = 1.45                                   # walls stop here, as in the render
XC     = LB.LOG_W * 2 + LB.WIN_W * 2            # party wall face
# The entrance wall, outer face. Block A is 18.00 m deep and there is a line
# of flats on each side of it, so a flat 8.40 m deep left 1.20 m of nothing
# between the two entrance walls - from the Top view a grey strip running the
# whole length of the floor, the user 2026-10-19: "in middle of flats we have
# spaces". At 9.00 the two lines meet: the front flat's entrance wall and the
# back flat's stand back to back as one 0.40 m party wall and the open floor
# is flats edge to edge. The 0.60 m goes to the hall, the bathroom and the
# kitchen run, all of which are set out from Y_ENT and follow it.
YC     = LB.A_DEPTH * 0.5                       # 9.00  entrance wall, outer face
# the cut stops at the entrance wall: behind it stands the back line's own
# entrance wall, as the building's mass stands beside the party wall
Y_END  = YC
# The sales plan was rectified to the flat as it was measured, 8.40 m deep,
# so the reference overlay keeps that depth and registers with the rooms
# instead of stretching the extra 0.60 over all of them.
PLAN_D = 8.40
# The wall the two lines share where they meet, used for the slab that stops
# you seeing through block A on the storeys that have no flats in them.
SPINE_T = 0.40
PT  = 0.12             # partition thickness

# Levels are resolved once block A exists (see _levels): where the facade
# storeys sit is still being fitted upstream, and the flat has to land on
# the same slab as the loggia kit of its own cell.
Z0 = ZC = FZ = FZT = TOPF = WALL_TOP = None
CUT_BOX = CUT_BOX_BK = CENTER = None


def _levels():
    global Z0, ZC, FZ, FZT, TOPF, WALL_TOP, CUT_BOX, CUT_BOX_BK, CENTER
    Z0 = LB.GROUND_H + getattr(LB, 'FACADE_OFF', 0.0) + FL * LB.FLOOR_H
    ob = bpy.data.objects.get('loggia_shell_f%d_b0' % FL)
    if ob is not None and abs(ob.location.z - Z0) > 1e-4:
        print('[flat] top floor slab from the kit instance: %.3f (formula %.3f)'
              % (ob.location.z, Z0))
        Z0 = ob.location.z
    ZC = Z0 + 0.02 + CUT_H          # cut plane (walls stand on 20 mm of floor)
    FZ = Z0 + 0.02                  # parquet surface
    FZT = Z0 + 0.025                # tile surface
    TOPF = Z0 + LB.FLOOR_H          # top of the top storey: loggia slab top
    # Where the outer shell of the flat stops. Everything the cutaway leaves
    # standing around the flats - the mass behind them, the pier between one
    # flat and the next - is capped here too, so the whole open floor reads
    # at one height instead of black fins rising over the white walls.
    WALL_TOP = Z0 + 2.45
    # The cell runs to the end of the flat's own bay group, not to its party
    # wall: stopping at the party wall left a 0.55 m slice of block A standing
    # full height between this flat and the next one along.
    CUT_BOX = (-5.0, -5.0, Z0, _BAYS[3][2], Y_END, 300.0)
    # the same cell on the back line, where the mirrored flat stands
    CUT_BOX_BK = (-5.0, LB.A_DEPTH - Y_END, Z0, _BAYS[3][2],
                  LB.A_DEPTH + 5.0, 300.0)
    CENTER = (XC * 0.5, 4.3, Z0)                    # what the camera looks at

# plan - every number is an inside face
X_GABLE  = 0.46                       # gable leaf, inner face
X_PARTY  = XC - 0.20                  # party wall, flat side
Y_FAC    = LB.WALL_T                  # facade, inner face (window bays)
Y_LOG    = LB.WALL_T + LB.LOG_D + 0.22   # loggia back wall, room side (2.07)
Y_ENT    = YC - 0.20                  # entrance wall, hall side (8.80)
# The facade in here is built from lib_building's own bay edges (see the
# facade loop in build_flat), so the plan has to read the same edges rather
# than add the nominal bay widths up. Adding them up assumed block A starts
# at x = 0 with every bay its nominal width; the rhythm is fitted upstream
# and now starts at 0.25 with a wider first window bay, so the openings had
# drifted 0.25 m at the gable end and 0.55 m at the party end - the loggia
# shells stood beside the holes the facade actually has (white cheek across
# the opening seen from the street, balcony off centre seen from inside) and
# the white lining covered a third of each window.
_BAYS = LB.bay_layout(LB.BAYS_A)[0]
assert [b[0] for b in _BAYS[:4]] == ['L', 'W', 'W', 'L'], \
    'block A no longer opens loggia, window, window, loggia: refit the flat'
# The same flat three more times, east along the street: units 1-3 of block
# A. They are not plain copies. Unit 0 was fitted 11.84 m wide because its
# first window bay is 2.55; units 1, 2 and 3 are 11.54 with a 2.25 bay, so
# the copy set is the flat with that 0.30 taken out of the pier between
# window 1 and the living | master partition. The seam falls on solid facade
# and on the living room floor, where only the slab, the facade, the white
# lining and the rug cross it - everything east of it (the partition, the
# bed, bedroom 2, the bathroom) travels together, so the rooms keep the fit
# they were measured into and only the living room loses the 0.30 that bay
# never had. One warped set is built and then instanced at each unit, so the
# three flats cost one flat's geometry.
ROW_UNITS = (1, 2, 3)
ROW_SEAM  = 5.20                       # in unit 0 metres, between the windows
LOG_LIV = _BAYS[0][1] + LB.LOG_JL      # 0.85  loggia at the gable end -> LIVING
LOG_BED = _BAYS[3][1] + LB.LOG_JL      # 9.17  loggia at the party end -> BEDROOM 2
WIN1 = _BAYS[1][1] + LB.W1_OFF         # 3.77  the master's two facade windows
WIN2 = _BAYS[2][1] + LB.W2_OFF         # 6.57
WW   = LB.W1_W
# The sales render is viewed from the entrance side, and seen from there its
# living room sits at the far end from the bathroom. Our corner unit is the
# opposite hand, so the two ends are swapped against the first pass: the
# LIVING room now takes the gable end and runs the full depth with the kitchen
# in its back corner, BEDROOM 2 takes the party end with the bathroom behind it.
# The render runs a wall down between two facade windows, so the two windows
# belong to different rooms. Ours had both in the bedroom, so the living |
# master partition moves into the pier between them and the master | bedroom 2
# partition moves out to the pier before the second balcony.
# The two partitions are fitted positions, not offsets from the windows: the
# furniture either side of them is placed in absolute metres, so they stay
# where they were measured while the openings move back onto the bays. Both
# still sit in a pier, so window 1 stays in the living room and window 2 in
# the master.
X_LIV    = 5.32                        # living | master, in the pier between the windows
X_BED    = 8.40                        # master | bedroom 2, in the pier before the loggia
Y_P23    = 5.30                        # bedrooms | hall
X_BATH   = 9.18                        # hall | bathroom
LX0, LX1 = X_GABLE, X_LIV              # living room, side to side


# ------------------------------------------------------------------ palette
def build_materials():
    for name, hexc, rough, metal in (
            ('int_wall',           '#ebe7df', 0.92, 0.0),
            # the same wall for the loggia's linings, named apart so the page
            # can take them away with the balcony (see materials.js)
            ('int_wall_loggia',    '#ebe7df', 0.92, 0.0),
            ('int_parquet',        '#b58a58', 0.50, 0.0),
            ('int_tile_grey',      '#8b8d8e', 0.28, 0.0),
            ('int_tile_white',     '#e4e2dd', 0.26, 0.0),
            ('int_white_gloss',    '#f2f1ee', 0.22, 0.0),
            ('int_wood_oak',       '#b3895a', 0.55, 0.0),
            ('int_wood_walnut',    '#4f3627', 0.48, 0.0),
            ('int_marble',         '#e8e5e0', 0.14, 0.0),
            ('int_black',          '#111214', 0.40, 0.2),
            ('int_stone_dark',     '#3a3a3c', 0.32, 0.0),
            ('int_ceramic',        '#f4f4f2', 0.10, 0.0),
            ('int_fabric_teal',    '#3c8a84', 0.92, 0.0),
            ('int_fabric_bluegrey','#8294a8', 0.92, 0.0),
            ('int_fabric_white',   '#eeeae2', 0.90, 0.0),
            ('int_fabric_orange',  '#d6622a', 0.92, 0.0),
            ('int_fabric_sofa',    '#7b7f86', 0.95, 0.0),
            ('int_fabric_dark',    '#3d4148', 0.95, 0.0),
            ('int_rug',            '#a3a7ad', 0.95, 0.0),
            ('int_curtain',        '#d3d6dc', 0.80, 0.0),
            ('int_accent_red',     '#8b2d29', 0.60, 0.0),
            ('int_pot',            '#36322f', 0.60, 0.0),
            ('int_wood_teak',      '#8a5a32', 0.42, 0.0),
            ('int_door_leaf',      '#ece9e3', 0.36, 0.0),
            ('int_tile_wall',      '#eceae6', 0.10, 0.0),
            ('int_tile_floor',     '#c9c7c3', 0.12, 0.0),
            ('int_leather_red',    '#7e1f1c', 0.50, 0.0),
            ('int_coffee_top',     '#2b3139', 0.30, 0.0),
            ('int_mint',           '#a7c3b2', 0.35, 0.0),
            ('int_brass',          '#b08c55', 0.35, 0.85),
            ('int_lamp_shade',     '#f1e8d6', 0.70, 0.0),
            ('int_mirror',         '#dfe3e8', 0.04, 1.0)):
        mat(name, srgb(hexc), rough=rough, metal=metal)
    mat('int_glass', srgb('#cfe2ea'), rough=0.05, alpha=0.30)


# ------------------------------------------------------------------ helpers
def prism(mb, pts, z0, z1):
    """Polygon (counter-clockwise from above) extruded z0..z1."""
    n = len(pts)
    o = len(mb.v)
    for (x, y) in pts:
        mb.v.append((x, y, z0))
    for (x, y) in pts:
        mb.v.append((x, y, z1))
    for k in range(n):
        j = (k + 1) % n
        mb.f.append((o + k, o + j, o + n + j, o + n + k))
    mb.f.append(tuple(o + n + k for k in range(n)))
    mb.f.append(tuple(o + (n - 1 - k) for k in range(n)))


def rbox(mb, p0, p1, r, seg=3):
    """Box with rounded vertical arrises - a mattress, a cushion, a sofa."""
    x0, y0, z0 = p0
    x1, y1, z1 = p1
    r = max(0.001, min(r, (x1 - x0) * 0.5 - 0.001, (y1 - y0) * 0.5 - 0.001))
    pts = []
    for cx, cy, a0 in ((x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, 90.0),
                       (x0 + r, y0 + r, 180.0), (x1 - r, y0 + r, 270.0)):
        for k in range(seg + 1):
            a = math.radians(a0 + 90.0 * k / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    prism(mb, pts, z0, z1)


def ellipsoid(mb, c, rx, ry, rz, seg=12, rings=7):
    cx, cy, cz = c
    o = len(mb.v)
    for i in range(rings + 1):
        phi = math.pi * i / rings
        for j in range(seg):
            th = 2.0 * math.pi * j / seg
            mb.v.append((cx + rx * math.sin(phi) * math.cos(th),
                         cy + ry * math.sin(phi) * math.sin(th),
                         cz + rz * math.cos(phi)))
    for i in range(rings):
        for j in range(seg):
            n = (j + 1) % seg
            a = o + i * seg + j; b = o + i * seg + n
            c_ = o + (i + 1) * seg + n; d = o + (i + 1) * seg + j
            mb.smooth.add(len(mb.f))
            mb.f.append((a, d, c_, b))          # outward


def wall_x(mb, x0, x1, y0, y1, z0, z1, ops=()):
    """Wall running along x, y0..y1 thick, with openings [(a, b, zlo, zhi)]."""
    x = x0
    for (a, b, lo, hi) in sorted(ops):
        if a > x + 1e-6:
            mb.box((x, y0, z0), (a, y1, z1))
        if lo > z0 + 1e-6:
            mb.box((a, y0, z0), (b, y1, lo))
        if hi < z1 - 1e-6:
            mb.box((a, y0, hi), (b, y1, z1))
        x = b
    if x1 > x + 1e-6:
        mb.box((x, y0, z0), (x1, y1, z1))


def wall_y(mb, y0, y1, x0, x1, z0, z1, ops=()):
    """Wall running along y, x0..x1 thick, with openings [(a, b, zlo, zhi)]."""
    y = y0
    for (a, b, lo, hi) in sorted(ops):
        if a > y + 1e-6:
            mb.box((x0, y, z0), (x1, a, z1))
        if lo > z0 + 1e-6:
            mb.box((x0, a, z0), (x1, b, lo))
        if hi < z1 - 1e-6:
            mb.box((x0, a, hi), (x1, b, z1))
        y = b
    if y1 > y + 1e-6:
        mb.box((x0, y, z0), (x1, y1, z1))


def rot2(cx, cy, ang, dx, dy):
    c, s = math.cos(ang), math.sin(ang)
    return (cx + dx * c - dy * s, cy + dx * s + dy * c)


def rbox_rot(mb, cx, cy, ang, hw, hd, z0, z1):
    """Box of half width hw (along its own x) and half depth hd, turned by ang."""
    pts = [rot2(cx, cy, ang, dx, dy) for (dx, dy) in
           ((hw, -hd), (hw, hd), (-hw, hd), (-hw, -hd))]
    prism(mb, pts, z0, z1)


def curtain(mb, a, b, c, z0, z1, along='x', amp=0.055, wl=0.21, phase=0.0):
    """A hanging curtain panel. Real curtains are gathered at the rail and
    swing free at the hem, so the fold amplitude grows down the drop and the
    bottom edge rises and falls with it. A ribbon with one offset per column
    reads as corrugated card; offsetting top and bottom differently is what
    makes it hang."""
    n = max(8, int((b - a) / 0.016))
    o = len(mb.v)
    for k in range(n + 1):
        t = a + (b - a) * k / n
        w = math.sin(2.0 * math.pi * (t - a) / wl + phase)
        ot, ob = c + amp * 0.30 * w, c + amp * w
        hem = z0 + 0.012 * (1.0 - w)
        pt = (t, ot) if along == 'x' else (ot, t)
        pb = (t, ob) if along == 'x' else (ob, t)
        mb.v.append((pb[0], pb[1], hem))
        mb.v.append((pt[0], pt[1], z1))
    for k in range(n):
        mb.smooth.add(len(mb.f))
        mb.f.append((o + 2 * k, o + 2 * k + 2, o + 2 * k + 3, o + 2 * k + 1))


def curtain_pair(P, a, b, c, z0, z1, along='x'):
    """Two gathered panels on a rail: the rod, its brackets, and the cloth."""
    R = P('metal_dark')
    if along == 'x':
        R.cyl((a - 0.06, c, z1 + 0.055), (b + 0.06, c, z1 + 0.055), 0.016, seg=10)
    else:
        R.cyl((c, a - 0.06, z1 + 0.055), (c, b + 0.06, z1 + 0.055), 0.016, seg=10)
    curtain(P('int_curtain', thin=True), a, b, c, z0, z1, along,
            amp=0.070, wl=0.26, phase=0.0)
    curtain(P('int_curtain', thin=True), a, b, c + 0.055, z0 + 0.01, z1, along,
            amp=0.052, wl=0.33, phase=1.9)


def window_unit(P, x0, w, z0, h, deep=None):
    """One window built the way a real one is: a dark outer frame on the
    street, a white inner frame and sash in the room, a central mullion, one
    opening light with its handle, double glazing, the reveal plastered white
    and an oak board on the sill."""
    deep = LB.WALL_T if deep is None else deep
    gy = LB.GLASS_Y
    O0, O1 = gy - 0.075, gy + 0.055          # dark frame, outside
    I0, I1 = gy + 0.075, gy + 0.185          # white frame, inside
    t, mull, sg = 0.052, 0.046, 0.038
    ti, mi = t + 0.014, mull + 0.016          # inner joinery, a touch wider so
    cx = x0 + w * 0.5                          # it always covers the dark frame
    D, Wt, G = P('frame_bronze'), P('int_white_gloss'), P('int_glass', thin=True)
    for (a_, b_, c_, d_) in ((x0, x0 + t, z0, z0 + h), (x0 + w - t, x0 + w, z0, z0 + h),
                             (x0 + t, x0 + w - t, z0, z0 + t),
                             (x0 + t, x0 + w - t, z0 + h - t, z0 + h)):
        D.panel(a_, b_, c_, d_, O0, O1)
    D.panel(cx - mull / 2, cx + mull / 2, z0 + t, z0 + h - t, O0, O1)
    for (a_, b_, c_, d_) in ((x0, x0 + ti, z0, z0 + h), (x0 + w - ti, x0 + w, z0, z0 + h),
                             (x0 + ti, x0 + w - ti, z0, z0 + ti),
                             (x0 + ti, x0 + w - ti, z0 + h - ti, z0 + h)):
        Wt.panel(a_, b_, c_, d_, I0, I1)
    Wt.panel(cx - mi / 2, cx + mi / 2, z0 + ti, z0 + h - ti, I0, I1)
    # the right light opens: its sash stands a little proud of the frame
    sx0, sx1 = cx + mi / 2, x0 + w - ti
    for (a_, b_, c_, d_) in ((sx0, sx0 + sg, z0 + ti, z0 + h - ti),
                             (sx1 - sg, sx1, z0 + ti, z0 + h - ti),
                             (sx0 + sg, sx1 - sg, z0 + ti, z0 + ti + sg),
                             (sx0 + sg, sx1 - sg, z0 + h - ti - sg, z0 + h - ti)):
        Wt.panel(a_, b_, c_, d_, I0 - 0.014, I1 + 0.012)
    hx, hz = sx0 + 0.030, z0 + h * 0.46
    P('chrome').box((hx - 0.017, I1 + 0.010, hz), (hx + 0.017, I1 + 0.036, hz + 0.052))
    P('chrome').box((hx - 0.013, I1 + 0.026, hz + 0.010), (hx + 0.013, I1 + 0.040, hz + 0.125))
    # double glazing: two leaves, a 16 mm cavity
    for (a_, b_) in ((x0 + ti, cx - mi / 2), (sx0 + sg, sx1 - sg)):
        for yy in (gy + 0.058, gy + 0.074):
            G.panel(a_, b_, z0 + ti, z0 + h - ti, yy, yy + 0.006)
    # the reveal, plastered white from the glass back into the room
    lin = P('int_wall')
    lin.box((x0 - 0.014, I1, z0), (x0, deep, z0 + h))
    lin.box((x0 + w, I1, z0), (x0 + w + 0.014, deep, z0 + h))
    lin.box((x0 - 0.014, I1, z0 + h), (x0 + w + 0.014, deep, z0 + h + 0.014))
    P('int_wood_oak').box((x0 - 0.045, I1, z0 - 0.042), (x0 + w + 0.045, deep + 0.032, z0))


def _curtain_unused(mb, a, b, c, z0, z1, along='x', amp=0.028, wl=0.24):
    """A hanging curtain: a ribbon folded on a sine, from a to b along the
    wall, standing off it at c. Double sided in the browser."""
    n = max(4, int((b - a) / 0.02))
    o = len(mb.v)
    for k in range(n + 1):
        t = a + (b - a) * k / n
        off = amp * math.sin(2.0 * math.pi * (t - a) / wl)
        p = (t, c + off) if along == 'x' else (c + off, t)
        mb.v.append((p[0], p[1], z0))
        mb.v.append((p[0], p[1], z1))
    for k in range(n):
        mb.smooth.add(len(mb.f))
        mb.f.append((o + 2 * k, o + 2 * k + 2, o + 2 * k + 3, o + 2 * k + 1))


# ------------------------------------------------------------------ models
# Downloaded CC0 furniture (Poly Haven). Each model is imported once, baked
# into its own frame with the base at z = 0 and the footprint centred on the
# origin, then dropped into rooms as linked duplicates - the same trick the
# building uses for its loggias, so one mesh serves many placements.
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets')
_models = {}


def load_model(name):
    if name in _models:
        return _models[name]
    path = os.path.join(MODEL_DIR, name, name + '.gltf')
    if not os.path.exists(path):
        print('[flat] model not downloaded: %s' % path)
        _models[name] = None
        return None
    before = set(bpy.data.objects)
    try:
        bpy.ops.import_scene.gltf(filepath=path)
    except Exception as e:
        print('[flat] import failed %s: %s' % (name, e))
        _models[name] = None
        return None
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == 'MESH']
    for o in meshes:
        _fit_budget(o)
    for o in new:
        if o.type != 'MESH':
            bpy.data.objects.remove(o, do_unlink=True)
    if not meshes:
        _models[name] = None
        return None
    # bake each world transform into the mesh so one placement matrix serves all
    for o in meshes:
        o.data.transform(o.matrix_world)
        o.matrix_world = Matrix.Identity(4)
    xs, ys, zs = [], [], []
    for o in meshes:
        for v in o.data.vertices:
            xs.append(v.co.x); ys.append(v.co.y); zs.append(v.co.z)
    cx, cy, z0 = (min(xs) + max(xs)) * .5, (min(ys) + max(ys)) * .5, min(zs)
    off = Matrix.Translation((-cx, -cy, -z0))
    for o in meshes:
        o.data.transform(off)
        o.hide_render = True
        o.hide_viewport = True
    size = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    _models[name] = (meshes, size)
    print('[flat] model %-24s %.2f x %.2f x %.2f m, %d part(s)'
          % (name, size[0], size[1], size[2], len(meshes)))
    return _models[name]


# A downloaded prop arrives at the resolution it was scanned at, which has
# nothing to do with the size it is drawn at here. Measured on 2026-10-14:
# the show flat was 2.6 M triangles and 1.97 M of them were pot plants - one
# POT was 69 k, and the flat holds eight of each plant, so two of the city's
# worth of triangles stood in the corners of the rooms. The whole street is
# 1.6 M. Nothing in this scene is ever more than a few hundred pixels tall,
# so every part is collapsed to a budget as it comes in; the duplicates are
# linked, so each source mesh is decimated once and every copy follows.
#
# Leaves get a bigger budget than solids: a collapse eats thin geometry
# first, and a leaf that loses its silhouette reads as a hole.
PROP_TRIS = 8000            # a solid part - a pot, a frame, a cushion
PROP_TRIS_LEAF = 30000      # anything that is foliage


def _tri_count(me):
    return sum(max(0, len(p.vertices) - 2) for p in me.polygons)


def _fit_budget(o):
    """Collapse one imported part to its triangle budget, in place."""
    name = (o.name + ' ' + (o.data.name or '')).lower()
    for m in o.data.materials:
        if m:
            name += ' ' + m.name.lower()
    # 'plant' is deliberately NOT in this list: every part of a potted plant
    # carries it, so the pot, the pebbles and the dirt were all handed the
    # leaf budget and came through untouched.
    leafy = any(k in name for k in ('leaf', 'leaves', 'foliage', 'frond'))
    budget = PROP_TRIS_LEAF if leafy else PROP_TRIS
    tris = _tri_count(o.data)
    if tris <= budget:
        return tris
    mod = o.modifiers.new('tri_budget', 'DECIMATE')
    mod.decimate_type = 'COLLAPSE'
    mod.use_collapse_triangulate = True
    mod.ratio = max(0.01, budget / float(tris))
    # apply it through the depsgraph rather than bpy.ops: no selection, no
    # view-layer state, and the result is a plain mesh this object then owns
    dg = bpy.context.evaluated_depsgraph_get()
    baked = bpy.data.meshes.new_from_object(o.evaluated_get(dg))
    o.modifiers.remove(mod)
    old = o.data
    o.data = baked
    if old.users == 0:
        bpy.data.meshes.remove(old)
    print('[flat] decimate %-28s %8d -> %7d tris%s'
          % (o.name, tris, _tri_count(baked), '  (leaf)' if leafy else ''))
    return _tri_count(baked)


def place_model(name, coll, x, y, z, rot_z=0.0, width=None, depth=None,
                height=None, scale=None, tag=''):
    """Drop a downloaded model with its base at (x, y, z), turned by rot_z.

    These models are scanned furniture: they already come at the size the real
    thing is, so the default is scale 1 - that is what keeps a chair a chair.
    Give width, depth or height only to nudge a piece to what the room wants,
    and prefer `height`, because height is what the eye measures furniture by.
    A seat at 0.30 or a table at 0.53 reads as a toy however right its plan is.
    """
    rec = load_model(name)
    if rec is None:
        return False
    meshes, size = rec
    s = scale or 1.0
    if width:
        s = width / size[0]
    elif depth:
        s = depth / size[1]
    elif height:
        s = height / size[2]
    print('[flat] place %-24s %-8s %.2f x %.2f x %.2f m'
          % (name, tag, size[0] * s, size[1] * s, size[2] * s))
    for i, src in enumerate(meshes):
        link_dup(src, 'flatm_%s_%s_%d' % (name, tag, i), loc=(x, y, z),
                 rot_z=rot_z, scale=(s, s, s), coll=coll)
    return True


def face_to(x, y, tx, ty):
    """The rot_z that turns a model standing at (x, y) to look at (tx, ty).

    Every seat we use is modelled with its back at +Y, so at rot_z 0 it looks
    down -Y; this is what stops a dining chair being parked side-on to its
    own table.
    """
    return math.atan2(tx - x, -(ty - y))


class Parts:
    """Geometry accumulator, keyed by (item, material).

    One mesh per material would be the fewest draw calls, but then clicking a
    bed in the browser selects every scrap of the same fabric in the flat. So
    the pieces are grouped by ITEM as well, and `at()` says which item the
    following geometry belongs to. The page welds them back together per
    material at load, so the split costs nothing at runtime - except in
    developer mode, where it is exactly what lets you pick one thing.
    """
    def __init__(self):
        self.d = {}
        self.cur = 'misc'
        self.order = []

    def at(self, item):
        self.cur = item
        return self

    def __call__(self, matname, thin=False):
        key = (self.cur, matname, thin)
        if key not in self.d:
            self.d[key] = MB()
            self.order.append(key)
        return self.d[key]

    def emit(self, coll):
        out = []
        for key in self.order:
            item, matname, thin = key
            mb = self.d[key]
            if not mb.f:
                continue
            name = ('flatx_' if thin else 'flat_') + item + '__' + matname
            out.append(mb.to_object(name, M(matname), coll))
        return out


# ------------------------------------------------------------------ doors
def _ccw(pts):
    """Polygon wound counter-clockwise, whichever way it came in."""
    a = 0.0
    for k in range(len(pts)):
        x0, y0 = pts[k]
        x1, y1 = pts[(k + 1) % len(pts)]
        a += x0 * y1 - x1 * y0
    return pts if a > 0 else pts[::-1]


def door(P, pos, w, t0, t1, along='x', hinge='lo', angle=70.0, side=-1,
         leaf='int_door_leaf', frame='int_white_gloss', z0=None, z1=None,
         h=2.05, ztop=None):
    """A real door rather than a board in a hole: a lining through the reveal,
    a mitred architrave on both faces, a 40 mm leaf hung on three butt hinges
    and swung open, a lever handle on a rose each side, and the striking plate
    in the jamb. `pos`/`w` are the structural opening along the wall, `t0`/`t1`
    the wall faces; the leaf hangs at the `lo` or `hi` jamb and swings `angle`
    degrees toward `side`. `ztop` caps the whole door - lining, architrave,
    leaf, lipping and hinges - at the plane the walls are cut on."""
    z0 = FZ if z0 is None else z0
    H = h
    tc = (t0 + t1) * 0.5
    XY = (lambda s, t: (s, t)) if along == 'x' else (lambda s, t: (t, s))
    # What hangs on the hinges goes into an object of its own, `<item>_swing`:
    # the leaf, its lipping and the two handles, which are the only pieces of
    # a door that move when it is opened. Everything else - the lining, the
    # architrave, the hinge barrels standing on the axis and the striking
    # plate in the far jamb - stays in `<item>` and never moves. The page
    # welds the flat per material, so without this split a swinging leaf
    # would take its own doorframe round with it; with it, the browser can
    # pick the four swinging parts of one flat out of the model and turn them
    # about their hinge. See `doorRig` in app.js.
    item, swing = P.cur, P.cur + '_swing'

    def box(mb, s0, ta, zb, s1, tb, zt):
        a = XY(s0, ta); b = XY(s1, tb)
        mb.box((min(a[0], b[0]), min(a[1], b[1]), zb),
               (max(a[0], b[0]), max(a[1], b[1]), zt))

    L = P(frame)
    LT, AW, AP = 0.018, 0.072, 0.016          # lining, architrave width / proud
    # The partitions are sliced well below the door head. Stop the WHOLE door
    # at the same plane as the wall it sits in - the frame and the leaf both -
    # so nothing is left hanging in the air above it: no surround, no raised
    # block beside the door, no blade of a leaf standing over the dollhouse.
    CZ = (z0 + H + LT + AW) if ztop is None else ztop

    def fbox(s0, ta, zb, s1, tb, zt):
        if zb >= CZ - 1e-6:
            return
        box(L, s0, ta, zb, s1, tb, min(zt, CZ))

    # lining: both jambs and the head, carried right through the reveal
    fbox(pos - LT, t0 - 0.002, z0, pos, t1 + 0.002, z0 + H)
    fbox(pos + w, t0 - 0.002, z0, pos + w + LT, t1 + 0.002, z0 + H)
    fbox(pos - LT, t0 - 0.002, z0 + H, pos + w + LT, t1 + 0.002, z0 + H + LT)
    # architrave, one on each face
    for (ta, tb) in ((t0 - AP, t0), (t1, t1 + AP)):
        fbox(pos - LT - AW, ta, z0, pos - LT, tb, z0 + H + LT + AW)
        fbox(pos + w + LT, ta, z0, pos + w + LT + AW, tb, z0 + H + LT + AW)
        fbox(pos - LT - AW, ta, z0 + H + LT, pos + w + LT + AW, tb, z0 + H + LT + AW)

    # ---- the leaf, hung and swung
    th = 0.040
    sgn = 1.0 if hinge == 'lo' else -1.0
    hs = pos if hinge == 'lo' else pos + w
    a = math.radians(angle)
    u = (sgn * math.cos(a), side * math.sin(a))      # along the leaf, in (s, t)
    v = (-u[1], u[0])                                 # across its thickness

    def pt(du, dv):
        return XY(hs + u[0] * du + v[0] * dv, tc + u[1] * du + v[1] * dv)

    # The leaf stops at the cut as well. It used to be the one piece of the
    # door that ignored `ztop`: a 2.05 m leaf in a flat whose walls are 1.47
    # stood 0.6 m proud of every wall in the plan, four white blades over the
    # dollhouse - "door is brokes sometimes ... and whole wall too". The page
    # rebuilds exactly this piece above the cut when a visitor walks into a
    # room (`doorTop` in app.js, which grips 40 mm down into what is left
    # here), so cutting it is what the two halves were always meant to be.
    lz = min(z0 + H - 0.006, CZ)
    lw = w - 0.008
    if lz > z0 + 0.010:
        P.at(swing)
        lf = P(leaf)
        prism(lf, _ccw([pt(0.004, -th / 2), pt(lw, -th / 2), pt(lw, th / 2), pt(0.004, th / 2)]),
              z0 + 0.010, lz)
        # a darker lipping on the three free edges, the way a veneered leaf is made
        lip = P('int_white_gloss')
        prism(lip, _ccw([pt(lw, -th / 2), pt(lw + 0.004, -th / 2),
                         pt(lw + 0.004, th / 2), pt(lw, th / 2)]),
              z0 + 0.010, lz)
        P.at(item)

    # ---- three butt hinges on the hanging stile
    S = P('chrome')
    for hz in (z0 + 0.24, z0 + H * 0.5, z0 + H - 0.24):
        c = pt(0.004, 0.0)
        zb, zt = hz - 0.048, min(hz + 0.048, CZ)
        if zt - zb < 1e-4:
            continue
        S.cyl((c[0], c[1], zb), (c[0], c[1], zt), 0.013, seg=10)

    # ---- lever handle and rose, both faces, at the usual 1.05 m
    hz = z0 + 1.05
    hd = lw - 0.060                                   # back off the leading edge
    HS = P.at(swing)('chrome')
    for face in (-1.0, 1.0):
        r0 = pt(hd, face * th / 2)
        r1 = pt(hd, face * (th / 2 + 0.010))
        HS.cyl((r0[0], r0[1], hz), (r1[0], r1[1], hz), 0.031, seg=14)
        g0 = pt(hd, face * (th / 2 + 0.008))
        g1 = pt(hd, face * (th / 2 + 0.030))
        HS.cyl((g0[0], g0[1], hz), (g1[0], g1[1], hz), 0.011, seg=10)
        lv = pt(hd - 0.105, face * (th / 2 + 0.030))
        HS.cyl((g1[0], g1[1], hz), (lv[0], lv[1], hz - 0.012), 0.010, seg=10)
    P.at(item)

    # ---- the striking plate in the far jamb
    ks = pos + w if hinge == 'lo' else pos - LT
    box(S, ks, tc - 0.028, hz - 0.055, ks + 0.003, tc + 0.028, hz + 0.055)


# ------------------------------------------------------------------ pieces
def lamp(P, x, y, z):
    P('int_brass').cyl((x, y, z), (x, y, z + 0.02), 0.07, seg=14)
    P('int_brass').cyl((x, y, z + 0.02), (x, y, z + 0.30), 0.011, seg=8)
    P('int_lamp_shade').cyl((x, y, z + 0.26), (x, y, z + 0.42), 0.11, 0.085, seg=16, caps=False)


def bed(P, x0, y0, x1, y1, head, duvet, z=None):
    """Bed with its head against side `head` ('-x', '+x', '-y', '+y')."""
    z = FZ if z is None else z
    fr = P('int_wood_walnut'); mt = P('int_fabric_white'); dv = P(duvet)
    hb = P('int_wood_oak'); pl = P('int_fabric_white')
    # 0.30 of frame under 0.24 of mattress: 0.54 to the top, which is the
    # height you sit down onto a real bed at
    rbox(fr, (x0, y0, z), (x1, y1, z + 0.30), 0.03)
    rbox(mt, (x0 + .04, y0 + .04, z + 0.30), (x1 - .04, y1 - .04, z + 0.54), 0.05)
    # duvet from the foot up to the pillows, pillows against the headboard
    pz = z + 0.54
    if head == '-x':
        hb.box((x0 - 0.05, y0 - 0.12, z), (x0, y1 + 0.12, z + 1.10))
        rbox(dv, (x0 + 0.52, y0 + .02, pz), (x1 - .02, y1 - .02, pz + 0.14), 0.08)
        for t in (0.30, 0.70):
            ellipsoid(pl, (x0 + 0.30, y0 + (y1 - y0) * t, pz + 0.07), 0.22, 0.30, 0.08)
    elif head == '+x':
        hb.box((x1, y0 - 0.12, z), (x1 + 0.05, y1 + 0.12, z + 1.10))
        rbox(dv, (x0 + .02, y0 + .02, pz), (x1 - 0.52, y1 - .02, pz + 0.14), 0.08)
        for t in (0.30, 0.70):
            ellipsoid(pl, (x1 - 0.30, y0 + (y1 - y0) * t, pz + 0.07), 0.22, 0.30, 0.08)
    elif head == '+y':
        hb.box((x0 - 0.12, y1, z), (x1 + 0.12, y1 + 0.05, z + 1.10))
        rbox(dv, (x0 + .02, y0 + .02, pz), (x1 - .02, y1 - 0.52, pz + 0.14), 0.08)
        for t in (0.30, 0.70):
            ellipsoid(pl, (x0 + (x1 - x0) * t, y1 - 0.30, pz + 0.07), 0.30, 0.22, 0.08)
    else:
        hb.box((x0 - 0.12, y0 - 0.05, z), (x1 + 0.12, y0, z + 1.10))
        rbox(dv, (x0 + .02, y0 + 0.52, pz), (x1 - .02, y1 - .02, pz + 0.14), 0.08)
        for t in (0.30, 0.70):
            ellipsoid(pl, (x0 + (x1 - x0) * t, y0 + 0.30, pz + 0.07), 0.30, 0.22, 0.08)


def chair(P, cx, cy, ang, mat='int_black', z=None):
    """Dining chair facing `ang` (its back is behind it)."""
    z = FZ if z is None else z
    s = P(mat)
    rbox_rot(s, cx, cy, ang, 0.21, 0.21, z + 0.44, z + 0.48)
    bx, by = rot2(cx, cy, ang, -0.19, 0.0)
    rbox_rot(s, bx, by, ang, 0.02, 0.20, z + 0.48, z + 0.88)
    for dx, dy in ((0.17, 0.17), (0.17, -0.17), (-0.17, 0.17), (-0.17, -0.17)):
        lx, ly = rot2(cx, cy, ang, dx, dy)
        s.cyl((lx, ly, z), (lx, ly, z + 0.44), 0.013, seg=6)


def make_plant_kit(coll):
    """A broad-leaved pot plant, the one in every room of the render. Leaves
    carry a per-blade tint as a vertex colour, as the trees do."""
    pot = MB()
    pot.cyl((0, 0, 0), (0, 0, 0.30), 0.14, 0.17, seg=18)
    pot.cyl((0, 0, 0.30), (0, 0, 0.31), 0.155, 0.155, seg=18)
    o_pot = pot.to_object('flat_plant_pot', M('int_pot'), coll)
    lv = MB()
    r = random.Random(7)
    for i in range(22):
        az = i * 2.399 + r.uniform(-0.3, 0.3)
        el = math.radians(r.uniform(22, 70))
        vd = (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el))
        nd = (-math.sin(el) * math.cos(az) * 0.6, -math.sin(el) * math.sin(az) * 0.6,
              math.cos(el) + 0.5)
        base = (0.03 * math.cos(az), 0.03 * math.sin(az), 0.30 + r.uniform(0.0, 0.08))
        g = r.uniform(0.70, 1.0)
        LC.leaf_blade(lv, base, vd, nd, r.uniform(0.10, 0.145), r, detail=1,
                      tint=(g * 0.95, g, g * 0.9))
    o_lv = lv.to_object('flatx_plant_leaves', M('foliage'), coll)
    for o in (o_pot, o_lv):
        o.hide_render = True
        o.hide_viewport = True
    return o_pot, o_lv


# ------------------------------------------------------------------ the flat
def build_flat():
    _levels()
    coll = collection('flat')
    P = Parts()
    W = lambda: P('int_wall')
    zc = ZC

    # ---------------------------------------------------------- floors
    P.at('floor')
    # To YC, not Y_ENT: the floor has to run under the entrance wall, because
    # the door opening in it is a hole and the black mass that used to stand
    # behind the wall is gone. Without this you look straight down through
    # the two front doors into the storey below.
    P('int_parquet').box((X_GABLE, Y_FAC, Z0), (X_PARTY, YC, FZ))

    # ---------------------------------------------------------- facade
    P.at('facade')
    # The render cuts only the partitions and the wall nearest the camera.
    # The outer walls stand their full height, so every window is a real
    # window with glass and a view out, with the curtains hung at its jambs.
    # The outer shell stops just above the window head rather than at the
    # ceiling: tall enough that every window is whole and the room reads as a
    # room from inside, low enough that the dollhouse shot still looks in.
    ZT = WALL_TOP
    WS, WH = LB.WIN_SILL, LB.WIN_H                   # 1.00 sill, 1.30 tall
    bays, _ = LB.bay_layout(LB.BAYS_A)
    seq = [b[0] for b in bays]
    dark = P('plaster_dark')
    gy = LB.GLASS_Y
    for kind, bx0, bx1, idx in bays[:4]:
        if kind == 'L':
            ox0, ox1 = bx0 + LB.LOG_JL, bx0 + LB.LOG_JL + LB.LOG_OP
            ax0, ax1 = ox0 - LB.LOG_RET, ox1 + LB.LOG_RET
            frame_for(bx0, bx1, Z0, ZT, ox0, ox1, Z0, Z0 + LB.LOG_H, 0.0, LB.LOG_CY, dark)
            frame_for(bx0, bx1, Z0, ZT, ax0, ax1, Z0, Z0 + LB.LOG_H, LB.LOG_CY, LB.LOG_SY, dark)
            frame_for(bx0, bx1, Z0, ZT, ax0, ax1, Z0, Z0 + LB.LOG_H, LB.LOG_SY, LB.WALL_T, dark)
        else:
            first = (idx == 0) or (seq[idx - 1] == 'L')
            wx0 = bx0 + (LB.W1_OFF if first else LB.W2_OFF)
            ww = LB.W1_W if first else LB.W2_W
            frame_for(bx0, bx1, Z0, ZT, wx0, wx0 + ww, Z0 + WS, Z0 + WS + WH,
                      0.0, LB.WALL_T, dark)
            window_unit(P, wx0, ww, Z0 + WS, WH)
            dark.box((wx0 - .035, -0.03, Z0 + WS - .085),
                     (wx0 + ww + .035, LB.WALL_T, Z0 + WS - .018))
            for cx0, cx1 in ((wx0 - 0.58, wx0 - 0.03), (wx0 + ww + 0.03, wx0 + ww + 0.58)):
                curtain_pair(P, cx0, cx1, LB.WALL_T + 0.085, Z0 + 0.02, Z0 + 2.50)
    # White lining on the room side of the facade. It has to span BOTH window
    # bays: window 1 belongs to the living room now and window 2 to the master,
    # so a lining that started at the living | master partition left window 1
    # staring at bare plaster.
    wall_x(W(), LOG_LIV + LB.LOG_OP + LB.LOG_RET, X_BED, Y_FAC, Y_FAC + 0.02, Z0, ZT,
           [(WIN1, WIN1 + WW, Z0 + WS, Z0 + WS + WH), (WIN2, WIN2 + WW, Z0 + WS, Z0 + WS + WH)])

    # ---------------------------------------------------------- loggias
    P.at('loggias')
    (d0, d1), wins = LB.loggia_openings(LB.LOG_OP)
    (w0, w1) = wins[0]
    y1 = LB.WALL_T + LB.LOG_D
    DT, WSL = 2.36, 0.88                              # door head, window sill
    for ox in (LOG_LIV, LOG_BED):
        op = LB.LOG_OP
        sh = P('concrete_loggia')
        # No soffit over the balcony in the show flat. The slab above is the
        # one the cutaway takes away, and a lid over the loggia hid both
        # balconies from the top and the hero shot. The cheeks stop with the
        # rest of the outer shell at ZT so nothing stands proud of the cut.
        sh.box((max(ox - LB.LOG_RET, X_GABLE), LB.LOG_CY, Z0), (ox, y1, ZT))
        sh.box((ox + op, LB.LOG_CY, Z0), (ox + op + LB.LOG_RET, y1, ZT))
        ops = [(ox + d0, ox + d1, Z0, Z0 + DT), (ox + w0, ox + w1, Z0 + WSL, Z0 + DT)]
        wall_x(sh, ox - LB.LOG_RET, ox + op + LB.LOG_RET, y1, y1 + 0.22, Z0, ZT, ops)
        # ...and its room-side lining, in the loggia's own wall material: it
        # stands too deep for the page's shallow cut, and it has to go with
        # the balcony when a storey is opened, not stand there on its own
        wall_x(P('int_wall_loggia'), ox - LB.LOG_RET, ox + op + LB.LOG_RET,
               y1 + 0.22, y1 + 0.24, Z0, ZT, ops)
        g = P('int_glass', thin=True)
        g.panel(ox + d0 + .05, ox + d1 - .05, Z0 + 0.05, Z0 + DT - .05, y1 + .07, y1 + .10)
        g.panel(ox + w0 + .05, ox + w1 - .05, Z0 + WSL + .05, Z0 + DT - .05, y1 + .07, y1 + .10)
        rv0, rv1 = y1 + 0.10, y1 + 0.24
        lin = P('int_wall_loggia')
        for (a, b, c, d) in ((ox + d0, ox + d1, Z0, Z0 + DT),
                             (ox + w0, ox + w1, Z0 + WSL, Z0 + DT)):
            lin.box((a, rv0, c), (a + .014, rv1, d))
            lin.box((b - .014, rv0, c), (b, rv1, d))
            lin.box((a, rv0, d - .014), (b, rv1, d))
            if c > Z0 + 0.01:
                lin.box((a, rv0, c), (b, rv1, c + .014))
        fr = P('frame_bronze')
        for (a, b, c, d) in ((ox + d0, ox + d1, Z0, Z0 + DT),
                             (ox + w0, ox + w1, Z0 + WSL, Z0 + DT)):
            fr.panel(a, a + .06, c, d, y1 + .04, y1 + .13)
            fr.panel(b - .06, b, c, d, y1 + .04, y1 + .13)
            fr.panel(a + .06, b - .06, c, c + .06, y1 + .04, y1 + .13)
            fr.panel(a + .06, b - .06, d - .06, d, y1 + .04, y1 + .13)
        LB.rail_run(P('rail_balcony'), ox + 0.03, ox + op - 0.03, LB.WALL_T + 0.07, Z0)
        P('int_tile_white').box((ox, LB.WALL_T, Z0), (ox + op, y1, FZT))
        for cx0, cx1 in ((ox - 0.58, ox - 0.04), (ox + op + 0.04, ox + op + 0.58)):
            cx0, cx1 = max(cx0, X_GABLE + 0.02), min(cx1, X_PARTY - 0.02)
            if cx1 - cx0 > 0.10:       # the gable end and the party wall are close
                curtain_pair(P, cx0, cx1, y1 + 0.32, Z0 + 0.02, Z0 + 2.50)
    P('int_accent_red').box((LOG_LIV, 0.40, FZT), (LOG_LIV + 0.012, y1 - 0.02, ZT))

    # ---------------------------------------------------------- gable
    P.at('gable')
    gy0, gy1 = 0.02, Y_END
    sa, sb = 4.31 - 1.05 / 2, 4.31 + 1.05 / 2
    sc0 = max(Z0 + 0.03, LB.GROUND_H + FL * LB.FLOOR_H + 0.18)
    sc1 = min(sc0 + 2.40, ZT - 0.08)
    frame_for_yz(gy0, gy1, Z0, ZT, sa, sb, sc0, sc1, 0.0, X_GABLE, P('plaster_light'))
    REV = 0.34
    sfm = 'frame_light' if 'frame_light' in bpy.data.materials else 'frame_bronze'
    rv = P('reveal_dark'); sf = P(sfm); sg = P('int_glass', thin=True)
    rv.panel(0.004, REV, sc0, sc1, sa, sa + 0.035)
    rv.panel(0.004, REV, sc0, sc1, sb - 0.035, sb)
    rv.panel(0.004, REV, sc0, sc0 + 0.035, sa + 0.035, sb - 0.035)
    rv.panel(0.004, REV, sc1 - 0.035, sc1, sa + 0.035, sb - 0.035)
    sf.panel(REV, REV + 0.075, sc0, sc1, sa, sa + 0.06)
    sf.panel(REV, REV + 0.075, sc0, sc1, sb - 0.06, sb)
    sf.panel(REV, REV + 0.075, sc0, sc0 + 0.06, sa + 0.06, sb - 0.06)
    sf.panel(REV, REV + 0.075, sc1 - 0.06, sc1, sa + 0.06, sb - 0.06)
    sf.panel(REV, REV + 0.065, sc0 + 0.06, sc1 - 0.06, 4.31 - 0.05, 4.31 + 0.05)
    sg.panel(REV + 0.05, REV + 0.07, sc0 + .06, sc1 - .06, sa + .06, 4.31 - 0.05)
    sg.panel(REV + 0.05, REV + 0.07, sc0 + .06, sc1 - .06, 4.31 + 0.05, sb - .06)
    wall_y(W(), Y_LOG, Y_ENT, X_GABLE, X_GABLE + 0.02, Z0, ZT, [(sa, sb, sc0, sc1)])

    # ---------------------------------------------------------- walls
    P.at('walls')
    # outer shell full height; entrance wall and every partition cut low so
    # the flat still reads as a dollhouse from above
    W().box((X_PARTY, Y_FAC, Z0), (XC, Y_END, ZT))                       # party wall
    wall_x(W(), X_GABLE, X_PARTY, Y_ENT, YC, Z0, zc, [(7.40, 8.30, Z0, zc)])   # entrance wall
    # Cheek beside the gable loggia. It stops at the start of the window bay -
    # tying it to X_LIV buried window 1 under a full-height block once the
    # living | master partition moved into the pier between the two windows.
    W().box((LOG_LIV + LB.LOG_OP + LB.LOG_RET, Y_FAC, Z0), (WIN1 - 0.62, Y_LOG, ZT))
    W().box((X_BED, Y_FAC, Z0), (LOG_BED - LB.LOG_RET, Y_LOG, ZT))
    W().box((LOG_BED + LB.LOG_OP + LB.LOG_RET, Y_FAC, Z0), (X_PARTY, Y_LOG, ZT))
    wall_y(W(), Y_FAC, Y_ENT, X_LIV, X_LIV + PT, Z0, zc, [(6.30, Y_ENT, Z0, zc)])
    wall_x(W(), X_LIV + PT, X_PARTY, Y_P23, Y_P23 + PT, Z0, zc,
           [(6.30, 7.10, Z0, zc), (9.30, 10.10, Z0, zc)])
    W().box((X_BED, Y_FAC, Z0), (X_BED + PT, Y_P23, zc))
    wall_y(W(), Y_P23 + PT, Y_ENT, X_BATH, X_BATH + PT, Z0, zc, [(6.35, 7.15, Z0, zc)])


    # ---------------------------------------------------------- doors
    P.at('door_entrance'); door(P, 7.40, 0.92, Y_ENT, YC, 'x', 'lo', 68, -1,
                               leaf='int_door_leaf', ztop=zc)
    # The back line's flat is this one mirrored at A_DEPTH, so its entrance
    # door is the same opening on the other face of the same wall: without
    # this you look through two open front doors into the flat behind. The
    # panel closes ours 30 mm short of the outer face - the mirrored copy's
    # sits in the 30 mm beyond it, so the two never share a plane - and it is
    # dark, which is what stood behind the door when the mass was there.
    P('int_stone_dark').box((7.40, YC - 0.03, Z0), (8.32, YC, zc))
    P.at('door_master');   door(P, 6.30, 0.80, Y_P23, Y_P23 + PT, 'x', 'hi', 70, -1, ztop=zc)
    P.at('door_bed2');     door(P, 9.30, 0.80, Y_P23, Y_P23 + PT, 'x', 'lo', 75, -1, ztop=zc)
    P.at('door_bath');     door(P, 6.35, 0.80, X_BATH, X_BATH + PT, 'y', 'lo', 84, -1, ztop=zc)

    # ---------------------------------------------------------- living room
    # gable end, full depth: seating at the facade, dining and the L-shaped
    # kitchen in the back corner, the TV on the gable wall
    # Measured off the render: the rug runs from the balcony wall back past
    # the seating, and the armchair, the dark table and the little round one
    # all stand ON it, lined up against the bedroom partition.
    P.at('rug_living')
    # placed from the developer gizmo: centre 4.121, 2.885 on the floor. The
    # chair and the low table ride the same offset so the pair stays on it.
    P('int_rug').box((3.036, 0.835, FZ), (5.206, 4.935, FZ + 0.014))
    # The lounge chair at the size the model was built, 0.82 x 0.99 x 1.02 -
    # it used to be stretched to a metre across, and a 1.24 m tall armchair is
    # what made the whole room read like a doll's house. Turned on the TV.
    TVY = 2.95
    place_model('modern_arm_chair_01', coll, 4.58, 2.66, FZ + 0.014,
                rot_z=face_to(4.58, 2.66, X_GABLE, TVY), tag='liv')
    # the render's pair: a dark low table in front of the chair (1.20 x 0.60 x
    # 0.39, its own size) and the small round white one at the foot of it
    place_model('modern_coffee_table_01', coll, 3.52, 2.78, FZ + 0.014,
                rot_z=0.0, tag='liv')
    place_model('coffee_table_round_01', coll, 3.76, 1.70, FZ + 0.014, rot_z=0.4,
                width=0.88, tag='livside')
    # tv wall on the gable, clear of the slot window above it
    P.at('tv_wall')
    P('int_marble').box((X_GABLE, TVY - 1.04, FZ), (X_GABLE + 0.10, TVY + 1.04, zc - 0.03))
    # the long low unit of the render: 1.90 x 0.40 x 0.53, a sideboard's height
    place_model('modern_wooden_cabinet', coll, X_GABLE + 0.31, TVY, FZ,
                rot_z=math.pi / 2, width=1.90, tag='tv')
    # a 55 inch set: 1.22 x 0.69 is 16:9, hung with its centre at 1.00 - eye
    # height from an armchair. The old one was 0.95 x 0.70, which is no TV.
    P('int_black').box((X_GABLE + 0.135, TVY - 0.61, FZ + 0.66),
                       (X_GABLE + 0.175, TVY + 0.61, FZ + 1.35))
    P.at('side_cabinet')
    # a console, not a crate: 0.42 deep and 0.74 to the top, so the lamp on it
    # stands where a lamp stands
    P('int_black').box((X_GABLE, 4.88, FZ), (X_GABLE + 0.42, 5.86, FZ + 0.74))
    P('int_white_gloss').box((X_GABLE, 4.90, FZ + 0.05), (X_GABLE + 0.40, 5.84, FZ + 0.66))
    lamp(P, X_GABLE + 0.21, 5.37, FZ + 0.74)

    # ---- dining, in front of the kitchen
    # The downloaded table is a farmhouse plank table under a gingham cloth,
    # and squeezing it to fit left a 0.53 m high table the chairs towered
    # over. The render's is a plain white rectangle on slim legs, so that is
    # what this is: 1.50 x 0.90 at 0.75, with the four chairs at their own
    # size, two to a long side, each tucked 40 mm under the top and turned to
    # face the table across it.
    P.at('dining_table')
    DX, DY = 2.92, 6.46
    DW, DD, DH = 0.90, 1.50, 0.75
    P('int_marble').box((DX - DW / 2, DY - DD / 2, FZ + DH - 0.04),
                        (DX + DW / 2, DY + DD / 2, FZ + DH))
    P('int_white_gloss').box((DX - DW / 2 + 0.03, DY - DD / 2 + 0.03, FZ + DH - 0.07),
                             (DX + DW / 2 - 0.03, DY + DD / 2 - 0.03, FZ + DH - 0.04))
    for lx in (DX - DW / 2 + 0.08, DX + DW / 2 - 0.08):
        for ly in (DY - DD / 2 + 0.08, DY + DD / 2 - 0.08):
            P('int_black').cyl((lx, ly, FZ), (lx, ly, FZ + DH - 0.07), 0.021, seg=10)
    P.at('dining_chairs')
    for k, (cx_, cy_) in enumerate(((DX - 0.70, DY - 0.37), (DX - 0.70, DY + 0.37),
                                    (DX + 0.70, DY - 0.37), (DX + 0.70, DY + 0.37))):
        place_model('dining_chair_02', coll, cx_, cy_, FZ,
                    rot_z=face_to(cx_, cy_, DX, cy_), tag='din%d' % k)
    # a plate and a bowl on the table, as the render has
    P.at('dining_setting')
    P('int_ceramic').cyl((DX - 0.02, DY + 0.26, FZ + DH), (DX - 0.02, DY + 0.26, FZ + DH + 0.016), 0.135, seg=20)
    P('int_black').cyl((DX + 0.04, DY - 0.24, FZ + DH), (DX + 0.04, DY - 0.24, FZ + DH + 0.085), 0.105, 0.125, seg=20)
    # kitchen: an L in the back corner - down the gable wall and along the
    # entrance wall - with the render's mint worktop
    P.at('kitchen')
    K = P('int_white_gloss'); MT = P('int_mint')
    K.box((X_GABLE, 5.95, FZ + 0.10), (X_GABLE + 0.60, Y_ENT, FZ + 0.86))
    K.box((X_GABLE + 0.60, Y_ENT - 0.60, FZ + 0.10), (1.90, Y_ENT, FZ + 0.86))
    P('int_black').box((X_GABLE, 5.95, FZ), (X_GABLE + 0.55, Y_ENT, FZ + 0.10))
    P('int_black').box((X_GABLE + 0.60, Y_ENT - 0.55, FZ), (1.90, Y_ENT, FZ + 0.10))
    MT.box((X_GABLE, 5.93, FZ + 0.86), (X_GABLE + 0.63, Y_ENT, FZ + 0.90))
    MT.box((X_GABLE + 0.63, Y_ENT - 0.63, FZ + 0.86), (1.92, Y_ENT, FZ + 0.90))
    MT.box((X_GABLE, 5.93, FZ + 0.90), (X_GABLE + 0.03, Y_ENT, zc - 0.02))      # splashback
    MT.box((X_GABLE + 0.03, Y_ENT - 0.03, FZ + 0.90), (1.92, Y_ENT, zc - 0.02))
    P('int_black').box((X_GABLE + 0.06, 6.42, FZ + 0.90), (X_GABLE + 0.58, 7.02, FZ + 0.906))
    P('chrome').box((X_GABLE + 0.08, 7.45, FZ + 0.885), (X_GABLE + 0.50, 7.95, FZ + 0.902))
    P('chrome').cyl((X_GABLE + 0.10, 7.70, FZ + 0.90), (X_GABLE + 0.10, 7.70, FZ + 1.22), 0.012, seg=8)
    P('chrome').cyl((X_GABLE + 0.10, 7.70, FZ + 1.20), (X_GABLE + 0.32, 7.70, FZ + 1.20), 0.010, seg=8)
    P('int_wood_teak').box((1.94, Y_ENT - 0.66, FZ), (2.60, Y_ENT, zc - 0.05))   # tall unit
    # the run reaches to Y_ENT, so the handles are spread over it at roughly
    # the 0.65 pitch they were drawn at rather than at four fixed metres -
    # with the deeper hall the last 0.60 of door had no handle on it
    hy0, hy1 = 6.20, Y_ENT - 0.15
    nh = max(1, int(round((hy1 - hy0) / 0.65)))
    for k in range(nh + 1):
        yy = hy0 + (hy1 - hy0) * k / nh
        P('int_brass').box((X_GABLE + 0.60, yy - 0.06, FZ + 0.78), (X_GABLE + 0.615, yy + 0.06, FZ + 0.80))

    # ---------------------------------------------------------- master
    # no headboard unit: the bed stands straight against the partition
    HB = X_LIV + PT + 0.04
    P.at('bed_master')
    bed(P, HB, 2.10, HB + 2.10, 3.90, '-x', 'int_fabric_teal')
    place_model('throw_pillows_01', coll, HB + 0.58, 3.00, FZ + 0.54, rot_z=0.2,
                scale=0.95, tag='bedpil')
    # 0.50 x 0.46 x 0.52 nightstands - a bedside table is a small thing, and
    # the 0.58 x 0.60 blocks that stood here read as sideboards
    for k, y0 in enumerate((1.42, 3.98)):
        P.at('nightstand_master_%d' % k)
        P('int_white_gloss').box((HB + 0.02, y0, FZ), (HB + 0.48, y0 + 0.50, FZ + 0.52))
        lamp(P, HB + 0.25, y0 + 0.25, FZ + 0.52)
    P.at('rug_master')
    P.at('wardrobe_master')
    # against the hall wall on the far side of the bedroom door, so the door
    # swing stays clear; it used to run from the partition, which left it 16 cm
    # wide once the partition moved between the windows
    P('int_wood_teak').box((7.20, 4.70, FZ), (X_BED, Y_P23, zc - 0.06))
    P('int_wood_teak').box((7.17, 4.70, zc - 0.06), (X_BED, Y_P23, zc))
    P.at('rug_master')
    P('int_rug').box((5.85, 1.80, FZ), (8.25, 4.30, FZ + 0.012))

    # ---------------------------------------------------------- bedroom 2
    # A 1.95 x 1.60 double with its head on the party wall, and pulled back
    # off the loggia: it used to stand 0.18 m from the balcony threshold with
    # its headboard floating half a metre short of the wall, so nobody could
    # have reached their own balcony. Now the strip in front of it is 0.68 m
    # and the column past its foot 0.82 m - a room you can walk round.
    P.at('bed_bed2')
    bed(P, 9.34, 2.75, 11.29, 4.35, '+x', 'int_fabric_bluegrey')
    P.at('rug_bed2')
    P('int_rug').box((8.75, 2.50, FZ), (11.34, 4.70, FZ + 0.012))
    P.at('nightstand_bed2')
    P('int_white_gloss').box((10.79, 4.38, FZ), (11.29, 4.86, FZ + 0.52))
    P.at('lamp_bed2')
    # on the nightstand, where a bedside lamp goes; it used to sit on the floor
    lamp(P, 11.04, 4.62, FZ + 0.52)

    # ---------------------------------------------------------- bathroom
    # Built the way one is actually fitted out: a tiled duct carrying the
    # concealed cistern with a wall-hung pan in front of it, a bath with a
    # rolled rim and a glass screen, a countertop basin on a teak vanity, a
    # tall mixer, a mirror with its light, a heated rail and a floor gully.
    P.at('bath_tiles')
    C = P('int_ceramic'); S = P('chrome'); G = P('int_glass', thin=True)
    TW = P('int_tile_wall'); TF = P('int_tile_floor')
    bx0, bx1 = X_BATH + PT, X_PARTY            # inside faces, side to side
    by0, by1 = Y_P23 + PT, Y_ENT               # front to back
    TF.box((bx0, by0, Z0), (bx1, by1, FZT))    # floor
    # The hall-side wall is tiled only where it is solid. It used to be tiled
    # straight across the door opening, so a ceramic sheet stood in the middle
    # of the doorway.
    DO0, DO1 = 6.35, 7.15                      # the bathroom door opening
    TW.box((bx0, by0, FZT), (bx0 + 0.015, DO0, zc))
    TW.box((bx0, DO1, FZT), (bx0 + 0.015, by1, zc))
    TW.box((bx1 - 0.015, by0, FZT), (bx1, by1, zc))
    TW.box((bx0, by0, FZT), (bx1, by0 + 0.015, zc))
    TW.box((bx0, by1 - 0.015, FZT), (bx1, by1, zc))
    S.cyl((bx0 + 1.55, by0 + 1.10, FZT), (bx0 + 1.55, by0 + 1.10, FZT + 0.004), 0.055, seg=16)

    # ---- bath along the back wall, rolled rim, apron, screen
    P.at('bathtub')
    C = P('int_ceramic'); S = P('chrome'); G = P('int_glass', thin=True)
    tx0, tx1 = bx0 + 0.02, bx0 + 1.72
    ty1 = by1 - 0.02
    ty0 = ty1 - 0.76
    RIM = FZT + 0.58
    for (a_, b_, c_, d_) in ((tx0, tx0 + 0.055, ty0, ty1), (tx1 - 0.055, tx1, ty0, ty1),
                             (tx0, tx1, ty0, ty0 + 0.055), (tx0, tx1, ty1 - 0.055, ty1)):
        rbox(C, (a_, c_, FZT), (b_, d_, RIM), 0.022, seg=3)
    C.box((tx0 + 0.055, ty0 + 0.055, FZT), (tx1 - 0.055, ty1 - 0.055, FZT + 0.10))   # tub floor
    S.cyl((tx0 + 0.86, ty0 + 0.36, FZT + 0.10), (tx0 + 0.86, ty0 + 0.36, FZT + 0.112), 0.045, seg=14)
    # mixer, riser rail and handset on the end wall
    S.cyl((tx0 + 0.07, ty0 + 0.30, RIM), (tx0 + 0.07, ty0 + 0.30, RIM + 0.16), 0.019, seg=12)
    S.cyl((tx0 + 0.07, ty0 + 0.30, RIM + 0.14), (tx0 + 0.34, ty0 + 0.30, RIM + 0.16), 0.014, seg=12)
    S.cyl((bx0 + 0.055, ty0 + 0.22, FZT + 0.95), (bx0 + 0.055, ty0 + 0.22, FZT + 1.42), 0.013, seg=10)
    S.cyl((bx0 + 0.07, ty0 + 0.22, FZT + 1.26), (bx0 + 0.19, ty0 + 0.22, FZT + 1.30), 0.017, seg=12)
    # a glass screen standing on the rim at the tap end
    G.box((tx0 + 0.02, ty0 + 0.04, RIM), (tx0 + 0.034, ty1 - 0.10, zc - 0.02))
    S.box((tx0 + 0.016, ty0 + 0.04, RIM), (tx0 + 0.040, ty0 + 0.09, zc - 0.02))

    # ---- tiled duct with the concealed cistern, wall-hung pan in front
    P.at('wc')
    C = P('int_ceramic'); S = P('chrome'); TW = P('int_tile_wall')
    dx0, dx1 = bx0 + 1.86, bx0 + 2.46
    TW.box((dx0, by0 + 0.02, FZT), (dx1, by0 + 0.30, FZT + 1.08))
    S.box((dx0 + 0.16, by0 + 0.295, FZT + 0.88), (dx1 - 0.16, by0 + 0.306, FZT + 1.02))  # flush plate
    # pan 0.26-0.40 with the seat on top: you sit on a WC at 0.42, not 0.59
    rbox(C, (dx0 + 0.07, by0 + 0.30, FZT + 0.26), (dx1 - 0.07, by0 + 0.86, FZT + 0.40), 0.14, seg=4)
    C.box((dx0 + 0.13, by0 + 0.30, FZT + 0.18), (dx1 - 0.13, by0 + 0.62, FZT + 0.28))
    rbox(P('int_white_gloss'), (dx0 + 0.07, by0 + 0.32, FZT + 0.40),
         (dx1 - 0.07, by0 + 0.84, FZT + 0.425), 0.15, seg=4)                            # seat

    # ---- teak vanity, countertop basin, tall mixer, mirror with a light
    P.at('vanity')
    C = P('int_ceramic'); S = P('chrome')
    vx0, vx1 = bx1 - 0.92, bx1 - 0.04
    vy0, vy1 = by0 + 0.30, by0 + 0.86      # 0.56 deep: a vanity, not a worktop
    P('int_wood_teak').box((vx0, vy0, FZT + 0.22), (vx1, vy1, FZT + 0.78))
    P('int_marble').box((vx0 - 0.02, vy0 - 0.02, FZT + 0.78), (vx1, vy1 + 0.02, FZT + 0.82))
    cbx, cby = (vx0 + vx1) * .5, (vy0 + vy1) * .5
    rbox(C, (cbx - 0.21, cby - 0.17, FZT + 0.82), (cbx + 0.21, cby + 0.17, FZT + 0.95), 0.08, seg=4)
    S.cyl((cbx + 0.30, cby, FZT + 0.82), (cbx + 0.30, cby, FZT + 1.12), 0.016, seg=12)
    S.cyl((cbx + 0.30, cby, FZT + 1.10), (cbx + 0.09, cby, FZT + 1.12), 0.013, seg=12)
    P('int_mirror').box((bx1 - 0.022, vy0 - 0.06, FZT + 1.02), (bx1 - 0.014, vy1 + 0.06, zc - 0.03))
    P('int_lamp_shade').box((bx1 - 0.05, vy0 - 0.08, zc - 0.05), (bx1 - 0.016, vy1 + 0.08, zc - 0.03))

    # ---- heated towel rail with a folded towel, and a bath mat
    P.at('towel_rail')
    S = P('chrome')
    for k in range(6):
        hz = FZT + 0.62 + k * 0.115
        S.cyl((dx1 + 0.16, by0 + 0.06, hz), (dx1 + 0.70, by0 + 0.06, hz), 0.011, seg=8)
    for sx in (dx1 + 0.16, dx1 + 0.70):
        S.cyl((sx, by0 + 0.06, FZT + 0.58), (sx, by0 + 0.06, FZT + 1.26), 0.014, seg=8)
    rbox(P('int_fabric_white'), (dx1 + 0.22, by0 + 0.055, FZT + 0.74),
         (dx1 + 0.62, by0 + 0.115, FZT + 1.20), 0.02)
    # off the tub, not off the front wall: the bathroom got 0.60 m deeper
    # when the entrance wall moved back and the mat stayed behind, stranded
    # in the middle of the floor. These are the metres it had from the tub.
    rbox(P('int_fabric_white'), (bx0 + 0.30, ty0 - 0.70, FZT), (bx0 + 1.10, ty0 - 0.22, FZT + 0.016), 0.03)

    # ---------------------------------------------------------- hall
    P.at('bench_hall')
    P('int_wood_oak').box((6.20, Y_ENT - 0.36, FZ), (7.30, Y_ENT - 0.02, FZ + 0.44))
    rbox(P('int_fabric_dark'), (6.22, Y_ENT - 0.34, FZ + 0.44), (7.28, Y_ENT - 0.04, FZ + 0.49), 0.02)
    P('int_fabric_dark').box((7.45, Y_ENT - 0.62, FZ), (8.25, Y_ENT - 0.02, FZ + 0.012))
    # on the solid piece of the bathroom wall past the door, not across the
    # opening - it used to hang in mid-air inside the open doorway
    P('int_mirror').box((X_BATH - 0.012, 7.28, FZ + 0.9), (X_BATH, 8.08, zc - 0.03))

    # ---------------------------------------------------------- plants
    for k, (name, x, y, z, h) in enumerate((
            ('potted_plant_01', 8.05, 0.95, FZ, 1.32),
            ('potted_plant_02', X_GABLE + 0.42, 4.30, FZ, 0.84),
            ('potted_plant_01', LOG_LIV + 0.30, 1.05, FZT, 1.10),
            ('potted_plant_02', LOG_BED + 1.38, 1.05, FZT, 0.80))):
        place_model(name, coll, x, y, z, rot_z=rnd.uniform(0, 6.28), height=h,
                    tag='p%d' % k)

    P.emit(coll)

    # ---------------------------------------------------------- the cutaway
    # The roof slab over the loggia soffits, on both elevations. The street
    # never sees it, but the lifted lid does: without it the soffit tops of
    # the top-floor loggias read as pale bars along the roof edge.
    D = LB.A_DEPTH
    LOGY = LB.WALL_T + LB.LOG_D + 0.26
    rp = MB()
    rp.box((0.0, 0.60, TOPF), (LB.A_LEN, LOGY, TOPF + 0.14))
    rp.box((0.0, D - LOGY, TOPF), (LB.A_LEN, D - 0.60, TOPF + 0.14))
    rp.to_object('A_roof_patch', M('plaster_dark'), collection('blockA'))
    build_row(coll)
    build_back_row(coll)
    build_fills()
    carve_cutaway()
    return coll


# ------------------------------------------------------------------ the row
def row_starts():
    """Where each copy of the flat begins, on block A's own bay table."""
    return [_BAYS[4 * u][1] for u in ROW_UNITS]


def row_shrink():
    """How much wider unit 0 is than the units the copies stand in."""
    return (_BAYS[3][2] - _BAYS[0][1]) - (_BAYS[7][2] - _BAYS[4][1])


def build_row(coll):
    """Three more flats east along the street, from the one we have.

    Each copy is the same geometry with `row_shrink()` taken out at
    ROW_SEAM. The first copy owns the warped meshes; the other two are
    linked duplicates of it, so the glTF carries two flats and four nodes.
    """
    x0, starts, dx = _BAYS[0][1], row_starts(), row_shrink()
    base = [ob for ob in list(coll.objects) if ob.name.startswith('flat')]
    first = []
    for ob in base:
        nb = ob.copy()
        nb.name = ob.name + '_u1'
        if ob.name.startswith('flatm_'):
            # a downloaded model: it shares its mesh and is placed by its
            # matrix, so it travels whole, on the side of the seam it stands
            nb.location.x += starts[0] - x0 - (dx if ob.location.x > ROW_SEAM else 0.0)
        else:
            nb.data = ob.data.copy()
            for v in nb.data.vertices:
                if v.co.x > ROW_SEAM:
                    v.co.x -= dx
            nb.location.x += starts[0] - x0
        coll.objects.link(nb)
        first.append(nb)
    for u, st in zip(ROW_UNITS[1:], starts[1:]):
        for ob in first:
            nb = ob.copy()                      # shares the warped mesh
            nb.name = ob.name[:-3] + '_u%d' % u
            nb.location.x += st - starts[0]
            coll.objects.link(nb)
    print('[flat] row: %d copies at %s, %.2f m taken out at the seam'
          % (len(starts), ', '.join('%.2f' % s for s in starts), dx))


# ------------------------------------------------------------- the back line
def build_back_row(coll):
    """The same four flats again on the back line of the top floor.

    The back of block A is its street elevation mirrored at `A_DEPTH`, so a
    flat mirrored with it keeps every opening it was fitted to: loggias in the
    loggia bays, windows in the window bays, at the same x as the flat in
    front of it. Turning the flat round by 180 degrees - which is what the
    word rotate means in a plan - would reverse x too, and unit 0's first
    window bay is 0.30 m wider than the rest, so nothing would line up.

    Each procedural mesh is mirrored once and the linked duplicates go on
    sharing it, so the back line costs two flats of geometry, not four. The
    downloaded furniture is not mirrored at all: a reflected chair is still a
    chair, so each model keeps its own mesh and is simply placed at the
    mirrored point, turned the mirrored way.

    That turn is `pi - theta`, not `-theta`, and the difference is the whole
    of it. Reflecting the WHOLE object in y - mesh and all - is the
    conjugation My.Rz(t).My = Rz(-t); but we are deliberately not reflecting
    the mesh, and Rz(-t) is the angle that goes with a mesh that HAS been
    reflected. Writing My = Rz(pi).Mx and leaning on the one symmetry every
    seat has - a chair is its own mirror image left to right - gives
    My.Rz(t).V = Rz(pi - t).Mx.V ~= Rz(pi - t).V, so the un-reflected model
    belongs at pi - t.

    With -t every chair in the back line was turned a half-turn from where
    it should stand: the four round the dining table sat looking out of the
    room instead of across the table, and the TV cabinet faced into the
    gable wall. The two chairs that flank the table on the x axis are the
    case that shows it, because a reflection in y leaves which SIDE of the
    table they stand on alone while -t swaps which way they look.
    """
    D = LB.A_DEPTH
    mirrored, n = {}, 0
    for ob in [o for o in list(coll.objects) if o.name.startswith('flat')]:
        nb = ob.copy()
        nb.name = ob.name + '_bk'
        if ob.name.startswith('flatm_'):
            nb.rotation_euler = (ob.rotation_euler.x, ob.rotation_euler.y,
                                 math.pi - ob.rotation_euler.z)
        else:
            me = mirrored.get(ob.data.name)
            if me is None:
                me = ob.data.copy()
                me.name = ob.data.name + '_bk'
                for v in me.vertices:
                    v.co.y = -v.co.y
                me.flip_normals()
                mirrored[ob.data.name] = me
            nb.data = me
        nb.location = (ob.location.x, D - ob.location.y, ob.location.z)
        coll.objects.link(nb)
        n += 1
    print('[flat] back line: %d objects, %d meshes mirrored at y=%.2f'
          % (n, len(mirrored), D * 0.5))


# ------------------------------------------------------------------ the fills
def build_fills():
    """Everything that has to stand on the open top floor once the cutaway
    has taken the building away, and the slab that stops you seeing through
    the block when a storey is lifted.

    With a line of flats on each side of the floor and the two lines meeting
    at YC, the spine that used to run between the entrance walls is gone -
    what is left up here is the pier between one unit and the next, and that
    now runs the whole depth in one piece. Nothing up here goes above
    WALL_TOP: the rule is that no black stands taller than the flat's walls.
    """
    D = LB.A_DEPTH
    x0, dx = _BAYS[0][1], row_shrink()
    unit_w = _BAYS[7][2] - _BAYS[4][1]
    cells = [(x0, _BAYS[3][2])] + [(st, st + unit_w) for st in row_starts()]
    spans = [(0.03, XC)] + [(st + (0.03 - x0), st + (XC - x0 - dx))
                            for st in row_starts()]
    XE = cells[-1][1]

    top = MB()
    for (ca, cb), (sa, sb) in zip(cells, spans):
        if cb - sb > 1e-6:          # the pier beside the flat, front to back
            top.box((sb, LB.WALL_T, Z0), (cb, D - LB.WALL_T, WALL_TOP))
    top.to_object('A_top_fill', M('plaster_dark'), collection('blockA'))

    # The same spine for every other storey. Block A's mass is a single sided
    # shell, so from inside it you look straight out through the back of it:
    # hover a floor on the page, where the street wall is taken away, and the
    # rooms had the sky behind them instead of the middle of the building.
    # East of the flats there is no cutaway, so there it runs to the parapet.
    # It used to be the whole 1.20 m spine; with the two lines meeting there
    # is no spine left to fill, so it is the party wall the two lines share,
    # SPINE_T thick about the middle of the plan.
    sy0, sy1 = Y_END - SPINE_T * 0.5, D - Y_END + SPINE_T * 0.5
    ib = MB()
    ib.box((0.03, sy0, LB.GROUND_H), (XE, sy1, Z0))
    ib.box((XE, sy0, LB.GROUND_H), (LB.A_LEN - 0.03, sy1, LB.ROOF_Z - 0.10))
    ib.to_object('A_inner_fill', M('plaster_dark'), collection('blockA'))


# ------------------------------------------------------------------ cutaway
def split_by_box(ob, box, suffix='__cut'):
    """Bisect the mesh on the box's six planes and move every face whose
    centre lies inside the box to a new object `name.cut` with the same
    material, in the same collections. Returns it, or None if nothing fell
    inside."""
    x0, y0, z0, x1, y1, z1 = box
    me = ob.data
    bm = bmesh.new()
    bm.from_mesh(me)
    for co, no in (((x0, 0, 0), (1, 0, 0)), ((x1, 0, 0), (1, 0, 0)),
                   ((0, y0, 0), (0, 1, 0)), ((0, y1, 0), (0, 1, 0)),
                   ((0, 0, z0), (0, 0, 1)), ((0, 0, z1), (0, 0, 1))):
        bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:],
                               dist=1e-5, plane_co=co, plane_no=no)
    bm.faces.ensure_lookup_table()
    inside = set()
    for f in bm.faces:
        c = f.calc_center_median()
        if x0 < c.x < x1 and y0 < c.y < y1 and z0 < c.z < z1:
            inside.add(f.index)
    if not inside:
        bm.free()
        return None
    bm2 = bm.copy()
    bm2.faces.ensure_lookup_table()
    bmesh.ops.delete(bm2, geom=[f for f in bm2.faces if f.index not in inside],
                     context='FACES')
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index in inside],
                     context='FACES')
    bm.to_mesh(me)
    bm.free()
    me2 = bpy.data.meshes.new(me.name + suffix)
    bm2.to_mesh(me2)
    bm2.free()
    for m in me.materials:
        me2.materials.append(m)
    ob2 = bpy.data.objects.new(ob.name + suffix, me2)
    for c in ob.users_collection:
        c.objects.link(ob2)
    return ob2


def carve_cutaway():
    """Split the top-floor cells out of block A's merged meshes, and tag the
    kit instances that stand in them.

    One box per flat, and there are eight of them now: four along the street
    and the same four on the back line. Unit 0's is the fitted one, which
    stops at its party wall and leaves the building standing in the pier
    before unit 1; each copy's box is its whole bay cell, because the copy
    brings its own facade for the full width and `build_fills` stands the
    pier beside it. Every piece carries a suffix the page reads as cut
    (`__cut`, `__cut1`, ...), so a second split never collides with the
    first one's name - and the suffix has to stay `__cut` plus digits,
    because that is the regex `groupOf` in app.js matches."""
    D = LB.A_DEPTH
    unit_w = _BAYS[7][2] - _BAYS[4][1]
    cells = [(-5.0, _BAYS[3][2])] + [(st, st + unit_w) for st in row_starts()]
    raw = [(ca, -5.0, Z0, cb, Y_END, 300.0) for ca, cb in cells] \
        + [(ca, D - Y_END, Z0, cb, D + 5.0, 300.0) for ca, cb in cells]
    # The cells are contiguous across the four units and the two lines meet
    # at Y_END, so between them they take the whole depth of the storey. The
    # ninth box this used to carry - the spine above WALL_TOP, where a 1.20 m
    # fin of the mass stood over the flats - has nothing left to cut.
    boxes = [(b, '__cut' if i == 0 else '__cut%d' % i) for i, b in enumerate(raw)]
    n = 0
    for name in ('A_facade_dark', 'A_facade_back', 'A_gable_light', 'A_mass',
                 'A_roof_patch', 'A_slot_glass', 'A_slot_frame', 'A_slot_reveal'):
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        for box, suffix in boxes:
            if split_by_box(ob, box, suffix) is not None:
                n += 1
    last = 4 * (1 + len(ROW_UNITS)) - 1          # the bays of the four flats
    pat = re.compile(r'_f%d_b(\d+)$' % FL)
    inst = bpy.data.collections.get('A_openings')
    k = 0
    if inst:
        for ob in list(inst.objects):
            m = pat.search(ob.name)
            if not m:
                continue
            b = int(m.group(1))                  # BACK_BAY up: back elevation
            if (b - LB.BACK_BAY if b >= LB.BACK_BAY else b) <= last:
                ob.name = ob.name + '__cut'
                k += 1
    print('[flat] cutaway: %d meshes split over %d cells, %d kit instances tagged'
          % (n, len(boxes), k))


def write_meta(root, path):
    """Where the flat is, in the browser's frame, so the page can aim its
    second camera without repeating the fit."""
    import json
    from mathutils import Matrix
    mw = Matrix.Translation(root.location) @ root.rotation_euler.to_matrix().to_4x4()
    def to3(v):
        w = mw @ Vector(v)
        return [round(w.x, 4), round(w.z, 4), round(-w.y, 4)]
    def dir3(v):
        w = mw.to_3x3() @ Vector(v)
        return [round(w.x, 5), round(w.z, 5), round(-w.y, 5)]
    meta = {
        'flat': {
            'center': to3(CENTER),
            'origin': to3((0.0, 0.0, Z0)),
            'ex': dir3((1, 0, 0)),      # along the street, from the gable
            'ey': dir3((0, 1, 0)),      # into the plan
            'size': [XC, Y_END],
            # The sales plan was rectified to the flat at the depth it was
            # measured; the flat is deeper now, so the overlay keeps its own
            # size and goes on registering with the rooms.
            'plan_size': [XC, PLAN_D],
            # the whole row of flats, so the page can frame it in one shot
            # - and where each unit of it begins along `ex`, so the floor
            # view can step from one flat to the next without the page
            # having to know anything about the bay table.
            'row': {'n': len(ROW_UNITS),
                    'starts': [round(s, 3) for s in [_BAYS[0][1]] + row_starts()],
                    'end': round(row_starts()[-1] + (_BAYS[7][2] - _BAYS[4][1]), 3)},
            'floor': Z0 + 0.02,
            'cut': CUT_H,
            # The plan itself, in the flat's own metres. The page keeps the
            # same table (`FM` in app.js) to rebuild the top of the flat
            # when a visitor walks into a room, and it was a HAND COPY until
            # one of these moved and the copy did not: `Y_ENT` went from
            # 8.20 to 8.80 when the two lines of flats were brought together
            # at the middle of the block, and the room shell went on
            # building the entrance wall 0.60 m thick with the front door's
            # leaf 0.30 m out of its own opening - a door and a wall that
            # broke in half at the cut line, but only from inside a room.
            # Written out here instead, so the two cannot drift again.
            'plan': {
                'X_GABLE': X_GABLE, 'X_PARTY': X_PARTY,
                'Y_FAC': Y_FAC, 'Y_LOG': round(Y_LOG, 4),
                'Y_ENT': Y_ENT, 'YC': YC,
                'X_LIV': X_LIV, 'X_BED': X_BED, 'X_BATH': X_BATH,
                'Y_P23': Y_P23, 'PT': PT,
                'LOG_LIV': LOG_LIV, 'LOG_BED': LOG_BED,
                'LOG_OP': LB.LOG_OP, 'LOG_RET': LB.LOG_RET,
                'SEAM': ROW_SEAM,
                # the parquet, and the balcony tiling 5 mm over it: a body
                # walking the flat stands on whichever of the two is under it
                'FZ': round(FZ - Z0, 4), 'FZT': round(FZT - Z0, 4),
                'CUT': round(ZC - Z0, 4),
                'TOP': round(WALL_TOP - Z0, 4),
                'DOOR_H': 2.05, 'LT': 0.018, 'AW': 0.072, 'AP': 0.016,
            },
        },
        # The near corner of block A at parapet top - the gable / facade
        # junction the hero is composed on. The page pins it under the top
        # edge of the window while the hero camera travels, so the building
        # keeps the same headroom all the way through the sweep.
        'block': {
            'corner': to3((0.0, 0.0, LB.ROOF_Z)),
            # ...and the middle of the mass, which the hero camera circles
            'center': to3((LB.A_LEN * 0.5, LB.A_DEPTH * 0.5, LB.ROOF_Z * 0.5)),
            # The storeys of the street front, for the page's floor map: the
            # facade runs from the corner above along `ex` for `len` metres,
            # storey 1 standing on the podium at `base` and each one `h`
            # tall. The page lays a band over each storey to hover.
            'floors': {'n': LB.N_FLOORS, 'base': LB.GROUND_H,
                       'h': LB.FLOOR_H, 'len': LB.A_LEN, 'depth': LB.A_DEPTH},
        },
    }
    with open(path, 'w') as fh:
        json.dump(meta, fh, indent=1)
    print('[flat] meta -> %s' % path)
