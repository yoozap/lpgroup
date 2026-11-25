# -*- coding: utf-8 -*-
"""Bedroom, kitchen and office pieces, modelled properly (build 6 kit).

Pure python (math + random only) inside build(): runs under Blender's python
and the system one (3.9) alike. A Blender preview lives under __main__:

    Blender -b -P blender/furn_kit_bed.py -- --kind bed_double [--out DIR] [--top]

Interface (the integrator relies on it):

    KINDS[kind] = {'drawn', 'params': {name: (default, min, max)}, 'footprint',
                   'wall', 'solid', 'notes'}
    build(kind, w, d, seed=0, **params) -> [(material, verts, faces, smooth)]
    tri_count(kind, w, d, **params) -> int

LOCAL FRAME (lib_furnish.py): +X is the way the piece faces (a bed's foot, a
worktop's front, a chair towards its desk), +Y its left, z up, metres, origin
on the floor at the centre of the footprint. w = the drawn box ACROSS the
heading (local Y), d = ALONG the heading (local X) - exactly lib_furnish's
box size [across, along] -> params w, d. Faces are tris/quads, counter-
clockwise seen from outside; `smooth` parts are curved, the rest flat. A
material comes out at most twice (once flat, once smooth); the two share
positions, so the integrator's remove_doubles welds them and Blender's
sharp-face rule keeps flat faces flat and curves curved.

Every material is one web/materials.js already defines, and none of them
needs UVs (they are all noise or projected in the flat's frame).

Triangles per kind at the default size (tri_count; re-run `python3
blender/furn_kit_bed.py` to print this table):

    kind             default w x d      tris
    bed_double       1.80 x 2.00       1698  (pillows=2: 1538, + throw=None: 1322, pillows=4: 1858)
    nightstand       0.50 x 0.40        540  (lamp=0: 316)
    kitchen_run      2.50 x 0.70        724  (+ sink cut-out + oven under the hob: 1032; 3.55 m: 1048)
    sink             0.50 x 0.42        680
    hob              0.58 x 0.50        386  (glass + zones + hood, either hood)
    desk             1.40 x 0.70        332  (the L01 V desk outline: 294)
    office_chair     0.60 x 0.60       1254
    desk_equipment   0.47 x 0.35        744
    wardrobe         1.80 x 0.60        218  (0.80 m: 110, 3.00 m: 326)
    dresser          1.20 x 0.45       1162  (decor=0, mirror=0: 454)
    rug_bedroom      2.00 x 1.40         82
    fridge_tower     0.60 x 0.70        142
    oven_tower       0.60 x 0.70        520
"""
import math
import random

TAU = 2.0 * math.pi


# =====================================================================
# geometry core
# =====================================================================
class Geo(object):
    """Vertices and faces of one material; faces carry their smooth flag."""
    __slots__ = ('v', 'f')

    def __init__(self):
        self.v = []
        self.f = []

    def extend(self, o):
        n = len(self.v)
        self.v.extend([list(p) for p in o.v])
        self.f.extend([(tuple(i + n for i in f), s) for f, s in o.f])
        return self

    def map(self, fn):
        self.v = [list(fn(p[0], p[1], p[2])) for p in self.v]
        return self

    def move(self, dx=0.0, dy=0.0, dz=0.0):
        return self.map(lambda x, y, z: (x + dx, y + dy, z + dz))

    def rotz(self, a, cx=0.0, cy=0.0):
        c, s = math.cos(a), math.sin(a)
        return self.map(lambda x, y, z: (cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c, z))

    def roty(self, a, cx=0.0, cz=0.0):
        """Right-handed about +Y: a > 0 lifts the -X end."""
        c, s = math.cos(a), math.sin(a)
        return self.map(lambda x, y, z: (cx + (x - cx) * c + (z - cz) * s, y, cz - (x - cx) * s + (z - cz) * c))

    def rotx(self, a, cy=0.0, cz=0.0):
        c, s = math.cos(a), math.sin(a)
        return self.map(lambda x, y, z: (x, cy + (y - cy) * c - (z - cz) * s, cz + (y - cy) * s + (z - cz) * c))

    def scale(self, sx, sy, sz, c=(0.0, 0.0, 0.0)):
        self.map(lambda x, y, z: (c[0] + (x - c[0]) * sx, c[1] + (y - c[1]) * sy, c[2] + (z - c[2]) * sz))
        if sx * sy * sz < 0:
            self.flip()
        return self

    def flip(self):
        self.f = [(tuple(reversed(f)), s) for f, s in self.f]
        return self

    def bbox(self):
        xs = [p[0] for p in self.v]
        ys = [p[1] for p in self.v]
        zs = [p[2] for p in self.v]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


class Kit(object):
    """Per-material accumulators for one piece."""

    def __init__(self):
        self.g = {}
        self.order = []

    def __call__(self, mat):
        if mat not in self.g:
            self.g[mat] = Geo()
            self.order.append(mat)
        return self.g[mat]

    def add(self, mat, geo):
        self(mat).extend(geo)
        return geo

    def parts(self):
        out = []
        for m in self.order:
            g = self.g[m]
            for sm in (False, True):
                fs = [f for f, s in g.f if s == sm]
                if not fs:
                    continue
                P = [tuple(round(c, 5) for c in p) for p in g.v]
                clean = []
                for f in fs:
                    # drop repeated corners (collapsed poles, zero-length bands)
                    q = []
                    for i in f:
                        if not q or P[q[-1]] != P[i]:
                            q.append(i)
                    while len(q) > 1 and P[q[0]] == P[q[-1]]:
                        q.pop()
                    if len(set(P[i] for i in q)) >= 3:
                        clean.append(tuple(q))
                if not clean:
                    continue
                used = sorted(set(i for f in clean for i in f))
                rm = dict((i, k) for k, i in enumerate(used))
                out.append((m, [P[i] for i in used], [tuple(rm[i] for i in f) for f in clean], sm))
        return out


def _dedupe(vals, eps=1e-7):
    out = []
    for v in sorted(vals):
        if not out or v - out[-1] > eps:
            out.append(v)
    return out


def box(p0, p1, skip=()):
    """Axis-aligned box, flat. skip: any of -x +x -y +y -z +z."""
    x0, x1 = sorted((p0[0], p1[0]))
    y0, y1 = sorted((p0[1], p1[1]))
    z0, z1 = sorted((p0[2], p1[2]))
    g = Geo()
    g.v = [[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
           [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]]
    F = {'-z': (0, 3, 2, 1), '+z': (4, 5, 6, 7), '-y': (0, 1, 5, 4),
         '+x': (1, 2, 6, 5), '+y': (2, 3, 7, 6), '-x': (3, 0, 4, 7)}
    for k, f in F.items():
        if k not in skip:
            g.f.append((f, False))
    return g


def chbox(p0, p1, r):
    """A box with all twelve edges chamfered (one facet each) and the
    corners cut: 44 tris, flat. The cheap way to catch a highlight on an
    edge that a hand or eye meets."""
    lo = [min(p0[i], p1[i]) for i in range(3)]
    hi = [max(p0[i], p1[i]) for i in range(3)]
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    h = [(hi[i] - lo[i]) / 2 for i in range(3)]
    r = max(0.0, min(r, min(h) * 0.95))
    if r < 1e-5:
        return box(p0, p1)
    g = Geo()
    ids = {}

    def V(a, sg):
        k = (a, sg)
        if k not in ids:
            p = [c[i] + sg[i] * (h[i] if i == a else h[i] - r) for i in range(3)]
            g.v.append(p)
            ids[k] = len(g.v) - 1
        return ids[k]

    def poly(vs):
        P = [g.v[i] for i in vs]
        m = [sum(p[i] for p in P) / len(P) for i in range(3)]
        n = _norm(_sub(m, c))
        t1 = _norm(_sub(P[0], m))
        t2 = _cross(n, t1)
        vs = sorted(vs, key=lambda i: math.atan2(_dot(_sub(g.v[i], m), t2), _dot(_sub(g.v[i], m), t1)))
        g.f.append((tuple(vs), False))
    S = (-1, 1)
    for a in range(3):
        for s in S:
            vs = []
            for s1 in S:
                for s2 in S:
                    sg = [0, 0, 0]
                    sg[a] = s
                    b, cc = (a + 1) % 3, (a + 2) % 3
                    sg[b], sg[cc] = s1, s2
                    vs.append(V(a, tuple(sg)))
            poly(vs)
    for a in range(3):
        for b in range(a + 1, 3):
            cc = 3 - a - b
            for sa in S:
                for sb in S:
                    vs = []
                    for sc in S:
                        sg = [0, 0, 0]
                        sg[a], sg[b], sg[cc] = sa, sb, sc
                        vs.append(V(a, tuple(sg)))
                        vs.append(V(b, tuple(sg)))
                    poly(vs)
    for sx in S:
        for sy in S:
            for sz in S:
                poly([V(a, (sx, sy, sz)) for a in range(3)])
    return g


def cbox(p0, p1, r=0.002, skip_back=True):
    """A front panel: a box facing +X whose front face has its four edges
    chamfered (one 45 degree facet). 20 tris; the back (-X) face is left
    out unless skip_back is False. Flat."""
    x0, x1 = sorted((p0[0], p1[0]))
    y0, y1 = sorted((p0[1], p1[1]))
    z0, z1 = sorted((p0[2], p1[2]))
    r = max(0.0, min(r, (y1 - y0) / 3, (z1 - z0) / 3, (x1 - x0) * 0.9))
    g = Geo()
    ring = [(y0, z0), (y1, z0), (y1, z1), (y0, z1)]          # CCW seen from +X
    inr = [(y0 + r, z0 + r), (y1 - r, z0 + r), (y1 - r, z1 - r), (y0 + r, z1 - r)]
    for (y, z) in ring:
        g.v.append([x0, y, z])
    for (y, z) in ring:
        g.v.append([x1 - r, y, z])
    for (y, z) in inr:
        g.v.append([x1, y, z])
    for i in range(4):
        j = (i + 1) % 4
        g.f.append(((i, j, 4 + j, 4 + i), False))
        g.f.append(((4 + i, 4 + j, 8 + j, 8 + i), False))
    g.f.append(((8, 9, 10, 11), False))
    if not skip_back:
        g.f.append(((3, 2, 1, 0), False))
    return g


def rbox(p0, p1, r, k=1, cuts=None, deform=None, skip=()):
    """Box with every edge rounded to radius r (k facets per 45 degrees),
    cube-mapped so the flat faces stay single flat quads unless `cuts` adds
    grid lines (absolute coordinates per axis) for a deform. Flat-region
    faces come out flat, the rounded bands smooth. k may be a 3-tuple.
    deform(x, y, z) acts on absolute coordinates."""
    lo = [min(p0[i], p1[i]) for i in range(3)]
    hi = [max(p0[i], p1[i]) for i in range(3)]
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    h = [(hi[i] - lo[i]) / 2 for i in range(3)]
    r = max(0.0, min(r, min(h)))
    if r < 1e-5 and not cuts and deform is None:
        return box(p0, p1, skip)
    ks = k if isinstance(k, (tuple, list)) else (k, k, k)
    inner = [h[i] - r for i in range(3)]
    S = []
    for i in range(3):
        s = []
        kk = max(1, ks[i])
        for j in range(kk + 1):
            s.append(-h[i] + r * j / kk)
            s.append(h[i] - r * j / kk)
        if cuts and cuts[i]:
            for cv in cuts[i]:
                q = cv - c[i]
                if -inner[i] < q < inner[i]:
                    s.append(q)
        S.append(_dedupe(s))
    g = Geo()
    key = {}

    def vid(q):
        kq = (round(q[0], 7), round(q[1], 7), round(q[2], 7))
        if kq in key:
            return key[kq]
        cl = [max(-inner[i], min(inner[i], q[i])) for i in range(3)]
        dv = [q[i] - cl[i] for i in range(3)]
        L = math.sqrt(dv[0] ** 2 + dv[1] ** 2 + dv[2] ** 2)
        if L > 1e-12 and r > 0:
            p = [cl[i] + r * dv[i] / L for i in range(3)]
        else:
            p = list(q)
        p = [p[i] + c[i] for i in range(3)]
        if deform is not None:
            p = list(deform(p[0], p[1], p[2]))
        g.v.append(p)
        key[kq] = len(g.v) - 1
        return key[kq]

    names = ('x', 'y', 'z')
    for a in range(3):
        b, cc = (a + 1) % 3, (a + 2) % 3
        for s in (-1, 1):
            if ('+' if s > 0 else '-') + names[a] in skip:
                continue
            Sb, Sc = S[b], S[cc]
            for i in range(len(Sb) - 1):
                for j in range(len(Sc) - 1):
                    cor = [(Sb[i], Sc[j]), (Sb[i + 1], Sc[j]), (Sb[i + 1], Sc[j + 1]), (Sb[i], Sc[j + 1])]
                    if s < 0:
                        cor.reverse()
                    idx = []
                    flat = deform is None
                    for (u, v) in cor:
                        q = [0.0, 0.0, 0.0]
                        q[a] = s * h[a]
                        q[b] = u
                        q[cc] = v
                        idx.append(vid(q))
                        if abs(u) > inner[b] + 1e-9 or abs(v) > inner[cc] + 1e-9:
                            flat = False
                    g.f.append((tuple(idx), not flat))
    return g


def spe(c, rx, ry, rz, e1=1.0, e2=1.0, nu=12, nv=6):
    """Superellipsoid: e1 shapes the vertical profile (>1 pinches a seam,
    like a pillow), e2 the plan (<1 squares it off). Smooth."""
    def sp(x, e):
        return math.copysign(abs(x) ** e, x)
    g = Geo()
    g.v.append([c[0], c[1], c[2] - rz])
    for j in range(1, nv):
        ph = -math.pi / 2 + math.pi * j / nv
        cp, sn = sp(math.cos(ph), e1), sp(math.sin(ph), e1)
        for i in range(nu):
            th = TAU * i / nu
            g.v.append([c[0] + rx * cp * sp(math.cos(th), e2), c[1] + ry * cp * sp(math.sin(th), e2), c[2] + rz * sn])
    g.v.append([c[0], c[1], c[2] + rz])
    top = len(g.v) - 1

    def R(j, i):
        return 1 + (j - 1) * nu + (i % nu)
    for i in range(nu):
        g.f.append(((0, R(1, i + 1), R(1, i)), True))
        g.f.append(((R(nv - 1, i), R(nv - 1, i + 1), top), True))
    for j in range(1, nv - 1):
        for i in range(nu):
            g.f.append(((R(j, i), R(j, i + 1), R(j + 1, i + 1), R(j + 1, i)), True))
    return g


def cushion(c, hx, hy, hz, rc, seg=3, prof=((-1.0, 0.6), (-0.72, 0.13), (0.0, 0.0), (0.72, 0.13), (1.0, 0.6))):
    """A soft cushion: rounded-rectangle rings (plan corner radius rc)
    stacked through its thickness, pulled in at top and bottom (inset =
    f * hz), capped by fans. Smooth. Corners stay round with few points
    because the straight sides are single edges."""
    g = Geo()
    rings = []
    for (zf, f) in prof:
        ins = f * hz
        pts = rrect(c[0], c[1], max(0.004, hx - ins), max(0.004, hy - ins), max(0.003, rc - ins), seg)
        row = []
        for p in pts:
            g.v.append([p[0], p[1], c[2] + zf * hz])
            row.append(len(g.v) - 1)
        rings.append(row)
    n = len(rings[0])
    for k in range(len(rings) - 1):
        A, B = rings[k], rings[k + 1]
        for i in range(n):
            j = (i + 1) % n
            g.f.append(((A[i], A[j], B[j], B[i]), True))
    zb, zt = c[2] + prof[0][0] * hz, c[2] + prof[-1][0] * hz
    g.v.append([c[0], c[1], zb])
    cb = len(g.v) - 1
    g.v.append([c[0], c[1], zt])
    ct = len(g.v) - 1
    for i in range(n):
        j = (i + 1) % n
        g.f.append(((cb, rings[0][j], rings[0][i]), True))
        g.f.append(((ct, rings[-1][i], rings[-1][j]), True))
    return g


def lathe(prof, n=12, c=(0.0, 0.0, 0.0), sx=1.0, sy=1.0, a0=0.0, smooth=True):
    """Profile [(r, z)] revolved about z. Go bottom-centre -> out -> up ->
    top-centre for a solid (outward faces); reverse it for an inward shell.
    Horizontal segments come out flat, the rest `smooth`."""
    g = Geo()
    rings = []
    for (r, z) in prof:
        if r < 1e-9:
            g.v.append([c[0], c[1], c[2] + z])
            rings.append([len(g.v) - 1] * n)
        else:
            ids = []
            for i in range(n):
                a = a0 + TAU * i / n
                g.v.append([c[0] + r * sx * math.cos(a), c[1] + r * sy * math.sin(a), c[2] + z])
                ids.append(len(g.v) - 1)
            rings.append(ids)
    for k in range(len(prof) - 1):
        A, B = rings[k], rings[k + 1]
        flat = abs(prof[k + 1][1] - prof[k][1]) < 1e-9
        sm = smooth and not flat
        for i in range(n):
            j = (i + 1) % n
            f = (A[i], A[j], B[j], B[i])
            q = []
            for x in f:
                if x not in q:
                    q.append(x)
            if len(q) >= 3:
                g.f.append((tuple(q), sm))
    return g


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    L = math.sqrt(_dot(a, a))
    return _mul(a, 1.0 / L) if L > 1e-12 else (0.0, 0.0, 0.0)


def sweep(path, rad, n=8, cap0=True, cap1=True, smooth=True, a0=0.0, up=(0.0, 0.0, 1.0)):
    """A tube along `path` (mitred joints), radius per point or one float.
    Caps are flat fans."""
    P = [tuple(map(float, p)) for p in path]
    m = len(P)
    rads = rad if isinstance(rad, (list, tuple)) else [rad] * m
    D = [_norm(_sub(P[k + 1], P[k])) for k in range(m - 1)]
    # frames per segment, parallel transported
    n0 = _sub(up, _mul(D[0], _dot(up, D[0])))
    if _dot(n0, n0) < 1e-8:
        n0 = _sub((1.0, 0.0, 0.0), _mul(D[0], D[0][0]))
        if _dot(n0, n0) < 1e-8:
            n0 = _sub((0.0, 1.0, 0.0), _mul(D[0], D[0][1]))
    N = [_norm(n0)]
    for k in range(1, m - 1):
        nn = _sub(N[-1], _mul(D[k], _dot(N[-1], D[k])))
        if _dot(nn, nn) < 1e-10:
            nn = N[-1]
        N.append(_norm(nn))
    g = Geo()
    rings = []
    for k in range(m):
        segi = k - 1 if k > 0 else 0
        d, nv = D[segi], N[segi]
        bv = _cross(d, nv)
        if 0 < k < m - 1:
            t = _norm(_add(D[k - 1], D[k]))
        else:
            t = d
        ids = []
        for i in range(n):
            a = a0 + TAU * i / n
            o = _add(_mul(nv, rads[k] * math.cos(a)), _mul(bv, rads[k] * math.sin(a)))
            if 0 < k < m - 1:
                den = _dot(d, t)
                s = -_dot(o, t) / den if abs(den) > 1e-6 else 0.0
                o = _add(o, _mul(d, s))
            g.v.append(list(_add(P[k], o)))
            ids.append(len(g.v) - 1)
        rings.append(ids)
    for k in range(m - 1):
        A, B = rings[k], rings[k + 1]
        for i in range(n):
            j = (i + 1) % n
            g.f.append(((A[i], A[j], B[j], B[i]), smooth))
    if cap0:
        g.v.append(list(P[0]))
        cidx = len(g.v) - 1
        for i in range(n):
            g.f.append(((cidx, rings[0][(i + 1) % n], rings[0][i]), False))
    if cap1:
        g.v.append(list(P[-1]))
        cidx = len(g.v) - 1
        for i in range(n):
            g.f.append(((cidx, rings[-1][i], rings[-1][(i + 1) % n]), False))
    return g


def _area2(pts):
    return sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts)))


def triangulate(pts):
    """Ear clipping for a simple CCW polygon -> index triples."""
    idx = list(range(len(pts)))
    out = []

    def cr(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def inside(p, a, b, c):
        return cr(a, b, p) >= -1e-12 and cr(b, c, p) >= -1e-12 and cr(c, a, p) >= -1e-12
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        done = False
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = pts[i0], pts[i1], pts[i2]
            x = cr(a, b, c)
            if abs(x) < 1e-12:
                idx.pop(k)
                done = True
                break
            if x < 0:
                continue
            if any(inside(pts[j], a, b, c) for j in idx if j not in (i0, i1, i2)
                   and pts[j] not in (a, b, c)):
                continue
            out.append((i0, i1, i2))
            idx.pop(k)
            done = True
            break
        if not done:
            break
    if len(idx) >= 3:
        for k in range(1, len(idx) - 1):
            out.append((idx[0], idx[k], idx[k + 1]))
    return out


def offset_poly(pts, r):
    """Move a CCW polygon's edges inward by r (mitred)."""
    n = len(pts)
    out = []
    for i in range(n):
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        e1 = _norm((b[0] - a[0], b[1] - a[1], 0.0))
        e2 = _norm((c[0] - b[0], c[1] - b[1], 0.0))
        n1 = (-e1[1], e1[0])
        n2 = (-e2[1], e2[0])
        dn = 1.0 + n1[0] * n2[0] + n1[1] * n2[1]
        dn = max(dn, 0.2)
        out.append((b[0] + r * (n1[0] + n2[0]) / dn, b[1] + r * (n1[1] + n2[1]) / dn))
    return out


def slab(poly, z0, z1, r=0.0, skip_bottom=False):
    """Polygon extruded z0..z1 with chamfered top and bottom arrises."""
    pts = [tuple(p[:2]) for p in poly]
    if _area2(pts) < 0:
        pts = pts[::-1]
    g = Geo()
    if r > 0:
        ins = offset_poly(pts, r)
        rings = [(ins, z0), (pts, z0 + r), (pts, z1 - r), (ins, z1)]
    else:
        ins = pts
        rings = [(pts, z0), (pts, z1)]
    n = len(pts)
    ids = []
    for (pp, z) in rings:
        row = []
        for p in pp:
            g.v.append([p[0], p[1], z])
            row.append(len(g.v) - 1)
        ids.append(row)
    for k in range(len(rings) - 1):
        A, B = ids[k], ids[k + 1]
        for i in range(n):
            j = (i + 1) % n
            g.f.append(((A[i], A[j], B[j], B[i]), False))
    tris = triangulate(ins)
    for t in tris:
        g.f.append(((ids[-1][t[0]], ids[-1][t[1]], ids[-1][t[2]]), False))
        if not skip_bottom:
            g.f.append(((ids[0][t[0]], ids[0][t[2]], ids[0][t[1]]), False))
    return g


def rrect(cx, cy, hx, hy, r, seg=4):
    """CCW rounded rectangle, 4 * (seg + 1) points."""
    r = max(1e-4, min(r, hx - 1e-4, hy - 1e-4))
    pts = []
    for (ox, oy, a0) in ((hx - r, hy - r, 0.0), (-hx + r, hy - r, 90.0), (-hx + r, -hy + r, 180.0), (hx - r, -hy + r, 270.0)):
        for k in range(seg + 1):
            a = math.radians(a0 + 90.0 * k / seg)
            pts.append((cx + ox + r * math.cos(a), cy + oy + r * math.sin(a)))
    return pts


def loft(rings, smooth=True, inward=False):
    """Stacked rings of equal length [(pts2d, z)] or [[(x,y,z)...]], quads
    between consecutive rings. Rings go upward and CCW -> outward faces."""
    g = Geo()
    ids = []
    for ring in rings:
        row = []
        if isinstance(ring, tuple) and len(ring) == 2 and not isinstance(ring[1], (list, tuple)):
            pts, z = ring
            for p in pts:
                g.v.append([p[0], p[1], z])
                row.append(len(g.v) - 1)
        else:
            for p in ring:
                g.v.append(list(p))
                row.append(len(g.v) - 1)
        ids.append(row)
    n = len(ids[0])
    for k in range(len(ids) - 1):
        A, B = ids[k], ids[k + 1]
        for i in range(n):
            j = (i + 1) % n
            f = (A[i], A[j], B[j], B[i])
            g.f.append((f[::-1] if inward else f, smooth))
    return g


def cap(pts, z, up=True):
    """A flat (convex) polygon at height z, fanned from its centroid."""
    g = Geo()
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    g.v.append([cx, cy, z])
    for p in pts:
        g.v.append([p[0], p[1], z])
    n = len(pts)
    for i in range(n):
        a, b = 1 + i, 1 + (i + 1) % n
        g.f.append(((0, a, b) if up else (0, b, a), False))
    return g


def handle_bar(xf, yc, zc, L, vertical=False, rad=0.006, stand=0.028, n=6):
    """A staple pull standing off a front whose face is the plane x = xf."""
    if vertical:
        P = [(xf - 0.002, yc, zc - L / 2), (xf + stand, yc, zc - L / 2), (xf + stand, yc, zc + L / 2), (xf - 0.002, yc, zc + L / 2)]
        up = (0.0, 1.0, 0.0)
    else:
        P = [(xf - 0.002, yc - L / 2, zc), (xf + stand, yc - L / 2, zc), (xf + stand, yc + L / 2, zc), (xf - 0.002, yc + L / 2, zc)]
        up = (0.0, 0.0, 1.0)
    return sweep(P, rad, n=n, cap0=False, cap1=False, smooth=True, up=up)


def smoothstep(e0, e1, x):
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0))) if e1 != e0 else (1.0 if x >= e1 else 0.0)
    return t * t * (3 - 2 * t)


# =====================================================================
# the drape: a soft slab lying on a rectangle and falling over its edges
# =====================================================================
def drape(mx1, my, zm, R, foot=True, bulge=None):
    """Flat-space (u, v, t) -> 3D. The mid-surface lies at z = zm over
    u <= mx1, |v| <= my, then rolls over those edges on radius R and hangs
    straight. t is the offset along the sheet's normal. bulge(u, v) adds a
    quilted puff on the flat part."""
    q = R * math.pi / 2

    def f(u, v, t):
        dx = max(0.0, u - mx1) if foot else 0.0
        dy = max(0.0, abs(v) - my)
        s = math.hypot(dx, dy)
        zb = bulge(u, v) if bulge else 0.0
        if s < 1e-9:
            return (u, v, zm + t + zb)
        ux = dx / s
        uy = math.copysign(dy / s, v) if dy > 0 else 0.0
        bx = mx1 if dx > 0 else u
        by = math.copysign(my, v) if dy > 0 else v
        if s <= q:
            th = s / R
            hh, zz, nh, nz = R * math.sin(th), -R * (1 - math.cos(th)), math.sin(th), math.cos(th)
        else:
            hh, zz, nh, nz = R, -R - (s - q), 1.0, 0.0
        hh += t * nh
        return (bx + ux * hh, by + uy * hh, zm + zz + t * nz + zb)
    return f


def soft_layer(u0, u1, vh, th, mx1, my, zm, R, zhem, foot=True, bulge=None, extra=None, k=1, ucuts=(), vcuts=()):
    """One draped layer (duvet, sheet fold, throw): a rounded slab of
    thickness th in flat space from u0 to u1 (or to the foot hem), +-vh
    (or to the side hems), bent by drape(). zhem: the height the hanging
    hem's mid-line reaches. Its underside is left out (it lies on the
    mattress or hangs a centimetre off its side: never seen)."""
    q = R * math.pi / 2
    straight = max(0.0, zm - R - zhem)
    ext = q + straight
    uend = mx1 + ext if foot else u1
    vend = my + ext if vh is None else vh
    f = drape(mx1, my, zm, R, foot, bulge)
    uc = [mx1, mx1 + q * 0.5, mx1 + q] if foot else []
    uc += list(ucuts)
    vc = [-my, my, -my - q * 0.5, my + q * 0.5, -my - q, my + q] + list(vcuts)

    def deform(x, y, z):
        p = f(x, y, z - zm)
        if extra:
            p = extra(x, y, p)
        return p
    return rbox((u0, -vend, zm - th / 2), (uend, vend, zm + th / 2), th / 2 * 0.98, k=k,
                cuts=(uc, vc, []), deform=deform, skip=('-z',))


# =====================================================================
# BEDROOM
# =====================================================================
def b_bed(K, w, d, rng, duvet='int_fabric_bluegrey', pillows=3, upholstery='int_fabric_sofa',
          throw='int_fabric_dark', fold='int_fabric_white', deco=None, legs='int_wood_oak',
          headboard_h=1.05, **_):
    x0, x1 = -d / 2, d / 2
    HB = 0.08
    TOP = 0.55                    # mattress top
    MB = 0.34                     # mattress bottom / base top
    deco = deco or duvet
    # headboard: one upholstered panel, rounded all round
    K.add(upholstery, rbox((x0, -w / 2, 0.04), (x0 + HB, w / 2, headboard_h), 0.035, k=(1, 2, 2)))
    # upholstered base on short tapered oak legs
    bx0, bx1, by = x0 + HB, x1 - 0.04, w / 2 - 0.04
    K.add(upholstery, rbox((bx0, -by, 0.12), (bx1, by, MB), 0.025, k=1))
    for lx in (bx0 + 0.10, bx1 - 0.10):
        for ly in (-by + 0.10, by - 0.10):
            K.add(legs, lathe([(0, 0), (0.016, 0), (0.024, 0.12)], 7, c=(lx, ly, 0)))
    # mattress
    mx0, mx1, my_m = x0 + HB + 0.005, x1 - 0.05, w / 2 - 0.05
    RM = 0.045
    K.add('int_fabric_white', rbox((mx0, -my_m, MB), (mx1, my_m, TOP), RM, k=1, skip=('-z',)))
    # the duvet: on the mattress from the pillows to the foot, rolling over
    # the sides and the foot, a quilted puff in the middle
    th = 0.07
    R = RM + th / 2 + 0.003
    ex, ey = mx1 - RM, my_m - RM            # where the mattress top starts to round
    zm = TOP + th / 2 + 0.002
    xs = mx0 + 0.60
    uc, uh = (xs + ex) / 2, (ex - xs) / 2

    def bulge(u, v):
        a = max(0.0, 1 - (v / ey) ** 2)
        b = max(0.0, 1 - ((u - uc) / uh) ** 2)
        return 0.018 * a * b
    K.add(duvet, soft_layer(xs, None, None, th, ex, ey, zm, R, zhem=MB + 0.06, bulge=bulge,
                            ucuts=[uc], vcuts=[0.0]))
    # the top sheet turned down over the duvet's head end
    t2 = 0.026
    zm2 = zm + th / 2 + t2 / 2
    R2 = R + th / 2 + t2 / 2
    u0 = xs - 0.055

    def roll(x, y, p):
        # the leading edge rolls down over the duvet's end onto the mattress
        k = smoothstep(xs + 0.01, xs - 0.05, x)
        return (p[0], p[1], p[2] - k * th)
    K.add(fold, soft_layer(u0, xs + 0.30, None, t2, ex, ey, zm2, R2, zhem=TOP - 0.02, foot=False,
                           bulge=bulge, extra=roll, ucuts=[xs - 0.03, xs], vcuts=[0.0]))
    # a throw across the foot
    if throw:
        t3 = 0.016
        zm3 = zm + th / 2 + t3 / 2
        R3 = R + th / 2 + t3 / 2
        ta, tb = ex - 0.62, ex - 0.12
        K.add(throw, soft_layer(ta, tb, None, t3, ex, ey, zm3, R3, zhem=MB + 0.12, foot=False,
                                bulge=bulge, vcuts=[0.0]))
    # pillows: two to sleep on, leaning on the headboard, then cushions
    npl = int(max(2, min(4, pillows)))
    py = min(0.72, my_m - 0.03)             # one pillow's length across
    pcx = mx0 + 0.27
    for s in (-1, 1):
        g = spe((0, 0, 0), 0.25, py / 2, 0.08, e1=1.45, e2=0.42, nu=12, nv=6)
        g.roty(math.radians(16 + rng.uniform(-3, 3)))
        g.rotz(math.radians(rng.uniform(-3, 3)))
        (a, b) = g.bbox()
        g.move(pcx, s * (py / 2 + 0.012), TOP - a[2] - 0.012)
        (a, b) = g.bbox()
        if a[0] < x0 + HB + 0.005:
            g.move(x0 + HB + 0.005 - a[0], 0, 0)
        K.add('int_fabric_white', g)
    cushions = []
    if npl == 3:
        cushions = [(0.0, 0.50, 0.30)]          # a lumbar cushion in the middle
    elif npl == 4:
        cushions = [(-1, 0.44, 0.44), (1, 0.44, 0.44)]
    for (s, cy, cz) in cushions:
        # made lying (seam round its thin axis), then stood up, leaning back
        g = spe((0, 0, 0), cz / 2, cy / 2, 0.075, e1=1.4, e2=0.62, nu=16, nv=6)
        g.roty(math.radians(-(90 - 24) + rng.uniform(-4, 4)))
        g.rotx(math.radians(rng.uniform(-4, 4)))
        (a, b) = g.bbox()
        yy = s * min(py / 2, my_m - 0.25)
        g.move(pcx + 0.17 - (a[0] + b[0]) / 2, yy, TOP - a[2] - 0.015)
        K.add(deco, g)


def b_nightstand(K, w, d, rng, h=0.52, body='int_white_gloss', front='int_wood_oak', top='int_wood_oak',
                 lamp=1, lamp_side=0.0, **_):
    x0, x1, y0, y1 = -d / 2, d / 2, -w / 2, w / 2
    LEG = 0.17
    T = 0.022
    zt = h - T
    # tapered, slightly splayed oak legs
    for lx in (x0 + 0.045, x1 - 0.045):
        for ly in (y0 + 0.045, y1 - 0.045):
            ox = math.copysign(0.012, lx)
            oy = math.copysign(0.012, ly)
            K.add(top, sweep([(lx + ox, ly + oy, 0.0), (lx, ly, LEG + 0.004)], [0.0095, 0.0145], n=7, cap1=False)
                  .map(lambda x, y, z: (x, y, max(0.0, z))))
    P = 0.016
    B = body
    K.add(B, box((x0, y0, LEG), (x1, y1, LEG + P)))                         # bottom
    K.add(B, box((x0, y0, LEG + P), (x1, y0 + P, zt)))                      # sides
    K.add(B, box((x0, y1 - P, LEG + P), (x1, y1, zt)))
    K.add(B, box((x0, y0 + P, LEG + P), (x0 + P, y1 - P, zt), skip=('-x',)))  # back
    mid = LEG + (zt - LEG) * 0.46
    K.add(B, box((x0 + P, y0 + P, mid - P), (x1 - 0.002, y1 - P, mid)))       # shelf
    K.add(B, box((x0 + P, y0 + P, mid), (x1 - 0.02, y1 - P, zt), skip=('+z', '-z', '-y', '+y')))  # drawer box face
    # oak top, a soft edge
    K.add(top, chbox((x0 - 0.004, y0 - 0.004, zt), (x1 + 0.006, y1 + 0.004, h), 0.004))
    # the drawer front, set in between the sides
    K.add(front, cbox((x1 - 0.018, y0 + P + 0.002, mid + 0.002), (x1 + 0.002, y1 - P - 0.002, zt - 0.002), 0.003))
    K.add('int_brass', lathe([(0, 0), (0.006, 0), (0.006, 0.012), (0.012, 0.018), (0.011, 0.024), (0, 0.025)], 8,
                             c=(0, 0, 0)).roty(math.pi / 2).move(x1 + 0.002, 0, (mid + zt) / 2))
    # a book lying in the niche
    bw = min(0.22, w - 2 * P - 0.06)
    K.add('int_accent_red', chbox((x0 + 0.05, -bw / 2, LEG + P), (min(x1 - 0.04, x0 + 0.05 + 0.16), bw / 2, LEG + P + 0.03), 0.003))
    # the lamp: a bellied ceramic base, brass stem, a drum shade that glows
    if lamp:
        lx = x0 + max(0.13, min(d * 0.5, 0.18))
        ly = max(-(w / 2 - 0.12), min(w / 2 - 0.12, lamp_side * (w / 2 - 0.12)))
        z = h
        base = [(0, 0), (0.045, 0), (0.064, 0.05), (0.058, 0.12), (0.03, 0.16), (0.012, 0.176), (0.0, 0.178)]
        K.add('int_ceramic', lathe([(r, z + zz) for r, zz in base], 12, c=(lx, ly, 0)))
        K.add('int_brass', lathe([(0, z + 0.175), (0.006, z + 0.175), (0.006, z + 0.36), (0, z + 0.36)], 8, c=(lx, ly, 0)))
        sr = min(0.13, w / 2 - 0.01)
        K.add('int_lamp_shade', lathe([(sr, z + 0.25), (sr * 0.84, z + 0.43)], 18, c=(lx, ly, 0)))
        K.add('int_brass', lathe([(sr * 0.84 + 0.001, z + 0.425), (sr * 0.84 + 0.001, z + 0.43)], 18, c=(lx, ly, 0), smooth=False))


def b_wardrobe(K, w, d, rng, h=2.30, front='int_white_gloss', body='int_white_gloss', handle='int_brass', **_):
    x0, x1, y0, y1 = -d / 2, d / 2, -w / 2, w / 2
    PL = 0.08
    fx = x1                       # door face
    FT = 0.019
    P = 0.018
    K.add('int_black', box((x0, y0 + 0.01, 0), (fx - FT - 0.05, y1 - 0.01, PL), skip=('-z',)))
    K.add(body, box((x0, y0, PL), (fx - FT - 0.003, y0 + P, h)))                 # sides
    K.add(body, box((x0, y1 - P, PL), (fx - FT - 0.003, y1, h)))
    K.add(body, box((x0, y0 + P, h - P), (fx - FT - 0.003, y1 - P, h), skip=('-z',)))  # top
    K.add(body, box((x0, y0 + P, PL), (fx - FT - 0.003, y1 - P, PL + P), skip=('+z',)))
    K.add('int_black', box((fx - FT - 0.0025, y0 + P, PL + P), (fx - FT - 0.002, y1 - P, h - P), skip=('-x', '-y', '+y', '-z', '+z')))
    n = max(1, int(round(w / 0.55)))
    gap = 0.003
    dw = w / n
    for i in range(n):
        a, b = y0 + i * dw + gap / 2, y0 + (i + 1) * dw - gap / 2
        K.add(front, cbox((fx - FT, a, PL + gap), (fx, b, h - gap)))
        # pulls at the meeting edges: a door's pull is on the side away from its hinge
        if n == 1:
            yc = b - 0.06
        else:
            yc = (b - 0.06) if i % 2 == 0 else (a + 0.06)
        K.add(handle, handle_bar(fx, yc, 1.05, 0.40, vertical=True, rad=0.007, stand=0.03))


def b_dresser(K, w, d, rng, h=0.80, wood='int_wood_walnut', legs='int_wood_walnut', knobs='int_brass',
              decor=1, mirror=1, **_):
    x0, x1, y0, y1 = -d / 2, d / 2, -w / 2, w / 2
    LEG = 0.16
    FT = 0.018
    for lx in (x0 + 0.05, x1 - 0.06):
        for ly in (y0 + 0.05, y1 - 0.05):
            ox = math.copysign(0.015, lx)
            oy = math.copysign(0.015, ly)
            K.add(legs, sweep([(lx + ox, ly + oy, 0.0), (lx, ly, LEG + 0.004)], [0.009, 0.016], n=7, cap1=False)
                  .map(lambda x, y, z: (x, y, max(0.0, z))))
    K.add(wood, chbox((x0, y0, LEG), (x1 - FT, y1, h), 0.006))
    K.add('int_black', box((x1 - FT - 0.0015, y0 + 0.012, LEG + 0.012), (x1 - FT - 0.001, y1 - 0.012, h - 0.012),
                           skip=('-x', '-y', '+y', '-z', '+z')))
    cols = 2 if w >= 1.0 else 1
    rows = 3
    gap = 0.003
    za, zb = LEG + 0.012, h - 0.012
    cw = (y1 - y0 - 0.024) / cols
    rh = (zb - za) / rows
    for ci in range(cols):
        for ri in range(rows):
            a = y0 + 0.012 + ci * cw + gap / 2
            b = a + cw - gap
            z0 = za + ri * rh + gap / 2
            z1 = z0 + rh - gap
            K.add(wood, cbox((x1 - FT, a, z0), (x1, b, z1)))
            L = min(0.22, cw - 0.16)
            if L > 0.07:
                K.add(knobs, handle_bar(x1, (a + b) / 2, (z0 + z1) / 2 + 0.03, L, rad=0.005, stand=0.024))
    if decor:
        # a ceramic vase with three twigs, two books, on the top
        vx, vy = x0 + d * 0.45, y1 - min(0.22, w * 0.2)
        prof = [(0, 0), (0.035, 0), (0.06, 0.06), (0.058, 0.14), (0.03, 0.2), (0.026, 0.24), (0.032, 0.25), (0.026, 0.25), (0.02, 0.21), (0, 0.21)]
        K.add('int_pot', lathe([(r, h + z) for r, z in prof], 14, c=(vx, vy, 0)))
        for k, (ax, ay, L) in enumerate(((0.10, 0.04, 0.42), (-0.06, 0.09, 0.50), (0.02, -0.10, 0.36))):
            p0 = (vx, vy, h + 0.20)
            p1 = (vx + ax * 0.5, vy + ay * 0.5, h + 0.21 + L * 0.55)
            p2 = (vx + ax, vy + ay, h + 0.21 + L)
            K.add('bark', sweep([p0, p1, p2], [0.004, 0.003, 0.0015], n=4, cap0=False))
        bx = x0 + d * 0.5
        by = y0 + min(0.25, w * 0.22)
        K.add('int_accent_red', chbox((bx - 0.11, by - 0.15, h), (bx + 0.11, by + 0.15, h + 0.028), 0.003))
        K.add('int_fabric_white', chbox((bx - 0.10, by - 0.13, h + 0.028), (bx + 0.09, by + 0.12, h + 0.05), 0.003)
              .rotz(math.radians(7), bx, by))
    if mirror:
        # a round mirror on the wall above, a brass rim
        rr = min(0.38, w * 0.33)
        zc = h + 0.30 + rr
        K.add('int_mirror', lathe([(0, 0), (rr, 0), (rr, 0.008), (0, 0.008)], 24).roty(math.pi / 2).move(x0 + 0.004, 0, zc))
        rim = []
        for i in range(25):
            a = TAU * i / 24
            rim.append((x0 + 0.014, rr * math.cos(a), zc + rr * math.sin(a)))
        K.add('int_brass', sweep(rim, 0.008, n=5, cap0=False, cap1=False, up=(1.0, 0.0, 0.0)))


def b_rug(K, w, d, rng, mat='int_rug', **_):
    K.add(mat, slab(rrect(0.0, 0.0, d / 2, w / 2, 0.02, 2), 0.0, 0.012, 0.004, skip_bottom=True))


# =====================================================================
# KITCHEN
# =====================================================================
KZ = dict(plinth=0.12, top0=0.86, top1=0.90, up0=1.45, up1=2.20, updep=0.35)
SINK_CUT = (-0.12, 0.20, -0.215, 0.215)        # worktop cut-out in the sink's own frame (x0, x1, y0, y1)


def worktop(x0, x1, y0, y1, Z0, Z1, hole=None, r=0.003):
    """One worktop slab, a soft arris on its front (+X) top edge, an
    optional rectangular cut-out (hx0, hx1, hy0, hy1) - one mesh, so no
    seams run across the top. Underside left out. Flat."""
    g = Geo()
    ids = {}

    def V(x, y, z):
        k = (round(x, 6), round(y, 6), round(z, 6))
        if k not in ids:
            g.v.append([x, y, z])
            ids[k] = len(g.v) - 1
        return ids[k]
    xs = [x0, x1 - r]
    ys = [y0, y1]
    if hole:
        hx0, hx1 = max(x0 + 0.01, hole[0]), min(x1 - r - 0.01, hole[1])
        hy0, hy1 = max(y0 + 0.01, hole[2]), min(y1 - 0.01, hole[3])
        if hx1 - hx0 > 0.05 and hy1 - hy0 > 0.05:
            xs = [x0, hx0, hx1, x1 - r]
            ys = [y0, hy0, hy1, y1]
        else:
            hole = None
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            if hole and i == 1 and j == 1:
                continue
            g.f.append(((V(xs[i], ys[j], Z1), V(xs[i + 1], ys[j], Z1), V(xs[i + 1], ys[j + 1], Z1), V(xs[i], ys[j + 1], Z1)), False))
    for j in range(len(ys) - 1):
        a, b = ys[j], ys[j + 1]
        g.f.append(((V(x1 - r, a, Z1), V(x1, a, Z1 - r), V(x1, b, Z1 - r), V(x1 - r, b, Z1)), False))
        g.f.append(((V(x1, a, Z0), V(x1, b, Z0), V(x1, b, Z1 - r), V(x1, a, Z1 - r)), False))
        g.f.append(((V(x0, b, Z0), V(x0, a, Z0), V(x0, a, Z1), V(x0, b, Z1)), False))
    for (yy, sgn) in ((y0, 1), (y1, -1)):
        poly = [V(xx, yy, Z1) for xx in xs[:-1]]
        ring = [V(x0, yy, Z0), V(x1, yy, Z0), V(x1, yy, Z1 - r)] + [V(xx, yy, Z1) for xx in reversed(xs)]
        if sgn < 0:
            ring = ring[::-1]
        for k in range(1, len(ring) - 1):
            g.f.append(((ring[0], ring[k], ring[k + 1]), False))
    if hole:
        hx0, hx1, hy0, hy1 = xs[1], xs[2], ys[1], ys[2]
        g.f.append(((V(hx0, hy0, Z0), V(hx0, hy1, Z0), V(hx0, hy1, Z1), V(hx0, hy0, Z1)), False))
        g.f.append(((V(hx1, hy1, Z0), V(hx1, hy0, Z0), V(hx1, hy0, Z1), V(hx1, hy1, Z1)), False))
        g.f.append(((V(hx1, hy0, Z0), V(hx0, hy0, Z0), V(hx0, hy0, Z1), V(hx1, hy0, Z1)), False))
        g.f.append(((V(hx0, hy1, Z0), V(hx1, hy1, Z0), V(hx1, hy1, Z1), V(hx0, hy1, Z1)), False))
    return g


def _merge_strips(prof):
    st = [list(s) for s in prof if s[1] - s[0] > 1e-4 and s[2] > 0]
    st.sort()
    changed = True
    while changed:
        changed = False
        for i, s in enumerate(st):
            if s[1] - s[0] >= 0.06 or len(st) == 1:
                continue
            nb = []
            if i > 0 and abs(st[i - 1][1] - s[0]) < 1e-3:
                nb.append(i - 1)
            if i + 1 < len(st) and abs(st[i + 1][0] - s[1]) < 1e-3:
                nb.append(i + 1)
            nb = [j for j in nb if st[j][2] <= s[2] + 1e-6]
            if not nb:
                continue
            j = min(nb, key=lambda j: st[j][2])
            st[j][0] = min(st[j][0], s[0])
            st[j][1] = max(st[j][1], s[1])
            st.pop(i)
            changed = True
            break
    return st


def _groups(st):
    gs = []
    for s in st:
        if gs and abs(gs[-1][-1][1] - s[0]) < 1e-3:
            gs[-1].append(s)
        else:
            gs.append([s])
    return gs


def _modules(Y0, Y1, fixed, target=0.6, seed=0):
    """Split [Y0, Y1] into cabinet modules around fixed ones (sink, oven)."""
    out = []
    cur = Y0
    fx = sorted([f for f in fixed if f[0] - f[1] / 2 < Y1 - 0.05 and f[0] + f[1] / 2 > Y0 + 0.05])
    fills = []
    for (yc, wd, kd) in fx:
        a, b = max(cur, yc - wd / 2), min(Y1, yc + wd / 2)
        if b - a < 0.25:
            continue
        if a - cur < 0.2:
            a = cur
        else:
            fills.append((cur, a))
        out.append((a, b, kd))
        cur = b
    if Y1 - cur < 0.2 and out:
        a, b, kd = out[-1]
        out[-1] = (a, Y1, kd)
    elif Y1 - cur > 1e-6:
        fills.append((cur, Y1))
    k = seed
    for (a, b) in fills:
        n = max(1, int(round((b - a) / target)))
        for i in range(n):
            ya, yb = a + (b - a) * i / n, a + (b - a) * (i + 1) / n
            kd = 'drawers' if (k % 2 == 0 and yb - ya >= 0.35) else 'door'
            out.append((ya, yb, kd))
            k += 1
    out.sort()
    return out


def _base_fronts(K, ya, yb, kind, fx, front, handle):
    """Fronts of one base module, faces on x = fx."""
    FT = 0.018
    g = 0.003
    z0, z1 = KZ['plinth'] + g / 2, KZ['top0'] - g / 2
    a, b = ya + g / 2, yb - g / 2
    yc, wd = (a + b) / 2, b - a
    L = min(0.32, wd - 0.12)

    def panel(za, zb, aa=a, bb=b, mat=front, pull=True):
        K.add(mat, cbox((fx - FT, aa, za), (fx, bb, zb)))
        LL = min(0.32, bb - aa - 0.12)
        if pull and LL > 0.07:
            K.add(handle, handle_bar(fx, (aa + bb) / 2, zb - 0.038, LL))
    if kind == 'drawers':
        zt = z1 - 0.165
        mid = (z0 + zt) / 2
        panel(zt + g / 2, z1)
        panel(mid + g / 2, zt - g / 2)
        panel(z0, mid - g / 2)
    elif kind == 'sink' and wd > 0.55:
        panel(z0, z1, a, yc - g / 2)
        panel(z0, z1, yc + g / 2, b)
    elif kind == 'oven':
        zo = z1 - 0.12
        panel(zo + g / 2, z1)
        # a built-in oven: brushed fascia with two knobs, black glass door
        K.add('frame_light', cbox((fx - FT, a, zo - 0.085), (fx - 0.002, b, zo - g / 2)))
        for s in (-1, 1):
            K.add('int_black', lathe([(0, 0), (0.016, 0), (0.016, 0.018), (0, 0.02)], 10).roty(math.pi / 2)
                  .move(fx - 0.002, yc + s * wd * 0.33, zo - 0.043))
        K.add('int_black', box((fx - 0.003, yc - 0.05, zo - 0.058), (fx - 0.0015, yc + 0.05, zo - 0.028), skip=('-x',)))
        K.add('int_black', cbox((fx - FT, a, z0 + 0.012), (fx, b, zo - 0.088), 0.003))
        K.add('frame_light', handle_bar(fx, yc, zo - 0.125, wd - 0.10, rad=0.008, stand=0.035))
    else:
        panel(z0, z1)


def b_kitchen_run(K, w, d, rng, upper=True, profile=None, sink_x=None, sink_y=None, hob_x=None, hob_y=None,
                  front='int_white_gloss', body='int_white_gloss', top='int_mint', splash=None,
                  handle='int_brass', seed=0, **_):
    x1 = d / 2
    FT = 0.018
    fx = x1 - 0.025                           # front face of the doors
    st = _merge_strips(profile) if profile else [[-w / 2, w / 2, d]]
    if splash is None:
        splash = upper
    hole = None
    if sink_y is not None:
        sx = 0.03 if sink_x is None else sink_x
        hole = (sx + SINK_CUT[0], sx + SINK_CUT[1], sink_y + SINK_CUT[2], sink_y + SINK_CUT[3])
    for (y0, y1, dep) in st:
        x0 = x1 - dep
        # plinth (recessed), carcass floor, worktop
        K.add('int_black', box((x0 + 0.02, y0, 0.0), (fx - 0.06, y1, KZ['plinth']), skip=('-z', '-x')))
        K.add(body, box((x0, y0, KZ['plinth'] - 0.002), (fx - FT - 0.004, y1, KZ['plinth'] + 0.016), skip=('-z', '-x')))
        Z0, Z1 = KZ['top0'], KZ['top1']
        hh = None
        if hole and hole[2] < y1 - 0.05 and hole[3] > y0 + 0.05 and hole[0] < x1 and hole[1] > x0:
            hh = hole
        K.add(top, worktop(x0, x1, y0, y1, Z0, Z1, hh))
        if splash:
            K.add(top, box((x0, y0, Z1), (x0 + 0.008, y1, KZ['up0'] if upper else 1.50), skip=('-x', '-z')))
    # per contiguous group: end panels, the shadow behind the gaps, fronts
    fixed = []
    if sink_y is not None:
        fixed.append((sink_y, 0.80 if w >= 1.6 else 0.6, 'sink'))
    if hob_y is not None:
        fixed.append((hob_y, 0.60, 'oven'))
    for grp in _groups(st):
        Y0, Y1 = grp[0][0], grp[-1][1]
        for (yy, dep, s) in ((Y0, grp[0][2], 1), (Y1, grp[-1][2], -1)):
            K.add(body, box((x1 - dep, min(yy, yy + s * 0.018), KZ['plinth'] - 0.002),
                            (fx - FT - 0.001, max(yy, yy + s * 0.018), KZ['top0']), skip=('-x', '+z')))
        K.add('int_black', box((fx - FT - 0.0025, Y0 + 0.018, KZ['plinth']), (fx - FT - 0.002, Y1 - 0.018, KZ['top0']),
                               skip=('-x', '-y', '+y', '-z', '+z')))
        for (ya, yb, kd) in _modules(Y0, Y1, fixed, seed=seed):
            _base_fronts(K, ya, yb, kd, fx, front, handle)
        # wall cabinets where a wall stands behind (strips >= 35 cm deep)
        if upper:
            # not in front of a column or duct the run steps round: there the
            # column itself is the wall, and a cabinet would stand out to
            # the worktop's edge
            dmax = max(s[2] for s in grp)
            ust = [s for s in grp if s[2] >= max(KZ['updep'], dmax - 0.05) - 1e-6 and s[1] - s[0] >= 0.25]
            for ug in _groups(ust):
                UY0, UY1 = ug[0][0], ug[-1][1]
                for (y0, y1, dep) in ug:
                    xb = x1 - dep
                    xf = xb + KZ['updep']
                    K.add(body, box((xb, y0, KZ['up0']), (xf - FT - 0.002, y1, KZ['up1']), skip=('-x',)))
                    # a warm LED strip under the front edge
                    K.add('int_lamp_shade', box((xf - FT - 0.045, max(y0, UY0 + 0.03), KZ['up0'] - 0.006),
                                                (xf - FT - 0.03, min(y1, UY1 - 0.03), KZ['up0']), skip=('+z',)))
                xf = x1 - max(s[2] for s in ug) + KZ['updep']
                # fronts along the wall-cabinet group (its back may step; the
                # fronts follow the deepest strip's line, strips stepping
                # forward are rare and narrow)
                n = max(1, int(round((UY1 - UY0) / 0.6)))
                for i in range(n):
                    a = UY0 + (UY1 - UY0) * i / n + 0.0015
                    b = UY0 + (UY1 - UY0) * (i + 1) / n - 0.0015
                    for (y0, y1, dep) in ug:
                        aa, bb = max(a, y0), min(b, y1)
                        if bb - aa < 0.01:
                            continue
                        xff = x1 - dep + KZ['updep']
                        K.add(front, cbox((xff - FT, aa, KZ['up0'] + 0.0015), (xff, bb, KZ['up1'] - 0.0015)))
                    seg = [s for s in ug if s[0] <= (a + b) / 2 <= s[1]]
                    xff = x1 - (seg[0][2] if seg else ug[0][2]) + KZ['updep']
                    LL = min(0.32, b - a - 0.12)
                    if LL > 0.07:
                        K.add(handle, handle_bar(xff, (a + b) / 2, KZ['up0'] + 0.04, LL))


def b_sink(K, w, d, rng, wall=0.38, bowl='frame_light', tap='chrome', **_):
    """Inset stainless bowl and a gooseneck mixer. Needs the run's worktop
    cut out under it (kitchen_run sink_x/sink_y)."""
    Z = KZ['top1']
    zr = Z + 0.003
    outer = rrect(0.0, 0.0, 0.21, 0.25, 0.02, 3)
    bx0, bx1 = -0.105, 0.185                  # bowl opening (x)
    bcx, bhx, bhy = (bx0 + bx1) / 2, (bx1 - bx0) / 2, 0.20
    inner = rrect(bcx, 0.0, bhx, bhy, 0.035, 3)
    n = len(outer)
    # rim: top surface, outer edge down to the worktop
    g = Geo()
    for p in outer:
        g.v.append([p[0], p[1], zr])
    for p in inner:
        g.v.append([p[0], p[1], zr])
    for p in outer:
        g.v.append([p[0], p[1], Z])
    for i in range(n):
        j = (i + 1) % n
        g.f.append(((i, j, n + j, n + i), False))
        g.f.append(((2 * n + i, 2 * n + j, j, i), False))
    K.add(bowl, g)
    # the bowl: walls straight down, a round into the floor, faces inward
    DEP = 0.19
    zb = zr - DEP
    RC = 0.03
    rings = [(inner, zr)]
    rings.append((rrect(bcx, 0, bhx, bhy, 0.035, 3), zr - 0.006))
    for k in range(0, 4):
        a = math.pi / 2 * k / 3
        off = RC * (1 - math.cos(a))
        zz = zb + RC - RC * math.sin(a)
        rings.append((rrect(bcx, 0, bhx - off, bhy - off, max(0.004, 0.035 - off), 3), zz))
    K.add(bowl, loft(rings, smooth=True))     # rings run downward: faces look in
    last = rrect(bcx, 0, bhx - RC, bhy - RC, 0.005, 3)
    # the floor of the bowl with a waste
    g = Geo()
    g.v.append([bcx, 0.0, zb])
    for p in last:
        g.v.append([p[0], p[1], zb])
    m = len(last)
    for i in range(m):
        g.f.append(((0, 1 + i, 1 + (i + 1) % m), False))
    K.add(bowl, g)
    K.add('chrome', lathe([(0, 0.0005), (0.035, 0.0005), (0.035, 0.003), (0.028, 0.004), (0, 0.004)], 16, c=(bcx + 0.02, 0, zb)))
    # the mixer: a round base, a column that arcs over into the bowl, a lever
    tx = -0.158
    K.add(tap, lathe([(0, 0), (0.027, 0), (0.027, 0.012), (0.022, 0.03), (0, 0.03)], 14, c=(tx, 0, zr)))
    R = 0.085
    col = [(tx, 0, zr + 0.025), (tx, 0, zr + 0.20)]
    for k in range(1, 9):
        a = math.pi - math.pi * k / 8
        col.append((tx + R + R * math.cos(a), 0, zr + 0.20 + R * math.sin(a)))
    col.append((tx + 2 * R, 0, zr + 0.17))
    K.add(tap, sweep(col, [0.0145, 0.0125] + [0.011] * 8 + [0.0125], n=10, cap0=False, cap1=True, up=(1.0, 0.0, 0.0)))
    K.add('int_black', lathe([(0.0115, 0), (0, 0)], 10, c=(tx + 2 * R, 0, zr + 0.1698)))
    K.add(tap, sweep([(tx, 0.010, zr + 0.125), (tx - 0.004, 0.045, zr + 0.135), (tx - 0.008, 0.085, zr + 0.15)],
                     [0.0105, 0.008, 0.0065], n=8, cap0=False, up=(0.0, 0.0, 1.0)))


def b_hob(K, w, d, rng, wall=0.38, upper=True, ceiling=3.0, hood=1, glass='int_black', steel='frame_light', **_):
    """Black glass induction hob with printed zones, the hood above it on
    the wall: a slim pull-out canopy under the wall cabinets (upper) or a
    chimney hood to the ceiling (no wall cabinets)."""
    Z = KZ['top1']
    K.add(glass, rbox((-0.25, -0.29, Z + 0.0002), (0.25, 0.29, Z + 0.006), 0.003, k=1, skip=('-z',)))
    zz = Z + 0.0063
    for (cx, cy, r) in ((-0.08, -0.15, 0.105), (-0.08, 0.15, 0.09), (0.12, -0.15, 0.08), (0.12, 0.15, 0.095)):
        ring = []
        for i in range(24):
            a = TAU * i / 24
            ring.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        ri = [(cx + (p[0] - cx) * (r - 0.004) / r, cy + (p[1] - cy) * (r - 0.004) / r) for p in ring]
        g = Geo()
        for p in ring + ri:
            g.v.append([p[0], p[1], zz])
        for i in range(24):
            j = (i + 1) % 24
            g.f.append(((i, j, 24 + j, 24 + i), False))
        K.add('int_stone_dark', g)
    # the touch strip at the front
    for k in range(7):
        yy = -0.12 + 0.04 * k
        K.add('int_stone_dark', cap([(0.215 + 0.006 * math.cos(TAU * i / 8), yy + 0.006 * math.sin(TAU * i / 8)) for i in range(8)], zz))
    if not hood:
        return
    wx = -wall
    if upper:
        z1 = KZ['up0'] - 0.001
        K.add(steel, box((wx + 0.02, -0.298, z1 - 0.06), (wx + 0.33, 0.298, z1), skip=('+z', '-x')))
        K.add(steel, chbox((wx + 0.20, -0.296, z1 - 0.075), (wx + 0.47, 0.296, z1 - 0.055), 0.004))
        K.add('int_black', box((wx + 0.465, -0.25, z1 - 0.07), (wx + 0.4705, 0.25, z1 - 0.06), skip=('-x',)))
        K.add('int_stone_dark', box((wx + 0.04, -0.27, z1 - 0.0605), (wx + 0.19, 0.27, z1 - 0.06), skip=('+z',)))
    else:
        zc = 1.62
        K.add(steel, chbox((wx + 0.001, -0.30, zc), (wx + 0.50, 0.30, zc + 0.06), 0.004))
        K.add('int_stone_dark', box((wx + 0.03, -0.27, zc - 0.002), (wx + 0.47, 0.27, zc), skip=('+z',)))
        K.add('int_black', box((wx + 0.5, -0.12, zc + 0.02), (wx + 0.5015, 0.12, zc + 0.04), skip=('-x',)))
        K.add(steel, box((wx + 0.001, -0.13, zc + 0.06), (wx + 0.25, 0.13, ceiling - 0.001), skip=('-x', '-z', '+z')))


def b_tower(K, w, d, rng, kind='fridge', h=2.20, front='int_white_gloss', body='int_white_gloss', handle='int_brass',
            hand=1, **_):
    """A tall unit for the end of a kitchen run: an integrated fridge-freezer
    or an oven + combi stack. Plinth, fronts and top line up with
    kitchen_run."""
    x0, x1, y0, y1 = -d / 2, d / 2, -w / 2, w / 2
    FT = 0.018
    fx = x1 - 0.025
    PL = KZ['plinth']
    K.add('int_black', box((x0 + 0.02, y0 + 0.018, 0.0), (fx - 0.06, y1 - 0.018, PL), skip=('-z', '-x')))
    for (a, b) in ((y0, y0 + 0.018), (y1 - 0.018, y1)):
        K.add(body, box((x0, a, 0.0), (fx - FT - 0.001, b, h), skip=('-x', '-z')))
    K.add(body, box((x0, y0 + 0.018, h - 0.018), (fx - FT - 0.001, y1 - 0.018, h), skip=('-x', '-z')))
    K.add('int_black', box((fx - FT - 0.0025, y0 + 0.018, PL), (fx - FT - 0.002, y1 - 0.018, h - 0.018),
                           skip=('-x', '-y', '+y', '-z', '+z')))
    g = 0.003
    a, b = y0 + g / 2, y1 - g / 2
    yc = (a + b) / 2
    ys = b - 0.05 if hand > 0 else a + 0.05

    def panel(z0, z1, mat=front):
        K.add(mat, cbox((fx - FT, a, z0), (fx, b, z1)))
    if kind == 'fridge':
        zm = PL + 0.72
        panel(PL + g / 2, zm - g / 2)
        panel(zm + g / 2, h - g / 2)
        K.add(handle, handle_bar(fx, ys, zm - 0.20, 0.30, vertical=True, rad=0.007, stand=0.03))
        K.add(handle, handle_bar(fx, ys, zm + 0.30, 0.45, vertical=True, rad=0.007, stand=0.03))
    else:
        zo0, zo1 = 0.50, 1.10                 # oven
        zc0, zc1 = 1.10, 1.55                 # compact combi
        dz = (zo0 - PL) / 2
        panel(PL + g / 2, PL + dz - g / 2)
        panel(PL + dz + g / 2, zo0 - g / 2)
        for (za, zb) in ((PL, PL + dz), (PL + dz, zo0)):
            K.add(handle, handle_bar(fx, yc, zb - 0.04, min(0.32, w - 0.14)))
        for (za, zb) in ((zo0, zo1), (zc0, zc1)):
            K.add('frame_light', cbox((fx - FT, a, zb - 0.085), (fx - 0.002, b, zb - g / 2)))
            K.add('int_black', box((fx - 0.003, yc - 0.06, zb - 0.06), (fx - 0.0015, yc + 0.06, zb - 0.03), skip=('-x',)))
            for s in (-1, 1):
                K.add('int_black', lathe([(0, 0), (0.016, 0), (0.016, 0.018), (0, 0.02)], 10).roty(math.pi / 2)
                      .move(fx - 0.002, yc + s * (w * 0.33), zb - 0.045))
            K.add('int_black', cbox((fx - FT, a, za + g / 2), (fx, b, zb - 0.088), 0.003))
            K.add('frame_light', handle_bar(fx, yc, zb - 0.125, w - 0.12, rad=0.008, stand=0.035))
        panel(zc1 + g / 2, h - g / 2)
        K.add(handle, handle_bar(fx, yc, zc1 + 0.045, min(0.32, w - 0.14)))


# =====================================================================
# OFFICE
# =====================================================================
def b_desk(K, w, d, rng, outline=None, top='int_wood_oak', legs='metal_dark', h=0.75, **_):
    if outline:
        pts = [tuple(p) for p in outline]
    else:
        pts = rrect(0.0, 0.0, d / 2, w / 2, 0.02, 3)
    if _area2(pts) < 0:
        pts = pts[::-1]
    T = 0.028
    K.add(top, slab(pts, h - T, h, 0.004))
    n = len(pts)
    feet = []
    convex = []
    for k in range(n):
        p0, p1, p2 = pts[k - 1], pts[k], pts[(k + 1) % n]
        cr = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        convex.append(cr > 1e-9)
    if not outline:
        # a rectangle: legs at its four true corners
        hx, hy = d / 2 - 0.05, w / 2 - 0.05
        feet = [(hx, hy), (-hx, hy), (-hx, -hy), (hx, -hy)]
    else:
        for k in range(n):
            if not convex[k]:
                continue
            p0, p1, p2 = pts[k - 1], pts[k], pts[(k + 1) % n]
            u = _norm((p0[0] - p1[0], p0[1] - p1[1], 0))
            v = _norm((p2[0] - p1[0], p2[1] - p1[1], 0))
            bis = _norm((u[0] + v[0], u[1] + v[1], 0))
            sa = math.sqrt(max(1e-6, (1 - (u[0] * v[0] + u[1] * v[1])) / 2))
            dist = 0.05 / sa
            feet.append((p1[0] + bis[0] * dist, p1[1] + bis[1] * dist))
    S = 0.02
    zt = h - T
    for (fx, fy) in feet:
        K.add(legs, box((fx - S, fy - S, 0.008), (fx + S, fy + S, zt), skip=('+z',)))
        K.add('int_black', lathe([(0, 0), (0.016, 0), (0.016, 0.008), (0, 0.008)], 8, c=(fx, fy, 0)))
    # aprons under the top between neighbouring legs along the outline
    nf = len(feet)
    if not outline:
        pairs = [(0, 1), (1, 2), (2, 3), (3, 0)]
    else:
        idx = [k for k in range(n) if convex[k]]
        pairs = []
        for i in range(len(idx)):
            a, b = idx[i], idx[(i + 1) % len(idx)]
            if (b - a) % n == 1:
                pairs.append((i, (i + 1) % len(idx)))
    for (i, j) in pairs:
        a, b = feet[i], feet[j]
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        if L < 0.1:
            continue
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        g = box((S, -0.01, zt - 0.06), (L - S, 0.01, zt), skip=('+z',))
        g.rotz(ang).move(a[0], a[1], 0)
        K.add(legs, g)


def b_office_chair(K, w, d, rng, base='chrome', shell='int_black', fabric='int_fabric_dark', **_):
    R = max(0.26, min(0.33, min(w, d) / 2 - 0.02))
    SEAT = 0.47
    # five-star base, tapered spokes on casters
    hub = 0.045
    K.add(base, lathe([(0, 0.085), (0.04, 0.085), (0.05, 0.11), (0.03, 0.13), (0, 0.13)], 12))
    for k in range(5):
        a = TAU * k / 5 + math.pi / 5
        ca, sa = math.cos(a), math.sin(a)
        p0 = (hub * ca, hub * sa, 0.105)
        p1 = ((R * 0.55) * ca, (R * 0.55) * sa, 0.095)
        p2 = ((R - 0.015) * ca, (R - 0.015) * sa, 0.075)
        K.add(base, sweep([p0, p1, p2], [0.02, 0.016, 0.012], n=6, cap0=False, cap1=True, up=(0.0, 0.0, 1.0)))
        # caster: a wheel pair under a black hood
        cx, cy = (R - 0.02) * ca, (R - 0.02) * sa
        wheel = spe((0, 0, 0), 0.026, 0.020, 0.026, e1=0.6, e2=0.9, nu=8, nv=4)
        wheel.rotz(a + math.pi / 2).move(cx - 0.012 * ca, cy - 0.012 * sa, 0.026)
        K.add('int_black', wheel)
        K.add('int_black', lathe([(0, 0.05), (0.008, 0.05), (0.008, 0.08), (0, 0.08)], 6, c=(cx, cy, 0)))
    # gas lift and mechanism
    K.add('int_black', lathe([(0, 0.12), (0.03, 0.12), (0.03, 0.27), (0.024, 0.28), (0, 0.28)], 12))
    K.add(base, lathe([(0.02, 0.27), (0.02, SEAT - 0.07), (0, SEAT - 0.07)], 10))
    K.add(shell, box((-0.10, -0.09, SEAT - 0.085), (0.10, 0.09, SEAT - 0.05), skip=('+z',)))
    # the seat: a moulded shell under a soft cushion
    K.add(shell, chbox((-0.235, -0.245, SEAT - 0.055), (0.235, 0.245, SEAT - 0.035), 0.008))
    seat = cushion((0.0, 0.0, SEAT - 0.012), 0.245, 0.255, 0.045, 0.09, seg=3)

    def seat_shape(x, y, z):
        # a waterfall front edge and a slight dish
        dz = -0.008 * max(0.0, 1 - (x / 0.2) ** 2 - (y / 0.2) ** 2)
        if x > 0.12:
            dz -= (x - 0.12) * 0.16
        return (x, y, z + dz)
    seat.map(seat_shape)
    K.add(fabric, seat)
    # the back: a curved cushion on a spine, raked back, wider at the shoulders
    back = cushion((0.0, 0.0, 0.0), 0.27, 0.235, 0.035, 0.11, seg=3)
    back.roty(-math.pi / 2)

    def wrap(x, y, z):
        y2 = y * (1.0 + 0.07 * z / 0.27)
        return (x + 0.09 * (y / 0.235) ** 2, y2, z)
    back.map(wrap)
    back.roty(math.radians(-12)).move(-0.255, 0, SEAT + 0.36)
    K.add(fabric, back)
    spine = [(-0.06, 0, SEAT - 0.06), (-0.24, 0, SEAT - 0.055), (-0.30, 0, SEAT + 0.02), (-0.302, 0, SEAT + 0.22)]
    K.add(shell, sweep(spine, [0.018, 0.018, 0.016, 0.014], n=6, cap0=True, cap1=True, up=(0, 1, 0)))
    # armrests: a loop up from under the seat and a soft pad
    for s in (-1, 1):
        y = s * 0.2
        path = [(-0.05, y * 0.6, SEAT - 0.045), (-0.05, s * 0.255, SEAT - 0.04), (-0.06, s * 0.265, SEAT + 0.17)]
        K.add(shell, sweep(path, 0.012, n=6, cap0=True, cap1=False, up=(1.0, 0.0, 0.0)))
        K.add(shell, chbox((-0.17, s * 0.265 - 0.035, SEAT + 0.17), (0.09, s * 0.265 + 0.035, SEAT + 0.195), 0.009))


def b_desk_equipment(K, w, d, rng, desk_h=0.75, lamp=1, lamp_y=0.36, kb=0.21, **_):
    Z = desk_h
    mx = -d / 2 + 0.09                       # the screen's plane
    Wm = max(0.50, min(0.62, w + 0.08))
    Hm = Wm * 0.565
    z0 = Z + 0.12
    # panel: black glass front, a silver back
    K.add('int_black', rbox((mx - 0.004, -Wm / 2, z0), (mx + 0.004, Wm / 2, z0 + Hm), 0.003, k=1, skip=('-x',)))
    K.add('frame_light', chbox((mx - 0.022, -Wm / 2 + 0.002, z0 + 0.002), (mx - 0.003, Wm / 2 - 0.002, z0 + Hm - 0.002), 0.008))
    # stand: a slanted neck on a flat oval foot
    foot = rrect(mx - 0.03, 0.0, 0.085, 0.11, 0.06, 4)
    K.add('frame_light', slab(foot, Z, Z + 0.007, 0.002, skip_bottom=True))
    neck = [(mx - 0.09, 0, Z + 0.006), (mx - 0.05, 0, z0 + Hm * 0.45)]
    K.add('frame_light', sweep(neck, 0.016, n=4, cap0=False, cap1=True, a0=math.pi / 4, smooth=False, up=(0, 1, 0)))
    # keyboard: a slim silver deck with five rows of black keys
    kx = mx + kb
    KW = min(0.42, max(0.30, w))
    K.add('frame_light', chbox((kx - 0.065, -KW / 2, Z), (kx + 0.065, KW / 2, Z + 0.009), 0.004))
    for r in range(5):
        xx = kx + 0.048 - r * 0.023
        K.add('int_black', box((xx - 0.0095, -KW / 2 + 0.012, Z + 0.009), (xx + 0.0095, KW / 2 - 0.012, Z + 0.0115), skip=('-z',)))
    # mouse on the right (-Y)
    ms = spe((kx + 0.01, -KW / 2 - 0.09, Z), 0.055, 0.032, 0.03, e1=0.8, e2=0.8, nu=10, nv=6)
    ms.map(lambda x, y, z: (x, y, max(z, Z) if z < Z else z))
    K.add('int_black', ms)
    # a notebook to the left of the keyboard
    K.add('int_accent_red', chbox((kx - 0.10, KW / 2 + 0.03, Z), (kx + 0.11, KW / 2 + 0.18, Z + 0.012), 0.003)
          .rotz(math.radians(-8), kx, KW / 2 + 0.1))
    # an anglepoise lamp, behind and to the left
    if lamp:
        lx, ly = -d / 2 + 0.06, lamp_y
        K.add('metal_dark', lathe([(0.075, 0), (0.075, 0.012), (0.055, 0.024), (0, 0.026)], 14, c=(lx, ly, Z)))
        j1 = (lx + 0.02, ly, Z + 0.40)
        j2 = (lx + 0.28, ly, Z + 0.46)
        K.add('metal_dark', sweep([(lx, ly, Z + 0.02), j1, j2], 0.007, n=6, up=(0, 1, 0)))
        K.add('metal_dark', lathe([(0, 0), (0.014, 0), (0.014, 0.02), (0, 0.02)], 8).rotx(math.pi / 2).move(j1[0], j1[1] + 0.01, j1[2]))
        # the shade: a cone looking down, its mouth glowing
        # profile bottom -> top so the cone faces out; its mouth stays open
        # and a glowing disc sits just inside it, facing down
        sh = lathe([(0.075, -0.12), (0.035, -0.04), (0.02, 0.0), (0, 0.0)], 14)
        g2 = Geo().extend(sh)
        g2.roty(math.radians(-25)).move(j2[0] + 0.02, j2[1], j2[2] + 0.01)
        K.add('metal_dark', Geo().extend(g2))
        gl = cap([(0.068 * math.cos(TAU * i / 14), 0.068 * math.sin(TAU * i / 14)) for i in range(14)], 0.0, up=False)
        gl.move(0, 0, -0.112).roty(math.radians(-25)).move(j2[0] + 0.02, j2[1], j2[2] + 0.01)
        K.add('int_lamp_shade', gl)


# =====================================================================
# the table
# =====================================================================
KINDS = {
    'bed_double': dict(
        drawn=True, wall=True, solid=True,
        params=dict(duvet=('int_fabric_bluegrey', None, None), pillows=(3, 2, 4), upholstery=('int_fabric_sofa', None, None),
                    throw=('int_fabric_dark', None, None), fold=('int_fabric_white', None, None), deco=(None, None, None),
                    legs=('int_wood_oak', None, None), headboard_h=(1.05, 0.90, 1.30)),
        footprint='w = across (local Y, the bed\'s width 1.40-2.00), d = along (local X, length 1.90-2.20); '
                  'headboard at -X on the wall, foot at +X. The duvet hangs ~2 cm outside the box at the sides and foot.',
        notes='pillows: 2 sleeping pillows, 3 adds a lumbar cushion, 4 two square cushions (deco material, default the '
              'duvet\'s). throw=None leaves the foot throw out. Pass the existing teal / blue-grey duvet param.'),
    'nightstand': dict(
        drawn=True, wall=True, solid=True,
        params=dict(h=(0.52, 0.45, 0.62), lamp=(1, 0, 1), lamp_side=(0.0, -1.0, 1.0),
                    body=('int_white_gloss', None, None), front=('int_wood_oak', None, None), top=('int_wood_oak', None, None)),
        footprint='w = across (local Y, 0.35-0.60), d = along (local X, 0.28-0.50); back at -X on the wall, the drawer faces +X.',
        notes='lamp_side -1..1 slides the lamp from right (-Y) to left (+Y); for a nightstand on the bed\'s left '
              '(+Y of the bed) pass -1 to keep the lamp near the bed, or 0 (centre) when unknown.'),
    'kitchen_run': dict(
        drawn=True, wall=True, solid=True,
        params=dict(upper=(True, None, None), profile=(None, None, None), sink_x=(None, -0.2, 0.2), sink_y=(None, -3.0, 3.0),
                    hob_x=(None, -0.2, 0.2), hob_y=(None, -3.0, 3.0), front=('int_white_gloss', None, None),
                    top=('int_mint', None, None), handle=('int_brass', None, None), splash=(None, None, None), seed=(0, 0, 99)),
        footprint='w = across (local Y, the run\'s length 0.30-6.00), d = along (local X, the drawn depth 0.45-0.90); '
                  'worktop front at +X = d/2, wall at -X. profile = lib_furnish.kitchen_profile strips [[y0, y1, depth from the front]].',
        notes='Pass sink_y (and sink_x) in the RUN\'s local frame (to_local(sink.at, run.centre, run.rot)) to cut the '
              'worktop under the sink and put a double door there; hob_y puts an oven under the hob. Wall cabinets '
              '1.45-2.20 where upper (and the strip is >= 0.35 deep); splashback only where upper (no window).'),
    'sink': dict(
        drawn=True, wall=False, solid=False,
        params=dict(bowl=('frame_light', None, None), tap=('chrome', None, None)),
        footprint='the fixed module box [0.50 across, 0.42 along] lib_furnish gives; w, d are ignored. Origin at the '
                  'sink\'s spot on the floor; the rim sits on the worktop (z 0.90), the tap at -X (towards the wall).',
        notes='Needs the worktop cut-out: kitchen_run(sink_x=..., sink_y=...) - without it the bowl is hidden under a solid top.'),
    'hob': dict(
        drawn=True, wall=False, solid=False,
        params=dict(wall=(0.38, 0.25, 0.50), upper=(True, None, None), ceiling=(3.0, 2.4, 3.3), hood=(1, 0, 1)),
        footprint='the fixed module box [0.58 across, 0.50 along]; w, d ignored. Glass on the worktop (z 0.90-0.906).',
        notes='wall = distance from the hob origin back to the wall (lib_furnish puts the hob 3 cm in front of the '
              'leg centre: wall = leg depth / 2 + 0.03). upper = the leg\'s upper flag: True -> slim hood under the wall '
              'cabinets (1.38-1.45), False -> chimney hood (1.62) up to `ceiling` (room ceiling above the floor: 3.0 here).'),
    'desk': dict(
        drawn=True, wall=False, solid=True,
        params=dict(outline=(None, None, None), top=('int_wood_oak', None, None), legs=('metal_dark', None, None), h=(0.75, 0.70, 0.78)),
        footprint='outline = lib_furnish\'s local outline (it wins when given); else a w (local Y) x d (local X) rectangle.',
        notes='Legs at every convex corner of the outline, aprons between neighbouring legs.'),
    'office_chair': dict(
        drawn=True, wall=False, solid=True,
        params=dict(base=('chrome', None, None), shell=('int_black', None, None), fabric=('int_fabric_dark', None, None)),
        footprint='w x d (0.45-0.70) sets the star\'s radius; seat front at +X (towards the desk), back at -X.',
        notes='Seat top 0.47, arms 0.66, back to 1.12.'),
    'desk_equipment': dict(
        drawn=True, wall=False, solid=False,
        params=dict(desk_h=(0.75, 0.70, 0.78), lamp=(1, 0, 1), lamp_y=(0.36, -0.5, 0.5), kb=(0.21, 0.12, 0.40)),
        footprint='w = across (local Y), d = along (local X); the screen near -X looks +X (lib_furnish turns it '
                  '180 deg to face the chair). Keyboard kb in front of the screen, mouse at -Y, lamp at (-d/2+0.06, lamp_y).',
        notes='Stands on the desk top (desk_h). In the L01 V-desks the box sits in the V; lamp_y 0.36 keeps the lamp on the left arm.'),
    'wardrobe': dict(
        drawn=False, wall=True, solid=True,
        params=dict(h=(2.30, 1.90, 2.70), front=('int_white_gloss', None, None), handle=('int_brass', None, None)),
        footprint='w = across (local Y, 0.6-3.0), d = along (local X, 0.55-0.65); doors at +X, back on the wall at -X.',
        notes='One door per ~0.55 m, vertical brass pulls at the meeting edges. front=int_wood_oak for oak doors.'),
    'dresser': dict(
        drawn=False, wall=True, solid=True,
        params=dict(h=(0.80, 0.70, 0.95), wood=('int_wood_walnut', None, None), decor=(1, 0, 1), mirror=(1, 0, 1)),
        footprint='w = across (local Y, 0.6-1.6), d = along (local X, 0.40-0.50); drawers at +X, back at -X.',
        notes='mirror=1 hangs a round mirror on the wall above (needs a wall); decor=1 a vase with twigs and two books on top.'),
    'rug_bedroom': dict(
        drawn=False, wall=False, solid=False,
        params=dict(mat=('int_rug', None, None)),
        footprint='w = across (local Y), d = along (local X); 12 mm thick.',
        notes='Under the bed: centre it on the bed\'s footprint shifted ~0.4 m to the foot, w = bed w + 0.8, d = 1.6-2.0.'),
    'fridge_tower': dict(
        drawn=False, wall=True, solid=True,
        params=dict(h=(2.20, 2.0, 2.4), hand=(1, -1, 1), front=('int_white_gloss', None, None)),
        footprint='w = across (0.60), d = along (= the run\'s depth); fronts at +X like kitchen_run, top at 2.20 = wall cabinets.',
        notes='Stand it at either end of a run, same heading. hand=+1 puts the pulls at +Y.'),
    'oven_tower': dict(
        drawn=False, wall=True, solid=True,
        params=dict(h=(2.20, 2.0, 2.4), front=('int_white_gloss', None, None)),
        footprint='as fridge_tower.',
        notes='Two drawers, an oven at 0.50-1.10, a compact combi at 1.10-1.55, a door above.'),
}

DEFAULT_SIZE = {
    'bed_double': (1.80, 2.00), 'nightstand': (0.50, 0.40), 'kitchen_run': (2.50, 0.70), 'sink': (0.50, 0.42),
    'hob': (0.58, 0.50), 'desk': (1.40, 0.70), 'office_chair': (0.60, 0.60), 'desk_equipment': (0.47, 0.35),
    'wardrobe': (1.80, 0.60), 'dresser': (1.20, 0.45), 'rug_bedroom': (2.00, 1.40), 'fridge_tower': (0.60, 0.70),
    'oven_tower': (0.60, 0.70),
}
SIZE_RANGE = {
    'bed_double': ((1.40, 1.90), (2.00, 2.20)), 'nightstand': ((0.35, 0.28), (0.60, 0.50)),
    'kitchen_run': ((0.80, 0.60), (3.55, 0.70)), 'sink': ((0.50, 0.42), (0.50, 0.42)), 'hob': ((0.58, 0.50), (0.58, 0.50)),
    'desk': ((1.00, 0.55), (1.80, 0.80)), 'office_chair': ((0.45, 0.45), (0.70, 0.70)),
    'desk_equipment': ((0.15, 0.10), (0.70, 0.40)), 'wardrobe': ((0.80, 0.55), (3.00, 0.65)),
    'dresser': ((0.70, 0.40), (1.60, 0.50)), 'rug_bedroom': ((1.40, 1.00), (3.00, 2.40)),
    'fridge_tower': ((0.60, 0.60), (0.60, 0.70)), 'oven_tower': ((0.60, 0.60), (0.60, 0.70)),
}

_BUILDERS = {
    'bed_double': b_bed, 'nightstand': b_nightstand, 'kitchen_run': b_kitchen_run, 'sink': b_sink, 'hob': b_hob,
    'desk': b_desk, 'office_chair': b_office_chair, 'desk_equipment': b_desk_equipment, 'wardrobe': b_wardrobe,
    'dresser': b_dresser, 'rug_bedroom': b_rug,
    'fridge_tower': lambda K, w, d, rng, **p: b_tower(K, w, d, rng, kind='fridge', **p),
    'oven_tower': lambda K, w, d, rng, **p: b_tower(K, w, d, rng, kind='oven', **p),
}


def build(kind, w, d, seed=0, **params):
    """-> [(material, verts, faces, smooth)] in the LOCAL FRAME (see module doc)."""
    if kind not in _BUILDERS:
        raise ValueError('furn_kit_bed: unknown kind %r' % kind)
    p = {}
    for k, spec in KINDS[kind]['params'].items():
        p[k] = spec[0]
    p.update(params)
    for k, spec in KINDS[kind]['params'].items():
        v = p.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and spec[1] is not None and spec[2] is not None:
            p[k] = max(spec[1], min(spec[2], v))
    if kind == 'kitchen_run':
        p.setdefault('seed', seed)
    K = Kit()
    _BUILDERS[kind](K, float(w), float(d), random.Random(seed), **p)
    return K.parts()


def tri_count(kind, w, d, **p):
    return sum(sum(len(f) - 2 for f in faces) for (_m, _v, faces, _s) in build(kind, w, d, **p))


# =====================================================================
# Blender preview (bpy only here)
# =====================================================================
PREVIEW_COL = {
    'int_white_gloss': ('#e6e5e1', 0.22, 0.0), 'int_ceramic': ('#ecece9', 0.10, 0.0), 'chrome': ('#cdd0d4', 0.14, 1.0),
    'int_mirror': ('#e0e4e9', 0.03, 1.0), 'int_black': ('#111214', 0.40, 0.2), 'int_brass': ('#b08c55', 0.35, 0.85),
    'int_wood_oak': ('#b3895a', 0.55, 0.0), 'int_wood_walnut': ('#4f3627', 0.48, 0.0), 'int_wood_teak': ('#8a5a32', 0.45, 0.0),
    'int_fabric_sofa': ('#7b7f86', 0.95, 0.0), 'int_fabric_white': ('#eeeae2', 0.85, 0.0), 'int_fabric_teal': ('#3c8a84', 0.92, 0.0),
    'int_fabric_bluegrey': ('#8294a8', 0.92, 0.0), 'int_fabric_dark': ('#3d4148', 0.95, 0.0), 'int_fabric_orange': ('#d6622a', 0.9, 0.0),
    'int_rug': ('#9a9ea5', 0.95, 0.0), 'int_lamp_shade': ('#f1e8d6', 0.7, 0.0), 'int_mint': ('#a7c3b2', 0.30, 0.0),
    'int_marble': ('#e8e5e0', 0.12, 0.0), 'int_stone_dark': ('#3a3a3c', 0.32, 0.0), 'int_accent_red': ('#8b2d29', 0.6, 0.0),
    'int_pot': ('#36322f', 0.6, 0.0), 'metal_dark': ('#43444a', 0.34, 0.9), 'frame_light': ('#d9d6ce', 0.48, 0.3),
    'bark': ('#4a3a2c', 0.9, 0.0), 'foliage': ('#4b6128', 0.6, 0.0), 'int_glass': ('#cfe2ea', 0.05, 0.0),
}

if __name__ == '__main__':
    import sys
    try:
        import bpy  # noqa
    except ImportError:
        bpy = None
    if bpy is None:
        print('%-16s %-16s %6s' % ('kind', 'default w x d', 'tris'))
        for k in KINDS:
            w, d = DEFAULT_SIZE[k]
            print('%-16s %.2f x %.2f %10d' % (k, w, d, tri_count(k, w, d)))
        sys.exit(0)

    # ---------------------------------------------------------------- bpy
    import bmesh
    from mathutils import Vector
    args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []

    def arg(name, default):
        return args[args.index(name) + 1] if name in args else default
    OUTD = arg('--out', '/tmp')
    kinds = arg('--kind', 'bed_double').split(',')
    views = arg('--views', 'eye,top').split(',')
    sizes = arg('--sizes', 'min,def,max').split(',')
    extra = eval(arg('--params', '{}'))
    RES = int(arg('--res', '900'))
    import os
    os.makedirs(OUTD, exist_ok=True)

    def srgb(hx):
        c = [int(hx[i:i + 2], 16) / 255.0 for i in (1, 3, 5)]
        return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c] + [1.0]
    MATS = {}

    def mat(name):
        if name in MATS:
            return MATS[name]
        hx, r, m = PREVIEW_COL.get(name, ('#ff00ff', 0.5, 0.0))
        M = bpy.data.materials.new(name)
        M.use_nodes = True
        b = M.node_tree.nodes.get('Principled BSDF')
        b.inputs['Base Color'].default_value = srgb(hx)
        b.inputs['Roughness'].default_value = r
        b.inputs['Metallic'].default_value = m
        if name == 'int_lamp_shade':
            b.inputs['Emission Color'].default_value = srgb('#ffd9a6')
            b.inputs['Emission Strength'].default_value = 1.5
        if name in ('int_mirror',):
            b.inputs['Roughness'].default_value = 0.02
        M.use_backface_culling = name not in ('int_lamp_shade', 'int_glass', 'int_curtain')
        MATS[name] = M
        return M

    def make_obj(name, parts, loc=(0, 0, 0)):
        V, F, MI, S = [], [], [], []
        names = []
        for (m, v, f, sm) in parts:
            if m not in names:
                names.append(m)
            o = len(V)
            V.extend(v)
            for fc in f:
                F.append([o + i for i in fc])
                MI.append(names.index(m))
                S.append(sm)
        me = bpy.data.meshes.new(name)
        me.from_pydata(V, [], F)
        for m in names:
            me.materials.append(mat(m))
        for p, mi, s in zip(me.polygons, MI, S):
            p.material_index = mi
            p.use_smooth = s
        me.validate(clean_customdata=False)
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(name, me)
        ob.location = loc
        bpy.context.scene.collection.objects.link(ob)
        return ob

    def plane(name, size, loc, rot=(0, 0, 0), col='#b9b5ad'):
        me = bpy.data.meshes.new(name)
        s = size / 2
        me.from_pydata([(-s, -s, 0), (s, -s, 0), (s, s, 0), (-s, s, 0)], [], [(0, 1, 2, 3)])
        M = bpy.data.materials.new(name)
        M.use_nodes = True
        b = M.node_tree.nodes.get('Principled BSDF')
        b.inputs['Base Color'].default_value = srgb(col)
        b.inputs['Roughness'].default_value = 0.8
        me.materials.append(M)
        ob = bpy.data.objects.new(name, me)
        ob.location = loc
        ob.rotation_euler = rot
        bpy.context.scene.collection.objects.link(ob)
        return ob

    def setup():
        for o in list(bpy.data.objects):
            bpy.data.objects.remove(o, do_unlink=True)
        sc = bpy.context.scene
        for eng in ('BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'):
            try:
                sc.render.engine = eng
                break
            except TypeError:
                pass
        sc.render.resolution_x = RES
        sc.render.resolution_y = int(RES * 0.66)
        sc.render.film_transparent = False
        try:
            sc.eevee.taa_render_samples = 48
            sc.eevee.use_shadows = True
            sc.eevee.use_raytracing = True
        except Exception:
            pass
        sc.view_settings.view_transform = 'AgX'
        w = bpy.data.worlds.new('w') if not sc.world else sc.world
        sc.world = w
        w.use_nodes = True
        bg = w.node_tree.nodes.get('Background')
        bg.inputs['Color'].default_value = (0.75, 0.76, 0.78, 1)
        bg.inputs['Strength'].default_value = 0.45
        L = bpy.data.lights.new('key', 'AREA')
        L.energy = 700
        L.size = 5
        ob = bpy.data.objects.new('key', L)
        ob.location = (4, 3, 5)
        ob.rotation_euler = (math.radians(40), 0, math.radians(125))
        sc.collection.objects.link(ob)
        L2 = bpy.data.lights.new('sun', 'SUN')
        L2.energy = 2.0
        L2.angle = math.radians(12)
        ob2 = bpy.data.objects.new('sun', L2)
        ob2.rotation_euler = (math.radians(45), math.radians(10), math.radians(60))
        sc.collection.objects.link(ob2)

    def camera(loc, target, lens=40, ortho=None):
        cd = bpy.data.cameras.new('cam')
        cd.lens = lens
        cd.clip_start = 0.02
        if ortho:
            cd.type = 'ORTHO'
            cd.ortho_scale = ortho
        ob = bpy.data.objects.new('cam', cd)
        bpy.context.scene.collection.objects.link(ob)
        ob.location = loc
        dvec = Vector(target) - Vector(loc)
        ob.rotation_euler = dvec.to_track_quat('-Z', 'Y').to_euler()
        bpy.context.scene.camera = ob
        return ob

    # assemblies: (kind, w, d, params, (x, y), heading deg)
    SCENES = {
        'kitchen': [('kitchen_run', 2.5, 0.7, dict(upper=True, sink_x=0.03, sink_y=-0.55, hob_y=0.65), (0, 0), 0),
                    ('sink', 0.5, 0.42, {}, (0.03, -0.55), 0), ('hob', 0.58, 0.5, dict(wall=0.38, upper=True), (0.03, 0.65), 0),
                    ('fridge_tower', 0.6, 0.7, {}, (0, 1.55), 0), ('oven_tower', 0.6, 0.7, {}, (0, -1.55), 0)],
        'kitchen2': [('kitchen_run', 2.5, 0.7, dict(upper=False, sink_x=0.03, sink_y=0.6, hob_y=-0.5), (0, 0), 0),
                     ('sink', 0.5, 0.42, {}, (0.03, 0.6), 0), ('hob', 0.58, 0.5, dict(wall=0.38, upper=False), (0.03, -0.5), 0)],
        'kitchen3': [('kitchen_run', 2.5, 0.7, dict(upper=True, profile=[[-1.23, -1.07, 0.7], [-1.07, -1.05, 0.52], [-1.05, 0.35, 0.35],
                                                                         [0.35, 0.37, 0.63], [0.37, 1.25, 0.7]], hob_y=0.8), (0, 0), 0),
                     ('hob', 0.58, 0.5, dict(wall=0.38, upper=True), (0.03, 0.8), 0)],
        'bedroom': [('rug_bedroom', 2.6, 1.8, {}, (0.35, 0), 0), ('bed_double', 1.8, 2.0, dict(duvet='int_fabric_teal'), (0, 0), 0),
                    ('nightstand', 0.5, 0.4, dict(lamp_side=0), (-0.8, 1.2), 0), ('nightstand', 0.5, 0.4, dict(lamp_side=0), (-0.8, -1.2), 0),
                    ('wardrobe', 1.8, 0.6, {}, (1.2, 2.1), -90), ('dresser', 1.2, 0.45, {}, (1.6, -2.1), 90)],
        'office': [('desk', 1.5, 1.5, dict(outline=[(-1.06, -0.0), (0.0, -1.06), (0.43, -0.63), (-0.21, -0.0), (0.42, 0.64), (-0.0, 1.06)]), (0, 0), 0),
                   ('office_chair', 0.6, 0.6, {}, (0.35, 0.0), 180), ('desk_equipment', 0.47, 0.35, {}, (-0.43, 0.0), 0)],
    }
    scene = arg('--scene', None)
    if scene:
        setup()
        allz = []
        for i, (kind, w, d, prm, at, hd) in enumerate(SCENES[scene]):
            parts = build(kind, w, d, **prm)
            ob = make_obj('%s_%d' % (kind, i), parts, (at[0], at[1], 0))
            ob.rotation_euler = (0, 0, math.radians(hd))
            allz += [v[2] for (_m, vv, _f, _s) in parts for v in vv]
            print('[kit] %s %d tris' % (kind, sum(len(f) - 2 for (_m, _v, ff, _s) in parts for f in ff)))
        plane('floor', 40, (0, 0, 0))
        if scene.startswith('kitchen'):
            plane('wall', 40, (-0.351, 0, 0), rot=(0, math.radians(90), 0), col='#d6d2ca')
        if scene == 'bedroom':
            plane('wall', 40, (-1.001, 0, 0), rot=(0, math.radians(90), 0), col='#d6d2ca')
        cams = {
            'kitchen': [((3.2, -1.6, 1.6), (0, 0, 1.0)), ((1.3, -0.5, 1.6), (0, -0.4, 0.9)), ((1.4, 0.5, 1.6), (0, 0.65, 1.0))],
            'bedroom': [((3.6, -2.4, 1.6), (0, 0, 0.5)), ((2.6, 1.0, 1.6), (-0.6, 0.6, 0.6)), ((0, 0, 7), None)],
            'office': [((1.8, -1.4, 1.6), (-0.2, 0, 0.7)), ((1.1, 0.5, 1.5), (-0.4, 0, 0.85)), ((-1.8, 1.6, 1.6), (0, 0, 0.6))],
        }
        key = 'kitchen' if scene.startswith('kitchen') else scene
        for ci, (loc, tgt) in enumerate(cams[key]):
            if tgt is None:
                cam = camera(loc, (0, 0.0001, 0), ortho=6.0)
                cam.rotation_euler = (0, 0, math.radians(90))
            else:
                camera(loc, tgt, lens=32)
            bpy.context.scene.render.filepath = os.path.join(OUTD, '%s_%d.png' % (scene, ci))
            bpy.ops.render.render(write_still=True)
        kinds = []

    for kind in kinds:
        setup()
        lo, hi = SIZE_RANGE[kind]
        S = {'min': lo, 'def': DEFAULT_SIZE[kind], 'max': hi}
        ys = 0.0
        placed = []
        H = 0.0
        for sname in sizes:
            w, d = S[sname]
            parts = build(kind, w, d, **extra)
            span = max(w, d) + 0.6
            yc = ys + span / 2
            ob = make_obj('%s_%s' % (kind, sname), parts, (0, yc, 0))
            zs = [v[2] for (_m, vv, _f, _s) in parts for v in vv]
            H = max(H, max(zs))
            placed.append((yc, w, d))
            ys += span
            print('[kit] %s %s %.2f x %.2f  %d tris' % (kind, sname, w, d, sum(len(f) - 2 for (_m, _v, ff, _s) in parts for f in ff)))
        ymid = ys / 2
        plane('floor', 40, (0, ymid, 0))
        if KINDS[kind]['wall'] or kind in ('sink', 'hob'):
            dmax = max(p[2] for p in placed)
            wx = -dmax / 2 - 0.001 if kind not in ('sink', 'hob') else -0.381
            plane('wall', 40, (wx, ymid, 0), rot=(0, math.radians(90), 0), col='#d6d2ca')
        for v in views:
            span = ys
            if v == 'eye':
                dist = max(2.2, span * 0.95 + 0.8)
                camera((dist * 0.82, ymid - dist * 0.42, 1.6), (0, ymid, min(H, 1.4) * 0.45), lens=35)
            elif v == 'top':
                cam = camera((0.0, ymid, 8), (0.0, ymid + 0.0001, 0), ortho=max(span * 1.05, 2.0))
                cam.rotation_euler = (0, 0, math.radians(90))
            elif v == 'low':
                dist = max(1.6, span * 0.7)
                camera((dist * 0.9, ymid + dist * 0.3, 0.55), (0, ymid, H * 0.4), lens=35)
            elif v == 'close':
                dist = max(1.5, span * 0.6)
                camera((dist * 0.85, ymid - dist * 0.3, 1.6), (0, ymid, H * 0.5), lens=40)
            elif v == 'back':
                dist = max(2.2, span * 0.95 + 0.8)
                camera((-dist * 0.82, ymid + dist * 0.42, 1.6), (0, ymid, H * 0.4), lens=35)
            bpy.context.scene.render.filepath = os.path.join(OUTD, '%s_%s.png' % (kind, v))
            bpy.ops.render.render(write_still=True)
