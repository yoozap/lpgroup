# -*- coding: utf-8 -*-
"""Dress the flats: the pieces the architect did NOT draw (build 6).

Pure python + numpy (Blender's python and the system one alike), called by
lib_furnish.plan_levels() once a unit's drawn pieces are placed. Every piece
it adds carries `drawn: False`; it is chosen BY RULE from the room data
(blender/plans/rooms.json: rooms with kind, free-floor polygon, windows,
doors) and the door leaves web/plan_meta/<LEVEL>.json gives (hinge, width,
shut/open angles: the swing):

  living room  rug under the sofa group, a floor lamp by a sofa arm, a big
               floor plant in a free corner by the window, a snake plant, a
               trailing pothos on a wall shelf, a picture over the sofa, a
               sideboard and an armchair where the room has the floor, a
               pendant and a table plant / fruit bowl on the dining table,
               herbs on the worktop, a fridge tower at the end of a run
  bedroom      rug under the bed, a wardrobe on a free wall, a plant, a
               picture over the bed
  bathroom     a mat in front of the bath / shower, a towel rail, a roll
               holder by the wc, a cabinet over it, a washing machine (one a
               flat), a laundry basket, a small plant
  loggia       a planter along the balustrade, a pair of pots or a tree
  hall, office a plant (and a picture, a second plant in an office)
  every room   curtains at its windows (not the bathrooms, kitchens' worktop
               windows, or halls)

The rules a piece must pass, all of them, before it stands:
  - inside the room's free floor (rooms.json polygon_net), so never through
    a wall or a column;
  - clear of every other piece (2-D footprint AND height band overlap: a
    picture may hang over a sofa, a wardrobe may not stand in front of a
    nightstand), with a rug the only thing that may go under furniture;
  - never in a door's swing (the leaf's quarter circle) or its throat (the
    opening and 0.9 m either side of it), never across a window (the band
    over the sill in front of it; for a balcony door the whole height),
    unless it is a curtain;
  - if it is solid to a walking body (walk.js: top over 0.4 m, bottom under
    1.4 m) it must not cut the room's floor apart: every door the room had
    a way to before stays reachable, and no more than 0.15 m2 of floor
    beyond the piece's own footprint is lost (a 5 cm grid, the body's
    0.26 m radius).

Seeds: from the flat number (and the piece), so a stack of identical flats
differs a little from storey to storey and a rebuild is the same. Every seed
is a small bucket, so the level still shares one mesh per (kind, size
class, seed).

Index records: a solid piece carries `box` (its solid footprint, which
walk.js furnitureSolids and lib_plan.nav_furn collide with); a piece that is
not solid carries only `foot`. `z` is the node's height over the floor for a
piece standing on a table or a worktop (the reveal grows it from there).
"""
import math
import zlib

import numpy as np

import lib_furnish as LF

import os
SKIP_KINDS = set(filter(None, os.environ.get('DRESS_SKIP', '').split(',')))   # debugging: leave kinds out

CELL = 0.05
R_BODY = 0.30          # walk.js WALK.R (0.24) and margin: a passage stays 0.6 m wide
LOSS_MAX = 0.15        # m2 of floor a solid piece may cut off beyond itself
SOLID_Z = (0.4, 1.4)   # walk.js: solid if top > 0.4 and bottom < 1.4

LIVING = ('living_kitchen', 'living', 'studio')
BATH = ('bathroom', 'wc')

# the material the node is named after (CONTRACT: ..._furn_<kind><k>__<material>)
MAIN_MAT = {
    'rug': 'int_rug', 'rug_bedroom': 'int_rug', 'floor_lamp': 'int_lamp_shade', 'armchair': 'int_fabric_teal',
    'sideboard': 'int_wood_walnut', 'bookshelf': 'int_wood_oak', 'wall_art': 'int_wood_oak',
    'curtains': 'int_curtain', 'pendant': 'int_brass', 'wardrobe': 'int_white_gloss', 'dresser': 'int_wood_walnut',
    'fridge_tower': 'int_white_gloss', 'oven_tower': 'int_white_gloss',
    'towel_rail': 'chrome', 'washing_machine': 'int_white_gloss', 'wc_set': 'chrome', 'bath_mat': 'int_rug',
    'wall_cabinet': 'int_white_gloss', 'laundry_basket': 'int_fabric_white', 'bath_plant': 'foliage',
    'planter_balcony': 'int_pot', 'plant_loggia_pair': 'int_pot',
    'decor_vase': 'int_ceramic', 'decor_books': 'int_fabric_orange', 'decor_bowl': 'int_wood_walnut',
    'decor_candles': 'int_brass', 'decor_table_plant': 'foliage', 'plant_herbs': 'foliage',
    'plant_succulents': 'foliage', 'plant_pothos': 'foliage',
}
MAIN_MAT.update({
    'loveseat': 'int_fabric_white', 'pouf': 'int_fabric_white', 'table_dining': 'int_wood_walnut',
    'chair': 'int_fabric_sofa', 'tall_walnut': 'int_wood_walnut', 'kitchen_island': 'int_mint',
    'hall_wardrobe': 'int_mint', 'ac_unit': 'int_black', 'vanity': 'int_wood_walnut',
})
for _k in ('plant_monstera', 'plant_strelitzia', 'plant_fiddle', 'plant_rubber', 'plant_snake', 'plant_palm', 'plant_olive'):
    MAIN_MAT[_k] = 'foliage'

BIG_PLANTS = ('plant_monstera', 'plant_fiddle', 'plant_palm', 'plant_olive', 'plant_rubber')


# ------------------------------------------------------------ small geometry
def fwd(h):
    return (math.cos(math.radians(h)), math.sin(math.radians(h)))


def heading(v):
    return math.degrees(math.atan2(v[1], v[0])) % 360.0


def loc2plan(c, rot, x, y):
    f = fwd(rot)
    g = fwd(rot - 90.0)
    return (c[0] + f[0] * x + g[0] * y, c[1] + f[1] * x + g[1] * y)


def rect(c, w, d, h):
    """Corners of a box w across, d along heading h, centred at c (plan)."""
    return LF.footprint(c, [w, d], h)


def sat(A, B, eps=0.004):
    """Two convex polygons overlap by more than eps on every axis."""
    for P in (A, B):
        n = len(P)
        for i in range(n):
            x0, y0 = P[i]
            x1, y1 = P[(i + 1) % n]
            ax, ay = y0 - y1, x1 - x0
            L = math.hypot(ax, ay)
            if L < 1e-9:
                continue
            ax /= L
            ay /= L
            pa = [x * ax + y * ay for x, y in A]
            pb = [x * ax + y * ay for x, y in B]
            if min(max(pa), max(pb)) - max(min(pa), min(pb)) <= eps:
                return False
    return True


def pip(px, py, rings):
    """Vectorised even-odd point in polygon (with holes)."""
    px = np.asarray(px, float)
    py = np.asarray(py, float)
    c = np.zeros(px.shape, bool)
    for ring in rings:
        R = np.asarray(ring, float)
        x0, y0 = R[:, 0], R[:, 1]
        x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
        X = px[..., None]
        Y = py[..., None]
        with np.errstate(divide='ignore', invalid='ignore'):
            cross = ((y0 > Y) != (y1 > Y)) & (X < x0 + (Y - y0) * (x1 - x0) / (y1 - y0))
        c ^= (np.count_nonzero(cross, axis=-1) % 2).astype(bool)
    return c


def seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy or 1e-12
    t = np.clip(((px - ax) * vx + (py - ay) * vy) / L2, 0.0, 1.0)
    return np.hypot(px - (ax + vx * t), py - (ay + vy * t))


def poly_area(r):
    return 0.5 * sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))


def seed_of(n, *salt):
    return zlib.crc32(('%s|' % n + '|'.join(str(s) for s in salt)).encode()) & 0xffffffff


# ------------------------------------------------------------ the room
class Ob:
    __slots__ = ('poly', 'z0', 'z1', 'tag', 'solid', 'piece')

    def __init__(self, poly, z0, z1, tag, solid=False, piece=None):
        self.poly, self.z0, self.z1, self.tag, self.solid, self.piece = poly, z0, z1, tag, solid, piece


class Room:
    def __init__(self, r, rings, loggia=False, solids=()):
        self.r = r
        self.id = r['id']
        self.kind = r['kind']
        self.rings = rings
        self.loggia = loggia
        self.area = abs(poly_area(rings[0])) - sum(abs(poly_area(h)) for h in rings[1:])
        # walls: (a, b, u, n inward, length, is_hole)
        self.walls = []
        for ri, ring in enumerate(rings):
            m = len(ring)
            for i in range(m):
                a, b = tuple(ring[i]), tuple(ring[(i + 1) % m])
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                if L < 0.08:
                    continue
                u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
                n = (-u[1], u[0])
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                if not pip([mid[0] + n[0] * 0.03], [mid[1] + n[1] * 0.03], rings)[0]:
                    n = (-n[0], -n[1])
                self.walls.append((a, b, u, n, L, ri > 0))
        xs = [p[0] for p in rings[0]]
        ys = [p[1] for p in rings[0]]
        self.x0, self.y0 = min(xs) - 0.1, min(ys) - 0.1
        self.nx = int(math.ceil((max(xs) + 0.1 - self.x0) / CELL))
        self.ny = int(math.ceil((max(ys) + 0.1 - self.y0) / CELL))
        gx = self.x0 + (np.arange(self.nx) + 0.5) * CELL
        gy = self.y0 + (np.arange(self.ny) + 0.5) * CELL
        self.GX, self.GY = np.meshgrid(gx, gy)
        self.floor = pip(self.GX, self.GY, rings)
        # the walls as the walker has them (plan_meta nav.solid): a room the
        # sheet draws as one can be two on the field (flat 30's bathroom)
        bx0, by0, bx1, by1 = self.x0, self.y0, self.x0 + self.nx * CELL, self.y0 + self.ny * CELL
        for sr in solids:
            o = sr[0]
            xs = [p[0] for p in o]
            ys = [p[1] for p in o]
            if max(xs) < bx0 or min(xs) > bx1 or max(ys) < by0 or min(ys) > by1:
                continue
            self.floor &= ~pip(self.GX, self.GY, sr)
        bxs = [p[0] for p in rings[0]]
        bys = [p[1] for p in rings[0]]
        self.bbc = ((min(bxs) + max(bxs)) / 2, (min(bys) + max(bys)) / 2)

    def wall_near(self, p, normal=None, tol=0.45):
        """The wall edge nearest p (optionally facing `normal` inward)."""
        best = None
        for w in self.walls:
            a, b, u, n, L, hole = w
            if normal is not None and n[0] * normal[0] + n[1] * normal[1] < 0.8:
                continue
            t = (p[0] - a[0]) * u[0] + (p[1] - a[1]) * u[1]
            if t < -0.1 or t > L + 0.1:
                continue
            q = (a[0] + u[0] * t, a[1] + u[1] * t)
            dd = math.hypot(p[0] - q[0], p[1] - q[1])
            if dd < tol and (best is None or dd < best[0]):
                best = (dd, w, t, q)
        return best

    def contains(self, c, w, d, h, inset=0.02, back=None):
        """The box w x d at c facing h stands on this room's floor (sampled
        every 5 cm, `inset` in from its sides, `back` in from its -X side)."""
        back = inset if back is None else back
        us = np.linspace(-w / 2 + inset, w / 2 - inset, max(2, int(math.ceil((w - 2 * inset) / 0.05)) + 1))
        vs = np.linspace(-d / 2 + back, d / 2 - inset, max(2, int(math.ceil((d - back - inset) / 0.05)) + 1))
        U, V = np.meshgrid(us, vs)
        f = fwd(h)
        px = c[0] - f[1] * U + f[0] * V
        py = c[1] + f[0] * U + f[1] * V
        return bool(pip(px, py, self.rings).all())

    # ---- the walking body: what stays reachable
    def paint(self, poly, R=R_BODY):
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        i0 = max(0, int((min(xs) - R - self.x0) / CELL))
        i1 = min(self.nx, int((max(xs) + R - self.x0) / CELL) + 2)
        j0 = max(0, int((min(ys) - R - self.y0) / CELL))
        j1 = min(self.ny, int((max(ys) + R - self.y0) / CELL) + 2)
        M = np.zeros(self.floor.shape, bool)
        if i1 <= i0 or j1 <= j0:
            return M
        X = self.GX[j0:j1, i0:i1]
        Y = self.GY[j0:j1, i0:i1]
        m = pip(X, Y, [poly])
        n = len(poly)
        for k in range(n):
            m |= seg_dist(X, Y, poly[k], poly[(k + 1) % n]) < R
        M[j0:j1, i0:i1] = m
        return M

    def spot(self, raw):
        """walk.js roomSpot: the floor cell with the most clearance (capped at
        0.9 m), the room's middle breaking ties."""
        blocked = ~self.floor | raw
        d = np.zeros(self.floor.shape, float)
        cur = blocked.copy()
        for k in range(1, 19):
            n = cur.copy()
            n[1:, :] |= cur[:-1, :]
            n[:-1, :] |= cur[1:, :]
            n[:, 1:] |= cur[:, :-1]
            n[:, :-1] |= cur[:, 1:]
            n[1:, 1:] |= cur[:-1, :-1]
            n[:-1, :-1] |= cur[1:, 1:]
            n[1:, :-1] |= cur[:-1, 1:]
            n[:-1, 1:] |= cur[1:, :-1]
            d[~n] = k
            cur = n
        sc = np.minimum(d * CELL, 0.9) - 1e-3 * np.hypot(self.GX - self.bbc[0], self.GY - self.bbc[1])
        sc[~self.floor] = -9
        return np.unravel_index(np.argmax(sc), sc.shape)

    def reach(self, block, seeds):
        free = self.floor & ~block
        r = seeds & free
        if not r.any():
            return r
        while True:
            n = r.copy()
            n[1:, :] |= r[:-1, :]
            n[:-1, :] |= r[1:, :]
            n[:, 1:] |= r[:, :-1]
            n[:, :-1] |= r[:, 1:]
            n &= free
            if n.sum() == r.sum():
                return n
            r = n


# ------------------------------------------------------------ the unit
class Unit:
    def __init__(self, level, num, rec, is_office, pieces, meta, ceiling):
        self.level, self.num, self.rec, self.office = level, num, rec, is_office
        self.owner = ('o%s' if is_office else 'u%s') % num
        self.pieces = pieces
        self.ceiling = ceiling
        self.added = []
        self.removed = set()        # nodes of drawn pieces the dressing replaced (the round table set)
        self.count = {}
        for p in pieces:
            self.count[p['kind']] = max(self.count.get(p['kind'], 0), p['k'])
        self.rooms = {}
        self.rid = {r['id']: i for i, r in enumerate(rec['rooms'])}
        solids = []
        for q in ((meta or {}).get('nav') or {}).get('solid') or []:
            if isinstance(q, dict):
                solids.append([q['outline']] + list(q.get('holes') or []))
            else:
                solids.append([q])
        for r in rec['rooms']:
            rings = LF.room_net(r)
            loggia = False
            if rings is None and r['kind'] in ('balcony', 'loggia') and r.get('polygon'):
                pj = r['polygon']
                if isinstance(pj, list):
                    pj = max(pj, key=lambda q: len(q['outline']))
                rings = [pj['outline']] + list(pj.get('holes') or [])
                loggia = True
            if rings is None:
                continue
            if r['kind'] in ('balcony', 'loggia'):
                loggia = True
            self.rooms[r['id']] = Room(r, rings, loggia, solids)
        # the obstacles every new piece is tested against (all rooms: a swing
        # crosses into the next room, a piece never does)
        self.obs = []
        for p in pieces:
            self.obs.append(self.piece_ob(p))
        # door leaves: the swing (plan_meta), else a disc round the opening
        leaves = []
        if meta:
            for coll in ('flats', 'offices'):
                for u in meta.get(coll) or []:
                    if u.get('token') == self.owner:
                        leaves = u.get('doors') or []
                        self.loggia_polys = u.get('loggias') or []
        self.leaves = leaves
        for D in leaves:
            hx, hy = D['hinge']
            w = D['w'] + 0.06
            a0 = D['shut']
            a1 = D['shut'] + D['open']
            pts = [(hx, hy)]
            for k in range(7):
                a = math.radians(a0 + (a1 - a0) * k / 6.0)
                pts.append((hx + w * math.cos(a), hy + w * math.sin(a)))
            # a sector of up to 90 deg is convex; split a wider one
            if abs(a1 - a0) <= 95:
                self.obs.append(Ob(pts, 0.0, 2.15, 'swing'))
            else:
                self.obs.append(Ob(pts[:5], 0.0, 2.15, 'swing'))
                self.obs.append(Ob([pts[0]] + pts[4:], 0.0, 2.15, 'swing'))
        # throats and windows, per room
        for room in self.rooms.values():
            for dr in room.r.get('doors') or []:
                c = dr['centre']
                hit = room.wall_near(c, tol=0.4)
                if hit is None:
                    poly = rect(c, 1.0, 1.0, 0.0)
                else:
                    n = hit[1][3]
                    poly = rect(c, (dr.get('width') or 0.8) + 0.12, 1.9, heading(n))
                    if not leaves:
                        poly2 = rect(c, (dr.get('width') or 0.8) * 2.0, (dr.get('width') or 0.8) * 2.0, heading(n))
                        self.obs.append(Ob(poly2, 0.0, 2.15, 'swing'))
                self.obs.append(Ob(poly, 0.0, 2.15, 'throat'))
            for wd in room.r.get('windows') or []:
                c = wd['centre']
                out = fwd(wd.get('outward', 0.0))
                inn = (-out[0], -out[1])
                hit = room.wall_near(c, normal=inn, tol=0.5)
                q = hit[3] if hit else c
                door = wd.get('kind') != 'window'
                dep = 0.9 if door else 0.55
                cc = (q[0] + inn[0] * dep / 2, q[1] + inn[1] * dep / 2)
                self.obs.append(Ob(rect(cc, (wd.get('width') or 1.0) + 0.06, dep, heading(inn)),
                                   0.0 if door else 0.9, 2.5, 'window_door' if door else 'window'))

    # -- the obstacle a placed piece makes
    def piece_ob(self, p):
        b = p.get('box') or p.get('foot')
        bb = p.get('_bounds')
        if bb is None:
            parts = LF.class_parts(p['cls'], p['kind'], p['params'])
            bb = LF.parts_bounds(parts) if parts else (0, 0, 0, 0, 0, 2.0)
            p['_bounds'] = bb
        z0 = bb[2] + (p.get('z') or 0.0)
        z1 = bb[5] + (p.get('z') or 0.0)
        if b.get('axis_aligned'):
            cx, cy = b['centre']
            hx, hy = b['size'][0] / 2 + 0.02, b['size'][1] / 2 + 0.02
            poly = [(cx - hx, cy - hy), (cx + hx, cy - hy), (cx + hx, cy + hy), (cx - hx, cy + hy)]
        else:
            poly = rect(b['centre'], b['size'][0] + 0.04, b['size'][1] + 0.04, b.get('heading', 0.0))
        tag = 'rug' if p['kind'] in ('rug', 'rug_bedroom', 'bath_mat') else p['kind']
        return Ob(poly, z0, z1, tag, solid=bool(p.get('box')) and z1 > SOLID_Z[0] and z0 < SOLID_Z[1], piece=p)

    def pieces_by_kind(self, kind):
        return [p for p in self.added if p['kind'] == kind]

    def room_of(self, rid):
        return self.rooms.get(rid)

    def pieces_in(self, rid, kind=None):
        return [p for p in self.pieces + self.added if p['room'] == rid and (kind is None or p['kind'] == kind)
                and p['node'] not in self.removed]

    def forget(self, pcs):
        """Take pieces out: their obstacles go, the room's walking field is
        rebuilt on the next reach test. A drawn piece is left out of the
        output; an added one is dropped from `added`."""
        ids = set(id(p) for p in pcs)
        self.obs = [ob for ob in self.obs if ob.piece is None or id(ob.piece) not in ids]
        for p in pcs:
            self.removed.add(p['node'])
        self.added = [p for p in self.added if id(p) not in ids]
        self.stale()

    def restore(self, pcs):
        for p in pcs:
            self.removed.discard(p['node'])
            self.obs.append(self.piece_ob(p))
        self.stale()

    def stale(self):
        for room in self.rooms.values():
            for a in ('_block', '_raw', '_reach', '_seeds', '_allseed', '_spot_ok'):
                if hasattr(room, a):
                    delattr(room, a)

    def reshape(self, p, poly, z1=None):
        """A placed piece grew or moved: its obstacle follows."""
        for ob in self.obs:
            if ob.piece is p:
                ob.poly = poly
                if z1 is not None:
                    ob.z1 = z1
                if p.get('box'):
                    ob.solid = ob.z1 > SOLID_Z[0] and ob.z0 < SOLID_Z[1]
        self.stale()

    # -- the tests
    def clear(self, polys, z0, z1, ignore=(), rug=False, skip_tags=()):
        for ob in self.obs:
            if ob.piece is not None and ob.piece.get('node') in ignore:
                continue
            if ob.tag in skip_tags:
                continue
            if rug:
                # a rug goes under furniture and across a doorway (it is
                # 1.5 cm); it keeps off other rugs and a leaf's swing
                if ob.tag not in ('rug', 'swing'):
                    continue
            elif ob.tag == 'rug':
                continue
            if ob.z1 <= z0 + 1e-3 or ob.z0 >= z1 - 1e-3:
                continue
            for P in polys:
                if sat(P, ob.poly):
                    return False
        return True

    def reach_ok(self, room, poly):
        if not hasattr(room, '_block'):
            # a body's centre keeps R off the walls too: the floor eroded
            wall = ~room.floor
            k = int(math.ceil(R_BODY / CELL))
            room._block = wall.copy()
            H, Wd = wall.shape
            for dj in range(-k, k + 1):
                for di in range(-k, k + 1):
                    if di * di + dj * dj > (R_BODY / CELL) ** 2 or (di == 0 and dj == 0):
                        continue
                    src = wall[max(0, -dj):H - max(0, dj), max(0, -di):Wd - max(0, di)]
                    room._block[max(0, dj):H - max(0, -dj), max(0, di):Wd - max(0, -di)] |= src
            room._raw = np.zeros(room.floor.shape, bool)
            for ob in self.obs:
                if ob.solid:
                    room._block |= room.paint(ob.poly)
                    room._raw |= room.paint(ob.poly, R=0.001)
            seeds = []
            for dr in room.r.get('doors') or []:
                c = dr['centre']
                S = room.floor & (np.hypot(room.GX - c[0], room.GY - c[1]) < 0.55)
                if (S & ~room._block).any():
                    seeds.append(S)
            if not seeds:
                # no door of its own (an opening): the biggest free patch
                free = room.floor & ~room._block
                if free.any():
                    j, i = np.unravel_index(np.argmax(free), free.shape)
                    S = np.zeros(free.shape, bool)
                    # flood from every free cell's component; pick the largest
                    best = None
                    todo = free.copy()
                    while todo.any():
                        j, i = np.unravel_index(np.argmax(todo), todo.shape)
                        S = np.zeros(free.shape, bool)
                        S[j, i] = True
                        comp = room.reach(room._block, S)
                        todo &= ~comp
                        if best is None or comp.sum() > best.sum():
                            best = comp
                    seeds = [best]
            room._seeds = seeds
            allseed = np.zeros(room.floor.shape, bool)
            for S in seeds:
                allseed |= S
            room._allseed = allseed
            room._reach = room.reach(room._block, allseed)
            sp = room.spot(room._raw)
            room._spot_ok = bool(room._reach[sp])
        if poly and isinstance(poly[0][0], (tuple, list)):
            # a set of footprints tested as one (a table and its chairs)
            mine = np.zeros(room.floor.shape, bool)
            for q in poly:
                mine |= room.paint(q)
            raw_q = poly
        else:
            mine = room.paint(poly)
            raw_q = [poly]
        block = room._block | mine
        r1 = room.reach(block, room._allseed)
        for S in room._seeds:
            if (S & room._reach).any() and not (S & r1).any():
                return False
        # every seed must still meet every other (one region, not two)
        if len(room._seeds) > 1:
            r0 = room.reach(block, room._seeds[0])
            for S in room._seeds[1:]:
                if (S & room._reach).any() and not (S & r0).any():
                    return False
        lost = (room._reach & ~r1 & ~mine).sum() * CELL * CELL
        if lost > LOSS_MAX:
            return False
        # the walker's own target in the room must stay where a body gets to
        if room._spot_ok:
            rw = room._raw.copy()
            for q in raw_q:
                rw |= room.paint(q, R=0.001)
            sp = room.spot(rw)
            if not r1[sp]:
                return False
        return True

    def commit_solid(self, room, poly):
        if hasattr(room, '_block'):
            room._block |= room.paint(poly)
            room._raw |= room.paint(poly, R=0.001)
            room._reach = room.reach(room._block, room._allseed)
            room._spot_ok = bool(room._reach[room.spot(room._raw)])

    def try_place(self, room, kind, w, d, c, rot, z0, z1, params, seed, solid_poly=None, extra_polys=(),
                  inset=0.02, back=None, rug=False, ignore=(), skip_tags=(), z=0.0, check_contain=True,
                  foot=None, contain_wd=None):
        """Test and, if it passes, place one undrawn piece. `solid_poly`: its
        footprint for the walking body (None = not solid). -> piece or None"""
        poly = rect(c, w, d, rot) if foot is None else foot
        if check_contain:
            cw, cd = contain_wd or (w, d)
            if not room.contains(c, cw, cd, rot, inset=inset, back=back):
                return None
        if not self.clear([poly] + list(extra_polys), z0, z1, ignore=ignore, rug=rug, skip_tags=skip_tags):
            return None
        if solid_poly is not None and not self.reach_ok(room, solid_poly):
            return None
        return self.add(room, kind, w, d, c, rot, z0, z1, params, seed, poly, solid_poly, z)

    def add(self, room, kind, w, d, c, rot, z0, z1, params, seed, poly, solid_poly, z=0.0):
        if kind in SKIP_KINDS:
            return None
        P = dict(params)
        P['w'] = round(w, 3)
        P['d'] = round(d, 3)
        P['seed'] = int(seed)
        key = '_'.join('%s%s' % (a, ('%g' % v) if isinstance(v, (int, float)) else v)
                       for a, v in sorted(P.items()) if a not in ('w', 'd', 'seed'))
        cls = '%s_%03d_%03d_s%d%s' % (kind, round(w * 100), round(d * 100), seed, ('_' + key) if key else '')
        cls = cls.replace('.', 'p').replace('-', 'm')
        # the mesh as the kit really builds it (leaves, finials, a throw past
        # the box) stays in the room: 3 cm of slack, the back on its wall
        parts = LF.class_parts(cls, kind, P)
        if parts:
            bx0, by0, bz0, bx1, by1, bz1 = LF.parts_bounds(parts)
            rc = loc2plan(c, rot, (bx0 + bx1) / 2, (by0 + by1) / 2)
            if not room.contains(rc, max(0.02, by1 - by0 - 0.06), max(0.02, bx1 - bx0 - 0.06), rot, inset=0.0, back=0.0):
                return None
        self.count[kind] = self.count.get(kind, 0) + 1
        k = self.count[kind]
        node = 'in_%s_%s_furn_%s%d__%s' % (self.level, self.owner, kind, k, MAIN_MAT.get(kind, 'int_white_gloss'))
        foot = dict(centre=[round(c[0], 4), round(c[1], 4)], size=[round(w, 3), round(d, 3)], heading=round(rot % 360, 3))
        p = dict(node=node, kind=kind, k=k, owner=self.owner, n=self.num, cls=cls, params=P,
                 at=[round(c[0], 4), round(c[1], 4)], rot=round(rot % 360.0, 3), box=None, foot=foot,
                 room=room.id, room_index=self.rid.get(room.id), src=None, drawn=False, z=round(z, 3))
        if solid_poly is not None:
            # the solid footprint as a box record (walk.js / lib_plan read it)
            xs = solid_poly
            cx = sum(q[0] for q in xs) / len(xs)
            cy = sum(q[1] for q in xs) / len(xs)
            e0 = (xs[1][0] - xs[0][0], xs[1][1] - xs[0][1])
            e1 = (xs[2][0] - xs[1][0], xs[2][1] - xs[1][1])
            # footprint() corners: 0->1 runs across (w), 1->2 along (d)
            p['box'] = dict(centre=[round(cx, 4), round(cy, 4)],
                            size=[round(math.hypot(*e0), 3), round(math.hypot(*e1), 3)],
                            heading=round(rot % 360.0, 3))
        p['_bounds'] = (0, 0, z0 - z, 0, 0, z1 - z)
        self.added.append(p)
        ob = Ob(poly, z0, z1, 'rug' if kind in ('rug', 'rug_bedroom', 'bath_mat') else kind,
                solid=solid_poly is not None, piece=p)
        self.obs.append(ob)
        if solid_poly is not None:
            self.commit_solid(room, solid_poly)
        return p

    # -- candidate spots
    def wall_spots(self, room, w, d, gap=0.005, step=0.10, holes=False, min_len=None):
        """(centre, rot, wall, t) for a piece w wide, d deep, its back on a wall."""
        out = []
        for wl in room.walls:
            a, b, u, n, L, hole = wl
            if hole and not holes:
                continue
            if L < (min_len or w) - 0.02:
                continue
            m = max(1, int((L - w) / step) + 1)
            for k in range(m + 1):
                t = w / 2 + (L - w) * (k / m if m else 0.5)
                if L < w:
                    t = L / 2
                bp = (a[0] + u[0] * t, a[1] + u[1] * t)
                c = (bp[0] + n[0] * (d / 2 + gap), bp[1] + n[1] * (d / 2 + gap))
                out.append((c, heading(n), wl, t))
        return out

    def corner_spots(self, room, r):
        """Centres r + 0.12 off both walls of every inner corner."""
        out = []
        for ring in room.rings[:1]:
            m = len(ring)
            for i in range(m):
                v = ring[i]
                p0 = ring[i - 1]
                p1 = ring[(i + 1) % m]
                e0 = (v[0] - p0[0], v[1] - p0[1])
                e1 = (p1[0] - v[0], p1[1] - v[1])
                if math.hypot(*e0) < 0.25 or math.hypot(*e1) < 0.25:
                    continue
                # the inward normals of the two walls
                ns = []
                for (q0, q1) in ((p0, v), (v, p1)):
                    L = math.hypot(q1[0] - q0[0], q1[1] - q0[1])
                    uu = ((q1[0] - q0[0]) / L, (q1[1] - q0[1]) / L)
                    nn = (-uu[1], uu[0])
                    mid = ((q0[0] + q1[0]) / 2, (q0[1] + q1[1]) / 2)
                    if not pip([mid[0] + nn[0] * 0.03], [mid[1] + nn[1] * 0.03], room.rings)[0]:
                        nn = (-nn[0], -nn[1])
                    ns.append(nn)
                if ns[0][0] * ns[1][0] + ns[0][1] * ns[1][1] > 0.3:
                    continue
                off = r + 0.12
                c = (v[0] + (ns[0][0] + ns[1][0]) * off, v[1] + (ns[0][1] + ns[1][1]) * off)
                if pip([c[0]], [c[1]], room.rings)[0]:
                    out.append((c, heading((ns[0][0] + ns[1][0], ns[0][1] + ns[1][1]))))
        return out

    def windows(self, room):
        out = []
        for wd in room.r.get('windows') or []:
            out.append((wd['centre'], wd.get('width') or 1.0, wd.get('kind') != 'window', wd.get('outward', 0.0)))
        return out


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def pick(n, salt, options):
    return options[seed_of(n, salt) % len(options)]


# ------------------------------------------------------------ the rules
def plant_try(U, room, kinds, spots_fn, score_fn, sizes=('L', 'M', 'S'), salt='plant', solid=True, z=0.0):
    """A floor plant: the first kind/size that finds a spot, the best spot by
    score. Its leaves keep off walls and tall pieces, its pot off everything;
    its pot is solid to a walking body."""
    for kind in kinds:
        spec = LF.KIT[kind].KINDS[kind]
        for sz in sizes:
            w, d, extra = spec['sizes'][sz]
            prm = {k: v[0] for k, v in spec['params'].items() if k in ('h', 'pot_d', 'pot_h', 'plant_h')}
            prm.update(extra)
            h = prm.get('h', 1.0)
            pot = prm.get('pot_d', 0.3)
            seed = seed_of(U.num, salt, room.id) % 3
            r = max(w, d) / 2
            cands = []
            for c, rot in spots_fn(r):
                sc = score_fn(c)
                if sc is not None:
                    cands.append((sc, c, rot))
            cands.sort(key=lambda t: t[0])
            for sc, c, rot in cands[:80]:
                if not room.contains(c, w * 0.95, d * 0.95, rot, inset=0.0):
                    continue
                spread = rect(c, w * 0.95, d * 0.95, rot)
                potp = rect(c, pot + 0.04, pot + 0.04, rot)
                if not U.clear([potp], z, z + h):
                    continue
                if not U.clear([spread], z + h * 0.35, z + h, skip_tags=('window',)):
                    continue
                sp = rect(c, pot, pot, rot) if solid else None
                if sp is not None and not U.reach_ok(room, sp):
                    continue
                return U.add(room, kind, w, d, c, rot, z, z + h, dict(extra), seed, spread, sp, z)
    return None


def spots_free(U, room, r, step=0.15):
    """Corners first, then along every wall, r + 0.12 off it."""
    out = list(U.corner_spots(room, r))
    for c, rot, wl, t in U.wall_spots(room, 2 * r, 2 * r, gap=0.12, step=step):
        out.append((c, rot))
    return out


def near_window_score(U, room, c, prefer=None):
    ws = U.windows(room)
    s = 0.0
    if ws:
        s += min(dist(c, w[0]) for w in ws)
    if prefer is not None:
        s += 0.5 * dist(c, prefer)
    # keep away from the kitchen
    for p in U.pieces_in(room.id, 'kitchen_run'):
        if dist(c, p['at']) < 1.2:
            s += 3.0
    return s


def curtains(U, room):
    for (c, width, door, outward) in U.windows(room):
        out = fwd(outward)
        inn = (-out[0], -out[1])
        hit = room.wall_near(c, normal=inn, tol=0.5)
        if hit is None:
            continue
        q = hit[3]
        rot = heading(inn)
        cc = (q[0] + inn[0] * 0.085, q[1] + inn[1] * 0.085)
        # a worktop under the window: no curtain (a blind would go there)
        front = rect((q[0] + inn[0] * 0.4, q[1] + inn[1] * 0.4), width + 0.6, 0.8, rot)
        if any(sat(front, ob.poly) for ob in U.obs if ob.tag == 'kitchen_run'):
            continue
        for ow in (width, width - 0.1, width - 0.2, width - 0.3):
            if ow < 0.6:
                break
            tw = ow + 0.58
            p = U.try_place(room, 'curtains', ow, 0.16, cc, rot, 0.0, U.ceiling,
                            dict(head=min(2.7, U.ceiling - 0.25), ceiling=U.ceiling, open=0.9), 0,
                            foot=rect((q[0] + inn[0] * 0.11, q[1] + inn[1] * 0.11), tw, 0.22, rot), contain_wd=(tw, 0.16), back=0.06,
                            skip_tags=('window', 'window_door', 'swing', 'throat'))
            if p:
                break


def wall_art(U, room, over=None, w=0.8, cz=1.55, salt='art', score=None):
    """A picture: over a piece (its back on a wall), else the best free wall."""
    seed = seed_of(U.num, salt, room.id) % 3
    style = seed_of(U.num, salt + 's', room.id) % 3
    h_est = (1.3 * w) if w <= 0.75 else (0.75 * w)
    z0, z1 = cz - h_est / 2 - 0.02, cz + h_est / 2 + 0.02
    if over is not None:
        b = over['box']
        f = fwd(over['rot'])
        bp = (over['at'][0] - f[0] * b['size'][1] / 2, over['at'][1] - f[1] * b['size'][1] / 2)
        # the piece's back really is on a wall
        if not pip([bp[0] - f[0] * 0.08], [bp[1] - f[1] * 0.08], room.rings)[0]:
            c = (bp[0] + f[0] * 0.02, bp[1] + f[1] * 0.02)
            p = U.try_place(room, 'wall_art', w, 0.03, c, over['rot'], z0, z1, dict(cz=cz, style=style), seed,
                            back=0.0, inset=0.0, ignore=(over['node'],), contain_wd=(w, 0.02))
            if p:
                return p
    best = None
    for c, rot, wl, t in U.wall_spots(room, w + 0.3, 0.03, gap=0.005, step=0.1):
        sc = score(c) if score else -wl[4]
        if sc is None:
            continue
        if best is not None and sc >= best[0]:
            continue
        if not room.contains(c, w + 0.3, 0.03, rot, inset=0.0, back=0.0):
            continue
        if not U.clear([rect(c, w + 0.3, 0.30, rot)], z0, z1):
            continue
        best = (sc, c, rot)
    if best:
        sc, c, rot = best
        return U.add(room, 'wall_art', w, 0.03, c, rot, z0, z1, dict(cz=cz, style=style), seed,
                     rect(c, w, 0.03, rot), None)
    return None





def sideboard(U, room, near=None):
    if room.area < 19.0:
        return None
    for w in (1.6, 1.4, 1.2):
        best = None
        for c, rot, wl, t in U.wall_spots(room, w, 0.42, gap=0.005, step=0.1):
            sc = dist(c, near) if near else -wl[4]
            if best is not None and sc >= best[0]:
                continue
            if not room.contains(c, w, 0.42, rot, back=0.04):
                continue
            access = rect(loc2plan(c, rot, 0.21 + 0.35, 0.0), w, 0.7, rot)
            if not U.clear([rect(c, w, 0.42, rot)], 0.0, 1.3) or not U.clear([access], 0.0, 1.0):
                continue
            # not a second cabinet beside the TV's console
            wide = rect(c, w + 2.6, 1.0, rot)
            if any(ob.tag == 'tv' and sat(wide, ob.poly) for ob in U.obs):
                continue
            best = (sc, c, rot)
        if best:
            sc, c, rot = best
            sp = rect(c, w, 0.42, rot)
            if U.reach_ok(room, sp):
                return U.add(room, 'sideboard', w, 0.42, c, rot, 0.0, 1.3, dict(), seed_of(U.num, 'sb') % 2,
                             sp, sp)
    return None


def pothos(U, room, prefer=None):
    w, d = 0.6, 0.22
    best = None
    for c, rot, wl, t in U.wall_spots(room, w, d, gap=0.005, step=0.1):
        sc = dist(c, prefer) if prefer else 0.0
        if best is not None and sc >= best[0]:
            continue
        if not room.contains(c, w, d, rot, back=0.04):
            continue
        if not U.clear([rect(loc2plan(c, rot, 0.06, 0.0), w + 0.2, 0.36, rot)], 0.85, 1.85):
            continue
        best = (sc, c, rot)
    if best:
        sc, c, rot = best
        return U.add(room, 'plant_pothos', w, d, c, rot, 0.85, 1.85, dict(shelf_z=1.75, trail=0.8),
                     seed_of(U.num, 'pothos') % 3, rect(c, w, d, rot), None)
    return None


def tv_console(U, room, tv):
    """The TV kit stands on a media console wider and deeper than the drawn
    box: as wide as the wall allows, the index box made the console's."""
    w, d = tv['params']['w'], tv['params']['d']
    f = fwd(tv['rot'])
    for cw in (2.0, 1.8, 1.6, 1.4, 1.2, max(1.0, w + 0.15)):
        cd = 0.40
        c = (tv['at'][0] + f[0] * (cd - d) / 2, tv['at'][1] + f[1] * (cd - d) / 2)
        if not room.contains(c, cw, cd, tv['rot'], back=0.04):
            continue
        if not U.clear([rect(c, cw, cd, tv['rot'])], 0.0, 1.0, ignore=(tv['node'],)):
            continue
        access = rect(loc2plan(c, tv['rot'], cd / 2 + 0.3, 0.0), cw, 0.6, tv['rot'])
        if not U.clear([access], 0.0, 0.6, ignore=(tv['node'],), skip_tags=('window',)):
            continue
        # a wide console must not cut the room's doors apart (it did, in ~40
        # living rooms, before the renders' rebuild)
        if not U.reach_ok(room, rect(c, cw, cd, tv['rot'])):
            continue
        tv['params']['console_w'] = cw
        tv['cls'] = '%s_c%03d' % (tv['cls'], round(cw * 100))
        tv['box'] = dict(centre=[round(c[0], 4), round(c[1], 4)], size=[cw, cd], heading=tv['box'].get('heading', tv['rot']))
        tv.pop('_bounds', None)
        U.reshape(tv, rect(c, cw + 0.04, cd + 0.04, tv['rot']))
        return True
    # no wall for a console: the screen on the wall over a slim shelf
    cw, cd = max(1.0, round(w + 0.1, 2)), 0.32
    tv['params']['console_w'] = cw
    tv['params']['console_d'] = cd
    tv['cls'] = '%s_cw' % tv['cls']
    c = (tv['at'][0] + f[0] * (cd - d) / 2, tv['at'][1] + f[1] * (cd - d) / 2)
    tv['box'] = dict(centre=[round(c[0], 4), round(c[1], 4)], size=[cw, cd], heading=tv['box'].get('heading', tv['rot']))
    tv.pop('_bounds', None)
    U.reshape(tv, rect(c, cw + 0.04, cd + 0.04, tv['rot']))
    return False






def wardrobe(U, room):
    if U.pieces_in(room.id, 'wardrobe'):
        return None
    for w in (2.4, 2.0, 1.8, 1.6, 1.4, 1.2, 1.0):
        d = 0.60
        best = None
        for c, rot, wl, t in U.wall_spots(room, w, d, gap=0.005, step=0.05):
            a, b, u, n, L, hole = wl
            # snug: the nearer end of the wall
            snug = min(t - w / 2, L - t - w / 2)
            sc = snug
            if best is not None and sc >= best[0]:
                continue
            if not room.contains(c, w, d, rot, back=0.04):
                continue
            sp = rect(c, w, d, rot)
            access = rect(loc2plan(c, rot, d / 2 + 0.35, 0.0), w, 0.7, rot)
            if not U.clear([sp], 0.0, 2.35) or not U.clear([access], 0.0, 1.8):
                continue
            best = (sc, c, rot, sp)
        if best:
            for tries in range(1):
                sc, c, rot, sp = best
                if U.reach_ok(room, sp):
                    return U.add(room, 'wardrobe', w, d, c, rot, 0.0, 2.35, dict(h=2.3), 0, sp, sp)
    return None






# ------------------------------------------------------------ the owner's renders (Nov 2026)
# The rules below dress a flat after the ten renders the owner sent on
# 2026-11-26: a greige handleless kitchen with a marble top between tall
# walnut columns (a black fridge in one), an island where the living room
# has the floor, a rectangular walnut dining table with four curved chairs,
# a white boucle sofa (an L where it fits) with a loveseat and a pouf round
# a small dark table, big bird-of-paradise and monstera plants, a hall
# wardrobe wall, an A/C unit on the loggia. Gone: rugs, floor lamps, the
# armchair, sideboard, pothos shelf, herbs, the dining pendant, bath mats,
# bathroom plants and baskets, loggia troughs.
GREAT_PLANTS = ('plant_strelitzia', 'plant_monstera')
ISLAND_AREA = 30.0          # m2 of living room before an island is tried (the 1-bed flats of render 4 have none)


def long_wall(room):
    walls = [w for w in room.walls if not w[5]]
    return max(walls, key=lambda w: w[4]) if walls else None


def kitchen_aisles(U, room, depth=0.9):
    """The floor a cook stands on in front of every run leg."""
    out = []
    for leg in U.pieces_in(room.id, 'kitchen_run'):
        W, D = leg['params']['w'], leg['params']['d']
        out.append(rect(loc2plan(leg['at'], leg['rot'], D / 2 + depth / 2, 0.0), W, depth, leg['rot']))
    for isl in U.pieces_in(room.id, 'kitchen_island'):
        Li, Di = isl['params']['w'], isl['params']['d']
        out.append(rect(isl['at'], Li + 0.2, Di + 1.8, isl['rot']))
    return out


def restyle_kitchen(U):
    """The run as the renders draw it: handleless greige fronts (int_mint,
    the bars in the same colour), a marble worktop and splashback; the hob's
    chimney hood in steel (`chrome`, not the facade's frame_light)."""
    for p in U.pieces:
        if p['kind'] == 'kitchen_run':
            p['params'].update(front='int_mint', top='int_marble', handle='int_mint')
            p['cls'] += '_gm'
        elif p['kind'] == 'hob':
            p['params']['steel'] = 'chrome'
            p['cls'] += '_cr'


def take_dining(U, room):
    """The drawn round table and its three chairs, taken out (the renders
    seat four at a long walnut table). -> [(centre, [pieces])]"""
    out = []
    for t in U.pieces_in(room.id, 'table_round'):
        chairs = [p for p in U.pieces_in(room.id, 'chair') if dist(p['at'], t['at']) < 1.3]
        U.forget([t] + chairs)
        out.append((t['at'], [t] + chairs))
    return out


def dining_seats(c, rot, L, W):
    """Two chairs on each long side of a table L long, W wide, facing it,
    pushed in (the seat's front under the top)."""
    out = []
    for side in (1, -1):
        for y in (-L * 0.25, L * 0.25):
            out.append((loc2plan(c, rot, side * (W / 2 + 0.16), y), (rot + 180.0) if side > 0 else rot))
    return out


def place_dining(U, room, taken):
    for c0, old in taken:
        wl = long_wall(room)
        h0 = heading(wl[2]) if wl else 0.0
        sizes = ((1.6, 0.9), (1.4, 0.85), (1.2, 0.8)) if room.area >= ISLAND_AREA else ((1.4, 0.85), (1.2, 0.8))
        avoid = kitchen_aisles(U, room)
        R = 12 if U.pieces_in(room.id, 'kitchen_island') else 6
        shifts = sorted(((dx * 0.1, dy * 0.1) for dx in range(-R, R + 1) for dy in range(-R, R + 1)),
                        key=lambda s: math.hypot(*s))
        done = None
        for L, W in sizes:
            for rot in (h0 + 90.0, h0):
                for dx, dy in shifts:
                    c = (c0[0] + dx, c0[1] + dy)
                    D = W + 0.84                  # the chairs on both long sides
                    if not room.contains(c, L, D, rot, inset=0.0):
                        continue
                    seats = dining_seats(c, rot, L, W)
                    polys = [rect(c, L, W, rot)] + [rect(cc, 0.50, 0.52, cr) for cc, cr in seats]
                    if not U.clear(polys, 0.0, 0.85):
                        continue
                    if any(sat(q, a) for q in polys for a in avoid):
                        continue
                    if not U.reach_ok(room, polys):
                        continue
                    done = (L, W, c, rot, polys)
                    break
                if done:
                    break
            if done:
                break
        if not done:
            # no floor for the long table: the drawn set stays, in walnut and greige
            U.restore(old)
            t = old[0]
            what = 'decor_vase'
            w, d, extra = LF.KIT[what].KINDS[what]['sizes']['S']
            U.add(room, what, w, d, t['at'], t['rot'], 0.75, 1.2, dict(extra), seed_of(U.num, 'dine2') % 3,
                  rect(t['at'], w, d, t['rot']), None, z=0.75)
            continue
        L, W, c, rot, polys = done
        top = rect(c, L, W, rot)
        U.add(room, 'table_dining', L, W, c, rot, 0.0, 0.76, dict(), 0, top, top)
        for cc, crot in dining_seats(c, rot, L, W):
            U.add(room, 'chair', 0.50, 0.52, cc, crot, 0.0, 0.80, dict(), 0, rect(cc, 0.50, 0.52, crot),
                  rect(cc, 0.46, 0.46, crot))
        what = 'decor_vase'
        w, d, extra = LF.KIT[what].KINDS[what]['sizes']['S']
        U.add(room, what, w, d, c, rot, 0.75, 1.2, dict(extra), seed_of(U.num, 'dine2') % 3,
              rect(c, w, d, rot), None, z=0.75)
        # a pair of pictures on the nearest wall
        a1 = wall_art(U, room, w=0.5, cz=1.55, salt='art_dine', score=lambda q: dist(q, c) if dist(q, c) < 2.6 else None)
        if a1:
            wall_art(U, room, w=0.5, cz=1.55, salt='art_dine2',
                     score=lambda q: abs(dist(q, a1['at']) - 0.62) * 4 + dist(q, c) * 0.2
                     if abs(dist(q, a1['at']) - 0.62) < 0.08 else None)


def island(U, room):
    """A kitchen island parallel to the longest run, 1.0-1.15 m off its
    front, with a 1 m aisle on its room side too; the run's hob moves onto
    it. Only in living rooms of ISLAND_AREA and more."""
    if room.area < ISLAND_AREA:
        return None
    legs = sorted(U.pieces_in(room.id, 'kitchen_run'), key=lambda p: -p['params']['w'])
    if not legs:
        return None
    leg = legs[0]
    W, D = leg['params']['w'], leg['params']['d']
    if W < 1.8:
        return None
    rot = leg['rot']
    Di = 0.95
    for Li in (2.2, 2.0, 1.8):
        if Li > W + 0.4:
            continue
        for gap in (1.05, 1.15, 1.0):
            for t in (0.0, 0.15, -0.15, 0.3, -0.3, 0.45, -0.45):
                if abs(t) + Li / 2 > W / 2 + 0.35:
                    continue
                c = loc2plan(leg['at'], rot, D / 2 + gap + Di / 2, t)
                body = rect(c, Li, Di, rot)
                oc = loc2plan(c, rot, Di / 2 + 0.5, 0.0)
                out_aisle = rect(oc, Li, 1.0, rot)
                in_aisle = rect(loc2plan(leg['at'], rot, D / 2 + gap / 2, t), Li, gap - 0.04, rot)
                if not room.contains(c, Li, Di, rot, inset=0.0) or not room.contains(oc, Li, 1.0, rot, inset=0.0):
                    continue
                if not U.clear([body], 0.0, 1.0):
                    continue
                if not U.clear([in_aisle, out_aisle], 0.0, 1.2, skip_tags=('window', 'throat')):
                    continue
                if not U.clear([rect(c, 0.45, 0.45, rot)], 1.55, U.ceiling):
                    continue
                if not U.reach_ok(room, body):
                    continue
                p = U.add(room, 'kitchen_island', Li, Di, c, rot, 0.0, round(U.ceiling, 3),
                          dict(ceiling=round(U.ceiling, 2)), 0, body, body)
                if not p:
                    continue
                # the hob moves from the run onto the island
                for hb in U.pieces_in(room.id, 'hob'):
                    U.forget([hb])
                for lg in U.pieces_in(room.id, 'kitchen_run'):
                    lp = lg['params']
                    if 'hob_y' in lp:
                        lg['cls'] = lg['cls'].replace('_h%d_%d' % (round(lp['hob_x'] * 100), round(lp['hob_y'] * 100)), '')
                        lp.pop('hob_x', None)
                        lp.pop('hob_y', None)
                        lg['cls'] += '_nohob'
                return p
    return None


def tall_columns(U, room):
    """Floor-to-ceiling walnut columns at the ends of the longest straight
    run (renders 4, 5, 7): the first a black fridge beside a lit niche, the
    second two ovens or the niche alone. The run's ends meet the walls on
    the sheets, so a column takes the END of the run: the leg is shortened
    by the column's width (its sink and hob stay where they are), never at
    an end that turns a corner into another leg."""
    legs = [p for p in sorted(U.pieces_in(room.id, 'kitchen_run'), key=lambda p: -p['params']['w'])
            if not p['params'].get('profile')]
    if not legs:
        return
    leg = legs[0]
    others = [p for p in U.pieces_in(room.id, 'kitchen_run') if p is not leg]
    D = leg['params']['d']
    rot = leg['rot']
    H = round(min(U.ceiling - 0.01, 3.3), 2)
    order = (1, -1) if seed_of(U.num, 'tall') % 2 else (-1, 1)
    plans = [((1.00, 1), (0.62, 1)), ((1.00, 2), (0.45, 0))]
    k = 0
    for side in order:
        if k >= len(plans):
            break
        for tw, app in plans[k]:
            P = leg['params']
            W = P['w']
            if W - tw < 1.6:
                continue
            yc = -side * tw / 2                       # the shortened run's centre, in the leg's frame
            Wn = W - tw
            if any(abs(P[q] - yc) + 0.42 > Wn / 2 for q in ('sink_y', 'hob_y') if q in P):
                continue
            c = loc2plan(leg['at'], rot, 0.0, side * (W / 2 - tw / 2))
            sp = rect(c, tw, D, rot)
            if not room.contains(c, tw, D, rot, back=0.04):
                continue
            if any(sat(rect(c, tw + 0.12, D + 0.12, rot), ob.poly) for ob in U.obs if ob.piece in others):
                continue
            access = rect(loc2plan(c, rot, D / 2 + 0.4, 0.0), tw, 0.8, rot)
            if not U.clear([sp], 0.0, H, ignore=(leg['node'],)) or not U.clear([access], 0.0, 1.5, ignore=(leg['node'],)):
                continue
            # the run, shortened
            nc = loc2plan(leg['at'], rot, 0.0, yc)
            P['w'] = round(Wn, 3)
            for q in ('sink_y', 'hob_y'):
                if q in P:
                    P[q] = round(P[q] - yc, 3)
            leg['at'] = [round(nc[0], 4), round(nc[1], 4)]
            leg['box'] = dict(leg['box'], centre=list(leg['at']), size=[round(Wn, 3), leg['box']['size'][1]])
            leg['cls'] += '_c%s%d' % ('p' if side > 0 else 'n', round(tw * 100))
            leg.pop('_bounds', None)
            U.reshape(leg, rect(nc, Wn + 0.04, D + 0.04, rot))
            if U.add(room, 'tall_walnut', tw, D, c, rot, 0.0, H, dict(h=H, app=app, hand=-side), 0, sp, sp):
                k += 1
            break

def sofa_group(U, room, sofa):
    """The sofa made an L where the floor allows (a chaise at one end), a
    loveseat across the coffee table, a pouf beside it."""
    sw, sd = sofa['box']['size']
    srot = sofa['rot']
    cts = U.pieces_in(room.id, 'table_coffee')
    ct = min(cts, key=lambda p: dist(p['at'], sofa['at'])) if cts else None
    if ct and dist(ct['at'], sofa['at']) > 2.6:
        ct = None
    hw = sw / 2
    order = (1, -1) if seed_of(U.num, 'chaise') % 2 else (-1, 1)
    chaise = 0
    if sd >= 0.85 and sw >= 1.6:
        span = sw - 0.20
        n = 1 if span < 0.95 else (2 if span < 1.85 else 3)
        mw = span / n
        for s in order:
            for clen in (1.55, 1.40):
                ext = clen - sd
                cc = loc2plan(sofa['at'], srot, sd / 2 + ext / 2, s * (hw - mw / 2))
                poly = rect(cc, mw, ext, srot)
                if not room.contains(cc, mw, ext, srot, inset=0.0):
                    continue
                ign = (sofa['node'],) + ((ct['node'],) if ct else ())
                if not U.clear([poly], 0.0, 0.8, ignore=ign):
                    continue
                move = None
                if ct and sat(poly, rect(ct['at'], 0.78, 0.78, srot)):
                    lx, ly = LF.to_local(ct['at'], sofa['at'], srot)
                    for k in range(1, 7):
                        ny = ly - s * 0.08 * k
                        if abs(ny) > hw:
                            break
                        q = loc2plan(sofa['at'], srot, lx, ny)
                        qp = rect(q, 0.78, 0.78, srot)
                        if sat(poly, qp):
                            continue
                        if U.clear([qp], 0.0, 0.4, ignore=ign) and room.contains(q, 0.78, 0.78, srot, inset=0.0):
                            move = q
                            break
                    if move is None:
                        continue
                whole_c = loc2plan(sofa['at'], srot, (clen - sd) / 2, 0.0)
                whole = rect(whole_c, sw, clen, srot)
                if not U.reach_ok(room, whole):
                    continue
                chaise = s
                sofa['params'].update(chaise=s, chaise_len=clen)
                sofa['cls'] += '_ch%s%d' % ('p' if s > 0 else 'n', round(clen * 100))
                sofa['box'] = dict(centre=[round(whole_c[0], 4), round(whole_c[1], 4)], size=[sw, clen],
                                   heading=sofa['box'].get('heading', srot))
                sofa.pop('_bounds', None)
                U.reshape(sofa, rect(whole_c, sw + 0.04, clen + 0.04, srot))
                if move is not None:
                    ct['at'] = [round(move[0], 4), round(move[1], 4)]
                    ct['box'] = dict(ct['box'], centre=list(ct['at']))
                    U.reshape(ct, rect(move, 0.78, 0.78, srot))
                break
            if chaise:
                break
    if ct is None:
        return
    lx, ly = LF.to_local(ct['at'], sofa['at'], srot)
    # the loveseat: across the table, on the side away from the chaise
    if room.area >= 22.0 and 0.3 < lx < 2.4:
        done = False
        for s in [q for q in order if q != chaise]:
            for lw, ld in ((1.6, 0.9), (1.4, 0.88)):
                lrot = srot + 90.0 if s > 0 else srot - 90.0
                for gap in (0.40, 0.55, 0.30):
                    for dx in (0.0, 0.2, 0.4, 0.6):
                        x = lx + dx
                        y = ly + s * (0.38 + gap + ld / 2)
                        c = loc2plan(sofa['at'], srot, x, y)
                        sp = rect(c, lw, ld, lrot)
                        if U.try_place(room, 'loveseat', lw, ld, c, lrot, 0.0, 0.8, dict(),
                                       seed_of(U.num, 'love') % 2, solid_poly=sp, inset=0.0):
                            done = True
                            break
                    if done:
                        break
                if done:
                    break
            if done:
                break
    # the pouf: beside the table, else in front of it
    sides = [q for q in order if q == chaise] + [q for q in order if q != chaise]
    spots = [(lx, ly + s * (0.38 + 0.06 + 0.28)) for s in sides] + [(lx + 0.38 + 0.36, ly)]
    for x, y in spots:
        c = loc2plan(sofa['at'], srot, x, y)
        if U.try_place(room, 'pouf', 0.55, 0.55, c, srot, 0.0, 0.39, dict(), 0, inset=0.0):
            break


def big_plants(U, room, n, sizes=('L', 'M', 'S'), salt='big'):
    kinds = GREAT_PLANTS if seed_of(U.num, salt, room.id) % 2 else GREAT_PLANTS[::-1]
    placed = []

    def far(c):
        return sum(max(0.0, 2.8 - dist(c, q['at'])) * 2.0 for q in placed)
    for i in range(n):
        p = plant_try(U, room, (kinds[i % 2], kinds[(i + 1) % 2]), lambda r: spots_free(U, room, r),
                      lambda c: near_window_score(U, room, c) * 0.6 + far(c), sizes=sizes, salt='%s%d' % (salt, i))
        if p:
            placed.append(p)
    return placed


def living(U, room):
    sofas = U.pieces_in(room.id, 'sofa')
    tvs = U.pieces_in(room.id, 'tv')
    sofa = max(sofas, key=lambda p: p['box']['size'][0]) if sofas else None
    # the coffee table is a 0.7 m disc now, not the drawn 1.2 x 0.6
    for ct in U.pieces_in(room.id, 'table_coffee'):
        U.reshape(ct, rect(ct['at'], 0.78, 0.78, ct['rot']))
    for tv in tvs:
        tv_console(U, room, tv)
    curtains(U, room)
    taken = take_dining(U, room)
    island(U, room)
    tall_columns(U, room)
    place_dining(U, room, taken)
    if sofa:
        wall_art(U, room, over=sofa, w=min(1.0, round(sofa['box']['size'][0] * 0.45, 1)), cz=1.5, salt='art_sofa')
        sofa_group(U, room, sofa)
    big_plants(U, room, 3 if room.area >= ISLAND_AREA else 2)


def dress_bed(U, bed):
    """White linen and a terracotta or greige throw (renders 5, 6, 7 / 4, 12)."""
    throw = ('int_fabric_orange', 'int_fabric_sofa')[seed_of(U.num, 'throw', bed['room']) % 2]
    bed['params'].update(duvet='int_fabric_white', throw=throw)
    bed['cls'] += '_w%s' % throw[11]


def vanity(U, room):
    """The bedroom's vanity (renders 4, 5, 11, 12) where the bedroom kit
    has one: a free wall, near the window, a sitting zone in front."""
    if 'vanity' not in LF.KIT or U.pieces_in(room.id, 'vanity'):
        return None
    mod = LF.KIT['vanity']
    w, d = getattr(mod, 'DEFAULT_SIZE', {}).get('vanity', (1.0, 0.45))
    best = None
    for c, rot, wl, t in U.wall_spots(room, w, d, gap=0.005, step=0.1):
        sc = near_window_score(U, room, c)
        if best is not None and sc >= best[0]:
            continue
        if not room.contains(c, w, d, rot, back=0.04):
            continue
        sp = rect(c, w, d, rot)
        access = rect(loc2plan(c, rot, d / 2 + 0.35, 0.0), w, 0.7, rot)
        if not U.clear([sp], 0.0, 1.7) or not U.clear([access], 0.0, 1.0):
            continue
        best = (sc, c, rot, sp)
    if best:
        sc, c, rot, sp = best
        if U.reach_ok(room, sp):
            return U.add(room, 'vanity', w, d, c, rot, 0.0, 1.7, dict(), seed_of(U.num, 'van') % 2, sp, sp)
    return None


def bedroom(U, room):
    beds = U.pieces_in(room.id, 'bed_double')
    curtains(U, room)
    for bed in beds:
        dress_bed(U, bed)
    wardrobe(U, room)
    vanity(U, room)
    big_plants(U, room, 1, sizes=('L', 'M', 'S'), salt='bed')
    for bed in beds[:1]:
        wall_art(U, room, over=bed, w=min(1.0, round(bed['box']['size'][0] * 0.5, 1)), cz=1.62, salt='art_bed')


def hall_wardrobe(U, room):
    """The renders' hall: a wardrobe wall of greige doors and lit walnut
    shelves on the longest free wall, floor to just under the ceiling, with
    a passage of 0.9 m in front."""
    H = round(min(U.ceiling - 0.02, 3.3), 2)
    d = 0.60
    for w in (3.0, 2.6, 2.2, 1.8):
        best = None
        for c, rot, wl, t in U.wall_spots(room, w, d, gap=0.005, step=0.05):
            sc = -wl[4] + 0.1 * min(t - w / 2, wl[4] - t - w / 2)
            if best is not None and sc >= best[0]:
                continue
            if not room.contains(c, w, d, rot, back=0.04):
                continue
            sp = rect(c, w, d, rot)
            access = rect(loc2plan(c, rot, d / 2 + 0.45, 0.0), w, 0.9, rot)
            if not U.clear([sp], 0.0, H) or not U.clear([access], 0.0, 1.8, skip_tags=('throat',)):
                continue
            if not room.contains(loc2plan(c, rot, d / 2 + 0.45, 0.0), w, 0.9, rot, inset=0.0):
                continue
            best = (sc, c, rot, sp)
        if best:
            sc, c, rot, sp = best
            if U.reach_ok(room, sp):
                return U.add(room, 'hall_wardrobe', w, d, c, rot, 0.0, H, dict(h=H), seed_of(U.num, 'hw') % 3, sp, sp)
    return None


def hall(U, room):
    if room.area < 4.0:
        return
    hall_wardrobe(U, room)
    if room.area >= 6.0:
        plant_try(U, room, ('plant_strelitzia', 'plant_monstera'), lambda r: U.corner_spots(room, r),
                  lambda c: 0.0, sizes=('M', 'S'), salt='hall')


def loggia(U, room):
    """The renders' loggia: a black A/C unit against the facade wall in the
    corner away from the door, and one big plant in a dark pot."""
    doors = [dr['centre'] for dr in room.r.get('doors') or []]
    z = 0.02
    best = None
    for c, rot, wl, t in U.wall_spots(room, 0.80, 0.30, gap=0.01, step=0.1):
        a, b, u, n, L, hole = wl
        if doors and not any(abs((dc[0] - a[0]) * n[0] + (dc[1] - a[1]) * n[1]) < 0.35 for dc in doors):
            continue                                  # the facade wall: the one the door is in
        sc = -min([dist(c, dc) for dc in doors] + [9.0])
        if best is not None and sc >= best[0]:
            continue
        if not room.contains(c, 0.80, 0.30, rot, back=0.0):
            continue
        sp = rect(c, 0.80, 0.30, rot)
        if not U.clear([sp], z, z + 0.75):
            continue
        if not U.reach_ok(room, sp):
            continue
        best = (sc, c, rot, sp)
    if best:
        sc, c, rot, sp = best
        U.add(room, 'ac_unit', 0.80, 0.30, c, rot, z, z + 0.72, dict(), 0, sp, sp, z)
    kinds = GREAT_PLANTS if seed_of(U.num, 'logp', room.id) % 2 else GREAT_PLANTS[::-1]
    plant_try(U, room, kinds, lambda r: U.corner_spots(room, r),
              lambda c: -min([dist(c, dc) for dc in doors] + [9]), sizes=('M', 'S'), salt='logtree', z=z)


def bathroom(U, room, washer_left):
    """A towel rail by the shower, the wc's roll holder and a cabinet over
    it, the flat's washing machine. No mat, plant or basket (the renders)."""
    fixtures = [p for p in U.pieces_in(room.id) if p['kind'] in ('bath', 'shower', 'shower_corner', 'bath_corner')]
    wcs = U.pieces_in(room.id, 'wc')
    basins = U.pieces_in(room.id, 'basin')
    seed = seed_of(U.num, 'bath', room.id) % 3
    for wc in wcs:
        w, d = wc['box']['size']
        for side in ((1, -1) if seed % 2 else (-1, 1)):
            c = loc2plan(wc['at'], wc['rot'], -d / 2 + 0.08, side * (w / 2 + 0.22))
            if U.try_place(room, 'wc_set', 0.30, 0.16, c, wc['rot'], 0.0, 0.85, dict(), 0, back=0.03,
                           skip_tags=('window',)):
                break
        c = loc2plan(wc['at'], wc['rot'], -d / 2 + 0.09, 0.0)
        if U.pieces_by_kind('wall_cabinet'):
            continue
        U.try_place(room, 'wall_cabinet', 0.60, 0.18, c, wc['rot'], 1.42, 2.04, dict(z0=1.44, h=0.6), seed,
                    back=0.03, ignore=(wc['node'],), inset=0.0)
    tgt = fixtures[0]['at'] if fixtures else (basins[0]['at'] if basins else None)
    best = None
    for c, rot, wl, t in U.wall_spots(room, 0.5, 0.12, gap=0.005, step=0.05):
        sc = dist(c, tgt) if tgt else 0.0
        if best is not None and sc >= best[0]:
            continue
        if not room.contains(c, 0.5, 0.12, rot, back=0.03):
            continue
        if not U.clear([rect(c, 0.6, 0.14, rot)], 0.18, 1.2):
            continue
        best = (sc, c, rot)
    if best:
        sc, c, rot = best
        U.add(room, 'towel_rail', 0.5, 0.12, c, rot, 0.18, 1.2, dict(h=0.95, finish=seed % 2), seed,
              rect(c, 0.5, 0.12, rot), None)
    if washer_left[0]:
        best = None
        for c, rot, wl, t in U.wall_spots(room, 0.6, 0.6, gap=0.01, step=0.05):
            sc = min(t - 0.3, wl[4] - t - 0.3)
            if best is not None and sc >= best[0]:
                continue
            if not room.contains(c, 0.6, 0.6, rot, back=0.04):
                continue
            sp = rect(c, 0.6, 0.6, rot)
            access = rect(loc2plan(c, rot, 0.3 + 0.4, 0.0), 0.6, 0.8, rot)
            if not U.clear([sp], 0.0, 0.9) or not U.clear([access], 0.0, 0.9):
                continue
            if not U.reach_ok(room, sp):
                continue
            best = (sc, c, rot, sp)
        if best:
            sc, c, rot, sp = best
            if U.reach_ok(room, sp):
                U.add(room, 'washing_machine', 0.6, 0.6, c, rot, 0.0, 0.9, dict(), 0, sp, sp)
                washer_left[0] = False


def office(U, room):
    """An open-plan office: big plants by the windows, a few smaller ones
    between the desks and the walls, pictures and a credenza."""
    curtains(U, room)
    kinds = list(BIG_PLANTS)
    k0 = seed_of(U.num, 'obig') % len(kinds)
    kinds = kinds[k0:] + kinds[:k0]
    n_big = 1 + int(room.area // 30)
    placed = []

    def far_from_placed(c):
        return sum(max(0.0, 3.0 - dist(c, q['at'])) * 2.0 for q in placed)
    for i in range(n_big):
        p = plant_try(U, room, (kinds[i % len(kinds)], kinds[(i + 1) % len(kinds)]), lambda r: spots_free(U, room, r),
                      lambda c: near_window_score(U, room, c) + far_from_placed(c), salt='ob1%d' % i)
        if p:
            placed.append(p)
    for i in range(max(1, n_big - 1)):
        p = plant_try(U, room, ('plant_snake', 'plant_rubber') if i % 2 else ('plant_rubber', 'plant_snake'),
                      lambda r: spots_free(U, room, r), lambda c: far_from_placed(c) - 0.2 * near_window_score(U, room, c),
                      sizes=('L', 'M', 'S'), salt='ob2%d' % i)
        if p:
            placed.append(p)
    arts = []
    for i in range(1 + int(room.area // 45)):
        a = wall_art(U, room, w=0.9, cz=1.5, salt='oart%d' % i,
                     score=lambda c: sum(max(0.0, 4.0 - dist(c, q['at'])) for q in arts))
        if a:
            arts.append(a)
    sideboard(U, room)
    pothos(U, room)



def dress_unit(level, num, rec, is_office, pieces, meta, ceiling):
    U = Unit(level, num, rec, is_office, pieces, meta, ceiling)
    restyle_kitchen(U)
    washer = [not is_office]
    # bathrooms: the biggest first (it gets the washing machine)
    order = sorted(U.rooms.values(), key=lambda r: (r.kind not in LIVING, r.kind not in BATH, -r.area))
    for room in order:
        k = room.kind
        if k in LIVING:
            living(U, room)
            if k == 'studio':
                for bed in U.pieces_in(room.id, 'bed_double'):
                    dress_bed(U, bed)
        elif k == 'bedroom':
            bedroom(U, room)
        elif k in BATH:
            bathroom(U, room, washer)
        elif k in ('balcony', 'loggia'):
            loggia(U, room)
        elif k == 'office':
            office(U, room)
        elif k in ('hall', 'corridor'):
            hall(U, room)
    for p in U.added:
        p.pop('_bounds', None)
    for p in pieces:
        p.pop('_bounds', None)
    return [p for p in pieces if p['node'] not in U.removed] + U.added
