# -*- coding: utf-8 -*-
"""The bathroom kit: procedurally modelled sanitaryware, fittings and extras.

Pure python + math (no bpy) inside build(), so it runs under Blender's python
and the system one alike. Preview / render code lives under __main__ (Blender).

    import furn_kit_bath as KB
    parts = KB.build('basin', w=0.60, d=0.45)      # -> [(material, verts, faces, smooth), ...]

LOCAL FRAME (lib_furnish.py): +X is the way the piece FACES (the side you
use it from), +Y its left, z up, metres, origin on the floor at the centre of
the footprint. `w` = size ACROSS (local Y), `d` = size ALONG the facing
direction (local X): exactly the drawn box lib_furnish hands build_furnish as
params {w, d} (w = box size[0] "across", d = size[1] "along heading"). For a
piece that stands against a wall, the wall is the plane x = -d/2 (its back).
Corner pieces (shower_corner, bath_corner) take lib_furnish's {sx, sy}:
call build(kind, w=sy, d=sx); the corner of the two walls is (-d/2, -w/2),
the walls are the planes x = -d/2 and y = -w/2, and the front bulges toward
(+X, +Y), exactly as build_furnish.quarter() draws the glyph.

Every entry is one material and one shading mode: faces are counter-clockwise
seen from outside (the page culls back faces), quads or triangles. Flat faces
(caps, tops, panel fronts) come in entries with smooth=False, curved ones in
entries with smooth=True; the two never share vertices, so even after a
weld (build_furnish's remove_doubles) Blender keeps the edge between them
sharp (an edge next to a flat face is sharp), and flat things stay flat.
Materials are only web/materials.js names; all of them are procedural and
projected in world space, so nothing here needs UVs.

Triangles per kind at the default size and default params (tri_count()):

    kind               tris   footprint w x d (m)   drawn
    wc                 1388   0.45 x 0.65            yes  (wall-hung on a pre-wall; style=1 close-coupled: 1624)
    basin              1950   0.60 x 0.45            yes  (vanity + bowl + mixer + mirror + light + shelf + plant;
                                                           mirror=0 shelf=0 plant=0: 1040)
    shower_corner      1920   0.80 x 0.80            yes  (tray + curved sliding screen + column + corner shelf;
                                                           shape=1 square: 1676 at 0.90)
    shower             1758   1.95 x 0.90            yes  (walk-in: tray, linear drain, glass, column, teak stool)
    bath               1896   1.90 x 0.75            yes  (tub, apron, wall mixer, hand shower, teak caddy)
    bath_corner        1520   1.30 x 1.30            yes  (corner tub, apron, deck spout + knobs)
    towel_rail          780   0.50 x 0.12            no   (heated ladder rail + draped towel)
    washing_machine    1134   0.60 x 0.60            no
    wc_set              588   0.30 x 0.16            no   (roll holder on the wall + brush on the floor)
    bath_mat            112   0.80 x 0.50            no
    wall_cabinet        764   0.60 x 0.18            no   (hangs at 1.35..1.95)
    laundry_basket      776   0.40 x 0.40            no
    bath_plant          450   0.35 x 0.35            no   (snake plant; species=1 leafy bush: 734)

The composite kinds (basin, the showers, bath) are several products in one
mesh; each product on its own stays inside ~1000 (the shower column ~950, the
tub ~650, the vanity + bowl ~600).

(regenerate with `python3 blender/furn_kit_bath.py --table`)
"""
import math
import random

TAU = 2.0 * math.pi

# ---------------------------------------------------------------- kinds
KINDS = {
    'wc': dict(
        drawn=True,
        params={'style': (0, 0, 1)},
        footprint='w = across (local Y, the pan width side, drawn 0.36-0.50), d = along the facing (local X, '
                  'wall -> front of the pan, drawn 0.52-0.75); the wall is x = -d/2. style 0: wall-hung pan on a '
                  'tiled pre-wall (d - 0.53 deep, 1.12 high, marble cap, chrome flush plate at 1.0); '
                  'style 1: close-coupled floor pan with ceramic cistern.',
        wall=True, solid=True,
        notes='Seat at 0.42, lid closed (no bowl interior is modelled). Pre-wall / cistern fill the back of '
              'the footprint and stand on the wall line x = -d/2.'),
    'basin': dict(
        drawn=True,
        params={'mirror': (1, 0, 1), 'shelf': (1, 0, 1), 'plant': (1, 0, 1), 'front': (0, 0, 2)},
        footprint='w = across (the vanity width, local Y, drawn 0.45-0.80), d = along the facing (vanity '
                  'depth, local X, drawn 0.33-0.55); the wall is x = -d/2.',
        wall=True, solid=True,
        notes='Wall-hung vanity 0.42..0.80, ceramic top with an integrated bowl, rim at 0.85, single-lever '
              'mixer. On the wall above (x = -d/2 .. -d/2 + 0.13): an oak ledge at 1.10, a mirror 1.12..1.80 '
              'as wide as the vanity (max 0.80) and a light bar at 1.84 - all inside the footprint in plan. '
              'front: 0 oak drawer front, 1 walnut, 2 white. plant=1 puts a small pot on the back deck.'),
    'shower_corner': dict(
        drawn=True,
        params={'shape': (0, 0, 1)},
        footprint='lib_furnish {sx, sy}: call with d = sx (local X), w = sy (local Y). The two walls are '
                  'x = -d/2 and y = -w/2 (corner at (-d/2, -w/2)); the screen bulges toward (+X, +Y). '
                  'Drawn 0.70-1.60 each.',
        wall=True, solid=True,
        notes='shape 0: offset-quadrant tray (R <= 0.55) with two curved sliding doors; shape 1: square tray, '
              'corner entry. Shower column (thermostat bar 1.10, rain head 2.0) on the wall x = -d/2; corner '
              'shelf at 1.30. Needs both walls: it is placed by lib_furnish onto the drawn corner.'),
    'shower': dict(
        drawn=True,
        params={'tray': (0, 0, 1), 'stool': (1, 0, 1)},
        footprint='w = across (along the back wall, drawn 0.70-2.20), d = along the facing (out of the back '
                  'wall, drawn 0.70-1.40); the back wall is x = -d/2.',
        wall=True, solid=False,
        notes='Walk-in: low tray (tray 0 dark stone, 1 white), linear drain by the back wall, one fixed glass '
              'panel on the front edge from y = -w/2 (length 0.55 w, 0.8..1.2) with a stabiliser rod to the '
              'back wall at 1.98, shower column on the back wall behind the glass, teak stool in the open end '
              '(stool=1, only when the open end is >= 0.7). Walkable: only the glass panel line blocks.'),
    'bath': dict(
        drawn=True,
        params={'caddy': (1, 0, 1), 'tap_end': (0, 0, 1)},
        footprint='w = across = the bath LENGTH along the wall (local Y, drawn 1.20-2.20), d = along the '
                  'facing = the bath width (local X, drawn 0.60-0.90); the long wall is x = -d/2.',
        wall=True, solid=True,
        notes='Built-in tub: white apron 0.07..0.555 over a dark recessed plinth, ceramic rim at 0.58, '
              'sloped backrest. Wall-mounted mixer at 0.78 with a telephone hand shower on the -Y end '
              '(tap_end 0) or the +Y end (1), backrest at the other end; teak caddy across the rim.'),
    'bath_corner': dict(
        drawn=True,
        params={},
        footprint='lib_furnish {sx, sy}: call with d = sx (local X), w = sy (local Y). Walls x = -d/2 and '
                  'y = -w/2, corner at (-d/2, -w/2), front arc bulging toward (+X, +Y). Drawn 1.30-1.35.',
        wall=True, solid=True,
        notes='Corner tub with a deck in the corner carrying the spout and two knobs; apron over a dark plinth.'),
    'towel_rail': dict(
        drawn=False,
        params={'h': (0.95, 0.6, 1.6), 'finish': (0, 0, 2), 'towel': (-1, -1, 3)},
        footprint='w = across (rail width, local Y, 0.40-0.70), d = along the facing (0.10-0.15: rail '
                  'stand-off + towel); the wall is x = -d/2.',
        wall=True, solid=False,
        notes='Heated ladder rail 0.20 .. 0.20+h on four wall brackets with valves; one towel draped over a '
              'bar. finish: 0 chrome, 1 white, 2 black. towel: -1 by seed, 0 white, 1 teal, 2 blue-grey, '
              '3 orange. Any free wall, also beside the shower or above the bath end.'),
    'washing_machine': dict(
        drawn=False,
        params={},
        footprint='w = across (0.60), d = along the facing (0.55-0.65, door side at +X); the wall is x = -d/2.',
        wall=True, solid=True,
        notes='0.85 high front loader: porthole door, drawer, display, dial, feet.'),
    'wc_set': dict(
        drawn=False,
        params={},
        footprint='w = across (0.25-0.40), d = along the facing (0.12-0.20); the wall is x = -d/2.',
        wall=True, solid=False,
        notes='Roll holder on the wall at 0.70 (at +Y) and a floor brush at -Y. Place beside the wc, inside '
              '0.2..0.5 m of its side.'),
    'bath_mat': dict(
        drawn=False,
        params={'color': (-1, -1, 3)},
        footprint='w = across (0.5-1.0), d = along (0.4-0.7): lay it in front of the bath / shower / basin '
                  'with its +X away from the fixture.',
        wall=False, solid=False,
        notes='14 mm pile mat. color: -1 by seed, 0 white, 1 teal, 2 blue-grey, 3 dark.'),
    'wall_cabinet': dict(
        drawn=False,
        params={'z0': (1.35, 1.1, 1.6), 'h': (0.60, 0.4, 0.8)},
        footprint='w = across (0.40-0.90), d = along (0.15-0.25); the wall is x = -d/2.',
        wall=True, solid=True,
        notes='Hangs from z0 to z0 + h: white doors with brass knobs over an open oak niche (towels, a '
              'bottle). Above a wc or a washing machine. Solid only because a body is taller than z0.'),
    'laundry_basket': dict(
        drawn=False,
        params={},
        footprint='w x d = the basket box (0.30-0.50); round, diameter min(w, d).',
        wall=False, solid=True,
        notes='Fabric hamper 0.55 high with a rolled cuff, leather handles, towels in it.'),
    'bath_plant': dict(
        drawn=False,
        params={'species': (0, 0, 1), 'pot': (0, 0, 1)},
        footprint='w x d = the plant box (0.25-0.50); the pot diameter is ~0.6 min(w, d).',
        wall=False, solid=False,
        notes='species 0: snake plant (0.75 high at 0.35); 1: leafy bush. pot 0 white glaze, 1 dark. '
              'Corners of the room, beside the bath or the basin.'),
}


# ---------------------------------------------------------------- small vector maths
def v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def v_mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def v_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def v_cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def v_len(a):
    return math.sqrt(v_dot(a, a))


def v_norm(a):
    l = v_len(a) or 1e-12
    return (a[0] / l, a[1] / l, a[2] / l)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# affine 3x4: (R rows, t)
IDENT = (((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), (0.0, 0.0, 0.0))


def m_apply(M, p):
    R, t = M
    return (R[0][0] * p[0] + R[0][1] * p[1] + R[0][2] * p[2] + t[0],
            R[1][0] * p[0] + R[1][1] * p[1] + R[1][2] * p[2] + t[1],
            R[2][0] * p[0] + R[2][1] * p[1] + R[2][2] * p[2] + t[2])


def m_mul(A, B):
    """A after B."""
    Ra, ta = A
    Rb, tb = B
    R = tuple(tuple(sum(Ra[i][k] * Rb[k][j] for k in range(3)) for j in range(3)) for i in range(3))
    t = m_apply(A, tb)
    return (R, t)


def m_det(M):
    R = M[0]
    return (R[0][0] * (R[1][1] * R[2][2] - R[1][2] * R[2][1]) - R[0][1] * (R[1][0] * R[2][2] - R[1][2] * R[2][0])
            + R[0][2] * (R[1][0] * R[2][1] - R[1][1] * R[2][0]))


def m_t(x, y, z):
    return (IDENT[0], (x, y, z))


def m_rz(a, t=(0.0, 0.0, 0.0)):
    c, s = math.cos(a), math.sin(a)
    return (((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0)), t)


def m_ry(a, t=(0.0, 0.0, 0.0)):
    c, s = math.cos(a), math.sin(a)
    return (((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c)), t)


def m_wall(x, y, z, facing=1.0):
    """A frame lying on a wall plane x = const: local (u, v, n) -> world
    (Y, Z, X): something built flat in z-up (a slab, a plate) stands on the
    wall facing +X."""
    if facing > 0:
        return (((0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (x, y, z))
    return (((0.0, 0.0, -1.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), (x, y, z))


# ---------------------------------------------------------------- the accumulator
class Kit:
    """Per-material vertex / face lists; every face carries its own smooth
    flag. A transform stack places sub-assemblies."""

    def __init__(self):
        self.parts = {}
        self.stack = [IDENT]

    def push(self, M):
        self.stack.append(m_mul(self.stack[-1], M))

    def pop(self):
        self.stack.pop()

    def part(self, mat):
        if mat not in self.parts:
            self.parts[mat] = ([], [], [])
        return self.parts[mat]

    def verts(self, mat, pts):
        V = self.part(mat)[0]
        o = len(V)
        M = self.stack[-1]
        V.extend(m_apply(M, p) for p in pts)
        return o

    def face(self, mat, idx, smooth):
        P = self.part(mat)
        if m_det(self.stack[-1]) < 0:
            idx = tuple(reversed(idx))
        P[1].append(tuple(idx))
        P[2].append(bool(smooth))

    def out(self):
        res = []
        for mat in sorted(self.parts):
            V, F, S = self.parts[mat]
            for sm in (False, True):
                fs = [f for f, s in zip(F, S) if s == sm]
                if not fs:
                    continue
                remap = {}
                vv = []
                ff = []
                for f in fs:
                    g = []
                    for i in f:
                        if i not in remap:
                            remap[i] = len(vv)
                            p = V[i]
                            vv.append((round(p[0], 6), round(p[1], 6), round(p[2], 6)))
                        g.append(remap[i])
                    ff.append(tuple(g))
                res.append((mat, vv, ff, sm))
        return res


class at:
    """with at(k, M): ... builds under the transform M."""

    def __init__(self, k, M):
        self.k, self.M = k, M

    def __enter__(self):
        self.k.push(self.M)
        return self.k

    def __exit__(self, *a):
        self.k.pop()


# ---------------------------------------------------------------- primitives
def loft(k, mat, rings, smooth=True, cap0=False, cap1=False, closed=True):
    """Rings of equal length (or single-point poles) joined in order. A ring
    counter-clockwise about the direction of travel gives outward faces on
    the side to the right of travel ... in practice: rings CCW seen from +z,
    travelling up the outside of a solid = outward. caps: flat fans."""
    base = [k.verts(mat, r) for r in rings]
    for i in range(len(rings) - 1):
        A, B = rings[i], rings[i + 1]
        a, b = base[i], base[i + 1]
        sm = smooth[i] if isinstance(smooth, (list, tuple)) else smooth
        if len(A) == 1 and len(B) == 1:
            continue
        m = len(B) if len(A) == 1 else len(A)
        for j in range(m if closed else m - 1):
            jn = (j + 1) % m
            if len(A) == 1:
                k.face(mat, (a, b + jn, b + j), sm)
            elif len(B) == 1:
                k.face(mat, (a + j, a + jn, b), sm)
            else:
                k.face(mat, (a + j, a + jn, b + jn, b + j), sm)
    for flag, ring, o, rev in ((cap0, rings[0], base[0], True), (cap1, rings[-1], base[-1], False)):
        if not flag or len(ring) < 3:
            continue
        n = len(ring)
        c = (sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n, sum(p[2] for p in ring) / n)
        ci = k.verts(mat, [c])
        k.stack.append(k.stack[-1])
        for j in range(n):
            jn = (j + 1) % n
            k.face(mat, (ci, o + jn, o + j) if rev else (ci, o + j, o + jn), False)
        k.stack.pop()


def ring3(pts, z):
    return [(x, y, z) for x, y in pts]


def rpoly(keys, sup=0.0):
    """Polygon with filleted corners. keys: (x, y, r, seg), CCW. seg = 0:
    the point as it is. sup > 0: a support point that far outside each
    fillet along both edges (keeps the straight faces flat under smooth
    shading). The point count depends only on segs and sup."""
    n = len(keys)
    out = []
    for i in range(n):
        x, y, r, seg = keys[i]
        if seg <= 0:
            out.append((x, y))
            continue
        px, py = keys[i - 1][0], keys[i - 1][1]
        qx, qy = keys[(i + 1) % n][0], keys[(i + 1) % n][1]
        ax, ay = px - x, py - y
        bx, by = qx - x, qy - y
        la = math.hypot(ax, ay) or 1e-9
        lb = math.hypot(bx, by) or 1e-9
        ax, ay, bx, by = ax / la, ay / la, bx / lb, by / lb
        ang = math.acos(clamp(ax * bx + ay * by, -1.0, 1.0))
        half = ang / 2.0
        cnt = seg + 1 + (2 if sup > 0 else 0)
        if half < 1e-3 or abs(half - math.pi / 2) < 1e-3 or r <= 1e-6:
            # straight through (or no radius): spread the points a hair
            for s in range(cnt):
                f = (s / (cnt - 1) - 0.5) * 2e-4 if cnt > 1 else 0.0
                out.append((x - ax * f if f < 0 else x + bx * f, y - ay * f if f < 0 else y + by * f))
            continue
        t = r / math.tan(half)
        lim = 0.49 * min(la, lb) - (sup if sup > 0 else 0.0)
        t = max(1e-4, min(t, lim))
        rr = t * math.tan(half)
        mx, my = ax + bx, ay + by
        ml = math.hypot(mx, my) or 1e-9
        cx = x + mx / ml * rr / math.sin(half)
        cy = y + my / ml * rr / math.sin(half)
        t1 = (x + ax * t, y + ay * t)
        t2 = (x + bx * t, y + by * t)
        a1 = math.atan2(t1[1] - cy, t1[0] - cx)
        a2 = math.atan2(t2[1] - cy, t2[0] - cx)
        sw = a2 - a1
        while sw > math.pi:
            sw -= TAU
        while sw <= -math.pi:
            sw += TAU
        if sup > 0:
            out.append((x + ax * (t + sup), y + ay * (t + sup)))
        for s in range(seg + 1):
            a = a1 + sw * s / seg
            out.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        if sup > 0:
            out.append((x + bx * (t + sup), y + by * (t + sup)))
    return out


def rrect(xa, xb, ya, yb, r, seg=3, sup=0.0, rs=None):
    """Rounded rectangle, CCW from above. rs: per-corner radii
    (+x-y, +x+y, -x+y, -x-y)."""
    rs = rs or (r, r, r, r)
    return rpoly([(xb, ya, rs[0], seg), (xb, yb, rs[1], seg), (xa, yb, rs[2], seg), (xa, ya, rs[3], seg)], sup)


def centroid2(pts):
    n = len(pts)
    return (sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n)


def slab(k, mat, ringfn, z0, z1, rb=0.0, bseg=2, sup=0.002, side_smooth=True, bev_smooth=True,
         cap0=True, cap1=True, dome=0.0, bot_bevel=True, top_bevel=True):
    """A solid standing z0..z1 whose plan is ringfn(inset) (CCW 2-D points,
    same count for every inset), its edges rounded by rb. dome > 0 lifts the
    middle of the top (a lid, a cushion)."""
    prof = []                            # (inset, z, smooth of the band below)
    if rb > 0 and bot_bevel:
        for s in range(bseg + 1):
            th = (math.pi / 2) * s / bseg
            prof.append((rb * (1 - math.sin(th)), z0 + rb * (1 - math.cos(th)), bev_smooth))
        zs0 = z0 + rb
    else:
        prof.append((0.0, z0, side_smooth))
        zs0 = z0
    zs1 = z1 - rb if (rb > 0 and top_bevel) else z1
    if sup > 0 and rb > 0 and zs1 - zs0 > 3 * sup:
        if bot_bevel:
            prof.append((0.0, zs0 + sup, True))
        if top_bevel:
            prof.append((0.0, zs1 - sup, side_smooth))
            prof.append((0.0, zs1, True))
        else:
            prof.append((0.0, zs1, side_smooth))
    else:
        prof.append((0.0, zs1, side_smooth))
    if rb > 0 and top_bevel:
        for s in range(1, bseg + 1):
            th = (math.pi / 2) * s / bseg
            prof.append((rb * (1 - math.cos(th)), zs1 + rb * math.sin(th), bev_smooth))
    rings = []
    sm = []
    for j, (ins, z, s) in enumerate(prof):
        rings.append(ring3(ringfn(ins), z))
        if j > 0:
            sm.append(s)
    if dome > 0 and cap1:
        top = rings[-1]
        c = centroid2([(p[0], p[1]) for p in top])
        # a two-step dome: a ring a third of the way in, then the pole
        mid = [(p[0] + (c[0] - p[0]) * 0.45, p[1] + (c[1] - p[1]) * 0.45, p[2] + dome * 0.75) for p in top]
        rings.append(mid)
        sm.append(True)
        rings.append([(c[0], c[1], z1 + dome)])
        sm.append(True)
        loft(k, mat, rings, sm, cap0=cap0, cap1=False)
    else:
        loft(k, mat, rings, sm, cap0=cap0, cap1=cap1)


def boxr(k, mat, p0, p1, rb=0.0, bseg=1, smooth=False, sup=0.0, cap0=True, cap1=True):
    """Axis box, optionally with rounded / chamfered edges (rb)."""
    x0, y0, z0 = p0
    x1, y1, z1 = p1
    if rb <= 0:
        slab(k, mat, lambda i: [(x1, y0), (x1, y1), (x0, y1), (x0, y0)], z0, z1, 0.0, side_smooth=False,
             cap0=cap0, cap1=cap1)
        return
    rb = min(rb, (x1 - x0) / 2.01, (y1 - y0) / 2.01, (z1 - z0) / 2.01)
    seg = bseg
    slab(k, mat, lambda i: rrect(x0 + i, x1 - i, y0 + i, y1 - i, max(1e-4, rb - i), seg, sup), z0, z1, rb,
         bseg, sup=sup, side_smooth=smooth, bev_smooth=smooth, cap0=cap0, cap1=cap1)


def basis(axis):
    a = v_norm(axis)
    h = (0.0, 0.0, 1.0) if abs(a[2]) < 0.9 else (1.0, 0.0, 0.0)
    u = v_norm(v_cross(a, h))
    v = v_cross(a, u)
    return a, u, v


def lathe(k, mat, prof, seg=16, o=(0.0, 0.0, 0.0), axis=(0.0, 0.0, 1.0), smooth=True, closed=False,
          cap0=False, cap1=False, phase=0.0):
    """Profile [(r, h)] turned about `axis` through `o`; r = 0 is a pole.
    Going +h along the outside gives outward faces."""
    a, u, v = basis(axis)
    rings = []
    for r, h in prof:
        c = v_add(o, v_mul(a, h))
        if r < 1e-7:
            rings.append([c])
        else:
            rings.append([v_add(c, v_add(v_mul(u, r * math.cos(phase + TAU * j / seg)),
                                         v_mul(v, r * math.sin(phase + TAU * j / seg)))) for j in range(seg)])
    if closed:
        rings.append(rings[0])
        if isinstance(smooth, (list, tuple)):
            smooth = list(smooth) + [smooth[-1]]
    loft(k, mat, rings, smooth, cap0=cap0, cap1=cap1)


def frames(path, up=None):
    """Rotation-minimising frames along a polyline; up: a fixed side vector
    for planar paths."""
    n = len(path)
    T = []
    for i in range(n):
        if i == 0:
            t = v_sub(path[1], path[0])
        elif i == n - 1:
            t = v_sub(path[-1], path[-2])
        else:
            t = v_add(v_norm(v_sub(path[i], path[i - 1])), v_norm(v_sub(path[i + 1], path[i])))
        T.append(v_norm(t))
    F = []
    if up is not None:
        for t in T:
            b = v_norm(v_sub(up, v_mul(t, v_dot(up, t))))
            nrm = v_cross(b, t)
            F.append((nrm, b))
        return T, F
    t0 = T[0]
    h = (0.0, 0.0, 1.0) if abs(t0[2]) < 0.9 else (1.0, 0.0, 0.0)
    N = v_norm(v_cross(t0, h))
    for t in T:
        N = v_norm(v_sub(N, v_mul(t, v_dot(N, t))))
        F.append((N, v_cross(t, N)))
    return T, F


def sweep(k, mat, path, section, up=None, scale=None, smooth=True, cap0=True, cap1=True, closed=False):
    """Section [(a, b)] (CCW) carried along the path in the (N, B) frame."""
    T, F = frames(path, up)
    rings = []
    n = len(path)
    for i, p in enumerate(path):
        N, B = F[i]
        s = scale[i] if scale else 1.0
        # mitre: keep the tube's thickness through a bend
        if 0 < i < n - 1:
            d1 = v_norm(v_sub(path[i], path[i - 1]))
            c = v_dot(d1, T[i])
            s = s / max(0.55, c)
        rings.append([v_add(p, v_add(v_mul(N, a * s), v_mul(B, b * s))) for a, b in section])
    if closed:
        rings.append(rings[0])
    loft(k, mat, rings, smooth, cap0=cap0 and not closed, cap1=cap1 and not closed)


def circle2(r, seg, phase=0.0):
    return [(r * math.cos(phase + TAU * j / seg), r * math.sin(phase + TAU * j / seg)) for j in range(seg)]


def tube(k, mat, path, r, seg=8, cap0=True, cap1=True, smooth=True, closed=False, rs=None):
    sweep(k, mat, path, circle2(r, seg), scale=[x / r for x in rs] if rs else None, smooth=smooth,
          cap0=cap0, cap1=cap1, closed=closed)


def catmull(pts, n):
    """Catmull-Rom through pts, n samples."""
    out = []
    m = len(pts) - 1
    for s in range(n):
        u = s / (n - 1) * m
        i = min(int(u), m - 1)
        t = u - i
        p0 = pts[max(i - 1, 0)]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[min(i + 2, m)]
        out.append(tuple(0.5 * ((2 * p1[c]) + (-p0[c] + p2[c]) * t + (2 * p0[c] - 5 * p1[c] + 4 * p2[c] - p3[c]) * t * t
                                + (-p0[c] + 3 * p1[c] - 3 * p2[c] + p3[c]) * t * t * t) for c in range(3)))
    return out


def strip(k, mat, path2d, z0, z1, smooth=False):
    """A vertical sheet along a plan polyline (glass)."""
    lo = [(x, y, z0) for x, y in path2d]
    hi = [(x, y, z1) for x, y in path2d]
    loft(k, mat, [lo, hi], smooth, closed=False)


def leaf(k, mat, base, direction, face, length, width, nseg=4, droop=0.0, fold=0.15, twist=0.0,
         shape='lance', smooth=True):
    """One leaf card: a spine from base along `direction` bending down by
    droop, a V fold, width tapering to a point. The front (frontFacing in
    the page's leaf material) looks along `face`."""
    d = v_norm(direction)
    pts = [base]
    p = base
    seglen = length / nseg
    for s in range(1, nseg + 1):
        t = s / nseg
        dd = v_norm(v_add(d, (0.0, 0.0, -droop * t * t * 2.0)))
        p = v_add(p, v_mul(dd, seglen))
        pts.append(p)
    L, M, R = [], [], []
    for s, sp in enumerate(pts):
        t = s / nseg
        if s < nseg:
            tg = v_norm(v_sub(pts[s + 1], sp))
        else:
            tg = v_norm(v_sub(sp, pts[s - 1]))
        f = v_norm(v_sub(face, v_mul(tg, v_dot(face, tg))))
        side = v_norm(v_cross(f, tg))
        tw = twist * t
        side, f = (v_add(v_mul(side, math.cos(tw)), v_mul(f, math.sin(tw))),
                   v_add(v_mul(f, math.cos(tw)), v_mul(side, -math.sin(tw))))
        if shape == 'lance':
            wv = width * (math.sin(math.pi * min(1.0, 0.12 + t * 0.95)) ** 0.7) * (0.55 + 0.45 * (1 - t * 0.3))
        else:                                   # broad oval with a drawn-out point
            wv = width * (math.sin(math.pi * min(1.0, t * 0.92 + 0.04)) ** 0.5) * (1.0 - 0.35 * t * t)
        if s == 0:
            wv = width * (0.18 if shape == 'lance' else 0.08)
        if s == nseg:
            wv = 0.0
        hw = wv / 2.0
        L.append(v_add(sp, v_mul(side, hw)))
        R.append(v_sub(sp, v_mul(side, hw)))
        M.append(v_sub(sp, v_mul(f, fold * hw)))
    rows = [k.verts(mat, [L[i], M[i], R[i]]) for i in range(nseg + 1)]
    for i in range(nseg):
        a, b = rows[i], rows[i + 1]
        # wound so the front (frontFacing) looks along `face`
        if i == nseg - 1:
            # tip: L, R, M collapse to one point
            k.face(mat, (a + 1, b + 1, a + 0), smooth)
            k.face(mat, (a + 2, b + 1, a + 1), smooth)
        else:
            k.face(mat, (a + 1, b + 1, b + 0, a + 0), smooth)
            k.face(mat, (a + 2, b + 2, b + 1, a + 1), smooth)


# ---------------------------------------------------------------- shared fittings
def mixer_basin(k, x, y, z, h=0.16, reach=0.12):
    """Single-lever basin mixer standing at (x, y, z), spout along +X."""
    C = 'chrome'
    lathe(k, C, [(0.0262, 0.0), (0.025, 0.006), (0.0185, 0.016), (0.0185, h - 0.008), (0.0125, h),
                 (0.0, h + 0.001)], seg=12, o=(x, y, z), smooth=[True, True, True, True, False])
    zs = z + h - 0.035
    tube(k, C, [(x + 0.008, y, zs), (x + 0.05, y, zs + 0.006), (x + reach - 0.03, y, zs + 0.004),
                (x + reach - 0.008, y, zs - 0.012), (x + reach, y, zs - 0.035)], 0.0085, seg=8)
    # aerator: a dark ring in the spout's mouth
    lathe(k, 'int_black', [(0.0, -0.001), (0.0062, -0.001)], seg=10, o=(x + reach, y, zs - 0.0352),
          axis=(0, 0, -1), smooth=False)
    # the lever: a short collar and a paddle pointing back, lifted 14 deg
    with at(k, m_t(x, y, z + h + 0.004)):
        with at(k, m_ry(math.radians(-24.0))):
            boxr(k, C, (-0.05, -0.0065, -0.004), (0.004, 0.0065, 0.004), rb=0.003, bseg=1, smooth=True)


def rosette(k, mat, x, y, z, r=0.022, t=0.007, axis=(1, 0, 0), seg=10):
    lathe(k, mat, [(r, 0.0), (r * 0.92, t * 0.85), (0.0, t)], seg=seg, o=(x, y, z), axis=axis,
          smooth=[True, False])


def shower_column(k, xw, y, head='round', z_bar=1.10, z_top=2.0, arm=0.30, hand_z=1.55):
    """Thermostatic shower column on the wall x = xw (into +X), centred on y:
    a thermostat bar with two knobs, the riser, an arm, the rain head, a
    hand shower in its slider and the hose looping between."""
    C = 'chrome'
    xb = xw + 0.065                              # bar axis
    # wall unions
    for dy in (-0.075, 0.075):
        rosette(k, C, xw, y + dy, z_bar, 0.024, 0.008)
        tube(k, C, [(xw + 0.006, y + dy, z_bar), (xb - 0.01, y + dy, z_bar)], 0.0105, seg=8, cap0=False, cap1=False)
    # the thermostat bar along Y, knobs at both ends
    lathe(k, C, [(0.03, -0.13), (0.03, 0.13)], seg=14, o=(xb, y, z_bar), axis=(0, 1, 0))
    for s in (-1, 1):
        o = (xb, y + s * 0.13, z_bar)
        lathe(k, C, [(0.0, 0.0), (0.032, 0.0), (0.032, 0.036), (0.027, 0.044), (0.0, 0.045)], seg=10, o=o,
              axis=(0, s, 0), smooth=[False, True, True, False])
        lathe(k, 'int_black', [(0.0327, 0.012), (0.0327, 0.024)], seg=10, o=o, axis=(0, s, 0), smooth=True)
    # riser and arm
    xr = xb
    zr0 = z_bar + 0.028
    tube(k, C, [(xr, y, zr0), (xr, y, z_top - 0.05), (xr + 0.012, y, z_top - 0.012), (xr + 0.05, y, z_top),
                (xr + arm, y, z_top)], 0.0115, seg=8, cap0=False)
    # wall bracket near the top of the riser
    rosette(k, C, xw, y, z_top - 0.22, 0.02, 0.007)
    tube(k, C, [(xw + 0.006, y, z_top - 0.22), (xr - 0.008, y, z_top - 0.22)], 0.008, seg=6, cap0=False, cap1=False)
    lathe(k, C, [(0.0145, -0.02), (0.0145, 0.02)], seg=10, o=(xr, y, z_top - 0.22))
    # the rain head, its nozzle plate a dark disc under it
    hx = xr + arm - 0.02
    zh = z_top - 0.03
    tube(k, C, [(hx, y, z_top), (hx, y, zh + 0.012)], 0.012, seg=8, cap0=False, cap1=False)
    if head == 'round':
        R = 0.12
        lathe(k, C, [(R - 0.004, 0.0), (R, 0.005), (R - 0.008, 0.013), (0.0, 0.016)], seg=20, o=(hx, y, zh),
              smooth=[True, True, False])
        lathe(k, 'int_black', [(R - 0.004, 0.0), (R - 0.016, -0.0015), (0.0, -0.0015)], seg=20, o=(hx, y, zh),
              smooth=[True, False])
    else:
        S = 0.15
        slab(k, C, lambda i: rrect(hx - S + i, hx + S - i, y - S + i, y + S - i, max(1e-3, 0.03 - i), 2), zh,
             zh + 0.012, 0.004, 1, sup=0.0)
        slab(k, 'int_black', lambda i: rrect(hx - S + 0.015 + i, hx + S - 0.015 - i, y - S + 0.015 + i,
                                             y + S - 0.015 - i, 0.02, 3), zh - 0.0015, zh, 0.0, cap1=False)
    # slider and hand shower
    lathe(k, C, [(0.0115, -0.024), (0.0175, -0.018), (0.0175, 0.018), (0.0115, 0.024)], seg=8, o=(xr, y, hand_z))
    hb = (xr + 0.035, y, hand_z - 0.11)       # handle bottom
    ht = (xr + 0.075, y, hand_z + 0.10)       # head centre
    tube(k, C, [(xr + 0.01, y, hand_z), (xr + 0.035, y, hand_z)], 0.007, seg=6, cap0=False)
    hp = [hb, v_add(hb, (0.012, 0, 0.07)), v_add(hb, (0.026, 0, 0.15)), v_sub(ht, (0.006, 0, 0.035))]
    tube(k, C, hp, 0.012, seg=8, rs=[0.0105, 0.012, 0.0135, 0.016])
    face = (0.95, 0.0, -0.31)                 # the spray plate looks forward and a little down
    lathe(k, C, [(0.046, -0.012), (0.051, -0.004), (0.048, 0.008), (0.0, 0.012)], seg=14, o=ht,
          axis=v_mul(face, -1.0), smooth=[True, True, False])
    lathe(k, 'int_black', [(0.046, -0.012), (0.0, -0.013)], seg=14, o=ht, axis=v_mul(face, -1.0), smooth=False)
    # hose: out of the bar's underside, a loop down, up into the handle
    p0 = (xb + 0.004, y - 0.09, z_bar - 0.03)
    ctrl = [p0, (xb + 0.012, y - 0.10, z_bar - 0.12), (xb + 0.04, y - 0.08, z_bar - 0.33),
            (xb + 0.07, y - 0.02, z_bar - 0.40), (xb + 0.085, y + 0.03, z_bar - 0.30),
            (xb + 0.075, y + 0.025, z_bar - 0.05), (xb + 0.055, y + 0.012, z_bar + 0.18), (hb[0], y, hb[2] - 0.025)]
    hose = catmull(ctrl, 11)
    tube(k, C, hose, 0.0075, seg=5)
    lathe(k, C, [(0.0, -0.025), (0.0095, -0.025), (0.0105, 0.0), (0.0, 0.002)], seg=8,
          o=(hb[0], y, hb[2] - 0.004), axis=v_norm(v_sub(hp[1], hp[0])))


def bottle(k, x, y, z, r=0.025, h=0.17, body='int_white_gloss', cap='int_black', pump=False):
    lathe(k, body, [(0.0, 0.0), (r * 0.9, 0.0), (r, r * 0.12), (r, h * 0.78), (r * 0.82, h * 0.9),
                    (0.0, h * 0.95)], seg=10, o=(x, y, z), smooth=[False, True, True, True, False])
    if pump:
        lathe(k, cap, [(r * 0.42, 0.0), (r * 0.42, 0.03), (r * 0.18, 0.034), (r * 0.18, 0.05),
                       (0.0, 0.05)], seg=8, o=(x, y, z + h * 0.95), smooth=[True, False, True, False])
        boxr(k, cap, (x, y - 0.005, z + h * 0.95 + 0.042), (x + 0.04, y + 0.005, z + h * 0.95 + 0.052))
    else:
        lathe(k, cap, [(r * 0.5, 0.0), (r * 0.5, 0.035), (r * 0.42, 0.04), (0.0, 0.04)], seg=8,
              o=(x, y, z + h * 0.95), smooth=[True, True, False])


def pot(k, x, y, z, r_top, h, mat='int_ceramic', seg=20):
    """A planter: tapered, a soft rim, soil at 3 cm under the rim."""
    rb = r_top * 0.78
    lathe(k, mat, [(0.0, 0.0), (rb, 0.0), (r_top, h - 0.008), (r_top - 0.007, h), (r_top - 0.013, h - 0.04),
                   (0.0, h - 0.04)], seg=seg, o=(x, y, z), smooth=[False, True, True, True, False])
    lathe(k, 'soil', [(r_top - 0.0125, h - 0.03), (0.0, h - 0.022)], seg=seg, o=(x, y, z), smooth=True)


def plant_snake(k, rng, x, y, z, s=1.0, mat_pot='int_ceramic', r_pot=0.12):
    hp = r_pot * 2.1
    pot(k, x, y, z, r_pot, hp, mat_pot, seg=18)
    zs = z + hp - 0.025
    n = 16
    for i in range(n):
        a = TAU * i / n + rng.uniform(-0.25, 0.25)
        rad = rng.uniform(0.0, r_pot * 0.55) * (0.4 + 0.6 * (i % 2))
        bx, by = x + rad * math.cos(a), y + rad * math.sin(a)
        L = s * rng.uniform(0.33, 0.62) * (1.15 if rad < r_pot * 0.25 else 1.0)
        tilt = rng.uniform(0.06, 0.20) + rad / r_pot * 0.25
        d = (math.cos(a) * tilt, math.sin(a) * tilt, 1.0)
        face = (math.cos(a + rng.uniform(-0.9, 0.9)), math.sin(a + rng.uniform(-0.9, 0.9)), 0.15)
        leaf(k, 'foliage' if i % 4 else 'foliage_b', (bx, by, zs), d, face, L, s * rng.uniform(0.05, 0.07),
             nseg=5, droop=0.0, fold=0.35, twist=rng.uniform(-0.6, 0.6), shape='lance')


def plant_bush(k, rng, x, y, z, s=1.0, mat_pot='int_ceramic', r_pot=0.08, n=22, h_pot=None, wall=False):
    """A leafy pot plant (peace-lily habit): broad pointed leaves on short
    arching stems, the young ones upright in the middle, the old ones laid
    out round the rim. s = 1: about 0.45 across, 0.40 high over the pot."""
    hp = h_pot or r_pot * 1.7
    pot(k, x, y, z, r_pot, hp, mat_pot, seg=12 if r_pot < 0.06 else 18)
    zs = z + hp - 0.025
    for i in range(n):
        a = TAU * i * 0.618034 + rng.uniform(-0.15, 0.15)
        f = i / max(1, n - 1)                       # 0: young, upright centre .. 1: old, wide
        st_r = s * (0.01 + 0.06 * f)
        st_h = s * (0.20 - 0.10 * f + rng.uniform(-0.02, 0.02))
        ca, sa = math.cos(a), math.sin(a)
        if wall and ca < 0:
            ca *= 0.15                              # a wall at -X: lean those leaves along it
        p0 = (x + 0.006 * ca, y + 0.006 * sa, zs)
        p1 = (x + st_r * 0.4 * ca, y + st_r * 0.4 * sa, zs + st_h * 0.7)
        p2 = (x + st_r * ca, y + st_r * sa, zs + st_h)
        tube(k, 'foliage_b', [p0, p1, p2], 0.0028 * s ** 0.5, seg=3, cap0=False, cap1=False, smooth=True)
        rise = 1.1 - 1.15 * f
        d = (ca, sa, rise)
        face = (-ca * rise * 0.6, -sa * rise * 0.6, 1.0)
        L = s * rng.uniform(0.17, 0.22)
        leaf(k, 'foliage' if i % 3 else 'foliage_b', p2, d, face, L, L * rng.uniform(0.40, 0.48), nseg=4,
             droop=0.18 + 0.25 * f, fold=0.22, shape='oval', twist=rng.uniform(-0.25, 0.25))


def towel_drape(k, mat, xb, z_bar, r_bar, y0, y1, front=0.38, back=0.30, t=0.009, seed=0):
    """A towel folded to (y1 - y0) wide hanging over a bar along Y at
    (xb, z_bar): back half behind, front half in front."""
    R = r_bar + t / 2 + 0.002
    path = [(xb - R - 0.004, 0.0, z_bar - back), (xb - R - 0.001, 0.0, z_bar - back * 0.5),
            (xb - R, 0.0, z_bar - 0.01)]
    for a in (150, 120, 90, 60, 30):
        r = math.radians(a)
        path.append((xb + R * math.cos(r), 0.0, z_bar + R * math.sin(r)))
    path += [(xb + R, 0.0, z_bar - 0.01), (xb + R + 0.003, 0.0, z_bar - front * 0.5),
             (xb + R + 0.008, 0.0, z_bar - front)]
    hw = (y1 - y0) / 2
    yc = (y0 + y1) / 2
    path = [(p[0], yc, p[2]) for p in path]
    sec = rpoly([(t / 2, -hw, t / 2, 1), (t / 2, hw, t / 2, 1), (-t / 2, hw, t / 2, 1), (-t / 2, -hw, t / 2, 1)])
    # the section is (a along N, b along B = Y); N = Y x T
    sweep(k, mat, path, sec, up=(0.0, 1.0, 0.0), smooth=True)


def fabric_for(rng, idx, choices):
    if idx is None or idx < 0:
        return rng.choice(choices)
    return choices[int(idx) % len(choices)]


# ---------------------------------------------------------------- the kinds
def egg(xback, ab, af, b, n=24, nb=4.0, nf=2.3, taper=0.1):
    """Plan of a wc pan: a flat back on x = xback, round front."""
    pts = []
    cx = xback + ab
    for j in range(n):
        th = TAU * j / n
        c, s = math.cos(th), math.sin(th)
        if c >= 0:
            x = cx + af * (abs(c) ** (2.0 / nf))
            y = b * math.copysign(abs(s) ** (2.0 / nf), s) * (1 - taper * c)
        else:
            x = cx - ab * (abs(c) ** (2.0 / nb))
            y = b * math.copysign(abs(s) ** (2.0 / nb), s) * (1 - 0.06 * -c)
        pts.append((x, y))
    return pts


def b_wc(k, w, d, rng, style=0):
    x0, x1 = -d / 2, d / 2
    b = min(0.18, w / 2 - 0.02)
    if int(style) == 0:
        pw = clamp(d - 0.53, 0.08, 0.22)
        xw = x0 + pw
        H = 1.12
        # pre-wall: tiled, a stone cap with a small nose
        boxr(k, 'int_tile_white', (x0, -w / 2, 0.0), (xw, w / 2, H - 0.021), cap0=False)
        boxr(k, 'int_marble', (x0, -w / 2, H - 0.02), (xw + 0.012, w / 2, H), rb=0.004, bseg=1)
        # flush plate: a chrome frame, two white buttons
        with at(k, m_wall(xw, 0.0, 0.99)):
            slab(k, 'chrome', lambda i: rrect(-0.122 + i, 0.122 - i, -0.082 + i, 0.082 - i, max(1e-3, 0.012 - i), 2),
                 -0.001, 0.007, 0.003, 1, sup=0.0)
            slab(k, 'int_white_gloss', lambda i: rrect(-0.105 + i, -0.004 - i, -0.066 + i, 0.066 - i, 0.008, 2),
                 0.007, 0.010, 0.0, side_smooth=False, cap0=False)
            slab(k, 'int_white_gloss', lambda i: rrect(0.004 + i, 0.105 - i, -0.066 + i, 0.066 - i, 0.008, 2),
                 0.007, 0.010, 0.0, side_smooth=False, cap0=False)
        L = clamp(x1 - xw, 0.40, 0.56)
        ab, af = 0.46 * L, 0.54 * L

        def ring(i):
            return egg(xw, ab - 0.1 * i, af - 0.9 * i, b - 0.75 * i, n=28)
        prof = [(0.10, 0.25), (0.072, 0.252), (0.042, 0.262), (0.02, 0.283), (0.007, 0.318), (0.0015, 0.355),
                (0.0, 0.385), (0.0015, 0.396), (0.005, 0.40)]
        zr = 0.40
        seat_back = xw + 0.035
    else:
        # close-coupled: cistern on the back of a floor pan
        cw = min(0.19, w / 2 - 0.01)
        xc = x0 + 0.165
        slab(k, 'int_ceramic', lambda i: rrect(x0 + i, xc - i, -cw + i, cw - i, max(1e-3, 0.03 - i), 3, 0.002),
             0.385, 0.80, 0.012, 2, bot_bevel=False)
        slab(k, 'int_ceramic', lambda i: rrect(x0 + i, xc + 0.006 - i, -cw - 0.005 + i, cw + 0.005 - i,
                                               max(1e-3, 0.033 - i), 3), 0.80, 0.826, 0.008, 2, sup=0.0,
             bot_bevel=False)
        lathe(k, 'chrome', [(0.0, 0.0), (0.024, 0.0), (0.024, 0.004), (0.021, 0.007), (0.0, 0.007)], seg=16,
              o=((x0 + xc) / 2, 0.0, 0.826))
        boxr(k, 'int_black', ((x0 + xc) / 2 - 0.0008, -0.017, 0.8331), ((x0 + xc) / 2 + 0.0008, 0.017, 0.8336))
        xw = x0 + 0.03
        L = clamp(x1 - xw, 0.42, 0.64)
        ab, af = 0.50 * L, 0.50 * L

        def ring(i):
            return egg(xw, ab - 0.15 * i, af - 1.5 * i, b - 0.85 * i, n=28, nb=3.2)
        # a skirted foot: the front of the pedestal sweeps back and down
        prof = [(0.07, 0.0), (0.07, 0.012), (0.08, 0.08), (0.07, 0.19), (0.035, 0.28), (0.008, 0.34),
                (0.0, 0.38), (0.0015, 0.394), (0.006, 0.40)]
        zr = 0.40
        seat_back = xc + 0.012
    rings = [ring3(ring(i), z) for i, z in prof]
    loft(k, 'int_ceramic', rings, True, cap0=True, cap1=True)
    # seat and lid (closed), white gloss
    seat_ab = ab - (seat_back - xw)

    def seat(i):
        return egg(seat_back, seat_ab - 0.2 * i + 0.003, af + 0.003 - i, b + 0.003 - i, n=32, nb=2.8)
    slab(k, 'int_white_gloss', seat, zr + 0.001, zr + 0.018, 0.007, 2, sup=0.0, bot_bevel=False)

    def lid(i):
        return egg(seat_back + 0.012, seat_ab - 0.012 - 0.2 * i, af - 0.0 - i, b - 0.002 - i, n=32, nb=2.8)
    slab(k, 'int_white_gloss', lid, zr + 0.0195, zr + 0.04, 0.009, 2, sup=0.0, dome=0.007, bot_bevel=False)
    # hinges
    for s in (-1, 1):
        lathe(k, 'chrome', [(0.0, -0.016), (0.011, -0.014), (0.011, 0.014), (0.0, 0.016)], seg=8,
              o=(seat_back + 0.012, s * 0.075, zr + 0.022), axis=(0, 1, 0))


def b_basin(k, w, d, rng, mirror=1, shelf=1, plant=1, front=0):
    x0, x1 = -d / 2, d / 2
    TOP, zb = 0.85, 0.805
    hw = w / 2
    # opening of the bowl
    ox0, ox1 = x0 + 0.105, x1 - 0.045
    oy = hw - 0.055
    ro = min(0.085, 0.45 * (ox1 - ox0), 0.45 * oy * 2)
    seg = 3
    sup = 0.0
    D = min(0.125, 0.25 + (ox1 - ox0) * 0.3 - 0.2)
    zbot = TOP - D
    A = 0.62 * min((ox1 - ox0) / 2, oy)

    def out_r(i, z):
        return ring3(rrect(x0 + i, x1 - i, -hw + i, hw - i, max(1e-3, 0.014 - i), seg, sup), z)

    def bowl_r(i, z, extra_r=0.0):
        return ring3(rrect(ox0 + i, ox1 - i, -oy + i, oy - i, max(0.01, ro - 0.6 * i + extra_r), seg, sup), z)
    rb = 0.007
    rings, sm = [], []

    def add(r, s=None):
        rings.append(r)
        if s is not None:
            sm.append(s)
    add(bowl_r(-0.012, zb))
    add(out_r(rb, zb), False)                       # underside (flat)
    add(out_r(0.0, zb + rb), True)
    add(out_r(0.0, TOP - rb - 0.002), True)
    add(out_r(0.0, TOP - rb), True)
    add(out_r(rb * (1 - math.cos(math.pi / 4)), TOP - rb + rb * math.sin(math.pi / 4)), True)
    add(out_r(rb, TOP), True)
    add(bowl_r(-0.009, TOP), False)                 # the top deck (flat)
    add(bowl_r(-0.004, TOP - 0.0015), True)        # lip
    add(bowl_r(0.0, TOP - 0.006), True)
    n = 5
    for s in range(1, n + 1):
        th = (math.pi / 2) * s / n
        add(bowl_r(0.004 + A * (1 - math.cos(th)), TOP - 0.006 - (D - 0.006) * math.sin(th)), True)
    cx = (ox0 + ox1) / 2
    add([(cx, 0.0, zbot)], True)
    loft(k, 'int_ceramic', rings, sm)
    # drain
    lathe(k, 'chrome', [(0.031, 0.0), (0.029, 0.003), (0.0, 0.0035)], seg=14, o=(cx, 0.0, zbot),
          smooth=[True, False])
    # the vanity: a white carcass (open top, under the ceramic), a drawer front
    # with a finger gap under the top
    fm = ('int_wood_oak', 'int_wood_walnut', 'int_white_gloss')[int(front) % 3]
    xf = x1 - 0.026
    slab(k, 'int_white_gloss', lambda i: rrect(x0 + i, xf - i, -hw + 0.004 + i, hw - 0.004 - i, 0.004, 1),
         0.42, zb, 0.004, 1, sup=0.0, side_smooth=False, bev_smooth=False, cap1=False, top_bevel=False)
    boxr(k, fm, (xf, -hw + 0.004, 0.42), (x1 - 0.004, hw - 0.004, zb - 0.032), rb=0.003, bseg=1)
    # brass pull in the gap
    boxr(k, 'int_brass', (x1 - 0.012, -min(0.18, hw * 0.55), zb - 0.032), (x1 - 0.004, min(0.18, hw * 0.55), zb - 0.028))
    # mixer on the back deck
    mixer_basin(k, x0 + 0.055, 0.0, TOP, 0.16, min(0.125, ox0 - x0 - 0.055 + 0.075))
    # soap pump on the deck, a small plant on the other side
    if hw > 0.26:
        bottle(k, x0 + 0.05, hw - 0.06, TOP, 0.026, 0.15, 'int_white_gloss', 'chrome', pump=True)
        if plant:
            plant_bush(k, rng, x0 + 0.052, -(hw - 0.07), TOP, s=0.30, r_pot=0.042, n=9, h_pot=0.075, wall=True)
    mw = min(w, 0.80)
    if shelf:
        boxr(k, 'int_wood_oak', (x0, -mw / 2 + 0.04, 1.085), (x0 + 0.11, mw / 2 - 0.04, 1.105), rb=0.004, bseg=1)
        # a tumbler with two toothbrushes, a bottle
        ty = -mw / 2 + 0.14
        lathe(k, 'int_ceramic', [(0.0, 0.0), (0.031, 0.0), (0.036, 0.095), (0.032, 0.095),
                                 (0.028, 0.012), (0.0, 0.012)], seg=12, o=(x0 + 0.06, ty, 1.105),
              smooth=[False, True, False, True, False])
        for j, (m_, dy) in enumerate((('int_mint', -0.008), ('int_white_gloss', 0.01))):
            p0 = (x0 + 0.06 + 0.004 * j, ty + dy * 0.5, 1.118)
            p1 = (x0 + 0.06 - 0.006 + 0.012 * j, ty + dy * 2.6, 1.30)
            tube(k, m_, [p0, p1], 0.0045, seg=6)
            boxr(k, 'int_fabric_white', v_add(p1, (-0.006, -0.005, -0.03)), v_add(p1, (0.006, 0.005, 0.0)))
        bottle(k, x0 + 0.055, mw / 2 - 0.12, 1.105, 0.022, 0.12, 'int_mint', 'chrome')
    if mirror:
        zm0, zm1 = 1.12, 1.80
        with at(k, m_wall(x0, 0.0, (zm0 + zm1) / 2)):
            slab(k, 'int_black', lambda i: rrect(-mw / 2 + 0.025 + i, mw / 2 - 0.025 - i, -(zm1 - zm0) / 2 + 0.025 + i,
                                                 (zm1 - zm0) / 2 - 0.025 - i, 0.01, 2), 0.0, 0.016, 0.0, cap0=False)
            slab(k, 'int_mirror', lambda i: rrect(-mw / 2 + i, mw / 2 - i, -(zm1 - zm0) / 2 + i, (zm1 - zm0) / 2 - i,
                                                  0.03, 4), 0.016, 0.022, 0.0, cap0=False)
        # light bar over the mirror: chrome housing, a glowing diffuser under it
        lw = mw * 0.42
        boxr(k, 'chrome', (x0, -0.02, 1.84), (x0 + 0.008, 0.02, 1.885))
        boxr(k, 'chrome', (x0 + 0.008, -0.008, 1.866), (x0 + 0.072, 0.008, 1.876))
        boxr(k, 'chrome', (x0 + 0.07, -lw, 1.858), (x0 + 0.115, lw, 1.884), rb=0.005, bseg=1)
        boxr(k, 'int_lamp_shade', (x0 + 0.074, -lw + 0.006, 1.8545), (x0 + 0.111, lw - 0.006, 1.8585))


def quadrant_keys(cx0, cy0, d, w, i, R, na=10, rc=0.004, square=False):
    """Plan of a corner tray / screen line at inset i: walls on x = cx0 and
    y = cy0, the front an offset quadrant of radius R (CCW from above)."""
    keys = [(cx0 + i, cy0 + i, rc, 0), (cx0 + d - i, cy0 + i, 0.004, 0)]
    if square:
        keys.append((cx0 + d - i, cy0 + w - i, 0.03, 4))
    else:
        cxa, cya = cx0 + d - R, cy0 + w - R
        rr = R - i
        for s in range(na + 1):
            a = (math.pi / 2) * s / na
            keys.append((cxa + rr * math.cos(a), cya + rr * math.sin(a), 0.0, 0))
    keys.append((cx0 + i, cy0 + w - i, 0.004, 0))
    return keys


def path_len(p):
    return sum(math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1]) for i in range(len(p) - 1))


def path_sub(p, s0, s1, off=0.0):
    """Part of a plan polyline between arc lengths s0..s1, offset `off` to
    the left of travel."""
    out = []
    acc = 0.0
    for i in range(len(p) - 1):
        a, b = p[i], p[i + 1]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 1e-9:
            continue
        nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
        for s in ([s0] if acc <= s0 < acc + L else []) + ([acc] if s0 < acc < s1 else []):
            t = (s - acc) / L
            out.append((a[0] + (b[0] - a[0]) * t + nx * off, a[1] + (b[1] - a[1]) * t + ny * off))
        if acc < s1 <= acc + L + 1e-9:
            t = (s1 - acc) / L
            out.append((a[0] + (b[0] - a[0]) * t + nx * off, a[1] + (b[1] - a[1]) * t + ny * off))
            break
        acc += L
    return out


def offset_path(p, off):
    """Plan polyline offset to the left of travel (mitred)."""
    out = []
    n = len(p)
    for i in range(n):
        if i == 0:
            t = (p[1][0] - p[0][0], p[1][1] - p[0][1])
        elif i == n - 1:
            t = (p[-1][0] - p[-2][0], p[-1][1] - p[-2][1])
        else:
            t1 = (p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1])
            t2 = (p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1])
            l1, l2 = math.hypot(*t1) or 1e-9, math.hypot(*t2) or 1e-9
            t = (t1[0] / l1 + t2[0] / l2, t1[1] / l1 + t2[1] / l2)
        L = math.hypot(*t) or 1e-9
        nx, ny = -t[1] / L, t[0] / L
        sc = 1.0
        if 0 < i < n - 1:
            l1 = math.hypot(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]) or 1e-9
            e1 = (-(p[i][1] - p[i - 1][1]) / l1, (p[i][0] - p[i - 1][0]) / l1)
            sc = 1.0 / max(0.5, nx * e1[0] + ny * e1[1])
        out.append((p[i][0] + nx * off * sc, p[i][1] + ny * off * sc))
    return out


def corner_shelf(k, cx0, cy0, z, r=0.2):
    keys = [(cx0 + 0.002, cy0 + 0.002, 0.0, 0)]
    for s in range(7):
        a = (math.pi / 2) * s / 6
        keys.append((cx0 + r * math.cos(a), cy0 + r * math.sin(a), 0.0, 0))
    pts = rpoly(keys)
    slab(k, 'int_white_gloss', lambda i: [(p[0] - i * 0.0, p[1] - i * 0.0) for p in pts], z - 0.018, z, 0.0,
         side_smooth=False)
    bottle(k, cx0 + 0.075, cy0 + 0.075, z, 0.024, 0.18, 'int_white_gloss', 'int_black')


def glass_screen(k, path, panels, z0, z1):
    """Glass on the plan polyline: `panels` [(s0, s1, off)] by arc length."""
    for s0, s1, off in panels:
        sub = path_sub(offset_path(path, off), s0, s1)
        strip(k, 'int_glass', sub, z0, z1)


def b_shower_corner(k, w, d, rng, shape=0):
    cx0, cy0 = -d / 2, -w / 2
    sq = int(shape) == 1
    R = clamp(min(0.55, min(w, d) - 0.12), 0.25, 0.9)
    # the tray: 4 cm, a soft top edge
    slab(k, 'int_ceramic', lambda i: rpoly(quadrant_keys(cx0, cy0, d, w, i, R, 12, square=sq)), 0.0, 0.04, 0.006, 2,
         sup=0.0, side_smooth=False)
    # drain
    lathe(k, 'chrome', [(0.047, 0.0), (0.045, 0.0035), (0.03, 0.0035)], seg=14,
          o=(cx0 + min(d, w) * 0.36, cy0 + min(d, w) * 0.36, 0.04), smooth=[True, False])
    lathe(k, 'int_black', [(0.03, 0.0035), (0.0, 0.0025)], seg=14,
          o=(cx0 + min(d, w) * 0.36, cy0 + min(d, w) * 0.36, 0.04), smooth=False)
    # the screen line: from the wall y = cy0 round to the wall x = cx0
    g = 0.04
    line = [(x, y) for x, y in rpoly(quadrant_keys(cx0, cy0, d, w, g, R, 14, square=sq))]
    # drop the two points on the walls' side of the plan: keep x-end .. y-end
    line = line[1:]
    line[0] = (line[0][0], cy0)
    line[-1] = (cx0, line[-1][1])
    L = path_len(line)
    zg0, zg1 = 0.05, 1.95
    if sq:
        # corner entry: fixed panels by the walls, two doors meeting round the corner
        L1 = w - g                                  # the first leg: wall y = cy0 .. the corner
        panels = [(0.0, L1 - 0.30, 0.0), (L1 - 0.34, L1 - 0.02, 0.022), (L1 + 0.02, L1 + 0.34, 0.022),
                  (L1 + 0.30, L, 0.0)]
        meet = [L1 - 0.03, L1 + 0.03]
    else:
        panels = [(0.0, 0.31 * L, 0.0), (0.26 * L, 0.502 * L, 0.022), (0.498 * L, 0.74 * L, 0.022),
                  (0.69 * L, L, 0.0)]
        meet = [0.49 * L, 0.51 * L]
    glass_screen(k, line, panels, zg0, zg1)
    C = 'chrome'
    # top rail over the outer line, a low profile at the foot
    top = [(x, y, zg1 + 0.012) for x, y in offset_path(line, 0.011)]
    tube(k, C, top, 0.010, seg=6)
    # wall channels
    boxr(k, C, (line[0][0] - 0.016, cy0, 0.04), (line[0][0] + 0.016, cy0 + 0.028, zg1 + 0.03), rb=0.003)
    boxr(k, C, (cx0, line[-1][1] - 0.016, 0.04), (cx0 + 0.028, line[-1][1] + 0.016, zg1 + 0.03), rb=0.003)
    # door edges and handles: on the inner (door) line, a vertical bar handle
    # outside each door near where they meet
    for j, s in enumerate(meet):
        pin = path_sub(offset_path(line, 0.022), max(0.0, s - 0.001), s)
        if not pin:
            continue
        px, py = pin[-1]
        tube(k, C, [(px, py, zg0), (px, py, zg1)], 0.006, seg=6)
        sh = s + (-0.07 if j == 0 else 0.07)
        po = path_sub(offset_path(line, -0.022), max(0.0, sh - 0.001), sh)
        pi_ = path_sub(offset_path(line, 0.022), max(0.0, sh - 0.001), sh)
        if not po or not pi_:
            continue
        ox, oy = po[-1]
        ix, iy = pi_[-1]
        ux, uy = ox - ix, oy - iy
        hf = 0.95 if sq else 1.3
        hx, hy = ix + ux * hf, iy + uy * hf
        tube(k, C, [(hx, hy, 0.93), (hx, hy, 1.25)], 0.0085, seg=8)
        for zz in (0.97, 1.21):
            tube(k, C, [(ix, iy, zz), (hx, hy, zz)], 0.0055, seg=6, cap1=False)
    # column on the wall x = cx0
    yr = cy0 + clamp(0.5 * (w - g), 0.33, 0.55)
    shower_column(k, cx0, yr, 'round', 1.10, 2.0, min(0.30, d - 0.30))
    corner_shelf(k, cx0, cy0, 1.32, min(0.2, 0.3 * min(w, d)))


def b_shower(k, w, d, rng, tray=0, stool=1):
    x0, x1 = -d / 2, d / 2
    tm = ('int_stone_dark', 'int_ceramic')[int(tray) % 2]
    slab(k, tm, lambda i: rrect(x0 + i, x1 - i, -w / 2 + i, w / 2 - i, max(1e-3, 0.012 - i), 2), 0.0, 0.03,
         0.005, 2, sup=0.0, side_smooth=False)
    # linear drain by the back wall
    dl = min(0.40, w / 2 - 0.12)
    boxr(k, 'chrome', (x0 + 0.045, -dl, 0.0295), (x0 + 0.095, dl, 0.033), rb=0.002)
    for j in range(5):
        xx = x0 + 0.053 + j * 0.008
        boxr(k, 'int_black', (xx, -dl + 0.01, 0.033), (xx + 0.003, dl - 0.01, 0.0333), cap0=False)
    # the glass: one fixed panel on the front edge from y = -w/2
    Lg = min(clamp(0.55 * w, 0.8, 1.2), max(0.3, w - 0.6))     # leave at least 0.6 m to walk in
    xg = x1 - 0.035
    ya, yb = -w / 2, -w / 2 + Lg
    strip(k, 'int_glass', [(xg, ya + 0.02), (xg, yb)], 0.045, 2.0)
    C = 'chrome'
    boxr(k, C, (xg - 0.012, ya, 0.028), (xg + 0.012, yb, 0.058), rb=0.003)
    boxr(k, C, (xg - 0.012, ya, 0.028), (xg + 0.012, ya + 0.022, 2.01), rb=0.003)
    tube(k, C, [(xg, yb, 0.06), (xg, yb, 1.99)], 0.004, seg=6)          # polished free edge
    ys = yb - 0.12
    tube(k, C, [(xg, ys, 1.975), (x0 + 0.004, ys, 1.975)], 0.0095, seg=10)
    rosette(k, C, x0, ys, 1.975, 0.022, 0.008)
    for s in (-1, 1):
        boxr(k, C, (xg + s * 0.004 - 0.008 * (s < 0), ys - 0.02, 1.955), (xg + s * 0.004 + 0.008 * (s > 0), ys + 0.02, 1.995))
    # column on the back wall, behind the glass
    yc = clamp(ya + Lg * 0.5, -w / 2 + 0.19, w / 2 - 0.19)
    shower_column(k, x0, yc, 'square', 1.10, 2.05, min(0.36, d - 0.45))
    # teak stool in the open end
    if stool and (w / 2 - yb) >= 0.70:
        sy = w / 2 - 0.30
        sx = x0 + 0.24
        T = 'int_wood_teak'
        for j in range(4):
            xx = sx - 0.14 + j * 0.0725
            boxr(k, T, (xx, sy - 0.2, 0.42), (xx + 0.062, sy + 0.2, 0.445), rb=0.004, bseg=1)
        for s in (-1, 1):
            yy = sy + s * 0.16
            boxr(k, T, (sx - 0.13, yy - 0.012, 0.03), (sx + 0.13, yy + 0.012, 0.42))
        boxr(k, T, (sx - 0.012, sy - 0.148, 0.16), (sx + 0.012, sy + 0.148, 0.19))


def tub_profile(top, depth, rf, n_wall=2, n_fil=3):
    """(depth below the opening, extra inset factor in [0..1] for the slope,
    fillet inset) rings for a tub's inside: walls then a round fillet into a
    flat floor. Returns [(z_drop, wall_t, fil)] where wall_t in 0..1 scales
    each side's slope inset and fil is the fillet inset."""
    out = []
    hw = depth - rf
    for s in range(1, n_wall + 1):
        out.append((hw * s / n_wall, s / n_wall, 0.0))
    for s in range(1, n_fil + 1):
        a = (math.pi / 2) * s / n_fil
        out.append((hw + rf * math.sin(a), 1.0, rf * (1 - math.cos(a))))
    return out


def b_bath(k, w, d, rng, caddy=1, tap_end=0):
    x0, x1 = -d / 2, d / 2
    sgn = -1.0 if int(tap_end) == 0 else 1.0       # the foot (tap) end
    # plinth and apron
    boxr(k, 'int_black', (x0, -w / 2 + 0.04, 0.0), (x1 - 0.045, w / 2 - 0.04, 0.075), cap1=False)
    slab(k, 'int_white_gloss', lambda i: rrect(x0 + i, x1 - 0.006 - i, -w / 2 + 0.006 + i, w / 2 - 0.006 - i,
                                               0.004, 1), 0.07, 0.555, 0.004, 1, sup=0.0, side_smooth=False,
         bev_smooth=False, cap1=False, top_bevel=False)
    TOP = 0.58
    # opening: in from the rim, the backrest end longer
    ox0, ox1 = x0 + 0.075, x1 - 0.07
    yf = sgn * (w / 2 - 0.085)                      # foot end
    yh = -sgn * (w / 2 - 0.10)                      # head end
    ya, yb = min(yf, yh), max(yf, yh)
    r0 = min(0.17, 0.45 * (ox1 - ox0))
    zf = 0.12
    depth = TOP - 0.006 - zf
    seg, sup = 3, 0.002
    # per side slope inset at the floor: sides 6 cm, foot 7 cm, backrest 32 cm
    s_side, s_foot, s_head = 0.06, 0.07, min(0.34, 0.24 * w)
    rf = 0.09

    def inner(z_drop, wt, fil, z):
        ix = 0.004 + s_side * wt + fil
        if_ = 0.004 + s_foot * wt + fil
        ih = 0.004 + s_head * (wt ** 0.85) + fil
        if sgn < 0:
            yy0, yy1 = ya + if_, yb - ih
        else:
            yy0, yy1 = ya + ih, yb - if_
        r = max(0.04, r0 - 0.5 * (ix + 0.004))
        return ring3(rrect(ox0 + ix, ox1 - ix, yy0, yy1, r, seg, sup), z)

    def outer(i, z):
        return ring3(rrect(x0 + i, x1 - i, -w / 2 + i, w / 2 - i, max(1e-3, 0.01 - i), seg, sup), z)

    def opening(e, z):
        return ring3(rrect(ox0 - e, ox1 + e, ya - e, yb + e, r0 + e, seg, sup), z)
    rings, sm = [], []

    def add(r, s=None):
        rings.append(r)
        if s is not None:
            sm.append(s)
    rb = 0.008
    add(outer(0.012, 0.555))
    add(outer(0.0, 0.555), False)
    add(outer(0.0, 0.557), True)
    add(outer(0.0, TOP - rb), True)
    add(outer(rb * (1 - math.cos(math.pi / 4)), TOP - rb + rb * math.sin(math.pi / 4)), True)
    add(outer(rb, TOP), True)
    add(opening(0.01, TOP), False)
    add(opening(0.004, TOP - 0.0015), True)
    add(opening(0.0, TOP - 0.006), True)
    for z_drop, wt, fil in tub_profile(TOP - 0.006, depth, rf):
        add(inner(z_drop, wt, fil, TOP - 0.006 - z_drop), True)
    last = rings[-1]
    c = centroid2([(p[0], p[1]) for p in last])
    add([(c[0], c[1], zf)], False)
    loft(k, 'int_ceramic', rings, sm)
    # drain near the foot, on the floor
    fl = rings[-2]
    fy = min(p[1] for p in fl) if sgn < 0 else max(p[1] for p in fl)
    lathe(k, 'chrome', [(0.035, 0.0), (0.033, 0.0035), (0.0, 0.004)], seg=14, o=(c[0], fy - sgn * 0.06, zf),
          smooth=[True, False])
    # wall mixer at the foot end: bar along Y, two knobs, spout, telephone
    # hand shower in its cradle, the hose looping down
    C = 'chrome'
    ym = sgn * (w / 2 - 0.30)
    zm = 0.78
    xb = x0 + 0.07
    for dy in (-0.075, 0.075):
        rosette(k, C, x0, ym + dy, zm, 0.024, 0.008)
        tube(k, C, [(x0 + 0.006, ym + dy, zm), (xb, ym + dy, zm)], 0.0105, seg=10, cap0=False, cap1=False)
    lathe(k, C, [(0.027, -0.11), (0.027, 0.11)], seg=14, o=(xb, ym, zm), axis=(0, 1, 0))
    for s in (-1, 1):
        o = (xb, ym + s * 0.11, zm)
        lathe(k, C, [(0.0, 0.0), (0.031, 0.0), (0.031, 0.032), (0.026, 0.039), (0.0, 0.04)], seg=12, o=o,
              axis=(0, s, 0), smooth=[False, True, True, False])
        lathe(k, 'int_black', [(0.0316, 0.012), (0.0316, 0.022)], seg=12, o=o, axis=(0, s, 0))
    tube(k, C, [(xb + 0.01, ym, zm - 0.005), (xb + 0.07, ym, zm - 0.01), (xb + 0.12, ym, zm - 0.022),
                (xb + 0.145, ym, zm - 0.045)], 0.012, seg=12, rs=[0.012, 0.0125, 0.013, 0.013])
    lathe(k, 'int_black', [(0.0, 0.0), (0.008, 0.0)], seg=10, o=(xb + 0.1455, ym, zm - 0.0455), axis=(0.5, 0, -0.866),
          smooth=False)
    # cradle and hand shower lying along Y on top of the bar
    lathe(k, C, [(0.0, 0.0), (0.012, 0.0), (0.012, 0.03), (0.0, 0.03)], seg=10, o=(xb, ym, zm + 0.024),
          smooth=[True, True, False])
    hs = [(xb, ym - 0.10 * sgn, zm + 0.06), (xb, ym - 0.02 * sgn, zm + 0.062), (xb, ym + 0.06 * sgn, zm + 0.066)]
    tube(k, C, hs, 0.013, seg=12, rs=[0.011, 0.013, 0.016])
    lathe(k, C, [(0.0, -0.012), (0.042, -0.011), (0.045, 0.0), (0.04, 0.009), (0.0, 0.012)],
          seg=14, o=(xb, ym + 0.085 * sgn, zm + 0.067), axis=(0, sgn, 0.0), smooth=[False, True, True, False])
    hose = catmull([(xb + 0.004, ym - 0.10 * sgn, zm + 0.048), (xb + 0.018, ym - 0.128 * sgn, zm + 0.01),
                    (xb + 0.035, ym - 0.13 * sgn, zm - 0.07), (xb + 0.055, ym - 0.09 * sgn, zm - 0.145),
                    (xb + 0.065, ym - 0.02 * sgn, zm - 0.165), (xb + 0.065, ym + 0.045 * sgn, zm - 0.13),
                    (xb + 0.05, ym + 0.07 * sgn, zm - 0.06), (xb + 0.034, ym + 0.055 * sgn, zm - 0.022)], 14)
    tube(k, C, hose, 0.0075, seg=6)
    # teak caddy across the rim, a candle and a folded flannel on it
    if caddy:
        yc = -sgn * w * 0.08
        T = 'int_wood_teak'
        for j in range(3):
            yy = yc - 0.10 + j * 0.07
            boxr(k, T, (x0 + 0.02, yy, TOP + 0.001), (x1 - 0.02, yy + 0.042, TOP + 0.016), rb=0.004, bseg=1)
        for xx in (ox0 + 0.035, ox1 - 0.035):
            boxr(k, T, (xx - 0.012, yc - 0.1, TOP - 0.02), (xx + 0.012, yc + 0.106, TOP + 0.001))
        lathe(k, 'int_white_gloss', [(0.0, 0.0), (0.031, 0.0), (0.031, 0.07), (0.027, 0.072),
                                     (0.0, 0.069)], seg=10, o=(0.06, yc + 0.03, TOP + 0.016),
              smooth=[False, True, True, False])
        tube(k, 'int_black', [(0.06, yc + 0.03, TOP + 0.085), (0.06, yc + 0.03, TOP + 0.097)], 0.0012, seg=4)
        boxr(k, 'int_fabric_white', (-0.12, yc - 0.06, TOP + 0.016), (0.0, yc + 0.06, TOP + 0.05), rb=0.01,
             bseg=1, smooth=True)


def corner_bath_keys(cx0, cy0, d, w, i, e, rc, rf, na=12, n=2.25):
    O = (cx0 + e, cy0 + e)
    ax, ay = d - i - e, w - i - e
    keys = [(cx0 + i, cy0 + i, rc, 5), (cx0 + d - i, cy0 + i, rf, 2)]
    for s in range(na + 1):
        th = (math.pi / 2) * s / na
        c, sn = math.cos(th), math.sin(th)
        keys.append((O[0] + ax * (c ** (2.0 / n) if c > 0 else 0.0), O[1] + ay * (sn ** (2.0 / n) if sn > 0 else 0.0),
                     0.0, 0))
    keys.append((cx0 + i, cy0 + w - i, rf, 2))
    return keys


def b_bath_corner(k, w, d, rng):
    cx0, cy0 = -d / 2, -w / 2
    e = min(0.48, 0.37 * min(d, w))
    TOP = 0.58
    sup = 0.002

    def R(i, rc, rf, z):
        return ring3(rpoly(corner_bath_keys(cx0, cy0, d, w, i, e, rc, rf), sup), z)
    # plinth and apron
    loft(k, 'int_black', [R(0.045, 0.01, 0.01, 0.0), R(0.045, 0.01, 0.01, 0.075)], False, cap0=False)
    loft(k, 'int_white_gloss', [R(0.01, 0.006, 0.006, 0.066), R(0.006, 0.006, 0.006, 0.07),
                                R(0.006, 0.006, 0.006, 0.555)], [False, True], cap0=True)
    rings, sm = [], []

    def add(r, s=None):
        rings.append(r)
        if s is not None:
            sm.append(s)
    rb = 0.008
    io, rco, rfo = 0.075, 0.42, 0.10                # the opening: a deck in the corner
    add(R(0.012, 0.008, 0.008, 0.555))
    add(R(0.0, 0.008, 0.008, 0.555), False)
    add(R(0.0, 0.008, 0.008, 0.557), True)
    add(R(0.0, 0.008, 0.008, TOP - rb), True)
    add(R(rb * 0.29, 0.008, 0.008, TOP - rb * 0.29), True)
    add(R(rb, 0.008, 0.008, TOP), True)
    add(R(io - 0.01, rco + 0.01, rfo + 0.01, TOP), False)
    add(R(io - 0.004, rco + 0.004, rfo + 0.004, TOP - 0.0015), True)
    add(R(io, rco, rfo, TOP - 0.006), True)
    zf = 0.13
    depth = TOP - 0.006 - zf
    for z_drop, wt, fil in tub_profile(TOP - 0.006, depth, 0.10):
        ii = io + 0.07 * wt + fil
        add(R(ii, max(0.05, rco - 0.4 * (ii - io)), max(0.03, rfo - 0.3 * (ii - io)), TOP - 0.006 - z_drop), True)
    last = rings[-1]
    c = centroid2([(p[0], p[1]) for p in last])
    add([(c[0], c[1], zf)], False)
    loft(k, 'int_ceramic', rings, sm)
    lathe(k, 'chrome', [(0.035, 0.0), (0.033, 0.0035), (0.0, 0.004)], seg=14, o=(c[0], c[1], zf),
          smooth=[True, False])
    # deck mixer in the corner: a spout arching toward the middle of the tub,
    # two knobs beside it
    C = 'chrome'
    ux, uy = math.sqrt(0.5), math.sqrt(0.5)
    px, py = cx0 + 0.105, cy0 + 0.105
    lathe(k, C, [(0.026, 0.0), (0.026, 0.004), (0.02, 0.01), (0.0, 0.012)], seg=12, o=(px, py, TOP),
          smooth=[True, True, False])
    sp = [(px, py, TOP + 0.005), (px, py, TOP + 0.10), (px + ux * 0.03, py + uy * 0.03, TOP + 0.14),
          (px + ux * 0.10, py + uy * 0.10, TOP + 0.15), (px + ux * 0.16, py + uy * 0.16, TOP + 0.12),
          (px + ux * 0.175, py + uy * 0.175, TOP + 0.09)]
    tube(k, C, catmull(sp, 10), 0.013, seg=10)
    for s in (-1, 1):
        kx, ky = px - uy * s * 0.09 - ux * 0.01, py + ux * s * 0.09 - uy * 0.01
        lathe(k, C, [(0.024, 0.0), (0.019, 0.008), (0.019, 0.045), (0.015, 0.052), (0.0, 0.053)], seg=10,
              o=(kx, ky, TOP), smooth=[True, True, True, False])
        boxr(k, C, (kx - 0.004, ky - 0.004, TOP + 0.05), (kx + 0.004, ky + 0.004, TOP + 0.056), cap0=False)


def b_towel_rail(k, w, d, rng, h=0.95, finish=0, towel=-1):
    x0 = -d / 2
    M = ('chrome', 'int_white_gloss', 'int_black')[int(finish) % 3]
    xb = x0 + 0.055
    z0, z1 = 0.20, 0.20 + h
    yv = w / 2 - 0.016
    for s in (-1, 1):
        lathe(k, M, [(0.0, z0 - 0.012), (0.0145, z0 - 0.004), (0.0145, z1), (0.0, z1 + 0.011)], seg=10,
              o=(xb, s * yv, 0.0))
        # brackets top and bottom
        for zz in (z0 + 0.06, z1 - 0.06):
            rosette(k, M, x0, s * yv, zz, 0.02, 0.007, seg=10)
            tube(k, M, [(x0 + 0.006, s * yv, zz), (xb - 0.01, s * yv, zz)], 0.0075, seg=6, cap0=False, cap1=False)
        # valve tails into the wall
        tube(k, 'chrome', [(xb, s * yv, z0 - 0.01), (xb, s * yv, z0 - 0.06), (xb - 0.012, s * yv, z0 - 0.075),
                           (x0 + 0.004, s * yv, z0 - 0.078)], 0.0075, seg=6, cap0=False, cap1=False)
        rosette(k, 'chrome', x0, s * yv, z0 - 0.078, 0.019, 0.006, seg=10)
    # bars: groups of four with a gap
    bars = []
    z = z1 - 0.035
    while z > z0 + 0.04:
        for j in range(4):
            if z - j * 0.048 > z0 + 0.04:
                bars.append(z - j * 0.048)
        z -= 4 * 0.048 + 0.075
    for zz in bars:
        tube(k, M, [(xb, -yv, zz), (xb, yv, zz)], 0.0105, seg=8, cap0=False, cap1=False)
    tm = fabric_for(rng, towel, ('int_fabric_white', 'int_fabric_teal', 'int_fabric_bluegrey', 'int_fabric_orange'))
    if len(bars) >= 2:
        zt = bars[1] if len(bars) > 4 else bars[0]
        tw = min(0.44, 2 * yv - 0.05)
        towel_drape(k, tm, xb, zt, 0.0105, -tw / 2, tw / 2, front=min(0.40, zt - 0.25), back=min(0.32, zt - 0.27))


def b_washing_machine(k, w, d, rng):
    x0, x1 = -d / 2, d / 2 - 0.062
    H = 0.85
    W = 'int_white_gloss'
    for sx in (-1, 1):
        for sy in (-1, 1):
            lathe(k, 'int_black', [(0.02, 0.0), (0.02, 0.016), (0.0, 0.016)], seg=8,
                  o=((x0 + x1) / 2 + sx * ((x1 - x0) / 2 - 0.06), sy * (w / 2 - 0.06), 0.0), smooth=[True, False])
    slab(k, W, lambda i: rrect(x0 + i, x1 - i, -w / 2 + i, w / 2 - i, max(1e-3, 0.02 - i), 3, 0.002), 0.014, H,
         0.012, 2, bot_bevel=False, cap0=False)
    # porthole door on the front
    cz = 0.43
    with at(k, (((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)), (x1, 0.0, cz))):
        # local z -> world +X (out of the front), local x -> world -Z, local y -> world Y
        lathe(k, 'frame_light', [(0.236, -0.004), (0.238, 0.012), (0.23, 0.032), (0.205, 0.041)],
              seg=32, smooth=True)
        lathe(k, 'chrome', [(0.205, 0.041), (0.199, 0.046), (0.193, 0.044)], seg=32, smooth=True)
        lathe(k, 'int_black', [(0.193, 0.044), (0.15, 0.053), (0.0, 0.06)], seg=32)
        # the handle on the door's right (+Y) edge
        boxr(k, 'chrome', (-0.05, 0.215, 0.012), (0.05, 0.236, 0.034), rb=0.006, bseg=1, smooth=True)
    # control strip: drawer, display, dial
    with at(k, m_wall(x1, 0.0, 0.78)):
        slab(k, W, lambda i: rrect(-w / 2 + 0.035 + i, -w / 2 + 0.235 - i, -0.042 + i, 0.042 - i, 0.006, 1), 0.0,
             0.006, 0.0, cap0=False)
        boxr(k, 'int_black', (-w / 2 + 0.06, -0.04, 0.006), (-w / 2 + 0.21, -0.03, 0.0065))
        boxr(k, 'int_black', (-0.03, -0.022, 0.0), (0.09, 0.022, 0.003), cap0=False)
        for j in range(3):
            lathe(k, 'chrome', [(0.0055, 0.0), (0.005, 0.004), (0.0, 0.0045)], seg=6, o=(0.12, -0.024 + 0.024 * j, 0.0),
                  smooth=[True, False])
    dial = (x1, w / 2 - 0.12, 0.78)
    lathe(k, 'chrome', [(0.034, -0.002), (0.035, 0.006), (0.027, 0.01)], seg=20, o=dial, axis=(1, 0, 0))
    lathe(k, W, [(0.027, 0.01), (0.027, 0.03), (0.024, 0.036), (0.0, 0.037)], seg=20, o=dial, axis=(1, 0, 0),
          smooth=[True, True, False])
    boxr(k, 'int_black', (x1 + 0.037, dial[1] - 0.002, 0.78 + 0.006), (x1 + 0.0376, dial[1] + 0.002, 0.78 + 0.021))
    # top seam: the worktop lid sits a hair proud
    boxr(k, 'int_black', (x1 - 0.0005, -w / 2 + 0.02, 0.695), (x1 + 0.0005, w / 2 - 0.02, 0.697))
    # service hatch low right
    with at(k, m_wall(x1, w / 2 - 0.12, 0.075)):
        slab(k, W, lambda i: rrect(-0.06 + i, 0.06 - i, -0.035 + i, 0.035 - i, 0.006, 1), 0.0, 0.004, 0.0,
             cap0=False)


def b_wc_set(k, w, d, rng):
    x0 = -d / 2
    C = 'chrome'
    yh = w / 2 - 0.035
    z = 0.70
    rosette(k, C, x0, yh, z, 0.026, 0.009, seg=16)
    xr = x0 + 0.072
    tube(k, C, [(x0 + 0.008, yh, z), (xr - 0.02, yh, z), (xr - 0.004, yh - 0.004, z), (xr, yh - 0.02, z),
                (xr, yh - 0.14, z)], 0.0055, seg=8, cap0=False)
    yc = yh - 0.085
    lathe(k, 'int_fabric_white', [(0.021, -0.05), (0.054, -0.05), (0.058, -0.044), (0.058, 0.044),
                                  (0.054, 0.05), (0.021, 0.05)], seg=16, o=(xr, yc, z), axis=(0, 1, 0), closed=True,
          smooth=[False, True, True, True, False, True])
    # the loose end of the paper
    boxr(k, 'int_fabric_white', (xr + 0.0565, yc - 0.0475, z - 0.07), (xr + 0.0575, yc + 0.0475, z))
    # brush on the floor
    yb = -w / 2 + 0.06
    xbh = x0 + 0.07
    lathe(k, 'int_white_gloss', [(0.0, 0.0), (0.044, 0.0), (0.047, 0.006), (0.048, 0.318)], seg=14,
          o=(xbh, yb, 0.0), smooth=[False, True, True])
    lathe(k, C, [(0.048, 0.318), (0.0485, 0.33), (0.043, 0.337), (0.036, 0.334), (0.0, 0.33)],
          seg=14, o=(xbh, yb, 0.0), smooth=[True, True, True, False])
    tube(k, C, [(xbh, yb, 0.30), (xbh, yb, 0.43)], 0.0065, seg=8)
    lathe(k, C, [(0.0, 0.0), (0.012, 0.004), (0.014, 0.012), (0.01, 0.018), (0.0, 0.02)], seg=10, o=(xbh, yb, 0.43))


def b_bath_mat(k, w, d, rng, color=-1):
    m = fabric_for(rng, color, ('int_fabric_white', 'int_fabric_teal', 'int_fabric_bluegrey', 'int_fabric_dark'))
    slab(k, m, lambda i: rrect(-d / 2 + i, d / 2 - i, -w / 2 + i, w / 2 - i, max(0.005, 0.05 - i), 3), 0.0,
         0.014, 0.006, 2, sup=0.0, cap0=False, bot_bevel=False)


def b_wall_cabinet(k, w, d, rng, z0=1.35, h=0.60):
    x0, x1 = -d / 2, d / 2 - 0.024                  # the knobs stand 24 mm proud
    W = 'int_white_gloss'
    O = 'int_wood_oak'
    z1 = z0 + h
    zn = z0 + 0.20                                   # top of the open niche
    t = 0.018
    xf = x1 - 0.02                                   # carcass front
    # carcass: sides, top, back, niche bottom (oak), shelf between
    for s in (-1, 1):
        yy = s * (w / 2 - t / 2)
        boxr(k, W, (x0, yy - t / 2, z0), (xf, yy + t / 2, z1))
    boxr(k, W, (x0, -w / 2 + t, z1 - t), (xf, w / 2 - t, z1))
    boxr(k, W, (x0, -w / 2 + t, z0), (x0 + 0.008, w / 2 - t, z1 - t))
    boxr(k, O, (x0 + 0.008, -w / 2 + t, z0), (x1, w / 2 - t, z0 + 0.022), rb=0.002)
    boxr(k, W, (x0 + 0.008, -w / 2 + t, zn), (xf, w / 2 - t, zn + t))
    # doors
    nd = 2 if w >= 0.5 else 1
    gap = 0.003
    for j in range(nd):
        ya = -w / 2 + j * w / nd + (gap / 2 if j else 0.0)
        yb = -w / 2 + (j + 1) * w / nd - (gap / 2 if j < nd - 1 else 0.0)
        boxr(k, W, (xf, ya, zn + 0.002), (x1, yb, z1), rb=0.003, bseg=1)
        ky = yb - 0.035 if (nd == 1 or j == 0) else ya + 0.035
        lathe(k, 'int_brass', [(0.005, 0.0), (0.005, 0.012), (0.011, 0.018), (0.0, 0.024)], seg=10,
              o=(x1, ky, zn + 0.05), axis=(1, 0, 0), smooth=[True, True, False])
    # in the niche: rolled towels, a bottle
    zz = z0 + 0.022
    ry = -w / 2 + t + 0.05
    cols = ('int_fabric_white', 'int_fabric_white', 'int_fabric_teal')
    for j in range(3 if w >= 0.5 else 2):
        r = 0.042
        y = ry + j * 0.09
        if y + r > w / 2 - t - 0.12:
            break
        lathe(k, cols[j], [(0.0, 0.0), (r - 0.01, 0.0), (r, 0.008), (r, d - 0.06), (r - 0.01, d - 0.05),
                           (0.0, d - 0.05)], seg=10, o=(x0 + 0.02, y, zz + r), axis=(1, 0, 0),
              smooth=[False, True, True, True, False])
    bottle(k, (x0 + xf) / 2, w / 2 - t - 0.06, zz, 0.024, 0.15, 'int_mint', 'chrome', pump=True)


def b_laundry_basket(k, w, d, rng):
    r = min(w, d) / 2 - 0.016
    rb = r * 0.86
    H = 0.55
    F = 'int_fabric_bluegrey'
    lathe(k, F, [(0.0, 0.0), (rb - 0.01, 0.0), (rb, 0.008), (r - 0.012, H - 0.05)], seg=20, smooth=[False, True, True])
    lathe(k, 'int_fabric_white', [(r - 0.012, H - 0.05), (r + 0.006, H - 0.045), (r + 0.014, H - 0.025),
                                  (r + 0.01, H - 0.004), (r - 0.004, H), (r - 0.016, H - 0.012),
                                  (r - 0.02, H - 0.05)], seg=24)
    lathe(k, F, [(r - 0.02, H - 0.05), (rb - 0.012, 0.03), (0.0, 0.03)], seg=24, smooth=[True, False])
    # handles: leather loops on both sides
    for s in (-1, 1):
        y = s * (r - 0.004)
        pts = [(-0.045, y, H - 0.085), (-0.03, y + s * 0.016, H - 0.11), (0.0, y + s * 0.022, H - 0.118),
               (0.03, y + s * 0.016, H - 0.11), (0.045, y, H - 0.085)]
        tube(k, 'int_accent_red', catmull(pts, 6), 0.007, seg=5)
    # towels heaped in it: two crumpled lumps, white and teal
    for (cx, cy, rad, top, m_, ph) in ((-0.03, 0.025, r * 0.62, H + 0.055, 'int_fabric_white', 0.0),
                                       (0.05, -0.05, r * 0.5, H + 0.035, 'int_fabric_teal', 1.7)):
        rings = []
        seg = 14
        for i, (fr, z) in enumerate([(1.0, H - 0.09), (1.08, H - 0.03), (0.95, top - 0.035), (0.62, top - 0.008),
                                     (0.0, top)]):
            if fr == 0.0:
                rings.append([(cx, cy, z)])
                continue
            ring = []
            for j in range(seg):
                a = TAU * j / seg
                f = 1.0 + 0.16 * math.sin(3 * a + ph + i) + 0.09 * math.sin(5 * a + 2 * i + ph)
                ring.append((cx + rad * fr * f * math.cos(a), cy + rad * fr * f * math.sin(a),
                             z + 0.018 * math.sin(2 * a + i + ph) * (i > 0)))
            rings.append(ring)
        loft(k, m_, rings, True)


def b_plant(k, w, d, rng, species=0, pot=0):
    pm = ('int_ceramic', 'int_pot')[int(pot) % 2]
    m = min(w, d)
    if int(species) == 0:
        rp = clamp(0.34 * m, 0.07, 0.17)
        plant_snake(k, rng, 0.0, 0.0, 0.0, s=clamp(m / 0.35, 0.6, 1.5), mat_pot=pm, r_pot=rp)
    else:
        rp = clamp(0.3 * m, 0.05, 0.15)
        plant_bush(k, rng, 0.0, 0.0, 0.0, s=clamp(m / 0.46, 0.4, 1.6), mat_pot=pm, r_pot=rp, n=22)


BUILDERS = {
    'wc': b_wc, 'basin': b_basin, 'shower_corner': b_shower_corner, 'shower': b_shower, 'bath': b_bath,
    'bath_corner': b_bath_corner, 'towel_rail': b_towel_rail, 'washing_machine': b_washing_machine,
    'wc_set': b_wc_set, 'bath_mat': b_bath_mat, 'wall_cabinet': b_wall_cabinet,
    'laundry_basket': b_laundry_basket, 'bath_plant': b_plant,
}

# default (w, d) per kind, for previews and the table
DEFAULT_SIZE = {
    'wc': (0.45, 0.65), 'basin': (0.60, 0.45), 'shower_corner': (0.80, 0.80), 'shower': (1.95, 0.90),
    'bath': (1.90, 0.75), 'bath_corner': (1.30, 1.30), 'towel_rail': (0.50, 0.12), 'washing_machine': (0.60, 0.60),
    'wc_set': (0.30, 0.16), 'bath_mat': (0.80, 0.50), 'wall_cabinet': (0.60, 0.18), 'laundry_basket': (0.40, 0.40),
    'bath_plant': (0.35, 0.35),
}
# sane limits per kind: (w lo, hi), (d lo, hi)
SIZE_LIMITS = {
    'wc': ((0.34, 0.60), (0.48, 0.80)), 'basin': ((0.40, 1.20), (0.30, 0.60)),
    'shower_corner': ((0.70, 1.60), (0.70, 1.60)), 'shower': ((0.70, 2.40), (0.70, 1.50)),
    'bath': ((1.20, 2.20), (0.60, 0.95)), 'bath_corner': ((1.10, 1.60), (1.10, 1.60)),
    'towel_rail': ((0.35, 0.80), (0.08, 0.20)), 'washing_machine': ((0.55, 0.65), (0.45, 0.70)),
    'wc_set': ((0.22, 0.45), (0.14, 0.25)), 'bath_mat': ((0.30, 1.40), (0.30, 1.00)),
    'wall_cabinet': ((0.30, 1.20), (0.12, 0.30)), 'laundry_basket': ((0.28, 0.55), (0.28, 0.55)),
    'bath_plant': ((0.15, 0.70), (0.15, 0.70)),
}


def build(kind, w, d, seed=0, **params):
    """-> [(material, verts, faces, smooth)] in the LOCAL FRAME (see the
    module docstring)."""
    if kind not in BUILDERS:
        raise ValueError('furn_kit_bath: unknown kind %r' % kind)
    spec = KINDS[kind]['params']
    p = {}
    for name, (dflt, lo, hi) in spec.items():
        v = params.get(name, dflt)
        p[name] = clamp(v, lo, hi) if isinstance(v, (int, float)) else v
    (wl, wh), (dl, dh) = SIZE_LIMITS[kind]
    w = clamp(float(w), wl, wh)
    d = clamp(float(d), dl, dh)
    k = Kit()
    rng = random.Random(seed * 7919 + sum(map(ord, kind)))
    BUILDERS[kind](k, w, d, rng, **p)
    return k.out()


def tri_count(kind, w=None, d=None, **p):
    if w is None or d is None:
        w, d = DEFAULT_SIZE[kind]
    n = 0
    for _m, _v, F, _s in build(kind, w, d, **p):
        for f in F:
            n += len(f) - 2
    return n


def bounds(parts):
    xs, ys, zs = [], [], []
    for _m, V, _f, _s in parts:
        for x, y, z in V:
            xs.append(x)
            ys.append(y)
            zs.append(z)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


# ---------------------------------------------------------------- preview (Blender) / table (any python)
if __name__ == '__main__':
    import sys
    if '--table' in sys.argv or 'bpy' not in sys.modules:
        try:
            import bpy  # noqa: F401
        except ImportError:
            for kd in BUILDERS:
                w_, d_ = DEFAULT_SIZE[kd]
                lo, hi = bounds(build(kd, w_, d_))
                print('%-16s %5d  %.2f x %.2f   box x %.3f..%.3f y %.3f..%.3f z %.3f..%.3f' % (
                    kd, tri_count(kd), w_, d_, lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]))
            sys.exit(0)
    import bpy
    sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    kind = args[0] if args else 'basin'
    w_, d_ = DEFAULT_SIZE[kind]
    if len(args) >= 3:
        w_, d_ = float(args[1]), float(args[2])
    parts = build(kind, w_, d_)
    for i, (m, V, F, S) in enumerate(parts):
        me = bpy.data.meshes.new('%s_%d' % (m, i))
        me.from_pydata(V, [], F)
        for poly in me.polygons:
            poly.use_smooth = S
        ob = bpy.data.objects.new(me.name, me)
        bpy.context.scene.collection.objects.link(ob)
    print('[kit] %s %.2f x %.2f: %d tris' % (kind, w_, d_, tri_count(kind, w_, d_)))
