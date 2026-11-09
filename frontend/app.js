/* ==========================================================================
   Outreach Desk - PS-3, prospect to draft.

   Six pages, no build step, no framework. Plain DOM on purpose: the point of
   this screen is that an interviewer can watch the backend think, so there is
   as little as possible between the event stream and the pixels.

   The file is laid out in the order the app is used: utilities, navigation,
   the reference data every page needs, then the run view, the dashboard, the
   review queue, the scenarios, the policy page, and the boot sequence.
   ========================================================================== */
(function () {
  'use strict';

  /* ==================================================== utilities ======= */

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const esc = (value) =>
    String(value == null ? '' : value).replace(/[&<>"']/g, (c) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  const plain = (value) => (value == null || value === '' ? '&mdash;' : esc(value));

  const duration = (msv) => {
    if (msv == null) return '';
    return msv < 1000 ? `${msv}ms` : `${(msv / 1000).toFixed(1)}s`;
  };

  function ago(iso) {
    const t = new Date(iso).getTime();
    if (!t) return '—';
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return `${Math.floor(s)}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  const host = (u) => {
    try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return ''; }
  };

  const words = (text) => String(text || '').trim().split(/\s+/).filter(Boolean).length;

  /** Every call to the backend goes through here, so a failure is reported
   *  once, in the same way, instead of each caller inventing its own. */
  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: options.body ? { 'Content-Type': 'application/json' } : {},
      ...options,
    });
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        if (payload && payload.detail) detail = payload.detail;
      } catch { /* the status line is the best we have */ }
      throw new Error(detail);
    }
    return response.json();
  }

  let toastTimer = null;
  function toast(message, isError = false) {
    const node = $('#toast');
    node.textContent = message;
    node.classList.toggle('is-err', !!isError);
    node.classList.add('is-on');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => node.classList.remove('is-on'), 3200);
  }

  /* A hover note on anything carrying data-tip. One node, moved around, so a
     table of fifty rows does not mean fifty absolutely-positioned divs. */
  const tipNode = $('#tooltip');
  function bindTooltips(root) {
    $$('[data-tip]', root).forEach((node) => {
      node.addEventListener('mouseenter', () => {
        tipNode.innerHTML = node.dataset.tip;
        tipNode.hidden = false;
        const box = node.getBoundingClientRect();
        const tip = tipNode.getBoundingClientRect();
        let left = box.left + box.width / 2 - tip.width / 2;
        left = Math.max(8, Math.min(left, window.innerWidth - tip.width - 8));
        let top = box.top - tip.height - 9;
        if (top < 8) top = box.bottom + 9;
        tipNode.style.left = `${left}px`;
        tipNode.style.top = `${top}px`;
      });
      node.addEventListener('mouseleave', () => { tipNode.hidden = true; });
    });
  }

  /* ============================================ the seven outcomes ======
     Each status maps onto one of three tones - something to send, something
     for a human, or nothing at all - and says in words what the rep does
     next. The tone is what the colour is allowed to carry; the difference
     between the four "needs a human" endings is carried by the label. */

  const STATUS = {
    running: {
      label: 'Running', tone: 'idle', glyph: '·',
      line: 'Working through the nine stages.',
      next: '',
    },
    ready_for_review: {
      label: 'Ready for review', tone: 'approve', glyph: '✓',
      line: 'A grounded draft, built on one sourced fact.',
      next: 'Read it, edit if you want to, and send it from your own tool.',
    },
    fallback_company_signal: {
      label: 'Fallback hook used', tone: 'flag', glyph: '⇄',
      line: 'The best signal was vetoed, so a weaker but safe one was used.',
      next: 'Readable and sendable, but worth a closer look - confidence is reduced to match.',
    },
    needs_manual_research: {
      label: 'Needs manual research', tone: 'flag', glyph: '⚑',
      line: 'Nothing citable and recent enough was found.',
      next: 'No hook was invented. Research this one by hand, or drop it.',
    },
    blocked_sensitive: {
      label: 'Blocked: sensitive', tone: 'reject', glyph: '⊘',
      line: 'Every available signal was a crisis story.',
      next: 'Nothing was drafted, deliberately. Come back when the news moves on.',
    },
    flagged_job_change: {
      label: 'Flagged: job change', tone: 'flag', glyph: '⚐',
      line: 'Sources place this person somewhere else.',
      next: 'The CRM record is wrong. Fix it before any outreach goes out.',
    },
    needs_disambiguation: {
      label: 'Needs disambiguation', tone: 'flag', glyph: '?',
      line: 'More than one person matches this name.',
      next: 'Confirm which one - a LinkedIn URL or a domain is enough - then re-run.',
    },
    error: {
      label: 'Error', tone: 'reject', glyph: '!',
      line: 'The run failed before it reached an answer.',
      next: 'The stage that failed is marked below.',
    },
  };

  const statusOf = (key) => STATUS[key] || {
    label: key || '—', tone: 'idle', glyph: '·', line: '', next: '',
  };

  const TONE_BADGE = { approve: 'badge-approve', flag: 'badge-flag', reject: 'badge-reject', idle: '' };

  const badge = (key) => {
    const s = statusOf(key);
    return `<span class="badge ${TONE_BADGE[s.tone]}">${esc(s.label)}</span>`;
  };

  /* Which chip on the dashboard a status answers to. */
  const FAMILY = {
    ready_for_review: 'READY',
    fallback_company_signal: 'HUMAN',
    needs_manual_research: 'HUMAN',
    flagged_job_change: 'HUMAN',
    needs_disambiguation: 'HUMAN',
    blocked_sensitive: 'BLOCKED',
    error: 'BLOCKED',
    running: 'HUMAN',
  };

  /* A status that produced something a person can read. */
  const HAS_DRAFT = new Set(['ready_for_review', 'fallback_company_signal']);

  const REVIEW = {
    pending: { label: 'Pending', cls: '' },
    approved: { label: 'Approved', cls: 'badge-approve' },
    edited: { label: 'Edited', cls: 'badge-accent' },
    rejected: { label: 'Rejected', cls: 'badge-reject' },
  };
  const reviewBadge = (key) => {
    const r = REVIEW[key] || REVIEW.pending;
    return `<span class="badge ${r.cls}">${r.label}</span>`;
  };

  const meter = (pct, tone) => {
    const value = Math.max(0, Math.min(100, Number(pct) || 0));
    const cls = tone || (value >= 75 ? 'is-ok' : value >= 50 ? 'is-warn' : 'is-bad');
    return `<span class="meter"><span class="mbar ${cls}"><span style="width:${value}%"></span></span>`
      + `<span class="pct">${value}</span></span>`;
  };

  /* ==================================================== state =========== */

  const state = {
    config: null,
    cases: [],
    runs: [],
    stats: null,
    health: null,
    mode: 'auto',
    activeCase: null,

    /* the live run */
    runId: null,
    run: null,
    stageByKey: {},
    lookups: [],
    streaming: false,
    startedAt: 0,
    ticker: null,
    source: null,
    openStages: new Set(),
    storyFolded: false,

    /* the dashboard table */
    filter: 'ALL',
    search: '',
    sortKey: 'created_at',
    sortDir: 'desc',

    /* the queue */
    qfilter: 'pending',

    /* the sheet */
    sheetRun: null,
    sheetOpenStages: new Set(),
  };

  /* ==================================================== navigation ======
     Six panels, one visible at a time, the hash as the address so a page
     survives a reload mid-demo. */

  /* Five pages. History, the figures and the review queue are one page
     rather than two, because they answer one question: what has this thing
     done, and what does it still need from me. */
  const TABS = ['run', 'runs', 'cases', 'policy', 'how'];
  const TAB_NAMES = {
    run: 'Draft outreach', runs: 'Runs', cases: 'Scenarios',
    policy: 'Rules & policy', how: 'How it works',
  };

  function showTab(name) {
    const tab = TABS.includes(name) ? name : 'run';
    $$('.tab').forEach((link) => link.classList.toggle('is-active', link.dataset.tab === tab));
    $$('.panel').forEach((panel) => panel.classList.toggle('is-active', panel.id === `panel-${tab}`));
    if (location.hash !== `#${tab}`) history.replaceState(null, '', `#${tab}`);
    window.scrollTo({ top: 0, behavior: 'auto' });
    if (tab === 'runs') loadRuns().then(loadQueue);
  }

  $$('.tab').forEach((link) => {
    link.addEventListener('click', () => showTab(link.dataset.tab));
  });

  /* Anything anywhere can send the user to a page by carrying data-goto. */
  document.addEventListener('click', (event) => {
    const go = event.target.closest('[data-goto]');
    if (go) showTab(go.dataset.goto);
  });

  window.addEventListener('hashchange', () => showTab(location.hash.replace('#', '')));

  /* ----- the theme ---------------------------------------------------------
     Dark is the default because this is a screen someone keeps open all day;
     the choice is remembered, and until one is made the operating system
     decides. The inline script in the document head applies the saved value
     before the first paint, so a reload never flashes the wrong theme. */

  const systemTheme = () =>
    (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');

  const currentTheme = () =>
    document.documentElement.getAttribute('data-theme') || systemTheme();

  function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('od-theme', theme); } catch { /* private mode */ }
    const btn = $('#theme-btn');
    btn.textContent = theme === 'dark' ? '\u25D0' : '\u25D1';
    btn.title = theme === 'dark' ? 'Switch to light' : 'Switch to dark';
  }

  const toggleTheme = () => setTheme(currentTheme() === 'dark' ? 'light' : 'dark');

  $('#theme-btn').addEventListener('click', toggleTheme);

  /* ----- back to top ------------------------------------------------------ */

  const toTop = $('#to-top');
  toTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  window.addEventListener('scroll', () => {
    toTop.classList.toggle('is-on', window.scrollY > 520);
  }, { passive: true });

  /* ----- the status popover --------------------------------------------- */

  const envBtn = $('#env-btn');
  envBtn.addEventListener('click', (event) => {
    event.stopPropagation();
    const pop = $('#env-pop');
    pop.hidden = !pop.hidden;
    envBtn.setAttribute('aria-expanded', String(!pop.hidden));
  });
  document.addEventListener('click', (event) => {
    if (!event.target.closest('.nav-right')) {
      $('#env-pop').hidden = true;
      envBtn.setAttribute('aria-expanded', 'false');
    }
  });

  async function loadHealth() {
    let health;
    try {
      health = await api('/api/health?deep=true');
    } catch {
      $('#env-dot').className = 'dot dot-bad';
      $('#env-label').textContent = 'offline';
      $('#env-pop').innerHTML = '<div class="pop-row is-bad"><span class="dot dot-bad"></span>'
        + '<span class="k">backend unreachable</span></div>';
      return;
    }
    state.health = health;

    const model = health.model || {};
    const connectors = health.connectors || {};
    const names = Object.keys(connectors);
    const live = names.filter((n) => connectors[n].ok);
    const modelOk = model.ok !== false && health.api_key_present;

    $('#env-dot').className = `dot ${modelOk && live.length ? 'dot-ok' : live.length ? '' : 'dot-bad'}`;
    $('#env-label').textContent = `${live.length}/${names.length || 0} src`;

    const llm = health.llm || {};
    const rows = [];
    rows.push('<span class="lbl">Model</span>');
    rows.push(`<div class="pop-row ${modelOk ? '' : 'is-bad'}">
      <span class="dot ${modelOk ? 'dot-ok' : 'dot-bad'}"></span>
      <span class="k">${esc(model.model || llm.last_model || 'gemini')}</span>
      <span class="v">${modelOk ? 'live' : esc(model.detail || 'no key')}</span></div>`);
    rows.push(`<div class="pop-row"><span class="dot"></span>
      <span class="k">calls this session</span>
      <span class="v">${llm.calls || 0} · ${llm.failures || 0} failed</span></div>`);

    rows.push('<div class="sub"><span class="lbl">Connectors</span>');
    names.forEach((name) => {
      const c = connectors[name];
      rows.push(`<div class="pop-row ${c.ok ? '' : 'is-bad'}">
        <span class="dot ${c.ok ? 'dot-ok' : 'dot-bad'}"></span>
        <span class="k">${esc(name.replace(/_/g, ' '))}</span>
        <span class="v">${c.ok ? 'ok' : esc(String(c.detail || 'failed').split(':')[0])}</span></div>`);
    });
    rows.push('</div>');
    rows.push(`<div class="sub"><span class="lbl">Source mode</span>
      <div class="pop-row"><span class="dot"></span>
      <span class="k">default for a new run</span>
      <span class="v">${esc(health.source_mode || 'auto')}</span></div></div>`);

    $('#env-pop').innerHTML = rows.join('');
    renderConnectorStrip();
  }

  function renderConnectorStrip() {
    const node = $('#connectors-strip');
    const health = state.health;
    if (!node || !health) return;
    const connectors = health.connectors || {};
    const names = Object.keys(connectors);
    if (!names.length) { node.innerHTML = ''; return; }
    node.innerHTML = `
      <div class="strip-head">
        <h3>Where the signal comes from</h3>
        <span class="strip-note">Checked live. A connector that fails degrades its stage and the
          run carries on with what the others returned.</span>
      </div>
      <div class="strip-list">
        ${names.map((name) => {
          const c = connectors[name];
          return `<span class="strip-item ${c.ok ? '' : 'is-bad'}">
            <span class="dot ${c.ok ? 'dot-ok' : 'dot-bad'}"></span>
            <b>${esc(name.replace(/_/g, ' '))}</b>
            ${c.ok ? '' : esc(String(c.detail || 'failed').split(':')[0])}</span>`;
        }).join('')}
      </div>`;
  }

  /* ==================================================== the nine stages ==
     The copy that turns a list of machine stages into something readable:
     one short name for the tracker, and one sentence saying what the stage is
     for. The sentence is written in the present tense because it is shown
     both before the stage runs and after it has. */

  const STAGE_COPY = {
    intake: {
      short: 'Intake',
      say: 'Check the record is usable, and decide which weight table will score the hook.',
    },
    identity: {
      short: 'Identity',
      say: 'Confirm this person still holds the seat, and that the name belongs to only one of them.',
    },
    harvest: {
      short: 'Harvest',
      say: 'Ask every connector what has actually happened at this company lately.',
    },
    interpret: {
      short: 'Interpret',
      say: 'Turn the retrieved documents into typed claims, each one tied to the source it came from.',
    },
    guardrail: {
      short: 'Screen',
      say: 'Veto anything sensitive, and drop anything too old to be worth mentioning.',
    },
    score: {
      short: 'Score',
      say: 'Score every surviving claim on five components, and pick the one hook to use.',
    },
    draft: {
      short: 'Draft',
      say: 'Write a short email built on exactly one permitted fact.',
    },
    verify: {
      short: 'Audit',
      say: 'Check every sentence in the draft back against the source it is supposed to rest on.',
    },
    package: {
      short: 'Package',
      say: 'Set the status and the confidence, and bundle the result for a human.',
    },
  };

  const stageCopy = (key) => STAGE_COPY[key] || { short: key, say: '' };

  const STATE_CLASS = {
    pending: 'is-pending', active: 'is-active', done: 'is-done', warn: 'is-warn',
    blocked: 'is-blocked', skipped: 'is-skipped', error: 'is-error',
  };
  const STATE_GLYPH = {
    done: '✓', warn: '!', blocked: '⊘', error: '✕', skipped: '–', active: '', pending: '',
  };
  const STATE_TAG = {
    active: ['is-live', 'running'], warn: ['is-warn', 'degraded'],
    blocked: ['is-stop', 'stopped here'], error: ['is-stop', 'failed'],
    skipped: ['is-skip', 'skipped'],
  };

  /* ==================================================== reference data === */

  const MODE_HELP = {
    auto: 'Live connectors first; the fixture corpus only if nothing comes back. This is the '
      + 'mode a real deployment runs in.',
    live: 'Real sources only. A prospect with no public footprint will correctly return nothing.',
    replay: 'The deterministic fixture corpus. Reproducible, offline, and the only way to run the '
      + 'controlled A/B cases.',
  };

  function setMode(mode) {
    state.mode = mode;
    $$('#mode-seg button').forEach((b) => b.classList.toggle('is-on', b.dataset.mode === mode));
    $('#mode-help').textContent = MODE_HELP[mode];
  }
  $$('#mode-seg button').forEach((b) => {
    b.addEventListener('click', () => setMode(b.dataset.mode));
  });

  /* Mirrors scoring.ROLE_KEYWORDS so the rep can see which weight table a
     typed title will be scored under before running anything. */
  const ROLE_KEYWORDS = [
    ['finance', ['cfo', 'chief financial', 'controller', 'finance', 'accounting', 'accounts payable', 'ap ', 'treasury', 'fp&a', 'audit', 'tax']],
    ['engineering', ['cto', 'cio', 'chief technology', 'chief information', 'engineer', 'engineering', 'developer', 'devops', 'platform', 'architect', 'technical', 'data', 'security']],
    ['sales', ['cro', 'chief revenue', 'sales', 'revenue', 'account executive', 'sdr', 'bdr', 'gtm', 'growth', 'marketing', 'demand']],
    ['operations', ['coo', 'chief operating', 'operations', 'operating', 'ops', 'procurement', 'supply', 'vendor', 'logistics', 'process', 'program']],
    ['executive', ['ceo', 'chief executive', 'founder', 'co-founder', 'cofounder', 'president', 'managing director', 'chairman', 'owner', 'partner']],
  ];

  function roleFamily(role) {
    const text = String(role || '').toLowerCase();
    if (!text) return 'default';
    for (const [family, keywords] of ROLE_KEYWORDS) {
      if (keywords.some((k) => text.includes(k))) return family;
    }
    return 'default';
  }

  function updateRoleRead() {
    const family = roleFamily($('#f-role').value);
    $('#role-read').innerHTML = `scored under <b>${esc(family)}</b> weights`;
  }

  async function loadConfig() {
    state.config = await api('/api/config');
    renderPolicy();
  }

  async function loadCases() {
    const payload = await api('/api/test-cases');
    state.cases = payload.cases || [];
    $('#tab-cases-n').textContent = state.cases.length;
    renderScenarioGroups();
    renderCasesPage();
  }

  const CASE_GROUPS = [
    {
      key: 'happy',
      title: 'Happy paths',
      blurb: 'What the process is for. Three live companies and one controlled A/B pair that '
        + 'differ only in the job title, to show the role weights doing the work.',
      match: (c) => c.kind === 'happy',
    },
    {
      key: 'edge',
      title: 'Edge cases',
      blurb: 'The five situations where behaving differently from the happy path is the whole '
        + 'point. None of them produce a draft by accident.',
      match: (c) => c.kind !== 'happy',
    },
  ];

  /* The prepared cases, as the second half of the run page. */
  function renderScenarioGroups() {
    $('#scenario-groups').innerHTML = CASE_GROUPS.map((group) => {
      const items = state.cases.filter(group.match);
      if (!items.length) return '';
      return `
        <section class="sgroup ${group.key === 'happy' ? 'sgroup-happy' : ''}">
          <div class="sgroup-head">
            <h3>${esc(group.title)} <span class="sgroup-n">${items.length}</span></h3>
            <p>${esc(group.blurb)}</p>
          </div>
          <div class="sgrid">
            ${items.map((c) => `
              <button class="scard" type="button" data-case-run="${esc(c.id)}">
                <div class="scard-top">
                  <span class="scard-title">${esc(c.label.replace(/^(Happy path|Edge|Role A\/B) — /, ''))}</span>
                  <span class="badge badge-mono">${esc(c.id)}</span>
                </div>
                <div class="scard-who">${esc(c.prospect.name)} · ${esc(c.prospect.role || 'no title')}
                  · ${esc(c.prospect.company)}</div>
                <p class="scard-why">${esc(c.expectation)}</p>
                <div class="scard-foot">
                  <span class="badge">${esc(c.source_mode)}</span>
                  <span class="scard-run">Run it &rarr;</span>
                </div>
              </button>`).join('')}
          </div>
        </section>`;
    }).join('');

    $$('[data-case-run]').forEach((node) => {
      node.addEventListener('click', () => {
        fillCase(node.dataset.caseRun);
        startRun();
      });
    });
  }

  /* The same cases as a page of their own, with the reasoning spelled out. */
  function renderCasesPage() {
    $('#cases-groups').innerHTML = CASE_GROUPS.map((group) => {
      const items = state.cases.filter(group.match);
      if (!items.length) return '';
      return `
        <section class="sgroup">
          <div class="sgroup-head">
            <h3>${esc(group.title)} <span class="sgroup-n">${items.length}</span></h3>
            <p>${esc(group.blurb)}</p>
          </div>
          <div class="cases">
            ${items.map((c) => `
              <article class="cs">
                <div class="cs-head">
                  <span class="cs-id">${esc(c.id)}</span>
                  <span class="spacer"></span>
                  <span class="badge ${c.kind === 'happy' ? 'badge-approve' : 'badge-flag'}">${esc(c.kind)}</span>
                  <span class="badge" data-tip="${c.persona === 'synthetic'
                    ? 'An invented persona at a real company. Real people are never attributed to roles they do not hold.'
                    : 'A real, publicly documented person.'}">${c.persona === 'synthetic' ? 'synthetic' : 'real person'}</span>
                </div>
                <div class="cs-body">
                  <h3 class="cs-title">${esc(c.label.replace(/^(Happy path|Edge|Role A\/B) — /, ''))}</h3>
                  <p class="cs-who">${esc(c.prospect.name)} · ${esc(c.prospect.company)}</p>
                  <p class="cs-exp"><b>Expected:</b> ${esc(c.expectation)}</p>
                  <p class="cs-why">${esc(c.why)}</p>
                  <dl class="cs-dl">
                    <div><dt>Role</dt><dd>${plain(c.prospect.role)}</dd></div>
                    <div><dt>Domain</dt><dd>${plain(c.prospect.domain)}</dd></div>
                    <div><dt>Sources</dt><dd>${esc(c.source_mode)}</dd></div>
                    <div><dt>Weights</dt><dd>${esc(roleFamily(c.prospect.role))}</dd></div>
                  </dl>
                  <div class="cs-acts">
                    <button class="btn btn-sm btn-primary" data-case-run="${esc(c.id)}">Run this case</button>
                    <button class="btn btn-sm" data-case-load="${esc(c.id)}">Load into the form</button>
                  </div>
                </div>
              </article>`).join('')}
          </div>
        </section>`;
    }).join('');

    $$('#cases-groups [data-case-run]').forEach((node) => {
      node.addEventListener('click', () => { fillCase(node.dataset.caseRun); startRun(); });
    });
    $$('#cases-groups [data-case-load]').forEach((node) => {
      node.addEventListener('click', () => { fillCase(node.dataset.caseLoad); showTab('run'); });
    });
    bindTooltips($('#panel-cases'));
  }

  function caseById(id) {
    return state.cases.find((c) => c.id === id) || null;
  }

  function fillCase(id) {
    const c = caseById(id);
    if (!c) return;
    state.activeCase = id;
    $('#f-name').value = c.prospect.name || '';
    $('#f-company').value = c.prospect.company || '';
    $('#f-domain').value = c.prospect.domain || '';
    $('#f-role').value = c.prospect.role || '';
    $('#f-notes').value = c.prospect.notes || '';
    setMode(c.source_mode || 'auto');
    updateRoleRead();
    showTab('run');
  }

  $('#f-role').addEventListener('input', updateRoleRead);
  ['#f-name', '#f-company'].forEach((sel) => {
    $(sel).addEventListener('input', () => { state.activeCase = null; });
  });

  /* ==================================================== the run ========= */

  $('#run-form').addEventListener('submit', (event) => {
    event.preventDefault();
    startRun();
  });

  $('#back-btn').addEventListener('click', () => {
    if (state.streaming) return;
    showResult(false);
  });

  $('#replay-btn').addEventListener('click', () => {
    if (!state.streaming) startRun();
  });

  $('#open-review-btn').addEventListener('click', () => {
    if (state.run) openSheet(state.run.id);
  });

  function showResult(on) {
    $('#run-intake').hidden = on;
    $('#run-result').hidden = !on;
  }

  async function startRun() {
    if (state.streaming) return;

    const prospect = {
      name: $('#f-name').value.trim(),
      company: $('#f-company').value.trim(),
      domain: $('#f-domain').value.trim(),
      role: $('#f-role').value.trim(),
      notes: $('#f-notes').value.trim(),
    };
    if (!prospect.name || !prospect.company) {
      toast('A name and a company are the two things it cannot run without', true);
      showTab('run');
      return;
    }

    /* A fresh board in the pending state, so the whole process is visible
       before anything runs rather than appearing a stage at a time. */
    state.stageByKey = {};
    (state.config.stages || []).forEach((s) => {
      state.stageByKey[s.key] = { ...s, state: 'pending', summary: '', detail: {} };
    });
    state.lookups = [];
    state.run = null;
    state.runId = null;
    state.openStages = new Set();
    state.storyFolded = false;
    state.streaming = true;
    state.startedAt = Date.now();

    showTab('run');
    showResult(true);
    $('#run-btn').disabled = true;
    $('#run-btn').textContent = 'Running…';
    $('#open-review-btn').hidden = true;
    $('#verdict').hidden = true;
    $('#run-panes').hidden = true;
    $('#run-story').hidden = false;
    $('#run-story').classList.remove('is-folded');

    const label = state.activeCase ? caseById(state.activeCase) : null;
    $('#run-who').innerHTML = `<b>${esc(prospect.name)}</b> · ${esc(prospect.role || 'no title given')}
      · ${esc(prospect.company)}`;
    renderIntent(label, null);
    renderTracker();
    renderTimeline();
    renderMeta();

    /* The elapsed clock is the only thing that moves while a slow stage runs,
       so it is worth having: silence plus a spinner reads as a hang. */
    state.ticker = setInterval(renderMeta, 100);

    let started;
    try {
      started = await api('/api/runs', {
        method: 'POST',
        body: JSON.stringify({
          prospect,
          source_mode: state.mode,
          case_id: state.activeCase,
        }),
      });
    } catch (err) {
      stopRun();
      toast(`Could not start the run: ${err.message}`, true);
      return;
    }

    state.runId = started.run_id;
    renderMeta();

    const source = new EventSource(started.stream);
    state.source = source;
    source.onmessage = (event) => {
      let payload;
      try { payload = JSON.parse(event.data); } catch { return; }
      handleEvent(payload);
    };
    source.onerror = () => {
      if (state.streaming) { source.close(); stopRun(); }
    };
  }

  function handleEvent(event) {
    const payload = event.payload || {};
    switch (event.kind) {
      case 'run':
        state.runId = payload.id || state.runId;
        renderMeta();
        break;
      case 'stage':
        state.stageByKey[payload.key] = payload;
        renderTracker();
        renderTimeline();
        break;
      case 'lookup':
        state.lookups.push(payload);
        renderTimeline();
        break;
      case 'repair':
        toast(`Draft rejected by the audit — repairing ${(payload.unsupported || []).length} unsupported claim(s)`);
        break;
      case 'done':
        finishRun();
        break;
      case 'error':
        toast(payload.detail || 'The run failed', true);
        break;
      case 'eof':
        if (state.source) state.source.close();
        stopRun();
        break;
      default:
        break;
    }
  }

  function stopRun() {
    state.streaming = false;
    clearInterval(state.ticker);
    state.ticker = null;
    $('#run-btn').disabled = false;
    $('#run-btn').textContent = 'Research & draft';
    renderTracker();
    renderMeta();
  }

  /** The run is over: fetch the whole record rather than assembling it from
   *  the events, so what is shown is exactly what was persisted. */
  async function finishRun() {
    try {
      state.run = await api(`/api/runs/${encodeURIComponent(state.runId)}`);
    } catch { /* the stage board alone is still worth showing */ }
    stopRun();
    if (state.run) {
      (state.run.stages || []).forEach((s) => { state.stageByKey[s.key] = s; });
      renderTracker();
      renderTimeline();
      renderVerdict(state.run);
      renderPanes(state.run);
      renderIntent(state.run.case_id ? caseById(state.run.case_id) : null, state.run);
      $('#open-review-btn').hidden = !state.run.draft;
      /* The stages are the thing to watch while it runs; once it is over the
         answer is what matters, so the story folds itself away. */
      foldStory(true);
    }
    loadRuns({ quiet: true });
  }

  /* ----- what a prepared case was built to prove ------------------------ */

  function renderIntent(testCase, run) {
    const node = $('#run-intent');
    if (!testCase) { node.hidden = true; return; }
    const settled = run && run.status;
    const met = settled ? expectationMet(testCase, run) : null;
    node.className = `intent ${met === true ? 'is-met' : met === false ? 'is-miss' : ''}`;
    node.hidden = false;
    node.innerHTML = `
      <div class="intent-k">${esc(testCase.id)}</div>
      <div>
        <div class="intent-lead"><b>Expected:</b> ${esc(testCase.expectation)}
          ${met === true ? '<span class="badge badge-approve">met</span>' : ''}
          ${met === false ? '<span class="badge badge-flag">read the stages</span>' : ''}</div>
        <div class="intent-why">${esc(testCase.why)}</div>
      </div>`;
  }

  /* The expectation is prose, so this is a deliberately crude check: it looks
     for the status the sentence names. It is a reading aid, not an assertion -
     the regression suite in tools/run_cases.py is where the real check is. */
  const EXPECT_HINTS = [
    ['needs disambiguation', 'needs_disambiguation'],
    ['job change', 'flagged_job_change'],
    ['manual research', 'needs_manual_research'],
    ['fallback', 'fallback_company_signal'],
    ['blocked', 'blocked_sensitive'],
    ['ready for review', 'ready_for_review'],
  ];

  function expectationMet(testCase, run) {
    const text = String(testCase.expectation || '').toLowerCase();
    /* "Picks the FUNDING hook" is checkable against the signal that won. */
    const kind = text.match(/picks the (\w+) hook/);
    if (kind) {
      const chosen = (run.signals || []).find((s) => s.id === run.chosen_signal_id);
      return !!chosen && chosen.kind === kind[1];
    }
    for (const [needle, status] of EXPECT_HINTS) {
      if (text.includes(needle)) return run.status === status;
    }
    return null;
  }

  /* ----- the phase tracker ---------------------------------------------- */

  function orderedStages() {
    return (state.config.stages || []).map((s) => state.stageByKey[s.key] || { ...s, state: 'pending' });
  }

  function renderTracker() {
    const node = $('#tracker');
    const stages = orderedStages();
    node.style.gridTemplateColumns = `repeat(${stages.length}, 1fr)`;
    node.innerHTML = stages.map((stage, i) => {
      const st = stage.state || 'pending';
      const glyph = STATE_GLYPH[st] || '';
      return `<li class="ph ${STATE_CLASS[st]}">
        <span class="ph-dot">${st === 'active' ? '' : (glyph || i + 1)}</span>
        <span class="ph-name">${esc(stageCopy(stage.key).short)}</span>
      </li>`;
    }).join('');

    /* What the live stage is doing, in a sentence. */
    const now = $('#now-doing');
    const active = stages.find((s) => s.state === 'active');
    if (active && state.streaming) {
      now.hidden = false;
      now.innerHTML = `<span class="now-dot"></span><span>${esc(stageCopy(active.key).say)}</span>`;
    } else {
      now.hidden = true;
    }
  }

  function renderMeta() {
    const run = state.run;
    const elapsed = state.streaming
      ? `${((Date.now() - state.startedAt) / 1000).toFixed(1)}s`
      : duration(run && run.ms != null ? run.ms : Date.now() - state.startedAt);
    const bits = [];
    if (state.runId) bits.push(`<span class="badge badge-mono">${esc(state.runId)}</span>`);
    bits.push(`<span class="badge">${esc((run && run.source_mode) || state.mode)} sources</span>`);
    if (run && run.status) bits.push(badge(run.status));
    bits.push(`<span class="badge badge-mono">${esc(elapsed)}</span>`);
    $('#run-meta').innerHTML = bits.join('');
  }

  /* ----- the story of the run ------------------------------------------
     The nine stages as a narrative: a numbered rail, a sentence per stage in
     plain English, then what that stage actually found. Everything the stage
     produced is one click away and off by default, because it is evidence
     rather than story. */

  function foldStory(folded) {
    state.storyFolded = folded;
    $('#run-story').classList.toggle('is-folded', folded);
    $('#story-toggle').setAttribute('aria-expanded', String(!folded));
  }

  $('#story-toggle').addEventListener('click', () => foldStory(!state.storyFolded));

  $('#expand-btn').addEventListener('click', () => {
    const stages = orderedStages().filter((s) => s.state !== 'pending');
    const allOpen = stages.length && stages.every((s) => state.openStages.has(s.key));
    state.openStages = allOpen ? new Set() : new Set(stages.map((s) => s.key));
    if (state.storyFolded) foldStory(false);
    renderTimeline();
  });

  function renderTimeline() {
    const stages = orderedStages();
    $('#timeline').innerHTML = renderSteps(stages, state.openStages, state.lookups);
    wireSteps($('#timeline'), state.openStages, renderTimeline);

    /* Folded, the panel still has to say what is behind it. */
    const settled = stages.filter((s) => ['done', 'warn', 'skipped'].includes(s.state)).length;
    const stopped = stages.filter((s) => ['blocked', 'error'].includes(s.state)).length;
    const skipped = stages.filter((s) => s.state === 'skipped').length;
    const parts = [`${settled + stopped} of ${stages.length} stages settled`];
    if (skipped) parts.push(`${skipped} skipped after an early stop`);
    if (stopped) parts.push('one stage stopped the run');
    $('#story-summary').textContent = `${parts.join(' · ')}. Click to read them.`;

    const allOpen = stages.filter((s) => s.state !== 'pending')
      .every((s) => state.openStages.has(s.key));
    $('#expand-btn').textContent = allOpen && state.openStages.size ? 'Collapse all' : 'Expand all';
  }

  /** One timeline, wherever it is drawn - the run view and the review sheet
   *  share this so a historical run reads exactly like a live one. */
  function renderSteps(stages, openSet, lookups) {
    return stages.map((stage, i) => {
      const st = stage.state || 'pending';
      const copy = stageCopy(stage.key);
      const tag = STATE_TAG[st];
      const body = st === 'pending' ? '' : stageDetail(stage, lookups);
      const open = openSet.has(stage.key);
      return `
        <li class="pstep ${STATE_CLASS[st]} ${open ? 'is-open' : ''}" data-key="${esc(stage.key)}">
          <div class="pstep-rail">
            <div class="pstep-mark">${st === 'active' ? '' : (STATE_GLYPH[st] || i + 1)}</div>
          </div>
          <div class="pstep-main">
            <div class="pstep-head">
              <span class="pstep-n">Stage ${i + 1}</span>
              <h3 class="pstep-name">${esc(stage.title)}</h3>
              ${tag ? `<span class="pstep-tag ${tag[0]}">${tag[1]}</span>` : ''}
              <span class="pstep-time">${esc(duration(stage.ms))}</span>
            </div>
            <p class="pstep-say">${esc(copy.say)}</p>
            ${stage.summary ? `<div class="pstep-found">${esc(stage.summary)}</div>` : ''}
            ${body ? `<button class="pstep-more" type="button" data-more="${esc(stage.key)}">
              <span class="caret">▶</span> ${open ? 'Hide' : 'Show'} what this stage produced
            </button><div class="stage-body">${body}</div>` : ''}
          </div>
        </li>`;
    }).join('');
  }

  function wireSteps(root, openSet, rerender) {
    $$('[data-more]', root).forEach((node) => {
      node.addEventListener('click', () => {
        const key = node.dataset.more;
        if (openSet.has(key)) openSet.delete(key); else openSet.add(key);
        rerender();
      });
    });
    bindTooltips(root);
  }

  /* ==================================================== stage payloads ==
     One renderer per stage. Each answers the question a reviewer actually has
     at that point in the process, rather than printing the payload. */

  function block(title, inner) {
    return `<div class="sub"><div class="sub-title">${esc(title)}</div>${inner}</div>`;
  }

  function kvList(rows) {
    return `<dl class="kv">${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
  }

  function lookupRow(l) {
    const n = l.ok ? `${l.n} hit${l.n === 1 ? '' : 's'}` : String(l.error || 'failed').split(':')[0];
    return `<div class="lookup ${l.ok ? '' : 'is-bad'}">
      <span class="dot ${l.ok ? 'dot-ok' : 'dot-bad'}"></span>
      <span class="conn">${esc(l.connector)}</span>
      <span class="q">${esc(l.query || '')}</span>
      <span class="n">${esc(n)}</span>
    </div>`;
  }

  function lookupList(rows) {
    if (!rows || !rows.length) return '';
    return `<div class="lookups">${rows.map(lookupRow).join('')}</div>`;
  }

  function signalCard(sig, opts) {
    const o = opts || {};
    return `<div class="sig ${o.win ? 'is-win' : ''} ${sig.vetoed ? 'is-veto' : ''}">
      <div class="sig-top">
        <span class="badge">${esc(sig.kind)}</span>
        <span class="badge">${esc(sig.level)}-level</span>
        <span class="spacer"></span>
        ${sig.score ? `<span class="badge ${sig.vetoed ? 'badge-reject' : o.win ? 'badge-approve' : ''}">
          ${sig.score.total}/100${o.win ? ' · used' : ''}</span>` : ''}
      </div>
      <div class="sig-claim">${esc(sig.claim)}</div>
      ${sig.why_it_matters ? `<div class="sig-why">${esc(sig.why_it_matters)}</div>` : ''}
      ${sig.vetoed ? `<div class="sig-note">Vetoed: ${esc(sig.veto_reason || sig.sensitive_reason || 'screened out')}</div>` : ''}
    </div>`;
  }

  const SCORE_COLS = [
    ['recency', 'Rec', 30], ['role_relevance', 'Role', 25], ['specificity', 'Spec', 20],
    ['source_quality', 'Src', 15], ['actionability', 'Act', 10],
  ];

  function stageDetail(stage, lookups) {
    const d = stage.detail || {};
    const live = (phase) => lookupList((lookups || []).filter((l) => l.phase === phase));
    switch (stage.key) {
      case 'intake': return Object.keys(d).length ? intakeDetail(d) : '';
      /* The live lookup fallback is only valid while a stage is in flight.
         Using it for a finished stage would paint the last run's lookups onto
         an unrelated historical one in the review sheet. */
      case 'identity': return Object.keys(d).length ? identityDetail(d) : live('identity');
      case 'harvest': return Object.keys(d).length ? harvestDetail(d) : live('harvest');
      case 'interpret':
        if (d.signals) return interpretDetail(d);
        return d.diagnostics ? diagnosticsDetail(d.diagnostics) : '';
      case 'guardrail': return Object.keys(d).length ? guardrailDetail(d) : '';
      case 'score': return d.ranked ? scoreDetail(d) : '';
      case 'draft': return d.draft ? emailBlock(d.draft, true) : '';
      case 'verify': return d.checks ? verifyDetail(d) : '';
      case 'package': return Object.keys(d).length ? packageDetail(d) : '';
      default: return '';
    }
  }

  function intakeDetail(d) {
    const p = d.policy || {};
    return kvList([
      ['Weight table', `${esc(d.role_family || 'default')} — chosen from the job title`],
      ['Sources', esc(d.source_mode_note || d.source_mode || '')],
      ['Recency cap', `${p.max_age_days} days, then a signal is vetoed rather than downranked`],
      ['Score floor', `${p.min_hook_score} company-level · ${p.min_person_hook_score} person-level`],
    ]);
  }

  function identityDetail(d) {
    const v = d.verdict || {};
    const tone = {
      confirmed: 'badge-approve', changed_role: 'badge-flag',
      left_company: 'badge-reject', unconfirmed: '',
    }[v.employment] || '';
    const gate = d.halt_gate;
    return `
      <div class="chips">
        <span class="badge ${tone}">${esc(String(v.employment || 'unknown').replace(/_/g, ' '))}</span>
        <span class="badge">${v.confidence || 0}% confident</span>
        ${v.name_collision ? '<span class="badge badge-flag">name collision</span>' : ''}
        ${v.stated_role ? `<span class="badge">source title: ${esc(v.stated_role)}</span>` : ''}
      </div>
      ${v.reasoning ? `<div class="note">${esc(v.reasoning)}</div>` : ''}
      ${v.collision_detail ? `<div class="note note-warn">${esc(v.collision_detail)}</div>` : ''}
      ${gate ? `<div class="note ${gate.halted ? 'note-bad' : 'note-warn'}">
        <b>Departure-claim gate:</b> ${gate.confidence}% confidence against ${gate.required}% required,
        source ${gate.evidence_id ? `<code>${esc(gate.evidence_id)}</code>` : 'not cited'} →
        ${gate.halted ? 'run halted' : 'treated as a namesake, run continued'}.</div>` : ''}
      ${(d.lookups || []).length ? block('Person-level lookups', lookupList(d.lookups)) : ''}`;
  }

  function harvestDetail(d) {
    const counts = Object.entries(d.by_connector || {})
      .map(([k, n]) => `<span class="badge"><b>${esc(k)}</b> ${n}</span>`).join('');
    return `${counts ? `<div class="chips">${counts}</div>` : ''}
      ${block('Every query it ran', lookupList(d.lookups))}`;
  }

  function interpretDetail(d) {
    const signals = d.signals || [];
    const note = d.diagnostics && d.diagnostics.retried
      ? `<div class="note note-warn">The first interpretation pass came back empty; it was retried
          and recovered ${signals.length} signal(s).</div>`
      : '';
    return note + signals.map((s) => signalCard(s, {})).join('');
  }

  /* When interpretation comes back empty, a reviewer needs to know whether the
     model found nothing or simply hiccuped. These counters answer that. */
  function diagnosticsDetail(g) {
    return kvList([
      ['Evidence in', `${g.evidence_in} document(s)`],
      ['Model returned', `${g.raw_signals} signal(s) across ${g.attempts} attempt(s)`],
      ['Dropped', `${g.dropped_no_valid_id} citing no retrieved source id,
        ${g.dropped_no_claim} with no claim`],
      ['Retried', g.retried ? 'yes — the first pass was empty' : 'no'],
    ]) + `<div class="note">A signal that cites no retrieved source id is discarded rather than
      kept, which is what makes an invented citation impossible rather than unlikely.</div>`;
  }

  function guardrailDetail(d) {
    const rows = [];
    (d.regex_hits || []).forEach((h) => rows.push([h.signal_id,
      'vetoed by the keyword screen', `category: ${h.category}`]));
    (d.llm_hits || []).forEach((h) => rows.push([h.signal_id,
      'vetoed by the model screen', `${h.category}: ${h.reason}`]));
    (d.stale || []).forEach((h) => rows.push([h.signal_id,
      'past the recency limit', h.note]));

    const surviving = (d.surviving || []).length;
    if (!rows.length) {
      return `<div class="note note-ok">Nothing vetoed. Every candidate is recent enough and safe
        to reference.</div>`;
    }
    return `<ul class="claims">
        ${rows.map(([id, what, why]) => `
          <li class="claim is-bad">
            <span class="claim-mark">⊘</span>
            <div class="claim-body">
              <div class="claim-text"><code>${esc(id)}</code> — ${esc(what)}</div>
              <div class="claim-src">${esc(why)}</div>
            </div>
          </li>`).join('')}
      </ul>
      <div class="note">${surviving} signal(s) cleared the screen.
        Sensitivity is a veto, never a score: a crisis story is allowed to score on its merits so
        that the veto is visibly the thing that removes it.</div>`;
  }

  function scoreDetail(d) {
    const ranked = d.ranked || [];
    const chosen = ranked.find((r) => r.id === d.chosen_id);
    const notes = (chosen && chosen.breakdown && chosen.breakdown.notes) || [];
    return `
      <div style="overflow-x:auto">
        <table class="score">
          <thead><tr>
            <th>Candidate signal</th>
            ${SCORE_COLS.map(([, label, max]) => `<th>${label} /${max}</th>`).join('')}
            <th>Total</th>
          </tr></thead>
          <tbody>
            ${ranked.map((r) => {
              const b = r.breakdown || {};
              const cls = r.vetoed ? 'is-veto' : (d.chosen_id === r.id ? 'is-win' : '');
              return `<tr class="${cls}">
                <td class="claim-cell">
                  <div class="meta">
                    <span class="badge">${esc(r.kind)}</span>
                    <span class="badge">${esc(r.level)}</span>
                    ${r.vetoed ? `<span class="badge badge-reject">vetoed: ${esc(r.veto_reason)}</span>` : ''}
                  </div>
                  ${esc(r.claim)}
                </td>
                ${SCORE_COLS.map(([k]) => `<td>${b[k] == null ? 0 : b[k]}</td>`).join('')}
                <td class="total">${r.total}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
      ${notes.length ? block('The winning signal, component by component',
        notes.map((n) => `<div class="hint">· ${esc(n)}</div>`).join('')) : ''}
      ${d.rationale ? `<div class="note"><b>Decision:</b> ${esc(d.rationale)}</div>` : ''}
      ${d.thresholds ? `<div class="hint">Floors: ${d.thresholds.company} company-level,
        ${d.thresholds.person} person-level. Below the floor nothing is drafted at all.</div>` : ''}`;
  }

  function verifyDetail(d) {
    const checks = d.checks || [];
    const style = d.style_issues || [];
    return `
      ${d.repair_attempts ? `<div class="note note-warn">The draft was rewritten
        ${d.repair_attempts}× after failing this audit.</div>` : ''}
      <ul class="claims">
        ${checks.map((c) => `
          <li class="claim ${c.supported ? 'is-ok' : 'is-bad'}">
            <span class="claim-mark">${c.supported ? '✓' : '✕'}</span>
            <div class="claim-body">
              <div class="claim-text">${esc(c.claim)}</div>
              <div class="claim-src">
                ${c.evidence_id ? `<span class="mono">${esc(c.evidence_id)}</span> · ` : ''}${esc(c.note)}
              </div>
            </div>
          </li>`).join('')}
      </ul>
      ${style.length ? block('Style audit',
        style.map((i) => `<div class="hint">! ${esc(i)}</div>`).join('')) : ''}`;
  }

  function packageDetail(d) {
    const rows = Object.entries(d).filter(([, v]) => typeof v !== 'object')
      .map(([k, v]) => [k.replace(/_/g, ' '), esc(String(v))]);
    return rows.length ? kvList(rows) : '';
  }

  /* ==================================================== the answer ====== */

  function renderVerdict(run) {
    const node = $('#verdict');
    const s = statusOf(run.status);
    node.hidden = false;
    node.className = `verdict is-${s.tone === 'idle' ? 'flag' : s.tone}`;
    node.innerHTML = `
      <div class="v-mark">${s.glyph}</div>
      <div class="v-text">
        <div class="v-word">${esc(s.label)}</div>
        <div class="v-line">${esc(run.headline || s.line)}</div>
        <div class="v-sub">${esc(s.next)}</div>
      </div>
      ${run.status === 'running' ? '' : `<div class="v-conf">
        <b>${run.confidence || 0}</b><span>confidence</span></div>`}`;
  }

  /* ----- the draft beside its evidence ---------------------------------- */

  function emailBlock(draft, highlight) {
    let body = esc(draft.body || '');
    if (highlight && draft.opener_claim) {
      const needle = esc(draft.opener_claim);
      if (body.includes(needle)) body = body.replace(needle, `<mark>${needle}</mark>`);
    }
    return `<div class="email">
      <div class="email-head">
        <span class="email-k">subject</span>
        <span class="email-subject">${esc(draft.subject || '(none)')}</span>
      </div>
      <div class="email-body">${body}</div>
      <div class="email-foot">
        <span>${draft.word_count || words(draft.body)} words</span>
        <span>${(draft.citations || []).length} cited source(s)</span>
        ${highlight && draft.opener_claim ? '<span>highlighted — the sourced hook</span>' : ''}
      </div>
    </div>`;
  }

  function paneCard(title, right, body) {
    return `<div class="pane">
      <div class="pane-head">${esc(title)}<span class="spacer"></span>${right || ''}</div>
      <div class="pane-body">${body}</div>
    </div>`;
  }

  function renderPanes(run) {
    const node = $('#run-panes');
    node.hidden = false;

    const chosen = (run.signals || []).find((s) => s.id === run.chosen_signal_id);
    const byId = Object.fromEntries((run.evidence || []).map((e) => [e.id, e]));

    $('#pane-draft').innerHTML = run.draft
      ? paneCard('The draft', `<button class="btn btn-sm btn-primary" data-review="${esc(run.id)}">Review it</button>`,
        emailBlock(run.draft, true)
        + `<div class="hint">Nothing is sent from here. Approving records that a human cleared the
            draft for the rep's own sending tool.</div>`)
      : paneCard('No draft was produced', '',
        `<div class="note note-warn">${esc(run.headline)}</div>
         ${run.selection_rationale ? `<div class="hint">${esc(run.selection_rationale)}</div>` : ''}
         <div class="hint">The process stopped deliberately rather than writing something it could
           not source. For this input, that is the intended outcome.</div>`);

    /* Left: what it says, and whether every sentence of it is true. Right:
       what it chose to say and what it chose not to. */
    $('#pane-draft').insertAdjacentHTML('beforeend',
      [claimsPane(run), sourcesPane(run, chosen, byId)].filter(Boolean).join(''));

    $('#pane-evidence').innerHTML = [
      hookPane(chosen),
      candidatesPane(run),
    ].filter(Boolean).join('');

    $$('[data-review]').forEach((b) => {
      b.addEventListener('click', () => openSheet(b.dataset.review));
    });
  }

  function hookPane(chosen) {
    if (!chosen) return '';
    return paneCard('The hook it used',
      `<span class="badge badge-approve">${chosen.score.total}/100</span>`,
      signalCard(chosen, { win: true })
      + ((chosen.score.notes || []).map((n) => `<div class="hint">· ${esc(n)}</div>`).join('')));
  }

  /* Every candidate and its fate. This is the pane that matters on a blocked
     or fallback run: without it the page only says no draft was produced, and
     a reviewer cannot see what was rejected or what it would have scored. */
  function candidatesPane(run) {
    const signals = run.signals || [];
    if (!signals.length) return '';
    const ranked = [...signals].sort((a, b) =>
      (Number(a.vetoed) - Number(b.vetoed)) || (b.score.total - a.score.total));
    const vetoed = ranked.filter((s) => s.vetoed).length;
    return paneCard('Every candidate it considered',
      `<span class="badge ${vetoed ? 'badge-flag' : ''}">${ranked.length} found${vetoed ? ` · ${vetoed} vetoed` : ''}</span>`,
      ranked.map((s) => signalCard(s, { win: s.id === run.chosen_signal_id })).join('')
      + (run.selection_rationale ? `<div class="note"><b>Decision:</b> ${esc(run.selection_rationale)}</div>` : ''));
  }

  function claimsPane(run) {
    const checks = run.claim_checks || [];
    if (!checks.length) return '';
    const bad = checks.filter((c) => !c.supported).length;
    return paneCard('The claim ledger',
      `<span class="badge ${bad ? 'badge-flag' : 'badge-approve'}">${checks.length - bad}/${checks.length} sourced</span>`,
      `<ul class="claims">${checks.map((c) => `
        <li class="claim ${c.supported ? 'is-ok' : 'is-bad'}">
          <span class="claim-mark">${c.supported ? '✓' : '✕'}</span>
          <div class="claim-body">
            <div class="claim-text">${esc(c.claim)}</div>
            <div class="claim-src">
              ${c.evidence_id ? `<span class="mono">${esc(c.evidence_id)}</span> · ` : ''}${esc(c.note)}
            </div>
          </div>
        </li>`).join('')}</ul>`);
  }

  function sourceRow(e, i) {
    return `<li class="srcrow">
      <span class="idx">${i + 1}</span>
      <div>
        <a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title)}</a>
        <div class="m"><b>${esc(e.publisher || host(e.url) || 'unattributed')}</b>
          · ${esc(e.published_at || 'undated')}
          ${e.age_days != null ? `· ${e.age_days}d old` : ''}
          · via ${esc(e.connector)}${e.connector === 'fixtures' ? ' <span class="badge">replay</span>' : ''}
        </div>
      </div>
    </li>`;
  }

  function sourcesPane(run, chosen, byId) {
    const citedIds = new Set((chosen && chosen.evidence_ids) || (run.draft && run.draft.citations) || []);
    const cited = [...citedIds].map((id) => byId[id]).filter(Boolean);
    const others = (run.evidence || []).filter((e) => !citedIds.has(e.id));
    if (!cited.length && !others.length) return '';
    return paneCard('Sources',
      `<span class="badge">${cited.length} cited · ${others.length} retrieved</span>`,
      `${cited.length
        ? `<ul class="srcs">${cited.map(sourceRow).join('')}</ul>`
        : '<div class="hint">Nothing was cited, because nothing was drafted.</div>'}
       ${others.length ? `<details style="margin-top:12px">
         <summary class="linkish">${others.length} other retrieved document(s) not used</summary>
         <ul class="srcs" style="margin-top:10px">${others.map(sourceRow).join('')}</ul>
       </details>` : ''}`);
  }

  /* ==================================================== the dashboard ===
     One fetch, then every figure, chart and row on the page is computed from
     the same array. Filtering and sorting are client-side so the charts
     always describe the whole history rather than the current filter. */

  async function loadRuns(opts = {}) {
    let payload;
    try {
      payload = await api('/api/runs?limit=300');
    } catch (err) {
      if (!opts.quiet) toast(`Could not load the run history: ${err.message}`, true);
      return;
    }
    state.runs = payload.runs || [];
    state.stats = payload.stats || {};
    $('#tab-runs-n').textContent = pendingRuns().length || '';
    renderTiles();
    renderCharts();
    renderRunsTable();
  }

  const pendingRuns = () => state.runs.filter(
    (r) => HAS_DRAFT.has(r.status) && (r.review_state || 'pending') === 'pending');

  function countBy(rows, fn) {
    const out = {};
    rows.forEach((r) => { const k = fn(r); out[k] = (out[k] || 0) + 1; });
    return out;
  }

  function renderTiles() {
    const s = state.stats || {};
    const by = s.by_status || {};
    const human = ['fallback_company_signal', 'needs_manual_research',
      'flagged_job_change', 'needs_disambiguation'].reduce((n, k) => n + (by[k] || 0), 0);
    const blocked = (by.blocked_sensitive || 0) + (by.error || 0);

    const tiles = [
      ['Prospects worked', s.total || 0, '', 'Every run ever recorded.'],
      ['Draft ready', by.ready_for_review || 0, 'is-approve', 'Grounded, every claim cited.'],
      ['Needs a human', human, 'is-flag', 'Stopped, and it says why.'],
      ['Nothing drafted', blocked, 'is-reject', 'Crisis-only signal, or a failure.'],
      ['Waiting on you', pendingRuns().length, 'is-flag', 'Drafts held for a person.'],
      ['Cleared by a person', s.approved || 0, '', 'Approved in the queue below.'],
      ['Mean confidence', `${s.avg_confidence || 0}<small>%</small>`, '', 'Across settled runs.'],
      ['Mean run time', `${((s.avg_ms || 0) / 1000).toFixed(1)}<small>s</small>`, '', 'Nine stages, end to end.'],
    ];
    $('#tiles').innerHTML = tiles.map(([label, value, cls, sub]) => `
      <div class="tile ${cls}">
        <div class="tile-label">${esc(label)}</div>
        <div class="tile-value">${value}</div>
        <div class="tile-sub">${esc(sub)}</div>
      </div>`).join('');
  }

  const FAMILY_META = [
    ['READY', 'Draft ready', 'var(--ok)'],
    ['HUMAN', 'Needs a human', 'var(--warn)'],
    ['BLOCKED', 'Nothing drafted', 'var(--bad)'],
  ];

  const REVIEW_META = [
    ['approved', 'Approved', 'var(--ok)'],
    ['edited', 'Edited then approved', 'var(--s2)'],
    ['rejected', 'Rejected', 'var(--bad)'],
    ['pending', 'Still waiting', 'var(--s4)'],
  ];

  function stackChart(title, sub, rows, total, foot) {
    if (!total) {
      return `<div class="chart"><div class="chart-h">${esc(title)}</div>
        <p class="chart-sub">${esc(sub)}</p>
        <p class="chart-empty">Nothing to chart yet — run a prospect.</p></div>`;
    }
    const present = rows.filter((r) => r.n > 0);
    return `<div class="chart">
      <div class="chart-h">${esc(title)}</div>
      <p class="chart-sub">${esc(sub)}</p>
      <div class="stack">
        ${present.map((r) => `<span class="seg-bar" style="flex:${r.n};background:${r.color}"
          data-tip="<div class='tt-head'>${esc(r.label)}</div>${r.n} of ${total} runs">
          ${r.n / total > .08 ? `<span class="seg-n">${r.n}</span>` : ''}</span>`).join('')}
      </div>
      <div class="legend">
        ${rows.map((r) => `<span class="lg">
          <span class="lg-dot" style="background:${r.color}"></span>
          ${esc(r.label)} <b>${r.n}</b>
          <span class="lg-pct">${Math.round((r.n / total) * 100)}%</span></span>`).join('')}
      </div>
      ${foot ? `<p class="chart-foot">${esc(foot)}</p>` : ''}
    </div>`;
  }

  function barChart(title, sub, rows, foot) {
    const max = Math.max(1, ...rows.map((r) => r.n));
    if (!rows.length) {
      return `<div class="chart"><div class="chart-h">${esc(title)}</div>
        <p class="chart-sub">${esc(sub)}</p>
        <p class="chart-empty">Nothing to chart yet.</p></div>`;
    }
    return `<div class="chart">
      <div class="chart-h">${esc(title)}</div>
      <p class="chart-sub">${esc(sub)}</p>
      <ul class="bars">
        ${rows.map((r) => `<li class="bar-row ${r.cls || ''}">
          <span class="bar-name">${esc(r.label)}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${(r.n / max) * 100}%"></span></span>
          <span class="bar-n">${r.n}</span>
        </li>`).join('')}
      </ul>
      ${foot ? `<p class="chart-foot">${esc(foot)}</p>` : ''}
    </div>`;
  }

  function renderCharts() {
    const runs = state.runs;
    const total = runs.length;

    /* 1. The outcome mix - three families, because the three things a rep can
          do next are the only distinction colour is allowed to carry. */
    const famCounts = countBy(runs, (r) => FAMILY[r.status] || 'HUMAN');
    const mix = stackChart(
      'What the process decided',
      'Every run, grouped by what it leaves the rep to do.',
      FAMILY_META.map(([key, label, color]) => ({ label, color, n: famCounts[key] || 0 })),
      total,
      'A process that returns nothing a third of the time and is right whenever it does return '
      + 'something is worth more than one that always answers.');

    /* 2. Where runs actually end, by status. One hue, because these are seven
          values of one thing. */
    const statusCounts = countBy(runs, (r) => r.status);
    const endings = barChart(
      'Where runs end',
      'The seven terminal statuses. The four in the middle are all "a human finishes this".',
      Object.keys(STATUS).filter((k) => statusCounts[k])
        .map((k) => ({
          label: statusOf(k).label,
          n: statusCounts[k],
          cls: `is-${statusOf(k).tone === 'idle' ? 'flag' : statusOf(k).tone}`,
        })));

    /* 3. The human half of the loop. */
    const draftable = runs.filter((r) => HAS_DRAFT.has(r.status));
    const reviewCounts = countBy(draftable, (r) => r.review_state || 'pending');
    const ledger = stackChart(
      'What people did with the drafts',
      'Only runs that produced one. Nothing here was ever sent by this system.',
      REVIEW_META.map(([key, label, color]) => ({ label, color, n: reviewCounts[key] || 0 })),
      draftable.length,
      'A rejection is as useful a signal as an approval: it says the hook was grounded but not '
      + 'worth sending.');

    /* 4. Confidence, bucketed. A single mean hides the shape. */
    const settled = runs.filter((r) => r.status !== 'running');
    const buckets = [
      ['80–100', (c) => c >= 80], ['60–79', (c) => c >= 60 && c < 80],
      ['40–59', (c) => c >= 40 && c < 60], ['1–39', (c) => c > 0 && c < 40],
      ['0 — nothing drafted', (c) => !c],
    ];
    const spread = barChart(
      'How confident it was',
      'Confidence is reduced by a fallback hook, an unconfirmed identity or a thin source, so a '
      + 'low number is informative rather than a failure.',
      buckets.map(([label, test]) => ({
        label, n: settled.filter((r) => test(r.confidence || 0)).length,
      })).filter((r) => r.n));

    $('#charts').innerHTML = mix + endings + ledger + spread;
    bindTooltips($('#charts'));
  }

  /* ----- the runs table -------------------------------------------------- */

  const SORTERS = {
    created_at: (r) => r.created_at || '',
    prospect_name: (r) => String(r.prospect_name || '').toLowerCase(),
    case_id: (r) => String(r.case_id || '').toLowerCase(),
    status: (r) => statusOf(r.status).label,
    confidence: (r) => r.confidence || 0,
    review_state: (r) => r.review_state || '',
    source_mode: (r) => r.source_mode || '',
    ms: (r) => r.ms || 0,
  };

  function visibleRuns() {
    const needle = state.search.trim().toLowerCase();
    let rows = state.runs.filter((r) => {
      if (state.filter !== 'ALL' && (FAMILY[r.status] || 'HUMAN') !== state.filter) return false;
      if (!needle) return true;
      return [r.prospect_name, r.company, r.role, r.case_id, r.headline]
        .some((v) => String(v || '').toLowerCase().includes(needle));
    });
    const get = SORTERS[state.sortKey] || SORTERS.created_at;
    rows = rows.slice().sort((a, b) => {
      const x = get(a); const y = get(b);
      if (x === y) return 0;
      return (x > y ? 1 : -1) * (state.sortDir === 'asc' ? 1 : -1);
    });
    return rows;
  }

  function renderRunsTable() {
    const rows = visibleRuns();
    const body = $('#runs-table tbody');
    $('#runs-empty').hidden = rows.length > 0;

    body.innerHTML = rows.map((r) => `
      <tr class="clickable" data-run="${esc(r.id)}">
        <td class="dim">${esc(ago(r.created_at))}</td>
        <td class="wrap">
          <div class="who">${esc(r.prospect_name)}</div>
          <div class="where">${esc(r.company)}${r.role ? ` · ${esc(r.role)}` : ''}</div>
        </td>
        <td>${r.case_id ? `<span class="badge badge-mono">${esc(r.case_id)}</span>` : '<span class="dim">—</span>'}</td>
        <td>${badge(r.status)}</td>
        <td class="num">${meter(r.confidence || 0)}</td>
        <td>${HAS_DRAFT.has(r.status) ? reviewBadge(r.review_state) : '<span class="dim">no draft</span>'}</td>
        <td class="dim">${esc(r.source_mode || '')}</td>
        <td class="num mono dim">${esc(duration(r.ms))}</td>
      </tr>`).join('');

    $$('#runs-table th[data-sort]').forEach((th) => {
      const on = th.dataset.sort === state.sortKey;
      th.classList.toggle('is-sorted', on);
      if (on) th.dataset.dir = state.sortDir; else delete th.dataset.dir;
    });

    $$('#runs-table tbody tr').forEach((tr) => {
      tr.addEventListener('click', () => openSheet(tr.dataset.run));
    });
  }

  $$('#runs-table th[data-sort]').forEach((th) => {
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        state.sortKey = key;
        /* Text reads better A-Z, numbers and dates biggest-first. */
        state.sortDir = ['prospect_name', 'case_id', 'status', 'review_state', 'source_mode']
          .includes(key) ? 'asc' : 'desc';
      }
      renderRunsTable();
    });
  });

  $$('#runs-filters .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      state.filter = chip.dataset.filter;
      $$('#runs-filters .chip').forEach((c) => c.classList.toggle('is-active', c === chip));
      renderRunsTable();
    });
  });

  let searchTimer = null;
  $('#runs-search').addEventListener('input', (event) => {
    clearTimeout(searchTimer);
    const value = event.target.value;
    searchTimer = setTimeout(() => { state.search = value; renderRunsTable(); }, 160);
  });

  $('#runs-refresh').addEventListener('click', async () => {
    await loadRuns();
    loadQueue();
    loadHealth();
    toast('Reloaded');
  });

  $('#runs-clear').addEventListener('click', async () => {
    if (!window.confirm('Delete every recorded run? This cannot be undone.')) return;
    try {
      const result = await api('/api/runs', { method: 'DELETE' });
      toast(`${result.deleted} run(s) deleted`);
      loadRuns();
      loadQueue();
    } catch (err) {
      toast(err.message, true);
    }
  });

  /* ==================================================== the review queue =
     The human half of the loop, and the only page where the drafts are
     fetched in full: a card has to show the subject line and the opening
     words, which the summary rows deliberately do not carry. */

  async function loadQueue() {
    if (!state.runs.length) await loadRuns({ quiet: true });

    const rows = state.runs.filter((r) => {
      const hasDraft = HAS_DRAFT.has(r.status);
      const decided = (r.review_state || 'pending') !== 'pending';
      if (state.qfilter === 'pending') return hasDraft && !decided;
      if (state.qfilter === 'decided') return hasDraft && decided;
      if (state.qfilter === 'nodraft') return !hasDraft;
      return true;
    }).slice(0, 36);

    $('#queue-empty').hidden = rows.length > 0;
    $('#queue-empty').textContent = state.qfilter === 'pending'
      ? 'Nothing is waiting. Every draft the process produced has been decided.'
      : 'Nothing here.';

    /* Only the drafts need their full record; the rest render from the row. */
    const detailed = await Promise.all(rows.map(async (r) => {
      if (!HAS_DRAFT.has(r.status)) return { row: r, run: null };
      try { return { row: r, run: await api(`/api/runs/${encodeURIComponent(r.id)}`) }; }
      catch { return { row: r, run: null }; }
    }));

    $('#queue').innerHTML = detailed.map(({ row, run }) => {
      const draft = run && run.draft;
      const chosen = run && (run.signals || []).find((s) => s.id === run.chosen_signal_id);
      const bad = run ? (run.claim_checks || []).filter((c) => !c.supported).length : 0;
      return `
        <button class="qcard" type="button" data-run="${esc(row.id)}">
          <div class="qcard-top">
            <div>
              <div class="qcard-who">${esc(row.prospect_name)}</div>
              <div class="qcard-where">${esc(row.company)}${row.role ? ` · ${esc(row.role)}` : ''}</div>
            </div>
            ${badge(row.status)}
          </div>
          ${draft
            ? `<div class="qcard-subject">${esc(draft.subject || '(no subject)')}</div>
               <p class="qcard-snip">${esc(draft.body || '')}</p>`
            : `<p class="qcard-snip" style="margin-top:12px">${esc(row.headline || '')}</p>`}
          <div class="qcard-foot">
            <span>
              ${chosen ? `${esc(chosen.kind)} hook · ${chosen.score.total}/100` : 'no hook'}
              ${bad ? ` · <b>${bad} unsourced</b>` : ''}
            </span>
            <span>${HAS_DRAFT.has(row.status) ? reviewBadge(row.review_state) : ''}
              <span class="qcard-open">Open &rarr;</span></span>
          </div>
        </button>`;
    }).join('');

    $$('#queue [data-run]').forEach((node) => {
      node.addEventListener('click', () => openSheet(node.dataset.run));
    });
  }

  $$('#queue-filters .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      state.qfilter = chip.dataset.qfilter;
      $$('#queue-filters .chip').forEach((c) => c.classList.toggle('is-active', c === chip));
      loadQueue();
    });
  });

  /* ==================================================== the review sheet =
     One run, in full: the draft on the left as an editable document, and
     everything it rests on beside it. A row anywhere in the app opens this. */

  async function openSheet(runId) {
    let run;
    try {
      run = await api(`/api/runs/${encodeURIComponent(runId)}`);
    } catch (err) {
      toast(err.message, true);
      return;
    }
    closeSheet();                      // never stack two of these
    state.sheetRun = run;
    state.sheetOpenStages = new Set();

    const s = statusOf(run.status);
    const chosen = (run.signals || []).find((x) => x.id === run.chosen_signal_id);
    const byId = Object.fromEntries((run.evidence || []).map((e) => [e.id, e]));

    const sheet = document.createElement('div');
    sheet.className = 'sheet';
    sheet.id = 'sheet';
    sheet.innerHTML = `
      <div class="sheet-back"></div>
      <div class="sheet-panel" role="dialog" aria-modal="true" aria-label="Review this run">
        <div class="sheet-head">
          <div>
            <div class="sheet-who">${esc(run.prospect.name)}</div>
            <div class="sheet-where">${esc(run.prospect.company)}${run.prospect.role ? ` · ${esc(run.prospect.role)}` : ''}
              · <span class="mono">${esc(run.id)}</span></div>
          </div>
          <span class="spacer"></span>
          ${run.case_id ? `<span class="badge badge-mono">${esc(run.case_id)}</span>` : ''}
          ${badge(run.status)}
          <span class="badge">${run.confidence || 0}% confident</span>
          <button class="sheet-x" type="button" aria-label="Close">&times;</button>
        </div>
        <div class="sheet-body">
          <div class="verdict is-${s.tone === 'idle' ? 'flag' : s.tone}" style="margin-bottom:18px">
            <div class="v-mark">${s.glyph}</div>
            <div class="v-text">
              <div class="v-word">${esc(s.label)}</div>
              <div class="v-line">${esc(run.headline || s.line)}</div>
              <div class="v-sub">${esc(s.next)}</div>
            </div>
          </div>
          <div class="panes">
            <div class="pane-stack" id="sheet-draft"></div>
            <div class="pane-stack" id="sheet-side"></div>
          </div>
          <div class="pane" style="margin-top:16px">
            <div class="pane-head">The nine stages, as they ran
              <span class="spacer"></span>
              <span class="badge badge-mono">${esc(duration(run.ms))}</span></div>
            <div class="pane-body" style="padding:4px 19px">
              <ol class="timeline" id="sheet-timeline"></ol>
            </div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(sheet);
    document.body.classList.add('is-sheet');

    $('#sheet-draft').innerHTML = run.draft ? reviewEditor(run) : paneCard(
      'No draft was produced', '',
      `<div class="note note-warn">${esc(run.headline)}</div>
       ${run.selection_rationale ? `<div class="hint">${esc(run.selection_rationale)}</div>` : ''}
       <div class="hint">Nothing to approve. The process stopped deliberately rather than writing
         something it could not source.</div>`);

    $('#sheet-draft').insertAdjacentHTML('beforeend',
      [claimsPane(run), sourcesPane(run, chosen, byId)].filter(Boolean).join(''));

    $('#sheet-side').innerHTML = [
      hookPane(chosen),
      candidatesPane(run),
    ].filter(Boolean).join('');

    renderSheetTimeline();
    if (run.draft) wireReview(run);

    const close = () => closeSheet();
    $('.sheet-back', sheet).addEventListener('click', close);
    $('.sheet-x', sheet).addEventListener('click', close);
    document.addEventListener('keydown', escClose);
  }

  function renderSheetTimeline() {
    const run = state.sheetRun;
    const node = $('#sheet-timeline');
    if (!node || !run) return;
    node.innerHTML = renderSteps(run.stages || [], state.sheetOpenStages, null);
    wireSteps(node, state.sheetOpenStages, renderSheetTimeline);
  }

  function escClose(event) {
    if (event.key === 'Escape') closeSheet();
  }

  function closeSheet() {
    const sheet = $('#sheet');
    if (sheet) sheet.remove();
    document.body.classList.remove('is-sheet');
    document.removeEventListener('keydown', escClose);
    state.sheetRun = null;
  }

  function reviewEditor(run) {
    const review = run.review || {};
    const rv = REVIEW[review.state || 'pending'] || REVIEW.pending;
    return paneCard('The draft', `<span class="badge ${rv.cls}">${rv.label}</span>`, `
      <label class="field">
        <span class="field-k">Subject</span>
        <input class="input edit-subject" id="r-subject" type="text" value="${esc(run.draft.subject)}">
      </label>
      <textarea class="edit-body" id="r-body">${esc(run.draft.body)}</textarea>
      <div class="email-foot" style="border:1px solid var(--border);border-top:0;border-radius:0 0 8px 8px">
        <span id="r-count">${run.draft.word_count} words</span>
        <span>${(run.draft.citations || []).length} cited source(s)</span>
        <span>limit ${state.config.policy.max_draft_words} words</span>
      </div>
      <div class="review-acts">
        <button class="btn btn-sm btn-ok" data-act="approved">Approve</button>
        <button class="btn btn-sm btn-primary" data-act="edited">Save my edit</button>
        <button class="btn btn-sm btn-danger" data-act="rejected">Reject</button>
        <button class="btn btn-sm" id="r-copy" type="button">Copy</button>
      </div>
      ${review.decided_at ? `<div class="hint">Last decision: ${esc(review.state)} at
        ${esc(review.decided_at)}.</div>` : ''}
      <div class="hint">This tool has no mail credential. Approving records that a human cleared
        the draft for the rep's own sending tool.</div>`);
  }

  function wireReview(run) {
    const body = $('#r-body');
    body.addEventListener('input', () => {
      const n = words(body.value);
      const over = n > state.config.policy.max_draft_words;
      $('#r-count').innerHTML = `${n} words${over ? ' — over the limit' : ''}`;
      $('#r-count').style.color = over ? 'var(--reject)' : '';
    });

    $('#r-copy').addEventListener('click', () => {
      const text = `Subject: ${$('#r-subject').value}\n\n${body.value}`;
      if (navigator.clipboard) navigator.clipboard.writeText(text);
      toast('Draft copied to the clipboard');
    });

    $$('#sheet [data-act]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const stateName = btn.dataset.act;
        btn.disabled = true;
        try {
          await api(`/api/runs/${encodeURIComponent(run.id)}/review`, {
            method: 'POST',
            body: JSON.stringify({
              state: stateName,
              subject: $('#r-subject').value,
              body: body.value,
            }),
          });
          toast(`Marked ${stateName}`);
          closeSheet();
          await loadRuns({ quiet: true });
          if ($('#panel-queue').classList.contains('is-active')) loadQueue();
        } catch (err) {
          toast(err.message, true);
          btn.disabled = false;
        }
      });
    });
  }

  /* ==================================================== rules & policy == */

  const RUBRIC = [
    ['recency', 'Recency', 30, 'How fresh is it?',
      'Full marks inside the fresh window, partial inside the recent one. Past the cap it is not '
      + 'downranked, it is vetoed.'],
    ['role_relevance', 'Role fit', 25, 'Does this matter to this job?',
      'The weight table for the title decides. A person-level claim earns a further +5, because '
      + 'something the prospect said themselves always beats company news.'],
    ['specificity', 'Specificity', 20, 'Is there something quotable?',
      'A figure, a named entity, a date. "Raised $75m" scores; "is growing fast" does not.'],
    ['source_quality', 'Source quality', 15, 'Who published it?',
      'Tier-one press and the company\'s own domain outrank aggregators and syndicated reprints.'],
    ['actionability', 'Actionability', 10, 'Is there a reason to write today?',
      'Does the event imply a problem the seller plausibly solves, now rather than eventually.'],
  ];

  function renderPolicy() {
    const c = state.config;
    if (!c) return;
    const p = c.policy;

    /* The rubric. */
    $('#rubric').innerHTML = RUBRIC.map(([key, name, max, question, detail]) => `
      <article class="rcard">
        <div class="rcard-top">
          <span class="rcard-id">${esc(name)}</span>
          <span class="rcard-w">${max} pts</span>
        </div>
        <p class="rcard-q">${esc(question)}</p>
        <p class="rcard-d">${esc(detail)}</p>
        ${key === 'recency' ? `<ul class="rcard-th">
          <li><code>SIGNAL_FRESH_DAYS</code><b>${p.fresh_days}</b><span>full marks inside this many days</span></li>
          <li><code>SIGNAL_RECENT_DAYS</code><b>${p.recent_days}</b><span>partial marks inside this many</span></li>
          <li><code>SIGNAL_MAX_AGE_DAYS</code><b>${p.max_age_days}</b><span>past this, vetoed outright</span></li>
        </ul>` : ''}
        ${key === 'role_relevance' ? `<ul class="rcard-th">
          <li><code>role_weights</code><b>${Object.keys(c.role_weights).length}</b><span>weight tables, one per role family</span></li>
        </ul>` : ''}
      </article>`).join('');

    /* The weight matrix. */
    const kinds = Object.keys(c.role_weights.default || {});
    $('#matrix').innerHTML = `
      <thead><tr><th>Role family</th>${kinds.map((k) => `<th>${esc(k)}</th>`).join('')}</tr></thead>
      <tbody>
        ${Object.entries(c.role_weights).map(([family, row]) => {
          const top = Math.max(...kinds.map((k) => row[k] || 0));
          return `<tr><td>${esc(family)}</td>
            ${kinds.map((k) => `<td class="${(row[k] || 0) === top ? 'is-top' : ''}">${row[k] == null ? '—' : row[k]}</td>`).join('')}
          </tr>`;
        }).join('')}
      </tbody>`;

    /* The guardrails. */
    $('#sensitive').innerHTML = (c.sensitive_categories || []).map((s) =>
      `<span class="badge badge-reject">${esc(s.replace(/_/g, ' '))}</span>`).join('');

    $('#policy-kv').innerHTML = [
      ['Recency cap', `${p.max_age_days} days — older signals are vetoed, not downranked`],
      ['Fresh / recent', `${p.fresh_days}d full marks · ${p.recent_days}d partial`],
      ['Score floor', `${p.min_hook_score} company-level · ${p.min_person_hook_score} person-level`],
      ['Draft length', `under ${p.max_draft_words} words`],
      ['Repair passes', `${p.repair_attempts} — then the run is held for a human`],
      ['Default sources', esc(c.source_mode)],
    ].map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('');

    /* What each outcome means. */
    $('#outcomes').innerHTML = Object.keys(STATUS).filter((k) => k !== 'running').map((k) => {
      const s = STATUS[k];
      return `<div class="outcome">
        <div>${badge(k)}</div>
        <div class="outcome-d"><b>${esc(s.line)}</b> ${esc(s.next)}</div>
      </div>`;
    }).join('');

    /* Who the rep works for. */
    const seller = c.seller || {};
    $('#seller-kv').innerHTML = [
      ['Company', esc(seller.company)],
      ['One-liner', esc(seller.one_liner)],
      ['Rep', `${esc(seller.rep_name)}, ${esc(seller.rep_title)}`],
      ['What it sells', esc(seller.what_we_do)],
      ['Proof point', esc(seller.proof)],
    ].map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join('');

    $('#models').innerHTML = (c.models || []).map((m) =>
      `<span class="badge badge-mono">${esc(m)}</span>`).join('');
  }

  /* ==================================================== the doc index ===
     Built from the headings that are actually in the document, so it can
     never list a section that is not there, and it marks the section in view
     rather than only the one that was clicked. */

  function buildDocIndex() {
    const panel = $('#panel-how');
    const sections = $$('.doc-sec', panel).filter((s) => $('h2', s));
    if (!sections.length) return;

    const nav = document.createElement('nav');
    nav.className = 'doc-index';
    nav.setAttribute('aria-label', 'Sections');
    nav.innerHTML = '<p class="doc-index-k">On this page</p>'
      + sections.map((section, i) => {
        const title = $('h2', section).textContent.replace(/^\d+\.\s*/, '');
        return `<button class="doc-index-link" type="button" data-to="${esc(section.id)}">
          <span class="doc-index-n">${i + 1}</span><span>${esc(title)}</span></button>`;
      }).join('');
    panel.insertBefore(nav, panel.firstElementChild);

    const links = $$('.doc-index-link', nav);
    links.forEach((link) => {
      link.addEventListener('click', () => {
        const target = document.getElementById(link.dataset.to);
        if (target) window.scrollTo({ top: target.offsetTop - 40, behavior: 'smooth' });
      });
    });

    const spy = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const i = sections.indexOf(entry.target);
        links.forEach((link, j) => link.classList.toggle('is-here', j === i));
      });
    }, { rootMargin: '-96px 0px -62% 0px' });
    sections.forEach((section) => spy.observe(section));
  }

  /* ==================================================== the command bar ==
     An all-day tool trains people to reach for a palette before they look for
     a menu, so this is the fastest route to any page and to any prepared
     case - and, during a demo, the way to launch an edge case without hunting
     for its card. The button in the bar says the shortcut out loud, because a
     keyboard-only affordance is invisible to anyone watching for the first
     time. */

  const CMD_STATE = { open: false, items: [], index: 0, node: null };

  function commands() {
    const out = TABS.map((tab) => ({
      kind: 'page',
      label: TAB_NAMES[tab],
      hint: 'page',
      run: () => showTab(tab),
    }));

    state.cases.forEach((c) => {
      out.push({
        kind: 'case',
        label: `${c.id} — ${c.label.replace(/^(Happy path|Edge|Role A\/B) — /, '')}`,
        hint: c.kind === 'happy' ? 'happy' : 'edge',
        run: () => { fillCase(c.id); startRun(); },
      });
    });

    out.push({
      kind: 'action', hint: 'theme',
      label: `Switch to the ${currentTheme() === 'dark' ? 'light' : 'dark'} theme`,
      run: toggleTheme,
    });
    out.push({
      kind: 'action', hint: 'action', label: 'Reload runs and connector health',
      run: () => { loadRuns(); loadQueue(); loadHealth(); toast('Reloaded'); },
    });
    return out;
  }

  function openCmd() {
    if (CMD_STATE.open) return;
    CMD_STATE.open = true;
    CMD_STATE.index = 0;

    const node = document.createElement('div');
    node.className = 'cmd';
    node.id = 'cmd';
    node.innerHTML = `
      <div class="cmd-back"></div>
      <div class="cmd-box" role="dialog" aria-modal="true" aria-label="Command bar">
        <input class="cmd-input" id="cmd-input" type="text" autocomplete="off"
               placeholder="Jump to a page, or run a prepared case…">
        <ul class="cmd-list" id="cmd-list"></ul>
        <div class="cmd-foot"><span>&uarr;&darr; move</span><span>&crarr; run</span><span>esc close</span></div>
      </div>`;
    document.body.appendChild(node);
    document.body.classList.add('is-locked');
    CMD_STATE.node = node;

    $('.cmd-back', node).addEventListener('click', closeCmd);
    const input = $('#cmd-input', node);
    input.addEventListener('input', () => renderCmd(input.value));
    input.addEventListener('keydown', onCmdKey);
    renderCmd('');
    input.focus();
  }

  function closeCmd() {
    if (!CMD_STATE.open) return;
    CMD_STATE.open = false;
    if (CMD_STATE.node) CMD_STATE.node.remove();
    CMD_STATE.node = null;
    document.body.classList.remove('is-locked');
  }

  function renderCmd(query) {
    const needle = query.trim().toLowerCase();
    CMD_STATE.items = commands().filter((c) => c.label.toLowerCase().includes(needle));
    CMD_STATE.index = Math.min(CMD_STATE.index, Math.max(0, CMD_STATE.items.length - 1));

    const list = $('#cmd-list');
    if (!CMD_STATE.items.length) {
      list.innerHTML = '<li class="cmd-empty">Nothing matches that.</li>';
      return;
    }
    list.innerHTML = CMD_STATE.items.map((c, i) => `
      <li><button class="cmd-item ${i === CMD_STATE.index ? 'is-on' : ''}" type="button" data-i="${i}">
        <span class="k">${esc(c.hint)}</span><span class="t">${esc(c.label)}</span>
      </button></li>`).join('');

    $$('#cmd-list [data-i]').forEach((btn) => {
      btn.addEventListener('click', () => fireCmd(Number(btn.dataset.i)));
    });
  }

  function fireCmd(i) {
    const item = CMD_STATE.items[i];
    closeCmd();
    if (item) item.run();
  }

  function onCmdKey(event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const step = event.key === 'ArrowDown' ? 1 : -1;
      const n = CMD_STATE.items.length;
      if (!n) return;
      CMD_STATE.index = (CMD_STATE.index + step + n) % n;
      renderCmd($('#cmd-input').value);
      const on = $('#cmd-list .is-on');
      if (on) on.scrollIntoView({ block: 'nearest' });
    } else if (event.key === 'Enter') {
      event.preventDefault();
      fireCmd(CMD_STATE.index);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      closeCmd();
    }
  }

  $('#cmd-btn').addEventListener('click', openCmd);

  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      if (CMD_STATE.open) closeCmd(); else openCmd();
    }
  });

  /* ==================================================== boot =========== */

  (async function boot() {
    setTheme(currentTheme());
    setMode('auto');
    updateRoleRead();

    try {
      await loadConfig();
    } catch (err) {
      toast(`Could not reach the backend: ${err.message}`, true);
      return;
    }

    if (window.HOW) window.HOW.renderDiagrams(document);
    buildDocIndex();

    await Promise.all([
      loadCases().catch(() => toast('Could not load the test library', true)),
      loadRuns({ quiet: true }),
      loadHealth(),
    ]);

    showTab(location.hash.replace('#', '') || 'run');
    setInterval(loadHealth, 120000);
  })();
})();
