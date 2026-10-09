# Big Iron Bank Fraud and Compliance Lakehouse

A Databricks data engineering capstone on **fake** bank data (made-up names, `@example.test` emails, reserved documentation IP ranges).

- `generator/`: deterministic fake-data generator with planted defects (duplicates, malformed amounts, corrupt JSON lines, late rows,
  schema drift, three fraud patterns) and an `expected.json` ground truth. 7 tests; mutation-checked.
- `generator/check_results.py`: compares CSV exports of your bronze/silver/gold/alert tables to `expected.json` and prints PASS/FAIL/SKIP per task (11 tests; mutation-checked).
- `CAPSTONE.md`: the 12-task spec and acceptance checks.
- `export.sh`: exports a workspace folder with the Databricks CLI and commits it (refuses if it finds secrets).
- `sql/`, `notebooks/`, `bundles/`, `evidence/`: the pipeline, grants, bundle files and screenshots (added as they are built).

## Who did what
The data generator, ground truth, tests, spec and export script were scaffolded with Claude (an AI assistant) and reviewed by me.
The Databricks pipeline, governance setup and write-up are written by me, in my own workspace.

## Run the generator
    python3 generator/bib_gen.py --out ./out --seed 42 --days 3
    python3 -m unittest generator/test_bib_gen.py generator/test_check_results.py -v
    python3 generator/check_results.py out/expected.json results/

No real data, credentials or payment details are in this repository.
