"""FastAPI service implementing docs/api/v1.md (base path /api/v1, OpenAPI at /api/v1/openapi.json).

    uv run patribot-api                         # uvicorn on 127.0.0.1:8000 (PATRIBOT_API_HOST / PATRIBOT_API_PORT)
    uv run uvicorn patribot.api.main:app --reload

Data comes from the warehouse (DuckDB) or the Postgres serving copy, see patribot.planner.repository.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from patribot.api.chat import parse_message
from patribot.planner import places, trains
from patribot.planner.plan import SamePlace, plan
from patribot.planner.repository import RepositoryUnavailable
from patribot.planner.schemas import ETA_MODEL, PlanRequest, PlanResponse, TrainDetail, TrainPerformance
from patribot.planner.service import PlannerService

API_PREFIX = "/api/v1"
DEFAULT_CORS = "http://localhost:3000,http://localhost:3100"  # web app: next dev, next start / e2e
log = logging.getLogger(__name__)
FREE_QUERIES_PER_DAY = 3  # BRD FR-23 default; the Phase 2 stub does not meter


class ChatRequest(BaseModel):
    session_id: str = Field("", max_length=128)
    message: str = Field(min_length=1, max_length=2000)


def create_app(service: PlannerService | None = None) -> FastAPI:
    app = FastAPI(
        title="PatriBot API",
        version="1.0.0",
        description="Indian Railways trip planner with predicted arrival times (docs/api/v1.md).",
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    origins = [o.strip() for o in os.environ.get("PATRIBOT_CORS_ORIGINS", DEFAULT_CORS).split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"]
    )
    app.state.service = service or PlannerService()

    @app.exception_handler(RepositoryUnavailable)
    async def _unavailable(_: Request, exc: RepositoryUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": f"data unavailable: {exc}"})

    @app.exception_handler(places.UnknownPlace)
    async def _unknown_place(_: Request, exc: places.UnknownPlace) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"unknown place: {exc.text}"})

    router = APIRouter(prefix=API_PREFIX)

    def svc(request: Request) -> PlannerService:
        return request.app.state.service

    @router.get("/health")
    def health(request: Request) -> JSONResponse:
        try:
            data = svc(request).data()
        except RepositoryUnavailable as exc:
            return JSONResponse(
                status_code=503, content={"status": "unavailable", "detail": str(exc), "eta_model": ETA_MODEL}
            )
        as_of = data.data_as_of.isoformat() if data.data_as_of else None
        return JSONResponse({"status": "ok", "data_as_of": as_of, "eta_model": ETA_MODEL})

    @router.get("/places/search")
    def places_search(
        request: Request, q: str = Query(min_length=1, max_length=64), limit: int = Query(10, ge=1, le=50)
    ):
        results = places.search(svc(request).data(), q, limit)
        return {"results": [r.model_dump_contract() for r in results]}

    @router.post("/plan", response_model=PlanResponse)
    def plan_endpoint(request: Request, body: PlanRequest) -> PlanResponse:
        s = svc(request)
        try:
            return plan(s.data(), body, s.today())
        except SamePlace as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/trains/{train_no}", response_model=TrainDetail)
    def train(request: Request, train_no: str) -> TrainDetail:
        s = svc(request)
        detail = trains.train_detail(s.data(), train_no, s.today())
        if detail is None:
            raise HTTPException(status_code=404, detail=f"unknown train: {train_no}")
        return detail

    @router.get("/trains/{train_no}/performance", response_model=TrainPerformance)
    def performance(request: Request, train_no: str, months: int = Query(3, ge=1, le=24)) -> TrainPerformance:
        s = svc(request)
        if train_no not in s.data().trains:
            raise HTTPException(status_code=404, detail=f"unknown train: {train_no}")
        return trains.performance(train_no, s.repo.runs(train_no), months)

    @router.post("/chat")
    def chat(request: Request, body: ChatRequest) -> StreamingResponse:
        s = svc(request)
        return StreamingResponse(
            _chat_events(s, body), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    app.include_router(router)
    return app


ChatErrorCode = Literal["quota_exhausted", "spend_guard", "server_error"]


def chat_error(code: ChatErrorCode, detail: str) -> dict[str, str]:
    """Payload of an SSE `error` event (docs/api/v1.md). The stub only emits server_error; quota_exhausted and
    spend_guard arrive with metering in Phase 4 (BRD FR-23, FR-24)."""
    return {"code": code, "detail": detail}


def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _chat_events(s: PlannerService, body: ChatRequest) -> Iterator[str]:
    """Phase 2 stub: rule-based parse → planner → fixed text + itineraries (docs/api/v1.md, POST /chat)."""
    done = sse("done", {"usage": {"queries_left_today": FREE_QUERIES_PER_DAY}})
    try:
        data = s.data()
        parsed = parse_message(body.message, data, s.today())
        if parsed.request is None:
            yield sse("token", {"text": parsed.question})
            yield done
            return
        result = plan(data, parsed.request, s.today())
    except (places.UnknownPlace, SamePlace, ValueError) as exc:
        # a question back, not an error (FR-3): the message was understood only in part
        if isinstance(exc, places.UnknownPlace):
            text = f"I don't know the place '{exc.text}'."
        elif isinstance(exc, SamePlace):
            text = "The origin and the destination are the same place."
        else:  # PlanRequest validation, e.g. a date window longer than 31 days
            text = "I couldn't turn that into a search (dates are limited to a 31-day window)."
        yield sse("token", {"text": f"{text} Could you rephrase, e.g. 'Kolkata to Delhi, Nov 20-30'?"})
        yield done
        return
    except RepositoryUnavailable as exc:
        yield sse("error", chat_error("server_error", f"data unavailable: {exc}"))
        return
    except Exception:  # never leak a stack trace into the stream
        log.exception("chat stub failed")
        yield sse("error", chat_error("server_error", "something went wrong, please try again"))
        return
    n = len(result.itineraries)
    text = (
        f"Here {'is the best option' if n == 1 else f'are the {n} best options'} I found for {parsed.summary}. "
        if n
        else f"I found no trains for {parsed.summary}. Try a wider date range or allow split journeys. "
    )
    text += "Predicted times come from past delays on these trains. (Simple rule-based reply: AI chat comes later.)"
    for chunk in re.split(r"(?<=\. )", text):
        if chunk:
            yield sse("token", {"text": chunk})
    yield sse("meta", result.meta.model_dump(mode="json"))  # addition: booking window, ETA model, data_as_of
    yield sse("itineraries", [it.model_dump(mode="json") for it in result.itineraries])
    yield done
