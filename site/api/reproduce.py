"""/api/reproduce — turn a Table Builder selection into runnable code WITHOUT executing it.

The builder is a query *composer*: the user picks dataset, group-bys, metrics, filters, and a
period, and we hand back the exact DuckDB/Python that would produce that table against the
public dataset (+ a one-click Colab). We never run the aggregation here — the full archive is
download-only — so this is instant regardless of how big the query would be.

Mirrors how table.build_response assembles its request, but calls query.reproduce_multi only.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from dims import resolve_col, parse_filters
import query
from data_loader import CACHE_CONTROL


def _period(params, name):
    raw = params.get(name, [""])[0]
    return tuple(raw.split("..", 1)) if ".." in raw else None


def reproduce_response(params):
    dataset = params.get("dataset", ["contracts"])[0]
    dims = [x for x in params.get("rows", ["funding_subagency"])[0].split(",") if x] or ["funding_subagency"]
    metrics = [x for x in params.get("metric", ["obligations"])[0].split(",") if x] or ["obligations"]
    clauses, binds = parse_filters(params)
    group_dims = [d for d in dims if resolve_col(d)] or ["funding_subagency"]
    top = params.get("top", [None])[0]
    req = dict(dataset=dataset, rows=group_dims, metrics=metrics,
               periodA=_period(params, "periodA"), periodB=_period(params, "periodB"),
               date_field=params.get("date_field", ["action_date"])[0],
               filter_clauses=clauses, filter_binds=binds,
               limit=int(top) if top and top.isdigit() else None)
    return query.reproduce_multi(req)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body, code = reproduce_response(parse_qs(urlparse(self.path).query)), 200
        except Exception as e:
            body, code = {"error": str(e)}, 400
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", CACHE_CONTROL if code == 200 else "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())
