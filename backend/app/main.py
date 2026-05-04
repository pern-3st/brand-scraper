import asyncio
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, TypeAdapter

from app import settings as app_settings
from app.brands import BrandAlreadyExists
from app.models import (
    EnrichmentRequest,
    FieldDef,
    ScrapeRequest,
    ScrapeStartResponse,
    UnifiedTable,
)
from app.runner import (
    ENRICHMENT_EXTRACTORS,
    PRODUCT_IDENTITIES,
    get_repo,
    run_enrichment,
    run_scrape,
)
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


@app.get("/api/brands/{brand_id}/sources/{source_id}/runs/{run_id}/logs")
async def get_run_logs(brand_id: str, source_id: str, run_id: str):
    repo = get_repo()
    if repo.get_source(brand_id, source_id) is None:
        raise HTTPException(404, f"source {source_id!r} not found")
    if repo.get_run_payload(brand_id, source_id, run_id) is None:
        raise HTTPException(404, f"run {run_id!r} not found")
    return repo.get_run_logs(brand_id, source_id, run_id)


@app.get(
    "/api/brands/{brand_id}/sources/{source_id}/runs/{run_id}"
    "/enrichments/{enrichment_id}/logs"
)
async def get_enrichment_logs(
    brand_id: str, source_id: str, run_id: str, enrichment_id: str,
):
    repo = get_repo()
    if repo.get_source(brand_id, source_id) is None:
        raise HTTPException(404, f"source {source_id!r} not found")
    if repo.get_run_payload(brand_id, source_id, run_id) is None:
        raise HTTPException(404, f"run {run_id!r} not found")
    if repo.get_enrichment_payload(brand_id, source_id, run_id, enrichment_id) is None:
        raise HTTPException(404, f"enrichment {enrichment_id!r} not found")
    return repo.get_enrichment_logs(brand_id, source_id, run_id, enrichment_id)


@app.delete("/api/brands/{brand_id}/sources/{source_id}/runs/{run_id}", status_code=204)
async def delete_run(brand_id: str, source_id: str, run_id: str):
    repo = get_repo()
    for sess in sessions.values():
        if getattr(sess, "brand_id", None) == brand_id and getattr(sess, "source_id", None) == source_id:
            raise HTTPException(409, "cannot delete run while a scrape is in flight for this source")
    if not repo.delete_run(brand_id, source_id, run_id):
        raise HTTPException(404, f"run {run_id!r} not found")
    return None


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


# ---- enrichment endpoints ----

class EnrichmentFieldsOut(BaseModel):
    fields: list[FieldDef]
    supports_freeform: bool


class EnrichmentStartResponse(BaseModel):
    session_id: str


class EnrichmentSummaryOut(BaseModel):
    id: str
    status: str
    aggregates: dict[str, Any]
    request: dict[str, Any]


def _validate_enrichment_request(platform: str, request: EnrichmentRequest) -> None:
    """Reject requests that ask for unknown curated fields or freeform
    prompts on a platform that doesn't support them. Identifier safety
    (valid Python identifiers, cross-collision) is already enforced by
    ``EnrichmentRequest``/``FreeformPrompt`` validators."""
    if platform not in ENRICHMENT_EXTRACTORS:
        raise HTTPException(422, f"platform {platform!r} does not support enrichment")
    extractor_cls = ENRICHMENT_EXTRACTORS[platform]
    catalog_ids = {fd.id for fd in extractor_cls.available_fields}
    unknown = [fid for fid in request.curated_fields if fid not in catalog_ids]
    if unknown:
        raise HTTPException(
            422, f"unknown curated fields for {platform!r}: {unknown}"
        )
    if request.freeform_prompts and not extractor_cls.supports_freeform:
        raise HTTPException(
            422, f"platform {platform!r} does not support freeform prompts"
        )


@app.get("/api/platforms/{platform}/enrichment_fields", response_model=EnrichmentFieldsOut)
async def get_enrichment_fields(platform: str) -> EnrichmentFieldsOut:
    if platform not in ENRICHMENT_EXTRACTORS:
        raise HTTPException(404, f"platform {platform!r} has no enrichment extractor")
    extractor_cls = ENRICHMENT_EXTRACTORS[platform]
    return EnrichmentFieldsOut(
        fields=list(extractor_cls.available_fields),
        supports_freeform=extractor_cls.supports_freeform,
    )


@app.post(
    "/api/brands/{brand_id}/sources/{source_id}/runs/{run_id}/enrichments",
    response_model=EnrichmentStartResponse,
)
async def start_enrichment(
    brand_id: str, source_id: str, run_id: str, payload: EnrichmentRequest,
) -> EnrichmentStartResponse:
    repo = get_repo()
    source = repo.get_source(brand_id, source_id)
    if source is None:
        raise HTTPException(404, f"source {source_id!r} not found")
    parent = repo.get_run_payload(brand_id, source_id, run_id)
    if parent is None:
        raise HTTPException(404, f"run {run_id!r} not found")
    parent_status = parent.get("_status")
    if parent_status not in {"ok", "cancelled"}:
        raise HTTPException(
            409,
            f"parent run is {parent_status!r}; enrichment requires an ok or cancelled run",
        )

    # The parent's platform drives field validation — callers don't pass it.
    platform = (parent.get("_meta") or {}).get("platform") or source.platform
    _validate_enrichment_request(platform, payload)

    # Mutex against any other session for this (brand, source).
    for sess in sessions.values():
        if sess.brand_id == brand_id and sess.source_id == source_id:
            raise HTTPException(409, "a run is already in flight for this source")

    session_id = uuid.uuid4().hex[:12]
    session = ScrapeSession(
        id=session_id,
        brand_id=brand_id,
        source_id=source_id,
        parent_run_id=run_id,
        request=payload,
    )
    sessions[session_id] = session
    session.task = asyncio.create_task(run_enrichment(session))
    return EnrichmentStartResponse(session_id=session_id)


@app.get(
    "/api/brands/{brand_id}/sources/{source_id}/runs/{run_id}/enrichments",
    response_model=list[EnrichmentSummaryOut],
)
async def list_enrichments(
    brand_id: str, source_id: str, run_id: str,
) -> list[EnrichmentSummaryOut]:
    repo = get_repo()
    if repo.get_run_payload(brand_id, source_id, run_id) is None:
        raise HTTPException(404, f"run {run_id!r} not found")
    return [EnrichmentSummaryOut(**e) for e in repo.list_enrichments(brand_id, source_id, run_id)]


@app.get(
    "/api/brands/{brand_id}/sources/{source_id}/runs/{run_id}/enrichments/{enrichment_id}"
)
async def get_enrichment(brand_id: str, source_id: str, run_id: str, enrichment_id: str):
    repo = get_repo()
    payload = repo.get_enrichment_payload(brand_id, source_id, run_id, enrichment_id)
    if payload is None:
        raise HTTPException(404, f"enrichment {enrichment_id!r} not found")
    return payload


@app.delete(
    "/api/brands/{brand_id}/sources/{source_id}/runs/{run_id}/enrichments/{enrichment_id}",
    status_code=204,
)
async def delete_enrichment(brand_id: str, source_id: str, run_id: str, enrichment_id: str):
    repo = get_repo()
    # Block while a session for this source is in flight — it might be the
    # pass we're about to delete.
    for sess in sessions.values():
        if sess.brand_id == brand_id and sess.source_id == source_id:
            raise HTTPException(
                409, "cannot delete enrichment while a run is in flight for this source",
            )
    if not repo.delete_enrichment(brand_id, source_id, run_id, enrichment_id):
        raise HTTPException(404, f"enrichment {enrichment_id!r} not found")
    return None


@app.get(
    "/api/brands/{brand_id}/sources/{source_id}/runs/{run_id}/table",
    response_model=UnifiedTable,
)
async def get_unified_table(
    brand_id: str,
    source_id: str,
    run_id: str,
    include_enrichments: str = "latest_per_field",
) -> UnifiedTable:
    repo = get_repo()
    parent = repo.get_run_payload(brand_id, source_id, run_id)
    if parent is None:
        raise HTTPException(404, f"run {run_id!r} not found")
    platform = (parent.get("_meta") or {}).get("platform")
    identity = PRODUCT_IDENTITIES.get(platform)
    if identity is None:
        raise HTTPException(
            422, f"platform {platform!r} has no registered product identity",
        )

    include: "str | list[str]"
    if include_enrichments in {"all", "latest_per_field"}:
        include = include_enrichments
    else:
        # Comma-separated id list selects specific passes.
        include = [p.strip() for p in include_enrichments.split(",") if p.strip()]
        if not include:
            raise HTTPException(422, "include_enrichments must be non-empty")
    try:
        return repo.get_unified_table(
            brand_id, source_id, run_id, identity=identity, include=include,
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# ---- settings endpoints ----

class SettingsOut(BaseModel):
    openrouter_api_key_set: bool
    openrouter_api_key_hint: str
    openrouter_model: str


class UpdateSettingsIn(BaseModel):
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None


@app.get("/api/settings", response_model=SettingsOut)
async def get_settings() -> SettingsOut:
    return SettingsOut(**app_settings.masked_view())


@app.put("/api/settings", response_model=SettingsOut)
async def update_settings(payload: UpdateSettingsIn) -> SettingsOut:
    key = payload.openrouter_api_key
    if key is not None:
        key = key.strip()
    model = payload.openrouter_model
    if model is not None:
        model = model.strip()
    app_settings.save(
        openrouter_api_key=key,
        openrouter_model=model,
    )
    return SettingsOut(**app_settings.masked_view())
