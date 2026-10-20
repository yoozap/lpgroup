#!/usr/bin/env python3
"""Split web/scene.glb into the street and the show flat.

    python3 tools/split_glb.py [web/scene.glb] [--check]

`scene.glb` is 12.52 MB and 9.09 MB of it is on the critical path to the
first frame - the largest single thing the page waits for. But the show
flat is not in that frame: it stands inside the block with `visible =
false` until somebody hovers a storey, and `prepareScene2()` spends the
second after `ready` warming it anyway. Its bytes are being paid for a
second before they are wanted.

The partition is unusually clean, which is what makes this safe:

    street geometry      7.16 MB
    flat geometry        1.77 MB
    flat images (33)     2.50 MB      - the street uses NONE of them
    shared bufferViews      0
    shared materials        8          (JSON only, duplicated into both)

So nothing has to be cut in half. Every node is a direct child of
`BuildingRoot` - 1048 of the 2814 are named `flat*` - and the two sides
touch disjoint buffers.

Writes `scene-street.glb` and `scene-flat.glb` beside the input. Both keep
`BuildingRoot` with its transform, so a node's world matrix is the same
whichever file it arrived in, and `app.js` can add the flat's children to
the scene exactly where the combined file had put them.

`--check` re-reads both and verifies that every node, mesh, material and
image of the original turns up in exactly one of them (images and
geometry) or at least one (materials, which may be shared).
"""
import json, struct, sys, os, collections

JSON_CHUNK, BIN_CHUNK = 0x4E4F534A, 0x004E4942
IS_FLAT = lambda name: (name or '').startswith('flat')


def read_glb(path):
    b = open(path, 'rb').read()
    magic, ver, total = struct.unpack('<III', b[:12])
    assert magic == 0x46546C67, 'not a glb'
    off, js, bin_ = 12, None, b''
    while off < total:
        ln, ty = struct.unpack('<II', b[off:off + 8])
        data = b[off + 8: off + 8 + ln]
        if ty == JSON_CHUNK:
            js = json.loads(data.decode('utf-8'))
        elif ty == BIN_CHUNK:
            bin_ = data
        off += 8 + ln + (-ln % 4)
    return js, bin_


def write_glb(path, js, bin_):
    jb = json.dumps(js, separators=(',', ':')).encode('utf-8')
    jb += b' ' * (-len(jb) % 4)
    bb = bytes(bin_) + b'\0' * (-len(bin_) % 4)
    total = 12 + 8 + len(jb) + (8 + len(bb) if bb else 0)
    with open(path, 'wb') as f:
        f.write(struct.pack('<III', 0x46546C67, 2, total))
        f.write(struct.pack('<II', len(jb), JSON_CHUNK))
        f.write(jb)
        if bb:
            f.write(struct.pack('<II', len(bb), BIN_CHUNK))
            f.write(bb)
    return total


def prim_views(js, mi, views, mats):
    """Every bufferView and material one mesh depends on."""
    for pr in js['meshes'][mi]['primitives']:
        if 'material' in pr:
            mats.add(pr['material'])
        ext = pr.get('extensions', {}).get('KHR_draco_mesh_compression')
        if ext:
            views.add(ext['bufferView'])
            # the accessors still describe the decoded data; with Draco they
            # carry no bufferView of their own, but keep any that do
        for a in list(pr.get('attributes', {}).values()) + \
                 ([pr['indices']] if 'indices' in pr else []):
            v = js['accessors'][a].get('bufferView')
            if v is not None:
                views.add(v)
        for t in pr.get('targets', []) or []:
            for a in t.values():
                v = js['accessors'][a].get('bufferView')
                if v is not None:
                    views.add(v)


def tex_sources(js, ti):
    """An image index for a texture, following EXT_texture_webp."""
    t = js['textures'][ti]
    s = t.get('source')
    if s is None:
        s = t.get('extensions', {}).get('EXT_texture_webp', {}).get('source')
    return s


def material_textures(js, mi, texs):
    """Every texture index a material refers to, wherever it is nested."""
    def walk(d):
        if isinstance(d, dict):
            if 'index' in d and isinstance(d['index'], int) and \
                    set(d) <= {'index', 'texCoord', 'scale', 'strength', 'extensions'}:
                texs.add(d['index'])
            for v in d.values():
                walk(v)
        elif isinstance(d, list):
            for v in d:
                walk(v)
    walk(js['materials'][mi])


def build(js, bin_, keep_nodes, label):
    """One side of the split, with every index space renumbered."""
    meshes, mats, views, texs = set(), set(), set(), set()
    for i in keep_nodes:
        n = js['nodes'][i]
        if 'mesh' in n:
            meshes.add(n['mesh'])
    for m in meshes:
        prim_views(js, m, views, mats)
    for m in mats:
        material_textures(js, m, texs)
    imgs = {s for s in (tex_sources(js, t) for t in texs) if s is not None}
    for im in imgs:
        v = js['images'][im].get('bufferView')
        if v is not None:
            views.add(v)
    samplers = {js['textures'][t]['sampler'] for t in texs
                if 'sampler' in js['textures'][t]}

    # accessors reachable from the kept meshes
    accs = set()
    for m in meshes:
        for pr in js['meshes'][m]['primitives']:
            for a in list(pr.get('attributes', {}).values()) + \
                     ([pr['indices']] if 'indices' in pr else []):
                accs.add(a)
            ext = pr.get('extensions', {}).get('KHR_draco_mesh_compression')
            if ext:
                for a in ext.get('attributes', {}).values():
                    pass            # draco attribute ids, not accessor indices
    for a in list(accs):
        v = js['accessors'][a].get('bufferView')
        if v is not None:
            views.add(v)

    remap = lambda S: {old: new for new, old in enumerate(sorted(S))}
    rN, rM, rMat, rT, rI, rS, rA, rV = (remap(keep_nodes), remap(meshes), remap(mats),
                                        remap(texs), remap(imgs), remap(samplers),
                                        remap(accs), remap(views))

    out = {k: v for k, v in js.items()
           if k not in ('nodes', 'meshes', 'materials', 'textures', 'images',
                        'samplers', 'accessors', 'bufferViews', 'buffers', 'scenes')}

    # --- bufferViews, repacked into a fresh binary chunk
    blob = bytearray()
    new_views = []
    for old in sorted(views):
        bv = dict(js['bufferViews'][old])
        off, ln = bv.get('byteOffset', 0), bv['byteLength']
        while len(blob) % 4:
            blob.append(0)
        bv['byteOffset'] = len(blob)
        bv['buffer'] = 0
        blob += bin_[off:off + ln]
        new_views.append(bv)
    out['bufferViews'] = new_views
    out['buffers'] = [{'byteLength': len(blob)}]

    out['accessors'] = []
    for old in sorted(accs):
        a = dict(js['accessors'][old])
        if 'bufferView' in a:
            a['bufferView'] = rV[a['bufferView']]
        out['accessors'].append(a)

    out['images'] = []
    for old in sorted(imgs):
        im = dict(js['images'][old])
        if 'bufferView' in im:
            im['bufferView'] = rV[im['bufferView']]
        out['images'].append(im)

    out['samplers'] = [js['samplers'][o] for o in sorted(samplers)]

    out['textures'] = []
    for old in sorted(texs):
        t = json.loads(json.dumps(js['textures'][old]))
        if 'source' in t:
            t['source'] = rI[t['source']]
        if 'sampler' in t:
            t['sampler'] = rS[t['sampler']]
        ex = t.get('extensions', {}).get('EXT_texture_webp')
        if ex and 'source' in ex:
            ex['source'] = rI[ex['source']]
        out['textures'].append(t)

    out['materials'] = []
    for old in sorted(mats):
        m = json.loads(json.dumps(js['materials'][old]))

        def fix(d):
            if isinstance(d, dict):
                if 'index' in d and isinstance(d['index'], int) and \
                        set(d) <= {'index', 'texCoord', 'scale', 'strength', 'extensions'}:
                    d['index'] = rT[d['index']]
                for v in d.values():
                    fix(v)
            elif isinstance(d, list):
                for v in d:
                    fix(v)
        fix(m)
        out['materials'].append(m)

    out['meshes'] = []
    for old in sorted(meshes):
        me = json.loads(json.dumps(js['meshes'][old]))
        for pr in me['primitives']:
            pr['attributes'] = {k: rA[v] for k, v in pr['attributes'].items()}
            if 'indices' in pr:
                pr['indices'] = rA[pr['indices']]
            if 'material' in pr:
                pr['material'] = rMat[pr['material']]
            ext = pr.get('extensions', {}).get('KHR_draco_mesh_compression')
            if ext:
                ext['bufferView'] = rV[ext['bufferView']]
        out['meshes'].append(me)

    out['nodes'] = []
    for old in sorted(keep_nodes):
        n = dict(js['nodes'][old])
        if 'mesh' in n:
            n['mesh'] = rM[n['mesh']]
        if 'children' in n:
            kids = [rN[c] for c in n['children'] if c in rN]
            if kids:
                n['children'] = kids
            else:
                n.pop('children')
        out['nodes'].append(n)

    out['scenes'] = [{'nodes': [rN[i] for i in js['scenes'][0]['nodes'] if i in rN]}]
    out['scene'] = 0
    return out, blob


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    src = args[0] if args else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), '..', 'web', 'scene.glb')
    js, bin_ = read_glb(src)
    nodes = js['nodes']

    # Every node is a direct child of BuildingRoot, so "the flat" is a flat
    # list of names - but walk the tree anyway, so a build that nests them
    # later still splits correctly.
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get('children', []):
            parent[c] = i
    side = {}

    def walk(i, s):
        s = 'flat' if IS_FLAT(nodes[i].get('name')) else s
        side[i] = s
        for c in nodes[i].get('children', []):
            walk(c, s)
    for r in js['scenes'][0]['nodes']:
        walk(r, 'street')

    # A root that carries flat children must exist in BOTH files, as a
    # transform-only node, or the flat's pieces land at the wrong place.
    def keep_for(want):
        keep = {i for i, s in side.items() if s == want}
        for i in list(keep):
            p = parent.get(i)
            while p is not None and p not in keep:
                keep.add(p)
                p = parent.get(p)
        return keep

    out = {}
    for want, name in (('street', 'scene-street.glb'), ('flat', 'scene-flat.glb')):
        keep = keep_for(want)
        # an ancestor kept only to carry children must not drag its mesh along
        doc, blob = build(js, bin_, keep, want)
        for i, old in enumerate(sorted(keep)):
            if side[old] != want and 'mesh' in doc['nodes'][i]:
                doc['nodes'][i].pop('mesh')
        path = os.path.join(os.path.dirname(os.path.abspath(src)), name)
        total = write_glb(path, doc, blob)
        out[want] = (path, total, doc)
        print('  %-18s %7.2f MB   %4d nodes  %4d meshes  %3d materials  %3d images'
              % (name, total / 1e6, len(doc['nodes']), len(doc['meshes']),
                 len(doc['materials']), len(doc['images'])))
    a = os.path.getsize(src)
    print('  %-18s %7.2f MB   (was one file)' % (os.path.basename(src), a / 1e6))
    print('  first frame now waits for %.2f MB instead of %.2f'
          % (out['street'][1] / 1e6, a / 1e6))

    if '--check' in sys.argv:
        print('\ncheck:')
        s, f = out['street'][2], out['flat'][2]
        named = lambda d: {n.get('name') for n in d['nodes'] if n.get('name')}
        orig = {n.get('name') for n in nodes if n.get('name')}
        both = named(s) & named(f)
        print('  node names: %d original, %d street, %d flat, %d in both (the carried roots)'
              % (len(orig), len(named(s)), len(named(f)), len(both)))
        missing = orig - named(s) - named(f)
        print('  node names in neither file: %d %s' % (len(missing), sorted(missing)[:5]))
        print('  images: %d original -> street %d, flat %d'
              % (len(js.get('images', [])), len(s['images']), len(f['images'])))
        mo = {m.get('name') for m in js['materials']}
        print('  materials: %d original -> street %d, flat %d, shared %d'
              % (len(mo), len(s['materials']), len(f['materials']),
                 len({m.get('name') for m in s['materials']} &
                     {m.get('name') for m in f['materials']})))
        om = sum(len(m['primitives']) for m in js['meshes'])
        nm = sum(len(m['primitives']) for m in s['meshes']) + \
             sum(len(m['primitives']) for m in f['meshes'])
        print('  primitives: %d original, %d across the two%s'
              % (om, nm, '' if om == nm else '   <-- MISMATCH'))


if __name__ == '__main__':
    main()
