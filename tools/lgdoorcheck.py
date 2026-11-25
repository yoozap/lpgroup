#!/usr/bin/env python3
"""Does every balcony / loggia door of the interior stand in a DOOR of the
street facade?

The interior files hang a glazed leaf wherever the plan's door is
(web/plan_meta.json, written by blender/build_interior.py); the street file
(blender/lib_building.py, loggia_module) builds the opening it stands in.
They used to disagree in 172 of 510 doors - the kit put its door at the
left end of every wide opening, with a window at sill height beside it, so
the leaf stood behind a window - and it read from inside as a door that
"sometimes does not sit right".

    python3 tools/lgdoorcheck.py [-v]

Runs Blender once (blocks only, ~10 s) to collect the street's door,
window and cheek spans (lib_building.LG_SPANS / LG_PLACED), then matches
every balcony leaf to the street span it overlaps most on its own storey:
  ok          in a street door (or cheek opening), within 0.10 m each end
  IN_WINDOW   in a street window
  OFFSET      in a door, but more than 0.10 m out
  NO_OPENING  in no street opening at all
Expected after the fix of 2026-11-25: 506 ok, 4 NO_OPENING (three L01 office
doors in walls the interior owns, one L10 common door behind a loggia corner).
Exit 1 if anything is IN_WINDOW or OFFSET.
"""
import sys, os, json, math, glob, collections, subprocess, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BLENDER = '/Applications/Blender.app/Contents/MacOS/Blender'

try:
    import bpy  # noqa: F401  - running inside Blender: dump and leave
    IN_BLENDER = True
except ImportError:
    IN_BLENDER = False

if IN_BLENDER:
    sys.path.insert(0, os.path.join(ROOT, 'blender'))
    import lib_build as LBD
    LBD.reset_scene()
    import lib_building as LB
    LB.build_materials()
    LB.build_blocks()
    out = {'placed': [{'lev': lev, 'nm': nm, 'org': list(org), 't': list(tt), 'n': list(nB),
                       'z': z, 'kit': shell}
                      for (lev, nm, org, tt, nB, z, shell) in LB.LG_PLACED],
           'spans': LB.LG_SPANS}
    with open(sys.argv[-1], 'w') as f:
        json.dump(out, f)
    sys.exit(0)

verbose = '-v' in sys.argv
tmp = os.path.join(tempfile.mkdtemp(), 'lg.json')
r = subprocess.run([BLENDER, '-b', '-P', os.path.abspath(__file__), '--', tmp],
                   capture_output=True, text=True)
if not os.path.exists(tmp):
    print(r.stdout[-2000:], r.stderr[-2000:])
    sys.exit('blender dump failed')
G = json.load(open(tmp))

# the street's openings, per storey, as plan segments
segs = collections.defaultdict(list)
for P in G['placed']:
    sp = G['spans'][P['kit']]
    o, t, n = P['org'], P['t'], P['n']

    def pl(lx, ly):
        # module frame -> Blender local -> plan (x, -y)
        return (o[0] + t[0] * lx - n[0] * ly, -(o[1] + t[1] * lx - n[1] * ly))
    for kind in ('doors', 'wins'):
        for (a, b) in sp[kind]:
            segs[P['lev']].append((kind[:-1], pl(a, sp['d']), pl(b, sp['d']), P['nm']))
    for (xm, a, b) in sp['sides']:
        segs[P['lev']].append(('side', pl(xm, a), pl(xm, b), P['nm']))

pm = json.load(open(os.path.join(ROOT, 'web', 'plan_meta.json')))
count = collections.Counter()
for L in pm['levels']:
    acc = []

    def walk(x):
        if isinstance(x, dict):
            if x.get('kind') == 'balcony' and 'hinge' in x:
                acc.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(L)
    for d in acc:
        h = d['hinge']
        a = math.radians(d['shut'])
        u = (math.cos(a), math.sin(a))
        c = (h[0] + d['w'] * u[0], h[1] + d['w'] * u[1])
        best = None
        for (k, p, q, nm) in segs[L['id']]:
            Ln = math.hypot(q[0] - p[0], q[1] - p[1])
            v = ((q[0] - p[0]) / Ln, (q[1] - p[1]) / Ln)
            if abs(u[0] * v[1] - u[1] * v[0]) > 0.1:
                continue                                    # not parallel
            perp = abs((h[0] - p[0]) * v[1] - (h[1] - p[1]) * v[0])
            if perp > 0.6:
                continue
            s0, s1 = sorted(((X[0] - p[0]) * v[0] + (X[1] - p[1]) * v[1]) for X in (h, c))
            ov = min(s1, Ln) - max(s0, 0.0)
            if ov <= 0:
                continue
            sc = ov / d['w']
            if not best or sc > best[0]:
                best = (sc, k, perp, s0, s1 - Ln, nm)
        if best is None:
            tag = 'NO_OPENING'
        elif best[1] not in ('door', 'side'):
            tag = 'IN_WINDOW'
        elif best[0] < 0.9 or abs(best[3]) > 0.1 or abs(best[4]) > 0.1 or best[2] > 0.25:
            tag = 'OFFSET'
        else:
            tag = 'ok'
        count[tag] += 1
        if verbose and tag != 'ok':
            print(L['id'], d['node'], tag, best and '%s overlap %.2f  ends %+.2f %+.2f  %s'
                  % (best[1], best[0], best[3], best[4], best[5]))
print(dict(count))
sys.exit(1 if count['IN_WINDOW'] or count['OFFSET'] else 0)
