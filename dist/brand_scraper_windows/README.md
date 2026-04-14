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

Create `backend/.env`:

```
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=x-ai/grok-4.1-fast
```

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

1. Ensure `backend/.env` exists locally with a real `OPENROUTER_API_KEY`.
   **This key will be embedded in the zip — use a dedicated key with a spend cap.**
2. Run `scripts/package_windows.sh` to produce `dist/brand_scraper_windows.zip`.
3. Send them the zip. They extract it, open the `windows/` folder, and
   double-click `setup.bat` once, then `run.bat` every time.

See `windows/HOW_TO_USE.txt` for the recipient-facing instructions.
