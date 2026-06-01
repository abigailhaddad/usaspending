"""/api/detail — record-level rows behind the current filters/period (Vercel function).

Dev routes this via serve_local_api; in production Vercel serves each api/*.py separately,
so this thin handler exposes table.detail_response.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
import table


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body, code = table.detail_response(parse_qs(urlparse(self.path).query)), 200
        except Exception as e:
            body, code = {"error": str(e)}, 400
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body, default=str).encode())
