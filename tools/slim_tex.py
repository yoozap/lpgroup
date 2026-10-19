#!/usr/bin/env python3
"""Convert the scanned maps in web/tex (and the plan overlay) to WebP.

    python3 tools/slim_tex.py [--delete]

Colour maps go at quality 82, normal and displacement maps at 92 - a normal
map is a direction, and the banding a low quality leaves in one shows up as
facets in the light. The old files stay unless --delete is given.
"""
import os, sys, glob
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DELETE = '--delete' in sys.argv


def conv(path, q):
    out = os.path.splitext(path)[0] + '.webp'
    im = Image.open(path)
    if im.mode not in ('RGB', 'RGBA'):
        im = im.convert('RGBA' if im.mode in ('LA', 'PA', 'P') and 'transparency' in im.info else 'RGB')
    im.save(out, format='WEBP', quality=q, method=6)
    a, b = os.path.getsize(path), os.path.getsize(out)
    # a well packed JPEG sometimes beats WebP on a noisy normal map; keep
    # whichever file is actually smaller
    if b >= a:
        os.remove(out)
        print('  %-26s %6.0f KB  kept (webp was %.0f KB)' % (os.path.basename(path), a / 1024, b / 1024))
        return a, a
    print('  %-26s %6.0f KB -> %6.0f KB  (q%d)' % (os.path.basename(path), a / 1024, b / 1024, q))
    if DELETE: os.remove(path)
    return a, b


tot_a = tot_b = 0
for f in sorted(glob.glob(os.path.join(HERE, 'web', 'tex', '*.png'))
                + glob.glob(os.path.join(HERE, 'web', 'tex', '*.jpg'))):
    q = 92 if ('_nor' in f or '_disp' in f) else 82
    a, b = conv(f, q); tot_a += a; tot_b += b

plan = os.path.join(HERE, 'web', 'plan_overlay.png')
if os.path.exists(plan):
    a, b = conv(plan, 88); tot_a += a; tot_b += b

print('[slim-tex] %.2f MB -> %.2f MB' % (tot_a / 1e6, tot_b / 1e6))
