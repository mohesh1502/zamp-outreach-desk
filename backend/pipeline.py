"""The process itself.

Nine stages, each one emitting an event so the Live Run view can show it as it
happens. The orchestrator owns two things worth reading closely:

  * Early exit. The identity check runs on person-targeted queries *before* the
    full company scrape. If the prospect has left the company or the name is
    ambiguous, the run stops there -- the remaining stages are marked skipped
    rather than executed. Drafting on a bad record is not just wasted work, it
    is the specific mistake that burns an account.

  * Degradation over failure. A dead connector, a throttled lookup or an LLM
    timeout marks its stage 'warn' and the run continues with what it has. Only
    a condition that makes the output untrustworthy stops the process.

Terminal statuses and what each one means to the rep:
  ready_for_review         draft is grounded, send-ready after a read
  fallback_company_signal  first-choice hook was vetoed, a weaker one was used
  needs_manual_research    nothing citable and recent enough -- do it by hand
  blocked_sensitive        every available hook was a crisis story
  flagged_job_change       the CRM record is wrong; fix it before outreach
  needs_disambiguation     more than one person matches this name
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import config, drafting, fixtures, guardrails, llm, scoring, sources, store
from .models import (
    ClaimCheck,
    Evidence,
    Prospect,
    Run,
    ScoreBreakdown,
    Signal,
    StageLog,
)

Emit = Callable[[str, dict[str, Any]], None]

STAGES: list[tuple[str, str]] = [
    ("intake", "Intake & normalisation"),
    ("identity", "Identity & employment check"),
    ("harvest", "Multi-source signal harvest"),
    ("interpret", "Signal interpretation"),
    ("guardrail", "Safety & recency screen"),
    ("score", "Scoring & hook selection"),
    ("draft", "Draft generation"),
    ("verify", "Claim grounding & style audit"),
    ("package", "Review packaging"),
]


class StageRunner:
    """Tracks stage state and pushes every transition to the client."""

    def __init__(self, run: Run, emit: Emit) -> None:
        self.run = run
        self.emit = emit
        run.stages = [StageLog(key=k, title=t) for k, t in STAGES]
        self._by_key = {s.key: s for s in run.stages}

    def start(self, key: str) -> StageLog:
        stage = self._by_key[key]
        stage.state = "active"
        stage.started_at = time.time()
        self.emit("stage", stage.model_dump())
        return stage

    def finish(
        self,
        key: str,
        state: str = "done",
        summary: str = "",
        detail: Optional[dict[str, Any]] = None,
    ) -> StageLog:
        stage = self._by_key[key]
        stage.state = state  # type: ignore[assignment]
        stage.summary = summary
        if detail:
            stage.detail = detail
        stage.ended_at = time.time()
        if stage.started_at:
            stage.ms = int((stage.ended_at - stage.started_at) * 1000)
        self.emit("stage", stage.model_dump())
        return stage

    def skip(self, keys: list[str], reason: str) -> None:
        for key in keys:
            stage = self._by_key[key]
            if stage.state == "pending":
                stage.state = "skipped"
                stage.summary = reason
                self.emit("stage", stage.model_dump())


def new_run_id() -> str:
    """Minted by the caller so the event channel can exist before stage one."""
    return "run_" + uuid.uuid4().hex[:10]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _retrieve(
    plan: list[tuple[str, str]], *, emit: Emit, label: str
) -> tuple[list[Evidence], list[dict[str, Any]]]:
    """Execute a query plan, reporting each lookup as it lands."""
    collected: list[Evidence] = []
    log: list[dict[str, Any]] = []

    for connector, query in plan:
        fn = sources.CONNECTORS[connector]
        started = time.time()
        try:
            found = fn(query)
            entry = {
                "connector": connector,
                "query": query,
                "n": len(found),
                "ok": True,
                "ms": int((time.time() - started) * 1000),
            }
            collected.extend(found)
        except Exception as exc:
            entry = {
                "connector": connector,
                "query": query,
                "n": 0,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}"[:160],
                "best_effort": connector in sources.BEST_EFFORT,
                "ms": int((time.time() - started) * 1000),
            }
        log.append(entry)
        emit("lookup", {"phase": label, **entry})

    return sources.dedupe(collected), log


def _resolve_source_mode(requested: Optional[str], company: str) -> tuple[str, str]:
    """Decide live vs replay. Returns (mode, note)."""
    mode = (requested or config.SOURCE_MODE or "auto").lower()
    if mode == "replay":
        return "replay", "replay requested: using the fixture corpus"
    if mode == "live":
        return "live", "live requested: fixtures disabled"
    return "auto", "auto: live connectors, fixtures only if live returns nothing"


def run_pipeline(
    prospect: Prospect,
    *,
    emit: Emit,
    source_mode: Optional[str] = None,
    case_id: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Run:
    started = time.time()
    mode, mode_note = _resolve_source_mode(source_mode, prospect.company)

    run = Run(
        id=run_id or new_run_id(),
        created_at=_now_iso(),
        prospect=prospect,
        case_id=case_id,
        source_mode=mode,
        status="running",
    )
    stages = StageRunner(run, emit)
    emit("run", {"id": run.id, "created_at": run.created_at, "source_mode": mode})

    def finalise(status: str, headline: str, confidence: int = 0) -> Run:
        run.status = status  # type: ignore[assignment]
        run.headline = headline
        run.confidence = confidence
        run.ms = int((time.time() - started) * 1000)
        store.save(run)
        emit("done", {"status": status, "headline": headline, "confidence": confidence,
                      "ms": run.ms})
        return run

    try:
        # ---------------------------------------------------------- 1. intake
        stages.start("intake")
        missing = [f for f in ("name", "company") if not getattr(prospect, f).strip()]
        if missing:
            stages.finish("intake", "error", f"missing required field(s): {', '.join(missing)}")
            stages.skip([k for k, _ in STAGES[1:]], "intake failed")
            run.error = f"missing required field(s): {', '.join(missing)}"
            return finalise("error", run.error)

        family = scoring.role_family(prospect.role)
        stages.finish(
            "intake",
            "done",
            f"{prospect.name} · {prospect.company} · scored as a '{family}' role",
            {
                "prospect": prospect.model_dump(),
                "role_family": family,
                "source_mode": mode,
                "source_mode_note": mode_note,
                "policy": {
                    "max_age_days": config.SIGNAL_MAX_AGE_DAYS,
                    "min_hook_score": config.MIN_HOOK_SCORE,
                    "min_person_hook_score": config.MIN_PERSON_HOOK_SCORE,
                },
            },
        )

        # ------------------------------------------------- replay short-circuit
        replay_evidence: Optional[list[Evidence]] = None
        if mode == "replay":
            replay_evidence = fixtures.corpus_for(prospect.company)
            if replay_evidence is None:
                replay_evidence = []

        # -------------------------------------------------------- 2. identity
        stages.start("identity")
        person_plan = [
            (c, q)
            for c, q in sources.plan_queries(
                prospect.name, prospect.company, prospect.role, prospect.domain
            )
            if prospect.name in q
        ]

        if replay_evidence is not None:
            person_evidence = [
                ev
                for ev in replay_evidence
                if prospect.name.split()[-1].lower() in (ev.title + " " + ev.snippet).lower()
            ]
            lookup_log: list[dict[str, Any]] = [
                {"connector": "fixtures", "query": prospect.company, "ok": True,
                 "n": len(replay_evidence)}
            ]
            emit("lookup", {"phase": "identity", **lookup_log[0]})
        else:
            person_evidence, lookup_log = _retrieve(person_plan, emit=emit, label="identity")

        run.evidence.extend(person_evidence)
        identity = guardrails.verify_identity(
            prospect.name, prospect.company, prospect.role, person_evidence
        )

        identity_detail = {
            "verdict": identity,
            "lookups": lookup_log,
            "person_evidence_ids": [e.id for e in person_evidence],
        }

        if identity.get("name_collision"):
            stages.finish(
                "identity",
                "blocked",
                f"two or more people match '{prospect.name}' — rep must confirm which",
                identity_detail,
            )
            stages.skip([k for k, _ in STAGES[2:]], "halted: identity is ambiguous")
            run.selection_rationale = identity.get("collision_detail", "")
            return finalise(
                "needs_disambiguation",
                f"Name collision: {identity.get('collision_detail') or 'multiple matches found'}",
            )

        if identity.get("employment") == "left_company":
            # Corroboration gate. A departure claim halts the run only when the
            # model is confident AND named the source it relied on. Without
            # both, this is almost always an unrelated namesake picked up by the
            # unscoped job-move probe, and halting would wrongly tell the rep
            # their CRM is stale.
            cited = identity.get("evidence_id") or ""
            confident = int(identity.get("confidence") or 0) >= config.IDENTITY_HALT_CONFIDENCE
            corroborated = bool(cited) and confident
            identity_detail["halt_gate"] = {
                "confidence": identity.get("confidence"),
                "required": config.IDENTITY_HALT_CONFIDENCE,
                "evidence_id": cited,
                "halted": corroborated,
            }

            if corroborated:
                stages.finish(
                    "identity",
                    "blocked",
                    f"{prospect.name} appears to have left {prospect.company}",
                    identity_detail,
                )
                stages.skip(
                    [k for k, _ in STAGES[2:]], "halted: prospect record is out of date"
                )
                run.selection_rationale = identity.get("reasoning", "")
                return finalise(
                    "flagged_job_change",
                    "Job change detected — "
                    + (identity.get("reasoning") or "sources place them elsewhere"),
                )

            # Not corroborated: treat as unknown and keep going, but say so.
            identity["employment"] = "unconfirmed"
            identity["downgraded_from"] = "left_company"
            identity_detail["verdict"] = identity

        verdict = identity.get("employment", "unconfirmed")
        state = "done" if verdict == "confirmed" else "warn"
        summary = {
            "confirmed": f"employment confirmed ({identity.get('confidence', 0)}% confidence)",
            "changed_role": f"title may differ: sources say '{identity.get('stated_role')}'",
            "unconfirmed": "no source confirms the seat — company-level hooks only",
        }.get(verdict, verdict)
        if identity.get("downgraded_from"):
            summary = (
                "possible job change was uncorroborated "
                f"({identity.get('confidence', 0)}% < {config.IDENTITY_HALT_CONFIDENCE}% "
                "or no source cited) — treated as a namesake, continuing"
            )
        stages.finish("identity", state, summary, identity_detail)

        # --------------------------------------------------------- 3. harvest
        stages.start("harvest")
        if replay_evidence is not None:
            company_evidence = replay_evidence
            harvest_log = [
                {"connector": "fixtures", "query": prospect.company, "ok": True,
                 "n": len(replay_evidence)}
            ]
            emit("lookup", {"phase": "harvest", **harvest_log[0]})
        else:
            company_plan = [
                (c, q)
                for c, q in sources.plan_queries(
                    prospect.name, prospect.company, prospect.role, prospect.domain
                )
                if (c, q) not in person_plan
            ]
            company_evidence, harvest_log = _retrieve(
                company_plan, emit=emit, label="harvest"
            )

            # auto mode: nothing live, but we hold a corpus for this company
            if mode == "auto" and not company_evidence and not person_evidence:
                corpus = fixtures.corpus_for(prospect.company)
                if corpus:
                    company_evidence = corpus
                    run.source_mode = "auto→replay"
                    harvest_log.append(
                        {"connector": "fixtures", "query": prospect.company,
                         "ok": True, "n": len(corpus), "note": "live returned nothing"}
                    )

        run.evidence = sources.dedupe(run.evidence + company_evidence)

        failed = [entry for entry in harvest_log if not entry.get("ok")]
        hard_failed = [entry for entry in failed if not entry.get("best_effort")]
        by_connector: dict[str, int] = {}
        for ev in run.evidence:
            by_connector[ev.connector] = by_connector.get(ev.connector, 0) + 1

        if not run.evidence:
            stages.finish(
                "harvest",
                "warn",
                "no evidence retrieved from any source",
                {"lookups": harvest_log, "by_connector": by_connector},
            )
            stages.skip([k for k, _ in STAGES[3:]], "nothing to work with")
            return finalise(
                "needs_manual_research",
                f"No public signal found for {prospect.name} at {prospect.company} — "
                "queued for manual research rather than inventing a hook",
            )

        stages.finish(
            "harvest",
            "warn" if hard_failed else "done",
            f"{len(run.evidence)} unique items from {len(by_connector)} source(s)"
            + (f"; {len(failed)} lookup(s) failed" if failed else ""),
            {"lookups": harvest_log, "by_connector": by_connector},
        )

        # ------------------------------------------------------- 4. interpret
        stages.start("interpret")
        try:
            raw_signals, interp_diag = drafting.interpret(
                name=prospect.name,
                company=prospect.company,
                role=prospect.role,
                evidence=run.evidence,
            )
        except llm.LLMError as exc:
            stages.finish("interpret", "error", f"interpretation failed: {exc}")
            stages.skip([k for k, _ in STAGES[4:]], "interpretation failed")
            run.error = str(exc)
            return finalise("error", f"Signal interpretation failed: {exc}")

        signals: list[Signal] = [
            Signal(
                id=f"sig_{i + 1}",
                kind=raw.get("kind", "other"),
                level=raw.get("level", "company"),
                claim=raw["claim"],
                why_it_matters=raw.get("why_it_matters", ""),
                evidence_ids=raw["evidence_ids"],
            )
            for i, raw in enumerate(raw_signals)
        ]
        run.signals = signals

        if not signals:
            stages.finish(
                "interpret",
                "warn",
                "no citable signal could be formed"
                + (" (retried once)" if interp_diag.get("retried") else ""),
                {"diagnostics": interp_diag},
            )
            stages.skip([k for k, _ in STAGES[4:]], "no candidate signals")
            return finalise(
                "needs_manual_research",
                f"{len(run.evidence)} items retrieved but none yielded a citable, "
                "specific claim — queued for manual research",
            )

        kinds = sorted({s.kind for s in signals})
        stages.finish(
            "interpret",
            "warn" if interp_diag.get("retried") else "done",
            f"{len(signals)} candidate signal(s): {', '.join(kinds)}"
            + (" — first pass came back empty, retried" if interp_diag.get("retried") else ""),
            {"signals": [s.model_dump() for s in signals], "diagnostics": interp_diag},
        )

        # ------------------------------------------------------- 5. guardrail
        stages.start("guardrail")
        evidence_by_id = {ev.id: ev for ev in run.evidence}
        guard_detail: dict[str, Any] = {"regex_hits": [], "llm_hits": [], "stale": []}

        # Pass A: regex pre-screen over claim + backing headlines.
        candidates_for_llm: list[dict[str, str]] = []
        for signal in signals:
            backing = [evidence_by_id[i] for i in signal.evidence_ids if i in evidence_by_id]
            blob = " ".join([signal.claim] + [e.title + " " + e.snippet for e in backing])
            hit, category = guardrails.regex_sensitivity(blob)
            if hit:
                signal.sensitive = True
                signal.sensitive_reason = f"keyword screen: {category}"
                guard_detail["regex_hits"].append(
                    {"signal_id": signal.id, "category": category}
                )
            candidates_for_llm.append(
                {
                    "id": signal.id,
                    "title": signal.claim,
                    "snippet": " | ".join(e.title for e in backing)[:300],
                }
            )

        # Pass B: LLM screen over everything the regex let through.
        llm_verdicts = guardrails.llm_sensitivity(
            [c for c in candidates_for_llm
             if not next(s for s in signals if s.id == c["id"]).sensitive]
        )
        for signal in signals:
            verdict = llm_verdicts.get(signal.id)
            if verdict:
                signal.sensitive = True
                signal.sensitive_reason = (
                    f"model screen ({verdict['category']}): {verdict['reason']}"
                )
                guard_detail["llm_hits"].append({"signal_id": signal.id, **verdict})

        # Recency + veto application.
        for signal in signals:
            backing = [evidence_by_id[i] for i in signal.evidence_ids if i in evidence_by_id]
            ages = [e.age_days for e in backing if e.age_days is not None]
            age = min(ages) if ages else None
            tier, note = guardrails.recency_verdict(age)
            if tier == "stale":
                signal.stale = True
                guard_detail["stale"].append({"signal_id": signal.id, "note": note})

            if signal.sensitive:
                signal.vetoed = True
                signal.veto_reason = "sensitive"
            elif signal.stale:
                signal.vetoed = True
                signal.veto_reason = "stale"

        vetoed = [s for s in signals if s.vetoed]
        survivors = [s for s in signals if not s.vetoed]
        guard_detail["surviving"] = [s.id for s in survivors]

        if not survivors:
            all_sensitive = all(s.sensitive for s in vetoed)
            stages.finish(
                "guardrail",
                "blocked",
                f"all {len(vetoed)} signal(s) vetoed",
                guard_detail,
            )
            stages.skip([k for k, _ in STAGES[5:]], "no signal survived the screen")
            for signal in signals:
                signal.score = scoring.score_signal(signal, evidence_by_id, prospect.role)
            if all_sensitive:
                reasons = sorted({s.sensitive_reason.split(":")[0] for s in vetoed})
                return finalise(
                    "blocked_sensitive",
                    f"Blocked: every available signal is a crisis story "
                    f"({', '.join(reasons)}) — no outreach drafted",
                )
            return finalise(
                "needs_manual_research",
                f"All {len(vetoed)} signals failed the {config.SIGNAL_MAX_AGE_DAYS}-day "
                "recency limit — nothing recent enough to reference",
            )

        stages.finish(
            "guardrail",
            "warn" if vetoed else "done",
            f"{len(survivors)} of {len(signals)} signal(s) cleared"
            + (f"; {len(vetoed)} vetoed" if vetoed else ""),
            guard_detail,
        )

        # ----------------------------------------------------------- 6. score
        stages.start("score")
        for signal in signals:
            signal.score = scoring.score_signal(signal, evidence_by_id, prospect.role)

        winner, rationale, ranked = scoring.select(signals)
        run.selection_rationale = rationale
        score_detail = {
            "ranked": [
                {
                    "id": s.id,
                    "kind": s.kind,
                    "level": s.level,
                    "claim": s.claim,
                    "total": s.score.total,
                    "vetoed": s.vetoed,
                    "veto_reason": s.veto_reason,
                    "breakdown": s.score.model_dump(),
                }
                for s in ranked
            ],
            "thresholds": {
                "company": config.MIN_HOOK_SCORE,
                "person": config.MIN_PERSON_HOOK_SCORE,
            },
            "rationale": rationale,
            # Explicit, so the UI highlights the hook that was actually used
            # rather than assuming the top surviving row won.
            "chosen_id": winner.id if winner else None,
        }

        if winner is None:
            stages.finish("score", "warn", rationale, score_detail)
            stages.skip([k for k, _ in STAGES[6:]], "no hook cleared the score floor")
            return finalise(
                "needs_manual_research",
                f"No hook strong enough to personalise on — {rationale}",
            )

        run.chosen_signal_id = winner.id
        # "Fallback" means the guardrail actually changed the outcome: the
        # highest-scoring signal was vetoed and we dropped to a weaker one. Note
        # this compares on raw score -- scoring.rank() deliberately sorts vetoed
        # signals last, so ranked[0] is always a survivor and would never show a
        # fallback.
        top_overall = max(signals, key=lambda s: s.score.total)
        used_fallback = bool(top_overall.vetoed and top_overall.id != winner.id)

        stages.finish(
            "score",
            "warn" if used_fallback else "done",
            f"hook: {winner.kind} at {winner.score.total}/100 — {rationale}",
            score_detail,
        )

        # ----------------------------------------------------------- 7. draft
        stages.start("draft")
        is_fallback_voice = winner.level == "company" and verdict != "confirmed"
        try:
            draft = drafting.write_draft(
                name=prospect.name,
                company=prospect.company,
                role=prospect.role,
                signal=winner,
                evidence=run.evidence,
                fallback=is_fallback_voice,
            )
        except llm.LLMError as exc:
            stages.finish("draft", "error", f"drafting failed: {exc}")
            stages.skip([k for k, _ in STAGES[7:]], "drafting failed")
            run.error = str(exc)
            return finalise("error", f"Draft generation failed: {exc}")

        run.draft = draft
        stages.finish(
            "draft",
            "done",
            f"{draft.word_count} words on the {winner.kind} hook",
            {"draft": draft.model_dump(), "fallback_voice": is_fallback_voice},
        )

        # ---------------------------------------------------------- 8. verify
        stages.start("verify")
        checks = drafting.verify_draft(draft, run.evidence)
        unsupported = [c for c in checks if not c.supported]
        attempts = 0

        while unsupported and attempts < config.DRAFT_REPAIR_ATTEMPTS:
            attempts += 1
            note = "\n".join(f"- {c.claim} ({c.note})" for c in unsupported)
            emit(
                "repair",
                {"attempt": attempts, "unsupported": [c.model_dump() for c in unsupported]},
            )
            try:
                draft = drafting.write_draft(
                    name=prospect.name,
                    company=prospect.company,
                    role=prospect.role,
                    signal=winner,
                    evidence=run.evidence,
                    fallback=is_fallback_voice,
                    repair_note=note,
                )
            except llm.LLMError:
                break
            run.draft = draft
            checks = drafting.verify_draft(draft, run.evidence)
            unsupported = [c for c in checks if not c.supported]

        run.claim_checks = checks
        style_issues = drafting.style_audit(draft)
        supported_n = len([c for c in checks if c.supported])

        verify_detail = {
            "checks": [c.model_dump() for c in checks],
            "style_issues": style_issues,
            "repair_attempts": attempts,
            "draft": draft.model_dump(),
        }

        if unsupported:
            stages.finish(
                "verify",
                "warn",
                f"{len(unsupported)} unverified claim(s) after {attempts} repair "
                "attempt(s) — held for a human",
                verify_detail,
            )
        else:
            stages.finish(
                "verify",
                "done" if not style_issues else "warn",
                f"all {supported_n} factual claim(s) tied to a source"
                + (f"; {len(style_issues)} style note(s)" if style_issues else ""),
                verify_detail,
            )

        # --------------------------------------------------------- 9. package
        stages.start("package")
        confidence = _confidence(
            winner=winner,
            identity=identity,
            checks=checks,
            style_issues=style_issues,
            used_fallback=used_fallback,
        )
        run.confidence = confidence
        run.review = {"state": "pending", "editable": True}

        if unsupported:
            status = "needs_manual_research"
            headline = (
                f"Draft written on the {winner.kind} hook, but "
                f"{len(unsupported)} claim(s) could not be tied to a source — "
                "needs a human edit before sending"
            )
        elif used_fallback:
            status = "fallback_company_signal"
            headline = (
                f"Fallback used: the top signal was vetoed ({top_overall.veto_reason}), "
                f"drafted on {winner.kind} at {winner.score.total}/100 instead"
            )
        else:
            status = "ready_for_review"
            headline = (
                f"Ready for review: {winner.kind} hook, {winner.score.total}/100, "
                f"{supported_n} claim(s) sourced"
            )

        stages.finish(
            "package",
            "done",
            f"status {status} · confidence {confidence}%",
            {"status": status, "confidence": confidence, "headline": headline},
        )
        return finalise(status, headline, confidence)

    except Exception as exc:  # noqa: BLE001 - the UI must always get a terminal state
        run.error = f"{type(exc).__name__}: {exc}"
        emit("error", {"detail": run.error})
        for stage in run.stages:
            if stage.state in ("pending", "active"):
                stage.state = "error" if stage.state == "active" else "skipped"
                emit("stage", stage.model_dump())
        return finalise("error", f"Run failed: {run.error}")


def _confidence(
    *,
    winner: Signal,
    identity: dict[str, Any],
    checks: list[ClaimCheck],
    style_issues: list[str],
    used_fallback: bool,
) -> int:
    """How much the rep should trust this draft, 0-100.

    Weighted from the four things that actually vary: how strong the hook was,
    whether we could confirm the person is in the seat, whether every claim tied
    to a source, and whether the prose came out clean.
    """
    hook = winner.score.total

    employment = identity.get("employment", "unconfirmed")
    if employment == "confirmed":
        identity_score = max(60, int(identity.get("confidence") or 0))
    elif employment == "changed_role":
        identity_score = 45
    else:
        # Unconfirmed is normal for a company-level hook and shouldn't be
        # punished as hard as a contradicted one.
        identity_score = 70 if winner.level == "company" else 35

    if checks:
        grounding = round(100 * len([c for c in checks if c.supported]) / len(checks))
    else:
        grounding = 50  # nothing checkable asserted: neither good nor bad

    score = 0.45 * hook + 0.20 * identity_score + 0.35 * grounding
    score -= 4 * len(style_issues)
    if used_fallback:
        score -= 8
    return max(0, min(100, round(score)))
