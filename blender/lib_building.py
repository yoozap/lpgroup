# -*- coding: utf-8 -*-
"""The two blocks' envelopes, built storey by storey from the architect's plan."""
import bpy, math, random, json, os
from mathutils import Vector
from lib_build import (MB, mat, srgb, link_dup, frame_for, frame_for_yz, collection,
                       mirror_y, mirror_obj_y, rnd)

# ------------------------------------------------------------------ palette
def build_materials():
    mat('plaster_dark',    srgb('#231f1b'), rough=0.90)
    mat('plaster_dark_b',  srgb('#1c1915'), rough=0.90)   # wing return wall
    mat('plaster_light',   srgb('#b6b0a7'), rough=0.92)
    mat('concrete_loggia', srgb('#c3bcae'), rough=0.86)
    mat('concrete_podium', srgb('#b2aca4'), rough=0.82)
    mat('concrete_frame',  srgb('#b9b2a6'), rough=0.84)
    mat('stone_classical', srgb('#cdc5b6'), rough=0.88)
    mat('stone_classical_b', srgb('#c2bbae'), rough=0.9)
    mat('metal_dark',      srgb('#191a1d'), rough=0.38, metal=0.85)
    # balcony balustrade: a painted light-warm-grey metal, not the near black
    # of the street railings - it reads clearly lighter than the loggia behind
    mat('rail_balcony',    srgb('#a2998b'), rough=0.73, metal=0.18)
    mat('frame_bronze',    srgb('#2b2724'), rough=0.42, metal=0.55)
    mat('frame_light',     srgb('#d9d6ce'), rough=0.48, metal=0.30)
    mat('glass_window',    srgb('#0c1014'), rough=0.06, metal=0.0, ior=1.52)
    # the punched windows: same pane, its own name so the web can keep the
    # blind down behind every one of them
    mat('glass_blind',     srgb('#0c1014'), rough=0.06, metal=0.0, ior=1.52)
    mat('glass_lit',       srgb('#1a1208'), rough=0.18,
        emis=srgb('#ffb55e'), emis_str=3.2)
    # the pale blind behind every pane: this is what makes a window read as a
    # window from the street rather than a dark hole punched in the wall
    mat('blind',           srgb('#d9d5cc'), rough=0.92,
        emis=srgb('#e8e6df'), emis_str=0.6)
    # stair / corridor slots in the gable: no blind behind them, so they stay
    # dark against the light render - exactly as in the reference
    mat('glass_slot',      srgb('#0a0d11'), rough=0.05, ior=1.52)
    mat('reveal_dark',     srgb('#17161a'), rough=0.55)
    mat('glass_shop',      srgb('#0a0c0f'), rough=0.05)
    mat('shop_interior',   srgb('#6b5c48'), rough=0.75,
        emis=srgb('#ffd9a0'), emis_str=0.9)
    mat('neon_orange',     srgb('#ff5712'), rough=0.4,
        emis=srgb('#ff5712'), emis_str=9.0)
    mat('sign_metal',      srgb('#3a3a3c'), rough=0.35, metal=0.7)
    mat('asphalt',         srgb('#3b3a3c'), rough=0.72)
    mat('road_paint',      srgb('#cfcdc6'), rough=0.6)
    mat('sidewalk',        srgb('#9b958e'), rough=0.85)
    mat('curb',            srgb('#8d8880'), rough=0.8)
    mat('grass',           srgb('#4a5c2a'), rough=0.9)
    mat('soil',            srgb('#3b332a'), rough=0.95)
    mat('bark',            srgb('#4b4239'), rough=0.9)
    mat('foliage',         srgb('#52702f'), rough=0.72)
    mat('foliage_b',       srgb('#617f36'), rough=0.72)
    mat('canopy_fabric',   srgb('#e8e6e0'), rough=0.65)
    mat('bus_green',       srgb('#79c143'), rough=0.3, metal=0.1)
    mat('tire',            srgb('#121214'), rough=0.85)
    mat('chrome',          srgb('#c9ccd0'), rough=0.18, metal=1.0)
    mat('car_glass',       srgb('#0b0e12'), rough=0.05)
    for i, c in enumerate(['#1a1d22', '#8d9299', '#2d3b52', '#6e6f72', '#b9bcc0',
                           '#30271f', '#1d4731', '#5a5e63', '#7a7b7f', '#262a2f']):
        mat('car_paint_%d' % i, srgb(c), rough=0.22, metal=0.55)
    mat('person', srgb('#2e2c30'), rough=0.85)
    mat('pole_metal', srgb('#232529'), rough=0.45, metal=0.6)
    # the DINER sign's box: the interiors' accent red, a name materials.js
    # already maps (the page styles by name; nothing new is added there)
    mat('int_accent_red', srgb('#8b2d29'), rough=0.6)
    # the L01 offices' side of the street's own outer wall (see LIN_L01_T):
    # the interior's wall finish, by name
    mat('int_wall', srgb('#d9d5cc'), rough=0.92)
    # the terrace's timber (planter-benches, cafe chairs, pergola slats): the
    # interiors' oak, procedural in materials.js (no maps to wait for)
    mat('int_wood_oak', srgb('#b3895a'), rough=0.55)
    # the neighbour blocks (lib_hood): their own names, so the page can give
    # them the architect's stone without touching the block's own materials
    mat('hood_panel',      srgb('#cfc8c0'), rough=0.70)   # honed panels, upper floors
    mat('hood_stone_low',  srgb('#b8ad9f'), rough=0.88)   # rough granite, lower order
    mat('hood_roof',       srgb('#a39a94'), rough=0.45, metal=0.3)   # zinc
    mat('hood_shopglass',  srgb('#1e1f1c'), rough=0.10)   # shop glass, black piers, frames
    mat('hood_awning',     srgb('#2a3650'), rough=0.90)   # navy canvas


M = lambda n: bpy.data.materials[n]

# ------------------------------------------------------------------ the plan
# Everything below is driven by the architect's plans, read by
# tools/plan_extract.py into blender/plans/plan.json (see CONTRACT.md there).
#
#   plan frame     x along the lettered axes a..J (0 .. 82.5), y along the
#                  numbered axes 1..10 (+y = the street side), z = level label
#   Blender local  (x, -y, z) under BuildingRoot - so the street is -y, as it
#                  always was in this file
#
# The photo fit this file used to carry (3.0 m storeys, a 55.6 m bar, a
# gallery wing) is gone: storeys, footprints, every window and every loggia
# mouth now come from the plan, level by level. What stays is the kit - the
# loggia, the punched window, the railing, the glazing - and the materials,
# which are the owner's look and are not touched.
PLAN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'plans', 'plan.json')
with open(PLAN_PATH) as _f:
    PLAN = json.load(_f)
LEVELS = {l['level']: l for l in PLAN['levels']}

FLOOR_H   = 3.30       # residential and office storey
GROUND_H  = 4.80       # commercial storey; the podium roof / terrace is +4.800
TOP_Z     = 37.80      # roof slab (ROOF level)
PARAPET   = 1.50       # wing frame top band, 006: ~1.5 m over the top loggia head
# ...measured from that head: L10 +34.50 + the 2.95 m loggia mouth. It was
# added to the roof slab (+37.80), a band 1.85 m deep over the top row where
# 006 has ~1.4 m (the wing end, against its 1.0 m pilasters)
ROOF_Z    = 34.50 + 2.95 + PARAPET   # 38.95 parapet top
ROOF_SLAB_Z0 = TOP_Z - 0.15     # roof slab underside, over the L10 ceilings (+37.50)
CEIL_CLEAR_L00 = GROUND_H - 0.25  # +4.55: street slabs' underside inside the podium (L00 ceilings +4.50)
HEAD_Z    = 40.20      # stair / lift heads (three level marks on the roof sheet)
# The facade leaf, from the face line in. The plan's wall poche is 0.206 m
# (rooms start 0.206 in from every face line on L02..L10) and the interiors
# line it 0.012 into the room, so the street's leaf stops short of both: at
# 0.30 it stood 9 cm proud of the lining and every flat's outside wall read
# black from inside.
WALL_T    = 0.19
JOINT_X   = PLAN['meta']['joint']['x']          # 44.4, the i|k expansion joint
JOINT_GAP = 0.05       # half width of the shadow gap drawn at the joint
CORNER_FRAME = 1.00    # the wing's SW corner frame, plan L03/L05 poche 61.85..62.85 x 35.55..36.55

# the storeys that carry the tower facade: (level id, z, data level). The
# +4.800 office floor wears the residential facade in every render (and the
# "summer areas cancelled" note on its sheet is not drawn in any of them),
# so it is built from the first residential floor's data at its own height.
FACADE_LEVELS = [('L01', 4.8, 'L02')] + [
    (l['level'], l['z'], l['level']) for l in PLAN['levels'] if l['kind'] == 'residential']

# loggia kit section (local: x across the mouth, y from the face inward, z up)
LOG_H   = 2.95     # mouth height; the 0.35 m slab band between stacked loggias
LOG_RET = 0.185    # cheek thickness, past the mouth on each side
LOG_CY  = 0.02     # cheek front face, set back behind the wall face
LOG_SY  = 0.10     # soffit and slab front face, set back further still
WIN_H   = 1.50     # punched window hole (006: square two-light windows)
WIN_W   = 1.50     # ...and the plan's standard window width
WIN_SILL = 0.90
SLOT_H, SLOT_SILL = 2.40, 0.30       # the light west gable's tall windows
LIN_L01_T = 0.012  # the interior's LIN_OUT: its lining stands this proud of a wall
GLASS_Y = 0.14     # glass back face 0.215 in: flush with the interior's lining

RL = random.Random(20261124)     # lit windows; NOT the shared rnd (trees)
RLX = random.Random(901)         # ...and the windows build 3 adds on L01


def B(p):
    """plan (x, y) -> Blender local (x, -y)"""
    return (p[0], -p[1])


def block_of(x):
    return 'A' if x < JOINT_X else 'B'


# ------------------------------------------------------------------ geometry helpers
def _area(pts):
    a = 0.0
    for i in range(len(pts)):
        x0, y0 = pts[i]; x1, y1 = pts[(i + 1) % len(pts)]
        a += x0 * y1 - x1 * y0
    return a * 0.5


def clean_poly(pts, tol=0.004):
    """drop duplicate and collinear vertices of an axis-aligned polygon"""
    p = [tuple(v) for v in pts]
    if len(p) > 1 and abs(p[0][0] - p[-1][0]) < tol and abs(p[0][1] - p[-1][1]) < tol:
        p = p[:-1]
    changed = True
    while changed and len(p) > 3:
        changed = False
        out = []
        n = len(p)
        for i in range(n):
            a, b, c = p[i - 1], p[i], p[(i + 1) % n]
            if abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol:
                changed = True
                continue
            cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            if abs(cross) < tol * 0.05:
                changed = True
                continue
            out.append(b)
        p = out
    return p


def in_poly(pt, poly):
    x, y = pt
    c = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                c = not c
        j = i
    return c


def prism(mb, pts, z0, z1, caps=(True, True), sides=True):
    """Vertical prism over a simple polygon in Blender local xy."""
    p = list(pts)
    if _area(p) < 0:
        p.reverse()
    n = len(p)
    o = len(mb.v)
    mb.v.extend([(x, y, z0) for (x, y) in p])
    mb.v.extend([(x, y, z1) for (x, y) in p])
    if caps[0]:
        mb.f.append(tuple(o + n - 1 - k for k in range(n)))
    if caps[1]:
        mb.f.append(tuple(o + n + k for k in range(n)))
    if sides:
        for k in range(n):
            j = (k + 1) % n
            mb.f.append((o + k, o + j, o + n + j, o + n + k))


# ------------------------------------------------------------------ railings
def rail_run(mb, a, b, y, z):
    """The baluster railing every balcony on the scheme carries: two flats and
    a picket run at 89 mm. Local x runs along the railing, y is the face it
    stands on, z the balcony floor."""
    mb.box((a, y, z + 1.02), (b, y + 0.05, z + 1.07))
    mb.box((a, y, z + 0.07), (b, y + 0.04, z + 0.11))
    n = max(2, int(round((b - a - 0.06) / 0.089)))
    for k in range(n + 1):
        x = a + 0.03 + (b - a - 0.06) * k / n
        mb.box((x - 0.009, y + 0.005, z + 0.09), (x + 0.009, y + 0.022, z + 1.03))


def loggia_openings(op):
    """Door and window(s) in the glazed back wall of a loggia `op` wide."""
    if op < 3.0:
        d0, dw = 0.14, min(0.86, op * 0.44)
        w0 = d0 + dw + 0.16
        return (d0, d0 + dw), [(w0, op - 0.14)]
    d0, dw = 0.16, 0.90
    n = 2 if op > 3.6 else 1
    gap = 0.34
    ww = (op - (d0 + dw) - 0.16 - gap * n) / n
    wins, x = [], d0 + dw + gap
    for k in range(n):
        wins.append((x, x + ww))
        x += ww + gap
    return (d0, d0 + dw), wins


# ------------------------------------------------------------------ bevel baked into the sources
def bake_bevel(ob, width=0.012):
    """Apply the 12 mm chamfer to a kit source once. A modifier left on the
    objects makes the exporter write every linked duplicate as its own mesh
    (measured: 180 loggia shells -> 180 meshes); baked into the source, nine
    floors of one window are one mesh on the wire."""
    m = ob.modifiers.new('bevel', 'BEVEL')
    m.width = width
    m.segments = 1
    m.limit_method = 'ANGLE'
    m.angle_limit = math.radians(35.0)
    m.harden_normals = True
    m.use_clamp_overlap = True
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    me.name = old.name
    bpy.data.meshes.remove(old)
    return ob


def _hide(obs):
    for o in obs:
        o.hide_render = True
        o.hide_viewport = True


# ------------------------------------------------------------------ module kit (hidden sources)
_KIT = {}


LG_SPANS = {}        # kit shell name -> its door / window spans
LG_PLACED = []       # (level, node, origin, t, n, z, kit shell name), Blender local


def loggia_module(op, d, kind='res', louvre='', oneway=False, gap=None, back=None, sides=None,
                  cheeks=(None, None), trims=(None, None), rail=True, bdoors=None):
    """Source objects for one recessed loggia `op` wide and `d` deep, reused
    as linked duplicates. Local x runs across the mouth, y from the face into
    the recess, z up from the floor. `kind` 'common' is the stair-hall loggia
    at C1/C2 with a solid parapet band instead of a railing; `louvre` 'l'/'r'
    puts the white AC screen against that cheek (the pocket the plan draws
    beside every flat's loggia)."""
    op = round(op, 2); d = round(d, 2)
    if gap:
        gap = (round(gap[0], 2), round(gap[1], 2))
    # `back` / `sides`: the openings the PLAN draws in this loggia - spans
    # (a, b) across the back wall, and ('l'|'r', y0, y1) down a cheek, where a
    # room beside the loggia has its own door onto it. Without them the kit
    # guessed one door and a window in the back and left every cheek blank:
    # a window on the sheet, a wall on the building.
    back = tuple(sorted((round(a, 2), round(b, 2)) for (a, b) in back)) if back else None
    sides = tuple(sorted((sd, round(a, 2), round(b, 2)) for (sd, a, b) in sides)) if sides else ()
    if louvre and any(q == louvre for (q, _a, _b) in sides):
        louvre = ''                 # a door in that cheek, not an AC screen
    # `cheeks` (left, right): a cheek's depth from the face (None: the full
    # depth; 0: none - the balcony runs on past that end); `trims`: the back
    # wall stops that far in from that end (the other arm of a wrap-round
    # loggia is there); `rail` False: a niche opening onto another loggia
    cheeks = tuple(None if c is None else round(c, 2) for c in cheeks)
    trims = tuple(round(t, 2) if t else 0.0 for t in trims)
    # `bdoors`: spans across the back wall where the interior hangs a glazed
    # leaf (plan_meta). They are the doors; the rest of each opening is window.
    bdoors = tuple(sorted((round(a, 2), round(b, 2)) for (a, b) in bdoors)) if bdoors else ()
    key = ('lg', op, d, kind, louvre, oneway, gap, back, sides, cheeks, trims, rail, bdoors)
    if key in _KIT:
        return _KIT[key]
    coll = collection('kit')
    tag = 'kit_lg%03dx%03d%s%s%s%s' % (int(op * 100 + .5), int(d * 100 + .5),
                                       'c' if kind == 'common' else '', louvre,
                                       'o' if oneway else '',
                                       ('g%03d' % int(gap[0] * 100 + .5)) if gap else '')
    if back is not None or sides or cheeks != (None, None) or any(trims) or not rail or bdoors:
        tag += 'p%02d' % (sum(1 for k in _KIT if k[0] == 'lg') % 100)
    # `oneway` (the office storey, build 3): the L01 interior is built from
    # its own sheet, whose offices run out to the face line, so this loggia's
    # back wall, glazing and cheeks stand INSIDE an office. Seen from the
    # street nothing changes; every face that would only be seen from inside
    # (the back of the back wall, glass and frames, the cheeks' outer sides)
    # is left out, and the page culls back faces - so from the office the
    # loggia is a bay of its own room. `gap`: an open doorway (local x a..b)
    # in the back wall where an L01 door leads through it (the wing's corridor
    # door d9 onto the terrace).
    IN = ('+y', '-x', '+x', '-z', '+z') if oneway else ()
    shell = MB()
    BW = 0.19          # back wall: inside the plan's 0.206 poche, as WALL_T
    shell.box((-LOG_RET, LOG_SY, LOG_H), (op + LOG_RET, d + BW, FLOOR_H),
              ('+y',) if oneway else ())                                       # soffit / slab
    DT, WS = 2.36, 0.88
    side_holes = []                                     # (x mid of the cheek, y0, y1)
    for sd, x0, x1, skip, cd in (('l', -LOG_RET, 0.0, ('-x', '+y'), cheeks[0]),
                                 ('r', op, op + LOG_RET, ('+x', '+y'), cheeks[1])):
        de = d if cd is None else min(d, cd)
        if de <= LOG_CY + 1e-6:
            continue                                    # no cheek at this end
        hs = sorted((max(a, LOG_CY + 0.10), min(b, de - 0.04)) for (q, a, b) in sides if q == sd)
        hs = [h for h in hs if h[1] - h[0] >= 0.5]
        y = LOG_CY
        for (a, b) in hs:
            if a > y + 1e-6:
                shell.box((x0, y, 0.0), (x1, a, LOG_H), skip if oneway else ())
            shell.box((x0, a, DT), (x1, b, LOG_H), skip if oneway else ())
            side_holes.append(((x0 + x1) * 0.5, a, b))
            y = b
        if de > y + 1e-6:
            shell.box((x0, y, 0.0), (x1, de, LOG_H), skip if oneway else ())                 # cheeks
    if back is None:
        (ox0, ox1), wins = loggia_openings(op)
        doors = [(ox0, ox1)]
    else:
        # the plan's spans, dressed the kit's way: a door, and where the
        # opening is wide enough a window beside it under one head
        doors, wins = [], []
        for (a, b) in back:
            a, b = max(a, 0.06), min(b, op - 0.06)
            if b - a < 0.5:
                continue
            if b - a < 1.3:
                doors.append((a, b))
            else:
                doors.append((a, a + 0.86))
                wins.append((a + 0.86, b))
        if not doors:
            (ox0, ox1), wins = loggia_openings(op)
            doors = [(ox0, ox1)]
    if bdoors:
        # the interior's leaves decide which part of an opening is the door
        spans = [(max(a, 0.06), min(b, op - 0.06)) for (a, b) in (back or ())]
        spans = [sp for sp in spans if sp[1] - sp[0] >= 0.5]
        doors = [(max(a, 0.02), min(b, op - 0.02)) for (a, b) in bdoors]
        doors = [dd for dd in doors if dd[1] - dd[0] >= 0.4]
        if not spans:
            # the plan draws no window here: the default windows, clear of the doors
            spans = loggia_openings(op)[1]
        wins = []
        for (a, b) in spans:
            cuts = sorted(dd for dd in doors if dd[1] > a and dd[0] < b)
            x = a
            for (da, db) in cuts:
                if da - x >= 0.45:
                    wins.append((x, da))
                x = max(x, db)
            if b - x >= 0.45:
                wins.append((x, b))
    if gap:
        wins = [w for w in wins if w[1] <= gap[0] - 0.05 or w[0] >= gap[1] + 0.05]
    if gap:
        doors = [w for w in doors if w[1] <= gap[0] - 0.05 or w[0] >= gap[1] + 0.05]
    bx0, bx1 = trims[0], op - trims[1]               # the back wall's run
    # ...carried on past an end left open, to meet the niche's own cheek
    if cheeks[0] is not None and cheeks[0] <= LOG_CY:
        bx0 = -LOG_RET
    if cheeks[1] is not None and cheeks[1] <= LOG_CY:
        bx1 = op + LOG_RET
    doors = [w for w in doors if w[0] >= bx0 - 1e-6 and w[1] <= bx1 + 1e-6]
    wins = [w for w in wins if w[0] >= bx0 - 1e-6 and w[1] <= bx1 + 1e-6]
    holes = sorted([(a, b, 'door') for (a, b) in doors] + [(a, b, 'win') for (a, b) in wins] +
                   ([(gap[0], gap[1], 'gap')] if gap else []))
    edges = [bx0] + [v for h in holes for v in h[:2]] + [bx1]
    for k in range(0, len(edges) - 1, 2):
        if edges[k + 1] > edges[k] + 1e-6:
            shell.panel(edges[k], edges[k + 1], 0.0, LOG_H, d, d + BW, IN)
    for (a, b, hk) in holes:
        shell.panel(a, b, DT, LOG_H, d, d + BW, IN)
        if hk == 'win':
            shell.panel(a, b, 0.0, WS, d, d + BW, IN)
    parts = {}
    parts['shell'] = bake_bevel(shell.to_object(tag + '_shell', M('concrete_loggia'), coll))
    g = MB()
    for (a, b) in doors:
        g.panel(a + .05, b - .05, 0.05, DT - .05, d + 0.07, d + 0.10, IN)
    for (xm, a, b) in side_holes:
        g.box((xm - 0.015, a + .05, 0.05), (xm + 0.015, b - .05, DT - .05))
    for (a, b) in wins:
        g.panel(a + .05, b - .05, WS + .05, DT - .05, d + 0.07, d + 0.10, IN)
    parts['glass'] = g.to_object(tag + '_glass', M('glass_window'), coll)
    parts['lit'] = g.to_object(tag + '_glasslit', M('glass_lit'), coll)
    fr = MB()
    for (xm, a, b) in side_holes:
        fr.box((xm - .045, a, 0.0), (xm + .045, a + .06, DT))
        fr.box((xm - .045, b - .06, 0.0), (xm + .045, b, DT))
        fr.box((xm - .045, a + .06, 0.0), (xm + .045, b - .06, 0.06))
        fr.box((xm - .045, a + .06, DT - .06), (xm + .045, b - .06, DT))
    for (a, b, c, e) in [(a, b, 0.0, DT) for (a, b) in doors] + [(a, b, WS, DT) for (a, b) in wins]:
        fr.panel(a, a + .06, c, e, d + .04, d + .13, IN)
        fr.panel(b - .06, b, c, e, d + .04, d + .13, IN)
        fr.panel(a + .06, b - .06, c, c + .06, d + .04, d + .13, IN)
        fr.panel(a + .06, b - .06, e - .06, e, d + .04, d + .13, IN)
    for (a, b) in wins:
        fr.panel((a + b) * .5 - .025, (a + b) * .5 + .025, WS + .06, DT - .06, d + .04, d + .12, IN)
    parts['frame'] = bake_bevel(fr.to_object(tag + '_frame', M('frame_bronze'), coll))
    if kind == 'common':
        pb = MB()
        pb.box((0.0, 0.02, 0.0), (op, 0.24, 1.08))
        parts['parapet'] = bake_bevel(pb.to_object(tag + '_parapet', M('plaster_dark'), coll))
    elif rail:
        r = MB()
        rail_run(r, 0.03, op - 0.03, 0.12, 0.0)
        parts['rail'] = r.to_object(tag + '_rail', M('rail_balcony'), coll)
    if louvre:
        lv = MB()
        x0, x1 = (0.004, 0.05) if louvre == 'l' else (op - 0.05, op - 0.004)
        y0, y1 = 0.22, min(d - 0.12, 1.02)
        lv.box((x0, y0, 0.05), (x1, y0 + 0.04, LOG_H - 0.05))
        lv.box((x0, y1 - 0.04, 0.05), (x1, y1, LOG_H - 0.05))
        z = 0.12
        while z < LOG_H - 0.12:
            lv.box((x0, y0 + 0.04, z), (x1, y1 - 0.04, z + 0.035))
            z += 0.085
        parts['louvre'] = lv.to_object(tag + '_louvre', M('frame_light'), coll)
    _hide(parts.values())
    _KIT[key] = parts
    # what was opened where, in the module's frame: the interior's glazed
    # leaves must stand in these doors (tools/lgdoorcheck.py)
    LG_SPANS[parts['shell'].name] = {'doors': doors, 'wins': wins, 'd': d,
                                     'sides': [(xm, a, b) for (xm, a, b) in side_holes]}
    return parts


def window_module(w, h, slot=False):
    """Punched window built in layers: reveal, sill, frame, sash, glass, each
    set back a little further (the dark body's two-light window), or - `slot`
    - the light gable's tall window: pale frame, thin dark mullion, no blind."""
    w = round(w, 2); h = round(h, 2)
    key = ('wn', w, h, slot)
    if key in _KIT:
        return _KIT[key]
    coll = collection('kit')
    tag = 'kit_%s%03dx%03d' % ('sl' if slot else 'wn', int(w * 100 + .5), int(h * 100 + .5))
    parts = {}
    if slot:
        REV, MULL = 0.06, 0.06
        cx = w * 0.5
        sg = MB(); sf = MB(); sm = MB(); rv = MB()
        rv.panel(0.0, 0.035, 0.0, h, 0.004, REV)
        rv.panel(w - 0.035, w, 0.0, h, 0.004, REV)
        rv.panel(0.035, w - 0.035, 0.0, 0.035, 0.004, REV)
        rv.panel(0.035, w - 0.035, h - 0.035, h, 0.004, REV)
        sg.panel(0.06, cx - MULL / 2, 0.06, h - 0.06, REV + 0.05, REV + 0.07)
        sg.panel(cx + MULL / 2, w - 0.06, 0.06, h - 0.06, REV + 0.05, REV + 0.07)
        sf.panel(0.0, 0.06, 0.0, h, REV, REV + 0.075)
        sf.panel(w - 0.06, w, 0.0, h, REV, REV + 0.075)
        sf.panel(0.06, w - 0.06, 0.0, 0.06, REV, REV + 0.075)
        sf.panel(0.06, w - 0.06, h - 0.06, h, REV, REV + 0.075)
        sm.panel(cx - MULL / 2, cx + MULL / 2, 0.06, h - 0.06, REV, REV + 0.065)
        parts['glass'] = sg.to_object(tag + '_glass', M('glass_slot'), coll)
        parts['frame'] = bake_bevel(sf.to_object(tag + '_frame', M('frame_light'), coll))
        parts['mullion'] = sm.to_object(tag + '_mullion', M('frame_bronze'), coll)
        parts['reveal'] = rv.to_object(tag + '_reveal', M('reveal_dark'), coll)
        _hide(parts.values())
        _KIT[key] = parts
        return parts
    g = MB()
    g.panel(0.0, w, 0.0, h, GLASS_Y + 0.055, GLASS_Y + 0.075)
    parts['glass'] = g.to_object(tag + '_glass', M('glass_blind'), coll)
    parts['lit'] = g.to_object(tag + '_glasslit', M('glass_lit'), coll)
    f = MB()
    t, sg_ = 0.062, 0.042
    y0, y1 = GLASS_Y - 0.075, GLASS_Y + 0.055
    f.panel(0.0, t, 0.0, h, y0, y1)
    f.panel(w - t, w, 0.0, h, y0, y1)
    f.panel(t, w - t, 0.0, t, y0, y1)
    f.panel(t, w - t, h - t, h, y0, y1)
    f.panel(t, t + sg_, t, h - t, GLASS_Y - 0.012, GLASS_Y + 0.062)
    f.panel(w - t - sg_, w - t, t, h - t, GLASS_Y - 0.012, GLASS_Y + 0.062)
    f.panel(t + sg_, w - t - sg_, t, t + sg_, GLASS_Y - 0.012, GLASS_Y + 0.062)
    f.panel(t + sg_, w - t - sg_, h - t - sg_, h - t, GLASS_Y - 0.012, GLASS_Y + 0.062)
    f.panel(w * .5 - .022, w * .5 + .022, t + sg_, h - t - sg_, GLASS_Y - 0.008, GLASS_Y + 0.058)
    parts['frame'] = bake_bevel(f.to_object(tag + '_frame', M('frame_bronze'), coll))
    sl = MB()
    sl.add([(-0.035, -0.030, -0.085), (w + 0.035, -0.030, -0.085),
            (w + 0.035, WALL_T, -0.085), (-0.035, WALL_T, -0.085),
            (-0.035, -0.030, -0.045), (w + 0.035, -0.030, -0.045),
            (w + 0.035, WALL_T, -0.018), (-0.035, WALL_T, -0.018)],
           [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6),
            (3, 0, 4, 7), (1, 2, 6, 5)])
    parts['sill'] = bake_bevel(sl.to_object(tag + '_sill', M('plaster_dark'), coll))
    _hide(parts.values())
    _KIT[key] = parts
    return parts


def _theta(n):
    """rot_z that turns a module's local +y (into the wall) onto -n, where n
    is the outward normal in Blender local xy; local +x then runs along
    t = (cos, sin)."""
    return math.atan2(n[0], -n[1])


def place(parts, name, origin, n, z, coll, lit_p=0.0, skip=(), rng=None):
    th = _theta(n)
    lit = (rng or RL).random() < lit_p
    out = []
    for k, src in parts.items():
        if k in skip:
            continue
        if k == 'lit' and not lit:
            continue
        if k == 'glass' and lit and 'lit' in parts:
            continue
        out.append(link_dup(src, '%s_%s' % (name, k), loc=(origin[0], origin[1], z),
                            rot_z=th, coll=coll))
    return out


# ------------------------------------------------------------------ the office storey's own sheet
# L01 wears L02's facade (every render shows it so), but its interior is built
# from its own sheet (blender/build_interior.py), whose offices run out to the
# face line behind long glazed runs. Two things here keep the inside honest
# without changing the street: a loggia whose back wall would stand inside an
# office is built one-way (see loggia_module), with an open doorway where an
# L01 door leads through it; and where an office's glazed run meets the
# copied facade's plain wall, that wall gets standard windows.
def _l01_sheet():
    """(glazed runs of the L01 sheet behind an office or the corridor, L01
    door leaves as plan segments from web/plan_meta.json)"""
    runs = []
    for r in LEVELS['L01']['facade']:
        if r['state'] != 'open' or not r['behind']:
            continue
        if not (r['behind'].startswith('unit') or r['behind'] == 'corridor'):
            continue
        (ax, ay), (bx, by) = r['a'], r['b']
        if abs(ay - by) < 1e-3:
            runs.append(('x', ay, min(ax, bx), max(ax, bx)))
        elif abs(ax - bx) < 1e-3:
            runs.append(('y', ax, min(ay, by), max(ay, by)))
    doors = []
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'web', 'plan_meta.json')
    try:
        with open(path) as f:
            pm = json.load(f)
        L = [l for l in pm['levels'] if l['id'] == 'L01'][0]
        for d in list(L.get('doors', [])) + [d for o in L.get('offices', []) for d in o.get('doors', [])]:
            (hx, hy), w, a = d['hinge'], d['w'], math.radians(d['shut'])
            doors.append((d.get('id'), d.get('kind'), (hx, hy), (hx + w * math.cos(a), hy + w * math.sin(a))))
    except (OSError, ValueError, KeyError, IndexError) as e:
        print('[blocks] no L01 doors from plan_meta.json (%s)' % e)
    return runs, doors


L01_RUNS, L01_DOORS = _l01_sheet()


def _balcony_doors():
    """{level: [(hinge, closed end)]} - every glazed leaf the interior hangs
    onto a balcony or loggia (web/plan_meta.json, written by
    build_interior.py). The loggia kit used to guess its own door - always
    at the left end of a wide back opening, with a window at sill height
    beside it - and in 133 of 510 loggia doors the interior's leaf, placed
    from the plan, stood behind that window instead (tools/lgdoorcheck.py)."""
    out = {}
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'web', 'plan_meta.json')
    try:
        with open(path) as f:
            pm = json.load(f)
    except (OSError, ValueError) as e:
        print('[blocks] no balcony doors from plan_meta.json (%s)' % e)
        return out

    def walk(x, acc):
        if isinstance(x, dict):
            if 'hinge' in x and x.get('kind') == 'balcony':
                (hx, hy), w, a = x['hinge'], x['w'], math.radians(x['shut'])
                acc.append(((hx, hy), (hx + w * math.cos(a), hy + w * math.sin(a))))
            for v in x.values():
                walk(v, acc)
        elif isinstance(x, list):
            for v in x:
                walk(v, acc)
    for l in pm.get('levels', []):
        acc = []
        walk(l, acc)
        out[l['id']] = acc
    return out


BALC_DOORS = _balcony_doors()
WX_PIER = 0.60        # pier between the windows added on L01's glazed runs
WX_GAP = 0.42         # ...and next to the copied facade's own windows
DEBUG_WX = False
# The block mass (<B>_mass) is no longer built (build 3): it stood INSIDE
# every flat - a room's strip along the facade is outside it, and from there
# its faces read as a black wall across the room (bl/mass_check: 2-3 k ray
# hits per level, every unit). From the street it hid nothing: all glass is
# opaque on the page and every opening is glazed; the street views diff at
# the noise floor without it. LP_MASS=1 builds it again.
BUILD_MASS = os.environ.get('LP_MASS', '0') == '1'
WX_START = 901        # their numbers: <B>_L01_wn901.. so no other name moves


# ------------------------------------------------------------------ one storey of facade from the plan
class Recess:
    # cheek_lo/hi: depth of the cheek at the s0/s1 end (None: full depth, 0:
    # no cheek - the balcony runs on past it); trim_lo/hi: the back wall
    # stops that far in from the s0/s1 end (it would stand inside the other
    # arm of a wrap-round loggia); rail/band False: a niche that opens onto
    # another loggia, not onto the air (no railing, no dark head band)
    __slots__ = ('axis', 'face', 'n', 's0', 's1', 'd', 'kind', 'louvre', 'poly',
                 'cheek_lo', 'cheek_hi', 'trim_lo', 'trim_hi', 'rail', 'band',
                 'pier_lo', 'pier_hi', 'inside')

    def __init__(self, **k):
        for a in self.__slots__:
            setattr(self, a, k.get(a))
        if self.rail is None:
            self.rail = True
        if self.band is None:
            self.band = True

    def rect(self):
        """plan-frame (x0, y0, x1, y1)"""
        if self.axis == 'x':                    # mouth runs along x, face at y
            y0, y1 = sorted((self.face, self.face - self.n[1] * self.d))
            return (self.s0, y0, self.s1, y1)
        x0, x1 = sorted((self.face, self.face - self.n[0] * self.d))
        return (x0, self.s0, x1, self.s1)


def find_recesses(lev, O):
    """Loggia mouths: the sides of every balcony/loggia polygon of this level
    that open to the outside, with the face line they sit in and the depth
    back to the outline. Coordinates in the plan frame."""
    rects = []
    for f in PLAN['flats']:
        if f['level'] != lev:
            continue
        for b in f['balconies']:
            rects.append((b['polygon']['outline'], 'res'))
    for c in LEVELS[lev].get('common_loggias', []):
        rects.append((c['polygon']['outline'], 'common'))
    O_edges = []
    for i in range(len(O)):
        a, b = O[i], O[(i + 1) % len(O)]
        O_edges.append((a, b))
    area_sign = 1 if _area(O) > 0 else -1

    def outward(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1.0
        return (area_sign * dy / L, -area_sign * dx / L)

    # the plan's facade runs on every outline line: where a balcony lies
    # INSIDE the traced outline (the outline was drawn along the parapet line
    # past it - the NE corner loggia of flats 6/27/.., the north half of the
    # bar's east notch loggia), the only record that its front is open is
    # the facade run, 'open' with the outside behind it
    FAC = LEVELS[lev].get('facade', [])

    def facade_span(axis, c, n, a0, a1):
        """(s0, s1) of the open front of a balcony side lying on an outline
        line, AC pockets left out; None if there is none"""
        runs = []
        for r in FAC:
            (ax_, ay_), (bx_, by_) = r['a'], r['b']
            if axis == 'x':
                if abs(ay_ - by_) > 1e-3 or abs(ay_ - c) > 0.15:
                    continue
                u, v = sorted((ax_, bx_))
            else:
                if abs(ax_ - bx_) > 1e-3 or abs(ax_ - c) > 0.15:
                    continue
                u, v = sorted((ay_, by_))
            if v <= a0 + 0.02 or u >= a1 - 0.02:
                continue
            runs.append((max(u, a0), min(v, a1), r['state'], r['behind']))
        walls = [(u, v) for (u, v, st, _b) in runs if st == 'wall']
        opens = sorted((u, v) for (u, v, st, bh) in runs if st == 'open' and bh == 'outside')
        keep = []
        for (u, v) in opens:
            # an AC pocket: a short open run at the balcony's end, behind
            # the 0.1 m screen the plan draws between it and the loggia
            at_lo = u - a0 < 0.25 and any(abs(wu - v) < 0.03 and wv - wu < 0.16 for (wu, wv) in walls)
            at_hi = a1 - v < 0.25 and any(abs(wv - u) < 0.03 and wv - wu < 0.16 for (wu, wv) in walls)
            if 0.5 <= v - u <= 0.95 and (at_lo or at_hi):
                continue
            keep.append((u, v))
        if not keep:
            return None
        return (keep[0][0], keep[-1][1])

    out = []
    seen = set()
    for poly, kind in rects:
        # the balcony's own edges (an L-shaped balcony's bounding box put the
        # probe line in the air in front of the wing face, and the inner
        # corner loggia opened 0.8 m into the plan's wall on five storeys)
        pp = clean_poly(poly)
        ps = 1 if _area(pp) > 0 else -1
        sides = []
        for i in range(len(pp)):
            p0, p1 = pp[i], pp[(i + 1) % len(pp)]
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            L_ = math.hypot(dx, dy)
            if L_ < 0.6:
                continue
            nn_ = (ps * dy / L_, -ps * dx / L_)
            if abs(dy) < 1e-3:
                sides.append(('x', p0[1], (0, round(nn_[1])), min(p0[0], p1[0]), max(p0[0], p1[0])))
            elif abs(dx) < 1e-3:
                sides.append(('y', p0[0], (round(nn_[0]), 0), min(p0[1], p1[1]), max(p0[1], p1[1])))
        for axis, c, n, a0, a1 in sides:
            span = facade_span(axis, c, n, a0, a1)
            ivs, cur = [], None
            s = a0 + 0.04
            while s <= a1 - 0.04:
                if axis == 'x':
                    pin = (s, c - n[1] * 0.06); pout = (s, c + n[1] * 0.40)
                else:
                    pin = (c - n[0] * 0.06, s); pout = (c + n[0] * 0.40, s)
                # ...and a mouth opens to the AIR, not onto the next balcony:
                # where one loggia is split between two flats (74 / 74-a,
                # L05..L08) the 0.2 m divider is thinner than the probe, each
                # half found a "mouth" in the other, and the corner rule
                # below then shut both real mouths to nothing - four storeys
                # of blank black wall in a column of white loggias
                air = (not in_poly(pout, O)) and \
                    not any(q is not poly and in_poly(pout, q) for q, _k in rects)
                ok = air and in_poly(pin, poly) and (
                    not in_poly(pin, O) or
                    (span is not None and span[0] - 0.02 <= s <= span[1] + 0.02))
                if ok and cur is None:
                    cur = [s, s]
                elif ok:
                    cur[1] = s
                elif cur is not None:
                    ivs.append(cur); cur = None
                s += 0.04
            if cur is not None:
                ivs.append(cur)
            for s0, s1 in ivs:
                if s1 - s0 < 0.6:
                    continue
                s0 -= 0.04; s1 += 0.04
                sm_ = 0.5 * (s0 + s1)
                pin_m = (sm_, c - n[1] * 0.06) if axis == 'x' else (c - n[0] * 0.06, sm_)
                inside = in_poly(pin_m, O)
                if inside and span is not None:
                    s0, s1 = max(s0, span[0]), min(s1, span[1])
                # face line: the outermost outline edge parallel to this side,
                # facing the same way, within 0.4 m and alongside the mouth
                face = c
                best = None
                for (p, q) in O_edges:
                    on = outward(p, q)
                    if abs(on[0] - n[0]) > 0.5 or abs(on[1] - n[1]) > 0.5:
                        continue
                    if axis == 'x':
                        if abs(p[1] - q[1]) > 1e-3:
                            continue
                        lo, hi = sorted((p[0], q[0])); coord = p[1]
                        rel = (coord - c) * n[1]
                    else:
                        if abs(p[0] - q[0]) > 1e-3:
                            continue
                        lo, hi = sorted((p[1], q[1])); coord = p[0]
                        rel = (coord - c) * n[0]
                    if -0.40 <= rel <= 0.40 and hi > s0 - 0.6 and lo < s1 + 0.6:
                        if best is None or rel > best[0]:
                            best = (rel, coord)
                if best is not None:
                    face = best[1]
                # snap the mouth ends onto outline vertices (the notch cheeks)
                for (p, q) in O_edges:
                    for v in (p, q):
                        sv = v[0] if axis == 'x' else v[1]
                        cv = v[1] if axis == 'x' else v[0]
                        if abs(cv - face) > 0.45:
                            continue
                        if abs(sv - s0) < 0.12:
                            s0 = sv
                        if abs(sv - s1) < 0.12:
                            s1 = sv
                # depth: from the face inward to the outline - and no further
                # than the balcony itself reaches. Probed on three lines across
                # the mouth and the shallowest kept: a wrap-round balcony (the
                # wing's corner flat on L02/L06/L10) is an L, and down its
                # centre line the probe ran on along the other arm to the 3 m
                # cap - a corner pier 0.5 m too wide and a loggia too deep.
                # A balcony inside the outline: as deep as the balcony.
                def probe(sm):
                    d = 0.3
                    entered = False
                    while d < 3.0:
                        pt = (sm, face - n[1] * d) if axis == 'x' else (face - n[0] * d, sm)
                        if not inside and in_poly(pt, O):
                            break
                        if in_poly(pt, poly):
                            entered = True
                        elif entered:
                            break
                        d += 0.02
                    return d
                d = min(probe(s0 + (s1 - s0) * f) for f in (0.3, 0.5, 0.7))
                d = round(d - 0.01, 2)
                key = (axis, round(face, 1), round(s0, 1), round(s1, 1))
                if key in seen or d < 0.6 or s1 - s0 < 0.6:
                    continue
                seen.add(key)
                # AC pocket: the balcony runs on past the mouth by a pocket's width
                lv = ''
                if 0.4 <= s0 - a0 <= 1.3:
                    lv = 'lo'
                elif 0.4 <= a1 - s1 <= 1.3:
                    lv = 'hi'
                out.append(Recess(axis=axis, face=face, n=n, s0=s0, s1=s1, d=d,
                                  kind=kind, louvre=lv, poly=poly, inside=inside))
                if inside:
                    print('[blocks] %s: loggia inside the outline, %s=%.2f %.2f..%.2f d %.2f%s' %
                          (lev, 'y' if axis == 'x' else 'x', face, s0, s1, d, (' louvre ' + lv) if lv else ''))
    # two mouths of one wrap-round balcony meet at a corner: the corner
    # becomes a pier (the wing's black frame) and both mouths stop at it.
    # The pier is the plan's corner frame - 1.0 x 1.0 m from the outer
    # corner (the U drawn at x 61.85..62.85, y 35.55..36.55 on every sheet;
    # 006 shows it the width of the pilasters on every storey) - not the
    # overlap of the two loggias, which grew with the loggia's depth: 1.5 m,
    # and 2.5 m on L02/L06/L10 where the corner flat's balcony is deeper.
    piers = []
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            a, b = out[i], out[j]
            if a.axis == b.axis:
                continue
            ra, rb = a.rect(), b.rect()
            ix0, iy0 = max(ra[0], rb[0]), max(ra[1], rb[1])
            ix1, iy1 = min(ra[2], rb[2]), min(ra[3], rb[3])
            if ix1 - ix0 > 0.3 and iy1 - iy0 > 0.3:
                ax_, ay_ = (a, b) if a.axis == 'y' else (b, a)     # x-face recess, y-face recess
                cx_, cy_ = ax_.face, ay_.face                      # the outer corner
                px = sorted((cx_, cx_ - ax_.n[0] * CORNER_FRAME))
                py = sorted((cy_, cy_ - ay_.n[1] * CORNER_FRAME))
                # flush with both face lines on the outside (the mouths stop
                # a little short of the corner), no deeper than the loggias
                if ax_.n[0] < 0:
                    ix0, ix1 = px[0], min(ix1, px[1])
                else:
                    ix0, ix1 = max(ix0, px[0]), px[1]
                if ay_.n[1] < 0:
                    iy0, iy1 = py[0], min(iy1, py[1])
                else:
                    iy0, iy1 = max(iy0, py[0]), py[1]
                for r, o in ((a, b), (b, a)):
                    lo, hi = (ix0, ix1) if r.axis == 'x' else (iy0, iy1)
                    ro = o.rect()
                    olo, ohi = (ro[0], ro[2]) if r.axis == 'x' else (ro[1], ro[3])
                    deep = (iy1 - iy0) if r.axis == 'x' else (ix1 - ix0)
                    if abs(r.s0 - lo) < 0.2 or r.s0 > lo:
                        r.s0 = hi
                        r.cheek_lo = deep if deep < r.d - 0.05 else None
                        # the back wall gives way to the other arm
                        r.trim_lo = max(0.0, ohi - hi) if r.cheek_lo else None
                        r.pier_lo = True
                        if r.louvre == 'lo':
                            r.louvre = ''
                    else:
                        r.s1 = lo
                        r.cheek_hi = deep if deep < r.d - 0.05 else None
                        r.trim_hi = max(0.0, lo - olo) if r.cheek_hi else None
                        r.pier_hi = True
                        if r.louvre == 'hi':
                            r.louvre = ''
                piers.append((ix0, iy0, ix1, iy1, a, b))
    # a balcony that runs on past a mouth's end behind the face line, into a
    # notch of its own (the inner corner: flat 32's / 74-a's balcony reaches
    # back 1.5 m into the bar's notch, where its door from the flat is): the
    # mouth's cheek there is left out and the notch is a loggia of its own,
    # opening onto the first - before, the cheek shut it off as a sealed
    # shaft and the balcony door faced a void
    niches = []
    for r in out:
        for end, sg in ((r.s0, -1), (r.s1, 1)):
            if (r.pier_lo if sg < 0 else r.pier_hi):
                continue
            ni_ = 1 if r.axis == 'x' else 0
            sp = end + sg * 0.12
            dm = r.face - r.n[ni_] * (r.d * 0.5)
            pt = (sp, dm) if r.axis == 'x' else (dm, sp)
            if not in_poly(pt, r.poly) or in_poly(pt, O):
                continue
            # across: the notch's width on the line just past the end
            def free(t):
                q = (sp, t) if r.axis == 'x' else (t, sp)
                return not in_poly(q, O)
            t0 = t1 = dm
            while free(t0 - 0.02) and abs(t0 - dm) < 4.0:
                t0 -= 0.02
            while free(t1 + 0.02) and abs(t1 - dm) < 4.0:
                t1 += 0.02
            # deep: from the end line on until the outline
            tm = 0.5 * (t0 + t1)
            dd = 0.1
            while dd < 3.0:
                q = (end + sg * dd, tm) if r.axis == 'x' else (tm, end + sg * dd)
                if in_poly(q, O):
                    break
                dd += 0.02
            dd = round(dd - 0.01, 2)
            if t1 - t0 < 0.6 or dd < 0.6:
                continue
            for (p, q) in O_edges:
                for v in (p, q):
                    tv = v[1] if r.axis == 'x' else v[0]
                    if abs(tv - t0) < 0.06: t0 = tv
                    if abs(tv - t1) < 0.06: t1 = tv
            nax = 'y' if r.axis == 'x' else 'x'
            nn_ = (-sg, 0) if nax == 'y' else (0, -sg)
            nr = Recess(axis=nax, face=end, n=nn_, s0=t0, s1=t1, d=dd, kind=r.kind,
                        louvre='', poly=r.poly, rail=False, band=False)
            if sg < 0:
                r.cheek_lo = 0.0
            else:
                r.cheek_hi = 0.0
            niches.append(nr)
            print('[blocks] %s: niche past the mouth end %s=%.2f, %.2f..%.2f d %.2f' %
                  (lev, 'y' if nax == 'x' else 'x', end, t0, t1, dd))
    out += niches
    return out, piers


def _segments_minus(a, b, axis, recs):
    """the parts of outline edge a->b not lying inside any recess rect"""
    if axis == 'x':
        lo, hi, c = min(a[0], b[0]), max(a[0], b[0]), a[1]
    else:
        lo, hi, c = min(a[1], b[1]), max(a[1], b[1]), a[0]
    cuts = []
    for r in recs:
        x0, y0, x1, y1 = r.rect()
        e = 0.03
        if axis == 'x':
            if y0 - e <= c <= y1 + e:
                cuts.append((x0 - e, x1 + e))
        else:
            if x0 - e <= c <= x1 + e:
                cuts.append((y0 - e, y1 + e))
    ivs = [(lo, hi)]
    for (u, v) in cuts:
        nxt = []
        for (p, q) in ivs:
            if v <= p or u >= q:
                nxt.append((p, q)); continue
            if u > p:
                nxt.append((p, u))
            if v < q:
                nxt.append((v, q))
        ivs = nxt
    return [(p, q) for (p, q) in ivs if q - p > 0.02], lo, hi, c


def wall_cells(mb, P0, t, m, s_a, s_b, d0, d1, z0, z1, holes):
    """Boxes for one depth layer of a wall strip: s along t from P0, d along
    the inward direction m, holes (s0, s1, za, zb) cut out. Adjacent columns
    with the same z runs are merged."""
    if s_b - s_a < 1e-3:
        return
    br = {s_a, s_b}
    for (h0, h1, za, zb) in holes:
        for v in (h0, h1):
            if s_a < v < s_b:
                br.add(v)
    br = sorted(br)
    cols = []
    for i in range(len(br) - 1):
        u, v = br[i], br[i + 1]
        mid = 0.5 * (u + v)
        zh = sorted((za, zb) for (h0, h1, za, zb) in holes if h0 <= mid <= h1)
        runs, zc = [], z0
        for (za, zb) in zh:
            if za > zc + 1e-4:
                runs.append((zc, min(za, z1)))
            zc = max(zc, zb)
        if zc < z1 - 1e-4:
            runs.append((zc, z1))
        if cols and cols[-1][2] == runs and abs(cols[-1][1] - u) < 1e-6:
            cols[-1][1] = v
        else:
            cols.append([u, v, runs])
    for (u, v, runs) in cols:
        for (za, zb) in runs:
            p = (P0[0] + t[0] * u + m[0] * d0, P0[1] + t[1] * u + m[1] * d0)
            q = (P0[0] + t[0] * v + m[0] * d1, P0[1] + t[1] * v + m[1] * d1)
            mb.box((p[0], p[1], za), (q[0], q[1], zb))


def build_storey(lev_id, z, data_lev, colls, meta):
    """One storey of both blocks' envelope, from the plan's outline, openings
    and balconies of `data_lev`, at height z."""
    L = LEVELS[data_lev]
    Op = clean_poly(L['outline']['outline'])            # plan frame
    recs, piers = find_recesses(data_lev, Op)
    sign = 1 if _area(Op) > 0 else -1
    n_pts = len(Op)
    H = FLOOR_H
    walls = {('A', 'dark'): MB(), ('B', 'dark'): MB(), ('A', 'light'): MB(),
             ('B', 'light'): MB()}
    first = (lev_id == 'L01')
    floors = {'A': MB(), 'B': MB()}
    lin01 = {'A': MB(), 'B': MB()}
    O1 = clean_poly(LEVELS['L01']['outline']['outline']) if first else None

    # windows from the plan, grouped by the outline line they sit in
    opens = []
    for o in L['openings']:
        opens.append(o)

    # every outline edge, minus what the recess modules build
    edges = []
    for i in range(n_pts):
        a, b = Op[i], Op[(i + 1) % n_pts]
        axis = 'x' if abs(a[1] - b[1]) < 1e-3 else 'y'
        dx, dy = b[0] - a[0], b[1] - a[1]
        Ln = math.hypot(dx, dy)
        n = (sign * dy / Ln, -sign * dx / Ln)          # outward, plan frame
        subs, lo, hi, c = _segments_minus(a, b, axis, recs)
        edges.append((a, b, axis, n, subs, lo, hi, c))

    def turn_convex(i):
        """is outline vertex i (start of edge i) a convex corner?"""
        a = Op[i - 1]; b = Op[i]; c = Op[(i + 1) % n_pts]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        return cross * sign > 0

    def mouth_end(axis, c, s):
        for r in recs:
            if r.axis == axis and abs(r.face - c) < 0.05 and (abs(r.s0 - s) < 0.08 or abs(r.s1 - s) < 0.08):
                return True
        return False

    for i, (a, b, axis, n, subs, lo, hi, c) in enumerate(edges):
        # vertex ends of this edge: start = Op[i], end = Op[i+1]
        for (p, q) in subs:
            # split at the joint across the bar
            pieces = [(p, q)]
            if axis == 'x' and p < JOINT_X < q:
                pieces = [(p, JOINT_X - JOINT_GAP), (JOINT_X + JOINT_GAP, q)]
            for (u, v) in pieces:
                end_kind = {}
                for s in (u, v):
                    at_lo = abs(s - lo) < 1e-3; at_hi = abs(s - hi) < 1e-3
                    if abs(s - (JOINT_X - JOINT_GAP)) < 1e-3 or abs(s - (JOINT_X + JOINT_GAP)) < 1e-3:
                        end_kind[s] = 'joint'
                        continue
                    if at_lo or at_hi:
                        # which polygon vertex is it, and does the neighbour edge survive there?
                        vtx = a if abs(((a[0] if axis == 'x' else a[1]) - s)) < 1e-3 else b
                        vi = i if vtx is a else (i + 1) % n_pts
                        nb = edges[i - 1] if vtx is a else edges[(i + 1) % n_pts]
                        nb_c = vtx[0] if nb[2] == 'x' else vtx[1]
                        alive = any(abs(pp - nb_c) < 1e-3 or abs(qq - nb_c) < 1e-3 for (pp, qq) in nb[4])
                        if alive:
                            end_kind[s] = 'convex' if turn_convex(vi) else 'concave'
                            continue
                    end_kind[s] = 'jamb' if mouth_end(axis, c, s) else 'plain'
                blk = block_of(0.5 * (u + v) if axis == 'x' else c)
                gable = (axis == 'y' and n[0] < -0.5 and c < 0.5)
                mb = walls[(blk, 'light' if gable else 'dark')]
                # Blender-frame strip: P0 at s=u, t along +s, m inward
                if axis == 'x':
                    P0 = B((u, c)); t = (1.0, 0.0)
                else:
                    P0 = B((c, u)); t = (0.0, -1.0)
                nB = (n[0], -n[1])
                mI = (-nB[0], -nB[1])
                Ls = v - u
                # holes: windows on this line
                holes = []
                wins = []
                for o in opens:
                    oa, ob = o['a'], o['b']
                    if o.get('axis') != axis:
                        continue
                    oc = oa[1] if axis == 'x' else oa[0]
                    if abs(oc - c) > 0.25:
                        continue
                    s0 = min(oa[0], ob[0]) if axis == 'x' else min(oa[1], ob[1])
                    s1 = max(oa[0], ob[0]) if axis == 'x' else max(oa[1], ob[1])
                    if s0 < u + 0.05 or s1 > v - 0.05:
                        continue
                    w = s1 - s0
                    if gable:
                        hh, sill = SLOT_H, SLOT_SILL
                    else:
                        hh, sill = WIN_H, WIN_SILL
                    if w < 0.5:
                        continue
                    holes.append((s0 - u, s1 - u, z + sill, z + sill + hh))
                    wins.append((s0, s1, sill, hh, w, False))
                # L01: where the sheet's glazed run meets this plain wall,
                # standard windows, as many as fit between WX_PIER piers
                extra = []
                if first and not gable and DEBUG_WX:
                    print('[wx]', axis, round(c, 2), round(u, 2), round(v, 2), [(round(h0 + u, 2), round(h1 + u, 2)) for (h0, h1, _, _) in holes])
                if first and not gable:
                    for (rax, rc, ra, rb) in L01_RUNS:
                        if rax != axis or abs(rc - c) > 0.25:
                            continue
                        lo_, hi_ = max(u + WX_PIER, ra), min(v - WX_PIER, rb)
                        if hi_ - lo_ < WIN_W:
                            continue
                        # the free stretches between this wall's own windows
                        cuts = sorted((h0 + u - WX_GAP, h1 + u + WX_GAP) for (h0, h1, _, _) in holes)
                        free, x0_ = [], lo_
                        for (ca, cb) in cuts:
                            if cb <= x0_ or ca >= hi_:
                                continue
                            if ca > x0_:
                                free.append((x0_, ca))
                            x0_ = max(x0_, cb)
                        if hi_ > x0_:
                            free.append((x0_, hi_))
                        for (fa, fb) in free:
                            k = int((fb - fa + WX_PIER + 1e-6) // (WIN_W + WX_PIER))
                            if k < 1:
                                continue
                            tot = k * WIN_W + (k - 1) * WX_PIER
                            sx = fa + (fb - fa - tot) / 2
                            for j in range(k):
                                s0 = sx + j * (WIN_W + WX_PIER)
                                extra.append((s0, s0 + WIN_W))
                for (s0, s1) in extra:
                    holes.append((s0 - u, s1 - u, z + WIN_SILL, z + WIN_SILL + WIN_H))
                    wins.append((s0, s1, WIN_SILL, WIN_H, WIN_W, True))
                # trims at the ends
                trims = []
                for s, side in ((u, 0), (v, 1)):
                    k = end_kind[s]
                    if k == 'convex' and axis == 'y':
                        trims.append((WALL_T, WALL_T, WALL_T))
                    elif k == 'jamb':
                        trims.append((0.0, LOG_RET, LOG_RET))
                    else:
                        trims.append((0.0, 0.0, 0.0))
                layers = [(0.0, LOG_CY), (LOG_CY, LOG_SY), (LOG_SY, WALL_T)]
                for li, (d0, d1) in enumerate(layers):
                    sa = trims[0][li]; sb = Ls - trims[1][li]
                    wall_cells(mb, P0, t, mI, sa, sb, d0, d1, z, z + H, holes)
                # L01: the sheet draws a glazed run here, so the interior builds
                # no wall and no lining (CONTRACT "Who builds which wall") - and
                # the offices looked at the back of this black wall. Line its
                # room side along those runs, window holes and all.
                if first:
                    sa = trims[0][2]; sb = Ls - trims[1][2]
                    for (rax, rc, ra, rb) in L01_RUNS:
                        if rax != axis or abs(rc - c) > 0.25:
                            continue
                        la, lb = max(sa, ra - u), min(sb, rb - u)
                        if lb - la > 0.05:
                            wall_cells(lin01[blk], P0, t, mI, la, lb, WALL_T, WALL_T + LIN_L01_T,
                                       z, z + H, holes)
                # the window modules
                for (s0, s1, sill, hh, w, added) in wins:
                    parts = window_module(w, hh, slot=gable)
                    # module origin: the end of the hole from which t' = (cos th, sin th) runs
                    th = _theta(nB)
                    tt = (math.cos(th), math.sin(th))
                    pa = B((s0, c)) if axis == 'x' else B((c, s0))
                    pb = B((s1, c)) if axis == 'x' else B((c, s1))
                    org = pa if (pb[0] - pa[0]) * tt[0] + (pb[1] - pa[1]) * tt[1] > 0 else pb
                    if added:
                        meta['wnx'] += 1
                        nm = '%s_%s_wn%03d' % (blk, lev_id, WX_START - 1 + meta['wnx'])
                    else:
                        meta['wn'] += 1
                        nm = '%s_%s_%s%03d' % (blk, lev_id, 'sl' if gable else 'wn', meta['wn'])
                    # (an added window draws its light from its own sequence, so
                    # the lit windows of every other storey stay where they were)
                    place(parts, nm, org, nB, z + sill, colls[blk], lit_p=0.0 if gable else 0.10,
                          rng=RLX if added else None)

    # loggia modules, their head bands and (on the lowest storey) their floors
    for r in recs:
        op = r.s1 - r.s0
        if op < 0.6:
            continue
        mid = 0.5 * (r.s0 + r.s1)
        blk = block_of(mid if r.axis == 'x' else r.face)
        nB = (r.n[0], -r.n[1])
        th = _theta(nB)
        tt = (math.cos(th), math.sin(th))
        pa = B((r.s0, r.face)) if r.axis == 'x' else B((r.face, r.s0))
        pb = B((r.s1, r.face)) if r.axis == 'x' else B((r.face, r.s1))
        forward = (pb[0] - pa[0]) * tt[0] + (pb[1] - pa[1]) * tt[1] > 0
        org = pa if forward else pb
        lv = ''
        if r.louvre:
            lv = 'l' if ((r.louvre == 'lo') == forward) else 'r'
        oneway, gap = False, None
        if first:
            # is this loggia's volume inside the L01 floor plate (an office
            # or the corridor), i.e. does the sheet draw no loggia here?
            mid = 0.5 * (r.s0 + r.s1)
            inner = (mid, r.face - r.n[1] * (r.d * 0.5)) if r.axis == 'x' else \
                (r.face - r.n[0] * (r.d * 0.5), mid)
            oneway = in_poly(inner, O1)
            if oneway:
                for (did, kind_, p, q) in L01_DOORS:
                    if kind_ != 'common':
                        continue                            # a balcony door hangs its own glazed leaf
                    ia = 1 if r.axis == 'x' else 0          # the face-normal coordinate
                    if abs(p[ia] - q[ia]) > 0.05:
                        continue                            # not parallel to the mouth
                    dep = abs(r.face - p[ia])
                    if dep > r.d - 0.10:
                        continue                            # not in front of the back wall
                    sa, sb = sorted((p[1 - ia], q[1 - ia]))
                    sa, sb = max(sa, r.s0 + 0.2), min(sb, r.s1 - 0.2)
                    if sb - sa < 0.6:
                        continue
                    la, lb = ((sa - r.s0, sb - r.s0) if forward else (r.s1 - sb, r.s1 - sa))
                    gap = (la, lb)
                    meta['l01_gaps'].append((lev_id, blk, did, round(sa, 2), round(sb, 2)))
                meta['l01_oneway'] += 1
        # the plan's own openings in this loggia, in the module's frame
        back, sides = [], []
        ni = 1 if r.axis == 'x' else 0
        nn = r.n[ni]
        lx = (lambda v: v - r.s0) if forward else (lambda v: r.s1 - v)
        for o in opens:
            oa, ob = o['a'], o['b']
            if o.get('axis') == r.axis:
                dep = -(oa[ni] - r.face) * nn
                q0, q1 = sorted((oa[1 - ni], ob[1 - ni]))
                if r.d - 0.4 <= dep <= r.d + 0.4 and q0 >= r.s0 - 0.1 and q1 <= r.s1 + 0.1:
                    back.append(tuple(sorted((lx(q0), lx(q1)))))
            elif not oneway:
                # a cheek opening is a door only where a room is behind it:
                # the plan's grey screen in front of an AC pocket (serves
                # nobody, balcony or street on both sides) was built as a
                # glazed door, and the louvre that cheek should carry dropped
                sv = str(o.get('serves') or '')
                if not (sv.startswith('unit') or sv == 'corridor'):
                    continue
                oc = oa[1 - ni]
                d0_, d1_ = sorted((-(oa[ni] - r.face) * nn, -(ob[ni] - r.face) * nn))
                if d0_ > -0.2 and d1_ < r.d + 0.3:
                    if abs(oc - r.s0) < 0.45:
                        sides.append(('l' if forward else 'r', d0_, d1_))
                    elif abs(oc - r.s1) < 0.45:
                        sides.append(('r' if forward else 'l', d0_, d1_))
        # the interior's glazed leaves in this loggia's back wall
        # (and in its cheeks: a leaf across a cheek is a door the plan's
        # opening list may not have - 11 of them, one a storey at x 78.85)
        bdoors = []
        for (h, c) in BALC_DOORS.get(lev_id, ()):
            if abs(h[ni] - c[ni]) <= 0.05:                  # parallel to the mouth
                dep = -(h[ni] - r.face) * nn
                q0, q1 = sorted((h[1 - ni], c[1 - ni]))
                if r.d - 0.4 <= dep <= r.d + 0.4 and q0 >= r.s0 - 0.15 and q1 <= r.s1 + 0.15:
                    bdoors.append(tuple(sorted((lx(q0), lx(q1)))))
            elif abs(h[1 - ni] - c[1 - ni]) <= 0.05 and not oneway:
                oc = h[1 - ni]
                d0_, d1_ = sorted((-(h[ni] - r.face) * nn, -(c[ni] - r.face) * nn))
                if not (d0_ > -0.2 and d1_ < r.d + 0.3):
                    continue
                sd = None
                if abs(oc - r.s0) < 0.45:
                    sd = 'l' if forward else 'r'
                elif abs(oc - r.s1) < 0.45:
                    sd = 'r' if forward else 'l'
                if sd and not any(q == sd and a < d1_ and b > d0_ for (q, a, b) in sides):
                    sides.append((sd, d0_, d1_))
        # the ends: s0 is the module's left side when it runs forward
        ends_lo, ends_hi = (r.cheek_lo, r.trim_lo), (r.cheek_hi, r.trim_hi)
        el, er = (ends_lo, ends_hi) if forward else (ends_hi, ends_lo)
        parts = loggia_module(op, r.d, r.kind, lv, oneway=oneway, gap=gap,
                              back=back or None, sides=sides,
                              cheeks=(el[0], er[0]), trims=(el[1], er[1]), rail=r.rail,
                              bdoors=bdoors)
        meta['lg'] += 1
        nm = '%s_%s_lg%03d' % (blk, lev_id, meta['lg'])
        place(parts, nm, org, nB, z, colls[blk], lit_p=0.08)
        LG_PLACED.append((lev_id, nm, org, tt, nB, z, parts['shell'].name))
        # head bands in front of the soffit: the dark face carried across
        mb = walls[(blk, 'dark')]
        mI = (-nB[0], -nB[1])
        for (d0, d1, e) in (((0.0, LOG_CY, 0.0), (LOG_CY, LOG_SY, LOG_RET)) if r.band else ()):
            p = (org[0] - tt[0] * e + mI[0] * d0, org[1] - tt[1] * e + mI[1] * d0)
            q = (org[0] + tt[0] * (op + e) + mI[0] * d1, org[1] + tt[1] * (op + e) + mI[1] * d1)
            mb.box((p[0], p[1], z + LOG_H), (q[0], q[1], z + H))
            if first:
                mb.box((p[0], p[1], z - 0.35), (q[0], q[1], z))
        if first:
            # the bottom row's floor: a pale slab where the storey below would
            # have put its soffit (the north face cantilevers 1.5 m over the plinth)
            e = LOG_RET
            p = (org[0] - tt[0] * e + mI[0] * LOG_SY, org[1] - tt[1] * e + mI[1] * LOG_SY)
            q = (org[0] + tt[0] * (op + e) + mI[0] * (r.d + 0.22),
                 org[1] + tt[1] * (op + e) + mI[1] * (r.d + 0.22))
            # Who owns the floor in a loggia bay (CONTRACT "Heights"): the
            # interior's finish (tiles at z+0.02, an office's parquet at z in
            # a one-way bay) is the floor; this is the slab under it, for the
            # street to see before the interior is in. Under a one-way bay
            # its top was 6 mm under the office floor - inside Draco's 5 mm
            # position step, so in places one floor over the other. 3 cm now.
            floors[blk].box((p[0], p[1], z - 0.35), (q[0], q[1], z - (0.03 if oneway else 0.0)))
        meta['recess'].append((lev_id, blk, r))
    for (x0, y0, x1, y1, ra, rb) in piers:
        # inset by a cheek on the sides the two loggias open from
        blk = block_of(0.5 * (x0 + x1))
        bx0, by0, bx1, by1 = x0, y0, x1, y1
        for r in (ra, rb):
            rr = r.rect()
            if r.axis == 'x':
                if rr[0] >= x1 - 1e-3: bx1 -= LOG_RET
                if rr[2] <= x0 + 1e-3: bx0 += LOG_RET
            else:
                if rr[1] >= y1 - 1e-3: by1 -= LOG_RET
                if rr[3] <= y0 + 1e-3: by0 += LOG_RET
        walls[(blk, 'dark')].box((bx0, -by0, z - (0.35 if first else 0.0)), (bx1, -by1, z + H))

    # the joint: a recessed dark filler behind the 0.1 m shadow gap
    for (yface, inward) in ((-1.75, 1), (18.25, -1)):
        y0 = yface + inward * 0.22; y1 = yface + inward * 0.55
        walls[('B', 'dark')].box((JOINT_X - JOINT_GAP - 0.01, -y0, z),
                                 (JOINT_X + JOINT_GAP + 0.01, -y1, z + H))

    out = []
    for (blk, kind), mb in walls.items():
        if mb.f:
            nm = '%s_%s_%s' % (blk, 'gable' if kind == 'light' else 'wall', lev_id)
            out.append(mb.to_object(nm, M('plaster_light' if kind == 'light' else 'plaster_dark'),
                                    colls[blk + 'w']))
    for blk, mb in floors.items():
        if mb.f:
            out.append(mb.to_object('%s_lgfloor_%s' % (blk, lev_id), M('concrete_loggia'),
                                    colls[blk + 'w']))
    for blk, mb in lin01.items():
        if mb.f:
            out.append(mb.to_object('%s_lining_%s' % (blk, lev_id), M('int_wall'),
                                    colls[blk + 'w']))
    return out, Op, recs


# ------------------------------------------------------------------ the two blocks
def build_blocks():
    """Both blocks' envelopes from the plan: nine residential storeys and the
    office storey, the first-floor slab, the mass behind the walls, the roof,
    the parapet and the three stair heads. Returns the collections and a
    summary for scene_meta."""
    colls = {'A': collection('A_openings'), 'B': collection('B_openings'),
             'Aw': collection('blockA'), 'Bw': collection('blockB')}
    meta = {'wn': 0, 'lg': 0, 'recess': [], 'wnx': 0, 'l01_oneway': 0, 'l01_gaps': []}
    storeys = {}
    for (lev_id, z, data_lev) in FACADE_LEVELS:
        obs, Op, recs = build_storey(lev_id, z, data_lev, colls, meta)
        storeys[lev_id] = (z, Op, recs)
        if lev_id == 'L01':
            # the office storey's walls, piers and loggia floors reach 0.35
            # below +4.8; inside the podium nothing of them may hang under
            # the L00 ceilings (+4.50): cut them back to +4.55 there
            pod = clean_poly(LEVELS['L00']['outline']['outline'])
            for ob in obs:
                cut = MB()
                prism(cut, [B(p) for p in pod], GROUND_H - 0.40, CEIL_CLEAR_L00)
                cut_away(ob, cut)
        print('[blocks] %s z=%.1f  recesses %d' % (lev_id, z, len(recs)))

    # first-floor slab under the tower: the outline of the office storey's
    # facade (L02 data) as a prism under +4.8, split at the joint
    Op = storeys['L01'][1]
    # Inside the podium (the L00 outline) its underside is +4.55, 5 cm over
    # the interior's L00 ceilings (+4.50): at +4.45 it hung under the
    # entrance halls' ceilings and read as a dark ceiling there (build 4).
    # Outside the podium - the north face's cantilever - the soffit stays
    # at +4.45, as the street has always seen it.
    pod = clean_poly(LEVELS['L00']['outline']['outline'])
    for blk in ('A', 'B'):
        mb = MB()
        pts = _clip_x(Op, blk)
        if pts:
            prism(mb, [B(p) for p in pts], GROUND_H - 0.35, GROUND_H - 0.001)
        ob = mb.to_object('%s_slab_L01' % blk, M('plaster_dark'), colls[blk + 'w'])
        cut = MB()
        prism(cut, [B(p) for p in pod], GROUND_H - 0.40, CEIL_CLEAR_L00)
        # ...and none at all over the cores (halls, stairwells, lift shafts):
        # the interior carries the L01 floor there, 0.30 thick where a flight
        # shows its edge, and a car rides through (CONTRACT "Heights")
        for poly in _core_zones():
            prism(cut, [B(p) for p in poly], GROUND_H - 0.40, GROUND_H + 0.05)
        cut_away(ob, cut)

    # the mass behind the walls and the loggias, so nothing is seen through
    mass = {'A': [(0.30, 0.35, JOINT_X - 0.12, 16.45)],
            'B': [(JOINT_X + 0.12, 0.35, 79.70, 16.45), (79.70, 0.35, 81.15, 13.40),
                  (63.65, 16.40, 81.10, 34.75)]}
    # ...but never in front of a loggia's back wall. The wing's corner flat
    # (9, 93, 177 on L02/L06/L10) has a loggia a metre deeper than the floors
    # between, and a mass sized for the shallow ones stood 0.7 m proud of its
    # back wall: from the street that bay read as a black hole every fourth
    # storey. So every box gives way to the deepest recess (+ its 0.22 back
    # wall) on any storey.
    BACK = 0.22 + 0.03
    for blk, boxes in mass.items():
        for bi, (x0, y0, x1, y1) in enumerate(boxes):
            for (_lev, _blk, r) in meta['recess']:
                rx0, ry0, rx1, ry1 = r.rect()
                if r.axis == 'x':
                    if r.n[1] > 0: ry0 -= BACK
                    else: ry1 += BACK
                else:
                    if r.n[0] > 0: rx0 -= BACK
                    else: rx1 += BACK
                if rx1 <= x0 or rx0 >= x1 or ry1 <= y0 or ry0 >= y1:
                    continue
                # pull the box's face that the recess opens from back behind it
                if r.axis == 'x':
                    if r.n[1] > 0: y1 = min(y1, ry0)
                    else: y0 = max(y0, ry1)
                else:
                    if r.n[0] > 0: x1 = min(x1, rx0)
                    else: x0 = max(x0, rx1)
            if (x0, y0, x1, y1) != boxes[bi]:
                print('[blocks] %s mass box %d %s -> %s' % (
                    blk, bi, boxes[bi], tuple(round(v, 3) for v in (x0, y0, x1, y1))))
            boxes[bi] = (x0, y0, x1, y1)
    for blk, boxes in mass.items():
        if not BUILD_MASS:
            continue
        mb = MB()
        for (x0, y0, x1, y1) in boxes:
            mb.box((x0, -y0, GROUND_H - 0.36), (x1, -y1, TOP_Z - 0.01))
        mb.to_object('%s_mass' % blk, M('plaster_dark'), colls[blk + 'w'])

    # roof slab, parapet with its coping, stair heads
    R = LEVELS['ROOF']
    Rp = clean_poly(R['outline']['outline'])
    sign = 1 if _area(Rp) > 0 else -1
    heads_xy = []
    for h in R.get('stair_heads', []):
        o = h['polygon']['outline']
        heads_xy.append((min(p[0] for p in o), min(p[1] for p in o),
                         max(p[0] for p in o), max(p[1] for p in o)))
    for blk in ('A', 'B'):
        mb = MB()
        pts = _clip_x(Rp, blk)
        # Inside the top loggias' soffits (37.45 .. 37.80: flush with them the
        # slab z-fought every top-row soffit black), and its underside 15 cm
        # over the L10 interior's ceilings (+37.50): at 37.50 it was exactly
        # coplanar with them and won in jagged black patches in every L10
        # room (build 4; CONTRACT "Heights"). Cut out over the stair heads,
        # whose floors (cores.glb, 37.50 .. 37.80) are the roof there.
        prism(mb, [B(p) for p in pts], ROOF_SLAB_Z0, TOP_Z + 0.01)
        ob = mb.to_object('%s_roof' % blk, M('plaster_dark'), colls[blk + 'w'])
        cut = MB()
        for (x0, y0, x1, y1) in heads_xy:
            if block_of(0.5 * (x0 + x1)) == blk:
                cut.box((x0, -y0, ROOF_SLAB_Z0 - 0.05), (x1, -y1, TOP_Z + 0.05))
        cut_away(ob, cut)
    par = {'A': MB(), 'B': MB()}
    light = {'A': MB(), 'B': MB()}
    PT = 0.30
    for i in range(len(Rp)):
        a, b = Rp[i], Rp[(i + 1) % len(Rp)]
        axis = 'x' if abs(a[1] - b[1]) < 1e-3 else 'y'
        dx, dy = b[0] - a[0], b[1] - a[1]
        Ln = math.hypot(dx, dy)
        n = (sign * dy / Ln, -sign * dx / Ln)
        if axis == 'x':
            lo, hi = sorted((a[0], b[0]))
            pieces = [(lo, hi)]
            if lo < JOINT_X < hi:
                pieces = [(lo, JOINT_X - JOINT_GAP), (JOINT_X + JOINT_GAP, hi)]
            for (u, v) in pieces:
                blk = block_of(0.5 * (u + v))
                y0 = a[1]; y1 = a[1] - n[1] * PT
                par[blk].box((u, -y0, TOP_Z), (v, -y1, ROOF_Z - 0.08))
                par[blk].box((u - (0.04 if u == lo else 0), -(y0 + n[1] * 0.05), ROOF_Z - 0.08),
                             (v + (0.04 if v == hi else 0), -(y0 - n[1] * (PT + 0.04)), ROOF_Z))
        else:
            lo, hi = sorted((a[1], b[1]))
            c = a[0]
            blk = block_of(c)
            x1 = c - n[0] * PT
            mb = light[blk] if (n[0] < -0.5 and c < 0.5) else par[blk]
            mb.box((c, -(lo + PT), TOP_Z), (x1, -(hi - PT), ROOF_Z - 0.08))
            mb.box((c + n[0] * 0.05, -(lo + PT), ROOF_Z - 0.08),
                   (c - n[0] * (PT + 0.04), -(hi - PT), ROOF_Z))
    # joint filler in the parapet
    for (yf, inward) in ((-1.75, 1), (18.25, -1)):
        par['B'].box((JOINT_X - JOINT_GAP - 0.01, -(yf + inward * 0.22), TOP_Z),
                     (JOINT_X + JOINT_GAP + 0.01, -(yf + inward * 0.55), ROOF_Z - 0.1))
    for blk in ('A', 'B'):
        par[blk].to_object('%s_parapet' % blk, M('plaster_dark'), colls[blk + 'w'])
        if light[blk].f:
            light[blk].to_object('%s_gable_parapet' % blk, M('plaster_light'), colls[blk + 'w'])
    heads = {'A': MB(), 'B': MB()}
    for h in R.get('stair_heads', []):
        o = h['polygon']['outline']
        xs = [p[0] for p in o]; ys = [p[1] for p in o]
        blk = block_of(0.5 * (min(xs) + max(xs)))
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        # keep it 5 cm inside the facade planes it touches
        x1 = min(x1, 82.75 - 0.35); x0 = max(x0, -0.25 + 0.35)
        heads[blk].box((x0, -y0, TOP_Z), (x1, -y1, h.get('z_top', HEAD_Z)))
        heads[blk].box((x0 - 0.06, -(y0 - 0.06), h.get('z_top', HEAD_Z) - 0.08),
                       (x1 + 0.06, -(y1 + 0.06), h.get('z_top', HEAD_Z)))
    for blk in ('A', 'B'):
        heads[blk].to_object('%s_stairhead' % blk, M('plaster_dark'), colls[blk + 'w'])
    print('[blocks] windows %d  loggias %d  kit sources %d' % (meta['wn'], meta['lg'], len(_KIT)))
    print('[blocks] L01: %d one-way loggias, doorways %s, %d windows added on the sheet\'s glazed runs'
          % (meta['l01_oneway'], meta['l01_gaps'], meta['wnx']))
    return colls, storeys, meta


def _core_zones():
    """Plan polygons of the three cores at the +4.8 slab (plan_meta.json,
    written by build_interior.py): each hall's outline, and the box of its
    L00 -> L01 flights and half landing where they stand out of it."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'web', 'plan_meta.json')
    try:
        with open(path) as f:
            cores = json.load(f)['cores']
    except (OSError, ValueError, KeyError) as e:
        print('[blocks] no cores from plan_meta (%s)' % e)
        return []
    out = []
    for c in cores:
        if c['id'] not in ('C1', 'C2', 'C3') or not c.get('hall'):
            continue
        hall = clean_poly(c['hall']['outline'])
        out.append(hall)
        hx0 = min(p[0] for p in hall); hx1 = max(p[0] for p in hall)
        hy0 = min(p[1] for p in hall); hy1 = max(p[1] for p in hall)
        st = [t for t in c['storeys'] if t['from'] == 'L00']
        for t in st:
            pts = [p for fl in t['flights'] + [t['half_landing']] for p in fl['poly']['outline']]
            x0 = min(p[0] for p in pts); x1 = max(p[0] for p in pts)
            y0 = min(p[1] for p in pts); y1 = max(p[1] for p in pts)
            # never past the hall's own box: C3's L00 half landing is drawn
            # out to x 83.06, past the east face, and a cut there would
            # notch the slab's edge on the street
            x0, x1 = max(x0, hx0), min(x1, hx1); y0, y1 = max(y0, hy0), min(y1, hy1)
            if x1 - x0 > 0.05 and y1 - y0 > 0.05:
                out.append([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    return out


def cut_away(ob, cutter_mb):
    """Boolean-subtract the closed boxes/prisms in `cutter_mb` from `ob`
    (both in the same local frame, `ob` not yet parented), in place."""
    if not cutter_mb.f:
        return ob
    ct = cutter_mb.to_object('_cut_' + ob.name, None)
    md = ob.modifiers.new('cut', 'BOOLEAN')
    md.operation = 'DIFFERENCE'
    md.solver = 'EXACT'
    md.use_self = True           # the cutter's pieces overlap one another
    md.object = ct
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
    ob.modifiers.remove(md)
    old = ob.data
    ob.data = me
    me.name = old.name
    bpy.data.meshes.remove(old)
    m = ct.data
    bpy.data.objects.remove(ct)
    bpy.data.meshes.remove(m)
    return ob


def _clip_x(pts, blk):
    """an axis-aligned polygon clipped to one side of the joint (plan frame)"""
    lim = JOINT_X - JOINT_GAP if blk == 'A' else JOINT_X + JOINT_GAP
    keep = (lambda x: x <= lim) if blk == 'A' else (lambda x: x >= lim)
    out = []
    n = len(pts)
    for i in range(n):
        p, q = pts[i], pts[(i + 1) % n]
        if keep(p[0]):
            out.append(p)
        if keep(p[0]) != keep(q[0]):
            tq = (lim - p[0]) / (q[0] - p[0])
            out.append((lim, p[1] + (q[1] - p[1]) * tq))
    return clean_poly(out) if len(out) >= 3 else []


def facade_runs():
    """Every outward face of the upper floors, for scene_meta.facades: the
    roof outline's edges (the face lines of the tower), split at the joint,
    in the plan frame with their outward normal."""
    R = clean_poly(LEVELS['ROOF']['outline']['outline'])
    sign = 1 if _area(R) > 0 else -1
    out = []
    for i in range(len(R)):
        a, b = R[i], R[(i + 1) % len(R)]
        dx, dy = b[0] - a[0], b[1] - a[1]
        Ln = math.hypot(dx, dy)
        n = (round(sign * dy / Ln, 3), round(-sign * dx / Ln, 3))
        if abs(a[1] - b[1]) < 1e-3 and min(a[0], b[0]) < JOINT_X < max(a[0], b[0]):
            j0, j1 = (JOINT_X - JOINT_GAP, JOINT_X + JOINT_GAP)
            if a[0] < b[0]:
                segs = [(a, (j0, a[1])), ((j1, a[1]), b)]
            else:
                segs = [(a, (j1, a[1])), ((j0, a[1]), b)]
        else:
            segs = [(a, b)]
        for (p, q) in segs:
            out.append({'block': block_of(0.5 * (p[0] + q[0]) if abs(dy) < 1e-3 else p[0]),
                        'a': [round(p[0], 3), round(p[1], 3)],
                        'b': [round(q[0], 3), round(q[1], 3)], 'out': list(n),
                        'z0': GROUND_H, 'z1': TOP_Z})
    return out


def block_footprints():
    R = clean_poly(LEVELS['ROOF']['outline']['outline'])
    return {blk: [[round(p[0], 3), round(p[1], 3)] for p in _clip_x(R, blk)] for blk in ('A', 'B')}
