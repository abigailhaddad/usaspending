"""Build a codebook (value -> label) for coded columns, from the data dictionary.

The dictionary's "Domain Values" field is either an enumerated code map
("Y = Yes\\nN = No", "NP = NEGOTIATED PROPOSAL/QUOTE\\n...") or free-text prose
("See https://...", "According to the GSA FPDS ..."). We extract only the
enumerated maps: lines of `<code> = <label>` where the code is a short token
with no spaces. Prose lines don't match and are skipped.

Output: data/reference/codebook.parquet with one row per (column, code):
    column   the parquet column name (data dictionary "Award Element")
    code     the raw value as it appears in the data
    label    its human meaning
    applies_to  "Contracts" | "Assistance" | "both"

This lets a user decode e.g. extent_competed='A' without leaving the dataset,
and powers value labels in the BI layer.
"""
from __future__ import annotations

import re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "data" / "reference"

# <code> = <label> ; code is a short token, no internal spaces (rules out prose).
_LINE = re.compile(r"^\s*(?P<code>\S{1,15})\s*=\s*(?P<label>\S.*?)\s*$")


def parse_domain_values(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        m = _LINE.match(line)
        if m and "=" not in m.group("code"):
            out.append((m.group("code"), m.group("label")))
    return out


def _applies_to(award_file: str | None) -> str:
    s = award_file or ""
    c, a = "Contracts" in s, "Assistance" in s
    return "both" if c and a else "Contracts" if c else "Assistance" if a else ""


def build(dictionary_path: Path | None = None) -> list[dict]:
    rows = pq.read_table(dictionary_path or REF / "data_dictionary.parquet").to_pylist()
    out: list[dict] = []
    for r in rows:
        col = r.get("Award Element") or r.get("Element")
        if not col:
            continue
        for code, label in parse_domain_values(str(r.get("Domain Values") or "")):
            out.append({"column": col, "code": code, "label": label,
                        "applies_to": _applies_to(r.get("Award File"))})
    return out


def write() -> Path:
    rows = build()
    REF.mkdir(parents=True, exist_ok=True)
    out = REF / "codebook.parquet"
    pq.write_table(pa.Table.from_pylist(rows), out, compression="zstd")
    cols = len({r["column"] for r in rows})
    print(f"codebook: {len(rows)} value labels across {cols} coded columns -> {out.relative_to(ROOT)}")
    return out


if __name__ == "__main__":
    write()
