# Booth Analytics dashboard

React + Vite + Tailwind + Recharts. Live occupancy, alerts, hourly traffic, demographics,
dwell distribution - pulls from the FastAPI service (`services/api`) via REST + WebSocket.

## Dev

```bash
npm install
npm run dev
```

`vite.config.js` proxies `/api` and `/ws` to `http://localhost:8000` - run the API service
locally alongside this (`uvicorn services.api.main:app --port 8000`) for real data.

## Build

```bash
npm run build
```

Served via the `dashboard` container in the root `docker-compose.yml` (nginx serving the
static build, `api` reachable at the same origin behind whatever reverse proxy fronts it
at the venue).
