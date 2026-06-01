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


def build_index():
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    groups = defaultdict(lambda: {"files": 0, "rows": 0, "bytes": 0})
    for logical_id, e in manifest.items():
        product, fy, _ = logical_id.split("/")
        g = groups[(product, fy)]
        g["files"] += 1
        g["rows"] += e.get("rows", 0) or 0
        g["bytes"] += e.get("parquet_bytes", 0) or 0
    # newest fiscal year first, contracts before assistance
    spending = [{"dataset": p, "fiscal_year": fy, "files": v["files"],
                 "rows": v["rows"], "bytes": v["bytes"], "browse": f"{TREE}{p}/fiscal_year={fy}"}
                for (p, fy), v in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1]), reverse=True)]
    reference = [{"name": n, "desc": d, "url": f"{RESOLVE}reference/{n}.parquet"} for n, d in REFERENCE]
    return {"hf_dataset": f"https://huggingface.co/datasets/{HF_REPO}",
            "spending": spending, "reference": reference}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(build_index()).encode())
