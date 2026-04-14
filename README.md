# Brand Scraper

A scraper for brand/product data with a FastAPI backend and a Next.js frontend.

## Prerequisites

- Python 3.14+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- An OpenRouter API key

## Backend

The backend is a FastAPI app that drives browser scraping sessions and streams progress over SSE.

### Setup

```bash
cd backend
uv sync
uv run patchright install chromium
```

The OpenRouter API key is configured from the UI — click the gear icon
on the dashboard after starting the app. The key is stored locally in
`backend/data/settings.json` (gitignored). If you prefer env vars,
`OPENROUTER_API_KEY` and `OPENROUTER_MODEL` in `backend/.env` still work
as a fallback.

### Run

```bash
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Key endpoints:

- `POST /api/scrape/start` — start a scrape session
- `GET  /api/scrape/{id}/stream` — SSE event stream
- `POST /api/scrape/{id}/cancel` — cancel a running session
- `POST /api/scrape/{id}/login_complete` — resume after manual login

## Frontend

The frontend is a Next.js 16 app (React 19) that talks to the backend on port 8000.

### Setup

```bash
cd frontend
npm install
```

### Run

```bash
cd frontend
npm run dev
```

Open `http://localhost:3000`. CORS on the backend is pinned to this origin.

### Other scripts

```bash
npm run build   # production build
npm run start   # serve production build
npm run lint    # eslint
```

## Project layout

```
backend/     FastAPI app, scraper runners, platform adapters
frontend/    Next.js app
docs/        Plans and notes
windows/     One-click bundle scripts for non-technical Windows users
```

## Windows bundle (for non-technical recipients)

To share a runnable copy with a non-technical Windows user:

1. Run `scripts/package_windows.sh` to produce `dist/brand_scraper_windows.zip`.
2. Send them the zip. They extract it, open the `windows/` folder, and
   double-click `setup.bat` once, then `run.bat` every time.
3. Tell the recipient to open the app, click the gear icon on the dashboard,
   and paste their OpenRouter API key — keys are no longer bundled into the zip.

See `windows/HOW_TO_USE.txt` for the recipient-facing instructions.
