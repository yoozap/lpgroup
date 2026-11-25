# -*- coding: utf-8 -*-
"""Living room and dining kit: modelled pieces for the furnished walkthrough.

Pure python (math + random only) inside build(), so it runs under Blender's
python and the system one alike. Run it with Blender to get preview renders:

    Blender -b -P blender/furn_kit_living.py -- OUTDIR [kind ...]

INTERFACE (what the integrator calls)

    KINDS[kind] = {'drawn', 'params': {name: (default, min, max)}, 'footprint',
                   'wall', 'solid', 'notes'}
    build(kind, w, d, seed=0, **params) -> [(material, verts, faces, smooth)]
    tri_count(kind, w, d, **params) -> int

LOCAL FRAME (lib_furnish.py): +X is the way the piece faces, +Y its left,
z up, metres, origin on the floor at the centre of the footprint.
    w = size ACROSS the facing direction = along local Y
    d = size ALONG the facing direction  = along local X
This is exactly how build_furnish.py reads a drawn box: lib_furnish gives
params w = box.size[0] (across heading), d = box.size[1] (along heading),
and b_sofa / b_tv lay d along x and w along y. A wall piece (wall=True) has
its BACK on local x = -d/2: the integrator puts the origin d/2 in front of
the wall, the piece's +X pointing into the room.

Faces are tris/quads wound counter-clockwise seen from outside (the page
culls back faces). `smooth` is per part: curved parts are smooth, caps,
panels and chamfered boxes flat. A part is ONE (material, smooth) group;
the parts of a piece never share vertices. Welding them (build_furnish's
remove_doubles) is safe: Blender keeps every edge of a flat face sharp, so
a smooth side meeting a flat cap stays creased. Hidden faces (cushion
bottoms, a door's back against its carcass, leg ends) are left out on
purpose; every solid is otherwise closed and right way out
(signed-volume checked), and no two same-facing faces share a plane.

Materials: only names web/materials.js defines. None of these pieces needs
UVs: every material used is flat or procedural in world space.
int_leather_red / dining_chair_02 (UV-mapped) and foliage (vertex colour)
are NOT used. int_curtain, int_lamp_shade and int_glass are DoubleSide in
the page, so the curtain cloth is a single sheet and a drum shade is a thin
closed tube. MAIN_MAT[kind] = the material to name the node after.

TRIANGLES (python3 blender/furn_kit_living.py prints this table)

    kind            default        min    def    max   (min / max = SIZE_RANGE)
    sofa            1.80 x 1.00   1598   1598   1874   (2 / 3 seat cushions)
    armchair        0.82 x 0.84   1034   1034   1034
    table_coffee    1.20 x 0.60    822    822    822   (with books, bowl, vase)
    tv              0.80 x 0.20   1218   1218   1442   (console, screen, soundbar, decor)
    table_round     0.80 x 0.80    804    804    868
    chair           0.40 x 0.47    544    544    544
    rug             2.00 x 1.40    120    120    120
    floor_lamp      0.40 x 0.40    612    612    612
    bookshelf       1.00 x 0.35   1452   1992   4050   (~2000 per metre of shelving)
    sideboard       1.60 x 0.42   1254   1478   1590   (with lamp, vases, book, bowl)
    wall_art        0.60 x 0.03     44     44     66
    curtains        1.40 x 0.16    652    764    988
    pendant         0.40 x 0.40    860    860    860
"""
import math
import random

TAU = 2.0 * math.pi


# ====================================================================== mesh core
def _v_add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(a):
    L = math.sqrt(_dot(a, a)) or 1e-12
    return (a[0] / L, a[1] / L, a[2] / L)


class Kit:
    """Parts of one piece, merged per (material, smooth)."""

    def __init__(self):
        self.parts = {}

    def add(self, mat, mesh, smooth=False):
        V, F = mesh
        P = self.parts.setdefault((mat, bool(smooth)), ([], []))
        o = len(P[0])
        P[0].extend(V)
        P[1].extend(tuple(o + i for i in f) for f in F)

    def out(self):
        return [(m, [tuple(round(c, 5) for c in v) for v in V], [tuple(f) for f in F], s)
                for (m, s), (V, F) in self.parts.items() if F]


def tf(mesh, fn):
    V, F = mesh
    return ([fn(v) for v in V], F)


def mv(mesh, dx=0.0, dy=0.0, dz=0.0):
    return tf(mesh, lambda v: (v[0] + dx, v[1] + dy, v[2] + dz))


def rot(mesh, axis, ang, about=(0.0, 0.0, 0.0)):
    """Right-handed turn about a principal axis through `about`."""
    c, s = math.cos(ang), math.sin(ang)
    ax, ay, az = about

    def f(v):
        x, y, z = v[0] - ax, v[1] - ay, v[2] - az
        if axis == 'x':
            y, z = y * c - z * s, y * s + z * c
        elif axis == 'y':
            z, x = z * c - x * s, z * s + x * c
        else:
            x, y = x * c - y * s, x * s + y * c
        return (x + ax, y + ay, z + az)
    return tf(mesh, f)


def mirror_y(mesh):
    V, F = mesh
    return ([(v[0], -v[1], v[2]) for v in V], [tuple(reversed(f)) for f in F])


def merge(*meshes):
    V, F = [], []
    for mV, mF in meshes:
        o = len(V)
        V.extend(mV)
        F.extend(tuple(o + i for i in f) for f in mF)
    return (V, F)


def signed_volume(mesh):
    V, F = mesh
    vol = 0.0
    for f in F:
        a = V[f[0]]
        for k in range(1, len(f) - 1):
            vol += _dot(a, _cross(V[f[k]], V[f[k + 1]]))
    return vol / 6.0


def flip(mesh):
    return (mesh[0], [tuple(reversed(f)) for f in mesh[1]])


def outward(mesh, *others):
    """Flip `mesh` (and `others`, the rest of the same closed solid) if the
    solid they make together is inside out."""
    whole = merge(mesh, *others)
    if signed_volume(whole) < 0:
        return [flip(mesh)] + [flip(o) for o in others]
    return [mesh] + list(others)


def ntris(F):
    return sum(len(f) - 2 for f in F)


# ====================================================================== primitives
def box(p0, p1, skip=()):
    """Axis-aligned box, outward winding. skip: any of -x +x -y +y -z +z."""
    x0, y0, z0 = p0
    x1, y1, z1 = p1
    x0, x1 = min(x0, x1), max(x0, x1)
    y0, y1 = min(y0, y1), max(y0, y1)
    z0, z1 = min(z0, z1), max(z0, z1)
    V = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = {'-z': (0, 3, 2, 1), '+z': (4, 5, 6, 7), '-y': (0, 1, 5, 4),
             '+y': (2, 3, 7, 6), '-x': (3, 0, 4, 7), '+x': (1, 2, 6, 5)}
    return (V, [f for k, f in faces.items() if k not in skip])


def _axis_vals(h, r, m, k):
    if r <= 1e-6 or m <= 0:
        return [-h + 2.0 * h * i / k for i in range(k + 1)], h, 0.0
    r = min(r, h)
    a = h - r
    zone = [a + r * math.tan(math.pi / 4.0 * j / m) for j in range(1, m + 1)]
    inner = [-a + 2.0 * a * i / k for i in range(k + 1)] if a > 1e-6 else [0.0]
    vals = [-z for z in reversed(zone)] + inner + zone
    out = []
    for v in vals:
        if not out or v - out[-1] > 1e-7:
            out.append(v)
    return out, a, r


def _trip(v):
    return v if isinstance(v, (tuple, list)) else (v, v, v)


def rbox(c, size, r, m=1, k=1, bulge=(0.0, 0.0, 0.0), skip=()):
    """Box with every edge and corner rounded (radius r, m segments per 45
    degrees, k divisions of each flat span): cushions, plinths, arms.
    `bulge` puffs each pair of faces outward by that much at their middle
    (a cushion's crown). skip: faces '-z' etc. left open (hidden ones)."""
    h = (size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)
    r, m, k = _trip(r), _trip(m), _trip(k)
    ax = [_axis_vals(h[i], r[i], m[i], k[i]) for i in range(3)]
    vals = [a[0] for a in ax]
    A = [a[1] for a in ax]
    R = [a[2] for a in ax]
    n = [len(v) for v in vals]
    idx = {}
    V = []

    def vert(i, j, l):
        key = (i, j, l)
        if key in idx:
            return idx[key]
        p = (vals[0][i], vals[1][j], vals[2][l])
        inner = [max(-A[t], min(A[t], p[t])) for t in range(3)]
        dn = [((p[t] - inner[t]) / R[t]) if R[t] > 0 else 0.0 for t in range(3)]
        L = math.sqrt(sum(x * x for x in dn))
        if L > 1e-12:
            q = [inner[t] + dn[t] / L * R[t] for t in range(3)]
        else:
            q = list(p)
        t01 = [max(-1.0, min(1.0, q[t] / h[t])) if h[t] > 0 else 0 for t in range(3)]
        for t in range(3):
            b = bulge[t]
            if b:
                o1, o2 = (t + 1) % 3, (t + 2) % 3
                f = (1.0 - t01[o1] ** 2) * (1.0 - t01[o2] ** 2)
                q[t] += q[t] / h[t] * b * f
        idx[key] = len(V)
        V.append((q[0] + c[0], q[1] + c[1], q[2] + c[2]))
        return idx[key]

    F = []
    nx, ny, nz = n
    if '-x' not in skip or '+x' not in skip:
        for j in range(ny - 1):
            for l in range(nz - 1):
                if '-x' not in skip:
                    F.append((vert(0, j, l), vert(0, j, l + 1), vert(0, j + 1, l + 1), vert(0, j + 1, l)))
                if '+x' not in skip:
                    i = nx - 1
                    F.append((vert(i, j + 1, l), vert(i, j + 1, l + 1), vert(i, j, l + 1), vert(i, j, l)))
    for i in range(nx - 1):
        for l in range(nz - 1):
            if '-y' not in skip:
                F.append((vert(i, 0, l), vert(i + 1, 0, l), vert(i + 1, 0, l + 1), vert(i, 0, l + 1)))
            if '+y' not in skip:
                j = ny - 1
                F.append((vert(i, j, l + 1), vert(i + 1, j, l + 1), vert(i + 1, j, l), vert(i, j, l)))
    for i in range(nx - 1):
        for j in range(ny - 1):
            if '-z' not in skip:
                F.append((vert(i, j, 0), vert(i, j + 1, 0), vert(i + 1, j + 1, 0), vert(i + 1, j, 0)))
            if '+z' not in skip:
                l = nz - 1
                F.append((vert(i + 1, j, l), vert(i + 1, j + 1, l), vert(i, j + 1, l), vert(i, j, l)))
    return (V, F)


def lathe(profile, seg, cx=0.0, cy=0.0, phase=0.0, split=()):
    """Surface of revolution about the vertical through (cx, cy). profile:
    [(r, z)] from the bottom on the axis (r = 0), out, up and back in, so the
    solid is closed and right way out. Returns [(mesh, smooth)]: the profile
    is cut into runs at `split` indices (creases); a run that is all
    horizontal (a cap, a shoulder) is flat, the rest smooth."""
    cuts = sorted(set([0, len(profile) - 1] + list(split)))
    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        run = profile[a:b + 1]
        V, F = [], []
        rings = []
        for r, z in run:
            if r < 1e-7:
                rings.append([len(V)])
                V.append((cx, cy, z))
            else:
                ring = []
                for j in range(seg):
                    t = phase + TAU * j / seg
                    ring.append(len(V))
                    V.append((cx + r * math.cos(t), cy + r * math.sin(t), z))
                rings.append(ring)
        for i in range(len(rings) - 1):
            A, B = rings[i], rings[i + 1]
            for j in range(seg):
                jn = (j + 1) % seg
                if len(A) == 1 and len(B) == 1:
                    continue
                if len(A) == 1:
                    F.append((A[0], B[jn], B[j]))
                elif len(B) == 1:
                    F.append((A[j], A[jn], B[0]))
                else:
                    F.append((A[j], A[jn], B[jn], B[j]))
        flat = all(abs(run[i][1] - run[i + 1][1]) < 1e-7 for i in range(len(run) - 1))
        out.append(((V, F), not flat))
    return out


def loft(rings, cap0=True, cap1=True):
    """Rings of equal point count -> (side, caps), wound outward if the result
    is closed (signed volume), else as the rings run CCW seen from +end."""
    n = len(rings[0])
    V, F = [], []
    for ring in rings:
        V.extend(ring)
    for i in range(len(rings) - 1):
        for j in range(n):
            jn = (j + 1) % n
            F.append((i * n + j, i * n + jn, (i + 1) * n + jn, (i + 1) * n + j))
    CV, CF = [], []
    for which, ring in ((0, rings[0]), (1, rings[-1])):
        if (which == 0 and not cap0) or (which == 1 and not cap1):
            continue
        o = len(CV)
        cen = tuple(sum(p[t] for p in ring) / n for t in range(3))
        CV.extend(ring)
        CV.append(cen)
        for j in range(n):
            jn = (j + 1) % n
            if which == 0:
                CF.append((o + jn, o + j, o + n))
            else:
                CF.append((o + j, o + jn, o + n))
    side, caps = (V, F), (CV, CF)
    if cap0 and cap1:
        side, caps = outward(side, caps)
    return side, caps


def circle2(r, n, phase=0.0):
    return [(r * math.cos(phase + TAU * j / n), r * math.sin(phase + TAU * j / n)) for j in range(n)]


def rrect2(sx, sy, r, seg=3, cx=0.0, cy=0.0):
    """Rounded rectangle, CCW, sizes along x and y."""
    r = max(0.0005, min(r, sx / 2 - 1e-4, sy / 2 - 1e-4))
    pts = []
    for qx, qy, a0 in ((sx / 2 - r, sy / 2 - r, 0.0), (-sx / 2 + r, sy / 2 - r, 90.0),
                       (-sx / 2 + r, -sy / 2 + r, 180.0), (sx / 2 - r, -sy / 2 + r, 270.0)):
        for kk in range(seg + 1):
            a = math.radians(a0 + 90.0 * kk / seg)
            pts.append((cx + qx + r * math.cos(a), cy + qy + r * math.sin(a)))
    return pts


def slab(outline, z0, z1, e, es=2):
    """A top / shelf / plate: plan outline(inset) -> 2D ring (CCW), extruded
    z0..z1 with its edge rounded by radius e (es segments a quarter). Returns
    (side smooth mesh, flat caps)."""
    e = min(e, (z1 - z0) / 2.0)
    prof = []
    if e > 1e-5 and es > 0:
        for kk in range(es + 1):                       # bottom quarter
            a = math.pi / 2 * kk / es
            prof.append((e * (1 - math.sin(a)), z0 + e * (1 - math.cos(a))))
        for kk in range(es + 1):                       # top quarter
            a = math.pi / 2 * kk / es
            prof.append((e * (1 - math.cos(a)), z1 - e + e * math.sin(a)))
    else:
        prof = [(0.0, z0), (0.0, z1)]
    rings = [[(x, y, z) for x, y in outline(ins)] for ins, z in prof]
    return loft(rings)


def sweep(path, prof2, cap0=True, cap1=True, up=(0.0, 0.0, 1.0)):
    """A profile (2D, CCW) carried along a 3D path with parallel-transported
    frames. -> (side, caps)."""
    n = len(path)
    T = []
    for i in range(n):
        a = path[max(0, i - 1)]
        b = path[min(n - 1, i + 1)]
        T.append(_norm(_v_sub(b, a)))
    N0 = _cross(up, T[0])
    if _dot(N0, N0) < 1e-8:
        N0 = _cross((1.0, 0.0, 0.0), T[0])
    N = [_norm(N0)]
    for i in range(1, n):
        p = N[-1]
        p = _v_sub(p, _v_mul(T[i], _dot(p, T[i])))
        N.append(_norm(p))
    rings = []
    for i in range(n):
        B = _cross(T[i], N[i])
        rings.append([_v_add(path[i], _v_add(_v_mul(N[i], u), _v_mul(B, v))) for u, v in prof2])
    return loft(rings, cap0, cap1)


def taper_leg(x, y, z0, z1, r0, r1, seg=8, lean=(0.0, 0.0), caps=True):
    """A round tapered leg, foot at (x, y, z0) radius r0, top radius r1,
    its top displaced by `lean` (dx, dy)."""
    rings = []
    for t, r in ((0.0, r0), (1.0, r1)):
        cx, cy = x + lean[0] * t, y + lean[1] * t
        z = z0 + (z1 - z0) * t
        rings.append([(cx + px, cy + py, z) for px, py in circle2(r, seg, math.pi / seg)])
    return loft(rings, caps, caps)


# ====================================================================== little things
COVERS = ['int_fabric_teal', 'int_fabric_orange', 'int_fabric_bluegrey', 'int_fabric_dark',
          'int_accent_red', 'int_mint', 'int_fabric_white', 'int_black', 'int_fabric_sofa']


def book(kit, x0, y0, z0, thick, height, depth, cover, lean=0.0):
    """One book standing on a shelf, spine to +X: a cover box and the page
    block's top as a quad 1.5 mm above it, inset by the boards and the spine
    (the fore-edge is at the back, against the wall). x0 = the spine face,
    y0 = its -Y side, z0 = the shelf top. lean (rad) tips it about its foot
    toward -Y (lean > 0) or +Y."""
    c = 0.0025
    cov = box((x0 - depth, y0, z0), (x0, y0 + thick, z0 + height), skip=('-z',))
    zt = z0 + height + 0.0015
    pg = ([(x0 - depth + 0.002, y0 + c, zt), (x0 - 0.006, y0 + c, zt), (x0 - 0.006, y0 + thick - c, zt),
           (x0 - depth + 0.002, y0 + thick - c, zt)], [(0, 1, 2, 3)])
    if lean:
        piv = (x0, y0 + (0.0 if lean > 0 else thick), z0)
        cov = rot(cov, 'x', lean, piv)
        pg = rot(pg, 'x', lean, piv)
    kit.add(cover, cov, False)
    kit.add('int_fabric_white', pg, False)


def lying_book(kit, cx, cy, z0, L, W, th, cover, yaw=0.0):
    """A book lying flat: two boards and a spine in the cover colour, the
    page block between them set 4 mm in on the three open sides. L along x,
    W along y (spine on -y), th thick; yaw about its centre."""
    b = 0.0025
    parts = [(cover, box((-L / 2, -W / 2, 0), (L / 2, W / 2, b))),
             (cover, box((-L / 2, -W / 2, th - b), (L / 2, W / 2, th))),
             (cover, box((-L / 2, -W / 2, b), (L / 2, -W / 2 + b, th - b), skip=('-z', '+z'))),
             ('int_fabric_white', box((-L / 2 + 0.004, -W / 2 + b, b), (L / 2 - 0.004, W / 2 - 0.004, th - b),
                                     skip=('-z', '+z', '-y')))]
    for m, mesh in parts:
        kit.add(m, mv(rot(mesh, 'z', yaw), cx, cy, z0), False)


def vase(kit, x, y, z0, h, r, mat='int_ceramic', seg=14, shape=0):
    if shape == 0:      # bottle vase
        prof = [(0, 0), (r * 0.85, 0), (r, h * 0.22), (r * 0.86, h * 0.55), (r * 0.40, h * 0.82),
                (r * 0.36, h), (r * 0.26, h), (0, h * 0.9)]
        split = (1, 6)
    else:               # squat bowl-vase
        prof = [(0, 0), (r * 0.7, 0), (r * 0.97, h * 0.3), (r * 0.9, h * 0.75), (r * 0.62, h),
                (r * 0.5, h), (0, h * 0.8)]
        split = (1, 5)
    for mesh, sm in lathe([(a, b + z0) for a, b in prof], seg, x, y, split=split):
        kit.add(mat, mesh, sm)


def bowl(kit, x, y, z0, r, h, mat='int_ceramic', seg=16):
    prof = [(0, 0), (r * 0.45, 0), (r * 0.78, h * 0.4), (r, h), (r * 0.92, h),
            (r * 0.62, h * 0.4), (0, h * 0.2)]
    for mesh, sm in lathe([(a, b + z0) for a, b in prof], seg, x, y, split=(1, 3, 4)):
        kit.add(mat, mesh, sm)


def candle_box(kit, x, y, z0, s, mat):
    kit.add(mat, box((x - s / 2, y - s / 2, z0), (x + s / 2, y + s / 2, z0 + s * 0.7), skip=('-z',)), False)


# ====================================================================== upholstery
FABRICS = ['int_fabric_sofa', 'int_fabric_bluegrey', 'int_fabric_teal', 'int_fabric_dark',
           'int_fabric_white', 'int_fabric_orange']
ACCENTS = ['int_fabric_orange', 'int_fabric_teal', 'int_fabric_white', 'int_fabric_bluegrey',
           'int_fabric_dark']


def pillow(c, sx, sz, th, lean, twist, yaw, n=5):
    """A scatter cushion standing up, facing +X: two squares of cloth sewn
    at a seam (the sides bow in, the corners stay pointed), stuffed to `th`
    at the middle; leant back by `lean` (rad), twisted about its face
    normal, turned by yaw."""
    def warp(t):
        return math.sin(math.pi / 2 * t)            # rows closer together toward the seam
    V, F = [], []
    front = {}
    for i in range(n + 1):
        for j in range(n + 1):
            u, v = warp(-1 + 2.0 * i / n), warp(-1 + 2.0 * j / n)
            y = u * sx / 2 * (1 - 0.07 * (1 - v * v))
            z = v * sz / 2 * (1 - 0.07 * (1 - u * u))
            x = th / 2 * max(0.0, 1 - u * u) ** 0.42 * max(0.0, 1 - v * v) ** 0.42
            front[i, j] = len(V)
            V.append((x, y, z))
    back = {}
    for (i, j), k in front.items():
        if i in (0, n) or j in (0, n):
            back[i, j] = k                             # the seam is shared
        else:
            x, y, z = V[k]
            back[i, j] = len(V)
            V.append((-x * 0.92, y, z))
    for i in range(n):
        for j in range(n):
            F.append((front[i, j], front[i + 1, j], front[i + 1, j + 1], front[i, j + 1]))
            F.append((back[i, j + 1], back[i + 1, j + 1], back[i + 1, j], back[i, j]))
    m = (V, F)
    m = rot(m, 'x', twist)
    m = rot(m, 'y', -lean)
    m = rot(m, 'z', yaw)
    return mv(m, *c)


def upholstered(kit, w, d, seed, seat_h=0.45, arm_w=0.16, arm_h=0.62, back_h=0.76, n_cush=0,
                scatter=2, throw=1, fabric=0, leg_h=0.13, back_cush_h=0.44, armchair=False):
    """Sofa and armchair: plinth on tapered walnut legs, arms, a back frame,
    seat cushions, leaning back cushions, scatter cushions, a throw."""
    rnd = random.Random(seed * 7919 + 17)
    F = FABRICS[int(fabric) % len(FABRICS)]
    x0, x1 = -d / 2.0, d / 2.0
    hw = w / 2.0
    aw = min(arm_w, w * 0.2)
    # ---- legs: tapered walnut, splayed a little out of the corners
    LEG = 'int_wood_walnut'
    legs = []
    for sx in (-1, 1):
        for sy in (-1, 1):
            legs.append((sx * (d / 2 - 0.075), sy * (hw - 0.075), sx * 0.018, sy * 0.018))
    if w > 2.05:
        legs += [(-(d / 2 - 0.075), 0.0, -0.018, 0.0), ((d / 2 - 0.075), 0.0, 0.018, 0.0)]
    for lx, ly, ox, oy in legs:
        # foot at the floor pushed out, top under the plinth
        side, caps = taper_leg(lx + ox, ly + oy, 0.0, leg_h + 0.01, 0.013, 0.021, seg=8, lean=(-ox, -oy), caps=False)
        kit.add(LEG, side, True)
    # ---- plinth (the frame the cushions sit on), soft edges
    pz0, pz1 = leg_h, seat_h - 0.15
    # set 3 cm back from the arms' fronts, so the seat cushions overhang it
    # (and 8 mm in from the back, so no face lies in the plane of another)
    kit.add(F, rbox((-0.011, 0, (pz0 + pz1) / 2), (d - 0.038, w - 0.02, pz1 - pz0), (0.03, 0.03, 0.03), (1, 1, 1),
                    (1, 2, 1), bulge=(0.004, 0, 0), skip=('-z',)), True)
    # ---- back frame: full width, behind the back cushions
    bt = 0.15 if not armchair else 0.13
    kit.add(F, rbox((x0 + 0.004 + bt / 2, 0, (pz0 + back_h) / 2), (bt, w - 0.012, back_h - pz0), (0.05, 0.05, 0.05), (1, 1, 2),
                    (1, 1, 1), skip=('-z',)), True)
    # ---- arms, full depth, rounded top, a little crown on the outside
    for s in (-1, 1):
        cy = s * (hw - aw / 2)
        arm = rbox((0.0, cy, (pz0 + arm_h) / 2), (d, aw, arm_h - pz0), (0.05, 0.06, 0.06), (1, 2, 2), (1, 1, 1),
                   skip=('-z',))
        kit.add(F, arm, True)
    # ---- seat cushions
    iw = w - 2 * aw
    if not n_cush:
        n_cush = 1 if iw < 0.95 else (2 if iw < 1.75 else 3)
    n_cush = int(n_cush)
    sx0, sx1 = x0 + bt, x1 + 0.01
    sz0, sz1 = seat_h - 0.15, seat_h - 0.012
    cw = iw / n_cush
    for i in range(n_cush):
        cy = -iw / 2 + cw * (i + 0.5)
        kit.add(F, rbox(((sx0 + sx1) / 2, cy, (sz0 + sz1) / 2), (sx1 - sx0, cw - 0.006, sz1 - sz0),
                        (0.05, 0.05, 0.045), (1, 1, 1), (1, 2, 1), bulge=(0.004, 0.008, 0.012), skip=('-z',)), True)
    # ---- back cushions, leaning back ~13 degrees on the back frame
    bct = min(0.19, max(0.15, (d - bt) * 0.24))
    lean = math.radians(13.0)
    zb = seat_h - 0.03
    for i in range(n_cush):
        cy = -iw / 2 + cw * (i + 0.5)
        m = rbox((bct / 2, 0, back_cush_h / 2), (bct, cw - 0.008, back_cush_h), (0.06, 0.05, 0.07), (1, 1, 1), (1, 2, 2),
                 bulge=(0.022, 0.0, 0.006), skip=('-z',))
        m = rot(m, 'y', -lean)
        kit.add(F, mv(m, x0 + bt - 0.03, cy, zb), True)
    back_front = x0 + bt - 0.03 + bct * math.cos(lean)
    # ---- scatter cushions against the back cushions at the arms
    acc = list(ACCENTS)
    rnd.shuffle(acc)
    if F in acc:
        acc.remove(F)
    spots = []
    if scatter >= 1:
        spots.append(-1)
    if scatter >= 2:
        spots.append(1)
    if scatter >= 3:
        spots.append(0)
    for k, s in enumerate(spots):
        ps = 0.45 if not armchair else 0.36
        if s == 0:
            ps = 0.40
        yy = s * (iw / 2 - ps / 2 - 0.05) if s else rnd.uniform(-0.1, 0.1) + 0.1
        if s and armchair:
            yy = 0.0
        tw = math.radians(rnd.uniform(-6, 6))
        yaw = -s * math.radians(rnd.uniform(8, 16))
        c = (back_front + 0.075, yy, seat_h + ps / 2 - 0.03)
        kit.add(acc[k % len(acc)] if s else acc[2 % len(acc)], pillow(c, ps, ps, 0.15, math.radians(20), tw, yaw), True)
    # ---- a throw over one arm
    if throw:
        s = 1 if rnd.random() < 0.5 else -1
        tm = 'int_fabric_white' if F != 'int_fabric_white' else 'int_fabric_bluegrey'
        tm = [tm, 'int_fabric_bluegrey', 'int_fabric_teal'][rnd.randrange(3)] if F == 'int_fabric_sofa' else tm
        if tm == F:
            tm = 'int_fabric_white'
        yi, yo = s * (hw - aw), s * hw
        th = 0.012
        rr = 0.06                       # arm top rounding
        # path in (y, z), offset 7 mm off the upholstery, from the seat over the arm
        pts = []
        # tucked down between the seat cushion and the arm
        pts.append((yi - s * 0.012, sz1 - 0.06))
        pts.append((yi - s * 0.010, sz1 + 0.06))
        pts.append((yi - s * 0.009, arm_h - rr))
        for kk in range(1, 3):
            a = math.pi / 2 * kk / 3
            pts.append((yi + s * (rr - (rr + 0.009) * math.cos(a)), arm_h - rr + (rr + 0.009) * math.sin(a)))
        pts.append((yi + s * (aw / 2), arm_h + 0.009))
        for kk in range(1, 3):
            a = math.pi / 2 * kk / 3
            pts.append((yo - s * (rr - (rr + 0.009) * math.sin(a)), arm_h - rr + (rr + 0.009) * math.cos(a)))
        pts.append((yo + s * 0.011, arm_h - rr - 0.05))
        pts.append((yo + s * 0.018, 0.34))
        pts.append((yo + s * 0.030, 0.24))
        tw0 = 0.52
        xc = x1 - 0.38
        # a cloth sheet: across x (6 points) x along the path; a top and an
        # under surface joined at the edges -> a closed thin slab
        nX = 5
        rings = []
        L = len(pts)
        for i, (py, pz) in enumerate(pts):
            # local normal of the path in (y, z)
            a = pts[max(0, i - 1)]
            b = pts[min(L - 1, i + 1)]
            ty, tz = b[0] - a[0], b[1] - a[1]
            tl = math.hypot(ty, tz) or 1
            ny, nz = -tz / tl, ty / tl
            if (ny * s + nz) < 0 and s > 0:
                ny, nz = -ny, -nz
            # outward = away from the arm: for s=+1 the path runs +y, normal (-tz, ty) points up/out
            fall = max(0.0, min(1.0, (arm_h - pz) / 0.35)) if i > L // 2 else 0.0
            wid = tw0 * (1.0 + 0.10 * fall)
            ring_top, ring_bot = [], []
            for j in range(nX):
                u = -wid / 2 + wid * j / (nX - 1)
                wave = 0.022 * fall * math.sin(u / wid * TAU * 1.5 + 0.7)
                sh = 0.10 * (i / (L - 1) - 0.5)          # it crosses the arm on a slant
                ring_top.append((xc + u + sh, py + ny * (th / 2 + wave) * s, pz + nz * (th / 2) * s))
                ring_bot.append((xc + u + sh, py - ny * (th / 2 - wave) * s, pz - nz * (th / 2) * s))
            rings.append(ring_top + ring_bot[::-1])
        side, caps = loft(rings)
        kit.add(tm, side, True)
        kit.add(tm, caps, False)


# ====================================================================== kinds
def b_sofa(kit, w, d, seed, P):
    upholstered(kit, w, d, seed, seat_h=P['seat_h'], arm_w=P['arm_w'], n_cush=int(P['cushions']),
                scatter=int(P['scatter']), throw=int(P['throw']), fabric=int(P['fabric']))


def b_armchair(kit, w, d, seed, P):
    upholstered(kit, w, d, seed, seat_h=P['seat_h'], arm_w=P['arm_w'], arm_h=0.60, back_h=0.74, n_cush=1,
                scatter=int(P['scatter']), throw=0, fabric=int(P['fabric']), back_cush_h=0.42, armchair=True)


def b_table_coffee(kit, w, d, seed, P):
    rnd = random.Random(seed * 31 + 5)
    H = P['h']
    x0, x1, y0, y1 = -d / 2, d / 2, -w / 2, w / 2
    rc = min(0.09, d * 0.18)
    top = lambda ins: rrect2(d - 2 * ins, w - 2 * ins, rc - ins, 4)
    side, caps = slab(top, H - 0.032, H, 0.010, 1)
    kit.add('int_coffee_top', side, True)
    kit.add('int_coffee_top', caps, False)
    # apron-less: four walnut legs, round, tapered, splayed outward, and a
    # walnut magazine shelf low down
    WOOD = 'int_wood_walnut'
    ix, iy = d / 2 - 0.07, w / 2 - 0.08
    for sx in (-1, 1):
        for sy in (-1, 1):
            side, caps = taper_leg(sx * (ix + 0.012), sy * (iy + 0.012), 0.0, H - 0.031, 0.013, 0.019, 8,
                                   lean=(-sx * 0.012, -sy * 0.012))
            kit.add(WOOD, side, True)
            kit.add(WOOD, caps, False)
    sh = lambda ins: rrect2(d - 0.12 - 2 * ins, w - 0.14 - 2 * ins, 0.03 - ins, 2)
    side, caps = slab(sh, 0.115, 0.135, 0.005, 1)
    kit.add(WOOD, side, True)
    kit.add(WOOD, caps, False)
    if P['decor']:
        # a stack of two books, a ceramic bowl, a small vase; on the shelf two more books
        bx = -d * 0.08
        by = w * 0.22 * (1 if rnd.random() < 0.5 else -1)
        c1, c2, c3 = rnd.sample(COVERS[:7], 3)
        lying_book(kit, bx, by, H, 0.22, 0.30, 0.028, c1, math.radians(rnd.uniform(-12, -4)))
        lying_book(kit, bx, by, H + 0.028, 0.18, 0.24, 0.022, c2, math.radians(rnd.uniform(6, 16)))
        vase(kit, bx + 0.02, by + 0.02 * (1 if by < 0 else -1), H + 0.050, 0.16, 0.040, 'int_ceramic', 12, 0)
        bowl(kit, d * 0.10, -by * 0.85, H, 0.13, 0.065, 'int_stone_dark', 18)
        lying_book(kit, 0.0, -by * 0.6, 0.135, 0.24, 0.32, 0.03, c3, math.radians(rnd.uniform(-8, 8)))


def cabinet(kit, w, d, H, leg_h, seed, doors=None, body='int_wood_walnut', front='int_wood_oak',
            handle='int_brass', back_x=None):
    """A low cabinet on legs: a body with a bevelled top, slab doors with
    shadow gaps, brass edge pulls, tapered legs. Back at x = back_x."""
    bx0 = -d / 2 if back_x is None else back_x
    bx1 = bx0 + d
    cx = (bx0 + bx1) / 2
    # body: a carcass with soft 2-step bevels, flat shaded so the planes read
    zb0, zb1 = leg_h, H
    kit.add(body, rbox((cx - 0.004, 0, (zb0 + zb1) / 2), (d - 0.008, w, zb1 - zb0), 0.006, 1, 1), False)
    # doors
    n = doors or max(2, int(round(w / 0.45)))
    gap = 0.004
    dw = (w - 0.03) / n
    fz0, fz1 = zb0 + 0.025, zb1 - 0.025
    for i in range(n):
        yA = -w / 2 + 0.015 + dw * i + gap / 2
        yB = yA + dw - gap
        kit.add(front, rbox((bx1 + 0.007, (yA + yB) / 2, (fz0 + fz1) / 2), (0.018, yB - yA, fz1 - fz0), 0.003, 1, 1,
                            skip=('-x',)), False)
        # a brass edge pull on the top edge, near the meeting edge of a pair
        hy = yB - 0.05 if i % 2 == 0 else yA + 0.05
        kit.add(handle, box((bx1 + 0.012, hy - 0.035, fz1 - 0.016), (bx1 + 0.030, hy + 0.035, fz1 - 0.008),
                            skip=('-x',)), False)
        kit.add(handle, box((bx1 + 0.016, hy - 0.035, fz1 - 0.008), (bx1 + 0.030, hy + 0.035, fz1 + 0.004)), False)
    # legs: square-tapered black steel? no: turned walnut, slightly splayed
    for sx in (-1, 1):
        for sy in (-1, 1):
            lx = cx + sx * (d / 2 - 0.05)
            ly = sy * (w / 2 - 0.06)
            side, caps = taper_leg(lx + sx * 0.008, ly + sy * 0.008, 0.0, leg_h + 0.005, 0.011, 0.017, 8,
                                   lean=(-sx * 0.008, -sy * 0.008))
            kit.add('int_wood_walnut' if body != 'int_wood_walnut' else 'int_wood_oak', side, True)
            kit.add('int_wood_walnut' if body != 'int_wood_walnut' else 'int_wood_oak', caps, False)
    return bx0, bx1


def b_tv(kit, w, d, seed, P):
    rnd = random.Random(seed * 101 + 3)
    cw = P['console_w'] or max(1.40, min(2.2, w + 0.70))
    cd = P['console_d']
    ch = P['console_h']
    bx0 = -d / 2
    cabinet(kit, cw, cd, ch, 0.14, seed, doors=None, back_x=bx0)
    # ---- the screen: a slim panel on a centre pedestal, w wide (16:9)
    sw = w
    sh = w * 0.5625
    tx = bx0 + 0.10
    zs0 = ch + 0.075
    # panel body (the bezel shows as a 6 mm black frame round the glass)
    kit.add('metal_dark', rbox((tx, 0, zs0 + sh / 2), (0.022, sw, sh), (0.004, 0.006, 0.006), 1, 1), False)
    # the glass: a black gloss sheet 1 mm proud of the bezel, set in 6 mm
    kit.add('int_black', box((tx + 0.011, -sw / 2 + 0.006, zs0 + 0.012), (tx + 0.012, sw / 2 - 0.006, zs0 + sh - 0.006),
                             skip=('-x', '-y', '+y', '-z', '+z')), False)
    # the electronics hump at the back
    kit.add('metal_dark', box((tx - 0.037, -sw * 0.31, zs0 + sh * 0.17), (tx - 0.011, sw * 0.31, zs0 + sh * 0.67),
                              skip=('+x',)), False)
    # pedestal: a short neck and an oval-ish foot plate
    kit.add('metal_dark', box((tx - 0.015, -0.03, ch), (tx + 0.005, 0.03, zs0 + 0.05)), False)
    side, caps = slab(lambda ins: rrect2(0.18 - 2 * ins, 0.30 - 2 * ins, 0.06 - ins, 4, tx + 0.01, 0), ch, ch + 0.010,
                      0.003, 1)
    kit.add('metal_dark', side, True)
    kit.add('metal_dark', caps, False)
    # ---- a soundbar in front of the foot
    sbw = min(cw - 0.2, max(0.6, sw * 0.85))
    sbx = bx0 + 0.26
    kit.add('int_fabric_dark', rbox((sbx, 0, ch + 0.036), (0.085, sbw, 0.062), (0.03, 0.03, 0.028), (1, 1, 1), (1, 1, 1),
                                    skip=('-z',)), True)
    kit.add('metal_dark', box((sbx - 0.03, -sbw / 2 + 0.03, ch), (sbx + 0.03, sbw / 2 - 0.03, ch + 0.007), skip=('-z',)),
            False)
    # ---- decor: a vase at one end, books with a bowl on them at the other
    if P['decor']:
        s = 1 if rnd.random() < 0.5 else -1
        ey = s * (cw / 2 - 0.16)
        vase(kit, bx0 + cd * 0.5, ey, ch, 0.30, 0.065, 'int_ceramic', 14, 0)
        c1, c2 = rnd.sample(COVERS[:7], 2)
        oy = -s * (cw / 2 - 0.19)
        lying_book(kit, bx0 + cd * 0.52, oy, ch, 0.24, 0.18, 0.03, c1, 0.08)
        lying_book(kit, bx0 + cd * 0.52, oy, ch + 0.03, 0.20, 0.15, 0.022, c2, -0.1)
        candle_box(kit, bx0 + cd * 0.52 + 0.02, oy + 0.01, ch + 0.052, 0.06, 'int_stone_dark')


def b_sideboard(kit, w, d, seed, P):
    rnd = random.Random(seed * 13 + 1)
    H = P['h']
    cabinet(kit, w, d, H, 0.16, seed, doors=None)
    if P['decor']:
        # a lamp on one end, a pair of vases, a book stack
        s = 1 if rnd.random() < 0.5 else -1
        ly = s * (w / 2 - 0.20)
        lamp_table(kit, 0.0, ly, H)
        vase(kit, -0.02, -s * (w / 2 - 0.22), H, 0.34, 0.07, 'int_ceramic', 14, 0)
        vase(kit, 0.06, -s * (w / 2 - 0.34), H, 0.17, 0.075, 'int_stone_dark', 14, 1)
        c1, c2 = rnd.sample(COVERS[:7], 2)
        lying_book(kit, 0.0, s * 0.05, H, 0.26, 0.20, 0.03, c1, 0.05)
        bowl(kit, 0.0, s * 0.05, H + 0.03, 0.10, 0.05, 'int_brass', 14)


def lamp_table(kit, x, y, z0):
    """A table lamp: a ceramic bulb base, a linen drum."""
    prof = [(0, 0), (0.06, 0), (0.075, 0.08), (0.07, 0.17), (0.03, 0.25), (0.018, 0.27), (0, 0.27)]
    for mesh, sm in lathe([(a, b + z0) for a, b in prof], 14, x, y, split=(1, 5)):
        kit.add('int_ceramic', mesh, sm)
    kit.add('int_brass', lathe([(0, z0 + 0.27), (0.006, z0 + 0.27), (0.006, z0 + 0.34), (0, z0 + 0.34)], 6, x, y)[0][0],
            True)
    shade_drum(kit, x, y, z0 + 0.30, 0.13, 0.15, 0.19, 18)


def shade_drum(kit, x, y, z0, r0, r1, h, seg):
    """An open drum shade: outer and inner sheet joined by a lip top and
    bottom (closed, 3 mm wall). int_lamp_shade glows in the page."""
    t = 0.003
    prof = [(r1 - t, z0 + h), (r0 - t, z0), (r0, z0), (r1, z0 + h)]
    # outer: r0->r1 bottom->top; lathe expects axis-out-up-in ordering, so build
    # as a ring tube: [inner top, inner bottom, outer bottom, outer top] closes
    V, F = [], []
    rings = []
    for r, z in prof:
        ring = []
        for j in range(seg):
            a = TAU * j / seg
            ring.append(len(V))
            V.append((x + r * math.cos(a), y + r * math.sin(a), z))
        rings.append(ring)
    for i in range(4):
        A, B = rings[i], rings[(i + 1) % 4]
        for j in range(seg):
            jn = (j + 1) % seg
            F.append((A[j], A[jn], B[jn], B[j]))
    m = (V, F)
    # tube: orientation by signed volume of the closed torus-like ring
    if signed_volume(m) < 0:
        m = flip(m)
    kit.add('int_lamp_shade', m, False)


def b_table_round(kit, w, d, seed, P):
    D = P.get('dia') or max(w, d)
    R = D / 2
    H = 0.75
    seg = 48 if D >= 1.0 else 40
    top = lambda ins: circle2(R - ins, seg)
    side, caps = slab(top, H - 0.024, H, 0.008, 1)
    kit.add('int_marble', side, True)
    kit.add('int_marble', caps, False)
    WOOD = 'int_wood_oak'
    if int(P['legs']) == 0:
        # a turned oak pedestal: a flared foot, a waisted column, a spreader
        rb = min(0.26, R * 0.62)
        prof = [(0, 0), (rb, 0), (rb, 0.012), (rb * 0.80, 0.030), (rb * 0.42, 0.075), (0.075, 0.16),
                (0.058, 0.32), (0.055, 0.50), (0.07, 0.62), (0.13, 0.69), (0.15, 0.70), (0.15, H - 0.024), (0, H - 0.024)]
        for mesh, sm in lathe(prof, 22, split=(1, 2, 11, 12)):
            kit.add(WOOD, mesh, sm)
    else:
        # four turned legs under an apron ring
        ra = R * 0.62
        for k in range(4):
            a = TAU * (k + 0.5) / 4
            lx, ly = ra * math.cos(a), ra * math.sin(a)
            prof = [(0, 0), (0.016, 0), (0.019, 0.05), (0.024, 0.40), (0.026, 0.60), (0.024, H - 0.09),
                    (0.024, H - 0.024), (0, H - 0.024)]
            for mesh, sm in lathe(prof, 10, lx, ly, split=(1, 6)):
                kit.add(WOOD, mesh, sm)
        apr = [(0, H - 0.10), (ra + 0.03, H - 0.10), (ra + 0.03, H - 0.024), (0, H - 0.024)]
        for mesh, sm in lathe(apr, 28, split=(1, 2)):
            kit.add(WOOD, mesh, sm)


def b_chair(kit, w, d, seed, P):
    """A dining chair: four tapered oak legs, the back pair rising into posts
    that carry a curved bentwood back rail, a padded seat on an oak shell.
    Faces +X (towards the table); back at -X."""
    rnd = random.Random(seed)
    SW = max(0.40, min(0.48, w + 0.04))          # seat width across
    SD = max(0.40, min(0.46, d - 0.03))          # seat depth
    SH = P['seat_h']
    WOOD = 'int_wood_oak'
    FAB = FABRICS[int(P['fabric']) % len(FABRICS)]
    fx = SD / 2
    bxp = -SD / 2
    cx = 0.015                                   # the seat sits a little forward of the box centre
    # ---- seat shell: a thin oak tray with rounded corners, front edge rolled
    sz0 = SH - 0.055
    shell = lambda ins: rrect2(SD - 2 * ins, SW - 2 * ins, 0.06 - ins, 3, cx, 0)
    side, caps = slab(shell, sz0, sz0 + 0.022, 0.008, 1)
    kit.add(WOOD, side, True)
    kit.add(WOOD, caps, False)
    # ---- the pad: a soft cushion, slightly dished (front higher, saddle)
    pad = rbox((cx, 0, 0), (SD - 0.025, SW - 0.025, 0.034), (0.03, 0.05, 0.016), (1, 1, 1), (2, 2, 1),
               bulge=(0, 0, 0.010), skip=('-z',))
    pad = tf(pad, lambda v: (v[0], v[1], v[2] + 0.006 * ((v[0] - cx) / (SD / 2)) ** 2
                              - 0.004 * (1 - abs(v[1]) / (SW / 2))))
    kit.add(FAB, mv(pad, 0, 0, sz0 + 0.022 + 0.017), True)
    # ---- legs
    lz1 = sz0 + 0.002
    for sy in (-1, 1):
        ly = sy * (SW / 2 - 0.035)
        # front legs: straight taper, a touch splayed
        side, caps = taper_leg(cx + fx - 0.03 + 0.012, ly + sy * 0.010, 0.0, lz1, 0.012, 0.016, 6,
                               lean=(-0.012, -sy * 0.010))
        kit.add(WOOD, side, True)
        kit.add(WOOD, caps, False)
        # back legs: one continuous post, foot kicked back, rising through
        # the seat to the back rail, raked ~10 degrees
        p_foot = (cx + bxp + 0.005, ly + sy * 0.006, 0.0)
        p_seat = (cx + bxp + 0.035, ly, sz0 + 0.01)
        p_top = (cx + bxp + 0.000, ly * 0.97, 0.80)
        path = [p_foot, p_seat, ((p_seat[0] + p_top[0]) / 2 + 0.004, ly * 0.985, (p_seat[2] + p_top[2]) / 2), p_top]
        rings = []
        for i, p in enumerate(path):
            r = [0.012, 0.016, 0.0145, 0.012][i]
            rings.append([(p[0] + a, p[1] + b, p[2]) for a, b in circle2(r, 6, math.pi / 6)])
        side, caps = loft(rings)
        kit.add(WOOD, side, True)
        kit.add(WOOD, caps, False)
    # ---- the back rail: bent plywood, an arc in plan round the sitter
    Rb = 0.42
    span = SW / 2 + 0.01
    th0 = math.asin(min(0.95, span / Rb))
    arc = []
    nA = 9
    for i in range(nA):
        t = -th0 + 2 * th0 * i / (nA - 1)
        arc.append((cx + bxp - 0.012 + Rb - Rb * math.cos(t) - 0.0, Rb * math.sin(t)))
    zr0, zr1 = 0.64, 0.80
    rail_prof = rrect2(0.016, zr1 - zr0, 0.007, 1)      # (thickness, height) section
    # build rings: for each arc point, the section in (normal, z)
    rings = []
    for i, (ax, ay) in enumerate(arc):
        a = arc[max(0, i - 1)]
        b = arc[min(nA - 1, i + 1)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        tl = math.hypot(tx, ty) or 1
        nx, ny = ty / tl, -tx / tl
        ring = []
        for u, v in rail_prof:
            zz = (zr0 + zr1) / 2 + v
            rake = -(zz - 0.45) * math.tan(math.radians(10))     # the back leans back with the posts
            ring.append((ax + nx * u + rake, ay + ny * u, zz))
        rings.append(ring)
    side, caps = loft(rings)
    kit.add(WOOD, side, True)
    kit.add(WOOD, caps, False)


def b_rug(kit, w, d, seed, P):
    t = P['thick']
    out = lambda ins: rrect2(d - 2 * ins, w - 2 * ins, 0.03 - ins, 2)
    side, caps = slab(out, 0.0015, t, min(0.004, t / 2.5), 1)
    kit.add('int_rug', side, True)
    kit.add('int_rug', caps, False)
    if P['border']:
        # a bound edge in a darker yarn: a band 6 cm in from the edge
        b = 0.05
        inner = rrect2(d - 2 * b, w - 2 * b, 0.02, 2)
        outer = rrect2(d - 2 * b + 0.04, w - 2 * b + 0.04, 0.04, 2)
        zt = t + 0.0004
        V = [(x, y, zt) for x, y in outer] + [(x, y, zt) for x, y in inner]
        n = len(outer)
        F = [(j, (j + 1) % n, n + (j + 1) % n, n + j) for j in range(n)]
        kit.add('int_fabric_dark', (V, F), False)


def b_floor_lamp(kit, w, d, seed, P):
    H = P['h']
    rb = max(0.12, min(0.16, min(w, d) * 0.4))
    # a heavy round marble foot with a soft edge
    side, caps = slab(lambda ins: circle2(rb - ins, 24), 0.0, 0.028, 0.008, 1)
    kit.add('int_stone_dark', side, True)
    kit.add('int_stone_dark', caps, False)
    # the stem: brass, with a collar and a switch knuckle
    prof = [(0, 0.028), (0.016, 0.028), (0.016, 0.045), (0.009, 0.05), (0.009, H - 0.33), (0.013, H - 0.32),
            (0.013, H - 0.30), (0.0, H - 0.30)]
    for mesh, sm in lathe(prof, 10, split=(1, 2, 6)):
        kit.add('int_brass', mesh, sm)
    # the spider and a bulb glow inside the drum
    kit.add('int_brass', lathe([(0, H - 0.30), (0.008, H - 0.30), (0.008, H - 0.10), (0, H - 0.10)], 6)[0][0], True)
    for k in range(3):
        a = TAU * k / 3
        p0 = (0.0, 0.0, H - 0.12)
        p1 = (0.19 * math.cos(a), 0.19 * math.sin(a), H - 0.10)
        side, caps = sweep([p0, p1], circle2(0.003, 4))
        kit.add('int_brass', side, False)
    for mesh, sm in lathe([(0, H - 0.20), (0.028, H - 0.18), (0.032, H - 0.15), (0.02, H - 0.12), (0, H - 0.11)], 10):
        kit.add('int_lamp_shade', mesh, True)
    rs = max(0.17, min(0.24, min(w, d) / 2))
    shade_drum(kit, 0.0, 0.0, H - 0.32, rs, rs * 0.92, 0.32, 24)


def b_pendant(kit, w, d, seed, P):
    """A spun brass dome over the dining table, glowing linen white inside."""
    ceil = P['ceiling']
    zb = P['drop']
    R = max(0.15, min(0.30, min(w, d) / 2))
    Hd = R * 0.70
    # dome outer shell (brass) - a quarter-ellipse profile, a 4 mm rolled lip
    n = 6
    outer = []
    for k in range(n + 1):
        a = math.pi / 2 * k / n
        outer.append((R * math.cos(a) + 0.0, zb + Hd * math.sin(a)))
    # outer runs from the lip up to the top; lathe wants axis-out-up-in: the
    # solid is a shell, so build it as one closed ring profile: inner surface
    # (lip -> top, inset 4 mm), the top on the axis, the outer surface back
    # down, the lip
    t = 0.004
    inner = [((R - t) * math.cos(math.pi / 2 * k / n), zb + 0.002 + (Hd - t) * math.sin(math.pi / 2 * k / n))
             for k in range(n + 1)]
    # outer: brass, as a lathe from the axis top outward/down = reversed
    prof_out = [(0.0, zb + Hd)] + [p for p in reversed(outer)]
    # lathe expects bottom-axis -> out -> up -> top-axis; this one runs top-axis
    # -> out -> down, so its faces come out inward: flip
    V, F = [], []
    for mesh, sm in lathe(prof_out, 24):
        kit.add('int_brass', flip(mesh), True)
    # the inside, seen from under the table: the glowing shade, facing down/in
    prof_in = [(0.0, zb + 0.002 + Hd - t)] + [p for p in reversed(inner)]
    for mesh, sm in lathe(prof_in, 24):
        kit.add('int_lamp_shade', mesh, True)
    # the lip joins the two
    lip = [(R - t, zb + 0.002), (R, zb)]
    Vl, Fl = [], []
    seg = 24
    for r, z in lip:
        for j in range(seg):
            a = TAU * j / seg
            Vl.append((r * math.cos(a), r * math.sin(a), z))
    for j in range(seg):
        jn = (j + 1) % seg
        Fl.append((j, jn, seg + jn, seg + j))
    kit.add('int_brass', (Vl, Fl), False)
    # a globe bulb peeking under the dome
    for mesh, sm in lathe([(0, zb + 0.03), (0.035, zb + 0.045), (0.05, zb + 0.08), (0.035, zb + 0.115),
                           (0.015, zb + 0.125), (0, zb + 0.125)], 12):
        kit.add('int_lamp_shade', mesh, True)
    # the cable and the ceiling canopy
    for mesh, sm in lathe([(0, zb + Hd - 0.01), (0.022, zb + Hd - 0.01), (0.022, zb + Hd + 0.04),
                           (0.004, zb + Hd + 0.045), (0, zb + Hd + 0.045)], 12, split=(1, 3)):
        kit.add('int_brass', mesh, sm)
    kit.add('int_black', lathe([(0, zb + Hd + 0.04), (0.0025, zb + Hd + 0.04), (0.0025, ceil - 0.03), (0, ceil - 0.03)],
                               5)[0][0], True)
    for mesh, sm in lathe([(0, ceil - 0.032), (0.05, ceil - 0.032), (0.06, ceil - 0.02), (0.06, ceil - 0.002),
                           (0, ceil - 0.002)], 16, split=(1, 2, 3)):
        kit.add('int_brass', mesh, sm)


def b_bookshelf(kit, w, d, seed, P):
    """An open oak shelving unit with a white back, books in runs (some
    leaning, a few lying), vases and a bowl here and there."""
    rnd = random.Random(seed * 977 + 11)
    H = P['h']
    t = 0.025
    x0, x1 = -d / 2, d / 2
    FR = 'int_wood_oak'
    plinth = 0.06
    # carcass: two sides, a top, a bottom over a recessed plinth, a back panel
    for s in (-1, 1):
        kit.add(FR, box((x0, s * (w / 2 - t), 0.0), (x1, s * w / 2, H), skip=('-z',)), False)
    kit.add(FR, box((x0, -w / 2 + t, H - t), (x1, w / 2 - t, H), skip=('-y', '+y')), False)
    kit.add(FR, box((x0, -w / 2 + t, plinth), (x1, w / 2 - t, plinth + t), skip=('-y', '+y')), False)
    kit.add('int_black', box((x0 + 0.03, -w / 2 + t, 0.0), (x1 - 0.03, w / 2 - t, plinth), skip=('-z',)), False)
    kit.add('int_white_gloss', box((x0, -w / 2 + t, plinth), (x0 + 0.008, w / 2 - t, H - t), skip=('-x',)), False)
    # shelves, evenly spaced
    n_sh = max(3, int(round((H - plinth - t) / 0.36)))
    pitch = (H - plinth - t) / n_sh
    levels = []
    for i in range(n_sh):
        z = plinth + t + pitch * i
        if i > 0:
            kit.add(FR, box((x0 + 0.008, -w / 2 + t, z - t), (x1 - 0.004, w / 2 - t, z), skip=('-y', '+y', '-x')),
                    False)
        levels.append((z, pitch - t))
    inner_w = w - 2 * t
    depth = d - 0.02
    sx = x1 - 0.015                                        # spines line up 1.5 cm behind the front
    for li, (z, clear) in enumerate(levels):
        y = -inner_w / 2 + 0.008
        y_end = inner_w / 2 - 0.008
        last = None
        while y < y_end - 0.06:
            room = y_end - y
            r = rnd.random()
            if last != 'run' and room > 0.12 and (r < 0.55 or last in ('obj', 'stack')):
                # a run of standing books, a few leaning at its end
                run = rnd.randint(3, 7)
                base_h = rnd.uniform(0.19, 0.27)
                for k in range(run):
                    th = rnd.uniform(0.02, 0.048)
                    if y + th > y_end:
                        break
                    hb = min(clear - 0.025, base_h * rnd.uniform(0.86, 1.06))
                    dp = min(depth - 0.03, rnd.uniform(0.15, 0.22))
                    book(kit, sx - rnd.uniform(0, 0.012), y, z, th, hb, dp, rnd.choice(COVERS))
                    y += th + 0.0008
                if rnd.random() < 0.4 and y_end - y > 0.10:
                    th = rnd.uniform(0.02, 0.03)
                    hb = min(clear - 0.05, base_h * 0.9)
                    lean = math.radians(rnd.uniform(14, 22))
                    y += math.sin(lean) * hb + 0.002
                    book(kit, sx - 0.01, y - th, z, th, hb, 0.17, rnd.choice(COVERS), lean=lean)
                    y += 0.004
                last = 'run'
            elif r < 0.80 and room > 0.20:
                # an object: a vase or a bowl with space round it
                if rnd.random() < 0.6:
                    hh = min(clear - 0.04, rnd.uniform(0.14, 0.26))
                    rv = rnd.uniform(0.04, 0.06)
                    vase(kit, x0 + d * 0.5, y + 0.03 + rv, z, hh, rv, rnd.choice(['int_ceramic', 'int_stone_dark',
                                                                                 'int_mint', 'int_pot']), 10, rnd.randrange(2))
                    y += 2 * rv + 0.09
                else:
                    rb = rnd.uniform(0.06, 0.08)
                    bowl(kit, x0 + d * 0.5, y + 0.03 + rb, z, rb, rb * 0.6, rnd.choice(['int_brass', 'int_ceramic']), 12)
                    y += 2 * rb + 0.08
                last = 'obj'
            elif room > 0.26:
                # a lying stack, sometimes with a small box on it
                zz = z
                L0, W0 = rnd.uniform(0.17, 0.21), rnd.uniform(0.22, 0.27)
                for k in range(rnd.randint(2, 4)):
                    th = rnd.uniform(0.02, 0.035)
                    lying_book(kit, sx - L0 / 2 - 0.01, y + W0 / 2 + 0.01, zz, L0 * rnd.uniform(0.9, 1.0),
                               W0 * rnd.uniform(0.88, 1.0), th, rnd.choice(COVERS), math.radians(rnd.uniform(-5, 5)))
                    zz += th
                if rnd.random() < 0.5 and clear - (zz - z) > 0.10:
                    candle_box(kit, sx - L0 / 2 - 0.01, y + W0 / 2 + 0.01, zz, 0.07,
                               rnd.choice(['int_brass', 'int_stone_dark', 'int_ceramic']))
                y += W0 + 0.05
                last = 'stack'
            else:
                y += rnd.uniform(0.05, 0.12)
                last = 'gap'


def b_wall_art(kit, w, d, seed, P):
    """A framed print on the wall: an oak or black frame, a white mount, an
    abstract composition in the flat's palette. Back on x = -d/2."""
    rnd = random.Random(seed * 53 + int(w * 100))
    W = w
    Hh = P['h'] or (round(W * 1.30, 3) if W <= 0.75 else round(W * 0.72, 3))   # portrait, or landscape when wide
    zc = P['cz']
    fr = 0.022
    dep = max(0.02, min(0.04, d))
    x0 = -d / 2
    style = int(P['style']) if P['style'] >= 0 else rnd.randrange(3)
    FR = ['int_wood_oak', 'int_black', 'int_wood_walnut'][style % 3]
    # frame: four mitred bars, flat-shaded with a small chamfer outside
    o = [(W / 2, Hh / 2), (-W / 2, Hh / 2), (-W / 2, -Hh / 2), (W / 2, -Hh / 2)]
    i_ = [(W / 2 - fr, Hh / 2 - fr), (-W / 2 + fr, Hh / 2 - fr), (-W / 2 + fr, -Hh / 2 + fr), (W / 2 - fr, -Hh / 2 + fr)]
    # frame as a closed ring solid: front face, back face, outer side, inner side
    V, F = [], []
    xf, xb = x0 + dep, x0
    for (yy, zz) in o:
        V.append((xb, yy, zc + zz))
    for (yy, zz) in o:
        V.append((xf - 0.004, yy, zc + zz))
    for (yy, zz) in i_:
        V.append((xf, yy, zc + zz))
    for (yy, zz) in i_:
        V.append((xf - 0.010, yy, zc + zz))
    for j in range(4):
        jn = (j + 1) % 4
        F.append((j, jn, 4 + jn, 4 + j))                # outer side
        F.append((4 + j, 4 + jn, 8 + jn, 8 + j))        # front (bevelled in)
        F.append((8 + j, 8 + jn, 12 + jn, 12 + j))      # inner lip
        F.append((12 + j, 12 + jn, jn, j))              # back to the wall (the rebate)
    m = (V, F)
    if signed_volume(m) < 0:
        m = flip(m)
    kit.add(FR, m, False)
    # the mount (passe-partout), set back 10 mm
    xm = xf - 0.010
    mw, mh = W - 2 * fr, Hh - 2 * fr
    kit.add('int_fabric_white', ([(xm, -mw / 2, zc - mh / 2), (xm, mw / 2, zc - mh / 2), (xm, mw / 2, zc + mh / 2),
                                  (xm, -mw / 2, zc + mh / 2)], [(0, 1, 2, 3)]), False)
    # the picture area
    pw, ph = mw * 0.68, mh * 0.72
    pz = zc + mh * 0.03
    xp = xm + 0.001
    pal = ['int_fabric_orange', 'int_fabric_teal', 'int_mint', 'int_accent_red', 'int_fabric_bluegrey', 'int_brass',
           'int_fabric_dark', 'int_wood_oak']
    rnd.shuffle(pal)

    def rect(mat, y0, y1, z0, z1, xx):
        kit.add(mat, ([(xx, y0, z0), (xx, y1, z0), (xx, y1, z1), (xx, y0, z1)], [(0, 1, 2, 3)]), False)

    def disc(mat, cy, cz, r, xx, n=24, half=False):
        Vd = [(xx, cy, cz)]
        nn = n // 2 if half else n
        for k in range(nn + 1 if half else n):
            a = (math.pi * k / nn) if half else TAU * k / n
            Vd.append((xx, cy + r * math.cos(a), cz + r * math.sin(a)))
        if half:
            Fd = [(0, k + 1, k + 2) for k in range(nn)]
        else:
            Fd = [(0, k + 1, (k + 1) % n + 1) for k in range(n)]
        kit.add(mat, (Vd, Fd), False)
    # the ground
    rect('int_fabric_white' if style != 1 else 'int_tile_white', -pw / 2, pw / 2, pz - ph / 2, pz + ph / 2, xp)
    ground = pal[0] if style == 1 else 'int_fabric_white'
    if style == 0:
        # mid-century: a sun over two hills of colour
        rect(pal[1], -pw / 2, pw / 2, pz - ph / 2, pz - ph * 0.12, xp + 0.001)
        disc(pal[2], pw * 0.12, pz + ph * 0.12, pw * 0.22, xp + 0.002, 28)
        disc(pal[3], -pw * 0.18, pz - ph * 0.12, pw * 0.30, xp + 0.003, 28, half=True)
    elif style == 1:
        # colour field: three stacked bands
        rect(pal[0], -pw / 2, pw / 2, pz + ph * 0.10, pz + ph / 2, xp + 0.001)
        rect(pal[1], -pw / 2, pw / 2, pz - ph * 0.22, pz + ph * 0.06, xp + 0.001)
        rect(pal[2], -pw / 2, pw / 2, pz - ph / 2, pz - ph * 0.26, xp + 0.001)
    else:
        # bauhaus: a quarter circle, a bar and a dot
        rect(pal[0], -pw / 2, pw * 0.05, pz - ph / 2, pz + ph * 0.05, xp + 0.001)
        disc(pal[1], pw * 0.18, pz + ph * 0.22, pw * 0.16, xp + 0.002, 24)
        rect(pal[2], -pw * 0.3, pw / 2, pz - ph * 0.30, pz - ph * 0.22, xp + 0.003)
    # a glass sheet over it all
    kit.add('int_glass', ([(xf - 0.003, -mw / 2, zc - mh / 2), (xf - 0.003, mw / 2, zc - mh / 2),
                           (xf - 0.003, mw / 2, zc + mh / 2), (xf - 0.003, -mw / 2, zc + mh / 2)], [(0, 1, 2, 3)]), False)


def b_curtains(kit, w, d, seed, P):
    """A pair of floor-length pleated curtains on a rod, drawn open to the
    sides of a window w wide. Back (the wall) on x = -d/2; the rod hangs
    P['head'] + 0.12 up (under the ceiling), its ends 0.22 past the opening."""
    rnd = random.Random(seed * 17 + 2)
    head = P['head']
    ceil = P['ceiling']
    over = 0.22
    rz = min(head + 0.13, ceil - 0.05)
    xw = -d / 2
    xr = xw + 0.10                                 # the rod's axis, 10 cm off the wall
    L = w + 2 * over
    # the rod: matt black, two wall brackets, ball finials
    kit.add('metal_dark', sweep([(xr, -L / 2 - 0.02, rz), (xr, L / 2 + 0.02, rz)], circle2(0.011, 8))[0], True)
    for s in (-1, 1):
        for mesh, sm in lathe([(0, rz - 0.022), (0.02, rz - 0.017), (0.024, rz), (0.02, rz + 0.017), (0, rz + 0.022)],
                              10, xr, s * (L / 2 + 0.035)):
            kit.add('metal_dark', mesh, True)
        by = s * (L / 2 - 0.08)
        kit.add('metal_dark', box((xw, by - 0.008, rz - 0.01), (xr, by + 0.008, rz + 0.01), skip=('-x',)), False)
        side, caps = slab(lambda ins: circle2(0.025 - ins, 10, 0), 0, 0.008, 0.002, 1)
        disk = rot(merge(side, caps), 'y', math.pi / 2)
        kit.add('metal_dark', mv(disk, xw + 0.0, by, rz), False)
    # the cloth: a gathered sheet hanging from just under the rod to 1 cm off
    # the floor; open fraction -> how much of the window each panel covers
    opn = max(0.0, min(1.0, P['open']))
    top = rz - 0.035
    bot = 0.012
    for s in (-1, 1):
        outer_y = s * (L / 2 - 0.03)
        stack = max(0.28, min(0.50, 0.18 + 0.10 * w))   # the gathered panel, drawn right back
        span = stack + (w / 2) * (1.0 - opn)
        inner_y = outer_y - s * span
        pleat = 0.10
        nP = max(3, int(round(span / pleat)))
        samples = nP * 4
        nz = 4
        V, F = [], []
        ph = rnd.uniform(0, TAU)
        for iz in range(nz + 1):
            tz = iz / nz
            z = bot + (top - bot) * (1 - tz) ** 1.0
            # toward the floor the pleats open a little and the hem kicks out
            amp = 0.036 + 0.010 * tz
            fl = 1.0 + 0.10 * tz                    # the panel spreads toward the hem
            for k in range(samples + 1):
                u = k / samples
                yy = outer_y + (inner_y - outer_y) * u
                yy = outer_y + (yy - outer_y) * fl if True else yy
                wave = math.sin(u * nP * TAU + ph * 0.0)
                # pinch pleats at the top: sharp folds; softer lower down
                x = xr + 0.045 + amp * wave * (0.75 + 0.25 * math.sin(u * 7 + ph))
                V.append((x, yy, z))
        n = samples + 1
        for iz in range(nz):
            for k in range(samples):
                a = iz * n + k
                q = (a, a + 1, a + n + 1, a + n)
                # face the room (+X): wind so the normal points +x on average
                F.append(q if s > 0 else q)
        m = (V, F)
        # make the sheet face +X (into the room): test one face normal
        a, b, c = V[F[0][0]], V[F[0][1]], V[F[0][2]]
        nrm = _cross(_v_sub(b, a), _v_sub(c, b))
        mesh = m if nrm[0] > 0 else flip(m)
        kit.add('int_curtain', mesh, True)
        # the heading tape along the top: a thin straight band
    return


# ====================================================================== registry
KINDS = {
    'sofa': dict(
        drawn=True, wall=True, solid=True,
        params=dict(seat_h=(0.45, 0.40, 0.48), arm_w=(0.16, 0.10, 0.24), cushions=(0, 0, 3),
                    scatter=(2, 0, 3), throw=(1, 0, 1), fabric=(0, 0, 5)),
        footprint='w = across (local Y, arm to arm), d = along the facing (local X, back at -d/2, seat front at +d/2). '
                  'The whole piece stays inside the box except the front of the seat cushions (1 cm proud) and the '
                  'throw (2-3 cm outside one arm). Drawn boxes: 1.80 x 1.00 everywhere; 1.4-2.6 x 0.8-1.05 works.',
        notes='Seat top 0.45, arms 0.62, back cushions to ~0.88. 2 seat/back cushions under 1.75 m inner width, else 3. '
              'Scatter cushions and the throw colour/side vary with seed. fabric indexes FABRICS (0 = int_fabric_sofa). '
              'Main material int_fabric_sofa; legs int_wood_walnut; accents int_fabric_orange/teal/white/bluegrey.'),
    'armchair': dict(
        drawn=False, wall=False, solid=True,
        params=dict(seat_h=(0.43, 0.40, 0.46), arm_w=(0.14, 0.10, 0.20), scatter=(1, 0, 1), fabric=(2, 0, 5)),
        footprint='w across (arm to arm, 0.70-0.95), d along the facing (0.75-0.92); back at -d/2.',
        notes='A lounge chair to go with the sofa (default teal). Wants floor 0.80 x 0.85 free beside the sofa or by a '
              'window, turned toward the coffee table; the back may stand free.'),
    'table_coffee': dict(
        drawn=True, wall=False, solid=False,
        params=dict(h=(0.40, 0.35, 0.45), decor=(1, 0, 1)),
        footprint='w across (local Y, the long side as drawn: 1.20), d along the facing (local X, 0.60). The legs splay '
                  '1 cm inside the box; nothing outside it.',
        notes='Top int_coffee_top (the owner\'s), walnut legs and shelf, books / bowl / vase on top. 0.40 high: under '
              'the walk\'s 0.4 m solid threshold by design (only the top is at 0.40).'),
    'tv': dict(
        drawn=True, wall=True, solid=True,
        params=dict(console_w=(0.0, 0.0, 2.4), console_d=(0.40, 0.32, 0.48), console_h=(0.50, 0.40, 0.60),
                    decor=(1, 0, 1)),
        footprint='w = the SCREEN width (local Y; the sheets draw 0.80), d = the drawn depth (0.20); the back of the '
                  'piece is x = -d/2 = the wall. The media console is WIDER and DEEPER than the drawn box: '
                  'console_w (0 = auto: w + 0.70, 1.40..2.20) across, console_d (0.40) from the wall, so it reaches '
                  'console_d - d = 0.20 m in front of the drawn box.',
        notes='Integrator: check that console_w fits the wall it stands on (clear of doors/corners) - pass console_w '
              'explicitly where the wall is short; the solid footprint for the walk is console_w x console_d with '
              'its back on the wall, not the drawn 0.80 x 0.20. Screen 16:9, centre ~1.0 m; soundbar; decor.'),
    'table_round': dict(
        drawn=True, wall=False, solid=True,
        params=dict(dia=(0.0, 0.0, 1.30), legs=(0, 0, 1)),
        footprint='a circle of diameter dia (0 = max(w, d)); orientation free.',
        notes='Marble top at 0.75 (int_marble), turned oak pedestal (legs=0) or four turned legs (legs=1). '
              'Pair with the pendant above its centre.'),
    'chair': dict(
        drawn=True, wall=False, solid=True,
        params=dict(seat_h=(0.46, 0.43, 0.48), fabric=(3, 0, 5)),
        footprint='w across (seat width = clamp(w + 0.04, 0.40, 0.48)), d along the facing (seat depth = '
                  'clamp(d - 0.03, 0.40, 0.46)); faces +X (toward its table), back rail at -X. The seat is '
                  'centred 1.5 cm forward of the box centre; the back rail\'s top leans back to ~ -d/2 - 0.03.',
        notes='Oak frame, padded seat (fabric index into FABRICS: 3 = int_fabric_dark), bentwood back rail at '
              '0.64-0.80. Main material int_wood_oak (not dining_chair_02, which needs UVs).'),
    'rug': dict(
        drawn=False, wall=False, solid=False,
        params=dict(thick=(0.012, 0.006, 0.02), border=(1, 0, 1)),
        footprint='w across, d along (the rug\'s two sides); centred on the origin.',
        notes='Under the sofa front legs and the coffee table: e.g. w = sofa w + 0.4, d = 1.6-2.0, its centre ~0.25 m '
              'in front of the sofa box centre. int_rug + a darker bound band. Bottom at z = 1.5 mm.'),
    'floor_lamp': dict(
        drawn=False, wall=False, solid=False,
        params=dict(h=(1.60, 1.40, 1.75)),
        footprint='w x d = the shade\'s box (0.34-0.48); round, orientation free.',
        notes='A brass stem on a dark stone foot, a glowing linen drum. Beside a sofa arm or armchair, in a corner. '
              'Thin, so not solid in the walk (the foot is 3 cm).'),
    'bookshelf': dict(
        drawn=False, wall=True, solid=True,
        params=dict(h=(1.90, 1.40, 2.30)),
        footprint='w across (0.8-2.0), d along the facing (0.30-0.40); back on x = -d/2 = the wall.',
        notes='Oak carcass, white back, shelves every ~0.36 filled with seeded runs of books, a leaning book, lying '
              'stacks, vases and bowls. Wants a stretch of plain wall w long with nothing in front for 0.8 m.'),
    'sideboard': dict(
        drawn=False, wall=True, solid=True,
        params=dict(h=(0.75, 0.60, 0.85), decor=(1, 0, 1)),
        footprint='w across (1.0-2.2), d along the facing (0.38-0.48); back on x = -d/2 = the wall.',
        notes='Walnut credenza with oak doors and brass pulls, a table lamp, vases, a book and a brass bowl on top. '
              'In a dining area against a wall; wall_art centred above it at cz ~1.55.'),
    'wall_art': dict(
        drawn=False, wall=True, solid=False,
        params=dict(h=(0.0, 0.0, 1.4), cz=(1.50, 1.20, 1.80), style=(-1, -1, 2)),
        footprint='w = frame width (0.4-1.2) across, d = depth off the wall (0.03); back (x = -d/2) on the wall. '
                  'h = frame height (0 = 1.3 w, portrait); cz = the centre height above the floor.',
        notes='Hangs on a wall: over the sofa (w ~0.6-0.9, cz 1.45, or two side by side), over a sideboard (cz 1.55), '
              'beside the dining table. style -1 = seeded (0 sun and hills, 1 colour field, 2 bauhaus).'),
    'curtains': dict(
        drawn=False, wall=True, solid=False,
        params=dict(head=(2.30, 1.90, 2.70), ceiling=(2.70, 2.40, 3.20), open=(0.90, 0.0, 1.0)),
        footprint='w = the window OPENING width (local Y), d = 0.16 (depth off the wall, local X); back (x = -d/2) on '
                  'the window wall, origin centred on the opening. The rod runs 0.22 past each side of the opening '
                  '(+ finials ~0.06), so the piece is w + 0.56 wide.',
        notes='head = the window\'s head height above this floor; the rod hangs at min(head + 0.13, ceiling - 0.05). '
              'open = 1 draws both panels right back (each a gathered stack 0.28-0.50 wide, most of it past the opening); '
                 'lower values bring them in over the glass by (1 - open) * w / 2. '
              'int_curtain is DoubleSide and translucent in the page: the cloth is ONE sheet. The page needs a '
              'window wall at least w + 0.6 wide (corners / side walls within 0.3 m of the opening clip the rod).'),
    'pendant': dict(
        drawn=False, wall=False, solid=False,
        params=dict(ceiling=(2.70, 2.40, 3.20), drop=(1.50, 1.35, 1.80)),
        footprint='w x d = the dome\'s box (dia = min(w, d), 0.30-0.60); origin on the FLOOR right under it.',
        notes='Place at the dining table\'s centre (same at). ceiling = the room\'s clear height (the cable runs to '
              'it); drop = the height of the dome\'s rim above the floor (1.50 = 0.75 over the table).'),
}


_BUILDERS = {
    'sofa': b_sofa, 'armchair': b_armchair, 'table_coffee': b_table_coffee, 'tv': b_tv, 'table_round': b_table_round,
    'chair': b_chair, 'rug': b_rug, 'floor_lamp': b_floor_lamp, 'bookshelf': b_bookshelf, 'sideboard': b_sideboard,
    'wall_art': b_wall_art, 'curtains': b_curtains, 'pendant': b_pendant,
}

# the material a node should be named after (CONTRACT: ..._furn_<kind><k>__<material>)
MAIN_MAT = {
    'sofa': 'int_fabric_sofa', 'armchair': 'int_fabric_teal', 'table_coffee': 'int_coffee_top', 'tv': 'int_wood_walnut',
    'table_round': 'int_marble', 'chair': 'int_wood_oak', 'rug': 'int_rug', 'floor_lamp': 'int_lamp_shade',
    'bookshelf': 'int_wood_oak', 'sideboard': 'int_wood_walnut', 'wall_art': 'int_wood_oak', 'curtains': 'int_curtain',
    'pendant': 'int_brass',
}


def params_of(kind, given):
    P = {k: v[0] for k, v in KINDS[kind]['params'].items()}
    for k, v in given.items():
        if k in P:
            lo, hi = KINDS[kind]['params'][k][1], KINDS[kind]['params'][k][2]
            P[k] = max(lo, min(hi, v))
        else:
            P[k] = v
    return P


def build(kind, w, d, seed=0, **params):
    """-> [(material_name, verts, faces, smooth)] in the local frame."""
    if kind not in KINDS:
        raise ValueError('unknown kind %r' % kind)
    kit = Kit()
    _BUILDERS[kind](kit, float(w), float(d), int(seed), params_of(kind, params))
    return kit.out()


def tri_count(kind, w, d, **p):
    return sum(ntris(f) for _, _, f, _ in build(kind, w, d, **p))


DEFAULT_SIZE = {
    'sofa': (1.80, 1.00), 'armchair': (0.82, 0.84), 'table_coffee': (1.20, 0.60), 'tv': (0.80, 0.20),
    'table_round': (0.80, 0.80), 'chair': (0.40, 0.47), 'rug': (2.00, 1.40), 'floor_lamp': (0.40, 0.40),
    'bookshelf': (1.00, 0.35), 'sideboard': (1.60, 0.42), 'wall_art': (0.60, 0.03), 'curtains': (1.40, 0.16),
    'pendant': (0.40, 0.40),
}
SIZE_RANGE = {
    'sofa': ((1.40, 0.80), (2.60, 1.05)), 'armchair': ((0.70, 0.75), (0.95, 0.92)),
    'table_coffee': ((0.90, 0.45), (1.45, 0.70)), 'tv': ((0.60, 0.10), (1.40, 0.30)),
    'table_round': ((0.70, 0.70), (1.30, 1.30)), 'chair': ((0.36, 0.42), (0.48, 0.52)),
    'rug': ((1.20, 0.80), (3.00, 2.40)), 'floor_lamp': ((0.34, 0.34), (0.48, 0.48)),
    'bookshelf': ((0.80, 0.30), (2.00, 0.40)), 'sideboard': ((1.00, 0.38), (2.20, 0.48)),
    'wall_art': ((0.40, 0.03), (1.20, 0.04)), 'curtains': ((0.80, 0.16), (3.00, 0.16)),
    'pendant': ((0.30, 0.30), (0.60, 0.60)),
}


# ====================================================================== preview (Blender only)
PREVIEW_COL = {
    'int_fabric_sofa': ('#7b7f86', 0.95, 0), 'int_fabric_bluegrey': ('#8294a8', 0.92, 0),
    'int_fabric_teal': ('#3c8a84', 0.92, 0), 'int_fabric_dark': ('#3d4148', 0.95, 0),
    'int_fabric_white': ('#eeeae2', 0.88, 0), 'int_fabric_orange': ('#d6622a', 0.9, 0),
    'int_wood_walnut': ('#4f3627', 0.48, 0), 'int_wood_oak': ('#b3895a', 0.55, 0),
    'int_coffee_top': ('#2b3139', 0.22, 0), 'int_marble': ('#e8e5e0', 0.12, 0), 'int_ceramic': ('#ecece9', 0.10, 0),
    'int_stone_dark': ('#3a3a3c', 0.32, 0), 'int_black': ('#111214', 0.25, 0.2), 'metal_dark': ('#43444a', 0.34, 0.9),
    'int_brass': ('#b08c55', 0.35, 0.85), 'int_white_gloss': ('#e6e5e1', 0.22, 0), 'int_mint': ('#a7c3b2', 0.3, 0),
    'int_accent_red': ('#8b2d29', 0.6, 0), 'int_rug': ('#9a9ea5', 0.95, 0), 'int_lamp_shade': ('#f1e8d6', 0.7, 0),
    'int_curtain': ('#ccd2da', 0.86, 0), 'int_glass': ('#cfe3ea', 0.04, 0), 'int_tile_white': ('#e6e4df', 0.3, 0),
    'chrome': ('#cdd0d4', 0.14, 1.0), 'int_pot': ('#36322f', 0.6, 0),
}


def _preview_main():
    import bpy
    import sys
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    outdir = argv[0] if argv else '/tmp/living'
    want = [a for a in argv[1:] if not a.startswith('--')] or list(KINDS)
    import os
    os.makedirs(outdir, exist_ok=True)

    def srgb(hx):
        c = [int(hx[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    mats = {}

    def mat(name):
        if name in mats:
            return mats[name]
        hx, r, mt = PREVIEW_COL.get(name, ('#ff00ff', 0.5, 0))
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        b = m.node_tree.nodes['Principled BSDF']
        b.inputs['Base Color'].default_value = srgb(hx) + [1]
        b.inputs['Roughness'].default_value = r
        b.inputs['Metallic'].default_value = mt
        if name in ('int_lamp_shade',):
            b.inputs['Emission Color'].default_value = srgb('#ffd9a6') + [1]
            b.inputs['Emission Strength'].default_value = 0.6
        if name in ('int_glass',):
            b.inputs['Alpha'].default_value = 0.15
            m.surface_render_method = 'BLENDED'
        if name in ('int_curtain',):
            b.inputs['Alpha'].default_value = 0.9
            b.inputs['Subsurface Weight'].default_value = 0.0
        m.use_backface_culling = name not in ('int_curtain', 'int_lamp_shade', 'int_glass')
        mats[name] = m
        return m

    sc = bpy.context.scene
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    sc.render.engine = 'BLENDER_EEVEE' if 'BLENDER_EEVEE' in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items] else 'BLENDER_EEVEE_NEXT'
    sc.render.resolution_x, sc.render.resolution_y = 900, 640
    sc.render.film_transparent = False
    sc.view_settings.view_transform = 'AgX'
    try:
        sc.eevee.use_shadows = True
        sc.eevee.use_raytracing = True
    except Exception:
        pass
    world = bpy.data.worlds.new('w')
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Color'].default_value = (0.75, 0.76, 0.78, 1)
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.30
    sc.world = world
    # floor + back wall
    fl = bpy.data.meshes.new('floor')
    fl.from_pydata([(-6, -6, 0), (6, -6, 0), (6, 6, 0), (-6, 6, 0)], [], [(0, 1, 2, 3)])
    fo = bpy.data.objects.new('floor', fl)
    fm = bpy.data.materials.new('floorm')
    fm.use_nodes = True
    fm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.42, 0.33, 0.24, 1)
    fm.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 0.5
    fl.materials.append(fm)
    sc.collection.objects.link(fo)
    wl = bpy.data.meshes.new('wall')
    wl.from_pydata([(0, -6, 0), (0, 6, 0), (0, 6, 3.2), (0, -6, 3.2)], [], [(0, 1, 2, 3)])
    wo = bpy.data.objects.new('wall', wl)
    wm = bpy.data.materials.new('wallm')
    wm.use_nodes = True
    wm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.70, 0.68, 0.64, 1)
    wl.materials.append(wm)
    sc.collection.objects.link(wo)
    # lights: a big soft key from front-left, a fill, a sun for contact shadows
    for nm, loc, rotv, en, size in (('key', (3.5, 2.5, 3.0), (0.9, 0, 2.2), 380, 3.0),
                                    ('fill', (3.0, -3.0, 2.0), (1.1, 0, 0.8), 150, 4.0),
                                    ('top', (0.8, 0, 3.0), (0, 0, 0), 120, 2.0)):
        ld = bpy.data.lights.new(nm, 'AREA')
        ld.energy = en
        ld.size = size
        lo = bpy.data.objects.new(nm, ld)
        lo.location = loc
        lo.rotation_euler = rotv
        sc.collection.objects.link(lo)
        lo.constraints.new('TRACK_TO').target = fo
    cam_d = bpy.data.cameras.new('cam')
    cam = bpy.data.objects.new('cam', cam_d)
    sc.collection.objects.link(cam)
    sc.camera = cam
    tgt = bpy.data.objects.new('tgt', None)
    sc.collection.objects.link(tgt)
    tc = cam.constraints.new('TRACK_TO')
    tc.target = tgt
    from mathutils import Vector
    report = []

    def make(kind, w, d, seed=0, name=None, **p):
        parts = build(kind, w, d, seed, **p)
        V, F, M, S = [], [], [], []
        mlist = []
        for mname, pv, pf, sm in parts:
            if mname not in mlist:
                mlist.append(mname)
            o = len(V)
            V.extend(pv)
            for f in pf:
                F.append(tuple(o + i for i in f))
                M.append(mlist.index(mname))
                S.append(sm)
        me = bpy.data.meshes.new(name or kind)
        me.from_pydata(V, [], F)
        for mname in mlist:
            me.materials.append(mat(mname))
        for poly, mi, s in zip(me.polygons, M, S):
            poly.material_index = mi
            poly.use_smooth = s
        me.validate()
        import bmesh
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(name or kind, me)
        sc.collection.objects.link(ob)
        zs = [v[2] for v in V]
        xs = [v[0] for v in V]
        ys = [v[1] for v in V]
        report.append('%s w%.2f d%.2f: %d tris  x[%.3f %.3f] y[%.3f %.3f] z[%.4f %.3f] parts %d' % (
            kind, w, d, sum(len(f) - 2 for f in F), min(xs), max(xs), min(ys), max(ys), min(zs), max(zs), len(parts)))
        return ob

    def shot(path, eye, look, lens=35):
        cam.location = eye
        tgt.location = look
        cam_d.lens = lens
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)

    for kind in want:
        sizes = [('def', DEFAULT_SIZE[kind])]
        if '--range' in sys.argv:
            sizes = [('min', SIZE_RANGE[kind][0]), ('def', DEFAULT_SIZE[kind]), ('max', SIZE_RANGE[kind][1])]
        for tag, (w, d) in sizes:
            for o in [o for o in sc.collection.objects if o.type == 'MESH' and o.name not in ('floor', 'wall')]:
                bpy.data.objects.remove(o, do_unlink=True)
            ob = make(kind, w, d, seed=int(os.environ.get('SEED', '0')))
            wall = KINDS[kind]['wall']
            # wall pieces stand with their back on the wall plane x=0
            ob.location = (d / 2 + 0.001, 0, 0) if wall else (1.2, 0, 0)
            wo.hide_render = not wall
            c = Vector(ob.location)
            dims = ob.dimensions
            big = max(dims.x, dims.y, dims.z * 0.9, 0.5)
            zc = dims.z * 0.45 if kind not in ('pendant', 'wall_art', 'curtains') else (dims.z * 0.5 + (2.7 - dims.z))
            if kind == 'wall_art':
                zc = 1.5
            if kind == 'pendant':
                zc = 1.8
            look = c + Vector((0, 0, zc if kind != 'curtains' else 1.4))
            dist = (big * 1.9 + 0.8) * float(os.environ.get('DIST', '1'))
            shot(os.path.join(outdir, '%s_%s_eye.png' % (kind, tag)),
                 c + Vector((dist * 0.82, dist * 0.55, 0)) + Vector((0, 0, 1.6 - c.z)), look)
            shot(os.path.join(outdir, '%s_%s_low.png' % (kind, tag)),
                 c + Vector((dist * 0.65, -dist * 0.6, 0)) + Vector((0, 0, 0.75)), look)
            shot(os.path.join(outdir, '%s_%s_top.png' % (kind, tag)),
                 c + Vector((dist * 0.35, dist * 0.2, dist * 1.25 + 1.0)), c + Vector((0, 0, 0.3)))
    open(os.path.join(outdir, 'report.txt'), 'w').write('\n'.join(report) + '\n')
    print('\n'.join(report))


if __name__ == '__main__':
    try:
        import bpy  # noqa
        _in_blender = True
    except ImportError:
        _in_blender = False
    if _in_blender:
        _preview_main()
    else:
        print('%-14s %-12s %6s %6s %6s' % ('kind', 'default', 'min', 'def', 'max'))
        for k in KINDS:
            (a, b), (c, e) = SIZE_RANGE[k]
            w, d = DEFAULT_SIZE[k]
            print('%-14s %4.2f x %4.2f %6d %6d %6d' % (k, w, d, tri_count(k, a, b), tri_count(k, w, d), tri_count(k, c, e)))
