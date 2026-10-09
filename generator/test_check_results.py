"""Tests for check_results.py: it must pass correct exports and fail wrong ones, for the stated reason.

Run from ~/databricks-lab:  python3 -m unittest generator/test_check_results.py -v
"""
import csv                      # write the CSV exports the checker reads
import json                     # read expected.json
import sys                      # find sibling modules
import tempfile                 # throwaway folders
import unittest                 # standard test runner
from pathlib import Path        # paths

sys.path.insert(0, str(Path(__file__).parent))
import bib_gen                  # noqa: E402  makes the data and expected.json
import check_results            # noqa: E402  module under test


def read_rows(path: Path):
    with open(path, newline="") as f:
        return list(csv.reader(f))


def write_csv(path: Path, header, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def good_exports(exp, res: Path):
    """Write the exports a correct pipeline would produce."""
    res.mkdir(parents=True, exist_ok=True)
    write_csv(res / "task2_bronze.csv", ["date", "bronze_rows", "quarantined_lines"],
              [[d["date"], d["json_rows"], d["corrupt_json_lines"]] for d in exp["days"]])
    write_csv(res / "task4_silver.csv",
              ["date", "valid_unique_txns", "malformed_amount_rows", "duplicate_extra_rows", "late_rows"],
              [[d["date"], d["valid_unique_txns"], d["malformed_amount_rows"], d["duplicate_extra_rows"], d["late_rows"]]
               for d in exp["days"]])
    write_csv(res / "task5_gold.csv", ["date", "channel", "amount"],
              [[d["date"], ch, amt] for d in exp["days"] for ch, amt in d["amount_by_channel"].items()])
    alerts = []
    for d in exp["days"]:
        for a, _ in d["planted"]["impossible_travel"]:
            alerts.append([a, "impossible_travel"])
        for burst in d["planted"]["card_testing_bursts"]:
            alerts += [[t, "card_testing"] for t in burst]
        for tk in d["planted"]["account_takeovers"]:
            alerts.append([tk["wire_txn"], "account_takeover"])
    alerts.append(["T9999999", "card_testing"])  # one false positive: reported, must not fail the run
    write_csv(res / "task6_alerts.csv", ["txn_id", "pattern"], alerts)


class Check(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        bib_gen.generate(self.root / "out", seed=11, days=3, n_txn=150, n_login=80)
        self.exp = json.loads((self.root / "out" / "expected.json").read_text())
        self.res = self.root / "res"
        good_exports(self.exp, self.res)

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self):
        return check_results.run(self.root / "out" / "expected.json", self.res)

    def status(self, report, task):
        return next(r["status"] for r in report if r["task"] == task)

    def test_correct_exports_pass_all_tasks(self):
        report = self.run_check()
        for t in ("task2", "task4", "task5", "task6"):
            self.assertEqual(self.status(report, t), "PASS", report)

    def test_false_positives_are_reported_not_failed(self):
        r6 = next(r for r in self.run_check() if r["task"] == "task6")
        self.assertEqual(r6["status"], "PASS")
        self.assertIn("false positives: 1", r6["detail"])

    def test_missing_file_is_skipped_not_failed(self):
        (self.res / "task5_gold.csv").unlink()
        self.assertEqual(self.status(self.run_check(), "task5"), "SKIP")

    def test_wrong_duplicate_count_fails_task4(self):
        rows = read_rows(self.res / "task4_silver.csv")
        rows[1][3] = str(int(rows[1][3]) + 1)
        write_csv(self.res / "task4_silver.csv", rows[0], rows[1:])
        r = next(x for x in self.run_check() if x["task"] == "task4")
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("duplicate_extra_rows", r["detail"])

    def test_gold_off_by_one_cent_fails_task5(self):
        rows = read_rows(self.res / "task5_gold.csv")
        cents = round(float(rows[1][2]) * 100) + 1
        rows[1][2] = f"{cents // 100}.{cents % 100:02d}"
        write_csv(self.res / "task5_gold.csv", rows[0], rows[1:])
        self.assertEqual(self.status(self.run_check(), "task5"), "FAIL")

    def test_bronze_that_lost_rows_fails_task2(self):
        rows = read_rows(self.res / "task2_bronze.csv")
        rows[1][1] = str(int(rows[1][1]) - 1)
        write_csv(self.res / "task2_bronze.csv", rows[0], rows[1:])
        self.assertEqual(self.status(self.run_check(), "task2"), "FAIL")

    def test_missed_planted_fraud_fails_task6(self):
        rows = read_rows(self.res / "task6_alerts.csv")
        keep = [r for r in rows[1:] if r[1] != "account_takeover"]
        write_csv(self.res / "task6_alerts.csv", rows[0], keep)
        r = next(x for x in self.run_check() if x["task"] == "task6")
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("account_takeover", r["detail"])

    def test_partial_burst_fails_task6(self):
        rows = read_rows(self.res / "task6_alerts.csv")
        burst_id = self.exp["days"][0]["planted"]["card_testing_bursts"][0]
        drop = set(burst_id[:8])  # leaves 7 of 15
        keep = [r for r in rows[1:] if r[0] not in drop]
        write_csv(self.res / "task6_alerts.csv", rows[0], keep)
        self.assertEqual(self.status(self.run_check(), "task6"), "FAIL")

    def test_wrong_pattern_label_fails_task6(self):
        rows = read_rows(self.res / "task6_alerts.csv")
        relabeled = [[r[0], "card_testing" if r[1] == "impossible_travel" else r[1]] for r in rows[1:]]
        write_csv(self.res / "task6_alerts.csv", rows[0], relabeled)
        r = next(x for x in self.run_check() if x["task"] == "task6")
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("impossible_travel", r["detail"])

    def test_unknown_date_fails(self):
        rows = read_rows(self.res / "task4_silver.csv")
        rows.append(["2030-01-01", "1", "1", "1", "1"])
        write_csv(self.res / "task4_silver.csv", rows[0], rows[1:])
        r = next(x for x in self.run_check() if x["task"] == "task4")
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("unknown date", r["detail"])

    def test_only_days_present_are_checked(self):
        rows = read_rows(self.res / "task4_silver.csv")
        write_csv(self.res / "task4_silver.csv", rows[0], rows[1:2])  # day 1 only
        self.assertEqual(self.status(self.run_check(), "task4"), "PASS")


if __name__ == "__main__":
    unittest.main()
