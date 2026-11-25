# -*- coding: utf-8 -*-
"""Plants and small decor for the furnished flats: a procedural kit.

Pure python (math + random) inside build(); runs under Blender's python and
the system one alike. Run it under Blender for the check renders:

    Blender -b -P blender/furn_kit_plants.py -- [--kinds a,b] [--out DIR] [--views eye,top]

INTERFACE (the integrator relies on it)

    KINDS[kind] = {'drawn', 'params': {name: (default, min, max)}, 'footprint',
                   'wall', 'solid', 'notes'}  (+ 'w', 'd': (default, min, max)
                   and 'sizes': {'S'|'M'|'L': (w, d, {params})} as extras)
    build(kind, w, d, seed=0, **params) -> [(material, verts, faces, smooth)]
    tri_count(kind, w, d, **params) -> int

LOCAL FRAME (lib_furnish / build_furnish): +X is the way the piece faces,
+Y its left, z up, metres, origin on the floor at the centre of the
footprint. w = size ACROSS (local Y), d = size ALONG the facing (local X) -
build_furnish.py draws every box as x in [-d/2, d/2], y in [-w/2, w/2], and
lib_furnish's box size is [across, along]. Faces are wound counter-clockwise
seen from outside; every part is emitted with its own vertices.

Leaves are single-sided cards on purpose: web/materials.js makes `foliage`
and `foliage_b` DoubleSide and shades the face a card is wound toward as the
waxy top and the other as the pale matt underside (frontFacing), so every
blade here is wound toward its top. Neither leaf material needs UVs; the
vertex colour they multiply by falls back to white when the mesh has none
(build_furnish exports none), so a plant gets two greens: foliage (dark,
#4b6128) and foliage_b (lighter, #577331). No material here reads UVs.

Triangles per kind at the default size, seed 0 (M = KINDS[k]['w'/'d'] defaults;
S / L = KINDS[k]['sizes']); other seeds vary by ~10 %:

    kind                M tris  (S / L)
    plant_monstera        770  (566 / 922)
    plant_fiddle          934  (758 / 1110)
    plant_rubber          890  (608 / 1022)
    plant_snake           374  (320 / 446)
    plant_palm            856  (678 / 1034)
    plant_olive           948  (684 / 1014)
    plant_pothos          875  (692 / 1241)
    plant_succulents      864  (864 / 864)
    plant_herbs           942  (942 / 942)
    planter_balcony       838  (384 / 1368)
    plant_loggia_pair     728  (728 / 728)
    decor_vase            732  (625 / 946)
    decor_books           162  (108 / 270)
    decor_bowl            565  (465 / 774)
    decor_candles         623  (623 / 623)
    decor_table_plant     518  (518 / 518)

(`python3 blender/furn_kit_plants.py` prints the exact table.)
"""
import math
import random
import zlib

TAU = 2.0 * math.pi
GOLD = math.pi * (3.0 - math.sqrt(5.0))
UP = (0.0, 0.0, 1.0)
DOWN = (0.0, 0.0, -1.0)


# ------------------------------------------------------------------ vectors
def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def vlen(a):
    return math.sqrt(dot(a, a))


def nrm(a):
    L = vlen(a)
    return (a[0] / L, a[1] / L, a[2] / L) if L > 1e-12 else (0.0, 0.0, 1.0)


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def perp(want, v):
    """Unit component of `want` perpendicular to unit `v` (with a fallback)."""
    p = sub(want, mul(v, dot(want, v)))
    if vlen(p) < 1e-6:
        alt = (1.0, 0.0, 0.0) if abs(v[0]) < 0.9 else (0.0, 1.0, 0.0)
        p = sub(alt, mul(v, dot(alt, v)))
    return nrm(p)


def hdir(az):
    return (math.cos(az), math.sin(az), 0.0)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def reach(w, d, az):
    """Distance from the origin to the footprint ellipse (d along X, w along Y)."""
    rx, ry = max(d, 1e-3) / 2.0, max(w, 1e-3) / 2.0
    c, s = math.cos(az), math.sin(az)
    return 1.0 / math.sqrt((c / rx) ** 2 + (s / ry) ** 2)


def bezier(p0, p1, p2, n):
    out = []
    for i in range(n):
        t = i / float(n - 1)
        a = lerp(p0, p1, t)
        b = lerp(p1, p2, t)
        out.append(lerp(a, b, t))
    return out


def bezier3(p0, p1, p2, p3, n):
    out = []
    for i in range(n):
        t = i / float(n - 1)
        u = 1 - t
        out.append(add(add(mul(p0, u * u * u), mul(p1, 3 * u * u * t)),
                       add(mul(p2, 3 * u * t * t), mul(p3, t * t * t))))
    return out


def along(path, t):
    """Point and unit tangent at arclength fraction t of a polyline."""
    seg = [vlen(sub(b, a)) for a, b in zip(path[:-1], path[1:])]
    tot = sum(seg) or 1e-9
    s = clamp(t, 0.0, 1.0) * tot
    for i, L in enumerate(seg):
        if s <= L or i == len(seg) - 1:
            u = s / L if L > 1e-12 else 0.0
            return lerp(path[i], path[i + 1], clamp(u, 0.0, 1.0)), nrm(sub(path[i + 1], path[i]))
        s -= L
    return path[-1], nrm(sub(path[-1], path[-2]))


def path_len(path):
    return sum(vlen(sub(b, a)) for a, b in zip(path[:-1], path[1:]))


# ------------------------------------------------------------------ meshes
class Mesh(object):
    __slots__ = ('v', 'f')

    def __init__(self):
        self.v = []
        self.f = []


class Kit(object):
    """Parts keyed (material, smooth); each part its own vertex list."""

    def __init__(self):
        self.parts = {}

    def __call__(self, mat, smooth=True):
        k = (mat, bool(smooth))
        if k not in self.parts:
            self.parts[k] = Mesh()
        return self.parts[k]

    def result(self):
        out = []
        for (m, s), me in self.parts.items():
            if me.f:
                out.append((m, [(round(p[0], 5), round(p[1], 5), round(p[2], 5)) for p in me.v],
                            [tuple(f) for f in me.f], s))
        return out


def newell(m, f):
    n = [0.0, 0.0, 0.0]
    for i in range(len(f)):
        a = m.v[f[i]]
        b = m.v[f[(i + 1) % len(f)]]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return tuple(n)


def face_toward(m, f, want):
    """Append face f wound so its normal points along `want`."""
    if dot(newell(m, f), want) < 0:
        f = tuple(reversed(f))
    m.f.append(tuple(f))


def face_out(m, f, centre):
    """Append face f wound away from `centre` (small closed solids)."""
    c = [0.0, 0.0, 0.0]
    for i in f:
        c = [c[0] + m.v[i][0], c[1] + m.v[i][1], c[2] + m.v[i][2]]
    c = (c[0] / len(f), c[1] / len(f), c[2] / len(f))
    face_toward(m, f, sub(c, centre))


def sweep(m, rings):
    """Rings of points (equal counts; a 1-point ring is a pole), stacked in
    profile order. A profile that climbs the OUTSIDE of a surface of
    revolution with every ring counter-clockwise seen from above faces out;
    one that runs inward over a rim faces up, one that runs down an inner
    wall faces the axis - so outer-up, rim-in, inner-down is all right way
    out."""
    idx = []
    for r in rings:
        o = len(m.v)
        m.v.extend(r)
        idx.append(list(range(o, o + len(r))))
    for a, b in zip(idx[:-1], idx[1:]):
        if len(a) == 1 and len(b) == 1:
            continue
        if len(a) == 1:
            n = len(b)
            for j in range(n):
                m.f.append((a[0], b[(j + 1) % n], b[j]))
        elif len(b) == 1:
            n = len(a)
            for j in range(n):
                m.f.append((a[j], a[(j + 1) % n], b[0]))
        else:
            n = len(a)
            for j in range(n):
                k = (j + 1) % n
                m.f.append((a[j], a[k], b[k], b[j]))
    return idx


def fan(m, ring_pts, centre, up=True):
    """Close a ring (CCW seen from above) with a fan to `centre`."""
    o = len(m.v)
    m.v.extend(ring_pts)
    c = len(m.v)
    m.v.append(centre)
    n = len(ring_pts)
    for j in range(n):
        k = (j + 1) % n
        m.f.append((o + j, o + k, c) if up else (o + k, o + j, c))


def circ(cx, cy, z, r, seg, a0=0.0, mod=None, sx=1.0, sy=1.0):
    if r <= 1e-7:
        return [(cx, cy, z)]
    out = []
    for j in range(seg):
        a = a0 + TAU * j / seg
        rr = r * (mod(a) if mod else 1.0)
        out.append((cx + rr * sx * math.cos(a), cy + rr * sy * math.sin(a), z))
    return out


def rrect(cx, cy, z, hx, hy, cr, cs=3):
    """Rounded rectangle ring, counter-clockwise seen from above."""
    cr = max(0.002, min(cr, hx - 0.001, hy - 0.001))
    out = []
    for (qx, qy, a0) in ((hx - cr, hy - cr, 0.0), (-hx + cr, hy - cr, 90.0),
                         (-hx + cr, -hy + cr, 180.0), (hx - cr, -hy + cr, 270.0)):
        for k in range(cs + 1):
            a = math.radians(a0 + 90.0 * k / cs)
            out.append((cx + qx + cr * math.cos(a), cy + qy + cr * math.sin(a), z))
    return out


def tube(m, pts, radii, seg=4, cap_end=True, cap_start=False, tip=0.6, a0=0.0):
    """A round stem along a polyline (parallel-transport frames), outward."""
    n = len(pts)
    if not isinstance(radii, (list, tuple)):
        radii = [radii] * n
    T = []
    for i in range(n):
        if i == 0:
            t = sub(pts[1], pts[0])
        elif i == n - 1:
            t = sub(pts[-1], pts[-2])
        else:
            t = add(nrm(sub(pts[i + 1], pts[i])), nrm(sub(pts[i], pts[i - 1])))
        T.append(nrm(t))
    ref = UP if abs(T[0][2]) < 0.9 else (1.0, 0.0, 0.0)
    N = perp(ref, T[0])
    o = len(m.v)
    for i in range(n):
        if i:
            N = perp(N, T[i])
        B = cross(T[i], N)
        for j in range(seg):
            a = a0 + TAU * j / seg
            c, s = math.cos(a) * radii[i], math.sin(a) * radii[i]
            m.v.append(add(pts[i], add(mul(N, c), mul(B, s))))
    for i in range(n - 1):
        for j in range(seg):
            k = (j + 1) % seg
            m.f.append((o + i * seg + j, o + i * seg + k, o + (i + 1) * seg + k, o + (i + 1) * seg + j))
    if cap_end:
        c = len(m.v)
        m.v.append(add(pts[-1], mul(T[-1], radii[-1] * tip)))
        b = o + (n - 1) * seg
        for j in range(seg):
            m.f.append((b + j, b + (j + 1) % seg, c))
    if cap_start:
        c = len(m.v)
        m.v.append(sub(pts[0], mul(T[0], radii[0] * tip)))
        for j in range(seg):
            m.f.append((o + (j + 1) % seg, o + j, c))


def sphere(m, c, r, seg=8, rings=5, sz=1.0, rnd=None, jitter=0.0):
    rs = []
    for i in range(rings + 1):
        phi = math.pi * (1.0 - i / float(rings))          # bottom pole first
        z = c[2] + r * sz * math.cos(phi)
        rr = r * math.sin(phi)
        if i in (0, rings):
            rs.append([(c[0], c[1], z)])
            continue
        ring = []
        for j in range(seg):
            a = TAU * j / seg + (0.5 * TAU / seg if i % 2 else 0.0)
            k = 1.0 + (rnd.uniform(-jitter, jitter) if rnd else 0.0)
            ring.append((c[0] + rr * k * math.cos(a), c[1] + rr * k * math.sin(a), z))
        rs.append(ring)
    sweep(m, rs)


def box(m, p0, p1):
    x0, y0, z0 = p0
    x1, y1, z1 = p1
    o = len(m.v)
    m.v.extend([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)])
    for f in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        m.f.append(tuple(o + i for i in f))


def xform(pts, origin, ex, ey, ez=UP):
    return [add(origin, add(add(mul(ex, p[0]), mul(ey, p[1])), mul(ez, p[2]))) for p in pts]


def rbox_z(m, cx, cy, z0, z1, hx, hy, cr, cs=2, bev=0.0):
    """Rounded-corner slab with an optional bevel on the top edge."""
    rings = [rrect(cx, cy, z0, hx, hy, cr, cs)]
    if bev > 0:
        rings.append(rrect(cx, cy, z1 - bev, hx, hy, cr, cs))
        rings.append(rrect(cx, cy, z1, hx - bev, hy - bev, cr - bev, cs))
    else:
        rings.append(rrect(cx, cy, z1, hx, hy, cr, cs))
    sweep(m, rings)
    top = rings[-1]
    fan(m, top, (cx, cy, z1), up=True)
    fan(m, rings[0], (cx, cy, z0), up=False)


# ------------------------------------------------------------------ leaves
def leaf_map(base, v, n, L, fold=0.0, cup=0.0, droop=0.0, curl=0.0):
    """Leaf plane -> world. x runs along the midrib (0 at the stalk, L at the
    tip), y across; a polygon counter-clockwise in (x, y) faces n (the top).
    fold lifts the margins by fold*|y| (V: +, tent: -), cup by cup*y^2/L,
    droop sags the tip toward world -z, curl bends the midrib along -n."""
    v = nrm(v)
    n = perp(n, v)
    w = cross(n, v)

    def P(x, y, h=0.0):
        t = x / L if L > 1e-9 else 0.0
        off = h + fold * abs(y) + cup * y * y / max(L, 1e-6) - curl * L * t * t
        p = add(add(base, mul(v, x)), add(mul(w, y), mul(n, off)))
        if droop:
            p = add(p, (0.0, 0.0, -droop * L * t * t))
        return p
    return P


def emit2d(m, P, pts, faces):
    """Vertices given in leaf-plane (x, y[, h]); each face is re-wound to be
    counter-clockwise in the plane, i.e. to face the leaf's top."""
    o = len(m.v)
    for p in pts:
        m.v.append(P(*p))
    for f in faces:
        a = 0.0
        for i in range(len(f)):
            x0, y0 = pts[f[i]][0], pts[f[i]][1]
            x1, y1 = pts[f[(i + 1) % len(f)]][0], pts[f[(i + 1) % len(f)]][1]
            a += x0 * y1 - x1 * y0
        if a < 0:
            f = tuple(reversed(f))
        m.f.append(tuple(o + i for i in f))


def blade2d(L, rows, hws, wave=0.0, rnd=None, cols=3, midlift=0.0):
    """A simple leaf blade: rows (fractions of L along the midrib) and half
    widths (fractions of L); the last row with hw 0 is a tip point."""
    pts, faces, R = [], [], []
    for i, (t, hw) in enumerate(zip(rows, hws)):
        x = t * L
        if hw <= 1e-6:
            R.append([len(pts)])
            pts.append((x, 0.0, 0.0))
            continue
        h = 0.0
        if wave and rnd is not None and 0 < i < len(rows) - 1:
            h = rnd.uniform(-wave, wave) * L
        row = []
        ys = (-1.0, 0.0, 1.0) if cols == 3 else (-1.0, -0.45, 0.0, 0.45, 1.0)
        for s in ys:
            row.append(len(pts))
            pts.append((x, s * hw * L, (h if abs(s) == 1.0 else (midlift * L if s == 0 else h * 0.4))))
        R.append(row)
    for a, b in zip(R[:-1], R[1:]):
        if len(a) == 1 and len(b) == 1:
            continue
        if len(a) == 1:
            for j in range(len(b) - 1):
                faces.append((a[0], b[j], b[j + 1]))
        elif len(b) == 1:
            for j in range(len(a) - 1):
                faces.append((a[j], a[j + 1], b[0]))
        else:
            for j in range(len(a) - 1):
                faces.append((a[j], a[j + 1], b[j + 1], b[j]))
    return pts, faces


def ribbon(m, centres, across, hws, normals, fold=0.0, mid=True):
    """A strap leaf along a centreline: rows of (left, [mid,] right); a row
    with hw 0 is a point. fold lifts the margins toward the normal by
    fold*hw (a channel). Faces turned toward the local normal."""
    rows = []
    for c, a, hw, nn in zip(centres, across, hws, normals):
        if hw <= 1e-6:
            rows.append([len(m.v)])
            m.v.append(c)
            continue
        lift = mul(nn, fold * hw)
        r = [len(m.v)]
        m.v.append(add(add(c, mul(a, -hw)), lift))
        if mid:
            r.append(len(m.v))
            m.v.append(c)
        r.append(len(m.v))
        m.v.append(add(add(c, mul(a, hw)), lift))
        rows.append(r)
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        want = add(normals[i], normals[i + 1])
        if len(a) == 1 and len(b) == 1:
            continue
        if len(b) == 1:
            for j in range(len(a) - 1):
                face_toward(m, (a[j], a[j + 1], b[0]), want)
        elif len(a) == 1:
            for j in range(len(b) - 1):
                face_toward(m, (a[0], b[j], b[j + 1]), want)
        else:
            for j in range(len(a) - 1):
                face_toward(m, (a[j], a[j + 1], b[j + 1], b[j]), want)


def grow(p0, d0, length, n, bend_to=DOWN, bend=0.0, bend_pow=1.0, wiggle=0.0, rnd=None):
    """A centreline that starts along d0 and bends toward bend_to."""
    pts = [p0]
    d = nrm(d0)
    ds = length / float(n - 1)
    p = p0
    for i in range(1, n):
        t = i / float(n - 1)
        k = bend * (t ** bend_pow) * ds * 3.0
        d = nrm(add(d, mul(bend_to, k)))
        if wiggle and rnd is not None:
            d = nrm(add(d, (rnd.uniform(-wiggle, wiggle), rnd.uniform(-wiggle, wiggle), rnd.uniform(-wiggle, wiggle) * 0.5)))
        p = add(p, mul(d, ds))
        pts.append(p)
    return pts


def pillow(m, base, v, n, L, W, T, shoulder=0.55, centre_lift=0.0):
    """A small thick succulent leaf: top and underside meeting at the base
    and the tip, so it is closed and round-shouldered."""
    v = nrm(v)
    n = perp(n, v)
    w = cross(n, v)

    def P(x, y, z):
        return add(base, add(add(mul(v, x), mul(w, y)), mul(n, z)))
    o = len(m.v)
    m.v.extend([P(0, 0, 0), P(L, 0, T * 0.25),
                P(shoulder * L, -W / 2, T * 0.35), P(shoulder * L, W / 2, T * 0.35),
                P(shoulder * L * 0.9, 0, T * (0.55 + centre_lift)),
                P(shoulder * L, -W * 0.42, -T * 0.25), P(shoulder * L, W * 0.42, -T * 0.25),
                P(shoulder * L * 0.9, 0, -T * 0.45)])
    cen = P(shoulder * L * 0.8, 0, 0)
    b, t, l, r, tm, lb, rb, bm = range(o, o + 8)
    for f in ((b, l, tm), (b, tm, r), (l, t, tm), (tm, t, r),
              (b, bm, lb), (b, rb, bm), (lb, bm, t), (bm, rb, t),
              (b, lb, l), (l, lb, t), (b, r, rb), (r, t, rb)):
        face_out(m, f, cen)


# ------------------------------------------------------------------ pots
POT_MATS = ('int_pot', 'int_white_gloss', 'int_ceramic', 'int_stone_dark')
POT_STYLES = ('cyl', 'taper', 'belly', 'bowl', 'tall', 'square')
PROFILES = {
    # (r / R, z / H) up the outside; the last row is the rim's outer edge
    'cyl': [(0.90, 0.0), (0.975, 0.025), (1.0, 0.085), (1.0, 1.0)],
    'taper': [(0.70, 0.0), (0.735, 0.03), (1.0, 1.0)],
    'belly': [(0.62, 0.0), (0.80, 0.09), (0.95, 0.30), (1.0, 0.55), (0.95, 0.80), (0.88, 1.0)],
    'bowl': [(0.52, 0.0), (0.58, 0.05), (0.88, 0.45), (1.0, 1.0)],
    'tall': [(0.78, 0.0), (0.80, 0.02), (0.95, 0.90), (1.02, 0.915), (1.02, 1.0)],
    'square': [(0.86, 0.0), (0.90, 0.03), (1.0, 1.0)],
}


def pot(K, mat, cx, cy, D, H, style='cyl', seg=18, soil_drop=None, wall=None, aspect=1.0, a0=0.0):
    """A planter with a real rim and wall thickness, and its soil.
    -> dict(z_soil, r_in (inner radius at the soil), R, H)."""
    R = D / 2.0
    t = wall if wall else clamp(R * 0.075, 0.005, 0.022)
    if soil_drop is None:
        soil_drop = clamp(H * 0.09, 0.012, 0.05)
    prof = PROFILES[style]
    square = style == 'square'

    def ring(r, z):
        if square:
            off = R - r
            return rrect(cx, cy, z, R * aspect - off, R - off, R * 0.22 - off * 0.5, 3)
        return circ(cx, cy, z, r, seg, a0)
    outer = [ring(rf * R, zf * H) for rf, zf in prof]
    sweep(K(mat, True), outer)
    rt = prof[-1][0] * R
    sweep(K(mat, False), [ring(rt, H), ring(rt - t, H)])
    r_in = rt - t * 1.15
    zs = H - soil_drop
    sweep(K(mat, True), [ring(rt - t, H), ring(r_in, zs)])
    # flat-shaded: the soil meets the inner wall at a crease, and the two
    # would share smoothed normals once welded
    fan(K('soil', False), ring(r_in, zs), (cx, cy, zs + min(0.012, D * 0.03)))
    return dict(z_soil=zs, r_in=r_in, R=R, H=H)


def pick_pot(rng, mat_p, style_p, styles, mats=POT_MATS):
    st = styles[int(style_p)] if style_p is not None and style_p >= 0 and int(style_p) < len(styles) \
        else styles[rng.randrange(len(styles))]
    mt = POT_MATS[int(mat_p)] if mat_p is not None and 0 <= mat_p < len(POT_MATS) \
        else mats[rng.randrange(len(mats))]
    return st, mt


# ================================================================== plants
def b_monstera(K, w, d, rng, h=1.1, pot_d=0.32, leaves=8, pot_style=-1, pot_mat=-1):
    st, mt = pick_pot(rng, pot_mat, pot_style, ('cyl', 'belly', 'taper'))
    P = pot(K, mt, 0, 0, pot_d, pot_d * 0.92, st, seg=18)
    zs, rin = P['z_soil'], P['r_in']
    n = int(round(leaves))
    Lmax = clamp(0.34 * h + 0.06, 0.20, 0.56)
    phase = rng.uniform(0, TAU)
    stem = K('foliage_b', True)
    blade = K('foliage', True)
    for i in range(n):
        age = i / float(max(1, n - 1))          # 0 = oldest, outermost
        az = phase + i * GOLD * 1.0 + rng.uniform(-0.25, 0.25)
        out = hdir(az)
        L = Lmax * (1.0 - 0.38 * age) * rng.uniform(0.88, 1.08)
        e = (-0.25 + 0.95 * age) + rng.uniform(-0.15, 0.15)       # blade pitch
        e = clamp(e, -0.35, 0.95)
        rr = reach(w, d, az) * 0.97
        hor = L * math.cos(e) * 0.95
        ra = clamp(rr - hor, 0.06, rr * 0.7)
        L = min(L, (rr - 0.04) / max(0.4, math.cos(e)))
        top = h - zs
        za = zs + (top - L * max(0.12, math.sin(e)) - 0.02) * (0.45 + 0.55 * age) * rng.uniform(0.9, 1.05)
        za = max(za, zs + 0.15)
        b0 = (rng.uniform(-0.35, 0.35) * rin, rng.uniform(-0.35, 0.35) * rin, zs - 0.01)
        att = add(mul(out, ra), (0.0, 0.0, za))
        ctrl = (b0[0] + out[0] * ra * 0.5, b0[1] + out[1] * ra * 0.5, zs + (za - zs) * 0.72)
        pts = bezier(b0, ctrl, att, 5)
        tube(stem, pts, [0.011, 0.0095, 0.008, 0.007, 0.006], seg=4, cap_end=False)
        v = nrm(add(mul(out, math.cos(e)), (0.0, 0.0, math.sin(e))))
        nn = perp(add(UP, mul(out, 0.35 + 0.4 * max(0, e))), v)
        mature = L > 0.22
        monstera_leaf(blade, att, v, nn, L, rng, mature)


def monstera_leaf(m, base, v, n, L, rng, mature):
    N = 6 if mature else 5
    C, a, b = 0.40 * L, 0.60 * L, 0.43 * L
    phi0 = math.pi - 0.40
    fin = rng.uniform(0.30, 0.40) if mature else 1.0
    P = leaf_map(base, v, n, L, fold=-0.05, cup=-0.10, droop=0.10 + rng.uniform(0, 0.08))
    pts, faces = [], []
    tip = None
    mid = {}

    def midv(x):
        k = round(x, 5)
        if k not in mid:
            mid[k] = len(pts)
            pts.append((x, 0.0, 0.0))
        return mid[k]
    for side in (-1.0, 1.0):
        E, M = [], []
        lastm = 0.0
        for k in range(N + 1):
            ph = phi0 * (1.0 - k / float(N))
            ex = C + a * math.cos(ph)
            ey = side * b * math.sin(ph) * (1.0 + 0.10 * math.sin(ph))
            mx = clamp(ex - abs(ey) * 0.55, 0.0, L)
            mx = max(mx, lastm + (0.04 * L if k else 0.0)) if k < N else L
            lastm = mx
            E.append((ex, ey))
            M.append(mx)
        if tip is None:
            tip = midv(L)
        mids = [midv(x) if k < N else tip for k, x in enumerate(M)]
        inner = []
        for k in range(N + 1):
            if k == N:
                inner.append(tip)
                continue
            if fin >= 1.0:
                inner.append(None)
                continue
            x = M[k] + (E[k][0] - M[k]) * fin
            y = E[k][1] * fin
            inner.append(len(pts))
            pts.append((x, y, 0.0))
        if fin >= 1.0:
            # a juvenile leaf: entire, no slits
            e_idx = []
            for k in range(N + 1):
                if k == N:
                    e_idx.append(tip)
                else:
                    e_idx.append(len(pts))
                    pts.append((E[k][0], E[k][1], 0.0))
            for k in range(N):
                q = [mids[k], mids[k + 1], e_idx[k + 1], e_idx[k]]
                q = [x for i, x in enumerate(q) if x not in q[:i]]
                if len(q) >= 3:
                    faces.append(tuple(q))
            continue
        gap = rng.uniform(0.06, 0.10)
        for k in range(N):
            q = [mids[k], mids[k + 1], inner[k + 1], inner[k]]
            q = [x for i, x in enumerate(q) if x not in q[:i]]
            if len(q) >= 3:
                faces.append(tuple(q))
            if k == N - 1:
                lo = lerp((E[k][0], E[k][1], 0), (E[k + 1][0], E[k + 1][1], 0), gap * 0.6)
                o = len(pts)
                pts.append((lo[0], lo[1], 0.0))
                faces.append((inner[k], tip, o))
                continue
            g0 = 0.0 if k == 0 else gap
            lo = lerp((E[k][0], E[k][1], 0), (E[k + 1][0], E[k + 1][1], 0), g0)
            hi = lerp((E[k + 1][0], E[k + 1][1], 0), (E[k][0], E[k][1], 0), gap)
            o = len(pts)
            pts.append((lo[0], lo[1], 0.0))
            pts.append((hi[0], hi[1], 0.0))
            faces.append((inner[k], inner[k + 1], o + 1, o))
    emit2d(m, P, pts, faces)


def b_fiddle(K, w, d, rng, h=1.6, pot_d=0.34, leaves=28, pot_style=-1, pot_mat=-1):
    st, mt = pick_pot(rng, pot_mat, pot_style, ('cyl', 'taper', 'belly'))
    P = pot(K, mt, 0, 0, pot_d, pot_d * 0.95, st, seg=16)
    zs = P['z_soil']
    top = h - 0.04
    lean = hdir(rng.uniform(0, TAU))
    trunk = bezier3((0, 0, zs - 0.02), add((0, 0, zs + (top - zs) * 0.35), mul(lean, 0.03)),
                    add((0, 0, zs + (top - zs) * 0.7), mul(lean, -0.02)),
                    add((0, 0, top), mul(lean, 0.04)), 7)
    r0 = clamp(0.012 * h + 0.004, 0.012, 0.03)
    tube(K('bark', True), trunk, [r0 * (1.0 - 0.6 * i / 6.0) for i in range(7)], seg=6)
    n = int(round(leaves))
    phase = rng.uniform(0, TAU)
    bl = K('foliage', True)
    for i in range(n):
        t = 0.22 + 0.78 * (i / float(max(1, n - 1))) ** 0.75
        p, tan = along(trunk, t)
        az = phase + i * GOLD + rng.uniform(-0.2, 0.2)
        out = hdir(az)
        e = -0.05 + 0.95 * t ** 2.5 + rng.uniform(-0.15, 0.15)
        L = clamp(0.25 * h ** 0.6, 0.20, 0.40) * (1.05 - 0.40 * t ** 3) * rng.uniform(0.88, 1.1)
        rr = reach(w, d, az) * 1.05
        L = min(L, rr / max(0.35, math.cos(e)))
        v = nrm(add(mul(out, math.cos(e)), (0, 0, math.sin(e))))
        nn = perp(add(UP, mul(out, 0.5)), v)
        base = add(p, mul(out, r0 * 0.8))
        pts, faces = blade2d(L, [0.0, 0.08, 0.30, 0.52, 0.72, 0.88, 1.0],
                             [0.02, 0.14, 0.25, 0.30, 0.34, 0.27, 0.0], wave=0.03, rnd=rng)
        emit2d(bl, leaf_map(base, v, nn, L, fold=0.08, cup=0.10, droop=0.10 + 0.12 * (1 - t)), pts, faces)


def b_rubber(K, w, d, rng, h=1.2, pot_d=0.30, leaves=24, pot_style=-1, pot_mat=-1):
    st, mt = pick_pot(rng, pot_mat, pot_style, ('cyl', 'belly', 'square'))
    P = pot(K, mt, 0, 0, pot_d, pot_d * 0.9, st, seg=16)
    zs, rin = P['z_soil'], P['r_in']
    ns = 3 if h > 0.9 else 2
    phase = rng.uniform(0, TAU)
    stems = []
    for s in range(ns):
        az = phase + TAU * s / ns + rng.uniform(-0.3, 0.3)
        out = hdir(az)
        hs = (h - zs - 0.05) * (1.0 if s == 0 else rng.uniform(0.62, 0.85))
        lean = rng.uniform(0.06, 0.20) * (0.0 if s == 0 else 1.0) + 0.04
        b0 = add(mul(out, rin * 0.25), (0, 0, zs - 0.02))
        p3 = add(add(b0, mul(out, hs * lean)), (0, 0, hs))
        pts = bezier3(b0, add(b0, (0, 0, hs * 0.35)), add(add(b0, mul(out, hs * lean * 0.6)), (0, 0, hs * 0.7)), p3, 6)
        r0 = clamp(0.007 * h + 0.004, 0.008, 0.017)
        tube(K('bark', True), pts, [r0 * (1 - 0.5 * i / 5.0) for i in range(6)], seg=5, cap_end=False)
        # the red sheath of the next leaf, at the tip
        tp, tt = along(pts, 1.0)
        tube(K('int_accent_red', True), [tp, add(tp, mul(nrm(add(tt, (0, 0, 0.3))), 0.07 * h ** 0.5))],
             [r0 * 0.6, r0 * 0.35], seg=4, tip=1.6)
        stems.append(pts)
    n = int(round(leaves))
    per = [n // ns + (1 if k < n % ns else 0) for k in range(ns)]
    bl = K('foliage', True)
    for s, pts in enumerate(stems):
        m = per[s]
        ph = rng.uniform(0, TAU)
        for i in range(m):
            t = 0.12 + 0.84 * i / float(max(1, m - 1))
            p, tan = along(pts, t)
            az = ph + i * 2.4 + rng.uniform(-0.3, 0.3)
            out = hdir(az)
            e = -0.05 + 0.85 * t ** 1.5 + rng.uniform(-0.12, 0.12)
            L = clamp(0.22 * h ** 0.4, 0.16, 0.30) * (1.05 - 0.35 * t ** 2) * rng.uniform(0.9, 1.1)
            rr = reach(w, d, az) * 1.05
            L = min(L, max(0.06, rr - vlen((p[0], p[1], 0))) / max(0.35, math.cos(e)))
            v = nrm(add(mul(out, math.cos(e)), (0, 0, math.sin(e))))
            nn = perp(add(UP, mul(out, 0.6)), v)
            # a short petiole
            pe = add(p, mul(v, 0.012))
            pts2, faces = blade2d(L, [0.0, 0.07, 0.28, 0.52, 0.76, 0.92, 1.0],
                                  [0.02, 0.16, 0.25, 0.26, 0.20, 0.09, 0.0], wave=0.01, rnd=rng)
            emit2d(bl, leaf_map(pe, v, nn, L, fold=0.06, cup=0.08, droop=0.05), pts2, faces)


def b_snake(K, w, d, rng, h=0.75, pot_d=0.24, leaves=11, pot_style=-1, pot_mat=-1):
    st, mt = pick_pot(rng, pot_mat, pot_style, ('cyl', 'taper', 'square'))
    P = pot(K, mt, 0, 0, pot_d, pot_d * 0.85, st, seg=16)
    zs, rin = P['z_soil'], P['r_in']
    n = int(round(leaves))
    phase = rng.uniform(0, TAU)
    for i in range(n):
        az = phase + i * GOLD + rng.uniform(-0.2, 0.2)
        out = hdir(az)
        rad = rin * 0.65 * math.sqrt((i + 0.5) / n)
        base = add(mul(out, rad), (0, 0, zs - 0.015))
        outer = (i + 0.5) / n
        Lh = (h - zs) * (1.0 - 0.30 * outer) * rng.uniform(0.88, 1.02)
        lean = (0.02 + 0.16 * outer) * rng.uniform(0.7, 1.2)
        rr = reach(w, d, az) * 0.95
        lean = min(lean, max(0.0, (rr - rad - 0.03)) / max(Lh, 0.1) * 1.4)
        d0 = nrm(add(UP, mul(out, lean * 0.6)))
        cen = grow(base, d0, Lh, 6, bend_to=out, bend=lean * 0.25, bend_pow=1.0)
        wd = clamp(0.075 * (h / 0.75) ** 0.5, 0.045, 0.095) * rng.uniform(0.85, 1.15)
        tw0 = az + math.pi / 2 + rng.uniform(-0.5, 0.5)
        twist = rng.uniform(-0.6, 0.6)
        across, normals = [], []
        for k, c in enumerate(cen):
            _, tn = along(cen, k / 5.0)
            a = perp(hdir(tw0 + twist * k / 5.0), tn)
            across.append(a)
            normals.append(nrm(cross(tn, a)) if dot(cross(tn, a), out) >= 0 else mul(nrm(cross(tn, a)), -1))
        hws = [wd * f / 2 for f in (0.45, 0.85, 1.0, 0.95, 0.70, 0.0)]
        ribbon(K('foliage' if i % 5 else 'foliage_b', True), cen, across, hws, normals, fold=0.35)


def b_palm(K, w, d, rng, h=1.5, pot_d=0.36, fronds=8, pot_style=-1, pot_mat=-1):
    st, mt = pick_pot(rng, pot_mat, pot_style, ('cyl', 'taper', 'belly'))
    P = pot(K, mt, 0, 0, pot_d, pot_d * 0.92, st, seg=16)
    zs, rin = P['z_soil'], P['r_in']
    n = int(round(fronds))
    phase = rng.uniform(0, TAU)
    stem = K('foliage_b', True)
    pin = K('foliage', True)
    for i in range(n):
        age = i / float(max(1, n - 1))          # 0 = old (low, spreading)
        az = phase + i * GOLD + rng.uniform(-0.2, 0.2)
        out = hdir(az)
        base = add(mul(out, rin * 0.3 * rng.random()), (0, 0, zs - 0.02))
        lean = (0.40 - 0.32 * age) * rng.uniform(0.8, 1.2)
        d0 = nrm(add(mul(UP, math.cos(lean)), mul(out, math.sin(lean))))
        # unit-length frond: a straight-ish stalk, then a rachis arching over
        path = grow(base, d0, 1.0, 8, bend_to=add(mul(out, 0.5), DOWN), bend=0.22 + 0.85 * (1 - age) ** 1.5,
                    bend_pow=1.3)
        lp_max = clamp(0.30 * (h / 1.5) ** 0.7, 0.18, 0.40)
        ztop = max(q[2] for q in path) - base[2]
        hreach = max(vlen((q[0], q[1], 0)) for q in path)
        want_top = (h - zs) * (0.80 + 0.20 * age) * rng.uniform(0.95, 1.02)
        rr = reach(w, d, az) * 1.0 - lp_max * 0.35
        sc = min(want_top / max(1e-3, ztop), max(0.1, rr) / max(1e-3, hreach))
        path = [add(base, mul(sub(q, base), sc)) for q in path]
        sp = path[:3] + path[3::2]
        tube(stem, sp, [0.0075 - 0.0045 * k / (len(sp) - 1) for k in range(len(sp))], seg=3, cap_end=True)
        pairs = 14
        lp_max *= clamp(sc / 1.2, 0.6, 1.0)
        for k in range(pairs):
            u = k / float(pairs - 1)
            t = 0.22 + 0.76 * u
            p, tn = along(path, t)
            side = perp(cross(tn, UP), tn) if abs(tn[2]) < 0.98 else perp(cross(out, UP), tn)
            lp = lp_max * (0.55 + 0.6 * math.sin(math.pi * (0.2 + 0.75 * u))) * (1.0 - 0.5 * u)
            lp *= rng.uniform(0.9, 1.08)
            for sgn in (-1.0, 1.0):
                dp = nrm(add(add(mul(tn, 0.5), mul(side, sgn * 0.85)), (0, 0, -0.25)))
                nn = perp(add(UP, mul(side, -sgn * 0.25)), dp)
                wp = lp * 0.06
                pts = [(0.0, 0.0, 0.0), (0.33 * lp, -wp, 0.35 * wp), (lp, 0.0, 0.0), (0.33 * lp, wp, 0.35 * wp)]
                emit2d(pin, leaf_map(p, dp, nn, lp, droop=0.8), pts, [(0, 1, 2), (0, 2, 3)])


def b_olive(K, w, d, rng, h=1.7, pot_d=0.40, leaves=260, pot_style=-1, pot_mat=-1):
    """A potted olive standard: gnarled trunk, scaffold branches and a
    rounded crown of leaf sprays at the twig ends."""
    st, mt = pick_pot(rng, pot_mat, pot_style, ('tall', 'taper', 'square'),
                      mats=('int_pot', 'int_stone_dark', 'int_white_gloss'))
    Hp = pot_d * (1.25 if st == 'tall' else 1.0)
    P = pot(K, mt, 0, 0, pot_d, Hp, st, seg=16)
    zs = P['z_soil']
    crx, cry = d / 2.0 * 0.92, w / 2.0 * 0.92
    zt = zs + (h - zs) * 0.40                      # top of the clear trunk
    crz = (h - zt) * 0.5
    zcc = h - crz                                  # crown centre
    lean = hdir(rng.uniform(0, TAU))
    tr = [(0, 0, zs - 0.02)]
    for k in range(1, 6):
        t = k / 5.0
        j = (rng.uniform(-1, 1) * 0.02, rng.uniform(-1, 1) * 0.02, 0)
        tr.append(add(add((0, 0, zs + (zt - zs) * t), mul(lean, 0.05 * math.sin(t * 3))), j))
    r0 = clamp(0.020 * h, 0.024, 0.042)
    bark = K('bark', True)
    tube(bark, tr, [r0 * (1.15 - 0.3 * k / 5.0) for k in range(6)], seg=6, cap_end=True, tip=0.2)
    nb = 5
    phase = rng.uniform(0, TAU)
    branches = []
    for b in range(nb):
        az = phase + TAU * b / nb + rng.uniform(-0.3, 0.3)
        out = hdir(az)
        tgt = (out[0] * crx * 0.40, out[1] * cry * 0.40, zcc + crz * rng.uniform(-0.2, 0.25))
        p0, _ = along(tr, rng.uniform(0.85, 1.0))
        mid = add(lerp(p0, tgt, 0.5), (rng.uniform(-1, 1) * 0.03, rng.uniform(-1, 1) * 0.03, -0.03))
        bp = [p0, mid, tgt]
        tube(bark, bp, [r0 * 0.55, r0 * 0.38, r0 * 0.22], seg=4, cap_end=True, tip=0.5)
        branches.append(bp)
    # twig ends on the crown's shell; each twig grows from the nearest branch
    n = int(round(leaves))
    nt = max(14, int(round(n / 9.0)))
    lw = K('foliage_b', True)
    lw2 = K('foliage', True)
    for i in range(nt):
        z = 1.0 - 2.0 * (i + 0.5) / nt
        z = z * 0.85 + 0.05
        r = math.sqrt(max(0.0, 1.0 - z * z))
        a = i * GOLD + rng.uniform(-0.2, 0.2)
        sh = rng.uniform(0.75, 1.0)
        end = (r * math.cos(a) * crx * sh, r * math.sin(a) * cry * sh, zcc + z * crz * sh)
        best = None
        for bp in branches:
            for t in (0.5, 0.75, 1.0):
                q, _ = along(bp, t)
                dd = vlen(sub(end, q))
                if best is None or dd < best[0]:
                    best = (dd, q)
        q = best[1]
        tp = [q, end]
        tube(bark, tp, [r0 * 0.11, r0 * 0.05], seg=3, cap_end=False)
        tdir = nrm(sub(end, q))
        outw = nrm((end[0], end[1], (end[2] - zcc) * 0.5 + 0.001))
        m = max(4, n // nt // 2)
        for k in range(m):
            t = 0.12 + 0.88 * (k + 0.5) / m
            p, tn = along(tp, t)
            side = perp(cross(tn, UP), tn)
            rot = k * 1.7
            sd = nrm(add(mul(side, math.cos(rot)), mul(perp(UP, tn), math.sin(rot) * 0.7)))
            for sgn in (-1.0, 1.0):
                L = rng.uniform(0.085, 0.11) * clamp(h / 1.7, 0.85, 1.1)
                Wd = L * rng.uniform(0.17, 0.21)
                dv = nrm(add(add(mul(tn, 0.55), mul(sd, sgn * 0.9)), add(mul(outw, 0.25), (0, 0, rng.uniform(-0.25, 0.3)))))
                nn = perp(add(add(UP, mul(outw, 0.8)), (rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5), 0)), dv)
                pts = [(0.0, 0.0, 0.0), (0.42 * L, -Wd / 2, 0.0), (L, 0.0, 0.0), (0.42 * L, Wd / 2, 0.0)]
                emit2d(lw if (k + i) % 4 else lw2, leaf_map(p, dv, nn, L, fold=0.25, droop=0.1), pts,
                       [(0, 1, 2), (0, 2, 3)])


def heart_leaf(m, base, v, n, L, rng, fold=0.12):
    Wd = L * 0.72
    pts = [(0.0, 0.0, 0.0), (-0.06 * L, -0.30 * Wd, 0.0), (0.36 * L, -0.50 * Wd, 0.0), (1.0 * L, 0.0, 0.0),
           (0.36 * L, 0.50 * Wd, 0.0), (-0.06 * L, 0.30 * Wd, 0.0), (0.42 * L, 0.0, 0.025 * L)]
    faces = [(0, 1, 6), (1, 2, 6), (2, 3, 6), (3, 4, 6), (4, 5, 6), (5, 0, 6)]
    emit2d(m, leaf_map(base, v, n, L, fold=fold, droop=0.12), pts, faces)


def b_pothos(K, w, d, rng, shelf_z=1.7, trail=0.8, vines=5, pot_d=0.16, pot_style=-1, pot_mat=-1):
    """A floating oak shelf on the wall (local -X) with a trailing pothos."""
    x0 = -d / 2.0
    th = 0.028
    oak = K('int_wood_oak', False)
    rbox_z(oak, 0.0, 0.0, shelf_z - th, shelf_z, d / 2.0, w / 2.0, 0.006, cs=1, bev=0.003)
    md = K('metal_dark', False)
    for sy in (-1.0, 1.0):
        y = sy * (w / 2.0 - 0.07)
        box(md, (x0, y - 0.006, shelf_z - th - 0.14), (x0 + 0.012, y + 0.006, shelf_z - th))
        box(md, (x0, y - 0.006, shelf_z - th - 0.012), (x0 + d * 0.8, y + 0.006, shelf_z - th))
    st, mt = pick_pot(rng, pot_mat, pot_style, ('belly', 'cyl', 'bowl'), mats=('int_white_gloss', 'int_ceramic', 'int_pot'))
    pd = min(pot_d, d * 0.85, w * 0.6)
    py = rng.uniform(-0.2, 0.2) * (w / 2.0 - pd / 2.0)
    pxc = x0 + d / 2.0 + 0.01
    start = {k: len(me.v) for k, me in K.parts.items()}
    Pp = pot(K, mt, pxc, py, pd, pd * 0.85, st, seg=16)
    # lift the pot onto the shelf
    for k, me in K.parts.items():
        s = start.get(k, 0)
        me.v[s:] = [(p[0], p[1], p[2] + shelf_z) for p in me.v[s:]]
    zs = Pp['z_soil'] + shelf_z
    leafm = K('foliage', True)
    leafb = K('foliage_b', True)
    vine = K('foliage_b', True)
    nv = int(round(vines))
    phase = rng.uniform(-0.5, 0.5)
    # a crown of leaves in the pot
    for i in range(9):
        az = i * GOLD + phase
        o = hdir(az)
        b0 = (pxc + o[0] * pd * 0.12, py + o[1] * pd * 0.12, zs)
        v = nrm(add(mul(o, 0.8), (0, 0, rng.uniform(0.2, 0.9))))
        L = rng.uniform(0.07, 0.10)
        tip = add(b0, mul(v, 0.05))
        tube(vine, [b0, tip], [0.003, 0.0025], seg=3, cap_end=False)
        heart_leaf(leafm if i % 3 else leafb, tip, nrm(add(v, (0, 0, -0.3))), perp(add(UP, mul(o, 0.6)), v), L, rng)
    for k in range(nv):
        # vines leave the rim, run over the shelf edge and hang
        side = (k / float(max(1, nv - 1)) - 0.5) * 2.0          # -1 .. 1 along the shelf
        az = rng.uniform(-0.9, 0.9) * 0.9 + side * 0.9
        o = hdir(az)
        b0 = (pxc + o[0] * pd * 0.45, py + o[1] * pd * 0.45, zs + 0.01)
        ex = (d / 2.0 + rng.uniform(0.01, 0.04), clamp(py + o[1] * 0.25 + side * w * 0.25, -w / 2 + 0.03, w / 2 - 0.03), shelf_z + 0.01)
        Lh = trail * rng.uniform(0.45, 1.0)
        sway = rng.uniform(-0.12, 0.12)
        hang_bot = (ex[0] + rng.uniform(0.02, 0.08), ex[1] + sway, max(0.35, shelf_z - Lh))
        path = bezier3(b0, (b0[0] + 0.05, b0[1], zs + 0.06), (ex[0] + 0.02, ex[1], ex[2] + 0.04), ex, 4)
        nh = max(3, int(Lh / 0.13))
        hang = [lerp(ex, hang_bot, (i / float(nh)) ** 1.0) for i in range(1, nh + 1)]
        hang = [add(p, (0.015 * math.sin(i * 1.3 + k), 0.02 * math.sin(i * 0.7 + k * 2), 0)) for i, p in enumerate(hang)]
        path = path + hang
        tube(vine, path, [0.0032] * len(path), seg=3, cap_end=True)
        # leaves, alternating, every ~8 cm, smaller toward the tip
        Lp = path_len(path)
        nl = max(3, int(Lp / 0.085))
        for i in range(nl):
            t = (i + 0.6) / nl
            p, tn = along(path, t)
            sgn = 1.0 if i % 2 else -1.0
            outw = nrm((1.0, sgn * 0.6 + rng.uniform(-0.3, 0.3), 0.0))
            L = rng.uniform(0.07, 0.11) * (1.0 - 0.4 * t)
            v = nrm(add(add(mul(outw, 0.8), mul(tn, 0.4)), (0, 0, -0.35)))
            nn = perp(add(outw, (0, 0, 0.8)), v)
            heart_leaf(leafm if (i + k) % 3 else leafb, p, v, nn, L, rng)


def b_succulents(K, w, d, rng, lift=0.0):
    """Three small pots in a row along local Y: cactus, echeveria, haworthia..."""
    kinds = ['column', 'echeveria', 'haworthia', 'globe']
    rng.shuffle(kinds)
    kinds = kinds[:3]
    if 'column' not in kinds and rng.random() < 0.6:
        kinds[0] = 'column'
    n = 3
    slot = w / n
    for i, kd in enumerate(kinds):
        cy = -w / 2 + slot * (i + 0.5) + rng.uniform(-0.01, 0.01)
        cx = rng.uniform(-0.15, 0.15) * d
        D = clamp(min(slot * 0.86, d * 0.9) * rng.uniform(0.82, 1.0), 0.06, 0.16)
        st, mt = pick_pot(rng, -1, -1, ('cyl', 'bowl', 'taper', 'belly'))
        H = D * (0.62 if st == 'bowl' else 0.92) * rng.uniform(0.9, 1.1)
        P = pot(K, mt, cx, cy, D, H, st, seg=12, soil_drop=0.008)
        zs = P['z_soil']
        rin = P['r_in']
        if kd == 'column':
            R = rin * 0.55
            Hc = D * rng.uniform(1.3, 2.2)
            ribs = rng.choice((7, 8, 9))
            mod = lambda a, ribs=ribs: 1.0 + 0.13 * math.cos(ribs * a)
            rings = [circ(cx, cy, zs - 0.004, R * 0.92, ribs * 2, 0, mod)]
            for zf, rf in ((0.08, 1.0), (0.62, 0.98), (0.84, 0.86), (0.95, 0.55)):
                rings.append(circ(cx, cy, zs + Hc * zf, R * rf, ribs * 2, 0, mod))
            rings.append([(cx, cy, zs + Hc)])
            sweep(K('foliage', False), rings)
            if rng.random() < 0.6:
                # a side arm
                az = rng.uniform(0, TAU)
                o = hdir(az)
                p0 = (cx + o[0] * R * 0.6, cy + o[1] * R * 0.6, zs + Hc * 0.4)
                p1 = add(p0, add(mul(o, R * 1.2), (0, 0, 0.004)))
                p2 = add(p1, (0, 0, Hc * 0.28))
                tube(K('foliage', False), [p0, p1, p2], [R * 0.5, R * 0.48, R * 0.44], seg=8, tip=0.9)
        elif kd == 'globe':
            R = rin * 0.78
            ribs = 9
            mod = lambda a: 1.0 + 0.09 * math.cos(9 * a)
            rings = [circ(cx, cy, zs - 0.004, R * 0.8, 18, 0, mod)]
            for zf, rf in ((0.3, 0.98), (0.65, 0.88), (0.9, 0.50)):
                rings.append(circ(cx, cy, zs + R * 1.5 * zf, R * rf, 18, 0, mod))
            rings.append([(cx, cy, zs + R * 1.45)])
            sweep(K('foliage_b', False), rings)
        elif kd == 'echeveria':
            Rr = rin * 1.45
            k = 0
            for ring, (cnt, Lf, el) in enumerate(((7, 0.62, 0.22), (6, 0.48, 0.55), (4, 0.33, 0.95))):
                for j in range(cnt):
                    az = TAU * j / cnt + ring * 0.45 + rng.uniform(-0.1, 0.1)
                    o = hdir(az)
                    L = Rr * Lf * rng.uniform(0.92, 1.08)
                    v = nrm(add(mul(o, math.cos(el)), (0, 0, math.sin(el))))
                    nn = perp(UP, v)
                    b0 = (cx + o[0] * Rr * 0.08, cy + o[1] * Rr * 0.08, zs + 0.006 + ring * 0.006)
                    pillow(K('foliage_b', True), b0, v, nn, L, L * 0.62, L * 0.16)
                    k += 1
        else:   # haworthia / aloe: an upright spiky rosette
            Rr = rin * 1.3
            cnt = 13
            for j in range(cnt):
                az = j * GOLD
                o = hdir(az)
                el = 0.55 + 0.8 * (j / float(cnt))
                L = Rr * rng.uniform(0.9, 1.25) * (1.15 - 0.35 * j / cnt)
                v = nrm(add(mul(o, math.cos(el)), (0, 0, math.sin(el))))
                nn = perp(add(UP, mul(o, -0.3)), v)
                b0 = (cx + o[0] * Rr * 0.06, cy + o[1] * Rr * 0.06, zs + 0.004)
                pillow(K('foliage', True), b0, v, nn, L, L * 0.30, L * 0.12, shoulder=0.35)
    if lift:
        for me in K.parts.values():
            me.v = [(p[0], p[1], p[2] + lift) for p in me.v]


def b_herbs(K, w, d, rng, lift=0.0, tray=1):
    """Kitchen herbs: basil, rosemary, chives in three pots on an oak tray."""
    z0 = 0.0
    if tray >= 0.5:
        rbox_z(K('int_wood_oak', False), 0.0, 0.0, 0.0, 0.016, d / 2.0, w / 2.0, 0.012, cs=2, bev=0.003)
        z0 = 0.016
    order = ['basil', 'rosemary', 'chives']
    rng.shuffle(order)
    slot = w / 3.0
    st, mt = pick_pot(rng, -1, -1, ('cyl', 'taper', 'belly'),
                      mats=('int_white_gloss', 'int_ceramic', 'int_white_gloss', 'int_pot'))
    for i, herb in enumerate(order):
        cy = -w / 2 + slot * (i + 0.5)
        D = clamp(min(slot * 0.88, d * 0.88), 0.07, 0.15)
        H = D * 0.95
        start = {k: len(me.v) for k, me in K.parts.items()}
        P = pot(K, mt, 0.0, cy, D, H, st, seg=12, soil_drop=0.01)
        zs = P['z_soil'] + z0
        rin = P['r_in']
        # lift this pot onto the tray
        for k, me in K.parts.items():
            s = start.get(k, 0)
            me.v[s:] = [(p[0], p[1], p[2] + z0) for p in me.v[s:]]
        hh = D * rng.uniform(1.6, 2.2)
        if herb == 'basil':
            st_m = K('foliage_b', True)
            nst = 6
            for s in range(nst):
                o = hdir(s * GOLD + rng.uniform(0, 1))
                b0 = (o[0] * rin * 0.3, cy + o[1] * rin * 0.3, zs - 0.004)
                top = add(b0, add(mul(o, rin * rng.uniform(0.5, 1.0)), (0, 0, hh * rng.uniform(0.45, 0.75))))
                path = [b0, lerp(b0, top, 0.5), top]
                tube(st_m, path, [0.0025, 0.002, 0.0015], seg=3)
                pairs = 3
                for k in range(pairs):
                    t = 0.45 + 0.55 * k / (pairs - 1)
                    p, tn = along(path, t)
                    sd = perp(hdir(k * 1.57 + s), tn)
                    for sgn in (-1.0, 1.0):
                        L = rng.uniform(0.05, 0.065) * (1.2 - 0.4 * t)
                        dv = nrm(add(mul(sd, sgn), (0, 0, rng.uniform(-0.05, 0.4))))
                        pts = [(0, 0, 0), (0.42 * L, -0.34 * L, 0), (L, 0, 0), (0.42 * L, 0.34 * L, 0), (0.42 * L, 0, 0.12 * L)]
                        emit2d(st_m, leaf_map(p, dv, perp(UP, dv), L, cup=0.6, droop=0.15), pts,
                               [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)])
        elif herb == 'rosemary':
            st_m = K('foliage', True)
            nd = K('foliage', True)
            for s in range(6):
                o = hdir(s * GOLD + rng.uniform(0, 1))
                b0 = (o[0] * rin * 0.45 * rng.random(), cy + o[1] * rin * 0.45 * rng.random(), zs - 0.004)
                dd = nrm(add(UP, mul(o, rng.uniform(0.05, 0.35))))
                path = grow(b0, dd, hh * rng.uniform(0.75, 1.1), 3, bend_to=o, bend=0.1)
                tube(st_m, path, [0.0018, 0.0014, 0.001], seg=3, cap_end=False)
                for k in range(13):
                    t = 0.15 + 0.83 * k / 12.0
                    p, tn = along(path, t)
                    sd = perp(hdir(k * 2.4), tn)
                    L = 0.03 * (1.1 - 0.4 * t)
                    dv = nrm(add(mul(sd, 1.0), mul(tn, 0.4)))
                    pts = [(0, -0.003, 0), (L, 0, 0), (0, 0.003, 0)]
                    emit2d(nd, leaf_map(p, dv, perp(UP, dv), L), pts, [(0, 1, 2)])
        else:   # chives
            bl = K('foliage', True)
            for s in range(18):
                o = hdir(s * GOLD)
                b0 = (o[0] * rin * 0.55 * math.sqrt(rng.random()), cy + o[1] * rin * 0.55 * math.sqrt(rng.random()), zs - 0.004)
                dd = nrm(add(UP, mul(o, rng.uniform(0.05, 0.4))))
                Lb = hh * rng.uniform(0.8, 1.15)
                cen = grow(b0, dd, Lb, 4, bend_to=add(o, DOWN), bend=rng.uniform(0.1, 0.5), bend_pow=2)
                across = [perp(cross(o, UP), along(cen, k / 3.0)[1]) for k in range(4)]
                normals = [nrm(cross(across[k], along(cen, k / 3.0)[1])) for k in range(4)]
                ribbon(bl, cen, across, [0.0025, 0.0024, 0.002, 0.0], normals, fold=0.0, mid=False)
    if lift:
        for me in K.parts.values():
            me.v = [(p[0], p[1], p[2] + lift) for p in me.v]


def boxwood(K, c, R, rng, sz=1.0, cards=46):
    sphere(K('foliage', True), c, R * 0.90, seg=8, rings=5, sz=sz, rnd=rng, jitter=0.05)
    m = K('foliage_b', True)
    for i in range(cards):
        # Fibonacci sphere, upper part denser
        z = 1.0 - 2.0 * (i + 0.5) / cards
        z = z * 0.9 + 0.1
        r = math.sqrt(max(0.0, 1.0 - z * z))
        a = i * GOLD
        nrmv = (r * math.cos(a), r * math.sin(a), z)
        p = (c[0] + nrmv[0] * R * 0.93, c[1] + nrmv[1] * R * 0.93, c[2] + nrmv[2] * R * 0.93 * sz)
        tdir = perp((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1)), nrmv)
        L = R * rng.uniform(0.24, 0.32)
        b0 = sub(p, mul(tdir, L * 0.5))
        pts = [(0, 0, 0), (0.5 * L, -0.28 * L, 0.0), (L, 0, 0), (0.5 * L, 0.28 * L, 0.0)]
        emit2d(m, leaf_map(b0, tdir, nrmv, L, fold=0.1, cup=-0.3), pts, [(0, 1, 2), (0, 2, 3)])


def grass_tuft(m, c, R, H, rng, n=16, spread=1.0):
    for i in range(n):
        o = hdir(i * GOLD + rng.uniform(-0.3, 0.3))
        b0 = (c[0] + o[0] * R * 0.3 * rng.random(), c[1] + o[1] * R * 0.3 * rng.random(), c[2] - 0.004)
        out = rng.uniform(0.05, 0.45) * spread
        Lb = H * rng.uniform(0.8, 1.1) * (1.0 + 0.3 * out)
        d0 = nrm(add(UP, mul(o, out)))
        cen = grow(b0, d0, Lb, 4, bend_to=add(mul(o, 0.6), DOWN), bend=rng.uniform(0.08, 0.35) * spread, bend_pow=1.5)
        across, normals = [], []
        for k in range(4):
            _, tn = along(cen, k / 3.0)
            a = perp(cross(o, UP), tn)
            across.append(a)
            nn = nrm(cross(a, tn))
            normals.append(nn if nn[2] >= 0 else mul(nn, -1))
        wb = rng.uniform(0.005, 0.008)
        ribbon(m, cen, across, [wb, wb * 0.9, wb * 0.6, 0.0], normals, fold=0.3, mid=False)


def lavender(K, c, R, H, rng):
    lf = K('foliage_b', True)
    for i in range(10):
        o = hdir(i * GOLD)
        b0 = (c[0] + o[0] * R * 0.25, c[1] + o[1] * R * 0.25, c[2] - 0.004)
        cen = grow(b0, nrm(add(UP, mul(o, 0.8))), H * 0.35, 3, bend_to=DOWN, bend=0.3)
        across = [perp(cross(o, UP), along(cen, k / 2.0)[1]) for k in range(3)]
        normals = [nrm(add(UP, mul(o, 0.2))) for k in range(3)]
        ribbon(lf, cen, across, [0.003, 0.0025, 0.0], normals, mid=False)
    stem = K('foliage_b', True)
    head = K('int_fabric_bluegrey', True)
    for i in range(9):
        o = hdir(i * GOLD + 0.4)
        b0 = (c[0] + o[0] * R * 0.2, c[1] + o[1] * R * 0.2, c[2])
        top = add(b0, add(mul(o, R * rng.uniform(0.4, 0.9)), (0, 0, H * rng.uniform(0.8, 1.05))))
        tube(stem, [b0, lerp(b0, top, 0.6), top], [0.0016, 0.0014, 0.0012], seg=3, cap_end=False)
        dvec = nrm(sub(top, lerp(b0, top, 0.6)))
        hl = H * 0.22
        tube(head, [top, add(top, mul(dvec, hl * 0.5)), add(top, mul(dvec, hl))], [0.0045, 0.006, 0.004], seg=4,
             cap_start=True, tip=1.2)


def b_planter(K, w, d, rng, box_h=0.38, plant_h=0.45, pot_mat=-1):
    """A long planter box along local Y (w = its length): grasses, clipped
    box balls and lavender. Its back (local -X) goes against the balustrade."""
    mt = POT_MATS[int(pot_mat)] if 0 <= pot_mat < len(POT_MATS) else rng.choice(('int_pot', 'int_stone_dark', 'int_white_gloss'))
    R = d / 2.0
    t = clamp(R * 0.1, 0.012, 0.025)

    def ring(off, z):
        return rrect(0.0, 0.0, z, R - off, w / 2.0 - off, 0.03 - off * 0.3, 2)
    outer = [ring(0.012, 0.0), ring(0.004, 0.02), ring(0.0, box_h)]
    sweep(K(mt, True), outer)
    sweep(K(mt, False), [ring(0.0, box_h), ring(t, box_h)])
    zs = box_h - 0.035
    sweep(K(mt, True), [ring(t, box_h), ring(t + 0.002, zs)])
    fan(K('soil', False), ring(t + 0.002, zs), (0, 0, zs + 0.008))
    slots = max(2, int(round(w / 0.26)))
    pattern = rng.choice((('grass', 'ball', 'lav'), ('ball', 'grass', 'grass', 'lav'), ('lav', 'grass', 'ball')))
    gm = K('foliage', True)
    for i in range(slots):
        y = -w / 2.0 + (w - 0.04) * (i + 0.5) / slots + 0.02
        kind = pattern[i % len(pattern)]
        x = rng.uniform(-0.15, 0.15) * (R - t)
        c = (x, y, zs)
        sl = (w / slots) / 2.0
        if kind == 'grass':
            grass_tuft(gm, c, min(R - t, sl), plant_h, rng, n=20, spread=0.7)
        elif kind == 'ball':
            Rb = clamp(min(R - t, sl) * 1.0, 0.08, plant_h * 0.45)
            boxwood(K, (x, y, zs + Rb * 0.82), Rb, rng, cards=56)
        else:
            lavender(K, c, min(R - t, sl), plant_h * 0.9, rng)


def b_loggia(K, w, d, rng, pot_h=0.55, plant_h=0.9, species=-1, pot_mat=-1):
    """A matching pair of tall pots, side by side along local Y."""
    mt = POT_MATS[int(pot_mat)] if 0 <= pot_mat < len(POT_MATS) else rng.choice(('int_pot', 'int_stone_dark', 'int_white_gloss'))
    st = rng.choice(('tall', 'square', 'taper'))
    D = clamp(min(d, w / 2.0 - 0.06), 0.25, 0.6)
    sp = int(species) if species >= 0 else rng.randrange(3)
    for i, sy in enumerate((-1.0, 1.0)):
        cy = sy * (w / 4.0 + 0.0)
        cy = sy * min(w / 2.0 - D / 2.0, max(D / 2.0 + 0.04, w / 4.0))
        P = pot(K, mt, 0.0, cy, D, pot_h, st, seg=18)
        zs = P['z_soil']
        kind = ('ball', 'grass')[i] if sp == 2 else ('ball', 'grass')[sp % 2] if sp < 2 else 'ball'
        if kind == 'ball':
            Rb = clamp(D * 0.62, 0.13, 0.30)
            ztop = pot_h + plant_h
            zc = ztop - Rb
            stem_top = zc - Rb * 0.6
            tube(K('bark', True), [(0, cy, zs - 0.01), (0.005, cy, (zs + stem_top) / 2), (0, cy, stem_top + 0.02)],
                 [0.016, 0.013, 0.011], seg=5, cap_end=False)
            boxwood(K, (0.0, cy, zc), Rb, rng, cards=70)
            # a little underplanting of moss-ish leaves at the foot
            for k in range(8):
                o = hdir(k * GOLD)
                b0 = (o[0] * P['r_in'] * 0.6, cy + o[1] * P['r_in'] * 0.6, zs)
                v = nrm(add(o, (0, 0, 0.25)))
                pts = [(0, 0, 0), (0.05, -0.02, 0), (0.1, 0, 0), (0.05, 0.02, 0)]
                emit2d(K('foliage_b', True), leaf_map(b0, v, UP, 0.1, fold=0.2, droop=0.2), pts, [(0, 1, 2), (0, 2, 3)])
        else:
            grass_tuft(K('foliage_b', True), (0.0, cy, zs), P['r_in'] * 0.8, plant_h, rng, n=44, spread=0.6)


# ================================================================== decor
def b_vase(K, w, d, rng, h=0.6, vase_h=0.26, stems=4, finish=-1, lift=0.0):
    mats = ('int_ceramic', 'int_white_gloss', 'int_stone_dark', 'int_pot')
    mt = mats[int(finish)] if 0 <= finish < len(mats) else rng.choice(mats)
    R = min(w, d) / 2.0
    H = vase_h
    shape = rng.randrange(2)
    if shape == 0:     # bottle: round belly, narrow neck, flared lip
        prof = [(0.62, 0.0), (0.86, 0.06), (1.0, 0.25), (0.96, 0.45), (0.62, 0.68), (0.34, 0.80), (0.30, 0.93), (0.38, 1.0)]
    else:              # tall ovoid
        prof = [(0.58, 0.0), (0.80, 0.08), (0.98, 0.35), (0.96, 0.62), (0.70, 0.88), (0.56, 1.0)]
    seg = 16
    rings = [circ(0, 0, z * H, r * R, seg) for r, z in prof]
    sweep(K(mt, True), rings)
    rt = prof[-1][0] * R
    t = clamp(R * 0.08, 0.004, 0.008)
    sweep(K(mt, False), [circ(0, 0, H, rt, seg), circ(0, 0, H, rt - t, seg)])
    sweep(K(mt, True), [circ(0, 0, H, rt - t, seg), circ(0, 0, H - 0.06, rt - t * 1.3, seg),
                        [(0, 0, H - 0.07)]])
    # eucalyptus stems
    bk = K('bark', True)
    lf = K('foliage_b', True)
    n = int(round(stems))
    for s in range(n):
        az = s * GOLD + rng.uniform(0, 1)
        o = hdir(az)
        b0 = (o[0] * (rt - t) * 0.3, o[1] * (rt - t) * 0.3, H - 0.06)
        top_z = h * rng.uniform(0.82, 1.0)
        lean = rng.uniform(0.15, 0.45)
        Ls = (top_z - b0[2]) / math.cos(lean * 0.7)
        path = grow(b0, nrm(add(UP, mul(o, lean))), Ls, 5, bend_to=add(o, DOWN), bend=0.25, bend_pow=1.5)
        tube(bk, path, [0.0025, 0.0022, 0.0019, 0.0016, 0.0012], seg=3, cap_end=True)
        pairs = 5
        for k in range(pairs):
            tt = 0.35 + 0.63 * k / (pairs - 1)
            p, tn = along(path, tt)
            sd = perp(hdir(az + math.pi / 2 + k * 1.2), tn)
            for sgn in (-1.0, 1.0):
                Lr = rng.uniform(0.032, 0.045) * (1.1 - 0.35 * tt) * clamp(h / 0.6, 0.8, 1.2)
                dv = nrm(add(mul(sd, sgn), mul(tn, 0.3)))
                nn = perp(add(UP, mul(o, 0.6)), dv)
                ring = [(0.0, 0.0, 0.0)]
                for j in range(5):
                    a = math.pi * (j / 4.0)
                    ring.append((Lr * 0.5 - Lr * 0.5 * math.cos(a), Lr * 0.48 * math.sin(a), 0.0))
                for j in range(1, 4):
                    a = math.pi * (j / 4.0)
                    ring.append((Lr * 0.5 + Lr * 0.5 * math.cos(a), -Lr * 0.48 * math.sin(a), 0.0))
                pts = [(Lr * 0.5, 0.0, 0.08 * Lr)] + ring[1:]
                m_ = len(pts) - 1
                faces = [(0, 1 + j, 1 + (j + 1) % m_) for j in range(m_)]
                emit2d(lf, leaf_map(p, dv, nn, Lr, cup=0.2, droop=0.1), pts, faces)
    if lift:
        for me in K.parts.values():
            me.v = [(p[0], p[1], p[2] + lift) for p in me.v]


BOOK_MATS = ('int_fabric_teal', 'int_fabric_bluegrey', 'int_fabric_dark', 'int_fabric_orange', 'int_wood_walnut',
             'int_fabric_white', 'int_mint', 'int_accent_red', 'int_black')


def b_books(K, w, d, rng, n=3, lift=0.0):
    """A stack of hardbacks, the spines toward the front (+X) or the back."""
    z = 0.0
    pages = K('int_fabric_white', False)
    cm = list(BOOK_MATS)
    rng.shuffle(cm)
    nb = int(round(n))
    for i in range(nb):
        bw = w * rng.uniform(0.70, 0.98) * (1.0 - 0.06 * i)      # across (y)
        bd = d * rng.uniform(0.75, 0.98) * (1.0 - 0.05 * i)      # spine to fore-edge (x)
        th = rng.uniform(0.018, 0.045)
        ang = rng.uniform(-0.12, 0.12)
        sx = 1.0 if rng.random() < 0.75 else -1.0               # spine side
        ca, sa = math.cos(ang), math.sin(ang)
        mat = cm[i % len(cm)]
        cover = K(mat, False)
        coverS = K(mat, True)
        bt = 0.0025
        start_c, start_s, start_p = len(cover.v), len(coverS.v), len(pages.v)
        # boards (x from fore-edge to spine), page block between them
        x0, x1 = -bd / 2, bd / 2
        box(cover, (x0, -bw / 2, 0.0), (x1 - th * 0.35, bw / 2, bt))
        box(cover, (x0, -bw / 2, th - bt), (x1 - th * 0.35, bw / 2, th))
        box(pages, (x0 + 0.003, -bw / 2 + 0.003, bt), (x1 - th * 0.35, bw / 2 - 0.003, th - bt))
        # rounded spine: half a tube along y
        r = th / 2.0
        cxs = x1 - th * 0.35
        ring = []
        segs = 5
        for j in range(segs + 1):
            a = -math.pi / 2 + math.pi * j / segs
            ring.append((cxs + r * 0.75 * math.cos(a), r + r * math.sin(a)))
        o = len(coverS.v)
        for (x, zz) in ring:
            coverS.v.append((x, -bw / 2, zz))
        for (x, zz) in ring:
            coverS.v.append((x, bw / 2, zz))
        m_ = segs + 1
        for j in range(segs):
            face_toward(coverS, (o + j, o + j + 1, o + m_ + j + 1, o + m_ + j),
                        (ring[j][0] + ring[j + 1][0] - 2 * cxs, 0, ring[j][1] + ring[j + 1][1] - 2 * r))
        for yy, base in ((-1.0, o), (1.0, o + m_)):
            for j in range(1, segs - 1 + 1):
                face_toward(coverS, (base, base + j, base + j + 1), (0, yy, 0))
        # turn and lift this book
        for me, s in ((cover, start_c), (coverS, start_s), (pages, start_p)):
            me.v[s:] = [(sx * (ca * p[0] - sa * p[1]), sx * (sa * p[0] + ca * p[1]), p[2] + z + lift) for p in me.v[s:]]
        if sx < 0:
            # a turn of 180 deg about z (sx flips both x and y): still a rotation
            pass
        z += th


def b_bowl(K, w, d, rng, fruit=3, finish=-1, lift=0.0):
    mats = ('int_wood_walnut', 'int_ceramic', 'int_stone_dark', 'int_brass')
    mt = mats[int(finish)] if 0 <= finish < len(mats) else rng.choice(mats)
    R = min(w, d) / 2.0
    H = R * 0.42
    seg = 16
    t = clamp(R * 0.05, 0.004, 0.009)
    outer = [(0.36, 0.0), (0.40, 0.04), (0.62, 0.30), (0.88, 0.70), (1.0, 1.0)]
    sweep(K(mt, True), [circ(0, 0, z * H, r * R, seg) for r, z in outer])
    sweep(K(mt, False), [circ(0, 0, H, R, seg), circ(0, 0, H, R - t, seg)])
    inner = [(1.0, 1.0), (0.80, 0.62), (0.45, 0.22), (0.0, 0.12)]
    prof_in = [((R - t) * r, H * z + (t * 0.6 if z < 0.9 else 0)) for r, z in inner]
    rings = [circ(0, 0, z, r, seg) for r, z in prof_in]
    sweep(K(mt, True), rings)
    fan(K(mt, True), circ(0, 0, 0.0, outer[0][0] * R, seg), (0, 0, 0.0), up=False)
    nf = int(round(fruit))
    if nf <= 0:
        return

    def floor_z(rho, rf):
        best = 0.0
        for (r0, z0), (r1, z1) in zip(prof_in[:-1], prof_in[1:]):
            for k in range(5):
                u = k / 4.0
                rr, zz = r0 + (r1 - r0) * u, z0 + (z1 - z0) * u
                for s in (rr, -rr):
                    dx = rho - s
                    if abs(dx) < rf:
                        best = max(best, zz + math.sqrt(rf * rf - dx * dx))
        return best
    placed = []
    ring_n = min(nf, 4)
    rf0 = clamp(R * 0.30, 0.035, 0.045)
    ph = rng.uniform(0, TAU)
    for i in range(nf):
        kind = 'int_fabric_orange' if (i + int(ph * 10)) % 3 else 'int_accent_red'
        rf = rf0 * rng.uniform(0.92, 1.05)
        if i < ring_n:
            a = ph + TAU * i / ring_n
            rho = (R - t) * 0.42 if ring_n > 1 else 0.0
            x, y = rho * math.cos(a), rho * math.sin(a)
            zc = floor_z(rho, rf)
        else:
            a = ph + TAU * (i + 0.5) / max(1, nf - ring_n) + 0.3
            rho = (R - t) * 0.12
            x, y = rho * math.cos(a), rho * math.sin(a)
            zc = floor_z(rho, rf)
        for (px, py, pz, pr) in placed:
            dd = math.hypot(x - px, y - py)
            if dd < pr + rf:
                zc = max(zc, pz + math.sqrt((pr + rf) ** 2 - dd * dd))
        placed.append((x, y, zc, rf))
        sphere(K(kind, True), (x, y, zc), rf, seg=10, rings=6, sz=(0.92 if kind == 'int_fabric_orange' else 0.95))
        if kind == 'int_accent_red':
            tube(K('bark', True), [(x, y, zc + rf * 0.85), (x + 0.003, y, zc + rf * 1.15)], [0.0018, 0.0014], seg=3)
    if lift:
        for me in K.parts.values():
            me.v = [(p[0], p[1], p[2] + lift) for p in me.v]


def b_candles(K, w, d, rng, tray=1, lift=0.0):
    z0 = 0.0
    if tray >= 0.5:
        # an oval brass tray with a raised lip
        seg = 20
        sx, sy = d / 2.0, w / 2.0
        R = 1.0
        prof = [(0.94, 0.0), (0.97, 0.004), (1.0, 0.016)]
        sweep(K('int_brass', True), [circ(0, 0, z, r, seg, sx=sx, sy=sy) for r, z in prof])
        sweep(K('int_brass', False), [circ(0, 0, 0.016, 1.0, seg, sx=sx, sy=sy), circ(0, 0, 0.016, 0.96, seg, sx=sx, sy=sy)])
        sweep(K('int_brass', True), [circ(0, 0, 0.016, 0.96, seg, sx=sx, sy=sy), circ(0, 0, 0.004, 0.92, seg, sx=sx, sy=sy)])
        fan(K('int_brass', True), circ(0, 0, 0.004, 0.92, seg, sx=sx, sy=sy), (0, 0, 0.004))
        fan(K('int_brass', True), circ(0, 0, 0.0, 0.94, seg, sx=sx, sy=sy), (0, 0, 0.0), up=False)
        z0 = 0.004
    hs = sorted([rng.uniform(0.08, 0.11), rng.uniform(0.12, 0.16), rng.uniform(0.17, 0.22)])
    order = [1, 2, 0] if rng.random() < 0.5 else [0, 2, 1]
    span = w * 0.62
    for i in range(3):
        H = hs[order[i]]
        r = clamp(min(d * 0.30, w * 0.12), 0.022, 0.04) * rng.uniform(0.92, 1.05)
        y = -span / 2 + span * i / 2.0
        x = rng.uniform(-0.08, 0.08) * d + (0.012 if i == 1 else -0.006)
        seg = 12
        wax = K('int_fabric_white', True)
        prof = [(0.97, 0.0), (1.0, 0.004), (1.0, H - 0.010), (0.97, H - 0.003), (0.90, H)]
        sweep(wax, [circ(x, y, z0 + z, r * f, seg) for f, z in prof])
        # the burnt-down dish of the top
        sweep(wax, [circ(x, y, z0 + H, r * 0.90, seg), circ(x, y, z0 + H - 0.004, r * 0.55, seg),
                    [(x, y, z0 + H - 0.006)]])
        tube(K('int_black', True), [(x, y, z0 + H - 0.006), (x + 0.001, y, z0 + H + 0.008)], [0.0012, 0.0009], seg=3)
    if lift:
        for me in K.parts.values():
            me.v = [(p[0], p[1], p[2] + lift) for p in me.v]


def b_table_plant(K, w, d, rng, h=0.28, pot_d=0.12, pot_style=-1, pot_mat=-1, lift=0.0):
    """A Chinese money plant (Pilea peperomioides): round coin leaves held
    flat on long stalks from one upright stem - it reads from any side."""
    st, mt = pick_pot(rng, pot_mat, pot_style, ('cyl', 'belly', 'bowl'), mats=('int_white_gloss', 'int_ceramic', 'int_pot'))
    pd = min(pot_d, min(w, d) * 0.7)
    P = pot(K, mt, 0, 0, pd, pd * (0.65 if st == 'bowl' else 0.9), st, seg=14, soil_drop=0.01)
    zs = P['z_soil']
    stem = K('foliage_b', True)
    sh = (h - zs) * 0.55
    sp = [(0, 0, zs - 0.005), (0.004, 0.002, zs + sh * 0.5), (0.0, 0.004, zs + sh)]
    tube(stem, sp, [0.005, 0.0045, 0.004], seg=4)
    lf = K('foliage', True)
    n = 18
    for i in range(n):
        t = 0.15 + 0.85 * (i / float(n - 1))
        p, _ = along(sp, t)
        az = i * GOLD
        o = hdir(az)
        rr = reach(w, d, az) * 0.95
        el = -0.15 + 1.1 * t + rng.uniform(-0.1, 0.1)
        Lp = (rr - 0.03) * (0.85 - 0.35 * t) * rng.uniform(0.85, 1.0)
        tip = add(p, add(mul(o, Lp * math.cos(el)), (0, 0, Lp * max(0.05, math.sin(el)) * 0.8)))
        tip = (tip[0], tip[1], min(tip[2], h - 0.01))
        tube(stem, [p, tip], [0.0016, 0.0012], seg=3, cap_end=False)
        Rl = clamp(0.026 + 0.012 * (1 - t), 0.02, 0.042) * rng.uniform(0.9, 1.1) * clamp(h / 0.28, 0.8, 1.25)
        nn = nrm(add(UP, mul(o, 0.35 + rng.uniform(0, 0.4))))
        v = perp(o, nn)
        w_ = cross(nn, v)
        cen = add(tip, mul(nn, 0.004))
        ring = []
        for j in range(10):
            a = TAU * j / 10
            ring.append(add(add(cen, mul(v, Rl * math.cos(a))), add(mul(w_, Rl * math.sin(a)), mul(nn, -Rl * 0.12))))
        o0 = len(lf.v)
        lf.v.extend(ring)
        lf.v.append(add(cen, mul(nn, Rl * 0.05)))
        for j in range(10):
            face_toward(lf, (o0 + j, o0 + (j + 1) % 10, o0 + 10), nn)
    if lift:
        for me in K.parts.values():
            me.v = [(p[0], p[1], p[2] + lift) for p in me.v]


# ================================================================== table
def _pp():
    return {'pot_style': (-1, -1, 2), 'pot_mat': (-1, -1, 3)}


FLOOR_NOTES = ('Not on the sheets: the integrator chooses where (a free room corner, beside the sofa or a '
               'window, at least 0.15 m off walls). Collide with the pot only: a circle of radius pot_d/2 at '
               'the origin; the leaves overhang and may be walked under/through at the edges. ')

KINDS = {
    'plant_monstera': dict(
        drawn=False, w=(0.95, 0.6, 1.3), d=(0.95, 0.6, 1.3),
        params=dict(h=(1.1, 0.6, 1.6), pot_d=(0.32, 0.22, 0.42), leaves=(8, 4, 11), **_pp()),
        footprint='w x d = the leaf spread (ellipse inscribed in the box, d along local X, w along local Y); '
                  'the pot (pot_d) stands at the origin; h = top leaf above the floor',
        wall=False, solid=True,
        notes=FLOOR_NOTES + 'Split-leaf philodendron: green petioles (foliage_b), split leaves (foliage). '
              'pot_style 0..2 = cylinder/belly/taper, pot_mat 0..3 = int_pot/int_white_gloss/int_ceramic/'
              'int_stone_dark (-1 = by seed).',
        sizes={'S': (0.70, 0.70, dict(h=0.75, pot_d=0.24, leaves=6)), 'M': (0.95, 0.95, {}),
               'L': (1.25, 1.25, dict(h=1.5, pot_d=0.40, leaves=10))}),
    'plant_fiddle': dict(
        drawn=False, w=(0.70, 0.45, 0.95), d=(0.70, 0.45, 0.95),
        params=dict(h=(1.6, 1.0, 2.1), pot_d=(0.34, 0.26, 0.44), leaves=(28, 14, 36), **_pp()),
        footprint='w x d = the crown spread (ellipse in the box); pot at the origin; h = the top',
        wall=False, solid=True,
        notes=FLOOR_NOTES + 'Fiddle-leaf fig: one bark trunk, big wavy violin leaves spiralling up.',
        sizes={'S': (0.55, 0.55, dict(h=1.1, pot_d=0.28, leaves=20)), 'M': (0.70, 0.70, {}),
               'L': (0.90, 0.90, dict(h=2.0, pot_d=0.42, leaves=36))}),
    'plant_rubber': dict(
        drawn=False, w=(0.60, 0.4, 0.85), d=(0.60, 0.4, 0.85),
        params=dict(h=(1.2, 0.7, 1.8), pot_d=(0.30, 0.22, 0.40), leaves=(24, 12, 32), **_pp()),
        footprint='w x d = the crown spread; pot at the origin; h = the top',
        wall=False, solid=True,
        notes=FLOOR_NOTES + 'Rubber plant: 2-3 stems, dark glossy oval leaves, a red sheath at every tip. '
              'pot_style 0..2 = cylinder/belly/square.',
        sizes={'S': (0.45, 0.45, dict(h=0.8, pot_d=0.24, leaves=14)), 'M': (0.60, 0.60, {}),
               'L': (0.80, 0.80, dict(h=1.7, pot_d=0.38, leaves=30))}),
    'plant_snake': dict(
        drawn=False, w=(0.36, 0.22, 0.5), d=(0.36, 0.22, 0.5),
        params=dict(h=(0.75, 0.4, 1.1), pot_d=(0.24, 0.16, 0.32), leaves=(11, 6, 16), **_pp()),
        footprint='w x d = the leaf spread (barely wider than the pot); pot at the origin; h = the top',
        wall=False, solid=True,
        notes=FLOOR_NOTES + 'Sansevieria: upright channelled sword leaves. Good in a bathroom or hall corner '
              '(needs ~0.35 m square). pot_style 0..2 = cylinder/taper/square.',
        sizes={'S': (0.26, 0.26, dict(h=0.45, pot_d=0.17, leaves=8)), 'M': (0.36, 0.36, {}),
               'L': (0.46, 0.46, dict(h=1.05, pot_d=0.30, leaves=15))}),
    'plant_palm': dict(
        drawn=False, w=(1.25, 0.8, 1.6), d=(1.25, 0.8, 1.6),
        params=dict(h=(1.5, 1.0, 2.1), pot_d=(0.36, 0.28, 0.46), fronds=(8, 5, 10), **_pp()),
        footprint='w x d = the frond spread; pot at the origin; h = the top of the arching fronds',
        wall=False, solid=True,
        notes=FLOOR_NOTES + 'Kentia palm: arching fronds with drooping pinnae from a cluster of stalks.',
        sizes={'S': (0.90, 0.90, dict(h=1.1, pot_d=0.30, fronds=6)), 'M': (1.25, 1.25, {}),
               'L': (1.55, 1.55, dict(h=2.0, pot_d=0.44, fronds=10))}),
    'plant_olive': dict(
        drawn=False, w=(0.75, 0.5, 1.0), d=(0.75, 0.5, 1.0),
        params=dict(h=(1.7, 1.2, 2.2), pot_d=(0.40, 0.32, 0.50), leaves=(260, 150, 360), **_pp()),
        footprint='w x d = the crown spread; the tall pot at the origin; h = the top of the crown',
        wall=False, solid=True,
        notes=FLOOR_NOTES + 'Olive tree in a tall pot (pot height ~1.3 x pot_d): gnarled bark trunk, grey-green '
              'narrow leaves (foliage_b). Living room corner or loggia. pot_style 0..2 = tall/taper/square, '
              'pot_mat by seed from int_pot/int_stone_dark/int_white_gloss.',
        sizes={'S': (0.55, 0.55, dict(h=1.3, pot_d=0.34, leaves=150)), 'M': (0.75, 0.75, {}),
               'L': (0.95, 0.95, dict(h=2.1, pot_d=0.48, leaves=290))}),
    'plant_pothos': dict(
        drawn=False, w=(0.60, 0.40, 0.90), d=(0.22, 0.18, 0.28),
        params=dict(shelf_z=(1.7, 1.3, 2.0), trail=(0.8, 0.3, 1.2), vines=(5, 3, 7), pot_d=(0.16, 0.12, 0.2),
                    **_pp()),
        footprint='w = shelf length along the wall (local Y), d = shelf depth (local X); the shelf back is at '
                  'x = -d/2, which must be the wall; shelf top at shelf_z',
        wall=True, solid=False,
        notes='A floating oak shelf with two dark steel brackets and a pothos whose vines trail over the front '
              'edge (lowest leaf at max(0.35, shelf_z - trail)). Place against a wall: the local -X face IS the '
              'wall plane (rot = the wall\'s inward normal). Nothing reaches the floor, so it does not block '
              'walking; keep it off door swings and out of a walking line if trail > shelf_z - 1.9. '
              'pot_style 0..2 = belly/cylinder/bowl.',
        sizes={'S': (0.45, 0.20, dict(trail=0.5, vines=4)), 'M': (0.60, 0.22, {}),
               'L': (0.85, 0.26, dict(trail=1.1, vines=7))}),
    'plant_succulents': dict(
        drawn=False, w=(0.36, 0.24, 0.5), d=(0.14, 0.09, 0.2),
        params=dict(lift=(0.0, 0.0, 1.2)),
        footprint='w = the row of three pots along local Y, d = their depth (local X); origin on the surface '
                  'they stand on (or add lift = that surface\'s height)',
        wall=False, solid=False,
        notes='A trio of small pots (cactus column with ribs, echeveria rosette, haworthia, globe cactus - three '
              'of the four, by seed). Tabletop: a windowsill, sideboard, the TV unit or a desk. Place the node at '
              'the surface height (or pass lift).',
        sizes={'S': (0.26, 0.10, {}), 'M': (0.36, 0.14, {}), 'L': (0.48, 0.18, {})}),
    'plant_herbs': dict(
        drawn=False, w=(0.42, 0.30, 0.6), d=(0.14, 0.11, 0.18),
        params=dict(lift=(0.0, 0.0, 1.2), tray=(1, 0, 1)),
        footprint='w = the row of three pots along local Y, d = the tray depth (local X); origin on the '
                  'worktop (or lift = 0.90)',
        wall=False, solid=False,
        notes='Basil, rosemary and chives in three matching pots on an oak tray (tray=0: no tray). For the '
              'kitchen worktop: at the back of the worktop (x toward the wall), away from the hob; node z = '
              'worktop top 0.90 or lift=0.90. Faces +X (into the room).',
        sizes={'S': (0.32, 0.12, {}), 'M': (0.42, 0.14, {}), 'L': (0.55, 0.17, {})}),
    'planter_balcony': dict(
        drawn=False, w=(1.0, 0.5, 1.6), d=(0.30, 0.2, 0.45),
        params=dict(box_h=(0.38, 0.25, 0.6), plant_h=(0.45, 0.2, 0.8), pot_mat=(-1, -1, 3)),
        footprint='w = the trough length along local Y, d = its depth along local X; trough fills the box',
        wall=True, solid=True,
        notes='A long planter box with ornamental grass, clipped box balls and lavender (blue-grey heads). '
              'For loggias and the terrace: back (local -X) against the balustrade or wall, rot = the inward '
              'normal; collide with the trough box w x d.',
        sizes={'S': (0.6, 0.25, dict(box_h=0.3, plant_h=0.35)), 'M': (1.0, 0.30, {}),
               'L': (1.5, 0.40, dict(box_h=0.45, plant_h=0.6))}),
    'plant_loggia_pair': dict(
        drawn=False, w=(1.2, 0.7, 1.8), d=(0.45, 0.28, 0.6),
        params=dict(pot_h=(0.55, 0.35, 0.8), plant_h=(0.9, 0.4, 1.3), species=(-1, -1, 2), pot_mat=(-1, -1, 3)),
        footprint='w = across both pots (local Y; the pots sit at +-~w/4), d = pot diameter (local X)',
        wall=False, solid=True,
        notes='A matching pair of tall pots: species 0 = clipped box-ball standards, 1 = big ornamental grass, '
              '2 = one of each (-1 = by seed). Either side of a loggia door or a window. Collide with two '
              'circles of radius d/2 at (0, +-y) - the y is in the returned verts\' pot centres (= '
              'clamp(w/4, d/2+0.04, w/2-d/2)).',
        sizes={'S': (0.8, 0.30, dict(pot_h=0.4, plant_h=0.55)), 'M': (1.2, 0.45, {}),
               'L': (1.7, 0.58, dict(pot_h=0.75, plant_h=1.2))}),
    'decor_vase': dict(
        drawn=False, w=(0.15, 0.10, 0.22), d=(0.15, 0.10, 0.22),
        params=dict(h=(0.6, 0.35, 0.9), vase_h=(0.26, 0.15, 0.4), stems=(4, 2, 6), finish=(-1, -1, 3),
                    lift=(0.0, 0.0, 1.2)),
        footprint='w x d = the vase belly (min of the two is its diameter); the eucalyptus stems spread past '
                  'it by ~0.15 m; origin on the surface it stands on',
        wall=False, solid=False,
        notes='A ceramic bottle or ovoid vase with eucalyptus stems (round leaves on bark stems). finish 0..3 = '
              'int_ceramic/int_white_gloss/int_stone_dark/int_pot. Dining table centre, sideboard, nightstand.',
        sizes={'S': (0.11, 0.11, dict(h=0.4, vase_h=0.18, stems=3)), 'M': (0.15, 0.15, {}),
               'L': (0.20, 0.20, dict(h=0.85, vase_h=0.36, stems=6))}),
    'decor_books': dict(
        drawn=False, w=(0.24, 0.16, 0.36), d=(0.17, 0.12, 0.28),
        params=dict(n=(3, 1, 6), lift=(0.0, 0.0, 1.2)),
        footprint='w = book height across (local Y), d = spine-to-fore-edge (local X); most spines face +X',
        wall=False, solid=False,
        notes='A stack of hardbacks with rounded spines and cream page blocks, covers in the int_fabric_* / '
              'leather colours. Coffee table, nightstand, desk, shelf. Origin on the surface.',
        sizes={'S': (0.20, 0.14, dict(n=2)), 'M': (0.24, 0.17, {}), 'L': (0.32, 0.24, dict(n=5))}),
    'decor_bowl': dict(
        drawn=False, w=(0.30, 0.18, 0.42), d=(0.30, 0.18, 0.42),
        params=dict(fruit=(3, 0, 6), finish=(-1, -1, 3), lift=(0.0, 0.0, 1.2)),
        footprint='min(w, d) = the bowl diameter; origin on the surface',
        wall=False, solid=False,
        notes='A wide turned bowl (finish 0..3 = walnut/ceramic/stone_dark/brass) with oranges and red apples. '
              'Dining table, kitchen island/worktop, coffee table.',
        sizes={'S': (0.22, 0.22, dict(fruit=2)), 'M': (0.30, 0.30, {}), 'L': (0.40, 0.40, dict(fruit=5))}),
    'decor_candles': dict(
        drawn=False, w=(0.28, 0.16, 0.4), d=(0.14, 0.1, 0.2),
        params=dict(tray=(1, 0, 1), lift=(0.0, 0.0, 1.2)),
        footprint='w = the row of three candles / the oval tray length (local Y), d = tray width (local X)',
        wall=False, solid=False,
        notes='Three pillar candles of three heights on an oval brass tray (tray=0: none). Coffee table, '
              'bath rim/shelf, sideboard.',
        sizes={'S': (0.20, 0.11, {}), 'M': (0.28, 0.14, {}), 'L': (0.38, 0.18, {})}),
    'decor_table_plant': dict(
        drawn=False, w=(0.24, 0.14, 0.36), d=(0.24, 0.14, 0.36),
        params=dict(h=(0.28, 0.18, 0.4), pot_d=(0.12, 0.08, 0.16), lift=(0.0, 0.0, 1.2), **_pp()),
        footprint='w x d = the leaf spread; pot at the origin; origin on the surface',
        wall=False, solid=False,
        notes='Pilea (Chinese money plant): coin leaves on long stalks. Desk, nightstand, windowsill, bathroom '
              'shelf. pot_style 0..2 = cylinder/belly/bowl.',
        sizes={'S': (0.17, 0.17, dict(h=0.2, pot_d=0.09)), 'M': (0.24, 0.24, {}),
               'L': (0.34, 0.34, dict(h=0.38, pot_d=0.15))}),
}

_BUILDERS = {
    'plant_monstera': b_monstera, 'plant_fiddle': b_fiddle, 'plant_rubber': b_rubber, 'plant_snake': b_snake,
    'plant_palm': b_palm, 'plant_olive': b_olive, 'plant_pothos': b_pothos, 'plant_succulents': b_succulents,
    'plant_herbs': b_herbs, 'planter_balcony': b_planter, 'plant_loggia_pair': b_loggia,
    'decor_vase': b_vase, 'decor_books': b_books, 'decor_bowl': b_bowl, 'decor_candles': b_candles,
    'decor_table_plant': b_table_plant,
}


def build(kind, w, d, seed=0, **params):
    """-> [(material, verts, faces, smooth)] in the local frame (see module doc)."""
    spec = KINDS[kind]
    p = {}
    for name, (dv, lo, hi) in spec['params'].items():
        v = params.get(name, dv)
        p[name] = clamp(float(v), lo, hi) if v is not None else dv
    for name in ('leaves', 'fronds', 'vines', 'stems', 'n', 'fruit'):
        if name in p:
            p[name] = int(round(p[name]))
    w = clamp(float(w), spec['w'][1], spec['w'][2])
    d = clamp(float(d), spec['d'][1], spec['d'][2])
    rng = random.Random((zlib.crc32(kind.encode()) * 1000003 + int(seed) * 7919) & 0xffffffff)
    K = Kit()
    _BUILDERS[kind](K, w, d, rng, **p)
    return K.result()


def tri_count(kind, w, d, **p):
    seed = p.pop('seed', 0)
    return sum(len(f) - 2 for _, _, F, _ in build(kind, w, d, seed=seed, **p) for f in F)


def bounds(parts):
    xs, ys, zs = [], [], []
    for _, V, _, _ in parts:
        for x, y, z in V:
            xs.append(x); ys.append(y); zs.append(z)
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


# ================================================================== preview (Blender)
PREVIEW_COL = {
    'foliage': ('#4b6128', 0.55, 0.0), 'foliage_b': ('#577331', 0.6, 0.0), 'bark': ('#4e453b', 0.9, 0.0),
    'soil': ('#3f372d', 0.95, 0.0), 'int_pot': ('#36322f', 0.6, 0.0), 'int_white_gloss': ('#e6e5e1', 0.22, 0.0),
    'int_ceramic': ('#ecece9', 0.1, 0.0), 'int_stone_dark': ('#3a3a3c', 0.32, 0.0),
    'int_wood_oak': ('#b3895a', 0.55, 0.0), 'int_wood_walnut': ('#4f3627', 0.48, 0.0),
    'int_brass': ('#b08c55', 0.35, 0.85), 'metal_dark': ('#43444a', 0.34, 0.9), 'int_black': ('#111214', 0.4, 0.2),
    'int_fabric_teal': ('#3c8a84', 0.9, 0.0), 'int_fabric_bluegrey': ('#8294a8', 0.9, 0.0),
    'int_fabric_white': ('#eeeae2', 0.85, 0.0), 'int_fabric_orange': ('#d6622a', 0.7, 0.0),
    'int_fabric_dark': ('#3d4148', 0.95, 0.0), 'int_leather_red': ('#7a2620', 0.5, 0.0),
    'int_mint': ('#a7c3b2', 0.3, 0.0), 'int_accent_red': ('#8b2d29', 0.6, 0.0),
}


def _preview():
    import sys
    import os
    import bpy
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    out = argv[argv.index('--out') + 1] if '--out' in argv else '/tmp/plants'
    os.makedirs(out, exist_ok=True)
    kinds = argv[argv.index('--kinds') + 1].split(',') if '--kinds' in argv else list(KINDS)
    views = argv[argv.index('--views') + 1].split(',') if '--views' in argv else ['eye', 'top']
    seeds = [int(s) for s in argv[argv.index('--seeds') + 1].split(',')] if '--seeds' in argv else None
    res = int(argv[argv.index('--res') + 1]) if '--res' in argv else 900

    def srgb(hx):
        h = hx.lstrip('#')
        o = []
        for k in (0, 2, 4):
            c = int(h[k:k + 2], 16) / 255.0
            o.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
        return o
    mats = {}

    def mat(name):
        if name in mats:
            return mats[name]
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        nt = m.node_tree
        b = nt.nodes['Principled BSDF']
        hx, r, me = PREVIEW_COL.get(name, ('#ff00ff', 0.5, 0.0))
        b.inputs['Base Color'].default_value = srgb(hx) + [1]
        b.inputs['Roughness'].default_value = r
        b.inputs['Metallic'].default_value = me
        if name in ('int_white_gloss', 'int_ceramic'):
            try:
                b.inputs['Coat Weight'].default_value = 0.8
            except Exception:
                pass
        if name.startswith('foliage'):
            # paler, matt underside (the page keys it off frontFacing) + a
            # touch of translucency
            geo = nt.nodes.new('ShaderNodeNewGeometry')
            mix = nt.nodes.new('ShaderNodeMix')
            mix.data_type = 'RGBA'
            mix.inputs['A'].default_value = srgb(hx) + [1]
            under = [0.62 * c + 0.38 * u for c, u in zip(srgb(hx), srgb('#93a078'))]
            mix.inputs['B'].default_value = under + [1]
            nt.links.new(geo.outputs['Backfacing'], mix.inputs['Factor'])
            nt.links.new(mix.outputs['Result'], b.inputs['Base Color'])
        m.use_backface_culling = not name.startswith('foliage')
        mats[name] = m
        return m

    def make_obj(name, parts, loc):
        V, F, MI, S = [], [], [], []
        ml = []
        for mn, verts, faces, smooth in parts:
            if mn not in ml:
                ml.append(mn)
            o = len(V)
            V.extend(verts)
            for f in faces:
                F.append(tuple(o + i for i in f))
                MI.append(ml.index(mn))
                S.append(smooth)
        me = bpy.data.meshes.new(name)
        me.from_pydata(V, [], F)
        for mn in ml:
            me.materials.append(mat(mn))
        for p, mi, s in zip(me.polygons, MI, S):
            p.material_index = mi
            p.use_smooth = s
        me.validate()
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(name, me)
        ob.location = loc
        bpy.context.scene.collection.objects.link(ob)
        return ob

    def scene_reset():
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        for m in list(bpy.data.meshes):
            bpy.data.meshes.remove(m)
        sc = bpy.context.scene
        try:
            sc.render.engine = 'BLENDER_EEVEE'
        except Exception:
            sc.render.engine = 'BLENDER_EEVEE_NEXT'
        sc.render.resolution_x = int(res * 1.5)
        sc.render.resolution_y = res
        sc.view_settings.view_transform = 'AgX' if 'AgX' in [i.name for i in type(sc.view_settings).bl_rna.properties['view_transform'].enum_items] else 'Filmic'
        w = bpy.data.worlds.new('w') if not bpy.data.worlds else bpy.data.worlds[0]
        sc.world = w
        w.use_nodes = True
        bg = w.node_tree.nodes.get('Background')
        bg.inputs[0].default_value = (0.55, 0.57, 0.6, 1)
        bg.inputs[1].default_value = 0.9
        # floor + back wall
        bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
        fl = bpy.context.object
        fm = bpy.data.materials.new('floor')
        fm.use_nodes = True
        fm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.42, 0.40, 0.38, 1)
        fm.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.7
        fl.data.materials.append(fm)
        bpy.ops.mesh.primitive_plane_add(size=40, location=(-3.0, 0, 0), rotation=(0, math.pi / 2, 0))
        wl = bpy.context.object
        wm = bpy.data.materials.new('wall')
        wm.use_nodes = True
        wm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.7, 0.69, 0.66, 1)
        wl.data.materials.append(wm)
        ld = bpy.data.lights.new('key', 'AREA')
        ld.energy = 900
        ld.size = 4
        lo = bpy.data.objects.new('key', ld)
        lo.location = (4, 3, 5)
        lo.rotation_euler = (math.radians(45), 0, math.radians(125))
        sc.collection.objects.link(lo)
        sd = bpy.data.lights.new('sun', 'SUN')
        sd.energy = 2.2
        sd.angle = math.radians(8)
        so = bpy.data.objects.new('sun', sd)
        so.rotation_euler = (math.radians(40), math.radians(15), math.radians(60))
        sc.collection.objects.link(so)
        try:
            sc.eevee.use_shadows = True
        except Exception:
            pass

    def cam(loc, target, lens=40, ortho=None):
        cd = bpy.data.cameras.new('cam')
        cd.lens = lens
        if ortho:
            cd.type = 'ORTHO'
            cd.ortho_scale = ortho
        co = bpy.data.objects.new('cam', cd)
        co.location = loc
        bpy.context.scene.collection.objects.link(co)
        dvec = [target[i] - loc[i] for i in range(3)]
        from mathutils import Vector
        co.rotation_euler = Vector(dvec).to_track_quat('-Z', 'Y').to_euler()
        bpy.context.scene.camera = co
        return co

    for kind in kinds:
        spec = KINDS[kind]
        scene_reset()
        items = []
        if seeds:
            for s in seeds:
                items.append(('M', spec['sizes']['M'], s))
        else:
            for sz in ('S', 'M', 'L'):
                items.append((sz, spec['sizes'][sz], 0))
            items.append(('M', spec['sizes']['M'], 1))
        y = 0.0
        maxh = 0.0
        maxw = 0.0
        placed = []
        for sz, (w, d, p), s in items:
            parts = build(kind, w, d, seed=s, **p)
            bb = bounds(parts)
            span = max(bb[4] - bb[1], w) + 0.25
            yy = y + span / 2.0
            placed.append((kind + '_' + sz + str(s), parts, yy))
            y += span
            maxh = max(maxh, bb[5])
            maxw = max(maxw, bb[3] - bb[0])
            print('[kit] %-18s %s seed %d  %.2f x %.2f  tris %5d  bounds x %.2f..%.2f y %.2f..%.2f z %.2f..%.2f'
                  % (kind, sz, s, w, d, sum(len(f) - 2 for _, _, F, _ in parts for f in F), *(
                      bb[0], bb[3], bb[1], bb[4], bb[2], bb[5])))
        off = y / 2.0
        for name, parts, yy in placed:
            make_obj(name, parts, (0.0, yy - off, 0.0))
        tgt_z = maxh * 0.45
        span = max(y, maxh * 1.4)
        for view in views:
            if view == 'eye':
                dist = max(1.2, span * 0.95)
                cam((dist, -dist * 0.2, 1.6 if maxh > 0.8 else max(0.6, maxh + 0.45)), (0, 0, tgt_z), lens=35)
            elif view == 'close':
                dist = max(0.9, span * 0.7)
                cam((dist, -dist * 0.3, max(maxh * 0.9, 0.4)), (0, 0, maxh * 0.55), lens=45)
            elif view == 'top':
                cam((0.3, -0.1, max(1.0, span * 1.25) + maxh), (0, 0, 0), lens=35)
            elif view == 'low':
                dist = max(1.2, span * 1.0)
                cam((dist, 0.0, 0.25), (0, 0, maxh * 0.6), lens=35)
            bpy.context.scene.render.filepath = os.path.join(out, '%s_%s.png' % (kind, view))
            bpy.ops.render.render(write_still=True)
            print('[kit] wrote', bpy.context.scene.render.filepath)


if __name__ == '__main__':
    try:
        import bpy  # noqa
        _preview()
    except ImportError:
        print('%-20s %8s %8s %6s   %s' % ('kind', 'w', 'd', 'tris', 'S / M / L tris'))
        for k, s in KINDS.items():
            row = []
            for sz in ('S', 'M', 'L'):
                w, d, p = s['sizes'][sz]
                row.append(tri_count(k, w, d, **p))
            print('%-20s %8.2f %8.2f %6d   %s' % (k, s['w'][0], s['d'][0], tri_count(k, s['w'][0], s['d'][0]),
                                                  ' / '.join(str(x) for x in row)))
