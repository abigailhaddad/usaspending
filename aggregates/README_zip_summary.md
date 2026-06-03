# ZIP-level spending summary (`zip_summary.parquet`)

A precomputed rollup of federal contract and assistance spending **by recipient ZIP code**,
so you can filter/download ZIP-level numbers without scanning the full ~2-billion-row archive.

## Grain & columns

One row per **`dataset` × `fiscal_year` × `awarding_agency` × recipient ZIP5**:

| column | type | notes |
|---|---|---|
| `dataset` | string | `contracts` or `assistance` |
| `fiscal_year` | string | federal fiscal year, FY2007–2026 |
| `awarding_agency` | string | awarding agency name (so you can filter by agency) |
| `recipient_zip` | string | recipient 5-digit ZIP (first 5 of the recipient ZIP+4) |
| `recipient_state_code` | string | recipient state (ZIP→state is effectively 1:1) |
| `obligations` | double | sum of `federal_action_obligation` |
| `transactions` | bigint | number of award transactions |

~3.7M rows, ~55,700 distinct ZIPs. To get a ZIP's all-agency total, sum across
`awarding_agency` (and/or `fiscal_year`).

## Coverage caveat

These are **recipient-ZIP** totals and cover only the awards that carry a usable recipient
ZIP — about **$30.6T of the ~$69T** total obligations in the archive. A large share of
assistance in particular (e.g. direct payments, and awards booked to aggregate/again-unknown
recipients) has no specific recipient ZIP and is **not** represented here. Use the full
per-year / per-agency parquet for complete totals.

Note: `recipient_zip` is taken as the first 5 characters of the reported recipient ZIP+4 and
is not otherwise validated, so a small number of malformed ZIPs may appear.

## Source & regeneration

Derived from the `serve/{dataset}/*.parquet` tables in this dataset (public USAspending Award
Data Archive, FY2007–2026). Rebuild with `usaspending_archive/build_zip_summary.py`.
