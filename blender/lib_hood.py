# -*- coding: utf-8 -*-
"""The neighbourhood round the block, as the architect's renders show it
(~/Desktop/wetransfer_006.../001-006): cream stone perimeter blocks on every
side - dark shopfronts, a giant order of pilasters over two storeys,
cornices, smooth panelled upper floors that step back, low hipped roofs,
the odd nine-storey corner tower - behind avenues of street trees, lamp
columns, planted beds with timber-slat fences at the corners, and a planted
square across the main street. No vehicles, no people.

Plan frame as in lib_city. The blocks wear five materials of their own
(hood_panel, hood_stone_low, hood_roof, hood_shopglass, hood_awning), built
in web/materials.js from world position alone - no UVs - to the renders'
stone: honed 0.66 m panels from the order's cornice up, rough granite on the
order and the ground storey, black piers round lit shop glass, navy awnings
on every street front, warm grey zinc roofs. The upper panes are the dark
honed hood_shopglass of the piers (the renders' windows read dark; the main
building's glazing shows them as pale blinds or flat sky); the shop panes
reuse the main building's glass_shop, so neither adds a pipeline.
Storeys follow the building's own grid (4.80 + n x 3.30) because the
window glass draws its rooms on that grid.

A bar of building is generated once per (type, bays, lod, variant) and
placed as linked duplicates, so the GLB carries each only once.
"""
import bpy, math, random
from lib_build import MB, link_dup, collection, TAU
import lib_building as LB
import lib_city as LC

M = LB.M
P = LC.P
pbox = LC.pbox

BAY = 3.0
DEP = 15.0            # a bar's depth
GH = 4.80             # ground storey
FH = 3.30
PAV = 6.0             # kerb to the building line
LOD_R = 150.0         # bars nearer the site than this get the full detail
SITE_C = (41.0, 17.0)

# what a bar is made of, bottom up, and its upper volumes:
# (from, to) along the bar as fractions, front set-back, storeys
TYPES = {
    'grand7': {'base': ('shop', 'order', 'mid', 'mid'),
               'tops': ((0.0, 0.28, 1.8, 1), (0.28, 0.80, 0.0, 2), (0.80, 1.0, 1.8, 2))},
    'six':    {'base': ('shop', 'order', 'mid'),
               'tops': ((0.0, 0.62, 0.0, 2), (0.62, 1.0, 1.8, 1))},
    'low5':   {'base': ('stone', 'order'),
               'tops': ((0.0, 0.24, 0.0, 1), (0.24, 1.0, 0.0, 2))},
    'tower9': {'base': ('shop', 'order', 'mid', 'mid'),
               'tops': ((0.0, 1.0, 0.0, 4),)},
}
MATS = ('hood_panel', 'hood_stone_low', 'hood_roof', 'glass_shop', 'hood_shopglass',
        'hood_awning', 'rail_balcony')


class Seg:
    """One wall of a volume. u runs along it, d into the building (negative
    = proud of the wall), z up. Walls are walked counter-clockwise, so
    (u, d, z) is a proper turn of (x, y, z) and a box keeps its winding."""

    def __init__(self, ox, oy, tx, ty, L):
        self.o = (ox, oy); self.t = (tx, ty); self.n = (-ty, tx); self.L = L

    def box(self, mb, u0, u1, d0, d1, z0, z1, keep=None, flip=False):
        o, t, n = self.o, self.t, self.n
        v = [(o[0] + t[0] * u + n[0] * d, o[1] + t[1] * u + n[1] * d, z)
             for (u, d, z) in ((u0, d0, z0), (u1, d0, z0), (u1, d1, z0), (u0, d1, z0),
                               (u0, d0, z1), (u1, d0, z1), (u1, d1, z1), (u0, d1, z1))]
        faces = {'-z': (0, 3, 2, 1), '+z': (4, 5, 6, 7), 'f': (0, 1, 5, 4),
                 'b': (2, 3, 7, 6), '-u': (3, 0, 4, 7), '+u': (1, 2, 6, 5)}
        fl = [f for k, f in faces.items() if keep is None or k in keep]
        if flip:
            fl = [tuple(reversed(f)) for f in fl]
        mb.add(v, fl)

    def face(self, mb, u0, u1, z0, z1, d=0.0):
        self.box(mb, u0, u1, d, d + 0.1, z0, z1, keep=('f',))


def rect_segs(x0, y0, x1, y1):
    """front (y0), right end, back, left end"""
    return [Seg(x0, y0, 1, 0, x1 - x0), Seg(x1, y0, 0, 1, y1 - y0),
            Seg(x1, y1, -1, 0, x1 - x0), Seg(x0, y1, 0, -1, y1 - y0)]


def _bays(L):
    n = max(1, int(round(L / BAY)))
    return n, L / n


def _window(mbs, sg, cx, z0, z1, lod, d=0.0, ww=1.25, sill=True, rail=False, wall='hood_panel'):
    """the opening cx +- ww/2, z0..z1, in a wall standing at depth d; the
    caller has laid the wall round it (lod 0) or behind it (lod 1)"""
    a, b = cx - ww / 2, cx + ww / 2
    if lod:
        sg.face(mbs['hood_shopglass'], a, b, z0, z1, d - 0.05)
        return
    sg.box(mbs[wall], a, b, d, d + 0.17, z0, z1, keep=('-z', '+z', '-u', '+u'), flip=True)
    sg.face(mbs['hood_shopglass'], a, b, z0, z1, d + 0.17)
    if sill:
        sg.box(mbs[wall], a - 0.12, b + 0.12, d - 0.10, d, z0 - 0.12, z0, keep=('f', '+z', '-z'))
    if rail:
        r = mbs['rail_balcony']
        for zz in (z0 + 0.12, z0 + 1.0):
            sg.box(r, a, b, d - 0.05, d - 0.02, zz, zz + 0.04, keep=('f', '+z', '-z'))
        for k in range(1, 5):
            uu = a + (b - a) * k / 5.0
            sg.box(r, uu - 0.014, uu + 0.014, d - 0.045, d - 0.025, z0 + 0.16, z0 + 1.0, keep=('f',))


def _holed(mb, sg, u0, u1, z0, z1, a, b, oz0, oz1, d):
    """the wall of one bay with its opening left out"""
    sg.face(mb, u0, a, z0, z1, d); sg.face(mb, b, u1, z0, z1, d)
    sg.face(mb, a, b, z0, oz0, d); sg.face(mb, a, b, oz1, z1, d)


def storey(mbs, sg, kind, z0, lod, plain=False, blank=False, awn=False):
    """One storey (two for 'order') of one wall; returns its height."""
    L = sg.L
    n, b = _bays(L)
    S, SB = mbs['hood_panel'], mbs['hood_stone_low']
    if kind == 'shop':      # the shopfront's piers, plinth and fascia are black stone
        SB = mbs['hood_shopglass']
    h = GH if kind in ('shop', 'stone') else (2 * FH if kind == 'order' else FH)
    if blank:
        sg.face(S if kind in ('top', 'mid') else SB, 0, L, z0, z0 + h)
        return h
    if plain:
        # the courtyard side: a flat wall and flush panes
        sg.face(S if kind in ('top', 'mid') else SB, 0, L, z0, z0 + h)
        zs = [z0 + 0.3] if kind in ('shop', 'stone') else ([z0, z0 + FH] if kind == 'order' else [z0])
        for zz in zs:
            for k in range(n):
                _window(mbs, sg, (k + 0.5) * b, zz + 0.78, zz + 2.66, 1)
        return h
    if kind == 'shop':
        zf = 3.90
        if lod:
            sg.face(mbs['glass_shop'], 0, L, 0.0, zf, 0.0)
            sg.face(SB, 0, L, zf, h)
            for k in range(n + 1):
                u = min(max(k * b, 0.35), L - 0.35)
                sg.box(SB, u - 0.35, u + 0.35, -0.12, 0.0, 0.0, zf, keep=('f', '-u', '+u'))
            return h
        sg.face(mbs['glass_shop'], 0, L, 0.45, zf, 0.28)
        sg.box(SB, 0, L, 0.10, 0.30, 0.0, 0.45, keep=('f', '+z'))
        sg.box(SB, -0.08, L + 0.08, -0.08, 0.30, zf, h, keep=('f', '-z', '+z', '-u', '+u'))
        F = mbs['hood_shopglass']; A = mbs['hood_awning']
        sg.box(F, 0, L, 0.22, 0.28, 3.05, 3.13, keep=('f', '+z', '-z'))
        for k in range(n + 1):
            u = min(max(k * b, 0.36), L - 0.36)
            sg.box(SB, u - 0.36, u + 0.36, -0.05, 0.30, 0.0, zf, keep=('f', '-u', '+u'))
        for k in range(n):
            for q in (1, 2):
                uu = (k + q / 3.0) * b
                sg.box(F, uu - 0.03, uu + 0.03, 0.22, 0.28, 0.45, zf, keep=('f', '-u', '+u'))
            if awn and k % 3 != 2:
                # the dark awnings over the shop windows (002)
                a0, a1 = k * b + 0.45, (k + 1) * b - 0.45
                pts = [(a0, 0.0, 3.55), (a1, 0.0, 3.55), (a1, -1.25, 3.05), (a0, -1.25, 3.05),
                       (a0, -1.25, 2.83), (a1, -1.25, 2.83)]
                vs = [(sg.o[0] + sg.t[0] * u_ + sg.n[0] * d_, sg.o[1] + sg.t[1] * u_ + sg.n[1] * d_, z_)
                      for (u_, d_, z_) in pts]
                # each side on its own vertices: mesh.validate() drops a face
                # that repeats another's vertices reversed, which left only
                # the underside and hid the awnings from above
                A.add(vs, [(0, 1, 2, 3), (3, 2, 5, 4)])
                A.add(vs, [(3, 2, 1, 0), (4, 5, 2, 3)])
        return h
    if kind == 'stone':
        # a stone ground storey: tall windows over a plinth, a band on top
        for k in range(n):
            cx = (k + 0.5) * b
            if lod:
                continue
            _holed(SB, sg, k * b, (k + 1) * b, z0, z0 + h - 0.35, cx - 0.7, cx + 0.7, z0 + 0.95, z0 + 3.75, 0.0)
        if lod:
            sg.face(SB, 0, L, z0, z0 + h - 0.35)
        for k in range(n):
            _window(mbs, sg, (k + 0.5) * b, z0 + 0.95, z0 + 3.75, lod, ww=1.4, wall='hood_stone_low')
        sg.box(SB, -0.10, L + 0.10, -0.10, 0.1, z0 + h - 0.35, z0 + h, keep=('f', '-z', '+z', '-u', '+u'))
        if not lod:
            sg.box(SB, -0.06, L + 0.06, -0.06, 0.0, z0, z0 + 0.55, keep=('f', '+z', '-u', '+u'))
        return h
    if kind == 'order':
        d = 0.0 if lod else 0.14
        zc = z0 + h
        if lod:
            sg.face(SB, 0, L, z0, zc - 0.65)
        for k in range(n):
            cx = (k + 0.5) * b
            for zz in (z0, z0 + FH):
                if not lod:
                    _holed(SB, sg, k * b, (k + 1) * b, zz, min(zz + FH, zc - 0.65), cx - 0.625, cx + 0.625,
                           zz + 0.78, zz + 2.66, d)
                _window(mbs, sg, cx, zz + 0.78, zz + 2.66, lod, d=d, sill=False, wall='hood_stone_low')
            if not lod:   # the relief panel between the two storeys
                sg.box(SB, cx - 0.58, cx + 0.58, d - 0.05, d, z0 + 2.86, z0 + FH + 0.60,
                       keep=('f', '-u', '+u', '+z', '-z'))
        for k in range(n + 1):
            u = min(max(k * b, 0.31), L - 0.31)
            if lod:
                sg.box(SB, u - 0.30, u + 0.30, -0.16, 0.0, z0, zc - 0.65, keep=('f', '-u', '+u'))
                continue
            sg.box(SB, u - 0.38, u + 0.38, -0.10, d, z0, z0 + 0.50, keep=('f', '-u', '+u', '+z'))
            sg.box(SB, u - 0.29, u + 0.29, -0.04, d, z0 + 0.50, zc - 1.05, keep=('f', '-u', '+u'))
            sg.box(SB, u - 0.33, u + 0.33, -0.07, d, zc - 1.05, zc - 0.93, keep=('f', '-u', '+u', '-z', '+z'))
            sg.box(SB, u - 0.43, u + 0.43, -0.13, d, zc - 0.93, zc - 0.65, keep=('f', '-u', '+u', '-z'))
        sg.box(SB, -0.08, L + 0.08, -0.08, d + 0.01, zc - 0.65, zc - 0.34, keep=('f', '-z', '-u', '+u'))
        sg.box(SB, -0.45, L + 0.45, -0.45, 0.02, zc - 0.34, zc, keep=('f', '-z', '+z', '-u', '+u'))
        return h
    # the panels run down to the order's cornice: only the order and the
    # stone ground storey are granite (001, 002)
    wall = S
    wn = 'hood_panel'
    french = kind == 'top'
    wz0 = z0 + (0.22 if french else 0.78)
    top = z0 + h - (0.30 if kind == 'mid' else 0.0)
    if lod:
        sg.face(wall, 0, L, z0, top)
    for k in range(n):
        cx = (k + 0.5) * b
        if not lod:
            _holed(wall, sg, k * b, (k + 1) * b, z0, top, cx - 0.625, cx + 0.625, wz0, z0 + 2.66, 0.0)
        _window(mbs, sg, cx, wz0, z0 + 2.66, lod, sill=not french, rail=french, wall=wn)
    if kind == 'mid':
        sg.box(SB, -0.30, L + 0.30, -0.30, 0.02, top, z0 + h, keep=('f', '-z', '+z', '-u', '+u'))
        if not lod:
            sg.box(SB, -0.10, L + 0.10, -0.10, 0.0, top - 0.16, top, keep=('f', '-z', '-u', '+u'))
    return h


def hip_roof(mbs, x0, y0, x1, y1, z, rise=None):
    """an eaves slab and a low hipped roof over a rectangle"""
    e = 0.32
    mbs['hood_panel'].box((x0 - e, y0 - e, z), (x1 + e, y1 + e, z + 0.20),
                               skip=('+z',))
    a0, b0, a1, b1 = x0 - e, y0 - e, x1 + e, y1 + e
    w, d = a1 - a0, b1 - b0
    hw = min(w, d) / 2.0
    rise = rise if rise is not None else min(2.2, hw * 0.30)
    zb, zt = z + 0.20, z + 0.20 + rise
    R = mbs['hood_roof']
    if w >= d:
        r0, r1 = (a0 + hw, b0 + hw, zt), (a1 - hw, b0 + hw, zt)
        c = [(a0, b0, zb), (a1, b0, zb), (a1, b1, zb), (a0, b1, zb)]
        R.add([c[0], c[1], r1, r0], [(0, 1, 2, 3)]); R.add([c[2], c[3], r0, r1], [(0, 1, 2, 3)])
        R.add([c[1], c[2], r1], [(0, 1, 2)]); R.add([c[3], c[0], r0], [(0, 1, 2)])
    else:
        r0, r1 = (a0 + hw, b0 + hw, zt), (a0 + hw, b1 - hw, zt)
        c = [(a0, b0, zb), (a1, b0, zb), (a1, b1, zb), (a0, b1, zb)]
        R.add([c[1], c[2], r1, r0], [(0, 1, 2, 3)]); R.add([c[3], c[0], r0, r1], [(0, 1, 2, 3)])
        R.add([c[0], c[1], r0], [(0, 1, 2)]); R.add([c[2], c[3], r1], [(0, 1, 2)])


_KITS = {}


def bar_kit(kind, nb, lod, var):
    """{material: source object} for one bar, local frame: the street front
    on y = 0 looking -y, x 0..L, depth to +y"""
    key = (kind, nb, lod, var)
    if key in _KITS:
        return _KITS[key]
    T = TYPES[kind]
    L = nb * BAY
    mbs = {m: MB() for m in MATS}
    segs = rect_segs(0.0, 0.0, L, DEP)
    z = 0.0
    for i, sg in enumerate(segs):
        z = 0.0
        for kd in T['base']:
            z += storey(mbs, sg, kd, z, lod, plain=(i == 2), awn=(i != 2))
    zb = z
    mbs['hood_roof'].add([(0, 0, zb), (L, 0, zb), (L, DEP, zb), (0, DEP, zb)], [(0, 1, 2, 3)])
    tops = T['tops']
    if var % 2:
        tops = tuple((1.0 - b_, 1.0 - a_, sb, nf) for (a_, b_, sb, nf) in reversed(tops))
    nt = len(tops)
    for j, (fa, fb, sb, nf) in enumerate(tops):
        xa = round(fa * nb) * BAY; xb = round(fb * nb) * BAY
        if xb - xa < BAY:
            continue
        end_in = 1.8 if sb else 0.0          # a set-back volume steps in at its free end too
        x0 = xa + (end_in if j == 0 else 0.0); x1 = xb - (end_in if j == nt - 1 else 0.0)
        vs = rect_segs(x0, sb, x1, DEP)
        for i, sg in enumerate(vs):
            zz = zb
            inner = (i == 1 and j < nt - 1) or (i == 3 and j > 0)
            for _ in range(nf):
                zz += storey(mbs, sg, 'top', zz, lod, plain=(i == 2), blank=inner)
        if sb and not lod:      # the terrace's parapet rail
            r = mbs['rail_balcony']
            segs[0].box(r, x0, x1, 0.06, 0.10, zb + 1.0, zb + 1.05, keep=('f', 'b', '+z', '-z'))
            k = x0
            while k <= x1 + 1e-6:
                segs[0].box(r, k - 0.02, k + 0.02, 0.06, 0.10, zb, zb + 1.0, keep=('f', 'b', '-u', '+u'))
                k += (x1 - x0) / max(1, round((x1 - x0) / 1.5))
        hip_roof(mbs, x0, sb, x1, DEP, zb + nf * FH, rise=(1.0 if kind == 'tower9' else None))
    kc = collection('hoodkit')
    out = {}
    for mn, mb in mbs.items():
        if not mb.f:
            continue
        ob = mb.to_object('hoodkit_%s%d_%d_%d_%s' % (kind, nb, lod, var, mn), M(mn), kc)
        ob.hide_render = True; ob.hide_viewport = True
        out[mn] = ob
    _KITS[key] = out
    return out


# ------------------------------------------------------------------ placing
# facing -> (rotation, where the bar's local origin goes given its start s
# along the edge, its length L and the building line c)
def _place(kit, name, face, s, L, c, coll):
    if face == 'S':      # front looks +y; the edge runs in x
        loc, rot = P(s, c), 0.0
    elif face == 'N':
        loc, rot = P(s + L, c), math.pi
    elif face == 'E':    # front looks +x; the edge runs in y
        loc, rot = P(c, s + L), math.pi / 2
    else:
        loc, rot = P(c, s), -math.pi / 2
    for mn, src in kit.items():
        link_dup(src, '%s_%s' % (name, mn), loc=loc, rot_z=rot, coll=coll)


def _split(Le, r, pattern):
    """bars along an edge: [(start, bays, type)]"""
    n = max(1, int(round(Le / 31.0)))
    types = [pattern[int(round(i * (len(pattern) - 1) / max(1, n - 1)))] if n > 1 else pattern[0]
             for i in range(n)]
    nbs = [r.choice((6, 7, 8) if t == 'tower9' else (8, 9, 10, 11, 12)) for t in types]
    while sum(nbs) * BAY > Le and max(nbs) > 5:
        nbs[nbs.index(max(nbs))] -= 1
    while (sum(nbs) + 1) * BAY <= Le - 4.0 * (n > 1):
        i = min(range(n), key=lambda q: nbs[q] + (9 if types[q] == 'tower9' else 0))
        if nbs[i] >= 13:
            break
        nbs[i] += 1
    left = Le - sum(nbs) * BAY
    gaps = [0.0] * n
    if n > 1:
        if left / (n - 1) >= 3.5:
            gaps = [left / (n - 1)] * (n - 1) + [0.0]
            left = 0.0
        elif left >= 3.0:
            gaps[r.randrange(n - 1)] = left
            left = 0.0
    out, s = [], left / 2.0
    for i in range(n):
        out.append((s, nbs[i], types[i]))
        s += nbs[i] * BAY + gaps[i]
    return out


MIX = ('grand7', 'low5', 'six', 'low5', 'six', 'grand7', 'tower9', 'low5')


def build_cell(coll, name, x0, y0, x1, y1, r, owner='ns', patterns=None, lawn=None):
    """A perimeter block on the rectangle (building lines), a court inside.
    `patterns`: {'N'|'S'|'E'|'W': types along that edge, in +x / +y order}"""
    patterns = patterns or {}
    edges = []
    if owner == 'ns':
        edges += [('S', x0, x1, y1), ('N', x0, x1, y0), ('E', y0 + DEP, y1 - DEP, x1), ('W', y0 + DEP, y1 - DEP, x0)]
    else:
        edges += [('E', y0, y1, x1), ('W', y0, y1, x0), ('S', x0 + DEP, x1 - DEP, y1), ('N', x0 + DEP, x1 - DEP, y0)]
    k = 0
    for (face, a, b, c) in edges:
        if b - a < 5 * BAY:
            continue
        pat = patterns.get(face)
        if not pat:
            o = r.randrange(len(MIX))
            pat = [MIX[(o + q) % len(MIX)] for q in range(4)]
        for (s, nb, kind) in _split(b - a, r, pat):
            L = nb * BAY
            if face in ('S', 'N'):
                mx, my = a + s + L / 2, c
            else:
                mx, my = c, a + s + L / 2
            lod = 0 if math.hypot(mx - SITE_C[0], my - SITE_C[1]) < LOD_R else 1
            _place(bar_kit(kind, nb, lod, r.randrange(2)), '%s_%d' % (name, k), face, a + s, L, c, coll)
            k += 1
    if lawn is not None and x1 - x0 > 2 * DEP + 8 and y1 - y0 > 2 * DEP + 8:
        pbox(lawn, x0 + DEP + 3, y0 + DEP + 3, 0.0, x1 - DEP - 3, y1 - DEP - 3, 0.03)


# ------------------------------------------------------------------ street furniture
def lamp(mb, x, y, dx, dy, H=9.2, arm=2.6):
    """the renders' column: a slim dark mast, a long level arm, a flat head"""
    mb.cyl(P(x, y, 0.0), P(x, y, H), 0.09, 0.06, seg=6, caps=False)
    pbox(mb, x - 0.035 + min(0, dx * arm), y - 0.035 + min(0, dy * arm), H - 0.10,
         x + 0.035 + max(0, dx * arm), y + 0.035 + max(0, dy * arm), H - 0.02)
    hx, hy = x + dx * arm, y + dy * arm
    pbox(mb, hx - (0.45 if dx else 0.14), hy - (0.45 if dy else 0.14), H - 0.13,
         hx + (0.45 if dx else 0.14), hy + (0.45 if dy else 0.14), H - 0.02)


def fence(posts, slats, pts, H=0.62):
    """the low timber-slat fence round the corner beds (002-004): dark steel
    posts, four boards; `pts` an axis-aligned polyline"""
    for (a, b) in zip(pts, pts[1:]):
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(round(L / 1.7)))
        for k in range(n + 1):
            x = a[0] + (b[0] - a[0]) * k / n; y = a[1] + (b[1] - a[1]) * k / n
            pbox(posts, x - 0.04, y - 0.04, 0.0, x + 0.04, y + 0.04, H + 0.03)
        hx = 0.018 if abs(b[1] - a[1]) > abs(b[0] - a[0]) else 0.0
        hy = 0.018 if not hx else 0.0
        for q in range(4):
            z = 0.12 + q * 0.135
            pbox(slats, min(a[0], b[0]) - hx, min(a[1], b[1]) - hy, z,
                 max(a[0], b[0]) + hx, max(a[1], b[1]) + hy, z + 0.095)


def _tuft(mb, r, x, y, rad, hgt, n=6):
    """a low clump of pointed leaves for the beds' ground cover (plan coords)"""
    for _ in range(n):
        az = r.uniform(0, TAU); t = r.uniform(0.25, 1.2)
        s = rad * r.uniform(0.6, 1.0)
        cx, cy = x + math.cos(az) * rad * 0.3, y + math.sin(az) * rad * 0.3
        ox, oy = math.cos(az) * s * math.sin(t), math.sin(az) * s * math.sin(t)
        px, py = -math.sin(az) * s * 0.16, math.cos(az) * s * 0.16
        h = hgt * r.uniform(0.55, 1.0) * math.cos(t) + 0.04
        o = len(mb.v)
        mb.v.extend([P(cx - px, cy - py, 0.10), P(cx + px, cy + py, 0.10),
                     P(cx + ox, cy + oy, 0.10 + h)])
        lo = r.uniform(0.45, 0.62); hi = r.uniform(0.95, 1.25)
        mb.col.extend([(lo, lo, lo * 0.9)] * 2 + [(hi * 1.02, hi, hi * 0.88)])
        mb.f.append((o, o + 1, o + 2))


_BEDS = {}


def bed(soil, edge, green, r, x0, y0, x1, y1, hgt=0.55, pitch=0.40):
    """a planted bed: steel edging, soil, ground cover. The planting is a
    kit per bed size (two variants), placed as linked duplicates; `green`
    is the collection they go to."""
    pbox(soil, x0, y0, 0.0, x1, y1, 0.10)
    t = 0.03
    for (a, b, c, d) in ((x0 - t, y0 - t, x1 + t, y0), (x0 - t, y1, x1 + t, y1 + t),
                         (x0 - t, y0, x0, y1), (x1, y0, x1 + t, y1)):
        pbox(edge, a, b, 0.0, c, d, 0.16)
    w, d = round(x1 - x0, 2), round(y1 - y0, 2)
    key = (w, d, hgt, r.randrange(2))
    if key not in _BEDS:
        mb = MB()
        rr = random.Random(hash(key) & 0xffff)
        y = pitch * 0.5
        while y < d:
            x = pitch * 0.5
            while x < w:
                _tuft(mb, rr, x + rr.uniform(-.15, .15), y + rr.uniform(-.15, .15),
                      pitch * rr.uniform(0.8, 1.2), hgt * rr.uniform(0.6, 1.0))
                x += pitch
            y += pitch
        ob = mb.to_object('hoodkit_bed%d' % len(_BEDS), M('foliage_b'), collection('hoodkit'),
                          shade_smooth_all=True)
        ob.hide_render = True; ob.hide_viewport = True
        _BEDS[key] = ob
    _BEDS['n'] = _BEDS.get('n', 0) + 1
    link_dup(_BEDS[key], 'hood_bed_%d' % _BEDS['n'],
             loc=P(x0, y0, 0.0), coll=green)


def bench(wood, metal, x, y, along_x=True, L=2.0):
    a, b = (L / 2, 0.24) if along_x else (0.24, L / 2)
    for q in (-1, 0, 1):
        if along_x:
            pbox(wood, x - a, y + q * 0.16 - 0.065, 0.42, x + a, y + q * 0.16 + 0.065, 0.46)
        else:
            pbox(wood, x + q * 0.16 - 0.065, y - b, 0.42, x + q * 0.16 + 0.065, y + b, 0.46)
    for s in (-0.8, 0.8):
        if along_x:
            pbox(metal, x + s * L / 2 - 0.03, y - 0.22, 0.0, x + s * L / 2 + 0.03, y + 0.22, 0.42)
        else:
            pbox(metal, x - 0.22, y + s * L / 2 - 0.03, 0.0, x + 0.22, y + s * L / 2 + 0.03, 0.42)


# ------------------------------------------------------------------ the whole of it


def build_hood():
    coll = collection('hood')
    r = random.Random(20261125)
    XB, YB = LC.XB, LC.YB
    lawn = MB()
    xc = [(XB[i], XB[i + 1]) for i in range(0, len(XB) - 1, 2)]
    yc = [(YB[j], YB[j + 1]) for j in range(0, len(YB) - 1, 2)]
    # what the renders show on the rows that face the building
    FACING = {
        (1, 2): ('we', {'E': ('grand7', 'low5', 'tower9', 'grand7'), 'W': None}),
        (3, 2): ('we', {'W': ('six', 'low5', 'grand7')}),
        (2, 1): ('ns', {'S': ('low5', 'six', 'low5', 'tower9')}),
        (1, 1): ('ns', {'S': ('six', 'low5', 'grand7'), 'E': ('low5', 'six')}),
        (3, 1): ('ns', {'S': ('tower9', 'low5', 'six'), 'W': ('six', 'low5')}),
    }
    for i, (x0, x1) in enumerate(xc):
        for j, (y0, y1) in enumerate(yc):
            if (i, j) == (2, 2):
                continue
            a, b, c, d = x0 + PAV, y0 + PAV, x1 - PAV, y1 - PAV
            if i == 0: a = x0 + 30.0
            if i == len(xc) - 1: c = min(c, x0 + 150.0)
            if j == 0: b = y0 + 20.0
            if j == len(yc) - 1: d = min(d, y0 + 115.0)
            owner, pats = FACING.get((i, j), (r.choice(('ns', 'we')), None))
            if j == 3 and 1 <= i <= 3:
                # across the main street the renders show buildings on the
                # building line, like every other side (005, 006): the
                # cameras stand on that pavement, not in a square
                owner = 'ns'
                pats = {'N': (('grand7', 'low5', 'six', 'grand7'), ('six', 'low5', 'grand7'),
                              ('grand7', 'low5', 'six'))[i % 3]}
            build_cell(coll, 'hood_%d%d' % (i, j), a, b, c, d, r, owner, pats, lawn)

    soil = MB(); edge = MB(); green = coll; wood = MB(); metal = MB(); posts = MB(); lamps = MB()
    px0, px1 = LC.ROAD_W[1], LC.ROAD_E[0]
    # the far pavement of the main street: beds and benches between the
    # trees (001, 006: the foreground), the whole way between the corners
    x = px0 + 21.0
    while x + 8.0 < px1 - 19.0:
        bed(soil, edge, green, r, x, LC.ROAD_S[1] + 1.3, x + 8.0, LC.ROAD_S[1] + 3.4)
        bench(wood, metal, x + 10.0, LC.ROAD_S[1] + 2.4, along_x=True, L=1.8)
        x += 12.0

    # ---- corner beds with slat fences, on the eight corners that face the site
    for rx in (LC.ROAD_W, LC.ROAD_E):
        for ry in (LC.ROAD_N, LC.ROAD_S):
            for sx in (-1, 1):
                for sy in (-1, 1):
                    cx = rx[0] if sx < 0 else rx[1]
                    cy = ry[0] if sy < 0 else ry[1]
                    if (rx is LC.ROAD_W) == (sx > 0) and (ry is LC.ROAD_N) == (sy > 0):
                        continue                     # the site's own corners
                    # an L of two beds, 1.2 m in from the kerbs, clear of the crossings
                    for horiz in (True, False):
                        if horiz:
                            a0, a1 = cx + sx * 7.5, cx + sx * 15.5
                            b0, b1 = cy + sy * 1.2, cy + sy * 3.3
                        else:
                            a0, a1 = cx + sx * 1.2, cx + sx * 3.3
                            b0, b1 = cy + sy * 7.5, cy + sy * 15.5
                        X0, X1 = min(a0, a1), max(a0, a1); Y0, Y1 = min(b0, b1), max(b0, b1)
                        bed(soil, edge, green, r, X0, Y0, X1, Y1)
                        if horiz:
                            yk = cy + sy * 1.05
                            fence(posts, wood, [(X0, yk), (X1, yk)])
                        else:
                            xk = cx + sx * 1.05
                            fence(posts, wood, [(xk, Y0), (xk, Y1)])

    # ---- lamp columns down both sides of the four streets
    def clear(x, y):
        # not on the shop pavement (lib_city has its own row there) and not
        # between the page's rail and the building: an arm there catches the
        # sun into bloom in the opening sweep
        if LC.ROAD_W[1] - 2 < x < LC.ROAD_E[0] + 2 and LC.ROAD_N[1] - 2 < y < 135.0:
            return False
        return not (any(b_[0] - 9 < x < b_[1] + 9 for b_ in LC.ROADS_X)
                    and any(b_[0] - 9 < y < b_[1] + 9 for b_ in LC.ROADS_Y))
    for band in (LC.ROAD_S, LC.ROAD_N):
        x = -150.0
        while x < 215.0:
            for (y, dy) in ((band[0] - 0.9, 1), (band[1] + 0.9, -1)):
                if clear(x, y) and not any(b_[0] - 1 < x < b_[1] + 1 for b_ in LC.ROADS_X):
                    lamp(lamps, x, y, 0, dy)
            x += 30.0
    for band in (LC.ROAD_W, LC.ROAD_E):
        y = -125.0
        while y < 180.0:
            for (x, dx) in ((band[0] - 0.9, 1), (band[1] + 0.9, -1)):
                if clear(x, y) and not any(b_[0] - 1 < y < b_[1] + 1 for b_ in LC.ROADS_Y):
                    lamp(lamps, x, y, dx, 0)
            y += 30.0

    lawn.to_object('hood_lawn', M('grass'), coll)
    soil.to_object('hood_soil', M('soil'), coll)
    edge.to_object('hood_edging', M('hood_shopglass'), coll)
    posts.to_object('hood_fence_posts', M('hood_shopglass'), coll)
    wood.to_object('hood_timber', M('int_wood_oak'), coll)
    metal.to_object('hood_bench_legs', M('pole_metal'), coll)
    lamps.to_object('hood_lights', M('pole_metal'), coll)
    return coll


def build_hood_trees(light_kits, big_kits):
    """Avenues in front of the neighbours.
    `light_kits`: thin-crowned sources for the far rows (a full street tree
    is ~12 k faces; these are a fifth of that)."""
    coll = collection('trees')
    r = random.Random(4711)
    n = [0]

    def put(x, y, s, kit):
        for o in kit:
            link_dup(o, '%s_h%d' % (o.name, n[0]), loc=P(x, y, 0.0), rot_z=r.uniform(0, 6.28),
                     scale=(s, s, s * r.uniform(0.95, 1.12)), coll=coll)
        n[0] += 1

    def junction(x, y, m=11.0):
        return (any(b_[0] - m < x < b_[1] + m for b_ in LC.ROADS_X)
                and any(b_[0] - m < y < b_[1] + m for b_ in LC.ROADS_Y))
    W, E, N, S = LC.ROAD_W, LC.ROAD_E, LC.ROAD_N, LC.ROAD_S
    # the neighbours' side of each street, the whole first ring
    rows = [(True, N[0] - 2.4, -118.0, 176.0), (True, S[1] + 2.4, -118.0, 176.0),
            (False, W[0] - 2.4, -104.0, 70.0), (False, E[1] + 2.4, -104.0, 70.0),
            # our side of the west and north streets, sparser (003, 004)
            (False, W[1] + 2.4, -20.0, 50.0), (True, N[1] + 2.4, -26.0, 86.0)]
    for q, (horiz, c, a, b) in enumerate(rows):
        s = a + r.uniform(0, 4)
        while s < b:
            x, y = (s, c) if horiz else (c, s)
            ok = not junction(x, y)
            if horiz and c > S[1] and W[1] - 6 < x < E[0] + 2:
                # the main street's far pavement: lib_city plants its ends;
                # the middle stays low, the page's rail flies over it
                ok = False
            if any(b_[0] - 1 < (x if horiz else y) < b_[1] + 1 for b_ in (LC.ROADS_X if horiz else LC.ROADS_Y)):
                ok = False
            if ok:
                put(x + (r.uniform(-.3, .3) if not horiz else 0), y + (r.uniform(-.3, .3) if horiz else 0),
                    r.uniform(1.25, 1.65), light_kits[n[0] % len(light_kits)])
            s += r.uniform(13.0, 16.0) if q < 4 else r.uniform(17.0, 22.0)
    return coll
