"""Single source of truth for the table builder: datasets, dimensions, metrics, filters.

Everything the aggregate engine can do is declared here as an allowlist, so dimension/
metric/filter keys map to vetted SQL (no injection — values are always bound parameters).
Mirrors the role of usajobs_historical/web/api/columns.py, generalized to a pivot builder.
"""

# Public HuggingFace dataset — used in the reproducible-code we hand back to users.
HF_REPO = "abigailhaddad/usaspending-bulk-awards"

OBL = "TRY_CAST(federal_action_obligation AS DOUBLE)"
UEI = "NULLIF(TRIM(recipient_uei), '')"

DATASETS = {
    "contracts":  {"award_key": "contract_award_unique_key"},
    "assistance": {"award_key": "assistance_award_unique_key"},
}

# dimension key -> {col, label, coded?}. `coded` dims get codebook labels in the UI.
DIMENSIONS = {
    "fiscal_year":      {"col": "action_date_fiscal_year", "label": "Fiscal year"},
    "month":            {"col": "strftime(TRY_CAST(action_date AS DATE), '%Y-%m')", "label": "Month"},
    "awarding_agency":  {"col": "awarding_agency_name", "label": "Awarding agency"},
    "awarding_subagency": {"col": "awarding_sub_agency_name", "label": "Awarding sub-agency"},
    "funding_agency":   {"col": "funding_agency_name", "label": "Funding agency"},
    "funding_subagency": {"col": "funding_sub_agency_name", "label": "Funding sub-agency"},
    "recipient":        {"col": "recipient_name", "label": "Recipient"},
    "recipient_parent": {"col": "recipient_parent_name", "label": "Recipient parent"},
    "state":            {"col": "recipient_state_code", "label": "Recipient state"},
    "county":           {"col": "recipient_county_name", "label": "Recipient county"},
    "naics":            {"col": "naics_code", "label": "NAICS code"},
    "naics_desc":       {"col": "naics_description", "label": "Industry (NAICS)"},
    "psc":              {"col": "product_or_service_code", "label": "PSC (product/service)"},
    "psc_desc":         {"col": "product_or_service_code_description", "label": "Product/service"},
    "award_type":       {"col": "award_type_code", "label": "Award type", "coded": True},
    "extent_competed":  {"col": "extent_competed", "label": "Competition", "coded": True},
    "set_aside":        {"col": "type_of_set_aside", "label": "Set-aside", "coded": True},
    "pricing":          {"col": "type_of_contract_pricing", "label": "Pricing type", "coded": True},
    "business_size":    {"col": "contracting_officers_determination_of_business_size",
                         "label": "Business size"},
}
# assistance-only / contracts-only dims are filtered in the UI per dataset; the SQL is generic.

# metric key -> {sql template, label}. {p} is replaced by the period mask (1 for no-period).
METRICS = {
    "obligations":  {"label": "Obligations ($)",
                     "sql": f"sum(CASE WHEN {{p}} THEN {OBL} END)"},
    "transactions": {"label": "Transactions",
                     "sql": "sum(CASE WHEN {p} THEN 1 ELSE 0 END)"},
    "vendors":      {"label": "Distinct vendors",
                     "sql": f"count(DISTINCT CASE WHEN {{p}} THEN {UEI} END)"},
    # nonzero-net vendors needs a per-UEI HAVING; handled specially in query.py
    "vendors_nonzero_net": {"label": "Vendors (nonzero net)", "special": True},
}

DATE_COL = "action_date"

# Columns returned by the disaggregated (record-level) download, per dataset.
DETAIL_COLUMNS = {
    "contracts": [
        "award_id_piid", "recipient_name", "recipient_uei", "awarding_agency_name",
        "funding_sub_agency_name", "action_date", "federal_action_obligation",
        "naics_code", "product_or_service_code", "extent_competed",
        "recipient_state_code", "recipient_county_name", "award_type_code",
    ],
    "assistance": [
        "award_id_fain", "recipient_name", "recipient_uei", "awarding_agency_name",
        "funding_sub_agency_name", "action_date", "federal_action_obligation",
        "cfda_number", "assistance_type_code",
        "recipient_state_code", "recipient_county_name",
    ],
}


import re

_IDENT = re.compile(r"^[a-z0-9_]{1,80}$")
# friendly aliases for a few raw code columns (codes are how people pin agencies)
_ALIASES = {
    "funding_subagency_code": "funding_sub_agency_code",
    "awarding_subagency_code": "awarding_sub_agency_code",
    "naics_code": "naics_code",
    "psc_code": "product_or_service_code",
}


def resolve_col(field):
    """SQL column expression for a field id: a curated dimension, a known alias, or ANY
    raw column name (validated as a bare identifier so it can't inject; then quoted).
    Returns None if the field isn't a safe identifier."""
    if field in DIMENSIONS:
        return DIMENSIONS[field]["col"]
    if field in _ALIASES:
        return _ALIASES[field]
    if _IDENT.match(field):
        return '"' + field + '"'
    return None


def parse_filters(params):
    """filter_<field>=a|b (IN) and filter_<field>_min/_max (range) -> (clauses, binds).

    `field` may be any column (validated by resolve_col); values are always bound.
    """
    clauses, binds = [], []
    for key, vals in params.items():
        if not key.startswith("filter_"):
            continue
        if key.endswith("_min"):
            col = resolve_col(key[len("filter_"):-len("_min")])
            if col:
                clauses.append(f"TRY_CAST({col} AS DOUBLE) >= ?"); binds.append(float(vals[0]))
        elif key.endswith("_max"):
            col = resolve_col(key[len("filter_"):-len("_max")])
            if col:
                clauses.append(f"TRY_CAST({col} AS DOUBLE) <= ?"); binds.append(float(vals[0]))
        else:
            col = resolve_col(key[len("filter_"):])
            items = [x for v in vals for x in v.split("|") if x != ""]
            if col and items:
                clauses.append(f"{col} IN ({','.join(['?']*len(items))})")
                binds += items
    return clauses, binds
