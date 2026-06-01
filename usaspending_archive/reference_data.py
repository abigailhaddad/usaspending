"""Snapshot USAspending reference/dimension tables to parquet (Tier 1 in FINDINGS).

These are small JSON endpoints on api.usaspending.gov (a different host than the
throttled archive bucket — no IP lockout here). They make the award/assistance
parquet joinable + self-describing:

  data_dictionary   the Rosetta crosswalk — every column's definition (powers the dataset card)
  toptier_agencies  agency code <-> name crosswalk
  def_codes         Disaster Emergency Fund Codes (COVID = L-U, IIJA = Z & 1)
  glossary          term definitions (for the about/methodology page)
  assistance_listing CFDA / program catalog

Output: data/reference/{name}.parquet . Nested values (lists/dicts) are JSON-encoded
to keep the tables flat and easy to query.

NAICS (industry) and PSC (product/service) full trees require recursive filter_tree
walks; deferred as best-effort (see TODO at bottom).
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

API = "https://api.usaspending.gov/api/v2/"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "reference"


def _get(path: str, retries: int = 4) -> dict | list:
    url = API + path
    for attempt in range(retries):
        try:
            return json.loads(urllib.request.urlopen(url, timeout=60).read())
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(3 * (attempt + 1))


def _flatten(rows: list[dict]) -> list[dict]:
    """JSON-encode any non-scalar values so the parquet schema stays flat."""
    out = []
    for r in rows:
        out.append({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                    for k, v in r.items()})
    return out


# --- per-table extractors: each returns list[dict] ---

def dd_columns(headers: list[dict]) -> list[str]:
    """Unique column names for the data dictionary.

    The dictionary has two sections, so several display names repeat ('Element',
    'Award File', 'Award Element', 'Subaward Element' each appear twice). We keep
    all of them by appending the header's raw letter to the second occurrence
    (e.g. 'Element (N)').
    """
    seen: dict[str, int] = {}
    cols: list[str] = []
    for h in headers:
        disp = h["display"]
        cols.append(f"{disp} ({h['raw'].split(':', 1)[0]})" if disp in seen else disp)
        seen[disp] = seen.get(disp, 0) + 1
    return cols


def parse_data_dictionary(doc: dict) -> list[dict]:
    """Turn the data_dictionary `document` into list[dict].

    Every row carries a constant trailing null beyond the 17 headers; aligning
    row values to the column names drops it.
    """
    cols = dd_columns(doc["headers"])
    return [dict(zip(cols, row[:len(cols)])) for row in doc["rows"]]


def _data_dictionary() -> list[dict]:
    return parse_data_dictionary(_get("references/data_dictionary/")["document"])


def _glossary() -> list[dict]:
    return _get("references/glossary/")["results"]


def _agency_codes() -> list[dict]:
    """CGAC AGENCY CODE -> AGENCY NAME from the archive's agency_codes.csv — the FULL
    crosswalk for the archive's per-agency partition codes (covers the long tail that
    references/toptier_agencies misses)."""
    import csv
    import io
    text = urllib.request.urlopen(
        "https://files.usaspending.gov/reference_data/agency_codes.csv", timeout=60
    ).read().decode("utf-8-sig")
    out, seen = [], set()
    for row in csv.DictReader(io.StringIO(text)):
        c = (row.get("CGAC AGENCY CODE") or "").strip()
        if c and c not in seen:
            seen.add(c)
            out.append({"cgac_code": c, "agency_name": (row.get("AGENCY NAME") or "").strip()})
    return out


SPECS = {
    "data_dictionary": _data_dictionary,
    "toptier_agencies": lambda: _get("references/toptier_agencies/")["results"],
    "agency_codes": _agency_codes,
    "def_codes": lambda: _get("references/def_codes/")["codes"],
    "glossary": _glossary,
    "assistance_listing": lambda: _get("references/assistance_listing/"),
}


def write_table(name: str, rows: list[dict]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(_flatten(rows))
    out = OUT / f"{name}.parquet"
    pq.write_table(table, out, compression="zstd")
    return out


def snapshot_all() -> None:
    import os
    for name, fn in SPECS.items():
        try:
            rows = fn()
            out = write_table(name, rows)
            print(f"{name:20s} {len(rows):>6} rows -> {out.relative_to(ROOT)} ({out.stat().st_size/1e3:.0f} KB)")
        except Exception as exc:
            print(f"{name:20s} FAILED: {exc}")
    if os.environ.get("HF_TOKEN"):  # publish to the HF dataset's reference/ folder
        from huggingface_hub import HfApi
        api = HfApi(token=os.environ["HF_TOKEN"])
        for p in sorted(OUT.glob("*.parquet")):
            api.upload_file(path_or_fileobj=str(p), path_in_repo=f"reference/{p.name}",
                            repo_id="abigailhaddad/usaspending-bulk-awards", repo_type="dataset")
            print(f"uploaded reference/{p.name}")


if __name__ == "__main__":
    snapshot_all()

# TODO: NAICS + PSC full code->description trees (recursive references/filter_tree/...).
