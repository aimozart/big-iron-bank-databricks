#!/usr/bin/env python3
"""Compare your pipeline's CSV exports to expected.json (the generator's ground truth).

Put these CSVs in one folder (export them from your notebooks; only days you have done need to be present):
  task2_bronze.csv   date,bronze_rows,quarantined_lines
  task4_silver.csv   date,valid_unique_txns,malformed_amount_rows,duplicate_extra_rows,late_rows
  task5_gold.csv     date,channel,amount            (amount like 123.45)
  task6_alerts.csv   txn_id,pattern                  (impossible_travel | card_testing | account_takeover)
Usage: python3 generator/check_results.py out/expected.json results/
A missing file is SKIP. Wrong numbers are FAIL. Extra alerts are reported as false positives and do not fail.
"""
import csv                      # read the exports
import json                     # read expected.json
import sys                      # command line and exit code
from decimal import Decimal     # compare money exactly (no float rounding)
from pathlib import Path        # file paths

BURST_MIN = 10  # a card-testing burst counts as found when at least this many of its charges are alerted


def read_csv(path: Path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def result(task, status, detail=""):
    return {"task": task, "status": status, "detail": detail}


def check_ints(task, rows, days, mapping):
    """mapping: column in the export -> key in expected.json."""
    problems, seen = [], 0
    for r in rows:
        day = days.get(r["date"])
        if day is None:
            problems.append(f"{r['date']}: unknown date")
            continue
        seen += 1
        for col, key in mapping.items():
            got = int(r[col])
            if got != day[key]:
                problems.append(f"{r['date']} {col}: got {got}, expected {day[key]}")
    return result(task, "FAIL", "; ".join(problems)) if problems else result(task, "PASS", f"{seen} day(s) match")


def check_gold(rows, days):
    problems, dates = [], set()
    by_date = {}
    for r in rows:
        by_date.setdefault(r["date"], {})[r["channel"]] = Decimal(r["amount"])
    for date, chans in by_date.items():
        day = days.get(date)
        if day is None:
            problems.append(f"{date}: unknown date")
            continue
        dates.add(date)
        want = {k: Decimal(v) for k, v in day["amount_by_channel"].items()}
        for ch in sorted(set(want) | set(chans)):
            if want.get(ch) != chans.get(ch):
                problems.append(f"{date} {ch}: got {chans.get(ch)}, expected {want.get(ch)}")
    return result("task5", "FAIL", "; ".join(problems)) if problems else result("task5", "PASS", f"{len(dates)} day(s) match")


def check_alerts(rows, exp_days):
    alerts = {}
    for r in rows:
        alerts.setdefault(r["txn_id"], set()).add(r["pattern"])
    planted_ids, missing, days_checked = set(), [], 0
    for i, day in enumerate(exp_days):
        if not any(t.startswith(f"T{i}") and len(t) == 8 for t in alerts):
            continue  # nothing alerted for this day yet: not checked
        days_checked += 1
        p = day["planted"]
        for a, b in p["impossible_travel"]:
            planted_ids.update((a, b))
            if not any("impossible_travel" in alerts.get(t, ()) for t in (a, b)):
                missing.append(f"impossible_travel day {i} ({a})")
        for burst in p["card_testing_bursts"]:
            planted_ids.update(burst)
            hit = sum("card_testing" in alerts.get(t, ()) for t in burst)
            if hit < BURST_MIN:
                missing.append(f"card_testing day {i} ({hit}/{len(burst)} charges alerted)")
        for tk in p["account_takeovers"]:
            planted_ids.add(tk["wire_txn"])
            if "account_takeover" not in alerts.get(tk["wire_txn"], ()):
                missing.append(f"account_takeover day {i} ({tk['wire_txn']})")
    false_pos = sum(1 for t in alerts if t not in planted_ids)
    if missing:
        return result("task6", "FAIL", "missed: " + "; ".join(missing) + f"; false positives: {false_pos}")
    return result("task6", "PASS", f"{days_checked} day(s): all planted patterns found; false positives: {false_pos}")


def run(expected_path, results_dir):
    exp = json.loads(Path(expected_path).read_text())
    days = {d["date"]: d for d in exp["days"]}
    res = Path(results_dir)
    report = []

    def load(name, task):
        p = res / name
        if not p.exists():
            report.append(result(task, "SKIP", f"{name} not found"))
            return None
        return read_csv(p)

    rows = load("task2_bronze.csv", "task2")
    if rows is not None:
        report.append(check_ints("task2", rows, days, {"bronze_rows": "json_rows", "quarantined_lines": "corrupt_json_lines"}))
    rows = load("task4_silver.csv", "task4")
    if rows is not None:
        report.append(check_ints("task4", rows, days, {k: k for k in
                                 ("valid_unique_txns", "malformed_amount_rows", "duplicate_extra_rows", "late_rows")}))
    rows = load("task5_gold.csv", "task5")
    if rows is not None:
        report.append(check_gold(rows, days))
    rows = load("task6_alerts.csv", "task6")
    if rows is not None:
        report.append(check_alerts(rows, exp["days"]))
    return sorted(report, key=lambda r: r["task"])


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    report = run(sys.argv[1], sys.argv[2])
    for r in report:
        print(f"{r['status']:5} {r['task']}  {r['detail']}")
    return 1 if any(r["status"] == "FAIL" for r in report) else 0


if __name__ == "__main__":
    sys.exit(main())
