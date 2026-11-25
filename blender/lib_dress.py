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
for _k in ('plant_monstera', 'plant_fiddle', 'plant_rubber', 'plant_snake', 'plant_palm', 'plant_olive'):
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
        return [p for p in self.pieces + self.added if p['room'] == rid and (kind is None or p['kind'] == kind)]

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
        mine = room.paint(poly)
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
            sp = room.spot(room._raw | room.paint(poly, R=0.001))
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


def rug_under_sofa(U, room, sofa):
    s_rot = sofa['rot']
    sw, sd = sofa['box']['size']
    cts = [p for p in U.pieces_in(room.id, 'table_coffee')]
    x_near = sd / 2 - 0.30
    x_far = x_near + 1.6
    yc = 0.0
    if cts:
        ct = min(cts, key=lambda p: dist(p['at'], sofa['at']))
        lx, ly = LF.to_local(ct['at'], sofa['at'], s_rot)
        cw, cd = ct['box']['size']
        if 0.0 < lx < 2.6 and abs(ly) < sw / 2:
            x_far = max(x_far, lx + max(cw, cd) / 2 * 0.6 + 0.45)
    for rw in (sw + 0.4, sw + 0.2, sw):
        for rd in (x_far - x_near, x_far - x_near - 0.2, 1.4, 1.2):
            rw2 = round(min(3.0, max(1.4, rw)) * 10) / 10
            rd2 = round(min(2.4, max(1.2, rd)) * 10) / 10
            for shift in (0.0, -0.1, 0.1, -0.2):
                cx = x_near + rd2 / 2 + shift
                c = loc2plan(sofa['at'], s_rot, cx, yc)
                p = U.try_place(room, 'rug', rw2, rd2, c, s_rot, 0.0, 0.015, dict(border=1), seed_of(U.num, 'rug') % 2,
                                rug=True, inset=0.05)
                if p:
                    return p
    return None


def floor_lamp(U, room, sofa):
    sw, sd = sofa['box']['size']
    order = (1, -1) if seed_of(U.num, 'lamp') % 2 else (-1, 1)
    for side in order:
        for dx in (0.22, 0.35, 0.10):
            c = loc2plan(sofa['at'], sofa['rot'], -sd / 2 + dx, side * (sw / 2 + 0.26))
            p = U.try_place(room, 'floor_lamp', 0.40, 0.40, c, sofa['rot'], 0.0, 1.65, dict(), 0, inset=0.0,
                            skip_tags=('window',))
            if p:
                return p
    return None


def armchair(U, room, sofa):
    if room.area < 21.0:
        return None
    cts = U.pieces_in(room.id, 'table_coffee')
    if not cts:
        return None
    ct = min(cts, key=lambda p: dist(p['at'], sofa['at']))
    lx, ly = LF.to_local(ct['at'], sofa['at'], sofa['rot'])
    if not (0.2 < lx < 2.2):
        return None
    cw = ct['box']['size'][0]
    sw = sofa['box']['size'][0]
    order = (1, -1) if seed_of(U.num, 'arm') % 2 else (-1, 1)
    for side in order:
        for off in (0.62, 0.72):
            y = side * max(cw / 2 + off, sw / 2 - 0.25)
            c = loc2plan(sofa['at'], sofa['rot'], lx + 0.05, y)
            v = (ct['at'][0] - c[0], ct['at'][1] - c[1])
            rot = heading(v)
            rot = rot - side * 0.0
            sp = rect(c, 0.82, 0.84, rot)
            front = rect(loc2plan(c, rot, 0.62, 0.0), 0.6, 0.4, rot)
            p = U.try_place(room, 'armchair', 0.82, 0.84, c, rot, 0.0, 0.9, dict(), seed_of(U.num, 'armc') % 2,
                            solid_poly=sp, inset=0.0)
            if p:
                return p
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
        tv['params']['console_w'] = cw
        tv['cls'] = '%s_c%03d' % (tv['cls'], round(cw * 100))
        tv['box'] = dict(centre=[round(c[0], 4), round(c[1], 4)], size=[cw, cd], heading=tv['box'].get('heading', tv['rot']))
        tv.pop('_bounds', None)
        for ob in U.obs:
            if ob.piece is tv:
                ob.poly = rect(c, cw + 0.04, cd + 0.04, tv['rot'])
        return True
    # no wall for a console: the screen on the wall over a slim shelf
    cw, cd = max(1.0, round(w + 0.1, 2)), 0.32
    tv['params']['console_w'] = cw
    tv['params']['console_d'] = cd
    tv['cls'] = '%s_cw' % tv['cls']
    c = (tv['at'][0] + f[0] * (cd - d) / 2, tv['at'][1] + f[1] * (cd - d) / 2)
    tv['box'] = dict(centre=[round(c[0], 4), round(c[1], 4)], size=[cw, cd], heading=tv['box'].get('heading', tv['rot']))
    tv.pop('_bounds', None)
    for ob in U.obs:
        if ob.piece is tv:
            ob.poly = rect(c, cw + 0.04, cd + 0.04, tv['rot'])
    return False


def herbs_on_run(U, room):
    """Basil, rosemary and chives at the back of the worktop, clear of the
    sink and the hob (and of a strip where the run steps round a column)."""
    legs = U.pieces_in(room.id, 'kitchen_run')
    if not legs:
        return None
    for leg in sorted(legs, key=lambda p: -p['params']['w']):
        P = leg['params']
        W, D = P['w'], P['d']
        prof = P.get('profile')
        busy = [P[k] for k in ('sink_y', 'hob_y') if k in P]

        def full(y0, y1):
            if not prof:
                return True
            return any(a <= y0 + 1e-3 and b >= y1 - 1e-3 and dep >= D - 0.03 for a, b, dep in prof)
        best = None
        for k in range(-40, 41):
            y = k * 0.05
            if abs(y) > W / 2 - 0.25:
                continue
            if any(abs(y - b) < 0.42 for b in busy):
                continue
            if not full(y - 0.24, y + 0.24):
                continue
            sc = -min([abs(y - b) for b in busy] + [9.0]) + 0.1 * abs(y)
            if best is None or sc < best[0]:
                best = (sc, y)
        if best is None:
            continue
        x = -D / 2 + 0.17
        c = loc2plan(leg['at'], leg['rot'], x, best[1])
        return U.add(room, 'plant_herbs', 0.42, 0.14, c, leg['rot'], 0.90, 1.30, dict(tray=1),
                     seed_of(U.num, 'herbs') % 3, rect(c, 0.42, 0.14, leg['rot']), None, z=0.90)
    return None


def fridge(U, room):
    legs = U.pieces_in(room.id, 'kitchen_run')
    if not legs:
        return None
    for leg in sorted(legs, key=lambda p: -p['params']['w']):
        P = leg['params']
        W, D = P['w'], P['d']
        if P.get('profile'):
            continue
        for side in (1, -1):
            c = loc2plan(leg['at'], leg['rot'], 0.0, side * (W / 2 + 0.31))
            # built in: a wall right beyond its far side
            far = loc2plan(leg['at'], leg['rot'], 0.0, side * (W / 2 + 0.62 + 0.06))
            if pip([far[0]], [far[1]], room.rings)[0]:
                continue
            sp = rect(c, 0.60, D, leg['rot'])
            access = rect(loc2plan(c, leg['rot'], D / 2 + 0.4, 0.0), 0.6, 0.8, leg['rot'])
            if not room.contains(c, 0.60, D, leg['rot'], back=0.04):
                continue
            if not U.clear([sp], 0.0, 2.25) or not U.clear([access], 0.0, 1.5):
                continue
            if not U.reach_ok(room, sp):
                continue
            return U.add(room, 'fridge_tower', 0.60, D, c, leg['rot'], 0.0, 2.25,
                         dict(hand=side), 0, sp, sp)
    return None


def dining(U, room):
    out = []
    for t in U.pieces_in(room.id, 'table_round'):
        dia = t['params']['dia']
        c = t['at']
        out.append(U.add(room, 'pendant', 0.42, 0.42, c, 0.0, 1.45, U.ceiling,
                         dict(ceiling=U.ceiling, drop=1.55), 0, rect(c, 0.42, 0.42, 0.0), None))
        what = pick(U.num, 'dine', ('decor_bowl', 'decor_table_plant', 'decor_vase'))
        spec = LF.KIT[what].KINDS[what]
        w, d, extra = spec['sizes']['M']
        out.append(U.add(room, what, w, d, c, t['rot'], 0.75, 1.3, dict(extra), seed_of(U.num, 'dine2') % 3,
                         rect(c, w, d, t['rot']), None, z=0.75))
    return out


def rug_bed(U, room, bed):
    bw, bd = bed['box']['size']
    for rw in (bw + 0.8, bw + 0.6, bw + 0.4):
        for rd in (1.8, 1.6, 1.4):
            for shift in (0.45, 0.35, 0.55):
                c = loc2plan(bed['at'], bed['rot'], shift, 0.0)
                rw2 = round(rw * 10) / 10
                p = U.try_place(room, 'rug_bedroom', rw2, rd, c, bed['rot'], 0.0, 0.013, dict(),
                                0, rug=True, inset=0.05)
                if p:
                    return p
    return None


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


def bathroom(U, room, washer_left):
    fixtures = [p for p in U.pieces_in(room.id) if p['kind'] in ('bath', 'shower', 'shower_corner', 'bath_corner')]
    wcs = U.pieces_in(room.id, 'wc')
    basins = U.pieces_in(room.id, 'basin')
    seed = seed_of(U.num, 'bath', room.id) % 3
    # the mat
    placed = False
    for fx in fixtures + basins:
        b = fx['box']
        if b.get('axis_aligned'):
            sx, sy = b['size']
            R = min(sx, sy)
            dd = 0.29 * R + 0.30
            for dd2 in (dd, dd + 0.08):
                c = (b['centre'][0] + fwd(b['heading'])[0] * dd2, b['centre'][1] + fwd(b['heading'])[1] * dd2)
                p = U.try_place(room, 'bath_mat', 0.70, 0.45, c, b['heading'], 0.0, 0.016, dict(), seed,
                                rug=True, inset=0.03, ignore=(fx['node'],))
                if p:
                    placed = True
                    break
        else:
            w, d = b['size']
            ys = [0.0]
            if fx['kind'] == 'shower':
                ys = [w / 2 - 0.45, 0.0]
            ys = ys + [w / 4, -w / 4]
            for y in ys:
                for mw in (0.8, 0.6, 0.5):
                    c = loc2plan(fx['at'], fx['rot'], d / 2 + 0.25, y)
                    p = U.try_place(room, 'bath_mat', mw, 0.45, c, fx['rot'], 0.0, 0.016, dict(), seed,
                                    rug=True, inset=0.03, ignore=(fx['node'],))
                    if p:
                        placed = True
                        break
                if placed:
                    break
        if placed:
            break
    # the wc's roll holder and the cabinet over it
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
    # a towel rail by the bath / shower
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
    # a washing machine: one a flat
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
            # its reach test was on a copy: run it again, it is cheap
            if U.reach_ok(room, sp):
                U.add(room, 'washing_machine', 0.6, 0.6, c, rot, 0.0, 0.9, dict(), 0, sp, sp)
                washer_left[0] = False

    # a plant and a basket in the corners
    tgt2 = basins[0]['at'] if basins else None

    def corners(r):
        return U.corner_spots(room, r)
    p = None
    for kind, w in (('bath_plant', 0.35), ('bath_plant', 0.28)):
        for c, rot in sorted(corners(w / 2), key=lambda t: dist(t[0], tgt2) if tgt2 else 0):
            sp = rect(c, 0.22, 0.22, rot)
            p = U.try_place(room, 'bath_plant', w, w, c, rot, 0.0, 0.85, dict(species=seed % 2, pot=(seed // 2) % 2),
                            seed, solid_poly=sp, inset=0.0)
            if p:
                break
        if p:
            break
    if room.area > 4.5:
        for c, rot in corners(0.2):
            sp = rect(c, 0.40, 0.40, rot)
            if U.try_place(room, 'laundry_basket', 0.40, 0.40, c, rot, 0.0, 0.6, dict(), 0, solid_poly=sp, inset=0.0):
                break


def loggia(U, room):
    """A planter along the balustrade (the side away from the doors) and a
    pair of pots or a tree in a corner."""
    doors = [dr['centre'] for dr in room.r.get('doors') or []]
    z = 0.02
    seed = seed_of(U.num, 'loggia', room.id) % 3
    # planters along the balustrade: one, and one more for every 3 m past
    # the first 2 m of it (a long loggia is not one trough at one end)
    rail = max([wl[4] for wl in room.walls
                if not any(abs((dc[0] - wl[0][0]) * wl[3][0] + (dc[1] - wl[0][1]) * wl[3][1]) < 0.35 for dc in doors)]
               or [0.0])
    n_pl = 1 + max(0, int((rail - 2.0) // 3.0))
    planters = []
    for k in range(n_pl):
        for size in ('M', 'S'):
            w, d, extra = LF.KIT['planter_balcony'].KINDS['planter_balcony']['sizes'][size]
            best = None
            for c, rot, wl, t in U.wall_spots(room, w, d, gap=0.10, step=0.1):
                a, b, u, n, L, hole = wl
                # the balustrade: no door on this edge
                if any(abs((dc[0] - a[0]) * n[0] + (dc[1] - a[1]) * n[1]) < 0.35 for dc in doors):
                    continue
                # the first at the far end from the doors, the next ones spread out
                sc = -L - (min(dist(c, dc) for dc in doors) * 0.3 if doors else 0.0)
                if planters:
                    near = min(dist(c, q) for q in planters)
                    if near < 1.6:
                        continue
                    sc = -L - min(near, 3.5)
                if best is not None and sc >= best[0]:
                    continue
                if not room.contains(c, w, d, rot, back=0.0):
                    continue
                sp = rect(c, w, d, rot)
                if not U.clear([sp], z, z + 0.9):
                    continue
                if not U.reach_ok(room, sp):
                    continue
                best = (sc, c, rot, sp)
            if best:
                sc, c, rot, sp = best
                if U.reach_ok(room, sp):
                    if U.add(room, 'planter_balcony', w, d, c, rot, z, z + 0.9, dict(extra), (seed + k) % 3, sp, sp, z):
                        planters.append(c)
                        break
    # pots: a pair on a short wall, else a tree in a corner
    kind = pick(U.num, 'pots' + room.id, ('plant_loggia_pair', 'plant_loggia_pair', 'plant_olive'))
    if kind == 'plant_loggia_pair':
        for size in ('M', 'S'):
            w, d, extra = LF.KIT[kind].KINDS[kind]['sizes'][size]
            ok = False
            for c, rot, wl, t in sorted(U.wall_spots(room, w, d, gap=0.10, step=0.1), key=lambda s: s[2][4]):
                if not room.contains(c, w, d, rot, back=0.0):
                    continue
                yy = max(d / 2 + 0.04, min(w / 4, w / 2 - d / 2))
                pots = [rect(loc2plan(c, rot, 0.0, s * yy), d, d, rot) for s in (1, -1)]
                h = extra.get('pot_h', 0.55) + extra.get('plant_h', 0.9)
                if not U.clear(pots, z, z + h):
                    continue
                sp = rect(c, w, d, rot)
                if not U.reach_ok(room, sp):
                    continue
                U.add(room, kind, w, d, c, rot, z, z + h, dict(extra, species=seed % 2), seed, sp, sp, z)
                ok = True
                break
            if ok:
                return
        kind = 'plant_olive'
    plant_try(U, room, (kind, 'plant_snake'), lambda r: U.corner_spots(room, r),
              lambda c: min([dist(c, dc) for dc in doors] + [9]) * -1, sizes=('M', 'S'), salt='logtree', z=z)


def living(U, room):
    sofas = U.pieces_in(room.id, 'sofa')
    tvs = U.pieces_in(room.id, 'tv')
    for tv in tvs:
        tv_console(U, room, tv)
    curtains(U, room)
    sofa = max(sofas, key=lambda p: p['box']['size'][0]) if sofas else None
    if sofa:
        rug_under_sofa(U, room, sofa)
    dining(U, room)
    herbs_on_run(U, room)
    fridge(U, room)
    tables = U.pieces_in(room.id, 'table_round')
    if sofa:
        armchair(U, room, sofa)
    sideboard(U, room, near=tables[0]['at'] if tables else None)
    # the big plant, by a window, away from the kitchen
    kinds = list(BIG_PLANTS)
    k0 = seed_of(U.num, 'big') % len(kinds)
    kinds = kinds[k0:] + kinds[:k0]
    plant_try(U, room, kinds[:2], lambda r: spots_free(U, room, r),
              lambda c: near_window_score(U, room, c), salt='big')
    if sofa:
        floor_lamp(U, room, sofa)
        wall_art(U, room, over=sofa, w=min(1.0, round(sofa['box']['size'][0] * 0.45, 1)), cz=1.5, salt='art_sofa')
    # a second, smaller floor plant: by the TV, else anywhere free
    tgt = tvs[0]['at'] if tvs else (sofa['at'] if sofa else None)
    plant_try(U, room, ('plant_snake', 'plant_rubber') if seed_of(U.num, 'p2') % 2 else ('plant_rubber', 'plant_snake'),
              lambda r: spots_free(U, room, r),
              lambda c: (dist(c, tgt) if tgt else 0) + near_window_score(U, room, c) * 0.2, sizes=('M', 'S'), salt='p2')
    # the trailing plant on a shelf, near the dining table or the TV
    pothos(U, room, prefer=tables[0]['at'] if tables else tgt)


def bedroom(U, room):
    beds = U.pieces_in(room.id, 'bed_double')
    curtains(U, room)
    for bed in beds:
        rug_bed(U, room, bed)
    wardrobe(U, room)
    kinds = ('plant_fiddle', 'plant_rubber', 'plant_snake', 'plant_monstera')
    k0 = seed_of(U.num, 'bedplant', room.id) % len(kinds)
    kinds = kinds[k0:] + kinds[:k0]
    plant_try(U, room, kinds[:2] + ('plant_snake',), lambda r: spots_free(U, room, r),
              lambda c: near_window_score(U, room, c), sizes=('M', 'S'), salt='bed' + room.id)
    for bed in beds[:1]:
        wall_art(U, room, over=bed, w=min(1.0, round(bed['box']['size'][0] * 0.5, 1)), cz=1.62, salt='art_bed')


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


def hall(U, room):
    if room.area < 4.0:
        return
    plant_try(U, room, ('plant_snake', 'plant_rubber'), lambda r: U.corner_spots(room, r),
              lambda c: 0.0, sizes=('L', 'M', 'S'), salt='hall')


def dress_unit(level, num, rec, is_office, pieces, meta, ceiling):
    U = Unit(level, num, rec, is_office, pieces, meta, ceiling)
    washer = [not is_office]
    # bathrooms: the biggest first (it gets the washing machine)
    order = sorted(U.rooms.values(), key=lambda r: (r.kind not in LIVING, r.kind not in BATH, -r.area))
    for room in order:
        k = room.kind
        if k in LIVING:
            living(U, room)
            if k == 'studio':
                for bed in U.pieces_in(room.id, 'bed_double'):
                    rug_bed(U, room, bed)
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
    return pieces + U.added
