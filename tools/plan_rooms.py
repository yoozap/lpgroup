#!/usr/bin/env python3
"""What every room is, and what the architect drew in it.

    python3 tools/plan_rooms.py [--pages 3,5] [--no-check]

Input : blender/plans/plans.pdf, blender/plans/plan.json (read only)
Output: blender/plans/rooms.json
        blender/plans/check/rooms_NN.png (page raster with rooms coloured by
        kind, names, and every recognised symbol as its oriented box)

The sheets print no room names.  They do draw furniture and sanitary
symbols, and those are what this reads:

SYMBOLS
    Every symbol on the sheets is a CAD block that the PDF writes as a run
    of consecutive paths: white-filled shapes (the block masks the floor
    tone) followed by their 0.368 black strokes.  So:
      1. walk the page's paths in document order and cut them into runs of
         white fills / black fills / 0.368 strokes whose boxes touch (gap
         <= 4 paths, <= 6 cm), inside the flat / office / balcony fills;
      2. inside a run, white shapes that touch (1.2 cm) form one PIECE; a
         stroke belongs to the piece whose outline holds 70 % of its points;
      3. a piece is named by its size, white-shape count and shape (the
         clusters were named once by looking at crops of them; the table is
         KIND_RULES below).  Beds come with their two night stands and the
         office desk blocks with their chairs: those are exploded into
         their parts.
    Not white-filled, so found separately:
      * kitchen runs: an open 0.368 polyline in front of a wall (the
        architect draws the worktop's front edge only, no sink or hob).
        The line splits the room; the thin side (0.45 - 0.9 m deep) is the
        worktop;
        The same front-edge-only line inside a wet room is a rectangular
        bath (<= 0.85 m deep) or walk-in shower; a line there that fits
        neither is kept as `partition_line` and reported;
      * vent ducts: the 1.2 x 0.25 black-filled wedge bars in the
        wet-room / kitchen walls.
    Office blocks: 4 L-desks, a chair in each desk's crook and a small
    two-part black glyph at each desk's inner corner (`desk_equipment`:
    monitor or phone, too small to tell).
    Heading = the direction the piece FACES (bed: head -> foot; sofa, WC,
    basin, TV, worktop: away from the wall it backs onto), as degrees of
    atan2(dy, dx) in the plan frame (0 = +x, 90 = +y = street side).
    size = [width across the heading, depth along it].

ROOMS
    plan.json's rooms (flat fill minus wall poche, cut at closed door
    leaves) are the free floor of each room ("area_net").  Each flat fill
    is then partitioned among its rooms by nearest room boundary (walls
    and door throats split down their middle), so every square metre of
    the flat belongs to exactly one room ("area"; sums to the flat fill).
    Slivers < 1.0 m2 with nothing in them are merged into the neighbour
    they share most boundary with.  The kind comes from the symbols in
    the room, then the entrance door, then size.

    A room holding a WC/bath and anything else, or two double beds, lost
    a wall/door on the sheet: it is cut at the narrowest neck between the
    groups (erosion) and reported.  Bed + sofa/kitchen in one room is a
    `studio` room, not an error.

PER FLAT: bedrooms -> type, `layout_group` (same fill + rooms under one
of the 8 plan symmetries) and `kit_group` (also every drawn piece within
0.35 m: one furniture kit fits all), with `*_same_as` {flat, rotate_deg,
mirror_x} pointing at the group's representative, aspect from window directions (-y north, +y south/street,
-x west, +x east; 'courtyard' = over the podium terrace), and the nearest
core by walking distance along the corridor (8-connected 10 cm raster of
corridor minus walls, from the entrance door to the core's stair/lift
hall).
"""
import json
import math
import os
import sys
from collections import Counter, defaultdict

import numpy as np
from shapely import contains_xy, make_valid, set_precision, voronoi_polygons
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.ops import polylabel, split, unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan_extract as pe  # noqa: E402  (read-only use: Page, poly helpers)

ROOT = os.path.dirname(HERE)
PLANS = os.path.join(ROOT, 'blender', 'plans')
PDF = os.path.join(PLANS, 'plans.pdf')
WHITE = 'rgb(100%, 100%, 100%)'
BLACK = pe.BLACK
MITRE = dict(join_style=2)
EYE = 1.6

NAMES = {
    'living_kitchen': ('Living room with kitchen', 'მისაღები სამზარეულოთი'),
    'living': ('Living room', 'მისაღები'),
    'studio': ('Studio room', 'სტუდიო ოთახი'),
    'kitchen': ('Kitchen', 'სამზარეულო'),
    'bedroom': ('Bedroom', 'საძინებელი'),
    'bathroom': ('Bathroom', 'სააბაზანო'),
    'wc': ('WC', 'საპირფარეშო'),
    'hall': ('Entrance hall', 'შესასვლელი ჰოლი'),
    'corridor': ('Hallway', 'დერეფანი'),
    'storage': ('Storage', 'საკუჭნაო'),
    'balcony': ('Balcony', 'აივანი'),
    'loggia': ('Loggia', 'ლოჯია'),
    'office': ('Office space', 'საოფისე სივრცე'),
    'room': ('Room', 'ოთახი'),
}
KIND_COLOUR = {
    'living_kitchen': (255, 214, 120), 'studio': (255, 170, 200), 'living': (255, 190, 90), 'kitchen': (255, 150, 60),
    'bedroom': (150, 190, 255), 'bathroom': (120, 230, 230), 'wc': (170, 240, 200),
    'hall': (225, 225, 170), 'corridor': (235, 235, 200), 'storage': (200, 170, 140),
    'balcony': (200, 200, 200), 'loggia': (180, 180, 180), 'office': (230, 180, 240),
    'room': (255, 80, 80),
}
ABBR = dict(bed_double='bed', nightstand='ns', sofa='sofa', table_round='tbl', chair='ch',
            table_coffee='ct', tv='tv', wc='WC', basin='bas', bath_corner='bath',
            shower_corner='shwr', bath='bath', shower='shwr', partition_line='line', kitchen_run='kit', vent_duct='vent', desk='desk',
            office_chair='och', desk_equipment='eq', unknown='??')


def rnd(v, k=3):
    return round(float(v), k)


def pjson(p, k=3):
    return pe.poly_json(p, k)


def pj(d):
    from shapely import make_valid
    p = Polygon(d['outline'], d.get('holes') or [])
    if not p.is_valid:
        p = unary_union([q for q in pe.polys_of(make_valid(p))])
    return p


def ptj(p, k=3):
    return [rnd(p[0], k), rnd(p[1], k)]


# ------------------------------------------------------------------ symbols
def page_items(pg):
    out = []
    for i, it in enumerate(pg.items):
        if not it.subs:
            continue
        if it.fill == WHITE:
            c = 'W'
        elif it.fill == BLACK:
            c = 'K'
        elif it.stroke == BLACK and it.sw == 0.368 and it.fill in (None, 'none'):
            c = 'S'
        else:
            continue
        subs = [(pg.pts_m(s), cl, cv) for s, cl, cv in it.subs]
        pts = np.vstack([s for s, _, _ in subs])
        out.append(dict(i=i, c=c, subs=subs, pts=pts, bb=(*pts.min(0), *pts.max(0))))
    return out


def filled(it):
    """White shape -> filled polygon (outer rings; the even-odd hole of a
    bed frame is part of the bed)."""
    g = []
    for a, cl, cv in it['subs']:
        if len(a) < 3:
            continue
        p = Polygon(a)
        if not p.is_valid:
            p = p.buffer(0)
        if p.area > 1e-5:
            g.append(p)
    if not g:
        return None
    u = unary_union(g)
    return u if u.area > 2e-4 else None


def runs(items, mask):
    G, cur, last = [], None, -99
    for it in items:
        x0, y0, x1, y1 = it['bb']
        if (x1 - x0) > 8 or (y1 - y0) > 8:
            continue
        if not contains_xy(mask, (x0 + x1) / 2, (y0 + y1) / 2):
            continue
        b = cur['bb'] if cur else None
        if cur and it['i'] - last <= 4 and x0 < b[2] + 0.06 and x1 > b[0] - 0.06 and y0 < b[3] + 0.06 and y1 > b[1] - 0.06:
            cur['items'].append(it)
            cur['bb'] = (min(b[0], x0), min(b[1], y0), max(b[2], x1), max(b[3], y1))
        else:
            cur = dict(items=[it], bb=it['bb'])
            G.append(cur)
        last = it['i']
    return G


def pieces_of(run):
    W = [(it, filled(it)) for it in run['items'] if it['c'] == 'W']
    W = [(it, w) for it, w in W if w is not None]
    comps = []
    for it, w in W:
        hit = [c for c in comps if c['poly'].buffer(0.012).intersects(w)]
        if hit:
            base = hit[0]
            for h in hit[1:]:
                base['ws'] += h['ws']
                base['poly'] = unary_union([base['poly'], h['poly']])
                comps.remove(h)
            base['ws'].append(w)
            base['poly'] = unary_union([base['poly'], w])
        else:
            comps.append(dict(ws=[w], poly=w, strokes=[]))
    loose = []
    for it in run['items']:
        if it['c'] != 'S':
            continue
        best = None
        for c in comps:
            bp = c['poly'].buffer(0.03)
            f = contains_xy(bp, it['pts'][:, 0], it['pts'][:, 1]).mean()
            if f >= 0.7 and (best is None or f > best[0]):
                best = (f, c)
        (best[1]['strokes'] if best else loose).append(it)
    return comps, loose


def obb(g):
    """-> centre, (long, short), unit vector of the long side, corner ring."""
    r = g.minimum_rotated_rectangle
    if r.geom_type != 'Polygon':
        r = g.envelope.buffer(0.01)
    q = np.array(r.exterior.coords)[:4]
    e1, e2 = q[1] - q[0], q[2] - q[1]
    l1, l2 = np.hypot(*e1), np.hypot(*e2)
    if l1 >= l2:
        return q.mean(0), (l1, l2), e1 / max(l1, 1e-9), q
    return q.mean(0), (l2, l1), e2 / max(l2, 1e-9), q


def is_circle(w):
    c, (L, W), _, _ = obb(w)
    if abs(L - W) > 0.06 * L:
        return False
    cc = np.array(w.centroid.coords[0])
    return np.hypot(*(cc - c)) < 0.04 * L and abs(w.area / (L * W) - math.pi / 4) < 0.06


def classify(comp):
    """piece -> [(kind, polygon, strokes_pts)] (exploded where needed)."""
    poly = comp['poly']
    c, (L, W), u, _ = obb(poly)
    ws = sorted(comp['ws'], key=lambda w: -w.area)
    nW = len(ws)
    ink = np.vstack([a for it in comp['strokes'] for a, _, _ in it['subs']]) if comp['strokes'] else np.zeros((0, 2))
    curved = any(cv for it in comp['strokes'] for _, _, cv in it['subs'])
    if L < 0.3 or W < 0.12:
        return []
    # bed + night stands (2.8 x 2.0) or a bare bed (2.0 x 1.8)
    if ws[0].area > 2.5 and 1.7 <= W <= 2.2:
        bed = ws[0]
        out = [('bed_double', bed, ink)]
        rest = [w for w in ws[1:] if not bed.buffer(0.01).contains(w)]
        for g in merge_touching(rest):
            out.append(('nightstand', g, np.zeros((0, 2))))
        return out
    if L > 2.5 and nW >= 8:            # office block: 4 desks + chairs
        out = []
        desks = [w for w in ws if w.area > 0.4]
        for d in desks:
            out.append(('desk', d, np.zeros((0, 2))))
        rest = [w for w in ws if w.area <= 0.4]
        # the diamond in each L-desk's crook is the chair; the small black
        # two-part glyph at the desk's inner corner is desk equipment
        # (monitor / phone - too small to tell)
        chairs = [w for w in rest if w.area > 0.12]
        small = [w for w in rest if w.area <= 0.12]
        for g in merge_touching(chairs, 0.012):
            out.append(('office_chair', g, np.zeros((0, 2))))
        for g in merge_touching(small, 0.12):
            out.append(('desk_equipment', g, np.zeros((0, 2))))
        return out
    if 1.6 <= L <= 2.4 and 0.75 <= W <= 1.1 and nW >= 3:
        return [('sofa', poly, ink)]
    if 0.6 <= L <= 1.0 and 0.12 <= W <= 0.3:
        return [('tv', poly, ink)]
    if 0.9 <= L <= 1.45 and 0.45 <= W <= 0.7 and nW == 1 and poly.area / (L * W) > 0.9:
        return [('table_coffee', poly, ink)]
    if nW == 1 and 0.6 <= L <= 1.5 and is_circle(ws[0]):
        return [('table_round', poly, ink)]
    if 0.5 <= L <= 0.75 and 0.33 <= W <= 0.55 and nW >= 2:
        small = sorted(w.area for w in ws)[0]
        return [('basin' if small < 0.02 else 'wc', poly, ink)]
    if 0.62 <= L <= 1.45 and curved and nW <= 2:
        return [('bath_corner' if L >= 1.2 else 'shower_corner', poly, ink)]
    if 0.33 <= L <= 0.66 and 0.28 <= W <= 0.66:
        return [('chair' if nW == 1 else 'office_chair', poly, ink)]
    return [('unknown', poly, ink)]


def merge_touching(ws, tol=0.012):
    groups = []
    for w in ws:
        hit = [g for g in groups if g.buffer(tol).intersects(w)]
        g = unary_union(hit + [w])
        groups = [x for x in groups if x not in hit] + [g]
    return groups


def worktop_rect(a, walls):
    """A closed axis-aligned rectangle 0.5-0.8 deep and 1.0-4.2 long with
    one long side on a wall face -> its other three sides (open polyline),
    else None."""
    a = np.asarray(a)
    x0, y0, x1, y1 = a[:, 0].min(), a[:, 1].min(), a[:, 0].max(), a[:, 1].max()
    dx, dy = x1 - x0, y1 - y0
    if not (len(a) in (4, 5) and min(dx, dy) > 0.5 and min(dx, dy) < 0.8 and 1.0 < max(dx, dy) < 4.2):
        return None
    if np.any(np.minimum(np.abs(a[:, 0][:, None] - [x0, x1]).min(1), np.abs(a[:, 1][:, None] - [y0, y1]).min(1)) > 0.01):
        return None                               # not a rectangle
    if dx >= dy:
        sides = [((x0, y0), (x1, y0), (x1, y1), (x0, y1)), ((x0, y1), (x1, y1), (x1, y0), (x0, y0))]
    else:
        sides = [((x0, y0), (x0, y1), (x1, y1), (x1, y0)), ((x1, y0), (x1, y1), (x0, y1), (x0, y0))]
    # sides[k]: the wall-side edge is the first pair's opposite; test which long edge is on a wall
    best = None
    for poly in sides:
        back = LineString([poly[2], poly[3]]) if dx >= dy else LineString([poly[2], poly[3]])
        d = walls.distance(back.interpolate(0.5, normalized=True))
        if best is None or d < best[0]:
            best = (d, poly)
    if best[0] > 0.06:
        return None
    p = best[1]
    # free sides: wall-end -> front edge -> wall-end  (p[3] -> p[0] -> p[1] -> p[2])
    return np.array([p[3], p[0], p[1], p[2]], dtype=float)


def kitchen_lines(items, runs_, mask_flats, hinges, balc, walls):
    """Open thin polylines that are not part of a white symbol."""
    in_white = set()
    for r in runs_:
        if any(it['c'] == 'W' for it in r['items']):
            in_white.update(it['i'] for it in r['items'])
    tables = []
    for it in items:
        if it['c'] == 'S' and len(it['pts']) == 5:
            x0, y0, x1, y1 = it['bb']
            if 2.85 < x1 - x0 < 3.15 and 0.9 < y1 - y0 < 1.1:
                tables.append(box(x0, y0, x1, y1).buffer(0.03))
    tables = unary_union(tables) if tables else Polygon()
    out = []
    for it in items:
        if it['c'] != 'S' or it['i'] in in_white:
            continue
        if any(cv for _, _, cv in it['subs']):
            continue
        x0, y0, x1, y1 = it['bb']
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if not contains_xy(mask_flats, cx, cy):
            continue
        if contains_xy(balc, cx, cy) or tables.contains(MultiPoint(it['pts'])):
            continue
        for a, cl, cv in it['subs']:
            if len(a) < 2:
                continue
            ln = float(np.hypot(*np.diff(a, axis=0).T).sum())
            if ln < 0.6:
                continue
            sg = np.diff(a, axis=0)
            sg = sg[np.hypot(sg[:, 0], sg[:, 1]) > 0.02]
            if len(sg) and np.any(np.minimum(np.abs(sg[:, 0]), np.abs(sg[:, 1])) > 0.03 * np.hypot(sg[:, 0], sg[:, 1])):
                continue                          # slanted strokes: facade fold marks, not worktops
            dd = sorted([np.ptp(a[:, 0]), np.ptp(a[:, 1])])
            if 2.8 < dd[1] < 3.15 and (0.9 < dd[0] < 1.1 or dd[0] < 0.01):
                continue                          # area-label table
            if cl or (len(a) >= 5 and np.hypot(*(a[0] - a[-1])) < 0.01):
                # A closed outline is a label box or a balcony line - or, on
                # some sheets (flats 11 / 32 / 53 ... in the wing), the
                # worktop drawn as a whole rectangle whose back edge lies on
                # the wall. Kept as its three free sides, so it splits its
                # room the way the usual front-edge line does.
                fr = worktop_rect(a, walls)
                if fr is not None:
                    out.append(fr)
                continue
            # A door leaf is one straight stroke about a door wide that starts
            # at a hinge. A worktop line may END at the jamb of a door beside
            # it (flat 8 and its stack: the run stops 4 cm from the hinge), so
            # touching a hinge alone does not make a line a leaf.
            if len(hinges) and len(a) <= 3 and ln < 1.25 and \
                    np.min(np.hypot(hinges[:, None, 0] - a[None, :, 0], hinges[:, None, 1] - a[None, :, 1])) < 0.07:
                continue                          # door leaf
            out.append(np.asarray(a))
    return out


def extend(a, d=0.15):
    a = np.array(a, dtype=float)
    v0 = a[0] - a[1]
    v1 = a[-1] - a[-2]
    a[0] = a[0] + v0 / max(np.hypot(*v0), 1e-9) * d
    a[-1] = a[-1] + v1 / max(np.hypot(*v1), 1e-9) * d
    return a


def rect_legs(P):
    """Worktop polygon (axis-aligned L / I / U) -> its straight legs: the
    largest inscribed axis-aligned rectangle, then the largest in what is
    left, while pieces > 0.1 m2 remain."""
    legs = []
    rest = P
    for _ in range(4):
        ps = [p for p in pe.polys_of(rest) if p.area > 0.1]
        if not ps:
            break
        Q = max(ps, key=lambda p: p.area)
        c = np.array(Q.exterior.coords)
        xs = sorted(set(np.round(c[:, 0], 3)))
        ys = sorted(set(np.round(c[:, 1], 3)))
        Qb = Q.buffer(0.003, **MITRE)
        best = None
        for i in range(len(xs)):
            for j in range(i + 1, len(xs)):
                for k in range(len(ys)):
                    for m in range(k + 1, len(ys)):
                        a = (xs[j] - xs[i]) * (ys[m] - ys[k])
                        if best is not None and a <= best[0]:
                            continue
                        r = box(xs[i], ys[k], xs[j], ys[m])
                        if Qb.contains(r):
                            best = (a, r)
        if best is None:
            legs.append(Q.minimum_rotated_rectangle)
            break
        legs.append(best[1])
        rest = rest.difference(best[1].buffer(0.003, **MITRE))
    return legs


def legs_from_line(line, poly, walls):
    """The worktop's straight legs, read off the FRONT-EDGE line the sheet
    draws rather than off the worktop polygon (which carries every column
    notch of the wall behind it and came apart into slivers).

    A segment at either end of the line that runs back to a wall is a
    return (the worktop's end), every other segment is a front. Each front
    is swept back to the wall behind it; where two fronts meet in a corner
    the corner square goes to the longer one, so legs never overlap.
    -> [(centre, facing unit vector, length, depth, depth_assumed)]"""
    a = np.asarray(line, dtype=float)
    keep = [a[0]]
    for p in a[1:]:
        if np.hypot(*(p - keep[-1])) > 0.02:
            keep.append(p)
    # a stroke that doubles back on itself (flat 15: up into the duct and
    # down again) is one segment to where it ends up
    k = 1
    while k < len(keep) - 1:
        u = keep[k] - keep[k - 1]
        v = keep[k + 1] - keep[k]
        if abs(u[0] * v[1] - u[1] * v[0]) < 1e-4 * (np.hypot(*u) * np.hypot(*v) + 1e-9) and float(np.dot(u, v)) < 0:
            del keep[k]
            k = max(1, k - 1)
        else:
            k += 1
    # the sheet runs some lines on into the wall they stop at: trim each end
    # back to the wall face, so a return ends where the room does
    wb = walls.buffer(0.003)
    for end in (0, -1):
        if len(keep) < 2:
            break
        p0 = keep[end]
        p1 = keep[1] if end == 0 else keep[-2]
        if wb.contains(Point(p0)):
            seg = LineString([p1, p0]).difference(wb)
            gs = [x for x in getattr(seg, 'geoms', [seg]) if not x.is_empty and x.geom_type == 'LineString']
            if gs:
                g0 = min(gs, key=lambda x: x.distance(Point(p1)))
                c0 = np.array(g0.coords)
                keep[end] = c0[np.argmax(np.hypot(*(c0 - p1).T))]
    a = np.array(keep)
    if len(a) < 2:
        return []
    segs = [(a[i], a[i + 1]) for i in range(len(a) - 1)]
    front = [True] * len(segs)
    for i in (0, len(segs) - 1):
        p0, p1 = segs[i]
        if len(segs) > 1 and np.hypot(*(p1 - p0)) < 1.0:
            outer = p0 if i == 0 else p1
            if walls.distance(Point(outer)) < 0.10:
                front[i] = False
    pb = poly.buffer(0.02)
    info = []
    for i, (p0, p1) in enumerate(segs):
        if not front[i]:
            info.append(None)
            continue
        d = p1 - p0
        L = float(np.hypot(*d))
        d = d / max(L, 1e-9)
        n = np.array([-d[1], d[0]])
        m = (p0 + p1) / 2
        # the worktop lies behind the front: n must point away from it
        if pb.contains(Point(m + n * 0.08)) and not pb.contains(Point(m - n * 0.08)):
            n = -n
        deps = []
        for t in (0.2, 0.5, 0.8):
            q = p0 + (p1 - p0) * t
            dd = 0.0
            while dd < 1.2 and not walls.contains(Point(q - n * (dd + 0.01))):
                dd += 0.01
            deps.append(dd)
        # the deepest sample: a duct or a column standing in the wall behind
        # part of a run does not make the whole run shallower
        dep = float(max(deps))
        if dep >= 1.19:
            dep = 0.6                              # nothing behind it: a standard worktop
        # ...and where the sheet draws the worktop's end, that return IS its
        # depth - for every leg of the run: a worktop is one depth all round,
        # and a duct drawn inside it (flat 7) is boxed in behind the units
        rets = [float(np.hypot(*(segs[j][1] - segs[j][0]))) for j in range(len(segs)) if not front[j]]
        if rets and max(rets) >= 0.5:
            dep = max(rets)
        assumed = False
        if dep < 0.5:
            # what is behind the line is a column or a duct, not the wall the
            # units stand on: a standard 0.60 run, flagged
            dep, assumed = 0.6, True
        info.append(dict(p0=p0, p1=p1, d=d, n=n, L=L, dep=min(dep, 0.9), assumed=assumed))
    # corners: consecutive fronts share an end; the longer leg takes the square
    for i in range(len(info) - 1):
        A, B = info[i], info[i + 1]
        if A is None or B is None:
            continue
        if A['L'] >= B['L']:
            A['p1'] = A['p1'] + A['d'] * B['dep']
            A['L'] += B['dep']
        else:
            B['p0'] = B['p0'] - B['d'] * A['dep']
            B['L'] += A['dep']
    out = []
    for I in info:
        if I is None or I['L'] < 0.3:
            continue
        c = (I['p0'] + I['p1']) / 2 - I['n'] * I['dep'] / 2
        out.append((c, snap_dir(I['n']), I['L'], I['dep'], I['assumed']))
    return out


# ------------------------------------------------------------------ geometry helpers
def heading_from_wall(q, walls, max_d=0.14, long_sides=False):
    """OBB corners -> facing unit vector: away from the side nearest a wall
    (only the two long sides with long_sides)."""
    best = None
    Lmax = max(np.hypot(*(q[(k + 1) % 4] - q[k])) for k in range(4))
    for k in range(4):
        a, b = q[k], q[(k + 1) % 4]
        if long_sides and np.hypot(*(b - a)) < Lmax - 1e-6 and abs(np.hypot(*(b - a)) - Lmax) > 0.02:
            continue
        ds = [walls.distance(Point(a + (b - a) * t)) for t in (0.25, 0.5, 0.75)]
        d = float(np.mean(ds))
        if best is None or d < best[0]:
            mid = (a + b) / 2
            best = (d, mid)
    d, mid = best
    if d > max_d:
        return None
    v = q.mean(0) - mid
    return v / max(np.hypot(*v), 1e-9)


def heading_from_ink(centre, u, ink, length_axis):
    """Facing = away from where the drawing has more lines (pillows,
    back cushions, cistern).  length_axis=True: along the long side."""
    if len(ink) < 4:
        return None
    ax = u if length_axis else np.array([-u[1], u[0]])
    off = float(((ink - centre) @ ax).mean())
    if abs(off) < 0.01:
        return None
    return -ax if off > 0 else ax


def ang(v):
    a = round(math.degrees(math.atan2(v[1], v[0])) % 360.0, 1)
    return 0.0 if a >= 360.0 else a


def size_along(L, W, u, h):
    """width across heading, depth along heading."""
    if abs(float(np.dot(u, h))) > 0.7:     # heading along the long side
        return [rnd(W), rnd(L)]
    return [rnd(L), rnd(W)]


def snap_dir(v):
    """unit vector -> nearest of the 4 axis directions when within 10 deg."""
    a = math.atan2(v[1], v[0])
    s = round(a / (math.pi / 2)) * (math.pi / 2)
    if abs(a - s) < math.radians(10):
        return np.array([math.cos(s), math.sin(s)])
    return v


# ------------------------------------------------------------------ rooms
def partition(flat_poly, rooms):
    """Every point of the flat -> the room whose boundary is nearest.  The
    rooms keep their own floor; what is left (walls, door throats) is cut
    by the Voronoi cells of points sampled along the room boundaries."""
    pts, owner = [], []
    for k, r in enumerate(rooms):
        for p in pe.polys_of(r):
            for ring in [p.exterior] + list(p.interiors):
                n = max(int(ring.length / 0.05), 8)
                for t_ in np.linspace(0, ring.length, n, endpoint=False):
                    q = ring.interpolate(t_)
                    pts.append((q.x, q.y))
                    owner.append(k)
    pts = np.array(pts)
    owner = np.array(owner)
    Fv = set_precision(make_valid(flat_poly), 1e-5)
    base = [set_precision(make_valid(r).intersection(Fv), 1e-5) for r in rooms]
    left = Fv.difference(unary_union(base))
    acc = defaultdict(list)
    if not left.is_empty and left.area > 1e-6:
        env = flat_poly.envelope.buffer(2.0)
        cells = voronoi_polygons(MultiPoint(pts), extend_to=env)
        for cell in cells.geoms:
            cell = make_valid(cell)
            if not cell.intersects(left):
                continue
            c = cell.centroid
            k = int(owner[np.argmin((pts[:, 0] - c.x) ** 2 + (pts[:, 1] - c.y) ** 2)])
            piece = cell.intersection(left)
            if not piece.is_empty:
                acc[k].append(piece)
    out = []
    for k in range(len(rooms)):
        g = unary_union([base[k]] + acc[k]) if acc[k] else base[k]
        out.append(set_precision(g, 1e-5))
    return out


def largest(g):
    ps = pe.polys_of(g)
    return max(ps, key=lambda p: p.area) if ps else g


GROUP = dict(bed_double='sleep', wc='wet', basin='wet', shower_corner='wet', bath_corner='wet',
             sofa='live', table_round='live', table_coffee='live')


def split_mixed(net, usyms, flines, notes):
    out = []
    for room in net:
        pts = [(GROUP[s['kind']], np.array(s['g'].centroid.coords[0])) for s in usyms
               if s['kind'] in GROUP and room.buffer(0.02).contains(s['g'].centroid)]
        # each double bed is its own group: two beds in one room means a
        # wall / door between two bedrooms was not found
        nb = 0
        for i, (g, p) in enumerate(pts):
            if g == 'sleep':
                pts[i] = ('sleep%d' % nb, p)
                nb += 1
        groups = set(g for g, _ in pts)
        # bed + sofa / kitchen in one room is a studio, not an error:
        # split only a WC / bath sharing a room with anything else, or two beds
        if len(groups) < 2 or ('wet' not in groups and nb < 2):
            out.append(room)
            continue
        done = False
        for r in np.arange(0.15, 0.9, 0.05):
            comps = [c for c in pe.polys_of(room.buffer(-r, **MITRE)) if c.area > 0.3]
            if len(comps) < 2:
                continue
            lab = defaultdict(set)
            for g, p in pts:
                k = min(range(len(comps)), key=lambda j: comps[j].distance(Point(p)))
                lab[k].add(g)
            if any(len(v) > 1 and not (nb < 2 and 'wet' not in v) for v in lab.values()):
                continue
            used = [comps[k] for k in sorted(lab)]
            rest = [c for j, c in enumerate(comps) if j not in lab]
            parts = partition(room, used + rest)
            # empty eroded parts join the neighbour they touch most
            pieces = [p for p in parts[:len(used)]]
            for q in parts[len(used):]:
                j = max(range(len(pieces)), key=lambda j: pieces[j].buffer(0.02).intersection(q).area)
                pieces[j] = unary_union([pieces[j], q])
            pieces = [largest(p.intersection(room)) for p in pieces]
            notes.append('room %.1f m2 holding %s split at a %.2f m neck (door leaf not found)'
                         % (room.area, '+'.join(sorted(groups)), 2 * r))
            out += pieces
            done = True
            break
        if not done:
            out.append(room)
    return out


# ------------------------------------------------------------------ walking distance
class Walk:
    def __init__(self, free, step=0.1):
        x0, y0, x1, y1 = free.bounds
        self.x0, self.y0, self.s = x0, y0, step
        self.nx, self.ny = int((x1 - x0) / step) + 2, int((y1 - y0) / step) + 2
        X, Y = np.meshgrid(x0 + (np.arange(self.nx) + 0.5) * step, y0 + (np.arange(self.ny) + 0.5) * step)
        self.ok = contains_xy(free, X, Y)
        self.X, self.Y = X, Y

    def cell(self, p):
        i = int((p[1] - self.y0) / self.s)
        j = int((p[0] - self.x0) / self.s)
        if 0 <= i < self.ny and 0 <= j < self.nx and self.ok[i, j]:
            return i, j
        ii, jj = np.nonzero(self.ok)
        k = np.argmin((self.X[ii, jj] - p[0]) ** 2 + (self.Y[ii, jj] - p[1]) ** 2)
        return int(ii[k]), int(jj[k])

    def dist_from(self, p):
        import heapq
        D = np.full(self.ok.shape, np.inf)
        s = self.cell(p)
        D[s] = 0
        h = [(0.0, s)]
        nb = [(-1, 0, 1), (1, 0, 1), (0, -1, 1), (0, 1, 1), (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]
        while h:
            d, (i, j) = heapq.heappop(h)
            if d > D[i, j]:
                continue
            for di, dj, w in nb:
                a, b = i + di, j + dj
                if 0 <= a < self.ny and 0 <= b < self.nx and self.ok[a, b]:
                    nd = d + w * self.s
                    if nd < D[a, b]:
                        D[a, b] = nd
                        heapq.heappush(h, (nd, (a, b)))
        return D


# ------------------------------------------------------------------ main work per page
def process_page(n, P, issues):
    pg = pe.Page(PDF, n)
    lev = [l for l in P['levels'] if l['page'] == n][0]
    units = [f for f in P['flats'] + P['offices'] if f['page'] == n]
    is_office = lev['kind'] == 'offices'
    walls = unary_union([pj(p) for p in lev['walls']['poche']])
    outline = pj(lev['outline'])
    fpolys = {u['number']: pj(u['polygon']) for u in units}
    balc = unary_union([pj(b['polygon']) for u in units for b in u['balconies']] +
                       [pj(b['polygon']) for b in lev.get('common_loggias', [])])
    mask = unary_union(list(fpolys.values()) + [balc]).buffer(0.05)
    mask_flats = unary_union(list(fpolys.values())).buffer(0.02)
    items = page_items(pg)
    R = runs(items, mask)
    hinges = np.array([d['hinge'] for d in lev['doors']]) if lev['doors'] else np.zeros((0, 2))

    # ---- symbols
    syms = []
    unknown = []
    for r in R:
        comps, loose = pieces_of(r)
        for comp in comps:
            for kind, g, ink in classify(comp):
                syms.append(dict(kind=kind, g=g, ink=ink))
        if not comps:
            for it in r['items']:
                if it['c'] != 'K':
                    continue
                g = filled(it)
                if g is None:
                    continue
                c, (L, W), u, q = obb(g)
                if 0.9 <= L <= 1.5 and 0.15 <= W <= 0.35:
                    syms.append(dict(kind='vent_duct', g=g, ink=np.zeros((0, 2))))
    # vent ducts sit in the walls, partly outside the fills: second pass on black fills
    have = [s['g'] for s in syms if s['kind'] == 'vent_duct']
    big = mask_flats.buffer(0.35)
    for it in items:
        if it['c'] != 'K':
            continue
        g = filled(it)
        if g is None:
            continue
        c, (L, W), u, q = obb(g)
        if 0.9 <= L <= 1.5 and 0.15 <= W <= 0.35 and contains_xy(big, *c) and not any(h.intersects(g) for h in have):
            syms.append(dict(kind='vent_duct', g=g, ink=np.zeros((0, 2))))
            have.append(g)

    # the same block drawn twice on top of itself counts once
    ded = []
    for s in syms:
        c = s['g'].centroid
        if any(o['kind'] == s['kind'] and o['g'].centroid.distance(c) < 0.05 for o in ded):
            continue
        ded.append(s)
    syms = ded
    # ---- kitchen runs (open polylines)
    lines = kitchen_lines(items, R, mask_flats, hinges, balc.buffer(0.05), walls)

    # ---- per unit
    out = {}
    all_room_draw = []
    for u in units:
        num = u['number']
        F = fpolys[num]
        net = [pj(r['polygon']) for r in u['rooms']]
        net = [r for r in net if r.area > 0.05]
        rec_issues = []
        # pieces of the flat not covered by any plan room and large enough to be a room
        cover = unary_union(net) if net else Polygon()
        left = F.difference(cover).difference(walls.buffer(0.005))
        for p in pe.polys_of(left.buffer(-0.15, **MITRE).buffer(0.15, **MITRE)):
            if p.area > 0.8:
                net.append(p)
                rec_issues.append('room recovered from fill not covered by plan rooms (%.2f m2)' % p.area)
        # unit symbols
        usyms = [s for s in syms if F.buffer(0.05).contains(s['g'].centroid) or
                 (s['kind'] == 'vent_duct' and F.distance(s['g'].centroid) < 0.35 and
                  min(fpolys.values(), key=lambda q: q.distance(s['g'].centroid)) is F)]
        # rooms where a door leaf was not found hold two rooms' furniture
        # (bed + WC, ...): cut them at the narrowest neck between the groups
        flines = [a for a in lines if F.buffer(0.05).contains(LineString(a).centroid)]
        net = split_mixed(net, usyms, flines, rec_issues)
        # kitchen runs -> split a net room
        klist = []
        for a in lines:
            ls = LineString(a)
            if not F.buffer(0.05).contains(ls.centroid):
                continue
            host = [k for k, r in enumerate(net) if r.buffer(0.05).intersects(ls)]
            if not host:
                continue
            k = max(host, key=lambda k: net[k].intersection(ls.buffer(0.05)).area)
            cutter = LineString(extend(a, 0.2)).buffer(0.004, cap_style=2, join_style=2)
            parts = [q for q in pe.polys_of(net[k].difference(cutter)) if q.area > 0.05]
            if len(parts) < 2:
                rec_issues.append('line at %.2f,%.2f did not split its room' % ls.centroid.coords[0])
                continue
            parts.sort(key=lambda p: -p.area)
            near = [q for q in parts[1:] if q.distance(ls) < 0.02]
            cand = unary_union([q.buffer(0.004, join_style=2) for q in near]).intersection(net[k]) if near else parts[-1]
            if cand.is_empty:
                continue
            depth = 2 * cand.area / max(cand.length, 1e-6) * 1.15
            if not (0.3 < depth < 1.3):
                rec_issues.append('line at %.2f,%.2f: piece %.2f m2 depth %.2f is not a worktop' % (*ls.centroid.coords[0], cand.area, depth))
                continue
            klist.append(dict(poly=cand, line=a, room=k, depth=depth))
        # ---- partition and room records
        if not net:
            issues.append(dict(unit=num, issue='no rooms'))
            continue
        share = partition(F, net)
        # merge empty slivers
        def sym_in(g):
            return [s for s in usyms if s['kind'] != 'vent_duct' and g.buffer(0.02).contains(s['g'].centroid)]
        changed = True
        while changed:
            changed = False
            for k in range(len(net)):
                if net[k].area < 1.0 and not sym_in(share[k]) and not any(kl['room'] == k for kl in klist) and len(net) > 1:
                    nb = max((j for j in range(len(net)) if j != k),
                             key=lambda j: share[k].buffer(0.02).intersection(share[j]).area)
                    rec_issues.append('sliver %.2f m2 merged' % net[k].area)
                    net[nb] = unary_union([net[nb], net[k]])
                    share[nb] = unary_union([share[nb], share[k]])
                    for kl in klist:
                        if kl['room'] > k:
                            kl['room'] -= 1
                        elif kl['room'] == k:
                            kl['room'] = nb if nb < k else nb - 1
                    del net[k], share[k]
                    changed = True
                    break
        # doors (with room sides)
        doors = u['doors']
        ent_c = [np.array(d['centre']) for d in u['entrance']]
        if not ent_c and u.get('entrance_suggested'):
            ent_c = [np.array(u['entrance_suggested']['centre'])]

        def where(p):
            pt = Point(p)
            for k, g in enumerate(share):
                if g.buffer(0.005).contains(pt):
                    return k
            return None

        def side_name(p):
            k = where(p)
            if k is not None:
                return k
            for bi, b in enumerate(u['balconies']):
                if pj(b['polygon']).buffer(0.05).contains(Point(p)):
                    return 'balcony:%d' % bi
            for c in lev['corridor']:
                if pj(c).buffer(0.05).contains(Point(p)):
                    return 'corridor'
            return 'outside'
        door_recs = []
        for di, d in enumerate(doors):
            h, e = np.array(d['hinge']), np.array(d['closed_end'])
            v = (e - h) / max(np.hypot(*(e - h)), 1e-9)
            nrm = np.array([-v[1], v[0]])
            m = (h + e) / 2
            a, b = side_name(m + nrm * 0.35), side_name(m - nrm * 0.35)
            door_recs.append(dict(i=di, sides=(a, b), d=d))
        rooms = []
        fur = []
        for k in range(len(net)):
            rooms.append(dict(k=k, net=net[k], share=share[k], syms=[], kitchen=[], doors=[], windows=[]))
        for s in usyms:
            k = where(np.array(s['g'].centroid.coords[0]))
            if k is None:
                k = min(range(len(share)), key=lambda j: share[j].distance(s['g'].centroid))
            rooms[k]['syms'].append(s)
        for kl in klist:
            # the same front-edge-only line in a wet room is a rectangular bath
            sanit = any(s['kind'] in ('wc', 'basin', 'shower_corner', 'bath_corner', 'bath', 'shower') for s in rooms[kl['room']]['syms'])
            c_, (L_, W_), u_, q_ = obb(kl['poly'])
            if sanit and 1.2 <= L_ <= 2.2 and 0.6 <= W_ <= 1.15:
                # bath (<= 0.85 deep) or walk-in shower, drawn as one edge line
                rooms[kl['room']]['syms'].append(dict(kind='bath' if W_ < 0.85 else 'shower', g=kl['poly'], ink=np.zeros((0, 2))))
            elif sanit or kl['depth'] > 0.95:
                a_ = np.asarray(kl['line'])
                ls_ = LineString(a_)
                rooms[kl['room']]['syms'].append(dict(kind='partition_line', g=ls_.buffer(0.01, cap_style=2), ink=np.zeros((0, 2)),
                                                      note='thin line across %s room; the %.2f x %.2f zone beyond it holds no symbol (screen / niche?)' % ('a wet' if sanit else 'a', L_, W_)))
                rec_issues.append('line piece %.2f x %.2f at %.2f,%.2f in %s room: kept as partition_line, zone untyped' % (L_, W_, c_[0], c_[1], 'a wet' if sanit else 'a'))
            else:
                rooms[kl['room']]['kitchen'].append(kl)
        for dr in door_recs:
            for sd in dr['sides']:
                if isinstance(sd, int):
                    rooms[sd]['doors'].append(dr)
        win_dirs = []
        for wi, w in enumerate(u['windows']):
            c = np.array(w['centre'])
            nrm = np.array([0.0, 1.0]) if w['axis'] == 'x' else np.array([1.0, 0.0])
            inn = None
            for sg in (1, -1):
                k = where(c + nrm * sg * 0.45)
                if k is not None:
                    inn = (k, -sg * nrm)
                    break
            if inn is None:
                k = min(range(len(share)), key=lambda j: share[j].distance(Point(c)))
                # outward = away from the flat
                sg = 1 if F.contains(Point(c - nrm * 0.45)) else -1
                inn = (k, sg * nrm)
            rooms[inn[0]]['windows'].append(dict(i=wi, w=w, out=inn[1]))
            win_dirs.append((w, inn[1]))
        # ---- type the rooms
        has_ent = set()
        for c in ent_c:
            k = where(c)
            if k is None:
                k = min(range(len(share)), key=lambda j: share[j].distance(Point(c)))
            has_ent.add(k)
        for r in rooms:
            kinds = Counter(s['kind'] for s in r['syms'])
            r['kinds'] = kinds
            seating = kinds['sofa'] + kinds['table_round'] + kinds['table_coffee'] + kinds['tv']
            wet = kinds['bath_corner'] + kinds['shower_corner'] + kinds['bath'] + kinds['shower']
            area = r['net'].area
            mixed = []
            if is_office:
                if kinds['wc'] or kinds['basin']:
                    kind = 'wc'
                elif kinds['desk'] or kinds['office_chair'] or area > 8:
                    kind = 'office'
                elif r['k'] in has_ent:
                    kind = 'hall'
                elif area < 4:
                    kind = 'storage'
                else:
                    kind = 'office'
            elif wet or kinds['wc']:
                kind = 'bathroom' if wet else 'wc'
                if kinds['bed_double'] or kinds['sofa'] or r['kitchen']:
                    mixed.append('sanitary + living furniture in one room')
            elif kinds['bed_double'] and (kinds['sofa'] or r['kitchen']):
                kind = 'studio'          # one room: bed + sitting / kitchen
            elif kinds['bed_double']:
                kind = 'bedroom'
            elif r['kitchen'] and seating:
                kind = 'living_kitchen'
            elif r['kitchen']:
                kind = 'kitchen'
            elif seating:
                kind = 'living'
            elif kinds['basin']:
                kind = 'wc'
            elif r['k'] in has_ent:
                kind = 'hall'
            elif area < 4.0:
                kind = 'storage'
            elif len(r['doors']) >= 2:
                kind = 'corridor'
            else:
                kind = 'room'
            r['kind'] = kind
            r['mixed'] = mixed
            if mixed:
                rec_issues.append('%s: %s' % (kind, '; '.join(mixed)))
            if kind == 'room':
                rec_issues.append('room %.1f m2 has no symbol, no entrance: untyped' % area)
        # names + numbering
        cnt = Counter(r['kind'] for r in rooms)
        seen = Counter()
        order = ['hall', 'corridor', 'studio', 'living_kitchen', 'living', 'kitchen', 'office', 'bedroom', 'bathroom', 'wc', 'storage', 'room']
        rooms.sort(key=lambda r: (order.index(r['kind']), -r['net'].area))
        for r in rooms:
            seen[r['kind']] += 1
            en, ka = NAMES[r['kind']]
            if cnt[r['kind']] > 1:
                en, ka = '%s %d' % (en, seen[r['kind']]), '%s %d' % (ka, seen[r['kind']])
            r['name'], r['name_ka'] = en, ka
            r['id'] = '%s%d' % ({'living_kitchen': 'lk', 'living': 'lv', 'kitchen': 'kt', 'bedroom': 'br', 'bathroom': 'ba',
                                 'wc': 'wc', 'hall': 'hl', 'studio': 'sd', 'corridor': 'co', 'storage': 'st', 'room': 'rm', 'office': 'of'}[r['kind']], seen[r['kind']])
        kid = {r['k']: r['id'] for r in rooms}
        # ---- furniture records
        all_f = []
        for r in rooms:
            for s in r['syms']:
                all_f.append((r, s))
        tables = [np.array(s['g'].centroid.coords[0]) for r, s in all_f if s['kind'] == 'table_round']
        sofas = [np.array(s['g'].centroid.coords[0]) for r, s in all_f if s['kind'] == 'sofa']
        desks_c = [np.array(s['g'].centroid.coords[0]) for r, s in all_f if s['kind'] == 'desk']
        ochairs = [np.array(s['g'].centroid.coords[0]) for r, s in all_f if s['kind'] == 'office_chair']
        for r, s in all_f:
            g = s['g']
            c, (L, W), uu, q = obb(g)
            h = None
            free = False
            if s['kind'] in ('office_chair', 'desk', 'desk_equipment') and desks_c and ochairs:
                pool = desks_c if s['kind'] == 'office_chair' else ochairs
                t_ = min(pool, key=lambda t: np.hypot(*(t - c)))
                v = (t_ - c) if s['kind'] != 'desk_equipment' else (c - t_)
                h = v / max(np.hypot(*v), 1e-9)
            elif s['kind'] == 'chair' and tables:
                t = min(tables, key=lambda t: np.hypot(*(t - c)))
                if np.hypot(*(t - c)) < 1.3:
                    h = (t - c) / max(np.hypot(*(t - c)), 1e-9)
            elif s['kind'] == 'table_coffee' and sofas:
                t = min(sofas, key=lambda t: np.hypot(*(t - c)))
                if np.hypot(*(t - c)) < 2.5:
                    v = t - c
                    h = snap_dir(v / max(np.hypot(*v), 1e-9))
            elif s['kind'] in ('bath', 'shower'):
                # a bath backs onto the wall along its LENGTH: in a niche its
                # ends touch walls too, and the nearest side alone turned
                # flat 89's bath end-on (size 0.75 x 1.89 "deep")
                h = heading_from_wall(q, walls, 0.2, long_sides=True)
            elif s['kind'] in ('table_round',):
                h, free = np.array([1.0, 0.0]), True
            if h is None and s['kind'] in ('bath', 'shower'):
                # no long side on a wall: across the length, into the room
                nv = np.array([-uu[1], uu[0]])
                rc = np.array(r['net'].representative_point().coords[0])
                h = nv if float(np.dot(rc - c, nv)) >= 0 else -nv
            if h is None and s['kind'] != 'desk':
                h = heading_from_wall(q, walls)
            if h is None and s['kind'] in ('bed_double', 'sofa', 'wc', 'basin', 'tv'):
                h = heading_from_ink(c, uu, s['ink'], length_axis=s['kind'] in ('bed_double', 'wc'))
            if h is None:
                h, free = (uu if s['kind'] != 'desk' else np.array([-uu[1], uu[0]])), True
            rec = dict(kind=s['kind'], room=kid[r['k']], centre=ptj(c), size=size_along(L, W, uu, h),
                       heading=ang(h))
            if free:
                rec['heading_free'] = True
            if s.get('note'):
                rec['note'] = s['note']
            if s['kind'] in ('desk', 'bath', 'shower'):
                rec['outline'] = pjson(largest(g))
            if s['kind'] in ('bath_corner', 'shower_corner'):
                # heading points out of the corner (along the diagonal); size is the square
                v = np.array(g.centroid.coords[0]) - c
                rec['size'] = [rnd(max(L, W)), rnd(max(L, W))]
                rec['heading'] = ang(-v / max(np.hypot(*v), 1e-9)) if np.hypot(*v) > 1e-3 else rec['heading']
                rec['note'] = 'quarter-round corner glyph; heading = out of the corner'
            if s['kind'] in ('bath_corner', 'shower_corner'):
                x0_, y0_, x1_, y1_ = g.bounds
                rec['centre'] = ptj(((x0_ + x1_) / 2, (y0_ + y1_) / 2))
                rec['size'] = [rnd(x1_ - x0_), rnd(y1_ - y0_)]
                rec['box_axis_aligned'] = True
                rec['note'] = 'quarter-round corner glyph: size = [dx, dy] of its axis-aligned box; heading = out of the corner (diagonal)'
            fur.append(rec)
        for r in rooms:
            for kl in r['kitchen']:
                for c, h, L, W, assumed in legs_from_line(kl['line'], kl['poly'], walls):
                    fur.append(dict(kind='kitchen_run', room=kid[r['k']], centre=ptj(c), size=[rnd(L), rnd(W)],
                                    heading=ang(h), worktop=pjson(kl['poly']),
                                    front=[ptj(p) for p in kl['line']],
                                    **({'depth_assumed': True} if assumed else {})))
        # ---- room records
        out_rooms = []
        for r in rooms:
            net_g, sh = r['net'], r['share']
            lp = polylabel(largest(net_g), 0.02)
            st = stance(largest(net_g), r, fur, kid[r['k']])
            doors_j = []
            for dr in r['doors']:
                other = [s for s in dr['sides'] if s != r['k']]
                other = other[0] if other else r['k']
                doors_j.append(dict(door=dr['i'], centre=dr['d']['centre'], width=dr['d']['width'],
                                    to=kid.get(other, other) if isinstance(other, int) else other,
                                    entrance=bool({'corridor'} & set(dr['sides']))))
            if r['k'] in has_ent and not any(d['entrance'] for d in doors_j):
                doors_j.append(dict(door=None, centre=[rnd(v) for v in ent_c[0]], width=None, to='corridor', entrance=True,
                                    note='no entrance door drawn; suggested position'))
            out_rooms.append(dict(
                id=r['id'], kind=r['kind'], name=r['name'], name_ka=r['name_ka'],
                area=rnd(sh.area, 2), area_net=rnd(net_g.area, 2),
                polygon=pjson(largest(sh).simplify(0.02)) if len(pe.polys_of(sh)) == 1 else [pjson(p.simplify(0.02)) for p in pe.polys_of(sh) if p.area > 0.01],
                polygon_net=pjson(largest(net_g)),
                label=ptj(lp.coords[0]), doors=doors_j,
                windows=[dict(window=w['i'], centre=w['w']['centre'], width=w['w']['width'], kind=w['w']['kind'],
                              outward=ang(w['out'])) for w in r['windows']],
                furniture=[i for i, f in enumerate(fur) if f['room'] == r['id']],
                stance=st,
                **({'issue': r['mixed']} if r['mixed'] else {})))
            all_room_draw.append((num, r, out_rooms[-1]))
        for bi, b in enumerate(u['balconies']):
            bp = pj(b['polygon'])
            con = [dr['i'] for dr in door_recs if 'balcony:%d' % bi in dr['sides']]
            kind = b['kind'] if b['kind'] in ('balcony', 'loggia') else 'balcony'
            en, ka = NAMES[kind]
            out_rooms.append(dict(id='%s%d' % ('bc' if kind == 'balcony' else 'lg', bi + 1), kind=kind,
                                  name=en, name_ka=ka, area=rnd(bp.area, 2), area_net=rnd(bp.area, 2),
                                  polygon=pjson(bp), label=ptj(polylabel(bp, 0.02).coords[0]),
                                  doors=[dict(door=i, centre=doors[i]['centre'], width=doors[i]['width']) for i in con],
                                  windows=[], furniture=[], stance=None, outside_inner_area=True))
            all_room_draw.append((num, dict(kind=kind, share=bp, net=bp, name=en), out_rooms[-1]))
        # ---- aspect
        asp = set()
        bpolys = [pj(b['polygon']) for b in u['balconies']] + [pj(b['polygon']) for b in lev.get('common_loggias', [])]
        for w, o in win_dirs:
            probe = Point(np.array(w['centre']) + o * 0.6)
            onto = [b for b in bpolys if b.buffer(0.05).contains(probe)]
            if onto:
                # opening onto a balcony / loggia: the aspect is where the balcony looks
                bc = np.array(onto[0].centroid.coords[0])
                fp = F.exterior.interpolate(F.exterior.project(Point(bc)))
                o = bc - np.array(fp.coords[0])
                o = o / max(np.hypot(*o), 1e-9)
                if abs(o[0]) < 0.7 and abs(o[1]) < 0.7:
                    o = np.array([np.sign(o[0]), 0.0]) if abs(o[0]) > abs(o[1]) else np.array([0.0, np.sign(o[1])])
            d = 'east' if o[0] > 0.7 else 'west' if o[0] < -0.7 else 'south' if o[1] > 0.7 else 'north'
            asp.add(d)
            c = w['centre']
            if (d == 'south' and 17.5 < c[1] < 19.5 and c[0] < 61.8) or (d == 'west' and abs(c[0] - 61.9) < 1.0 and c[1] > 18.0):
                asp.add('courtyard')
        aspect = [a for a in ('north', 'east', 'south', 'west', 'courtyard') if a in asp]
        sum_share = sum(r['area'] for r in out_rooms if not r.get('outside_inner_area'))
        rec = dict(number=num, level=u['level'], floor=u['floor'], block=u['block'], part=u['part'],
                   area_inner=rnd(F.area, 2), rooms_area_sum=rnd(sum_share, 2),
                   rooms_net_sum=rnd(sum(r['area_net'] for r in out_rooms if not r.get('outside_inner_area')), 2),
                   aspect=aspect, loggia=any(b['kind'] == 'loggia' for b in u['balconies']),
                   balconies=len(u['balconies']),
                   rooms=out_rooms, furniture=fur, issues=rec_issues, _F=F, _ent=ent_c)
        if not is_office:
            kinds_ = [r['kind'] for r in out_rooms]
            if not any(k in ('kitchen', 'living_kitchen', 'studio') for k in kinds_):
                rec_issues.append('no kitchen drawn in this flat (no worktop line anywhere in it)')
            for r in out_rooms:
                if r['kind'] in ('hall', 'corridor') and r['area_net'] > 14:
                    rec_issues.append('%s %s is %.1f m2 and empty on the sheet: possibly an unfurnished living / dining space' % (r['kind'], r['id'], r['area_net']))
        if abs(sum_share - F.area) > 0.01 * F.area:
            rec_issues.append('room areas %.2f vs flat %.2f' % (sum_share, F.area))
        out[num] = rec
    # unknown symbols
    unk = [s for s in syms if s['kind'] == 'unknown']
    for s in unk:
        c, (L, W), _, _ = obb(s['g'])
        issues.append(dict(page=n, issue='unrecognised symbol', centre=ptj(c), size=[rnd(L), rnd(W)]))
    # ---- walking distance to cores
    corr = unary_union([pj(c) for c in lev['corridor']])
    if not corr.is_empty:
        free = corr.difference(walls.buffer(0.02)).buffer(0.0)
        wk = Walk(free)
        cores = {}
        for cid, cs in (lev.get('core_summary') or {}).items():
            x0, y0, x1, y1 = cs['stair_cell']
            cores[cid] = ((x0 + x1) / 2, (y0 + y1) / 2)
        D = {cid: wk.dist_from(p) for cid, p in cores.items()}
        for num, rec in out.items():
            F = rec['_F']
            ents = rec['_ent'] or [np.array(F.centroid.coords[0])]
            e = ents[0]
            # step 0.4 m into the corridor
            best = None
            for v in ((0.4, 0), (-0.4, 0), (0, 0.4), (0, -0.4)):
                p = e + np.array(v)
                if free.contains(Point(p)) and not F.contains(Point(p)):
                    best = p
                    break
            if best is None:
                best = np.array(free.exterior.interpolate(free.exterior.project(Point(e))).coords[0]) if free.geom_type == 'Polygon' else e
            i, j = wk.cell(best)
            dist = {cid: float(D[cid][i, j]) for cid in D}
            fin = {k: v for k, v in dist.items() if np.isfinite(v)}
            rec['core'] = min(fin, key=fin.get) if fin else None
            rec['core_walk_m'] = {k: rnd(v, 1) for k, v in sorted(fin.items())}
            rec['core_straight'] = next(f['core'] for f in units if f['number'] == num)
    return out, pg, lev, all_room_draw, syms, lines


def stance(room, r, fur, rid):
    """Eye 1.6 m above the floor, well inside, looking at the window (or
    down the room's longest view)."""
    inner = room.buffer(-0.45, **MITRE)
    if inner.is_empty or inner.area < 0.05:
        inner = room.buffer(-0.25, **MITRE)
    if inner.is_empty:
        inner = room
    x0, y0, x1, y1 = inner.bounds
    X, Y = np.meshgrid(np.arange(x0, x1 + 0.1, 0.1), np.arange(y0, y1 + 0.1, 0.1))
    ok = contains_xy(inner, X, Y)
    blocks = []
    for f in fur:
        if f['room'] != rid or f['kind'] in ('tv', 'vent_duct'):
            continue
        h = math.radians(f['heading'])
        w, d = f['size']
        c = np.array(f['centre'])
        hv = np.array([math.cos(h), math.sin(h)])
        pv = np.array([-hv[1], hv[0]])
        q = [c + pv * w / 2 + hv * d / 2, c - pv * w / 2 + hv * d / 2, c - pv * w / 2 - hv * d / 2, c + pv * w / 2 - hv * d / 2]
        blocks.append(Polygon(q).buffer(0.2))
    if blocks:
        bu = unary_union(blocks)
        ok2 = ok & ~contains_xy(bu, X, Y)
        if ok2.any():
            ok = ok2
    cand = np.column_stack([X[ok], Y[ok]])
    if not len(cand):
        p = room.representative_point()
        cand = np.array([[p.x, p.y]])
    if r['windows']:
        w = max(r['windows'], key=lambda w: w['w']['width'])
        tgt = np.array(w['w']['centre'])
        tz = 1.2
        d = np.hypot(cand[:, 0] - tgt[0], cand[:, 1] - tgt[1])
        # prefer far, but in line of sight inside the room
        order = np.argsort(-d)
        eye = cand[order[0]]
        roomb = room.buffer(0.3)
        for k in order[:200]:
            if roomb.contains(LineString([cand[k], tgt])):
                eye = cand[k]
                break
        why = 'window'
    else:
        c, (L, W), u, q = obb(room)
        a, b = c - u * L / 2, c + u * L / 2
        da = np.hypot(cand[:, 0] - a[0], cand[:, 1] - a[1])
        eye = cand[np.argmin(da)]
        tgt = b
        tz = 1.2
        why = 'longest view'
    return dict(eye=[rnd(eye[0]), rnd(eye[1]), EYE], look=[rnd(tgt[0]), rnd(tgt[1]), tz], looks_at=why,
                z='above this level\'s floor (add the level z)')


# ------------------------------------------------------------------ layout groups
SYMS8 = [(a, m) for m in (False, True) for a in (0, 90, 180, 270)]


def norm_pts(F, rooms, fur, a, m):
    from shapely import affinity
    c = F.centroid
    g = affinity.translate(F, -c.x, -c.y)
    if m:
        g = affinity.scale(g, -1, 1, origin=(0, 0))
    g = affinity.rotate(g, a, origin=(0, 0))
    return g


def transform_pt(p, c, a, m):
    x, y = p[0] - c[0], p[1] - c[1]
    if m:
        x = -x
    t = math.radians(a)
    return (x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t))


def layout_groups(flats, furniture, haus=0.4, room_tol=0.8, sym_tol=0.35, darea=1.0):
    """Group flats that are the same under one of the 8 plan symmetries
    (identity, rotations, mirrors): fill outline within `haus` m (Hausdorff,
    about the centroids), the same room kinds with label points within
    `room_tol` m, and - when `furniture` - every drawn piece of the same
    kind within `sym_tol` m."""
    from shapely import affinity
    recs = []
    for num, f in flats.items():
        F = f['_F']
        c = F.centroid.coords[0]
        feats = [(r['kind'], r['label']) for r in f['rooms'] if not r.get('outside_inner_area')]
        sy = [(s['kind'], s['centre']) for s in f['furniture'] if s['kind'] not in ('vent_duct', 'nightstand')] if furniture else []
        recs.append((num, F, c, feats, sy))

    def match(pts, c, a, m, ref, rc, tol):
        for kind, p in pts:
            q = transform_pt(p, c, a, m)
            if not any(k2 == kind and math.hypot(q[0] - (p2[0] - rc[0]), q[1] - (p2[1] - rc[1])) < tol for k2, p2 in ref):
                return False
        return True
    groups = []
    for num, F, c, feats, sy in sorted(recs, key=lambda r: (-round(r[1].area), str(r[0]))):
        placed = False
        for g in groups:
            rn, rF, rc, rfeats, rsy = g['rep']
            if abs(F.area - rF.area) > darea or Counter(k for k, _ in feats) != Counter(k for k, _ in rfeats):
                continue
            if Counter(k for k, _ in sy) != Counter(k for k, _ in rsy):
                continue
            g0 = affinity.translate(rF, -rc[0], -rc[1])
            for a, m in SYMS8:
                if norm_pts(F, None, None, a, m).hausdorff_distance(g0) > haus:
                    continue
                if match(feats, c, a, m, rfeats, rc, room_tol) and match(sy, c, a, m, rsy, rc, sym_tol):
                    g['members'].append((num, a, m))
                    placed = True
                    break
            if placed:
                break
        if not placed:
            groups.append(dict(rep=(num, F, c, feats, sy), members=[(num, 0, False)]))
    return sorted(groups, key=lambda g: (-len(g['members']), str(g['rep'][0])))


# ------------------------------------------------------------------ check image
def draw_check(pg, lev, flats, draws, fn, lines):
    from PIL import Image, ImageDraw, ImageFont
    dpi = 300
    X0, Y0, X1, Y1 = -2.5, -2.5, 85.0, 38.5
    import subprocess
    import tempfile
    k = dpi / 72.0
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(['pdftoppm', '-f', str(pg.n), '-l', str(pg.n), '-r', str(dpi), '-png', '-singlefile', PDF,
                        os.path.join(td, 'r')], check=True)
        ras = Image.open(os.path.join(td, 'r.png')).convert('RGB')
        ras.load()
    a = ((pg.ox + X0 * pg.s) * k, (pg.oy + Y0 * pg.s) * k)
    b = ((pg.ox + X1 * pg.s) * k, (pg.oy + Y1 * pg.s) * k)
    ras = ras.crop((int(a[0]), int(a[1]), int(b[0]), int(b[1])))
    pxm = pg.s * k
    base = ras.convert('L').convert('RGB')
    ov = Image.new('RGBA', ras.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    f9 = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 11)
    fb = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 13)

    def P(x, y):
        return ((x - X0) * pxm, (y - Y0) * pxm)
    for num, r, rj in draws:
        col = KIND_COLOUR.get(rj['kind'], (255, 0, 0))
        for p in pe.polys_of(r['share']):
            d.polygon([P(*q) for q in p.exterior.coords], fill=col + (120,), outline=(0, 0, 0, 255))
    img = Image.alpha_composite(base.convert('RGBA'), ov)
    d = ImageDraw.Draw(img)
    for num, f in flats.items():
        for s in f['furniture']:
            h = math.radians(s['heading'])
            w, dd = s['size']
            c = np.array(s['centre'])
            hv = np.array([math.cos(h), math.sin(h)])
            pv = np.array([-hv[1], hv[0]])
            q = [c + pv * w / 2 + hv * dd / 2, c - pv * w / 2 + hv * dd / 2, c - pv * w / 2 - hv * dd / 2, c + pv * w / 2 - hv * dd / 2]
            if s.get('box_axis_aligned'):
                q = [c + np.array(v) * np.array([w, dd]) / 2 for v in ((1, 1), (-1, 1), (-1, -1), (1, -1))]
                dd = min(w, dd) * 1.2
            colr = (200, 0, 0) if s['kind'] == 'unknown' else (0, 90, 220) if s['kind'] != 'kitchen_run' else (230, 90, 0)
            d.polygon([P(*x) for x in q], outline=colr, width=2)
            # facing tick
            d.line([P(*c), P(*(c + hv * dd / 2))], fill=(220, 0, 160), width=2)
            t = ABBR.get(s['kind'], s['kind'])
            X, Y = P(*c)
            d.text((X - d.textlength(t, font=f9) / 2, Y - 6), t, fill=(0, 0, 120), font=f9)
    for num, r, rj in draws:
        if 'label' not in rj:
            continue
        X, Y = P(*rj['label'])
        t = rj['name'] if rj['kind'] not in ('balcony', 'loggia') else rj['kind'][:4]
        t2 = '%s %.1f' % (num, rj['area'])
        d.text((X - d.textlength(t, font=fb) / 2, Y + 4), t, fill=(120, 0, 0), font=fb)
        d.text((X - d.textlength(t2, font=f9) / 2, Y + 18), t2, fill=(60, 60, 60), font=f9)
        st = rj.get('stance')
        if st:
            e = P(*st['eye'][:2])
            l = P(*st['look'][:2])
            d.ellipse((e[0] - 3, e[1] - 3, e[0] + 3, e[1] + 3), fill=(0, 160, 0))
            v = np.array(l) - np.array(e)
            v = v / max(np.hypot(*v), 1e-9) * 25
            d.line([e, (e[0] + v[0], e[1] + v[1])], fill=(0, 160, 0), width=2)
    for f in flats.values():
        for i in f['issues']:
            pass
    out = Image.new('RGB', (ras.size[0], ras.size[1] * 2 + 8), (255, 0, 0))
    out.paste(ras, (0, 0))
    out.paste(img.convert('RGB'), (0, ras.size[1] + 8))
    out.save(fn)


# ------------------------------------------------------------------ main
def main(argv):
    pages = list(range(3, 13))
    check = '--no-check' not in argv
    if '--pages' in argv:
        pages = [int(x) for x in argv[argv.index('--pages') + 1].split(',')]
    P = json.load(open(os.path.join(PLANS, 'plan.json')))
    issues = []
    flats, offices = {}, {}
    sym_count = Counter()
    for n in pages:
        out, pg, lev, draws, syms, lines = process_page(n, P, issues)
        for num, rec in out.items():
            (offices if lev['kind'] == 'offices' else flats)[num] = rec
            for s in rec['furniture']:
                sym_count[s['kind']] += 1
        if check:
            cdir = argv[argv.index('--checkdir') + 1] if '--checkdir' in argv else os.path.join(PLANS, 'check')
            draw_check(pg, lev, out, draws, os.path.join(cdir, 'rooms_%02d.png' % n), lines)
        print('page %d: %d units, %d symbols' % (n, len(out), sum(len(r['furniture']) for r in out.values())), flush=True)
    # per flat type + groups
    for num, f in flats.items():
        br = sum(1 for r in f['rooms'] if r['kind'] == 'bedroom')
        f['bedrooms'] = br
        f['type'] = 'studio' if br == 0 else '%d-bedroom' % br
        has_living = any(r['kind'] in ('living', 'living_kitchen') for r in f['rooms'])
        f['type_ka'] = 'სტუდიო' if br == 0 else '%d-ოთახიანი' % (br + (1 if has_living else 0))
        f['bathrooms'] = sum(1 for r in f['rooms'] if r['kind'] in ('bathroom', 'wc'))
    lgroups = layout_groups(flats, furniture=False)
    kgroups = layout_groups(flats, furniture=True)
    how = 'rep = this flat mirrored in x about its centroid (if mirror_x), then rotated rotate_deg counter-clockwise in the plan frame, then moved onto the rep\'s centroid'
    for key, groups, pre in (('layout', lgroups, 'L'), ('kit', kgroups, 'K')):
        for gi, g in enumerate(groups):
            rep = g['rep'][0]
            for num, a, m in g['members']:
                f = flats[num]
                f['%s_group' % key] = '%s%02d' % (pre, gi + 1)
                f['%s_group_size' % key] = len(g['members'])
                if num != rep:
                    f['%s_same_as' % key] = dict(flat=rep, rotate_deg=a, mirror_x=m)
    for num, f in flats.items():
        kinds = Counter(r['kind'] for r in f['rooms'] if not r.get('outside_inner_area'))
        f['signature'] = '%s|%s|%s' % (f['type'], '+'.join('%s%s' % (k, '' if v == 1 else v) for k, v in sorted(kinds.items())), f['layout_group'])
        f['mirror_of'] = f.get('layout_same_as')
    # summary
    types = defaultdict(lambda: defaultdict(Counter))
    for num, f in flats.items():
        types['by_floor'][str(f['floor'])][f['type']] += 1
        types['by_block'][f['block']][f['type']] += 1
        types['all']['all'][f['type']] += 1
    room_count = Counter(r['kind'] for f in list(flats.values()) + list(offices.values()) for r in f['rooms'])
    for f in list(flats.values()) + list(offices.values()):
        for i in f['issues']:
            issues.append(dict(unit=f['number'], level=f['level'], issue=i))
        f.pop('_F')
        f.pop('_ent')
        f.pop('issues')
    summary = dict(
        types={k: {kk: dict(vv) for kk, vv in v.items()} for k, v in types.items()},
        symbols=dict(sym_count.most_common()),
        rooms=dict(room_count.most_common()),
        layout_groups={('L%02d' % (i + 1)): [m[0] for m in g['members']] for i, g in enumerate(lgroups)},
        kit_groups={('K%02d' % (i + 1)): [m[0] for m in g['members']] for i, g in enumerate(kgroups)},
        groups_note=how + '. layout_group: same fill outline (0.4 m) and rooms (kinds, label points 0.8 m); kit_group: also every drawn piece within 0.35 m (one furniture kit fits all).',
    )
    meta = dict(
        generator='tools/plan_rooms.py', source='blender/plans/plans.pdf + blender/plans/plan.json',
        frame='plan frame of plan.json (metres, x along a..J, y along 1..10, +y street side)',
        furniture='centre [x,y]; size [width across heading, depth along heading]; heading = degrees of atan2(dy,dx) of the direction the piece faces (bed: head->foot; sofa/WC/basin/TV/worktop: away from the wall it backs onto; chair: towards its table); heading_free = symmetric or free-standing, heading arbitrary',
        rooms='area = the room\'s share of the flat fill (walls split down the middle; sums to the flat); area_net = free floor; polygon / polygon_net likewise; label = pole of inaccessibility; stance.eye z 1.6 above the level floor',
        corner_glyphs='bath_corner (>= 1.2 m) and shower_corner (0.8 - 1.0 m) are the same quarter-round glyph drawn at different sizes',
        kitchens='the sheets draw kitchens as a worktop front line only (no sink/hob/fridge symbols); kitchen_run = one straight leg of the worktop, worktop = its polygon',
        aspect='-y north, +y south (street), -x west, +x east; courtyard = over the podium terrace (bar south face west of the wing, wing west face)')
    out = dict(meta=meta, flats=flats, offices=offices, types=summary, issues=issues)
    dst = argv[argv.index('--out') + 1] if '--out' in argv else os.path.join(PLANS, 'rooms.json')
    json.dump(out, open(dst, 'w'), ensure_ascii=False, indent=1, default=lambda o: o.tolist() if hasattr(o, 'tolist') else str(o))
    print('flats %d offices %d issues %d' % (len(flats), len(offices), len(issues)))
    print('symbols', dict(sym_count.most_common()))
    print('rooms', dict(room_count.most_common()))


if __name__ == '__main__':
    main(sys.argv[1:])
