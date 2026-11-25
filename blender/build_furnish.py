# -*- coding: utf-8 -*-
"""Furnish every flat and office the way the architect drew it.

    Blender -b -P blender/build_furnish.py [-- --levels L03,L04] [--out DIR] [--noweld] [--blend F]

Writes web/interior/furn/<LEVEL>.glb (L01 offices, L02..L10) and
web/interior/furn/index.json. Reads blender/plans/rooms.json (through
blender/lib_furnish.py, which decides what goes where) and the two
downloaded models that match a drawn symbol (blender/assets: the dining
chair and the low coffee table). Never touches anything else in web/.

Frame: the Blender local frame of CONTRACT.md, (x, -y, z) of the plan
frame with real z and no root - the same frame as web/interior/<LEVEL>.glb,
so the page hangs both under one transform.

Every piece is a node of its own (the page furnishes one flat at a time,
and staggers a flat's arrival piece by piece), and every node is an
INSTANCE of one mesh per (kind, size class): a level of 21 flats holds
~25 meshes, not ~400. The instances carry no modifiers, so the exporter
really does write one mesh (see blender.md: a modifier on an instance
silently un-shares it).
"""
import bpy, bmesh, os, sys, json, math, subprocess, tempfile, time
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import lib_build as LBD
import lib_furnish as LF

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = os.path.join(REPO, 'web', 'interior', 'furn')
if '--out' in args:
    OUT = args[args.index('--out') + 1]
WANT = args[args.index('--levels') + 1].split(',') if '--levels' in args else None
os.makedirs(OUT, exist_ok=True)
TAU = 2 * math.pi

# Triangle budgets for the two downloaded models. The chair is 22 k as it
# ships, and a residential floor holds ~57 of them; nothing in a floor view
# is more than a couple of hundred pixels tall.
CHAIR_TRIS = 1400
TABLE_TRIS = 700

# ------------------------------------------------------------ materials
# Names are web/materials.js keys (the page shades by name); the colours
# here only matter for Blender's own check renders.
MATDEF = {
    'int_wood_walnut': ('#4f3627', 0.48, 0.0), 'int_wood_oak': ('#b3895a', 0.55, 0.0),
    'int_fabric_white': ('#eeeae2', 0.90, 0.0), 'int_fabric_teal': ('#3c8a84', 0.92, 0.0),
    'int_fabric_bluegrey': ('#8294a8', 0.92, 0.0), 'int_fabric_sofa': ('#7b7f86', 0.95, 0.0),
    'int_fabric_dark': ('#3d4148', 0.95, 0.0), 'int_white_gloss': ('#f2f1ee', 0.22, 0.0),
    'int_black': ('#111214', 0.40, 0.2), 'int_coffee_top': ('#2b3139', 0.30, 0.0),
    'int_marble': ('#e8e5e0', 0.14, 0.0), 'dining_chair_02': ('#202227', 0.5, 0.0),
    'int_ceramic': ('#f4f4f2', 0.10, 0.0), 'chrome': ('#cdd0d4', 0.14, 1.0),
    'int_tile_wall': ('#eceae6', 0.10, 0.0), 'int_mint': ('#a7c3b2', 0.35, 0.0),
    'int_brass': ('#b08c55', 0.35, 0.85), 'metal_dark': ('#191a1d', 0.38, 0.85),
}


# the kits' preview colours for the names build 6 brought in (the page
# shades by name; these only colour Blender's own check renders)
for _m in (LF._KB, LF._KL, LF._KD, LF._KP):
    for _n, _v in getattr(_m, 'PREVIEW_COL', {}).items():
        MATDEF.setdefault(_n, _v)


def material(name):
    if name == 'int_glass':
        return LBD.mat('int_glass', LBD.srgb('#cfe2ea'), rough=0.05, alpha=0.30)
    hx, r, m = MATDEF[name]
    return LBD.mat(name, LBD.srgb(hx), rough=r, metal=m)


# ------------------------------------------------------------ geometry
class G:
    """Per-material accumulators for one piece, in its local frame."""
    def __init__(self):
        self.mb = {}

    def __call__(self, m):
        if m not in self.mb:
            self.mb[m] = LBD.MB()
        return self.mb[m]

    def mesh(self, name):
        V, F, M, S = [], [], [], []
        mats = list(self.mb)
        for mi, m in enumerate(mats):
            mb = self.mb[m]
            o = len(V)
            V.extend(mb.v)
            for k, f in enumerate(mb.f):
                F.append(tuple(o + i for i in f))
                M.append(mi)
                S.append(k in mb.smooth)
        me = bpy.data.meshes.new(name)
        me.from_pydata(V, [], F)
        for m in mats:
            me.materials.append(material(m))
        for p, mi, s in zip(me.polygons, M, S):
            p.material_index = mi
            p.use_smooth = s
        me.validate(clean_customdata=False)
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        bm.to_mesh(me)
        bm.free()
        return me


def prism(mb, pts, z0, z1, smooth=False):
    """Polygon (any winding) extruded z0..z1, outward faces."""
    a = sum(pts[k][0] * pts[(k + 1) % len(pts)][1] - pts[(k + 1) % len(pts)][0] * pts[k][1] for k in range(len(pts)))
    if a < 0:
        pts = pts[::-1]
    n = len(pts)
    o = len(mb.v)
    mb.v.extend([(x, y, z0) for x, y in pts])
    mb.v.extend([(x, y, z1) for x, y in pts])
    for k in range(n):
        j = (k + 1) % n
        if smooth:
            mb.smooth.add(len(mb.f))
        mb.f.append((o + k, o + j, o + n + j, o + n + k))
    # caps: fan-free, via tessellation of the polygon
    from mathutils.geometry import tessellate_polygon
    tris = tessellate_polygon([[Vector((x, y, 0)) for x, y in pts]])
    for t in tris:
        a_, b_, c_ = pts[t[0]], pts[t[1]], pts[t[2]]
        cr = (b_[0] - a_[0]) * (c_[1] - a_[1]) - (b_[1] - a_[1]) * (c_[0] - a_[0])
        top = (o + n + t[0], o + n + t[1], o + n + t[2])
        bot = (o + t[0], o + t[2], o + t[1])
        if cr < 0:
            top, bot = (top[0], top[2], top[1]), (bot[0], bot[2], bot[1])
        mb.f.append(top)
        mb.f.append(bot)


def rbox(mb, p0, p1, r, seg=3):
    """Box with rounded vertical arrises (lib_flat's): a mattress, a cushion."""
    x0, y0, z0 = p0
    x1, y1, z1 = p1
    r = max(0.001, min(r, (x1 - x0) * 0.5 - 0.001, (y1 - y0) * 0.5 - 0.001))
    pts = []
    for cx, cy, a0 in ((x1 - r, y1 - r, 0.0), (x0 + r, y1 - r, 90.0), (x0 + r, y0 + r, 180.0), (x1 - r, y0 + r, 270.0)):
        for k in range(seg + 1):
            a = math.radians(a0 + 90.0 * k / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    prism(mb, pts, z0, z1)


def ellipsoid(mb, c, rx, ry, rz, seg=10, rings=6):
    cx, cy, cz = c
    o = len(mb.v)
    for i in range(rings + 1):
        phi = math.pi * i / rings
        for j in range(seg):
            th = TAU * j / seg
            mb.v.append((cx + rx * math.sin(phi) * math.cos(th), cy + ry * math.sin(phi) * math.sin(th),
                         cz + rz * math.cos(phi)))
    for i in range(rings):
        for j in range(seg):
            n = (j + 1) % seg
            a = o + i * seg + j; b = o + i * seg + n
            c_ = o + (i + 1) * seg + n; d = o + (i + 1) * seg + j
            mb.smooth.add(len(mb.f))
            mb.f.append((a, d, c_, b))


def quarter(sx, sy, seg=10, inset=0.0):
    """Quarter-round footprint: corner at (-sx/2, -sy/2), bulging to (+,+)."""
    cx, cy = -sx / 2 + inset, -sy / 2 + inset
    rx, ry = sx - 2 * inset, sy - 2 * inset
    pts = [(cx, cy)]
    for k in range(seg + 1):
        t = (math.pi / 2) * k / seg
        pts.append((cx + rx * math.cos(t), cy + ry * math.sin(t)))
    return pts


# ---- one builder per kind; every one in the local frame: +X faces, origin
# at the footprint centre on the floor
def b_bed(g, w, d, duvet):
    x0, x1 = -d / 2, d / 2
    g('int_wood_oak').box((x0, -w / 2 - 0.04, 0.0), (x0 + 0.05, w / 2 + 0.04, 1.00))
    rbox(g('int_wood_walnut'), (x0 + 0.05, -w / 2, 0.0), (x1, w / 2, 0.30), 0.03)
    rbox(g('int_fabric_white'), (x0 + 0.09, -w / 2 + 0.04, 0.30), (x1 - 0.04, w / 2 - 0.04, 0.54), 0.05)
    rbox(g(duvet), (x0 + 0.60, -w / 2 + 0.02, 0.54), (x1 - 0.02, w / 2 - 0.02, 0.66), 0.08)
    for t in (-0.25, 0.25):
        ellipsoid(g('int_fabric_white'), (x0 + 0.34, t * w, 0.61), 0.20, 0.30 * w / 1.8, 0.08)


def b_nightstand(g, w, d):
    g('int_white_gloss').box((-d / 2, -w / 2, 0.0), (d / 2, w / 2, 0.48))
    g('int_wood_oak').box((-d / 2, -w / 2, 0.48), (d / 2, w / 2, 0.50))


def b_sofa(g, w, d):
    x0, x1 = -d / 2, d / 2
    for sy in (-1, 1):
        for xx in (x0 + 0.06, x1 - 0.06):
            g('int_black').box((xx - 0.02, sy * (w / 2 - 0.06) - 0.02, 0.0), (xx + 0.02, sy * (w / 2 - 0.06) + 0.02, 0.10))
    F = g('int_fabric_sofa')
    rbox(F, (x0, -w / 2, 0.10), (x1, w / 2, 0.40), 0.03)
    rbox(F, (x0, -w / 2, 0.40), (x0 + 0.22, w / 2, 0.80), 0.05)               # back
    for sy in (-1, 1):                                                           # arms
        y0, y1 = sorted((sy * w / 2, sy * (w / 2 - 0.18)))
        rbox(F, (x0 + 0.22, y0, 0.40), (x1, y1, 0.62), 0.05)
    inner = w / 2 - 0.18
    for y0, y1 in ((-inner, 0.0), (0.0, inner)):                                  # seat cushions
        rbox(g('int_fabric_dark'), (x0 + 0.22, y0 + 0.01, 0.40), (x1 - 0.02, y1 - 0.01, 0.50), 0.04)
    for y0, y1 in ((-inner, 0.0), (0.0, inner)):                                  # back cushions
        rbox(g('int_fabric_dark'), (x0 + 0.22, y0 + 0.02, 0.50), (x0 + 0.40, y1 - 0.02, 0.86), 0.05)


def b_coffee(g, w, d):
    """A low table that reads as one (build 4; the decimated Poly Haven model
    read as a dark block): a thin lacquered top with soft corners - the
    owner's int_coffee_top - an oak shelf low down, and four slim black legs
    set in from the corners, so the floor shows through it."""
    x0, x1, y0, y1 = -d / 2, d / 2, -w / 2, w / 2
    rbox(g('int_coffee_top'), (x0, y0, 0.365), (x1, y1, 0.39), 0.05, seg=4)
    rbox(g('int_wood_oak'), (x0 + 0.07, y0 + 0.07, 0.10), (x1 - 0.07, y1 - 0.07, 0.12), 0.02, seg=2)
    K = g('int_black')
    for (lx, ly) in ((x0 + 0.06, y0 + 0.06), (x1 - 0.06, y0 + 0.06), (x0 + 0.06, y1 - 0.06), (x1 - 0.06, y1 - 0.06)):
        K.box((lx - 0.0125, ly - 0.0125, 0.0), (lx + 0.0125, ly + 0.0125, 0.365))


def b_tv(g, w, d):
    h = w * 0.57
    xb = -d / 2 + 0.02
    g('int_black').box((xb, -w / 2, 0.80), (xb + 0.045, w / 2, 0.80 + h))


def b_table_round(g, dia):
    r = dia / 2
    g('int_marble').cyl((0, 0, 0.72), (0, 0, 0.75), r, seg=28)
    g('int_black').cyl((0, 0, 0.03), (0, 0, 0.72), 0.04, seg=10)
    g('int_black').cyl((0, 0, 0.0), (0, 0, 0.03), min(0.26, r * 0.6), seg=18)


def b_wc(g, w, d):
    x0, x1 = -d / 2, d / 2
    g('int_tile_wall').box((x0, -w / 2, 0.0), (x0 + 0.16, w / 2, 0.95))           # duct, concealed cistern
    g('chrome').box((x0 + 0.16, -0.10, 0.78), (x0 + 0.166, 0.10, 0.92))           # flush plate
    C = g('int_ceramic')
    rbox(C, (x0 + 0.16, -w / 2 + 0.03, 0.26), (x1, w / 2 - 0.03, 0.40), 0.14, seg=4)
    C.box((x0 + 0.16, -0.12, 0.18), (x0 + 0.42, 0.12, 0.28))
    rbox(g('int_white_gloss'), (x0 + 0.18, -w / 2 + 0.04, 0.40), (x1 - 0.01, w / 2 - 0.04, 0.425), 0.15, seg=4)


def b_basin(g, w, d):
    x0, x1 = -d / 2, d / 2
    rbox(g('int_ceramic'), (x0, -w / 2, 0.70), (x1, w / 2, 0.85), 0.07, seg=4)
    S = g('chrome')
    S.cyl((x0 + 0.06, 0, 0.85), (x0 + 0.06, 0, 1.02), 0.016, seg=10)
    S.cyl((x0 + 0.06, 0, 1.00), (x0 + 0.20, 0, 1.00), 0.012, seg=8)
    S.cyl((x0 + 0.08, 0, 0.42), (x0 + 0.08, 0, 0.70), 0.025, seg=10)            # trap


def b_corner(g, sx, sy, bath):
    if bath:
        prism(g('int_ceramic'), quarter(sx, sy, 12), 0.0, 0.55)
        prism(g('int_white_gloss'), quarter(sx, sy, 12, 0.07), 0.55, 0.552)
        g('chrome').cyl((-sx / 2 + 0.12, -sy / 2 + 0.12, 0.55), (-sx / 2 + 0.12, -sy / 2 + 0.12, 0.68), 0.016, seg=10)
        return
    prism(g('int_ceramic'), quarter(sx, sy, 10), 0.0, 0.05)
    arc = quarter(sx, sy, 10)[1:]
    G_ = g('int_glass')
    for a, b in zip(arc[:-1], arc[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1e-9
        nx, ny = -dy / L * 0.004, dx / L * 0.004
        prism(G_, [(a[0] - nx, a[1] - ny), (b[0] - nx, b[1] - ny), (b[0] + nx, b[1] + ny), (a[0] + nx, a[1] + ny)], 0.05, 1.95)
    S = g('chrome')
    cx, cy = -sx / 2 + 0.06, -sy / 2 + 0.06
    S.cyl((cx, cy, 0.05), (cx, cy, 2.00), 0.012, seg=8)
    S.cyl((cx + 0.10, cy + 0.10, 1.96), (cx + 0.10, cy + 0.10, 1.98), 0.10, seg=14)
    S.cyl((cx, cy, 1.97), (cx + 0.10, cy + 0.10, 1.97), 0.010, seg=6)


def b_bath(g, w, d):
    x0, x1, y0, y1 = -d / 2, d / 2, -w / 2, w / 2
    C = g('int_ceramic')
    for a_, b_, c_, d_ in ((x0, x0 + 0.06, y0, y1), (x1 - 0.06, x1, y0, y1),
                           (x0, x1, y0, y0 + 0.06), (x0, x1, y1 - 0.06, y1)):
        rbox(C, (a_, c_, 0.0), (b_, d_, 0.56), 0.02, seg=2)
    C.box((x0 + 0.06, y0 + 0.06, 0.0), (x1 - 0.06, y1 - 0.06, 0.12))
    g('chrome').cyl((x0 + 0.03, y0 + 0.30, 0.56), (x0 + 0.03, y0 + 0.30, 0.72), 0.016, seg=10)


def b_shower(g, w, d):
    x0, x1, y0, y1 = -d / 2, d / 2, -w / 2, w / 2
    g('int_ceramic').box((x0, y0, 0.0), (x1, y1, 0.04))
    g('int_glass').box((x1 - 0.01, y0, 0.04), (x1, y0 + w * 0.55, 1.95))
    S = g('chrome')
    S.cyl((x0 + 0.04, 0, 0.04), (x0 + 0.04, 0, 2.00), 0.012, seg=8)
    S.cyl((x0 + 0.20, 0, 1.96), (x0 + 0.20, 0, 1.98), 0.11, seg=14)
    S.cyl((x0 + 0.04, 0, 1.97), (x0 + 0.20, 0, 1.97), 0.010, seg=6)


def b_screen(g, L):
    g('int_glass').box((-0.004, -L / 2, 0.02), (0.004, L / 2, 1.95))
    g('chrome').box((-0.012, -L / 2, 1.95), (0.012, L / 2, 1.97))


def b_kitchen(g, w, d, upper, profile=None):
    if profile:
        # clipped to the room (lib_furnish.kitchen_profile): one run per
        # strip of equal depth, the back stepping forward round a column
        # or duct; the front line stays where the sheet draws it
        x1 = d / 2
        for (y0, y1, dep) in profile:
            x0 = x1 - dep
            g('int_black').box((x0, y0, 0.0), (x1 - 0.06, y1, 0.10))
            g('int_white_gloss').box((x0, y0, 0.10), (x1 - 0.02, y1, 0.86))
            g('int_mint').box((x0, y0, 0.86), (x1, y1, 0.90))
            n = max(1, int(round((y1 - y0) / 0.6)))
            if y1 - y0 >= 0.30:
                for k in range(n):
                    yc = y0 + (y1 - y0) * (k + 0.5) / n
                    g('int_brass').box((x1 - 0.02, yc - 0.08, 0.78), (x1 - 0.005, yc + 0.08, 0.80))
            if upper and dep >= 0.35:
                g('int_white_gloss').box((x0, y0, 1.45), (x0 + 0.35, y1, 2.15))
                if y1 - y0 >= 0.30:
                    for k in range(n):
                        yc = y0 + (y1 - y0) * (k + 0.5) / n
                        g('int_brass').box((x0 + 0.35, yc - 0.08, 1.49), (x0 + 0.365, yc + 0.08, 1.51))
        return
    x0, x1 = -d / 2, d / 2
    g('int_black').box((x0, -w / 2, 0.0), (x1 - 0.06, w / 2, 0.10))
    g('int_white_gloss').box((x0, -w / 2, 0.10), (x1 - 0.02, w / 2, 0.86))
    g('int_mint').box((x0, -w / 2, 0.86), (x1, w / 2, 0.90))
    n = max(1, int(round(w / 0.6)))
    for k in range(n):
        yc = -w / 2 + w * (k + 0.5) / n
        g('int_brass').box((x1 - 0.02, yc - 0.08, 0.78), (x1 - 0.005, yc + 0.08, 0.80))
    if upper:
        g('int_white_gloss').box((x0, -w / 2, 1.45), (x0 + 0.35, w / 2, 2.15))
        for k in range(n):
            yc = -w / 2 + w * (k + 0.5) / n
            g('int_brass').box((x0 + 0.35, yc - 0.08, 1.49), (x0 + 0.365, yc + 0.08, 1.51))


def b_sink(g):
    g('chrome').box((-0.21, -0.25, 0.9005), (0.21, 0.25, 0.905))
    g('int_black').box((-0.16, -0.20, 0.9050), (0.16, 0.20, 0.9055))             # the bowl, read from above
    S = g('chrome')
    S.cyl((-0.25, 0, 0.90), (-0.25, 0, 1.18), 0.014, seg=10)
    S.cyl((-0.25, 0, 1.16), (-0.08, 0, 1.16), 0.011, seg=8)


def b_hob(g):
    g('int_black').box((-0.25, -0.29, 0.9005), (0.25, 0.29, 0.907))


def b_desk(g, outline):
    prism(g('int_white_gloss'), list(outline), 0.72, 0.75)
    pts = list(outline)
    a = sum(pts[k][0] * pts[(k + 1) % len(pts)][1] - pts[(k + 1) % len(pts)][0] * pts[k][1] for k in range(len(pts)))
    if a < 0:
        pts = pts[::-1]
    n = len(pts)
    for k in range(n):
        p0, p1, p2 = pts[k - 1], pts[k], pts[(k + 1) % n]
        cr = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        if cr <= 0:
            continue                                   # a reflex corner carries no leg
        ux, uy = p0[0] - p1[0], p0[1] - p1[1]
        vx, vy = p2[0] - p1[0], p2[1] - p1[1]
        lu, lv = math.hypot(ux, uy) or 1, math.hypot(vx, vy) or 1
        cx = p1[0] + (ux / lu + vx / lv) * 0.05
        cy = p1[1] + (uy / lu + vy / lv) * 0.05
        g('metal_dark').box((cx - 0.02, cy - 0.02, 0.0), (cx + 0.02, cy + 0.02, 0.72))


def b_office_chair(g, w, d):
    K = g('int_black')
    for k in range(5):
        a = TAU * k / 5
        K.cyl((0, 0, 0.08), (0.30 * math.cos(a), 0.30 * math.sin(a), 0.05), 0.018, seg=6)
    K.cyl((0, 0, 0.08), (0, 0, 0.44), 0.025, seg=8)
    rbox(g('int_fabric_dark'), (-0.23, -0.24, 0.44), (0.23, 0.24, 0.52), 0.06)
    rbox(g('int_fabric_dark'), (-0.27, -0.22, 0.55), (-0.21, 0.22, 0.98), 0.05)
    K.box((-0.24, -0.03, 0.46), (-0.22, 0.03, 0.60))


def b_monitor(g, w, d):
    ww = max(0.45, min(0.62, w))
    g('int_black').box((-0.015, -ww / 2, 0.86), (0.015, ww / 2, 0.86 + ww * 0.58))
    g('int_black').box((-0.06, -0.012, 0.75), (-0.03, 0.012, 0.90))
    g('int_black').box((-0.12, -0.10, 0.75), (0.04, 0.10, 0.758))


# ------------------------------------------------------------ the two downloaded models
_assets = {}


def asset(name, budget, mat, face_from_neg_y, keep_uv):
    """Import once, join, bake, centre the footprint on the origin, collapse
    to `budget` triangles, turn to face +X, and re-dress in one material the
    page already maps. Kept out of the scene (fake user) so every level
    file can link it."""
    if name in _assets:
        return _assets[name]
    path = os.path.join(HERE, 'assets', name, name + '.gltf')
    before = set(bpy.data.objects)
    mats0, imgs0 = set(bpy.data.materials), set(bpy.data.images)
    bpy.ops.import_scene.gltf(filepath=path)
    # the model's own textured material is dropped: it would take the name
    # the page maps (Blender would then call ours `dining_chair_02.001`)
    for m in set(bpy.data.materials) - mats0:
        m.name = 'imported_' + m.name
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == 'MESH']
    bm = bmesh.new()
    for o in meshes:
        tmp = o.data.copy()
        tmp.transform(o.matrix_world)
        bm.from_mesh(tmp)
        bpy.data.meshes.remove(tmp)
    me = bpy.data.meshes.new('src_' + name)
    bm.to_mesh(me)
    bm.free()
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    for m in set(bpy.data.materials) - mats0:
        if m.users == 0:
            bpy.data.materials.remove(m)
    for im in set(bpy.data.images) - imgs0:
        bpy.data.images.remove(im)
    # decimate through a throwaway object
    ob = bpy.data.objects.new('tmp_' + name, me)
    bpy.context.scene.collection.objects.link(ob)
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    if tris > budget:
        mod = ob.modifiers.new('dec', 'DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.use_collapse_triangulate = True
        mod.ratio = budget / float(tris)
        dg = bpy.context.evaluated_depsgraph_get()
        baked = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
        ob.modifiers.remove(mod)
        ob.data = baked
        bpy.data.meshes.remove(me)
        me = baked
    bpy.data.objects.remove(ob, do_unlink=True)
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    me.transform(Matrix.Translation((-(min(xs) + max(xs)) / 2, -(min(ys) + max(ys)) / 2, -min(zs))))
    if face_from_neg_y:
        # the models are built with their back at +Y, looking down -Y
        # (lib_flat.face_to); turning +90 deg about z looks them down +X
        me.transform(Matrix.Rotation(math.pi / 2, 4, 'Z'))
    me.materials.clear()
    me.materials.append(material(mat))
    if not keep_uv:
        while me.uv_layers:
            me.uv_layers.remove(me.uv_layers[0])
    for p in me.polygons:
        p.use_smooth = True
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    size = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    me.use_fake_user = True
    print('[furn] model %-24s %6d -> %5d tris  %.2f x %.2f x %.2f' % (name, tris, sum(len(p.vertices) - 2 for p in me.polygons), *size))
    _assets[name] = (me, size)
    return _assets[name]


def parts_mesh(name, parts):
    """A kit's parts -> one mesh. Each part is welded on its own (its
    coincident vertices merged), never into its neighbours: a smooth cushion
    touching a flat frame keeps its own normals. Smooth per part."""
    V, F, M, S = [], [], [], []
    mats = []
    for m, verts, faces, smooth in parts:
        if m not in mats:
            mats.append(m)
        mi = mats.index(m)
        remap, idx = {}, []
        for v in verts:
            key = (round(v[0] * 1e5), round(v[1] * 1e5), round(v[2] * 1e5))
            if key not in remap:
                remap[key] = len(V)
                V.append((v[0], v[1], v[2]))
            idx.append(remap[key])
        for f in faces:
            q = []
            for i in f:
                j = idx[i]
                if not q or q[-1] != j:
                    q.append(j)
            if len(q) > 1 and q[0] == q[-1]:
                q.pop()
            if len(q) < 3 or len(set(q)) < len(q):
                continue
            F.append(tuple(q))
            M.append(mi)
            S.append(bool(smooth))
    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    for m in mats:
        me.materials.append(material(m))
    for p, mi, s in zip(me.polygons, M, S):
        p.material_index = mi
        p.use_smooth = s
    me.validate(clean_customdata=False)
    return me


def class_mesh(cid, kind, params):
    parts = LF.class_parts(cid, kind, params)
    if parts is not None:
        return parts_mesh(cid, parts)
    if kind == 'chair':
        me, size = asset('dining_chair_02', CHAIR_TRIS, 'dining_chair_02', True, True)
        return me
    g = G()
    P = params
    if kind == 'table_coffee':
        b_coffee(g, P['w'], P['d'])
    elif kind == 'bed_double':
        b_bed(g, P['w'], P['d'], P['duvet'])
    elif kind == 'nightstand':
        b_nightstand(g, P['w'], P['d'])
    elif kind == 'sofa':
        b_sofa(g, P['w'], P['d'])
    elif kind == 'tv':
        b_tv(g, P['w'], P['d'])
    elif kind == 'table_round':
        b_table_round(g, P['dia'])
    elif kind == 'wc':
        b_wc(g, P['w'], P['d'])
    elif kind == 'basin':
        b_basin(g, P['w'], P['d'])
    elif kind in ('shower_corner', 'bath_corner'):
        b_corner(g, P['sx'], P['sy'], kind == 'bath_corner')
    elif kind == 'bath':
        b_bath(g, P['w'], P['d'])
    elif kind == 'shower':
        b_shower(g, P['w'], P['d'])
    elif kind == 'partition_line':
        b_screen(g, P['L'])
    elif kind == 'kitchen_run':
        b_kitchen(g, P['w'], P['d'], P['upper'], P.get('profile'))
    elif kind == 'sink':
        b_sink(g)
    elif kind == 'hob':
        b_hob(g)
    elif kind == 'desk':
        b_desk(g, P['outline'])
    elif kind == 'office_chair':
        b_office_chair(g, P['w'], P['d'])
    elif kind == 'desk_equipment':
        b_monitor(g, P['w'], P['d'])
    else:
        raise ValueError(kind)
    return g.mesh(cid)


# ------------------------------------------------------------ files
def build_level(lv, L):
    for o in list(bpy.context.scene.collection.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    for me in list(bpy.data.meshes):
        if me.users == 0:
            bpy.data.meshes.remove(me)
    meshes = {}
    for cid, c in sorted(L['classes'].items()):
        meshes[cid] = class_mesh(cid, c['kind'], c['params'])
    coll = bpy.context.scene.collection
    tris = 0
    for p in L['pieces']:
        me = meshes[p['cls']]
        ob = bpy.data.objects.new(p['node'], me)
        ob.location = (p['at'][0], -p['at'][1], L['z'] + (p.get('z') or 0.0))
        ob.rotation_euler = (0.0, 0.0, -math.radians(p['rot']))
        coll.objects.link(ob)
        tris += sum(len(q.vertices) - 2 for q in me.polygons)
    names = [o.name for o in coll.objects]
    bad = [p['node'] for p in L['pieces'] if p['node'] not in names]
    if bad:
        raise SystemExit('[furn] Blender renamed %d nodes (duplicates?): %s' % (len(bad), bad[:5]))
    path = os.path.join(OUT, lv + '.glb')
    bpy.ops.export_scene.gltf(
        filepath=path, export_format='GLB',
        use_visible=True, export_apply=True,
        export_yup=True, export_cameras=False, export_lights=False,
        export_normals=True, export_texcoords=True,
        export_materials='EXPORT', export_extras=False,
        export_vertex_color='NONE', export_image_format='NONE',
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=7,
        export_draco_position_quantization=14,
        export_draco_normal_quantization=10,
        export_draco_texcoord_quantization=12,
        export_draco_color_quantization=8)
    uniq = sum(sum(len(q.vertices) - 2 for q in m.polygons) for m in meshes.values())
    if '--dump' in args:
        # every class's local bounds, for the footprint checks
        bb = {}
        for cid, m in meshes.items():
            xs = [v.co.x for v in m.vertices]; ys = [v.co.y for v in m.vertices]; zs = [v.co.z for v in m.vertices]
            bb[cid] = [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
        DUMP[lv] = dict(z=L['z'], classes=bb, tris={cid: sum(len(q.vertices) - 2 for q in m.polygons) for cid, m in meshes.items()},
                        profiles={cid: c['params']['profile'] for cid, c in L['classes'].items()
                                  if c['params'].get('profile')},
                        omitted=[o for o in LF.OMITTED if o['level'] == lv],
                        pieces=[{k: p.get(k) for k in ('node', 'kind', 'n', 'owner', 'cls', 'at', 'rot', 'box', 'foot', 'z', 'room', 'src', 'drawn')}
                                                     for p in L['pieces']])
    return path, tris, uniq, len(L['pieces']), len(meshes)


def weld(path):
    """The same lossless weld + re-encode build_interior.py gives its files."""
    tmp = tempfile.mktemp(suffix='.glb')
    cmd = ['npx', '--yes', '@gltf-transform/cli@4.5.1', 'draco', path, tmp,
           '--quantize-position', '14', '--quantize-normal', '10',
           '--quantize-texcoord', '12', '--quantize-color', '8',
           '--encode-speed', '3', '--decode-speed', '3']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) < os.path.getsize(path):
            os.replace(tmp, path)
            return True
    except Exception as e:
        print('[furn] weld skipped:', e)
    if os.path.exists(tmp):
        os.remove(tmp)
    return False


t0 = time.time()
LBD.reset_scene()
LBD.MATS.clear()
levels = LF.plan_levels(WANT)
stats = {}
DUMP = {}
for lv in sorted(levels):
    t1 = time.time()
    path, tris, uniq, nodes, nmesh = build_level(lv, levels[lv])
    raw = os.path.getsize(path)
    welded = '--noweld' not in args and weld(path)
    import gzip
    gz = len(gzip.compress(open(path, 'rb').read(), 9))
    stats[lv] = dict(tris_placed=tris, tris_unique=uniq, nodes=nodes, meshes=nmesh,
                     bytes=os.path.getsize(path), gzip=gz, bytes_export=raw, welded=welded)
    print('[furn] %-4s %5d nodes %3d meshes %7d tris placed %6d unique %8d B (%d gz)  %.1f s'
          % (lv, nodes, nmesh, tris, uniq, os.path.getsize(path), gz, time.time() - t1))
    if '--blend' in args:
        bpy.ops.wm.save_as_mainfile(filepath=args[args.index('--blend') + 1].replace('.blend', '_%s.blend' % lv))
if '--dump' in args:
    json.dump(DUMP, open(args[args.index('--dump') + 1], 'w'))
idx_path = os.path.join(OUT, 'index.json')
idx = LF.index_json(levels, stats)
if WANT and os.path.exists(idx_path):
    # a partial run keeps the other levels' entries
    old = json.load(open(idx_path))
    for k, v in old.get('levels', {}).items():
        idx['levels'].setdefault(k, v)
    idx['levels'] = dict(sorted(idx['levels'].items()))
json.dump(idx, open(idx_path, 'w'), ensure_ascii=False, separators=(',', ':'))
print('[furn] index %s (%d B)' % (idx_path, os.path.getsize(idx_path)))
print('[furn] done in %.1f s' % (time.time() - t0))
