"""Daily/final PDF report rendering via WeasyPrint. WeasyPrint needs a system GTK/Pango
install (present in the Docker image via apt, not always on a Windows dev box) - imported
lazily so the rest of the reporting package stays usable without it.
"""

TEMPLATE = """
<html><head><style>
  body {{ font-family: sans-serif; background: #0b0b0f; color: #f0f0f0; padding: 32px; }}
  h1 {{ color: #6ee7ff; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
  th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid #333; }}
</style></head><body>
  <h1>{booth_id} — {day}</h1>
  <table>
    <tr><th>Passersby</th><td>{passersby}</td></tr>
    <tr><th>Stoppers</th><td>{stoppers}</td></tr>
    <tr><th>Capture rate</th><td>{capture_rate:.1%}</td></tr>
    <tr><th>Avg dwell (s)</th><td>{avg_dwell}</td></tr>
    <tr><th>Median dwell (s)</th><td>{median_dwell}</td></tr>
    <tr><th>Peak hour</th><td>{peak_hour}</td></tr>
  </table>
</body></html>
"""


def render_daily_pdf(report_data: dict, out_path: str) -> str:
    from weasyprint import HTML  # lazy import - see module docstring

    s = report_data["summary"]
    html = TEMPLATE.format(**s)
    HTML(string=html).write_pdf(out_path)
    return out_path
