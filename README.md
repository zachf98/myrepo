# UFC Betting Edge Calculator

Lightweight full-stack web app that analyzes UFC fight cards using only free, publicly available data.

## What it does

- Select a UFC event from a dropdown
- Fetch and parse event fight card data
- Pull fighter stats and fight-history-derived features
- Retrieve public moneyline odds snapshots (when available)
- Compute:
  - Implied probabilities from American odds
  - No-vig normalized market probabilities
  - Explainable model-based win probabilities
  - Method of victory probabilities (KO/TKO, Submission, Decision)
- Compare model vs market and output per-fighter edge
- Highlight largest discrepancies and sort by strongest edge

## Free data sources used

- UFCStats.com
  - Event list (upcoming + completed)
  - Event cards
  - Fighter profile metrics
  - Fighter fight history and method outcomes
- Action Network public UFC scoreboard endpoint
  - Public moneyline snapshots (when available)

No paid APIs are used.

## Tech stack

- Frontend: React + Vite
- Backend: Node.js + Express
- Scraping/parsing: Axios + Cheerio

## Project structure

```text
backend/
  src/
    server.js
    services/
      analyzeService.js
      oddsService.js
      ufcStatsService.js
    models/
      probabilityModel.js
    utils/
      http.js
      probability.js
      text.js

frontend/
  src/
    App.jsx
    api/client.js
    components/
      EventSelector.jsx
      AnalysisDashboard.jsx
```

## Local setup

### 1) Install dependencies

```bash
npm install --prefix backend
npm install --prefix frontend
```

### 2) Start backend

```bash
npm run dev:backend
```

Backend defaults to `http://localhost:8080`.

### 3) Start frontend (new terminal)

```bash
npm run dev:frontend
```

Frontend defaults to `http://localhost:5173`.

If your backend runs on a different URL, set:

```bash
VITE_API_BASE_URL=http://your-backend-host:port
```

## API endpoints

- `GET /api/health`
- `GET /api/events`
- `POST /api/analyze`
  - body: `{ "eventUrl": "http://ufcstats.com/event-details/<id>" }`

## Notes on model transparency

The model is intentionally deterministic and explainable:

- Win probability combines weighted differences in:
  - Striking differential and efficiency
  - Grappling differential and submission activity
  - Finish rate profile
  - Opponent strength proxy (opponent aggregate win percentage)
- Method probabilities are derived from fighter-specific KO/Sub/Decision tendencies adjusted by opponent defensive/loss profiles.

All probability outputs are constrained and normalized to keep values interpretable.