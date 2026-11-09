/* ==========================================================================
   "How it works" - five diagrams.

   Written against the code as it is: the stage names come from `pipeline.py`,
   the floors and the halt threshold from `config.py`, so when one of those
   changes the diagram documenting it is the thing to change with it.

   Five, not fifteen. A page that documents a system in every notation it can
   think of teaches nobody anything; these answer the five questions people
   actually arrive with - what does it decide, how does it get there, why does
   it check the person first, how is the hook picked, and what stops it making
   things up. Each is one shape, small enough to take in at a glance.

   Built on the vocabulary in `uml.js`; see the note at the top of that file.
   ========================================================================== */
(function () {
  'use strict';

  const U = window.UML;

  /* ============================================== 1. what it decides ===== */

  function decides() {
    const W = 760;
    const H = 180;
    const y = 62;
    const h = 42;
    const mid = y + h / 2;          // 83
    let svg = '';

    svg += U.box(4, y, 108, h, 'Prospect', { sub: 'a name, a company', tone: 'in' });
    svg += U.arrow(116, mid, 144, mid);
    svg += U.box(148, y, 108, h, 'Research', { sub: 'live sources', tone: 'step' });
    svg += U.arrow(260, mid, 288, mid);
    svg += U.box(292, y, 108, h, 'Judge', { sub: 'score, then veto', tone: 'step' });
    svg += U.arrow(404, mid, 432, mid);
    svg += U.box(436, y, 100, h, 'Write', { sub: 'then audit it', tone: 'step' });

    /* The fork. Three ends, which is the whole decision. */
    const outs = [
      { label: 'Draft ready', sub: 'a rep reads and sends', y: 18, tone: 'approve' },
      { label: 'Needs a human', sub: 'and it says why', y: 64, tone: 'flag' },
      { label: 'Nothing drafted', sub: 'every hook was a crisis', y: 110, tone: 'reject' },
    ];
    outs.forEach((out) => {
      svg += U.arrow(540, mid, 568, out.y + 19);
      svg += U.box(572, out.y, 150, 38, out.label, { sub: out.sub, tone: out.tone });
    });

    /* What it is allowed to say, drawn once rather than as four arrows. */
    svg += U.box(280, 134, 160, 34, 'Retrieved sources',
      { sub: 'the only permitted facts', tone: 'ref' });
    svg += U.arrow(360, 132, 360, 108);

    return U.figure(
      'One prospect in, one of three answers out. The answer always arrives with the signal it '
      + 'was built on, the score that chose it, and the source every sentence came from.',
      { svg: svg, width: W, height: H });
  }

  /* ================================================ 2. the nine stages === */

  function stages() {
    const W = 760;
    const BX = 30;
    const BW = 186;
    const BH = 30;
    const GAP = 42;
    const TOP = 8;

    const rows = [
      ['Intake', 'Validate the record and bucket the job title into a weight table.'],
      ['Identity check', 'Person-level lookups only. Can stop the run before anything else runs.'],
      ['Signal harvest', 'Company-level intents across the connectors, then deduplicated.'],
      ['Interpretation', 'Documents become typed claims, each carrying its source ids.'],
      ['Safety & recency', 'Crisis categories vetoed outright; anything past 180 days dropped.'],
      ['Scoring', 'Five components out of 100 pick the hook and explain the margin.'],
      ['Drafting', 'One short email built from exactly one permitted fact.'],
      ['Grounding audit', 'Every sentence checked back against its source; failures rewrite.'],
      ['Packaging', 'Status, confidence and the review bundle a human acts on.'],
    ];

    let svg = '';
    rows.forEach((row, i) => {
      const y = TOP + i * GAP;
      svg += U.num(14, y + BH / 2, i + 1);
      svg += U.box(BX, y, BW, BH, row[0], { tone: 'step' });
      svg += U.text(BX + BW + 18, y + BH / 2 + 4, row[1], 'dg-say');
      if (i < rows.length - 1) svg += U.thin(BX + BW / 2, y + BH, BX + BW / 2, y + GAP);
    });

    return U.figure(
      'The same nine stages, in the same order, for every prospect. Stage 2 is the one that '
      + 'halts outright; stages 3 to 6 each end the run if the thing they are looking for is '
      + 'not there, and stage 8 can send the draft back to be rewritten once. Everything after '
      + 'a stop is marked skipped rather than failed, because the work was deliberately not done.',
      { svg: svg, width: W, height: TOP + rows.length * GAP, min: 700 });
  }

  /* =========================================== 3. the identity gate ====== */

  function identity() {
    const W = 760;
    const H = 152;
    const y = 56;
    const h = 42;
    const mid = y + h / 2;          // 77
    let svg = '';

    svg += U.box(4, y, 116, h, 'Prospect', { sub: 'name + stated role', tone: 'in' });
    svg += U.arrow(124, mid, 152, mid);
    svg += U.box(156, y, 132, h, 'Person lookups', { sub: 'joins / steps down', tone: 'step' });
    svg += U.arrow(292, mid, 320, mid);
    svg += U.box(324, y, 124, h, 'Verdict', { sub: 'model, must cite', tone: 'model' });
    svg += U.arrow(452, mid, 480, mid);
    svg += U.box(484, y, 120, h, 'Confident?', { sub: '70% + a source', tone: 'decide' });

    svg += U.arrow(608, mid, 628, 37);
    svg += U.text(600, 42, 'yes', 'dg-l-left');
    svg += U.box(632, 18, 124, 38, 'Halt the run',
      { sub: 'the CRM is wrong', tone: 'reject' });

    svg += U.arrow(608, mid, 628, 119);
    svg += U.text(600, 122, 'no', 'dg-l-left');
    svg += U.box(632, 100, 124, 38, 'Warn, continue',
      { sub: 'company-level hooks', tone: 'flag' });

    return U.figure(
      'The departure probe searches unscoped language, so it reliably surfaces unrelated '
      + 'namesakes. A halt therefore needs a confident verdict that names a specific source; '
      + 'anything weaker degrades to a warning and the run goes on. Telling a rep their CRM is '
      + 'wrong is expensive, and being wrong about it is worse.',
      { svg: svg, width: W, height: H });
  }

  /* ============================================= 4. how a hook wins ===== */

  function scoring() {
    const W = 760;
    const H = 152;
    const y = 62;
    const h = 42;
    const mid = y + h / 2;          // 83
    let svg = '';

    svg += U.box(4, y, 104, h, 'Documents', { sub: 'what was retrieved', tone: 'in' });
    svg += U.arrow(112, mid, 140, mid);
    svg += U.box(144, y, 124, h, 'Typed claims', { sub: 'model, must cite', tone: 'model' });

    const parts = [
      'Recency /30', 'Role fit /25', 'Specificity /20', 'Source /15', 'Actionability /10',
    ];
    parts.forEach((part, i) => {
      const py = 8 + i * 27;
      svg += U.thin(268, mid, 296, py + 11);
      svg += U.box(300, py, 132, 22, part, { tone: 'ref' });
      svg += U.thin(432, py + 11, 460, mid);
    });

    svg += U.box(464, y, 96, h, 'Total /100', { sub: 'arithmetic', tone: 'step' });
    svg += U.arrow(564, mid, 592, mid);
    svg += U.box(596, y, 96, h, 'Floor', { sub: '55 or 62', tone: 'decide' });
    svg += U.arrow(696, mid, 716, mid);
    svg += U.box(720, y, 36, h, 'Hook', { tone: 'approve' });

    return U.figure(
      'The model forms the candidates; it does not choose between them. Five deterministic '
      + 'components do, so identical evidence always picks the same hook and the margin is '
      + 'auditable. Role fit is the component that does the interesting work - the same funding '
      + 'round is worth 25 points to a finance title and 17 to an engineering one.',
      { svg: svg, width: W, height: H, min: 720 });
  }

  /* ====================================== 5. what stops it inventing ==== */

  function verify() {
    const W = 760;
    const H = 178;
    const y = 60;
    const h = 40;
    const mid = y + h / 2;          // 80
    let svg = '';

    svg += U.box(4, y, 96, h, 'The hook', { sub: 'one fact', tone: 'in' });
    svg += U.arrow(104, mid, 132, mid);
    svg += U.box(136, y, 116, h, 'Draft', { sub: 'model writes', tone: 'model' });
    svg += U.arrow(256, mid, 284, mid);
    svg += U.box(288, y, 132, h, 'Audit every claim', { sub: 'against the sources', tone: 'step' });
    svg += U.arrow(424, mid, 452, mid);
    svg += U.box(456, y, 112, h, 'All sourced?', { tone: 'decide' });

    svg += U.arrow(572, mid, 592, 35);
    svg += U.text(566, 40, 'yes', 'dg-l-left');
    svg += U.box(596, 16, 160, 38, 'Ready for review',
      { sub: 'every claim cited', tone: 'approve' });

    svg += U.arrow(572, mid, 592, 119);
    svg += U.text(566, 124, 'no', 'dg-l-left');
    svg += U.box(596, 100, 160, 38, 'Rewrite once',
      { sub: 'then hold for a human', tone: 'flag' });

    /* The loop back into drafting - one pass, not an indefinite retry. */
    svg += U.elbow('M596 138 L570 138 L570 162 L194 162 L194 102', 'one repair pass', 380, 158);

    return U.figure(
      'Writing is the only stage that produces prose a person will read, so it is the only one '
      + 'whose output is audited rather than trusted. A sentence that cannot be traced to a '
      + 'retrieved document triggers a rewrite; a second failure holds the run for manual '
      + 'research rather than sending something merely plausible.',
      { svg: svg, width: W, height: H });
  }

  const FIGURES = { decides, stages, identity, scoring, verify };

  /** Fill every `data-uml="name"` slot on the How-it-works page. Called once
   *  on boot: the figures are static, so nothing redraws them. */
  function renderDiagrams(root) {
    U.resetFigures();
    Array.from((root || document).querySelectorAll('[data-uml]')).forEach((slot) => {
      const fn = FIGURES[slot.dataset.uml];
      slot.innerHTML = fn ? fn() : '';
    });
  }

  window.HOW = { renderDiagrams };
})();
