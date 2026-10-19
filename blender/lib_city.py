# -*- coding: utf-8 -*-
"""Podium, street, background blocks, planting and traffic.
Everything is authored in block A's local frame:
    +x  runs along the street (north-east), 0 at the west gable
    -y  points toward the camera / the roadway
     z  is up, 0 = pavement
"""
import bpy, math, random
from mathutils import Vector
from lib_build import (MB, srgb, link_dup, frame_for, frame_for_yz, collection,
                       rnd, TAU)
import lib_building as LB

M = LB.M
GROUND_H = LB.GROUND_H

# ------------------------------------------------------------------ geometry
STREET_Y   = LB.B_Y0     # the wing's street face: the building line at the east end
WALK_EDGE  = -21.40      # far kerb
PARK_EDGE  = -24.00      # edge of the parking lane
NEAR_KERB  = -50.30      # near kerb, right in front of the camera
PARK_TOP   = 4.65        # terrace floor == first residential floor level
PARAPET_TOP = 5.90       # top of the fascia band (Z 5.9 in the photograph)
FASCIA_Z   = 4.20        # shopfront glazing head; one plain band from here up
FASCIA_D   = 0.29        # fascia / parapet thickness
POD_PT     = 0.40        # pier depth / glazing recess

# The podium front in plan, from the stub beside the gable round to the wing
# corner, back-projected from the fascia top in the photograph at Z = 5.9.
# A west face in the gable plane (the near-horizontal fascia in the picture),
# a short solid chamfer at the corner, then one straight face to the wing.
POD_FRONT = [(-0.30, 1.60), (-0.30, -13.50), (0.00, -16.80), (LB.B_X0, LB.B_Y0)]


def _seg_frames():
    """(origin, t, n, length) per segment of POD_FRONT; n points INTO the podium."""
    out = []
    for i in range(len(POD_FRONT) - 1):
        ax, ay = POD_FRONT[i]
        bx, by = POD_FRONT[i + 1]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        t = (dx / L, dy / L)
        out.append(((ax, ay), t, (-t[1], t[0]), L))
    return out


def front_pt(seg, s, d, z):
    """Point `s` along a front segment, `d` into the building, `z` up."""
    (ax, ay), t, n, L = seg
    return (ax + t[0] * s + n[0] * d, ay + t[1] * s + n[1] * d, z)


def seg_box(mb, seg, s0, s1, d0, d1, z0, z1):
    """Box in a segment's frame (s along the face, d into the podium)."""
    v = [front_pt(seg, s0, d0, z0), front_pt(seg, s1, d0, z0),
         front_pt(seg, s1, d1, z0), front_pt(seg, s0, d1, z0),
         front_pt(seg, s0, d0, z1), front_pt(seg, s1, d0, z1),
         front_pt(seg, s1, d1, z1), front_pt(seg, s0, d1, z1)]
    mb.add(v, [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6),
               (3, 0, 4, 7), (1, 2, 6, 5)])


def offset_front(d):
    """POD_FRONT moved `d` into the podium, corners mitred."""
    segs = _seg_frames()
    pts = [front_pt(segs[0], 0.0, d, 0.0)[:2]]
    for i in range(len(segs) - 1):
        (ax, ay), t1, n1, L1 = segs[i]
        (bx, by), t2, n2, L2 = segs[i + 1]
        p1 = (ax + n1[0] * d, ay + n1[1] * d)
        p2 = (bx + n2[0] * d, by + n2[1] * d)
        den = t1[0] * t2[1] - t1[1] * t2[0]
        if abs(den) < 1e-9:
            pts.append(p2)
        else:
            k = ((p2[0] - p1[0]) * t2[1] - (p2[1] - p1[1]) * t2[0]) / den
            pts.append((p1[0] + t1[0] * k, p1[1] + t1[1] * k))
    last = segs[-1]
    pts.append(front_pt(last, last[3], d, 0.0)[:2])
    return pts


def prism(mb, pts, z0, z1):
    """Vertical prism over a polygon given counter-clockwise in plan."""
    n = len(pts)
    o = len(mb.v)
    mb.v.extend([(x, y, z0) for (x, y) in pts])
    mb.v.extend([(x, y, z1) for (x, y) in pts])
    mb.f.append(tuple(o + n - 1 - k for k in range(n)))          # bottom
    mb.f.append(tuple(o + n + k for k in range(n)))              # top
    for k in range(n):
        j = (k + 1) % n
        mb.f.append((o + k, o + j, o + n + j, o + n + k))


def front_bays(seg, s_start, target):
    """Shopfront bays along one segment: (a, b) pairs in s."""
    (ax, ay), t, n, L = seg
    span = L - s_start
    nb = max(1, int(round(span / target)))
    w = span / nb
    return [(s_start + k * w, s_start + (k + 1) * w) for k in range(nb)]


# ------------------------------------------------------------------ podium
def build_podium():
    """Retail podium: shopfront storey under a plain fascia band, the terrace
    slab on top, built face by face along POD_FRONT."""
    coll = collection('podium')
    segs = _seg_frames()
    c = MB(); fas = MB(); g = MB(); ins = MB(); mull = MB()
    PIER = 0.50
    SILL = 0.55
    for i, seg in enumerate(segs):
        (ax, ay), t, n, L = seg
        if i == 1:                               # the chamfer is solid wall
            seg_box(c, seg, 0.0, L, 0.0, POD_PT, 0.0, FASCIA_Z)
            continue
        s_start = 1.00 if i == 0 else 0.0       # the stub beside the gable is solid
        target = 4.70 if i == 0 else 5.60
        bays = front_bays(seg, s_start, target)
        if s_start > 0:
            seg_box(c, seg, 0.0, s_start, 0.0, POD_PT, 0.0, FASCIA_Z)
        for (a, b) in bays:
            seg_box(c, seg, a, a + PIER, 0.0, POD_PT, 0.0, FASCIA_Z)        # pier
            seg_box(c, seg, a + PIER, b - PIER, 0.0, POD_PT, 0.0, SILL)    # sill / plinth
            seg_box(g, seg, a + PIER + 0.04, b - PIER - 0.04, POD_PT - 0.04, POD_PT - 0.01,
                    SILL + 0.03, FASCIA_Z - 0.03)                            # glass
            seg_box(ins, seg, a + PIER + 0.04, b - PIER - 0.04, POD_PT + 2.60, POD_PT + 2.65,
                    0.20, FASCIA_Z - 0.10)                                   # lit interior
            for q in (0.0, 0.33, 0.66, 1.0):
                x = a + PIER + 0.04 + (b - a - 2 * PIER - 0.08) * q
                seg_box(mull, seg, x - 0.035, x + 0.035, POD_PT - 0.09, POD_PT + 0.01,
                        SILL + 0.03, FASCIA_Z - 0.03)
            for zz in (SILL + 0.03, 2.72, FASCIA_Z - 0.11):
                seg_box(mull, seg, a + PIER + 0.04, b - PIER - 0.04, POD_PT - 0.09, POD_PT + 0.01,
                        zz, zz + 0.08)
        seg_box(c, seg, L - PIER, L, 0.0, POD_PT, 0.0, FASCIA_Z)            # end pier
    # the fascia band and parapet: one plane from the glazing head to the top,
    # mitred at the corners so nothing overlaps
    o0 = offset_front(0.0); o1 = offset_front(FASCIA_D)
    for i in range(len(o0) - 1):
        prism(fas, [o0[i], o0[i + 1], o1[i + 1], o1[i]], FASCIA_Z, PARAPET_TOP)
    # terrace slab, set 2 cm inside the parapet and 2 cm clear of the gable
    # and the wing, so it shares no plane with either
    sl = offset_front(FASCIA_D + 0.02)
    sl[-1] = (LB.B_X0 + 0.50, sl[-1][1])
    sl += [(LB.B_X0 + 0.50, 2.50), (0.02, 2.50), (0.02, 1.60)]
    prism(c, sl, PARK_TOP - 0.35, PARK_TOP)
    # the closed body behind the shops, so nothing can be seen through
    fill = offset_front(3.10)
    fill[-1] = (LB.B_X0 + 0.50, fill[-1][1])
    fill += [(LB.B_X0 + 0.50, 2.50), (0.02, 2.50), (0.02, 1.60)]
    fill[0] = (fill[0][0], 1.60)
    prism(c, fill, 0.0, PARK_TOP - 0.36)
    c.to_object('podium_shell', M('concrete_podium'), coll)
    fas.to_object('podium_fascia', M('concrete_podium'), coll)
    g.to_object('podium_glass', M('glass_shop'), coll)
    ins.to_object('podium_interior', M('shop_interior'), coll)
    mull.to_object('podium_mullions', M('frame_bronze'), coll)
    return coll


# terrace furniture, measured off the photograph (local metres)
# (x, y, petal radius, extra pole height): five butterfly parasols, the third
# one the big one in the picture
PARASOLS = [(2.60, -3.60, 1.60, 0.0), (3.50, -7.90, 1.60, 0.0),
            (5.40, -13.30, 2.00, 0.45), (13.40, -15.80, 1.60, 0.0),
            (19.60, -15.70, 1.60, 0.0)]
PARASOL_H = PARK_TOP + 2.85        # pole top 7.5 m
SAILS = [((4.6, -4.4), (7.6, -4.8), (6.1, -7.4)),
         ((8.2, -9.6), (11.4, -10.4), (9.4, -12.8)),
         ((11.6, -14.8), (14.8, -15.3), (12.8, -18.0))]
PERGOLA = (5.20, -11.30)           # centre of a small 3.5 x 3.0 m trellis


def build_terrace():
    """Roof terrace over the podium: four butterfly parasols along the near
    faces, three shade sails, a small trellis, a hedge of clipped shrubs and
    a rail along the parapet, one planter for the tree."""
    coll = collection('terrace')
    sail = MB(); poles = MB(); plant = MB(); foli = MB(); rail = MB()
    for (x, y, R, hx) in PARASOLS:
        h = PARASOL_H + hx
        poles.cyl((x, y, PARK_TOP), (x, y, h), 0.05, seg=8)
        for k in range(4):
            a = math.pi / 2 * k + math.pi / 4
            dx, dy = math.cos(a) * R, math.sin(a) * R
            px, py = math.cos(a + 0.9) * R * 0.69, math.sin(a + 0.9) * R * 0.69
            qx, qy = math.cos(a - 0.9) * R * 0.69, math.sin(a - 0.9) * R * 0.69
            sail.add([(x, y, h - 0.12), (x + px, y + py, h + 0.25),
                      (x + dx, y + dy, h - 0.90), (x + qx, y + qy, h + 0.25)],
                     [(0, 1, 2, 3)])
    for tri in SAILS:
        zs = (PARK_TOP + 2.55, PARK_TOP + 2.25, PARK_TOP + 2.75)
        pts = [(p[0], p[1], z) for p, z in zip(tri, zs)]
        sail.add(pts, [(0, 1, 2)])
        sail.add(pts, [(0, 2, 1)])
        for (p, z) in zip(tri, zs):
            poles.cyl((p[0], p[1], PARK_TOP), (p[0], p[1], z), 0.035, seg=6)
    # trellis
    px, py = PERGOLA
    for (dx, dy) in ((-1.7, -1.4), (1.7, -1.4), (-1.7, 1.4), (1.7, 1.4)):
        poles.box((px + dx - 0.05, py + dy - 0.05, PARK_TOP),
                  (px + dx + 0.05, py + dy + 0.05, PARK_TOP + 2.35))
    for k in range(6):
        yy = py - 1.4 + k * 0.56
        poles.box((px - 1.75, yy - 0.04, PARK_TOP + 2.25), (px + 1.75, yy + 0.04, PARK_TOP + 2.35))
    # hedge: clipped shrubs every 3 m just inside the parapet, their tops
    # 0.75 m above it, out of a planter trough that the parapet hides
    segs = _seg_frames()
    for i, seg in enumerate(segs):
        (ax, ay), t, n, L = seg
        s0 = 1.6 if i == 0 else 0.0
        seg_box(plant, seg, s0, L, FASCIA_D + 0.03, FASCIA_D + 1.10, PARK_TOP, PARK_TOP + 0.85)
        s = s0 + 1.5
        while s < L - 0.8:
            cx, cy, _ = front_pt(seg, s, FASCIA_D + 0.56, 0.0)
            cz = PARAPET_TOP + 0.05
            for k in range(140):
                a_ = rnd.uniform(0, TAU); b_ = rnd.uniform(0, math.pi)
                rr = 0.45 * rnd.uniform(0.75, 1.0)
                out = (math.sin(b_) * math.cos(a_), math.sin(b_) * math.sin(a_), math.cos(b_))
                p = (cx + out[0] * rr, cy + out[1] * rr, cz + out[2] * rr)
                vd = _tilt(out, rnd.uniform(0.5, 1.5), rnd.uniform(0, TAU))
                shade = 0.72 + 0.5 * rnd.uniform(0.0, 1.0)
                leaf_blade(foli, p, vd, out, rnd.uniform(0.05, 0.08), rnd,
                           0, (shade * 1.02, shade, shade * 0.94))
            s += 6.0
        # a thin rail along the parapet
        seg_box(rail, seg, s0, L, 0.12, 0.16, PARAPET_TOP + 0.31, PARAPET_TOP + 0.35)
        s = s0 + 1.0
        while s < L:
            seg_box(rail, seg, s - 0.02, s + 0.02, 0.12, 0.16, PARAPET_TOP, PARAPET_TOP + 0.31)
            s += 2.0
    for (x, y) in terrace_planters():
        plant.box((x - 0.9, y - 0.9, PARK_TOP), (x + 0.9, y + 0.9, PARK_TOP + 0.35))
    sail.to_object('terrace_sails', M('canopy_fabric'), coll)
    poles.to_object('terrace_frames', M('pole_metal'), coll)
    plant.to_object('terrace_planters', M('concrete_podium'), coll)
    rail.to_object('terrace_rail', M('metal_dark'), coll)
    foli.to_object('terrace_foliage', M('foliage_b'), coll, shade_smooth_all=True)
    return coll


def build_signage():
    """Shop signs on the fascia: PUBLIC MARKET in neon and Sonny's in metal,
    where the photograph has them - the west face, the start of the long
    face, its middle and its east end."""
    coll = collection('signage')
    import bpy
    segs = _seg_frames()

    def text_obj(body, seg, s, z, size, matname, extrude=0.035, track=1.0):
        (ax, ay), t, n, L = seg
        x, y, _ = front_pt(seg, s, -0.02, 0.0)
        cu = bpy.data.curves.new('t', type='FONT')
        cu.body = body
        cu.size = size
        cu.extrude = extrude
        cu.space_character = track
        cu.align_x = 'CENTER'
        ob = bpy.data.objects.new('sign_' + body[:9], cu)
        ob.location = (x, y, z)
        ob.rotation_euler = (math.pi / 2, 0, math.atan2(-n[0], n[1]))
        ob.data.materials.append(M(matname))
        coll.objects.link(ob)
        return ob
    # letter heights and tracking read off the photograph: the neon is two
    # lines of 0.5 m letters set wide, the script logo about 1.2 m tall
    text_obj('PUBLIC', segs[0], 3.6, 5.50, 0.65, 'neon_orange', track=1.55)
    text_obj('MARKET', segs[0], 3.6, 4.75, 0.65, 'neon_orange', track=1.55)
    text_obj("Sonny's", segs[0], 13.9, 4.90, 1.35, 'sign_metal', 0.06)
    text_obj('PUBLIC', segs[2], 14.0, 5.45, 0.60, 'neon_orange', track=1.55)
    text_obj('MARKET', segs[2], 14.0, 4.80, 0.60, 'neon_orange', track=1.55)
    text_obj("Sonny's", segs[2], 36.0, 4.95, 1.10, 'sign_metal', 0.05)
    text_obj('PUBLIC', segs[2], 49.4, 5.45, 0.44, 'neon_orange', track=1.55)
    text_obj('MARKET', segs[2], 49.4, 4.80, 0.44, 'neon_orange', track=1.55)
    return coll


# ------------------------------------------------------------------ street
def build_street():
    coll = collection('street')
    X0, X1 = -170.0, 190.0
    road = MB(); walk = MB(); kerb = MB(); paint = MB(); grass = MB()
    road.plane_xy(X0, NEAR_KERB, X1, PARK_EDGE, 0.0)
    walk.box((X0, STREET_Y - 0.001, 0.0), (X1, WALK_EDGE, 0.14))
    kerb.box((X0, WALK_EDGE - 0.16, 0.0), (X1, WALK_EDGE, 0.16))
    walk.box((X0, NEAR_KERB, 0.0), (X1, NEAR_KERB - 9.0, 0.15))
    kerb.box((X0, NEAR_KERB, 0.0), (X1, NEAR_KERB + 0.16, 0.16))
    grass.plane_xy(X0, NEAR_KERB - 9.0, X1, NEAR_KERB - 26.0, 0.10)
    road.plane_xy(X0, PARK_EDGE, X1, WALK_EDGE, 0.0)           # parking bay
    # lane markings
    for i in range(1, 8):
        y = PARK_EDGE - i * 3.68
        if y < NEAR_KERB + 2:
            break
        x = X0
        while x < X1:
            paint.box((x, y - 0.075, 0.004), (x + 3.0, y + 0.075, 0.006))
            x += 9.0
    paint.box((X0, PARK_EDGE - 0.12, 0.004), (X1, PARK_EDGE + 0.02, 0.006))
    # Zebra crossing. The camera sits at local (-49.8, -50.8) looking down the
    # street, so x -66..-47 - where this used to be - is behind it and never
    # appeared at all. x -50..-38 is the stretch that lands in the bottom-left
    # of frame, where the photograph puts it. The bars are wide (1.2 m on a
    # 2.4 m pitch): seen this close to edge-on, narrow bars compress into thin
    # lines that the chromatic aberration then fringes into scratches.
    # Back-projecting the crossing in the photograph onto the road plane puts
    # it at local x -47..-32, y -41.5..-26.5. The y extent is the part that
    # matters: running the bars the full 26 m of carriageway, as before, makes
    # each one a 26 m stripe that sweeps diagonally across the whole frame
    # instead of reading as a crossing.
    x = -47.0
    while x < -32.0:
        paint.box((x, -41.5, 0.004), (x + 1.20, -26.5, 0.006))
        x += 2.40
    road.to_object('road', M('asphalt'), coll)
    walk.to_object('pavement', M('sidewalk'), coll)
    kerb.to_object('kerb', M('curb'), coll)
    paint.to_object('road_markings', M('road_paint'), coll)
    grass.to_object('verge', M('grass'), coll)

    # kerbside railing on the near pavement
    rail = MB()
    for k in range(26):
        x = -78 + k * 2.4
        rail.box((x, NEAR_KERB - 1.5, 0.15), (x + 0.07, NEAR_KERB - 1.43, 1.05))
        rail.box((x, NEAR_KERB - 1.5, 0.95), (x + 2.4, NEAR_KERB - 1.43, 1.05))
    rail.to_object('kerb_railing', M('metal_dark'), coll)

    # street lighting columns
    pole = MB()
    for x in (-34.0, -4.0, 26.0, 56.0):
        pole.cyl((x, WALK_EDGE - 0.8, 0.0), (x, WALK_EDGE - 0.8, 8.6), 0.10, 0.07, seg=8)
        pole.cyl((x, WALK_EDGE - 0.8, 8.6), (x, WALK_EDGE - 3.6, 8.9), 0.07, 0.06, seg=8)
        pole.box((x - 0.22, WALK_EDGE - 4.3, 8.72), (x + 0.22, WALK_EDGE - 3.5, 8.90))
    pole.to_object('street_lights', M('pole_metal'), coll)
    return coll


# ------------------------------------------------------------------ planting
def terrace_planters():
    """The one slim tree the photograph shows standing on the terrace."""
    return [(9.30, -14.80)]


GOLDEN = math.radians(137.507)      # the divergence angle of a leaf spiral


def _nrm(v):
    L = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / L, v[1] / L, v[2] / L) if L > 1e-9 else (0.0, 0.0, 1.0)


def _crs(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _frame(d):
    """Any two unit vectors perpendicular to d."""
    up = (0.0, 0.0, 1.0) if abs(d[2]) < 0.95 else (1.0, 0.0, 0.0)
    t1 = _nrm(_crs(d, up))
    return t1, _crs(d, t1)


def _tilt(d, ang, az):
    """d rotated away from itself by `ang`, in the direction `az` around it."""
    t1, t2 = _frame(d)
    c, s = math.cos(ang), math.sin(ang)
    ca, sa = math.cos(az), math.sin(az)
    off = (t1[0] * ca + t2[0] * sa, t1[1] * ca + t2[1] * sa, t1[2] * ca + t2[2] * sa)
    return _nrm((d[0] * c + off[0] * s, d[1] * c + off[1] * s, d[2] * c + off[2] * s))


def _perp(want, axis):
    """`want` with its component along `axis` removed - the blade normal has to
    be perpendicular to the blade, but we want it as close to the light as the
    blade's own direction allows."""
    k = _dot(want, axis)
    o = (want[0] - axis[0] * k, want[1] - axis[1] * k, want[2] - axis[2] * k)
    return _nrm(o) if (o[0] * o[0] + o[1] * o[1] + o[2] * o[2]) > 1e-8 else _frame(axis)[0]


def leaf_blade(mb, base, vdir, ndir, s, r, detail=0, tint=None):
    """One leaf, attached at `base`, running along `vdir`, blade facing `ndir`.

    A flat quad reads as a green chip. What makes foliage read as leaves is the
    pointed tip, the shoulder about a third of the way up, and the fold along
    the midrib that leaves the two halves at different angles, so one side
    catches the sun while the other stays in shade. All three come for the
    price of the rectangle they replace: four verts whose quad is deliberately
    NON-PLANAR, so triangulating it along the base-to-tip diagonal puts the
    crease exactly on the midrib. detail=1 adds a second pair of shoulders and
    a petiole, for the leaves near enough to read an outline.

    Proportions are off the foreground branch in the photograph: a broad lime
    leaf about four fifths as wide as it is long, blunt rather than spiky. The
    blade is attached at its base and droops under its own weight toward world
    -Z, which is what makes a canopy hang rather than bristle.
    """
    L = s * 2.90                       # petiole base to tip
    W = s * 1.16                       # half width at the widest point
    fold = s * 0.30                    # depth of the midrib crease
    droop = s * 0.80                   # gravity sag at the tip
    t0 = 0.26 if detail else 0.16      # blade starts here; before it, petiole
    v = _nrm(vdir)
    n = _perp(ndir, v)
    u = _crs(v, n)

    def P(du, t, fd):
        d = L * t
        g = -droop * max(0.0, (t - t0) / (1.0 - t0)) ** 2
        return (base[0] + u[0] * du + v[0] * d + n[0] * fd,
                base[1] + u[1] * du + v[1] * d + n[1] * fd,
                base[2] + u[2] * du + v[2] * d + n[2] * fd + g)

    o = len(mb.v)
    if detail:
        pw = s * 0.055                 # petiole half width
        mb.v.extend([P(-pw, 0.0, 0.0), P(pw, 0.0, 0.0),            # 0 1 stalk
                     P(0, t0, 0.0),                                 # 2 blade base
                     P(-W, t0 + 0.30, -fold), P(W, t0 + 0.30, -fold),
                     P(0, t0 + 0.30, 0.0),                          # 5 midrib
                     P(-W * 0.84, t0 + 0.62, -fold * 0.84),
                     P(W * 0.84, t0 + 0.62, -fold * 0.84),
                     P(0, t0 + 0.62, 0.0),                          # 8 midrib
                     P(0, 1.0, 0.0)])                               # 9 tip
        # wound so the geometric front face is the side turned to the light;
        # the material keys the pale matt underside off that
        for f in ((2, 1, 0),
                  (5, 3, 2), (5, 8, 6, 3), (8, 9, 6),
                  (4, 5, 2), (4, 7, 8, 5), (7, 9, 8)):
            mb.f.append(tuple(o + k for k in f))
    else:
        # base - shoulder - tip - shoulder, creasing along the base/tip diagonal
        mb.v.extend([P(0, t0, 0.0), P(-W, t0 + 0.40, -fold),
                     P(0, 1.0, 0.0), P(W, t0 + 0.40, -fold)])
        mb.f.append((o, o + 3, o + 2, o + 1))
    if tint is None:
        tint = (1.0, 1.0, 1.0)
    mb.col.extend([tint] * (len(mb.v) - o))


def leaf_shoot(mb, p0, dirv, length, n_leaf, size, r, detail, light, tintf):
    """A terminal shoot: leaves set along a twig on a golden-angle spiral.

    This is the part that decides whether a canopy reads as a tree or as green
    fog. Leaves do not float in a cloud around a branch - they sit on shoots,
    in a spiral, at a regular spacing, and they turn their blades to the sky.
    Scattering them through a sphere gives an even density with no structure;
    running them along shoots gives the clumps and the gaps between clumps that
    a real crown is made of.
    """
    phase = r.uniform(0, TAU)
    for i in range(n_leaf):
        t = (i + 0.55) / n_leaf
        att = (p0[0] + dirv[0] * length * t,
               p0[1] + dirv[1] * length * t,
               p0[2] + dirv[2] * length * t)
        az = phase + i * GOLDEN
        # the blade swings out from the shoot, a little more at the base
        out = r.uniform(1.00, 1.38) - 0.22 * t
        vd = _tilt(dirv, out, az)
        # light seeking: present the blade to the sky, as far as its own
        # direction allows, with a little randomness so they are not a deck
        want = (light[0] + r.uniform(-0.35, 0.35),
                light[1] + r.uniform(-0.35, 0.35),
                light[2] + r.uniform(-0.15, 0.25))
        nd = _perp(want, vd)
        leaf_blade(mb, att, vd, nd, size * r.uniform(0.80, 1.18), r,
                   detail, tintf(att))


def leaf_tinter(z0, z1, cx, cy, crad, r, kd=0.62):
    """Per-leaf light, baked into the mesh as a vertex colour.

    This is the only self-shadowing the canopy ever gets. The shadow map
    covers a 420 m frustum, so one texel lands on 10 cm: a leaf casts about
    four of them and the inside of a crown comes back as bright as its
    skin. That one fact is what makes rendered foliage read as a heap of
    green chips rather than as a tree - a real crown runs five to one
    between the leaves in the sun and the leaves two layers in, and it is
    that range, not the green, that the eye reads as mass.

    So the tint is not a gradient picked to look right, it is an optical
    depth. The crown is taken as the ellipsoid its tips describe, the leaf
    is traced out of it toward the sun and again toward the zenith, and
    each ray is attenuated by the leaf area it has to pass: exp( -kd * d ),
    with d in metres. Sun leaves come out lighter, yellower and slightly
    scorched; the ones in the core go dark and blue, because all they ever
    see is sky through foliage.
    """
    zc = 0.5 * (z0 + z1)
    zr = max(0.5 * (z1 - z0), 0.35)
    cr = max(crad, 0.35)
    rm = (2.0 * cr + zr) / 3.0                 # mean radius, for metres
    # Blender Z-up, matching `light` in the generators: up, leaning into sun
    sun_d = _nrm((0.30, -0.18, 1.0))
    sun_e = (sun_d[0] / cr, sun_d[1] / cr, sun_d[2] / zr)
    sky_e = (0.0, 0.0, 1.0 / zr)

    def _exit(e, d):
        """How far out of the unit sphere `e` is, along `d`."""
        a = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
        b = 2.0 * (e[0] * d[0] + e[1] * d[1] + e[2] * d[2])
        c = e[0] * e[0] + e[1] * e[1] + e[2] * e[2] - 1.0
        disc = b * b - 4.0 * a * c
        if disc <= 0.0 or a <= 0.0:
            return 0.0
        return max(0.0, (-b + math.sqrt(disc)) / (2.0 * a))

    def f(p):
        e = ((p[0] - cx) / cr, (p[1] - cy) / cr, (p[2] - zc) / zr)
        # metres of crown between this leaf and the sun, and the zenith
        d_sun = _exit(e, sun_e) * rm
        d_sky = _exit(e, sky_e) * rm
        expo = (0.58 * math.exp(-kd * d_sun)
                + 0.42 * math.exp(-kd * 0.80 * d_sky))
        val = (0.34 + 1.00 * expo) * r.uniform(0.86, 1.14)
        return (val * (0.88 + 0.30 * expo),      # sun leaves run yellow
                val,
                val * (1.08 - 0.32 * expo))      # shade leaves run blue
    return f


def make_tree_kit(coll, seed=1, levels=4, n_leaf=13000, lmin=0.072, lmax=0.117,
                  H=9.4, blob=1.45, lift=0.17, spread=2.1, r0=0.30,
                  leaf_detail=0):
    """One source tree, grown rather than scattered.

    Three things do most of the work, and all three are standard practice for
    believable trees:

    * apical dominance - a branch does not fork into equals, it carries on as
      a leader and sheds thinner laterals. Forking into equals is what gives
      procedural trees that tell-tale broccoli look.
    * the pipe model (da Vinci's rule) - the cross-section of a limb equals
      the sum of its children's, so a child's radius is the parent's times its
      share to the power 1/2.49. Taper falls out of it instead of being a
      fudge factor.
    * gravitropism - thin shoots turn back toward the sky, so the crown ends
      in upswept tips rather than straight spokes.

    The leaves then go on shoots in a golden-angle spiral (see leaf_shoot),
    not in a cloud, and carry a baked per-leaf tint (see leaf_tinter).
    """
    r = random.Random(seed)
    trunk = MB(); leaves = MB()

    # ---- trunk: a slight sweep, tapering by the pipe model
    th = r.uniform(0, TAU)
    lean = r.uniform(0.010, 0.030)
    top = H * 0.36
    p = (0.0, 0.0, 0.0)
    rad = r0 * 1.15
    for i in range(4):
        t1 = (i + 1) / 4.0
        q = (math.cos(th) * lean * (top * t1) ** 1.5,
             math.sin(th) * lean * (top * t1) ** 1.5,
             top * t1)
        rq = r0 * 1.15 * (1.0 - 0.40 * t1)
        trunk.cyl(p, q, rad, rq, seg=10)
        p, rad = q, rq

    # ---- crown: leader + laterals, pipe-model taper, gravitropic tips
    tips = []
    twigs = []
    stack = [(p, (0.0, 0.0, 1.0), rad, 0)]
    while stack:
        pos, dr, rr, d = stack.pop()
        if d >= levels:
            tips.append((pos, dr))
            continue
        n_lat = 2 if d < 2 else r.choice((1, 1, 2))
        lead = 0.60 if d < 2 else 0.55
        shares = [lead] + [(1.0 - lead) / n_lat] * n_lat
        base_az = r.uniform(0, TAU)
        seg = spread * (0.74 ** d) * r.uniform(0.80, 1.22)
        for j, sh in enumerate(shares):
            rc = rr * sh ** (1.0 / 2.49)            # pipe model
            if j == 0:
                ang = r.uniform(0.10, 0.26)
                az = base_az + r.uniform(-0.5, 0.5)
                ln = seg * r.uniform(0.95, 1.15)
            else:
                ang = r.uniform(0.62, 1.00)
                az = base_az + GOLDEN * j + r.uniform(-0.35, 0.35)
                ln = seg * r.uniform(0.62, 0.90)
            nd = _tilt(dr, ang, az)
            # gravitropism, stronger the thinner the limb
            g = min(0.55, 0.16 + 0.40 * (1.0 - rc / max(r0, 1e-6)))
            mid = _nrm((nd[0], nd[1], nd[2] + g * 0.5))
            end = _nrm((nd[0], nd[1], nd[2] + g))
            m = (pos[0] + mid[0] * ln * 0.5,
                 pos[1] + mid[1] * ln * 0.5,
                 pos[2] + mid[2] * ln * 0.5 + H * lift * 0.10)
            q = (m[0] + end[0] * ln * 0.5,
                 m[1] + end[1] * ln * 0.5,
                 m[2] + end[2] * ln * 0.5 + H * lift * 0.10)
            sg = 6 if d < 2 else 5
            trunk.cyl(pos, m, rc, rc * 0.84, seg=sg)
            trunk.cyl(m, q, rc * 0.84, rc * 0.62, seg=sg)
            if d >= levels - 3:
                w = 1.0 if d == levels - 1 else (0.55 if d == levels - 2 else 0.3)
                twigs.append((pos, q, w))
            stack.append((q, end, rc * 0.62, d + 1))

    # ---- shoots and leaves
    if not tips:
        tips = [(p, (0.0, 0.0, 1.0))]
    zs = [t[0][2] for t in tips]
    xs = [t[0][0] for t in tips]
    ys = [t[0][1] for t in tips]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    crad = max(0.4, max(math.hypot(x - cx, y - cy) for x, y in zip(xs, ys)))
    tintf = leaf_tinter(min(zs), max(zs), cx, cy, crad, r)
    light = _nrm((0.30, -0.18, 1.0))        # up, leaning into the sun
    size = (lmin + lmax) * 0.5
    # n_leaf is a whole-tree budget: the branch generator makes a different
    # number of twigs than the old recursion did, so sharing it out by weight
    # keeps the canopy density independent of how the branching came out
    wsum = sum(w for _, _, w in twigs) or 1.0
    # Leaves come in rosettes, not in a mist. Scattering them one at a time
    # through the blob around a twig gives an even density, and an even
    # density is exactly what makes a canopy read as green fog: there is
    # nothing for the eye to resolve as a clump, and so no gap between
    # clumps either, which is where a real crown shows its depth and lets
    # the sky through. Grouping the same budget into shoots of ~CLUMP costs
    # nothing and buys both.
    CLUMP = 9
    for (pa_, pb_, wgt) in twigs:
        n_here = int(round(n_leaf * wgt / wsum))
        n_cl = max(1, int(round(n_here / float(CLUMP))))
        for ci in range(n_cl):
            f = r.uniform(-0.05, 1.12)
            bx = pa_[0] + (pb_[0] - pa_[0]) * f
            by = pa_[1] + (pb_[1] - pa_[1]) * f
            bz = pa_[2] + (pb_[2] - pa_[2]) * f
            a_ = r.uniform(0, TAU); b_ = r.uniform(0, math.pi)
            rr = blob * r.uniform(0.02, 1.0) ** 0.42
            c0 = (bx + math.sin(b_) * math.cos(a_) * rr,
                  by + math.sin(b_) * math.sin(a_) * rr,
                  bz + math.cos(b_) * rr * 0.78 + blob * 0.12)
            # the rosette runs along its own little shoot, and every leaf on
            # it shares that direction, which is what makes a clump a clump
            sa_ = r.uniform(0, TAU); sb_ = r.uniform(0.25, 1.35)
            shoot = (math.sin(sb_) * math.cos(sa_),
                     math.sin(sb_) * math.sin(sa_), math.cos(sb_) * 0.7)
            reach = blob * r.uniform(0.17, 0.30)
            # where a leaf sits in its own rosette, -1 at the bottom, +1 at
            # the top: the clump-scale contrast the crown-wide gradient is
            # far too slow to give
            dzc = lambda q, _z=c0[2], _r=reach: (q[2] - _z) / max(_r, 1e-3)
            k_here = n_here // n_cl + (1 if ci < n_here % n_cl else 0)
            for j in range(k_here):
                t = (j + r.uniform(0.0, 0.9)) / max(k_here, 1)
                sp_ = reach * (0.25 + 0.95 * t)
                c = (c0[0] + shoot[0] * sp_ + r.uniform(-1, 1) * reach * 0.34,
                     c0[1] + shoot[1] * sp_ + r.uniform(-1, 1) * reach * 0.34,
                     c0[2] + shoot[2] * sp_ + r.uniform(-1, 1) * reach * 0.28)
                sz = r.uniform(lmin, lmax) * (1.0 - 0.22 * t)
                # pitch biased down: in the photograph the leaves hang
                ya = r.uniform(0, TAU); pa = r.uniform(-1.30, 0.45)
                ca, sa = math.cos(ya), math.sin(ya)
                cp, sp = math.cos(pa), math.sin(pa)
                vd = (-sa * cp, ca * cp, sp)
                nd = (sa * sp, -ca * sp, cp)
                base = (c[0] - vd[0] * sz * 1.22,
                        c[1] - vd[1] * sz * 1.22,
                        c[2] - vd[2] * sz * 1.22)
                # the rosette shades itself: the leaves at the tip of the
                # shoot stand over the ones at its base. This is the contrast
                # the eye actually resolves in a canopy - the crown-wide
                # gradient is too slow to read as anything but a tint - and
                # it is centred on 1.0, so the canopy's mean does not move.
                sh = min(1.26, max(0.66, 0.96 + 0.34 * dzc(c)))
                tc = tintf(c)
                leaf_blade(leaves, base, vd, nd, sz, r, leaf_detail,
                           (tc[0] * sh, tc[1] * sh, tc[2] * sh))

    ot = trunk.to_object('tree%d_trunk' % seed, M('bark'), coll,
                         shade_smooth_all=True)
    ol = leaves.to_object('tree%d_leaves' % seed,
                          M('foliage' if seed % 2 else 'foliage_b'), coll)
    return ot, ol


def build_planting():
    coll = collection('planting')
    kits = collection('treekit')
    kit = [make_tree_kit(kits, s, levels=5, n_leaf=13000) for s in (1, 2, 3)]
    # Flat shading splits every face, so the detailed blade costs 24 verts in
    # the GLB against 6 for the simple one. These two sit 15-20 m out, where a
    # leaf is about eight pixels and the second pair of shoulders cannot be
    # seen - so they take the simple blade and spend the saving on density.
    # Only the branch framing the corner is near enough to justify detail=1.
    # The near kerb trees are the only ones a visitor reads leaf by leaf, and
    # at 0.43 m the old blade was four times the length of a real lime's. A
    # leaf cannot be brought all the way down - keeping the crown opaque
    # costs leaves as the square of the shrink, and the canopy is already the
    # heaviest geometry in the frame - but 1.55x smaller against 2.2x more of
    # them is paid for by two kits and buys the whole near canopy its grain.
    hero = [make_tree_kit(kits, s, levels=5, n_leaf=42000, lmin=0.072, lmax=0.118,
                          H=11.4, blob=1.70, lift=0.15, spread=2.5, r0=0.40)
            for s in (7, 8)]
    # Roof terrace: slim ornamental trees, the kind a podium slab can carry.
    # Measured off the photograph their crowns sit about 4 m above the parapet
    # - storey pitch is 39 px at that distance - which puts them at 4.6 m out
    # of a planter whose top is 0.65 m above the deck.
    terr = [make_tree_kit(kits, s, levels=4, n_leaf=5400, lmin=0.057, lmax=0.091,
                          H=4.6, blob=0.80, lift=0.21, spread=0.95, r0=0.13)
            for s in (11, 12)]
    kit = kit + hero
    for o in kit + terr:
        for p in o:
            p.hide_render = True
            p.hide_viewport = True
    placed = collection('trees')
    tz = PARK_TOP + 0.05
    for j, (tx, ty) in enumerate(terrace_planters()):
        sc = 0.78                      # crown top at z ~8.9, as in the picture
        for src in terr[j % 2]:
            link_dup(src, src.name + '_t', loc=(tx, ty, tz),
                     rot_z=rnd.uniform(0, 6.28), scale=(sc, sc, sc),
                     coll=placed)
    def put(x, y, s, rz, i):
        for src in kit[i % 3]:
            link_dup(src, src.name + '_i', loc=(x, y, 0.14), rot_z=rz,
                     scale=(s, s, s), coll=placed)
    i = 0
    x = 26.0
    while x < 200.0:                      # avenue on the far pavement
        put(x + rnd.uniform(-1, 1), WALK_EDGE + 1.7 + rnd.uniform(-.5, .5),
            rnd.uniform(0.80, 1.05), rnd.uniform(0, 6.28), i)
        x += 9.4; i += 1
    x = -40.0
    while x < 10.0:                       # planting in front of the far block
        put(x, 44.0 + rnd.uniform(-2, 2), rnd.uniform(1.0, 1.3),
            rnd.uniform(0, 6.28), i)
        x += 11.0; i += 1
    for x, y, s, k in ((-30.0, NEAR_KERB - 1.8, 1.08, 3),
                       (-17.0, NEAR_KERB - 1.9, 0.98, 4),
                       (-56.0, NEAR_KERB - 1.6, 1.05, 1),
                       (-70.0, NEAR_KERB - 1.5, 0.98, 2)):
        for src in kit[k]:
            link_dup(src, src.name + '_n', loc=(x, y, 0.14),
                     rot_z=rnd.uniform(0, 6.28), scale=(s, s, s), coll=placed)
    # the branch that frames the top-left corner of the frame
    br = MB(); lv = MB()
    r = random.Random(9)
    p0 = (-53.4, -38.6, 9.75)
    ends = []
    p = p0
    for k in range(4):
        q = (p[0] + r.uniform(1.3, 1.8), p[1] - r.uniform(1.1, 1.6),
             p[2] + r.uniform(-0.30, 0.18))
        br.cyl(p, q, 0.135 - k * 0.022, 0.118 - k * 0.022, seg=7)
        ends.append(q); p = q
        if k >= 1:
            s2 = (q[0] + r.uniform(0.5, 1.1), q[1] - r.uniform(0.6, 1.2),
                  q[2] + r.uniform(-0.55, 0.12))
            br.cyl(q, s2, 0.065, 0.045, seg=6)
            ends.append(s2)
    # These are the largest leaves in the frame, so they get the detailed
    # blade, a petiole, and proper shoots rather than a cloud.
    zl = [t[2] for t in ends]
    tintf = leaf_tinter(min(zl) - 1.0, max(zl) + 0.4,
                        sum(t[0] for t in ends) / len(ends),
                        sum(t[1] for t in ends) / len(ends), 2.2, r)
    light = _nrm((0.30, -0.18, 1.0))
    for t in ends:
        for _ in range(980):
            a_ = r.uniform(0, TAU); b_ = r.uniform(0, math.pi)
            rr = 0.80 * r.uniform(0.15, 1.0) ** 0.5
            c = (t[0] + math.sin(b_) * math.cos(a_) * rr,
                 t[1] + math.sin(b_) * math.sin(a_) * rr,
                 t[2] + math.cos(b_) * rr * 0.85)
            sz = r.uniform(0.052, 0.082)
            ya = r.uniform(0, TAU); pa = r.uniform(-1.40, 0.50)
            ca, sa = math.cos(ya), math.sin(ya)
            cp, sp = math.cos(pa), math.sin(pa)
            vd = (-sa * cp, ca * cp, sp)
            nd = (sa * sp, -ca * sp, cp)
            leaf_blade(lv, (c[0] - vd[0] * sz * 1.22, c[1] - vd[1] * sz * 1.22,
                            c[2] - vd[2] * sz * 1.22),
                       vd, nd, sz, r, 1, tintf(c))
    br.to_object('fg_branch', M('bark'), placed, shade_smooth_all=True)
    lv.to_object('fg_branch_leaves', M('foliage'), placed)
    return coll


# ------------------------------------------------------------------ classical background blocks
def build_classical(name, coll, length, depth, floors, fh=3.40, base_h=4.60,
                    bay=3.05, attic=True):
    """Simplified stone perimeter block: rusticated base, punched windows with
    sills and architraves, projecting cornice, attic storey."""
    m = MB(); gl = MB()
    H = base_h + floors * fh
    nb = max(2, int(round(length / bay)))
    b = length / nb
    m.box((0, 0, 0), (length, depth, base_h))
    for k in range(nb):                                   # base openings
        a0, a1 = k * b + 0.55, (k + 1) * b - 0.55
        m.box((a0, -0.03, 0.35), (a1, 0.22, base_h - 0.75))
        gl.box((a0 + .08, 0.05, 0.42), (a1 - .08, 0.09, base_h - 0.82))
    m.box((0, -0.22, base_h - 0.62), (length, depth, base_h + 0.10))   # band
    for f in range(floors):
        z0 = base_h + 0.10 + f * fh
        for k in range(nb):
            cx = (k + 0.5) * b
            ww, wh = 1.30, 2.05
            frame_for(k * b, (k + 1) * b, z0, z0 + fh, cx - ww / 2, cx + ww / 2,
                      z0 + 0.72, z0 + 0.72 + wh, 0.0, 0.32, m)
            m.box((cx - ww / 2 - 0.16, -0.14, z0 + 0.60),
                  (cx + ww / 2 + 0.16, 0.0, z0 + 0.74))          # sill
            if f < 2:
                m.box((cx - ww / 2 - 0.14, -0.10, z0 + 0.72 + wh),
                      (cx + ww / 2 + 0.14, 0.0, z0 + 0.86 + wh))  # architrave
            gl.box((cx - ww / 2 + .07, 0.14, z0 + 0.79),
                   (cx + ww / 2 - .07, 0.18, z0 + 0.65 + wh))
    m.box((0, 0.32, 0), (length, depth, H))                        # mass
    m.box((-0.30, -0.55, H - 0.30), (length + 0.30, depth, H + 0.42))   # cornice
    if attic:
        m.box((0.6, 0.4, H + 0.42), (length - 0.6, depth - 0.4, H + 3.3))
        for k in range(0, nb, 2):
            cx = (k + 0.5) * b
            m.box((cx - 0.75, 0.25, H + 0.9), (cx + 0.75, 0.45, H + 2.6))
    o = m.to_object(name, M('stone_classical'), coll)
    gl.to_object(name + '_glass', M('glass_window'), coll)
    return o, H


def build_background():
    coll = collection('background')
    # ---- street wall continuing east past the wing
    x = 85.0
    i = 0
    while x < 260.0:
        L = rnd.uniform(34, 52)
        o, H = build_classical('bg_e%d' % i, coll, L, 26.0,
                               rnd.choice([5, 6, 6, 7]),
                               fh=rnd.uniform(3.25, 3.6))
        o.location = (x, STREET_Y, 0.0)
        for c in coll.objects:
            if c.name.startswith('bg_e%d' % i):
                c.location = (x, STREET_Y, 0.0)
        x += L + rnd.uniform(0.0, 1.5)
        i += 1
    # ---- block behind, seen past the west gable
    x = -52.0
    i = 0
    while x < 14.0:
        L = rnd.uniform(30, 46)
        o, H = build_classical('bg_w%d' % i, coll, L, 30.0,
                               rnd.choice([5, 6, 6]), fh=rnd.uniform(3.3, 3.6))
        for c in coll.objects:
            if c.name.startswith('bg_w%d' % i):
                c.location = (x, 50.0, 0.0)
        x += L + rnd.uniform(0.5, 2.0)
        i += 1
    # ---- far side of the avenue, way down to the east
    x = 70.0
    i = 0
    west_end = None
    while x < 240.0:
        L = rnd.uniform(28, 44)
        o, H = build_classical('bg_n%d' % i, coll, L, 26.0, rnd.choice([4, 5, 6]),
                               fh=rnd.uniform(3.2, 3.5))
        if west_end is None:
            west_end = x - L
        for c in coll.objects:
            if c.name.startswith('bg_n%d' % i):
                c.location = (x, -64.0, 0.0)
                c.rotation_euler = (0, 0, math.pi)
        x += L + rnd.uniform(1.0, 3.0)
        i += 1
    # ---- the same row carried back west, past the camera.
    # The page now gives the render the whole window instead of letterboxing
    # it to the photograph's frame, and at that width the eye runs past the
    # near tree and used to land on the blank west end of bg_n0 - a storey
    # high slab of plain stone filling the right of frame. Carrying the row
    # back until it is behind the camera puts a facade there instead.
    # Its own random stream, appended after everything else, so not one block
    # that was already in the frame moves.
    r2 = random.Random(20261011)
    x = west_end
    i = 100
    while x > -95.0:
        L = r2.uniform(28, 44)
        build_classical('bg_n%d' % i, coll, L, 26.0, r2.choice([4, 5, 6]),
                        fh=r2.uniform(3.2, 3.5))
        for c in coll.objects:
            if c.name.startswith('bg_n%d' % i):
                c.location = (x, -64.0, 0.0)
                c.rotation_euler = (0, 0, math.pi)
        x -= L + r2.uniform(1.0, 3.0)
        i += 1
    return coll


# ------------------------------------------------------------------ vehicles
def _loft(mb, rings, close_start=True, close_end=True):
    n = len(rings[0])
    o = len(mb.v)
    for r in rings:
        mb.v.extend(r)
    for i in range(len(rings) - 1):
        for j in range(n):
            k = (j + 1) % n
            mb.smooth.add(len(mb.f))
            mb.f.append((o + i * n + j, o + i * n + k,
                         o + (i + 1) * n + k, o + (i + 1) * n + j))
    if close_start:
        mb.f.append(tuple(o + j for j in range(n)))
    if close_end:
        b = o + (len(rings) - 1) * n
        mb.f.append(tuple(b + n - 1 - j for j in range(n)))


def _section(x, cz, hw, hh, n=14, p=2.7):
    pts = []
    for j in range(n):
        a = math.pi * 2 * j / n
        ca, sa = math.cos(a), math.sin(a)
        f = lambda t: math.copysign(abs(t) ** (2.0 / p), t)
        pts.append((x, cz + hh * f(sa) * 0 + 0, 0))   # placeholder
    return pts


def make_car(coll, name, L=4.62, W=1.88, H_BELT=0.98, H_ROOF=1.46,
             suv=False, mat='car_paint_0'):
    """Lofted saloon/SUV body. The cross section carries real tumblehome so the
    glasshouse narrows above the waistline, and the sill lifts into wheel
    arches - without those two things a car reads as a pod at street scale."""
    body = MB(); glass = MB(); wheel = MB(); rim = MB(); trim = MB()
    SILL = 0.30 if not suv else 0.36
    RW = 0.335 if not suv else 0.385
    WX = (0.185, 0.815)

    #  u      roof    belt    halfwidth  roofwidth
    prof = [(0.000, 0.455, 0.735, 0.30, 1.00),
            (0.025, 0.510, 0.800, 0.62, 1.00),
            (0.075, 0.555, 0.870, 0.84, 1.00),
            (0.160, 0.590, 0.930, 0.94, 0.99),
            (0.265, 0.640, 0.975, 0.985, 0.97),
            (0.345, 0.830, 1.000, 1.000, 0.86),
            (0.430, 0.975, 1.000, 1.000, 0.795),
            (0.540, 1.000, 0.998, 0.998, 0.785),
            (0.645, 0.985, 0.992, 0.985, 0.795),
            (0.745, 0.905, 0.980, 0.955, 0.845),
            (0.845, 0.760, 0.962, 0.900, 0.925),
            (0.935, 0.665, 0.930, 0.790, 0.985),
            (1.000, 0.620, 0.870, 0.40, 1.00)]

    def arch(u):
        a = 0.0
        for cx in WX:
            d = (u - cx) / 0.085
            a = max(a, (RW + 0.07 - SILL) * math.exp(-d * d))
        return a

    def section(u, roof, belt, hwf, rwf):
        hw = (W * 0.5) * hwf
        rw = hw * rwf
        zb = SILL + arch(u) + 0.045 * abs(2 * u - 1) ** 3
        zt = max(H_ROOF * roof, H_BELT * belt + 0.035)
        zbl = H_BELT * belt
        if zbl <= zb + 0.02:
            zbl = zb + 0.02
        if zt <= zbl + 0.02:
            zt = zbl + 0.02
        half = [(0.00, zb), (hw * 0.70, zb), (hw * 0.94, zb + (zbl - zb) * 0.18),
                (hw, zb + (zbl - zb) * 0.55), (hw * 0.995, zbl),
                (rw + (hw - rw) * 0.45, zbl + (zt - zbl) * 0.42),
                (rw, zt - (zt - zbl) * 0.22), (rw * 0.80, zt), (0.0, zt)]
        ring = [(u * L, y, z) for (y, z) in half]
        ring += [(u * L, -y, z) for (y, z) in reversed(half[1:-1])]
        return ring

    rings = [section(*p) for p in prof]
    _loft(body, rings)

    # glasshouse: a thin shell just outside the body between the A and C pillars
    gprof = [p for p in prof if 0.26 <= p[0] <= 0.85]
    grings = []
    for (u, roof, belt, hwf, rwf) in gprof:
        hw = (W * 0.5) * hwf
        rw = hw * rwf
        zt = max(H_ROOF * roof, H_BELT * belt + 0.035)
        zbl = H_BELT * belt
        half = [(0.0, zbl + 0.01),
                (rw + (hw - rw) * 0.45, zbl + (zt - zbl) * 0.42),
                (rw, zt - (zt - zbl) * 0.22), (rw * 0.80, zt), (0.0, zt)]
        ring = [(u * L, y * 1.006, z) for (y, z) in half]
        ring += [(u * L, -y * 1.006, z) for (y, z) in reversed(half[1:-1])]
        grings.append(ring)
    _loft(glass, grings, close_start=False, close_end=False)

    # waist trim, lamps
    for (u0, u1) in ((0.0, 0.055), (0.955, 1.0)):
        trim.box((u0 * L, -W * 0.40, H_BELT * 0.52),
                 (u1 * L, W * 0.40, H_BELT * 0.52 + 0.14))
    for ux in WX:
        cx = ux * L
        for side in (1, -1):
            cy = side * (W * 0.5 - 0.055)
            wheel.cyl((cx, cy, RW), (cx, cy - side * 0.225, RW), RW, RW, seg=18)
            rim.cyl((cx, cy - side * 0.015, RW), (cx, cy - side * 0.055, RW),
                    RW * 0.64, RW * 0.64, seg=18)
    ob = body.to_object(name, M(mat), coll, shade_smooth_all=True)
    og = glass.to_object(name + '_glass', M('car_glass'), coll, shade_smooth_all=True)
    ow = wheel.to_object(name + '_tyre', M('tire'), coll, shade_smooth_all=True)
    orr = rim.to_object(name + '_rim', M('chrome'), coll, shade_smooth_all=True)
    ot = trim.to_object(name + '_trim', M('chrome'), coll)
    return [ob, og, ow, orr, ot]


def make_bus(coll, name='bus'):
    body = MB(); glass = MB(); wheel = MB()
    L, W, H = 12.2, 2.55, 3.15
    rings = []
    for u in (0.0, 0.03, 0.10, 0.90, 0.97, 1.0):
        t = 2 * u - 1
        hw = (W / 2) * (1 - 0.55 * max(0, abs(t) - 0.88) ** 1.4 * 8)
        bot, top = 0.42, H * (1 - 0.10 * max(0, abs(t) - 0.9) ** 1.2 * 9)
        n = 16
        ring = []
        for j in range(n):
            a = math.pi * 2 * j / n + math.pi / n
            ca, sa = math.cos(a), math.sin(a)
            e = 5.0
            sx = math.copysign(abs(ca) ** (2.0 / e), ca)
            sz = math.copysign(abs(sa) ** (2.0 / e), sa)
            ring.append((u * L, hw * sx, (top + bot) * .5 + (top - bot) * .5 * sz))
        rings.append(ring)
    _loft(body, rings)
    for side in (1, -1):
        glass.box((0.9, side * (W / 2 + 0.01), 1.55), (L - 0.9, side * (W / 2 - 0.03), 2.68))
    glass.box((0.05, -W / 2 + 0.05, 1.35), (0.30, W / 2 - 0.05, 2.78))
    glass.box((L - 0.30, -W / 2 + 0.05, 1.45), (L - 0.05, W / 2 - 0.05, 2.78))
    for ux in (0.16, 0.62, 0.78):
        for side in (1, -1):
            cx = ux * L; cy = side * (W / 2 - 0.08)
            wheel.cyl((cx, cy, 0.52), (cx, cy - side * 0.28, 0.52), 0.52, 0.52, seg=16)
    ob = body.to_object(name, M('bus_green'), coll, shade_smooth_all=True)
    og = glass.to_object(name + '_glass', M('car_glass'), coll)
    ow = wheel.to_object(name + '_tyre', M('tire'), coll, shade_smooth_all=True)
    return [ob, og, ow]


def build_traffic():
    coll = collection('traffic')
    kits = collection('carkit')
    fleet = []
    specs = [(4.70, 1.86, 0.98, 1.44, False), (4.92, 1.94, 1.02, 1.48, False),
             (4.55, 1.85, 1.12, 1.66, True),  (5.05, 1.98, 1.18, 1.76, True),
             (4.35, 1.80, 0.94, 1.40, False), (4.80, 1.90, 1.14, 1.70, True)]
    for i, (L, W, hb, hr, suv) in enumerate(specs):
        fleet.append(make_car(kits, 'car%d' % i, L, W, hb, hr, suv,
                              'car_paint_%d' % (i * 2 % 10)))
    bus = make_bus(kits)
    for grp in fleet + [bus]:
        for o in grp:
            o.hide_render = True
            o.hide_viewport = True

    def place(grp, x, y, rz, name):
        for src in grp:
            link_dup(src, name + '_' + src.name, loc=(x, y, 0.0), rot_z=rz, coll=coll)

    # street deliberately left clear of vehicles
    return coll, []


def build_people():
    coll = collection('people')
    m = MB()
    for k in range(26):
        x = rnd.uniform(-20, 70)
        y = rnd.uniform(STREET_Y - 4.2, WALK_EDGE + 0.6)
        h = rnd.uniform(1.62, 1.86)
        m.cyl((x, y, 0.14), (x, y, 0.14 + h * 0.52), 0.115, 0.145, seg=7)
        m.cyl((x, y, 0.14 + h * 0.50), (x, y, 0.14 + h * 0.86), 0.185, 0.145, seg=7)
        m.sphere((x, y, 0.14 + h * 0.93), 0.105, seg=8, rings=5)
    m.to_object('people', M('person'), coll, shade_smooth_all=True)
    return coll
