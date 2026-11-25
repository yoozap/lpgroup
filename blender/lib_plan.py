#!/usr/bin/env python3
"""The inside of the building, computed from the architect's plan.

    python3 blender/lib_plan.py --geo OUT.json [--levels L03,L04] [--meta web/plan_meta.json]

Runs under the SYSTEM python (it needs shapely 2, which Blender's python does
not have). `blender/build_interior.py` calls it, reads OUT.json and turns it
into meshes; nothing here imports bpy.

Input : blender/plans/plan.json (tools/plan_extract.py), and
        blender/plans/rooms.json when it exists (room types; optional).
Output: --geo   geometry for Blender, already in the BLENDER LOCAL frame
                (x, -y, z) of the plan frame - see blender/plans/CONTRACT.md.
        --meta  web/plan_meta.json, in PLAN metres (x, y as in plan.json).

Nothing below is typed in by hand except the handful of building
conventions at the top (heights of sills, heads, doors, the slab, how close
to the outside the street file's walls reach). Every wall, door, floor,
room, stair flight, lift and landing comes out of plan.json.

The pieces of one level:

  W      every cut wall and column (`walls.poche`), minus the throats cut for
         the four entrance doors the drawing leaves out (flats 128, 129,
         140, 141 on +27.900; `entrance_suggested`).
  OUT    outside the level outline + balconies + loggias + the terrace.
  EXT    W within EXT_D of OUT: the street file's (CONTRACT.md).
  WI     W - EXT: built here, full storey height, top cap only.
  LIN    the room-side lining of EXT (0.06 deep, 0.012 proud of the face).
  fills  voids inside the outline that are not a room, a corridor, a door
         throat or a window: ducts. Built solid.
  gaps   door throats (between the jambs of a drawn door leaf) get a lintel
         at DOOR_H; window gaps get a lining sill and head.

Ownership: a wall piece belongs to a flat when it is within OWN_D of that
flat and of nothing else; everything else (party walls, corridor walls,
core walls) belongs to the level.
"""
import json
import math
import os
import sys
from collections import defaultdict

from shapely.geometry import (LineString, MultiPolygon, Point, Polygon, box,
                              GeometryCollection)
from shapely.ops import unary_union
import shapely

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PLAN = os.path.join(HERE, 'plans', 'plan.json')
ROOMS = os.path.join(HERE, 'plans', 'rooms.json')

# ---------------------------------------------------------------- conventions
SLAB = 0.30          # floor-to-floor minus clear height (structure + build-up)
DOOR_H = 2.10        # head of every swing door
WIN_SILL = 0.90      # renders.md 3: sill about 0.9, windows 1.5 high
WIN_HEAD = 2.40
BDOOR_H = 2.40       # balcony / loggia doors run to the window head
EXT_D = 0.25         # the street file owns wall poche this close to outside
LIN_IN = 0.06        # lining depth into EXT
LIN_OUT = 0.012      # lining stands proud of the wall face
OWN_D = 0.22         # a wall this close to one flat only is that flat's
BALC_TOP = 0.02      # loggia tiles stand above the slab (CONTRACT)
LEAF_T = 0.04
RISER_MAX = 0.19
GOING_MIN = 0.25
WAIST = 0.25         # flight soffit below the pitch line / landing slab
RAIL_H = 0.90
SKIRT_H = 0.08       # skirting board: height, and how far it stands off the wall
SKIRT_T = 0.012
SILL_T = 0.006       # a door threshold where two floor finishes meet stands this proud
LEVELS_BUILT = ['L00', 'L01', 'L02', 'L03', 'L04', 'L05', 'L06', 'L07',
                'L08', 'L09', 'L10']
CORES = ('C1', 'C2', 'C3')

MAT_WALL = 'int_wall'
MAT_PARQ = 'int_parquet'
MAT_TILE = 'int_tile_floor'
MAT_STONE = 'int_marble'          # common parts
MAT_COMM = 'int_tile_grey'        # commercial floor (unfurnished halls)
MAT_TRIM = 'int_white_gloss'      # door linings, skirting
MAT_LEAF = 'int_door_leaf'
MAT_ENTR = 'int_wood_walnut'      # flat entrance leaves
MAT_HANDLE = 'int_black'
MAT_GLASS = 'int_glass'
MAT_TREAD = 'int_stone_dark'
MAT_STAIR = 'concrete_frame'
MAT_METAL = 'metal_dark'
MAT_CEIL = 'int_wall'

R3 = lambda v: round(float(v), 3)


# ---------------------------------------------------------------- geometry
def P(rec):
    """plan.json polygon record -> shapely Polygon (valid)."""
    g = Polygon(rec['outline'], rec.get('holes') or [])
    if not g.is_valid:
        g = g.buffer(0)
    return g


def polys(g, min_area=1e-4):
    """Any geometry -> list of Polygons with area > min_area."""
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g] if g.area > min_area else []
    out = []
    for q in getattr(g, 'geoms', []):
        out.extend(polys(q, min_area))
    return out


def U(gs):
    gs = [g for g in gs if g is not None and not g.is_empty]
    return unary_union(gs) if gs else Polygon()


def clean(g, eps=0.0005):
    """Snap away slivers that boolean ops leave behind."""
    if g.is_empty:
        return g
    g = g.buffer(eps, join_style=2).buffer(-2 * eps, join_style=2).buffer(eps, join_style=2)
    return U(polys(g, 2e-4))


def grow(g, d):
    return g.buffer(d, join_style=2, mitre_limit=3.0)


def rings_of(p, ndp=4):
    """Polygon -> [outer, hole...] as lists of (x, y), unclosed, deduped."""
    out = []
    for r in [p.exterior] + list(p.interiors):
        pts = [(round(x, ndp), round(y, ndp)) for x, y in r.coords[:-1]]
        q = []
        for pt in pts:
            if not q or (abs(pt[0] - q[-1][0]) > 1e-4 or abs(pt[1] - q[-1][1]) > 1e-4):
                q.append(pt)
        while len(q) > 1 and abs(q[0][0] - q[-1][0]) < 1e-4 and abs(q[0][1] - q[-1][1]) < 1e-4:
            q.pop()
        if len(q) >= 3:
            out.append(q)
    return out


def coords_m(p, nd=3, tol=0.002):
    """Polygon -> plan_meta polygon: outline [[x,y]..] (+ holes)."""
    p = p.simplify(tol)
    rs = rings_of(p, nd)
    if not rs:
        return None
    d = {'outline': [[R3(x), R3(y)] for x, y in rs[0]]}
    if len(rs) > 1:
        d['holes'] = [[[R3(x), R3(y)] for x, y in r] for r in rs[1:]]
    return d


def cm(g, tol=0.002):
    """Geometry -> list of plan_meta polygons."""
    return [c for c in (coords_m(p, tol=tol) for p in polys(g, 1e-3)) if c]


# ------------------------------------------------------------- the geo sink
class Geo:
    """Collects meshes per node, in the Blender local frame (x, -y, z).

    A node holds parts: {'mat', 'prisms': [...], 'v': [...], 'f': [...]}.
    Explicit faces are given in the PLAN frame with outward winding and
    are mirrored (y -> -y, winding reversed) on the way out.
    """

    def __init__(self):
        self.nodes = {}           # name -> {'parts': {mat: part}, 'loc', 'rot', 'mesh'}
        self.shared = {}          # mesh id -> {'parts': {...}} (leaves)

    def _part(self, name, mat):
        n = self.nodes.setdefault(name, {'parts': {}})
        return n['parts'].setdefault(mat, {'mat': mat, 'prisms': [], 'v': [], 'f': []})

    def prism(self, name, mat, g, z0, z1, top=True, bottom=False, sides=True):
        for p in polys(g, 2e-4):
            rs = rings_of(p)
            if not rs:
                continue
            rs = [[(x, -y) for x, y in r] for r in rs]
            self._part(name, mat)['prisms'].append(
                {'rings': rs, 'z0': round(z0, 4), 'z1': round(z1, 4),
                 'top': top, 'bottom': bottom, 'sides': sides})

    def faces(self, name, mat, verts, faces):
        part = self._part(name, mat)
        o = len(part['v'])
        part['v'].extend([[round(x, 4), round(-y, 4), round(z, 4)] for x, y, z in verts])
        part['f'].extend([[o + i for i in reversed(f)] for f in faces])

    def instance(self, name, mesh_id, loc, rot_z):
        self.nodes[name] = {'mesh': mesh_id, 'loc': [round(loc[0], 4), round(-loc[1], 4), round(loc[2], 4)],
                            'rot': round(rot_z, 6)}

    def shared_faces(self, mesh_id, mat, verts, faces, local=True):
        """A mesh in a node-local frame (already Blender-handed)."""
        m = self.shared.setdefault(mesh_id, {'parts': {}})
        part = m['parts'].setdefault(mat, {'mat': mat, 'prisms': [], 'v': [], 'f': []})
        o = len(part['v'])
        part['v'].extend([[round(a, 4) for a in v] for v in verts])
        part['f'].extend([[o + i for i in f] for f in faces])

    def dump(self):
        nodes = []
        for name, n in self.nodes.items():
            d = {'name': name}
            if 'mesh' in n:
                d.update(mesh=n['mesh'], loc=n['loc'], rot=n['rot'])
            else:
                d['parts'] = list(n['parts'].values())
            nodes.append(d)
        shared = {k: list(v['parts'].values()) for k, v in self.shared.items()}
        return {'nodes': nodes, 'shared': shared}


def box_faces(x0, y0, z0, x1, y1, z1, skip=()):
    """Axis-aligned box in the plan frame, outward winding (plan frame)."""
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    f = {'-z': (0, 3, 2, 1), '+z': (4, 5, 6, 7), '-y': (0, 1, 5, 4),
         '+y': (2, 3, 7, 6), '-x': (3, 0, 4, 7), '+x': (1, 2, 6, 5)}
    return v, [q for k, q in f.items() if k not in skip]


def oriented_quad(pts, hint):
    """Four points -> index order whose normal points along `hint`."""
    a, b, c = pts[0], pts[1], pts[2]
    u = [b[i] - a[i] for i in range(3)]
    w = [c[i] - a[i] for i in range(3)]
    n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    if sum(n[i] * hint[i] for i in range(3)) < 0:
        return [3, 2, 1, 0]
    return [0, 1, 2, 3]


class Faces:
    """Small accumulator of explicit faces in the plan frame."""

    def __init__(self):
        self.v, self.f = [], []

    def quad(self, pts, hint):
        o = len(self.v)
        self.v.extend(pts)
        self.f.append([o + i for i in oriented_quad(pts, hint)])

    def box(self, x0, y0, z0, x1, y1, z1, skip=()):
        x0, x1 = min(x0, x1), max(x0, x1)
        y0, y1 = min(y0, y1), max(y0, y1)
        z0, z1 = min(z0, z1), max(z0, z1)
        v, f = box_faces(x0, y0, z0, x1, y1, z1, skip)
        o = len(self.v)
        self.v.extend(v)
        self.f.extend([[o + i for i in q] for q in f])

    def obox(self, c, u, v, hu, hv, z0, z1):
        """Oriented box: centre c (x,y), unit axes u, v (plan), half sizes."""
        pts = []
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            pts.append((c[0] + su * hu * u[0] + sv * hv * v[0], c[1] + su * hu * u[1] + sv * hv * v[1]))
        # make the base counter-clockwise in the plan frame
        a = sum(pts[i][0] * pts[(i + 1) % 4][1] - pts[(i + 1) % 4][0] * pts[i][1] for i in range(4))
        if a < 0:
            pts = pts[::-1]
        o = len(self.v)
        self.v.extend([(x, y, z0) for x, y in pts] + [(x, y, z1) for x, y in pts])
        self.f.append([o + 3, o + 2, o + 1, o + 0])
        self.f.append([o + 4, o + 5, o + 6, o + 7])
        for i in range(4):
            j = (i + 1) % 4
            self.f.append([o + i, o + j, o + 4 + j, o + 4 + i])


# ------------------------------------------------------------- plan loading
class Plan:
    def __init__(self, path=PLAN):
        self.raw = json.load(open(path))
        self.levels = {l['level']: l for l in self.raw['levels']}
        self.units = defaultdict(list)
        for f in self.raw['flats']:
            self.units[f['level']].append(('u', f))
        for f in self.raw.get('offices', []):
            self.units[f['level']].append(('o', f))
        self.rooms = load_rooms()

    def z(self, lid):
        return self.levels[lid]['z']

    def h(self, lid):
        return self.levels[lid]['floor_to_floor']


def load_rooms():
    """rooms.json (tools/plan_rooms.py): room kinds and names per flat.
    Returns {('u'|'o', number): [room dicts]} or {} when the file is absent."""
    if not os.path.exists(ROOMS):
        return {}
    try:
        R = json.load(open(ROOMS))
    except Exception as e:
        print('[lib_plan] rooms.json unreadable:', e, file=sys.stderr)
        return {}
    out = {}
    for grp, pre in (('flats', 'u'), ('offices', 'o')):
        for k, v in (R.get(grp) or {}).items():
            rs = v.get('rooms') if isinstance(v, dict) else None
            if isinstance(rs, list):
                out[(pre, str(k))] = rs
            fs = v.get('furniture') if isinstance(v, dict) else None
            if isinstance(fs, list):
                FURN[(pre, str(k))] = fs
    return out


FURN = {}     # (pre, number) -> rooms.json furniture (filled by load_rooms)


def furn_boxes(pre, n):
    """The drawn furniture of one unit as plan-frame footprints."""
    out = []
    for p in FURN.get((pre, str(n)), []):
        try:
            c, (w, d), hd = p['centre'], p['size'], p.get('heading', 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        if p.get('box_axis_aligned'):
            out.append(box(c[0] - w / 2, c[1] - d / 2, c[0] + w / 2, c[1] + d / 2))
            continue
        t = math.radians(hd)
        f, s_ = (math.cos(t), math.sin(t)), (-math.sin(t), math.cos(t))
        out.append(Polygon([(c[0] + f[0] * df * d / 2 + s_[0] * sw * w / 2, c[1] + f[1] * df * d / 2 + s_[1] * sw * w / 2)
                            for df, sw in ((-1, -1), (1, -1), (1, 1), (-1, 1))]))
    return out


WET_WORDS = ('bath', 'wc', 'toilet', 'shower', 'laundry')


def room_kind(rec):
    for k in ('kind', 'type', 'name', 'use'):
        if isinstance(rec.get(k), str):
            return rec[k]
    return None


# -------------------------------------------------------------- the level
class Level:
    def __init__(self, plan, lid):
        self.plan = plan
        self.id = lid
        L = self.L = plan.levels[lid]
        self.z = L['z']
        self.h = L['floor_to_floor']
        self.clear = round(self.h - SLAB, 3)
        self.kind = L['kind']
        self.notes = []
        self.outline = P(L['outline'])
        self.W0 = U([P(p) for p in L['walls']['poche']])
        self.cols = [c for c in L.get('columns', [])]

        # spaces --------------------------------------------------------
        self.units = []        # dicts: token, n, rec, poly, balc[]
        for pre, f in plan.units.get(lid, []):
            self.units.append({'token': '%s%s' % (pre, f['number']), 'n': f['number'],
                               'pre': pre, 'rec': f, 'poly': P(f['polygon']),
                               'balc': [P(b['polygon']) for b in f.get('balconies', [])]})
        self.corr = U([P(c) for c in L.get('corridor', [])])
        self.halls = []        # L00: (token, poly)
        self.commercial = Polygon()
        if lid == 'L00':
            self.commercial = U([P(L['floor_area'])])
            for c in L.get('cores', []):
                self.halls.append((c['core'], P(c['polygon'])))
        self.loggias = U([P(c['polygon']) for c in L.get('common_loggias', [])])
        self.terrace = U([P(t) for t in L.get('terraces', [])])
        balc = U([b for u in self.units for b in u['balc']])
        self.balc = balc
        big = box(-30, -30, 120, 80)
        self.OUT = U([big.difference(self.outline), balc, self.loggias, self.terrace])
        # rooms/corridor/halls: the spaces a wall can face from the inside
        self.SP = U([u['poly'] for u in self.units] + [self.corr, self.commercial] +
                    [h for _, h in self.halls])

    # ------------------------------------------------------------ owners
    def owner_regions(self):
        """token -> region of walls that is that owner's alone."""
        regs = [(u['token'], grow(u['poly'], OWN_D)) for u in self.units]
        regs += [(t, grow(h, OWN_D)) for t, h in self.halls]
        common = grow(U([self.corr, self.commercial, self.loggias]), OWN_D)
        out = {}
        for i, (t, r) in enumerate(regs):
            others = U([r2 for j, (t2, r2) in enumerate(regs) if j != i] + [common])
            out[t] = r.difference(others)
        return out

    def split_owner(self, g, excl):
        """g -> [(token|None, piece)]"""
        res = []
        rest = g
        for t, r in excl.items():
            if rest.is_empty:
                break
            if not r.intersects(rest):
                continue
            piece = rest.intersection(r)
            if piece.area > 1e-4:
                res.append((t, piece))
                rest = rest.difference(r)
        if not rest.is_empty and rest.area > 1e-4:
            res.append((None, rest))
        return res

    def space_at(self, pt):
        """What a point stands in: ('u', token) / ('balc', token) / ('corr',) ..."""
        p = Point(pt)
        for u in self.units:
            if u['poly'].buffer(0.02).contains(p):
                return ('unit', u['token'])
        for u in self.units:
            for b in u['balc']:
                if b.buffer(0.02).contains(p):
                    return ('balc', u['token'])
        for t, h in self.halls:
            if h.buffer(0.02).contains(p):
                return ('hall', t)
        if self.corr.buffer(0.02).contains(p):
            return ('corr', None)
        if self.loggias.buffer(0.02).contains(p):
            return ('loggia', None)
        if self.commercial.buffer(0.02).contains(p):
            return ('comm', None)
        if self.terrace.buffer(0.02).contains(p):
            return ('terrace', None)
        if not self.outline.buffer(-0.02).contains(p):
            return ('out', None)
        return ('wall', None)


# ---------------------------------------------------------------- doors
def unit(v):
    l = math.hypot(v[0], v[1])
    return (v[0] / l, v[1] / l) if l > 1e-9 else (1.0, 0.0)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def interval_hits(line, W):
    """Pieces of `line` inside W as (t0, t1) params along the line."""
    inter = line.intersection(W)
    out = []
    L = line.length
    p0 = line.coords[0]
    d = unit((line.coords[1][0] - p0[0], line.coords[1][1] - p0[1]))
    for g in getattr(inter, 'geoms', [inter]):
        if g.is_empty or g.geom_type not in ('LineString',):
            continue
        ts = [dot((x - p0[0], y - p0[1]), d) for x, y in g.coords]
        out.append((min(ts), max(ts)))
    return sorted(out)


def door_gap(lv, hinge, closed, W):
    """The throat a door leaf closes: rectangle between the jambs, across
    the wall. Returns (Polygon, frame) or None. frame = (origin, a, n, a0,
    a1, c0, c1) in along/across coordinates."""
    a = unit((closed[0] - hinge[0], closed[1] - hinge[1]))
    n = (-a[1], a[0])
    t0 = dot(hinge, n)
    sh, sc = dot(hinge, a), dot(closed, a)
    slo, shi = min(sh, sc), max(sh, sc)

    def pt(s, t):
        return (a[0] * s + n[0] * t, a[1] * s + n[1] * t)

    cs = []
    for off in (0.04, 0.08, 0.15, 0.25):
        for s in (slo - off, shi + off):
            ln = LineString([pt(s, t0 - 0.7), pt(s, t0 + 0.7)])
            for u0, u1 in interval_hits(ln, W):
                c0, c1 = t0 - 0.7 + u0, t0 - 0.7 + u1
                dd = 0 if c0 - 0.03 <= t0 <= c1 + 0.03 else min(abs(t0 - c0), abs(t0 - c1))
                if dd < 0.12 and c1 - c0 > 0.05:
                    cs.append((c0, c1))
    if not cs:
        return None
    # a probe that runs along a crossing wall reads it as very thick: the
    # wall the door sits in is the thinnest reading
    # ...and a probe that grazes a window gap reads it too thin: take the
    # thickest reading that can still be a wall (columns are 0.5-0.6)
    walls = [c for c in cs if c[1] - c[0] <= 0.45]
    if walls:
        c0, c1 = max(walls, key=lambda c: c[1] - c[0])
        # readings of the same wall that are offset (a jamb drawn a few cm
        # out of line): cover them all, or a sliver of wall is left standing
        for r0, r1 in walls:
            if r0 < c1 and r1 > c0:
                c0, c1 = min(c0, r0), max(c1, r1)
    else:
        c0, c1 = min(cs, key=lambda c: c[1] - c[0])
    tm = 0.5 * (c0 + c1)
    span = 2.5
    ln = LineString([pt(slo - span, tm), pt(shi + span, tm)])
    hits = interval_hits(ln, W)
    mid = 0.5 * (slo + shi) - (slo - span)
    a0, a1 = 0.0, (shi - slo) + 2 * span
    for u0, u1 in hits:
        if u1 <= mid:
            a0 = max(a0, u1)
        elif u0 >= mid:
            a1 = min(a1, u0)
    a0 += slo - span
    a1 += slo - span
    a0 = max(a0, slo - 0.25)
    a1 = min(a1, shi + 0.25)
    if a1 - a0 < 0.4:
        return None
    g = Polygon([pt(a0, c0), pt(a1, c0), pt(a1, c1), pt(a0, c1)])
    return g, (a, n, a0, a1, c0, c1, t0)


def heading(v):
    return math.degrees(math.atan2(v[1], v[0]))


def signed_angle(a, b):
    return math.degrees(math.atan2(a[0] * b[1] - a[1] * b[0], dot(a, b)))


# ------------------------------------------------------------------ stairs
def stair_layout(plan):
    """Per core: the dog-leg as the drawing gives it.

    The flight drawn with an arrow rises towards the floor landing (it is
    the second flight of a storey; the other one leaves the floor). Bands
    and run extents are taken per storey from the sheet of the storey's
    lower level when that sheet draws both flights in full, otherwise from
    the nearest sheet that does.
    """
    lay = {}
    for c in CORES + ('podium',):
        floor_end = None
        for lid in ['L03', 'L04', 'L05', 'L02', 'L06', 'L07', 'L08', 'L09', 'L10', 'L01']:
            for s in plan.levels[lid].get('stairs', []):
                if s['core'] == c and s.get('arrow') and s.get('rises_towards'):
                    floor_end = s['rises_towards']
                    break
            if floor_end:
                break
        lay[c] = {'floor_end': floor_end}
    return lay


def flights_on(plan, lid, core):
    fl = [s for s in plan.levels[lid].get('stairs', []) if s['core'] == core]
    return fl


def pick_flights(plan, lid, core):
    """Two full flights for the storey starting at lid."""
    order = [lid] + ['L01', 'L03', 'L04', 'L05', 'L02', 'L06']
    if lid == 'L00':
        order = ['L01', 'L03']
    if lid == 'P-1':
        order = ['P-1']
    for l2 in order:
        fl = flights_on(plan, l2, core)
        if len(fl) == 2 and min(f['treads'] for f in fl) >= 10 and fl[0]['step_axis'] == fl[1]['step_axis']:
            return fl, l2
    return None, None


def risers_for(rise, run):
    """n risers in a flight of plan length `run` (n-1 goings)."""
    best = None
    for n in range(6, 30):
        R = rise / n
        g = run / (n - 1)
        if R > RISER_MAX or g < GOING_MIN:
            continue
        score = abs(2 * R + g - 0.63)
        if best is None or score < best[0]:
            best = (score, n)
    if best is None:
        n = int(math.ceil(rise / RISER_MAX))
        return n
    return best[1]


def storey_stairs(plan, lid, lay):
    """The flights of the storey that starts at `lid`, per core.

    Returns {core: {...}} with the two flights (first leaves the floor,
    second arrives at the next floor), the half landing and the hole the
    stair cuts through the slab above `lid`.
    """
    seq = LEVELS_BUILT + ['ROOF']
    if lid not in seq[:-1]:
        return {}
    nxt = seq[seq.index(lid) + 1]
    z0 = plan.z(lid)
    z1 = plan.z(nxt) if nxt != 'ROOF' else plan.levels['ROOF']['z']
    rise = z1 - z0
    out = {}
    cores = list(CORES) + (['podium'] if lid == 'L00' else [])
    for c in cores:
        fl, src = pick_flights(plan, lid if lid != 'L00' else 'L00', c)
        if c == 'podium':
            fl = [s for s in plan.levels['L00'].get('stairs', []) if s['core'] == 'podium']
            src = 'L00'
            if len(fl) != 2:
                continue
        if not fl:
            continue
        ax = fl[0]['step_axis']
        k = 0 if ax == 'x' else 1           # along index
        j = 1 - k                           # across index
        # the podium stair has no arrow: the +4.800 sheet puts its door to the
        # terrace at the -y end, so both floor landings are at -y (from the
        # street door at +y one walks in under the upper flight) - inferred
        fe = lay[c]['floor_end'] or ('-y' if c == 'podium' else None)
        if fe is None:
            continue
        sgn = 1 if fe[0] == '+' else -1     # floor landing at the + or - end
        # second flight: the one whose band is the arrowed one
        arrowed = None
        for s in plan.levels.get('L01', {}).get('stairs', []) + plan.levels['L03'].get('stairs', []):
            if s['core'] == c and s.get('arrow'):
                arrowed = s['bbox']
                break
        def band(s):
            b = s['bbox']
            return (b[j], b[j + 2])
        if arrowed:
            ab = (arrowed[j], arrowed[j + 2])
            fl.sort(key=lambda s: abs(band(s)[0] - ab[0]))
            second, first = fl[0], fl[1]
        else:
            # no arrow (the podium stair): the flight nearer the street door
            # leaves the floor; inferred
            fl.sort(key=lambda s: s['bbox'][j])
            first, second = fl[1], fl[0]
        lo = min(min(s['bbox'][k] for s in fl), 1e9)
        hi = max(s['bbox'][k + 2] for s in fl)
        run = hi - lo
        n = risers_for(rise / 2.0, run)
        # half landing: from the far end of the flights to the wall
        far = lo if sgn > 0 else hi
        out[c] = dict(core=c, axis=ax, k=k, j=j, sgn=sgn, lo=lo, hi=hi, run=run,
                      first=band(first), second=band(second), z0=z0, z1=z1,
                      rise=rise, n=n, src=src, far=far, level=lid, next=nxt,
                      inferred=(arrowed is None),
                      probe_W=plan_W(plan, 'L01') if c == 'podium' else None)
    return out


def probe_depth(W, k, j, far, sgn, bands, maxd=2.5):
    """Distance from the flights' far end to the wall behind the landing."""
    lo_b = min(b[0] for b in bands)
    hi_b = max(b[1] for b in bands)
    mids = [lo_b + 0.3, 0.5 * (lo_b + hi_b), hi_b - 0.3]
    best = maxd
    for m in mids:
        d = 0.0
        while d < maxd:
            s = far - sgn * (d + 0.025)
            pt = (s, m) if k == 0 else (m, s)
            if W.contains(Point(pt)):
                break
            d += 0.025
        best = min(best, d)
    return best


def rect_kj(k, s0, s1, t0, t1):
    s0, s1 = min(s0, s1), max(s0, s1)
    t0, t1 = min(t0, t1), max(t0, t1)
    if k == 0:
        return box(s0, t0, s1, t1)
    return box(t0, s0, t1, s1)


def stair_geom(st, W):
    """Footprints of one storey's stair: flights, half landing, zone."""
    k, sgn = st['k'], st['sgn']
    dep = probe_depth(st.get('probe_W') or W, k, st['j'], st['far'], sgn, [st['first'], st['second']])
    dep = max(0.9, min(dep, 2.0))
    lo_b = min(st['first'][0], st['second'][0])
    hi_b = max(st['first'][1], st['second'][1])
    land = rect_kj(k, st['far'], st['far'] - sgn * dep, lo_b, hi_b)
    f1 = rect_kj(k, st['lo'], st['hi'], *st['first'])
    f2 = rect_kj(k, st['lo'], st['hi'], *st['second'])
    zone = U([land, rect_kj(k, st['lo'], st['hi'], lo_b, hi_b)])
    st.update(land=land, f1=f1, f2=f2, zone=zone, land_depth=dep)
    return st


def flight_faces(F, k, sgn_up, s_start, t0, t1, z0, z1, n, rail_t=None):
    """One straight flight, plan frame. sgn_up: +1 rises towards +axis.

    n risers between z0 and z1 over |run| = (n-1) goings; the last riser is
    the front of the landing at the top.
    """
    R = (z1 - z0) / n
    run = None

    def P3(s, t, z):
        return (s, t, z) if k == 0 else (t, s, z)

    up = (sgn_up, 0, 0) if k == 0 else (0, sgn_up, 0)
    fw = (-up[0], -up[1], 0)            # faces looking down the flight
    side_lo = (0, -1, 0) if k == 0 else (-1, 0, 0)
    side_hi = (0, 1, 0) if k == 0 else (1, 0, 0)
    return R, P3, up, fw, side_lo, side_hi


def build_flight(F, st, band, s_start, s_end, z0, z1):
    """Treads, risers, sides and soffit of one flight into Faces F."""
    k = st['k']
    n = st['n']
    t0, t1 = band
    run = s_end - s_start
    g = run / (n - 1)
    R = (z1 - z0) / n
    sgn = 1 if run > 0 else -1

    def P3(s, t, z):
        return (s, t, z) if k == 0 else (t, s, z)

    up = (sgn, 0, 0) if k == 0 else (0, sgn, 0)
    down = (-up[0], -up[1], 0)
    tl = (0, -1, 0) if k == 0 else (-1, 0, 0)
    th = (0, 1, 0) if k == 0 else (1, 0, 0)
    L = abs(run)
    slope = (z1 - z0) / L if L > 0 else 1

    def soffit(u):
        return max(z0, z1 - WAIST - slope * (L - u))

    for i in range(n):
        s = s_start + sgn * i * g
        za, zb = z0 + i * R, z0 + (i + 1) * R
        # riser i
        F.quad([P3(s, t0, za), P3(s, t1, za), P3(s, t1, zb), P3(s, t0, zb)], down)
        if i < n - 1:
            s2 = s + sgn * g
            F.quad([P3(s, t0, zb), P3(s, t1, zb), P3(s2, t1, zb), P3(s2, t0, zb)], (0, 0, 1))
            u0, u1 = i * g, (i + 1) * g
            for t, hint in ((t0, tl), (t1, th)):
                F.quad([P3(s, t, soffit(u0)), P3(s2, t, soffit(u1)), P3(s2, t, zb), P3(s, t, zb)], hint)
    # soffit: from where it leaves the floor to the landing
    ub = max(0.0, L - (z1 - WAIST - z0) / slope)
    sb = s_start + sgn * ub
    F.quad([P3(sb, t0, z0), P3(sb, t1, z0), P3(s_end, t1, z1 - WAIST), P3(s_end, t0, z1 - WAIST)],
           (-up[0] * 0.3, -up[1] * 0.3, -1))
    # the last riser's lower part (under the landing nosing) is the landing's


def rail_faces(F, st, band_edge, s_start, s_end, z0, z1, h=RAIL_H, w=0.05):
    """A sloped handrail along the well edge of a flight, with two posts."""
    k = st['k']

    def P2(s, t):
        return (s, t) if k == 0 else (t, s)

    L = s_end - s_start
    a = unit(P2(L, 0) if k == 0 else (0, L)) if False else None
    # rail: a quad tube approximated by an oriented box per flight
    sm = 0.5 * (s_start + s_end)
    zm = 0.5 * (z0 + z1)
    # sloped beam: build 8 corners
    t = band_edge
    pts = []
    for s, z in ((s_start, z0 + h), (s_end, z1 + h)):
        for dt, dz in ((-w / 2, -w / 2), (w / 2, -w / 2), (w / 2, w / 2), (-w / 2, w / 2)):
            x, y = P2(s, t + dt)
            pts.append((x, y, z + dz))
    o = len(F.v)
    F.v.extend(pts)
    # sides of the beam (4 long faces + 2 ends), oriented by hint
    quads = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (0, 3, 2, 1), (4, 5, 6, 7)]
    cen = [sum(p[i] for p in pts) / 8 for i in range(3)]
    for q in quads:
        qp = [pts[i] for i in q]
        c = [sum(p[i] for p in qp) / 4 for i in range(3)]
        hint = [c[i] - cen[i] for i in range(3)]
        order = oriented_quad(qp, hint)
        F.f.append([o + q[i] for i in order])
    for s, z in ((s_start, z0), (s_end, z1)):
        x, y = P2(s, t)
        F.box(x - 0.02, y - 0.02, z, x + 0.02, y + 0.02, z + h - w / 2, skip=('-z',))


# ================================================================== levels
def wall_probe_axis(W, c):
    """Which way does the wall through point c run, and how thick is it."""
    best = None
    for ax in ('x', 'y'):
        a = (1, 0) if ax == 'x' else (0, 1)
        n = (-a[1], a[0])
        ln = LineString([(c[0] - n[0] * 0.6, c[1] - n[1] * 0.6), (c[0] + n[0] * 0.6, c[1] + n[1] * 0.6)])
        for u0, u1 in interval_hits(ln, W):
            if u0 - 0.15 <= 0.6 <= u1 + 0.15 and 0.08 < u1 - u0 < 0.45:
                th = u1 - u0
                along = LineString([(c[0] - a[0] * 1.5, c[1] - a[1] * 1.5), (c[0] + a[0] * 1.5, c[1] + a[1] * 1.5)])
                L = along.intersection(W).length
                if best is None or L > best[0]:
                    best = (L, a, n, dot(c, n) - 0.6 + u0, dot(c, n) - 0.6 + u1)
    return best


def synth_door(c, a, n, room_a, room_b, w=0.86, kind='entrance'):
    """A leaf in the wall between two spaces at point c, opening into
    room_a. The throat runs from room_a's face to room_b's face."""
    s = dot(c, a)
    t = dot(c, n)
    ln = LineString([(c[0] - n[0] * 1.2, c[1] - n[1] * 1.2), (c[0] + n[0] * 1.2, c[1] + n[1] * 1.2)])
    fa = interval_hits(ln, room_a.buffer(0.005))
    fb = interval_hits(ln, room_b.buffer(0.005))
    if not fa or not fb:
        return None
    base = t - 1.2
    # nearest faces of the two spaces to the wall at c
    ta = min([(abs(base + u - t), base + u) for iv in fa for u in iv])[1]
    tb = min([(abs(base + u - t), base + u) for iv in fb for u in iv])[1]
    if abs(tb - ta) > 0.6 or abs(tb - ta) < 0.05:
        return None
    into = 1 if dot((room_a.representative_point().x - c[0], room_a.representative_point().y - c[1]), n) > 0 else -1
    # into: the side of the wall room_a is on
    into = 1 if ta > tb else -1
    P2 = lambda ss, tt: (a[0] * ss + n[0] * tt, a[1] * ss + n[1] * tt)
    hinge = P2(s - w / 2, ta)
    closed = P2(s + w / 2, ta)
    open_end = (hinge[0] + n[0] * into * w, hinge[1] + n[1] * into * w)
    c0, c1 = sorted((ta, tb))
    c0, c1 = c0 - 0.02, c1 + 0.02     # bite through the faces: no sliver of wall left
    gap = Polygon([P2(s - w / 2 - 0.04, c0), P2(s + w / 2 + 0.04, c0), P2(s + w / 2 + 0.04, c1), P2(s - w / 2 - 0.04, c1)])
    return {'hinge': list(hinge), 'closed_end': list(closed), 'open_end': list(open_end),
            'width': w, 'synth': True, 'gap': gap, 'synth_kind': kind}


def stack_entrance(plan, lv, u):
    """The entrance the same flat draws on the storeys above and below.

    +27.900 draws no front door for 128, 129, 140, 141; +24.600 and +31.200
    draw the same flats (same outline, same rooms) with their doors. The
    nearest storey whose flat covers this one (95 % both ways) and has the
    same number of rooms gives the leaf: hinge, shut and open ends."""
    me = u['poly']
    nr = len(u['rec'].get('rooms') or [])
    order = sorted((l for l in plan.levels if l in LEVELS_BUILT and l != lv.id),
                   key=lambda l: (abs(plan.z(l) - lv.z), plan.z(l)))
    for l2 in order:
        for pre, f in plan.units.get(l2, []):
            if pre != u['pre'] or not f.get('entrance'):
                continue
            g = P(f['polygon'])
            ov = g.intersection(me).area
            if ov < 0.95 * me.area or ov < 0.95 * g.area or len(f.get('rooms') or []) != nr:
                continue
            e = f['entrance'][0]
            return dict(e, src_level=l2, src_flat=f['number'])
    return None


def synth_entrance(lv, u, W, plan=None):
    """A door where the drawing has none: where the same flat has it on the
    storey above/below (stack_entrance), else at entrance_suggested."""
    es = u['rec'].get('entrance_suggested')
    if not es:
        return None
    st = stack_entrance(plan, lv, u) if plan is not None else None
    if st is not None:
        h, ce, oe = st['hinge'], st['closed_end'], st['open_end']
        a = unit((ce[0] - h[0], ce[1] - h[1]))
        n = (-a[1], a[0])
        w = math.hypot(ce[0] - h[0], ce[1] - h[1])
        c = ((h[0] + ce[0]) / 2, (h[1] + ce[1]) / 2)
        d = synth_door(c, a, n, u['poly'], lv.corr, w, 'entrance')
        if d:
            d.update(hinge=list(h), closed_end=list(ce), open_end=list(oe), width=w, flat=u['n'],
                     made_from='entrance of flat %s on %s (same flat, same place; this sheet draws none)' %
                               (st['src_flat'], st['src_level']))
            return d
    c = es['centre']
    pr = wall_probe_axis(W, c)
    if pr is None:
        return None
    _, a, n, c0, c1 = pr
    d = synth_door(c, a, n, u['poly'], lv.corr, 0.86, 'entrance')
    if d:
        d['flat'] = u['n']
    return d


def street_run(lv, t, hp):
    """The open run of the +0.000 facade behind hall t (no leaf drawn)."""
    cands = []
    for f in lv.L.get('facade', []):
        if f['state'] != 'open' or f['behind'] != 'core':
            continue
        if not (0.8 <= f['length'] <= 3.0):
            continue
        if LineString([f['a'], f['b']]).distance(hp) > 0.4:
            continue
        cands.append((f['length'], f))
    if not cands:
        return None
    st_cells = [s for s in lv.L.get('stairs', []) if s['core'] == t]

    def stair_d(f):
        m = Point(0.5 * (f['a'][0] + f['b'][0]), 0.5 * (f['a'][1] + f['b'][1]))
        return min([m.distance(box(*s['bbox'])) for s in st_cells] or [9])
    cands.sort(key=lambda c: (-stair_d(c[1]), -c[0]))
    return cands[0][1]


def made_street_doors(lv, W, raw_doors):
    """Halls whose street door the +0.000 sheet does not draw (C3: its east
    face is drawn as a wall; the hall opens onto the commercial floor). The
    stage-1 build inferred an open run there and the street file put its
    door on it, so the opening is kept - as a MADE double door (two glazed
    leaves opening out), flagged made: true for the owner."""
    out = []
    for t, hp in lv.halls:
        drawn = [d for d in raw_doors if 'outside' in (d.get('opens_into'), d.get('from_side'))
                 and Point(d['centre']).distance(hp) < 0.4]
        if drawn:
            continue
        f = street_run(lv, t, hp)
        if f is None:
            continue
        A, B = f['a'], f['b']
        a = unit((B[0] - A[0], B[1] - A[1]))
        n = (-a[1], a[0])
        m = (0.5 * (A[0] + B[0]), 0.5 * (A[1] + B[1]))
        if hp.buffer(0.05).contains(Point(m[0] + n[0] * 0.4, m[1] + n[1] * 0.4)):
            pass
        else:
            n = (-n[0], -n[1])                      # n points into the hall
        # wall depth behind the run, from the facade line inwards
        dep = 0.0
        while dep < 0.6 and W.buffer(0.005).contains(Point(m[0] + n[0] * (dep + 0.01), m[1] + n[1] * (dep + 0.01))):
            dep += 0.01
        dep = max(dep, 0.10)
        s0, s1 = dot(A, a), dot(B, a)
        t0 = dot(A, n)
        P2 = lambda ss, tt: (a[0] * ss + n[0] * tt, a[1] * ss + n[1] * tt)
        gap = Polygon([P2(s0, t0 - 0.02), P2(s1, t0 - 0.02), P2(s1, t0 + dep + 0.02), P2(s0, t0 + dep + 0.02)])
        # the leaves hang in the facade line and open OUT: the C3 run lands
        # under the half landing, where leaves opening in would close the
        # one way round to the first flight
        tin = t0
        L = s1 - s0
        leaves = [(s0, s0 + L / 2), (s1, s1 - L / 2)] if L > 1.6 else [(s0, s1)]
        for hs, cs in leaves:
            w = abs(cs - hs)
            hinge = P2(hs, tin)
            closed = P2(cs, tin)
            out.append({'hinge': list(hinge), 'closed_end': list(closed),
                        'open_end': [hinge[0] - n[0] * w, hinge[1] - n[1] * w], 'width': w,
                        'synth': True, 'synth_kind': 'street', 'hall': t, 'gap': gap,
                        'centre': [0.5 * (hinge[0] + closed[0]), 0.5 * (hinge[1] + closed[1])],
                        'made_from': 'the stage-1 open run of the facade (%.2f m at %s..%s) kept as a made '
                                     'double door; the sheet draws a wall there' % (L, [R3(v) for v in A], [R3(v) for v in B])})
    return out


def sealed_room_doors(lv, u, doors, W):
    """Rooms of a flat that no drawn door reaches from its entrance: give
    each a door in the longest wall it shares with a reached room. The
    drawing omits these doors (e.g. the bedroom of the bar_E flat by the
    wing, 12/33/54/75/96/117/138/159/180)."""
    rooms = [P(r['polygon']) for r in (u['rec'].get('rooms') or [])]
    if len(rooms) < 2:
        return []
    gaps = [d['gap'] for d in doors]
    made = []
    for _round in range(4):
        # rooms joined by a door throat, or touching (open plan pieces)
        adj = defaultdict(set)
        for i, ri in enumerate(rooms):
            for j, rj in enumerate(rooms):
                if j <= i:
                    continue
                if ri.distance(rj) < 0.02 and ri.intersection(rj.buffer(0.03)).length >= 0 and \
                        ri.buffer(0.03).intersection(rj.buffer(0.03)).area > 0.02:
                    adj[i].add(j); adj[j].add(i)
                    continue
                for g in gaps + [m['gap'] for m in made]:
                    gg = g.buffer(0.12)
                    if gg.intersects(ri) and gg.intersects(rj):
                        adj[i].add(j); adj[j].add(i)
                        break
        start = set()
        for d in doors + made:
            if d.get('kind') == 'entrance':
                for i, r in enumerate(rooms):
                    if d['gap'].buffer(0.12).intersects(r):
                        start.add(i)
        if not start:
            return made
        seen, stack = set(start), list(start)
        while stack:
            i = stack.pop()
            for j in adj[i]:
                if j not in seen:
                    seen.add(j); stack.append(j)
        sealed = [i for i in range(len(rooms)) if i not in seen and rooms[i].area > 1.0]
        if not sealed:
            return made
        progress = False
        for i in sealed:
            best = None
            for j in seen:
                strip = grow(rooms[i], 0.3).intersection(grow(rooms[j], 0.3)).intersection(W)
                for q in polys(strip, 0.01):
                    x0, y0, x1, y1 = q.bounds
                    L = max(x1 - x0, y1 - y0)
                    sc = L + (3.0 if j in start else 0.0)
                    if L > 1.1 and (best is None or sc > best[0]):
                        best = (sc, q, j)
            if best is None:
                continue
            L, q, j = best
            x0, y0, x1, y1 = q.bounds
            if x1 - x0 >= y1 - y0:
                a, n = (1.0, 0.0), (0.0, 1.0)
            else:
                a, n = (0.0, 1.0), (-1.0, 0.0)
            # where along the wall: the leaf must not sweep the drawn
            # furniture (the bed of the bar_E bedroom stands at the middle
            # of the wall); the middle, else an end clear of the corners
            cm_ = (0.5 * (x0 + x1), 0.5 * (y0 + y1))
            lo_, hi_ = (x0, x1) if a[0] else (y0, y1)
            k_ = 0 if a[0] else 1
            lo_ = max(lo_, rooms[i].bounds[k_], rooms[j].bounds[k_])      # the face the two rooms share,
            hi_ = min(hi_, rooms[i].bounds[k_ + 2], rooms[j].bounds[k_ + 2])  # not the walls round its ends
            fb = U(furn_boxes(u['pre'], u['n']))
            ri_, rj_ = rooms[i].buffer(0.03), rooms[j].buffer(0.03)

            def spans(cand):
                """the whole throat lies between room i and room j"""
                h, ce = cand['hinge'], cand['closed_end']
                av = unit((ce[0] - h[0], ce[1] - h[1]))
                nv = (-av[1], av[0])
                for f_ in (0.05, 0.5, 0.95):
                    px, py = h[0] + (ce[0] - h[0]) * f_, h[1] + (ce[1] - h[1]) * f_
                    sides = []
                    for sg in (-1, 1):
                        q_ = None
                        for dd_ in (0.15, 0.25, 0.35):
                            pt_ = Point(px + nv[0] * sg * dd_, py + nv[1] * sg * dd_)
                            if ri_.contains(pt_):
                                q_ = 'i'
                                break
                            if rj_.contains(pt_):
                                q_ = 'j'
                                break
                        sides.append(q_)
                    if sorted(map(str, sides)) != ['i', 'j']:
                        return False
                return True
            best_d = None
            mid_ = 0.5 * (lo_ + hi_)
            steps = int((hi_ - lo_) / 0.05)
            for k2 in sorted(range(steps + 1), key=lambda k2: abs(lo_ + k2 * 0.05 - mid_)):
                sc = lo_ + k2 * 0.05
                c = (sc, cm_[1]) if a[0] else (cm_[0], sc)
                dd = synth_door(c, a, n, rooms[i], rooms[j], 0.80, 'room')
                if not dd:
                    continue
                for flip in (False, True):
                    cand = dict(dd)
                    if flip:
                        h, ce = cand['hinge'], cand['closed_end']
                        oe = (ce[0] + cand['open_end'][0] - h[0], ce[1] + cand['open_end'][1] - h[1])
                        cand.update(hinge=list(ce), closed_end=list(h), open_end=list(oe))
                    if not spans(cand):
                        continue
                    h = cand['hinge']
                    sweep = Point(h).buffer(0.80).intersection(
                        box(min(h[0], cand['closed_end'][0], cand['open_end'][0]) - 0.01,
                            min(h[1], cand['closed_end'][1], cand['open_end'][1]) - 0.01,
                            max(h[0], cand['closed_end'][0], cand['open_end'][0]) + 0.01,
                            max(h[1], cand['closed_end'][1], cand['open_end'][1]) + 0.01))
                    hit = sweep.buffer(0.10).intersection(fb).area if not fb.is_empty else 0.0
                    if best_d is None or hit < best_d[0] - 1e-4:
                        best_d = (hit, cand)
                if best_d is not None and best_d[0] < 1e-4:
                    break
            d = best_d[1] if best_d else None
            if d:
                d['flat'] = u['n']
                d['note'] = 'room %d has no door on the sheet' % i
                made.append(d)
                progress = True
        if not progress:
            break
    return made


def leaf_mesh(geo, style, w, vs, hgt):
    """Shared leaf mesh in the node's local frame: x along the shut leaf
    from the hinge, y = vs * thickness, z up from the floor."""
    mid = 'leaf_%s_%d_%s_%d' % (style, round(w * 100), 'p' if vs > 0 else 'n', round(hgt * 100))
    if mid in geo.shared:
        return mid
    t = LEAF_T * vs
    y0, y1 = sorted((0.0, t))
    L = w - 0.006
    if style == 'glazed':
        fr = 0.07
        F = Faces()
        F.box(0.003, y0, 0.01, 0.003 + fr, y1, hgt)
        F.box(L - fr, y0, 0.01, L, y1, hgt)
        F.box(0.003 + fr, y0, 0.01, L - fr, y1, 0.01 + 0.12)
        F.box(0.003 + fr, y0, hgt - fr, L - fr, y1, hgt)
        geo.shared_faces(mid, MAT_TRIM, F.v, F.f)
        G = Faces()
        ym = 0.5 * (y0 + y1)
        G.box(0.003 + fr, ym - 0.004, 0.13, L - fr, ym + 0.004, hgt - fr)
        geo.shared_faces(mid, MAT_GLASS, G.v, G.f)
        H = Faces()
    else:
        F = Faces()
        F.box(0.003, y0, 0.01, L, y1, hgt)
        geo.shared_faces(mid, MAT_ENTR if style == 'entrance' else MAT_LEAF, F.v, F.f)
        H = Faces()
    # lever handles on both faces
    hx = L - 0.075
    for yy, d in ((y0, -1), (y1, 1)):
        H.box(hx - 0.11, yy + d * 0.045, 1.0, hx + 0.01, yy + d * 0.065, 1.025)
        H.box(hx - 0.01, min(yy, yy + d * 0.045), 0.99, hx + 0.01, max(yy, yy + d * 0.045), 1.035, )
    geo.shared_faces(mid, MAT_HANDLE, H.v, H.f)
    return mid


SKIRT = True
seen_sill = set()


HOUSE_IN = 2.73      # L01 walls round the terrace stair stop here (the street's house: 2.75 high)


def stair_house_zone(plan, lay):
    """Plan-frame footprint of the street file's terrace stair house, its
    walls included (+0.25): the podium stair's flights and half landing
    (its L00 storey's zone) and the 1.25 m top landing north of them - the
    street's STAIR_HOLE (lib_city._stair_hole reads the same stair off
    plan_meta) grown by the house's 0.20 walls."""
    try:
        st = storey_stairs(plan, 'L00', lay).get('podium')
        if st is not None and st.get('zone') is None and st.get('probe_W') is not None:
            stair_geom(st, st['probe_W'])
    except Exception as e:
        print('stair_house_zone:', e)
        st = None
    if not st or st.get('zone') is None or st['zone'].is_empty:
        return None
    x0, y0, x1, y1 = st['zone'].bounds
    return box(x0 - 0.25, y0 - 1.25 - 0.25, x1 + 0.25, y1 + 0.25)


def build_level(plan, lid, geo, lay, report):
    seen_sill.clear()
    lv = Level(plan, lid)
    L = lv.L
    z, h = lv.z, lv.h
    W = lv.W0
    notes = lv.notes
    nm = lambda tok, kind, mat: 'in_%s_%s%s__%s' % (lid, (tok + '_') if tok else '', kind, mat)

    # ---------------------------------------------------------- doors
    raw_doors = [dict(d) for d in L.get('doors', [])]
    synth = []
    for u in lv.units:
        if not u['rec'].get('entrance') and u['rec'].get('entrance_suggested'):
            d = synth_entrance(lv, u, W, plan)
            if d:
                synth.append(d)
                notes.append('flat %s: no entrance drawn; door made %s' %
                             (u['n'], d.get('made_from') or 'at entrance_suggested %s' % u['rec']['entrance_suggested']['centre']))
            else:
                notes.append('flat %s: no entrance drawn and none could be made' % u['n'])
    if lid == 'L00':
        for d in made_street_doors(lv, W, raw_doors):
            synth.append(d)
            nt = '%s hall: no street door drawn on the +0.000 sheet; %s' % (d['hall'], d['made_from'])
            if nt not in notes:
                notes.append(nt)
    if synth:
        W = W.difference(U([d['gap'] for d in synth]))
    # lift shafts and their door throats (cut where a level draws none)
    shafts = lift_shafts(plan, lid)
    # L00 draws the lift boxes but its poche leaves their walls out: take
    # the shaft walls of the first floor that has them (flagged)
    for sh in shafts:
        ring = grow(sh['poly'], 0.22).difference(sh['poly'])
        ref_W = plan_W(plan, 'L01')
        have, ref = W.intersection(ring).area, ref_W.intersection(ring).area
        if ref > 0 and have < 0.5 * ref:
            W = U([W, ref_W.intersection(ring)])
            notes.append('%s lift %d: shaft walls not drawn on %s; walls of L01 used' % (sh['core'], sh['k'], lid))
    lift_stops = []
    for sh in shafts:
        seg, gap, made = lift_door(W, sh, lv.SP.difference(U([q['poly'] for q in shafts])))
        if gap is not None and made:
            W = W.difference(gap)
            notes.append('%s lift %d: no landing door throat drawn on %s; cut one like the floors above' %
                         (sh['core'], sh['k'], lid))
        lift_stops.append(dict(sh, seg=seg, gap=gap))

    doors = []
    for d in raw_doors + synth:
        hinge, closed = d['hinge'], d['closed_end']
        if 'gap' in d:
            g = d['gap']
            a = unit((closed[0] - hinge[0], closed[1] - hinge[1]))
            n = (-a[1], a[0])
            cs = sorted(dot(p, n) for p in g.exterior.coords[:-1])
            ss = sorted(dot(p, a) for p in g.exterior.coords[:-1])
            fr = (a, n, ss[0], ss[-1], cs[0], cs[-1], dot(hinge, n))
        else:
            r = door_gap(lv, hinge, closed, W)
            if r is None:
                notes.append('door at %s: no jambs found, leaf only' % (d['centre'],))
                a = unit((closed[0] - hinge[0], closed[1] - hinge[1]))
                n = (-a[1], a[0])
                t0 = dot(hinge, n)
                oe = d['open_end']
                into = 1 if dot((oe[0] - hinge[0], oe[1] - hinge[1]), n) > 0 else -1
                c0, c1 = sorted((t0, t0 - into * 0.2))
                ss = sorted((dot(hinge, a), dot(closed, a)))
                fr = (a, n, ss[0], ss[1], c0, c1, t0)
                g = Polygon([(a[0] * s + n[0] * t, a[1] * s + n[1] * t)
                             for s, t in ((ss[0], c0), (ss[1], c0), (ss[1], c1), (ss[0], c1))])
            else:
                g, fr = r
        a, n, a0, a1, c0, c1, t0 = fr
        sm = 0.5 * (a0 + a1)
        side = []
        for t in (c0 - 0.3, c1 + 0.3):
            side.append(lv.space_at((a[0] * sm + n[0] * t, a[1] * sm + n[1] * t)))
        d.update(gap=g, frame=fr, sides=side)
        doors.append(d)

    # throats the drawing leaves without a recognised leaf between a common
    # space and the terrace (the podium stair's door onto the +4.800 terrace)
    if not lv.terrace.is_empty and not lv.corr.is_empty:
        cand = grow(lv.corr, 0.3).intersection(grow(lv.terrace, 0.3)).difference(W).difference(
            lv.corr).difference(lv.terrace)
        have = U([d['gap'] for d in doors])
        for q in polys(cand, 0.05):
            if q.intersects(have):
                continue
            x0, y0, x1, y1 = q.bounds
            if max(x1 - x0, y1 - y0) < 0.7:
                continue
            if x1 - x0 >= y1 - y0:
                a_, n_ = (1.0, 0.0), (0.0, 1.0)
            else:
                a_, n_ = (0.0, 1.0), (-1.0, 0.0)
            c_ = (0.5 * (x0 + x1), 0.5 * (y0 + y1))
            w_ = round(max(x1 - x0, y1 - y0) - 0.1, 2)
            room_a = [p for p in polys(lv.corr) if p.distance(q) < 0.05]
            if not room_a:
                continue
            d = synth_door(c_, a_, n_, room_a[0], lv.terrace, w_, 'common')
            if d is None:
                continue
            W = W.difference(d['gap'])
            a2 = unit((d['closed_end'][0] - d['hinge'][0], d['closed_end'][1] - d['hinge'][1]))
            n2 = (-a2[1], a2[0])
            cs = sorted(dot(p, n2) for p in d['gap'].exterior.coords[:-1])
            ss = sorted(dot(p, a2) for p in d['gap'].exterior.coords[:-1])
            d['frame'] = (a2, n2, ss[0], ss[-1], cs[0], cs[-1], dot(d['hinge'], n2))
            d['sides'] = [('corr', None), ('terrace', None)]
            d['centre'] = list(c_)
            d['flat'] = None
            doors.append(d)
            notes.append('opening %s between %s corridor and the terrace has no leaf on the sheet; door made' %
                         ([round(v, 2) for v in c_], lid))

    # classify + owner
    for i, d in enumerate(doors):
        kinds = sorted(s[0] for s in d['sides'])
        toks = [s[1] for s in d['sides'] if s[0] in ('unit', 'balc', 'hall')]
        unit_toks = [s[1] for s in d['sides'] if s[0] == 'unit']
        if 'unit' in kinds and ('corr' in kinds or 'comm' in kinds):
            kind, owner = 'entrance', unit_toks[0]
        elif 'unit' in kinds and ('balc' in kinds or 'out' in kinds or 'loggia' in kinds or 'terrace' in kinds):
            kind, owner = 'balcony', unit_toks[0]
        elif kinds == ['unit', 'unit']:
            kind = 'room'
            owner = unit_toks[0] if unit_toks[0] == unit_toks[1] else None
        elif 'out' in kinds and 'hall' in kinds:
            kind, owner = 'street', toks[0]
        elif 'hall' in kinds:
            kind, owner = 'hall', [s[1] for s in d['sides'] if s[0] == 'hall'][0]
        elif 'out' in kinds or 'loggia' in kinds or 'terrace' in kinds or 'balc' in kinds:
            kind, owner = ('street' if lid == 'L00' else 'balcony'), None
        elif 'unit' in kinds:
            kind, owner = 'room', unit_toks[0]
        else:
            kind, owner = 'common', None
        if d.get('synth') and d.get('flat') is not None:
            kind = d.get('synth_kind', 'entrance')
            owner = [u['token'] for u in lv.units if u['n'] == d['flat']][0]
        elif d.get('synth') and d.get('hall'):
            kind, owner = 'street', d['hall']
        elif d.get('synth'):
            kind, owner = d.get('synth_kind', 'common'), None
        d['kind'], d['owner'] = kind, owner
        ext_share = d['gap'].intersection(grow(lv.OUT, EXT_D)).area / max(d['gap'].area, 1e-6)
        d['ext'] = ext_share > 0.5 or kind in ('balcony', 'street')

    # rooms no drawn door reaches from the flat's entrance
    for u in lv.units:
        ud = [d for d in doors if d['owner'] == u['token']]
        extra = sealed_room_doors(lv, u, ud, W)
        for d in extra:
            W = W.difference(d['gap'])
            a_ = unit((d['closed_end'][0] - d['hinge'][0], d['closed_end'][1] - d['hinge'][1]))
            n_ = (-a_[1], a_[0])
            cs = sorted(dot(p, n_) for p in d['gap'].exterior.coords[:-1])
            ss = sorted(dot(p, a_) for p in d['gap'].exterior.coords[:-1])
            d['frame'] = (a_, n_, ss[0], ss[-1], cs[0], cs[-1], dot(d['hinge'], n_))
            d['sides'] = [('unit', u['token']), ('unit', u['token'])]
            d['centre'] = list(d['gap'].centroid.coords[0])
            d['kind'], d['owner'], d['ext'] = 'room', u['token'], False
            doors.append(d)
            notes.append('flat %s: %s; door made at %s' % (u['n'], d['note'], [round(v, 2) for v in d['centre']]))
            report.setdefault('made_room_doors', []).append([lid, u['n'], [round(v, 2) for v in d['centre']]])

    # A pair of leaves in one doorway (the core lobbies' double doors, every
    # storey): each leaf measured its own throat, so the pair got two door
    # frames, offset by half a leaf, and their inner jambs stood in the middle
    # of the opening as two posts (user, 2026-11-25: "where the double door
    # is, there are 2 planks in the middle"). Leaves that close in the same
    # wall line onto overlapping throats share ONE throat - the union - and
    # so one frame, one head, one threshold, jambs only at the outer ends.
    for i, d in enumerate(doors):
        for e in doors[i + 1:]:
            a1_, a2_ = d['frame'][0], e['frame'][0]
            if abs(abs(dot(a1_, a2_)) - 1.0) > 0.01:
                continue                                    # not the same wall line
            n1_ = d['frame'][1]
            if abs(dot(d['hinge'], n1_) - dot(e['hinge'], n1_)) > 0.10:
                continue
            if not d['gap'].buffer(0.01).intersects(e['gap']):
                continue
            g = U([d['gap'], e['gap']])
            g = g if g.geom_type == 'Polygon' else g.convex_hull
            pts = list(g.exterior.coords[:-1])
            for x in (d, e):
                a_, n_, _, _, _, _, t_ = x['frame']
                ss = [dot(p, a_) for p in pts]
                cs = [dot(p, n_) for p in pts]
                x['gap'] = g
                x['frame'] = (a_, n_, min(ss), max(ss), min(cs), max(cs), t_)
            report.setdefault('paired_doors', []).append([lid, [round(v, 2) for v in g.centroid.coords[0]]])

    # door ids: per owner, in plan order
    cnt = defaultdict(int)
    for d in sorted(doors, key=lambda d: (str(d['owner']), round(d['hinge'][1], 1), round(d['hinge'][0], 1))):
        cnt[d['owner']] += 1
        d['id'] = 'd%d' % cnt[d['owner']]

    # ---------------------------------------------------------- walls
    OUTg = grow(lv.OUT, EXT_D)
    EXT = W.intersection(OUTg)
    WI = W.difference(OUTg)
    # voids: ducts and joint gaps inside the outline, not a space, not a gap
    gaps_all = U([d['gap'] for d in doors] + [s['gap'] for s in lift_stops if s['gap'] is not None])
    win_gaps = []
    for o in L.get('openings', []):
        aa, bb = o['a'], o['b']
        dv = unit((bb[0] - aa[0], bb[1] - aa[1]))
        nv = (-dv[1], dv[0])
        t = o.get('wall_depth', 0.2) / 2 + 0.02
        g = Polygon([(aa[0] + nv[0] * t, aa[1] + nv[1] * t), (bb[0] + nv[0] * t, bb[1] + nv[1] * t),
                     (bb[0] - nv[0] * t, bb[1] - nv[1] * t), (aa[0] - nv[0] * t, aa[1] - nv[1] * t)])
        g = g.difference(W)
        # the extractor reads some loggia mouths as openings: an "opening"
        # lying in a balcony or a room is not a window in a wall
        open_sp = U([lv.balc, lv.loggias, lv.SP])
        if g.is_empty or g.intersection(open_sp).area > 0.3 * g.area:
            continue
        isdoor = any(d['gap'].buffer(0.05).intersects(g) and d['ext'] for d in doors)
        win_gaps.append({'gap': g, 'door': isdoor, 'rec': o})
    spaces_all = U([lv.SP, lv.balc, lv.loggias, lv.terrace] + [s['poly'] for s in shafts])
    voids = lv.outline.difference(U([W, spaces_all, grow(gaps_all, 0.03)] + [grow(w['gap'], 0.03) for w in win_gaps]))
    fills = []
    for v in polys(voids, 0.03):
        if v.intersects(grow(lv.OUT, 0.03)):
            continue
        if v.buffer(-0.04).is_empty:
            continue
        fills.append(v)
    FILL = U(fills)
    if fills:
        report.setdefault('fills', {})[lid] = [round(sum(f.area for f in fills), 2), len(fills)]
    WI = clean(U([WI, FILL]))
    LIN = grow(EXT, LIN_OUT).intersection(grow(lv.SP, LIN_IN)).difference(WI)
    LIN = clean(LIN)

    excl = lv.owner_regions()
    wall_groups = []      # (geom, z0, z1, top)
    wall_groups.append((WI, z, z + h, True))
    wall_groups.append((LIN, z, z + h, True))
    # door heads (a pair of leaves shares one throat: one head)
    seen_gap = set()
    for d in doors:
        gk = tuple(round(v, 2) for v in d['gap'].bounds)
        d['gap_key'] = gk
        if gk in seen_gap:
            continue
        seen_gap.add(gk)
        if d['ext']:
            head = DOOR_H if d['kind'] == 'street' else BDOOR_H
            pc = grow(d['gap'], LIN_OUT).intersection(grow(lv.SP, LIN_IN)).difference(WI).difference(LIN)
            wall_groups.append((pc, z + head, z + h, False))
        else:
            wall_groups.append((d['gap'], z + DOOR_H, z + h, False))
    for wg in win_gaps:
        if wg['door']:
            continue        # the door's own head covers it
        pc = grow(wg['gap'], LIN_OUT).intersection(grow(lv.SP, LIN_IN)).difference(WI).difference(LIN)
        wall_groups.append((pc, z, z + WIN_SILL, True))
        wall_groups.append((pc, z + WIN_HEAD, z + h, False))
    for s in lift_stops:
        if s['gap'] is not None:
            wall_groups.append((s['gap'], z + DOOR_H, z + h, False))
    # The terrace stair house (L01 only): the street file builds it as a
    # 2.75 m house on the +4.8 deck (lib_city STAIR_HOLE, lining ceiling at
    # z + 2.74). The walls round its landing stop under that ceiling, not at
    # z + h - at full storey height their pale tops stood out over the
    # house's dark roof from the whole terrace (build 4).
    if lid == 'L01':
        hs = stair_house_zone(plan, lay)
        if hs is not None:
            capped = []
            for g, z0, z1, top in wall_groups:
                inn = g.intersection(hs)
                if inn.is_empty or z1 <= z + HOUSE_IN:
                    capped.append((g, z0, z1, top))
                    continue
                capped.append((g.difference(hs), z0, z1, top))
                if z0 < z + HOUSE_IN:
                    capped.append((inn, z0, z + HOUSE_IN, True))
            wall_groups = capped
    # wall groups into owner pieces
    for g, z0, z1, top in wall_groups:
        if g.is_empty:
            continue
        for tok, piece in lv.split_owner(g, excl):
            geo.prism(nm(tok, 'walls', MAT_WALL), MAT_WALL, piece, z0, z1, top=top, bottom=not top and z0 > z + 0.01)

    # ---------------------------------------------------------- stairs here
    here = storey_stairs(plan, lid, lay)
    for c, st in here.items():
        stair_geom(st, W)
    prev = None
    seq = LEVELS_BUILT
    if lid in seq and seq.index(lid) > 0:
        prev = storey_stairs(plan, seq[seq.index(lid) - 1], lay)
        for c, st in prev.items():
            stair_geom(st, W)
    hole_floor = U([st['zone'] for st in (prev or {}).values()])
    hole_ceil = U([st['zone'] for st in here.values()])
    shaft_g = U([s['poly'] for s in shafts])

    # ---------------------------------------------------------- floors
    meta_units = []
    for u in lv.units:
        fp = u['poly']
        rooms = u['rec'].get('rooms') or []
        kinds, wet_rj = room_kinds_for(plan, u['pre'], u['rec'])
        wet = []
        rm_meta = []
        for i, r in enumerate(rooms):
            rp = P(r['polygon'])
            kd = kinds[i] if kinds and i < len(kinds) else (None, None, None)
            if kinds is not None:
                is_wet = bool(kd[0]) and any(wd in kd[0].lower() for wd in WET_WORDS)
                how = 'rooms.json'
            else:
                is_wet = guess_wet(rp, u, doors, win_gaps)
                how = 'guess'
            if is_wet:
                wet.append(rp)
            rm = {'poly': coords_m(rp, tol=0.01), 'area': round(rp.area, 2), 'finish': 'tile' if is_wet else 'parquet',
                  'finish_from': how}
            if kd[0]:
                rm.update(kind=kd[0], name=kd[1], rooms_id=kd[2])
            rm_meta.append(rm)
        if wet_rj:
            # rooms.json splits wet rooms off at necks the plan's rooms keep
            wet = wet + wet_rj
        tile = grow(U(wet), 0.10).intersection(fp) if wet else Polygon()
        parq = fp.difference(tile)
        geo.prism(nm(u['token'], 'floor', MAT_PARQ), MAT_PARQ, parq, z, z, top=True, sides=False)
        if not tile.is_empty:
            geo.prism(nm(u['token'], 'floor', MAT_TILE), MAT_TILE, tile, z, z, top=True, sides=False)
        geo.prism(nm(u['token'], 'ceiling', MAT_CEIL), MAT_CEIL, fp, z + lv.clear, z + lv.clear,
                  top=False, bottom=True, sides=False)
        for b in u['balc']:
            geo.prism(nm(u['token'], 'loggia', MAT_TILE), MAT_TILE, b, z, z + BALC_TOP, top=True, sides=True)
        u['rooms_meta'] = rm_meta
        u['tile'] = tile
        meta_units.append(u)
    # corridor / common
    corr = lv.corr.difference(hole_floor).difference(shaft_g)
    if not corr.is_empty:
        geo.prism(nm(None, 'floor', MAT_STONE), MAT_STONE, corr, z - SLAB, z, top=True, sides=True)
    corr_c = lv.corr.difference(hole_ceil).difference(shaft_g)
    if lid == 'L01' and stair_house_zone(plan, lay) is not None:
        corr_c = corr_c.difference(stair_house_zone(plan, lay))   # the house's own ceiling is the street's
    if not corr_c.is_empty:
        geo.prism(nm(None, 'ceiling', MAT_CEIL), MAT_CEIL, corr_c, z + lv.clear, z + lv.clear,
                  top=False, bottom=True, sides=False)
    if not lv.loggias.is_empty:
        geo.prism(nm(None, 'loggia', MAT_TILE), MAT_TILE, lv.loggias, z, z + BALC_TOP)
    halls_meta = []
    for t, hp in lv.halls:
        f = hp.difference(hole_floor).difference(shaft_g)
        geo.prism(nm(t, 'floor', MAT_STONE), MAT_STONE, f, z - SLAB, z, top=True, sides=True)
        geo.prism(nm(t, 'ceiling', MAT_CEIL), MAT_CEIL, hp.difference(hole_ceil).difference(shaft_g),
                  z + lv.clear, z + lv.clear, top=False, bottom=True, sides=False)
    if not lv.commercial.is_empty:
        geo.prism(nm(None, 'floor', MAT_COMM), MAT_COMM, lv.commercial, z, z, top=True, sides=False)
        geo.prism(nm(None, 'ceiling', MAT_CEIL), MAT_CEIL, lv.commercial, z + lv.clear, z + lv.clear,
                  top=False, bottom=True, sides=False)

    # ---------------------------------------------------------- doors: throats, linings, leaves
    floors_here = U([u['poly'] for u in lv.units] + [b for u in lv.units for b in u['balc']] +
                    [lv.corr, lv.loggias, lv.commercial] + [hp for _, hp in lv.halls]).buffer(0.002)
    leaf_n = 0
    seen_gap = set()
    for d in doors:
        tok = d['owner']
        a, n, a0, a1, c0, c1, t0 = d['frame']
        g = d['gap']
        first = d['gap_key'] not in seen_gap
        seen_gap.add(d['gap_key'])
        fmat = MAT_STONE if d['kind'] in ('entrance', 'common', 'street', 'hall') else (
            MAT_TILE if d['kind'] == 'balcony' else MAT_PARQ)
        # only where no room / corridor floor is already (no coplanar fight)
        thr = g.difference(floors_here)
        if first and thr.area > 0.005:
            geo.prism(nm(tok, 'threshold', fmat), fmat, thr, z, z, top=True, sides=False)
        if not d['ext'] and first:
            F = Faces()
            cc0, cc1 = c0 - 0.012, c1 + 0.012
            for s0, s1 in ((a0, a0 + 0.025), (a1 - 0.025, a1)):
                F.obox(((s0 + s1) / 2 * a[0] + (cc0 + cc1) / 2 * n[0], (s0 + s1) / 2 * a[1] + (cc0 + cc1) / 2 * n[1]),
                       a, n, (s1 - s0) / 2, (cc1 - cc0) / 2, z, z + DOOR_H)
            F.obox(((a0 + a1) / 2 * a[0] + (cc0 + cc1) / 2 * n[0], (a0 + a1) / 2 * a[1] + (cc0 + cc1) / 2 * n[1]),
                   a, n, (a1 - a0) / 2 - 0.025, (cc1 - cc0) / 2, z + DOOR_H - 0.025, z + DOOR_H)
            geo.faces(nm(tok, 'frames', MAT_TRIM), MAT_TRIM, F.v, F.f)
        # the leaf
        hinge, closed = d['hinge'], d['closed_end']
        w = math.hypot(closed[0] - hinge[0], closed[1] - hinge[1])
        tm = 0.5 * (c0 + c1)
        body = 1 if tm >= t0 else -1
        nb = (n[0] * body, n[1] * body)
        vs = 1 if (nb[0] * a[1] + (-nb[1]) * a[0]) > 0 else -1
        style = 'glazed' if d['kind'] in ('balcony', 'street') else ('entrance' if d['kind'] == 'entrance' else 'room')
        hgt = (BDOOR_H if d['kind'] == 'balcony' else DOOR_H) - 0.02
        mid = leaf_mesh(geo, style, w, vs, hgt)
        node = nm(tok, d['id'] + '_swing', MAT_TRIM if style == 'glazed' else (MAT_ENTR if style == 'entrance' else MAT_LEAF))
        geo.instance(node, mid, (hinge[0], hinge[1], z), math.atan2(-a[1], a[0]))
        oe = d['open_end']
        d['node'] = node
        d['shut'] = round(heading(a), 2)
        d['open'] = round(signed_angle(a, unit((oe[0] - hinge[0], oe[1] - hinge[1]))), 1)
        leaf_n += 1

    # ---------------------------------------------------------- skirting, thresholds
    # one extruded profile round the free floor of each owner (flats,
    # offices, the corridor, the halls), cut at every door throat; and a
    # stone sill in the throat of a door between two floor finishes
    if SKIRT:
        WALLS = U([WI, LIN, EXT])
        cut = grow(U([gaps_all] + [wg['gap'] for wg in win_gaps if wg['door']]), 0.005)
        owners = [(u['token'], u['poly']) for u in lv.units] + [(None, lv.corr)] + list(lv.halls)
        if not lv.commercial.is_empty:
            owners.append((None, lv.commercial))
        for tok, fp in owners:
            if fp.is_empty:
                continue
            if tok is None or tok in [t for t, _ in lv.halls]:
                fp = fp.difference(hole_floor).difference(shaft_g)
            free = fp.difference(WALLS)
            band = grow(WALLS, SKIRT_T).intersection(free).difference(cut)
            band = U([q for q in polys(band, 0.0005) if q.buffer(-0.004).area > 0])
            if band.is_empty:
                continue
            # the top and the faces that look into the room; the faces
            # against the wall are never seen (half the triangles)
            F = Faces()
            wb = WALLS.buffer(0.002)
            for q in polys(band.simplify(0.003), 0.0005):
                for r in [q.exterior] + list(q.interiors):
                    cs = list(r.coords)
                    ccw = r.is_ccw
                    for (ax_, ay_), (bx_, by_) in zip(cs[:-1], cs[1:]):
                        L_ = math.hypot(bx_ - ax_, by_ - ay_)
                        if L_ < 1e-4:
                            continue
                        # outward normal of this edge (away from the band)
                        ex, ey = (bx_ - ax_) / L_, (by_ - ay_) / L_
                        nx_, ny_ = (ey, -ex) if ccw == (r is q.exterior) else (-ey, ex)
                        mx_, my_ = 0.5 * (ax_ + bx_) + nx_ * 0.005, 0.5 * (ay_ + by_) + ny_ * 0.005
                        if wb.contains(Point(mx_, my_)):
                            continue
                        F.quad([(ax_, ay_, z), (bx_, by_, z), (bx_, by_, z + SKIRT_H), (ax_, ay_, z + SKIRT_H)],
                               (nx_, ny_, 0))
            node = nm(tok, 'walls', MAT_WALL)
            geo.faces(node, MAT_TRIM, F.v, F.f)
            # a 12 mm top is all but invisible: the board is the one face
        wet_all = U([u['tile'] for u in meta_units if not u['tile'].is_empty])
        for d in doors:
            if d['kind'] != 'room' or d['gap_key'] in seen_sill:
                continue
            seen_sill.add(d['gap_key'])
            a, n, a0, a1, c0, c1, t0 = d['frame']
            sm = 0.5 * (a0 + a1)
            fin = []
            for tt in (c0 - 0.25, c1 + 0.25):
                fin.append(wet_all.contains(Point(a[0] * sm + n[0] * tt, a[1] * sm + n[1] * tt)))
            if fin[0] != fin[1]:
                geo.prism(nm(d['owner'], 'threshold', MAT_STONE), MAT_STONE, d['gap'], z, z + SILL_T, top=True, sides=True)
                d['sill'] = True

    # ---------------------------------------------------------- nav
    walk = []
    for u in meta_units:
        # the flat's own polygon: its rooms are in flats[].rooms, the walls
        # inside it are in solid
        walk.append({'poly': coords_m(u['poly'], tol=0.01), 'z': R3(z), 'kind': 'flat', 'owner': u['token']})
        for b in u['balc']:
            walk.append({'poly': coords_m(b, tol=0.01), 'z': R3(z + BALC_TOP), 'kind': 'loggia', 'owner': u['token']})
    for p in polys(corr, 0.05):
        walk.append({'poly': coords_m(p), 'z': R3(z), 'kind': 'corridor'})
    for p in polys(lv.loggias, 0.05):
        walk.append({'poly': coords_m(p), 'z': R3(z + BALC_TOP), 'kind': 'loggia'})
    for t, hp in lv.halls:
        for p in polys(hp.difference(hole_floor).difference(shaft_g), 0.05):
            walk.append({'poly': coords_m(p), 'z': R3(z), 'kind': 'hall', 'owner': t})
    for p in polys(lv.commercial, 0.05):
        walk.append({'poly': coords_m(p), 'z': R3(z), 'kind': 'commercial'})
    for p in polys(lv.terrace, 0.05):
        walk.append({'poly': coords_m(p), 'z': R3(z), 'kind': 'terrace'})
    for d in doors:
        walk.append({'poly': coords_m(d['gap']), 'z': R3(z), 'kind': 'door', 'owner': d['owner'], 'door': d['id']})
    ramps = []
    for c, st in here.items():
        zm = st['z0'] + st['rise'] / 2
        walk.append({'poly': coords_m(st['land']), 'z': R3(zm), 'kind': 'half_landing', 'core': c})
        k, sgn = st['k'], st['sgn']
        # first flight rises away from the floor end (towards -sgn)
        axis1 = (-sgn, 0) if k == 0 else (0, -sgn)
        axis2 = (sgn, 0) if k == 0 else (0, sgn)
        ramps.append({'core': c, 'flight': 1, 'poly': coords_m(st['f1']), 'z0': R3(st['z0']), 'z1': R3(zm),
                      'axis': list(axis1), 'from': lid, 'to': st['next'], 'risers': st['n']})
        ramps.append({'core': c, 'flight': 2, 'poly': coords_m(st['f2']), 'z0': R3(zm), 'z1': R3(st['z1']),
                      'axis': list(axis2), 'from': lid, 'to': st['next'], 'risers': st['n']})
    # solids: what stands between knee and chest: every wall (the street
    # file's EXT included - the body must not walk through it), linings,
    # duct fills, window sills, lift shafts, balcony rails
    rails = []
    for b in list(lv.balc.geoms if hasattr(lv.balc, 'geoms') else [lv.balc]) + polys(lv.loggias):
        if b.is_empty:
            continue
        free = b.exterior.difference(grow(U([W, lv.SP, gaps_all] + [wg['gap'] for wg in win_gaps]), 0.06))
        if not free.is_empty:
            rails.append(free.buffer(0.03, cap_style=2))
    sills = [wg['gap'] for wg in win_gaps if not wg['door']]
    SOLID = U([W, FILL, LIN, shaft_g] + sills + rails)
    # door throats are passable by definition: a simplified edge must not
    # creep across one
    SOLID = SOLID.simplify(0.01).difference(grow(gaps_all, 0.012))
    solid = cm(SOLID, tol=0.0)

    report.setdefault('levels', {})[lid] = {
        'units': len(lv.units), 'doors': len(doors), 'synth_doors': len(synth),
        'door_kinds': dict(sorted(defaultdict(int, {k: sum(1 for d in doors if d['kind'] == k)
                                                    for k in set(d['kind'] for d in doors)}).items())),
        'fills': len(fills), 'notes': notes,
    }

    # ---------------------------------------------------------- meta
    lm = {'id': lid, 'z': R3(z), 'h': R3(h), 'kind': lv.kind, 'clear': R3(lv.clear)}
    flats = []
    for u in meta_units:
        f = u['rec']
        fd = []
        for d in doors:
            if d['owner'] == u['token']:
                fd.append(door_meta(d))
        rec = {'n': u['n'], 'token': u['token'], 'block': f.get('block'), 'part': f.get('part'),
               'core': f.get('core'), 'poly': coords_m(u['poly']), 'label_at': f['label'].get('at') if f.get('label') else None,
               'area': {'inner': (f.get('table') or {}).get('inner') or (f.get('label') or {}).get('inner'),
                        'balcony': (f.get('table') or {}).get('balcony') or (f.get('label') or {}).get('balcony'),
                        'total': (f.get('table') or {}).get('total') or (f.get('label') or {}).get('total'),
                        'polygon': f.get('area_polygon')},
               'rooms': u['rooms_meta'], 'doors': fd,
               'loggias': [coords_m(b) for b in u['balc']]}
        if f.get('entrance_suggested') and not f.get('entrance'):
            rec['entrance_made'] = True
        flats.append(rec)
    if lid == 'L01':
        lm['offices'] = flats
    else:
        lm['flats'] = flats
    lm['corridor'] = cm(lv.corr)
    lm['doors'] = [door_meta(d) for d in doors if d['owner'] is None or not str(d['owner'])[:1] in 'uo']
    if lv.halls:
        lm['halls'] = [{'core': t, 'poly': coords_m(hp)} for t, hp in lv.halls]
    lm['nav'] = {'walk': [w for w in walk if w['poly']], 'solid': solid, 'ramps': ramps,
                 'lifts': [{'core': s['core'], 'shaft': s['k'], 'cab': coords_m(s['poly'].buffer(-0.08, join_style=2)),
                            'z': R3(z), 'door': [[R3(v) for v in p] for p in s['seg']] if s['seg'] else None}
                           for s in lift_stops]}
    ctx = {'lv': lv, 'W': W, 'here': here, 'doors': doors, 'lift_stops': lift_stops, 'shafts': shafts}
    return lm, ctx


_WCACHE = {}


def plan_W(plan, lid):
    if lid not in _WCACHE:
        _WCACHE[lid] = U([P(p) for p in plan.levels[lid]['walls']['poche']])
    return _WCACHE[lid]


def door_meta(d):
    return {'id': d['id'], 'node': d['node'], 'kind': d['kind'], 'owner': d['owner'],
            'hinge': [R3(d['hinge'][0]), R3(d['hinge'][1])],
            'w': R3(math.hypot(d['closed_end'][0] - d['hinge'][0], d['closed_end'][1] - d['hinge'][1])),
            'shut': d['shut'], 'open': d['open'],
            **({'made': True} if d.get('synth') else {}),
            **({'made_from': d['made_from']} if d.get('made_from') else {})}


def room_kinds_for(plan, pre, rec):
    """Per plan.json room: (kind, name, id) of the rooms.json room it
    overlaps most, and the rooms.json wet-room polygons. (None, []) when
    rooms.json has nothing for this flat."""
    rs = plan.rooms.get((pre, str(rec['number'])))
    if not rs:
        return None, []
    cand = []
    for r in rs:
        if r.get('kind') in ('balcony', 'loggia') or not r.get('polygon'):
            continue
        try:
            cand.append((r, P(r['polygon'])))
        except Exception:
            continue
    out = []
    for room in rec.get('rooms') or []:
        rp = P(room['polygon'])
        best = None
        for r, g in cand:
            a = rp.intersection(g).area
            if a > 0.05 * rp.area and (best is None or a > best[0]):
                best = (a, r)
        out.append((best[1].get('kind'), best[1].get('name'), best[1].get('id')) if best else (None, None, None))
    wet = [g for r, g in cand if any(w in (r.get('kind') or '').lower() for w in WET_WORDS)]
    return out, wet


def guess_wet(rp, u, doors, win_gaps):
    """No room types: a small room with no window, no balcony door and no
    entrance door is a bathroom/WC (tile). Marked 'guess' in the meta."""
    if rp.area > 7.0 or rp.area < 1.2:
        return False
    g = grow(rp, 0.35)
    for wg in win_gaps:
        if g.intersects(wg['gap']):
            return False
    for d in doors:
        if d['kind'] in ('entrance', 'balcony') and g.intersects(d['gap']):
            return False
    return True


# ------------------------------------------------------------------ lifts
def lift_shafts(plan, lid):
    """Shaft polygons for a level: drawn on it, else the residential ones."""
    src = plan.levels[lid].get('lifts') or []
    if len(src) < 4:
        src = plan.levels['L03']['lifts']
    out = []
    per = defaultdict(list)
    for s in src:
        per[s['core']].append(s)
    for c in sorted(per):
        for k, s in enumerate(sorted(per[c], key=lambda s: P(s['polygon']).centroid.x), 1):
            p = P(s['polygon'])
            # the drawn shaft polygon can carry a notch; use its box
            out.append({'core': c, 'k': k, 'poly': box(*p.bounds)})
    return out


def lift_door(W, sh, space):
    """The throat in front of a shaft: (segment on the shaft face, gap, made?).

    The throat is the part of a 0.16 m ring round the shaft that is not wall;
    the lintel above it spans from the shaft face to the lobby."""
    p = sh['poly']
    ring = grow(p, 0.16).difference(p)
    # an opening drops the hairline slivers where the drawn shaft box and
    # the wall poche miss by a few mm (C1 lift 1 on +31.200 read its whole
    # west face as the door): a throat is the full ring depth
    free = ring.difference(W).buffer(-0.03, join_style=2).buffer(0.03, join_style=2)
    throat = [q for q in polys(free.intersection(ring), 0.02)]
    x0, y0, x1, y1 = p.bounds
    best = None
    for q in throat:
        qx0, qy0, qx1, qy1 = q.bounds
        L = max(qx1 - qx0, qy1 - qy0)
        if L < 0.6 or min(qx1 - qx0, qy1 - qy0) < 0.1:
            continue
        # it must open onto a room / hall / corridor, not onto a flight
        mx, my = 0.5 * (qx0 + qx1), 0.5 * (qy0 + qy1)
        if space is not None and not space.is_empty and \
                not space.buffer(0.05).intersects(grow(q, 0.3).difference(p)):
            continue
        if best is None or L > best[0]:
            best = (L, q)
    if best is None:
        return None, None, False
    q = best[1]
    qx0, qy0, qx1, qy1 = q.bounds
    if qx1 - qx0 > qy1 - qy0:   # door in a face of constant y
        yf = y1 if qy0 >= y1 - 0.02 else y0
        seg = [(max(qx0, x0), yf), (min(qx1, x1), yf)]
        d = 0.35 if yf == y1 else -0.35
        reach = box(seg[0][0], min(yf, yf + d), seg[1][0], max(yf, yf + d))
    else:
        xf = x1 if qx0 >= x1 - 0.02 else x0
        seg = [(xf, max(qy0, y0)), (xf, min(qy1, y1))]
        d = 0.35 if xf == x1 else -0.35
        reach = box(min(xf, xf + d), seg[0][1], max(xf, xf + d), seg[1][1])
    # the jambs either side bound the wall depth: fill between them
    jam = grow(reach, 0.12).intersection(W)
    hull = jam.convex_hull.intersection(reach) if not jam.is_empty else q
    gap = U(polys(hull.difference(W).difference(p), 0.01))
    if gap.is_empty:
        gap = q
    return [list(seg[0]), list(seg[1])], gap, False


# ================================================================== cores
def build_flight2(T, B, st, band, s_start, s_end, z0, z1):
    """Treads + risers into T, sides + soffit into B (plan frame)."""
    k = st['k']
    n = st['n']
    t0, t1 = band
    run = s_end - s_start
    g = abs(run) / (n - 1)
    R = (z1 - z0) / n
    sgn = 1 if run > 0 else -1

    def P3(s, t, z):
        return (s, t, z) if k == 0 else (t, s, z)

    up = (sgn, 0, 0) if k == 0 else (0, sgn, 0)
    down = (-up[0], -up[1], 0)
    tl = (0, -1, 0) if k == 0 else (-1, 0, 0)
    th = (0, 1, 0) if k == 0 else (1, 0, 0)
    L = abs(run)
    slope = (z1 - z0) / L

    def soffit(u):
        return max(z0, z1 - WAIST - slope * (L - u))

    for i in range(n):
        s = s_start + sgn * i * g
        za, zb = z0 + i * R, z0 + (i + 1) * R
        T.quad([P3(s, t0, za), P3(s, t1, za), P3(s, t1, zb), P3(s, t0, zb)], down)
        if i < n - 1:
            s2 = s + sgn * g
            T.quad([P3(s, t0, zb), P3(s, t1, zb), P3(s2, t1, zb), P3(s2, t0, zb)], (0, 0, 1))
            u0, u1 = i * g, (i + 1) * g
            for t, hint in ((t0, tl), (t1, th)):
                B.quad([P3(s, t, soffit(u0)), P3(s2, t, soffit(u1)), P3(s2, t, zb), P3(s, t, zb)], hint)
    ub = max(0.0, L - (z1 - WAIST - z0) / slope)
    sb = s_start + sgn * ub
    B.quad([P3(sb, t0, z0), P3(sb, t1, z0), P3(s_end, t1, z1 - WAIST), P3(s_end, t0, z1 - WAIST)],
           (-up[0] * 0.3, -up[1] * 0.3, -1))


def rail_beam(F, k, t, s_start, s_end, z0, z1, h=RAIL_H, w=0.05):
    def P2(s, tt):
        return (s, tt) if k == 0 else (tt, s)
    pts = []
    for s, zz in ((s_start, z0 + h), (s_end, z1 + h)):
        for dt, dz in ((-w / 2, -w / 2), (w / 2, -w / 2), (w / 2, w / 2), (-w / 2, w / 2)):
            x, y = P2(s, t + dt)
            pts.append((x, y, zz + dz))
    o = len(F.v)
    F.v.extend(pts)
    cen = [sum(p[i] for p in pts) / 8 for i in range(3)]
    for q in [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (0, 3, 2, 1), (4, 5, 6, 7)]:
        qp = [pts[i] for i in q]
        c = [sum(p[i] for p in qp) / 4 for i in range(3)]
        order = oriented_quad(qp, [c[i] - cen[i] for i in range(3)])
        F.f.append([o + q[i] for i in order])
    for s, zz in ((s_start, z0), (s_end, z1)):
        x, y = P2(s, t)
        F.box(x - 0.02, y - 0.02, zz, x + 0.02, y + 0.02, zz + h - w / 2, skip=('-z',))


# ------------------------------------------------------------------ lift kit
# Everything a lift has that the plan does not draw: stainless landing frames
# and centre-opening leaves, a call station beside every door, a dot-matrix
# floor indicator over it, and a car with panelled walls, a mirror, a
# handrail, a lit ceiling and an operating panel. Existing materials only.
MAT_STEEL = 'chrome'
MAT_PANEL = 'frame_light'
MAT_LED = 'neon_orange'
MAT_BLACK = 'int_black'
MAT_MIRROR = 'int_mirror'
MAT_LIGHT = 'int_lamp_shade'

GLYPH = {  # 3 x 5 dot matrix, rows top to bottom
    '0': ('111', '101', '101', '101', '111'), '1': ('010', '110', '010', '010', '111'),
    '2': ('111', '001', '111', '100', '111'), '3': ('111', '001', '111', '001', '111'),
    '4': ('101', '101', '111', '001', '001'), '5': ('111', '100', '111', '001', '111'),
    '6': ('111', '100', '111', '101', '111'), '7': ('111', '001', '010', '010', '010'),
    '8': ('111', '101', '111', '101', '111'), '9': ('111', '101', '111', '001', '111'),
    'G': ('111', '100', '101', '101', '111'), 'O': ('111', '101', '101', '101', '111'),
    'P': ('111', '101', '111', '100', '100'), '-': ('000', '000', '111', '000', '000'),
    '^': ('010', '111', '101', '000', '000'), 'v': ('000', '000', '101', '111', '010'),
}


def lift_label(lid):
    """What the indicator shows, as the page's own lift panel names the stops:
    Ground, Offices, then the residential floors 1..9."""
    if lid == 'L00':
        return 'G'
    if lid == 'L01':
        return 'O'
    if lid == 'P-1':
        return '-1'
    return str(int(lid[1:]) - 1)


def _dots(F, text, c0, u, v, t0, t1, zc, px=0.011, pitch=0.014):
    """Dot-matrix text centred on plan point c0 + height zc; u runs to the
    READER's right, v out of the wall; dots stand from t0 to t1 along v."""
    w = len(text) * 3 * pitch + (len(text) - 1) * pitch
    x = -w / 2 + pitch / 2
    for ch in text:
        g = GLYPH.get(ch)
        if g:
            for r, row in enumerate(g):
                for k, bit in enumerate(row):
                    if bit == '1':
                        s_ = x + k * pitch
                        z_ = zc + (2 - r) * pitch
                        tc = 0.5 * (t0 + t1)
                        F.obox((c0[0] + u[0] * s_ + v[0] * tc, c0[1] + u[1] * s_ + v[1] * tc), u, v,
                               px / 2, (t1 - t0) / 2, z_ - px / 2, z_ + px / 2)
        x += 4 * pitch


def lift_landing(geo, base, m, a, no, Ls, T, zl, label, W, first=False, last=False):
    """One landing: m the door's middle on the shaft face, a along the door,
    no the unit normal into the lobby, Ls the clear width, T the wall."""
    def P(s_, t_):
        return (m[0] + a[0] * s_ + no[0] * t_, m[1] + a[1] * s_ + no[1] * t_)
    # the reader stands in the lobby looking at the door; plan y is flipped,
    # so their right is (-f.y, f.x) with f = -no
    f_ = (-no[0], -no[1])
    r_ = (-f_[1], f_[0])
    sr = 1.0 if (r_[0] * a[0] + r_[1] * a[1]) > 0 else -1.0
    ur = (a[0] * sr, a[1] * sr)
    H = DOOR_H
    # two leaves meeting in the middle, each a skin with a raised panel
    for nm_, s0, s1 in (('door', -Ls / 2 + 0.003, -0.002), ('door2', 0.002, Ls / 2 - 0.003)):
        D = Faces()
        D.obox(P((s0 + s1) / 2, 0.05), a, no, (s1 - s0) / 2, 0.015, zl, zl + H)
        D.obox(P((s0 + s1) / 2, 0.067), a, no, (s1 - s0) / 2 - 0.045, 0.002, zl + 0.10, zl + H - 0.10)
        geo.faces('%s_%s__%s' % (base, nm_, MAT_STEEL), MAT_STEEL, D.v, D.f)
    # the frame: linings through the wall, an architrave on the lobby face, a sill
    Fm = Faces()
    tl0, tl1 = 0.07, T
    for sg in (-1, 1):
        Fm.obox(P(sg * (Ls / 2 + 0.008), (tl0 + tl1) / 2), a, no, 0.008, (tl1 - tl0) / 2, zl, zl + H)
        Fm.obox(P(sg * (Ls / 2 + 0.05), T + 0.009), a, no, 0.05, 0.009, zl, zl + H + 0.10)
    Fm.obox(P(0, (tl0 + tl1) / 2), a, no, Ls / 2, (tl1 - tl0) / 2, zl + H - 0.016, zl + H)
    Fm.obox(P(0, T + 0.009), a, no, Ls / 2, 0.009, zl + H, zl + H + 0.10)
    Fm.obox(P(0, (0.03 + T) / 2), a, no, Ls / 2, (T - 0.03) / 2, zl - 0.02, zl + 0.004)
    geo.faces('%s_frame__%s' % (base, MAT_STEEL), MAT_STEEL, Fm.v, Fm.f)
    # the indicator over the door: a black glass strip and its dots
    zi = zl + H + 0.20
    Fb, Fl_ = Faces(), Faces()
    Fb.obox(P(0, T + 0.006), a, no, 0.15, 0.006, zi - 0.055, zi + 0.055)
    _dots(Fl_, label, P(0, 0), ur, no, T + 0.012, T + 0.0145, zi)
    # the call station, on the reader's right if there is wall there
    for side in (sr, -sr):
        sc = side * (Ls / 2 + 0.30)
        if W.contains(Point(*P(sc, T - 0.05))) and not W.contains(Point(*P(sc, T + 0.12))):
            Fs = Faces()
            Fs.obox(P(sc, T + 0.004), a, no, 0.042, 0.004, zl + 0.96, zl + 1.24)
            geo.faces('%s_call__%s' % (base, MAT_STEEL), MAT_STEEL, Fs.v, Fs.f)
            btns = ([] if last else [(zl + 1.15, '^')]) + ([] if first else [(zl + 1.05, 'v')])
            if len(btns) == 1:
                btns = [(zl + 1.10, btns[0][1])]
            for zb, arrow in btns:
                Fb.obox(P(sc, T + 0.0095), a, no, 0.019, 0.0015, zb - 0.019, zb + 0.019)
                _dots(Fl_, arrow, P(sc, 0), ur, no, T + 0.011, T + 0.0125, zb, px=0.006, pitch=0.008)
            break
    geo.faces('%s_ind__%s' % (base, MAT_BLACK), MAT_BLACK, Fb.v, Fb.f)
    if Fl_.f:
        geo.faces('%s_led__%s' % (base, MAT_LED), MAT_LED, Fl_.v, Fl_.f)


def lift_car(box, front, seg):
    """The car in the plan frame, parked with its floor at z = 0:
    {material: Faces}. `front` is the side the landing doors are on."""
    bx0, by0, bx1, by1 = box
    cxm, cym = 0.5 * (bx0 + bx1), 0.5 * (by0 + by1)
    Hc = 2.25
    t = 0.04
    out = {m: Faces() for m in (MAT_PANEL, MAT_STEEL, MAT_TREAD, MAT_TRIM, MAT_MIRROR, MAT_LIGHT, MAT_BLACK, MAT_LED)}
    Wp, St = out[MAT_PANEL], out[MAT_STEEL]
    out[MAT_TREAD].box(bx0, by0, -0.08, bx1, by1, 0.0)
    out[MAT_TRIM].box(bx0, by0, Hc, bx1, by1, Hc + 0.05)
    # the lit ceiling: a luminous panel in a steel surround
    out[MAT_LIGHT].box(bx0 + 0.16, by0 + 0.16, Hc - 0.012, bx1 - 0.16, by1 - 0.16, Hc - 0.004)
    for (x0, y0, x1, y1) in ((bx0 + 0.13, by0 + 0.13, bx1 - 0.13, by0 + 0.16), (bx0 + 0.13, by1 - 0.16, bx1 - 0.13, by1 - 0.13),
                             (bx0 + 0.13, by0 + 0.16, bx0 + 0.16, by1 - 0.16), (bx1 - 0.16, by0 + 0.16, bx1 - 0.13, by1 - 0.16)):
        St.box(x0, y0, Hc - 0.016, x1, y1, Hc)
    # wall frames: mid of the inner face, tangent, inward normal, half length
    WF = {'-x': ((bx0 + t, cym), (0.0, 1.0), (1.0, 0.0), (by1 - by0) / 2 - t),
          '+x': ((bx1 - t, cym), (0.0, 1.0), (-1.0, 0.0), (by1 - by0) / 2 - t),
          '-y': ((cxm, by0 + t), (1.0, 0.0), (0.0, 1.0), (bx1 - bx0) / 2 - t),
          '+y': ((cxm, by1 - t), (1.0, 0.0), (0.0, -1.0), (bx1 - bx0) / 2 - t)}
    sides = {'-x': (bx0, by0, bx0 + t, by1), '+x': (bx1 - t, by0, bx1, by1),
             '-y': (bx0, by0, bx1, by0 + t), '+y': (bx0, by1 - t, bx1, by1)}
    opp = {'-x': '+x', '+x': '-x', '-y': '+y', '+y': '-y'}
    back = opp.get(front)

    def on(key, s_, d_):
        (px_, py_), u, v, _h = WF[key]
        return (px_ + u[0] * s_ + v[0] * d_, py_ + u[1] * s_ + v[1] * d_)

    for key, (x0, y0, x1, y1) in sides.items():
        (pm, u, v, hl) = WF[key]
        if key != front:
            Wp.box(x0, y0, 0.0, x1, y1, Hc)
            # steel skirting, a joint down the middle of each panel run, a handrail
            St.obox(on(key, 0, 0.006), u, v, hl, 0.006, 0.0, 0.10)
            St.obox(on(key, 0, 0.002), u, v, 0.004, 0.002, 0.10, Hc)
            St.obox(on(key, 0, 0.055), u, v, hl - 0.10, 0.016, 0.885, 0.915)
            for sg in (-1, 1):
                St.obox(on(key, sg * (hl - 0.22), 0.022), u, v, 0.012, 0.022, 0.892, 0.908)
            if key == back:
                out[MAT_MIRROR].obox(on(key, 0, 0.004), u, v, hl - 0.08, 0.004, 1.00, Hc - 0.14)
                for zz in (0.992, Hc - 0.14):
                    St.obox(on(key, 0, 0.005), u, v, hl - 0.072, 0.005, zz, zz + 0.008)
        elif seg:
            (ax_, ay_), (bx_, by_) = seg
            if key in ('-x', '+x'):
                o0, o1 = sorted((ay_, by_))
                Wp.box(x0, y0, 0.0, x1, max(y0, o0 + 0.05), Hc)
                Wp.box(x0, min(y1, o1 - 0.05), 0.0, x1, y1, Hc)
                Wp.box(x0, o0 + 0.05, DOOR_H, x1, o1 - 0.05, Hc)
                mid_s, c_ = 0.5 * (o0 + o1) - cym, cym
            else:
                o0, o1 = sorted((ax_, bx_))
                Wp.box(x0, y0, 0.0, max(x0, o0 + 0.05), y1, Hc)
                Wp.box(min(x1, o1 - 0.05), y0, 0.0, x1, y1, Hc)
                Wp.box(o0 + 0.05, y0, DOOR_H, o1 - 0.05, y1, Hc)
                mid_s = 0.5 * (o0 + o1) - cxm
            hw = (o1 - o0) / 2 - 0.05
            # steel portal round the car's own opening, and its position strip
            for sg in (-1, 1):
                St.obox(on(key, mid_s + sg * (hw + 0.012), 0.004), u, v, 0.012, 0.004, 0.0, DOOR_H + 0.024)
            St.obox(on(key, mid_s, 0.004), u, v, hw, 0.004, DOOR_H, DOOR_H + 0.024)
            out[MAT_BLACK].obox(on(key, mid_s, 0.005), u, v, 0.13, 0.005, DOOR_H + 0.045, DOOR_H + 0.115)
            # reader inside looks at the front wall: right = (-f.y, f.x), f = -v
            f_ = (-v[0], -v[1]); r_ = (-f_[1], f_[0])
            sr = 1.0 if (r_[0] * u[0] + r_[1] * u[1]) > 0 else -1.0
            ur = (u[0] * sr, u[1] * sr)
            _dots(out[MAT_LED], '^v', on(key, mid_s, 0), ur, v, 0.010, 0.012, DOOR_H + 0.08, px=0.007, pitch=0.009)
            # the operating panel on the return beside the opening (the wider one)
            room_lo = (mid_s - hw) - (-hl); room_hi = hl - (mid_s + hw)
            sgp = -1 if room_lo >= room_hi else 1
            wret = max(room_lo, room_hi)
            if wret >= 0.16:
                sc = mid_s + sgp * (hw + 0.024 + (wret - 0.024) / 2)
                hwp = min(0.075, (wret - 0.05) / 2)
                St.obox(on(key, sc, 0.006), u, v, hwp, 0.006, 0.80, 1.62)
                out[MAT_BLACK].obox(on(key, sc, 0.0135), u, v, hwp - 0.012, 0.0015, 1.50, 1.59)
                _dots(out[MAT_LED], 'G', on(key, sc, 0), ur, v, 0.015, 0.0165, 1.545, px=0.008, pitch=0.010)
                # eleven stops in two columns, and door open / close under them
                k = 0
                for row in range(7):
                    for col in (-1, 1):
                        zb = 1.43 - row * 0.085
                        cs = sc + col * hwp * 0.45
                        out[MAT_BLACK].obox(on(key, cs, 0.0135), u, v, 0.015, 0.0015, zb - 0.015, zb + 0.015)
                        if k < 11:
                            out[MAT_LED].obox(on(key, cs, 0.0155), u, v, 0.004, 0.0005, zb - 0.004, zb + 0.004)
                        k += 1
    return out



def to_local(F, c):
    """Plan-frame faces -> Blender-local verts about plan point c (z kept)."""
    v = [(x - c[0], -(y - c[1]), z) for x, y, z in F.v]
    f = [list(reversed(q)) for q in F.f]
    return v, f


def build_cores(plan, lay, ctxs, geo, report):
    seq = LEVELS_BUILT
    cores_meta = {c: {'id': c, 'storeys': []} for c in CORES + ('podium',)}
    for lid in seq:
        ctx = ctxs[lid]
        here = ctx['here']
        for c, st in here.items():
            T, B, Ld, Rl = Faces(), Faces(), Faces(), Faces()
            k, sgn = st['k'], st['sgn']
            near = st['hi'] if sgn > 0 else st['lo']
            far = st['far']
            zm = st['z0'] + st['rise'] / 2
            build_flight2(T, B, st, st['first'], near, far, st['z0'], zm)
            build_flight2(T, B, st, st['second'], far, near, zm, st['z1'])
            # half landing slab
            lb = st['land'].bounds
            Ld.box(lb[0], lb[1], zm - WAIST, lb[2], lb[3], zm)
            # rails on the well edges
            f1, f2 = st['first'], st['second']
            if f1[1] <= f2[0] + 1e-6:
                e1, e2 = f1[1] - 0.03, f2[0] + 0.03
            else:
                e1, e2 = f1[0] + 0.03, f2[1] - 0.03
            rail_beam(Rl, k, e1, near, far, st['z0'], zm)
            rail_beam(Rl, k, e2, far, near, zm, st['z1'])
            base = 'in_%s_stair_%s_' % (c, lid)
            geo.faces(base + 'flights__' + MAT_TREAD, MAT_TREAD, T.v, T.f)
            geo.faces(base + 'body__' + MAT_STAIR, MAT_STAIR, B.v, B.f)
            geo.faces(base + 'landing__' + MAT_TREAD, MAT_TREAD, Ld.v, Ld.f)
            geo.faces(base + 'rail__' + MAT_HANDLE, MAT_HANDLE, Rl.v, Rl.f)
            R = st['rise'] / 2 / st['n']
            cores_meta[c]['storeys'].append({
                'from': lid, 'to': st['next'], 'z0': R3(st['z0']), 'z1': R3(st['z1']),
                'risers_per_flight': st['n'], 'riser': R3(R), 'going': R3(st['run'] / (st['n'] - 1)),
                'half_landing': {'poly': coords_m(st['land']), 'z': R3(zm)},
                'flights': [{'poly': coords_m(st['f1']), 'z0': R3(st['z0']), 'z1': R3(zm)},
                            {'poly': coords_m(st['f2']), 'z0': R3(zm), 'z1': R3(st['z1'])}],
                'layout_from_sheet': st['src'], 'up_direction_inferred': st['inferred']})
            if 'floor_end' not in cores_meta[c]:
                cores_meta[c]['floor_end'] = ('+' if sgn > 0 else '-') + st['axis']

    # ---------------------------------------------------- lifts
    lifts = []
    shafts = lift_shafts(plan, 'L03')
    for sh in shafts:
        c, kk, p = sh['core'], sh['k'], sh['poly']
        stops = []
        for lid in seq:
            for s in ctxs[lid]['lift_stops']:
                if s['core'] == c and s['k'] == kk:
                    stops.append({'level': lid, 'z': R3(plan.z(lid)), 'door': s['seg']})
                    if s['seg']:
                        (ax_, ay_), (bx_, by_) = s['seg']
                        a = unit((bx_ - ax_, by_ - ay_))
                        n = (-a[1], a[0])
                        # the lobby side of the face
                        mx, my = 0.5 * (ax_ + bx_), 0.5 * (ay_ + by_)
                        out = 1 if not p.contains(Point(mx + n[0] * 0.1, my + n[1] * 0.1)) else -1
                        Ls = math.hypot(bx_ - ax_, by_ - ay_)
                        zl = plan.z(lid)
                        # the wall the door stands in: from the shaft face out
                        # to the lobby (the throat drawn on this sheet)
                        T = 0.16
                        if s.get('gap') is not None and not s['gap'].is_empty:
                            T = max([((x - mx) * n[0] + (y - my) * n[1]) * out
                                     for g_ in polys(s['gap'], 0.0) for (x, y) in g_.exterior.coords] + [0.12])
                        lift_landing(geo, 'in_%s_lift%d_%s' % (c, kk, lid), (mx, my), a, (n[0] * out, n[1] * out),
                                     Ls, T, zl, lift_label(lid), ctxs[lid]['W'],
                                     first=(lid == seq[0]), last=(lid == 'L10'))
        # the car, parked at L00, origin at its floor centre
        cab = p.buffer(-0.08, join_style=2)
        bx0, by0, bx1, by1 = cab.bounds
        cx, cy = 0.5 * (bx0 + bx1), 0.5 * (by0 + by1)
        top_seg = next((s['door'] for s in stops if s['door']), None)
        front = None
        if top_seg:
            (ax_, ay_), (bx_, by_) = top_seg
            if abs(ax_ - bx_) < 1e-3:
                front = '+x' if ax_ > cx else '-x'
            else:
                front = '+y' if ay_ > cy else '-y'
        mid = 'car_%s_%d' % (c, kk)
        for m_, F_ in lift_car((bx0, by0, bx1, by1), front, top_seg).items():
            if F_.f:
                v, f = to_local(F_, (cx, cy))
                geo.shared_faces(mid, m_, v, f)
        geo.instance('in_%s_lift%d_car__%s' % (c, kk, MAT_METAL), mid, (cx, cy, 0.0), 0.0)
        lifts.append({'core': c, 'shaft': kk, 'shaft_poly': coords_m(p), 'cab': coords_m(cab),
                      'car_node': 'in_%s_lift%d_car__%s' % (c, kk, MAT_METAL), 'car_at': 'L00',
                      'stops': stops})

    # ---------------------------------------------------- stair heads
    R = plan.levels['ROOF']
    ctx10 = ctxs['L10']
    W10 = ctx10['W']
    for shd in R.get('stair_heads', []):
        c = shd['core']
        hp = P(shd['polygon'])
        z0, ztop = R['z'], shd.get('z_top', 40.2)
        zc = ztop - SLAB
        outside = box(-30, -30, 120, 80).difference(hp)
        ext = W10.intersection(grow(outside, EXT_D))
        inner = W10.intersection(hp).difference(grow(outside, EXT_D))
        sp = hp.difference(W10)
        lin = grow(ext, LIN_OUT).intersection(grow(sp, LIN_IN)).difference(inner)
        base = 'in_%s_head_' % c
        geo.prism(base + 'walls__' + MAT_WALL, MAT_WALL, clean(U([inner, lin])), z0, zc, top=False)
        st = ctx10['here'].get(c)
        zone = st['zone'] if st else Polygon()
        shaft_g = U([s['poly'] for s in shafts if s['core'] == c])
        fl = sp.difference(zone).difference(shaft_g)
        geo.prism(base + 'floor__' + MAT_STONE, MAT_STONE, fl, z0 - SLAB, z0, top=True, sides=True)
        geo.prism(base + 'ceiling__' + MAT_CEIL, MAT_CEIL, sp, zc, zc, top=False, bottom=True, sides=False)
        cores_meta[c]['head'] = {'poly': coords_m(hp), 'z': R3(z0), 'z_top': R3(ztop),
                                 'walk': cm(fl.difference(U([inner, lin])))}
    return cores_meta, lifts


# ================================================================== main
def portals_from(ctx00):
    """Street doors of the entrance halls (and the podium stair): one per
    hall, spanning the throat its leaf (or pair of leaves) closes."""
    lv = ctx00['lv']
    out = {}
    for d in ctx00['doors']:
        if d['kind'] == 'street' and d['owner']:
            a, n, a0, a1, c0, c1, t0 = d['frame']
            sm = 0.5 * (a0 + a1)
            # outward = towards the side that is outside
            p_hi = (a[0] * sm + n[0] * (c1 + 0.3), a[1] * sm + n[1] * (c1 + 0.3))
            sgn = 1 if lv.space_at(p_hi)[0] == 'out' else -1
            tt = c1 if sgn > 0 else c0
            A = (a[0] * a0 + n[0] * tt, a[1] * a0 + n[1] * tt)
            Bp = (a[0] * a1 + n[0] * tt, a[1] * a1 + n[1] * tt)
            # the facade line: snap to the +0.000 sheet's run when the throat
            # reading lands a few cm off it (jamb poche drawn proud)
            for f in lv.L.get('facade', []):
                fa, fb = f['a'], f['b']
                if abs(fa[0] - fb[0]) < 1e-3 and abs(n[0]) > 0.9 and abs(fa[0] - A[0]) < 0.1 and \
                        min(fa[1], fb[1]) - 0.05 <= 0.5 * (A[1] + Bp[1]) <= max(fa[1], fb[1]) + 0.05:
                    A, Bp = (fa[0], A[1]), (fa[0], Bp[1])
                    break
                if abs(fa[1] - fb[1]) < 1e-3 and abs(n[1]) > 0.9 and abs(fa[1] - A[1]) < 0.1 and \
                        min(fa[0], fb[0]) - 0.05 <= 0.5 * (A[0] + Bp[0]) <= max(fa[0], fb[0]) + 0.05:
                    A, Bp = (A[0], fa[1]), (Bp[0], fa[1])
                    break
            if d['owner'] in out:
                p = out[d['owner']]
                p['doors'].append(d['id'])
                p['nodes'].append(d['node'])
                # a pair of leaves: the portal spans both throats
                k = 0 if abs(a[0]) > abs(a[1]) else 1
                pts = sorted([p['a'], p['b'], [R3(A[0]), R3(A[1])], [R3(Bp[0]), R3(Bp[1])]], key=lambda q: q[k])
                lo, hi = pts[0], pts[-1]
                if (p['a'][k] > p['b'][k]):
                    lo, hi = hi, lo
                p['a'], p['b'] = lo, hi
                continue
            out[d['owner']] = {
                'core': d['owner'], 'a': [R3(A[0]), R3(A[1])], 'b': [R3(Bp[0]), R3(Bp[1])],
                'normal': [R3(n[0] * sgn), R3(n[1] * sgn)], 'door': d['id'], 'node': d['node'],
                'doors': [d['id']], 'nodes': [d['node']],
                'from': ('MADE: ' + d['made_from']) if d.get('synth') else 'door leaf drawn on the +0.000 sheet'}
            if d.get('synth'):
                out[d['owner']]['made'] = True
    return [out[k] for k in sorted(out, key=lambda k: ('C1', 'C2', 'C3', 'podium').index(k)
                                    if k in ('C1', 'C2', 'C3', 'podium') else 9)]


FURN_DIR = os.path.join(REPO, 'web', 'interior', 'furn')


def _glb_json(path):
    import struct
    with open(path, 'rb') as fh:
        b = fh.read()
    n = struct.unpack('<I', b[12:16])[0]
    return json.loads(b[20:20 + n])


def nav_furn(lid):
    """The furniture the walker collides with on one level, from
    web/interior/furn/index.json (blender/build_furnish.py) and the
    heights of the pieces in web/interior/furn/<LEVEL>.glb: per piece its
    footprint as the index box (c centre, s [width across heading, depth
    along it], hd heading, plan degrees) and z [bottom, top] above the
    level's floor; node = the piece's node in furn/<LEVEL>.glb."""
    idx = os.path.join(FURN_DIR, 'index.json')
    glb = os.path.join(FURN_DIR, lid + '.glb')
    if not (os.path.exists(idx) and os.path.exists(glb)):
        return None
    try:
        I = json.load(open(idx))
        G = _glb_json(glb)
    except Exception as e:
        print('[lib_plan] furniture unreadable for %s: %s' % (lid, e), file=sys.stderr)
        return None
    acc, meshes = G['accessors'], G['meshes']
    hz = {}
    for nd in G['nodes']:
        if 'mesh' not in nd:
            continue
        ys = [(acc[p['attributes']['POSITION']]['min'][1], acc[p['attributes']['POSITION']]['max'][1])
              for p in meshes[nd['mesh']]['primitives'] if 'POSITION' in p['attributes']]
        sc = (nd.get('scale') or [1, 1, 1])[1]
        if ys:
            hz[nd['name']] = (min(a for a, _ in ys) * sc, max(b for _, b in ys) * sc)
    out = []
    for n, rec in sorted(((I.get('levels') or {}).get(lid) or {}).get('units', {}).items()):
        for p in rec.get('pieces', []):
            b = p.get('box') or {}
            if p['node'] not in hz or 'centre' not in b:
                continue
            c, (w, d), hd = b['centre'], b['size'], b.get('heading', 0.0)
            z0, z1 = hz[p['node']]
            out.append({'node': p['node'], 'c': [R3(c[0]), R3(c[1])], 's': [R3(w), R3(d)], 'hd': round(hd, 1),
                        'z': [R3(max(0.0, z0)), R3(z1)]})
    return out


def write_split(meta, folder):
    """plan_meta.json cut per level, for a page that loads one storey at a
    time: <folder>/index.json (everything but the levels' contents, plus
    levels[] {id, z, h, kind, clear, built, file, bytes}) and
    <folder>/<LEVEL>.json (that level's record, exactly as in the
    monolithic file). Written ALONGSIDE plan_meta.json (CONTRACT.md)."""
    os.makedirs(folder, exist_ok=True)
    idx = {k: v for k, v in meta.items() if k != 'levels'}
    idx['about'] = meta['about'] + ' Split per level: levels[].file is that level\'s record of plan_meta.json.'
    idx['levels'] = []
    for l in meta['levels']:
        rec = {k: l[k] for k in ('id', 'z', 'h', 'kind', 'clear', 'built') if k in l}
        if 'nav' in l:
            fn = '%s.json' % l['id']
            txt = json.dumps(l, separators=(',', ':'))
            tmp = os.path.join(folder, fn + '.tmp')
            open(tmp, 'w').write(txt)
            os.replace(tmp, os.path.join(folder, fn))
            rec.update(file=fn, bytes=len(txt))
        idx['levels'].append(rec)
    tmp = os.path.join(folder, 'index.json.tmp')
    open(tmp, 'w').write(json.dumps(idx, separators=(',', ':')))
    os.replace(tmp, os.path.join(folder, 'index.json'))


def run(levels_wanted=None, geo_out=None, meta_out=None):
    plan = Plan()
    lay = stair_layout(plan)
    report = {}
    ctxs, metas, geos = {}, {}, {}
    for lid in LEVELS_BUILT:
        g = Geo()
        lm, ctx = build_level(plan, lid, g, lay, report)
        ctxs[lid], metas[lid], geos[lid] = ctx, lm, g
    gc = Geo()
    cores_meta, lifts = build_cores(plan, lay, ctxs, gc, report)
    geos['cores'] = gc
    portals = portals_from(ctxs['L00'])
    # cores meta: shafts + hall
    for c, cm_ in cores_meta.items():
        cm_['block'] = 'A' if c == 'C1' else ('B' if c in ('C2', 'C3') else None)
        cm_['shafts'] = [{'k': l['shaft'], 'poly': l['shaft_poly']} for l in lifts if l['core'] == c]
        for t, hp in ctxs['L00']['lv'].halls:
            if t == c:
                cm_['hall'] = coords_m(hp)
    for lid, lm in metas.items():
        fu = nav_furn(lid)
        if fu is not None:
            lm['nav']['furn'] = fu
    levels = []
    for l in plan.raw['levels']:
        lid = l['level']
        if lid in metas:
            levels.append(metas[lid])
        else:
            levels.append({'id': lid, 'z': R3(l['z']), 'h': R3(l['floor_to_floor']) if l.get('floor_to_floor') else None,
                           'kind': l['kind'], 'built': False})
    meta = {
        'about': 'Interior of the building from the architect\'s plan (blender/lib_plan.py). '
                 'PLAN metres: x along axes a->J, y along axes 1->10 (+y = street side), z = level. '
                 'Browser world = scene_meta.frame applied to these. Angles in degrees in the plan '
                 'frame (from +x toward +y); the plan frame is a mirror of the browser frame.',
        'source': 'blender/plans/plan.json' + (' + rooms.json' if plan.rooms else ''),
        'conventions': {'slab': SLAB, 'door_h': DOOR_H, 'win_sill': WIN_SILL, 'win_head': WIN_HEAD,
                        'balcony_door_h': BDOOR_H, 'balcony_floor_top': BALC_TOP,
                        'nav_band': [0.25, 1.40], 'ext_depth': EXT_D},
        'levels': levels,
        'cores': list(cores_meta.values()),
        'lifts': lifts,
        'portals': portals,
    }
    report['portals'] = portals
    if meta_out:
        txt = json.dumps(meta, separators=(',', ':'))
        open(meta_out, 'w').write(txt)
        write_split(meta, os.path.join(os.path.dirname(os.path.abspath(meta_out)), 'plan_meta'))
    if geo_out:
        want = levels_wanted or (LEVELS_BUILT + ['cores'])
        out = {k: geos[k].dump() for k in want if k in geos}
        json.dump(out, open(geo_out, 'w'), separators=(',', ':'))
    return meta, report, ctxs, geos


if __name__ == '__main__':
    a = sys.argv[1:]
    geo_out = a[a.index('--geo') + 1] if '--geo' in a else None
    meta_out = a[a.index('--meta') + 1] if '--meta' in a else None
    rep_out = a[a.index('--report') + 1] if '--report' in a else None
    lv = a[a.index('--levels') + 1].split(',') if '--levels' in a else None
    meta, report, _, _ = run(lv, geo_out, meta_out)
    if rep_out:
        json.dump(report, open(rep_out, 'w'), indent=1, default=str)
    for lid, r in report.get('levels', {}).items():
        print('[lib_plan] %-4s units %2d doors %3d (made %d) fills %d %s' %
              (lid, r['units'], r['doors'], r['synth_doors'], r['fills'], r['door_kinds']))
        for n in r['notes']:
            print('            ', n)
