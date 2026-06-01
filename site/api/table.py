"""/api/table and /api/detail — the table-builder endpoints.

/api/table  : one or more breakdowns at once, each with one or more metrics, optional
              two-period (A/B) comparison. Returns { tables:[...], meta } where each table
              carries its own reproduce code.
/api/detail : the disaggregated record-level rows behind the current filters/period
              (the download), with reproduce code.

Params: dataset, rows=dim1,dim2 (comma), metric=m1,m2 (comma),
        periodA=YYYY-MM-DD..YYYY-MM-DD, periodB=..., filter_<dim>=a|b, filter_<dim>_min/_max
"""
import json
import math
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


def _clean(v):
    """JSON-safe: NaN/NaT -> None, numpy scalars -> native Python (JSON has no NaN)."""
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v

sys.path.insert(0, os.path.dirname(__file__))
from dims import DIMENSIONS, METRICS, parse_filters, resolve_col
import query
from data_loader import get_conn, source_expr


def _period(params, name):
    raw = params.get(name, [""])[0]
    return tuple(raw.split("..", 1)) if ".." in raw else None


def _csv(params, name, default):
    return [x for x in params.get(name, [default])[0].split(",") if x] or [default]


def build_response(params):
    dataset = params.get("dataset", ["contracts"])[0]
    dims = _csv(params, "rows", "funding_subagency")
    metrics = _csv(params, "metric", "obligations")
    pa, pb = _period(params, "periodA"), _period(params, "periodB")
    clauses, binds = parse_filters(params)
    top = params.get("top", [None])[0]
    base = dict(dataset=dataset, metrics=metrics, periodA=pa, periodB=pb,
                filter_clauses=clauses, filter_binds=binds,
                limit=int(top) if top and top.isdigit() else None)

    con = get_conn()
    src = source_expr(dataset)
    two = pb is not None
    tables = []
    for dim in dims:
        if not resolve_col(dim):  # curated dim, alias, or any valid column
            continue
        dim_label = DIMENSIONS[dim]["label"] if dim in DIMENSIONS else dim.replace("_", " ")
        req = dict(base, rows=dim)
        sql, qbinds, mets, _ = query.build_multi_sql(req)
        df = con.execute(sql.format(src=src), qbinds).df()

        columns = [dim_label]
        for m in mets:
            lab = METRICS[m]["label"]
            columns += [f"{lab} — A", f"{lab} — B", f"{lab} — Δ", f"{lab} — Δ%"] if two else [lab]
        data = []
        for _, r in df.iterrows():
            row = [_clean(r["row"])]
            for m in mets:
                a = _clean(r.get(f"{m}__a"))
                if two:
                    b = _clean(r.get(f"{m}__b"))
                    d = (b - a) if (a is not None and b is not None) else None
                    pct = round(d / a * 100, 1) if (d is not None and a) else None
                    row += [a, b, d, pct]
                else:
                    row += [a]
            data.append(row)
        tables.append({"dimension": dim, "label": dim_label,
                       "columns": columns, "data": data, "reproduce": query.reproduce_multi(req)})
    con.close()
    return {"meta": {"dataset": dataset, "dims": dims, "metrics": metrics,
                     "periodA": pa, "periodB": pb, "tables": len(tables)},
            "tables": tables}


def fields_response(params):
    """Every column in the dataset, for the 'filter/break down by anything' picker."""
    dataset = params.get("dataset", ["contracts"])[0]
    con = get_conn()
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {source_expr(dataset)}").fetchall()]
    con.close()
    # hide the hive partition virtuals; everything else is filterable/groupable
    cols = [c for c in cols if c not in ("fiscal_year", "agency")]
    return {"fields": [{"value": c, "label": c.replace("_", " ")} for c in cols]}


def detail_response(params, limit=100000):
    dataset = params.get("dataset", ["contracts"])[0]
    pa, pb = _period(params, "periodA"), _period(params, "periodB")
    clauses, binds = parse_filters(params)
    req = dict(dataset=dataset, periodA=pa, periodB=pb,
               filter_clauses=clauses, filter_binds=binds)
    raw = params.get("limit", [""])[0]  # preview rows (table) vs full (download)
    if raw.isdigit():
        limit = min(int(raw), 100000)
    sql, qbinds, cols = query.build_detail_sql(req, limit)
    con = get_conn()
    rows = con.execute(sql.format(src=source_expr(dataset)), qbinds).fetchall()
    con.close()
    rows = [[_clean(v) for v in r] for r in rows]
    return {"columns": cols, "data": rows, "count": len(rows),
            "truncated": len(rows) >= limit, "reproduce": query.reproduce_detail(req)}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            params = parse_qs(urlparse(self.path).query)
            body = build_response(params)
            code = 200
        except Exception as e:
            body, code = {"error": str(e)}, 400
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body, default=str).encode())
