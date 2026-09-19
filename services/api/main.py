"""FastAPI app: REST + WebSocket. Phase 6: occupancy, totals, capture rate, demographic split, alerts."""
from fastapi import FastAPI

app = FastAPI(title="booth-analytics-api")


@app.get("/health")
def health():
    return {"status": "ok"}
