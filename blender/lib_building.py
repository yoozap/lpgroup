# -*- coding: utf-8 -*-
"""Facade generators for the two residential bars and the retail podium."""
import bpy, math, random
from mathutils import Vector
from lib_build import (MB, mat, srgb, link_dup, frame_for, frame_for_yz, collection,
                       mirror_y, mirror_obj_y, rnd)

# ------------------------------------------------------------------ palette
def build_materials():
    mat('plaster_dark',    srgb('#231f1b'), rough=0.90)
    mat('plaster_dark_b',  srgb('#1c1915'), rough=0.90)   # wing return wall
    mat('plaster_light',   srgb('#b6b0a7'), rough=0.92)
    mat('concrete_loggia', srgb('#c3bcae'), rough=0.86)
    mat('concrete_podium', srgb('#b2aca4'), rough=0.82)
    mat('concrete_frame',  srgb('#b9b2a6'), rough=0.84)
    mat('stone_classical', srgb('#cdc5b6'), rough=0.88)
    mat('stone_classical_b', srgb('#c2bbae'), rough=0.9)
    mat('metal_dark',      srgb('#191a1d'), rough=0.38, metal=0.85)
    # balcony balustrade: a painted light-warm-grey metal, not the near black
    # of the street railings - it reads clearly lighter than the loggia behind
    mat('rail_balcony',    srgb('#a2998b'), rough=0.73, metal=0.18)
    mat('frame_bronze',    srgb('#2b2724'), rough=0.42, metal=0.55)
    mat('frame_light',     srgb('#d9d6ce'), rough=0.48, metal=0.30)
    mat('glass_window',    srgb('#0c1014'), rough=0.06, metal=0.0, ior=1.52)
    # the punched windows: same pane, its own name so the web can keep the
    # blind down behind every one of them
    mat('glass_blind',     srgb('#0c1014'), rough=0.06, metal=0.0, ior=1.52)
    mat('glass_lit',       srgb('#1a1208'), rough=0.18,
        emis=srgb('#ffb55e'), emis_str=3.2)
    # the pale blind behind every pane: this is what makes a window read as a
    # window from the street rather than a dark hole punched in the wall
    mat('blind',           srgb('#d9d5cc'), rough=0.92,
        emis=srgb('#e8e6df'), emis_str=0.6)
    # stair / corridor slots in the gable: no blind behind them, so they stay
    # dark against the light render - exactly as in the reference
    mat('glass_slot',      srgb('#0a0d11'), rough=0.05, ior=1.52)
    mat('reveal_dark',     srgb('#17161a'), rough=0.55)
    mat('glass_shop',      srgb('#0a0c0f'), rough=0.05)
    mat('shop_interior',   srgb('#6b5c48'), rough=0.75,
        emis=srgb('#ffd9a0'), emis_str=0.9)
    mat('neon_orange',     srgb('#ff5712'), rough=0.4,
        emis=srgb('#ff5712'), emis_str=9.0)
    mat('sign_metal',      srgb('#3a3a3c'), rough=0.35, metal=0.7)
    mat('asphalt',         srgb('#3b3a3c'), rough=0.72)
    mat('road_paint',      srgb('#cfcdc6'), rough=0.6)
    mat('sidewalk',        srgb('#9b958e'), rough=0.85)
    mat('curb',            srgb('#8d8880'), rough=0.8)
    mat('grass',           srgb('#4a5c2a'), rough=0.9)
    mat('soil',            srgb('#3b332a'), rough=0.95)
    mat('bark',            srgb('#4b4239'), rough=0.9)
    mat('foliage',         srgb('#52702f'), rough=0.72)
    mat('foliage_b',       srgb('#617f36'), rough=0.72)
    mat('canopy_fabric',   srgb('#e8e6e0'), rough=0.65)
    mat('bus_green',       srgb('#79c143'), rough=0.3, metal=0.1)
    mat('tire',            srgb('#121214'), rough=0.85)
    mat('chrome',          srgb('#c9ccd0'), rough=0.18, metal=1.0)
    mat('car_glass',       srgb('#0b0e12'), rough=0.05)
    for i, c in enumerate(['#1a1d22', '#8d9299', '#2d3b52', '#6e6f72', '#b9bcc0',
                           '#30271f', '#1d4731', '#5a5e63', '#7a7b7f', '#262a2f']):
        mat('car_paint_%d' % i, srgb(c), rough=0.22, metal=0.55)
    mat('person', srgb('#2e2c30'), rough=0.85)
    mat('pole_metal', srgb('#232529'), rough=0.45, metal=0.6)


M = lambda n: bpy.data.materials[n]

# ------------------------------------------------------------------ constants
# Fitted against the reference photograph (see README). Storey pitch, floor
# count and podium level all re-measured within 1 px; the openings were not.
FLOOR_H   = 3.00   # 60 px per storey at x=820 in the reference
GROUND_H  = 4.65   # podium slab == first residential floor level
N_FLOORS  = 10
WALL_T    = 0.35
PARAPET   = 1.40
TOP_Z     = GROUND_H + N_FLOORS * FLOOR_H          # 34.65  roof slab
ROOF_Z    = TOP_Z + PARAPET                        # 36.05  parapet top

LOG_W   = 3.520    # loggia bay   ) 2*(L+W) = 11.73 m, the unit measured
LOG_OP  = 1.760    # loggia opening: 1.71-1.77 m measured on the photograph
LOG_JL  = 0.600    # jamb from the bay start to the opening. The pier between
                   # a pair of loggias comes out at 1.67 m, as measured.
LOG_H   = 2.620    # loggia opening height
LOG_D   = 1.50     # loggia recess depth
LOG_RET = 0.185    # shell returns this far past the opening on every side
LOG_CY  = 0.02     # cheek front face, set back behind the wall face
LOG_SY  = 0.10     # soffit and slab front face, set back further still
WIN_W   = 2.250    # window bay: two-unit pitch measures 11.53 m, not 11.73
# The white of a window in the photograph is 1.12 x 1.24 m and sits 1.02 m
# above the slab. The frame and sash around the pane are dark and 0.104 m
# deep each side, so the hole in the wall is that much bigger all round.
W1_W, W2_W = 1.33, 1.33
W1_OFF, W2_OFF = 0.00, 0.25 # hole left edge from the start of its bay: the
                            # first window hugs the loggia, the second sits
                            # a little left of its bay centre
WIN_H   = 1.45     # hole; the white pane runs 1.00..2.25 above the floor
WIN_SILL = 0.90
GLASS_Y = 0.16

# the glazed wall at the back of a deep gallery bay: the same door-and-window
# pair the loggias carry, so the two elevations read as the same building
GAL_OP  = 2.70     # glazed opening in the back wall
GAL_DW  = 1.00     # terrace door
GAL_WW  = 1.12     # window beside it
GAL_H   = 2.43     # door and window head
GAL_WS  = 1.00     # window sill

# bay rhythm read off the reference: one loggia on the corner, a pair of
# windows, then alternating pairs of loggias and pairs of windows
BAYS_A = ['L', 'W', 'W'] + ['L', 'L', 'W', 'W'] * 4
END_PIER = 0.25    # pier between the arris and the first loggia bay
BAY_EXTRA = {1: 0.30}   # the first window bay is 0.3 m wider than the rest
# Block A's storeys sit 0.15 m above the podium datum the gable slots and the
# wing use: sills, heads and slab lines all measured that much higher.
FACADE_OFF = 0.15


def bay_layout(seq):
    out, x = [], END_PIER
    for i, k in enumerate(seq):
        w = (LOG_W if k == 'L' else WIN_W) + BAY_EXTRA.get(i, 0.0)
        out.append((k, x, x + w, i))
        x += w
    return out, x


# ------------------------------------------------------------------ railings
def rail_run(mb, a, b, y, z):
    """The baluster railing every balcony on the scheme carries: two flats and
    a picket run at 89 mm, the pitch read off the reference. Local x runs along
    the railing, y is the face it stands on, z the balcony floor."""
    mb.box((a, y, z + 1.02), (b, y + 0.05, z + 1.07))
    mb.box((a, y, z + 0.07), (b, y + 0.04, z + 0.11))
    n = max(2, int(round((b - a - 0.06) / 0.089)))
    for k in range(n + 1):
        x = a + 0.03 + (b - a - 0.06) * k / n
        mb.box((x - 0.009, y + 0.005, z + 0.09), (x + 0.009, y + 0.022, z + 1.03))


# ------------------------------------------------------------------ loggia kit
def loggia_openings(op):
    """Door and window(s) in the glazed back wall of a loggia `op` wide."""
    if op < 3.0:
        d0, dw = 0.14, min(0.86, op * 0.44)
        w0 = d0 + dw + 0.16
        return (d0, d0 + dw), [(w0, op - 0.14)]
    d0, dw = 0.16, 0.90
    n = 2 if op > 3.6 else 1
    gap = 0.34
    ww = (op - (d0 + dw) - 0.16 - gap * n) / n
    wins, x = [], d0 + dw + gap
    for k in range(n):
        wins.append((x, x + ww))
        x += ww + gap
    return (d0, d0 + dw), wins


def make_loggia_module(coll, op=None, tag='', back=None):
    """Source objects for one recessed balcony `op` wide; reused as linked
    duplicates. Local x runs across the opening, y into the recess, z up.
    `back` names the material of the glazed back wall: pale concrete on
    block A, the dark plaster on the wing, where the photograph shows the
    balconies as dark boxes behind pale slab edges."""
    op = LOG_OP if op is None else op
    shell = MB()
    wall = MB()
    y0 = WALL_T
    y1 = WALL_T + LOG_D
    # The soffit runs from the head of the opening up to the floor above, so
    # one box is the ceiling of this balcony, the slab edge seen from the
    # street, and the floor of the balcony above. A separate nosing box sat
    # wholly inside it, and two sets of faces on one plane is what makes a
    # facade blink. The bottom row stands on the podium roof at GROUND_H.
    shell.box((-LOG_RET, LOG_SY, LOG_H), (op + LOG_RET, y1 + 0.22, FLOOR_H))
    shell.box((-LOG_RET, LOG_CY, 0.0), (0.0, y1, LOG_H))
    shell.box((op, LOG_CY, 0.0), (op + LOG_RET, y1, LOG_H))
    (ox0, ox1), wins = loggia_openings(op)
    DT = 2.36                      # door head
    WS = 0.88                      # window sill
    edges = [0.0, ox0, ox1] + [v for w in wins for v in w] + [op]
    bw = wall if back else shell
    for k in range(0, len(edges) - 1, 2):
        if edges[k + 1] > edges[k] + 1e-6:
            bw.panel(edges[k], edges[k + 1], 0.0, LOG_H, y1, y1 + 0.22)
    bw.panel(ox0, ox1, DT, LOG_H, y1, y1 + 0.22)
    for (a, b) in wins:
        bw.panel(a, b, 0.0, WS, y1, y1 + 0.22)
        bw.panel(a, b, DT, LOG_H, y1, y1 + 0.22)
    o_shell = shell.to_object('loggia_shell' + tag, M('concrete_loggia'), coll)
    o_back = wall.to_object('loggia_back' + tag, M(back), coll) if back else None

    g = MB()
    g.panel(ox0 + .05, ox1 - .05, 0.05, DT - .05, y1 + 0.07, y1 + 0.10)
    for (a, b) in wins:
        g.panel(a + .05, b - .05, WS + .05, DT - .05, y1 + 0.07, y1 + 0.10)
    o_glass = g.to_object('loggia_glass' + tag, M('glass_window'), coll)

    fr = MB()
    for (a, b, c, d) in [(ox0, ox1, 0.0, DT)] + [(a, b, WS, DT) for (a, b) in wins]:
        fr.panel(a, a + .06, c, d, y1 + .04, y1 + .13)
        fr.panel(b - .06, b, c, d, y1 + .04, y1 + .13)
        fr.panel(a + .06, b - .06, c, c + .06, y1 + .04, y1 + .13)
        fr.panel(a + .06, b - .06, d - .06, d, y1 + .04, y1 + .13)
    for (a, b) in wins:
        fr.panel((a + b) * .5 - .025, (a + b) * .5 + .025, WS + .06, DT - .06,
                 y1 + .04, y1 + .12)
    o_frame = fr.to_object('loggia_frame' + tag, M('frame_bronze'), coll)

    r = MB()
    rail_run(r, 0.03, op - 0.03, WALL_T + 0.07, 0.0)
    o_rail = r.to_object('loggia_rail' + tag, M('rail_balcony'), coll)
    return [o_shell, o_glass, o_frame, o_rail] + ([o_back] if o_back else [])


def make_window_module(coll, w, name, h=None):
    """Punched window built in layers, the way a real one is: reveal, sill,
    lintel, frame, sash, glass - each one set back a little further. The
    stack of small shadow lines is what stops a window reading as a sticker."""
    h = WIN_H if h is None else h
    g = MB()
    g.panel(0.0, w, 0.0, h, GLASS_Y + 0.055, GLASS_Y + 0.075)
    og = g.to_object(name + '_glass', M('glass_blind'), coll)

    f = MB()
    t = 0.062                      # frame face
    sg = 0.042                     # sash face
    for (y0, y1, k) in ((GLASS_Y - 0.075, GLASS_Y + 0.055, t),):
        f.panel(0.0, k, 0.0, h, y0, y1)
        f.panel(w - k, w, 0.0, h, y0, y1)
        f.panel(k, w - k, 0.0, k, y0, y1)
        f.panel(k, w - k, h - k, h, y0, y1)
    # sash, one more step back inside the frame
    f.panel(t, t + sg, t, h - t, GLASS_Y - 0.012, GLASS_Y + 0.062)
    f.panel(w - t - sg, w - t, t, h - t, GLASS_Y - 0.012, GLASS_Y + 0.062)
    f.panel(t + sg, w - t - sg, t, t + sg, GLASS_Y - 0.012, GLASS_Y + 0.062)
    f.panel(t + sg, w - t - sg, h - t - sg, h - t,
            GLASS_Y - 0.012, GLASS_Y + 0.062)
    f.panel(w * .5 - .022, w * .5 + .022, t + sg, h - t - sg,
            GLASS_Y - 0.008, GLASS_Y + 0.058)
    of = f.to_object(name + '_frame', M('frame_bronze'), coll)

    sl = MB()
    # a shallow weathered sill: enough to throw a shadow line and keep the rain
    # off the wall below, not enough to read as a stone band from the street
    # bottom ring first, then the sloping top - the same vertex order MB.box
    # uses. Written the other way round every face came out inside out.
    sl.add([(-0.035, -0.030, -0.085), (w + 0.035, -0.030, -0.085),
            (w + 0.035, WALL_T, -0.085), (-0.035, WALL_T, -0.085),
            (-0.035, -0.030, -0.045), (w + 0.035, -0.030, -0.045),
            (w + 0.035, WALL_T, -0.018), (-0.035, WALL_T, -0.018)],
           [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6),
            (3, 0, 4, 7), (1, 2, 6, 5)])
    osl = sl.to_object(name + '_sill', M('plaster_dark'), coll)
    return og, of, osl


def make_lit_glass(coll, w, name, h=None):
    """The same pane as the window kit, in the lit material. A few flats on
    every elevation have the light on; it is most of what sells a dark wall."""
    h = WIN_H if h is None else h
    g = MB()
    g.panel(0.0, w, 0.0, h, GLASS_Y + 0.055, GLASS_Y + 0.075)
    return g.to_object(name + '_glass_lit', M('glass_lit'), coll)


def make_gallery_module(coll, w, depth, name):
    """One bay of a deep open gallery, fitted out the way the loggias are: a
    baluster railing across the open front, then a glazed door and a window set
    back at the far wall, each in its own frame. An empty bay reads as a
    concrete rack - the railing and the glazing are what make it a facade.

    Local x runs across the bay, y from the open front into the recess, z from
    the balcony floor; `depth` is the distance back to the glazed wall."""
    r = MB()
    rail_run(r, 0.03, w - 0.03, 0.08, 0.0)
    o_rail = r.to_object(name + '_rail', M('rail_balcony'), coll)

    q = (w - GAL_OP) * 0.5                       # opening, centred on the bay
    dx0, dx1 = q + 0.14, q + 0.14 + GAL_DW       # door
    wx0, wx1 = q + 1.44, q + 1.44 + GAL_WW       # window beside it
    g = MB()
    g.panel(dx0 + .05, dx1 - .05, 0.17, GAL_H - .05, depth + .07, depth + .10)
    g.panel(wx0 + .05, wx1 - .05, GAL_WS + .05, GAL_H - .05,
            depth + .07, depth + .10)
    o_glass = g.to_object(name + '_glass', M('glass_window'), coll)
    o_lit = g.to_object(name + '_glass_lit', M('glass_lit'), coll)

    fr = MB()
    for (a, b, c, d) in ((dx0, dx1, 0.12, GAL_H), (wx0, wx1, GAL_WS, GAL_H)):
        fr.panel(a, a + .06, c, d, depth + .04, depth + .13)
        fr.panel(b - .06, b, c, d, depth + .04, depth + .13)
        fr.panel(a + .06, b - .06, c, c + .06, depth + .04, depth + .13)
        fr.panel(a + .06, b - .06, d - .06, d, depth + .04, depth + .13)
    fr.panel((wx0 + wx1) * .5 - .025, (wx0 + wx1) * .5 + .025,
             GAL_WS + .06, GAL_H - .06, depth + .04, depth + .12)
    o_frame = fr.to_object(name + '_frame', M('frame_bronze'), coll)
    return o_rail, o_frame, o_glass, o_lit


def place_bay(kit, coll, tag, loc, rot_z=0.0):
    """Railing, frame and one of the two panes - a tenth of the flats lit."""
    rail, frame, glass, lit = kit
    for src in (rail, frame, lit if rnd.random() < 0.10 else glass):
        link_dup(src, '%s_%s' % (src.name, tag), loc=loc, rot_z=rot_z, coll=coll)


# ------------------------------------------------------------------ block A
A_LEN   = 55.58     # to the wing's return wall: 19 bays plus a 0.45 m pier
A_DEPTH = 18.00     # gable back edge at u=574 in the photograph
BACK_BAY = 100      # added to a bay number to say 'the same bay, back elevation'


def build_block_a(root_coll):
    coll = collection('blockA')
    bays, used = bay_layout(BAYS_A)
    L = A_LEN

    kit_coll = collection('kit')
    loggia_kit = make_loggia_module(kit_coll)
    w1_kit = make_window_module(kit_coll, W1_W, 'winA')
    w2_kit = make_window_module(kit_coll, W2_W, 'winB')
    # The same kit turned round for the back elevation. Mirrored, not rotated:
    # a rotated balcony would put its door at the other end of the opening and
    # the back of the building would read as the other hand of the front.
    back_kit = {}
    for o in loggia_kit + list(w1_kit) + list(w2_kit):
        o.hide_render = True
        o.hide_viewport = True
        b = mirror_obj_y(o, o.name + '_bk', kit_coll, A_DEPTH)
        b.hide_render = True
        b.hide_viewport = True
        back_kit[o.name] = b

    seq = [b[0] for b in bays]

    def win_at(bx0, first):
        return bx0 + (W1_OFF if first else W2_OFF), (W1_W if first else W2_W)

    light = MB()
    Z0 = GROUND_H + FACADE_OFF
    ZT = Z0 + N_FLOORS * FLOOR_H           # 34.80: top of the facade storeys

    def elevation(dark):
        """One whole elevation of block A: ten storeys of the bay rhythm, the
        blank ends, the plinth band, the parapet and its coping.

        It is a function because the building has two of them. The back used
        to be a blind slab of plaster - the flats only ever stood along the
        street - and the back line of the top floor was an empty deck behind
        them. The same elevation mirrored at `A_DEPTH` gives the back line its
        own loggias and windows for the flats that stand there now."""
        for fl in range(N_FLOORS):
            z0 = Z0 + fl * FLOOR_H
            z1 = z0 + FLOOR_H
            for kind, bx0, bx1, idx in bays:
                if kind == 'L':
                    # The shell is pushed into the wall slab, so the wall is cut
                    # back to it in three depth layers. Run it the full thickness
                    # instead and dark plaster lands on the same planes as the pale
                    # concrete: the head and jambs of every balcony then dither.
                    ox0, ox1 = bx0 + LOG_JL, bx0 + LOG_JL + LOG_OP
                    ax0, ax1 = ox0 - LOG_RET, ox1 + LOG_RET
                    frame_for(bx0, bx1, z0, z1, ox0, ox1, z0, z0 + LOG_H,
                              0.0, LOG_CY, dark)
                    frame_for(bx0, bx1, z0, z1, ax0, ax1, z0, z0 + LOG_H,
                              LOG_CY, LOG_SY, dark)
                    frame_for(bx0, bx1, z0, z1, ax0, ax1, z0, z1,
                              LOG_SY, WALL_T, dark)
                else:
                    first = (idx == 0) or (seq[idx - 1] == 'L')
                    wx0, ww = win_at(bx0, first)
                    frame_for(bx0, bx1, z0, z1, wx0, wx0 + ww,
                              z0 + WIN_SILL, z0 + WIN_SILL + WIN_H, 0.0, WALL_T, dark)
        if L > used + 1e-6:                       # plain wall up to the wing
            dark.panel(used, L, Z0, ZT, 0.0, WALL_T)
        if END_PIER > 1e-6:                       # pier between arris and bay 0
            dark.panel(0.0, END_PIER, Z0, ZT, 0.0, WALL_T)
        # the podium roof slab already tops out at GROUND_H under the whole
        # footprint; a second face on that plane is what the ground-row balcony
        # floors were dithering on
        dark.panel(0.0, L, 0.0, Z0, 0.0, WALL_T, skip=('+z',))
        dark.panel(0.0, L, ZT, ROOF_Z - 0.10, 0.0, WALL_T)
        dark.panel(0.0, L, ZT, ROOF_Z, WALL_T, 0.60)
        dark.box((0.0, -0.065, ROOF_Z - 0.10), (L, 0.62, ROOF_Z))      # coping
        dark.box((0.0, -0.045, Z0 - 0.12), (L, 0.0, Z0))               # string course

    dark = MB()
    elevation(dark)
    o_dark = dark.to_object('A_facade_dark', M('plaster_dark'), coll)
    back = MB()
    elevation(back)
    mirror_y(back, A_DEPTH)
    back.to_object('A_facade_back', M('plaster_dark'), coll)

    # ---- west gable: light render with two columns of deep slot windows.
    # Measured off the reference photograph: slots 0.97 m wide, 2.40 m tall,
    # ten per column from the podium up, columns at y 14.1 and 4.3. Two
    # shopfronts are cut into its foot, where the photograph has them.
    # The leaf starts 2 cm behind the street face: the dark render of the
    # facade owns the arris, so the corner reads light -> dark on one edge
    # as it does in the photograph, and no face is shared with the facade.
    gy0, gy1 = 0.02, A_DEPTH - 0.02
    LEAF = 0.46          # gable leaf thickness
    # The slots are glazed almost flush: the dark 0.34 m band beside each
    # pane in the photograph is a flush dark panel, not a deep reveal. A deep
    # reveal looked the same from the street but swallowed half of every
    # pane the moment the camera rose above it.
    REV = 0.06           # face to frame
    # The slots are the photograph's 1.05 m, glazed over their whole width:
    # the dark band beside the glass in the picture is invisible against a
    # dark gable, and then the window read far narrower than it is.
    SLOT_W, SLOT_H = 1.60, 2.40      # client's call: wider than the photo reads
    SLOT_OFF = 0.18      # sill above floor level
    MULL = 0.06          # central mullion, dark and thin
    DK = 0.0             # no dark side panel
    cols = [14.12, 4.31]
    slots = []
    for cy in cols:
        for fl in range(0, N_FLOORS):
            z0 = GROUND_H + fl * FLOOR_H + SLOT_OFF
            if z0 + SLOT_H > TOP_Z - 0.25:
                continue
            slots.append((cy - SLOT_W / 2, cy + SLOT_W / 2, z0, z0 + SLOT_H))
    SHOPS = [(2.20, 6.40, 0.55, 4.20), (6.90, 11.05, 0.55, 4.20)]
    holes = slots + SHOPS
    xs = sorted({gy0, gy1} | {v for sl in holes for v in sl[:2]})
    zs = sorted({0.0, ROOF_Z} | {v for sl in holes for v in sl[2:]})

    def is_hole(ya, yb, za, zb):
        for (a, b, c, d) in holes:
            if ya >= a - 1e-6 and yb <= b + 1e-6 and za >= c - 1e-6 and zb <= d + 1e-6:
                return True
        return False
    for i in range(len(xs) - 1):
        for j in range(len(zs) - 1):
            ya, yb, za, zb = xs[i], xs[i + 1], zs[j], zs[j + 1]
            if not is_hole(ya, yb, za, zb):
                light.box((0.0, ya, za), (LEAF, yb, zb))
    o_light = light.to_object('A_gable_light', M('plaster_light'), coll)

    sg = MB(); sf = MB(); sl = MB(); sm = MB()
    for (a, b, c, d) in slots:
        gb = b - DK                      # glass unit a..gb, dark panel gb..b
        cy = (a + gb) * 0.5
        # a shallow dark lining round the opening
        sl.panel(0.004, REV, c, d, a, a + 0.035)
        sl.panel(0.004, REV, c, d, b - 0.035, b)
        sl.panel(0.004, REV, c, c + 0.035, a + 0.035, b - 0.035)
        sl.panel(0.004, REV, d - 0.035, d, a + 0.035, b - 0.035)
        if DK > 0.0:                 # dark panel, flush with the frame
            sl.panel(REV, REV + 0.075, c + 0.035, d - 0.035, gb, b - 0.035)
        # two panes either side of a thin mullion, just behind the frame
        sg.panel(REV + 0.05, REV + 0.07, c + .06, d - .06, a + .06, cy - MULL / 2)
        sg.panel(REV + 0.05, REV + 0.07, c + .06, d - .06, cy + MULL / 2, gb - .06)
        # pale frame round the glass unit
        sf.panel(REV, REV + 0.075, c, d, a, a + 0.06)
        sf.panel(REV, REV + 0.075, c, d, gb - 0.06, gb)
        sf.panel(REV, REV + 0.075, c, c + 0.06, a + 0.06, gb - 0.06)
        sf.panel(REV, REV + 0.075, d - 0.06, d, a + 0.06, gb - 0.06)
        sm.panel(REV, REV + 0.065, c + 0.06, d - 0.06,
                 cy - MULL / 2, cy + MULL / 2)
    o_slotglass = sg.to_object('A_slot_glass', M('glass_slot'), coll)
    # pale frames, as in the photograph; only the mullion stays dark
    sf.to_object('A_slot_frame', M('frame_light'), coll)
    sm.to_object('A_slot_mullion', M('frame_bronze'), coll)
    sl.to_object('A_slot_reveal', M('reveal_dark'), coll)

    # shopfronts in the foot of the gable: glass set back in the leaf, a lit
    # interior just behind it, bronze mullions
    gg = MB(); gi = MB(); gm = MB()
    for (a, b, c, d) in SHOPS:
        gg.box((0.36, a + 0.04, c + 0.03), (0.39, b - 0.04, d - 0.03))
        gi.box((0.42, a + 0.02, c + 0.02), (0.44, b - 0.02, d - 0.02))
        for t in (0.0, 0.33, 0.66, 1.0):
            y = a + 0.04 + (b - a - 0.08) * t
            gm.box((0.31, y - 0.035, c + 0.03), (0.41, y + 0.035, d - 0.03))
        for zz in (c + 0.03, 2.72, d - 0.11):
            gm.box((0.31, a + 0.04, zz), (0.41, b - 0.04, zz + 0.08))
    gg.to_object('A_shop_glass', M('glass_shop'), coll)
    gi.to_object('A_shop_interior', M('shop_interior'), coll)
    gm.to_object('A_shop_mullions', M('frame_bronze'), coll)

    bulk = MB()
    # the mass has to start behind the deepest loggia, otherwise it fills the
    # recesses and every balcony reads as a flat dark panel
    bulk.box((0.46, WALL_T + LOG_D + 0.24, 0.0),
             (L, A_DEPTH - (WALL_T + LOG_D + 0.24), ROOF_Z))
    o_bulk = bulk.to_object('A_mass', M('plaster_dark'), coll)

    inst = collection('A_openings')
    # The back instances carry the front's own name with BACK_BAY added to the
    # bay number. The name is what the page sorts the block by (`IS_TOWER` in
    # app.js wants `loggia_shell_f<storey>_b<bay>` exactly), and what the
    # cutaway reads the storey off, so the two elevations have to be told
    # apart by the number rather than by a tag in the middle of the name.
    for fl in range(N_FLOORS):
        z0 = Z0 + fl * FLOOR_H
        for kind, bx0, bx1, idx in bays:
            if kind == 'L':
                srcs, loc = loggia_kit, (bx0 + LOG_JL, 0.0, z0)
            else:
                first = (idx == 0) or (seq[idx - 1] == 'L')
                wx0, ww = win_at(bx0, first)
                srcs, loc = (w1_kit if first else w2_kit), (wx0, 0.0, z0 + WIN_SILL)
            for src in srcs:
                link_dup(src, '%s_f%d_b%d' % (src.name, fl, idx), loc=loc, coll=inst)
                link_dup(back_kit[src.name],
                         '%s_f%d_b%d' % (src.name, fl, idx + BACK_BAY),
                         loc=loc, coll=inst)
    return coll, inst, (loggia_kit, w1_kit, w2_kit), L, A_DEPTH


# ------------------------------------------------------------------ block B
# The east wing projects toward the street at the end of block A. Its return
# wall - the face that looks back down the street at the camera - is read off
# the photograph from the junction toward the corner: a pale pier, one wide
# loggia, a pale pier, a slot window, two wide two-light windows, a pale pier,
# a narrow loggia, and the dark corner pier. The street elevation is an open
# concrete gallery of three bays that starts 1.1 m east of the corner.
B_X0, B_X1 = A_LEN, 74.90
B_Y0    = -17.20               # street face of the wing
B_ROOF  = 35.60
B_TOP   = B_ROOF - 1.30        # head of the top gallery opening
B_GAL_X = 1.10                 # gallery starts this far east of the corner
B_GD    = 2.70                 # gallery depth
B_CW    = 0.30                 # half width of a gallery column
B_CF    = 0.40                 # concrete face of a column, in from the front
B_NB    = 3                    # gallery bays
# return wall cells from the junction (y=0) toward the corner (y=B_Y0):
# P pale pier | L loggia opening | S slot window | W two-light window.
# Anything between two cells is plain dark wall.
B_RET = [('P', -0.70, -1.56), ('L', -1.56, -5.61), ('P', -5.61, -6.30),
         ('S', -6.30, -7.30), ('W', -8.40, -9.80), ('W', -11.25, -12.70),
         ('P', -13.75, -14.40), ('L', -14.40, -16.40)]
B_WIN_H, B_WIN_SILL = WIN_H, WIN_SILL      # the two-light windows are block A's
B_SLOT_H, B_SLOT_SILL = 1.60, 0.05         # the stair slot sits on the floor


def build_block_b(kit):
    coll = collection('blockB')
    kit_coll = collection('kit')
    x0, x1 = B_X0, B_X1
    y0, y1 = B_Y0, 0.0
    XW = x0 + WALL_T                      # inner face of the return wall
    XM = x0 + WALL_T + LOG_D + 0.24       # mass front, behind the loggia shells
    XG = x0 + B_GAL_X                     # first gallery column
    GD = B_GD
    NB = B_NB
    GY0, GY1 = y0 + GD, y0 + GD + WALL_T  # gallery back wall
    TOP = GROUND_H + N_FLOORS * FLOOR_H   # top of the residential floors
    bay = (x1 - XG) / NB

    # ---- kits: one loggia module per opening width, one window module per
    #      window width, the gallery fit-out; all hidden sources
    gal_kit = make_gallery_module(kit_coll, bay - 2 * B_CW, GD + 0.30, 'B_gal')
    log_kits, win_kits = {}, {}
    for kind, ya, yb in B_RET:
        w = round(ya - yb, 3)
        if kind == 'L' and w not in log_kits:
            log_kits[w] = make_loggia_module(kit_coll, w, 'B%d' % len(log_kits),
                                             back='plaster_dark')
        elif kind in 'SW' and (kind, w) not in win_kits:
            nm = 'winC%d' % len(win_kits)
            hh = B_SLOT_H if kind == 'S' else B_WIN_H
            win_kits[(kind, w)] = (make_window_module(kit_coll, w, nm, hh),
                                   make_lit_glass(kit_coll, w, nm, hh))
    hide = list(gal_kit)
    for k in log_kits.values():
        hide += k
    for (k, lit) in win_kits.values():
        hide += list(k) + [lit]
    for o in hide:
        o.hide_render = True
        o.hide_viewport = True

    # ---- the return wall, cell by cell
    cells, yh = [], y1
    for kind, ya, yb in B_RET:
        if ya < yh - 1e-6:
            cells.append(('D', yh, ya))
        cells.append((kind, ya, yb))
        yh = yb
    if yh > y0 + 1e-6:
        cells.append(('D', yh, y0))                 # corner pier

    darkB = MB(); paleB = MB()
    for kind, ya, yb in cells:
        w = round(ya - yb, 3)
        if kind == 'P':
            paleB.box((x0, yb, GROUND_H), (XM, ya, TOP))
            continue
        for fl in range(N_FLOORS):
            z0 = GROUND_H + fl * FLOOR_H
            z1 = z0 + FLOOR_H
            if kind == 'L':
                # the dark band over the opening, in two depth layers in
                # front of the pale soffit, exactly as on block A
                darkB.box((x0, yb, z0 + LOG_H), (x0 + LOG_CY, ya, z1))
                darkB.box((x0 + LOG_CY, yb - LOG_RET, z0 + LOG_H),
                          (x0 + LOG_SY, ya + LOG_RET, z1))
                for src in log_kits[w]:
                    link_dup(src, '%s_f%d_y%d' % (src.name, fl, int(-ya * 100)),
                             loc=(x0, ya, z0), rot_z=-math.pi / 2, coll=coll)
            elif kind in 'SW':
                (glass, frame, sill), lit = win_kits[(kind, w)]
                sl = B_SLOT_SILL if kind == 'S' else B_WIN_SILL
                hh = B_SLOT_H if kind == 'S' else B_WIN_H
                frame_for_yz(yb, ya, z0, z1, yb, ya, z0 + sl, z0 + sl + hh,
                             x0, XW, darkB)
                darkB.box((XW, yb, z0), (XM, ya, z1))
                pane = lit if rnd.random() < 0.18 else glass
                for src in (pane, frame, sill):
                    link_dup(src, '%s_f%d_y%d' % (src.name, fl, int(-ya * 100)),
                             loc=(x0, ya, z0 + sl),
                             rot_z=-math.pi / 2, coll=coll)
            else:
                darkB.box((x0, yb, z0), (XM, ya, z1))
    darkB.box((x0, y0, 0.0), (XM, y1, GROUND_H))     # ground storey, behind the podium
    darkB.box((x0, y0, TOP), (XM, y1, B_ROOF))       # parapet band

    # ---- the rest of the wing: the mass behind everything, the east end
    darkB.box((XM, GY1, 0.0), (x1 - WALL_T, y1, B_ROOF))
    darkB.box((x1 - WALL_T, y0, 0.0), (x1, y1, B_ROOF))

    # ---- gallery frame. The floor bands stand 40 mm proud of the columns so
    #      nothing on the street face shares a plane. Each column is pale only
    #      for its first 40 cm; from there back it is the dark wall, so the
    #      bays read as deep shadow with a slab edge, as they do in the photo.
    #      The corner column keeps only its pale face: behind it the corner
    #      loggia of the return wall and the first gallery bay share the
    #      corner, with the loggia's back wall as the divider between them.
    gal = MB()
    for fl in range(N_FLOORS):
        z = GROUND_H + fl * FLOOR_H
        gal.box((XG, y0 - 0.34, z - 0.22), (x1, y0 + GD, z - 0.004))
    for k in range(NB + 1):
        x = XG + k * bay
        gal.box((x - B_CW, y0 - 0.30, 0.0), (x + B_CW, y0 + B_CF, B_TOP))
        if k > 0:
            darkB.box((x - B_CW, y0 + B_CF, 0.0), (x + B_CW, GY0, B_TOP))
    gal.box((XG, y0 - 0.30, B_TOP), (x1, y0 + B_CF, B_ROOF))
    gal.box((XM, y0 + B_CF, B_TOP), (x1, y0 + GD, B_ROOF))
    gal.box((XG, y0 - 0.34, 0.0), (x1, y0, GROUND_H - 0.30))
    gal.to_object('B_gallery', M('concrete_frame'), coll)

    # ---- back wall of the gallery: a door and a window to every bay, split
    #      into two cells so each opening gets its own reveal
    for fl in range(N_FLOORS):
        z0 = GROUND_H + fl * FLOOR_H
        for k in range(NB):
            a, b = XG + k * bay + B_CW, XG + (k + 1) * bay - B_CW
            a = max(a, XM)
            q = (a + b) * .5 - GAL_OP * .5
            dx0, dx1 = q + 0.14, q + 0.14 + GAL_DW
            wx0, wx1 = q + 1.44, q + 1.44 + GAL_WW
            sx = (dx1 + wx0) * .5
            frame_for(a, sx, z0, z0 + FLOOR_H, dx0, dx1,
                      z0 + 0.12, z0 + GAL_H, GY0, GY1, darkB)
            frame_for(sx, b, z0, z0 + FLOOR_H, wx0, wx1,
                      z0 + GAL_WS, z0 + GAL_H, GY0, GY1, darkB)
            place_bay(gal_kit, coll, 'f%d_k%d' % (fl, k),
                      (XG + k * bay + B_CW, y0 - 0.30, z0))
    darkB.panel(XM, x1, 0.0, GROUND_H, GY0, GY1)
    darkB.to_object('B_dark', M('plaster_dark_b'), coll)
    paleB.to_object('B_piers', M('concrete_loggia'), coll)
    return coll
