"""/api/filter_options?field=<dim>[&dataset=] — values to populate a filter dropdown.

Coded dimensions (award_type, extent_competed, set-aside, pricing) come back with their
codebook labels; code fields (funding_subagency_code) come back with the agency name; other
low-cardinality fields list their distinct values. High-cardinality fields (recipient, NAICS,
PSC, county) return {searchable:true} so the UI falls back to a text box.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
import dims
from data_loader import get_conn, source_expr

CAP = 400
CODED = {k for k, v in dims.DIMENSIONS.items() if v.get("coded")}
# code field -> (code column, label/name column)
CODE_FIELDS = {
    "funding_subagency_code": ("funding_sub_agency_code", "funding_sub_agency_name"),
    "awarding_subagency_code": ("awarding_sub_agency_code", "awarding_sub_agency_name"),
}


def _codebook_expr():
    return os.environ.get(
        "USP_CODEBOOK",
        f"read_parquet('hf://datasets/{dims.HF_REPO}/reference/codebook.parquet')")


def build_options(field, dataset="contracts"):
    con = get_conn()
    src = source_expr(dataset)

    if field in CODE_FIELDS:
        col, namecol = CODE_FIELDS[field]
        rows = con.execute(
            f"SELECT DISTINCT {col} AS v, any_value({namecol}) AS l FROM {src} "
            f"WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY 2 LIMIT {CAP+1}").fetchall()
        con.close()
        if len(rows) > CAP:
            return {"field": field, "searchable": True}
        return {"field": field, "options": [{"value": v, "label": f"{l} ({v})" if l else v} for v, l in rows]}

    if field not in dims.DIMENSIONS:
        con.close()
        return {"field": field, "searchable": True}
    col = dims.DIMENSIONS[field]["col"]

    # label map from the codebook for coded dimensions
    labels = {}
    if field in CODED:
        try:
            for code, lab in con.execute(
                    f"SELECT code, any_value(label) FROM {_codebook_expr()} "
                    f"WHERE column = ? GROUP BY 1", [col]).fetchall():
                labels[code] = lab
        except Exception:
            pass

    rows = con.execute(
        f"SELECT DISTINCT {col} AS v FROM {src} WHERE {col} IS NOT NULL "
        f"ORDER BY 1 LIMIT {CAP+1}").fetchall()
    con.close()
    if len(rows) > CAP:
        return {"field": field, "searchable": True}
    opts = [{"value": v, "label": (f"{labels[v]} ({v})" if v in labels else v)} for (v,) in rows]
    return {"field": field, "options": opts}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            p = parse_qs(urlparse(self.path).query)
            body = build_options(p.get("field", ["state"])[0], p.get("dataset", ["contracts"])[0])
            code = 200
        except Exception as e:
            body, code = {"error": str(e)}, 400
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())
