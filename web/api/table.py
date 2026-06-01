"""/api/table — the table-builder endpoint.

GET params:
  dataset=contracts|assistance   rows=<dim>   metric=<metric>
  periodA=YYYY-MM-DD..YYYY-MM-DD  [periodB=...]   filter_<dim>=a|b  filter_<dim>_min/_max

Returns { meta, columns, data, reproduce:{sql, python} } — including the exact runnable
code against the PUBLIC dataset so the result is independently verifiable.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from dims import DIMENSIONS, METRICS, parse_filters
import query
from data_loader import get_conn, source_expr


def _period(params, name):
    raw = params.get(name, [""])[0]
    if ".." in raw:
        s, e = raw.split("..", 1)
        return (s, e)
    return None


def build_response(params):
    dataset = params.get("dataset", ["contracts"])[0]
    rows = params.get("rows", ["funding_subagency"])[0]
    metric = params.get("metric", ["obligations"])[0]
    pa, pb = _period(params, "periodA"), _period(params, "periodB")
    clauses, binds = parse_filters(params)

    req = dict(dataset=dataset, rows=rows, metric=metric, periodA=pa, periodB=pb,
               filter_clauses=clauses, filter_binds=binds)
    sql, qbinds = query.build_sql(req)

    con = get_conn()
    df = con.execute(sql.format(src=source_expr(dataset)), qbinds).df()
    con.close()

    two = pb is not None
    if two and len(df):
        df["delta"] = df["b"] - df["a"]
        df["pct"] = (df["delta"] / df["a"].replace(0, None)) * 100

    columns = [DIMENSIONS[rows]["label"], METRICS[metric]["label"] + (" — A" if two else "")]
    if two:
        columns += [METRICS[metric]["label"] + " — B", "Change", "% change"]
    data = []
    for _, r in df.iterrows():
        row = [r["row"], r["a"]]
        if two:
            row += [r["b"], r["delta"], round(r["pct"], 1) if r["pct"] == r["pct"] else None]
        data.append(row)

    return {
        "meta": {"dataset": dataset, "rows": rows, "metric": metric,
                 "periodA": pa, "periodB": pb, "count": len(data)},
        "columns": columns,
        "data": data,
        "reproduce": query.reproduce(req),
    }


class handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body, default=str).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()

    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            self._send(200, build_response(params))
        except Exception as e:
            self._send(400, {"error": str(e)})
