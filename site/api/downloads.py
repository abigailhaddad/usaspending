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
from data_loader import CACHE_CONTROL

ROOT = Path(__file__).resolve().parents[2]
# Prefer a manifest bundled inside site/ (the Vercel deployment root only uploads files
# under site/); fall back to the repo-root copy for local dev.
SITE_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = next((p for p in (SITE_ROOT / "metadata" / "manifest.json",
                             ROOT / "metadata" / "manifest.json") if p.exists()),
                ROOT / "metadata" / "manifest.json")
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
            # Vercel: only /tmp is writable, so relocate DuckDB home/extension dir there
            # before INSTALL (mirrors data_loader.get_conn). Harmless locally.
            if os.path.isdir("/tmp"):
                con.execute("SET home_directory='/tmp'")
                con.execute("SET extension_directory='/tmp/duckdb_ext'")
            con.execute("INSTALL httpfs; LOAD httpfs;")
            _AGENCY_NAMES = {}
            # full CGAC crosswalk (covers the long tail); fall back to toptier list
            for ref, code_col in [("agency_codes", "cgac_code"), ("toptier_agencies", "toptier_code")]:
                try:
                    for c, nm in con.execute(
                        f"SELECT {code_col}, agency_name FROM read_parquet('{RESOLVE}reference/{ref}.parquet')"
                    ).fetchall():
                        if c and nm and c not in _AGENCY_NAMES:
                            _AGENCY_NAMES[c] = nm
                except Exception:
                    pass
            con.close()
        except Exception:
            _AGENCY_NAMES = {}
    return _AGENCY_NAMES


def build_index():
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    names = agency_names()
    year_total = {}                                     # (product, fy) -> All-file rows (authoritative)
    year_sum = defaultdict(int)                         # per-agency sum (fallback if no All file)
    by_agency = defaultdict(lambda: defaultdict(list))  # dataset -> code -> [{fy,rows,url}]
    for logical_id, e in manifest.items():
        product, fy, code = logical_id.split("/")
        rows = e.get("rows", 0) or 0
        if code == "All":               # the archive's complete per-year file (not an agency)
            year_total[(product, fy)] = rows
            continue
        year_sum[(product, fy)] += rows
        if rows > 0:                    # skip empty per-agency files (archive emits one even w/ no awards)
            by_agency[product][code].append(
                {"fiscal_year": fy, "rows": rows, "url": RESOLVE + e["parquet_key"]})

    # one clean file per (dataset, fiscal year) — the serving layer, direct download
    serve = [{"dataset": p, "fiscal_year": fy, "rows": year_total.get((p, fy), year_sum[(p, fy)]),
              "url": f"{RESOLVE}serve/{p}/{fy}.parquet"}
             for (p, fy) in sorted(set(year_total) | set(year_sum), reverse=True)]

    # per-agency files, named, newest year first; named agencies first, then unnamed codes
    agencies = {}
    for product, codes in by_agency.items():
        agencies[product] = sorted(
            [{"code": c, "name": names.get(c, c),
              "files": sorted(fs, key=lambda x: x["fiscal_year"], reverse=True)}
             for c, fs in codes.items()],
            key=lambda a: (a["name"] == a["code"], a["name"].lower()))

    reference = [{"name": n, "desc": d, "url": f"{RESOLVE}reference/{n}.parquet"} for n, d in REFERENCE]
    return {"hf_dataset": f"https://huggingface.co/datasets/{HF_REPO}",
            "serve": serve, "agencies": agencies, "reference": reference}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body, code = build_index(), 200
        except Exception as e:
            body, code = {"error": str(e)}, 400
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", CACHE_CONTROL if code == 200 else "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())
