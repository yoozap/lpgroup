#!/usr/bin/env python3
"""Tiny static server for the render page (no-store so edits show up at once).

    python3 serve.py           ->  http://127.0.0.1:8777/
"""
import http.server, socketserver, os, sys, gzip, io
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8777
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web'))

# three.js is served from web/vendor now, not from a CDN, and it is 3.8 MB of
# unminified JavaScript. Every real host gzips that to about a tenth; a dev
# server that does not would say the page is far heavier than it ships.
ZIP = ('.js', '.css', '.html', '.json', '.svg', '.wasm')

class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, max-age=0')
        super().end_headers()

    def send_head(self):
        path = self.translate_path(self.path)
        if (os.path.isfile(path) and path.endswith(ZIP)
                and 'gzip' in self.headers.get('Accept-Encoding', '')):
            with open(path, 'rb') as f:
                body = gzip.compress(f.read(), 5)
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

with socketserver.TCPServer(('127.0.0.1', PORT), H) as httpd:
    print('serving web/ on http://127.0.0.1:%d/' % PORT)
    httpd.serve_forever()
