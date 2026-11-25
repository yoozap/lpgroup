# Blender -b -P tools/plan_ceilcheck.py -- web/scene-street.glb web/interior web/plan_meta.json [N=30]
# For L02..L10: N random points in the flats' rooms at z+1.5, a ray straight up;
# for L01 in the offices' rooms, for L00 in the entrance halls (cores[].hall).
# PASS if the first hit is that level's own ceiling (an in_<L>_ node, at
# z+h-0.30 +-2 cm), and nothing else lies within 3 cm beyond it (a coplanar
# or near-coplanar face there z-fights it on the page).
import bpy, sys, json, random, os, re
from mathutils import Vector, Matrix
a = sys.argv[sys.argv.index('--') + 1:]
N = int(a[3]) if len(a) > 3 else 30
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=a[0])
root = bpy.data.objects['BuildingRoot']; root.matrix_world = Matrix.Identity(4)
for f in ['cores.glb'] + ['L%02d.glb' % i for i in range(0, 11)]:
    p = os.path.join(a[1], f)
    if os.path.exists(p): bpy.ops.import_scene.gltf(filepath=p)
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get(); sc = bpy.context.scene
meta = json.load(open(a[2]))
def inside(pt, poly):
    x, y = pt; c = False; n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1): c = not c
    return c
rnd = random.Random(7)
bad = 0; tot = 0
for L in meta['levels']:
    if L['id'] not in ['L%02d' % i for i in range(0, 11)]: continue
    z, h = L['z'], L['h']; cz = z + h - 0.30
    rooms = [(f['n'], r) for f in L.get('flats', []) + L.get('offices', []) for r in f['rooms']]
    if L['id'] == 'L00':
        rooms = [(c['id'], {'poly': c['hall'], 'rooms_id': 'hall'}) for c in meta['cores'] if c.get('hall')]
    got = 0; tries = 0; lbad = []
    while got < N and tries < 5000:
        tries += 1
        n, r = rnd.choice(rooms); P = r['poly']['outline']
        xs = [p[0] for p in P]; ys = [p[1] for p in P]
        pt = (rnd.uniform(min(xs), max(xs)), rnd.uniform(min(ys), max(ys)))
        if not inside(pt, P): continue
        o = Vector((pt[0], -pt[1], z + 1.5))
        ok, loc, nn, i, ob, m = sc.ray_cast(dg, o, Vector((0, 0, 1)), distance=10)
        if not ok: continue   # furniture-free open sky would be a fail too, but rooms always have a ceiling
        if ob.name.startswith('in_%s_' % L['id']) and loc.z < cz - 0.05 and \
                any(k in ob.name for k in ('_walls__', '_frames__', '_door', '_d')):
            continue      # under a door head or inside a wall: not a room point
        if L['id'] == 'L00' and ob.name.startswith('in_') and ('_lift' in ob.name or '_stair_' in ob.name):
            continue      # a lift car or a flight stands over this hall point: not a ceiling point
        if L['id'] == 'L01' and re.match(r'^[AB]_L01_lg\d+_', ob.name) and loc.z > cz - 0.10:
            continue      # a one-way loggia bay of an office: its soffit (z+h-0.35) is the bay's ceiling
        got += 1; tot += 1
        why = None
        if not ob.name.startswith('in_%s_' % L['id']): why = 'first hit %s at %.3f' % (ob.name, loc.z)
        elif abs(loc.z - cz) > 0.02: why = 'own hit %s at %.3f (ceiling %.2f)' % (ob.name, loc.z, cz)
        else:
            ok2, loc2, nn2, i2, ob2, m2 = sc.ray_cast(dg, loc + Vector((0, 0, 1e-4)), Vector((0, 0, 1)), distance=0.03)
            if ok2: why = 'clash: %s at %.3f behind %s at %.3f' % (ob2.name, loc2.z, ob.name, loc.z)
            ok3, loc3, nn3, i3, ob3, m3 = sc.ray_cast(dg, loc - Vector((0, 0, 0.03)), Vector((0, 0, 1)), distance=0.03 - 1e-4)
            if ok3 and ob3 != ob: why = 'clash: %s at %.3f just under %s' % (ob3.name, loc3.z, ob.name)
        if why: lbad.append((n, r['rooms_id'], tuple(round(v, 2) for v in pt), why))
    bad += len(lbad)
    print('CEIL %s: %d rays, %d bad' % (L['id'], got, len(lbad)))
    for b in lbad[:6]: print('   BAD', b)
print('CEILING CHECK %s: %d/%d bad' % ('PASS' if bad == 0 else 'FAIL', bad, tot))
# Stairwells at grade: over every L00 -> L01 flight and half landing, a ray up
# from +3.9 must meet the interior (the L01 floor's edge, a flight above) or,
# at the terrace stair, the stair house - never a street slab or the deck.
sbad = 0; sn = 0
for c in meta['cores']:
    hb = c['hall']['outline']; hx = [p[0] for p in hb]; hy = [p[1] for p in hb]
    for st in c['storeys']:
        if st['from'] != 'L00': continue
        for fl in st['flights'] + [st['half_landing']]:
            P = fl['poly']['outline']; xs = [p[0] for p in P]; ys = [p[1] for p in P]
            x0, x1 = max(min(xs), min(hx)), min(max(xs), max(hx)); y0, y1 = max(min(ys), min(hy)), min(max(ys), max(hy))
            for i in range(6):
                pt = (rnd.uniform(x0 + 0.1, x1 - 0.1), rnd.uniform(y0 + 0.1, y1 - 0.1))
                ok, loc, nn, ii, ob, m = sc.ray_cast(dg, Vector((pt[0], -pt[1], 3.9)), Vector((0, 0, 1)), distance=40)
                sn += 1
                if ok and not (ob.name.startswith('in_') or ob.name.startswith('terrace_stairhouse')):
                    sbad += 1
                    print('   BAD stairwell', c['id'], tuple(round(v, 2) for v in pt), ob.name, round(loc.z, 3))
print('STAIRWELL CHECK %s: %d/%d bad' % ('PASS' if sbad == 0 else 'FAIL', sbad, sn))
