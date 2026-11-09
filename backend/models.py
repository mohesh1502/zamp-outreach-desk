"""Shared data shapes for the pipeline, the store and the API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- input

class Prospect(BaseModel):
    name: str
    company: str
    domain: str = ""
    role: str = ""
    notes: str = ""          # anything the rep already knows
    linkedin: str = ""


class RunRequest(BaseModel):
    prospect: Prospect
    source_mode: Optional[Literal["live", "replay", "auto"]] = None
    case_id: Optional[str] = None       # set when launched from the test library


# ---------------------------------------------------------------- evidence

# Topic only. Sensitivity is deliberately NOT a kind: if a layoff story were
# typed "sensitive" it would score near zero on actionability and role fit, and
# the guardrail would look effective while actually having changed nothing. A
# crisis story must be allowed to score on its merits so that the veto is
# visibly the thing that removes it.
SignalKind = Literal[
    "funding", "hiring", "leadership", "product", "expansion",
    "regulatory", "partnership", "earnings", "other",
]

Level = Literal["person", "company"]


class Evidence(BaseModel):
    """One retrieved document. Never invented by the model."""
    id: str
    title: str
    url: str
    publisher: str = ""
    published_at: Optional[str] = None   # ISO date
    age_days: Optional[int] = None
    snippet: str = ""
    connector: str = ""                  # which source fetched it
    query: str = ""                      # the query that surfaced it


class ScoreBreakdown(BaseModel):
    recency: int = 0
    role_relevance: int = 0
    specificity: int = 0
    source_quality: int = 0
    actionability: int = 0
    total: int = 0
    notes: list[str] = Field(default_factory=list)


class Signal(BaseModel):
    """An interpreted claim backed by one or more pieces of evidence."""
    id: str
    kind: SignalKind = "other"
    level: Level = "company"
    claim: str                       # the one factual sentence we would reference
    why_it_matters: str = ""         # tied to this person's role
    evidence_ids: list[str] = Field(default_factory=list)
    sensitive: bool = False
    sensitive_reason: str = ""
    stale: bool = False
    vetoed: bool = False
    veto_reason: str = ""
    score: ScoreBreakdown = Field(default_factory=ScoreBreakdown)


class Draft(BaseModel):
    subject: str = ""
    body: str = ""
    opener_claim: str = ""           # the sentence that carries the hook
    citations: list[str] = Field(default_factory=list)   # evidence ids
    word_count: int = 0


class ClaimCheck(BaseModel):
    claim: str
    supported: bool
    evidence_id: str = ""
    note: str = ""


# ---------------------------------------------------------------- run

RunStatus = Literal[
    "running",
    "ready_for_review",
    "fallback_company_signal",
    "needs_manual_research",
    "blocked_sensitive",
    "flagged_job_change",
    "needs_disambiguation",
    "error",
]

StageState = Literal["pending", "active", "done", "warn", "blocked", "skipped", "error"]


class StageLog(BaseModel):
    key: str
    title: str
    state: StageState = "pending"
    summary: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    ms: Optional[int] = None


class Run(BaseModel):
    id: str
    created_at: str
    prospect: Prospect
    case_id: Optional[str] = None
    source_mode: str = "auto"
    status: RunStatus = "running"
    headline: str = ""               # one-line human summary of the outcome
    stages: list[StageLog] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    chosen_signal_id: Optional[str] = None
    selection_rationale: str = ""
    draft: Optional[Draft] = None
    claim_checks: list[ClaimCheck] = Field(default_factory=list)
    confidence: int = 0
    review: dict[str, Any] = Field(default_factory=dict)   # approve/edit state
    error: str = ""
    ms: Optional[int] = None
