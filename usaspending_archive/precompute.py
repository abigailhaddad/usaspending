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
from pathlib import Path

import duckdb

OBL = "TRY_CAST(federal_action_obligation AS DOUBLE)"
TOPN = 25  # high-cardinality dims keep their top N; categorical dims keep all values
HF_REPO = "abigailhaddad/usaspending-bulk-awards"

# curated dimensions per dataset: key -> (label, sql column, categorical?)
# categorical dims are small and kept whole; the rest are truncated to the top N by $.
DIMS = {
    "contracts": {
        "awarding_agency":    ("Awarding agency",       "awarding_agency_name",        False),
        "awarding_subagency": ("Awarding sub-agency",    "awarding_sub_agency_name",    False),
        "recipient":          ("Recipient",              "recipient_name",              False),
        "state":              ("Recipient state",        "recipient_state_code",        True),
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
        "state":              ("Recipient state",        "recipient_state_code",        True),
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
    if os.environ.get("CF_R2_ACCOUNT_ID"):
        con.execute(f"""CREATE SECRET r2 (TYPE r2, KEY_ID '{os.environ['CF_R2_ACCESS_KEY_ID']}',
            SECRET '{os.environ['CF_R2_SECRET_ACCESS_KEY']}', ACCOUNT_ID '{os.environ['CF_R2_ACCOUNT_ID']}')""")
    elif os.environ.get("HF_TOKEN"):
        con.execute(f"CREATE SECRET hf (TYPE huggingface, TOKEN '{os.environ['HF_TOKEN']}')")
    return con


def build(dataset, con):
    src = source(dataset)
    out = {"trend": [], "kpis": {}, "dims": {}, "years": []}

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
        out["dims"][key] = {"label": label, "categorical": categorical, "periods": periods}

    return out


# Table Builder filter dropdowns: precompute distinct values (+ labels) for the low-card
# filterable fields so the wizard's pickers are static, not live queries. Known high-card
# fields are marked searchable (free-text) without scanning.
FILTER_SKIP = {"recipient", "recipient_parent", "county", "naics", "naics_desc",
               "psc", "psc_desc", "month", "naics_code", "psc_code"}


def build_filters(dataset):
    """{field: {options:[{value,label}]} | {searchable:true}} for the Table Builder."""
    import filter_options  # from site/api (added to sys.path in main)
    import dims as sdims
    fields = list(sdims.DIMENSIONS.keys()) + [
        "funding_subagency_code", "awarding_subagency_code", "naics_code", "psc_code"]
    out = {}
    for f in fields:
        if f in FILTER_SKIP:
            out[f] = {"searchable": True}
            continue
        try:
            r = filter_options.build_options(f, dataset)
            out[f] = {"options": r["options"]} if r.get("options") else {"searchable": True}
        except Exception as e:
            print(f"  filter {f}: {str(e)[:60]} -> searchable", flush=True)
            out[f] = {"searchable": True}
    return out


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "site" / "api"))
    dest = Path("site/public/precomputed")
    dest.mkdir(parents=True, exist_ok=True)
    con = connect()
    for dataset in ("contracts", "assistance"):
        print(f"precomputing {dataset} …", flush=True)
        data = build(dataset, con)
        path = dest / f"{dataset}.json"
        path.write_text(json.dumps(data, separators=(",", ":")))
        print(f"  wrote {path} ({path.stat().st_size/1e6:.2f} MB, "
              f"{len(data['years'])} years, {len(data['dims'])} dims)", flush=True)

        filters = build_filters(dataset)
        fpath = dest / f"{dataset}.filters.json"
        fpath.write_text(json.dumps(filters, separators=(",", ":")))
        n_opt = sum(1 for v in filters.values() if "options" in v)
        print(f"  wrote {fpath} ({fpath.stat().st_size/1e6:.2f} MB, {n_opt} option lists)", flush=True)


if __name__ == "__main__":
    main()
