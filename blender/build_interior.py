# -*- coding: utf-8 -*-
"""Build the inside of the building from the architect's plan.

    Blender -b -P blender/build_interior.py [-- --levels L03,L04,cores] [--out DIR] [--meta F] [--noweld] [--nometa]

Writes web/interior/<LEVEL>.glb (L00, L01, L02..L10), web/interior/cores.glb
and web/plan_meta.json (+ web/plan_meta/<LEVEL>.json + index.json, the same
data split per level). Build in scratch with --out DIR --meta DIR/plan_meta.json
and swap the files in afterwards. Never touches web/scene*.glb or web/scene_meta.json.

The geometry is computed by blender/lib_plan.py under the system python
(it needs shapely); this script only turns it into meshes and exports.
Frame: the Blender local frame of CONTRACT.md, (x, -y, z) of the plan frame,
no BuildingRoot - the page applies scene_meta.frame.
"""
import bpy, bmesh, os, sys, json, subprocess, tempfile, time, math
from mathutils import Vector
from mathutils.geometry import tessellate_polygon

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import lib_build as LBD

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
OUT = os.path.join(REPO, 'web', 'interior')
if '--out' in args:
    OUT = args[args.index('--out') + 1]
WANT = args[args.index('--levels') + 1].split(',') if '--levels' in args else None
META = None if '--nometa' in args else os.path.join(REPO, 'web', 'plan_meta.json')
if '--meta' in args:            # build in scratch: plan_meta.json (+ plan_meta/ split) go here
    META = args[args.index('--meta') + 1]
os.makedirs(OUT, exist_ok=True)

# ------------------------------------------------------------ materials
# The names are web/materials.js keys (the page shades by name); the
# colours only matter for Blender renders. Values as lib_flat/lib_building.
MATDEF = {
    'int_wall': ('#ebe7df', 0.92, 0.0), 'int_parquet': ('#b58a58', 0.50, 0.0),
    'int_tile_floor': ('#c9c7c3', 0.12, 0.0), 'int_tile_grey': ('#8b8d8e', 0.28, 0.0),
    'int_marble': ('#e8e5e0', 0.14, 0.0), 'int_white_gloss': ('#f2f1ee', 0.22, 0.0),
    'int_door_leaf': ('#ece9e3', 0.36, 0.0), 'int_wood_walnut': ('#4f3627', 0.48, 0.0),
    'int_black': ('#111214', 0.40, 0.2), 'int_stone_dark': ('#3a3a3c', 0.32, 0.0),
    'concrete_frame': ('#b9b2a6', 0.84, 0.0), 'metal_dark': ('#191a1d', 0.38, 0.85),
    # the lift kit (lib_plan "lift kit")
    'chrome': ('#cdd0d4', 0.14, 1.0), 'frame_light': ('#d9d6ce', 0.48, 0.30),
    'neon_orange': ('#ff5a16', 0.4, 0.0), 'int_mirror': ('#e0e4e9', 0.03, 1.0),
    'int_lamp_shade': ('#f1e8d6', 0.7, 0.0),
}


def material(name):
    if name == 'int_glass':
        return LBD.mat('int_glass', LBD.srgb('#cfe2ea'), rough=0.05, alpha=0.30)
    hx, r, m = MATDEF[name]
    return LBD.mat(name, LBD.srgb(hx), rough=r, metal=m)


# ------------------------------------------------------------ mesh from spec
def ring_area(r):
    a = 0.0
    for i in range(len(r)):
        x0, y0 = r[i]
        x1, y1 = r[(i + 1) % len(r)]
        a += x0 * y1 - x1 * y0
    return a / 2


def add_prism(V, F, M, mi, pr):
    rings = [list(r) for r in pr['rings']]
    # outer counter-clockwise, holes clockwise (Blender frame, seen from +z)
    if ring_area(rings[0]) < 0:
        rings[0].reverse()
    for r in rings[1:]:
        if ring_area(r) > 0:
            r.reverse()
    z0, z1 = pr['z0'], pr['z1']
    if pr['sides'] and z1 - z0 > 1e-5:
        for r in rings:
            n = len(r)
            for i in range(n):
                (ax, ay), (bx, by) = r[i], r[(i + 1) % n]
                o = len(V)
                V.extend([(ax, ay, z0), (bx, by, z0), (bx, by, z1), (ax, ay, z1)])
                F.append((o, o + 1, o + 2, o + 3)); M.append(mi)
    caps = []
    if pr['top']:
        caps.append((z1, True))
    if pr['bottom']:
        caps.append((z0, False))
    if caps:
        loops = [[Vector((x, y, 0)) for x, y in r] for r in rings]
        tris = tessellate_polygon(loops)
        flat = [p for r in rings for p in r]
        for zc, up in caps:
            o = len(V)
            V.extend([(x, y, zc) for x, y in flat])
            for t in tris:
                a, b, c = (flat[t[0]], flat[t[1]], flat[t[2]])
                cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
                if abs(cr) < 1e-12:
                    continue
                tri = (o + t[0], o + t[1], o + t[2])
                if (cr > 0) != up:
                    tri = (tri[0], tri[2], tri[1])
                F.append(tri); M.append(mi)


def make_mesh(name, parts):
    V, F, M = [], [], []
    mats = []
    for p in parts:
        mi = len(mats)
        mats.append(p['mat'])
        o = len(V)
        V.extend([tuple(v) for v in p['v']])
        for f in p['f']:
            F.append(tuple(o + i for i in f)); M.append(mi)
        for pr in p['prisms']:
            add_prism(V, F, M, mi, pr)
    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    for m in mats:
        me.materials.append(material(m))
    for poly, mi in zip(me.polygons, M):
        poly.material_index = mi
    me.validate(clean_customdata=False)
    # merge coincident corners so the exporter has less to write
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.to_mesh(me)
    bm.free()
    for poly in me.polygons:
        poly.use_smooth = False
    return me


def build_file(key, spec):
    LBD.reset_scene()
    LBD.MATS.clear()
    coll = bpy.context.scene.collection
    shared = {}
    for mid, parts in spec['shared'].items():
        shared[mid] = make_mesh(mid, parts)
    tris = 0
    for nd in spec['nodes']:
        if 'mesh' in nd:
            me = shared[nd['mesh']]
            ob = bpy.data.objects.new(nd['name'], me)
            ob.location = nd['loc']
            ob.rotation_euler = (0, 0, nd['rot'])
        else:
            me = make_mesh(nd['name'], nd['parts'])
            if not me.polygons:
                continue
            ob = bpy.data.objects.new(nd['name'], me)
        coll.objects.link(ob)
        tris += sum(len(p.vertices) - 2 for p in me.polygons)
    path = os.path.join(OUT, key + '.glb')
    bpy.ops.export_scene.gltf(
        filepath=path, export_format='GLB',
        use_visible=True, export_apply=True,
        export_yup=True, export_cameras=False, export_lights=False,
        export_normals=True, export_texcoords=False,
        export_materials='EXPORT', export_extras=False,
        export_vertex_color='NONE',
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=7,
        export_draco_position_quantization=14,
        export_draco_normal_quantization=10,
        export_draco_texcoord_quantization=12,
        export_draco_color_quantization=8)
    return path, tris, len(spec['nodes']), len(shared)


def weld(path):
    """The same lossless weld + re-encode tools/weld_glb.sh gives the street
    file (Draco gets one vertex per corner from the exporter)."""
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
        print('[interior] weld skipped:', e)
    if os.path.exists(tmp):
        os.remove(tmp)
    return False


# ------------------------------------------------------------ run
t0 = time.time()
geo = tempfile.mktemp(suffix='.json')
cmd = ['python3', os.path.join(HERE, 'lib_plan.py'), '--geo', geo]
if META:
    cmd += ['--meta', META]
if WANT:
    cmd += ['--levels', ','.join(WANT)]
r = subprocess.run(cmd, capture_output=True, text=True)
print(r.stdout)
if r.returncode != 0:
    print(r.stderr)
    raise SystemExit('lib_plan failed')
spec = json.load(open(geo))
os.remove(geo)
print('[interior] plan computed in %.1f s' % (time.time() - t0))
stats = {}
for key, s in spec.items():
    t1 = time.time()
    path, tris, nodes, shared = build_file(key, s)
    raw0 = os.path.getsize(path)
    welded = '--noweld' not in args and weld(path)
    stats[key] = {'tris': tris, 'nodes': nodes, 'shared_meshes': shared,
                  'bytes': os.path.getsize(path), 'bytes_export': raw0, 'welded': welded}
    print('[interior] %-6s %7d tris %4d nodes %8d B (export %d)  %.1f s' %
          (key, tris, nodes, os.path.getsize(path), raw0, time.time() - t1))
if '--stats' in args:
    json.dump(stats, open(args[args.index('--stats') + 1], 'w'), indent=1)
print('[interior] done in %.1f s' % (time.time() - t0))
