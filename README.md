# usaspending

Mirror the [USAspending Award Data Archive](https://files.usaspending.gov/award_data_archive/)
(public-domain prime contract & assistance bulk files) into clean partitioned
parquet, publish to HuggingFace, query from a Vercel BI site, and ship a Colab
demo notebook — following the OPM / usajobs_historical pattern.

**Status: feasibility scoping.** See [`docs/FINDINGS.md`](docs/FINDINGS.md) for the
full inventory, measured sizes, reuse map, and open decisions.

## The archive at a glance

91.4 GB compressed, FY2007–FY2026, one file per agency:

| Product | Files | Compressed |
|---|---|---|
| Contracts_Full (297 cols) | 2,260 | 54.8 GB |
| Assistance_Full (112 cols) | 2,260 | 35.8 GB |
| Contracts_Delta / Assistance_Delta | 109 | 0.8 GB |

zip → CSV ≈ 9.3× (~830 GB CSV). Subawards & account File A/B/C are **not** here —
they come from the Custom Bulk Download API (not the Postgres dump).

## Modules

- `usaspending_archive/archive_index.py` — list/classify the full archive
  (`python3 usaspending_archive/archive_index.py` prints the inventory).
