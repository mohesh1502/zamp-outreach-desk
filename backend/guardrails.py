"""Safety, recency and identity screens.

This is the part of the process that decides what the system is *not* allowed to
say. Three independent screens, run before any drafting:

  1. Sensitivity  -- a regex pre-screen for crisis language, then an LLM pass on
                     whatever survives. The regex is cheap and catches the
                     obvious; the LLM catches framing the keywords miss ("a
                     wrongful-death suit" has no keyword overlap with "lawsuit").
                     A signal is sensitive if *either* screen says so -- the two
                     are a union, not a vote, because a false positive costs us
                     one hook and a false negative costs the client a customer.
  2. Recency      -- anything older than SIGNAL_MAX_AGE_DAYS cannot be a hook.
                     Referencing a two-year-old funding round reads worse than
                     sending nothing.
  3. Identity     -- is this person still in this seat, and are we even looking
                     at the right person? Both are run over retrieved evidence.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from . import config, llm
from .models import Evidence

# ---------------------------------------------------------------- sensitivity

# Grouped so the UI can name the category that fired, not just "sensitive".
SENSITIVE_PATTERNS: dict[str, list[str]] = {
    "workforce_reduction": [
        r"\blay[\s-]?offs?\b", r"\blaid off\b", r"\bjob cuts?\b", r"\bsacks?\b",
        r"\bretrench", r"\bdownsiz", r"\bheadcount reduction\b", r"\bfires? \d+",
        r"\bhiring freeze\b", r"\bfurlough",
    ],
    "bereavement": [
        r"\bobituary\b", r"\bpasses? away\b", r"\bpassed away\b", r"\bdies?\b",
        r"\bdeath\b", r"\bmourn", r"\bcondolence", r"\btragic", r"\bfatal\b",
    ],
    "legal_action": [
        r"\blawsuits?\b", r"\bsued\b", r"\bsues\b", r"\blitigation\b",
        r"\bsubpoena", r"\bindict", r"\barrest", r"\bfraud\b", r"\bprobe\b",
        r"\binvestigation\b", r"\braids?\b", r"\bpenalt", r"\bfined\b",
        r"\bclass action\b", r"\bsettlement\b", r"\bmisconduct\b",
    ],
    "security_incident": [
        r"\bdata breach\b", r"\bbreached\b", r"\bhacked\b", r"\bransomware\b",
        r"\bleaked?\b", r"\bcyber ?attack\b", r"\bexposed records\b",
    ],
    "financial_distress": [
        r"\bbankrupt", r"\binsolven", r"\bwinding up\b", r"\bshuts? down\b",
        r"\bshutting down\b", r"\bdefaults?\b", r"\bwrite[\s-]?off\b",
        r"\bdistress", r"\bwind[\s-]?down\b",
    ],
    "reputational": [
        r"\bscandal\b", r"\bharassment\b", r"\bdiscriminat", r"\bbacklash\b",
        r"\bboycott\b", r"\bcontrovers", r"\bresigns? amid\b", r"\bousted\b",
        r"\bstrike\b", r"\bprotest",
    ],
}

_COMPILED = {
    cat: [re.compile(p, re.I) for p in pats] for cat, pats in SENSITIVE_PATTERNS.items()
}


def regex_sensitivity(text: str) -> tuple[bool, str]:
    """Fast pre-screen. Returns (hit, category)."""
    for category, patterns in _COMPILED.items():
        for pattern in patterns:
            if pattern.search(text or ""):
                return True, category
    return False, ""


_SENSITIVITY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "sensitive": {"type": "boolean"},
                    "category": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "sensitive", "category", "reason"],
            },
        }
    },
    "required": ["verdicts"],
}

_SENSITIVITY_SYSTEM = (
    "You screen news items before a sales rep is allowed to reference them in a "
    "cold outreach email. You are the last line of defence against a tone-deaf "
    "message.\n\n"
    "Mark an item sensitive if referencing it in a sales email would be callous, "
    "opportunistic or embarrassing. That includes: layoffs or job cuts, a death "
    "or bereavement, lawsuits, regulatory probes, fraud or arrests, data "
    "breaches, bankruptcy or distress, scandals, harassment, strikes, or any "
    "crisis the company is publicly suffering through.\n\n"
    "Do NOT mark ordinary business news sensitive just because it is negative in "
    "tone: missing an earnings estimate, a competitor launching something, a "
    "share price dip, or routine regulatory filings are all fair game.\n\n"
    "When genuinely unsure, mark it sensitive. A missed hook is cheap; an "
    "insensitive email is not."
)


def llm_sensitivity(items: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Classify a batch of candidate items. Returns {id: {category, reason}}.

    Fails open to {} -- the regex screen has already run, and an LLM outage must
    not silently disable the whole guardrail. The caller records the degradation.
    """
    if not items:
        return {}

    lines = [
        "Screen each item. Reply for every id.",
        "",
    ]
    for item in items:
        lines.append(f"id: {item['id']}")
        lines.append(f"headline: {item['title']}")
        if item.get("snippet"):
            lines.append(f"context: {item['snippet'][:300]}")
        lines.append("")

    try:
        data = llm.generate_json(
            "\n".join(lines),
            _SENSITIVITY_SCHEMA,
            system=_SENSITIVITY_SYSTEM,
            temperature=0.0,
        )
    except llm.LLMError:
        return {}

    out: dict[str, dict[str, str]] = {}
    for verdict in data.get("verdicts", []):
        if verdict.get("sensitive"):
            out[str(verdict.get("id"))] = {
                "category": str(verdict.get("category") or "unspecified"),
                "reason": str(verdict.get("reason") or ""),
            }
    return out


# ---------------------------------------------------------------- recency

def recency_verdict(age_days: Optional[int]) -> tuple[str, str]:
    """Returns (tier, note). Tier is fresh | recent | ageing | stale | undated."""
    if age_days is None:
        return "undated", "no publication date on this source"
    if age_days <= config.SIGNAL_FRESH_DAYS:
        return "fresh", f"{age_days}d old"
    if age_days <= config.SIGNAL_RECENT_DAYS:
        return "recent", f"{age_days}d old"
    if age_days <= config.SIGNAL_MAX_AGE_DAYS:
        return "ageing", f"{age_days}d old, near the {config.SIGNAL_MAX_AGE_DAYS}d limit"
    return "stale", f"{age_days}d old, past the {config.SIGNAL_MAX_AGE_DAYS}d limit"


# ---------------------------------------------------------------- identity

_IDENTITY_SCHEMA = {
    "type": "object",
    "properties": {
        "employment": {
            "type": "string",
            "enum": ["confirmed", "unconfirmed", "changed_role", "left_company"],
        },
        "confidence": {"type": "integer"},
        "stated_role": {"type": "string"},
        "evidence_id": {"type": "string"},
        "name_collision": {"type": "boolean"},
        "collision_detail": {"type": "string"},
        "reasoning": {"type": "string"},
    },
    "required": [
        "employment", "confidence", "stated_role", "evidence_id",
        "name_collision", "collision_detail", "reasoning",
    ],
}

_IDENTITY_SYSTEM = (
    "You verify that a sales prospect is who the rep thinks they are, using only "
    "the retrieved sources given to you. You never use outside knowledge, and "
    "you never guess.\n\n"
    "employment:\n"
    "  confirmed    -- a source places this person at this company now\n"
    "  left_company -- a source ties THIS person to THIS company and says they "
    "departed it\n"
    "  changed_role -- still there, but a source gives a different title\n"
    "  unconfirmed  -- the sources simply do not say. This is common and fine, "
    "and is the right answer far more often than any other.\n\n"
    "CRITICAL -- namesakes are not departures. Common names recur. A source "
    "saying 'Jane Smith joins Acme as partner' tells you nothing about the Jane "
    "Smith at the company you were asked about unless that source also connects "
    "her to that company. If no source ever mentions the target company "
    "alongside this person, the answer is 'unconfirmed', never 'left_company'. "
    "Only choose left_company when a source explicitly links the person to the "
    "target company AND reports them leaving it.\n\n"
    "name_collision: true only when the sources clearly describe two or more "
    "different people sharing this name, such that a message could be addressed "
    "to the wrong one. A single unrelated namesake with an obviously different "
    "profession is still a collision if it could mislead the rep.\n\n"
    "confidence is 0-100 for the employment verdict. evidence_id must be one of "
    "the ids provided, or empty string if nothing supports the verdict."
)


def verify_identity(
    name: str, company: str, role: str, evidence: list[Evidence]
) -> dict[str, Any]:
    """Employment + name-collision check over person-level evidence."""
    fallback = {
        "employment": "unconfirmed",
        "confidence": 0,
        "stated_role": "",
        "evidence_id": "",
        "name_collision": False,
        "collision_detail": "",
        "reasoning": "identity screen unavailable",
        "degraded": True,
    }
    if not evidence:
        fallback["reasoning"] = "no person-level sources were retrieved"
        fallback["degraded"] = False
        return fallback

    lines = [
        f"Prospect as supplied by the rep: {name}",
        f"Company as supplied: {company}",
        f"Role as supplied: {role or '(not given)'}",
        "",
        "Retrieved sources:",
    ]
    for ev in evidence[:14]:
        lines.append(f"- id: {ev.id}")
        lines.append(f"  title: {ev.title}")
        if ev.publisher:
            lines.append(f"  publisher: {ev.publisher}")
        if ev.published_at:
            lines.append(f"  date: {ev.published_at}")
        if ev.snippet:
            lines.append(f"  snippet: {ev.snippet[:260]}")

    try:
        data = llm.generate_json(
            "\n".join(lines), _IDENTITY_SCHEMA, system=_IDENTITY_SYSTEM, temperature=0.0
        )
    except llm.LLMError as exc:
        fallback["reasoning"] = f"identity screen failed: {exc}"
        return fallback

    data["degraded"] = False
    data["confidence"] = max(0, min(100, int(data.get("confidence") or 0)))
    return data
