# Demo runbook

Two things to deliver: a 5-minute video and a live run in the interview. Same
material, different pacing. Everything below has been rehearsed against the
actual build — the timings are measured, not estimated.

## Before you record or present

```powershell
.\run.ps1                          # http://127.0.0.1:8000
python -m tools.run_cases --quiet   # 10/10 expected, ~3 min
```

Run the suite first. It both proves the build works and seeds the Runs page,
so it isn't empty on camera. Then open the browser, click the status pill in the
top right and check the four connectors are green, and clear the history if you
want a clean table (`Clear run history`, under the table on Runs). Pick the
theme you are recording in before you start — Ctrl/Cmd+K, then "theme".

If a source dot is red: DuckDuckGo throttles and is marked best-effort, so a run
survives without it. If **both** news connectors are red you have no network —
switch **Draft outreach** to `Replay` and present the five edge cases, which
need no network at all.

## The 5-minute video

| Time | What's on screen | What you say |
|---|---|---|
| 0:00–0:30 | Draft, empty | The problem in one line: an SDR with 200 prospects can't research each one, so they don't, and reply rates show it. This takes a prospect and produces a draft grounded in something real, with a human reviewing before anything sends. |
| 0:30–1:45 | Run `HAPPY-01` | Narrate the tracker and the stage story as they move. Identity confirms he's in the seat. Harvest pulls ~50 real items across three connectors. Interpretation turns them into competing typed claims. Then open the **Scoring** stage — this is the money shot. Five components, 100 points, and the margin plus the component that decided it. |
| 1:45–2:30 | Same run, Draft + Claim ledger | Open the draft. Point at the highlighted sentence: that's the hook, and it traces to a source. Then the claim ledger — every factual assertion matched against the source that supports it. Say plainly: the model never produces a URL, so it can't invent a citation. |
| 2:30–3:30 | Run `EDGE-04` | The guardrail case. The layoff story is the freshest, most specific, best-sourced item and scores **83 — highest in the set**. It gets vetoed anyway, and the process falls back to a weaker safe hook at 66. Status reads `Fallback used`, confidence drops to 71%. The point: the guardrail is a veto, not a tiebreaker. |
| 3:30–4:15 | Run `EDGE-01`, then `EDGE-03` | Two refusals. EDGE-01: nothing citable, so it declines rather than inventing a hook. EDGE-03: the prospect left three weeks ago, so it halts at identity before spending the scrape — and the departure claim had to cite a source to be allowed to halt. |
| 4:15–5:00 | Runs | The worklist of everything the desk has done, filtered to what is waiting on a person, then select one: editable subject and body on the left with its claim ledger and sources beneath, the hook and every rejected candidate on the right, Approve / Save edit / Reject. Close on the honest line: nothing here sends mail. Approving records that a human cleared it. |

Keep `HAPPY-01` and `EDGE-04` if you have to cut. They carry the two ideas that
matter: explained selection, and a guardrail that actually changes the outcome.

## Live interview order

Run these in sequence. Each one answers a question they're likely to ask next.

1. **`HAPPY-01`** — the happy path. Expand Scoring and Claim ledger.
2. **`ROLE-A` then `ROLE-B`** — the controlled proof. Identical evidence, two job
   titles, **different winning hook** (funding 93 vs product 85). Fast, both
   replay, no network risk. This is the strongest single thing in the build:
   it shows the rubric does real work rather than decorating one model guess.
3. **`EDGE-04`** — the guardrail biting a top-scoring signal.
4. **`EDGE-02`** — recency. A 65/100 funding signal vetoed purely for being
   742 days old. Referencing a two-year-old round is worse than saying nothing.
5. **`EDGE-05`** — two people, one name. It asks instead of guessing.
6. **Rules & policy page** — if they ask "how would I change this?", the role
   weight matrix and the guardrail list are right there, and editable in
   `config.py`.

Runs take 20–50s live. Don't talk over silence — use the stage story. Say what the
stage is doing while it does it.

## Questions you should expect

**"How do you know it isn't making things up?"**
Retrieval is separate from reasoning. Connectors fetch evidence with real URLs
and real dates; the model only ever references evidence ids those connectors
returned. It is structurally unable to produce a URL. Then every assertion in
the finished draft is re-checked against its source, and an unsupported one
triggers a rewrite naming the offending sentence. Show the claim ledger.

**"Why not let the model search?"**
Two reasons. The practical one: Gemini's grounding tool returns 429 on this key.
The real one: if the model does the searching, it also authors the citations,
and you lose the one guarantee worth having. Separating them is the better
design regardless of quota.

**"Why is the scoring not done by the LLM?"**
Then "why this hook?" has no auditable answer and the same input gives different
answers on different days. As built, it's 100 points across five components, so a
rep can argue with the weights and a regression is visible. The model does the
part it's good at — turning messy text into typed claims — and gets no vote on
which claim wins.

**"What happens when it's wrong?"**
It's designed to be wrong in the cheap direction. Both sensitivity screens are
unions, not votes, so a false positive costs one hook and a false negative costs
the client a customer. Score floors mean it declines rather than personalising on
something weak. And the departure gate exists because the job-move probe
reliably surfaces namesakes — an uncorroborated departure claim degrades to a
warning instead of halting, which you can see in the Identity stage detail.

**"Is the data real?"**
Happy paths are live against real news. The five edge cases use a fixture corpus
at **fictional** companies — you can't summon a job change or a layoff round from
today's news on demand, and attaching an invented lawsuit to a real company
would be defamatory. Fixture evidence is badged `REPLAY` everywhere it appears,
and the Scenarios page labels every persona `real person` or `synthetic`.

**"What would you build next?"**
Honest answer, in order: (1) outcome feedback — log replies against the hook
kind and score band, then tune the weights on data instead of judgement;
(2) a CRM write-back so `flagged_job_change` fixes the record that caused it;
(3) per-sender tone calibration from a rep's sent folder; (4) batch mode over a
CSV with a review queue, since the per-prospect UI is the demo shape, not the
production shape.

## Known limits — say these before you're asked

- DuckDuckGo throttles scraped traffic, so it's best-effort and often returns
  zero. The news connectors carry the run.
- 20–50s per run, mostly model latency. Batch would need concurrency.
- The identity screen returns `unconfirmed` for most prospects, because most
  people aren't in the news. That's correct, and it's why company-level hooks
  exist rather than a failure.
- Free-tier Gemini throws 503 often enough that `llm.py` walks a three-model
  fallback chain. A single model made the demo flaky.
- No auth, single user, SQLite. It's an internal console, not a product.
