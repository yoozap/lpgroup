#!/bin/zsh
# Weld the two model halves and encode them again: 9.31 -> 8.03 MB on the wire.
#
#     zsh tools/weld_glb.sh            # web/scene-street.glb, web/scene-flat.glb
#
# Blender's exporter hands Draco a vertex per CORNER wherever it thinks a
# face might need one, and with `export_apply` on a bevelled mesh that is
# most of them. Once the attributes have been quantised - 14 bits of
# position, 10 of normal, 12 of texcoord, 8 of colour, see blender/build.py -
# a great many of those vertices are bit for bit the same vertex:
# `A_facade_dark` alone is 72,392 of them where 22,447 are distinct. Draco
# codes every one, because it was given every one.
#
# This decodes each primitive, welds the vertices that are IDENTICAL in every
# attribute (tolerance zero - nothing is moved onto anything) and encodes it
# again at the same bits:
#
#     scene-street.glb   7.65 -> 5.95 MB    5.71 -> 4.71 MB gzipped
#     scene-flat.glb     4.87 -> 4.32 MB    3.60 -> 3.32 MB gzipped
#     decoded vertices   1.95 M -> 1.32 M   (a third less for the page to
#                                            decode, weld and upload at boot)
#
# It is lossless in the sense that matters and it was checked rather than
# assumed: both files decoded before and after and compared as multisets of
# exact-float triangles. 998 of 1390 primitives are identical; the other 392
# are identical once the triangles with two coincident corners are left out
# - 30,187 of 1.2 M, collapsed bevels that never drew a pixel. Every node,
# its transform, its mesh's materials and all 33 images are byte for byte
# what went in; the one difference in the JSON is that the samplers' wrap
# mode is now written out (10497, REPEAT) instead of left to the default.
#
# Deliberately NOT done here: `gltf-transform dedup`. It merges materials
# that are content-identical, and web/materials.js shades by material NAME -
# `glass_blind` and `int_wall_loggia` have twins that only differ in what
# the page does with them.
#
# Encode speed 3, not 0: the slowest setting saves 44 KB and costs the
# visitor 17% more decode. Run by blender/build.py after split_glb.py; safe
# to run twice. Needs node (npx fetches @gltf-transform/cli, pinned).
set -e
cd "$(dirname "$0")/../web"
GT=(npx --yes @gltf-transform/cli@4.5.1)
for f in scene-street.glb scene-flat.glb scene-hood.glb; do
  [[ -f $f ]] || { echo "weld_glb: no $f"; continue; }
  tmp=$(mktemp -t weld).glb
  $GT draco $f $tmp --quantize-position 14 --quantize-normal 10 \
      --quantize-texcoord 12 --quantize-color 8 \
      --encode-speed 3 --decode-speed 3 > /dev/null
  a=$(stat -f %z $f); b=$(stat -f %z $tmp)
  # a file that did not shrink was welded already: leave it exactly as it is
  if (( b < a )); then
    echo "weld_glb: $f $a -> $b bytes ($(gzip -6 -c $tmp | wc -c | tr -d ' ') gzipped)"
    mv $tmp $f
  else
    echo "weld_glb: $f already welded ($a bytes)"; rm -f $tmp
  fi
done
