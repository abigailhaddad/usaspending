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

from dims import DATE_COL, DATASETS, DIMENSIONS, METRICS, OBL, UEI, HF_REPO, parse_filters, resolve_col, resolve_date_col

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def hf_source(dataset):
    # The SERVING layer: one parquet per fiscal year (serve/{dataset}/{fy}.parquet).
    # ~20 files per product, so DuckDB lists a single dir — no recursive partition
    # listing, no HuggingFace 429. This is the exact source the site queries too, so
    # the reproduce code runs the identical query against identical data.
    return (f"read_parquet('hf://datasets/{HF_REPO}/serve/{dataset}/*.parquet', "
            f"union_by_name=true)")


def _mask(period, date_col=DATE_COL):
    """period = (start, end) -> a SQL boolean on the chosen date column. Strictly validated."""
    if not period:
        return "TRUE"
    s, e = period
    if not (_DATE.match(s) and _DATE.match(e)):
        raise ValueError("bad date")
    return f"TRY_CAST({date_col} AS DATE) BETWEEN '{s}' AND '{e}'"


def _group_cols(req):
    """Resolve the group-by dimension(s) to SQL column expressions. `rows` may be a single
    dim or a list — a real GROUP BY over all of them."""
    rows = req["rows"]
    rows = rows if isinstance(rows, (list, tuple)) else [rows]
    cols = [resolve_col(r) for r in rows]
    if not cols or any(c is None for c in cols):
        raise ValueError("bad group-by dimension")
    return cols


def build_sql(req):
    """One metric grouped by one or more columns. Group cols are selected as g0..gN.
    Returns (sql_template_with_{src}, binds)."""
    if req["dataset"] not in DATASETS:
        raise ValueError("bad dataset")
    if req["metric"] not in METRICS:
        raise ValueError("bad metric")
    gcols = _group_cols(req)
    gsel = ", ".join(f"{c} AS g{i}" for i, c in enumerate(gcols))   # SELECT … AS g0, g1…
    gby = ", ".join(gcols)                                          # GROUP BY <exprs>
    gids = ", ".join(f"g{i}" for i in range(len(gcols)))           # outer alias list
    where = req.get("filter_clauses", [])
    binds = list(req.get("filter_binds", []))
    pa, pb = req.get("periodA"), req.get("periodB")
    dcol = resolve_date_col(req.get("date_field"))
    mask_a, mask_b = _mask(pa, dcol), _mask(pb, dcol) if pb else None
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
        sql = (f"SELECT {gids}, {', '.join(cols)} FROM ("
               f"  SELECT {gsel}, {UEI} AS uei, {', '.join(inner_cols)} "
               f"  FROM {{src}} {where_sql} {'AND' if where_sql else 'WHERE'} {UEI} IS NOT NULL "
               f"  GROUP BY {gby}, {UEI}"
               f") GROUP BY {gids} ORDER BY a DESC NULLS LAST")
    else:
        tmpl = METRICS[req["metric"]]["sql"]
        cols = [tmpl.format(p=mask_a) + " AS a"]
        if mask_b:
            cols.append(tmpl.format(p=mask_b) + " AS b")
        sql = (f"SELECT {gsel}, {', '.join(cols)} "
               f"FROM {{src}} {where_sql} GROUP BY {gby} ORDER BY a DESC NULLS LAST")
    return sql, binds


def build_multi_sql(req):
    """One table grouped by the dimension(s) in `rows`, with one or more metrics.
    Returns (sql_template, binds, metrics, two). Output columns: g0..gN then per-metric a/b."""
    metrics = req.get("metrics") or [req.get("metric", "obligations")]
    two = bool(req.get("periodB"))
    ng = len(_group_cols(req))  # number of group-by columns
    subs, binds = [], []
    for i, m in enumerate(metrics):
        s, b = build_sql({**req, "metric": m})
        subs.append((f"t{i}", s))
        binds += b
    # coalesce each group column across the per-metric subqueries
    cols = [f"COALESCE({', '.join(a + f'.g{k}' for a, _ in subs)}) AS g{k}" for k in range(ng)]
    for (a, _), m in zip(subs, metrics):
        cols.append(f'{a}.a AS "{m}__a"')
        if two:
            cols.append(f'{a}.b AS "{m}__b"')
    sql = f"SELECT {', '.join(cols)} FROM ({subs[0][1]}) t0"
    for i in range(1, len(subs)):
        on = " AND ".join(f"t0.g{k} IS NOT DISTINCT FROM t{i}.g{k}" for k in range(ng))
        sql += f" FULL JOIN ({subs[i][1]}) t{i} ON {on}"
    sql += f' ORDER BY "{metrics[0]}__a" DESC NULLS LAST'
    if req.get("limit"):
        sql += f" LIMIT {int(req['limit'])}"
    return sql, binds, metrics, two


def build_detail_sql(req, limit=100000):
    """Record-level rows behind the current filters/period (the disaggregated data)."""
    from dims import DETAIL_COLUMNS
    cols = DETAIL_COLUMNS.get(req["dataset"], DETAIL_COLUMNS["contracts"])
    where = list(req.get("filter_clauses", []))
    binds = list(req.get("filter_binds", []))
    dcol = resolve_date_col(req.get("date_field"))
    masks = [_mask(p, dcol) for p in (req.get("periodA"), req.get("periodB")) if p]
    if masks:
        where.append("(" + " OR ".join(masks) + ")")
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sel = ", ".join(cols)
    return (f"SELECT {sel} FROM {{src}} {where_sql} "
            f"ORDER BY {OBL} DESC NULLS LAST LIMIT {limit}"), binds, cols


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


def _render_code(sql_hf):
    """One faithful artifact: the EXACT query the table ran, wrapped in a minimal Python
    runner so it both shows the query and executes it. Same SQL + same public serving
    layer as the site → it reproduces the table by construction and can't diverge."""
    q = (sql_hf.replace(" FROM ", "\n  FROM ").replace(" WHERE ", "\n  WHERE ")
               .replace(" GROUP BY ", "\n  GROUP BY ").replace(" FULL JOIN ", "\n  FULL JOIN "))
    header = "This is the exact query the table ran, against the public USAspending dataset."
    python = (
        f"# {header}\n# pip install duckdb=={DUCKDB_VERSION}\nimport duckdb\n"
        "con = duckdb.connect()\ncon.execute(\"INSTALL httpfs; LOAD httpfs;\")\n"
        f'con.sql(r"""\n{q}\n""").show()\n'
    )
    return {"python": python, "sql": q}


def reproduce(req):
    sql, binds = build_sql(req)
    return _render_code(_inline(sql.format(src=hf_source(req["dataset"])), binds))


def reproduce_multi(req):
    """Reproduce code for a multi-metric table (one combined query)."""
    sql, binds, _, _ = build_multi_sql(req)
    return _render_code(_inline(sql.format(src=hf_source(req["dataset"])), binds))


def reproduce_detail(req):
    """Reproduce code for the disaggregated record-level download."""
    sql, binds, _ = build_detail_sql(req)
    return _render_code(_inline(sql.format(src=hf_source(req["dataset"])), binds))
