# -*- coding: utf-8 -*-
"""Build the street scene - the real building from the architect's plans,
its podium and terrace, the streets and the city round it - and export it.

  /Applications/Blender.app/Contents/MacOS/Blender -b -P blender/build.py -- \
      [--render] [--noexport] [--meta] [--out preview.png] \
      [--cam px py pz tx ty tz lens_mm] [--res W H]

Writes web/scene.glb -> web/scene-street.glb (split, welded) and
web/scene_meta.json. `--noexport` writes neither file unless `--meta` asks
for the meta. `--cam` takes the preview camera in PLAN coordinates (see
blender/plans/CONTRACT.md); without it the preview stands where the page's
opening shot does.

No interiors are built here (blender/build_interior.py does that, into
web/interior/*.glb). lib_flat.py - the old invented show flat - is no longer
called; its furniture and door code stay in that file for reuse.
"""
import sys, os, math, time, json
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy
from mathutils import Vector, Matrix
import lib_build as LBD
import fit

t0 = time.time()
sc = LBD.reset_scene()

import importlib
import lib_building, lib_city, lib_hood
importlib.reload(lib_building)
importlib.reload(lib_city)
importlib.reload(lib_hood)
LB, LC = lib_building, lib_city

LB.build_materials()

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []

# ----------------------------------------------------------------- hierarchy
root = bpy.data.objects.new('BuildingRoot', None)
root.empty_display_size = 2.0
sc.collection.objects.link(root)
root.location = fit.ROOT_ORIGIN
root.rotation_euler = (0, 0, math.radians(fit.BEARING))

colls, storeys, bmeta = LB.build_blocks()
collP = LC.build_podium()
collT = LC.build_terrace()
collS = LC.build_signage()
collSt = LC.build_street()
collBg = LC.build_background() if os.environ.get('LP_NOHOOD') else lib_hood.build_hood()      # the neighbourhood the renders show
# no vehicles and no people: the scene is the architecture only
collPl = LC.build_planting()

for c in (colls['Aw'], colls['Bw'], colls['A'], colls['B'], collP, collT, collS,
          collSt, collBg, collPl, LBD.collection('trees')):
    for ob in list(c.objects):
        if ob.parent is None:
            ob.parent = root
            # Leave the parent inverse at identity. Setting it to the root's
            # inverse cancels the very placement we are parenting for - it only
            # ever worked because root.matrix_world was still stale here. Any
            # bpy.ops call earlier in the build (importing a model, say) forces
            # a depsgraph evaluation, and then the whole scene exports at the
            # origin.
            ob.matrix_parent_inverse = Matrix.Identity(4)

# no node of the street file may belong to the interiors' namespaces
bad = [o.name for o in bpy.data.objects
       if o.users_scene and (o.name.startswith('flat') or o.name.startswith('in_'))]
assert not bad, 'interior-named objects in the street build: %s' % bad[:5]


# ----------------------------------------------------------------- scene_meta.json
def hero_candidates(W):
    """lib_city.HERO_CANDIDATES in the browser's world: a level camera at
    `eye` turned to `at`'s bearing, `hfov` across a 16:9 frame, the shift
    lens putting `at` on the frame's centre line (as metaHero does)."""
    out = {}
    for name, c in LC.HERO_CANDIDATES.items():
        out[name] = dict(c, eye=W(*c['eye']), at=W(*c['at']),
                         plan_eye=list(c['eye']), plan_at=list(c['at']))
    return out


def write_meta(path):
    """The plan frame in the browser's world, and everything the page needs
    to find the building - see blender/plans/CONTRACT.md."""
    root.matrix_world = Matrix.Translation(Vector(fit.ROOT_ORIGIN)) @ \
        Matrix.Rotation(math.radians(fit.BEARING), 4, 'Z')
    Mw = root.matrix_world

    def W(x, y, z=0.0):
        """plan (x, y, z) -> three.js world (glTF y-up: (X, Z, -Y))"""
        v = Mw @ Vector((x, -y, z))
        return [round(v.x, 4), round(v.z, 4), round(-v.y, 4)]

    def D(x, y, z=0.0):
        o = W(0, 0, 0); p = W(x, y, z)
        return [round(p[i] - o[i], 6) for i in range(3)]
    R = LB.LEVELS['ROOF']
    xs = [p[0] for p in R['outline']['outline']]; ys = [p[1] for p in R['outline']['outline']]
    bx0, bx1, by0, by1 = min(xs), max(xs), min(ys), max(ys)
    cx, cy, cz = (bx0 + bx1) / 2, (by0 + by1) / 2, LB.ROOF_Z / 2
    levels = []
    for l in LB.PLAN['levels']:
        res = l['kind'] == 'residential'
        levels.append({'id': l['level'], 'z': l['z'],
                       'h': l.get('floor_to_floor') or (0.0 if l['level'] == 'ROOF' else None),
                       'kind': l['kind'],
                       'res': (int(l['level'][1:]) - 1) if res else None})
    fp = LB.block_footprints()
    blocks = [{'id': b, 'footprint': fp[b], 'roof_z': LB.TOP_Z, 'parapet_z': LB.ROOF_Z,
               'levels': [s[0] for s in LB.FACADE_LEVELS]} for b in ('A', 'B')]
    cores = []
    entrances = []
    for cid, e in LC.ENTRANCES.items():
        (dx, dy), (nx, ny) = e['c'], e['n']
        dx, dy = round(dx, 3), round(dy, 3)
        ent = {'door': [dx, dy], 'z': 0.0, 'out': [nx, ny],
               # the way a visitor faces walking IN, plan
               # frame, degrees from +x towards +y
               'heading': round(math.degrees(math.atan2(-ny, -nx)), 1),
               'world': W(dx, dy, 0.0), 'w': round(e['w'], 3), 'h': LC.DOOR_H}
        if cid in LC.CORE_DOORS:
            cores.append({'id': cid, 'block': LB.block_of(dx), 'entrance': ent})
        # the street's shut leaf at this door is a stand-in: hide these nodes
        # once web/interior/L00.glb is in, and the hall's own leaf (or none,
        # an open run) takes over
        entrances.append(dict(ent, id=cid, interior_leaf=e['leaf'],
                              street_leaf=['podium_door_%s_leaf' % cid,
                                           'podium_door_%s_leaf_glass' % cid],
                              # what the plate beside the door says, and its
                              # number in geometry (build 3)
                              label=LC.ENTRANCE_LABEL.get(cid),
                              sign='sign_entrance_%s' % cid,
                              # build 4: what kind of door it is
                              kind='terrace' if cid == 'podium' else 'core'))
    # the commercial street doors in the shopfronts (build 4): real openings
    # with shut stand-in leaves; the interior's L00 level doors are their
    # leaves (plan_meta L00 doors kind 'street', no owner). No portal, no
    # label, no sign: they lead into the shops, not to the flats.
    for sid, e in LC.SHOP_DOORS.items():
        if not e.get('n'):
            print('[build] shop door %s found no shopfront: left out of the meta' % sid)
            continue
        (dx, dy), (nx, ny) = e['c'], e['n']
        dx, dy = round(dx, 3), round(dy, 3)
        entrances.append({'door': [dx, dy], 'z': 0.0, 'out': [nx, ny],
                          'heading': round(math.degrees(math.atan2(-ny, -nx)), 1),
                          'world': W(dx, dy, 0.0), 'w': round(e['w'], 3), 'h': LC.DOOR_H,
                          'id': sid, 'interior_leaf': True,
                          'street_leaf': ['podium_door_%s_leaf' % sid,
                                          'podium_door_%s_leaf_glass' % sid],
                          'label': None, 'sign': None, 'kind': 'commercial',
                          'leaves': [d['node'] for d in e['leaves']]})
    hero = {'eye': W(*LC.HERO_EYE), 'at': W(*LC.HERO_AT),
            'plan_eye': list(LC.HERO_EYE), 'plan_at': list(LC.HERO_AT)}
    # The page's rail. app.js circles meta.block.center at RAIL_ZOOM (0.82)
    # times the further of these two, between their bearings, and pins
    # meta.block.corner - the light gable's top south corner - 52% across
    # the window: everything else of the L lies to the right of it, clear of
    # the hero's text. So the sweep runs south-west of the building, from
    # where the bar recedes to the joint and the wing stands at its end with
    # both its faces showing (renders 002 -> 006), ~112 m out.
    # The arc used to stand ~100 m out at bearings 134 -> 112, in a planted
    # square across the main street. That side is buildings now (renders
    # 005, 006), and pulling the arc in over the street put the building
    # past the frame's edge, so it stands back at 94 m and swings round to
    # where open street is that far out: from over the west street (160,
    # x -47 y 50) to the south-west junction's far corner (143, x -34
    # y 74, short of the building line at 77) - render 002's standpoint.
    # 94 -> 85 m (user, 2026-11-25: "a little closer"); both ends still
    # over open street (x -38 y 46 -> x -27 y 68).
    R = 85.0 / 0.82
    def on_circle(bearing_deg, z):
        a = math.radians(bearing_deg)
        return W(cx + R * math.cos(a), cy + R * math.sin(a), z)
    rail = {'a': on_circle(160.0, 17.0), 'b': on_circle(143.0, 15.0)}
    corner = W(-0.25, 18.25, LB.ROOF_Z)
    meta = {
        'frame': {'origin': W(0, 0, 0), 'ex': D(1, 0, 0), 'ey': D(0, 1, 0), 'up': [0, 1, 0],
                  'note': 'world = origin + ex*x + ey*y + up*z, (x, y, z) in plan metres'},
        'site': {'center': W(cx, cy, cz),
                 'bbox': {'plan': [[bx0, by0], [bx1, by1]], 'z': [0.0, LB.HEAD_Z]},
                 'hero': hero, 'rail': rail,
                 # every way in from the street, the terrace stair included
                 'entrances': entrances,
                 # alternative opening shots for the owner to choose from
                 # (exterior review, build 2); nothing reads them yet
                 'hero_candidates': hero_candidates(W),
                 # the +4.8 roof garden (build 3): what stands on the deck,
                 # as plan rectangles, for the walk to keep the body out of;
                 # the walkable deck itself is plan_meta L01 nav 'terrace'
                 'terrace': {'z': LC.PARK_TOP,
                             'solids': [list(r) for r in LC.terrace_solids()],
                             'trees': [list(t) for t in LC.terrace_planters()]},
                 'boundary': LB.PLAN['site']['boundary']},
        'levels': levels,
        'blocks': blocks,
        'facades': LB.facade_runs(),
        'cores': cores,
        # ---- legacy keys, read by app.js until the next stage replaces them
        'block': {'corner': corner, 'center': W(cx, cy, cz),
                  'floors': {'n': len(LB.FACADE_LEVELS), 'base': LB.GROUND_H,
                             'h': LB.FLOOR_H, 'len': round(bx1 - bx0, 3),
                             'depth': 20.0}},
        'flat': {'origin': W(-0.25, 18.25, 34.5), 'ex': D(1, 0, 0), 'ey': D(0, -1, 0),
                 'center': W(41.25, 8.25, 34.5), 'size': [round(bx1 - bx0, 3), 20.0],
                 'plan_size': [round(bx1 - bx0, 3), 20.0],
                 'row': {'n': 0, 'starts': [0.0], 'end': round(bx1 - bx0, 3)},
                 'floor': 34.52, 'cut': 1.45, 'plan': {}, 'none': True},
    }
    with open(path, 'w') as f:
        json.dump(meta, f, indent=1)
    print('[build] meta -> %s' % path)
    return meta


EXPORT = '--noexport' not in args
if EXPORT or '--meta' in args:
    write_meta(os.path.join(os.path.dirname(HERE), 'web', 'scene_meta.json'))

# kits never render
for cname in ('kit', 'treekit', 'carkit'):
    c = bpy.data.collections.get(cname)
    if c:
        c.hide_render = True
        c.hide_viewport = True
        sc.collection.children.unlink(c) if c.name in \
            [x.name for x in sc.collection.children] else None

# ----------------------------------------------------------------- camera
def plan_world(x, y, z):
    m = Matrix.Translation(Vector(fit.ROOT_ORIGIN)) @ \
        Matrix.Rotation(math.radians(fit.BEARING), 4, 'Z')
    return m @ Vector((x, -y, z))


cam_data = bpy.data.cameras.new('shot')
cam_data.sensor_fit = 'HORIZONTAL'
cam_data.sensor_width = 36.0
cam_data.clip_start = 0.1
cam_data.clip_end = 2000.0
cam = bpy.data.objects.new('shot', cam_data)
if '--cam' in args:
    k = args.index('--cam')
    px, py, pz, tx, ty, tz, lens = map(float, args[k + 1:k + 8])
else:
    px, py, pz = LC.HERO_EYE
    tx, ty, tz = LC.HERO_AT
    lens = 22.0
cam_data.lens = lens
eye = plan_world(px, py, pz)
at = plan_world(tx, ty, tz)
# a shift lens: the camera stays level, the frame rises to the target, so
# verticals stay vertical as they do in the architect's renders
fwd = (at - eye)
hz = Vector((fwd.x, fwd.y, 0.0))
cam.location = eye
cam.rotation_euler = (math.radians(90.0), 0.0, math.atan2(hz.y, hz.x) - math.pi / 2)
res = (1600, 1000)
if '--res' in args:
    k = args.index('--res')
    res = (int(args[k + 1]), int(args[k + 2]))
ratio_h = res[1] / res[0]
elev = math.atan2(fwd.z, hz.length)
cam_data.shift_y = max(-0.6, min(0.6, math.tan(elev) * lens / 36.0 * 0.85))
sc.collection.objects.link(cam)
sc.camera = cam

# ----------------------------------------------------------------- lighting
sun_d = bpy.data.lights.new('sun', type='SUN')
sun_d.energy = 4.2
sun_d.angle = math.radians(1.1)
sun_d.color = (1.0, 0.953, 0.878)
sun = bpy.data.objects.new('sun', sun_d)
el = math.radians(fit.SUN_ELEV)
az = math.radians(fit.SUN_AZI)
d = Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
sun.location = d * 300.0
sun.rotation_euler = (math.acos(d.z), 0.0, math.atan2(d.y, d.x) + math.pi / 2)
sc.collection.objects.link(sun)

w = bpy.data.worlds.new('sky')
sc.world = w
w.use_nodes = True
nt = w.node_tree
nt.nodes.clear()
bg = nt.nodes.new('ShaderNodeBackground')
sky = nt.nodes.new('ShaderNodeTexSky')
sky.sky_type = 'MULTIPLE_SCATTERING'
for k, v in (('sun_elevation', el), ('sun_rotation', az), ('sun_intensity', 0.06),
             ('air_density', 1.25), ('dust_density', 1.1), ('ozone_density', 1.4),
             ('sun_disc', False), ('altitude', 120.0)):
    try:
        setattr(sky, k, v)
    except Exception:
        pass
out = nt.nodes.new('ShaderNodeOutputWorld')
nt.links.new(sky.outputs[0], bg.inputs[0])
nt.links.new(bg.outputs[0], out.inputs[0])
bg.inputs[1].default_value = 0.85

# ----------------------------------------------------------------- render cfg
sc.render.resolution_x = res[0]
sc.render.resolution_y = res[1]
sc.render.resolution_percentage = 100
sc.render.film_transparent = False
sc.view_settings.view_transform = 'AgX'
sc.view_settings.look = 'AgX - Base Contrast'
sc.view_settings.exposure = -0.35

# ----------------------------------------------------------------- bevels
# Nothing in the world has a 0 mm edge. A 12 mm chamfer with hardened normals
# catches the sun along every arris and is the cheapest realism there is.
# Only on meshes that are their own: the kit sources (windows, loggias) have
# it baked in already (lib_building.bake_bevel), so their linked duplicates
# stay ONE mesh on the wire - a modifier on an instance makes the exporter
# write a mesh per instance.
BEVEL_PREFIX = ('A_wall_', 'B_wall_', 'A_gable_', 'B_gable_', 'A_parapet', 'B_parapet',
                'A_stairhead', 'B_stairhead', 'A_slab_', 'B_slab_')
BEVEL_NAMES = ('podium_shell', 'podium_fascia', 'terrace_planters', 'street_lights',
               'podium_entrance_canopy', 'podium_entrance_plates', 'terrace_stairhouse',
               'pavement')
for ob in list(bpy.data.objects):
    base = ob.name.split('.')[0]
    if ob.type != 'MESH' or ob.data.users > 1 or not ob.users_scene:
        continue
    if base.startswith('bg_') and not base.endswith('_glass'):
        pass
    elif base.startswith(BEVEL_PREFIX):
        pass
    elif base not in BEVEL_NAMES:
        continue
    m = ob.modifiers.new('bevel', 'BEVEL')
    m.width = 0.012
    m.segments = 1
    m.limit_method = 'ANGLE'
    m.angle_limit = math.radians(35.0)
    m.harden_normals = True
    m.use_clamp_overlap = True


# ----------------------------------------------------------------- stats
tris = 0
objs = 0
for ob in sc.objects:
    if ob.type == 'MESH' and not ob.hide_render:
        objs += 1
        tris += len(ob.data.polygons)
print('[build] objects %d   faces %d   %.1fs' % (objs, tris, time.time() - t0))
for c in bpy.data.collections:
    n = sum(len(o.data.polygons) for o in c.objects if o.type == 'MESH')
    print('   %-14s objs %4d  faces %7d' % (c.name, len(c.objects), n))

# ----------------------------------------------------------------- export
if EXPORT:
    outp = os.path.join(os.path.dirname(HERE), 'web', 'scene.glb')
    bpy.ops.export_scene.gltf(
        filepath=outp, export_format='GLB',
        use_visible=True, export_apply=True,
        export_yup=True, export_cameras=False, export_lights=False,
        export_normals=True, export_texcoords=True,
        export_materials='EXPORT', export_extras=False,
        # forced on: the leaf tint lives in a colour attribute and the
        # default ('MATERIAL') only exports one a Blender material reads
        export_vertex_color='ACTIVE', export_all_vertex_colors=False,
        export_try_sparse_sk=False,
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=7,
        export_draco_position_quantization=14,
        export_draco_normal_quantization=10,
        export_draco_texcoord_quantization=12,
        export_draco_color_quantization=8)
    print('[build] exported %s  (%.2f MB)' % (outp, os.path.getsize(outp) / 1e6))
    import subprocess
    # images -> WebP (the street carries none today; harmless if so)
    try:
        slim = os.path.join(os.path.dirname(HERE), 'tools', 'slim_glb.py')
        if os.path.exists(slim):
            print(subprocess.run(['python3', slim, outp, '--max', '1024'],
                                 capture_output=True, text=True, timeout=300).stdout.strip())
    except Exception as e:
        print('[build] slim_glb skipped:', e)
    # the street file the page fetches; interiors ('in_*') would go to their own
    try:
        split = os.path.join(os.path.dirname(HERE), 'tools', 'split_glb.py')
        if os.path.exists(split):
            print(subprocess.run(['python3', split, outp],
                                 capture_output=True, text=True, timeout=300).stdout.strip())
        stale = os.path.join(os.path.dirname(HERE), 'web', 'scene-flat.glb')
        if os.path.exists(stale):
            os.remove(stale)          # the old show flat: no longer built or fetched
            print('[build] removed the stale web/scene-flat.glb')
    except Exception as e:
        print('[build] split_glb skipped:', e)
    # weld identical vertices and encode again (needs node; see the script)
    try:
        weld = os.path.join(os.path.dirname(HERE), 'tools', 'weld_glb.sh')
        if os.path.exists(weld):
            print(subprocess.run(['zsh', weld], capture_output=True, text=True,
                                 timeout=600).stdout.strip())
    except Exception as e:
        print('[build] weld_glb skipped:', e)

if '--render' in args:
    sc.render.engine = 'BLENDER_EEVEE'
    try:
        sc.eevee.use_raytracing = True
        sc.eevee.use_shadows = True
        sc.eevee.taa_render_samples = 32
    except Exception as e:
        print('eevee cfg', e)
    outp = os.path.join(HERE, 'preview.png')
    if '--out' in args:
        outp = args[args.index('--out') + 1]
    sc.render.filepath = outp
    bpy.ops.render.render(write_still=True)
    print('[build] preview written', outp)
