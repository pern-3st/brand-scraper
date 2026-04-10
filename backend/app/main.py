import asyncio
import json
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.models import ScrapeRequest, ScrapeResponse, ScrapeStartResponse
from app.scraper import run_scrape_streaming
from app.session import ScrapeSession, sessions

app = FastAPI(title="Brand Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/scrape/start", response_model=ScrapeStartResponse)
async def start_scrape(request: ScrapeRequest) -> ScrapeStartResponse:
    scrape_id = uuid.uuid4().hex[:12]
    session = ScrapeSession(id=scrape_id, request=request)
    sessions[scrape_id] = session
    session.task = asyncio.create_task(run_scrape_streaming(session))
    return ScrapeStartResponse(scrape_id=scrape_id)


@app.get("/api/scrape/{scrape_id}/stream")
async def stream_scrape(scrape_id: str):
    session = sessions.get(scrape_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scrape session not found")

    async def event_generator():
        while True:
            event = await session.queue.get()
            evt_type = event["event"]
            evt_data = event["data"]
            yield f"event: {evt_type}\ndata: {evt_data}\n\n"
            if evt_type in ("done", "error", "cancelled"):
                # Clean up session after terminal event
                sessions.pop(scrape_id, None)
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/scrape/{scrape_id}/cancel")
async def cancel_scrape(scrape_id: str):
    session = sessions.get(scrape_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scrape session not found")
    session.cancel_event.set()
    return {"status": "cancelling"}
