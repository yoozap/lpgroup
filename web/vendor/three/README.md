# three.js, vendored

three@0.186.1, served from this project instead of from cdn.jsdelivr.net.
Twenty cross-origin requests - a DNS lookup, a TLS handshake and a round trip
each, before a single byte of the model could be asked for - were about a
second of every cold boot, and they were the first thing in the chain, so
nothing else could start until they were done.

Only the module graph this page imports is here, not all 16 MB of the
package: the two builds, the eleven addons `web/app.js` imports, everything
those import in turn, and the Draco decoder's wasm pair, which `GLTFLoader`
fetches at runtime rather than importing.

## Serve it compressed

It is 3.8 MB of unminified JavaScript - three ships no minified WebGPU build -
and about a tenth of that gzipped. `serve.py` gzips it; any real host does
too, but check, because uncompressed this is heavier than the CDN was.

## Replacing it

    curl -o three.tgz https://registry.npmjs.org/three/-/three-<version>.tgz
    tar xzf three.tgz

then copy `package/build/*.js`, the addons `app.js` imports plus their
transitive relative imports, and `package/examples/jsm/libs/draco/` (the
`.wasm` and its wrapper; the 700 KB `draco_decoder.js` fallback is not used).

## Going back to the CDN

Put this import map back in `index.html` and `lab.html`, and point
`setDecoderPath` in `app.js` at the same host:

    "three":        "https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.webgpu.js",
    "three/webgpu": "https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.webgpu.js",
    "three/tsl":    "https://cdn.jsdelivr.net/npm/three@0.186.1/build/three.tsl.js",
    "three/addons/":"https://cdn.jsdelivr.net/npm/three@0.186.1/examples/jsm/"
