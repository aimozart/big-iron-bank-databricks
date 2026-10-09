#!/usr/bin/env python3
"""Big Iron Bank fake-data generator. Made-up values only. Same seed gives the same bytes.

Writes, under --out:
  reference/customers.csv, reference/accounts.csv
  landing/transactions/YYYY-MM-DD.jsonl   (one file per day, like a nightly drop)
  landing/logins/YYYY-MM-DD.jsonl
  expected.json                           (ground truth to reconcile your pipeline against)

Planted on purpose, so a pipeline can be checked: duplicates, malformed amounts, one corrupt JSON
line per day, late-arriving rows, schema drift (new column from day index 2), and three fraud patterns.
Usage: python3 generator/bib_gen.py --out ./out --seed 42 --days 3
"""
import argparse                               # command line options
import csv                                    # write the customer and account files
import json                                   # write JSON lines and expected.json
import random                                 # seeded random numbers (deterministic per seed)
from datetime import date, datetime, timedelta  # dates and timestamps
from pathlib import Path                      # file paths

N_MALFORMED = 5     # rows per day whose amount is the text "N/A"
N_DUP = 12          # exact duplicate rows per day
N_LATE = 8          # rows per day (from day index 1) dated 3 days earlier than the file
DRIFT_FROM_DAY = 2  # index of the first file that has the extra column
DRIFT_COLUMN = "device_trust_score"

FIRST = ["Ari", "Bela", "Cato", "Dena", "Elio", "Faye", "Gus", "Hana", "Ivo", "Jada",
         "Kian", "Lena", "Milo", "Nora", "Omar", "Pia", "Quin", "Rhea", "Sven", "Tala"]
LAST = ["Ardent", "Brook", "Calder", "Dunmore", "Ellery", "Fenwick", "Garrow", "Holloway", "Ironside", "Jessup",
        "Kestrel", "Lowell", "Marlow", "Norwood", "Overton", "Pryce", "Quill", "Ridley", "Stroud", "Thorne"]
MERCHANTS = ["Grocer", "Fuel", "Pharmacy", "Airline", "Hotel", "Streaming", "Hardware", "Restaurant", "Utilities", "Marketplace"]
CHANNELS = ["card", "ach", "wire", "mobile"]
HOME_GEOS = ["US-AZ", "US-CA", "US-TX", "US-NY", "CA-ON"]
DOC_IPS = [f"{net}.{h}" for net in ("192.0.2", "198.51.100", "203.0.113") for h in range(1, 60)]  # reserved ranges


def money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def make_reference(out: Path, rng: random.Random, n_customers=300, n_accounts=400):
    customers = []
    for i in range(n_customers):
        cid = f"C{i + 1:04d}"
        customers.append({
            "customer_id": cid,
            "name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
            "email": f"{cid.lower()}@example.test",
            "region": rng.choice(["west", "central", "east"]),
            "home_geo": rng.choice(HOME_GEOS),
        })
    accounts = [{"account_id": f"A{i + 1:05d}", "customer_id": customers[rng.randrange(n_customers)]["customer_id"],
                 "type": rng.choice(["checking", "savings", "credit"])} for i in range(n_accounts)]
    ref = out / "reference"
    ref.mkdir(parents=True, exist_ok=True)
    with open(ref / "customers.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "name", "email", "region", "home_geo"])
        for c in customers:
            w.writerow([c["customer_id"], c["name"], c["email"], c["region"], c["home_geo"]])
    with open(ref / "accounts.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["account_id", "customer_id", "type"])
        for a in accounts:
            w.writerow([a["account_id"], a["customer_id"], a["type"]])
    return {c["customer_id"]: c for c in customers}, accounts


def generate(out, seed=42, days=3, start="2026-10-01", n_txn=800, n_login=600):
    out = Path(out)
    (out / "landing" / "transactions").mkdir(parents=True, exist_ok=True)
    (out / "landing" / "logins").mkdir(parents=True, exist_ok=True)
    customers, accounts = make_reference(out, random.Random(f"{seed}-master"))
    start_day = date.fromisoformat(start)
    expected = {"seed": seed, "config": {"days": days, "n_txn": n_txn, "n_login": n_login,
                                         "n_malformed": N_MALFORMED, "n_dup": N_DUP, "n_late": N_LATE},
                "schema_drift": {"column": DRIFT_COLUMN, "first_day_index": DRIFT_FROM_DAY}, "days": []}
    seq = 0

    def txn(d, rng, acct, ts, cents, channel, geo, fraud):
        nonlocal seq
        seq += 1
        row = {"txn_id": f"T{d}{seq:06d}", "ts": stamp(ts), "account_id": acct["account_id"],
               "amount": money(cents), "merchant": rng.choice(MERCHANTS), "channel": channel,
               "geo": geo, "is_fraud_label": fraud}
        if d >= DRIFT_FROM_DAY:
            row[DRIFT_COLUMN] = round(rng.random(), 3)
        return row

    for d in range(days):
        day = start_day + timedelta(days=d)
        midnight = datetime(day.year, day.month, day.day)
        rng = random.Random(f"{seed}-day-{d}")
        home = lambda a: customers[a["customer_id"]]["home_geo"]  # noqa: E731

        rows = []
        for _ in range(n_txn):
            a = rng.choice(accounts)
            rows.append(txn(d, rng, a, midnight + timedelta(seconds=rng.randrange(86400)),
                            rng.randint(100, 50000), rng.choice(CHANNELS), home(a), rng.random() < 0.005))

        # planted fraud patterns
        picks = rng.sample(accounts, 4)
        travel_pairs, bursts, takeovers = [], [], []
        for a in picks[:2]:                                   # impossible travel: two countries 5 minutes apart
            t0 = midnight + timedelta(seconds=rng.randrange(40000, 60000))
            x = txn(d, rng, a, t0, rng.randint(40000, 90000), "card", "US-AZ", True)
            y = txn(d, rng, a, t0 + timedelta(minutes=5), rng.randint(40000, 90000), "card", "GB-LND", True)
            rows += [x, y]
            travel_pairs.append([x["txn_id"], y["txn_id"]])
        a = picks[2]                                          # card testing: 15 tiny charges in 10 minutes
        t0 = midnight + timedelta(seconds=rng.randrange(20000, 40000))
        burst = [txn(d, rng, a, t0 + timedelta(seconds=40 * k), rng.randint(100, 499), "card", home(a), True) for k in range(15)]
        rows += burst
        bursts.append([r["txn_id"] for r in burst])
        a = picks[3]                                          # takeover: failed logins, new device, big wire
        t_login = midnight + timedelta(seconds=rng.randrange(30000, 50000))
        wire = txn(d, rng, a, t_login + timedelta(minutes=10), rng.randint(500000, 900000), "wire", home(a), True)
        rows.append(wire)
        takeovers.append({"user_id": a["customer_id"], "new_device": f"DV-NEW-{d}", "wire_txn": wire["txn_id"]})

        late_ids = []
        if d >= 1:                                            # late-arriving rows: dated 3 days before the file
            for _ in range(N_LATE):
                a = rng.choice(accounts)
                r = txn(d, rng, a, midnight - timedelta(days=3) + timedelta(seconds=rng.randrange(86400)),
                        rng.randint(100, 50000), rng.choice(CHANNELS), home(a), False)
                rows.append(r)
                late_ids.append(r["txn_id"])

        base = [r for r in rows if r["txn_id"] not in set(late_ids)]
        spoilable = [r for r in base if not r["is_fraud_label"]]
        for r in rng.sample(spoilable, N_MALFORMED):          # malformed amounts
            r["amount"] = "N/A"
        dup_pool = [r for r in rows if r["amount"] != "N/A"]
        rows += [dict(r) for r in rng.sample(dup_pool, N_DUP)]  # exact duplicates
        rng.shuffle(rows)

        lines = [json.dumps(r, separators=(",", ":")) for r in rows]
        victim = rng.choice(rows)["txn_id"]
        lines.insert(rng.randrange(len(lines)), '{"txn_id":"%s","ts":"%s","amount":' % (victim, stamp(midnight)))  # truncated JSON
        (out / "landing" / "transactions" / f"{day.isoformat()}.jsonl").write_text("\n".join(lines) + "\n")

        # logins
        users = list(customers)
        logins = []
        for _ in range(n_login):
            u = rng.choice(users)
            logins.append({"ts": stamp(midnight + timedelta(seconds=rng.randrange(86400))), "user_id": u,
                           "ip": rng.choice(DOC_IPS), "device_id": f"DV{u[1:]}-{rng.randint(1, 2)}",
                           "result": "success" if rng.random() < 0.92 else "fail",
                           "geo": customers[u]["home_geo"], "risk_flag": False})
        tk = takeovers[0]
        for k in range(6):
            logins.append({"ts": stamp(t_login + timedelta(seconds=20 * k)), "user_id": tk["user_id"], "ip": rng.choice(DOC_IPS),
                           "device_id": tk["new_device"], "result": "fail", "geo": "JP-13", "risk_flag": True})
        logins.append({"ts": stamp(t_login + timedelta(seconds=140)), "user_id": tk["user_id"], "ip": rng.choice(DOC_IPS),
                       "device_id": tk["new_device"], "result": "success", "geo": "JP-13", "risk_flag": True})
        rng.shuffle(logins)
        (out / "landing" / "logins" / f"{day.isoformat()}.jsonl").write_text(
            "\n".join(json.dumps(x, separators=(",", ":")) for x in logins) + "\n")

        # ground truth, computed from the rows exactly as they were written
        valid = [r for r in rows if r["amount"] != "N/A"]
        uniq = {r["txn_id"]: r for r in valid}
        by_channel = {}
        for r in uniq.values():
            by_channel[r["channel"]] = by_channel.get(r["channel"], 0) + round(float(r["amount"]) * 100)
        expected["days"].append({
            "date": day.isoformat(), "raw_lines": len(lines), "corrupt_json_lines": 1, "json_rows": len(rows),
            "malformed_amount_rows": len(rows) - len(valid), "duplicate_extra_rows": len(valid) - len(uniq),
            "late_rows": len(late_ids), "valid_unique_txns": len(uniq),
            "fraud_labeled_unique": sum(1 for r in uniq.values() if r["is_fraud_label"]),
            "amount_by_channel": {k: money(v) for k, v in sorted(by_channel.items())},
            "login_rows": len(logins), "login_failed_rows": sum(1 for x in logins if x["result"] == "fail"),
            "planted": {"impossible_travel": travel_pairs, "card_testing_bursts": bursts, "account_takeovers": takeovers},
        })
    (out / "expected.json").write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
    return expected


def main():
    p = argparse.ArgumentParser(description="Generate fake Big Iron Bank data with planted defects.")
    p.add_argument("--out", default="out")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--start", default="2026-10-01")
    p.add_argument("--n-txn", type=int, default=800)
    p.add_argument("--n-login", type=int, default=600)
    a = p.parse_args()
    generate(a.out, a.seed, a.days, a.start, a.n_txn, a.n_login)
    print(f"wrote {a.out} (seed {a.seed}, {a.days} days)")


if __name__ == "__main__":
    main()
