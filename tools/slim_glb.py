#!/usr/bin/env python3
"""Re-encode every picture inside a .glb as WebP, in place.

Blender writes the props' 1k maps back out as PNG (glTF's AUTO), which is what
made web/scene.glb 19 MB - 12 MB of it pictures of furniture. Its own WEBP
export is not usable here: it silently drops the occlusion/roughness/metal
maps it packs itself, and the file then has textures pointing at nothing. So
the pictures are converted after the export instead.

    python3 tools/slim_glb.py web/scene.glb [--quality 80] [--max 1024]

Geometry, accessors and the Draco buffers are copied through untouched; only
the image buffer views change size, so every view is re-laid out and every
offset rewritten. Textures gain EXT_texture_webp, which three reads.
"""
import json, struct, sys, io, os
from PIL import Image

JSON_CHUNK, BIN_CHUNK = 0x4E4F534A, 0x004E4942


def read_glb(path):
    b = open(path, 'rb').read()
    magic, ver, total = struct.unpack('<III', b[:12])
    assert magic == 0x46546C67, 'not a glb'
    off, js, bin_ = 12, None, b''
    while off < total:
        ln, ty = struct.unpack('<II', b[off:off + 8])
        data = b[off + 8: off + 8 + ln]
        if ty == JSON_CHUNK: js = json.loads(data.decode('utf-8'))
        elif ty == BIN_CHUNK: bin_ = data
        off += 8 + ln + (-ln % 4)
    return js, bin_


def write_glb(path, js, bin_):
    jb = json.dumps(js, separators=(',', ':')).encode('utf-8')
    jb += b' ' * (-len(jb) % 4)
    bb = bin_ + b'\0' * (-len(bin_) % 4)
    total = 12 + 8 + len(jb) + (8 + len(bb) if bb else 0)
    out = [struct.pack('<III', 0x46546C67, 2, total),
           struct.pack('<II', len(jb), JSON_CHUNK), jb]
    if bb: out += [struct.pack('<II', len(bb), BIN_CHUNK), bb]
    open(path, 'wb').write(b''.join(out))


def main():
    path = sys.argv[1]
    q = int(sys.argv[sys.argv.index('--quality') + 1]) if '--quality' in sys.argv else 80
    mx = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else 1024
    js, bin_ = read_glb(path)
    views = js.get('bufferViews', [])
    before = os.path.getsize(path)

    # 1. every image -> webp bytes, kept against its buffer view
    new_data = {}
    kept = 0
    for i, im in enumerate(js.get('images', [])):
        bv = im.get('bufferView')
        if bv is None: continue
        v = views[bv]
        raw = bin_[v['byteOffset']: v['byteOffset'] + v['byteLength']]
        pic = Image.open(io.BytesIO(raw))
        if im.get('mimeType') == 'image/webp' and max(pic.size) <= mx:
            continue                      # already done, and small enough
        if max(pic.size) > mx:
            pic.thumbnail((mx, mx), Image.LANCZOS)
        if pic.mode not in ('RGB', 'RGBA'):
            pic = pic.convert('RGBA' if 'A' in pic.mode or pic.mode == 'P' else 'RGB')
        buf = io.BytesIO()
        pic.save(buf, format='WEBP', quality=q, method=5)
        new_data[bv] = buf.getvalue()
        im['mimeType'] = 'image/webp'
        kept += 1

    if not new_data:
        print('[slim] nothing to do'); return

    # 2. re-lay the binary chunk, keeping every view's contents intact
    out = bytearray()
    for i, v in enumerate(views):
        data = new_data.get(i, bin_[v['byteOffset']: v['byteOffset'] + v['byteLength']])
        pad = -len(out) % 4
        out += b'\0' * pad
        v['byteOffset'] = len(out)
        v['byteLength'] = len(data)
        out += data
    js['buffers'][0]['byteLength'] = len(out)

    # 3. a webp image is only reachable through the extension
    for t in js.get('textures', []):
        if 'source' in t:
            t.setdefault('extensions', {})['EXT_texture_webp'] = {'source': t.pop('source')}
    used = set(js.get('extensionsUsed', []))
    used.add('EXT_texture_webp')
    js['extensionsUsed'] = sorted(used)
    req = set(js.get('extensionsRequired', []))
    req.add('EXT_texture_webp')
    js['extensionsRequired'] = sorted(req)

    write_glb(path, js, bytes(out))
    print('[slim] %d images -> webp q%d, %.2f MB -> %.2f MB'
          % (kept, q, before / 1e6, os.path.getsize(path) / 1e6))


if __name__ == '__main__':
    main()
