"""Signal scoring.

Every component here is deterministic. The LLM turns evidence into a typed
claim; it does not get a vote on which claim wins. Two reasons that matters:

  1. The same evidence always produces the same hook, so a live demo is
     reproducible and a regression is visible.
  2. "Why did it pick this one?" has an arithmetic answer the rep can audit,
     not a paragraph of model prose.

100 points, five components:
  recency         0-30   how fresh the source is
  role_relevance  0-25   does this kind of news matter to *this* job title
  specificity     0-20   is there a concrete number or named entity to quote
  source_quality  0-15   publisher tier
  actionability   0-10   does it imply a problem worth a conversation

Two hard vetoes sit outside the arithmetic -- sensitive and stale. A vetoed
signal keeps its score so the UI can show what was rejected and what it would
otherwise have been worth.
"""
from __future__ import annotations

import re

from . import config
from .models import Evidence, ScoreBreakdown, Signal

# ---------------------------------------------------------------- role mapping

# Which kinds of news a given function actually cares about. Values are the
# role_relevance points (max 25). Tuned so that the same company signal ranks
# differently for a CFO than for a VP Engineering -- that difference is the
# whole point of the component.
ROLE_WEIGHTS: dict[str, dict[str, int]] = {
    "finance": {
        "funding": 25, "earnings": 23, "regulatory": 21, "expansion": 19,
        "leadership": 16, "hiring": 15, "partnership": 13, "product": 10,
        "other": 5,
    },
    "operations": {
        "expansion": 25, "hiring": 23, "funding": 19, "partnership": 18,
        "product": 16, "regulatory": 16, "earnings": 13, "leadership": 13,
        "other": 5,
    },
    "engineering": {
        "product": 25, "hiring": 22, "funding": 17, "expansion": 16,
        "partnership": 15, "leadership": 12, "regulatory": 10, "earnings": 8,
        "other": 5,
    },
    "sales": {
        "expansion": 25, "funding": 23, "partnership": 21, "product": 18,
        "hiring": 17, "leadership": 14, "earnings": 12, "regulatory": 9,
        "other": 5,
    },
    "executive": {
        "funding": 25, "expansion": 22, "regulatory": 20, "earnings": 19,
        "leadership": 18, "partnership": 16, "hiring": 14, "product": 13,
        "other": 5,
    },
    "default": {
        "funding": 21, "expansion": 19, "hiring": 17, "product": 16,
        "partnership": 14, "leadership": 14, "earnings": 13, "regulatory": 12,
        "other": 5,
    },
}

ROLE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("finance", ("cfo", "chief financial", "controller", "finance", "accounting",
                 "accounts payable", "ap ", "treasury", "fp&a", "audit", "tax")),
    ("engineering", ("cto", "cio", "chief technology", "chief information",
                     "engineer", "engineering", "developer", "devops",
                     "platform", "architect", "technical", "data", "security")),
    ("sales", ("cro", "chief revenue", "sales", "revenue", "account executive",
               "sdr", "bdr", "gtm", "growth", "marketing", "demand")),
    ("operations", ("coo", "chief operating", "operations", "operating", "ops",
                    "procurement", "supply", "vendor", "logistics", "process",
                    "program")),
    ("executive", ("ceo", "chief executive", "founder", "co-founder", "cofounder",
                   "president", "managing director", "chairman", "owner",
                   "partner")),
]


def role_family(role: str) -> str:
    """Bucket a free-text job title into one of the weight tables."""
    text = (role or "").lower()
    if not text:
        return "default"
    # Executive is checked last in ROLE_KEYWORDS order but should win for a
    # plain "CEO"; functional titles like "VP Finance" are more specific, so
    # scan functional families first and fall through to executive.
    for family, keywords in ROLE_KEYWORDS:
        if any(kw in text for kw in keywords):
            return family
    return "default"


# ---------------------------------------------------------------- components

ACTIONABILITY: dict[str, int] = {
    "funding": 10,   # fresh budget, new reporting pressure
    "expansion": 9,  # new entities, new currencies, new compliance surface
    "hiring": 9,     # a team being built implies a process not yet built
    "regulatory": 8,
    "earnings": 7,
    "partnership": 6,
    "leadership": 6,  # a new exec rebuilds their stack
    "product": 5,
    "other": 2,
}

_NUMBERISH = re.compile(
    r"(\$|₹|€|£)\s?\d|"           # currency amounts
    r"\b\d{1,3}(,\d{3})+\b|"      # 1,200,000
    r"\b\d+(\.\d+)?\s?(%|percent|bn|billion|mn|million|crore|lakh|k\b)|"
    r"\bq[1-4]\b|\bfy\d{2,4}\b|\b(19|20)\d{2}\b",
    re.I,
)
_PROPER_NOUN = re.compile(r"\b[A-Z][a-zA-Z]{2,}(?:\s+[A-Z][a-zA-Z]{2,})*\b")


def score_recency(age_days: int | None) -> tuple[int, str]:
    if age_days is None:
        # Undated sources are usable but can never win on freshness.
        return 8, "undated source, capped at 8/30"
    if age_days <= config.SIGNAL_FRESH_DAYS:
        return 30, f"fresh ({age_days}d)"
    if age_days <= config.SIGNAL_RECENT_DAYS:
        return 22, f"recent ({age_days}d)"
    if age_days <= config.SIGNAL_MAX_AGE_DAYS:
        return 12, f"ageing ({age_days}d)"
    return 0, f"stale ({age_days}d) — past the {config.SIGNAL_MAX_AGE_DAYS}d limit"


def score_role_relevance(kind: str, role: str, level: str) -> tuple[int, str]:
    family = role_family(role)
    table = ROLE_WEIGHTS.get(family, ROLE_WEIGHTS["default"])
    base = table.get(kind, table["other"])
    note = f"{kind} news scores {base}/25 for a {family} role"
    if level == "person":
        # Something about them personally beats something about their employer.
        bonus = min(25, base + 5) - base
        if bonus:
            note += f" (+{bonus} person-level)"
        base = min(25, base + 5)
    return base, note


def score_specificity(claim: str) -> tuple[int, str]:
    """Can the rep quote something concrete, or is it vague PR filler?"""
    points = 0
    notes: list[str] = []

    if _NUMBERISH.search(claim):
        points += 10
        notes.append("has a figure or date")
    proper = {m.group(0) for m in _PROPER_NOUN.finditer(claim)}
    if len(proper) >= 2:
        points += 6
        notes.append(f"{len(proper)} named entities")
    elif proper:
        points += 3
        notes.append("1 named entity")

    words = len(claim.split())
    if 8 <= words <= 40:
        points += 4
        notes.append("quotable length")
    elif words < 8:
        notes.append("too short to carry an opener")

    return min(20, points), "; ".join(notes) or "no concrete detail"


def score_actionability(kind: str) -> tuple[int, str]:
    pts = ACTIONABILITY.get(kind, 2)
    return pts, f"{kind} implies {pts}/10 of a reason to talk now"


# ---------------------------------------------------------------- aggregate

def score_signal(
    signal: Signal, evidence_by_id: dict[str, Evidence], role: str
) -> ScoreBreakdown:
    """Fill in and return the breakdown for one signal."""
    backing = [evidence_by_id[eid] for eid in signal.evidence_ids if eid in evidence_by_id]
    primary = backing[0] if backing else None

    ages = [e.age_days for e in backing if e.age_days is not None]
    age = min(ages) if ages else None

    recency, recency_note = score_recency(age)
    relevance, relevance_note = score_role_relevance(signal.kind, role, signal.level)
    specificity, specificity_note = score_specificity(signal.claim)
    actionability, actionability_note = score_actionability(signal.kind)

    if primary is not None:
        from . import sources  # local import keeps the module import-light

        quality = sources.source_quality(primary.url, primary.publisher)
        quality_note = f"{primary.publisher or 'unknown publisher'} → {quality}/15"
    else:
        quality, quality_note = 5, "no source attached → 5/15"

    breakdown = ScoreBreakdown(
        recency=recency,
        role_relevance=relevance,
        specificity=specificity,
        source_quality=quality,
        actionability=actionability,
        total=recency + relevance + specificity + quality + actionability,
        notes=[
            f"recency {recency}/30 — {recency_note}",
            f"role fit {relevance}/25 — {relevance_note}",
            f"specificity {specificity}/20 — {specificity_note}",
            f"source {quality}/15 — {quality_note}",
            f"actionability {actionability}/10 — {actionability_note}",
        ],
    )
    return breakdown


def threshold_for(level: str) -> int:
    """Person-level claims are held higher: misattributing something to a named
    individual is a worse failure than being generic about their employer."""
    return config.MIN_PERSON_HOOK_SCORE if level == "person" else config.MIN_HOOK_SCORE


def rank(signals: list[Signal]) -> list[Signal]:
    """Highest score first; vetoed signals always sort below live ones."""
    return sorted(signals, key=lambda s: (not s.vetoed, s.score.total), reverse=True)


def select(signals: list[Signal]) -> tuple[Signal | None, str, list[Signal]]:
    """Pick the hook.

    Returns (winner, rationale, ranked). Winner is None when nothing clears its
    threshold, which is the "needs manual research" outcome -- the process is
    expected to decline rather than personalise on something weak.
    """
    ranked = rank(signals)
    live = [s for s in ranked if not s.vetoed]

    if not live:
        blocked = [s for s in ranked if s.vetoed]
        if blocked:
            reasons = ", ".join(sorted({s.veto_reason for s in blocked if s.veto_reason}))
            return None, f"all {len(blocked)} candidate signals were vetoed ({reasons})", ranked
        return None, "no usable signals were retrieved", ranked

    winner = live[0]
    threshold = threshold_for(winner.level)
    if winner.score.total < threshold:
        return (
            None,
            (
                f"best candidate scored {winner.score.total}/100, below the "
                f"{threshold} floor for a {winner.level}-level hook — declining "
                "to personalise on a weak signal"
            ),
            ranked,
        )

    parts = [
        f"picked {winner.kind} ({winner.level}-level) at {winner.score.total}/100"
    ]
    if len(live) > 1:
        runner_up = live[1]
        margin = winner.score.total - runner_up.score.total
        parts.append(
            f"beat {runner_up.kind} at {runner_up.score.total}/100 by {margin} pts"
        )
        # Name the component that actually decided it.
        deltas = {
            "recency": winner.score.recency - runner_up.score.recency,
            "role fit": winner.score.role_relevance - runner_up.score.role_relevance,
            "specificity": winner.score.specificity - runner_up.score.specificity,
            "source quality": winner.score.source_quality - runner_up.score.source_quality,
            "actionability": winner.score.actionability - runner_up.score.actionability,
        }
        decider = max(deltas, key=lambda k: deltas[k])
        if deltas[decider] > 0:
            parts.append(f"decided on {decider} (+{deltas[decider]})")
    vetoed = [s for s in ranked if s.vetoed]
    if vetoed:
        parts.append(f"{len(vetoed)} signal(s) vetoed before ranking")

    return winner, "; ".join(parts), ranked
