#!/usr/bin/env python3
"""Tiny static server for the render page (no-store so edits show up at once).

    python3 serve.py           ->  http://127.0.0.1:8777/

Two things here are not cosmetic, because every measurement in `tools/` is
taken through this server:

* **It is threaded.** `TCPServer` serves one request at a time, and the page's
  very first act is to put the 12 MB `scene.glb` on the wire (see the inline
  script in `index.html`). Single-threaded, that download blocks three.js,
  app.js, the stylesheet, the fonts and all 30 textures BEHIND it - the exact
  opposite of what fetching the model early is for, and it made the boot
  look like a serial chain that no real host would impose.
* **It compresses.** three.js ships no minified WebGPU build, and the glb's
  glTF chunk is 1.2 MB of JSON. Gzip takes the vendored library to about a
  third and the model 12.2 -> 9.3 MB. A host that does not do this would
  make the page far heavier than it ships, so neither should this.
"""
import http.server, socketserver, os, sys, gzip, io, threading
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web'))

# `.glb` is here for its JSON chunk and its uncompressed accessors: the Draco
# buffers and the embedded WebP do not shrink, but the whole file still goes
# 12.2 -> 9.3 MB. `.woff2` is NOT - it is Brotli already.
ZIP = ('.js', '.css', '.html', '.json', '.svg', '.wasm', '.glb')
# Gzipping 12 MB on every request is a tenth of a second of CPU that a real
# host spends once, so the dev server remembers what it compressed. Keyed on
# the file's size and mtime, so an edit is still picked up at once - and
# bounded, because threads now ask for several files at the same time.
_cache, _lock = {}, threading.Lock()


class H(http.server.SimpleHTTPRequestHandler):
    # keep-alive, so the browser is not re-opening a socket per texture
    protocol_version = 'HTTP/1.1'

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, max-age=0')
        super().end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        if (os.path.isfile(path) and path.endswith(ZIP)
                and 'gzip' in self.headers.get('Accept-Encoding', '')):
            st = os.stat(path)
            key = (path, st.st_size, st.st_mtime_ns)
            with _lock:
                body = _cache.get(key)
            if body is None:
                with open(path, 'rb') as f:
                    body = gzip.compress(f.read(), 5)
                with _lock:
                    if len(_cache) > 64:
                        _cache.clear()
                    _cache[key] = body
            ctype = self.guess_type(path)
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Encoding', 'gzip')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            return io.BytesIO(body)
        return super().send_head()

    def log_message(self, *a):
        pass


class S(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


with S(('127.0.0.1', PORT), H) as httpd:
    print('serving web/ on http://127.0.0.1:%d/' % PORT)
    httpd.serve_forever()
