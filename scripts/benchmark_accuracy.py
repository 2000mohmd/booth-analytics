"""Compare system counts (from the event store) against a manually-recorded ground-truth CSV.
Re-run after any model/logic change - kept in the repo permanently per the testing strategy.

Ground-truth CSV columns: day,passersby,stoppers,avg_dwell
"""
import argparse
import csv

from services.metrics_engine import store


def load_ground_truth(csv_path: str) -> dict[str, dict]:
    with open(csv_path, newline="") as f:
        return {row["day"]: row for row in csv.DictReader(f)}


def compare(conn, booth_id: str, ground_truth: dict[str, dict]) -> list[dict]:
    results = []
    for day, truth in ground_truth.items():
        row = conn.execute(
            "SELECT * FROM daily_summary WHERE booth_id=? AND day=?", (booth_id, day)
        ).fetchone()
        if row is None:
            results.append({"day": day, "error": "no daily_summary row - run the metrics_engine rollup first"})
            continue
        results.append({
            "day": day,
            "passersby_system": row["passersby"], "passersby_truth": int(truth["passersby"]),
            "passersby_diff": row["passersby"] - int(truth["passersby"]),
            "stoppers_system": row["stoppers"], "stoppers_truth": int(truth["stoppers"]),
            "stoppers_diff": row["stoppers"] - int(truth["stoppers"]),
            "avg_dwell_system": row["avg_dwell"], "avg_dwell_truth": float(truth["avg_dwell"]),
            "avg_dwell_diff_s": round(row["avg_dwell"] - float(truth["avg_dwell"]), 2),
        })
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/events.db")
    parser.add_argument("--booth-id", required=True)
    parser.add_argument("--ground-truth-csv", required=True)
    args = parser.parse_args()

    conn = store.connect(args.db_path)
    ground_truth = load_ground_truth(args.ground_truth_csv)
    results = compare(conn, args.booth_id, ground_truth)

    for r in results:
        print(r)


if __name__ == "__main__":
    main()
