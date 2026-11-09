"""Run persistence.

SQLite with the run serialised as JSON. The dashboard needs to filter and sort
on a handful of fields, so those are promoted to real columns and everything
else lives in the blob -- the shape of a Run is still changing, and this avoids
a migration every time a stage gains a field.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Optional

from . import config
from .models import Run

_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    prospect_name TEXT NOT NULL,
    company       TEXT NOT NULL,
    role          TEXT,
    case_id       TEXT,
    status        TEXT NOT NULL,
    headline      TEXT,
    confidence    INTEGER DEFAULT 0,
    source_mode   TEXT,
    ms            INTEGER,
    review_state  TEXT DEFAULT 'pending',
    payload       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_status  ON runs(status);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    # A hosted instance can point DB_PATH at a mounted disk, and the mount is
    # empty on first boot, so the directory is made rather than assumed.
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, _connect() as conn:
        conn.executescript(_SCHEMA)


def save(run: Run) -> None:
    payload = run.model_dump_json()
    with _LOCK, _connect() as conn:
        conn.execute(
            """
            INSERT INTO runs (id, created_at, prospect_name, company, role, case_id,
                              status, headline, confidence, source_mode, ms,
                              review_state, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                headline=excluded.headline,
                confidence=excluded.confidence,
                ms=excluded.ms,
                review_state=excluded.review_state,
                payload=excluded.payload
            """,
            (
                run.id,
                run.created_at,
                run.prospect.name,
                run.prospect.company,
                run.prospect.role,
                run.case_id,
                run.status,
                run.headline,
                run.confidence,
                run.source_mode,
                run.ms,
                str(run.review.get("state", "pending")),
                payload,
            ),
        )


def get(run_id: str) -> Optional[Run]:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
    return Run.model_validate_json(row["payload"]) if row else None


def list_runs(
    *, limit: int = 200, status: Optional[str] = None, query: Optional[str] = None
) -> list[dict[str, Any]]:
    """Summary rows for the dashboard table -- deliberately not full payloads."""
    sql = [
        "SELECT id, created_at, prospect_name, company, role, case_id, status,",
        "       headline, confidence, source_mode, ms, review_state",
        "FROM runs WHERE 1=1",
    ]
    params: list[Any] = []
    if status and status != "all":
        sql.append("AND status = ?")
        params.append(status)
    if query:
        sql.append("AND (prospect_name LIKE ? OR company LIKE ? OR case_id LIKE ?)")
        needle = f"%{query}%"
        params += [needle, needle, needle]
    sql.append("ORDER BY created_at DESC LIMIT ?")
    params.append(limit)

    with _LOCK, _connect() as conn:
        rows = conn.execute(" ".join(sql), params).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict[str, Any]:
    """Counters for the dashboard header."""
    with _LOCK, _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        by_status = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM runs GROUP BY status"
            ).fetchall()
        }
        approved = conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE review_state = 'approved'"
        ).fetchone()["n"]
        avg_conf = conn.execute(
            "SELECT AVG(confidence) AS a FROM runs WHERE status != 'running'"
        ).fetchone()["a"]
        avg_ms = conn.execute(
            "SELECT AVG(ms) AS a FROM runs WHERE ms IS NOT NULL"
        ).fetchone()["a"]

    return {
        "total": total,
        "by_status": by_status,
        "approved": approved,
        "avg_confidence": round(avg_conf or 0),
        "avg_ms": round(avg_ms or 0),
    }


def set_review(run_id: str, patch: dict[str, Any]) -> Optional[Run]:
    """Record an approve / edit / reject decision against a run."""
    run = get(run_id)
    if run is None:
        return None

    run.review.update(patch)
    if "body" in patch and run.draft is not None:
        run.draft.body = patch["body"]
        run.draft.word_count = len(patch["body"].split())
    if "subject" in patch and run.draft is not None:
        run.draft.subject = patch["subject"]

    save(run)
    return run


def delete_all() -> int:
    with _LOCK, _connect() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        conn.execute("DELETE FROM runs")
    return n
