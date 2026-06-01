"""Generic table-builder query engine + reproducible-code emission.

build_sql() turns a validated request into a parameterized SQL template (with a {src}
placeholder for the parquet source). The site runs it against its own source (R2/HF);
reproduce() renders the SAME query against the PUBLIC HuggingFace dataset with values
inlined, so every result ships the exact SQL + a self-contained Python snippet a user can
run to verify it independently.

Supported now: one dataset, one row dimension, one metric, optional two-period (A/B)
comparison, allowlisted filters. (Column crosstab + more metrics are incremental adds.)
"""
import re

from dims import DATE_COL, DATASETS, DIMENSIONS, METRICS, OBL, UEI, HF_REPO, parse_filters

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def hf_source(dataset):
    return (f"read_parquet('hf://datasets/{HF_REPO}/{dataset}/**/*.parquet', "
            f"hive_partitioning=true, union_by_name=true)")


def _mask(period):
    """period = (start, end) -> a SQL boolean on action_date. Dates strictly validated."""
    if not period:
        return "TRUE"
    s, e = period
    if not (_DATE.match(s) and _DATE.match(e)):
        raise ValueError("bad date")
    return f"{DATE_COL} BETWEEN '{s}' AND '{e}'"


def build_sql(req):
    """req: {dataset, rows, metric, periodA?, periodB?, filter_clauses, filter_binds}.
    Returns (sql_template_with_{src}, binds)."""
    if req["dataset"] not in DATASETS:
        raise ValueError("bad dataset")
    if req["rows"] not in DIMENSIONS:
        raise ValueError("bad row dimension")
    if req["metric"] not in METRICS:
        raise ValueError("bad metric")
    rcol = DIMENSIONS[req["rows"]]["col"]
    where = req.get("filter_clauses", [])
    binds = list(req.get("filter_binds", []))
    pa, pb = req.get("periodA"), req.get("periodB")
    mask_a, mask_b = _mask(pa), _mask(pb) if pb else None

    # restrict the scan to the relevant period(s)
    if pa and pb:
        where = where + [f"({mask_a} OR {mask_b})"]
    elif pa:
        where = where + [mask_a]
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    if req["metric"] == "vendors_nonzero_net":
        a_net = f"sum(CASE WHEN {mask_a} THEN {OBL} END)"
        b_net = f"sum(CASE WHEN {mask_b} THEN {OBL} END)" if mask_b else None
        cols = ["count(*) FILTER (WHERE net_a IS NOT NULL AND net_a != 0) AS a"]
        if b_net:
            cols.append("count(*) FILTER (WHERE net_b IS NOT NULL AND net_b != 0) AS b")
        inner_cols = [f"{a_net} AS net_a"] + ([f"{b_net} AS net_b"] if b_net else [])
        sql = (f"SELECT row, {', '.join(cols)} FROM ("
               f"  SELECT {rcol} AS row, {UEI} AS uei, {', '.join(inner_cols)} "
               f"  FROM {{src}} {where_sql} {'AND' if where_sql else 'WHERE'} {UEI} IS NOT NULL "
               f"  GROUP BY 1, 2"
               f") GROUP BY 1 ORDER BY a DESC NULLS LAST")
    else:
        tmpl = METRICS[req["metric"]]["sql"]
        cols = [tmpl.format(p=mask_a) + " AS a"]
        if mask_b:
            cols.append(tmpl.format(p=mask_b) + " AS b")
        sql = (f"SELECT {rcol} AS row, {', '.join(cols)} "
               f"FROM {{src}} {where_sql} GROUP BY 1 ORDER BY a DESC NULLS LAST")
    return sql, binds


def _inline(sql, binds):
    """Replace ? placeholders with safely-quoted literals (for the copy-paste snippet)."""
    out = sql
    for b in binds:
        lit = (str(b) if isinstance(b, (int, float))
               else "'" + str(b).replace("'", "''") + "'")
        out = out.replace("?", lit, 1)
    return out


# Pinned package versions so the reproduction is deterministic (DuckDB ships Python,
# R and CLI from the same release; 1.5.2 is current on PyPI and CRAN).
DUCKDB_VERSION = "1.5.2"


def reproduce(req):
    """The exact query against the PUBLIC HF dataset, in SQL, Python, and R — version-pinned."""
    sql, binds = build_sql(req)
    sql_hf = _inline(sql.format(src=hf_source(req["dataset"])), binds)
    q = (sql_hf.replace(" FROM ", "\n  FROM ").replace(" WHERE ", "\n  WHERE ")
               .replace(" GROUP BY ", "\n  GROUP BY "))

    header = "Reproduce this exact result from the public USAspending dataset on HuggingFace."
    sql_script = (
        f"-- {header}\n-- DuckDB {DUCKDB_VERSION} — run in the DuckDB CLI or any DuckDB client.\n"
        f"INSTALL httpfs; LOAD httpfs;\n{q};\n"
    )
    python = (
        f"# {header}\n# pip install duckdb=={DUCKDB_VERSION}\n"
        "import duckdb\n"
        "con = duckdb.connect()\n"
        'con.execute("INSTALL httpfs; LOAD httpfs;")\n'
        f'con.sql(r"""\n{q}\n""").show()\n'
    )
    r = (
        f"# {header}\n"
        f'# install.packages("duckdb")  # version {DUCKDB_VERSION}\n'
        "library(duckdb)\n"
        "con <- dbConnect(duckdb())\n"
        'dbExecute(con, "INSTALL httpfs; LOAD httpfs;")\n'
        f'print(dbGetQuery(con, r"(\n{q}\n)"))\n'
    )
    return {"sql": sql_script, "python": python, "r": r}
