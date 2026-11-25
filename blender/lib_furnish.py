# -*- coding: utf-8 -*-
"""Where every piece of furniture the architect drew goes, and what it is.

Pure python (no bpy, no shapely), so it runs under Blender's python and the
system one alike. `plan_levels()` reads blender/plans/rooms.json (the symbols
tools/plan_rooms.py found on the sheets: kind, centre, size, heading, room)
and plan.json (the level heights) and returns, per level, every piece as

    node   in_<LEVEL>_<owner>_furn_<kind><k>__<material>   (CONTRACT.md)
    cls    the mesh it is an instance of: one mesh per (kind, size class)
    at     [x, y] plan metres, the piece's foot (footprint centre, floor level)
    rot    plan degrees, the way the piece's local +X faces (see below)
    box    the drawn box {centre, size [across, along], heading} it stands in

and `classes`: cls -> the parameters build_furnish.py makes the mesh from.

LOCAL FRAME of every mesh: +X is the way the piece FACES (a bed's foot, a
sofa's seat, a worktop's front, a chair towards its table), +Y to its left
(Blender's right-handed frame, z up), origin on the floor at the centre of
its footprint. The plan frame is a mirror of Blender's (CONTRACT: Blender =
(x, -y, z)), so a piece facing plan heading h is turned by -h about Blender z,
and its local +Y lands on plan heading h - 90. Every placement is a turn,
never a reflection: a mirrored flat gets the same meshes turned the other
way, and the only pieces with a hand (the L-desks and the quarter-round
corner glyphs) are built from their own drawn outline or turned onto their
corner, so nothing is ever inside out.

Size classes: the drawn box is snapped to 5 cm, so the eight flats of a
stack share one bed, one sofa, one worktop leg. A piece is placed at its
exact drawn centre; its footprint differs from the drawing by <= 2.5 cm.

Not built, on purpose: `vent_duct` (a shaft in the wall - the interior
files already fill it solid). The sink and hob are NOT on the sheets (the
sheet draws a worktop's front edge and nothing on it); they are part of the
kitchen-run module and carry `drawn: false` in the index.
"""
import hashlib
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PLANS = os.path.join(HERE, 'plans')
WEB = os.path.join(os.path.dirname(HERE), 'web')

import sys as _sys
if HERE not in _sys.path:
    _sys.path.insert(0, HERE)
import furn_kit_bath as _KB      # noqa: E402  the four furniture kits (build 6):
import furn_kit_living as _KL    # noqa: E402  pure python, every kind built in
import furn_kit_bed as _KD       # noqa: E402  the LOCAL FRAME below, one mesh
import furn_kit_plants as _KP    # noqa: E402  per (kind, size class, seed)

KIT = {}
for _m in (_KB, _KL, _KD, _KP):
    for _k in _m.KINDS:
        KIT.setdefault(_k, _m)

# the kits' fixed module sizes for the kinds whose w, d the plan does not set
_FIXED_WD = {'chair': (0.40, 0.47), 'sink': (0.50, 0.42), 'hob': (0.58, 0.50), 'desk': (1.0, 1.0)}
PARTS = {}      # cls -> [(material, verts, faces, smooth)] (filled by class_parts)


def class_parts(cls, kind, params):
    """The kit's mesh parts for one class, in the piece's local frame (cached).
    None for the kinds no kit builds (partition_line: build_furnish's own)."""
    if cls in PARTS:
        return PARTS[cls]
    if kind not in KIT:
        PARTS[cls] = None
        return None
    P = dict(params)
    seed = int(P.pop('seed', 0))
    P.pop('kit', None)
    if kind in ('shower_corner', 'bath_corner'):
        # lib_furnish's {sx (local X), sy (local Y)}; the bath kit takes w = Y, d = X
        w, d = P.pop('sy'), P.pop('sx')
    elif kind == 'table_round':
        w = d = P['dia']
    elif kind in _FIXED_WD:
        w, d = _FIXED_WD[kind]
        P.pop('w', None), P.pop('d', None)
    else:
        w, d = P.pop('w'), P.pop('d')
    parts = KIT[kind].build(kind, w, d, seed=seed, **P)
    PARTS[cls] = parts
    return parts


def parts_bounds(parts):
    xs, ys, zs = [], [], []
    for _m, V, _f, _s in parts or []:
        for x, y, z in V:
            xs.append(x); ys.append(y); zs.append(z)
    if not xs:
        return None
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def parts_tris(parts):
    return sum(len(f) - 2 for _m, _v, F, _s in parts or [] for f in F)

SNAP = 0.05

# rooms.json kind -> the material the node is named after (its main one;
# the mesh may carry more primitives, each named by its own material)
MAIN_MAT = {
    'bed_double': 'int_fabric_white', 'nightstand': 'int_white_gloss', 'sofa': 'int_fabric_sofa',
    'table_coffee': 'int_coffee_top', 'tv': 'int_black', 'table_round': 'int_marble',
    'chair': 'dining_chair_02', 'wc': 'int_ceramic', 'basin': 'int_ceramic',
    'shower_corner': 'int_ceramic', 'bath_corner': 'int_ceramic', 'bath': 'int_ceramic',
    'shower': 'int_ceramic', 'partition_line': 'int_glass', 'kitchen_run': 'int_white_gloss',
    'sink': 'chrome', 'hob': 'int_black', 'desk': 'int_white_gloss', 'office_chair': 'int_fabric_dark',
    'desk_equipment': 'int_black',
}
SKIP = {'vent_duct'}

# sane limits for the drawn box, per kind: (across lo, hi), (along lo, hi)
LIMITS = {
    'bed_double': ((1.40, 2.00), (1.90, 2.20)),
    'nightstand': ((0.35, 0.60), (0.28, 0.50)),
    'sofa': ((1.40, 2.60), (0.80, 1.05)),
    'table_coffee': ((0.90, 1.45), (0.45, 0.70)),
    'tv': ((0.60, 1.40), (0.10, 0.30)),
    'table_round': ((0.70, 1.30), (0.70, 1.30)),
    'wc': ((0.36, 0.50), (0.52, 0.75)),
    'basin': ((0.45, 0.80), (0.33, 0.55)),
    'bath': ((1.20, 2.20), (0.60, 0.90)),
    'shower': ((0.70, 2.20), (0.70, 1.40)),
    'kitchen_run': ((0.30, 6.00), (0.45, 0.90)),
    'office_chair': ((0.45, 0.70), (0.45, 0.70)),
    'desk_equipment': ((0.15, 0.70), (0.10, 0.40)),
}


def snap(v):
    return round(round(v / SNAP) * SNAP, 3)


def clampv(v, lo, hi):
    return max(lo, min(hi, v))


def rad(d):
    return math.radians(d)


def fwd(h):
    return (math.cos(rad(h)), math.sin(rad(h)))


def footprint(c, size, h):
    """Corners of a box [across, along] centred at c facing h (plan)."""
    w, d = size
    f = fwd(h)
    p = (-f[1], f[0])
    return [(c[0] + p[0] * w / 2 * sx + f[0] * d / 2 * sy, c[1] + p[1] * w / 2 * sx + f[1] * d / 2 * sy)
            for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1))]


def to_local(P, c, rot):
    """Plan point -> the mesh's local (x, y) for a piece at c turned to `rot`
    (local +X on plan heading rot, local +Y on plan heading rot - 90)."""
    dx, dy = P[0] - c[0], P[1] - c[1]
    f = fwd(rot)
    g = fwd(rot - 90.0)
    return (dx * f[0] + dy * f[1], dx * g[0] + dy * g[1])


CEILING = {}    # level -> clear height (plan_meta 'clear'), filled by plan_levels


def level_z():
    P = json.load(open(os.path.join(PLANS, 'plan.json')))
    return {l['level']: l['z'] for l in P['levels']}


def windows_of(room):
    return [(w['centre'], w.get('width') or 1.0) for w in room.get('windows', [])]


def seg_near(p, a, b, tol):
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy or 1e-9
    t = ((p[0] - ax) * vx + (p[1] - ay) * vy) / L2
    if t < -0.05 or t > 1.05:
        return False
    qx, qy = ax + vx * t, ay + vy * t
    return math.hypot(p[0] - qx, p[1] - qy) < tol


def room_net(room):
    """The room's free floor as a list of rings (outer first), or None."""
    pj = room.get('polygon_net')
    if not pj:
        return None
    if isinstance(pj, list):
        pj = max(pj, key=lambda q: len(q['outline']))
    return [pj['outline']] + list(pj.get('holes') or [])


def inside(p, rings):
    """Even-odd point in polygon (with holes)."""
    x, y = p
    c = False
    for ring in rings:
        n = len(ring)
        for i in range(n):
            x0, y0 = ring[i]
            x1, y1 = ring[(i + 1) % n]
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                c = not c
    return c


def kitchen_profile(c, rot, ws, ds, net, blocks):
    """Where a kitchen leg may stand (build 4). The leg is a box ws across,
    ds deep, front at local +X; the sheet's worktop zone sometimes runs over a
    column or a duct (flat 42's corner), and a box there pokes through the
    wall into the next flat or the corridor. Walk the leg in 2 cm strips; in
    each, the depth from the front that stays on the room's free floor (and
    off any drawn duct). -> None if the whole box stands free (within 4 cm
    at the back: the snap to 5 cm classes), else [[y0, y1, depth], ...] in
    local metres, strips of equal depth merged, strips under 0.15 deep left
    out."""
    if net is None:
        return None
    f = fwd(rot)
    g = fwd(rot - 90.0)

    def free(x, y):
        P = (c[0] + f[0] * x + g[0] * y, c[1] + f[1] * x + g[1] * y)
        if not inside(P, net):
            return False
        return not any(inside(P, [b]) for b in blocks)
    STEP = 0.02
    n = max(1, int(round(ws / STEP)))
    strips = []
    full = True
    for k in range(n):
        y0 = -ws / 2 + ws * k / n
        y1 = -ws / 2 + ws * (k + 1) / n
        dep = ds
        for yy in (y0 + 0.002, 0.5 * (y0 + y1), y1 - 0.002):
            t = 0.0
            while t < dep:
                if not free(ds / 2 - t - 0.005, yy):
                    dep = t
                    break
                t += 0.01
        if dep < ds - 0.04:
            full = False
        else:
            dep = ds
        strips.append([y0, y1, round(dep if dep >= 0.15 else 0.0, 2)])
    loss = sum((ds - d) * (b - a) for a, b, d in strips)
    if full or loss < 0.015:
        return None             # a sliver at most: the 5 cm snap, not a column
    out = []
    for st in strips:
        if out and abs(out[-1][2] - st[2]) < 1e-6:
            out[-1][1] = st[1]
        else:
            out.append(list(st))
    return [[round(a, 3), round(b, 3), d] for a, b, d in out if d > 0]


OMITTED = []        # drawn pieces deliberately not placed (build 4), with why


def plan_unit(level, num, rec, is_office):
    """-> list of pieces for one flat / office."""
    owner = ('o%s' if is_office else 'u%s') % num
    rooms = rec['rooms']
    rid = {r['id']: i for i, r in enumerate(rooms)}
    out = []
    count = {}

    def add(kind, cls, params, at, rot, box, room, src, drawn=True, extra=None):
        count[kind] = count.get(kind, 0) + 1
        k = count[kind]
        mat = MAIN_MAT[kind]
        pc = dict(node='in_%s_%s_furn_%s%d__%s' % (level, owner, kind, k, mat), kind=kind, k=k,
                  owner=owner, n=num, cls=cls, params=params, at=[round(at[0], 4), round(at[1], 4)],
                  rot=round(rot % 360.0, 3), box=box, room=room, room_index=rid.get(room), src=src, drawn=drawn)
        if extra:
            pc.update(extra)
        out.append(pc)
        return pc

    fur = rec['furniture']
    kitchen_legs = []
    room_kind = {r['id']: r.get('kind') for r in rooms}
    for i, f in enumerate(fur):
        kind = f['kind']
        if kind in SKIP:
            continue
        if kind == 'nightstand' and room_kind.get(f.get('room')) in ('hall', 'corridor'):
            # build 4: the 33/54/../180 stack's second bed has its nightstand
            # drawn ACROSS the bedroom wall, centred in the hall; between that
            # wall and the bed there are 0.2 m. Not placed (it stood half in
            # the hall); listed for the owner.
            OMITTED.append(dict(level=level, n=num, kind=kind, src=i, room=f.get('room'),
                                why='drawn across the bedroom wall into the hall; no room beside the bed'))
            continue
        c = f['centre']
        w, d = f['size']
        h = 0.0 if f.get('heading_free') and kind == 'table_round' else f['heading']
        box = dict(centre=c, size=[w, d], heading=h)
        if kind in ('shower_corner', 'bath_corner'):
            # axis-aligned [dx, dy]; heading = out of the corner. Turned to
            # h + 45 so local +X / +Y run along the plan axes and the curve
            # bulges along local (+1, +1), i.e. plan h.
            rot = (round((h - 45.0) / 90.0) * 90.0 + 45.0) + 45.0
            ax = round(rot / 90.0) % 2              # local X along plan y?
            sx, sy = (f['size'][1], f['size'][0]) if ax else (f['size'][0], f['size'][1])
            sx, sy = snap(clampv(sx, 0.7, 1.6)), snap(clampv(sy, 0.7, 1.6))
            box = dict(centre=c, size=list(f['size']), heading=h, axis_aligned=True)
            add(kind, '%s_%03d_%03d' % (kind, sx * 100, sy * 100), dict(sx=sx, sy=sy), c, rot, box, f['room'], i)
            continue
        if kind == 'partition_line':
            # a glass screen on the drawn line: long axis across or along h
            L = max(w, d)
            rot = h if w >= d else h + 90.0
            L = snap(L)
            add(kind, 'screen_%03d' % (L * 100), dict(L=L), c, rot, box, f['room'], i)
            continue
        if kind == 'desk':
            ol = f['outline']['outline'] if isinstance(f.get('outline'), dict) else f['outline']
            loc = [to_local(p, c, h) for p in ol]
            loc = [(round(x, 2), round(y, 2)) for x, y in loc]
            # one mesh per drawn desk shape (left- and right-handed L's are
            # two shapes, not one mesh reflected)
            key = 'desk_' + hashlib.md5(repr(loc).encode()).hexdigest()[:8]
            add(kind, key, dict(outline=loc), c, h, box, f['room'], i)
            continue
        if kind == 'chair':
            add(kind, 'chair', dict(), c, h, box, f['room'], i)
            continue
        if kind == 'kitchen_run':
            lim = LIMITS[kind]
            ws, ds = snap(clampv(w, *lim[0])), snap(clampv(d, *lim[1]))
            kitchen_legs.append((i, f, ws, ds))
            continue
        lim = LIMITS.get(kind)
        if lim:
            ws, ds = snap(clampv(w, *lim[0])), snap(clampv(d, *lim[1]))
        else:
            ws, ds = snap(w), snap(d)
        cls = '%s_%03d_%03d' % (kind, round(ws * 100), round(ds * 100))
        params = dict(w=ws, d=ds)
        if kind == 'basin':
            params['shelf'] = 0         # build 6: the mirror and its plant, no shelf (budget)
        if kind == 'bed_double':
            # the first bedroom's duvet teal, the others blue-grey, as the
            # show flat had them
            room = next((r for r in rooms if r['id'] == f['room']), None)
            teal = room is not None and room['id'] in ('br1', 'sd1')
            params['duvet'] = 'int_fabric_teal' if teal else 'int_fabric_bluegrey'
            cls += '_t' if teal else '_b'
        if kind == 'table_round':
            dd = snap(clampv(max(w, d), 0.7, 1.3))
            cls, params = 'table_round_%03d' % (dd * 100), dict(dia=dd)
        if kind == 'desk_equipment':
            # rooms.json points it from the chair to the glyph; the screen
            # faces the chair
            h = h + 180.0
        add(kind, cls, params, c, h, box, f['room'], i)

    # ---- the kitchen run module: legs as drawn, wall units where a wall
    # stands behind and no window, a sink and a hob on the longest legs
    legp = {}
    if kitchen_legs:
        ducts = [footprint(fd['centre'], fd['size'], fd['heading']) for fd in fur if fd['kind'] == 'vent_duct']
        by_room = {}
        for i, f, ws, ds in kitchen_legs:
            by_room.setdefault(f['room'], []).append((i, f, ws, ds))
        for room_id, legs in by_room.items():
            room = rooms[rid[room_id]] if room_id in rid else {}
            wins = windows_of(room)
            legs.sort(key=lambda t: -t[2])
            for j, (i, f, ws, ds) in enumerate(legs):
                c, h = f['centre'], f['heading']
                fv = fwd(h)
                pv = (-fv[1], fv[0])
                back = (c[0] - fv[0] * f['size'][1] / 2, c[1] - fv[1] * f['size'][1] / 2)
                a = (back[0] + pv[0] * f['size'][0] / 2, back[1] + pv[1] * f['size'][0] / 2)
                b = (back[0] - pv[0] * f['size'][0] / 2, back[1] - pv[1] * f['size'][0] / 2)
                win = any(seg_near(wc, a, b, 0.45) for wc, ww in wins)
                upper = (not win) and ws >= 0.6
                cls = 'kitchen_run_%03d_%03d%s' % (round(ws * 100), round(ds * 100), '_u' if upper else '')
                params = dict(w=ws, d=ds, upper=upper)
                # clipped to the room's free floor where the drawn zone runs
                # over a column or a duct: its own mesh then (build 4)
                prof = kitchen_profile(c, h, ws, ds, room_net(room), ducts)
                if prof is not None:
                    params['profile'] = prof
                    cls += '_k' + hashlib.md5(repr(prof).encode()).hexdigest()[:8]
                legp[i] = add('kitchen_run', cls, params, c, h,
                              dict(centre=c, size=list(f['size']), heading=h), room_id, i)
            # sink on the longest leg, hob on the next one long enough (or
            # further along the same leg): module, not drawn
            i0, f0, w0, d0 = legs[0]
            total = sum(t[2] for t in legs)
            if total >= 1.0:
                spots = []
                if len(legs) > 1 and legs[1][2] >= 1.0:
                    spots = [(legs[0], 0.0, 'sink'), (legs[1], 0.0, 'hob')]
                elif w0 >= 1.8:
                    spots = [(legs[0], -0.25, 'sink'), (legs[0], 0.25, 'hob')]
                else:
                    spots = [(legs[0], 0.0, 'sink')]
                net = room_net(room)
                taken = []
                for (ii, ff, ww, dd), t, what in spots:
                    c, h = ff['centre'], ff['heading']
                    fv = fwd(h)
                    pv = (-fv[1], fv[0])
                    sz = [0.50, 0.42] if what == 'sink' else [0.58, 0.50]
                    # where along the leg: as near the wanted spot as the room
                    # allows - a duct the sheet draws inside the worktop zone
                    # (flat 42's corner) boxes in the back of the run, and a
                    # sink is not set into a duct
                    best = None
                    for k in range(-20, 21):
                        tt = k / 40.0
                        if abs(tt) * ww > ww / 2 - sz[0] / 2 - 0.03:
                            continue
                        aa = (c[0] + pv[0] * tt * ww + fv[0] * 0.03, c[1] + pv[1] * tt * ww + fv[1] * 0.03)
                        corners = footprint(aa, [sz[0] + 0.04, sz[1] + 0.04], h) + [aa]
                        ok = net is None or all(inside(q, net) for q in corners)
                        clash = any(abs((aa[0] - q[0]) * pv[0] + (aa[1] - q[1]) * pv[1]) < 0.62 and
                                    abs((aa[0] - q[0]) * fv[0] + (aa[1] - q[1]) * fv[1]) < 0.3 for q in taken)
                        if ok and not clash:
                            sc = abs(tt - t)
                            if best is None or sc < best[0]:
                                best = (sc, aa)
                    if best is None:
                        continue                           # nowhere clear on this leg: left out
                    at = best[1]
                    taken.append(at)
                    # build 6: the run under it gets the cut-out (sink) or
                    # the oven (hob) at this spot, in the leg's own frame
                    leg = legp[ii]
                    lx, ly = to_local(at, leg['at'], leg['rot'])
                    lp = leg['params']
                    lp[what + '_x'] = round(lx, 3)
                    lp[what + '_y'] = round(ly, 3)
                    if what == 'hob':
                        wall = round(lp['d'] / 2 + lx, 3)
                        params = dict(wall=wall, upper=lp['upper'], ceiling=CEILING.get(level, 3.0))
                        cls = 'hob_%s_%03d' % ('u' if lp['upper'] else 'c', round(wall * 100))
                    else:
                        params, cls = dict(), 'sink'
                    add(what, cls, params, at, h, dict(centre=list(at), size=sz, heading=h), room_id, ii, drawn=False,
                        extra=dict(module='kitchen_run', note='not on the sheet: part of the kitchen-run module'))
        for leg in legp.values():
            lp = leg['params']
            for what in ('sink', 'hob'):
                if what + '_y' in lp:
                    leg['cls'] += '_%s%d_%d' % (what[0], round(lp[what + '_x'] * 100), round(lp[what + '_y'] * 100))
    return out


def plan_meta_level(lv):
    """web/plan_meta/<LEVEL>.json (lib_plan.py's): the door leaves and the
    clear height the dressing needs. None if it is not there."""
    path = os.path.join(WEB, 'plan_meta', lv + '.json')
    try:
        return json.load(open(path))
    except Exception:
        return None


def plan_levels(want=None, dress=True):
    import lib_dress
    R = json.load(open(os.path.join(PLANS, 'rooms.json')))
    Z = level_z()
    levels = {}
    metas = {}
    for is_office, coll in ((False, R['flats']), (True, R['offices'])):
        for num, rec in coll.items():
            lv = rec['level']
            if want and lv not in want:
                continue
            if lv not in metas:
                metas[lv] = plan_meta_level(lv)
                CEILING[lv] = float((metas[lv] or {}).get('clear') or 3.0)
            L = levels.setdefault(lv, dict(z=Z[lv], units={}, pieces=[], classes={}))
            pcs = plan_unit(lv, num, rec, is_office)
            if dress:
                # build 6: the undrawn pieces that make it a show flat
                pcs = lib_dress.dress_unit(lv, num, rec, is_office, pcs, metas[lv], CEILING[lv])
            L['units'][num] = dict(token=('o%s' if is_office else 'u%s') % num, office=is_office,
                                   layout_group=rec.get('layout_group'), kit_group=rec.get('kit_group'),
                                   type=rec.get('type'), rooms=[r['id'] for r in rec['rooms']],
                                   room_kinds=[r['kind'] for r in rec['rooms']])
            for p in pcs:
                L['pieces'].append(p)
                L['classes'].setdefault(p['cls'], dict(kind=p['kind'], params=p['params']))
    return levels


def index_json(levels, stats=None):
    """web/interior/furn/index.json: per level per flat the pieces, the room
    each stands in, the drawn box, and the groups (for the reveal stagger)."""
    out = dict(
        about='Furniture the architect drew, per level and flat. Written by blender/build_furnish.py from '
              'blender/plans/rooms.json. Frame: plan metres (CONTRACT.md). Files: <LEVEL>.glb in the same frame as '
              'web/interior/<LEVEL>.glb; nodes in_<LEVEL>_<owner>_furn_<kind><k>__<material>, origin = the piece\'s '
              'foot (footprint centre at the level\'s floor), so it can be scaled about its own origin.',
        fields=dict(node='glTF node name', kind='rooms.json symbol kind (sink/hob: kitchen-run module)',
                    room='room id in rooms.json flats[n].rooms', room_index='index into that list',
                    box='the drawn box: centre [x,y], size [across, along heading], heading (plan deg); '
                        'axis_aligned boxes (corner glyphs) give size = [dx, dy]',
                    at='the node origin, plan [x,y]', rot='plan degrees the piece faces',
                    drawn='false = not on the sheet (sink, hob, and the dressing: plants, rugs, curtains, art...)',
                    order='reveal order within the flat: by room, drawn pieces first, then largest first',
                    nobox='an undrawn piece WITHOUT a box is not solid to a walking body (a rug, a curtain, a '
                          'picture, a lamp, a table plant); a solid one carries its solid footprint as box',
                    z='the node origin\'s height over the level floor when it is not 0 (a plant on a table, a loggia '
                      'pot on the loggia\'s raised floor)'),
        levels={})
    # drawn pieces deliberately not placed, and why (build 4)
    out['omitted'] = [dict(o) for o in OMITTED if o['level'] in levels]
    for lv, L in sorted(levels.items()):
        units = {}
        for num, u in L['units'].items():
            pcs = [p for p in L['pieces'] if p['n'] == num and p['owner'] == u['token']]
            ro = {rid: i for i, rid in enumerate(u['rooms'])}
            def area(p):
                b = p.get('box') or p.get('foot')
                return b['size'][0] * b['size'][1]
            pcs.sort(key=lambda p: (ro.get(p['room'], 99), not p['drawn'], -area(p)))

            def rec(p, k):
                r = dict(node=p['node'], kind=p['kind'], room=p['room'], room_index=p['room_index'])
                if p.get('box'):
                    r['box'] = p['box']
                r.update(at=p['at'], rot=p['rot'], drawn=p['drawn'], order=k)
                if p.get('z'):
                    r['z'] = p['z']
                return r
            units[num] = dict(token=u['token'], office=u['office'], type=u['type'],
                              layout_group=u['layout_group'], kit_group=u['kit_group'],
                              pieces=[rec(p, k) for k, p in enumerate(pcs)])
        out['levels'][lv] = dict(z=L['z'], file='%s.glb' % lv, units=units,
                                 **({'stats': stats[lv]} if stats and lv in stats else {}))
    return out


def patch_plan_meta(furn_dir, levels=None, web=None):
    """Bring web/plan_meta.json's nav.furn (and the per-level split files)
    up to date with the furniture in `furn_dir`: lib_plan.nav_furn's own
    records (the walker's collision wins from them), nothing else touched.
    Needs the system python (lib_plan imports shapely)."""
    import lib_plan
    lib_plan.FURN_DIR = furn_dir
    web = web or WEB
    meta_path = os.path.join(web, 'plan_meta.json')
    split = os.path.join(web, 'plan_meta')
    M = json.load(open(meta_path))
    done = []
    for L in M['levels']:
        if 'nav' not in L or (levels and L['id'] not in levels):
            continue
        fu = lib_plan.nav_furn(L['id'])
        if fu is None:
            continue
        L['nav']['furn'] = fu
        done.append((L['id'], len(fu)))
        fn = os.path.join(split, L['id'] + '.json')
        if os.path.exists(fn):
            S = json.load(open(fn))
            S['nav']['furn'] = fu
            txt = json.dumps(S, separators=(',', ':'))
            open(fn + '.tmp', 'w').write(txt)
            os.replace(fn + '.tmp', fn)
    # the split index records each level file's size
    idx = os.path.join(split, 'index.json')
    if os.path.exists(idx):
        I = json.load(open(idx))
        for rec in I.get('levels', []):
            fn = os.path.join(split, rec.get('file') or '')
            if rec.get('file') and os.path.exists(fn):
                rec['bytes'] = os.path.getsize(fn)
        open(idx + '.tmp', 'w').write(json.dumps(I, separators=(',', ':')))
        os.replace(idx + '.tmp', idx)
    txt = json.dumps(M, separators=(',', ':')) if not open(meta_path).read(200).count('\n') else json.dumps(M, indent=1)
    open(meta_path + '.tmp', 'w').write(txt)
    os.replace(meta_path + '.tmp', meta_path)
    return done


if __name__ == '__main__':
    import sys
    if '--nav' in sys.argv:
        # python3 blender/lib_furnish.py --nav [FURN_DIR] : plan_meta nav.furn from the furniture
        i = sys.argv.index('--nav')
        d = sys.argv[i + 1] if len(sys.argv) > i + 1 else os.path.join(WEB, 'interior', 'furn')
        w = sys.argv[sys.argv.index('--web') + 1] if '--web' in sys.argv else None
        print(patch_plan_meta(d, web=w))
        raise SystemExit(0)
    lv = plan_levels(sys.argv[1:] or None)
    for k, L in sorted(lv.items()):
        print(k, len(L['pieces']), 'pieces', len(L['classes']), 'classes')
