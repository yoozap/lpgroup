# -*- coding: utf-8 -*-
"""Podium, terrace, street, forecourt, background blocks and planting.

Everything is authored in the plan frame of blender/plans/plan.json and
converted on the way out: Blender local under BuildingRoot = (x, -y, z).
    plan x   along the lettered axes a..J, 0 at axis a (west gable)
    plan y   along the numbered axes 1..10, +y = the street side (south)
    z        up; 0 = the plan's +-0.000 = the pavement and forecourt
Roads sit 0.15 m below it, parking asphalt 0.12 m below.
"""
import bpy, math, random
from mathutils import Vector
from lib_build import (MB, srgb, link_dup, frame_for, frame_for_yz, collection,
                       rnd, TAU)
import lib_building as LB

M = LB.M
PLAN = LB.PLAN
LEV = LB.LEVELS
GROUND_H = LB.GROUND_H                       # 4.8: podium roof / terrace

PARK_TOP = GROUND_H                          # terrace deck
PARAPET_TOP = 5.90                           # 006: 5.9 m over the pavement
FASCIA_Z = 3.90                              # glass head (006: 3.6 m of glass, a 2.0 m band)
SHOP_SILL = 0.40
POD_T = 0.40                                 # podium wall
HALL_SKIN = 0.07     # ...in front of an entrance hall: a skin OUTSIDE the outline (the interior's wall is the wall, and stands up to 6 cm proud of it)
ROAD_Z = -0.15
LOT_Z = -0.12

# streets (plan frame): one each side, the south one the main street
ROAD_S = (53.0, 71.0)        # y band
ROAD_N = (-42.0, -26.0)
ROAD_W = (-48.0, -32.0)      # x band
ROAD_E = (88.0, 104.0)
# the next streets out: the city is a grid of blocks about the size of ours
ROAD_S2 = (181.0, 197.0)
ROAD_N2 = (-152.0, -136.0)
ROAD_W2 = (-178.0, -162.0)
ROAD_E2 = (218.0, 234.0)
ROADS_X = (ROAD_W2, ROAD_W, ROAD_E, ROAD_E2)
ROADS_Y = (ROAD_N2, ROAD_N, ROAD_S, ROAD_S2)
# the ground slab's bounds, then every kerb: even gaps are blocks, odd are roads
XB = [-320.0] + [v for b_ in ROADS_X for v in b_] + [440.0]
YB = [-280.0] + [v for b_ in ROADS_Y for v in b_] + [330.0]
# where the opening shot stands (renders survey section 6, judged in the page)
# on the far pavement of the main street, against the shopfronts across it:
# the square the shot used to stand in is buildings now, as in the renders
HERO_EYE = (26.0, 75.5, 1.70)
HERO_AT = (44.0, 18.0, 15.0)
# Alternatives for the owner (exterior review, build 2), written to
# scene_meta.site.hero_candidates; plan frame, hfov in degrees across 16:9
# `shift` lifts the frame (horizon at -shift in NDC), `pan` slides it so the
# L stands right of the hero's text scrim (spent by 50% of the width): the
# lensShift / lensPan of app.js installLensShift. Rendered from the page for
# the owner: scratchpad build2/exterior-review/hero3/*.
HERO_CANDIDATES = {
    # across the planted square, a first-floor eye: both masses whole, the
    # wing's frame and west face, the terrace over the shopfronts (pick)
    'square_9m': {'eye': (0.0, 75.5, 9.0), 'at': (41.0, 17.0, 9.0),
                  'hfov': 84, 'shift': 0.24, 'pan': 0.35},
    # 006's own street, eye level, from the far pavement west of the axis
    'front_eye': {'eye': (20.0, 75.5, 1.7), 'at': (41.0, 17.0, 1.7),
                  'hfov': 92, 'shift': 0.36, 'pan': 0.35},
    # 002's corner of the junction, eye level: the gable leads, the bar
    # recedes to the wing
    'sw_corner_eye': {'eye': (-29.0, 75.5, 1.7), 'at': (41.0, 17.0, 1.7),
                      'hfov': 92, 'shift': 0.36, 'pan': 0.35},
}


# the terrace stair (cores.glb 'podium'): the hole its upper flight and top
# landing need in the +4.8 deck, and the door out of its house (L01 d10)
STAIR_HOLE = (19.15, 29.05, 21.85, 34.53)
STAIR_DOOR = (19.40, 20.79)


def _stair_hole():
    """The hole from the interior's own stair (plan_meta cores 'podium'):
    from the hall's north end (the +4.8 top landing, which the interior
    floors) to the far end of its flights and half landing - build 3 had it
    1.25 m short of the stair (y 29.05..33.30 against 30.30..34.53)."""
    import json, os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'web', 'plan_meta.json')
    try:
        with open(path) as f:
            pm = json.load(f)
        c = [c for c in pm['cores'] if c['id'] == 'podium'][0]
        hx = [p[0] for p in c['hall']['outline']]; hy = [p[1] for p in c['hall']['outline']]
        ys = []
        for st in c['storeys']:
            for fl in st['flights'] + [st['half_landing']]:
                ys += [p[1] for p in fl['poly']['outline']]
        hole = (round(min(hx), 2), round(min(hy), 2), round(max(hx), 2), round(max(ys), 2))
        door = None
        for L in pm['levels']:
            if L['id'] != 'L01':
                continue
            for d in L['doors']:
                hxx, hyy = d['hinge']
                if abs(hyy - hole[1]) < 0.1 and hole[0] - 0.1 < hxx < hole[2] + 0.1:
                    a = math.radians(d['shut'])
                    xe = hxx + d['w'] * math.cos(a)
                    door = (round(min(hxx, xe), 2), round(max(hxx, xe), 2), d['id'])
        print('[terrace] stair hole %s from plan_meta, door %s' % (hole, door))
        return hole, (door[:2] if door else STAIR_DOOR), (door[2] if door else 'd10')
    except (OSError, ValueError, KeyError, IndexError) as e:
        print('[terrace] stair hole: fallback (%s)' % e)
        return STAIR_HOLE, STAIR_DOOR, 'd10'


STAIR_HOLE, STAIR_DOOR, STAIR_DOOR_ID = _stair_hole()
DECK_Z0 = LB.CEIL_CLEAR_L00      # the deck's underside: over the L00 ceilings (+4.50)


def P(x, y, z=0.0):
    return (x, -y, z)


def pbox(mb, x0, y0, z0, x1, y1, z1):
    """box given in the plan frame"""
    mb.box((x0, -y0, z0), (x1, -y1, z1))


# ------------------------------------------------------------------ podium
def _podium_outline():
    return LB.clean_poly(LEV['L00']['outline']['outline'])


def _tower_poly():
    return LB.clean_poly(LEV['ROOF']['outline']['outline'])


CORE_DOORS = {
    # entrance hall doors to the outside, from the +0.000 sheet: C1 and C2 on
    # the rear (row 1) face, C3 on the east face. Fallback only - ENTRANCES
    # below takes them from the interior build's portals when it has run.
    'C1': ((21.92, 0.26), (0.0, -1.0)),
    'C2': ((60.63, 0.26), (0.0, -1.0)),
    'C3': ((82.55, 20.50), (1.0, 0.0)),
}
DOOR_H = 2.10            # the interior lines every street door to +2.10
# what the plate beside each street door says (scene_meta site.entrances[].label)
ENTRANCE_LABEL = {'C1': '1', 'C2': '2', 'C3': '3', 'podium': 'TERRACE'}


def _entrances():
    """The four ways in from the street - three core halls and the terrace
    stair - one per portal of web/plan_meta.json (written by
    build_interior.py, so the door stands exactly where the hall has its
    opening). Plan frame: centre, outward normal, clear width, the portal
    line, and whether the interior hangs its own leaf there (then the street
    leaf is only a stand-in until the interior arrives; see CONTRACT.md)."""
    import json, os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'web', 'plan_meta.json')
    out = {}
    try:
        with open(path) as f:
            for p in json.load(f).get('portals', []):
                a, b = p['a'], p['b']
                n = p['normal']
                n = (round(n[0]), round(n[1]))
                out[p['core']] = {'c': ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), 'n': n,
                                  'w': math.hypot(b[0] - a[0], b[1] - a[1]),
                                  'line': a[1] if n[1] else a[0],
                                  'leaf': bool(p.get('door'))}
    except (OSError, ValueError, KeyError) as e:
        print('[podium] no portals from plan_meta.json (%s): fallback doors' % e)
    for k, ((x, y), n) in CORE_DOORS.items():
        out.setdefault(k, {'c': (x, y), 'n': n, 'w': 1.1, 'line': y if n[1] else x,
                           'leaf': False})
    out.setdefault('podium', {'c': (20.625, 36.354), 'n': (0, 1), 'w': 2.456,
                              'line': 36.354, 'leaf': False})
    return out


ENTRANCES = _entrances()
# Fronts that stay glazed whatever hangs in the door: C3's and the terrace
# stair's are glass the full width of the run (C1 and C2 are a blank plinth
# with a door in it). Build 3 tied this to "no interior leaf"; since the
# interior hangs leaves at C3 and the podium too, the look is pinned here.
GLAZED_FRONTS = ('C3', 'podium')


def _shop_doors():
    """The commercial street doors the +0.000 sheet draws in the shopfronts
    (plan_meta L00 doors kind 'street' with no owner), paired into openings:
    {id: {'leaves': [door records], 'a', 'b' (the span, plan), 'line', 'axis',
    'c', 'n' (outward, set where the face is found), 'w'}}. Ids S1, S2... in
    order round the outline (the north face west to east, then the west face)."""
    import json, os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'web', 'plan_meta.json')
    try:
        with open(path) as f:
            L0 = [L for L in json.load(f)['levels'] if L['id'] == 'L00'][0]
    except (OSError, ValueError, KeyError, IndexError) as e:
        print('[podium] no shop doors (%s)' % e)
        return {}
    spans = []
    for d in L0['doors']:
        if d.get('kind') != 'street' or d.get('owner'):
            continue
        a = d['hinge']; t = math.radians(d['shut'])
        b = (a[0] + d['w'] * math.cos(t), a[1] + d['w'] * math.sin(t))
        axis = 'x' if abs(b[1] - a[1]) < abs(b[0] - a[0]) else 'y'
        k = 0 if axis == 'x' else 1
        lo, hi = sorted((a[k], b[k]))
        spans.append([axis, (a[1] + b[1]) / 2 if axis == 'x' else (a[0] + b[0]) / 2, lo, hi, [d]])
    spans.sort(key=lambda r: (r[0], round(r[1], 1), r[2]))
    pairs = []
    for sp in spans:
        if pairs and pairs[-1][0] == sp[0] and abs(pairs[-1][1] - sp[1]) < 0.1 and \
                abs(sp[2] - pairs[-1][3]) < 0.1:
            pairs[-1][3] = max(pairs[-1][3], sp[3]); pairs[-1][4] += sp[4]
        else:
            pairs.append(sp)
    # north face (axis x, small y) west to east first, then the west face
    pairs.sort(key=lambda r: (0 if r[0] == 'x' else 1, r[2]))
    out = {}
    for i, (axis, line, lo, hi, ds) in enumerate(pairs):
        c = ((lo + hi) / 2, line) if axis == 'x' else (line, (lo + hi) / 2)
        out['S%d' % (i + 1)] = {'axis': axis, 'line': line, 'lo': lo, 'hi': hi,
                                'c': c, 'w': hi - lo, 'leaves': ds, 'n': None}
    print('[podium] shop doors: %s' % {k: (v['axis'], round(v['line'], 3), round(v['lo'], 3),
                                           round(v['hi'], 3), [d['id'] for d in v['leaves']])
                                       for k, v in out.items()})
    return out


SHOP_DOORS = _shop_doors()


def build_podium():
    """The commercial storey from the +0.000 plan: its outline walled in light
    concrete, one shopfront in every glazed run the plan draws (south and west
    faces, three under the bar's east gable), glazed lobby fronts where the
    three cores' entrance halls reach the outside, each with a door and a
    canopy, the sign band and the parapet round the terrace, the pilotis of
    the ramp passage under the wing."""
    coll = collection('podium')
    Op = _podium_outline()
    tower = _tower_poly()
    sign = 1 if LB._area(Op) > 0 else -1
    runs = [r for r in LEV['L00']['facade'] if r['state'] == 'open']
    c = MB(); fas = MB(); g = MB(); ins = MB(); mull = MB()
    lob_g = MB(); lob_f = MB(); doors = MB(); canopy = MB(); plates = MB()
    n_pts = len(Op)
    leaves = {}
    plate_text = []

    def door(eid, d0, d1, dpl, sbox):
        """A street door at [d0, d1] along the front, its plane `dpl` in from
        the outline: a metal surround and a canopy (podium_entrance_doors /
        _canopy), and the shut glazed leaf - one leaf, or a pair when the
        opening is wider than a leaf - as its OWN nodes,
        podium_door_<id>_leaf and _leaf_glass, so the page can take them
        away once the interior (with its own swinging leaf, or none) is in
        and the visitor walks through. See CONTRACT.md."""
        lf, lg = leaves.setdefault(eid, (MB(), MB()))
        H = DOOR_H
        sbox(doors, d0 - 0.08, d0, dpl - 0.08, dpl + 0.08, 0.0, H + 0.08)
        sbox(doors, d1, d1 + 0.08, dpl - 0.08, dpl + 0.08, 0.0, H + 0.08)
        sbox(doors, d0 - 0.08, d1 + 0.08, dpl - 0.08, dpl + 0.08, H, H + 0.08)
        nl = 1 if d1 - d0 < 1.4 else 2
        for k in range(nl):
            a = d0 + (d1 - d0) * k / nl + 0.005
            b = d0 + (d1 - d0) * (k + 1) / nl - 0.005
            sbox(lf, a, b, dpl - 0.025, dpl + 0.025, 0.01, 0.13)
            sbox(lf, a, a + 0.07, dpl - 0.025, dpl + 0.025, 0.13, H - 0.01)
            sbox(lf, b - 0.07, b, dpl - 0.025, dpl + 0.025, 0.13, H - 0.01)
            sbox(lf, a + 0.07, b - 0.07, dpl - 0.025, dpl + 0.025, H - 0.09, H - 0.01)
            hx = b - 0.14 if (nl == 1 or k == 0) else a + 0.10
            sbox(lf, hx, hx + 0.04, dpl - 0.14, dpl - 0.025, 0.85, 1.85)   # pull handle
            sbox(lg, a + 0.07, b - 0.07, dpl - 0.01, dpl + 0.01, 0.13, H - 0.09)
        # The portal: a dark steel frame standing 14 cm proud of the wall round
        # the opening, a deep canopy over it, and the entrance's number on a
        # pale plate beside it ("1", "2", "3" as the floor view names the
        # cores' entrances; the terrace stair says where it goes) - so each
        # way in reads as a front door from across the street.
        F = 0.22
        sbox(canopy, d0 - 0.08 - F, d0 - 0.08, -0.14, 0.02, 0.0, 2.92)
        sbox(canopy, d1 + 0.08, d1 + 0.08 + F, -0.14, 0.02, 0.0, 2.92)
        sbox(canopy, d0 - 0.08, d1 + 0.08, -0.14, 0.02, H + 0.08, 2.92)
        c0, c1 = d0 - 0.08 - F - 0.45, d1 + 0.08 + F + 0.45
        sbox(canopy, c0, c1, -1.85, 0.02, 2.92, 3.14)              # cantilevered
        sbox(canopy, c0, c1, -1.85, -1.79, 2.86, 2.92)             # its drip edge
        lab = ENTRANCE_LABEL.get(eid)
        if lab:
            # the number over the door, on the portal's head panel
            pw = 0.52 if len(lab) < 3 else 1.30
            sm = (d0 + d1) / 2
            sbox(plates, sm - pw / 2, sm + pw / 2, -0.17, -0.13, 2.30, 2.80)
            mid = at(sm, -0.17)
            plate_text.append((eid, lab, (mid[0], -mid[1]), n, 2.55,
                               0.40 if len(lab) < 3 else 0.17))

    def convex(i):
        a = Op[i - 1]; b = Op[i]; d = Op[(i + 1) % n_pts]
        cr = (b[0] - a[0]) * (d[1] - b[1]) - (b[1] - a[1]) * (d[0] - b[0])
        return cr * sign > 0

    # is this edge under the tower (the wall stops at the slab) or round the
    # terrace (it runs on up as the parapet)? Probed 0.6 m in from its middle;
    # a short return - the 0.4 m pilaster on the west gable at y 16.56..16.75 -
    # follows its neighbours: its own probe landed outside the tower and it
    # stood up to the parapet top, a stub in front of the black gable
    under = []
    for i in range(n_pts):
        a, b = Op[i], Op[(i + 1) % n_pts]
        dx, dy = b[0] - a[0], b[1] - a[1]
        Ln = math.hypot(dx, dy)
        n = (sign * dy / Ln, -sign * dx / Ln)
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        under.append(LB.in_poly((mid[0] - n[0] * 0.6, mid[1] - n[1] * 0.6), tower))
    for i in range(n_pts):
        a, b = Op[i], Op[(i + 1) % n_pts]
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 1.0 and not under[i] and \
                under[i - 1] and under[(i + 1) % n_pts]:
            under[i] = True
            print('[podium] short return %s..%s follows its neighbours under the tower' % (a, b))
    for i in range(n_pts):
        a, b = Op[i], Op[(i + 1) % n_pts]
        axis = 'x' if abs(a[1] - b[1]) < 1e-3 else 'y'
        dx, dy = b[0] - a[0], b[1] - a[1]
        Ln = math.hypot(dx, dy)
        n = (sign * dy / Ln, -sign * dx / Ln)
        if axis == 'x':
            lo, hi, cc = min(a[0], b[0]), max(a[0], b[0]), a[1]
            P0 = (lo, -cc); t = (1.0, 0.0)
        else:
            lo, hi, cc = min(a[1], b[1]), max(a[1], b[1]), a[0]
            P0 = (cc, -lo); t = (0.0, -1.0)
        nB = (n[0], -n[1]); m = (-nB[0], -nB[1])
        holes, shops, lobbies = [], [], []
        for r in runs:
            ra, rb = r['a'], r['b']
            if axis == 'x':
                if abs(ra[1] - cc) > 0.03 or abs(rb[1] - cc) > 0.03:
                    continue
                s0, s1 = sorted((ra[0], rb[0]))
            else:
                if abs(ra[0] - cc) > 0.03 or abs(rb[0] - cc) > 0.03:
                    continue
                s0, s1 = sorted((ra[1], rb[1]))
            s0 = max(s0, lo); s1 = min(s1, hi)
            if s1 - s0 < 0.8:
                continue
            if r['behind'] == 'core':
                ent = None
                for eid, e in ENTRANCES.items():
                    sd = e['c'][0] if axis == 'x' else e['c'][1]
                    if abs(e['line'] - cc) < 0.35 and s0 - 0.2 <= sd <= s1 + 0.2 and \
                            abs(e['n'][1 if axis == 'x' else 0]) == 1:
                        ent = (eid, e, sd)
                # C1 and C2 are a blank plinth with a door in it (renders
                # 003/004 show no lobby glazing on the north face, and the
                # interior lines the run as wall); C3 and the terrace stair
                # are glazed fronts whose whole width is the door
                solid = ent is not None and ent[0] not in GLAZED_FRONTS
                if solid:
                    hw = ent[1]['w'] / 2 + 0.08
                    holes.append((ent[2] - hw - lo, ent[2] + hw - lo, 0.0, DOOR_H + 0.08))
                else:
                    holes.append((s0 - lo, s1 - lo, 0.0, 3.05))
                lobbies.append((s0, s1, ent, solid))
            else:
                holes.append((s0 - lo, s1 - lo, SHOP_SILL, FASCIA_Z))
                # a commercial street door drawn in this shopfront: the run
                # opens to the floor over the door (build 4)
                sd = []
                for sid, e in SHOP_DOORS.items():
                    if e['axis'] == axis and abs(e['line'] - cc) < 0.35 and \
                            s0 - 0.05 <= e['lo'] and e['hi'] <= s1 + 0.05:
                        e['n'] = (round(n[0]), round(n[1]))
                        dd = (e['line'] - cc) * (-n[1] if axis == 'x' else -n[0])
                        sd.append((sid, e['lo'], e['hi'], max(dd, 0.03)))
                        holes.append((e['lo'] - 0.06 - lo, e['hi'] + 0.06 - lo, 0.0, SHOP_SILL + 0.01))
                shops.append((s0, s1, sd))
        # under the tower the wall stops at the slab; round the terrace it
        # runs on up as the parapet and sign band
        top = GROUND_H - 0.002 if under[i] else PARAPET_TOP
        # Where the run is an entrance hall's front, the plan's own wall (the
        # interior's, lined) is the hall's wall: the street keeps only a skin
        # in the outline, outside its lining. At 0.40 deep the podium wall
        # stood 0.39 m inside C1's and C2's halls (their north wall WAS the
        # street's concrete, half over the upper flight) and 0.27 m into C3's
        # over its door (build 4).
        core_len = sum(max(0.0, min(max(r['a'][0 if axis == 'x' else 1], r['b'][0 if axis == 'x' else 1]), hi) -
                           max(min(r['a'][0 if axis == 'x' else 1], r['b'][0 if axis == 'x' else 1]), lo))
                       for r in runs if r['behind'] == 'core' and
                       abs((r['a'][1] if axis == 'x' else r['a'][0]) - cc) < 0.03 and
                       abs((r['b'][1] if axis == 'x' else r['b'][0]) - cc) < 0.03)
        skin = core_len > 0.5 * (hi - lo)
        wd0, wd = (-HALL_SKIN, 0.0) if skin else (0.0, POD_T)
        if skin:
            print('[podium] hall front %s=%.3f %.3f..%.3f: a skin outside the outline' % ('y' if axis == 'x' else 'x', cc, lo, hi))
        tr0 = POD_T if (axis == 'y' and convex(i)) else 0.0
        tr1 = POD_T if (axis == 'y' and convex((i + 1) % n_pts)) else 0.0
        if axis == 'y' and a[1] > b[1]:
            tr0, tr1 = tr1, tr0
        LB.wall_cells(c, P0, t, m, tr0, (hi - lo) - tr1, wd0, wd, 0.0,
                      top - (0.06 if top > GROUND_H else 0.0), holes)
        if top > GROUND_H:
            # coping, a hair proud both sides
            p = (P0[0] + t[0] * tr0 - m[0] * 0.03, P0[1] + t[1] * tr0 - m[1] * 0.03)
            q = (P0[0] + t[0] * ((hi - lo) - tr1) + m[0] * (POD_T + 0.03),
                 P0[1] + t[1] * ((hi - lo) - tr1) + m[1] * (POD_T + 0.03))
            fas.box((p[0], p[1], top - 0.06), (q[0], q[1], top))

        def at(s, d):
            return (P0[0] + t[0] * (s - lo) + m[0] * d, P0[1] + t[1] * (s - lo) + m[1] * d)

        def sbox(mb, s0, s1, d0, d1, z0, z1):
            p = at(s0, d0); q = at(s1, d1)
            mb.box((p[0], p[1], z0), (q[0], q[1], z1))
        for (s0, s1, sd) in shops:
            # spans of the run with no door in them, and the doors' openings
            cuts = sorted((d0 - 0.06, d1 + 0.06) for (_i, d0, d1, _p) in sd)
            free, u = [], s0 + 0.04
            for (a_, b_) in cuts:
                free.append((u, a_)); u = b_
            free.append((u, s1 - 0.04))
            free = [(a_, b_) for (a_, b_) in free if b_ - a_ > 0.02]
            for (a_, b_) in free:
                sbox(g, a_, b_, POD_T - 0.06, POD_T - 0.03, SHOP_SILL + 0.03, FASCIA_Z - 0.03)
            ifree, u = [], s0 + 0.04
            for (a_, b_) in cuts:
                ifree.append((u, a_ - 0.30)); u = b_ + 0.30
            ifree.append((u, s1 - 0.04))
            for (a_, b_) in ifree:
                if b_ - a_ > 0.05:
                    sbox(ins, a_, b_, POD_T + 1.90, POD_T + 1.95, 0.20, FASCIA_Z - 0.10)
            k = max(2, int(round((s1 - s0) / 1.4)))
            for q in range(k + 1):
                s = s0 + 0.04 + (s1 - s0 - 0.08) * q / k
                if any(a_ - 0.04 < s < b_ + 0.04 for (a_, b_) in cuts):
                    continue
                sbox(mull, s - 0.035, s + 0.035, POD_T - 0.11, POD_T - 0.01, SHOP_SILL + 0.03, FASCIA_Z - 0.03)
            for zz in (SHOP_SILL + 0.03, 2.95, FASCIA_Z - 0.11):
                for (a_, b_) in (free if zz < DOOR_H else [(s0 + 0.04, s1 - 0.04)]):
                    sbox(mull, a_, b_, POD_T - 0.11, POD_T - 0.01, zz, zz + 0.08)
            for (sid, d0, d1, dpl) in sd:
                # the door: a bronze frame in the plane the interior hangs its
                # leaves in, glass over it to the run's head, the run's
                # mullions either side, and the shut stand-in leaves as their
                # own nodes (podium_door_<id>_leaf, as at the cores: the page
                # hides them once L00 is in)
                lf, lg = leaves.setdefault(sid, (MB(), MB()))
                H = DOOR_H
                for (a_, b_) in ((d0 - 0.06, d0), (d1, d1 + 0.06)):
                    sbox(mull, a_, b_, dpl - 0.05, POD_T - 0.01, 0.0, FASCIA_Z - 0.03)
                sbox(mull, d0, d1, dpl - 0.05, POD_T - 0.01, H, H + 0.08)
                sbox(g, d0, d1, POD_T - 0.06, POD_T - 0.03, H + 0.08, FASCIA_Z - 0.03)
                sbox(mull, d0, d1, POD_T - 0.11, POD_T - 0.01, FASCIA_Z - 0.11, FASCIA_Z - 0.03)
                e = SHOP_DOORS[sid]
                for dr in e['leaves']:
                    ha = dr['hinge']; t_ = math.radians(dr['shut'])
                    hb = (ha[0] + dr['w'] * math.cos(t_), ha[1] + dr['w'] * math.sin(t_))
                    kk = 0 if axis == 'x' else 1
                    a_, b_ = sorted((ha[kk], hb[kk]))
                    a_ += 0.005; b_ -= 0.005
                    sbox(lf, a_, b_, dpl - 0.025, dpl + 0.025, 0.01, 0.13)
                    sbox(lf, a_, a_ + 0.07, dpl - 0.025, dpl + 0.025, 0.13, H - 0.01)
                    sbox(lf, b_ - 0.07, b_, dpl - 0.025, dpl + 0.025, 0.13, H - 0.01)
                    sbox(lf, a_ + 0.07, b_ - 0.07, dpl - 0.025, dpl + 0.025, H - 0.09, H - 0.01)
                    free_end = b_ - 0.14 if abs(ha[kk] - a_) < abs(ha[kk] - b_) else a_ + 0.10
                    sbox(lf, free_end, free_end + 0.04, dpl - 0.14, dpl - 0.025, 0.85, 1.85)
                    sbox(lg, a_ + 0.07, b_ - 0.07, dpl - 0.01, dpl + 0.01, 0.13, H - 0.09)
        for (s0, s1, ent, solid) in lobbies:
            # the door: in the plane of the hall's own opening (the portal
            # line, 0.10 m in), so the interior's leaf and lining meet it
            if ent:
                eid, e, sd = ent
                dpl = (e['line'] - cc) * (-n[1] if axis == 'x' else -n[0]) + 0.10
                dw = e['w']
                d0, d1 = sd - dw / 2, sd + dw / 2
                door(eid, d0, d1, dpl, sbox)
            if solid:
                continue
            # the glazed rest of the front, in the same plane - or, where no
            # door is, just outside the outline: the sheet draws the hall's
            # wall there (outline-drawn, interior-fix build 3), and glass
            # 0.10 in stood inside C3's hall in front of it
            dpl = -0.04 if not ent else dpl
            segs = [(s0, s1)] if not ent else [(s0, d0 - 0.08), (d1 + 0.08, s1)]
            for (u, v) in segs:
                if v - u < 0.3:
                    continue
                k = max(1, int(round((v - u) / 1.5)))
                for q in range(k + 1):
                    sq = u + (v - u) * q / k
                    sbox(lob_f, sq - 0.04, sq + 0.04, dpl - 0.06, dpl + 0.04, 0.0, 3.05)
                for zz in (0.0, DOOR_H + 0.08, 2.97):
                    sbox(lob_f, u, v, dpl - 0.06, dpl + 0.04, zz, zz + 0.08)
                sbox(lob_g, u + 0.04, v - 0.04, dpl - 0.02, dpl, 0.08, 2.97)
            if ent:
                # transom over the door up to the glazing head
                sbox(lob_f, d0 - 0.08, d1 + 0.08, dpl - 0.06, dpl + 0.04, 2.97, 3.05)
                sbox(lob_g, d0, d1, dpl - 0.02, dpl, DOOR_H + 0.16, 2.97)
                sbox(lob_f, d0, d1, dpl - 0.06, dpl + 0.04, DOOR_H + 0.08, DOOR_H + 0.16)

    # the body behind the shops, kept clear of the three entrance halls and
    # the terrace stair so they stay open for the interiors
    for (x0, y0, x1, y1) in ((2.4, 7.6, 74.0, 28.7), (2.4, 28.7, 18.8, 34.0),
                             (22.2, 28.7, 74.0, 34.0), (2.4, 2.4, 12.5, 7.6),
                             (22.9, 2.4, 59.6, 7.6), (70.0, 2.4, 74.0, 7.6),
                             (74.0, 2.4, 78.6, 16.4), (2.4, 34.0, 18.8, 34.0)):
        if x1 - x0 > 0.1 and y1 - y0 > 0.1:
            pbox(c, x0, y0, 0.0, x1, y1, GROUND_H - 0.36)
    # the ramp passage under the wing: pilotis on its open east side
    for col in LEV['L00']['columns']:
        x, y = col['c']
        if x > 81.5 and 21.5 < y < 37.0:
            s = (col.get('size') or 0.6) / 2
            pbox(c, x - s, y - s, 0.0, x + s, y + s, GROUND_H - 0.36)
    # the terrace deck over the podium roof
    terr = LEV['L01']['terraces'][0]['outline']
    tp = [(min(max(p[0], 0.15), 61.85), min(p[1], 36.15)) for p in terr]
    # ...open over the terrace stair's upper flight and its landing at +4.8
    # (the stair is the interior's, cores.glb): the deck goes round the hole
    xs = [p[0] for p in tp]; ys = [p[1] for p in tp]
    tx0, tx1, ty0, ty1 = min(xs), max(xs), min(ys), max(ys)
    hx0, hy0, hx1, hy1 = STAIR_HOLE
    for (x0, y0, x1, y1) in ((tx0, ty0, hx0, ty1), (hx1, ty0, tx1, ty1),
                             (hx0, ty0, hx1, hy0), (hx0, hy1, hx1, ty1)):
        pbox(c, x0, y0, DECK_Z0, x1, y1, GROUND_H)
    c.to_object('podium_shell', M('concrete_podium'), coll)
    fas.to_object('podium_fascia', M('concrete_podium'), coll)
    g.to_object('podium_glass', M('glass_shop'), coll)
    ins.to_object('podium_interior', M('shop_interior'), coll)
    mull.to_object('podium_mullions', M('frame_bronze'), coll)
    lob_g.to_object('podium_lobby_glass', M('glass_window'), coll)
    lob_f.to_object('podium_lobby_frame', M('frame_bronze'), coll)
    doors.to_object('podium_entrance_doors', M('metal_dark'), coll)
    for eid, (lf, lg) in sorted(leaves.items()):
        lf.to_object('podium_door_%s_leaf' % eid, M('metal_dark'), coll)
        lg.to_object('podium_door_%s_leaf_glass' % eid, M('glass_window'), coll)
    canopy.to_object('podium_entrance_canopy', M('metal_dark'), coll)
    plates.to_object('podium_entrance_plates', M('frame_light'), coll)
    for (eid, lab, (px, py), n, zc, size) in plate_text:
        t = text_obj(coll, lab, px, py, n, zc - size * 0.36, size, 'metal_dark', 0.02,
                     name='sign_entrance_%s' % eid, off=0.0)
    # the ramp down to -3.000 inside the passage
    rp = MB(); rw = MB()
    x0, x1 = 76.9, 82.15
    y_top, y_bot = 36.55, 21.95
    zb = -(y_top - y_bot) * 0.1667
    rp.add([P(x0, y_top, LOT_Z), P(x1, y_top, LOT_Z), P(x1, y_bot, zb), P(x0, y_bot, zb)],
           [(0, 3, 2, 1)])
    for xa, xb in ((76.5, x0), (x1, 82.55)):
        rw.add([P(xa, y_top, 0.0), P(xb, y_top, 0.0), P(xb, y_bot, 0.0), P(xa, y_bot, 0.0)],
               [(0, 3, 2, 1)])
        # the ramp's side walls down to its floor
        rw.add([P(x0 if xa < x0 else x1, y_top, LOT_Z), P(x0 if xa < x0 else x1, y_bot, zb),
                P(x0 if xa < x0 else x1, y_bot, 0.0), P(x0 if xa < x0 else x1, y_top, 0.0)],
               [(0, 1, 2, 3)] if xa < x0 else [(3, 2, 1, 0)])
    pbox(rw, x0, y_bot - 0.3, zb - 0.1, x1, y_bot, 0.0)
    rp.to_object('ramp', M('asphalt'), coll)
    rw.to_object('ramp_walls', M('concrete_podium'), coll)
    return coll


# ------------------------------------------------------------------ terrace
# The +4.8 roof garden, after render 005 (and 001/006 from the street): along
# the bar a row of timber planter-benches, each with its tree, pale end caps
# and lawn between them; a paved promenade down the middle with the drainage
# channel along its north edge; cafe tables under 4 m butterfly umbrellas on
# the south half; two timber-slatted pergolas over the lawns and two shade
# sails. All plan frame, deck top at PARK_TOP. Repeated pieces are hidden kit
# sources (collection 'kit') placed as linked duplicates: one mesh per kit and
# material on the wire. Kept clear for the walk (plan_meta L01 nav): the
# promenade y 23.8..28.6 end to end, the stair house door's apron, and the
# forecourt of the wing's corridor door d9 (x 55..61.85, y 18.6..28.6).
# scene_meta.site.terrace.solids lists every footprint below for the walk.
PLANTERS = [(6.0, 20.05, 5.0), (17.5, 20.05, 5.0), (29.0, 20.05, 5.0),
            (40.5, 20.05, 5.0), (51.0, 20.05, 5.0)]          # centre x, y; length
PLANTERS_S = [(24.6, 34.15), (32.5, 34.15), (48.5, 34.15)]  # square tree tubs by the hedge
LAWNS = [(1.15, 18.65, 3.25, 22.9), (8.95, 18.65, 14.55, 22.9), (53.95, 18.65, 54.6, 22.9)]
# timber decks (3 cm boards on the paving): the lounge under the first sail,
# the lounge and the long table under the pergolas, the two cafe floors
DECKS = [(20.6, 18.75, 25.9, 22.8), (32.2, 18.75, 37.3, 22.8), (43.6, 18.75, 47.9, 22.8),
         (3.5, 29.2, 16.2, 33.6), (25.6, 29.2, 55.0, 33.6)]
# lounge sets: sofa centre, the way it faces (plan: 1 = +y south, -1 = north)
LOUNGES = [(23.3, 19.6, 1), (34.75, 19.6, 1), (58.4, 33.45, -1)]
DINING = (45.75, 20.75)                                      # long table and benches, 2.4 m
LOUNGERS = [(10.0, 20.9), (11.75, 20.9), (13.5, 20.9)]       # sun loungers on the lawn, heads north
# potted plants (lib kit furn_kit_plants, grown to outdoor size): kind, x, y, scale
POTS = [('plant_olive', 18.2, 30.3, 1.7), ('plant_olive', 22.8, 30.3, 1.7),
        ('plant_palm', 9.75, 34.3, 1.6), ('plant_fiddle', 16.9, 34.3, 1.6),
        ('plant_monstera', 28.6, 34.4, 1.7), ('plant_palm', 40.5, 34.3, 1.6),
        ('plant_olive', 44.5, 34.4, 1.6), ('plant_fiddle', 53.0, 34.3, 1.6),
        ('plant_palm', 1.9, 29.3, 1.7), ('plant_monstera', 1.9, 33.6, 1.7),
        ('plant_olive', 60.9, 29.1, 1.6), ('plant_rubber', 54.3, 20.7, 1.8),
        ('plant_palm', 2.2, 20.7, 1.6)]
BOLLARDS = [(x, 28.95) for x in (4.0, 10.3, 16.6, 24.5, 30.8, 37.1, 43.4, 49.7)]
# festoon lights round the two cafe floors: the posts of each loop, in order
FESTOONS = [[(3.3, 29.0), (16.4, 29.0), (16.4, 33.85), (3.3, 33.85)],
            [(26.0, 29.0), (40.4, 29.0), (54.8, 29.0), (54.8, 33.85), (40.4, 33.85), (26.0, 33.85)]]
FESTOON_H = 3.55
CAFES = [(6.5, 31.4, 0.0), (13.0, 31.4, 90.0), (28.5, 31.4, 0.0), (36.6, 31.4, 90.0),
         (44.5, 31.4, 0.0), (52.6, 31.4, 90.0)]               # centre, turn (deg)
SAILS = [(((20.85, 18.85), 3.55), ((25.75, 19.05), 3.05), ((23.3, 22.75), 3.75)),
         (((55.6, 29.35), 3.45), ((61.25, 29.85), 3.85), ((58.2, 34.6), 3.15))]
PERGOLAS = [(34.75, 20.75), (45.75, 20.75)]                  # 3.8 x 2.8 m
CHANNEL = (1.4, 61.5, 23.55)                                 # x0, x1, y
PLANTER_SOIL = 0.80                                          # tree base over the deck (005: the box is the bench's back)


def terrace_planters():
    """the trees on the terrace: one in every planter-bench and tub"""
    return [(x, y) for (x, y, _) in PLANTERS] + list(PLANTERS_S)


def terrace_solids():
    """Footprints (plan x0, y0, x1, y1) of everything standing on the deck,
    for the walk (scene_meta.site.terrace.solids): planters with their
    benches, tubs, cafe sets, umbrella/pergola/sail posts, the stair house."""
    out = []
    for (x, y, L) in PLANTERS:
        out.append((x - L / 2 - 0.08, y - 0.7, x + L / 2 + 0.08, y + 1.15))
    for (x, y) in PLANTERS_S:
        out.append((x - 0.8, y - 0.8, x + 0.8, y + 0.8))
    for (x, y, rot) in CAFES:
        a, b = (2.15, 1.10) if rot == 0.0 else (1.10, 2.15)
        out.append((x - a, y - b, x + a, y + b))
    for (px, py) in PERGOLAS:
        for (dx, dy) in ((-1.85, -1.35), (1.85, -1.35), (-1.85, 1.35), (1.85, 1.35)):
            out.append((px + dx - 0.06, py + dy - 0.06, px + dx + 0.06, py + dy + 0.06))
    for tri in SAILS:
        for ((x, y), _) in tri:
            out.append((x - 0.08, y - 0.08, x + 0.08, y + 0.08))
    for (x, y, f) in LOUNGES:
        out.append((x - 1.15, y - 0.5, x + 1.15, y + 0.5))            # sofa
        out.append((x - 0.55, y + f * 1.0, x + 0.55, y + f * 1.6))    # table
        for sx in (-1, 1):
            out.append((x + sx * 1.3 - 0.42, y + f * 1.35 - 0.42, x + sx * 1.3 + 0.42, y + f * 1.35 + 0.42))
    dx, dy = DINING
    out.append((dx - 1.25, dy - 1.05, dx + 1.25, dy + 1.05))
    for (x, y) in LOUNGERS:
        out.append((x - 0.36, y - 1.0, x + 0.36, y + 1.0))
    for (_, x, y, sc) in POTS:
        out.append((x - 0.25 * sc, y - 0.25 * sc, x + 0.25 * sc, y + 0.25 * sc))
    for (x, y) in BOLLARDS:
        out.append((x - 0.09, y - 0.09, x + 0.09, y + 0.09))
    for loop in FESTOONS:
        for (x, y) in loop:
            out.append((x - 0.07, y - 0.07, x + 0.07, y + 0.07))
    hx0, hy0, hx1, hy1 = STAIR_HOLE
    out.append((hx0 - 0.2, hy0 - 0.2, hx1 + 0.2, hy1 + 0.2))
    return [tuple(round(v, 3) for v in r) for r in out]


# The interior's furniture kits (furn_kit_*: pure python, kit-local +X = the
# way a piece faces), dressed for outdoors: the street file already carries
# every material named here, so a sofa on the terrace costs it no new one.
OUTDOOR = {'int_wood_walnut': 'int_wood_oak', 'int_coffee_top': 'int_wood_oak',
           'int_fabric_sofa': 'canopy_fabric', 'int_fabric_white': 'canopy_fabric',
           'int_fabric_teal': 'canopy_fabric', 'int_fabric_orange': 'int_accent_red',
           'int_fabric_dark': 'frame_bronze', 'int_fabric_bluegrey': 'stone_classical',
           'int_mint': 'stone_classical', 'int_ceramic': 'stone_classical',
           'int_marble': 'stone_classical', 'int_stone_dark': 'metal_dark',
           'int_pot': 'frame_bronze', 'int_white_gloss': 'frame_light',
           'int_brass': 'pole_metal', 'int_black': 'metal_dark'}
LEAFY = ('foliage', 'foliage_b', 'bark')


def _parts_into(mbs, parts, cx=0.0, cy=0.0, th=0.0, sc=1.0, z=0.0):
    """add a furniture kit's parts [(material, verts, faces, smooth)] to
    {material: MB}, scaled, turned by th about z and moved - Blender frame.
    Leaves get the per-vertex tint the street's foliage carries (darker low
    in the plant), or one untinted plant would strip it from every tree."""
    c, s_ = math.cos(th), math.sin(th)
    for (mname, vs, fs, smooth) in parts:
        mname = OUTDOOR.get(mname, mname)
        mb = mbs.setdefault(mname, MB())
        if mname in LEAFY and len(mb.col) < len(mb.v):
            mb.col.extend([(1.0, 1.0, 1.0)] * (len(mb.v) - len(mb.col)))
        zs = [v[2] for v in vs] or [0.0]
        z0, z1 = min(zs), max(zs)
        mb.add([(cx + (x * c - y * s_) * sc, cy + (x * s_ + y * c) * sc, z + zz * sc) for (x, y, zz) in vs],
               [tuple(f) for f in fs], smooth)
        if mname in LEAFY:
            for v in vs:
                k = 0.74 + 0.38 * ((v[2] - z0) / max(z1 - z0, 1e-6)) if mname != 'bark' else 1.0
                mb.col.append((k * 1.02, k, k * 0.94))


def _kit_mbs(name, mbs):
    return _kit(name, {('p%02d' % i): (mb, mname) for i, (mname, mb) in enumerate(sorted(mbs.items()))})


def _obox(mb, o, ex, ey, ez, sx, sy, sz):
    """a box on its own axes: corner o, unit axes ex ey ez, sizes"""
    def pt(a, b, c_):
        return tuple(o[i] + ex[i] * a + ey[i] * b + ez[i] * c_ for i in range(3))
    v = [pt(0, 0, 0), pt(sx, 0, 0), pt(sx, sy, 0), pt(0, sy, 0),
         pt(0, 0, sz), pt(sx, 0, sz), pt(sx, sy, sz), pt(0, sy, sz)]
    mb.add(v, [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)])


def kit_lounge():
    """An outdoor lounge: a three-seat sofa in pale canvas on an oak frame,
    a low table and two armchairs. Origin: the sofa's centre; it faces kit
    -y (turned by the placement)."""
    import furn_kit_living as FL
    mbs = {}
    _parts_into(mbs, FL.build('sofa', 2.2, 0.95, seed=3), 0.0, 0.0, -math.pi / 2)
    _parts_into(mbs, FL.build('table_coffee', 1.1, 0.6, seed=2), 0.0, -1.3, -math.pi / 2)
    _parts_into(mbs, FL.build('armchair', 0.82, 0.84, seed=1), -1.3, -1.35, 0.0)
    _parts_into(mbs, FL.build('armchair', 0.82, 0.84, seed=2), 1.3, -1.35, math.pi)
    return _kit_mbs('lounge', mbs)


def kit_dining():
    """the long table under the pergola: 2.4 m of oak on dark steel frames,
    a bench either side, a pot of herbs in the middle"""
    import furn_kit_plants as FP
    oak = MB(); st = MB()
    oak.box((-1.2, -0.45, 0.70), (1.2, 0.45, 0.75))
    for sx in (-0.95, 0.95):
        for sy in (-0.36, 0.36):
            st.box((sx - 0.03, sy - 0.03, 0.0), (sx + 0.03, sy + 0.03, 0.70), skip=('-z', '+z'))
        st.box((sx - 0.03, -0.36, 0.64), (sx + 0.03, 0.36, 0.70))
    for by in (-0.85, 0.85):
        for k in range(3):
            y0 = by - 0.17 + k * 0.118
            oak.box((-1.2, y0, 0.41), (1.2, y0 + 0.10, 0.45))
        for sx in (-0.95, 0.95):
            st.box((sx - 0.025, by - 0.15, 0.0), (sx + 0.025, by + 0.15, 0.41), skip=('-z',))
    mbs = {'int_wood_oak': oak, 'pole_metal': st}
    _parts_into(mbs, FP.build('decor_table_plant', 0.24, 0.24, seed=4), 0.0, 0.0, 0.0, 1.6, 0.75)
    return _kit_mbs('dining', mbs)


def kit_lounger():
    """A sun lounger: slatted oak on a low frame, the back raised, a canvas
    pad. Lies along kit y, head at +y (the plan's north)."""
    oak = MB(); pad = MB()
    W, L, h = 0.66, 1.95, 0.30
    hinge = 0.45                                   # where the back starts (kit y)
    for sx in (-W / 2, W / 2 - 0.05):
        oak.box((sx, -L / 2, h - 0.07), (sx + 0.05, L / 2, h))
        for sy in (-L / 2 + 0.12, L / 2 - 0.17):
            oak.box((sx, sy, 0.0), (sx + 0.05, sy + 0.05, h - 0.07), skip=('-z', '+z'))
    y = -L / 2
    while y < hinge - 0.08:
        oak.box((-W / 2, y, h), (W / 2, y + 0.085, h + 0.022))
        y += 0.105
    pad.box((-W / 2 + 0.03, -L / 2 + 0.03, h + 0.022), (W / 2 - 0.03, hinge - 0.01, h + 0.085))
    a = math.radians(32.0)
    ey = (0.0, math.cos(a), math.sin(a)); ez = (0.0, -math.sin(a), math.cos(a))
    _obox(oak, (-W / 2, hinge, h), (1, 0, 0), ey, ez, W, 0.82, 0.022)
    _obox(pad, (-W / 2 + 0.03, hinge, h + 0.022), (1, 0, 0), ey, ez, W - 0.06, 0.80, 0.063)
    oak.box((-W / 2, hinge + 0.50, h - 0.07), (-W / 2 + 0.04, hinge + 0.54, h + 0.33), skip=('-z',))
    oak.box((W / 2 - 0.04, hinge + 0.50, h - 0.07), (W / 2, hinge + 0.54, h + 0.33), skip=('-z',))
    kit = _kit('lounger', {'timber': (oak, 'int_wood_oak'), 'pad': (pad, 'canopy_fabric')})
    LB.bake_bevel(kit['timber'], 0.006)
    return kit


def kit_pot(kind, seed):
    import furn_kit_plants as FP
    w, d, prm = FP.KINDS[kind]['sizes']['L']
    mbs = {}
    _parts_into(mbs, FP.build(kind, w, d, seed=seed, **prm))
    return _kit_mbs('pot_' + kind, mbs)


def kit_shrub(seed, rad=0.42, n=230):
    """a clipped ball of leaves for the hedge and the planters"""
    r = random.Random(seed)
    mb = MB()
    for k in range(n):
        a_ = r.uniform(0, TAU); b_ = math.acos(r.uniform(-0.35, 1.0))
        rr = rad * r.uniform(0.72, 1.0)
        out = (math.sin(b_) * math.cos(a_), math.sin(b_) * math.sin(a_), math.cos(b_))
        p = (out[0] * rr, out[1] * rr, out[2] * rr * 0.85)
        vd = _tilt(out, r.uniform(0.5, 1.5), r.uniform(0, TAU))
        shade = 0.62 + 0.42 * (0.5 + 0.5 * out[2]) + 0.16 * r.random()
        leaf_blade(mb, p, vd, out, r.uniform(0.034, 0.052), r, 0, (shade * 1.02, shade, shade * 0.94))
    ob = mb.to_object('kit_shrub%d_leaves' % seed, M('foliage_b'), collection('kit'), shade_smooth_all=True)
    ob.hide_render = True; ob.hide_viewport = True
    return {'leaves': ob}


def kit_grass(seed, flowers=None):
    """An ornamental grass: arching blades from one crown; `flowers` (a
    material) tips a third of them with a small head, lavender fashion."""
    r = random.Random(seed)
    mb = MB(); fl = MB()
    for k in range(26):
        az = r.uniform(0, TAU); lean = r.uniform(0.10, 0.55)
        H = r.uniform(0.45, 0.80); wd = r.uniform(0.012, 0.020)
        dx, dy = math.cos(az), math.sin(az)
        px, py = -dy, dx
        pts = []
        for i in range(4):
            t = i / 3.0
            out = lean * H * t * t
            pts.append((dx * (0.04 + out), dy * (0.04 + out), H * t * (1.0 - 0.25 * lean * t)))
        o = len(mb.v)
        for i, p in enumerate(pts):
            w_ = wd * (1.0 - 0.8 * i / 3.0)
            mb.v.append((p[0] - px * w_, p[1] - py * w_, p[2])); mb.v.append((p[0] + px * w_, p[1] + py * w_, p[2]))
            sh = 0.70 + 0.45 * i / 3.0
            mb.col.extend([(sh * 1.04, sh, sh * 0.86)] * 2)
        for i in range(3):
            mb.f.append((o + 2 * i, o + 2 * i + 1, o + 2 * i + 3, o + 2 * i + 2))
        if flowers and k % 3 == 0:
            t = pts[-1]
            fl.box((t[0] - 0.022, t[1] - 0.022, t[2] - 0.01), (t[0] + 0.022, t[1] + 0.022, t[2] + 0.10))
    coll = collection('kit')
    out = {'blades': mb.to_object('kit_grass%d_blades' % seed, M('foliage'), coll, shade_smooth_all=True)}
    if flowers:
        out['flowers'] = fl.to_object('kit_grass%d_flowers' % seed, M(flowers), coll)
    for ob in out.values():
        ob.hide_render = True; ob.hide_viewport = True
    return out


def _put_s(kit, name, x, y, z, rot_deg, sc, coll):
    return [link_dup(src, '%s_%s' % (name, k), loc=P(x, y, z), rot_z=math.radians(rot_deg),
                     scale=(sc, sc, sc), coll=coll) for k, src in kit.items()]


def _rbox(mb, cx, cy, th, x0, y0, z0, x1, y1, z1, skip=()):
    """a box (x0..x1, y0..y1, z0..z1) turned by th about z, then moved to
    (cx, cy) - kit-local Blender coordinates"""
    c, s = math.cos(th), math.sin(th)
    o = len(mb.v)
    mb.box((x0, y0, z0), (x1, y1, z1), skip)
    for i in range(o, len(mb.v)):
        x, y, z = mb.v[i]
        mb.v[i] = (cx + x * c - y * s, cy + x * s + y * c, z)


def _kit(name, parts):
    """hide a kit's source objects; parts: {part: (MB, material)}"""
    coll = collection('kit')
    out = {}
    for k, (mb, mname) in parts.items():
        if mb.f:
            out[k] = mb.to_object('kit_%s_%s' % (name, k), M(mname), coll)
            out[k].hide_render = True
            out[k].hide_viewport = True
    return out


def _put(kit, name, x, y, rot_deg, coll, z=None):
    return [link_dup(src, '%s_%s' % (name, k), loc=P(x, y, PARK_TOP if z is None else z),
                     rot_z=math.radians(rot_deg), coll=coll) for k, src in kit.items()]


def kit_planter_bench(L):
    """A timber planter with a bench along its front (kit-local -y = the
    plan's +y, the promenade side) and pale end caps; soil 6 cm below the
    rim. Origin: the planter's centre on the deck."""
    oak = MB(); cap = MB(); soil = MB()
    h, D, rim = PLANTER_SOIL, 0.70, 0.06
    oak.box((-L / 2, -D, 0.0), (L / 2, D, h), skip=('+z', '-z'))
    for (x0, y0, x1, y1) in ((-L / 2, -D, L / 2, -D + rim), (-L / 2, D - rim, L / 2, D),
                             (-L / 2, -D + rim, -L / 2 + rim, D - rim),
                             (L / 2 - rim, -D + rim, L / 2, D - rim)):
        oak.box((x0, y0, h), (x1, y1, h + 0.06), skip=('-z',))
    soil.plane_xy(-L / 2 + rim, -D + rim, L / 2 - rim, D - rim, h)
    # the bench: a slatted top on a recessed timber plinth
    oak.box((-L / 2 + 0.10, -D - 0.40, 0.0), (L / 2 - 0.10, -D, 0.40), skip=('-z',))
    for k in range(4):
        y0 = -D - 0.46 + k * 0.115
        oak.box((-L / 2 + 0.06, y0, 0.40), (L / 2 - 0.06, y0 + 0.095, 0.45), skip=('-z',))
    for sx in (-1, 1):
        x0, x1 = sorted((sx * L / 2, sx * (L / 2 + 0.08)))
        cap.box((x0, -D - 0.46, 0.0), (x1, D, h + 0.08), skip=('-z',))
    kit = _kit('planter%d' % int(L * 10), {'timber': (oak, 'int_wood_oak'), 'cap': (cap, 'stone_classical'),
                                             'soil': (soil, 'soil')})
    LB.bake_bevel(kit['timber'], 0.008)
    return kit


def kit_tub():
    """a square timber tub for a tree, 1.6 m, same rim and soil"""
    oak = MB(); soil = MB()
    a, h = 0.8, PLANTER_SOIL
    oak.box((-a, -a, 0.0), (a, a, h), skip=('+z', '-z'))
    for (x0, y0, x1, y1) in ((-a, -a, a, -a + 0.06), (-a, a - 0.06, a, a),
                             (-a, -a + 0.06, -a + 0.06, a - 0.06), (a - 0.06, -a + 0.06, a, a - 0.06)):
        oak.box((x0, y0, h), (x1, y1, h + 0.06), skip=('-z',))
    soil.plane_xy(-a + 0.06, -a + 0.06, a - 0.06, a - 0.06, h)
    kit = _kit('tub', {'timber': (oak, 'int_wood_oak'), 'soil': (soil, 'soil')})
    LB.bake_bevel(kit['timber'], 0.008)
    return kit


def kit_cafe():
    """One cafe set: a 4 m butterfly umbrella (white fabric folded in eight,
    the edges high and the centre low on its mast, white struts under it), two
    round tables and six chairs - rattan-coloured timber, one in red. Origin:
    the mast's foot; the tables sit 1.05 m either side of it along kit x."""
    fab = MB(); white = MB(); oak = MB(); red = MB(); metal = MB()
    S, hc, hm, h0 = 2.0, 3.20, 2.92, 2.62
    C = (0.0, 0.0, h0)
    corners = []
    for k in range(4):
        a = math.pi / 2 * k
        ca, sa = math.cos(a), math.sin(a)
        corners.append((S * (ca - sa), S * (sa + ca), hc))
    ring = []
    for k in range(4):
        p, q = corners[k], corners[(k + 1) % 4]
        ring.append(p)
        ring.append(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, hm))   # the edge's middle dips
    for k in range(8):
        fab.add([C, ring[k], ring[(k + 1) % 8]], [(0, 1, 2)])
    white.cyl((0, 0, 0.06), (0, 0, h0 + 0.05), 0.04, seg=8)
    for k in range(0, 8, 2):
        p = ring[k]
        white.cyl((0, 0, 2.05), (p[0] * 0.95, p[1] * 0.95, p[2] - 0.05), 0.017, seg=4, caps=False)
    metal.box((-0.28, -0.28, 0.0), (0.28, 0.28, 0.06), skip=('-z',))
    import furn_kit_living as FL
    mbs = {'int_wood_oak': oak, 'int_accent_red': red, 'pole_metal': metal}
    for tx in (-1.05, 1.05):
        _parts_into(mbs, FL.build('table_round', 0.84, 0.84, seed=1), tx, 0.0)
        chairs = [(tx, -0.78, 0.0), (tx, 0.78, math.pi), (tx + (0.78 if tx > 0 else -0.78), 0.0,
                                                         math.pi / 2 if tx > 0 else -math.pi / 2)]
        for j, (cx, cy, th) in enumerate(chairs):
            parts = FL.build('chair', 0.45, 0.50, seed=j)
            if tx > 0 and j == 2:                  # one in red, as the render has it
                parts = [('int_accent_red' if m_ != 'int_wood_oak' else m_, v_, f_, s_) for (m_, v_, f_, s_) in parts]
            _parts_into(mbs, parts, cx, cy, th + math.pi / 2)
    extra = {('x%02d' % i): (mb_, mn_) for i, (mn_, mb_) in enumerate(sorted(mbs.items()))
             if mn_ not in ('int_wood_oak', 'int_accent_red', 'pole_metal') and mb_.f}
    d = {'fabric': (fab, 'canopy_fabric'), 'mast': (white, 'frame_light'),
         'timber': (oak, 'int_wood_oak'), 'red': (red, 'int_accent_red'),
         'metal': (metal, 'pole_metal')}
    d.update(extra)
    return _kit('cafe', d)


def kit_pergola():
    """3.8 x 2.8 m: dark posts and beams, timber slats across"""
    frame = MB(); slat = MB()
    for (dx, dy) in ((-1.85, -1.35), (1.85, -1.35), (-1.85, 1.35), (1.85, 1.35)):
        frame.box((dx - 0.05, dy - 0.05, 0.0), (dx + 0.05, dy + 0.05, 2.62), skip=('-z',))
    for dy in (-1.35, 1.35):
        frame.box((-1.95, dy - 0.05, 2.50), (1.95, dy + 0.05, 2.62))
    for k in range(10):
        x = -1.80 + k * 0.40
        slat.box((x - 0.025, -1.50, 2.62), (x + 0.025, 1.50, 2.72), skip=('-z',))
    return _kit('pergola', {'frame': (frame, 'pole_metal'), 'slats': (slat, 'int_wood_oak')})


def build_terrace():
    coll = collection('terrace')
    sail = MB(); poles = MB(); plant = MB(); foli = MB(); rail = MB()
    lawn = MB(); chan = MB(); grate = MB()
    r = random.Random(4801)
    kits = {}
    for i, (x, y, L) in enumerate(PLANTERS):
        if ('pl', L) not in kits:
            kits[('pl', L)] = kit_planter_bench(L)
        k = kits[('pl', L)]
        _put(k, 'terrace_planter%02d' % (i + 1), x, y, 0.0, coll)
    tub = kit_tub()
    for i, (x, y) in enumerate(PLANTERS_S):
        _put(tub, 'terrace_tub%02d' % (i + 1), x, y, 0.0, coll)
    cafe = kit_cafe()
    for i, (x, y, rot) in enumerate(CAFES):
        _put(cafe, 'terrace_cafe%02d' % (i + 1), x, y, rot, coll)
    perg = kit_pergola()
    for i, (x, y) in enumerate(PERGOLAS):
        _put(perg, 'terrace_pergola%02d' % (i + 1), x, y, 0.0, coll)
    # the planting in the planter-benches round each tree: clipped balls,
    # grasses and lavender, and a clipped hedge along the parapet box
    shrubs = [kit_shrub(s_) for s_ in (71, 72, 73)]
    grass = [kit_grass(81), kit_grass(82, 'int_accent_red'), kit_grass(83, 'canopy_fabric')]
    rp_ = random.Random(4811)
    n_ = 0
    for (x, y, L) in PLANTERS:
        for dx in (-2.1, -1.55, -1.0, 1.0, 1.55, 2.1):
            for dy in (-0.32, 0.30):
                n_ += 1
                px, py = x + dx + rp_.uniform(-0.12, 0.12), y + dy + rp_.uniform(-0.1, 0.1)
                if (n_ + (dy > 0)) % 3 == 0:
                    _put_s(shrubs[n_ % 3], 'terrace_shrub%03d' % n_, px, py, PARK_TOP + PLANTER_SOIL + 0.16,
                           rp_.uniform(0, 360), rp_.uniform(0.62, 0.85), coll)
                else:
                    _put_s(grass[n_ % 3], 'terrace_grass%03d' % n_, px, py, PARK_TOP + PLANTER_SOIL,
                           rp_.uniform(0, 360), rp_.uniform(0.85, 1.25), coll)
    for (x, y) in PLANTERS_S:
        for (dx, dy) in ((-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5)):
            n_ += 1
            _put_s(grass[n_ % 3], 'terrace_grass%03d' % n_, x + dx, y + dy, PARK_TOP + PLANTER_SOIL,
                   rp_.uniform(0, 360), rp_.uniform(0.9, 1.2), coll)
    # the furniture
    lounge = kit_lounge()
    for i, (x, y, f) in enumerate(LOUNGES):
        _put(lounge, 'terrace_lounge%02d' % (i + 1), x, y, 0.0 if f > 0 else 180.0, coll,
             z=PARK_TOP + (0.03 if y < 23 else 0.0))
    _put(kit_dining(), 'terrace_dining01', DINING[0], DINING[1], 0.0, coll, z=PARK_TOP + 0.03)
    lng = kit_lounger()
    for i, (x, y) in enumerate(LOUNGERS):
        _put(lng, 'terrace_lounger%02d' % (i + 1), x, y, 0.0, coll, z=PARK_TOP + 0.03)
    pots = {}
    for i, (kind, x, y, sc) in enumerate(POTS):
        if kind not in pots:
            pots[kind] = kit_pot(kind, 5 + len(pots))
        _put_s(pots[kind], 'terrace_pot%02d' % (i + 1), x, y, PARK_TOP, rp_.uniform(0, 360), sc, coll)
    # timber decks, the promenade's stone bands, bollard lights, festoons
    deck = MB(); band = MB(); post = MB(); glow = MB()
    for (x0, y0, x1, y1) in DECKS:
        pbox(deck, x0, y0, PARK_TOP, x1, y1, PARK_TOP + 0.03)
    for yb in (23.85, 28.45):
        pbox(band, 1.4, yb, PARK_TOP, 61.5, yb + 0.25, PARK_TOP + 0.006)
    xb = 3.25
    while xb < 61.0:
        pbox(band, xb, 24.1, PARK_TOP, xb + 0.3, 28.45, PARK_TOP + 0.006)
        xb += 5.75
    for (x, y) in BOLLARDS:
        post.cyl(P(x, y, PARK_TOP), P(x, y, PARK_TOP + 0.62), 0.055, seg=10, caps=False)
        glow.cyl(P(x, y, PARK_TOP + 0.62), P(x, y, PARK_TOP + 0.74), 0.050, seg=10, caps=False)
        post.cyl(P(x, y, PARK_TOP + 0.74), P(x, y, PARK_TOP + 0.80), 0.07, seg=10)
    for loop in FESTOONS:
        for (x, y) in loop:
            post.cyl(P(x, y, PARK_TOP), P(x, y, PARK_TOP + FESTOON_H + 0.05), 0.04, 0.03, seg=8)
        for k in range(len(loop)):
            (xa, ya), (xb_, yb_) = loop[k], loop[(k + 1) % len(loop)]
            Ln = math.hypot(xb_ - xa, yb_ - ya)
            nseg = max(6, int(Ln / 0.6))
            sag = min(0.55, 0.035 * Ln)
            prev = None
            for q in range(nseg + 1):
                t = q / nseg
                pt = P(xa + (xb_ - xa) * t, ya + (yb_ - ya) * t,
                       PARK_TOP + FESTOON_H - sag * 4.0 * t * (1.0 - t))
                if prev is not None:
                    post.cyl(prev, pt, 0.007, seg=3, caps=False)
                    if q < nseg:
                        glow.sphere((pt[0], pt[1], pt[2] - 0.06), 0.045, seg=6, rings=4)
                prev = pt
    deck.to_object('terrace_deck_timber', M('int_wood_oak'), coll)
    band.to_object('terrace_paving_bands', M('stone_classical'), coll)
    post.to_object('terrace_light_posts', M('pole_metal'), coll)
    glow.to_object('terrace_lights', M('glass_lit'), coll)
    # lawn strips between the planters, 3 cm proud of the paving
    for (x0, y0, x1, y1) in LAWNS:
        pbox(lawn, x0, y0, PARK_TOP, x1, y1, PARK_TOP + 0.03)
    # the drainage channel: a dark slot under a cast grating, flush-ish (the
    # deck has no recess; 8-12 mm proud so it holds at 100 m)
    cx0, cx1, cy = CHANNEL
    pbox(chan, cx0, cy - 0.11, PARK_TOP, cx1, cy + 0.11, PARK_TOP + 0.008)
    for yy in (cy - 0.13, cy + 0.11):
        pbox(grate, cx0, yy, PARK_TOP, cx1, yy + 0.02, PARK_TOP + 0.012)
    x = cx0 + 0.07
    while x < cx1 - 0.05:
        pbox(grate, x, cy - 0.11, PARK_TOP + 0.004, x + 0.04, cy + 0.11, PARK_TOP + 0.012)
        x += 0.15
    # shade sails: a tensioned triangle (its middle dropped a little) on
    # three masts of different heights
    for tri in SAILS:
        pts = [P(px, py, PARK_TOP + z) for ((px, py), z) in tri]
        m = tuple(sum(p[i] for p in pts) / 3.0 for i in range(3))
        m = (m[0], m[1], m[2] - 0.22)
        for k in range(3):
            sail.add([m, pts[k], pts[(k + 1) % 3]], [(0, 1, 2)])
        for ((px, py), z) in tri:
            poles.cyl(P(px, py, PARK_TOP), P(px, py, PARK_TOP + z + 0.15), 0.055, 0.045, seg=8)
    # hedge along the parapet on the south and west sides
    hedge_runs = [((0.6, 35.6), (61.2, 35.6)), ((0.6, 18.9), (0.6, 35.6))]
    for (a, b) in hedge_runs:
        if abs(a[1] - b[1]) < 1e-3:
            pbox(plant, a[0], a[1] - 0.45, PARK_TOP, b[0], a[1] + 0.45, PARK_TOP + 0.75)
        else:
            pbox(plant, a[0] - 0.45, a[1], PARK_TOP, a[0] + 0.45, b[1], PARK_TOP + 0.75)
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        s = 0.55
        while s < L - 0.3:
            cx = a[0] + (b[0] - a[0]) * s / L; cy = a[1] + (b[1] - a[1]) * s / L
            n_ += 1
            _put_s(shrubs[n_ % 3], 'terrace_hedge%03d' % n_, cx, cy, PARK_TOP + 0.75 + 0.14,
                   r.uniform(0, 360), r.uniform(1.0, 1.22), coll)
            s += 0.74
    # a thin rail on the parapet
    for (a, b) in (((-0.15, 36.35), (61.85, 36.35)), ((0.05, 18.3), (0.05, 36.35))):
        if abs(a[1] - b[1]) < 1e-3:
            pbox(rail, a[0], a[1] - 0.18, PARAPET_TOP + 0.31, b[0], a[1] - 0.14, PARAPET_TOP + 0.35)
            x = a[0] + 1.0
            while x < b[0]:
                pbox(rail, x - 0.02, a[1] - 0.18, PARAPET_TOP, x + 0.02, a[1] - 0.14, PARAPET_TOP + 0.31)
                x += 2.0
        else:
            pbox(rail, a[0] + 0.14, a[1], PARAPET_TOP + 0.31, a[0] + 0.18, b[1], PARAPET_TOP + 0.35)
            y = a[1] + 1.0
            while y < b[1]:
                pbox(rail, a[0] + 0.14, y - 0.02, PARAPET_TOP, a[0] + 0.18, y + 0.02, PARAPET_TOP + 0.31)
                y += 2.0
    # the stair head where the street stair arrives on the deck (p-03,
    # 14.8 m2): a hollow house round the hole in the deck, its door where the
    # interior hangs the leaf (L01 d12 since build 3, hinge (19.40, 29.05), 1.39 wide), pale
    # inside so the climb out of the podium is not into a black box
    pv = MB(); pl = MB()
    hx0, hy0, hx1, hy1 = STAIR_HOLE
    T, Hh = 0.20, 2.75
    z0, z1 = DECK_Z0, PARK_TOP + Hh
    dx0, dx1 = STAIR_DOOR
    pbox(pv, hx0 - T, hy0 - T, z0, dx0, hy0, z1)                    # north, west of the door
    pbox(pv, dx1, hy0 - T, z0, hx1 + T, hy0, z1)                    # ...east of it
    pbox(pv, dx0, hy0 - T, PARK_TOP + DOOR_H, dx1, hy0, z1)         # ...over its head
    pbox(pv, hx0 - T, hy1, z0, hx1 + T, hy1 + T, z1)                # south
    pbox(pv, hx0 - T, hy0, z0, hx0, hy1, z1)                        # west
    pbox(pv, hx1, hy0, z0, hx1 + T, hy1, z1)                        # east
    pbox(pv, hx0 - T - 0.08, hy0 - T - 0.08, z1, hx1 + T + 0.08, hy1 + T + 0.08, z1 + 0.18)
    # the lining: a pale skin 1 cm inside the house, and its ceiling
    e = 0.01
    pbox(pl, hx0, hy0, PARK_TOP, hx0 + e, hy1, z1)
    pbox(pl, hx1 - e, hy0, PARK_TOP, hx1, hy1, z1)
    pbox(pl, hx0, hy1 - e, PARK_TOP, hx1, hy1, z1)
    pbox(pl, hx0, hy0, PARK_TOP, dx0, hy0 + e, z1)
    pbox(pl, dx1, hy0, PARK_TOP, hx1, hy0 + e, z1)
    pbox(pl, dx0, hy0, PARK_TOP + DOOR_H, dx1, hy0 + e, z1)
    pbox(pl, hx0, hy0, z1 - e, hx1, hy1, z1)
    pv.to_object('terrace_stairhouse', M('plaster_dark'), coll)
    pl.to_object('terrace_stairhouse_lining', M('concrete_podium'), coll)
    sail.to_object('terrace_sails', M('canopy_fabric'), coll)
    poles.to_object('terrace_frames', M('pole_metal'), coll)
    plant.to_object('terrace_planters', M('concrete_podium'), coll)
    lawn.to_object('terrace_lawn', M('grass'), coll)
    chan.to_object('terrace_channel', M('reveal_dark'), coll)
    grate.to_object('terrace_channel_grate', M('metal_dark'), coll)
    rail.to_object('terrace_rail', M('metal_dark'), coll)
    if foli.f:
        foli.to_object('terrace_foliage', M('foliage_b'), coll, shade_smooth_all=True)
    return coll


def text_obj(coll, body, x, y, n, z, size, matname, extrude=0.035, track=1.0,
             name=None, off=0.03):
    """Upright extruded text centred on plan (x, y), facing the plan normal n,
    its baseline at z."""
    cu = bpy.data.curves.new('t', type='FONT')
    cu.body = body
    cu.size = size
    cu.extrude = extrude
    cu.space_character = track
    cu.align_x = 'CENTER'
    ob = bpy.data.objects.new(name or ('sign_' + body[:9]), cu)
    bx, by = x + n[0] * off, -(y + n[1] * off)
    ob.location = (bx, by, z)
    nB = (n[0], -n[1])
    ob.rotation_euler = (math.pi / 2, 0, math.atan2(nB[0], -nB[1]))
    ob.data.materials.append(M(matname))
    coll.objects.link(ob)
    return ob


def build_signage():
    """Shop signs on the podium's sign band, where the renders have them:
    PUBLIC MARKET over g..d and l..m, Sonny's over T..i on the street face,
    PUBLIC MARKET and Sonny's on the west face (002)."""
    coll = collection('signage')

    def text_obj_(body, x, y, n, z, size, matname, extrude=0.035, track=1.0):
        return text_obj(coll, body, x, y, n, z, size, matname, extrude, track)
    S = (0.0, 1.0); W = (-1.0, 0.0)
    yS = 36.55; xW = -0.25
    text_obj_('PUBLIC', 15.75, yS, S, 5.15, 0.60, 'neon_orange', track=1.55)
    text_obj_('MARKET', 15.75, yS, S, 4.50, 0.60, 'neon_orange', track=1.55)
    text_obj_("Sonny's", 41.0, yS, S, 4.55, 1.10, 'sign_metal', 0.05)
    # DINER over the narrow e..z front (006: a red box, white letters). The
    # red is the interiors' accent red - an existing name, so materials.js is
    # untouched; pale letters in the gable-slot frame paint, standing proud
    xd = 29.2
    bx = MB()
    pbox(bx, xd - 1.25, yS, 4.55, xd + 1.25, yS + 0.14, 5.35)
    bx.to_object('sign_diner_box', M('int_accent_red'), coll)
    t = text_obj_('DINER', xd, yS + 0.14, S, 4.73, 0.56, 'frame_light', 0.03, track=1.2)
    t.name = 'sign_DINER'
    text_obj_('PUBLIC', 54.15, yS, S, 5.15, 0.50, 'neon_orange', track=1.55)
    text_obj_('MARKET', 54.15, yS, S, 4.50, 0.50, 'neon_orange', track=1.55)
    # 002, west face: PUBLIC MARKET over the first shopfront south of the
    # bar (L00 run y 18.25..22.30), Sonny's over the one by the SW corner
    # (29.61..34.30) - they stood the other way round
    text_obj_('PUBLIC', xW, 20.28, W, 5.15, 0.60, 'neon_orange', track=1.55)
    text_obj_('MARKET', xW, 20.28, W, 4.50, 0.60, 'neon_orange', track=1.55)
    text_obj_("Sonny's", xW, 31.95, W, 4.55, 1.20, 'sign_metal', 0.06)
    return coll


# ------------------------------------------------------------------ street, forecourt
def _merge_rects(grid, x0, y0, cell):
    """greedy rectangles over a boolean grid (rows = y, cols = x)"""
    import numpy as np
    g = grid.copy()
    out = []
    H, W = g.shape
    for j in range(H):
        i = 0
        while i < W:
            if not g[j, i]:
                i += 1
                continue
            k = i
            while k < W and g[j, k]:
                k += 1
            # grow down while the whole run is set
            jj = j + 1
            while jj < H and g[jj, i:k].all():
                jj += 1
            g[j:jj, i:k] = False
            out.append((x0 + i * cell, y0 + j * cell, x0 + k * cell, y0 + jj * cell))
            i = k
    return out


def build_street():
    """Four streets round the block (the renders have zebras at all four
    corners; the south one is the shopfront street), the forecourt inside the
    site line: pavements, the parking the +0.000 sheet draws (45-degree bays
    on the south and north, square bays on the west), the ramp's driveway."""
    import numpy as np
    coll = collection('street')
    road = MB(); walk = MB(); lot = MB(); paint = MB()
    for i in range(len(XB) - 1):
        for j in range(len(YB) - 1):
            x0, x1 = XB[i], XB[i + 1]; y0, y1 = YB[j], YB[j + 1]
            if i % 2 or j % 2:
                road.add([P(x0, y0, ROAD_Z), P(x1, y0, ROAD_Z), P(x1, y1, ROAD_Z), P(x0, y1, ROAD_Z)],
                         [(0, 3, 2, 1)])
            elif (x0, y0) == (ROAD_W[1], ROAD_N[1]):
                continue                                  # the site: below
            else:
                # every other cell is paved kerb to kerb; lib_hood lays the
                # park, the courtyards and the lawns over it
                pbox(walk, x0, y0, -0.5, x1, y1, 0.0)
    # the site block: 0.25 m raster of surface kinds, merged into boxes
    sx0, sx1, sy0, sy1 = ROAD_W[1], ROAD_E[0], ROAD_N[1], ROAD_S[0]
    cell = 0.25
    xs = np.arange(sx0 + cell / 2, sx1, cell)
    ys = np.arange(sy0 + cell / 2, sy1, cell)
    X, Y = np.meshgrid(xs, ys)
    kind = np.ones(X.shape, dtype=np.int8)        # 1 pavement, 2 asphalt, 0 nothing

    def poly_mask(poly):
        poly = list(poly)
        c = np.zeros(X.shape, dtype=bool)
        n = len(poly)
        for k in range(n):
            xi, yi = poly[k]; xj, yj = poly[k - 1]
            cond = (yi > Y) != (yj > Y)
            with np.errstate(divide='ignore', invalid='ignore'):
                xint = (xj - xi) * (Y - yi) / ((yj - yi) if yj != yi else 1e-12) + xi
            c ^= cond & (X < xint)
        return c

    def rect(x0, y0, x1, y1):
        return (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)
    # parking and driveways
    kind[rect(-6.0, 38.5, 76.5, 47.5)] = 2                # south lot + aisle
    kind[rect(76.5, 36.55, 82.55, 53.0)] = 2              # ramp driveway
    kind[rect(-20.0, -4.2, -6.0, 47.5)] = 2               # west lot
    kind[rect(-20.0, 47.5, -13.0, 53.0)] = 2              # its exit
    kind[rect(-20.0, -11.5, 83.0, -2.25)] = 2             # north lot
    kind[rect(83.0, -11.5, 88.0, -6.0)] = 2               # its exit to the east street
    kind[poly_mask(_podium_outline())] = 0
    kind[rect(76.5, 21.9, 82.6, 36.6)] = 0                # the ramp passage
    for k, mat_, top in ((1, walk, 0.0), (2, lot, LOT_Z)):
        for (x0, y0, x1, y1) in _merge_rects(kind == k, sx0, sy0, cell):
            pbox(mat_, x0, y0, -0.5, x1, y1, top)
    # lane markings: a dashed centre line, broken at every junction
    for (bands, cross, span, horiz) in ((ROADS_Y, ROADS_X, (XB[0], XB[-1]), True),
                                        (ROADS_X, ROADS_Y, (YB[0], YB[-1]), False)):
        for a in bands:
            mid = 0.5 * (a[0] + a[1])
            s = span[0]
            while s < span[1]:
                if not any(cb[0] - 6 < s < cb[1] + 6 for cb in cross):
                    if horiz:
                        pbox(paint, s, mid - 0.075, ROAD_Z + 0.004, s + 3.0, mid + 0.075, ROAD_Z + 0.006)
                    else:
                        pbox(paint, mid - 0.075, s, ROAD_Z + 0.004, mid + 0.075, s + 3.0, ROAD_Z + 0.006)
                s += 9.0
    # zebras on all four arms of every junction
    for rx in ROADS_X:
        for ry in ROADS_Y:
            for (yy0, yy1) in ((ry[0] - 5.5, ry[0] - 1.0), (ry[1] + 1.0, ry[1] + 5.5)):
                x = rx[0] + 0.6
                while x < rx[1] - 1.0:
                    pbox(paint, x, yy0, ROAD_Z + 0.004, x + 1.2, yy1, ROAD_Z + 0.006)
                    x += 2.4
            for (xx0, xx1) in ((rx[0] - 5.5, rx[0] - 1.0), (rx[1] + 1.0, rx[1] + 5.5)):
                y = ry[0] + 0.6
                while y < ry[1] - 1.0:
                    pbox(paint, xx0, y, ROAD_Z + 0.004, xx1, y + 1.2, ROAD_Z + 0.006)
                    y += 2.4
    # parking bays: the two long sides of every car glyph on the sheet
    for sp in LEV['L00'].get('parking_spaces', []):
        gq = sp['glyph']
        sides = sorted(((gq[k], gq[(k + 1) % 4]) for k in range(4)),
                       key=lambda e: -math.hypot(e[1][0] - e[0][0], e[1][1] - e[0][1]))[:2]
        for (a, b) in sides:
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy) or 1
            nx, ny = -dy / L * 0.06, dx / L * 0.06
            z = LOT_Z + 0.005
            paint.add([P(a[0] - nx, a[1] - ny, z), P(b[0] - nx, b[1] - ny, z),
                       P(b[0] + nx, b[1] + ny, z), P(a[0] + nx, a[1] + ny, z)], [(0, 3, 2, 1)])
    road.to_object('road', M('asphalt'), coll)
    lot.to_object('forecourt_lot', M('asphalt'), coll)
    walk.to_object('pavement', M('sidewalk'), coll)
    paint.to_object('road_markings', M('road_paint'), coll)
    # street lighting columns along the shopfront pavement and the far side
    pole = MB()
    for x in range(-24, 86, 18):
        # one row, on the shop side: a far row stood between the page's rail
        # and the building, and its metal arms caught the sun into bloom
        for (y, dirn) in ((ROAD_S[0] - 0.8, 1),):
            pole.cyl(P(x, y, 0.0), P(x, y, 8.6), 0.10, 0.07, seg=8)
            pole.cyl(P(x, y, 8.6), P(x, y + dirn * 2.8, 8.9), 0.07, 0.06, seg=8)
            pbox(pole, x - 0.22, y + dirn * 2.6 - 0.4, 8.72, x + 0.22, y + dirn * 2.6 + 0.4, 8.90)
    pole.to_object('street_lights', M('pole_metal'), coll)
    return coll


# ------------------------------------------------------------------ planting
GOLDEN = math.radians(137.507)      # the divergence angle of a leaf spiral


def _nrm(v):
    L = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / L, v[1] / L, v[2] / L) if L > 1e-9 else (0.0, 0.0, 1.0)


def _crs(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _frame(d):
    """Any two unit vectors perpendicular to d."""
    up = (0.0, 0.0, 1.0) if abs(d[2]) < 0.95 else (1.0, 0.0, 0.0)
    t1 = _nrm(_crs(d, up))
    return t1, _crs(d, t1)


def _tilt(d, ang, az):
    """d rotated away from itself by `ang`, in the direction `az` around it."""
    t1, t2 = _frame(d)
    c, s = math.cos(ang), math.sin(ang)
    ca, sa = math.cos(az), math.sin(az)
    off = (t1[0] * ca + t2[0] * sa, t1[1] * ca + t2[1] * sa, t1[2] * ca + t2[2] * sa)
    return _nrm((d[0] * c + off[0] * s, d[1] * c + off[1] * s, d[2] * c + off[2] * s))


def _perp(want, axis):
    """`want` with its component along `axis` removed - the blade normal has to
    be perpendicular to the blade, but we want it as close to the light as the
    blade's own direction allows."""
    k = _dot(want, axis)
    o = (want[0] - axis[0] * k, want[1] - axis[1] * k, want[2] - axis[2] * k)
    return _nrm(o) if (o[0] * o[0] + o[1] * o[1] + o[2] * o[2]) > 1e-8 else _frame(axis)[0]


def leaf_blade(mb, base, vdir, ndir, s, r, detail=0, tint=None):
    """One leaf, attached at `base`, running along `vdir`, blade facing `ndir`.

    A flat quad reads as a green chip. What makes foliage read as leaves is the
    pointed tip, the shoulder about a third of the way up, and the fold along
    the midrib that leaves the two halves at different angles, so one side
    catches the sun while the other stays in shade. All three come for the
    price of the rectangle they replace: four verts whose quad is deliberately
    NON-PLANAR, so triangulating it along the base-to-tip diagonal puts the
    crease exactly on the midrib. detail=1 adds a second pair of shoulders and
    a petiole, for the leaves near enough to read an outline.

    Proportions are off the foreground branch in the photograph: a broad lime
    leaf about four fifths as wide as it is long, blunt rather than spiky. The
    blade is attached at its base and droops under its own weight toward world
    -Z, which is what makes a canopy hang rather than bristle.
    """
    L = s * 2.90                       # petiole base to tip
    W = s * 1.16                       # half width at the widest point
    fold = s * 0.30                    # depth of the midrib crease
    droop = s * 0.80                   # gravity sag at the tip
    t0 = 0.26 if detail else 0.16      # blade starts here; before it, petiole
    v = _nrm(vdir)
    n = _perp(ndir, v)
    u = _crs(v, n)

    def P(du, t, fd):
        d = L * t
        g = -droop * max(0.0, (t - t0) / (1.0 - t0)) ** 2
        return (base[0] + u[0] * du + v[0] * d + n[0] * fd,
                base[1] + u[1] * du + v[1] * d + n[1] * fd,
                base[2] + u[2] * du + v[2] * d + n[2] * fd + g)

    o = len(mb.v)
    if detail:
        pw = s * 0.055                 # petiole half width
        mb.v.extend([P(-pw, 0.0, 0.0), P(pw, 0.0, 0.0),            # 0 1 stalk
                     P(0, t0, 0.0),                                 # 2 blade base
                     P(-W, t0 + 0.30, -fold), P(W, t0 + 0.30, -fold),
                     P(0, t0 + 0.30, 0.0),                          # 5 midrib
                     P(-W * 0.84, t0 + 0.62, -fold * 0.84),
                     P(W * 0.84, t0 + 0.62, -fold * 0.84),
                     P(0, t0 + 0.62, 0.0),                          # 8 midrib
                     P(0, 1.0, 0.0)])                               # 9 tip
        # wound so the geometric front face is the side turned to the light;
        # the material keys the pale matt underside off that
        for f in ((2, 1, 0),
                  (5, 3, 2), (5, 8, 6, 3), (8, 9, 6),
                  (4, 5, 2), (4, 7, 8, 5), (7, 9, 8)):
            mb.f.append(tuple(o + k for k in f))
    else:
        # base - shoulder - tip - shoulder, creasing along the base/tip diagonal
        mb.v.extend([P(0, t0, 0.0), P(-W, t0 + 0.40, -fold),
                     P(0, 1.0, 0.0), P(W, t0 + 0.40, -fold)])
        mb.f.append((o, o + 3, o + 2, o + 1))
    if tint is None:
        tint = (1.0, 1.0, 1.0)
    mb.col.extend([tint] * (len(mb.v) - o))


def leaf_shoot(mb, p0, dirv, length, n_leaf, size, r, detail, light, tintf):
    """A terminal shoot: leaves set along a twig on a golden-angle spiral.

    This is the part that decides whether a canopy reads as a tree or as green
    fog. Leaves do not float in a cloud around a branch - they sit on shoots,
    in a spiral, at a regular spacing, and they turn their blades to the sky.
    Scattering them through a sphere gives an even density with no structure;
    running them along shoots gives the clumps and the gaps between clumps that
    a real crown is made of.
    """
    phase = r.uniform(0, TAU)
    for i in range(n_leaf):
        t = (i + 0.55) / n_leaf
        att = (p0[0] + dirv[0] * length * t,
               p0[1] + dirv[1] * length * t,
               p0[2] + dirv[2] * length * t)
        az = phase + i * GOLDEN
        # the blade swings out from the shoot, a little more at the base
        out = r.uniform(1.00, 1.38) - 0.22 * t
        vd = _tilt(dirv, out, az)
        # light seeking: present the blade to the sky, as far as its own
        # direction allows, with a little randomness so they are not a deck
        want = (light[0] + r.uniform(-0.35, 0.35),
                light[1] + r.uniform(-0.35, 0.35),
                light[2] + r.uniform(-0.15, 0.25))
        nd = _perp(want, vd)
        leaf_blade(mb, att, vd, nd, size * r.uniform(0.80, 1.18), r,
                   detail, tintf(att))


def leaf_tinter(z0, z1, cx, cy, crad, r, kd=0.62):
    """Per-leaf light, baked into the mesh as a vertex colour.

    This is the only self-shadowing the canopy ever gets. The shadow map
    covers a 420 m frustum, so one texel lands on 10 cm: a leaf casts about
    four of them and the inside of a crown comes back as bright as its
    skin. That one fact is what makes rendered foliage read as a heap of
    green chips rather than as a tree - a real crown runs five to one
    between the leaves in the sun and the leaves two layers in, and it is
    that range, not the green, that the eye reads as mass.

    So the tint is not a gradient picked to look right, it is an optical
    depth. The crown is taken as the ellipsoid its tips describe, the leaf
    is traced out of it toward the sun and again toward the zenith, and
    each ray is attenuated by the leaf area it has to pass: exp( -kd * d ),
    with d in metres. Sun leaves come out lighter, yellower and slightly
    scorched; the ones in the core go dark and blue, because all they ever
    see is sky through foliage.
    """
    zc = 0.5 * (z0 + z1)
    zr = max(0.5 * (z1 - z0), 0.35)
    cr = max(crad, 0.35)
    rm = (2.0 * cr + zr) / 3.0                 # mean radius, for metres
    # Blender Z-up, matching `light` in the generators: up, leaning into sun
    sun_d = _nrm((0.30, -0.18, 1.0))
    sun_e = (sun_d[0] / cr, sun_d[1] / cr, sun_d[2] / zr)
    sky_e = (0.0, 0.0, 1.0 / zr)

    def _exit(e, d):
        """How far out of the unit sphere `e` is, along `d`."""
        a = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        b = 2.0 * (e[0] * d[0] + e[1] * d[1] + e[2] * d[2])
        c = e[0] * e[0] + e[1] * e[1] + e[2] * e[2] - 1.0
        disc = b * b - 4.0 * a * c
        if disc <= 0.0 or a <= 0.0:
            return 0.0
        return max(0.0, (-b + math.sqrt(disc)) / (2.0 * a))

    def f(p):
        e = ((p[0] - cx) / cr, (p[1] - cy) / cr, (p[2] - zc) / zr)
        # metres of crown between this leaf and the sun, and the zenith
        d_sun = _exit(e, sun_e) * rm
        d_sky = _exit(e, sky_e) * rm
        expo = (0.58 * math.exp(-kd * d_sun)
                + 0.42 * math.exp(-kd * 0.80 * d_sky))
        val = (0.34 + 1.00 * expo) * r.uniform(0.86, 1.14)
        return (val * (0.88 + 0.30 * expo),      # sun leaves run yellow
                val,
                val * (1.08 - 0.32 * expo))      # shade leaves run blue
    return f


def make_tree_kit(coll, seed=1, levels=4, n_leaf=13000, lmin=0.072, lmax=0.117,
                  H=9.4, blob=1.45, lift=0.17, spread=2.1, r0=0.30,
                  leaf_detail=0):
    """One source tree, grown rather than scattered.

    Three things do most of the work, and all three are standard practice for
    believable trees:

    * apical dominance - a branch does not fork into equals, it carries on as
      a leader and sheds thinner laterals. Forking into equals is what gives
      procedural trees that tell-tale broccoli look.
    * the pipe model (da Vinci's rule) - the cross-section of a limb equals
      the sum of its children's, so a child's radius is the parent's times its
      share to the power 1/2.49. Taper falls out of it instead of being a
      fudge factor.
    * gravitropism - thin shoots turn back toward the sky, so the crown ends
      in upswept tips rather than straight spokes.

    The leaves then go on shoots in a golden-angle spiral (see leaf_shoot),
    not in a cloud, and carry a baked per-leaf tint (see leaf_tinter).
    """
    r = random.Random(seed)
    trunk = MB(); leaves = MB()

    # ---- trunk: a slight sweep, tapering by the pipe model
    th = r.uniform(0, TAU)
    lean = r.uniform(0.010, 0.030)
    top = H * 0.36
    p = (0.0, 0.0, 0.0)
    rad = r0 * 1.15
    for i in range(4):
        t1 = (i + 1) / 4.0
        q = (math.cos(th) * lean * (top * t1) ** 1.5,
             math.sin(th) * lean * (top * t1) ** 1.5,
             top * t1)
        rq = r0 * 1.15 * (1.0 - 0.40 * t1)
        trunk.cyl(p, q, rad, rq, seg=10)
        p, rad = q, rq

    # ---- crown: leader + laterals, pipe-model taper, gravitropic tips
    tips = []
    twigs = []
    stack = [(p, (0.0, 0.0, 1.0), rad, 0)]
    while stack:
        pos, dr, rr, d = stack.pop()
        if d >= levels:
            tips.append((pos, dr))
            continue
        n_lat = 2 if d < 2 else r.choice((1, 1, 2))
        lead = 0.60 if d < 2 else 0.55
        shares = [lead] + [(1.0 - lead) / n_lat] * n_lat
        base_az = r.uniform(0, TAU)
        seg = spread * (0.74 ** d) * r.uniform(0.80, 1.22)
        for j, sh in enumerate(shares):
            rc = rr * sh ** (1.0 / 2.49)            # pipe model
            if j == 0:
                ang = r.uniform(0.10, 0.26)
                az = base_az + r.uniform(-0.5, 0.5)
                ln = seg * r.uniform(0.95, 1.15)
            else:
                ang = r.uniform(0.62, 1.00)
                az = base_az + GOLDEN * j + r.uniform(-0.35, 0.35)
                ln = seg * r.uniform(0.62, 0.90)
            nd = _tilt(dr, ang, az)
            # gravitropism, stronger the thinner the limb
            g = min(0.55, 0.16 + 0.40 * (1.0 - rc / max(r0, 1e-6)))
            mid = _nrm((nd[0], nd[1], nd[2] + g * 0.5))
            end = _nrm((nd[0], nd[1], nd[2] + g))
            m = (pos[0] + mid[0] * ln * 0.5,
                 pos[1] + mid[1] * ln * 0.5,
                 pos[2] + mid[2] * ln * 0.5 + H * lift * 0.10)
            q = (m[0] + end[0] * ln * 0.5,
                 m[1] + end[1] * ln * 0.5,
                 m[2] + end[2] * ln * 0.5 + H * lift * 0.10)
            sg = 6 if d < 2 else 5
            trunk.cyl(pos, m, rc, rc * 0.84, seg=sg)
            trunk.cyl(m, q, rc * 0.84, rc * 0.62, seg=sg)
            if d >= levels - 3:
                w = 1.0 if d == levels - 1 else (0.55 if d == levels - 2 else 0.3)
                twigs.append((pos, q, w))
            stack.append((q, end, rc * 0.62, d + 1))

    # ---- shoots and leaves
    if not tips:
        tips = [(p, (0.0, 0.0, 1.0))]
    zs = [t[0][2] for t in tips]
    xs = [t[0][0] for t in tips]
    ys = [t[0][1] for t in tips]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    crad = max(0.4, max(math.hypot(x - cx, y - cy) for x, y in zip(xs, ys)))
    tintf = leaf_tinter(min(zs), max(zs), cx, cy, crad, r)
    light = _nrm((0.30, -0.18, 1.0))        # up, leaning into the sun
    size = (lmin + lmax) * 0.5
    # n_leaf is a whole-tree budget: the branch generator makes a different
    # number of twigs than the old recursion did, so sharing it out by weight
    # keeps the canopy density independent of how the branching came out
    wsum = sum(w for _, _, w in twigs) or 1.0
    # Leaves come in rosettes, not in a mist. Scattering them one at a time
    # through the blob around a twig gives an even density, and an even
    # density is exactly what makes a canopy read as green fog: there is
    # nothing for the eye to resolve as a clump, and so no gap between
    # clumps either, which is where a real crown shows its depth and lets
    # the sky through. Grouping the same budget into shoots of ~CLUMP costs
    # nothing and buys both.
    CLUMP = 9
    for (pa_, pb_, wgt) in twigs:
        n_here = int(round(n_leaf * wgt / wsum))
        n_cl = max(1, int(round(n_here / float(CLUMP))))
        for ci in range(n_cl):
            f = r.uniform(-0.05, 1.12)
            bx = pa_[0] + (pb_[0] - pa_[0]) * f
            by = pa_[1] + (pb_[1] - pa_[1]) * f
            bz = pa_[2] + (pb_[2] - pa_[2]) * f
            a_ = r.uniform(0, TAU); b_ = r.uniform(0, math.pi)
            rr = blob * r.uniform(0.02, 1.0) ** 0.42
            c0 = (bx + math.sin(b_) * math.cos(a_) * rr,
                  by + math.sin(b_) * math.sin(a_) * rr,
                  bz + math.cos(b_) * rr * 0.78 + blob * 0.12)
            # the rosette runs along its own little shoot, and every leaf on
            # it shares that direction, which is what makes a clump a clump
            sa_ = r.uniform(0, TAU); sb_ = r.uniform(0.25, 1.35)
            shoot = (math.sin(sb_) * math.cos(sa_),
                     math.sin(sb_) * math.sin(sa_), math.cos(sb_) * 0.7)
            reach = blob * r.uniform(0.17, 0.30)
            # where a leaf sits in its own rosette, -1 at the bottom, +1 at
            # the top: the clump-scale contrast the crown-wide gradient is
            # far too slow to give
            dzc = lambda q, _z=c0[2], _r=reach: (q[2] - _z) / max(_r, 1e-3)
            k_here = n_here // n_cl + (1 if ci < n_here % n_cl else 0)
            for j in range(k_here):
                t = (j + r.uniform(0.0, 0.9)) / max(k_here, 1)
                sp_ = reach * (0.25 + 0.95 * t)
                c = (c0[0] + shoot[0] * sp_ + r.uniform(-1, 1) * reach * 0.34,
                     c0[1] + shoot[1] * sp_ + r.uniform(-1, 1) * reach * 0.34,
                     c0[2] + shoot[2] * sp_ + r.uniform(-1, 1) * reach * 0.28)
                sz = r.uniform(lmin, lmax) * (1.0 - 0.22 * t)
                # pitch biased down: in the photograph the leaves hang
                ya = r.uniform(0, TAU); pa = r.uniform(-1.30, 0.45)
                ca, sa = math.cos(ya), math.sin(ya)
                cp, sp = math.cos(pa), math.sin(pa)
                vd = (-sa * cp, ca * cp, sp)
                nd = (sa * sp, -ca * sp, cp)
                base = (c[0] - vd[0] * sz * 1.22,
                        c[1] - vd[1] * sz * 1.22,
                        c[2] - vd[2] * sz * 1.22)
                # the rosette shades itself: the leaves at the tip of the
                # shoot stand over the ones at its base. This is the contrast
                # the eye actually resolves in a canopy - the crown-wide
                # gradient is too slow to read as anything but a tint - and
                # it is centred on 1.0, so the canopy's mean does not move.
                sh = min(1.26, max(0.66, 0.96 + 0.34 * dzc(c)))
                tc = tintf(c)
                leaf_blade(leaves, base, vd, nd, sz, r, leaf_detail,
                           (tc[0] * sh, tc[1] * sh, tc[2] * sh))

    ot = trunk.to_object('tree%d_trunk' % seed, M('bark'), coll,
                         shade_smooth_all=True)
    ol = leaves.to_object('tree%d_leaves' % seed,
                          M('foliage' if seed % 2 else 'foliage_b'), coll)
    return ot, ol



def _hero_frame():
    """forward / right unit vectors of the opening shot, in the plan frame"""
    fx, fy = HERO_AT[0] - HERO_EYE[0], HERO_AT[1] - HERO_EYE[1]
    L = math.hypot(fx, fy)
    f = (fx / L, fy / L)
    # plan y runs south, so "right" of a camera looking north is +x: (-fy, fx)
    rt = (-f[1], f[0])
    return f, rt


# (Build 3 tried a half-leaf LOD for the street trees furthest from every
# camera the page and the architect use. Those cameras ring the block - 001
# and 004 stand 30-50 m from the east avenue - so no tree is far from all of
# them, and image diffs showed the lighter crowns plainly. Not done.)
def build_planting():
    coll = collection('planting')
    kits = collection('treekit')
    kit = [make_tree_kit(kits, s, levels=5, n_leaf=13000) for s in (1, 2, 3)]
    # slim ornamental trees for the terrace planters and the shop pavement
    terr = [make_tree_kit(kits, s, levels=4, n_leaf=5400, lmin=0.057, lmax=0.091,
                          H=4.6, blob=0.80, lift=0.21, spread=0.95, r0=0.13)
            for s in (11, 12)]
    for o in kit + terr:
        for p in o:
            p.hide_render = True
            p.hide_viewport = True
    placed = collection('trees')
    r = random.Random(20261124)
    # the terrace trees draw from their own sequence, and the street's keeps
    # the 27 draws the old nine planters took (a scale and two turns each),
    # so every street tree stands, turns and scales exactly as before
    rt_ = random.Random(4802)
    for _ in range(27):
        r.random()
    tz = PARK_TOP + PLANTER_SOIL
    for j, (tx, ty) in enumerate(terrace_planters()):
        sc = rt_.uniform(0.95, 1.25)
        for src in terr[j % 2]:
            link_dup(src, src.name + '_t', loc=P(tx, ty, tz),
                     rot_z=rt_.uniform(0, 6.28), scale=(sc, sc, sc), coll=placed)
    def put(x, y, s, i, z=0.0, src=None):
        for o in (src or kit[i % 3]):
            link_dup(o, o.name + '_i', loc=P(x, y, z), rot_z=r.uniform(0, 6.28),
                     scale=(s, s, s), coll=placed)
    # small trees in pits along the shopfront pavement, about one per bay (006)
    i = 0
    x = -2.0
    while x < 76.0:
        put(x + r.uniform(-0.6, 0.6), ROAD_S[0] - 2.3, r.uniform(1.15, 1.35), i, src=terr[i % 2])
        x += 9.45; i += 1
    # an avenue along the east street (001) and the ends of the far south
    # pavement. Trees are the heaviest geometry on the page (every one is
    # ~26 k leaf triangles drawn twice), so the count stays near the old
    # street's ~30 big trees rather than lining all four streets.
    y = -30.0
    while y < 50.0:
        put(ROAD_E[0] - 2.6 + r.uniform(-.4, .4), y, r.uniform(0.85, 1.05), i); i += 1
        y += 9.4
    for x in (-40.0, -26.0, -12.0, 98.0, 112.0, 126.0):
        put(x, ROAD_S[1] + 3.0 + r.uniform(-.4, .4), r.uniform(0.85, 1.05), i); i += 1
    # (Six big trees used to stand round the opening shot in a planted
    # square across the main street. The renders show buildings there, so
    # the square is gone, and the opening shot stands on the far pavement.)
    # the neighbours' avenues (lib_hood): far rows get a
    # thin-crowned kit with bigger leaves
    import lib_hood, os
    far = [make_tree_kit(kits, sd, levels=3, n_leaf=2000, lmin=0.15, lmax=0.23)
           for sd in (21, 22, 23)]
    for o in far:
        for p in o:
            p.hide_render = True
            p.hide_viewport = True
    if not os.environ.get('LP_NOHOOD'): lib_hood.build_hood_trees(far, kit)
    # (The foreground branch that framed the photo-fit's opening shot -
    # fg_branch, carried with HERO_EYE - is gone: from every other view it
    # hung in mid-air over the far pavement, and neither the page's rail nor
    # any architect's camera has it in frame.)
    return coll


# ------------------------------------------------------------------ classical background blocks
# ------------------------------------------------------------------ classical background blocks
def build_classical(name, coll, length, depth, floors, fh=3.40, base_h=4.60,
                    bay=3.05, attic=True):
    """Simplified stone perimeter block: rusticated base, punched windows with
    sills and architraves, projecting cornice, attic storey."""
    m = MB(); gl = MB()
    H = base_h + floors * fh
    nb = max(2, int(round(length / bay)))
    b = length / nb
    m.box((0, 0, 0), (length, depth, base_h))
    for k in range(nb):                                   # base openings
        a0, a1 = k * b + 0.55, (k + 1) * b - 0.55
        m.box((a0, -0.03, 0.35), (a1, 0.22, base_h - 0.75))
        gl.box((a0 + .08, 0.05, 0.42), (a1 - .08, 0.09, base_h - 0.82))
    m.box((0, -0.22, base_h - 0.62), (length, depth, base_h + 0.10))   # band
    for f in range(floors):
        z0 = base_h + 0.10 + f * fh
        for k in range(nb):
            cx = (k + 0.5) * b
            ww, wh = 1.30, 2.05
            frame_for(k * b, (k + 1) * b, z0, z0 + fh, cx - ww / 2, cx + ww / 2,
                      z0 + 0.72, z0 + 0.72 + wh, 0.0, 0.32, m)
            m.box((cx - ww / 2 - 0.16, -0.14, z0 + 0.60),
                  (cx + ww / 2 + 0.16, 0.0, z0 + 0.74))          # sill
            if f < 2:
                m.box((cx - ww / 2 - 0.14, -0.10, z0 + 0.72 + wh),
                      (cx + ww / 2 + 0.14, 0.0, z0 + 0.86 + wh))  # architrave
            gl.box((cx - ww / 2 + .07, 0.14, z0 + 0.79),
                   (cx + ww / 2 - .07, 0.18, z0 + 0.65 + wh))
    m.box((0, 0.32, 0), (length, depth, H))                        # mass
    m.box((-0.30, -0.55, H - 0.30), (length + 0.30, depth, H + 0.42))   # cornice
    if attic:
        m.box((0.6, 0.4, H + 0.42), (length - 0.6, depth - 0.4, H + 3.3))
        for k in range(0, nb, 2):
            cx = (k + 0.5) * b
            m.box((cx - 0.75, 0.25, H + 0.9), (cx + 0.75, 0.45, H + 2.6))
    o = m.to_object(name, M('stone_classical'), coll)
    gl.to_object(name + '_glass', M('glass_window'), coll)
    return o, H


def build_background():
    """Neighbouring blocks across all four streets (the renders' cream
    perimeter blocks), set back behind their own pavements."""
    coll = collection('background')
    r = random.Random(20260108)

    def block(name, L, D, floors, loc, rot):
        build_classical(name, coll, L, D, floors, fh=r.uniform(3.25, 3.6))
        for c in coll.objects:
            if c.name == name or c.name == name + '_glass':
                c.location = loc
                c.rotation_euler = (0, 0, rot)
    # Each row runs only between the cross streets, and stops short of every
    # junction: the first build ran all four rows straight across the roads,
    # so the streets ended in walls and the architect's own camera positions
    # (002, 003, 004 stand on the far corners of the junctions) were inside a
    # neighbour. The corners are left open as the renders show them.
    GAP = 8.0                      # kerb to the first neighbour at a junction
    DEP = 26.0

    def runs(lo_band, hi_band):
        """the free stretches along a row crossed by two road bands; past the
        junctions only one block or two, about the length the rows had"""
        return [(-110.0, lo_band[0] - GAP - DEP - 2.0), (lo_band[1] + GAP, hi_band[0] - GAP),
                (hi_band[1] + GAP + DEP + 2.0, 170.0)]

    def fill(lo, hi, put):
        x = lo
        while hi - x > 14.0:
            L = min(r.uniform(30, 46), hi - x)
            if hi - (x + L) < 14.0 and hi - x - L > 0.5:
                L = hi - x if hi - x <= 50.0 else L
            put(x, L)
            x += L + r.uniform(0.5, 2.0)
    i = [0]

    def nxt():
        i[0] += 1
        return i[0]
    # north row, facing the building across the north street
    for (lo, hi) in runs(ROAD_W, ROAD_E):
        fill(lo, hi, lambda x, L: block('bg_n%d' % nxt(), L, DEP, r.choice([5, 6, 6, 7]),
                                         P(x, ROAD_N[0] - 6.0), 0.0))
    # south row, behind the square the opening shot stands in
    for (lo, hi) in runs(ROAD_W, ROAD_E):
        fill(lo, hi, lambda x, L: block('bg_s%d' % nxt(), L, DEP, r.choice([5, 6, 7]),
                                         P(x + L, ROAD_S[1] + 82.0), math.pi))
    # west row, facing east (its blocks run from y down to y - L)
    for (lo, hi) in runs(ROAD_N, ROAD_S):
        fill(lo, hi, lambda y, L: block('bg_w%d' % nxt(), L, DEP, r.choice([5, 6, 6]),
                                         P(ROAD_W[0] - 6.0, y + L), math.pi / 2))
    # east row, facing west across the east street
    for (lo, hi) in runs(ROAD_N, ROAD_S):
        fill(lo, hi, lambda y, L: block('bg_e%d' % nxt(), L, DEP, r.choice([5, 6, 6, 7]),
                                         P(ROAD_E[1] + 6.0, y), -math.pi / 2))
    return coll


# ------------------------------------------------------------------ vehicles
def _loft(mb, rings, close_start=True, close_end=True):
    n = len(rings[0])
    o = len(mb.v)
    for r in rings:
        mb.v.extend(r)
    for i in range(len(rings) - 1):
        for j in range(n):
            k = (j + 1) % n
            mb.smooth.add(len(mb.f))
            mb.f.append((o + i * n + j, o + i * n + k,
                         o + (i + 1) * n + k, o + (i + 1) * n + j))
    if close_start:
        mb.f.append(tuple(o + j for j in range(n)))
    if close_end:
        b = o + (len(rings) - 1) * n
        mb.f.append(tuple(b + n - 1 - j for j in range(n)))


def _section(x, cz, hw, hh, n=14, p=2.7):
    pts = []
    for j in range(n):
        a = math.pi * 2 * j / n
        ca, sa = math.cos(a), math.sin(a)
        f = lambda t: math.copysign(abs(t) ** (2.0 / p), t)
        pts.append((x, cz + hh * f(sa) * 0 + 0, 0))   # placeholder
    return pts


def make_car(coll, name, L=4.62, W=1.88, H_BELT=0.98, H_ROOF=1.46,
             suv=False, mat='car_paint_0'):
    """Lofted saloon/SUV body. The cross section carries real tumblehome so the
    glasshouse narrows above the waistline, and the sill lifts into wheel
    arches - without those two things a car reads as a pod at street scale."""
    body = MB(); glass = MB(); wheel = MB(); rim = MB(); trim = MB()
    SILL = 0.30 if not suv else 0.36
    RW = 0.335 if not suv else 0.385
    WX = (0.185, 0.815)

    #  u      roof    belt    halfwidth  roofwidth
    prof = [(0.000, 0.455, 0.735, 0.30, 1.00),
            (0.025, 0.510, 0.800, 0.62, 1.00),
            (0.075, 0.555, 0.870, 0.84, 1.00),
            (0.160, 0.590, 0.930, 0.94, 0.99),
            (0.265, 0.640, 0.975, 0.985, 0.97),
            (0.345, 0.830, 1.000, 1.000, 0.86),
            (0.430, 0.975, 1.000, 1.000, 0.795),
            (0.540, 1.000, 0.998, 0.998, 0.785),
            (0.645, 0.985, 0.992, 0.985, 0.795),
            (0.745, 0.905, 0.980, 0.955, 0.845),
            (0.845, 0.760, 0.962, 0.900, 0.925),
            (0.935, 0.665, 0.930, 0.790, 0.985),
            (1.000, 0.620, 0.870, 0.40, 1.00)]

    def arch(u):
        a = 0.0
        for cx in WX:
            d = (u - cx) / 0.085
            a = max(a, (RW + 0.07 - SILL) * math.exp(-d * d))
        return a

    def section(u, roof, belt, hwf, rwf):
        hw = (W * 0.5) * hwf
        rw = hw * rwf
        zb = SILL + arch(u) + 0.045 * abs(2 * u - 1) ** 3
        zt = max(H_ROOF * roof, H_BELT * belt + 0.035)
        zbl = H_BELT * belt
        if zbl <= zb + 0.02:
            zbl = zb + 0.02
        if zt <= zbl + 0.02:
            zt = zbl + 0.02
        half = [(0.00, zb), (hw * 0.70, zb), (hw * 0.94, zb + (zbl - zb) * 0.18),
                (hw, zb + (zbl - zb) * 0.55), (hw * 0.995, zbl),
                (rw + (hw - rw) * 0.45, zbl + (zt - zbl) * 0.42),
                (rw, zt - (zt - zbl) * 0.22), (rw * 0.80, zt), (0.0, zt)]
        ring = [(u * L, y, z) for (y, z) in half]
        ring += [(u * L, -y, z) for (y, z) in reversed(half[1:-1])]
        return ring

    rings = [section(*p) for p in prof]
    _loft(body, rings)

    # glasshouse: a thin shell just outside the body between the A and C pillars
    gprof = [p for p in prof if 0.26 <= p[0] <= 0.85]
    grings = []
    for (u, roof, belt, hwf, rwf) in gprof:
        hw = (W * 0.5) * hwf
        rw = hw * rwf
        zt = max(H_ROOF * roof, H_BELT * belt + 0.035)
        zbl = H_BELT * belt
        half = [(0.0, zbl + 0.01),
                (rw + (hw - rw) * 0.45, zbl + (zt - zbl) * 0.42),
                (rw, zt - (zt - zbl) * 0.22), (rw * 0.80, zt), (0.0, zt)]
        ring = [(u * L, y * 1.006, z) for (y, z) in half]
        ring += [(u * L, -y * 1.006, z) for (y, z) in reversed(half[1:-1])]
        grings.append(ring)
    _loft(glass, grings, close_start=False, close_end=False)

    # waist trim, lamps
    for (u0, u1) in ((0.0, 0.055), (0.955, 1.0)):
        trim.box((u0 * L, -W * 0.40, H_BELT * 0.52),
                 (u1 * L, W * 0.40, H_BELT * 0.52 + 0.14))
    for ux in WX:
        cx = ux * L
        for side in (1, -1):
            cy = side * (W * 0.5 - 0.055)
            wheel.cyl((cx, cy, RW), (cx, cy - side * 0.225, RW), RW, RW, seg=18)
            rim.cyl((cx, cy - side * 0.015, RW), (cx, cy - side * 0.055, RW),
                    RW * 0.64, RW * 0.64, seg=18)
    ob = body.to_object(name, M(mat), coll, shade_smooth_all=True)
    og = glass.to_object(name + '_glass', M('car_glass'), coll, shade_smooth_all=True)
    ow = wheel.to_object(name + '_tyre', M('tire'), coll, shade_smooth_all=True)
    orr = rim.to_object(name + '_rim', M('chrome'), coll, shade_smooth_all=True)
    ot = trim.to_object(name + '_trim', M('chrome'), coll)
    return [ob, og, ow, orr, ot]


def make_bus(coll, name='bus'):
    body = MB(); glass = MB(); wheel = MB()
    L, W, H = 12.2, 2.55, 3.15
    rings = []
    for u in (0.0, 0.03, 0.10, 0.90, 0.97, 1.0):
        t = 2 * u - 1
        hw = (W / 2) * (1 - 0.55 * max(0, abs(t) - 0.88) ** 1.4 * 8)
        bot, top = 0.42, H * (1 - 0.10 * max(0, abs(t) - 0.9) ** 1.2 * 9)
        n = 16
        ring = []
        for j in range(n):
            a = math.pi * 2 * j / n + math.pi / n
            ca, sa = math.cos(a), math.sin(a)
            e = 5.0
            sx = math.copysign(abs(ca) ** (2.0 / e), ca)
            sz = math.copysign(abs(sa) ** (2.0 / e), sa)
            ring.append((u * L, hw * sx, (top + bot) * .5 + (top - bot) * .5 * sz))
        rings.append(ring)
    _loft(body, rings)
    for side in (1, -1):
        glass.box((0.9, side * (W / 2 + 0.01), 1.55), (L - 0.9, side * (W / 2 - 0.03), 2.68))
    glass.box((0.05, -W / 2 + 0.05, 1.35), (0.30, W / 2 - 0.05, 2.78))
    glass.box((L - 0.30, -W / 2 + 0.05, 1.45), (L - 0.05, W / 2 - 0.05, 2.78))
    for ux in (0.16, 0.62, 0.78):
        for side in (1, -1):
            cx = ux * L; cy = side * (W / 2 - 0.08)
            wheel.cyl((cx, cy, 0.52), (cx, cy - side * 0.28, 0.52), 0.52, 0.52, seg=16)
    ob = body.to_object(name, M('bus_green'), coll, shade_smooth_all=True)
    og = glass.to_object(name + '_glass', M('car_glass'), coll)
    ow = wheel.to_object(name + '_tyre', M('tire'), coll, shade_smooth_all=True)
    return [ob, og, ow]


def build_traffic():
    coll = collection('traffic')
    kits = collection('carkit')
    fleet = []
    specs = [(4.70, 1.86, 0.98, 1.44, False), (4.92, 1.94, 1.02, 1.48, False),
             (4.55, 1.85, 1.12, 1.66, True),  (5.05, 1.98, 1.18, 1.76, True),
             (4.35, 1.80, 0.94, 1.40, False), (4.80, 1.90, 1.14, 1.70, True)]
    for i, (L, W, hb, hr, suv) in enumerate(specs):
        fleet.append(make_car(kits, 'car%d' % i, L, W, hb, hr, suv,
                              'car_paint_%d' % (i * 2 % 10)))
    bus = make_bus(kits)
    for grp in fleet + [bus]:
        for o in grp:
            o.hide_render = True
            o.hide_viewport = True

    def place(grp, x, y, rz, name):
        for src in grp:
            link_dup(src, name + '_' + src.name, loc=(x, y, 0.0), rot_z=rz, coll=coll)

    # street deliberately left clear of vehicles
    return coll, []


def build_people():
    coll = collection('people')
    m = MB()
    for k in range(26):
        x = rnd.uniform(-20, 70)
        y = rnd.uniform(STREET_Y - 4.2, WALK_EDGE + 0.6)
        h = rnd.uniform(1.62, 1.86)
        m.cyl((x, y, 0.14), (x, y, 0.14 + h * 0.52), 0.115, 0.145, seg=7)
        m.cyl((x, y, 0.14 + h * 0.50), (x, y, 0.14 + h * 0.86), 0.185, 0.145, seg=7)
        m.sphere((x, y, 0.14 + h * 0.93), 0.105, seg=8, rings=5)
    m.to_object('people', M('person'), coll, shade_smooth_all=True)
    return coll

