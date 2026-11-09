"""The test library: prepared prospects plus a replay corpus.

Why a corpus exists at all. Four of the edge cases are conditions you cannot
summon on demand from the live web -- you cannot guarantee that today's news
contains a prospect who just changed jobs, a company in the middle of a layoff
round, or a genuine name collision. Waiting for the internet to produce one
during a live demo is not a plan.

So: happy paths run live against real connectors, and the edge cases run against
this corpus. Replay evidence is tagged connector="fixtures" and the UI badges it
REPLAY, so nothing synthetic is ever presented as a real citation.

Companies here are fictional on purpose. Attaching an invented layoff round or
lawsuit to a real company would be defamatory, and the case-study brief
explicitly allows made-up-but-plausible inputs.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .models import Evidence, Prospect


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def _ev(
    eid: str,
    title: str,
    url: str,
    publisher: str,
    age: int | None,
    snippet: str,
    query: str = "replay",
) -> Evidence:
    return Evidence(
        id=eid,
        title=title,
        url=url,
        publisher=publisher,
        published_at=_days_ago(age) if age is not None else None,
        age_days=age,
        snippet=snippet,
        connector="fixtures",
        query=query,
    )


# ------------------------------------------------------------------ corpus
# Keyed by lowercased company name. Each entry is the full evidence set the
# connectors would have returned.

CORPUS: dict[str, list[Evidence]] = {
    # EDGE-02 -- the only substantive news is well past the staleness limit.
    "lumenpay": [
        _ev(
            "fx_lumen_1",
            "Lumenpay closes $40M Series B led by Fairhaven Partners",
            "https://example-press.test/lumenpay-series-b",
            "Fintech Wire",
            742,
            "Lumenpay said the round would fund expansion into three new markets. "
            "The company last raised in 2021.",
        ),
        _ev(
            "fx_lumen_2",
            "Lumenpay appoints Rhea Castellano as VP Finance",
            "https://example-press.test/lumenpay-vp-finance",
            "Payments Observer",
            611,
            "Castellano joins from a mid-market processor and will own financial "
            "reporting and treasury.",
        ),
        _ev(
            "fx_lumen_3",
            "Lumenpay — Company Overview",
            "https://example-press.test/lumenpay-about",
            "lumenpay.test",
            None,
            "Lumenpay provides recurring billing infrastructure for subscription "
            "businesses.",
        ),
    ],
    # EDGE-03 -- the prospect has left. Two sources say so, clearly and recently.
    "northwind freight": [
        _ev(
            "fx_north_1",
            "Northwind Freight CFO Daniel Osei steps down after four years",
            "https://example-press.test/northwind-cfo-steps-down",
            "Logistics Daily",
            23,
            "Osei will leave at the end of the quarter. Northwind has begun an "
            "external search for a successor; interim duties pass to the "
            "group controller.",
        ),
        _ev(
            "fx_north_2",
            "Daniel Osei joins Calderwood Logistics as Chief Financial Officer",
            "https://example-press.test/osei-joins-calderwood",
            "Supply Chain Brief",
            11,
            "Calderwood Logistics confirmed Osei started this month, reporting to "
            "the chief executive.",
        ),
        _ev(
            "fx_north_3",
            "Northwind Freight opens automated cross-dock hub in Rotterdam",
            "https://example-press.test/northwind-rotterdam",
            "Freight Technology Review",
            19,
            "The 40,000 sq m facility is Northwind's third in Europe and will "
            "handle an estimated 1.2 million parcels a month.",
        ),
    ],
    # EDGE-04 -- a real crisis dominates the news. The usable hook is buried.
    "castellum health": [
        _ev(
            "fx_cast_1",
            "Castellum Health to cut 600 roles as it restructures payer business",
            "https://example-press.test/castellum-layoffs",
            "Health Markets Journal",
            6,
            "The reduction affects roughly 9% of staff, concentrated in claims "
            "operations. Executives called the cuts difficult but necessary.",
        ),
        _ev(
            "fx_cast_2",
            "Class action filed against Castellum Health over claims denials",
            "https://example-press.test/castellum-class-action",
            "Legal Wire",
            14,
            "The complaint alleges systematic improper denials across two states.",
        ),
        # Deliberately older and from a weaker publisher than the two crisis
        # stories above, so it loses on raw score. If the safe signal won on
        # merit, this case would prove nothing about the guardrail.
        _ev(
            "fx_cast_3",
            "Castellum Health goes live with FHIR-based records exchange in 11 states",
            "https://example-press.test/castellum-fhir",
            "Health IT Today",
            96,
            "The rollout connects 340 provider groups and replaces a batch file "
            "transfer process the company had run since 2016.",
        ),
    ],
    # EDGE-05 -- two different people, same name, both findable.
    "arcadia robotics": [
        _ev(
            "fx_arc_1",
            "Arcadia Robotics names Priya Raghavan as Head of Operations",
            "https://example-press.test/arcadia-priya-raghavan-ops",
            "Industrial Automation Weekly",
            34,
            "Raghavan will oversee manufacturing operations across the firm's two "
            "assembly sites.",
        ),
        _ev(
            "fx_arc_2",
            "Dr Priya Raghavan appointed to the Arcadia Robotics scientific advisory board",
            "https://example-press.test/arcadia-dr-priya-raghavan-advisory",
            "Robotics Research Digest",
            52,
            "Dr Raghavan is a professor of control systems and is unrelated to "
            "Arcadia's operations leadership. She will advise on motion planning.",
        ),
        _ev(
            "fx_arc_3",
            "Arcadia Robotics raises $55M to scale warehouse picking fleet",
            "https://example-press.test/arcadia-series-c",
            "Automation Capital",
            28,
            "The Series C brings total funding to $96M. Arcadia will triple fleet "
            "deployments and expand its field service team.",
        ),
    ],
    # EDGE-01 -- a real company with genuinely no public footprint.
    "thirumala logistics": [],

    # ROLE-A / ROLE-B -- the controlled proof that role weighting decides the
    # hook. Both cases run against this identical evidence set; only the job
    # title differs. The two headline signals are tuned so that neither wins
    # outright on the role-independent components:
    #
    #   funding  rec=22 (45d)  spec~20  src=10  act=10  role: finance 25 / eng 17
    #   product  rec=30 (10d)  spec~20  src=10  act=5   role: finance 10 / eng 25
    #
    # => finance picks funding (~87 vs ~75); engineering picks product (~90 vs
    #    ~79). The margin is double digits both ways, so the flip is robust
    #    rather than a coin toss on the model's phrasing.
    "meridian stack": [
        _ev(
            "fx_mer_1",
            "Meridian Stack raises $72M Series C led by Thornbury Capital",
            "https://example-press.test/meridian-series-c",
            "Enterprise Capital Review",
            45,
            "The round values Meridian Stack at $610M and brings total funding to "
            "$131M. Finance chief Alanna Pryce said the capital would fund entity "
            "consolidation across four new markets.",
        ),
        _ev(
            "fx_mer_2",
            "Meridian Stack open-sources Halyard, its distributed query engine",
            "https://example-press.test/meridian-halyard-oss",
            "Platform Engineering Weekly",
            10,
            "Halyard handles 40 billion rows a day in production and is released "
            "under Apache 2.0. The team cited a 6x reduction in p99 latency over "
            "the Presto deployment it replaced.",
        ),
        _ev(
            "fx_mer_3",
            "Meridian Stack named to the Fastline 500 for a third year",
            "https://example-press.test/meridian-fastline",
            "Fastline",
            62,
            "The list ranks private software companies by three-year revenue "
            "growth.",
        ),
    ],
}


# ------------------------------------------------------------------ test cases

TEST_CASES: list[dict[str, Any]] = [
    {
        "id": "HAPPY-01",
        "label": "Happy path — rich live signal",
        "kind": "happy",
        "persona": "real",
        "expectation": "Ready for review, person- or company-level hook from live news",
        "why": (
            "A well-covered company where the connectors reliably return several "
            "competing fresh signals, so the scoring step has a real choice to make. "
            "Run this first, then HAPPY-02."
        ),
        "source_mode": "live",
        "prospect": {
            "name": "Harshil Mathur",
            "company": "Razorpay",
            "domain": "razorpay.com",
            "role": "CEO & Co-founder",
            "notes": "Inbound from a payments webinar.",
        },
    },
    {
        "id": "HAPPY-02",
        "label": "Happy path — same company, finance role",
        "kind": "happy",
        "persona": "synthetic",
        "expectation": "Ready for review; identical evidence re-scored under finance weights",
        "why": (
            "The controlled A/B against HAPPY-01. Same company, so the evidence pool "
            "is the same and the ONLY variable is the job title. Watch the Role "
            "column in the scoring table move, and the opener change with it. "
            "Identity will read 'unconfirmed' — correct, and the normal case for an "
            "SDR target who is not himself in the news."
        ),
        "source_mode": "live",
        "prospect": {
            "name": "Arjun Ramanathan",
            "company": "Razorpay",
            "domain": "razorpay.com",
            "role": "VP Finance",
            "notes": "Synthetic persona at a real company — tests role re-ranking.",
        },
    },
    {
        "id": "HAPPY-03",
        "label": "Happy path — second live company",
        "kind": "happy",
        "persona": "synthetic",
        "expectation": "Ready for review, hook drawn from a different live news pool",
        "why": (
            "Breadth, and demo insurance. If one company's news goes quiet on the "
            "day, this proves the connectors and scoring are not tuned to a single "
            "account."
        ),
        "source_mode": "live",
        "prospect": {
            "name": "Meera Krishnan",
            "company": "Groww",
            "domain": "groww.in",
            "role": "Head of Finance Operations",
            "notes": "Synthetic persona at a real company.",
        },
    },
    {
        "id": "ROLE-A",
        "label": "Role A/B — finance title",
        "kind": "happy",
        "persona": "synthetic",
        "expectation": "Picks the FUNDING hook — finance weights funding 25, product 10",
        "why": (
            "Half of a controlled pair. ROLE-A and ROLE-B run against byte-identical "
            "evidence and differ only in job title. Run them back to back: the "
            "winning hook changes, which is the clearest possible proof that the "
            "scoring rubric is doing real work rather than decorating a single "
            "model guess."
        ),
        "source_mode": "replay",
        "prospect": {
            "name": "Alanna Pryce",
            "company": "Meridian Stack",
            "domain": "meridianstack.test",
            "role": "VP Finance",
            "notes": "Pair with ROLE-B — same company, same evidence.",
        },
    },
    {
        "id": "ROLE-B",
        "label": "Role A/B — engineering title",
        "kind": "happy",
        "persona": "synthetic",
        "expectation": "Picks the PRODUCT hook — engineering weights product 25, funding 17",
        "why": (
            "The other half. Identical evidence to ROLE-A, engineering title. The "
            "funding story is fresher-scoring on nothing it did not already have; "
            "role fit alone moves the open-source release above it."
        ),
        "source_mode": "replay",
        "prospect": {
            "name": "Devansh Rao",
            "company": "Meridian Stack",
            "domain": "meridianstack.test",
            "role": "VP Engineering",
            "notes": "Pair with ROLE-A — same company, same evidence.",
        },
    },
    {
        "id": "EDGE-01",
        "label": "Edge — no public signal at all",
        "kind": "edge",
        "persona": "synthetic",
        "expectation": "Needs manual research — no invented hook",
        "why": (
            "The failure mode that matters most. With nothing to cite, the correct "
            "output is an honest refusal, not a plausible sentence. Most tools "
            "hallucinate here."
        ),
        "source_mode": "replay",
        "prospect": {
            "name": "Ravi Subramanian",
            "company": "Thirumala Logistics",
            "domain": "",
            "role": "Accounts Payable Manager",
            "notes": "Scraped from a trade directory.",
        },
    },
    {
        "id": "EDGE-02",
        "label": "Edge — only stale signals",
        "kind": "edge",
        "persona": "synthetic",
        "expectation": "Needs manual research — every signal fails the 180-day filter",
        "why": (
            "A two-year-old funding round is worse than no hook: it tells the "
            "prospect you did not actually look. The recency veto has to bite even "
            "when the signal is otherwise strong."
        ),
        "source_mode": "replay",
        "prospect": {
            "name": "Rhea Castellano",
            "company": "Lumenpay",
            "domain": "lumenpay.test",
            "role": "VP Finance",
            "notes": "From a conference attendee list.",
        },
    },
    {
        "id": "EDGE-03",
        "label": "Edge — prospect has changed jobs",
        "kind": "edge",
        "persona": "synthetic",
        "expectation": "Flagged: job change — drafting halted before any send",
        "why": (
            "The CRM is stale, not the web. Addressing someone by a title they left "
            "three weeks ago is the single most common own-goal in outreach, and no "
            "amount of signal quality rescues it."
        ),
        "source_mode": "replay",
        "prospect": {
            "name": "Daniel Osei",
            "company": "Northwind Freight",
            "domain": "northwindfreight.test",
            "role": "Chief Financial Officer",
            "notes": "CRM last verified 7 months ago.",
        },
    },
    {
        "id": "EDGE-04",
        "label": "Edge — company in a public crisis",
        "kind": "edge",
        "persona": "synthetic",
        "expectation": "Fallback used — layoffs outscore everything and are vetoed anyway",
        "why": (
            "Tests that the guardrail is a veto and not a tiebreaker. The layoff "
            "story is the freshest, most specific, best-sourced item in the set, "
            "so it wins the scoring outright. Watch the score column: the hook "
            "that gets used is NOT the top-scoring one."
        ),
        "source_mode": "replay",
        "prospect": {
            "name": "Marcus Whitfield",
            "company": "Castellum Health",
            "domain": "castellumhealth.test",
            "role": "VP Revenue Operations",
            "notes": "Target account, Q4 push.",
        },
    },
    {
        "id": "EDGE-05",
        "label": "Edge — name collision",
        "kind": "edge",
        "persona": "synthetic",
        "expectation": "Needs disambiguation — rep must confirm which person",
        "why": (
            "Two findable people share the name at the same company. Guessing has a "
            "50% chance of addressing an advisor as an operator, so the process asks "
            "instead of picking."
        ),
        "source_mode": "replay",
        "prospect": {
            "name": "Priya Raghavan",
            "company": "Arcadia Robotics",
            "domain": "arcadiarobotics.test",
            "role": "Head of Operations",
            "notes": "Two matching profiles found by the list vendor.",
        },
    },
]


def case(case_id: str) -> dict[str, Any] | None:
    for entry in TEST_CASES:
        if entry["id"] == case_id:
            return entry
    return None


def prospect_for(case_id: str) -> Prospect | None:
    entry = case(case_id)
    return Prospect(**entry["prospect"]) if entry else None


def corpus_for(company: str) -> list[Evidence] | None:
    """Replay evidence for a company, or None when we hold nothing for it.

    An empty list is a meaningful answer (EDGE-01: we looked and there is
    nothing), so it must stay distinguishable from None (no fixture at all).
    """
    key = (company or "").strip().lower()
    if key in CORPUS:
        return [ev.model_copy(deep=True) for ev in CORPUS[key]]
    for name, items in CORPUS.items():
        if name in key or key in name:
            return [ev.model_copy(deep=True) for ev in items]
    return None
