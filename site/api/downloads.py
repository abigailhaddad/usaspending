"""/api/downloads — a download index built from the publish manifest.

Mirrors data.opm.gov's Data Downloads: the bulk files grouped by dataset x fiscal year
(newest first) with row counts + sizes, plus the reference tables and data dictionary —
all as direct HuggingFace download links. The manifest (metadata/manifest.json) is the
source of truth for what's published.
"""
import json
import os
import sys
from collections import defaultdict
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from dims import HF_REPO

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "metadata" / "manifest.json"
RESOLVE = f"https://huggingface.co/datasets/{HF_REPO}/resolve/main/"
TREE = f"https://huggingface.co/datasets/{HF_REPO}/tree/main/"

REFERENCE = [
    ("data_dictionary", "Data dictionary — every column defined"),
    ("codebook", "Codebook — value→label for coded columns"),
    ("toptier_agencies", "Agency code ↔ name crosswalk"),
    ("def_codes", "Disaster Emergency Fund Codes (COVID / IIJA)"),
    ("assistance_listing", "CFDA / assistance program catalog"),
    ("glossary", "Glossary of terms"),
]


_AGENCY_NAMES = None


def agency_names():
    """toptier agency code -> name, from our published reference table (so we show names
    not '003'). Read once from the public reference parquet on HuggingFace."""
    global _AGENCY_NAMES
    if _AGENCY_NAMES is None:
        try:
            import duckdb
            con = duckdb.connect()
            con.execute("INSTALL httpfs; LOAD httpfs;")
            rows = con.execute(
                f"SELECT toptier_code, agency_name FROM read_parquet('{RESOLVE}reference/toptier_agencies.parquet')"
            ).fetchall()
            con.close()
            _AGENCY_NAMES = {c: nm for c, nm in rows if c}
        except Exception:
            _AGENCY_NAMES = {}
    return _AGENCY_NAMES


def build_index():
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    names = agency_names()
    years = defaultdict(lambda: {"rows": 0})
    by_agency = defaultdict(lambda: defaultdict(list))  # dataset -> code -> [{fy,rows,url}]
    for logical_id, e in manifest.items():
        product, fy, code = logical_id.split("/")
        rows = e.get("rows", 0) or 0
        years[(product, fy)]["rows"] += rows
        if rows > 0:  # skip empty per-agency files (archive emits one per agency-year even w/ no awards)
            by_agency[product][code].append(
                {"fiscal_year": fy, "rows": rows, "url": RESOLVE + e["parquet_key"]})

    # one clean file per (dataset, fiscal year) — the serving layer, direct download
    serve = [{"dataset": p, "fiscal_year": fy, "rows": v["rows"],
              "url": f"{RESOLVE}serve/{p}/{fy}.parquet"}
             for (p, fy), v in sorted(years.items(), key=lambda kv: (kv[0][0], kv[0][1]), reverse=True)]

    # per-agency files, grouped + named, newest year first
    agencies = {}
    for product, codes in by_agency.items():
        agencies[product] = sorted(
            [{"code": c, "name": names.get(c, c),
              "files": sorted(fs, key=lambda x: x["fiscal_year"], reverse=True)}
             for c, fs in codes.items()],
            key=lambda a: a["name"])

    reference = [{"name": n, "desc": d, "url": f"{RESOLVE}reference/{n}.parquet"} for n, d in REFERENCE]
    return {"hf_dataset": f"https://huggingface.co/datasets/{HF_REPO}",
            "serve": serve, "agencies": agencies, "reference": reference}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(build_index()).encode())
