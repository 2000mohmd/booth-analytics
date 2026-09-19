"""CLI: generate a daily or final PDF report, or a raw Excel export, from the event store."""
import argparse
import os
from datetime import date

from services.metrics_engine import store
from services.reporting.data import daily_report_data
from services.reporting.excel import export_workbook


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=os.environ.get("DB_PATH", "data/events.db"))
    parser.add_argument("--booth-id", required=True)
    parser.add_argument("--day", default=date.today().isoformat())
    parser.add_argument("--out-dir", default="data/reports")
    parser.add_argument("--format", choices=["pdf", "excel"], default="pdf")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    conn = store.connect(args.db_path)

    if args.format == "excel":
        path = export_workbook(conn, args.booth_id, f"{args.out_dir}/{args.booth_id}_export.xlsx")
    else:
        from services.reporting.pdf import render_daily_pdf

        data = daily_report_data(conn, args.booth_id, args.day)
        path = render_daily_pdf(data, f"{args.out_dir}/{args.booth_id}_{args.day}.pdf")

    print(path)


if __name__ == "__main__":
    main()
