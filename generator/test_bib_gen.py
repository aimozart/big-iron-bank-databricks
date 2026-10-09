"""Tests for the Big Iron Bank fake-data generator.

Run:  python3 -m unittest generator/test_bib_gen.py -v     (from ~/databricks-lab)
The recount below is written separately from the generator on purpose: it re-reads the
landed files and must agree with expected.json, so the ground truth is checked, not trusted.
"""
import hashlib                  # fingerprint a whole output folder
import ipaddress                # check every IP is in a reserved documentation range
import json                     # read landed JSON lines and expected.json
import sys                      # let the test find bib_gen.py next to it
import tempfile                 # throwaway output folders
import unittest                 # standard library test runner
from datetime import datetime   # parse timestamps
from pathlib import Path        # file paths

sys.path.insert(0, str(Path(__file__).parent))
import bib_gen                  # noqa: E402  the module under test

DOC_NETS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
SMALL = dict(days=3, n_txn=200, n_login=120)


def fingerprint(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def read_txn_file(path: Path):
    """Return (rows, corrupt_line_count) from one landed transactions file."""
    rows, corrupt = [], 0
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            corrupt += 1
    return rows, corrupt


def is_number(v) -> bool:
    return isinstance(v, str) and v.replace(".", "", 1).isdigit()


class Gen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "a"
        bib_gen.generate(cls.out, seed=7, **SMALL)
        cls.exp = json.loads((cls.out / "expected.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_same_seed_same_bytes_other_seed_differs(self):
        with tempfile.TemporaryDirectory() as t:
            b, c = Path(t) / "b", Path(t) / "c"
            bib_gen.generate(b, seed=7, **SMALL)
            bib_gen.generate(c, seed=8, **SMALL)
            self.assertEqual(fingerprint(self.out), fingerprint(b))
            self.assertNotEqual(fingerprint(self.out), fingerprint(c))

    def test_expected_json_matches_independent_recount(self):
        for day in self.exp["days"]:
            rows, corrupt = read_txn_file(self.out / "landing" / "transactions" / f"{day['date']}.jsonl")
            valid = [r for r in rows if is_number(r.get("amount"))]
            uniq = {}
            for r in valid:
                uniq.setdefault(r["txn_id"], r)
            by_channel = {}
            for r in uniq.values():
                by_channel[r["channel"]] = by_channel.get(r["channel"], 0) + round(float(r["amount"]) * 100)
            self.assertEqual(day["corrupt_json_lines"], corrupt)
            self.assertEqual(day["json_rows"], len(rows))
            self.assertEqual(day["malformed_amount_rows"], len(rows) - len(valid))
            self.assertEqual(day["duplicate_extra_rows"], len(valid) - len(uniq))
            self.assertEqual(day["valid_unique_txns"], len(uniq))
            self.assertEqual(day["fraud_labeled_unique"], sum(1 for r in uniq.values() if r["is_fraud_label"]))
            self.assertEqual(
                {k: v for k, v in day["amount_by_channel"].items()},
                {k: f"{v // 100}.{v % 100:02d}" for k, v in by_channel.items()},
            )

    def test_planted_defects_are_present(self):
        for i, day in enumerate(self.exp["days"]):
            self.assertEqual(day["corrupt_json_lines"], 1)
            self.assertEqual(day["malformed_amount_rows"], bib_gen.N_MALFORMED)
            self.assertEqual(day["duplicate_extra_rows"], bib_gen.N_DUP)
            self.assertEqual(day["late_rows"], 0 if i == 0 else bib_gen.N_LATE)

    def test_late_rows_are_really_old(self):
        for i, day in enumerate(self.exp["days"]):
            rows, _ = read_txn_file(self.out / "landing" / "transactions" / f"{day['date']}.jsonl")
            file_date = datetime.strptime(day["date"], "%Y-%m-%d").date()
            late = {r["txn_id"] for r in rows
                    if (file_date - datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").date()).days >= 2}
            self.assertEqual(len(late), day["late_rows"])

    def test_schema_drift_only_from_day_index_2(self):
        # the contract is written here on purpose (not read from the generator's own output)
        col, first = "device_trust_score", 2
        self.assertEqual(self.exp["schema_drift"], {"column": col, "first_day_index": first})
        for i, day in enumerate(self.exp["days"]):
            rows, _ = read_txn_file(self.out / "landing" / "transactions" / f"{day['date']}.jsonl")
            has = [col in r for r in rows]
            self.assertTrue(all(has) if i >= first else not any(has), f"day {i}")

    def test_fraud_patterns_exist(self):
        for day in self.exp["days"]:
            rows, _ = read_txn_file(self.out / "landing" / "transactions" / f"{day['date']}.jsonl")
            by_id = {r["txn_id"]: r for r in rows}
            for a, b in day["planted"]["impossible_travel"]:
                x, y = by_id[a], by_id[b]
                self.assertEqual(x["account_id"], y["account_id"])
                self.assertNotEqual(x["geo"].split("-")[0], y["geo"].split("-")[0])
                dt = abs(datetime.strptime(x["ts"], "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(y["ts"], "%Y-%m-%dT%H:%M:%SZ"))
                self.assertLessEqual(dt.total_seconds(), 600)
            for burst in day["planted"]["card_testing_bursts"]:
                self.assertGreaterEqual(len(burst), 10)
                accts = {by_id[t]["account_id"] for t in burst}
                self.assertEqual(len(accts), 1)
                self.assertTrue(all(float(by_id[t]["amount"]) < 5 for t in burst))
            for tk in day["planted"]["account_takeovers"]:
                logins = [json.loads(x) for x in
                          (self.out / "landing" / "logins" / f"{day['date']}.jsonl").read_text().splitlines()]
                mine = [x for x in logins if x["user_id"] == tk["user_id"]]
                self.assertGreaterEqual(sum(1 for x in mine if x["result"] == "fail"), 5)
                self.assertTrue(any(x["result"] == "success" and x["device_id"] == tk["new_device"] for x in mine))
                self.assertGreaterEqual(float(by_id[tk["wire_txn"]]["amount"]), 5000)

    def test_only_made_up_values(self):
        for line in (self.out / "reference" / "customers.csv").read_text().splitlines()[1:]:
            self.assertTrue(line.split(",")[2].endswith("@example.test"), line)
        for f in (self.out / "landing" / "logins").glob("*.jsonl"):
            for line in f.read_text().splitlines():
                ip = ipaddress.ip_address(json.loads(line)["ip"])
                self.assertTrue(any(ip in n for n in DOC_NETS), ip)


if __name__ == "__main__":
    unittest.main()
