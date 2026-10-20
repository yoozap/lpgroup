#!/bin/zsh
# Build web/vendor/three-min from web/vendor/three.
#
#     zsh tools/min_three.sh
#
# three ships no minified WebGPU build, so the vendored copy was 3.74 MB of
# source: 818 KB gzipped on the wire and - the part that actually hurt - 3.74
# MB for the main thread to tokenise before a line of the page could run. In
# the user's own browser that parse was measured at 618-754 ms.
#
# Each module is minified ON ITS OWN rather than bundled. esbuild would
# happily roll the whole graph into one file, but then `app.js` could no
# longer `import 'three/webgpu'`, `'three/tsl'` and `'three/addons/...'`
# through the import map, and the page would need a build step of its own
# for every edit. File by file, every import specifier survives, the
# directory layout survives, and the import map in index.html / lab.html is
# the only thing that points anywhere new.
#
# The Draco pair is copied through untouched: `draco_wasm_wrapper.js` is
# emscripten output that is already compact (58.8 -> 57.8 KB, a single
# kilobyte for the one file in here most likely to resent being rewritten),
# and `app.js` points `setDecoderPath` at the SOURCE tree for exactly that
# reason. The wasm is binary and is copied, not minified.
#
# Re-run this after replacing web/vendor/three with a new three version, and
# re-check the render afterwards: tools/shot.cjs + tools/shot2.cjs against
# the build before, diffed with tools/imgdiff.py. Minification is supposed
# to be semantics-preserving; "supposed to be" is not a measurement.
set -e
cd "$(dirname "$0")/../web/vendor"
SRC=three
OUT=three-min
[ -d $SRC ] || { echo "no $SRC here"; exit 1; }
rm -rf $OUT
mkdir -p $OUT

JS=()
while IFS= read -r f; do JS+=("$f"); done < <(cd $SRC && find . -name '*.js' -type f)
echo "minifying ${#JS[@]} modules"
( cd $SRC && npx --yes esbuild "${JS[@]}" --minify --format=esm --target=es2022 \
    --outdir=../$OUT --outbase=. --log-level=error )
# the Draco wasm and anything else that is not JavaScript rides along as is
rsync -a --exclude '*.js' --exclude 'README.md' $SRC/ $OUT/
# ...and the wrapper, which is left alone on purpose (see above)
cp $SRC/examples/jsm/libs/draco/draco_wasm_wrapper.js \
   $OUT/examples/jsm/libs/draco/draco_wasm_wrapper.js

a=$(find $SRC -name '*.js' -exec cat {} + | wc -c)
b=$(find $OUT -name '*.js' -exec cat {} + | wc -c)
printf 'JavaScript %d -> %d bytes (%d%%)\n' $a $b $(( 100 * b / a ))
