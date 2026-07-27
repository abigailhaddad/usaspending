"""Precompute the curated dashboard aggregations from the serve layer.

The site is a curated explorer (modeled on data.opm.gov): a limited set of breakdown
dimensions, fiscal years, and two metrics — NOT open-ended querying over 2 billion rows.
So we precompute every view the dashboard can show into a small JSON the site serves
statically (site/public/precomputed/{dataset}.json). The dashboard then reads KB, never
scanning the full archive at request time. Arbitrary analysis is handed off to Colab.

Efficiency: one grouped scan per (dataset, dimension) over (fiscal_year, dimension); the
per-year breakdowns AND the all-years rollup are derived from that single pass in Python.
~17 scans total. The scans are slow (full-history column reads) but this runs offline on a
CI runner, not at request time.

Source resolution mirrors site/api/data_loader.py: R2 (CF_R2_*) else HF (HF_TOKEN).
Run from the repo root:  python usaspending_archive/precompute.py
"""
import json
import os
import time
from pathlib import Path

import duckdb

OBL = "TRY_CAST(federal_action_obligation AS DOUBLE)"
TOPN = 25  # high-cardinality dims keep their top N; categorical dims keep all values
HF_REPO = "abigailhaddad/usaspending-bulk-awards"

# Recipient county FIPS, cleaned to real county codes. A bare length=5 check is NOT enough:
# the assistance feed carries ~3% of county dollars under corrupt codes that are 5 chars but
# not real counties — float-formatted values ("423.0"), state-level placeholders ending 000
# (e.g. "48000", often with a mismatched county name), and the "unknown" sentinel 999. We
# require 5 digits AND a nonzero/non-999 county portion. Stored as the raw FIPS (the choropleth
# keys on it); a FIPS -> "County, ST" crosswalk (county_names) ships alongside for display.
# (Contracts is already clean; this is a no-op there. Same column name in both datasets.)
COUNTY_FIPS = ("CASE WHEN regexp_matches(prime_award_transaction_recipient_county_fips_code, '^[0-9]{5}$') "
               "AND substr(prime_award_transaction_recipient_county_fips_code, 3, 3) NOT IN ('000', '999') "
               "THEN prime_award_transaction_recipient_county_fips_code END")

# dims served from their OWN {dataset}.{key}.json, lazily fetched by the UI only when that
# group is selected — kept out of the main file so first paint stays small. County has
# ~3-5k values × 20 years; inlining it would add several MB to every page load. It ships as
# a separate file (same lazy pattern as the per-agency files) and carries full per-year
# periods, so the county view supports the same fiscal-year range as the rest of the charts.
LAZY_DIMS = {"county"}

# curated dimensions per dataset: key -> (label, sql column, categorical?)
# categorical dims are small and kept whole; the rest are truncated to the top N by $.
DIMS = {
    "contracts": {
        "awarding_agency":    ("Awarding agency",       "awarding_agency_name",        False),
        "awarding_subagency": ("Awarding sub-agency",    "awarding_sub_agency_name",    False),
        "recipient":          ("Recipient",              "recipient_name",              False),
        "recipient_parent":   ("Recipient parent",       "recipient_parent_name",       False),
        "state":              ("Recipient state",        "recipient_state_code",        True),
        "county":             ("Recipient county",       COUNTY_FIPS,                   True),
        "zip":                ("Recipient ZIP",          "NULLIF(substr(recipient_zip_4_code, 1, 5), '')", False),
        "naics":              ("Industry (NAICS)",       "naics_description",           False),
        "psc":                ("Product/service (PSC)",  "product_or_service_code_description", False),
        "competition":        ("Competition",            "extent_competed",             True),
        "set_aside":          ("Set-aside",              "type_of_set_aside",           True),
        "business_size":      ("Business size",          "contracting_officers_determination_of_business_size", True),
    },
    "assistance": {
        "awarding_agency":    ("Awarding agency",        "awarding_agency_name",        False),
        "awarding_subagency": ("Awarding sub-agency",    "awarding_sub_agency_name",    False),
        "recipient":          ("Recipient",              "recipient_name",              False),
        "recipient_parent":   ("Recipient parent",       "recipient_parent_name",       False),
        "state":              ("Recipient state",        "recipient_state_code",        True),
        "county":             ("Recipient county",       COUNTY_FIPS,                   True),
        "zip":                ("Recipient ZIP",          "NULLIF(substr(recipient_zip_code, 1, 5), '')", False),
        "assistance_type":    ("Assistance type",        "assistance_type_code",        True),
        "cfda":               ("CFDA program",           "cfda_number",                 False),
    },
}


def source(dataset):
    bucket = os.environ.get("CF_R2_BUCKET")
    if bucket:
        prefix = os.environ.get("CF_R2_PREFIX", "")
        return f"read_parquet('r2://{bucket}/{prefix}serve/{dataset}/*.parquet', union_by_name=true)"
    return f"read_parquet('hf://datasets/{HF_REPO}/serve/{dataset}/*.parquet', union_by_name=true)"


def connect():
    con = duckdb.connect()
    if os.path.isdir("/tmp"):
        con.execute("SET home_directory='/tmp'")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    # Resilience: precompute reads ~20 years of serve files over R2/HF, so a single
    # transient timeout shouldn't kill the whole run. Retry with backoff + a generous
    # per-request ceiling instead of failing fast.
    con.execute("SET http_timeout=300000")        # ms
    con.execute("SET http_retries=5")
    con.execute("SET http_retry_wait_ms=500")
    con.execute("SET http_retry_backoff=2")
    if os.environ.get("CF_R2_ACCOUNT_ID"):
        con.execute(f"""CREATE SECRET r2 (TYPE r2, KEY_ID '{os.environ['CF_R2_ACCESS_KEY_ID']}',
            SECRET '{os.environ['CF_R2_SECRET_ACCESS_KEY']}', ACCOUNT_ID '{os.environ['CF_R2_ACCOUNT_ID']}')""")
    elif os.environ.get("HF_TOKEN"):
        con.execute(f"CREATE SECRET hf (TYPE huggingface, TOKEN '{os.environ['HF_TOKEN']}')")
    return con


def with_retry(label, fn, attempts=3):
    """Run one scan step on a fresh connection, retrying it whole on a transient R2/HF error.

    connect()'s http_retries do fire on a 502 — but with wait 500ms and backoff 2 all six
    tries land inside ~15 seconds, which isn't enough for the R2 blips we actually see (a
    502 mid-scan killed a rebuild that had already run 4 minutes). A half-finished scan
    can't be resumed, so back off in minutes and redo the step. Every step here is
    idempotent: same immutable serve files in, same output files overwritten.
    """
    for attempt in range(1, attempts + 1):
        con = connect()
        try:
            return fn(con)
        except duckdb.IOException as e:      # HTTPException subclasses this
            if attempt == attempts:
                raise
            wait = 30 * 3 ** (attempt - 1)   # 30s, 90s
            print(f"  {label} failed ({str(e).splitlines()[0]}); "
                  f"retry {attempt}/{attempts - 1} in {wait}s", flush=True)
            time.sleep(wait)
        finally:
            con.close()


def build_timeseries(dataset, con):
    """(fiscal_year × agency × subagency) → metrics. Small enough to ship whole; the
    'spending over time' tool filters it by agency/subagency + year range in the browser."""
    src = source(dataset)
    rows = con.execute(
        f"SELECT action_date_fiscal_year fy, awarding_agency_name ag, awarding_sub_agency_name sub, "
        f"sum({OBL}) obl, count(*) txn FROM {src} "
        f"WHERE action_date_fiscal_year IS NOT NULL GROUP BY 1, 2, 3").fetchall()
    return [{"fy": fy, "agency": ag or "(unknown)", "sub": sub or "(unknown)",
             "obl": obl or 0, "txn": txn} for fy, ag, sub, obl, txn in rows]


def build(dataset, con):
    src = source(dataset)
    out = {"trend": [], "kpis": {}, "dims": {}, "years": [], "timeseries": []}
    lazy = {}  # dims routed to their own file (LAZY_DIMS) instead of the main payload

    # one scan -> the year trend + per-year and all-years KPI totals
    rows = con.execute(
        f"SELECT action_date_fiscal_year fy, sum({OBL}) obl, count(*) txn "
        f"FROM {src} GROUP BY 1 ORDER BY 1").fetchall()
    out["years"] = sorted(r[0] for r in rows if r[0])
    for fy, obl, txn in rows:
        if fy:
            out["trend"].append({"fy": fy, "obl": obl or 0, "txn": txn})
            out["kpis"][fy] = {"obl": obl or 0, "txn": txn}
    out["kpis"]["all"] = {"obl": sum((r[1] or 0) for r in rows), "txn": sum(r[2] for r in rows)}

    # one scan per dimension, grouped by (fiscal_year, dim); derive every period in Python
    for key, (label, col, categorical) in DIMS[dataset].items():
        grouped = con.execute(
            f"SELECT action_date_fiscal_year fy, {col} k, sum({OBL}) obl, count(*) txn "
            f"FROM {src} WHERE {col} IS NOT NULL GROUP BY 1, 2").fetchall()
        by_period, all_period = {}, {}
        for fy, k, obl, txn in grouped:
            if not fy:
                continue
            by_period.setdefault(fy, {}).setdefault(k, [0.0, 0])
            by_period[fy][k][0] += obl or 0; by_period[fy][k][1] += txn
            all_period.setdefault(k, [0.0, 0])
            all_period[k][0] += obl or 0; all_period[k][1] += txn

        def rank(d):
            items = sorted(d.items(), key=lambda kv: -kv[1][0])
            if not categorical:
                items = items[:TOPN]
            return [{"label": k, "obl": v[0], "txn": v[1]} for k, v in items]

        periods = {"all": rank(all_period)}
        for fy, d in by_period.items():
            periods[fy] = rank(d)
        entry = {"label": label, "categorical": categorical, "periods": periods}
        if key in LAZY_DIMS:
            lazy[key] = entry          # -> its own {dataset}.{key}.json, not the main file
        else:
            out["dims"][key] = entry

    out["timeseries"] = build_timeseries(dataset, con)
    if "county" in lazy:
        lazy["county"]["county_names"] = build_county_names(dataset, con)
    out["lazy_dims"] = sorted(lazy)    # marker so the UI knows which dims to lazy-fetch
    out["_lazy"] = lazy                # popped by the caller and written to separate files
    return out


def build_county_names(dataset, con):
    """FIPS -> "County, ST" display crosswalk for the county choropleth/labels. One scan;
    the dims store raw 5-digit FIPS (what the topojson keys on), this maps them to names."""
    src = source(dataset)
    rows = con.execute(
        f"SELECT {COUNTY_FIPS} f, any_value(recipient_county_name) n, any_value(recipient_state_code) s "
        f"FROM {src} WHERE {COUNTY_FIPS} IS NOT NULL GROUP BY 1").fetchall()
    out = {}
    for f, n, s in rows:
        if not f:
            continue
        name = (n or "").strip().title()
        out[f] = f"{name}, {s}" if name and s else (name or f)
    print(f"  county crosswalk: {len(out)} FIPS", flush=True)
    return out


# Table Builder filter dropdowns are cardinality-gated: a field is filterable only if it's
# enumerable (≤ FILTER_THRESHOLD distinct values) — then we precompute its full value list
# (ordered by $, with labels). Fields above the threshold (recipient name/parent/UEI, etc.)
# are simply not offered as filters in the UI; filtering by them is a Colab job. Generous
# threshold so medium fields (NAICS ~1.3k, county ~3.2k, sub-agency ~1.5k) stay dropdowns.
FILTER_THRESHOLD = 10000
FILTER_HARD_SKIP = {"recipient", "recipient_parent"}  # known millions-cardinality; don't even scan


def build_filters(dataset, con):
    """{field: {options:[{value,label}]}} — only the enumerable (filterable) fields."""
    import dims as sdims
    from filter_options import CODE_FIELDS
    src = source(dataset)
    candidates = list(sdims.DIMENSIONS.keys()) + list(CODE_FIELDS.keys()) + ["naics_code", "psc_code"]
    out = {}
    for f in candidates:
        if f in FILTER_HARD_SKIP or f in out:
            continue
        label_col = None
        if f in CODE_FIELDS:
            col, label_col = CODE_FIELDS[f]
        elif f in sdims.DIMENSIONS:
            col = sdims.DIMENSIONS[f]["col"]
        elif f == "naics_code":
            col = "naics_code"
        elif f == "psc_code":
            col = "product_or_service_code"
        else:
            continue
        try:
            sel = f"{col} v, any_value({label_col}) l, sum({OBL}) s" if label_col else f"{col} v, sum({OBL}) s"
            rows = con.execute(
                f"SELECT {sel} FROM {src} WHERE {col} IS NOT NULL GROUP BY {col} "
                f"ORDER BY s DESC LIMIT {FILTER_THRESHOLD + 1}").fetchall()
            if len(rows) > FILTER_THRESHOLD:
                print(f"  filter {f}: >{FILTER_THRESHOLD} distinct -> not filterable", flush=True)
                continue
            if label_col:
                opts = [{"value": v, "label": f"{l} ({v})" if l else v} for v, l, _ in rows]
            else:
                opts = [{"value": v, "label": v} for v, _ in rows]
            out[f] = {"options": opts}
            print(f"  filter {f}: {len(opts)} options", flush=True)
        except Exception as e:
            print(f"  filter {f}: skip ({str(e)[:60]})", flush=True)
    return out


import re

# dims that get a per-agency breakdown (skip the agency dims themselves — trivial within one agency)
AGENCY_BREAKDOWN_DIMS = ("recipient", "recipient_parent", "state", "county", "zip", "naics", "psc",
                         "competition", "set_aside", "assistance_type", "cfda", "business_size")


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "unknown"


def build_agency_files(dataset, con, timeseries, dest):
    """Per-agency files (same schema as the main file) so the page can re-scope to one agency.
    Bounded via window-function top-15 per (agency, period): one scan per dim covers all
    agencies at once. KPIs + timeseries come from the (fy x agency x sub) cube (no extra scan)."""
    src = source(dataset)
    dims = {k: v for k, v in DIMS[dataset].items() if k in AGENCY_BREAKDOWN_DIMS}
    per = {}  # agency -> {dim -> {label,categorical,periods}}

    def slot(agency, key, label, categorical):
        d = per.setdefault(agency, {}).setdefault(key, {"label": label, "categorical": categorical, "periods": {}})
        return d["periods"]

    for key, (label, col, categorical) in dims.items():
        # top-15 per (agency, fiscal year)
        sql_fy = (
            f"SELECT agency, fy, val, obl, txn FROM ("
            f"  SELECT awarding_agency_name agency, action_date_fiscal_year fy, {col} val, "
            f"         sum({OBL}) obl, count(*) txn, "
            f"         row_number() OVER (PARTITION BY awarding_agency_name, action_date_fiscal_year ORDER BY sum({OBL}) DESC) rn "
            f"  FROM {src} WHERE {col} IS NOT NULL AND awarding_agency_name IS NOT NULL AND action_date_fiscal_year IS NOT NULL "
            f"  GROUP BY 1, 2, 3) WHERE rn <= 15")
        for agency, fy, val, obl, txn in con.execute(sql_fy).fetchall():
            slot(agency, key, label, categorical).setdefault(fy, []).append({"label": val, "obl": obl or 0, "txn": txn})
        # top-15 per (agency, all years)
        sql_all = (
            f"SELECT agency, val, obl, txn FROM ("
            f"  SELECT awarding_agency_name agency, {col} val, sum({OBL}) obl, count(*) txn, "
            f"         row_number() OVER (PARTITION BY awarding_agency_name ORDER BY sum({OBL}) DESC) rn "
            f"  FROM {src} WHERE {col} IS NOT NULL AND awarding_agency_name IS NOT NULL "
            f"  GROUP BY 1, 2) WHERE rn <= 15")
        for agency, val, obl, txn in con.execute(sql_all).fetchall():
            slot(agency, key, label, categorical).setdefault("all", []).append({"label": val, "obl": obl or 0, "txn": txn})
        print(f"  agency breakdown: {key}", flush=True)

    years = sorted({r["fy"] for r in timeseries})
    agdir = dest / dataset / "agency"
    agdir.mkdir(parents=True, exist_ok=True)
    agencies = sorted({r["agency"] for r in timeseries})
    listing = []
    for a in agencies:
        rows = [r for r in timeseries if r["agency"] == a]
        kpis = {}
        for fy in years:
            kpis[fy] = {"obl": sum(r["obl"] for r in rows if r["fy"] == fy),
                        "txn": sum(r["txn"] for r in rows if r["fy"] == fy)}
        kpis["all"] = {"obl": sum(r["obl"] for r in rows), "txn": sum(r["txn"] for r in rows)}
        f = {"years": years, "kpis": kpis, "dims": per.get(a, {}),
             "timeseries": rows, "agency": a}
        slug = _slug(a)
        (agdir / f"{slug}.json").write_text(json.dumps(f, separators=(",", ":")))
        listing.append({"name": a, "slug": slug})
    print(f"  wrote {len(listing)} per-agency files under {agdir}", flush=True)
    return listing


def write_dataset(dataset, data, dest):
    """Write the main {dataset}.json plus one {dataset}.{key}.json per LAZY_DIMS entry
    (popped off `data['_lazy']` so they never land in the main payload)."""
    lazy = data.pop("_lazy", {})
    path = dest / f"{dataset}.json"
    path.write_text(json.dumps(data, separators=(",", ":")))
    print(f"  wrote {path} ({path.stat().st_size/1e6:.2f} MB, {len(data['years'])} years, "
          f"{len(data['dims'])} dims, {len(data.get('agencies', []))} agencies)", flush=True)
    for key, payload in lazy.items():
        lp = dest / f"{dataset}.{key}.json"
        lp.write_text(json.dumps(payload, separators=(",", ":")))
        print(f"  wrote {lp} ({lp.stat().st_size/1e6:.2f} MB, "
              f"{len(payload['periods'].get('all', []))} {key})", flush=True)


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "site" / "api"))
    dest = Path("site/public/precomputed")
    dest.mkdir(parents=True, exist_ok=True)
    for dataset in ("contracts", "assistance"):
        print(f"precomputing {dataset} …", flush=True)
        data = with_retry(f"{dataset} aggregates", lambda con: build(dataset, con))
        data["agencies"] = with_retry(
            f"{dataset} agency files",
            lambda con: build_agency_files(dataset, con, data["timeseries"], dest))
        write_dataset(dataset, data, dest)

        filters = with_retry(f"{dataset} filters", lambda con: build_filters(dataset, con))
        fpath = dest / f"{dataset}.filters.json"
        fpath.write_text(json.dumps(filters, separators=(",", ":")))
        print(f"  wrote {fpath} ({fpath.stat().st_size/1e6:.2f} MB, {len(filters)} filterable fields)", flush=True)


if __name__ == "__main__":
    main()
