#!/usr/bin/env python3
"""Check the interior files against the plan, level by level.

Two halves, one file:

  1. inside Blender - read back what was exported:
       Blender -b -P tools/plancheck.py -- dump OUT.json [web/interior]
     imports every web/interior/*.glb, and per node writes its triangle
     count, the area of its upward faces, its bounding box and the
     segments where its triangles cross z = level + 1.00 (plan frame).

  2. system python - judge it:
       python3 tools/plancheck.py check OUT.json [web/plan_meta.json] [--plots DIR]
     * floor area of every flat's floor meshes vs plan.json area_polygon
     * every flat has an entrance door; every room of every flat is
       reachable from the corridor through door throats (flood fill on
       nav.walk - nav.solid, body radius 0.20 m)
     * each core's stair: flight 1 leaves the level, meets the half
       landing, flight 2 arrives at the next level (meta AND meshes)
     * lift stops open onto the corridor; the street portals onto a hall
     * --plots: the 1.00 m slice of the exported meshes per level, walls
       coloured by owner, beside the sheet's check image.
"""
import json
import math
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ======================================================== 1. Blender side
def dump(out, folder, meta_path=None):
    import bpy
    import re
    meta = json.load(open(meta_path or os.path.join(REPO, 'web', 'plan_meta.json')))
    zl = {l['id']: l['z'] for l in meta['levels']}
    res = {}
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith('.glb'):
            continue
        key = fn[:-4]
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=os.path.join(folder, fn))
        dg = bpy.context.evaluated_depsgraph_get()
        z_cut = zl[key] + 1.0 if key in zl else None
        nodes = {}
        for ob in bpy.context.scene.objects:
            if ob.type != 'MESH':
                continue
            me = ob.data
            mw = ob.matrix_world
            me.calc_loop_triangles()
            vs = [mw @ v.co for v in me.vertices]
            tris = len(me.loop_triangles)
            up = 0.0
            segs = []
            down = []           # downward faces of ceilings (plan xy), for the headroom check
            want_down = '_ceiling__' in ob.name and key == 'L00'
            zmin, zmax = 1e9, -1e9
            for t in me.loop_triangles:
                p = [vs[i] for i in t.vertices]
                n = (p[1] - p[0]).cross(p[2] - p[0])
                a = n.length / 2
                if a > 0 and n.z / (2 * a) > 0.9:
                    up += a
                if want_down and a > 0 and n.z / (2 * a) < -0.9:
                    down.append([[round(q.x, 3), round(-q.y, 3)] for q in p])
                for q in p:
                    zmin = min(zmin, q.z); zmax = max(zmax, q.z)
                if z_cut is not None:
                    pts = []
                    for i in range(3):
                        A, B = p[i], p[(i + 1) % 3]
                        if (A.z - z_cut) * (B.z - z_cut) < 0:
                            s = (z_cut - A.z) / (B.z - A.z)
                            pts.append((A.x + s * (B.x - A.x), -(A.y + s * (B.y - A.y))))
                    if len(pts) == 2:
                        segs.append([round(pts[0][0], 3), round(pts[0][1], 3), round(pts[1][0], 3), round(pts[1][1], 3)])
            # name: the importer keeps node names; strip Blender's .001
            nm = re.sub(r'\.\d{3}$', '', ob.name)
            nodes[nm] = {'tris': tris, 'up': round(up, 4), 'z': [round(zmin, 3), round(zmax, 3)], 'segs': segs,
                         **({'down': down} if down else {}),
                         'loc': [round(ob.location.x, 3), round(-ob.location.y, 3), round(ob.location.z, 3)],
                         'mats': [m.name for m in me.materials]}
        res[key] = {'z_cut': z_cut, 'nodes': nodes}
        print('[plancheck] %s %d nodes' % (fn, len(nodes)))
    json.dump(res, open(out, 'w'))


# ======================================================== 2. judging
def check(dump_path, meta_path, plots=None):
    from shapely.geometry import Polygon, Point, LineString, box
    from shapely.ops import unary_union
    D = json.load(open(dump_path))
    M = json.load(open(meta_path))
    plan = json.load(open(os.path.join(REPO, 'blender', 'plans', 'plan.json')))
    area_poly = {(f['level'], f['number']): f['area_polygon'] for f in plan['flats']}
    area_poly.update({('L01', f['number']): f['area_polygon'] for f in plan['offices']})

    def P(d):
        g = Polygon(d['outline'], d.get('holes') or [])
        return g if g.is_valid else g.buffer(0)

    out = {'levels': {}, 'problems': []}
    prob = out['problems']
    levels = {l['id']: l for l in M['levels'] if 'nav' in l}
    R_BODY = 0.20
    comps_by_level = {}
    for lid, L in levels.items():
        z = L['z']
        nav = L['nav']
        walk_here = [w for w in nav['walk'] if abs(w['z'] - z) <= 0.05]
        # walk polygons are rounded to the mm: close the hairline cracks
        free = unary_union([P(w['poly']) for w in walk_here]).buffer(0.01, join_style=2).buffer(-0.01, join_style=2)
        solid = unary_union([P(s) for s in nav['solid']]).buffer(0)
        free = free.difference(solid)
        er = free.buffer(-R_BODY)   # round: a mitred inward buffer drops points near hairline notches
        comps = list(getattr(er, 'geoms', [er]))
        comps_by_level[lid] = comps

        def comp_of(g):
            hits = [i for i, c in enumerate(comps) if c.intersects(g)]
            return hits

        corr_w = [P(w['poly']) for w in walk_here if w['kind'] in ('corridor', 'hall', 'commercial')]
        corr_c = set()
        for g in corr_w:
            corr_c.update(comp_of(g))
        # the corridor of a residential level is one piece
        lr = {'components': len(comps), 'corridor_components': sorted(corr_c), 'flats': {}}
        units = L.get('flats') or L.get('offices') or []
        nodes = D.get(lid, {}).get('nodes', {})
        for f in units:
            tok = f['token']
            fl_area = sum(v['up'] for k, v in nodes.items()
                          if k.startswith('in_%s_%s_floor__' % (lid, tok)))
            ap = area_poly.get((lid, f['n']))
            dev = (fl_area - ap) / ap * 100 if ap else None
            ent = [d for d in f['doors'] if d['kind'] == 'entrance']
            rec = {'floor_area': round(fl_area, 2), 'area_polygon': ap,
                   'dev_pct': round(dev, 2) if dev is not None else None,
                   'entrances': len(ent), 'entrance_made': bool(f.get('entrance_made')),
                   'rooms': len(f['rooms']), 'unreached_rooms': []}
            if dev is None or abs(dev) > 2.0:
                prob.append('%s flat %s: floor %.2f vs polygon %s' % (lid, f['n'], fl_area, ap))
            if not ent:
                prob.append('%s flat %s: no entrance door' % (lid, f['n']))
            targets = [dict(kind='room', room=i, poly=r['poly']) for i, r in enumerate(f['rooms'])]
            targets += [w for w in walk_here if w.get('owner') == tok and w['kind'] == 'loggia']
            for w in targets:
                g = P(w['poly'])
                hit = set(comp_of(g))
                if not (hit & corr_c):
                    why = 'no component (too narrow for a 0.40 m body)' if not hit else 'cut off from the corridor'
                    rec['unreached_rooms'].append({'kind': w['kind'], 'room': w.get('room'), 'area': round(g.area, 2),
                                                   'why': why})
            if rec['unreached_rooms']:
                prob.append('%s flat %s: %d room(s)/loggia(s) not reached: %s' % (
                    lid, f['n'], len(rec['unreached_rooms']),
                    ', '.join('%s %s %.1f m2 (%s)' % (r['kind'], r['room'], r['area'], r['why']) for r in rec['unreached_rooms'])))
            lr['flats'][f['n']] = rec
        # common loggias and terraces
        lr['common_unreached'] = []
        for w in walk_here:
            if w.get('owner') is None and w['kind'] in ('loggia', 'terrace'):
                if not (set(comp_of(P(w['poly']))) & corr_c):
                    lr['common_unreached'].append(w['kind'])
                    prob.append('%s common %s at %s not reached' % (lid, w['kind'], [round(v, 1) for v in P(w['poly']).bounds]))
        # lifts
        lr['lifts'] = []
        for s in nav.get('lifts', []):
            ok = False
            if s['door']:
                (ax, ay), (bx, by) = s['door']
                cab = P(s['cab'])
                mx, my = (ax + bx) / 2, (ay + by) / 2
                dx, dy = bx - ax, by - ay
                l = math.hypot(dx, dy)
                nx, ny = -dy / l, dx / l
                if cab.contains(Point(mx + nx * 0.3, my + ny * 0.3)):
                    nx, ny = -nx, -ny
                pt = Point(mx + nx * 0.6, my + ny * 0.6).buffer(0.15)
                ok = bool(set(comp_of(pt)) & corr_c)
            lr['lifts'].append({'core': s['core'], 'shaft': s['shaft'], 'door_to_corridor': ok})
            if not ok:
                prob.append('%s lift %s/%s: landing door does not open onto the corridor' % (lid, s['core'], s['shaft']))
        # stair: flight 1 bottom on this level's corridor
        lr['stairs'] = []
        for r in nav.get('ramps', []):
            g = P(r['poly'])
            ax_, ay_ = r['axis']
            b = g.bounds
            if r['flight'] == 1:
                # bottom end = opposite of the uphill axis
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                hx = (b[2] - b[0]) / 2 * abs(ax_) + (b[3] - b[1]) / 2 * abs(ay_)
                p = Point(cx - ax_ * (hx + 0.35), cy - ay_ * (hx + 0.35)).buffer(0.12)
                ok = bool(set(comp_of(p)) & corr_c)
                lr['stairs'].append({'core': r['core'], 'flight1_starts_on_corridor': ok})
                if not ok:
                    prob.append('%s %s: flight 1 does not start on the corridor' % (lid, r['core']))
        out['levels'][lid] = lr
    # stairs across levels, from the meta
    seq = [l['id'] for l in M['levels'] if 'nav' in l] + ['ROOF']
    zmap = {l['id']: l['z'] for l in M['levels']}
    stair_ok = {}
    for c in M['cores']:
        cid = c['id']
        chain = []
        for st in c['storeys']:
            f1, f2 = st['flights']
            hl = P(st['half_landing']['poly'])
            ok = (abs(f1['z0'] - zmap[st['from']]) < 1e-3 and abs(f1['z1'] - st['half_landing']['z']) < 1e-3 and
                  abs(f2['z0'] - st['half_landing']['z']) < 1e-3 and abs(f2['z1'] - zmap[st['to']]) < 1e-3 and
                  P(f1['poly']).distance(hl) < 0.02 and P(f2['poly']).distance(hl) < 0.02)
            # the flights' meshes: top of the flight nodes = next level
            nd = D.get('cores', {}).get('nodes', {})
            fn = nd.get('in_%s_stair_%s_flights__int_stone_dark' % (cid, st['from']))
            ln = nd.get('in_%s_stair_%s_landing__int_stone_dark' % (cid, st['from']))
            mesh_ok = bool(fn and ln and abs(fn['z'][1] - zmap[st['to']]) < 0.01 and abs(fn['z'][0] - zmap[st['from']]) < 0.01
                           and abs(ln['z'][1] - st['half_landing']['z']) < 0.01)
            # does flight 2 arrive on the next level's corridor?
            arrive = None
            if st['to'] in comps_by_level:
                g = P(f2['poly'])
                b = g.bounds
                L2 = levels[st['to']]
                r2 = [r for r in levels[st['from']]['nav']['ramps'] if r['core'] == cid and r['flight'] == 2]
                ax_, ay_ = r2[0]['axis']
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                hx = (b[2] - b[0]) / 2 * abs(ax_) + (b[3] - b[1]) / 2 * abs(ay_)
                p = Point(cx + ax_ * (hx + 0.35), cy + ay_ * (hx + 0.35)).buffer(0.12)
                comps = comps_by_level[st['to']]
                arrive = any(cc.intersects(p) for cc in comps)
            elif st['to'] == 'ROOF':
                hw = c.get('head', {}).get('walk') or []
                g = P(f2['poly']); b = g.bounds
                arrive = any(P(w).buffer(0.05).intersects(g) for w in hw)
            chain.append({'from': st['from'], 'to': st['to'], 'risers': st['risers_per_flight'] * 2,
                          'riser': st['riser'], 'going': st['going'], 'meta_ok': ok, 'mesh_ok': mesh_ok,
                          'arrives_on_floor': arrive})
            if not (ok and mesh_ok and arrive):
                prob.append('stair %s %s->%s: meta %s mesh %s arrives %s' % (cid, st['from'], st['to'], ok, mesh_ok, arrive))
        stair_ok[cid] = chain
    out['stairs'] = stair_ok
    # portals
    out['portals'] = []
    if 'L00' in comps_by_level:
        comps = comps_by_level['L00']
        L00 = levels['L00']
        for p in M.get('portals', []):
            mx, my = (p['a'][0] + p['b'][0]) / 2, (p['a'][1] + p['b'][1]) / 2
            q = Point(mx - p['normal'][0] * 0.6, my - p['normal'][1] * 0.6).buffer(0.15)
            hit = [i for i, c in enumerate(comps) if c.intersects(q)]
            # is the core's flight 1 on the same component?
            fl = [r for r in L00['nav']['ramps'] if r['core'] == p['core'] and r['flight'] == 1]
            reach = None
            if fl:
                g = P(fl[0]['poly']); b = g.bounds; ax_, ay_ = fl[0]['axis']
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                hx = (b[2] - b[0]) / 2 * abs(ax_) + (b[3] - b[1]) / 2 * abs(ay_)
                s = Point(cx - ax_ * (hx + 0.35), cy - ay_ * (hx + 0.35)).buffer(0.12)
                reach = any(comps[i].intersects(s) for i in hit)
            out['portals'].append({'core': p['core'], 'inside_hall': bool(hit), 'reaches_stair': reach,
                                   'from': p.get('from')})
            if not hit or reach is False:
                prob.append('portal %s: inside %s, reaches its stair %s' % (p['core'], bool(hit), reach))
    stage3(D, M, plan, levels, prob, out)
    if plots:
        make_plots(D, M, plots)
    return out


def stage3(D, M, plan, levels, prob, out):
    """Assertions added by the build-3 fixes (each was seen to FAIL on the
    stage-2 data before its fix; see the build-3 report)."""
    from shapely.geometry import Polygon, Point, LineString, box
    from shapely.ops import unary_union

    def P(d):
        g = Polygon(d['outline'], d.get('holes') or [])
        return g if g.is_valid else g.buffer(0)

    def sweep(d):
        """quarter disc a leaf sweeps, plan frame"""
        h = d['hinge']
        a0 = math.radians(d['shut'])
        a1 = a0 + math.radians(d['open'])
        pts = [tuple(h)] + [(h[0] + d['w'] * math.cos(a0 + (a1 - a0) * i / 12), h[1] + d['w'] * math.sin(a0 + (a1 - a0) * i / 12))
                            for i in range(13)]
        return Polygon(pts).buffer(0)
    def furn_poly(q):
        (cx, cy), (w, d), t = q['c'], q['s'], math.radians(q['hd'])
        fw, sd = (math.cos(t), math.sin(t)), (-math.sin(t), math.cos(t))
        return Polygon([(cx + fw[0] * a * d / 2 + sd[0] * b * w / 2, cy + fw[1] * a * d / 2 + sd[1] * b * w / 2)
                        for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    o3 = out['stage3'] = {}
    # (1) a MADE door neither opens into a tiled (wet) room nor sweeps
    #     another door's throat of its flat (L08 129 at entrance_suggested)
    bad = []
    for lid, L in levels.items():
        throats = {}
        for w in L['nav']['walk']:
            if w['kind'] == 'door':
                throats.setdefault(w.get('owner'), []).append((w.get('door'), P(w['poly'])))
        for f in (L.get('flats') or []):
            tile = unary_union([P(r['poly']) for r in f['rooms'] if r.get('finish') == 'tile' and r.get('poly')])
            for d in f['doors']:
                if not d.get('made'):
                    continue
                sw = sweep(d)
                h = d['hinge']
                a = math.radians(d['shut'] + d['open'] / 2)
                into = Point(h[0] + 0.5 * d['w'] * math.cos(a), h[1] + 0.5 * d['w'] * math.sin(a))
                why = []
                if not tile.is_empty and tile.buffer(-0.05).contains(into):
                    why.append('opens into a tiled room')
                for did, g in throats.get(f['token'], []):
                    if did != d['id'] and sw.buffer(-0.03).intersects(g.buffer(-0.03)):
                        why.append('sweeps the throat of %s' % did)
                if why:
                    bad.append('%s flat %s %s: %s' % (lid, f['n'], d['id'], ', '.join(why)))
    o3['made_doors_bad'] = bad
    prob.extend('made door: ' + b for b in bad)
    # (2) every lift landing door opens onto a corridor / hall floor: not a
    #     flat, not under a flight; and it is a door, not a whole shaft side
    bad = []
    for lid, L in levels.items():
        nav = L['nav']
        common = unary_union([P(w['poly']) for w in nav['walk'] if w['kind'] in ('corridor', 'hall', 'commercial')
                              and abs(w['z'] - L['z']) < 0.05])
        stairs = unary_union([P(r['poly']) for r in nav['ramps']] +
                             [P(w['poly']) for w in nav['walk'] if w['kind'] == 'half_landing'])
        for s_ in nav['lifts']:
            tag = '%s %s-%s' % (lid, s_['core'], s_['shaft'])
            if not s_['door']:
                bad.append(tag + ': no landing door')
                continue
            (ax, ay), (bx, by) = s_['door']
            l = math.hypot(bx - ax, by - ay)
            if l > 1.3:
                bad.append(tag + ': landing door %.2f m wide (a whole shaft side)' % l)
            cab = P(s_['cab'])
            mx, my = (ax + bx) / 2, (ay + by) / 2
            nx, ny = -(by - ay) / l, (bx - ax) / l
            if cab.contains(Point(mx + nx * 0.3, my + ny * 0.3)):
                nx, ny = -nx, -ny
            pt = Point(mx + nx * 0.6, my + ny * 0.6)
            if not common.buffer(0.02).contains(pt):
                bad.append(tag + ': outside the landing door is not corridor/hall floor')
            if stairs.buffer(0.05).contains(pt):
                bad.append(tag + ': the landing door opens onto a stair flight')
    o3['lift_doors_bad'] = bad
    prob.extend('lift: ' + b for b in bad)
    # every car stops at +0.000 (the sheet draws a landing door for all four)
    for l_ in M['lifts']:
        if not any(st['level'] == 'L00' and st['door'] for st in l_['stops']):
            prob.append('lift %s-%s: no stop at L00' % (l_['core'], l_['shaft']))
    # (3) the entrance halls are rooms, not one open space: with every door
    #     throat shut, each hall falls apart into its drawn rooms
    want = {'C1': 4, 'C2': 4, 'C3': 3}
    o3['hall_rooms'] = {}
    if 'L00' in levels:
        L = levels['L00']
        nav = L['nav']
        solid = unary_union([P(q) for q in nav['solid']]).buffer(0)
        doors = unary_union([P(w['poly']).buffer(0.03) for w in nav['walk'] if w['kind'] == 'door'])
        for h in L.get('halls', []):
            hp = P(h['poly'])
            free = hp.difference(solid).difference(doors).buffer(-0.05)
            rooms = [g for g in getattr(free, 'geoms', [free]) if g.area > 1.0]
            o3['hall_rooms'][h['core']] = len(rooms)
            if h['core'] in want and len(rooms) < want[h['core']]:
                prob.append('hall %s: %d rooms with the doors shut, the sheet draws %d (street door -> vestibule -> '
                            'lift lobby -> stair)' % (h['core'], len(rooms), want[h['core']]))
    # (4) no L00 ceiling over a flight or the half landing (the podium stair
    #     was capped at +4.50)
    nd = D.get('L00', {}).get('nodes', {})
    ceil = unary_union([Polygon(t).buffer(0) for k, v in nd.items() if '_ceiling__' in k for t in v.get('down', [])
                        if Polygon(t).area > 1e-6])
    if 'L00' in levels:
        st = unary_union([P(r['poly']) for r in levels['L00']['nav']['ramps']] +
                         [P(w['poly']) for w in levels['L00']['nav']['walk'] if w['kind'] == 'half_landing'])
        cap = ceil.intersection(st.buffer(-0.05)).area if not ceil.is_empty else 0.0
        o3['L00_ceiling_over_stairs_m2'] = round(cap, 3)
        if not nd or not any('down' in v for v in nd.values()):
            prob.append('L00: dump carries no ceiling faces (re-run the dump)')
        elif cap > 0.01:
            prob.append('L00: %.2f m2 of ceiling over a stair flight / half landing' % cap)
    # (5) skirting in every flat and office (int_white_gloss in its walls node)
    miss = []
    for lid, L in levels.items():
        nodes = D.get(lid, {}).get('nodes', {})
        for f in (L.get('flats') or L.get('offices') or []):
            k = 'in_%s_%s_walls__int_wall' % (lid, f['token'])
            if k in nodes and 'int_white_gloss' not in nodes[k]['mats']:
                miss.append('%s %s' % (lid, f['n']))
    o3['no_skirting'] = miss
    if miss:
        prob.append('no skirting in %d units: %s' % (len(miss), ', '.join(miss[:8])))
    # (6) nav.furn: one footprint per piece of the furniture index that has
    # a box (build 6: an undrawn piece with no box - a rug, a curtain, a
    # picture - is not solid, and lib_plan.nav_furn writes no footprint)
    idx = os.path.join(REPO, 'web', 'interior', 'furn', 'index.json')
    if os.path.exists(idx):
        I = json.load(open(idx))
        for lid, Li in (I.get('levels') or {}).items():
            n_idx = sum(1 for u in Li.get('units', {}).values() for p in u.get('pieces', []) if p.get('box'))
            n_nav = len((levels.get(lid, {}).get('nav') or {}).get('furn') or [])
            if n_idx != n_nav:
                prob.append('%s nav.furn: %d footprints for %d pieces' % (lid, n_nav, n_idx))
        # info: the leaves of the doors that sweep a piece of furniture
        hits = []
        for lid, L in levels.items():
            fu = [(q['node'], furn_poly(q)) for q in (L['nav'].get('furn') or []) if q['z'][1] > 0.25 and q['z'][0] < 1.4]
            for f in (L.get('flats') or L.get('offices') or []):
                for d in f['doors']:
                    sw = sweep(d).buffer(-0.05)
                    for node, g in fu:
                        if ('_%s_' % f['token']) in node and sw.intersects(g):
                            hits.append('%s %s %s x %s' % (lid, f['n'], d['id'], node.split('_furn_')[1].split('__')[0]))
        o3['leaf_sweeps_furniture'] = hits


def make_plots(D, M, folder):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import hashlib
    import colorsys
    import re
    from PIL import Image
    os.makedirs(folder, exist_ok=True)
    page = {'L00': 2, 'L01': 3}
    page.update({'L%02d' % i: i + 2 for i in range(2, 11)})

    def col(tok):
        h = int(hashlib.md5(tok.encode()).hexdigest()[:6], 16) / 0xffffff
        return colorsys.hsv_to_rgb(h, 0.75, 0.75)

    for L in M['levels']:
        lid = L['id']
        if lid not in D or 'nav' not in L:
            continue
        fig = plt.figure(figsize=(1606 / 100, 988 / 100), dpi=100)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(-4, 87); ax.set_ylim(52, -4); ax.axis('off')
        units = L.get('flats') or L.get('offices') or []
        from shapely.geometry import Polygon
        for f in units:
            g = Polygon(f['poly']['outline'])
            ax.fill(*g.exterior.xy, color=col(f['token']) + (0.25,), lw=0)
            if f.get('label_at'):
                ax.text(f['label_at'][0], f['label_at'][1], f['n'], fontsize=7, ha='center')
        for name, nd in D[lid]['nodes'].items():
            m = re.match(r'in_[A-Z0-9-]+_(u[^_]+|o[^_]+|C\d|podium)_', name)
            if '_swing__' in name:
                c, lw = (0.1, 0.2, 1.0), 1.2
            elif 'walls' in name:
                c, lw = ((0, 0, 0) if not m else col(m.group(1))), 0.9
            elif 'frames' in name:
                c, lw = (0.1, 0.7, 0.1), 0.5
            else:
                continue
            for s in nd['segs']:
                ax.plot([s[0], s[2]], [s[1], s[3]], '-', color=c, lw=lw, solid_capstyle='butt')
        p1 = os.path.join(folder, 'slice_%s.png' % lid)
        fig.savefig(p1, dpi=100)
        plt.close(fig)
        chk = os.path.join(REPO, 'blender', 'plans', 'check', 'level_%02d.png' % page[lid])
        if os.path.exists(chk):
            a = Image.open(chk)
            b = Image.open(p1).convert('RGB')
            top = a.crop((0, 0, a.width, a.height // 2))
            im = Image.new('RGB', (a.width, top.height + b.height), 'white')
            im.paste(top, (0, 0))
            im.paste(b, (0, top.height))
            im.save(os.path.join(folder, 'cmp_%s.png' % lid))


if __name__ == '__main__':
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    if argv and argv[0] == 'dump':
        dump(argv[1], argv[2] if len(argv) > 2 else os.path.join(REPO, 'web', 'interior'),
             argv[3] if len(argv) > 3 else None)
    elif argv and argv[0] == 'check':
        plots = argv[argv.index('--plots') + 1] if '--plots' in argv else None
        rest = [a for a in argv[1:] if not a.startswith('--') and a != plots]
        meta = rest[1] if len(rest) > 1 else os.path.join(REPO, 'web', 'plan_meta.json')
        res = check(rest[0], meta, plots)
        print(json.dumps({'problems': res['problems'], 'n_problems': len(res['problems'])}, indent=1))
        json.dump(res, open(os.path.splitext(rest[0])[0] + '_check.json', 'w'), indent=1)
    else:
        print(__doc__)
