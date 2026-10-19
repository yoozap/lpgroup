# -*- coding: utf-8 -*-
"""
Shared helpers for the procedural reconstruction of the reference render.

World frame (Blender, Z-up, metres):
    camera sits at (0, 0, 1.65) and looks along +Y
    glTF export converts  Blender(x, y, z) -> three.js(x, z, -y)
    so Blender +Y  ==  three.js -Z  (camera forward)
"""
import bpy, bmesh, math, random, os
from mathutils import Vector, Matrix, Euler

TAU = math.pi * 2.0
rnd = random.Random(20260108)

# ---------------------------------------------------------------- scene reset
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    sc.unit_settings.scale_length = 1.0
    return sc


def collection(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(c)
    return c


# ---------------------------------------------------------------- materials
MATS = {}

def mat(name, base=(0.5, 0.5, 0.5), rough=0.8, metal=0.0, emis=None, emis_str=0.0,
        alpha=1.0, ior=1.45, transmission=0.0):
    """Principled BSDF material -> exports cleanly to glTF pbrMetallicRoughness."""
    if name in MATS:
        return MATS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    bsdf = m.node_tree.nodes.get('Principled BSDF')
    i = bsdf.inputs
    i['Base Color'].default_value = (base[0], base[1], base[2], 1.0)
    i['Roughness'].default_value = rough
    i['Metallic'].default_value = metal
    if 'IOR' in i:
        i['IOR'].default_value = ior
    if 'Transmission Weight' in i:
        i['Transmission Weight'].default_value = transmission
    if emis is not None:
        i['Emission Color'].default_value = (emis[0], emis[1], emis[2], 1.0)
        i['Emission Strength'].default_value = emis_str
    if alpha < 1.0:
        i['Alpha'].default_value = alpha
        m.blend_method = 'BLEND'
    MATS[name] = m
    return m


def srgb(hexstr):
    """#rrggbb -> linear float triple."""
    h = hexstr.lstrip('#')
    out = []
    for k in (0, 2, 4):
        c = int(h[k:k + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


# ---------------------------------------------------------------- mesh builder
class MB:
    """Accumulates verts/faces, optionally per-material; emits one Blender mesh.

    `col` carries an optional per-vertex colour. Foliage uses it to give every
    single leaf its own tint, which a world-space noise cannot do - a noise
    varies over centimetres of space, not from one leaf to the next.
    """
    __slots__ = ('v', 'f', 'smooth', 'col')

    def __init__(self):
        self.v = []
        self.f = []
        self.smooth = set()
        self.col = []

    def add(self, verts, faces, smooth=False):
        o = len(self.v)
        self.v.extend(verts)
        for fc in faces:
            if smooth:
                self.smooth.add(len(self.f))
            self.f.append(tuple(o + k for k in fc))
        return o

    def quad(self, a, b, c, d, smooth=False):
        self.add([a, b, c, d], [(0, 1, 2, 3)], smooth)

    def box(self, p0, p1, skip=()):
        """Axis aligned box, outward winding. skip: any of -x +x -y +y -z +z"""
        x0, y0, z0 = p0
        x1, y1, z1 = p1
        if x1 < x0: x0, x1 = x1, x0
        if y1 < y0: y0, y1 = y1, y0
        if z1 < z0: z0, z1 = z1, z0
        v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        faces = {'-z': (0, 3, 2, 1), '+z': (4, 5, 6, 7), '-y': (0, 1, 5, 4),
                 '+y': (2, 3, 7, 6), '-x': (3, 0, 4, 7), '+x': (1, 2, 6, 5)}
        fl = [f for k, f in faces.items() if k not in skip]
        self.add(v, fl)

    def panel(self, x0, x1, z0, z1, y0, y1, skip=()):
        self.box((x0, y0, z0), (x1, y1, z1), skip)

    def plane_xy(self, x0, y0, x1, y1, z):
        self.quad((x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z))

    def cyl(self, p0, p1, r0, r1=None, seg=12, caps=True):
        r1 = r0 if r1 is None else r1
        p0 = Vector(p0); p1 = Vector(p1)
        ax = (p1 - p0)
        L = ax.length
        if L < 1e-6:
            return
        ax = ax / L
        up = Vector((0, 0, 1)) if abs(ax.z) < 0.95 else Vector((1, 0, 0))
        t1 = ax.cross(up).normalized()
        t2 = ax.cross(t1).normalized()
        ring0, ring1 = [], []
        for k in range(seg):
            a = TAU * k / seg
            d = t1 * math.cos(a) + t2 * math.sin(a)
            ring0.append(tuple(p0 + d * r0))
            ring1.append(tuple(p1 + d * r1))
        o = len(self.v)
        self.v.extend(ring0)
        self.v.extend(ring1)
        for k in range(seg):
            n = (k + 1) % seg
            self.smooth.add(len(self.f))
            self.f.append((o + k, o + n, o + seg + n, o + seg + k))
        if caps:
            o2 = len(self.v)
            self.v.extend(ring0); self.v.extend(ring1)
            self.f.append(tuple(o2 + seg - 1 - k for k in range(seg)))
            self.f.append(tuple(o2 + seg + k for k in range(seg)))

    def sphere(self, c, r, seg=16, rings=10, scale=(1, 1, 1)):
        cx, cy, cz = c
        sx, sy, sz = scale
        o = len(self.v)
        for i in range(rings + 1):
            phi = math.pi * i / rings
            for j in range(seg):
                th = TAU * j / seg
                self.v.append((cx + r * sx * math.sin(phi) * math.cos(th),
                               cy + r * sy * math.sin(phi) * math.sin(th),
                               cz + r * sz * math.cos(phi)))
        for i in range(rings):
            for j in range(seg):
                n = (j + 1) % seg
                a = o + i * seg + j; b = o + i * seg + n
                c_ = o + (i + 1) * seg + n; d = o + (i + 1) * seg + j
                self.smooth.add(len(self.f))
                self.f.append((a, b, c_, d))

    def to_object(self, name, material, coll=None, shade_smooth_all=False):
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.v, [], self.f)
        me.validate(verbose=False)
        if self.col:
            if len(self.col) < len(self.v):
                self.col.extend([(1.0, 1.0, 1.0)] * (len(self.v) - len(self.col)))
            at = me.color_attributes.new(name='Col', type='FLOAT_COLOR',
                                         domain='POINT')
            flat = []
            for c in self.col[:len(me.vertices)]:
                flat.extend((c[0], c[1], c[2], 1.0))
            at.data.foreach_set('color', flat)
        if material is not None:
            me.materials.append(material)
        if shade_smooth_all:
            for p in me.polygons:
                p.use_smooth = True
        elif self.smooth:
            for idx in self.smooth:
                if idx < len(me.polygons):
                    me.polygons[idx].use_smooth = True
        me.update()
        ob = bpy.data.objects.new(name, me)
        (coll or bpy.context.scene.collection).objects.link(ob)
        return ob


def link_dup(src, name, loc=(0, 0, 0), rot_z=0.0, scale=(1, 1, 1), coll=None):
    """Instance sharing mesh data -> one glTF mesh referenced by many nodes."""
    ob = bpy.data.objects.new(name, src.data)
    ob.location = loc
    ob.rotation_euler = (0, 0, rot_z)
    ob.scale = scale
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def mirror_y(mb, d=0.0):
    """Reflect everything an MB has accumulated in the plane y = d/2 and
    re-wind every face, so the mesh keeps its normals pointing outwards.

    Block A's back elevation is its street elevation seen from the other
    side, so it is built by the same code and then turned round here. A
    rotation would do it without the re-winding, but it reverses x as well:
    the bays would no longer stand behind the ones at the front and the
    flats behind them would miss their own openings by a bay.
    """
    mb.v = [(v[0], d - v[1], v[2]) for v in mb.v]
    mb.f = [tuple(reversed(f)) for f in mb.f]
    return mb


def mirror_obj_y(src, name, coll=None, d=0.0):
    """A copy of `src` whose mesh is reflected in the plane y = d/2."""
    me = src.data.copy()
    me.name = name
    for v in me.vertices:
        v.co.y = d - v.co.y
    me.flip_normals()
    ob = bpy.data.objects.new(name, me)
    (coll or bpy.context.scene.collection).objects.link(ob)
    return ob


def frame_for(x0, x1, z0, z1, ox0, ox1, oz0, oz1, y0, y1, mb):
    """Wall cell with a rectangular opening -> four surrounding panels."""
    if ox0 > x0: mb.panel(x0, ox0, z0, z1, y0, y1)
    if x1 > ox1: mb.panel(ox1, x1, z0, z1, y0, y1)
    if oz0 > z0: mb.panel(ox0, ox1, z0, oz0, y0, y1)
    if z1 > oz1: mb.panel(ox0, ox1, oz1, z1, y0, y1)


def frame_for_yz(ya, yb, za, zb, oya, oyb, oza, ozb, xa, xb, mb):
    """Same as frame_for but for a wall whose normal runs along X."""
    if oya > ya: mb.box((xa, ya, za), (xb, oya, zb))
    if yb > oyb: mb.box((xa, oyb, za), (xb, yb, zb))
    if oza > za: mb.box((xa, oya, za), (xb, oyb, oza))
    if zb > ozb: mb.box((xa, oya, ozb), (xb, oyb, zb))
