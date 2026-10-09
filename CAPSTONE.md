# Capstone: Big Iron Bank Fraud and Compliance Lakehouse

Status: spec written Oct 8 2026, NOT run. Platform commands are from docs and unverified until you run them.
You build the pipeline in your Databricks workspace. Claude built the data generator, the ground truth and the checks.
Honesty note for the README and your résumé: say what Claude scaffolded (generator, spec, checks) and what you wrote (the pipeline).

## What it shows an employer
A governed medallion pipeline for fake bank data: ingestion with schema drift, data quality, fraud detection rules checked
against known answers, Unity Catalog access control, audit, CI/CD with Asset Bundles, and a cost report with a forecast vs actual.

## Data (made up; see generator/bib_gen.py)
`python3 generator/bib_gen.py --out ./out --seed 42 --days 3` writes landing files and `expected.json` (ground truth).
Planted per day: 5 malformed amounts ("N/A"), 12 exact duplicates, 1 truncated JSON line, 8 late rows (from day 2),
a new column `device_trust_score` from the third file, and 3 fraud patterns (impossible travel x2, card-testing burst x1, account takeover x1).

## Layers (catalog bank_sec, per the runbook)
- landing: a Unity Catalog volume holding the raw files (upload from your PC).
- bronze: Auto Loader into bronze tables, schema evolution on, bad lines kept (rescued/quarantined), nothing dropped.
- silver: typed, de-duplicated by txn_id, malformed rows moved to a quarantine table with a reason, late rows flagged by event time vs file date.
- gold: daily totals by channel, customer risk features, and an alerts table from three detectors.

## Tasks (do in order; each has a check)
| # | Task | Done when |
|---|---|---|
| 1 | Upload day 1-2 files to the volume | files visible in Catalog; counts match raw_lines |
| 2 | Bronze with Auto Loader | bronze row count + quarantined lines = raw_lines per day |
| 3 | Add day 3 (drift) without breaking | new column appears; no data lost; earlier rows null |
| 4 | Silver cleanup | valid_unique_txns, malformed_amount_rows, duplicate_extra_rows, late_rows all equal expected.json |
| 5 | Gold daily totals | amount_by_channel equals expected.json to the cent |
| 6 | Three detectors | every planted pattern id found; report false positives separately |
| 7 | Governance | analysts see masked account ids and only their region; engineers see bronze/silver; deny test screenshot |
| 8 | Audit | system.access.audit query shows who read what (if the table is available; otherwise note why) |
| 9 | Job + Asset Bundle | one scheduled job deployed from a bundle file; `databricks bundle validate` clean |
| 10 | CI | validate runs on every commit (GitHub Actions only if you decide to publish; otherwise a local script) |
| 11 | Cost report | forecast first, then actual usage from the usage page or system.billing, with variance explained |
| 12 | README | diagram, how to rebuild, screenshots, honest limits |

## Rebuild test
Delete nothing; make a new schema (bank_sec_v2) and rebuild everything from your scripts. If it works, you own it.

## Timeline fit (trial ends about Oct 22: confirm)
Course first; capstone tasks 1-6 about Oct 15-17, 7-9 about Oct 18-19, 10-12 plus export Oct 20-21.

## Next things Claude can build when you ask
- check_results.py: compares CSV exports of your silver/gold/alert tables to expected.json and prints pass/fail per task.
- Detector reference rules (hidden until you try) and a sample dashboard spec.
