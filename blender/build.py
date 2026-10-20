# -*- coding: utf-8 -*-
"""Build the whole scene and export it.

  /Applications/Blender.app/Contents/MacOS/Blender -b -P blender/build.py -- [--render] [--noexport] [--out preview.png]
"""
import sys, os, math, time
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
import lib_building, lib_city, lib_flat
importlib.reload(lib_building)
importlib.reload(lib_city)
importlib.reload(lib_flat)
LB, LC, LF = lib_building, lib_city, lib_flat

LB.build_materials()
LF.build_materials()

# ----------------------------------------------------------------- hierarchy
root = bpy.data.objects.new('BuildingRoot', None)
root.empty_display_size = 2.0
sc.collection.objects.link(root)
root.location = fit.A_ORIGIN
root.rotation_euler = (0, 0, math.radians(fit.A_BEARING))

collA, instA, kit, A_LEN, A_DEPTH = LB.build_block_a(sc.collection)
collB = LB.build_block_b(kit)
collP = LC.build_podium()
collT = LC.build_terrace()
collS = LC.build_signage()
collSt = LC.build_street()
collBg = LC.build_background()
# no vehicles and no people: the scene is the architecture only
collPl = LC.build_planting()
# the show flat on the top floor corner, and the cutaway that reveals it
collF = LF.build_flat()

for c in (collA, instA, collB, collP, collT, collS, collSt, collBg,
          collPl, LBD.collection('trees'), collF):
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
LF.write_meta(root, os.path.join(os.path.dirname(HERE), 'web', 'scene_meta.json'))

# kits never render
for cname in ('kit', 'treekit', 'carkit'):
    c = bpy.data.collections.get(cname)
    if c:
        c.hide_render = True
        c.hide_viewport = True
        sc.collection.children.unlink(c) if c.name in \
            [x.name for x in sc.collection.children] else None

# ----------------------------------------------------------------- camera
cam_data = bpy.data.cameras.new('shot')
cam_data.lens = fit.LENS_MM
cam_data.sensor_fit = 'HORIZONTAL'
cam_data.sensor_width = 36.0
cam_data.shift_x = 0.0
cam_data.shift_y = fit.SHIFT_Y
cam_data.clip_start = 0.1
cam_data.clip_end = 2000.0
cam = bpy.data.objects.new('shot', cam_data)
cam.location = (0.0, 0.0, fit.CAM_Z)
cam.rotation_euler = (math.radians(90.0), 0.0, 0.0)
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
sc.render.resolution_x = fit.IMG_W
sc.render.resolution_y = fit.IMG_H
sc.render.resolution_percentage = 50
sc.render.film_transparent = False
sc.view_settings.view_transform = 'AgX'
sc.view_settings.look = 'AgX - Base Contrast'
sc.view_settings.exposure = -0.35

args = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []

# ----------------------------------------------------------------- bevels
# Nothing in the world has a 0 mm edge. A 12 mm chamfer with hardened normals
# catches the sun along every arris and is the cheapest realism there is.
BEVEL_NAMES = ('A_facade_dark', 'A_facade_back', 'A_gable_light', 'A_mass', 'B_gallery', 'B_dark',
               'B_piers', 'podium_shell', 'podium_fascia', 'loggia_shell', 'loggia_frame',
               'winA_frame', 'winB_frame', 'winA_sill', 'winB_sill',
               'terrace_planters', 'kerb', 'street_lights')
for ob in list(bpy.data.objects):
    base = ob.name.split('.')[0]
    if ob.type != 'MESH':
        continue
    if base.startswith('bg_') and not base.endswith('_glass'):
        pass
    elif base.startswith('loggia_shell') or base.startswith('loggia_frame'):
        pass
    elif base.startswith('win') and (base.endswith('_frame') or base.endswith('_sill')):
        pass
    elif base.startswith('flat_'):
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
if '--noexport' not in args:
    outp = os.path.join(os.path.dirname(HERE), 'web', 'scene.glb')
    bpy.ops.export_scene.gltf(
        filepath=outp, export_format='GLB',
        use_visible=True, export_apply=True,
        export_yup=True, export_cameras=False, export_lights=False,
        export_normals=True, export_texcoords=True,   # downloaded models carry UVs
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
    # The exporter writes the props' 1k maps back out as PNG, which is most of
    # the file. Its own WEBP setting cannot be used - it drops the ORM maps it
    # packs itself and leaves textures pointing at nothing - so the pictures
    # are converted afterwards instead. Harmless if it is not there.
    try:
        import subprocess
        slim = os.path.join(os.path.dirname(HERE), 'tools', 'slim_glb.py')
        if os.path.exists(slim):
            # 1024, not 512: measured in the Scene 2 shot, the largest
            # furniture resolves at 0.7 texels per screen pixel at 512 - the
            # frame has more pixels across a cushion than the texture has
            # texels, so it is the texture that is the limit, not the render.
            # 1024 puts that at 2.8 and costs about 2 MB in the GLB.
            print(subprocess.run(['python3', slim, outp, '--max', '1024'],
                                 capture_output=True, text=True, timeout=300).stdout.strip())
    except Exception as e:
        print('[build] slim_glb skipped:', e)

    # ...and then cut in two. The page does not fetch this file: the first
    # frame waits for `scene-street.glb` and the show flat's 3.6 MB follows
    # behind it, because the flat is not in that frame. Without this step a
    # rebuild leaves the two halves stale while `scene.glb` moves on.
    try:
        import subprocess
        split = os.path.join(os.path.dirname(HERE), 'tools', 'split_glb.py')
        if os.path.exists(split):
            print(subprocess.run(['python3', split, outp],
                                 capture_output=True, text=True, timeout=300).stdout.strip())
    except Exception as e:
        print('[build] split_glb skipped:', e)

if '--render' in args:
    sc.render.engine = 'BLENDER_EEVEE'
    try:
        sc.eevee.use_raytracing = True
        sc.eevee.use_shadows = True
        sc.eevee.taa_render_samples = 48
    except Exception as e:
        print('eevee cfg', e)
    outp = os.path.join(HERE, 'preview.png')
    if '--out' in args:
        outp = args[args.index('--out') + 1]
    sc.render.filepath = outp
    bpy.ops.render.render(write_still=True)
    print('[build] preview written')
