"""Run the whole test library and assert each case lands where it should.

    python -m tools.run_cases              # every case
    python -m tools.run_cases EDGE-04      # just one
    python -m tools.run_cases --edge       # edge cases only
    python -m tools.run_cases --quiet      # one line per case

This is the regression check. Live cases depend on what the news actually says
today, so they are asserted loosely (did it produce a grounded draft) while the
replay cases are asserted exactly (status must match). That split is deliberate:
a strict assertion on live news would fail for reasons that are not bugs.

Exit code is non-zero if any assertion fails, so it works in a pre-demo check.
"""
from __future__ import annotations

import sys
import time
from typing import Any

from backend import fixtures, pipeline, store
from backend.models import Prospect

# What each case must produce. Replay cases are exact; live cases accept any of
# the healthy outcomes, because today's news decides which one is right.
EXPECTED: dict[str, set[str]] = {
    "HAPPY-01": {"ready_for_review", "fallback_company_signal"},
    "HAPPY-02": {"ready_for_review", "fallback_company_signal"},
    "HAPPY-03": {"ready_for_review", "fallback_company_signal"},
    "ROLE-A": {"ready_for_review"},
    "ROLE-B": {"ready_for_review"},
    "EDGE-01": {"needs_manual_research"},
    "EDGE-02": {"needs_manual_research"},
    "EDGE-03": {"flagged_job_change"},
    "EDGE-04": {"fallback_company_signal"},
    "EDGE-05": {"needs_disambiguation"},
}

# Extra invariants worth checking per case -- the behaviour the status alone
# does not prove.
def extra_checks(case_id: str, run: Any) -> list[tuple[str, bool]]:
    checks: list[tuple[str, bool]] = []
    ev_ids = {e.id for e in run.evidence}

    if run.draft:
        checks.append((
            "every draft citation resolves to retrieved evidence",
            all(c in ev_ids for c in run.draft.citations),
        ))
        checks.append((
            "draft is within the word limit",
            run.draft.word_count <= 120,
        ))
        checks.append((
            "no claim is left unsupported",
            all(c.supported for c in run.claim_checks),
        ))

    if case_id == "EDGE-01":
        checks.append(("no draft was written", run.draft is None))
        checks.append(("no evidence was invented", len(run.evidence) == 0))

    if case_id == "EDGE-02":
        checks.append(("no draft was written", run.draft is None))
        checks.append((
            "every signal was vetoed as stale",
            bool(run.signals) and all(s.stale and s.vetoed for s in run.signals),
        ))

    if case_id == "EDGE-03":
        checks.append(("halted before drafting", run.draft is None))
        checks.append((
            "harvest never ran",
            any(s.key == "harvest" and s.state == "skipped" for s in run.stages),
        ))

    if case_id == "EDGE-04":
        sensitive = [s for s in run.signals if s.sensitive]
        chosen = next((s for s in run.signals if s.id == run.chosen_signal_id), None)
        top = max(run.signals, key=lambda s: s.score.total) if run.signals else None
        checks.append(("crisis signals were detected", len(sensitive) >= 2))
        checks.append((
            "every sensitive signal was vetoed",
            all(s.vetoed for s in sensitive),
        ))
        checks.append((
            "the top-scoring signal was NOT the one used (guardrail bit)",
            bool(top and chosen and top.id != chosen.id),
        ))
        checks.append((
            "the hook actually used is not sensitive",
            bool(chosen and not chosen.sensitive),
        ))

    if case_id == "EDGE-05":
        checks.append(("halted before drafting", run.draft is None))

    # The controlled pair: each half must pick the kind its role table favours.
    if case_id in ("ROLE-A", "ROLE-B"):
        chosen = next((s for s in run.signals if s.id == run.chosen_signal_id), None)
        want = "funding" if case_id == "ROLE-A" else "product"
        checks.append((
            f"hook kind is '{want}' (role weighting decided it)",
            bool(chosen and chosen.kind == want),
        ))
        checks.append((
            "the competing signal was available but out-scored",
            len([s for s in run.signals if not s.vetoed]) >= 2,
        ))

    if case_id.startswith("HAPPY"):
        checks.append(("a draft was produced", run.draft is not None))
        checks.append(("at least one signal was found", len(run.signals) > 0))
        checks.append((
            "all cited evidence carries a real URL",
            all(e.url.startswith("http") for e in run.evidence),
        ))

    return checks


def run_one(case_id: str, *, quiet: bool) -> tuple[bool, str]:
    entry = fixtures.case(case_id)
    if entry is None:
        return False, f"{case_id}: no such case"

    prospect = Prospect(**entry["prospect"])
    started = time.time()

    def emit(kind: str, payload: dict) -> None:
        if quiet or kind != "stage" or payload.get("state") in ("pending", "active"):
            return
        mark = {
            "done": "  ok", "warn": "warn", "blocked": "STOP",
            "skipped": "   -", "error": " ERR",
        }.get(payload["state"], "    ")
        print(f"   {mark}  {payload['title']:<34} {payload.get('summary', '')[:78]}")

    if not quiet:
        print(f"\n{'=' * 100}")
        print(f"{case_id}  ·  {entry['label']}  ·  sources={entry['source_mode']}")
        print(f"expect: {entry['expectation']}")
        print(f"{'-' * 100}")

    run = pipeline.run_pipeline(
        prospect, emit=emit, source_mode=entry["source_mode"], case_id=case_id
    )
    took = time.time() - started

    allowed = EXPECTED.get(case_id, set())
    status_ok = run.status in allowed
    results = [(f"status is one of {sorted(allowed)}", status_ok)]
    results += extra_checks(case_id, run)
    passed = all(ok for _, ok in results)

    if quiet:
        flag = "PASS" if passed else "FAIL"
        print(f"[{flag}] {case_id:<10} {run.status:<26} "
              f"conf={run.confidence:>3}%  {took:>5.1f}s  "
              f"{sum(1 for _, ok in results if not ok)} failed check(s)")
    else:
        print(f"{'-' * 100}")
        print(f"got: {run.status}  ·  confidence {run.confidence}%  ·  {took:.1f}s")
        if run.headline:
            print(f"     {run.headline}")
        print()
        for label, ok in results:
            print(f"   {'PASS' if ok else 'FAIL'}  {label}")
        if run.draft:
            print(f"\n   subject: {run.draft.subject}")
            for line in run.draft.body.splitlines():
                print(f"   | {line}")

    detail = "" if passed else ", ".join(l for l, ok in results if not ok)
    return passed, detail


def main() -> int:
    args = [a for a in sys.argv[1:]]
    quiet = "--quiet" in args
    args = [a for a in args if a != "--quiet"]

    if "--edge" in args:
        ids = [c["id"] for c in fixtures.TEST_CASES if c["kind"] == "edge"]
    elif "--happy" in args:
        ids = [c["id"] for c in fixtures.TEST_CASES if c["kind"] == "happy"]
    elif args:
        ids = args
    else:
        ids = [c["id"] for c in fixtures.TEST_CASES]

    store.init()
    outcomes: list[tuple[str, bool, str]] = []
    for case_id in ids:
        try:
            ok, detail = run_one(case_id, quiet=quiet)
        except Exception as exc:  # a crash is a failure, not a stack trace
            ok, detail = False, f"{type(exc).__name__}: {exc}"
            print(f"[FAIL] {case_id:<10} crashed: {detail}")
        outcomes.append((case_id, ok, detail))

    failed = [(c, d) for c, ok, d in outcomes if not ok]
    print(f"\n{'=' * 100}")
    print(f"{len(outcomes) - len(failed)}/{len(outcomes)} cases passed")
    for case_id, detail in failed:
        print(f"  FAIL {case_id}: {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
