import asyncio
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter

from app.brands import BrandAlreadyExists
from app.models import ScrapeRequest, ScrapeStartResponse
from app.runner import get_repo, run_scrape
from app.session import ScrapeSession, sessions

app = FastAPI(title="Brand Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- brand / source / run models ----

class CreateBrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class BrandOut(BaseModel):
    id: str
    name: str
    created_at: str


class SourceOut(BaseModel):
    id: str
    brand_id: str
    platform: str
    spec: dict[str, Any]
    created_at: str


class RunSummaryOut(BaseModel):
    id: str
    status: str
    aggregates: dict[str, Any]
    created_at: str


class BrandSummaryOut(BaseModel):
    id: str
    name: str
    created_at: str
    source_count: int
    latest_run: RunSummaryOut | None
    latest_source_platform: str | None
    latest_source_id: str | None


class BrandDetailOut(BaseModel):
    id: str
    name: str
    created_at: str
    sources: list[SourceOut]
    latest_run_by_source: dict[str, RunSummaryOut | None]


class CreateSourceIn(BaseModel):
    platform: str
    spec: dict[str, Any]


class UpdateSourceIn(BaseModel):
    spec: dict[str, Any]


def _validate_spec_for_platform(platform: str, spec: dict[str, Any]) -> None:
    try:
        TypeAdapter(ScrapeRequest).validate_python({"platform": platform, **spec})
    except Exception as exc:
        raise HTTPException(422, f"invalid spec for platform {platform!r}: {exc}")


# ---- brand endpoints ----

@app.post("/api/brands", response_model=BrandOut, status_code=201)
async def create_brand(payload: CreateBrandIn):
    try:
        b = get_repo().create_brand(name=payload.name)
    except BrandAlreadyExists as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return BrandOut(id=b.id, name=b.name, created_at=b.created_at)


@app.get("/api/brands", response_model=list[BrandSummaryOut])
async def list_brands():
    repo = get_repo()
    out: list[BrandSummaryOut] = []
    for b in repo.list_brands():
        sources = repo.list_sources(b.id)
        latest_run: RunSummaryOut | None = None
        latest_source_id: str | None = None
        latest_source_platform: str | None = None
        for s in sources:
            runs = repo.list_runs(b.id, s.id)
            if runs and (latest_run is None or runs[0].id > latest_run.id):
                latest_run = RunSummaryOut(**runs[0].__dict__)
                latest_source_id = s.id
                latest_source_platform = s.platform
        out.append(BrandSummaryOut(
            id=b.id, name=b.name, created_at=b.created_at,
            source_count=len(sources),
            latest_run=latest_run,
            latest_source_platform=latest_source_platform,
            latest_source_id=latest_source_id,
        ))
    return out


@app.get("/api/brands/{brand_id}", response_model=BrandDetailOut)
async def get_brand(brand_id: str):
    repo = get_repo()
    brand = repo.get_brand(brand_id)
    if brand is None:
        raise HTTPException(404, f"brand {brand_id!r} not found")
    sources = repo.list_sources(brand_id)
    latest_by_source: dict[str, RunSummaryOut | None] = {}
    for s in sources:
        runs = repo.list_runs(brand_id, s.id)
        latest_by_source[s.id] = RunSummaryOut(**runs[0].__dict__) if runs else None
    return BrandDetailOut(
        id=brand.id, name=brand.name, created_at=brand.created_at,
        sources=[SourceOut(**s.__dict__) for s in sources],
        latest_run_by_source=latest_by_source,
    )


@app.delete("/api/brands/{brand_id}", status_code=204)
async def delete_brand(brand_id: str):
    repo = get_repo()
    # Disallow deletion while a run is in flight for any source under this brand.
    for sess in sessions.values():
        if getattr(sess, "brand_id", None) == brand_id:
            raise HTTPException(409, "cannot delete brand while a run is in flight")
    if not repo.delete_brand(brand_id):
        raise HTTPException(404, f"brand {brand_id!r} not found")
    return None


@app.post("/api/brands/{brand_id}/sources", response_model=SourceOut, status_code=201)
async def create_source(brand_id: str, payload: CreateSourceIn):
    repo = get_repo()
    if repo.get_brand(brand_id) is None:
        raise HTTPException(404, f"brand {brand_id!r} not found")
    # Drop any `platform` key from spec — platform lives on the Source, not the spec.
    spec = {k: v for k, v in payload.spec.items() if k != "platform"}
    _validate_spec_for_platform(payload.platform, spec)
    source = repo.add_source(brand_id=brand_id, platform=payload.platform, spec=spec)
    return SourceOut(**source.__dict__)


@app.patch("/api/brands/{brand_id}/sources/{source_id}", response_model=SourceOut)
async def update_source(brand_id: str, source_id: str, payload: UpdateSourceIn):
    repo = get_repo()
    source = repo.get_source(brand_id, source_id)
    if source is None:
        raise HTTPException(404, f"source {source_id!r} not found")
    # Disallow edits while a run is in flight for this source.
    for sess in sessions.values():
        if getattr(sess, "brand_id", None) == brand_id and getattr(sess, "source_id", None) == source_id:
            raise HTTPException(409, "cannot edit source while a run is in flight")
    spec = {k: v for k, v in payload.spec.items() if k != "platform"}
    _validate_spec_for_platform(source.platform, spec)
    updated = repo.update_source_spec(brand_id, source_id, spec=spec)
    return SourceOut(**updated.__dict__)


@app.get("/api/brands/{brand_id}/sources/{source_id}/runs", response_model=list[RunSummaryOut])
async def list_runs(brand_id: str, source_id: str):
    repo = get_repo()
    if repo.get_source(brand_id, source_id) is None:
        raise HTTPException(404, f"source {source_id!r} not found")
    return [RunSummaryOut(**r.__dict__) for r in repo.list_runs(brand_id, source_id)]


@app.get("/api/brands/{brand_id}/sources/{source_id}/runs/{run_id}")
async def get_run(brand_id: str, source_id: str, run_id: str):
    repo = get_repo()
    payload = repo.get_run_payload(brand_id, source_id, run_id)
    if payload is None:
        raise HTTPException(404, f"run {run_id!r} not found")
    return payload


# ---- scrape endpoints (reshape in Task 1.9) ----

class StartScrapeIn(BaseModel):
    brand_id: str
    source_id: str


@app.post("/api/scrape/start", response_model=ScrapeStartResponse)
async def start_scrape(payload: StartScrapeIn) -> ScrapeStartResponse:
    repo = get_repo()
    source = repo.get_source(payload.brand_id, payload.source_id)
    if source is None:
        raise HTTPException(404, f"source {payload.source_id!r} not found")
    for sess in sessions.values():
        if sess.brand_id == payload.brand_id and sess.source_id == payload.source_id:
            raise HTTPException(409, "a run is already in flight for this source")
    scrape_id = uuid.uuid4().hex[:12]
    session = ScrapeSession(
        id=scrape_id,
        brand_id=payload.brand_id,
        source_id=payload.source_id,
    )
    sessions[scrape_id] = session
    session.task = asyncio.create_task(run_scrape(session))
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
                sessions.pop(scrape_id, None)
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/scrape/{scrape_id}/cancel")
async def cancel_scrape(scrape_id: str):
    session = sessions.get(scrape_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scrape session not found")
    session.cancel_event.set()
    session.login_event.set()
    return {"status": "cancelling"}


@app.post("/api/scrape/{scrape_id}/login_complete")
async def login_complete(scrape_id: str):
    session = sessions.get(scrape_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scrape session not found")
    session.login_event.set()
    return {"status": "resumed"}
