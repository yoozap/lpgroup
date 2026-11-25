#!/usr/bin/env python3
"""Turn the architect's plans PDF into machine-readable geometry.

    python3 tools/plan_extract.py [blender/plans/plans.pdf] [--pages 4,5] [--no-check] [--out plan.json]

Input : blender/plans/plans.pdf  (13 A3 pages, vector, "Page rot 90")
Output: blender/plans/plan.json  (metres, one building frame)
        blender/plans/check/level_XX.png  (page raster | extraction, same scale)

Needs poppler (pdftocairo, pdftotext, pdftoppm) and python3 with numpy,
shapely>=2, PIL.  No PyMuPDF.

FRAME
    origin  = intersection of the first lettered axis (Georgian "a") and
              numbered axis 1.
    x       = along the lettered axes (the long direction of the bar),
              metres, increasing from axis "a" to axis "J" (page left->right).
    y       = along the numbered axes, metres, increasing from axis 1 to
              axis 10 (page top->bottom).  Axis 10 / large y is the STREET
              side (the podium front; the straight-on render 006 looks
              from +y towards -y, with the wing on the right = +x).
    NOTE: (x right, y down) as drawn is a mirror of the usual
    (x east, y north) map view.  Plot with y pointing down to see the
    drawing as printed; to build in Blender with z up and a right-handed
    frame use (X, Y, Z) = (x, -y, z).
    z       = the level's own elevation label (+8.100 etc.), metres.

HOW
    pdftocairo -svg applies the page rotation once, so SVG, pdftotext
    -bbox and pdftoppm rasters all share one landscape (1191 x 842 pt)
    space; everything below works in that space and converts to metres in
    one place (Page.to_m) using the grid of that page.

    Path classes (stroke width / fill colour) used by the drawing:
        fill 49.8% grey, no stroke ........ wall + column poche (cut walls)
        stroke 0.425, 49.8% grey .......... grid lines (dashed, exploded)
        stroke 0.992 black, circles ....... axis bubbles
        fill 90.98% / 79.99% grey ......... flat (and office) net-area
                                            polygons, balconies, loggias
                                            (alternating tones per flat)
        fill 59.99% grey .................. common corridor + stair halls
        stroke 0.708 black ................ wall outlines
        stroke 0.368 black ................ everything thin (furniture,
                                            door leaves + arcs, glazing,
                                            stair treads, dimensions)
        stroke 0.12 red ................... site boundary (1 polyline) and
                                            column centre ticks
    The flat polygons are the architect's own area polygons: their areas
    equal the printed inner areas to 0.15 m2 (190 of 191 in-plan labels),
    so they are taken as-is rather than reconstructed from walls.

plan.json (all lengths m, polygons {"outline": [[x, y], ...], "holes": [...]})
    meta      frame, joint, core centres, label fixes applied
    grid      x_axes [{label, label_ka, x}], y_axes [{label, y}],
              per_page {pt_per_m, origin_pt, x/y residuals, site check}
    site      boundary polyline (red line, identical on all 13 sheets)
    levels[]  page, level, name, z, floor_to_floor, kind, outline,
              walls {poche: polygons, segments: [{a, b, t, cls, sides}]},
              columns [{c, size}], doors [{hinge, closed_end, open_end,
              width, opens_into, from_side}], openings (exterior wall gaps),
              facade (outline walked: wall / open runs), stairs (flights,
              rises_towards), lifts, lobbies, core_summary, corridor,
              common_loggias, terraces, table, ... ; parking/commercial:
              floor_area, cores, ramps, parking_spaces
    flats[]   number, drawn_label, page, level, z, floor, block (A left /
              B right of the joint), part (bar_W, bar_E, wing), core,
              polygon, area_polygon, table {inner, balcony, total},
              label {...}, balconies[], entrance[] (or entrance_suggested),
              doors[], windows[], rooms[] (wall-bounded, cut at door leaves)
    offices[] same record for the 12 offices on +4.800
    anomalies[] every disagreement between drawing, in-plan label and table

LIMITS (see the survey report): rooms are geometric only (the drawing
prints no room names or room areas); window sills/heights are not in a
plan; door "how" says whether the leaf line was found.
"""
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict

import numpy as np
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, 'blender', 'plans')
PDF = os.path.join(OUT_DIR, 'plans.pdf')

# ---------------------------------------------------------------- constants
# Georgian axis letters as the legacy font transliterates them
# (a b g d e z T i k l m n o p J = ა ბ გ დ ე ზ თ ი კ ლ მ ნ ო პ ჟ; "v"/ვ is
# skipped by the architect, as usual).
LETTERS = ['a', 'b', 'g', 'd', 'e', 'z', 'T', 'i', 'k', 'l', 'm', 'n', 'o', 'p', 'J']
LETTERS_KA = ['ა', 'ბ', 'გ', 'დ', 'ე', 'ზ', 'თ', 'ი', 'კ', 'ლ', 'მ', 'ნ', 'ო', 'პ', 'ჟ']
NUMBERS = [str(i) for i in range(1, 11)]
# nominal axis coordinates (m) from the dimension strings
X_NOM = [0.0, 6.3, 12.6, 18.9, 25.2, 31.5, 37.8, 44.1, 44.7, 51.0, 57.3, 63.6, 69.9, 76.2, 82.5]
Y_NOM = [0.0, 5.5, 11.0, 16.5, 22.8, 29.1, 34.8, 38.5, 44.0, 47.5]

GREY_WALL = 'rgb(49.798584%, 49.798584%, 49.798584%)'
FLAT_FILLS = ('rgb(90.979004%, 90.979004%, 90.979004%)',
              'rgb(79.989624%, 79.989624%, 79.989624%)')
CORR_FILL = 'rgb(59.989929%, 59.989929%, 59.989929%)'
BLACK = 'rgb(0%, 0%, 0%)'
RED = 'rgb(100%, 0%, 0%)'
SHOP_DOOR = 'rgb(83.518982%, 63.519287%, 50.189209%)'   # shopfront doors (L00), stroke 0.51

PAGES = {
    1: dict(level='P-1', z=-3.0, kind='parking', name='parking -3.000'),
    2: dict(level='L00', z=0.0, kind='commercial', name='commercial +0.000'),
    3: dict(level='L01', z=4.8, kind='offices', name='offices +4.800'),
    13: dict(level='ROOF', z=37.8, kind='roof', name='roof +37.800'),
}
for _i, _p in enumerate(range(4, 13)):
    PAGES[_p] = dict(level='L%02d' % (_i + 2), z=round(8.1 + 3.3 * _i, 3),
                     kind='residential', floor=_i + 1,
                     name='residential floor %d +%.3f' % (_i + 1, 8.1 + 3.3 * _i))


# ---------------------------------------------------------------- parsing
_ATTR = re.compile(r'([a-zA-Z\-:]+)="([^"]*)"')
_NUM = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
_TOK = re.compile(r'[MLCZ]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')


def _parse_d(d):
    """SVG path data (M/L/C/Z only - that is all pdftocairo writes) ->
    [(points Nx2, closed, has_curve)].  Cubic segments are flattened to
    8 points."""
    toks = _TOK.findall(d)
    out, cur, curve, i, cmd = [], [], False, 0, None
    while i < len(toks):
        t = toks[i]
        if t in 'MLCZ':
            cmd = t
            i += 1
            if t == 'Z':
                if cur:
                    out.append((cur, True, curve))
                cur, curve = [], False
            elif t == 'M' and cur:
                out.append((cur, False, curve))
                cur, curve = [], False
            continue
        if cmd in ('M', 'L'):
            cur.append((float(toks[i]), float(toks[i + 1])))
            i += 2
        elif cmd == 'C':
            p0 = cur[-1]
            c = [float(v) for v in toks[i:i + 6]]
            i += 6
            for k in range(1, 9):
                t_ = k / 8.0
                a, b, cc, e = (1 - t_) ** 3, 3 * (1 - t_) ** 2 * t_, 3 * (1 - t_) * t_ * t_, t_ ** 3
                cur.append((a * p0[0] + b * c[0] + cc * c[2] + e * c[4],
                            a * p0[1] + b * c[1] + cc * c[3] + e * c[5]))
            curve = True
        else:
            i += 1
    if cur:
        out.append((cur, False, curve))
    return out


class Item:
    __slots__ = ('fill', 'stroke', 'sw', 'subs')

    def __init__(self, fill, stroke, sw, subs):
        self.fill, self.stroke, self.sw, self.subs = fill, stroke, sw, subs


def load_items(pdf, page):
    with tempfile.TemporaryDirectory() as td:
        fn = os.path.join(td, 'p.svg')
        subprocess.run(['pdftocairo', '-svg', '-f', str(page), '-l', str(page), pdf, fn], check=True)
        txt = open(fn).read()
    body = txt[txt.index('</defs>'):]
    items = []
    for m in re.finditer(r'<path ([^>]*)/>', body):
        a = dict(_ATTR.findall(m.group(1)))
        subs = _parse_d(a.get('d', ''))
        if 'transform' in a:
            A, B, C, D, E, F = [float(x) for x in _NUM.findall(a['transform'])]
            subs = [([(A * x + C * y + E, B * x + D * y + F) for x, y in s], cl, cv) for s, cl, cv in subs]
        stroke = a.get('stroke')
        items.append(Item(a.get('fill'), stroke,
                          float(a.get('stroke-width', '0')) if stroke else 0.0,
                          [(np.array(s), cl, cv) for s, cl, cv in subs if len(s)]))
    return items


def load_words(pdf, page):
    out = subprocess.run(['pdftotext', '-f', str(page), '-l', str(page), '-bbox', pdf, '-'],
                         capture_output=True, text=True, check=True).stdout
    W = []
    for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', out):
        W.append((float(m[1]), float(m[2]), float(m[3]), float(m[4]), m[5]))
    return W


def ring_poly(pts):
    if len(pts) < 3:
        return None
    p = Polygon(pts)
    if not p.is_valid:
        p = p.buffer(0)
    return p if not p.is_empty else None


def item_polygon(it):
    """Even-odd composition of the item's sub-paths."""
    g = None
    for s, cl, cv in it.subs:
        p = ring_poly(s)
        if p is None or p.area < 1e-6:
            continue
        g = p if g is None else g.symmetric_difference(p)
    return g


def polys_of(g):
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    return [p for p in getattr(g, 'geoms', []) if isinstance(p, Polygon) and not p.is_empty]


# ---------------------------------------------------------------- page / grid
class Page:
    def __init__(self, pdf, n):
        self.n = n
        self.meta = PAGES[n]
        self.items = load_items(pdf, n)
        self.words = load_words(pdf, n)
        self.grid = self._grid()

    # --- grid: grey 0.425 dashed lines, labelled from the bubbles
    def _grid(self):
        V, H = defaultdict(float), defaultdict(float)
        for it in self.items:
            if it.fill not in (None, 'none') or it.sw != 0.425 or it.stroke != GREY_WALL:
                continue
            for s, cl, cv in it.subs:
                for a, b in zip(s[:-1], s[1:]):
                    if abs(a[0] - b[0]) < 0.01:
                        V[round(a[0], 2)] += abs(a[1] - b[1])
                    elif abs(a[1] - b[1]) < 0.01:
                        H[round(a[1], 2)] += abs(a[0] - b[0])

        def lines(D, thr):
            ks = sorted(k for k, v in D.items() if v > thr)
            # merge near-duplicates (< 0.3 pt)
            out = []
            for k in ks:
                if out and k - out[-1][-1] < 0.3:
                    out[-1].append(k)
                else:
                    out.append([k])
            return [float(np.mean(g)) for g in out]
        xs, ys = lines(V, 100), lines(H, 100)
        # bubbles: circles, stroke 0.992, ~7.5 pt
        bub = []
        for it in self.items:
            if it.sw != 0.992:
                continue
            for s, cl, cv in it.subs:
                if cv and 6 < np.ptp(s[:, 0]) < 9 and abs(np.ptp(s[:, 0]) - np.ptp(s[:, 1])) < 0.5:
                    bub.append(((s[:, 0].min() + s[:, 0].max()) / 2, (s[:, 1].min() + s[:, 1].max()) / 2))
        labels = {}
        for x0, y0, x1, y1, t in self.words:
            if t in LETTERS or t in NUMBERS:
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                for bx, by in bub:
                    if abs(bx - cx) < 3 and abs(by - cy) < 3:
                        labels.setdefault(t, []).append((bx, by))
        # lettered axes: vertical lines; numbered: horizontal
        if len(xs) != 15 or len(ys) != 10:
            raise RuntimeError('page %d: %d vertical / %d horizontal grid lines' % (self.n, len(xs), len(ys)))
        # check bubble letters agree with the order (k is drawn offset - skip it)
        for L, x in zip(LETTERS, xs):
            if L == 'k' or L not in labels:
                continue
            bx = min(labels[L], key=lambda b: abs(b[0] - x))[0]
            assert abs(bx - x) < 1.0, (self.n, L, bx, x)
        for L, y in zip(NUMBERS, ys):
            if L in labels:
                by = min(labels[L], key=lambda b: abs(b[1] - y))[1]
                assert abs(by - y) < 1.0, (self.n, L, by, y)
        # scale: least squares on the 14 lettered intervals (fixed by the
        # 6,300 strings) - the numbered spacing is then a check.
        xn = np.array(X_NOM)
        A = np.vstack([xn, np.ones_like(xn)]).T
        (s, ox), *_ = np.linalg.lstsq(A, np.array(xs), rcond=None)
        oy = ys[0]
        self.s, self.ox, self.oy = float(s), float(ox), float(oy)
        res_x = [(L, round(float((x - ox) / s), 4), round(float((x - ox) / s - n_), 4)) for L, x, n_ in zip(LETTERS, xs, X_NOM)]
        res_y = [(L, round(float((y - oy) / s), 4), round(float((y - oy) / s - n_), 4)) for L, y, n_ in zip(NUMBERS, ys, Y_NOM)]
        return dict(pt_per_m=round(float(s), 5), origin_pt=[round(float(ox), 3), round(float(oy), 3)],
                    x_axes=res_x, y_axes=res_y, xs_pt=xs, ys_pt=ys)

    def to_m(self, X, Y):
        return ((np.asarray(X) - self.ox) / self.s, (np.asarray(Y) - self.oy) / self.s)

    def pts_m(self, pts):
        pts = np.asarray(pts, dtype=float)
        return np.column_stack(self.to_m(pts[:, 0], pts[:, 1]))

    def geom_m(self, g):
        """shapely geometry in pt -> metres."""
        from shapely import affinity
        return affinity.affine_transform(g, [1 / self.s, 0, 0, 1 / self.s, -self.ox / self.s, -self.oy / self.s])


# ---------------------------------------------------------------- text
_AREA = re.compile(r'^\d+(\.\d+)?$')


def area_labels(pg):
    """'12.3 m 2' labels in the drawing area -> [(x, y, value)] (pt)."""
    W = [w for w in pg.words if w[0] < 905]
    out = []
    for i, w in enumerate(W):
        t = w[4]
        tt = t[:-1] if t.endswith('m') else t
        if not _AREA.match(tt) or '.' not in tt:
            continue
        # must be followed by "m" (or glued "m")
        ok = t.endswith('m') or any(v[4] == 'm' and 0 <= v[0] - w[2] < 1.5 and abs(v[1] - w[1]) < 1.0 for v in W)
        if ok:
            out.append(((w[0] + w[2]) / 2, (w[1] + w[3]) / 2, float(tt), w))
    return out


def unit_labels(pg, word):
    """'bina 12' / 'ofisi 3' label blocks in the drawing area.

    A block is two lines:   bina N   TOTAL m2
                            INNER m2 BALCONY m2
    Returns [dict(name, x, y (pt, block centre), total, inner, balcony)]."""
    W = [w for w in pg.words if w[0] < 905]
    out = []
    for w in W:
        if w[4] != word:
            continue
        x0, y0, x1, y1 = w[:4]
        h = y1 - y0
        nxt = [v for v in W if abs(v[1] - y0) < 0.5 and 0 < v[0] - x1 < 2.5]
        if not nxt:
            continue
        name = nxt[0][4]
        nums = []
        for v in W:
            if x0 - 1.5 < v[0] < x0 + 6.5 * h * 2.6 and y0 - 0.6 < v[1] < y0 + 2.6 * h:
                t = v[4][:-1] if v[4].endswith('m') else v[4]
                if re.match(r'^\d+\.\d$', t):
                    nums.append((0 if abs(v[1] - y0) < h * 0.6 else 1, v[0], float(t), v))
        nums.sort()
        rows = defaultdict(list)
        for r, x, val, v in nums:
            rows[r].append(val)
        rk = sorted(rows)
        total = rows[rk[0]][0] if rk else None
        inner = rows[rk[1]][0] if len(rk) > 1 else None
        balc = rows[rk[1]][1] if len(rk) > 1 and len(rows[rk[1]]) > 1 else None
        allx = [v[3][2] for v in nums] + [x1]
        ally = [v[3][3] for v in nums] + [y1]
        out.append(dict(name=name, x=(x0 + max(allx)) / 2, y=(y0 + max(ally)) / 2,
                        bbox=[x0, y0, max(allx), max(ally)], total=total, inner=inner, balcony=balc))
    return out


def area_table(pg, word):
    """The table on the right of the sheet -> {name: (inner, balcony, total)}
    plus the common-area line ('sadarbazo da kibis ujredi')."""
    W = [w for w in pg.words if w[0] > 905 and 200 < w[1] < 560]
    rows = defaultdict(list)
    for w in W:
        rows[round(w[1])].append(w)
    tab, extra = {}, {}
    for y in sorted(rows):
        r = sorted(rows[y])
        txt = [w[4] for w in r]
        if txt and txt[0] == word and len(txt) > 1:
            vals = [float(t[:-1] if t.endswith('m') else t) for t in txt[2:] if re.match(r'^\d+\.\d+m?$', t)]
            tab[txt[1]] = dict(inner=vals[0] if len(vals) > 0 else None,
                               balcony=vals[1] if len(vals) > 1 else None,
                               total=vals[2] if len(vals) > 2 else None, row_y=y)
        elif txt and txt[0] in ('sadarbazo', 'sazafxulo', 'komerciuli', 'avtosadgomi'):
            vals = [float(t.replace(' ', '')) for t in txt if re.match(r'^\d+\.\d+$', t)]
            extra[' '.join(t for t in txt if not re.match(r'^[\d.]+$', t) and t not in ('m', '2'))] = vals[-1] if vals else None
    return tab, extra


# ---------------------------------------------------------------- geometry helpers
MITRE = dict(join_style=2, mitre_limit=10.0)


def close_m(g, r):
    """Morphological closing (mitre joints keep the right angles)."""
    d = g.buffer(r, **MITRE)
    d = d.buffer(0.02, **MITRE).buffer(-0.02, **MITRE)   # kill zero-width slits left by the union
    return d.buffer(-r, **MITRE)


def rnd(v, k=3):
    return round(float(v), k)


def ring_list(p, k=3):
    """Polygon -> [[x, y], ...] (exterior, not repeated)."""
    c = list(p.exterior.coords)[:-1]
    return [[rnd(x, k), rnd(y, k)] for x, y in c]


def poly_json(p, k=3):
    p = p.simplify(0.005)
    d = dict(outline=ring_list(p, k))
    if p.interiors:
        d['holes'] = [[[rnd(x, k), rnd(y, k)] for x, y in list(h.coords)[:-1]] for h in p.interiors]
    return d


def collect_fills(pg, fills):
    out = []
    for it in pg.items:
        if it.fill not in fills:
            continue
        g = item_polygon(it)
        for p in polys_of(g):
            pm = pg.geom_m(p)
            if pm.area > 1e-4:
                out.append((pm, it.fill))
    return out


def wall_poche(pg, region):
    """Union of the grey wall/column poche inside `region` (metres)."""
    ps = []
    for it in pg.items:
        if it.fill != GREY_WALL:
            continue
        for p in polys_of(item_polygon(it)):
            pm = pg.geom_m(p)
            if pm.area > 1e-4 and region.intersects(pm):
                ps.append(pm)
    return unary_union(ps).buffer(0.002, **MITRE).buffer(-0.002, **MITRE) if ps else Polygon()


# ---------------------------------------------------------------- units (flats / offices)
def extract_units(pg, word):
    """Flat (or office) polygons from the architect's area fills, matched to
    the in-plan label blocks; the rest of the tone fills become balconies /
    loggias and are attached to the flat they adjoin."""
    region = box(-2, -2, 84.5, 49.5)
    fills = [(p, f) for p, f in collect_fills(pg, FLAT_FILLS) if region.contains(p.representative_point())]
    corr = [p for p, f in collect_fills(pg, (CORR_FILL,)) if region.contains(p.representative_point())]
    labels = unit_labels(pg, word)
    for u in labels:
        u['xm'], u['ym'] = [float(v) for v in pg.to_m(u['x'], u['y'])]
    # label -> fill containing the label centre (else nearest big fill)
    used = {}
    units = []
    for u in labels:
        pt = Point(u['xm'], u['ym'])
        cand = [i for i, (p, f) in enumerate(fills) if p.contains(pt) and p.area > 15]
        if not cand:
            cand = sorted((i for i, (p, f) in enumerate(fills) if p.area > 15), key=lambda i: fills[i][0].distance(pt))[:1]
            how = 'nearest(%.2f m)' % fills[cand[0]][0].distance(pt) if cand else 'none'
        else:
            how = 'contains'
        if not cand:
            continue
        i = cand[0]
        if i in used:
            units[used[i]].setdefault('also_labelled', []).append(u['name'])
            continue
        used[i] = len(units)
        p, f = fills[i]
        units.append(dict(name=u['name'], poly=p, tone=f, label=u, match=how))
    rest = [(p, f) for i, (p, f) in enumerate(fills) if i not in used]
    return units, rest, corr


def attach_balconies(units, rest, footprint, alabels, common):
    """Every unlabelled tone fill is a balcony or loggia (they all carry an
    area label).  It belongs to whatever lies behind the wall it touches:
    the unit (or the common hall) with the longest boundary contact within
    0.75 m.  kind = 'balcony' if it projects past the closed footprint,
    'loggia' if it is recessed into it."""
    out = []
    for p, f in rest:
        outside = p.difference(footprint).area / p.area
        ring = p.exterior
        best, bv = None, 0.0
        cands = [(k, u['poly']) for k, u in enumerate(units)] + [('common', common)]
        for k, g in cands:
            if g.is_empty or g.distance(p) > 0.75:
                continue
            v = ring.intersection(g.buffer(0.75, **MITRE)).length
            if v > bv:
                best, bv = k, v
        lab = [a for a in alabels if p.buffer(0.05).contains(Point(a[0], a[1]))]
        out.append(dict(poly=p, unit=best, kind='balcony' if outside > 0.5 else 'loggia',
                        outside=outside, label_area=lab[0][2] if lab else None))
    return out


# ---------------------------------------------------------------- check images
CHECK_BOX = (-4.0, -4.0, 87.0, 52.0)   # metres
CHECK_DPI = 170


def page_raster(pg, pdf):
    from PIL import Image
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(['pdftoppm', '-f', str(pg.n), '-l', str(pg.n), '-r', str(CHECK_DPI), '-png', pdf,
                        os.path.join(td, 'r')], check=True)
        fn = [f for f in os.listdir(td) if f.endswith('.png')][0]
        im = Image.open(os.path.join(td, fn)).convert('RGB')
        im.load()
    k = CHECK_DPI / 72.0
    x0, y0, x1, y1 = CHECK_BOX
    X0, Y0 = pg.ox + x0 * pg.s, pg.oy + y0 * pg.s
    X1, Y1 = pg.ox + x1 * pg.s, pg.oy + y1 * pg.s
    return im.crop((int(X0 * k), int(Y0 * k), int(X1 * k), int(Y1 * k))), pg.s * k


def tone(i):
    import colorsys
    h = (i * 0.618034) % 1.0
    r, g, b = colorsys.hsv_to_rgb(h, 0.45, 0.95)
    return (int(r * 255), int(g * 255), int(b * 255))


class Canvas:
    def __init__(self, size, pxm):
        from PIL import Image, ImageDraw, ImageFont
        self.im = Image.new('RGB', size, 'white')
        self.d = ImageDraw.Draw(self.im)
        self.k = pxm
        try:
            self.font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 11)
            self.big = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf', 13)
        except Exception:
            self.font = self.big = ImageFont.load_default()

    def P(self, x, y):
        return ((x - CHECK_BOX[0]) * self.k, (y - CHECK_BOX[1]) * self.k)

    def poly(self, g, fill=None, outline=None, width=1):
        for p in polys_of(g) if not isinstance(g, list) else g:
            pts = [self.P(x, y) for x, y in p.exterior.coords]
            self.d.polygon(pts, fill=fill, outline=outline)
            if outline and width > 1:
                self.d.line(pts, fill=outline, width=width)
            for h in p.interiors:
                self.d.polygon([self.P(x, y) for x, y in h.coords], fill='white', outline=outline)

    def line(self, pts, fill='black', width=1):
        self.d.line([self.P(x, y) for x, y in pts], fill=fill, width=width)

    def text(self, x, y, s, fill='black', big=False):
        f = self.big if big else self.font
        X, Y = self.P(x, y)
        w = self.d.textlength(s, font=f)
        self.d.text((X - w / 2, Y - 7), s, fill=fill, font=f)


def save_check(pg, pdf, draw_fn, fn):
    from PIL import Image
    ras, pxm = page_raster(pg, pdf)
    c = Canvas(ras.size, pxm)
    draw_fn(c)
    out = Image.new('RGB', (ras.size[0], ras.size[1] * 2 + 6), (255, 0, 0))
    out.paste(ras, (0, 0))
    out.paste(c.im, (0, ras.size[1] + 6))
    out.save(fn)


# ---------------------------------------------------------------- walls
def rect_decompose(p, q=0.002):
    """Rectilinear polygon -> axis-aligned rectangles (row runs merged
    vertically).  Non-axis edges are approximated by the cell grid."""
    from shapely import contains_xy
    c = np.array(p.exterior.coords)
    xs = sorted(set(np.round(np.concatenate([c[:, 0]] + [np.array(h.coords)[:, 0] for h in p.interiors]) / q).astype(int)))
    ys = sorted(set(np.round(np.concatenate([c[:, 1]] + [np.array(h.coords)[:, 1] for h in p.interiors]) / q).astype(int)))
    xs = np.array(xs) * q
    ys = np.array(ys) * q
    if len(xs) < 2 or len(ys) < 2:
        return []
    cx, cy = (xs[:-1] + xs[1:]) / 2, (ys[:-1] + ys[1:]) / 2
    GX, GY = np.meshgrid(cx, cy)
    inside = contains_xy(p, GX, GY)
    # row runs
    open_runs = {}
    rects = []
    for j in range(len(cy)):
        runs = []
        i = 0
        row = inside[j]
        while i < len(cx):
            if row[i]:
                k = i
                while k + 1 < len(cx) and row[k + 1]:
                    k += 1
                runs.append((i, k))
                i = k + 1
            else:
                i += 1
        new_open = {}
        for r in runs:
            if r in open_runs:
                new_open[r] = open_runs.pop(r)
            else:
                new_open[r] = j
        for r, j0 in open_runs.items():
            rects.append((xs[r[0]], ys[j0], xs[r[1] + 1], ys[j]))
        open_runs = new_open
    for r, j0 in open_runs.items():
        rects.append((xs[r[0]], ys[j0], xs[r[1] + 1], ys[len(cy)]))
    return [r for r in rects if (r[2] - r[0]) > 0.01 and (r[3] - r[1]) > 0.01]


def classify_point(pt, ctx):
    for name, g in ctx:
        if g.contains(pt):
            return name
    return 'outside'


def wall_segments(poche, ctx, min_len=0.05):
    """Poche -> [dict(a, b, t, cls, sides)]  (centreline a->b, thickness t).

    cls: exterior  - one side is outside the building or a balcony/loggia
         party     - two different units, or a unit and the corridor/core
         interior  - the same unit on both sides
         core      - common space (corridor/stair/lift) on both sides
         column    - near-square piece 0.3..0.8 m"""
    segs = []
    for p in polys_of(poche):
        for x0, y0, x1, y1 in rect_decompose(p):
            w, h = x1 - x0, y1 - y0
            if max(w, h) < min_len:
                continue
            horiz = w >= h
            t = h if horiz else w
            if horiz:
                a, b = (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)
            else:
                a, b = ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1)
            sides = []
            for side in (-1, 1):
                got = []
                for f in (0.25, 0.5, 0.75):
                    if horiz:
                        pt = Point(x0 + f * w, (y0 if side < 0 else y1) + side * 0.12)
                    else:
                        pt = Point((x0 if side < 0 else x1) + side * 0.12, y0 + f * h)
                    got.append(classify_point(pt, ctx))
                sides.append(max(sorted(set(got)), key=got.count))   # sorted: ties do not follow the hash seed
            s0, s1 = sides
            if 0.3 <= w <= 0.8 and 0.3 <= h <= 0.8 and abs(w - h) < 0.12:
                cls = 'column'
            elif 'outside' in sides or any(s.startswith('balcony') for s in sides):
                cls = 'exterior'
            elif s0 == s1 and s0.startswith('unit:'):
                cls = 'interior'
            elif s0.startswith('unit:') or s1.startswith('unit:'):
                cls = 'party'
            else:
                cls = 'core'
            segs.append(dict(a=[rnd(a[0]), rnd(a[1])], b=[rnd(b[0]), rnd(b[1])], t=rnd(t), cls=cls,
                             sides=[s0, s1]))
    return segs


# ---------------------------------------------------------------- residential / office storeys
def storey(pg, word, terrace_min=200.0):
    units, rest, corr = extract_units(pg, word)
    terraces = [p for p, f in rest if p.area >= terrace_min]
    rest = [(p, f) for p, f in rest if p.area < terrace_min]
    region = unary_union([u['poly'] for u in units] + corr).buffer(2.0)
    poche = wall_poche(pg, region)
    solid = unary_union([poche] + [u['poly'] for u in units] + corr)
    # close window/door notches (shallow) and small gaps
    footprint = close_m(solid, 0.75)
    if terraces:   # +4.800: the podium roof terrace is not part of the storey
        footprint = footprint.difference(unary_union(terraces).buffer(0.05, **MITRE))
        footprint = footprint.buffer(-0.3, **MITRE).buffer(0.3, **MITRE)
    footprint = max(polys_of(footprint), key=lambda p: p.area)
    footprint = Polygon(footprint.exterior)          # stairs/lifts are inside
    alabels = [(float(pg.to_m(x, y)[0]), float(pg.to_m(x, y)[1]), v) for x, y, v, w in area_labels(pg)]
    corridor = unary_union(corr)
    common = footprint.difference(unary_union([u['poly'] for u in units] + [p for p, f in rest])).difference(poche)
    common = common.buffer(-0.3, **MITRE).buffer(0.3, **MITRE)      # drop notch slivers
    balconies = attach_balconies(units, rest, footprint, alabels, common)
    inner = []
    ctx = [('unit:' + u['name'], u['poly']) for u in units]
    ctx += [('corridor', corridor)]
    ctx += [('balcony:%d' % i, b['poly']) for i, b in enumerate(balconies)]
    ctx += [('inner_fill:%d' % i, b['poly']) for i, b in enumerate(inner)]
    ctx += [('wall', poche), ('core', footprint)]
    segs = wall_segments(poche, ctx)
    extras = storey_details(pg, units, balconies, corridor, poche, footprint, ctx)
    S = dict(units=units, balconies=balconies, inner=inner, corridor=corridor, poche=poche,
             footprint=footprint, segs=segs, alabels=alabels, terraces=terraces)
    S.update(extras)
    return S


def storey_details(pg, units, balconies, corridor, poche, footprint, ctx):
    region = footprint.buffer(0.5)
    arcs = door_arcs(pg, region)
    doors = make_doors(arcs, poche, ctx, door_leaves(pg, region))
    inside = unary_union([u['poly'] for u in units] + [corridor])
    openings = exterior_openings(footprint, poche, inside, balconies, ctx)
    core_region = corridor.buffer(0.1) if not corridor.is_empty else Polygon()
    flights = stair_flights(pg, core_region) if not core_region.is_empty else []
    arrows = stair_arrows(pg, core_region) if not core_region.is_empty else []
    # lift shafts / small enclosed cells of the common area
    cells = []
    if not corridor.is_empty:
        free = corridor.difference(poche)
        er = free.buffer(-0.45, **MITRE)
        for p in polys_of(er):
            q = p.buffer(0.45, **MITRE).intersection(free)
            q = max(polys_of(q), key=lambda a: a.area) if polys_of(q) else None
            if q is None:
                continue
            x0, y0, x1, y1 = q.bounds
            rect = q.area / max((x1 - x0) * (y1 - y0), 1e-9)
            has_stair = any(box(*f['bbox']).intersects(q) for f in flights)
            if 2.0 < q.area < 9.0 and rect > 0.85 and not has_stair:
                # a swing door in the cell makes it a lobby/vestibule, not a shaft
                doored = any(q.buffer(0.05).contains(Point(d['hinge'])) or q.buffer(0.05).contains(Point(d['open_end'])) for d in doors)
                cells.append(dict(poly=q, kind='lobby' if doored else 'lift_shaft', w=rnd(x1 - x0, 2), h=rnd(y1 - y0, 2)))
    # small non-poche voids inside units/footprint that belong to nobody
    occ = unary_union([u['poly'] for u in units] + [b['poly'] for b in balconies] + [corridor, poche])
    voids = []
    for p in polys_of(footprint.difference(occ).buffer(-0.03, **MITRE).buffer(0.03, **MITRE)):
        if p.area > 0.15:
            x0, y0, x1, y1 = p.bounds
            voids.append(dict(poly=p, w=rnd(x1 - x0, 2), h=rnd(y1 - y0, 2)))
    # rooms: unit minus walls, cut at the closed door leaves
    def closer(d):
        h, e = np.array(d['hinge']), np.array(d['closed_end'])
        v = (e - h) / max(np.hypot(*(e - h)), 1e-9)
        return LineString([h - v * 0.15, e + v * 0.15]).buffer(0.04, cap_style=2)
    closers = unary_union([closer(d) for d in doors]) if doors else Polygon()
    for u in units:
        rooms = u['poly'].difference(poche.buffer(0.005)).difference(closers)
        u['rooms'] = sorted([r for r in polys_of(rooms) if r.area > 0.8], key=lambda r: -r.area)
        u['doors'] = [d for d in doors if 'unit:' + u['name'] in (d['opens_into'], d['from_side'])]
        ent = [d for d in u['doors'] if {d['opens_into'], d['from_side']} == {'unit:' + u['name'], 'corridor'}]
        u['entrance'] = ent
        u['windows'] = [o for o in openings if o['serves'] == 'unit:' + u['name']]
    return dict(doors=doors, openings=openings, flights=flights, arrows=arrows, cells=cells, voids=voids)


def draw_storey(c, S, extra=None):
    for t in S.get('terraces', []):
        c.poly(t, fill=(215, 235, 205), outline=(0, 120, 0))
    c.poly(S['footprint'], fill=(245, 245, 245), outline=(0, 0, 0))
    for i, u in enumerate(S['units']):
        c.poly(u['poly'], fill=tone(i), outline=(60, 60, 60))
    for b in S['balconies']:
        col = tone(b['unit']) if isinstance(b['unit'], int) else (120, 120, 120) if b['unit'] == 'common' else (255, 0, 0)
        c.poly(b['poly'], fill=tuple(int(v * 0.8) for v in col), outline=(0, 0, 0))
    for b in S['inner']:
        c.poly(b['poly'], fill=(255, 120, 120), outline=(255, 0, 0))
    c.poly(S['corridor'], fill=(150, 150, 150), outline=(60, 60, 60))
    colors = dict(exterior=(0, 0, 0), party=(200, 0, 0), interior=(0, 0, 220), core=(0, 140, 0), column=(160, 0, 160))
    for s in S['segs']:
        (ax, ay), (bx, by), t = s['a'], s['b'], s['t']
        if ax == bx:
            r = box(ax - t / 2, ay, ax + t / 2, by)
        else:
            r = box(ax, ay - t / 2, bx, ay + t / 2)
        c.poly(r, fill=colors[s['cls']])
    for cell in S.get('cells', []):
        c.poly(cell['poly'], fill=(40, 40, 40) if cell['kind'] == 'lift_shaft' else (120, 200, 120))
    for v in S.get('voids', []):
        c.poly(v['poly'], fill=(255, 255, 0), outline=(0, 0, 0))
    for f in S.get('flights', []):
        x0, y0, x1, y1 = f['bbox']
        c.poly(box(x0, y0, x1, y1), outline=(255, 128, 0), width=3)
    for a in S.get('arrows', []):
        c.line([a['tip'], [a['tip'][0] - a['dir'][0], a['tip'][1] - a['dir'][1]]], fill=(255, 128, 0), width=3)
    for o in S.get('openings', []):
        c.line([o['a'], o['b']], fill=(0, 200, 255) if o['kind'] == 'window' else (255, 0, 255), width=5)
    for d in S.get('doors', []):
        ent = {d['opens_into'], d['from_side']} & {'corridor'}
        col = (255, 0, 0) if ent else (0, 120, 0)
        c.line([d['hinge'], d['closed_end']], fill=col, width=4)
        h = np.array(d['hinge']); e = np.array(d['closed_end'])
    for u in S['units']:
        x, y = u['poly'].representative_point().coords[0]
        c.text(x, y - 0.6, u['name'], big=True)
        c.text(x, y + 0.6, '%.1f' % u['poly'].area)
    if extra:
        extra(c)


# ---------------------------------------------------------------- doors, openings, stairs
def thin_lines(pg, colour=BLACK):
    for it in pg.items:
        if it.stroke == colour and it.fill in (None, 'none'):
            for s, cl, cv in it.subs:
                yield it, pg.pts_m(s), cl, cv


def _arc_fit(m):
    """Least-squares circle through points m -> (centre, r, max error, sweep deg)."""
    A = np.c_[2 * m, np.ones(len(m))]
    b = (m ** 2).sum(1)
    (cx, cy, c), *_ = np.linalg.lstsq(A, b, rcond=None)
    r = math.sqrt(max(c + cx * cx + cy * cy, 0))
    err = float(np.abs(np.hypot(m[:, 0] - cx, m[:, 1] - cy) - r).max())
    ang = float(np.degrees(np.ptp(np.unwrap(np.arctan2(m[:, 1] - cy, m[:, 0] - cx)))))
    return cx, cy, r, err, ang


def _door_arc(m):
    cx, cy, r, err, ang = _arc_fit(m)
    if 0.55 < r < 1.3 and err <= 0.01 and 75 < ang < 105:
        return (np.array([cx, cy]), r, m[0], m[-1])
    return None


def door_arcs(pg, region, colour=BLACK):
    """Quarter-circle door swings (radius 0.55..1.3 m, 75..105 deg).

    A double door is sometimes ONE path holding both swings (the C2 lobby
    door on every storey, a commercial street door): a curve that is not
    one arc is split where both halves are."""
    arcs = []
    for it, m, cl, cv in thin_lines(pg, colour):
        if not cv or len(m) < 6:
            continue
        found = []
        a = _door_arc(m)
        if a is not None:
            found = [a]
        elif len(m) >= 11 and _arc_fit(m)[3] > 0.01:
            for k in range(5, len(m) - 5):
                a1, a2 = _door_arc(m[:k + 1]), _door_arc(m[k:])
                if a1 is not None and a2 is not None:
                    found = [a1, a2]
                    break
        for a in found:
            if region.contains(Point(*a[0])):
                arcs.append(a)
    # de-duplicate (some arcs are drawn twice)
    out = []
    for a in arcs:
        if not any(np.hypot(*(a[0] - o[0])) < 0.03 and abs(a[1] - o[1]) < 0.03 for o in out):
            out.append(a)
    return out


def door_leaves(pg, region, colour=BLACK):
    """Straight thin segments 0.5..1.3 m long (candidate door leaves)."""
    segs = []
    for it, m, cl, cv in thin_lines(pg, colour):
        for a, b in zip(m[:-1], m[1:]):
            L = float(np.hypot(*(b - a)))
            if 0.5 < L < 1.35 and region.contains(Point((a + b) / 2)):
                segs.append((a, b, L))
    return segs


def make_doors(arcs, poche, ctx, leaves=()):
    """Arc -> door.  The leaf is drawn as a straight line from the hinge to
    the OPEN end of the arc; the other arc end is the CLOSED position, on
    the wall line.  If no leaf line is found, fall back to the jambs: past
    the closed end (and behind the hinge) the line runs into wall poche."""
    doors = []
    pb = poche.buffer(0.02)
    for h, r, e1, e2 in arcs:
        how = None
        for a, b, L in leaves:
            if abs(L - r) > 0.12 * r:
                continue
            for p, q in ((a, b), (b, a)):
                if np.hypot(*(p - h)) < 0.06:
                    if np.hypot(*(q - e1)) < 0.1:
                        closed, opn, how = e2, e1, 'leaf'
                    elif np.hypot(*(q - e2)) < 0.1:
                        closed, opn, how = e1, e2, 'leaf'
            if how:
                break
        if not how:
            best = None
            # a double door's two leaves shut onto one point: an arc end
            # that is also another arc's end is a CLOSED end
            others = [q for a2 in arcs if a2[0] is not h for q in (a2[2], a2[3])]
            for c_, o_ in ((e1, e2), (e2, e1)):
                d = (c_ - h) / r
                n = (o_ - h) / r
                score = pb.contains(Point(h - d * 0.08)) + pb.contains(Point(c_ + d * 0.08))
                score -= pb.contains(Point(o_ + n * 0.08))
                score += 2 * any(np.hypot(*(c_ - q)) < 0.06 for q in others)
                if best is None or score > best[0]:
                    best = (score, c_, o_)
            _, closed, opn = best
            how = 'jambs'
        # a door's closed leaf spans an OPENING: wall-free on both sides.
        # Corner baths (same quarter-circle + straight edge glyph) lie
        # along a wall face and fail this.
        v = (closed - h) / r
        nrm = np.array([-v[1], v[0]])
        bad = sum(poche.contains(Point(h + (closed - h) * f_ + nrm * sg * 0.15))
                  for f_ in (0.25, 0.5, 0.75) for sg in (1, -1))
        if bad >= 2:
            continue
        mid = (h + closed) / 2
        d = (closed - h) / r
        n = (opn - h) / r                          # swing side normal
        a_side = classify_point(Point(mid + n * 0.35), ctx)
        b_side = classify_point(Point(mid - n * 0.35), ctx)
        doors.append(dict(hinge=[rnd(h[0]), rnd(h[1])], closed_end=[rnd(closed[0]), rnd(closed[1])],
                          open_end=[rnd(opn[0]), rnd(opn[1])],
                          width=rnd(r, 2), centre=[rnd(mid[0]), rnd(mid[1])],
                          wall_axis='x' if abs(d[0]) > abs(d[1]) else 'y',
                          opens_into=a_side, from_side=b_side, how=how))
    return doors


def exterior_openings(footprint, poche, solid_inside, balconies, ctx, depth=0.75):
    """Gaps in the exterior wall band: windows, balcony/loggia doors."""
    band = footprint.difference(footprint.buffer(-depth, **MITRE))
    gaps = band.difference(poche).difference(solid_inside)
    gaps = gaps.buffer(-0.02, **MITRE).buffer(0.02, **MITRE)
    bal = unary_union([b['poly'] for b in balconies]) if balconies else Polygon()
    out = []
    for g in polys_of(gaps):
        if g.area < 0.04:
            continue
        x0, y0, x1, y1 = g.bounds
        w, h = x1 - x0, y1 - y0
        along_x = w >= h
        width, dep = (w, h) if along_x else (h, w)
        if width < 0.35 or dep < 0.08 or g.area / (w * h) < 0.6:
            continue
        c = g.centroid
        # inward / outward probes perpendicular to the wall
        probes = []
        for sgn in (-1, 1):
            p = Point(c.x, (y0 if sgn < 0 else y1) + sgn * 0.25) if along_x else Point((x0 if sgn < 0 else x1) + sgn * 0.25, c.y)
            probes.append(classify_point(p, ctx))
        inside = [s for s in probes if s not in ('outside',) and not s.startswith('balcony')]
        outside = [s for s in probes if s == 'outside' or s.startswith('balcony')]
        to_bal = any(s.startswith('balcony') for s in probes) or bal.distance(g) < 0.05
        out.append(dict(centre=[rnd(c.x), rnd(c.y)], width=rnd(width, 2), wall_depth=rnd(dep, 2),
                        axis='x' if along_x else 'y',
                        a=[rnd(x0), rnd(c.y)] if along_x else [rnd(c.x), rnd(y0)],
                        b=[rnd(x1), rnd(c.y)] if along_x else [rnd(c.x), rnd(y1)],
                        serves=inside[0] if inside else None,
                        kind='balcony_door_or_window' if to_bal else 'window',
                        probes=probes))
    return out


def stair_flights(pg, region):
    """Stair treads: thin lines 0.9..1.6 m long, parallel, stepping
    0.25..0.35 m.  -> flights with width, going, tread count."""
    T = []
    for it, m, cl, cv in thin_lines(pg):
        for a, b in zip(m[:-1], m[1:]):
            L = float(np.hypot(*(b - a)))
            if not (0.9 < L < 1.7):
                continue
            mid = (a + b) / 2
            if not region.contains(Point(mid)):
                continue
            if abs(a[0] - b[0]) < 0.01:
                T.append(('x', round(L, 2), round(mid[1], 2), mid[0]))   # tread along y, steps along x
            elif abs(a[1] - b[1]) < 0.01:
                T.append(('y', round(L, 2), round(mid[0], 2), mid[1]))
    groups = defaultdict(list)
    for ax, L, line, pos in T:
        groups[(ax, L, line)].append(pos)
    flights = []
    for (ax, L, line), ps in groups.items():
        ps = sorted(ps)
        ded = [ps[0]]
        for p in ps[1:]:
            if p - ded[-1] > 0.05:
                ded.append(p)
        runs, cur = [], [ded[0]]
        for p in ded[1:]:
            if 0.22 < p - cur[-1] < 0.38:
                cur.append(p)
            else:
                runs.append(cur)
                cur = [p]
        runs.append(cur)
        for r in runs:
            if len(r) < 4:
                continue
            going = (r[-1] - r[0]) / (len(r) - 1)
            if ax == 'x':
                bb = [r[0], line - L / 2, r[-1], line + L / 2]
            else:
                bb = [line - L / 2, r[0], line + L / 2, r[-1]]
            flights.append(dict(step_axis=ax, width=L, going=rnd(going, 3), treads=len(r),
                                bbox=[rnd(v) for v in bb]))
    # merge flights that are the same (duplicate lengths 1.196/1.204)
    out = []
    for f in sorted(flights, key=lambda f: -f['treads']):
        if any(f['step_axis'] == o['step_axis'] and box(*f['bbox']).buffer(0.05).intersects(box(*o['bbox'])) and
               box(*f['bbox']).intersection(box(*o['bbox']).buffer(0.05)).area > 0.5 * box(*f['bbox']).area for o in out):
            continue
        out.append(f)
    return out


def stair_arrows(pg, region):
    """Small filled/open arrowheads (3 points) inside the cores -> tip and
    direction (the 'up' direction of the walking line)."""
    out = []
    for it in pg.items:
        for s, cl, cv in it.subs:
            if len(s) != 4 or it.fill in (None, 'none'):
                continue
            m = pg.pts_m(s)[:3]
            if np.ptp(m[:, 0]) > 0.5 or np.ptp(m[:, 1]) > 0.5:
                continue
            c = m.mean(0)
            if not region.contains(Point(c)):
                continue
            # tip = vertex farthest from the other two's midpoint
            best = None
            for i in range(3):
                o = [m[j] for j in range(3) if j != i]
                v = m[i] - (o[0] + o[1]) / 2
                L = np.hypot(*v)
                if best is None or L > best[0]:
                    best = (L, m[i], v / max(L, 1e-9))
            out.append(dict(tip=[rnd(best[1][0]), rnd(best[1][1])], dir=[rnd(best[2][0], 2), rnd(best[2][1], 2)]))
    return out


# ---------------------------------------------------------------- columns, site
def columns(pg, poche):
    """Column centres from the red centre marks: every column carries a red
    cross of four 0.3 m arms plus a tiny centre dash (< 3 cm) - the dash IS
    the centre.  Size = largest square of wall poche around it."""
    pts = []
    for it in pg.items:
        if it.stroke != RED:
            continue
        for s, cl, cv in it.subs:
            m = pg.pts_m(s)
            if len(m) == 2 and np.hypot(*(m[1] - m[0])) < 0.03:
                c = m.mean(0)
                if not any(np.hypot(*(c - p)) < 0.1 for p in pts):
                    pts.append(c)
    cols = []
    for c in pts:
        size = None
        if not poche.is_empty:
            for h in np.arange(0.45, 0.1, -0.025):
                b = box(c[0] - h, c[1] - h, c[0] + h, c[1] + h)
                if poche.intersection(b).area > 0.97 * b.area:
                    size = rnd(2 * h, 3)
                    break
        cols.append(dict(c=[rnd(c[0]), rnd(c[1])], size=size))
    return cols


def site_boundary(pg):
    best = None
    for it in pg.items:
        if it.stroke != RED:
            continue
        for s, cl, cv in it.subs:
            if len(s) >= 20 and (best is None or len(s) > len(best)):
                best = s
    if best is None:
        return None
    m = pg.pts_m(best)
    # pdftocairo may split the same polyline into many collinear pieces
    keep = [m[0]]
    for p in m[1:]:
        if np.hypot(*(p - keep[-1])) > 0.01:
            keep.append(p)
    return LineString(keep).simplify(0.01)


def red_boxes(pg, min_len=6.0):
    out = []
    for it in pg.items:
        if it.stroke != RED:
            continue
        for s, cl, cv in it.subs:
            m = pg.pts_m(s)
            if 4 <= len(m) < 20 and np.hypot(*np.ptp(m, 0)) > min_len:
                out.append(m)
    # the boxes are drawn doubled (two offset outlines) - keep the outer
    polys = []
    for m in out:
        p = Polygon(m).buffer(0)
        if p.is_empty:
            continue
        if any(q.buffer(0.2).contains(p) for q in polys):
            continue
        polys = [q for q in polys if not p.buffer(0.2).contains(q)] + [p]
    return polys


def number_words(pg, lo, hi):
    out = []
    for w in pg.words:
        if w[0] < 905 and w[4].isdigit() and lo <= int(w[4]) <= hi and (w[3] - w[1]) > 2.0:
            x, y = pg.to_m((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
            out.append((int(w[4]), float(x), float(y)))
    return out


def car_symbols(pg, outside_of, lo=100, hi=300, inside=False):
    """At-grade spaces on the +0.000 sheet: the car glyphs (white fills of
    7.5..9 m2) with their numbers; the oriented rectangle of the glyph gives
    position and heading (the painted bay itself is ~2.5 x 5.0 m)."""
    nums = number_words(pg, lo, hi)
    out = []
    for it in pg.items:
        if it.fill != 'rgb(100%, 100%, 100%)':
            continue
        for p in polys_of(item_polygon(it)):
            pm = pg.geom_m(p)
            if not (7.0 < pm.area < 9.5):
                continue
            if outside_of.buffer(-0.5).contains(pm.centroid) != inside:
                continue
            r = pm.minimum_rotated_rectangle
            c = np.array(r.exterior.coords)[:4]
            e0, e1 = c[1] - c[0], c[2] - c[1]
            longv = e0 if np.hypot(*e0) > np.hypot(*e1) else e1
            ang = math.degrees(math.atan2(longv[1], longv[0])) % 180
            near = sorted(nums, key=lambda n: (n[1] - pm.centroid.x) ** 2 + (n[2] - pm.centroid.y) ** 2)
            num = near[0][0] if near and math.hypot(near[0][1] - pm.centroid.x, near[0][2] - pm.centroid.y) < 2.5 else None
            out.append(dict(number=num, centre=[rnd(pm.centroid.x), rnd(pm.centroid.y)], heading_deg=rnd(ang, 1),
                            glyph=[[rnd(x), rnd(y)] for x, y in c]))
    return out


# ---------------------------------------------------------------- open levels (parking, commercial) and roof
def open_level(pg):
    region = box(-8, -3, 86, 50)
    big = [(p, f) for p, f in collect_fills(pg, ('rgb(79.989624%, 79.989624%, 79.989624%)',)) if region.contains(p.representative_point())]
    area = max(big, key=lambda t: t[0].area)[0]
    cores = [p for p, f in collect_fills(pg, (CORR_FILL,)) if region.contains(p.representative_point()) and p.area > 5]
    poche = wall_poche(pg, area.buffer(1.5))
    solid = unary_union([area, poche.intersection(area.buffer(0.6, **MITRE))] + cores)
    footprint = max(polys_of(close_m(solid, 0.75)), key=lambda p: p.area)
    footprint = Polygon(footprint.exterior)
    ctx = [('core:%d' % i, c) for i, c in enumerate(cores)] + [('floor', area), ('wall', poche), ('inside', footprint)]
    segs = wall_segments(poche, ctx)
    doors = make_doors(door_arcs(pg, footprint.buffer(0.5)), poche, ctx, door_leaves(pg, footprint.buffer(0.5)))
    # the street doors of the halls drawn in the shopfront colour (the
    # terrace stair's double door): only inside a core, the shop doors are
    # the street file's
    if cores:
        creg = unary_union(cores).buffer(0.6)
        doors += make_doors(door_arcs(pg, creg, SHOP_DOOR), poche, ctx, door_leaves(pg, creg, SHOP_DOOR))
    openings = exterior_openings(footprint, poche, unary_union([area] + cores), [], ctx)
    flights = stair_flights(pg, unary_union(cores).buffer(0.1)) if cores else []
    parts = hall_partitions(pg, cores, poche, footprint)
    return dict(area=area, cores=cores, poche=poche, footprint=footprint, segs=segs, doors=doors,
                openings=openings, flights=flights, partitions=parts)


def hall_partitions(pg, cores, poche, footprint=None):
    """Walls of the entrance halls that the open sheets draw as a pair of
    0.708 outlines with no poche fill (the C1/C2 lift lobbies, vestibules,
    shaft walls; the C3 east wall). Two parallel outline segments 0.05 to
    0.30 m apart bound a wall where they overlap; T-junctions are closed by
    a 0.11 m morphological closing. Only inside the cores."""
    if not cores:
        return Polygon()
    reg = unary_union(cores).buffer(0.35, **MITRE)
    H, V = [], []          # (offset, lo, hi)
    for it in pg.items:
        if it.stroke != BLACK or abs(it.sw - 0.708) > 0.01:
            continue
        for s, cl, cv in it.subs:
            if cv or len(s) < 2:
                continue
            m = pg.pts_m(s)
            if cl:
                m = np.vstack([m, m[:1]])
            for a, b in zip(m[:-1], m[1:]):
                if not reg.intersects(LineString([a, b])):
                    continue
                if abs(a[1] - b[1]) < 0.01 and abs(a[0] - b[0]) > 0.02:
                    H.append(((a[1] + b[1]) / 2, min(a[0], b[0]), max(a[0], b[0])))
                elif abs(a[0] - b[0]) < 0.01 and abs(a[1] - b[1]) > 0.02:
                    V.append(((a[0] + b[0]) / 2, min(a[1], b[1]), max(a[1], b[1])))
    rects = []
    for segs, horiz in ((H, True), (V, False)):
        segs.sort()
        for i, (o1, l1, h1) in enumerate(segs):
            for o2, l2, h2 in segs[i + 1:]:
                if o2 - o1 > 0.30:
                    break
                if o2 - o1 < 0.05:
                    continue
                lo, hi = max(l1, l2), min(h1, h2)
                if hi - lo < 0.03:
                    continue
                rects.append(box(lo, o1, hi, o2) if horiz else box(o1, lo, o2, hi))
    # columns drawn as outlines inside a core (C1/C2 at the lobby's double
    # door): a 0.3..0.8 m box whose four sides are drawn (60 % or more)
    def cover(segs, off, lo, hi):
        iv = sorted((max(l, lo), min(h, hi)) for o, l, h in segs if abs(o - off) < 0.01 and h > lo and l < hi)
        tot, end = 0.0, lo
        for l, h in iv:
            if h > end:
                tot += h - max(l, end)
                end = h
        return tot / (hi - lo)
    for i, (o1, l1, h1) in enumerate(H):
        for o2, l2, h2 in H[i + 1:]:
            if not (0.3 <= o2 - o1 <= 0.8):
                continue
            lo, hi = max(l1, l2), min(h1, h2)
            if not (0.3 <= hi - lo <= 0.8) or abs((hi - lo) - (o2 - o1)) > 0.12:
                continue
            if cover(V, lo, o1, o2) >= 0.6 and cover(V, hi, o1, o2) >= 0.6:
                rects.append(box(lo, o1, hi, o2))
    if not rects:
        return Polygon()
    g = unary_union(rects)
    g = g.buffer(0.105, **MITRE).buffer(-0.105, **MITRE)
    g = g.intersection(reg).difference(poche)
    if footprint is not None:
        g = g.intersection(footprint)      # outlines drawn past the facade (the ramp's kerb) are not the hall's
    return unary_union([p for p in polys_of(g) if p.area > 0.003 and p.buffer(-0.02, **MITRE).area > 0]) \
        if not g.is_empty else Polygon()


def roof_level(pg):
    region = box(-8, -3, 86, 50)
    fills = sorted([p for p, f in collect_fills(pg, FLAT_FILLS) if region.contains(p.representative_point())], key=lambda p: -p.area)
    roof = unary_union([p for p in fills if p.area > 100])      # the two roofs either side of the joint
    heads = []
    for p in [p for p in fills if p.area <= 100]:
        if p.area > 5 and not any(p.equals_exact(h, 0.01) or p.symmetric_difference(h).area < 0.05 for h in heads):
            heads.append(p)
    poche = wall_poche(pg, roof.buffer(1.0))
    footprint = Polygon(max(polys_of(close_m(unary_union([roof, poche]), 0.3)), key=lambda p: p.area).exterior)
    return dict(roof=roof, heads=heads, poche=poche, footprint=footprint)


def draw_open(c, L):
    c.poly(L['footprint'], fill=(245, 245, 245), outline=(0, 0, 0))
    c.poly(L['area'], fill=(205, 220, 240), outline=(60, 60, 60))
    for k in L['cores']:
        c.poly(k, fill=(150, 150, 150), outline=(60, 60, 60))
    for b in L.get('bays', []):
        c.poly(b['poly'], outline=(0, 0, 255))
        if b['number']:
            x, y = b['poly'].centroid.coords[0]
            c.text(x, y, str(b['number']))
    for r in L.get('ramps', []):
        c.poly(r, outline=(255, 0, 0), width=3)
    colors = dict(exterior=(0, 0, 0), party=(200, 0, 0), interior=(0, 0, 220), core=(0, 140, 0), column=(160, 0, 160))
    for s in L['segs']:
        (ax, ay), (bx, by), t = s['a'], s['b'], s['t']
        r = box(ax - t / 2, ay, ax + t / 2, by) if ax == bx else box(ax, ay - t / 2, bx, ay + t / 2)
        c.poly(r, fill=colors[s['cls']])
    for f in L['flights']:
        c.poly(box(*f['bbox']), outline=(255, 128, 0), width=3)
    for o in L['openings']:
        c.line([o['a'], o['b']], fill=(0, 200, 255), width=5)
    for d in L['doors']:
        c.line([d['hinge'], d['closed_end']], fill=(0, 120, 0), width=4)
    for k in L.get('cols', []):
        x, y = k['c']
        h = (k['size'] or 0.3) / 2
        c.poly(box(x - h, y - h, x + h, y + h), fill=(255, 0, 255))
    for cs in L.get('cars', []):
        c.poly(Polygon(cs['glyph']), outline=(0, 0, 200))
        if cs['number']:
            c.text(cs['centre'][0], cs['centre'][1], str(cs['number']))


def facade_runs(footprint, poche, ctx, step=0.05, probe=0.12):
    """Walk the footprint outline; a sample whose inward probe is in wall
    poche is 'wall', otherwise 'open' (window, door, shop glazing, loggia
    mouth).  Consecutive samples are merged into runs a->b."""
    runs = []
    pb = poche.buffer(0.01)
    ring = footprint.exterior
    if not ring.is_ccw:
        ring = LineString(list(ring.coords)[::-1])
    coords = np.array(ring.coords)
    for a, b in zip(coords[:-1], coords[1:]):
        L = float(np.hypot(*(b - a)))
        if L < 1e-6:
            continue
        t = (b - a) / L
        inward = np.array([-t[1], t[0]])        # CCW ring -> left side is inside
        n = max(int(L / step), 1)
        cur = None
        for k in range(n):
            s0, s1 = k * L / n, (k + 1) * L / n
            m = a + t * (s0 + s1) / 2
            p = Point(m + inward * probe)
            state = 'wall' if pb.contains(p) else 'open'
            if cur and cur['state'] == state:
                cur['b'] = a + t * s1
            else:
                if cur:
                    runs.append(cur)
                cur = dict(state=state, a=a + t * s0, b=a + t * s1, behind=None)
                if state == 'open':
                    cur['behind'] = classify_point(Point(m + inward * 0.6), ctx)
        if cur:
            runs.append(cur)
    out = []
    for r in runs:
        L = float(np.hypot(*(r['b'] - r['a'])))
        if L < 0.02:
            continue
        out.append(dict(state=r['state'], a=[rnd(r['a'][0]), rnd(r['a'][1])], b=[rnd(r['b'][0]), rnd(r['b'][1])],
                        length=rnd(L, 3), behind=r['behind']))
    return out


# ---------------------------------------------------------------- assembly
# In-plan label corrections, each justified in the report:
#  p4 (+8.100): the wing-end flat is printed "bina 30" (a copy of floor 2's
#  label) but sits between 8 and 10 in the number sequence of the sheet, the
#  sheet's table has a row 9 and no row 30, and floor 2's flat 30 is on
#  another sheet.  -> 9.
LABEL_FIXES = {4: {'30': '9'}}
JOINT_X = 44.4          # centre of the 600 mm expansion joint (axes i | k)
CORES = {               # stair cores, by the centre of their stair flights
    'C1': (15.55, 1.5),     # bar, axes g-d, rows 1-2 (left of the joint)
    'C2': (66.95, 1.5),     # bar, axes n-o, rows 1-2 (right of the joint)
    'C3': (79.55, 20.5),    # wing, axes p-J, rows 4-5
}


def core_of(pt):
    return min(CORES, key=lambda k: math.hypot(CORES[k][0] - pt[0], CORES[k][1] - pt[1]))


def door_json(d):
    return {k: d[k] for k in ('hinge', 'closed_end', 'open_end', 'width', 'centre', 'wall_axis', 'opens_into', 'from_side', 'how')}


def walls_json(poche, segs):
    return dict(poche=[poly_json(p) for p in polys_of(poche) if p.area > 0.005],
                segments=segs)


def build_level_storey(pg, word, notes):
    S = storey(pg, word)
    fix = LABEL_FIXES.get(pg.n, {})
    table, extra = area_table(pg, word)
    # bar south face, for the bar / wing split
    fp = S['footprint']
    bar_south = max(y for x, y in fp.intersection(box(28, -5, 32, 60)).exterior.coords)
    units_out = []
    for k, u in enumerate(S['units']):
        name = fix.get(u['name'], u['name'])
        if name != u['name']:
            notes.append(dict(page=pg.n, kind='label_fixed', drawn=u['name'], used=name))
        c = u['poly'].centroid
        # wing = south of axis 4 (the bar is rows 1-4, the wing rows 4-7)
        part = 'wing' if c.y > Y_NOM[3] else ('bar_W' if c.x < JOINT_X else 'bar_E')
        block = 'A' if c.x < JOINT_X else 'B'
        bals = [b for b in S['balconies'] if b['unit'] == k]
        ent = u['entrance']
        suggested = None
        if not ent and not S['corridor'].is_empty:
            # no door drawn: the stretch of wall the flat shares with the corridor
            shared = u['poly'].buffer(0.6, **MITRE).intersection(S['corridor'].buffer(0.6, **MITRE)).difference(u['poly']).difference(S['corridor'])
            if not shared.is_empty:
                sc = shared.centroid
                suggested = dict(centre=[rnd(sc.x), rnd(sc.y)], shared_wall_length=rnd(shared.area / 0.6, 2),
                                 note='no entrance door drawn on this sheet; centre of the wall shared with the corridor')
        epos = ent[0]['centre'] if ent else (suggested['centre'] if suggested else [rnd(c.x), rnd(c.y)])
        row = table.get(name, {})
        units_out.append(dict(
            number=name, drawn_label=u['label']['name'], page=pg.n, level=pg.meta['level'], z=pg.meta['z'],
            floor=pg.meta.get('floor'), block=block, part=part, core=core_of(epos),
            polygon=poly_json(u['poly']), area_polygon=rnd(u['poly'].area, 2),
            table=dict(inner=row.get('inner'), balcony=row.get('balcony'), total=row.get('total')) if row else None,
            label=dict(inner=u['label']['inner'], balcony=u['label']['balcony'], total=u['label']['total'],
                       at=[rnd(u['label']['xm']), rnd(u['label']['ym'])]),
            balconies=[dict(kind=b['kind'], polygon=poly_json(b['poly']), area=rnd(b['poly'].area, 2),
                            label_area=b['label_area']) for b in bals],
            balcony_area_polygons=rnd(sum(b['poly'].area for b in bals), 2),
            entrance=[door_json(d) for d in ent],
            entrance_suggested=suggested,
            doors=[door_json(d) for d in u['doors']],
            windows=u['windows'],
            rooms=[dict(polygon=poly_json(r), area=rnd(r.area, 2)) for r in u['rooms']],
            tone=u['tone'][4:9]))
    common_balc = [dict(kind=b['kind'], polygon=poly_json(b['poly']), area=rnd(b['poly'].area, 2), label_area=b['label_area'])
                   for b in S['balconies'] if b['unit'] == 'common']
    stairs = []
    for f in S['flights']:
        x0, y0, x1, y1 = f['bbox']
        f = dict(f)
        f['core'] = core_of(((x0 + x1) / 2, (y0 + y1) / 2)) if (y0 < 25) else 'podium'
        ax_i = 0 if f['step_axis'] == 'x' else 1
        up = [a for a in S['arrows'] if box(x0, y0, x1, y1).buffer(0.25).contains(Point(a['tip']))
              and abs(a['dir'][ax_i]) > 0.97]
        f['arrow'] = up[0] if up else None
        # walking line: the arrow head marks the TOP of its flight
        f['rises_towards'] = (('+' if up[0]['dir'][ax_i] > 0 else '-') + f['step_axis']) if up else None
        stairs.append(f)
    lifts = [dict(polygon=poly_json(c['poly']), w=c['w'], h=c['h'], core=core_of(c['poly'].centroid.coords[0]))
             for c in S['cells'] if c['kind'] == 'lift_shaft']
    lobbies = [dict(polygon=poly_json(c['poly']), w=c['w'], h=c['h'], core=core_of(c['poly'].centroid.coords[0]))
               for c in S['cells'] if c['kind'] == 'lobby']
    shafts = [dict(polygon=poly_json(v['poly']), w=v['w'], h=v['h']) for v in S['voids']]
    cols = columns(pg, S['poche'])
    ctx = [('unit:' + u['name'], u['poly']) for u in S['units']] + [('corridor', S['corridor'])]
    level = dict(
        page=pg.n, level=pg.meta['level'], name=pg.meta['name'], z=pg.meta['z'], kind=pg.meta['kind'],
        outline=poly_json(S['footprint']), outline_area=rnd(S['footprint'].area, 1),
        corridor=[poly_json(p) for p in polys_of(S['corridor'])], corridor_area=rnd(S['corridor'].area, 2),
        common_loggias=common_balc,
        common_area_table=extra,
        walls=walls_json(S['poche'], S['segs']),
        columns=cols,
        doors=[door_json(d) for d in S['doors']],
        openings=S['openings'],
        facade=facade_runs(S['footprint'], S['poche'], ctx),
        stairs=stairs, lifts=lifts, lobbies=lobbies, shafts_and_voids=shafts,
        terraces=[poly_json(t) for t in S['terraces']], terrace_areas=[rnd(t.area, 1) for t in S['terraces']],
        units=[u['number'] for u in units_out],
        table={k: dict(inner=v['inner'], balcony=v['balcony'], total=v['total']) for k, v in table.items()},
    )
    return level, units_out, S


def build_level_open(pg, notes):
    L = open_level(pg)
    L['cols'] = columns(pg, L['poche'])
    L['ramps'] = [r for r in red_boxes(pg) if r.area < 400 and r.bounds[0] > 70]
    if pg.n == 1:
        L['cars'] = car_symbols(pg, L['footprint'], 1, 126, True)
    else:
        L['cars'] = car_symbols(pg, L['footprint'], 127, 190, False)
    table, extra = area_table(pg, 'xx')
    ctx = [('floor', L['area'])] + [('core', c) for c in L['cores']]
    stairs = []
    for f in L['flights']:
        x0, y0, x1, y1 = f['bbox']
        f = dict(f)
        f['core'] = core_of(((x0 + x1) / 2, (y0 + y1) / 2)) if y0 < 25 else 'podium'
        stairs.append(f)
    level = dict(
        page=pg.n, level=pg.meta['level'], name=pg.meta['name'], z=pg.meta['z'], kind=pg.meta['kind'],
        outline=poly_json(L['footprint']), outline_area=rnd(L['footprint'].area, 1),
        floor_area=poly_json(L['area']), floor_area_m2=rnd(L['area'].area, 1),
        cores=[dict(polygon=poly_json(c), area=rnd(c.area, 2), core=core_of(c.centroid.coords[0]) if c.centroid.y < 25 else 'podium') for c in L['cores']],
        area_table=extra,
        walls=walls_json(unary_union([L['poche'], L['partitions']]), L['segs']),
        columns=L['cols'], doors=[door_json(d) for d in L['doors']], openings=L['openings'],
        facade=facade_runs(L['footprint'], L['poche'], ctx),
        stairs=stairs,
        ramps=[poly_json(r) for r in L['ramps']],
        parking_spaces=L['cars'],
    )
    if not L['partitions'].is_empty:
        level['walls']['from_outlines_m2'] = rnd(L['partitions'].area, 2)
    return level, L


def build_level_roof(pg):
    R = roof_level(pg)
    marks = []
    for w in pg.words:
        if w[0] < 905 and re.match(r'^[+-]\d+,\d{3}$', w[4]):
            x, y = pg.to_m((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
            marks.append(dict(text=w[4], z=float(w[4].replace(',', '.')), at=[rnd(x), rnd(y)]))
    return dict(page=pg.n, level=pg.meta['level'], name=pg.meta['name'], z=pg.meta['z'], kind='roof',
                outline=poly_json(R['footprint']), outline_area=rnd(R['footprint'].area, 1),
                roof=poly_json(R['roof']), roof_area=rnd(R['roof'].area, 1),
                stair_heads=[dict(polygon=poly_json(h), area=rnd(h.area, 2), core=core_of(h.centroid.coords[0]), z_top=40.2) for h in R['heads']],
                parapets=walls_json(R['poche'], []), level_marks=marks), R


def draw_roof(c, R):
    c.poly(R['footprint'], fill=(245, 245, 245), outline=(0, 0, 0))
    c.poly(R['roof'], fill=(205, 220, 240), outline=(60, 60, 60))
    c.poly(R['poche'], fill=(0, 0, 0))
    for h in R['heads']:
        c.poly(h, fill=(150, 150, 150), outline=(0, 0, 0))


def anomalies_for(units, level, page):
    out = []
    drawn = {u['number'] for u in units}
    for k, v in level['table'].items():
        if k not in drawn:
            out.append(dict(page=page, unit=k, kind='table_row_not_drawn', table=v))
    for u in units:
        t = u['table']
        if t is None:
            out.append(dict(page=page, unit=u['number'], kind='drawn_not_in_table', polygon=u['area_polygon'], label=u['label']))
            continue
        if t['inner'] is not None and abs(u['area_polygon'] - t['inner']) > 0.15:
            out.append(dict(page=page, unit=u['number'], kind='polygon_vs_table_inner', polygon=u['area_polygon'], table=t, label=u['label']))
        if u['label']['inner'] != t['inner'] or u['label']['total'] != t['total'] or u['label']['balcony'] != t['balcony']:
            out.append(dict(page=page, unit=u['number'], kind='label_vs_table', label=u['label'], table=t))
        if t['balcony'] is not None and abs(u['balcony_area_polygons'] - t['balcony']) > 0.25:
            out.append(dict(page=page, unit=u['number'], kind='balcony_polygons_vs_table', polygons=u['balcony_area_polygons'], table=t))
        if not u['entrance']:
            out.append(dict(page=page, unit=u['number'], kind='no_entrance_door_found'))
    return out


def main(argv):
    pdf = PDF
    pages = sorted(PAGES)
    check = True
    args = list(argv)
    if '--no-check' in args:
        check = False
        args.remove('--no-check')
    if '--pages' in args:
        i = args.index('--pages')
        pages = [int(v) for v in args[i + 1].split(',')]
        del args[i:i + 2]
    out_path = os.path.join(OUT_DIR, 'plan.json')
    if '--out' in args:
        i = args.index('--out')
        out_path = args[i + 1]
        del args[i:i + 2]
    if args:
        pdf = args[0]
    os.makedirs(os.path.join(OUT_DIR, 'check'), exist_ok=True)
    levels, flats, offices, notes, grids = [], [], [], [], {}
    poche_by_level = []
    site = None
    for n in pages:
        pg = Page(pdf, n)
        grids[n] = pg.grid
        sb = site_boundary(pg)
        if sb is not None:
            if site is None:
                site = (n, sb)
            else:
                d = site[1].hausdorff_distance(sb)
                grids[n]['site_boundary_vs_page_%d_m' % site[0]] = rnd(d, 3)
        kind = pg.meta['kind']
        fn = os.path.join(OUT_DIR, 'check', 'level_%02d.png' % n)
        if kind in ('residential', 'offices'):
            word = 'bina' if kind == 'residential' else 'ofisi'
            level, units, S = build_level_storey(pg, word, notes)
            poche_by_level.append(S['poche'])
            notes.extend(anomalies_for(units, level, n))
            (flats if kind == 'residential' else offices).extend(units)
            if check:
                fix = LABEL_FIXES.get(n, {})
                for u in S['units']:
                    u['name'] = fix.get(u['name'], u['name'])
                save_check(pg, pdf, lambda c: draw_storey(c, S), fn)
        elif kind in ('parking', 'commercial'):
            level, L = build_level_open(pg, notes)
            poche_by_level.append(L['poche'])
            if check:
                save_check(pg, pdf, lambda c: draw_open(c, L), fn)
        else:
            level, R = build_level_roof(pg)
            poche_by_level.append(R['poche'])
            if check:
                save_check(pg, pdf, lambda c: draw_roof(c, R), fn)
        level['grid_fit'] = dict(pt_per_m=pg.grid['pt_per_m'], origin_pt=pg.grid['origin_pt'],
                                 max_axis_residual_m=rnd(max(abs(r[2]) for r in pg.grid['x_axes'] + pg.grid['y_axes']), 4))
        levels.append(level)
        print('page %2d %-28s done' % (n, pg.meta['name']), file=sys.stderr)
    # lift shafts are the same on every storey; fill the ones a sheet's
    # erosion test missed from the storeys that show all four
    sets = [l['lifts'] for l in levels if l.get('lifts') is not None]
    full = max(sets, key=len) if sets else []
    for l in levels:
        if 'lifts' not in l or l['kind'] not in ('residential', 'offices'):
            continue
        have = [Polygon(x['polygon']['outline']).centroid for x in l['lifts']]
        for x in full:
            c = Polygon(x['polygon']['outline']).centroid
            if not any(c.distance(h) < 0.3 for h in have):
                y = dict(x)
                y['propagated_from_other_storey'] = True
                l['lifts'].append(y)
    # core summary per storey: stair cell = the flights' box grown to the
    # enclosing walls (ray-march to wall poche, <= 2.5 m), plus the lifts
    for l, P_ in zip(levels, poche_by_level):
        if not l.get('stairs'):
            continue
        cores = {}
        for cid in sorted({f['core'] for f in l['stairs']}):
            fl = [f for f in l['stairs'] if f['core'] == cid]
            x0 = min(f['bbox'][0] for f in fl); y0 = min(f['bbox'][1] for f in fl)
            x1 = max(f['bbox'][2] for f in fl); y1 = max(f['bbox'][3] for f in fl)
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

            def march(px, py, dx, dy):
                for k in range(1, 51):
                    q = Point(px + dx * 0.05 * k, py + dy * 0.05 * k)
                    if P_.contains(q):
                        return 0.05 * (k - 1)
                return None
            ext = [march(x0, cy, -1, 0), march(cx, y0, 0, -1), march(x1, cy, 1, 0), march(cx, y1, 0, 1)]
            cell = [rnd(x0 - (ext[0] or 0)), rnd(y0 - (ext[1] or 0)), rnd(x1 + (ext[2] or 0)), rnd(y1 + (ext[3] or 0))]
            lifts = [x for x in l.get('lifts', []) if x['core'] == cid]
            env = box(*cell)
            for x in lifts:
                env = env.union(Polygon(x['polygon']['outline']))
            cores[cid] = dict(stair_cell=cell, stair_cell_open_sides=[n for n, e in zip(('-x', '-y', '+x', '+y'), ext) if e is None],
                              flights=len(fl), lifts=len(lifts), envelope=[rnd(v) for v in env.bounds])
        l['core_summary'] = cores
    # dog-leg stairs: the flight without an arrow rises the other way
    for l in levels:
        for f in l.get('stairs', []):
            if f.get('rises_towards') is None:
                mates = [g for g in l['stairs'] if g is not f and g['core'] == f['core'] and g.get('rises_towards')
                         and g['step_axis'] == f['step_axis']]
                if mates:
                    r = mates[0]['rises_towards']
                    f['rises_towards'] = ('-' if r[0] == '+' else '+') + r[1:]
                    f['rises_towards_inferred'] = 'dog-leg partner of the arrowed flight'
    levels.sort(key=lambda l: l['z'])
    for i, l in enumerate(levels):
        nxt = levels[i + 1]['z'] if i + 1 < len(levels) else None
        l['floor_to_floor'] = rnd(nxt - l['z'], 3) if nxt is not None else None
    ref = grids[pages[0]]
    out = dict(
        meta=dict(source='blender/plans/plans.pdf (13 A3 sheets, architect G+L, Rustavi 2023)',
                  generator='tools/plan_extract.py', units='m',
                  frame=('origin = axis a x axis 1; x along lettered axes a->J (page left->right); '
                         'y along numbered axes 1->10 (page top->bottom, +y = street side); '
                         'z = level label. Drawn with y down; for a right-handed z-up model use (x, -y, z).'),
                  joint=dict(x=JOINT_X, between=['i', 'k'], width=0.6),
                  cores=CORES, label_fixes=LABEL_FIXES),
        grid=dict(x_axes=[dict(label=L, label_ka=K, x=X) for L, K, X in zip(LETTERS, LETTERS_KA, X_NOM)],
                  y_axes=[dict(label=L, y=Y) for L, Y in zip(NUMBERS, Y_NOM)],
                  per_page={str(k): dict(pt_per_m=v['pt_per_m'], origin_pt=v['origin_pt'],
                                         x_residual_m={r[0]: r[2] for r in v['x_axes']},
                                         y_residual_m={r[0]: r[2] for r in v['y_axes']},
                                         **{kk: vv for kk, vv in v.items() if kk.startswith('site_')})
                            for k, v in grids.items()}),
        site=dict(boundary=[[rnd(x), rnd(y)] for x, y in site[1].coords]) if site else None,
        levels=levels, flats=flats, offices=offices, anomalies=notes)
    with open(out_path, 'w') as f:
        json.dump(out, f, separators=(',', ':'))
    print('wrote %s: %d levels, %d flats, %d offices, %d anomalies' % (
        out_path, len(levels), len(flats), len(offices), len(notes)), file=sys.stderr)


if __name__ == '__main__':
    main(sys.argv[1:])
