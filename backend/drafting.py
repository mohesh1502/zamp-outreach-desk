"""Interpretation, drafting and claim verification.

The three LLM-shaped jobs in the pipeline, kept together because they share the
same hard rule: the model may only reference evidence that was actually
retrieved, identified by the ids we hand it.

  interpret()     evidence -> typed, deduplicated candidate signals
  write_draft()   the winning signal -> a short email
  verify_draft()  the email -> a per-claim supported/unsupported ledger

verify_draft is the step that earns the "human in the loop" claim. A draft that
asserts something no retrieved source supports is sent back for one repair pass
with the offending sentences named; if it still fails, the run is marked for
manual review rather than quietly shipping an unverifiable sentence.
"""
from __future__ import annotations

import re
from typing import Any

from . import config, llm
from .models import ClaimCheck, Draft, Evidence, Signal

# ---------------------------------------------------------------- interpret

_INTERPRET_SCHEMA = {
    "type": "object",
    "properties": {
        "signals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "funding", "hiring", "leadership", "product",
                            "expansion", "regulatory", "partnership",
                            "earnings", "other",
                        ],
                    },
                    "level": {"type": "string", "enum": ["person", "company"]},
                    "claim": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["kind", "level", "claim", "why_it_matters", "evidence_ids"],
            },
        }
    },
    "required": ["signals"],
}

_INTERPRET_SYSTEM = (
    "You convert retrieved news items into candidate outreach hooks for a B2B "
    "sales rep. You are an analyst, not a writer.\n\n"
    "Rules:\n"
    "1. Every signal must cite at least one evidence id from the list provided. "
    "Never invent an id, a fact, a figure or a date.\n"
    "2. 'claim' is ONE factual sentence, stated plainly, containing only what the "
    "source actually says. Include the concrete figure or name if the source "
    "gives one. No adjectives, no sales language, no speculation.\n"
    "3. 'why_it_matters' is one sentence tying the claim to the prospect's job "
    "specifically -- what new problem or priority this creates for someone with "
    "that title. Not why it matters to the company in general.\n"
    "4. 'level' is 'person' only when the claim is about the named individual. "
    "News about their employer is 'company'.\n"
    "5. Merge items reporting the same underlying event into one signal with "
    "several evidence ids. Do not emit near-duplicates.\n"
    "6. Classify by TOPIC, never by how negative it is. Layoffs and headcount "
    "cuts are 'hiring'. Lawsuits, probes and penalties are 'regulatory'. "
    "Report these items like any other -- a separate guardrail stage decides "
    "what is safe to reference, and it can only veto what you surface. Never "
    "silently drop a story because it is bad news.\n"
    "7. Skip items that are about a different company, are pure product "
    "marketing with no event, or carry no usable fact.\n\n"
    "Return 3-8 signals when the evidence supports it. Fewer is correct when it "
    "does not -- returning an empty list is a valid and useful answer."
)


def interpret(
    *, name: str, company: str, role: str, evidence: list[Evidence]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Turn raw evidence into candidate signals.

    Returns (signals, diagnostics). The diagnostics matter: when this step comes
    back empty there are two very different causes -- the model genuinely found
    nothing citable, or it hiccuped -- and the stage detail needs to say which.

    Retries once on an empty result when evidence exists. Observed in testing:
    roughly one call in four over 50 real news items returned an empty array,
    which turned a healthy happy path into a false "needs manual research". A
    refusal is the right answer sometimes, but it has to be earned.
    """
    diag: dict[str, Any] = {
        "evidence_in": len(evidence),
        "attempts": 0,
        "raw_signals": 0,
        "dropped_no_valid_id": 0,
        "dropped_no_claim": 0,
        "retried": False,
    }
    if not evidence:
        return [], diag

    header = [
        f"Prospect: {name}",
        f"Title: {role or '(unknown)'}",
        f"Company: {company}",
        "",
        f"What we sell: {config.SELLER['what_we_do']}",
        "",
        "Retrieved evidence:",
    ]
    for ev in evidence:
        header.append(f"- id: {ev.id}")
        header.append(f"  title: {ev.title}")
        header.append(f"  publisher: {ev.publisher or 'unknown'}")
        header.append(f"  date: {ev.published_at or 'undated'}")
        if ev.snippet:
            header.append(f"  snippet: {ev.snippet[:300]}")
    prompt = "\n".join(header)

    valid_ids = {ev.id for ev in evidence}

    for attempt in range(2):
        diag["attempts"] = attempt + 1
        nudge = ""
        if attempt == 1:
            diag["retried"] = True
            nudge = (
                "\n\nYour previous response contained no usable signals. There "
                f"are {len(evidence)} real items above. Re-read them and return "
                "every one that carries a concrete, citable fact, copying the "
                "evidence ids EXACTLY as written. Returning an empty list is "
                "only correct if not one item contains a usable fact."
            )

        data = llm.generate_json(
            prompt + nudge,
            _INTERPRET_SCHEMA,
            system=_INTERPRET_SYSTEM,
            temperature=0.1 if attempt == 0 else 0.35,
        )

        raw_signals = data.get("signals") or []
        diag["raw_signals"] = len(raw_signals)
        diag["dropped_no_valid_id"] = 0
        diag["dropped_no_claim"] = 0

        out: list[dict[str, Any]] = []
        for raw in raw_signals:
            ids = [i for i in (raw.get("evidence_ids") or []) if i in valid_ids]
            if not ids:
                diag["dropped_no_valid_id"] += 1
                continue  # an uncitable signal is not a signal
            claim = (raw.get("claim") or "").strip()
            if not claim:
                diag["dropped_no_claim"] += 1
                continue
            out.append(
                {
                    "kind": raw.get("kind") or "other",
                    "level": raw.get("level") or "company",
                    "claim": claim,
                    "why_it_matters": (raw.get("why_it_matters") or "").strip(),
                    "evidence_ids": ids,
                }
            )

        diag["kept"] = len(out)
        if out:
            return out, diag

    return [], diag


# ---------------------------------------------------------------- draft

_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "opener_claim": {"type": "string"},
    },
    "required": ["subject", "body", "opener_claim"],
}


def _draft_system(fallback: bool) -> str:
    seller = config.SELLER
    base = (
        f"You write first-touch outreach emails for {seller['rep_name']}, "
        f"{seller['rep_title']} at {seller['company']}.\n\n"
        f"{seller['company']} in one line: {seller['one_liner']}.\n"
        f"Detail: {seller['what_we_do']}\n\n"
        "Structure. Exactly four blocks, each separated by a BLANK LINE:\n"
        "1. The hook. State the fact you were given, plainly, as something you "
        "noticed. One sentence.\n"
        "2. The bridge. The specific operational consequence that fact has for "
        "someone in their role. One or two sentences, 40 words maximum. This is "
        "the part that has to earn the reply.\n"
        "3. The ask. One low-friction question. Never 'a quick 15 minutes to "
        "pick your brain'.\n"
        f"4. The sign-off: the single word '{seller['rep_name'].split()[0]}' on "
        "its own line.\n\n"
        "The blank lines between blocks are mandatory. Returning one unbroken "
        "paragraph is a failed draft -- it reads as automated however good the "
        "hook is. Use a literal newline character twice between blocks.\n\n"
        "Hard rules:\n"
        f"- Under {config.MAX_DRAFT_WORDS} words in the body. Shorter is better.\n"
        "- No paragraph over 55 words.\n"
        "- State ONLY the fact in the hook you are given. Do not add figures, "
        "dates, customer names, round sizes, headcounts or anything else. If you "
        "want to say something you were not told, leave it out.\n"
        "- No flattery ('impressive', 'exciting', 'love what you're building'). "
        "No 'I hope this finds you well'. No 'I came across your profile'. No "
        "exclamation marks. No em-dashes.\n"
        "- Do not claim to have used their product, met them, or been referred.\n"
        "- Write like a competent person emailing a busy stranger: direct, "
        "specific, slightly informal. Contractions are fine.\n"
        "- subject: under 7 words, lower-case except proper nouns, no clickbait, "
        "no colons.\n"
        "- opener_claim: copy the single sentence from your body that carries the "
        "factual hook, verbatim.\n"
    )
    if fallback:
        base += (
            "\nThis is a COMPANY-LEVEL fallback: nothing was found about this "
            "person specifically. Do not imply personal knowledge of them or "
            "suggest they were personally involved in the event. Address them as "
            "someone whose job is affected by company news.\n"
        )
    return base


def write_draft(
    *,
    name: str,
    company: str,
    role: str,
    signal: Signal,
    evidence: list[Evidence],
    fallback: bool = False,
    repair_note: str = "",
) -> Draft:
    """Generate one draft from the winning signal."""
    cited = [ev for ev in evidence if ev.id in signal.evidence_ids]

    lines = [
        f"Prospect: {name}",
        f"Title: {role or '(unknown)'}",
        f"Company: {company}",
        "",
        "THE ONLY FACT YOU MAY STATE:",
        signal.claim,
        "",
        f"Why it matters to them: {signal.why_it_matters}",
        "",
        "Sources behind that fact (for your confidence, do not quote URLs):",
    ]
    for ev in cited:
        lines.append(f"- {ev.title} ({ev.publisher or 'unknown'}, {ev.published_at or 'undated'})")

    if repair_note:
        lines += [
            "",
            "YOUR PREVIOUS DRAFT WAS REJECTED. Unsupported statements found:",
            repair_note,
            "",
            "Rewrite it. Remove or rephrase every statement above so the body "
            "asserts nothing beyond the single permitted fact.",
        ]

    data = llm.generate_json(
        "\n".join(lines),
        _DRAFT_SCHEMA,
        system=_draft_system(fallback),
        temperature=0.5 if not repair_note else 0.2,
    )

    body = (data.get("body") or "").strip()
    return Draft(
        subject=(data.get("subject") or "").strip(),
        body=body,
        opener_claim=(data.get("opener_claim") or "").strip(),
        citations=list(signal.evidence_ids),
        word_count=len(body.split()),
    )


# ---------------------------------------------------------------- verify

_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "supported": {"type": "boolean"},
                    "evidence_id": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["claim", "supported", "evidence_id", "note"],
            },
        }
    },
    "required": ["claims"],
}

_VERIFY_SYSTEM = (
    "You audit a sales email against the sources it is allowed to rely on. You "
    "are looking for statements the sources do not support -- the email will be "
    "sent to a real person, and an invented detail is the worst outcome.\n\n"
    "Extract every CHECKABLE FACTUAL ASSERTION about the recipient, their "
    "company, or the world. For each one decide whether a provided source "
    "supports it, and name the source id.\n\n"
    "Checkable means a claim about reality: an event, a figure, a date, a name, "
    "a role, a relationship, a product capability.\n\n"
    "NOT checkable -- skip these entirely:\n"
    "- the sender's own description of what their company does or offers\n"
    "- questions, offers, and requests ('would it be useful if...', 'happy to "
    "share')\n"
    "- opinions and hypotheticals ('that usually means', 'I'd guess')\n"
    "- greetings, sign-offs, pleasantries\n\n"
    "Mark supported=false when no source states it, when the email states it "
    "more strongly or more precisely than the source does, or when it adds a "
    "figure or date the source does not contain. Partial support is not support."
)


def verify_draft(draft: Draft, evidence: list[Evidence]) -> list[ClaimCheck]:
    """Audit the draft. Fails closed: an LLM outage yields an explicit
    unverified marker rather than a clean bill of health."""
    allowed = [ev for ev in evidence if ev.id in draft.citations]
    if not allowed:
        allowed = evidence

    lines = ["EMAIL UNDER AUDIT:", f"Subject: {draft.subject}", "", draft.body, "", "SOURCES:"]
    for ev in allowed:
        lines.append(f"- id: {ev.id}")
        lines.append(f"  title: {ev.title}")
        lines.append(f"  publisher: {ev.publisher or 'unknown'}")
        lines.append(f"  date: {ev.published_at or 'undated'}")
        if ev.snippet:
            lines.append(f"  snippet: {ev.snippet[:300]}")

    try:
        data = llm.generate_json(
            "\n".join(lines), _VERIFY_SCHEMA, system=_VERIFY_SYSTEM, temperature=0.0
        )
    except llm.LLMError as exc:
        return [
            ClaimCheck(
                claim="(verification could not run)",
                supported=False,
                evidence_id="",
                note=f"claim check unavailable: {exc}",
            )
        ]

    allowed_ids = {ev.id for ev in allowed}
    checks: list[ClaimCheck] = []
    for raw in data.get("claims", []):
        claim = (raw.get("claim") or "").strip()
        if not claim:
            continue
        eid = (raw.get("evidence_id") or "").strip()
        supported = bool(raw.get("supported"))
        if supported and eid not in allowed_ids:
            # Cited something that is not in the allowed set: not support.
            supported = False
            raw["note"] = (raw.get("note") or "") + " [cited an id outside the allowed sources]"
            eid = ""
        checks.append(
            ClaimCheck(
                claim=claim,
                supported=supported,
                evidence_id=eid,
                note=(raw.get("note") or "").strip(),
            )
        )
    return checks


# ---------------------------------------------------------------- style audit

_BANNED = [
    (r"\bi hope this (email )?finds you well\b", "opens with a dead phrase"),
    (r"\bi came across your (profile|linkedin)\b", "generic prospecting tell"),
    (r"\b(pick your brain|quick chat|quick call|touch base|circle back)\b",
     "filler ask"),
    (r"\b(impressive|exciting|amazing|thrilled|love what you)\b", "flattery"),
    (r"!", "exclamation mark"),
    (r"—", "em-dash"),
    (r"\b(synergy|leverage our|best-in-class|cutting-edge|revolutionary)\b",
     "marketing cliche"),
]


def style_audit(draft: Draft) -> list[str]:
    """Deterministic smell test. Cheap, and catches what the model slips in
    despite being told not to.

    Structural checks earn their place here rather than in the prompt: a
    wall-of-text cold email reads as automated no matter how good the hook is,
    and telling the model "short paragraphs" does not reliably produce them.
    """
    issues: list[str] = []
    text = f"{draft.subject}\n{draft.body}"

    for pattern, label in _BANNED:
        match = re.search(pattern, text, re.I)
        if match:
            issues.append(f"{label}: {match.group(0)!r}")

    if draft.word_count > config.MAX_DRAFT_WORDS:
        issues.append(f"{draft.word_count} words, over the {config.MAX_DRAFT_WORDS} limit")
    if not draft.subject:
        issues.append("no subject line")
    if draft.opener_claim and draft.opener_claim not in draft.body:
        issues.append("opener_claim is not a verbatim sentence from the body")

    paragraphs = [p for p in re.split(r"\n\s*\n", draft.body.strip()) if p.strip()]
    if draft.word_count > 45 and len(paragraphs) < 2:
        issues.append("one unbroken block of text, no paragraph breaks")
    longest = max((len(p.split()) for p in paragraphs), default=0)
    if longest > 55:
        issues.append(f"longest paragraph is {longest} words, too dense to skim")

    # A sign-off is the last line standing alone, short, and not a question.
    lines = [l.strip() for l in draft.body.strip().splitlines() if l.strip()]
    last = lines[-1] if lines else ""
    if not last or len(last.split()) > 4 or last.endswith("?"):
        issues.append("no sign-off line")

    return issues
