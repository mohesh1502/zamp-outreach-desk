"""FastAPI app: run control, SSE streaming, history, review actions.

Streaming note. POST /api/runs returns the run id immediately and does the work
on a worker thread; the browser then opens GET /api/runs/{id}/stream. That is a
race -- the first stages can complete before the EventSource connects -- so every
event is appended to an in-memory buffer and the stream replays the buffer from
the start before tailing live. Reconnecting mid-run therefore shows the whole
run, not just the remainder.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any, Iterator, Optional

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from . import config, fixtures, guardrails, llm, pipeline, scoring, sources, store
from .models import RunRequest

app = FastAPI(title="Outreach Desk", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- live buffers

class RunChannel:
    """Event buffer + fan-out for one in-flight run."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.subscribers: list[queue.Queue] = []
        self.closed = False
        self.lock = threading.Lock()

    def publish(self, kind: str, payload: dict[str, Any]) -> None:
        event = {"kind": kind, "at": time.time(), "payload": payload}
        with self.lock:
            self.events.append(event)
            subscribers = list(self.subscribers)
            if kind in ("done", "error"):
                self.closed = True
        for sub in subscribers:
            sub.put(event)

    def subscribe(self) -> tuple[list[dict[str, Any]], queue.Queue]:
        sub: queue.Queue = queue.Queue()
        with self.lock:
            backlog = list(self.events)
            if not self.closed:
                self.subscribers.append(sub)
        return backlog, sub

    def unsubscribe(self, sub: queue.Queue) -> None:
        with self.lock:
            if sub in self.subscribers:
                self.subscribers.remove(sub)


CHANNELS: dict[str, RunChannel] = {}
CHANNELS_LOCK = threading.Lock()
MAX_CHANNELS = 40


def _channel(run_id: str) -> RunChannel:
    with CHANNELS_LOCK:
        if run_id not in CHANNELS:
            CHANNELS[run_id] = RunChannel()
            # Keep the dict from growing without bound across a long demo.
            if len(CHANNELS) > MAX_CHANNELS:
                for stale in list(CHANNELS)[: len(CHANNELS) - MAX_CHANNELS]:
                    if CHANNELS[stale].closed:
                        CHANNELS.pop(stale, None)
        return CHANNELS[run_id]


# ---------------------------------------------------------------- lifecycle

@app.on_event("startup")
def _startup() -> None:
    store.init()


# ---------------------------------------------------------------- runs

@app.post("/api/runs")
def create_run(request: RunRequest) -> dict[str, Any]:
    """Start a run. Returns immediately; watch /stream for progress."""
    prospect = request.prospect
    if request.case_id and not prospect.name.strip():
        seeded = fixtures.prospect_for(request.case_id)
        if seeded is not None:
            prospect = seeded

    # Mint the id here so the channel exists before the worker emits anything.
    run_id = pipeline.new_run_id()
    channel = _channel(run_id)

    def worker() -> None:
        try:
            pipeline.run_pipeline(
                prospect,
                emit=channel.publish,
                source_mode=request.source_mode,
                case_id=request.case_id,
                run_id=run_id,
            )
        except Exception as exc:  # the pipeline handles its own errors; this is
            # the belt-and-braces case so a stream never hangs open forever.
            channel.publish("error", {"detail": f"{type(exc).__name__}: {exc}"})

    threading.Thread(target=worker, daemon=True).start()
    return {"run_id": run_id, "stream": f"/api/runs/{run_id}/stream"}


@app.get("/api/runs/{run_id}/stream")
def stream_run(run_id: str) -> StreamingResponse:
    channel = _channel(run_id)

    def events() -> Iterator[str]:
        backlog, sub = channel.subscribe()
        try:
            for event in backlog:
                yield f"data: {json.dumps(event)}\n\n"
            if channel.closed:
                yield "data: {\"kind\": \"eof\", \"payload\": {}}\n\n"
                return
            while True:
                try:
                    event = sub.get(timeout=20)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(event)}\n\n"
                if event["kind"] in ("done", "error"):
                    yield "data: {\"kind\": \"eof\", \"payload\": {}}\n\n"
                    return
        finally:
            channel.unsubscribe(sub)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs")
def list_runs(
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=200, le=500),
) -> dict[str, Any]:
    return {
        "runs": store.list_runs(limit=limit, status=status, query=q),
        "stats": store.stats(),
    }


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="no such run")
    return run.model_dump()


@app.post("/api/runs/{run_id}/review")
def review_run(run_id: str, patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Record the human decision. Nothing in this system sends mail -- an
    approval marks the draft as cleared for the rep's own sending tool."""
    allowed = {"state", "subject", "body", "note", "reviewer"}
    clean = {k: v for k, v in patch.items() if k in allowed}
    if clean.get("state") not in (None, "pending", "approved", "edited", "rejected"):
        raise HTTPException(status_code=400, detail="invalid review state")
    clean["decided_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    run = store.set_review(run_id, clean)
    if run is None:
        raise HTTPException(status_code=404, detail="no such run")
    return run.model_dump()


@app.delete("/api/runs")
def clear_runs() -> dict[str, Any]:
    return {"deleted": store.delete_all()}


# ---------------------------------------------------------------- meta

@app.get("/api/test-cases")
def test_cases() -> dict[str, Any]:
    return {"cases": fixtures.TEST_CASES}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return {
        "seller": config.SELLER,
        "policy": {
            "max_age_days": config.SIGNAL_MAX_AGE_DAYS,
            "fresh_days": config.SIGNAL_FRESH_DAYS,
            "recent_days": config.SIGNAL_RECENT_DAYS,
            "min_hook_score": config.MIN_HOOK_SCORE,
            "min_person_hook_score": config.MIN_PERSON_HOOK_SCORE,
            "max_draft_words": config.MAX_DRAFT_WORDS,
            "repair_attempts": config.DRAFT_REPAIR_ATTEMPTS,
        },
        "source_mode": config.SOURCE_MODE,
        "models": config.GEMINI_MODELS,
        "stages": [{"key": k, "title": t} for k, t in pipeline.STAGES],
        "role_weights": scoring.ROLE_WEIGHTS,
        "sensitive_categories": sorted(guardrails.SENSITIVE_PATTERNS),
    }


@app.get("/api/health")
def health(deep: bool = Query(default=False)) -> dict[str, Any]:
    out: dict[str, Any] = {
        "api_key_present": bool(config.GEMINI_API_KEY),
        "llm": llm.stats(),
        "source_mode": config.SOURCE_MODE,
    }
    if deep:
        out["connectors"] = sources.health()
        out["model"] = llm.health()
    return out


# ---------------------------------------------------------------- static

@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.FRONTEND_DIR / "index.html")


# The frontend is four scripts, one stylesheet and two self-hosted fonts. They
# are listed rather than served through a directory mount so that the only
# things reachable under / are the ones the page actually asks for.
_STATIC: dict[str, str] = {
    "app.js": "application/javascript",
    "how.js": "application/javascript",
    "uml.js": "application/javascript",
    "styles.css": "text/css",
}


@app.get("/{name}.{ext}")
def static_file(name: str, ext: str) -> FileResponse:
    key = f"{name}.{ext}"
    media = _STATIC.get(key)
    if media is None:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(config.FRONTEND_DIR / key, media_type=media)


@app.get("/fonts/{name}")
def font_file(name: str) -> FileResponse:
    """Geist, copied into the repo rather than linked.

    The no-CDN rule exists so a graded live demo cannot be broken by a third
    party being slow, and that applies to a typeface as much as to a script.
    """
    path = (config.FRONTEND_DIR / "fonts" / name).resolve()
    if path.suffix != ".woff2" or not path.is_file()             or (config.FRONTEND_DIR / "fonts").resolve() not in path.parents:
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="font/woff2")
