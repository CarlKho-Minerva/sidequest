"""Sidequest's HTTP API and the one-page UI.

Endpoints:
  GET  /healthz                      liveness, plus whether Elasticsearch answers
  GET  /api/prompt                   the text an attendee pastes into their own AI to get an interest profile
  POST /api/search                   {"query", "kinds", "day", "k"} -> ranked hits (hybrid search)
  POST /api/plan                     {"interests", "day", "simplify", "side_events"} -> the day plan + side events
  POST /api/phone/register           {"event_name", "event_url"} -> start the phone agent on the attendee's own phone
  GET  /api/phone/status/{task_id}   what the phone agent is doing
  GET  /                             the UI (ui/index.html)

Observability is part of the product: every request and every outbound call runs inside an OpenTelemetry
span, the plan response carries its own build time and counts, and the metrics below feed a dashboard
and an SLO ("95 percent of plans in under 2 seconds").
"""

from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from sidequest import phone, search
from sidequest.planner import Candidate, candidate_from_hit, plan_day
from sidequest.telemetry import get_meter, get_tracer, setup_telemetry

log = logging.getLogger("sidequest.api")
UI_DIR = Path(__file__).resolve().parent.parent / "ui"
DEFAULT_DAY = os.environ.get("SIDEQUEST_DEFAULT_DAY", "2026-11-10")
DAY_NAMES = {
    "2026-11-09": "Monday November 9",
    "2026-11-10": "Tuesday November 10",
    "2026-11-11": "Wednesday November 11",
    "2026-11-12": "Thursday November 12",
}

setup_telemetry(service_name="sidequest-api")
tracer = get_tracer("sidequest.api")
meter = get_meter("sidequest.api")
plan_seconds = meter.create_histogram(
    "sidequest.plan.seconds", unit="s", description="Time to build one day plan"
)
plan_items = meter.create_histogram("sidequest.plan.items", unit="1", description="Talks kept in a plan")
search_hits = meter.create_histogram(
    "sidequest.search.hits", unit="1", description="Hits returned by a search"
)
phone_runs = meter.create_counter("sidequest.phone.runs", unit="1", description="Phone agent runs started")

app = FastAPI(title="Sidequest", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

try:  # instrument after the app exists; harmless when the exporter is not configured
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app)
except Exception as exc:  # pragma: no cover
    log.warning("FastAPI instrumentation not active: %s", exc)

_es = None


@app.on_event("startup")
def warm_up() -> None:
    """Load the embedding model before the first request. Agent0 showed the first plan of a process taking
    2.9 s against 0.2 s warm; that cold start was the model loading inside the request."""
    with tracer.start_as_current_span("startup.warm_embedder"):
        try:
            search.embed(["warm up"])
        except Exception as exc:
            log.warning("embedder warm-up skipped: %s", exc)


def es():
    global _es
    if _es is None:
        _es = search.es_client()
    return _es


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    kinds: list[str] = ["talk", "side_event"]
    day: str | None = None
    k: int = Field(default=20, ge=1, le=100)


class PlanRequest(BaseModel):
    interests: str = Field(
        min_length=1, max_length=4000, description="free text or the YAML profile from /api/prompt"
    )
    day: str = DEFAULT_DAY
    simplify: bool = False
    side_events: bool = True
    quiet_break: bool = True


class PhoneRegisterRequest(BaseModel):
    event_name: str = Field(min_length=2, max_length=200)
    event_url: str | None = None


PROMPT = """You know my interests, my work and how I like my days. Write me a short interest profile for the
KubeCon + CloudNativeCon North America 2026 conference, as YAML with exactly these keys:

topics: a list of 4 to 8 short phrases I want talks about (be specific: "LLM inference on GPUs", not "AI")
people: a list of 2 to 5 kinds of people I want to meet (roles, companies or communities)
avoid: a list of topics I do not want
energy: one of low, normal, high (how packed my day can be)
needs: a list of 1 to 3 plain-language needs (for example "breaks between talks", "quiet rooms", "captions")

Only the YAML, no commentary."""


def _interest_lines(text: str) -> list[str]:
    """Pull the search phrases out of free text or the YAML profile. Keeps 'avoid' out of the query."""
    lines, section = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.endswith(":") and " " not in line.rstrip(":"):
            section = line[:-1].lower()
            continue
        if ":" in line and not line.startswith("-"):
            key, _, val = line.partition(":")
            section = key.strip().lower()
            if val.strip() and section in {"topics", "people"}:
                lines.append(val.strip().strip("[]"))
            continue
        if line.startswith("-"):
            if section in {"topics", "people", ""}:
                lines.append(line[1:].strip().strip("\"'"))
            continue
        lines.append(line)
    return lines or [text.strip()]


def _avoid_terms(text: str) -> list[str]:
    section, terms = "", []
    for raw in text.splitlines():
        line = raw.strip()
        if ":" in line and not line.startswith("-"):
            section = line.partition(":")[0].strip().lower()
            continue
        if line.startswith("-") and section == "avoid":
            terms.append(line[1:].strip().strip("\"'").lower())
    return terms


def _why(hit: dict, phrases: list[str]) -> str:
    """One plain line saying which of the attendee's phrases this item matched. Deterministic."""
    hay = f"{hit.get('title', '')} {hit.get('track', '')} {' '.join(hit.get('tags') or [])} {hit.get('text', '')}".lower()
    matched = [p for p in phrases if any(w for w in p.lower().split() if len(w) > 3 and w in hay)]
    if matched:
        return f"Matches your interest in {matched[0]}."
    return f"Close in meaning to what you asked for ({hit.get('track') or 'related talk'})."


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    ok = False
    try:
        ok = bool(es().ping())
    except Exception as exc:
        log.warning("elasticsearch ping failed: %s", exc)
    return {
        "status": "ok" if ok else "degraded",
        "elasticsearch": ok,
        "time": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/prompt")
def prompt() -> dict[str, str]:
    return {"prompt": PROMPT}


@app.get("/api/rum-config")
def rum_config() -> dict[str, Any]:
    """Browser monitoring settings. Only an ingest-only token meant to be public goes here."""
    token = os.environ.get("DASH0_WEB_TOKEN")
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    if not token or not endpoint:
        return {"enabled": False}
    return {
        "enabled": True,
        "url": f"{endpoint}/v1/traces",
        "token": token,
        "environment": os.environ.get("SIDEQUEST_ENV", "hackathon"),
    }


@app.post("/api/search")
def api_search(req: SearchRequest) -> dict[str, Any]:
    with tracer.start_as_current_span("search") as span:
        span.set_attribute("sidequest.query", req.query[:200])
        hits = search.hybrid_search(
            es(), req.query, k=req.k, kinds=tuple(req.kinds), day=DAY_NAMES.get(req.day or "", req.day)
        )
        search_hits.record(len(hits), {"kinds": ",".join(req.kinds)})
        return {"hits": hits, "count": len(hits)}


@app.post("/api/plan")
def api_plan(req: PlanRequest) -> dict[str, Any]:
    t0 = time.perf_counter()
    with tracer.start_as_current_span("plan") as span:
        try:
            day = datetime.fromisoformat(req.day)
        except ValueError as exc:
            raise HTTPException(400, f"day must be YYYY-MM-DD: {exc}") from exc
        phrases = _interest_lines(req.interests)
        avoid = _avoid_terms(req.interests)
        span.set_attribute("sidequest.day", req.day)
        span.set_attribute("sidequest.phrases", len(phrases))
        span.set_attribute("sidequest.simplify", req.simplify)

        # One hybrid search per phrase, merged by best score, so a narrow interest is not drowned by a broad one.
        merged: dict[str, dict] = {}
        with tracer.start_as_current_span("plan.search"):
            for phrase in phrases[:8]:
                for h in search.hybrid_search(
                    es(), phrase, k=25, kinds=("talk",), day=DAY_NAMES.get(req.day)
                ):
                    if any(a in (h["title"] + " " + h.get("text", "")).lower() for a in avoid):
                        continue
                    if h["id"] not in merged or h["score"] > merged[h["id"]]["score"]:
                        merged[h["id"]] = h
        candidates: list[Candidate] = [c for c in (candidate_from_hit(h) for h in merged.values()) if c]

        with tracer.start_as_current_span("plan.schedule"):
            plan = plan_day(candidates, day=day, quiet_break=req.quiet_break, simplify=req.simplify)
        for item in plan.items:
            if item.type == "talk":
                item.why = _why(merged[item.id], phrases)

        side: list[dict] = []
        if req.side_events:
            with tracer.start_as_current_span("plan.side_events"):
                seen = set()
                for phrase in [*phrases, "networking happy hour meet people"][:6]:
                    for h in search.hybrid_search(es(), phrase, k=10, kinds=("side_event",)):
                        if h["id"] in seen:
                            continue
                        seen.add(h["id"])
                        h["why"] = _why(h, phrases)
                        side.append(h)
                side.sort(key=lambda h: (-h["score"], h["start"]))
                side = side[:8]

        elapsed = time.perf_counter() - t0
        plan_seconds.record(elapsed, {"simplify": str(req.simplify)})
        plan_items.record(len(plan.talks))
        span.set_attribute("sidequest.plan.chosen", len(plan.talks))
        out = plan.as_dict()
        out["day"] = req.day
        out["day_name"] = DAY_NAMES.get(req.day, req.day)
        out["phrases"] = phrases
        out["side_events"] = side
        out["stats"]["seconds"] = round(elapsed, 3)
        out["stats"]["talks_in_index"] = _count_talks(req.day)
        return out


def _count_talks(day: str) -> int:
    try:
        name = DAY_NAMES.get(day)
        q = {"bool": {"filter": [{"term": {"kind": "talk"}}] + ([{"term": {"day": name}}] if name else [])}}
        return int(es().count(index=search.INDEX, query=q)["count"])
    except Exception:
        return 0


@app.post("/api/phone/register")
def api_phone_register(req: PhoneRegisterRequest) -> dict[str, Any]:
    with tracer.start_as_current_span("phone.register") as span:
        span.set_attribute("sidequest.event", req.event_name)
        phone_runs.add(1)
        try:
            return phone.start_registration(req.event_name, req.event_url)
        except phone.PhoneUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc


@app.get("/api/phone/status/{task_id}")
def api_phone_status(task_id: str) -> dict[str, Any]:
    with tracer.start_as_current_span("phone.status") as span:
        span.set_attribute("sidequest.task_id", task_id)
        try:
            out = phone.status(task_id)
        except phone.PhoneUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        span.set_attribute("sidequest.phone.state", str(out.get("state")))
        return out


@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


if UI_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")


def today_default() -> str:
    d = date.today().isoformat()
    return d if d in DAY_NAMES else DEFAULT_DAY
