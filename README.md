# Outreach Desk — PS-3, prospect to draft

An operator console for personalised B2B outreach. A rep names a prospect; the
process researches them against live sources, decides which signal is worth
mentioning and why, writes a short email, audits every claim in it against a
real source, and hands the result to a human. Nothing is ever sent.

```
.\run.ps1 -Install              # first time
.\run.ps1                       # http://127.0.0.1:8000
python -m tools.run_cases       # the regression suite: 10/10 expected
```

Demo script and expected questions: **[DEMO.md](DEMO.md)**.

## The five pages

| Page | What it is |
|---|---|
| **Draft** | The prospect form, then the live run — a nine-phase tracker, a sentence saying what the live stage is doing, and the nine stages as a readable story. Expand any stage for the lookups it ran, the signals it formed, the vetoes it applied and the scoring table. The draft lands beside its hook, its claim ledger and its sources. |
| **Runs** | History and review in one place, because they answer one question: what has this thing done, and what does it still need from me. The figures across every run, four charts, the drafts still waiting on a person, and a sortable, filterable table. Any row opens the review sheet. |
| **Scenarios** | Five happy paths and five edge cases, each naming the outcome it should produce. One click runs any of them. |
| **Rules & policy** | What every prospect is checked against, the scoring rubric with its live thresholds, the role-weight matrix, the guardrail categories, and what each of the seven outcomes means. |
| **How it works** | The system written as a document, with five diagrams drawn from the code. For the reader who will never open the Runs page. |

Anywhere in the app, **Ctrl/Cmd+K** opens a command bar that jumps to any page
or launches any prepared case by name.

## The interface

A console, not a document. Dark by default — this is a screen someone keeps
open all day — with a complete light twin, remembered per browser and falling
back to the operating system's preference until a choice is made.

| | Dark | Light |
|---|---|---|
| base | `#0e1012` | `#f3f4f5` |
| surface → raised → overlay | `#15181b` → `#1b1f23` → `#22272b` | `#ffffff` → `#f7f8f8` → `#ffffff` |
| hairline | `rgba(255,255,255,.085)` | `rgba(14,16,18,.10)` |
| text | `#e6e9ea` / `#a4acb2` / `#6f777d` | `#14171a` / `#4c545b` / `#767e85` |
| accent | `#a3e635` | `#a3e635` fill, `#4d7c0f` as text |

Six decisions worth naming:

**Dark first, not dark as a toggle.** The tools people keep open all day are
designed dark and adapted to light, not the other way round, and it shows in
which theme looks accidental. Light here is a second full set of tokens, not an
inversion — the twelve surface, line and text tokens are all redefined.

**The base is a soft cool grey, never `#000`.** Pure black under ~90% white
text haloes badly in a long sitting, so body text sits at `#e6e9ea` on
`#0e1012` rather than `#fff` on black.

**Depth is elevation, not shadow.** Four surfaces, each a few per cent lighter
than the one beneath, with a hairline only where two surfaces of equal weight
meet. Shadows are the weakest depth signal on a dark ground and are used
nowhere.

**One accent, and it means one thing.** Lime appears on the page you are on,
the primary action and the focus ring. It keeps the same hex in both themes
because it is the identity; where lime-on-white would be unreadable, the token
for *text* darkens rather than the identity changing. Everything else is a
desaturated field, and the three outcome colours are the only other hues.

**Mono carries the machine.** Every label, id, query, score and timestamp is
Geist Mono, uppercased and letter-spaced. It is what makes a figure read as a
readout rather than as prose — and it is served from `/fonts`, because a graded
live demo should not be able to break on a CDN being slow.

**Nothing is a pill.** Radii are 4–10px; a fully-rounded control reads as
marketing rather than as a tool.

## How it works

```
prospect ──▶ intake ──▶ identity ──▶ harvest ──▶ interpret ──▶ guardrail
                           │                                       │
                     (can stop here)                         (can stop here)
                                                                   │
                            package ◀── verify ◀── draft ◀── score ┘
```

**Retrieval is separate from reasoning, and that is the main design decision.**
Evidence comes from connectors that return real URLs with real publication
dates — Google News RSS, Bing News RSS, Hacker News, and DuckDuckGo on a
best-effort basis. The model never searches and never produces a URL; it can
only reference evidence ids the connectors actually returned. A hallucinated
citation is therefore not possible, rather than merely discouraged.

*(Gemini's own `google_search` grounding tool returns 429 on a free-tier key, so
it was never an option here. It would also have been the weaker choice.)*

**Scoring is deterministic.** 100 points across recency (30), role relevance
(25), specificity (20), source quality (15) and actionability (10). The model
turns evidence into typed claims; it gets no vote on which claim wins. So the
same evidence always picks the same hook, a regression is visible, and "why this
one?" has an arithmetic answer the rep can audit — shown as a table in the
Scoring stage.

Role relevance is what makes the same company news produce different openers for
a CFO and a VP Engineering. `ROLE-A` and `ROLE-B` on the Scenarios page prove it:
byte-identical evidence, two job titles, **different winning hook** (funding 93
for finance, product 85 for engineering). The weight matrix is in
**Rules & policy**.

**Guardrails are vetoes, not tiebreakers.** Sensitivity is screened twice — a
keyword pass, then a model pass over whatever survives — and either firing is
enough. Anything older than 180 days is vetoed regardless of how strong it is.
A crisis story is deliberately allowed to score on its merits so the veto is
visibly the thing that removes it.

**Drafts are audited.** After generation, every checkable assertion in the email
is matched against the sources it was allowed to use. Unsupported statements
trigger one rewrite naming the offending sentences; if it still fails, the run is
marked for manual review rather than shipping an unverifiable claim. A separate
deterministic style pass catches the clichés, the wall-of-text paragraph and the
missing sign-off that a prompt alone does not reliably prevent.

**Halting is gated.** Telling a rep their CRM is wrong produces no draft, so a
departure verdict halts the run only when the model is confident *and* cited the
source it relied on. The job-move probe searches for "joins / steps down"
language unscoped to the company, which means it reliably surfaces unrelated
namesakes; an uncorroborated departure degrades to a warning and the run
continues on company-level hooks. The gate's arithmetic is shown in the Identity
stage detail.

## Outcomes

| Status | Meaning |
|---|---|
| `ready_for_review` | Grounded draft. Every claim ties to a source. |
| `fallback_company_signal` | Top signal was vetoed; a weaker safe hook was used. Confidence reduced. |
| `needs_manual_research` | Nothing citable and recent enough. No hook invented. |
| `blocked_sensitive` | Every signal was a crisis story. Nothing drafted. |
| `flagged_job_change` | Sources place the prospect elsewhere. Fix the CRM first. |
| `needs_disambiguation` | More than one person matches the name. |

## The scenarios

| Case | Sources | Tests |
|---|---|---|
| `HAPPY-01` rich live signal | live | The happy path, on a well-covered real company |
| `HAPPY-02` same company, finance role | live | Role weights move on identical live evidence |
| `HAPPY-03` second live company | live | Breadth, and insurance if one company goes quiet |
| `ROLE-A` / `ROLE-B` | replay | **The controlled proof.** Identical evidence, two titles, different winning hook |
| `EDGE-01` no public signal | replay | Declines instead of inventing a hook |
| `EDGE-02` only stale signals | replay | Recency veto bites a strong 65/100 funding signal |
| `EDGE-03` prospect changed jobs | replay | Halts at identity, before spending the scrape |
| `EDGE-04` company in crisis | replay | Layoffs score highest (83) and are vetoed anyway |
| `EDGE-05` name collision | replay | Asks the rep rather than guessing between two matches |

`python -m tools.run_cases` runs all ten and asserts both the status and the
behavioural invariants behind it — that EDGE-04's chosen hook is *not* the
top-scoring signal, that EDGE-03 never reached the harvest stage, that every
draft citation resolves to retrieved evidence. Live cases are asserted loosely
(today's news decides which healthy outcome is right); replay cases are exact.

Happy paths run live. The replay cases use a fixture corpus in
`backend/fixtures.py`, because you cannot summon a job change or a layoff round
from today's news on demand during a live demo. Fixture evidence is tagged
`REPLAY` everywhere it appears, so nothing synthetic is passed off as real, and
the companies in it are fictional — attaching an invented lawsuit to a real
company would be defamatory. Every persona is labelled `real person` or
`synthetic` on the Scenarios page; real people are never attributed to roles they
do not hold.

## Source modes

- **Auto** — live connectors, fixture corpus only if live returns nothing.
- **Live only** — real sources, no fallback. A prospect with no footprint returns nothing.
- **Replay** — deterministic corpus. Reproducible, works with no network.

## Deploying it

The repo carries a Render blueprint. In the Render dashboard: **New → Blueprint**,
point it at this repo, and the one field to fill in is `GEMINI_API_KEY`.
Everything else — Python version, build and start commands, the health check —
comes from [`render.yaml`](render.yaml).

Deploying by hand instead of by blueprint needs exactly two settings:

```
Build command:  pip install -r requirements.txt
Start command:  uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1
```

Three things about a hosted instance that are worth knowing before a live demo:

**One worker, deliberately.** A run streams its stages over SSE from an
in-memory channel. A second worker is a second process with its own channels,
and a browser that connects to the wrong one watches a run that never
progresses. Scale by instance, never by worker, unless that buffer moves to
Redis first.

**The free filesystem is ephemeral.** `runs.db` is wiped on every deploy and
every restart, so the history starts empty — rebuild it by running the prepared
cases, which takes a couple of minutes. To keep it, uncomment the disk block in
`render.yaml`, which also sets `DB_PATH`; that needs a paid instance.

**A free instance sleeps after 15 minutes idle** and takes roughly 50 seconds to
wake. Open the URL a few minutes before anyone is watching.

Everything else travels: there is no build step, no CDN at render time, and the
typeface is served from `/fonts` by the app itself.

## Layout

```
backend/
  config.py      policy knobs, seller profile, model chain
  sources.py     connectors + query planning + dedupe
  fixtures.py    prepared cases + replay corpus
  guardrails.py  sensitivity (regex + model), recency, identity
  scoring.py     the deterministic rubric
  drafting.py    interpret / write / verify / style audit
  pipeline.py    the 9-stage orchestrator
  store.py       SQLite run history
  main.py        API + SSE
  llm.py         Gemini REST client with a model fallback chain
render.yaml    the deployment blueprint
frontend/
  index.html     five panels, one visible at a time
  styles.css     both themes, as tokens; no CDN, no build step
  app.js         pages, the theme, the command bar, every renderer
  uml.js         the diagram vocabulary
  how.js         the five figures on How it works
  fonts/         Geist Mono, self-hosted
tools/
  run_cases.py   the regression suite
```

## Notes

- `GEMINI_MODELS` is a fallback chain, not one model. Free-tier Gemini returns
  503 and 404 often enough that a single model makes the demo flaky.
- Runs take 20–50s live. Most of that is the model; the stage story exists so the
  wait is legible instead of a spinner.
- DuckDuckGo throttles scraped traffic and answers `202` or `403`, so it is
  best-effort and a run never depends on it.
- Interpretation retries once on an empty result. Roughly one call in four over
  ~50 news items came back with an empty array, which turned a healthy happy
  path into a false `needs_manual_research`. A refusal has to be earned, so the
  step retries before declaring one — and the Interpretation stage detail shows
  the raw-vs-kept counters either way.
- Verified stable across five consecutive full-suite passes (50 case runs),
  identical statuses, confidence within ±5%.
- `runs.db` and `.env` are gitignored.
- **Rotate the Gemini key before sharing this repo** — the one in `.env` was
  pasted into a chat and should be treated as exposed.
