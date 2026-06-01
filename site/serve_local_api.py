"""Local dev server: serves web/ statics and routes /api/table to the handler.

  USP_SOURCE_TMPL=... python3 web/serve_local.py [port]

(Vercel runs each api/*.py as a function; this just stitches them together for local dev.)
"""
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import json

WEB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(WEB, "api"))
import table          # noqa: E402
import filter_options  # noqa: E402
import colab          # noqa: E402
import downloads      # noqa: E402


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

    def _json(self, fn):
        try:
            payload = json.dumps(fn(), default=str).encode(); code = 200
        except Exception as e:
            payload = json.dumps({"error": str(e)}).encode(); code = 400
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlparse(self.path).path
        q = parse_qs(urlparse(self.path).query)
        if path == "/api/table":
            return self._json(lambda: table.build_response(q))
        if path == "/api/detail":
            return self._json(lambda: table.detail_response(q))
        if path == "/api/fields":
            return self._json(lambda: table.fields_response(q))
        if path == "/api/downloads":
            return self._json(downloads.build_index)
        if path == "/api/filter_options":
            return self._json(lambda: filter_options.build_options(
                q.get("field", ["state"])[0], q.get("dataset", ["contracts"])[0]))
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == "/api/colab":
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            return self._json(lambda: {"colab_url": colab.make_colab(body["sql"], body.get("title"))})
        self.send_error(404)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"serving http://localhost:{port}  (source: {os.environ.get('USP_SOURCE_TMPL','HF')[:60]})")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
