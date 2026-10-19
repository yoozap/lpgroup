#!/usr/bin/env python3
"""Pixel diff two renders: mean / max channel error and where it sits.

    python3 tools/imgdiff.py a.png b.png [out_diff.jpg]
"""
import sys
from PIL import Image, ImageChops

a = Image.open(sys.argv[1]).convert('RGB')
b = Image.open(sys.argv[2]).convert('RGB')
if a.size != b.size:
    print('size differs', a.size, b.size); sys.exit(1)
d = ImageChops.difference(a, b)
st = d.getbbox()
px = list(d.getdata())
n = len(px)
tot = sum(max(p) for p in px)
mx = max(max(p) for p in px)
over = sum(1 for p in px if max(p) > 8)
print(f'size {a.size}  mean |err| {tot/n:.3f}/255  max {mx}  pixels>8: {over} ({100*over/n:.3f}%)  bbox {st}')
if len(sys.argv) > 3:
    d.point(lambda v: min(255, v * 8)).save(sys.argv[3], quality=92)
