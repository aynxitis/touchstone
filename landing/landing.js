/* Touchstone — landing page behaviour.
   Two live things and one story:
     · the example panel: the saved run's report and cards, selectable by click
     · the check: one claim, three states, driven by scroll or by picking a step
     · the page's reveals
   Motion (motion.dev, the engine behind Framer Motion, vendored in vendor/motion.js) does
   the timing; CSS already shows everything, so a failed script leaves a readable page. */

(() => {
  'use strict';

  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const M = window.Motion || null;
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  // Marks that JS is running: the CSS uses html.js to collapse the nav into a hamburger.
  // Without a script the section links simply stay visible, so navigation never depends
  // on this file.
  document.documentElement.classList.add('js');

  // The hamburger: toggles the dropdown, closes on Escape and on picking a section.
  const burger = $('#nav-burger');
  const barIn = $('.bar-in');
  if (burger && barIn) {
    const setMenu = (open) => {
      barIn.classList.toggle('menu-open', open);
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    };
    burger.addEventListener('click', () => setMenu(!barIn.classList.contains('menu-open')));
    $$('#site-nav a').forEach((a) => a.addEventListener('click', () => setMenu(false)));
    addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && barIn.classList.contains('menu-open')) { setMenu(false); burger.focus(); }
    });
  }

  const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  // The app's label → tone map (static/app.js), kept in sync by hand: the landing only
  // needs the three verdicts the saved run contains, but unknown labels fall back to grey.
  const TONE = { SOURCED: 'green', PARTIAL: 'yellow', 'COULDN\'T CONFIRM': 'yellow', UNSUPPORTED: 'yellow', CONTRADICTED: 'red' };
  const tone = (label) => TONE[label] || 'grey';

  /* ── the saved run ─────────────────────────────────────────────────────
     Copied from examples/demo_run.json (the same file the app replays). Served by the
     app, /api/example-run wins: that copy is always the committed one. */
  const FALLBACK = {"claims":[{"claim":1,"text":"For full-year 2025, Transsion—the parent of TECNO, Infinix, and itel—led Africa's smartphone market with about 48% of shipments (over 40.5 million units), according to Omdia data. Africa shipped 84.4 million smartphones in 2025, up 13% year over year.","label":"SOURCED","url":"https://www.gizmochina.com/2026/02/25/transsion-captures-48-as-africa-smartphone-market-grows-13-in-2025/","facts":[{"fact":"For full-year 2025, Transsion—the parent of TECNO, Infinix, and itel—led Africa's smartphone market with about 48% of shipments (over 40.5 million units), according to Omdia data","status":"stated","quote":"Transsion — through TECNO, Infinix, and itel — maintained a commanding 48% market share for the year, shipping over 40.5 million units.","note":""},{"fact":"Africa shipped 84.4 million smartphones in 2025, up 13% year over year","status":"stated","quote":"New data from Omdia shows the continent shipped 84.4 million smartphones last year, up 13% year-over-year, the fastest pace of recovery since 2021.","note":""}]},{"claim":2,"text":"Brand / group: Transsion (TECNO, Infinix, itel); Q2 2025 shipment share: 51%; Annual trend: +6% year over year","label":"SOURCED","url":"https://tech-ish.com/2025/08/22/africa-kenya-smartphone-market-share-q2-2025/","facts":[{"fact":"Brand / group: Transsion (TECNO, Infinix, itel)","status":"stated","quote":"| TRANSSION (TECNO, Infinix, itel) | 9.7 | 51% | 9.2 | 51% | +6% |","note":""},{"fact":"Q2 2025 shipment share: 51%","status":"stated","quote":"| TRANSSION (TECNO, Infinix, itel) | 9.7 | 51% | 9.2 | 51% | +6% |","note":""},{"fact":"Annual trend: +6% year over year","status":"stated","quote":"| TRANSSION (TECNO, Infinix, itel) | 9.7 | 51% | 9.2 | 51% | +6% |","note":""}]},{"claim":3,"text":"Brand / group: Samsung; Q2 2025 shipment share: 19%; Annual trend: +3% year over year","label":"CONTRADICTED","url":"https://tech-ish.com/2025/08/22/africa-kenya-smartphone-market-share-q2-2025/","facts":[{"fact":"Brand / group: Samsung","status":"stated","quote":"| Samsung | 3.4 | 18% | 3.3 | 19% | +3% |","note":""},{"fact":"Q2 2025 shipment share: 19%","status":"contradicted","quote":"| Samsung | 3.4 | 18% | 3.3 | 19% | +3% |","note":"The page gives 18% for Q2 2025; 19% is its Q2 2024 figure."},{"fact":"Annual trend: +3% year over year","status":"stated","quote":"| Samsung | 3.4 | 18% | 3.3 | 19% | +3% |","note":""}]},{"claim":4,"text":"Brand / group: Xiaomi (including Redmi and POCO); Q2 2025 shipment share: 14%; Annual trend: +32% year over year","label":"SOURCED","url":"https://tech-ish.com/2025/08/22/africa-kenya-smartphone-market-share-q2-2025/","facts":[{"fact":"Brand / group: Xiaomi (including Redmi and POCO)","status":"stated","quote":"| Xiaomi (Redmi, POCO) | 2.8 | 14% | 2.1 | 12% | +32% |","note":""},{"fact":"Q2 2025 shipment share: 14%","status":"stated","quote":"| Xiaomi (Redmi, POCO) | 2.8 | 14% | 2.1 | 12% | +32% |","note":""},{"fact":"Annual trend: +32% year over year","status":"stated","quote":"| Xiaomi (Redmi, POCO) | 2.8 | 14% | 2.1 | 12% | +32% |","note":""}]},{"claim":5,"text":"Samsung was the strongest challenger, with Q4 shipments up 27%, helped by the Galaxy A series and broader mid-range lineup.","label":"SOURCED","url":"https://www.gizmochina.com/2026/02/25/transsion-captures-48-as-africa-smartphone-market-grows-13-in-2025/","facts":[{"fact":"Samsung was the strongest challenger, with Q4 shipments up 27%, helped by the Galaxy A series and broader mid-range lineup","status":"stated","quote":"Samsung held second place, posting 27% Q4 growth thanks to the Galaxy A series and a broader mid-range portfolio.","note":""}]},{"claim":6,"text":"Devices priced below $200 made up 81% of African smartphone shipments in 2025, underscoring the market's price sensitivity.","label":"SOURCED","url":"https://www.gizmochina.com/2026/02/25/transsion-captures-48-as-africa-smartphone-market-grows-13-in-2025/","facts":[{"fact":"Devices priced below $200 made up 81% of African smartphone shipments in 2025","status":"stated","quote":"Entry-level devices below $200 accounted for 81% of shipments in 2025, leaving vendors exposed to rising component costs.","note":""}]},{"claim":7,"text":"Note: figures based on shipments differ from \"usage\" or installed-base statistics; for example, Samsung can lead usage-based mobile market estimates even while Transsion leads new smartphone shipments.","label":"UNSUPPORTED","url":"https://tech-ish.com/2025/08/22/africa-kenya-smartphone-market-share-q2-2025/","facts":[{"fact":"Note: figures based on shipments differ from \"usage\" or installed-base statistics; for example, Samsung can lead usage-based mobile market estimates even while Transsion leads new smartphone shipments","status":"missing","quote":"","note":""}]}]};

  let run = FALLBACK;
  fetch('/api/example-run', { headers: { accept: 'application/json' } })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((data) => {
      if (data && Array.isArray(data.claims) && data.claims.length) {
        run = data;
        paintCounts();
        buildStory();
        render(selected);
        lockStoryHeight();
        lockDemoHeight();
      }
    })
    .catch(() => { /* static hosting: the copy above is the whole example */ });

  const claims = () => run.claims || [];
  const claimById = (id) => claims().find((c) => String(c.claim ?? c.id) === String(id));
  const countOf = (label) => claims().filter((c) => c.label === label).length;
  const firstOf = (label) => claims().find((c) => c.label === label);

  /* ── the card: the app's own markup (static/app.js buildCard) ─────────── */

  function figure(text, pattern) {
    const m = String(text || '').match(pattern);
    return m ? m[0] : '';
  }

  function highlight(html, token, cls = 'diff') {
    if (!token) return html;
    const i = html.indexOf(token);
    return i < 0 ? html : html.slice(0, i) + `<span class="${cls}">${token}</span>` + html.slice(i + token.length);
  }

  function buildCard(c, opts = {}) {
    const label = c.label || '';
    // The app shows the contradicted fact first: it is the reason the card exists.
    const facts = [...(c.facts || [])].sort(
      (a, b) => (b.status === 'contradicted') - (a.status === 'contradicted'));
    const bad = facts.find((f) => f.status === 'contradicted');
    let claim = esc(c.text || '');

    // The figure the page contradicts: the number the fact states, not every number.
    if (bad) claim = highlight(claim, figure(bad.fact, /\d+(?:[.,]\d+)?\s*%/));

    const parts = facts.map((f) => {
      let q = esc(f.quote || '');
      // On a contradicted fact, mark the page's own figure inside the quote.
      if (bad && f === bad) q = highlight(q, figure(f.note, /\d+(?:[.,]\d+)?\s*%/));
      const rejected = f.status === 'contradicted' ? ' class="rejected"' : '';
      return `<li${rejected} data-status="${esc(f.status)}">
        <div class="part-head"><span class="tag">${esc(f.status)}</span>
          <span class="part-text">${esc(f.fact)}</span></div>
        ${q ? `<blockquote class="quote">${q}</blockquote>` : ''}
        ${f.note ? `<p class="part-note">${esc(f.note)}</p>` : ''}
      </li>`;
    }).join('');

    const source = c.url
      ? `<a class="source" href="${esc(c.url)}" target="_blank" rel="noopener noreferrer"
            title="${esc(c.url)}">${esc(c.url)}</a>`
      : '';

    const card = `<article class="card" data-label="${esc(label)}">
      <div class="card-head">
        <span class="badge tone-${tone(label)}">${esc(label)}</span>
        <span class="cno">Claim ${esc(c.claim ?? c.id ?? '')}</span>
      </div>
      <p class="claim">${claim}</p>
      ${opts.stage ? '<span class="source-line" data-src></span>' : ''}
      <ul class="parts">${parts}</ul>
      ${source}
    </article>`;

    if (!opts.stage) return card;
    // The story card starts at its first state; landing.css reveals the rest per stage.
    return `<div class="card-stage" data-stage="1">${card}</div>`;
  }

  /* ── the example panel ───────────────────────────────────────────────── */

  const exampleHost = $('#example-card');
  const report = $('#report');
  let selected = null;

  function paintCounts() {
    $$('#counts [data-count]').forEach((b) => {
      const n = countOf(b.dataset.count);
      if (!reduce && M) M.animate(Number(b.textContent) || 0, n, {
        duration: 0.5, ease: 'easeOut', onUpdate: (v) => { b.textContent = Math.round(v); },
      });
      else b.textContent = n;
    });
    const bits = ['SOURCED', 'UNSUPPORTED', 'CONTRADICTED'].map((l) => `${countOf(l)} ${l.toLowerCase()}`);
    const summary = $('#summary');
    if (summary) summary.textContent = bits.join(', ') + '.';
  }

  function paintMarks() {
    $$('.rmark', report).forEach((m) => {
      const c = claimById(m.dataset.for);
      m.dataset.tone = c ? tone(c.label) : 'grey';
      m.classList.add('is-set');
    });
  }

  function markRow(id) {
    $$('[data-claim]', report).forEach((el) => {
      const on = String(el.dataset.claim) === String(id);
      el.classList.toggle('is-sel', on);
      el.setAttribute('aria-current', on ? 'true' : 'false');
    });
    $$('#counts .cnt').forEach((b) => {
      const c = claimById(id);
      b.setAttribute('aria-pressed', c && c.label === b.dataset.label ? 'true' : 'false');
    });
  }

  function render(id, animateIn = true) {
    const c = claimById(id) || claims()[2] || claims()[0];
    if (!c) return;
    selected = c.claim ?? c.id;
    exampleHost.innerHTML = buildCard(c, { link: true });
    const card = $('.card', exampleHost);
    markRow(selected);
    if (animateIn && !reduce && M) {
      M.animate(card, { opacity: [0, 1], y: [8, 0] }, { duration: 0.32, ease: [0.22, 1, 0.36, 1] });
    }
  }

  let playing = false;

  // The example panel must not change height when a different claim is picked: a jump there
  // drags every section below it up and down. Measure the tallest card once (in a hidden
  // probe at the same width) and reserve that much space in the result column.
  // (lockStoryHeight, below, does the same job for the three step cards.)
  function lockStoryHeight() {
    const storyEl = $('.story');
    const card = $('.story-card');
    if (!storyEl || !card) return;
    if (innerWidth <= 1020) { storyEl.style.removeProperty('--story-h'); return; }
    const h = Math.ceil(card.getBoundingClientRect().height);
    if (h > 0) storyEl.style.setProperty('--story-h', `${h}px`);
  }

  function lockDemoHeight() {
    const host = exampleHost;
    const result = $('.result');
    if (!host || !result || !claims().length) return;
    const cs = getComputedStyle(host);
    const contentW = host.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    if (contentW <= 0) return;

    const probe = document.createElement('div');
    probe.setAttribute('aria-hidden', 'true');
    probe.style.cssText = `position:absolute;left:0;top:0;visibility:hidden;` +
      `pointer-events:none;width:${contentW}px`;
    result.appendChild(probe);
    let tallest = 0;
    for (const c of claims()) {
      probe.innerHTML = buildCard(c);
      if (probe.firstElementChild) {
        tallest = Math.max(tallest, probe.firstElementChild.offsetHeight);
      }
    }
    probe.remove();

    const hostPad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
    const chrome = result.offsetHeight - host.offsetHeight;   // the result header only
    result.style.minHeight = `${Math.ceil(tallest + hostPad + chrome)}px`;
  }

  async function play() {
    if (playing) return;
    paintMarks();
    paintCounts();
    if (!M || reduce) { render(3, false); resumeAuto(); return; }
    playing = true;

    const scan = $('#scan');
    const marks = $$('.rmark', report);
    marks.forEach((m) => m.classList.remove('is-set'));
    exampleHost.style.opacity = '0';

    try {
      await M.animate(scan, { opacity: [0, 1, 1, 0], top: ['0%', '100%'] },
        { duration: 0.95, ease: 'easeInOut' }).finished;
    } catch { /* a cancelled animation must not leave the panel empty */ }

    marks.forEach((m, i) => {
      const c = claimById(m.dataset.for);
      m.dataset.tone = c ? tone(c.label) : 'grey';
      m.classList.add('is-set');
      M.animate(m, { opacity: [0, 1], scale: [0.4, 1] },
        { duration: 0.22, delay: 0.05 * i, ease: 'easeOut' });
    });

    await new Promise((r) => setTimeout(r, 280));
    render(3, false);
    exampleHost.style.opacity = '1';
    M.animate($('.card', exampleHost), { opacity: [0, 1], y: [10, 0] },
      { duration: 0.4, ease: [0.22, 1, 0.36, 1] });
    playing = false;
    resumeAuto();
  }

  // Clicking a line or a row picks its claim; the counts pick the first of a verdict.
  report.addEventListener('click', (e) => {
    const el = e.target.closest('[data-claim]');
    if (!el) return;
    render(el.dataset.claim);
  });
  report.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const el = e.target.closest('[data-claim]');
    if (!el) return;
    e.preventDefault();
    render(el.dataset.claim);
  });
  $$('[data-claim]', report).forEach((el) => {
    el.setAttribute('tabindex', '0');
    el.setAttribute('role', 'button');
    const c = claimById(el.dataset.claim);
    if (c) el.setAttribute('aria-label', `Show claim ${c.claim ?? c.id}: ${c.label.toLowerCase()}`);
  });

  $('#counts').addEventListener('click', (e) => {
    const b = e.target.closest('.cnt');
    if (!b) return;
    const c = firstOf(b.dataset.label);
    if (c) render(c.claim ?? c.id);
  });
  $('#replay').addEventListener('click', () => { autoOn = true; play(); });

  /* ── the example plays itself ─────────────────────────────────────────
     Once the panel has been on screen it walks the report claim by claim, in
     report order, and loops. Clicking a line, a count, or typing hands control
     to the reader for good; the Replay button asks for the walk again. Scrolling
     the panel away pauses the walk and brings it back when it returns. A visitor
     who asked for reduced motion gets the still card, never a moving one. */
  const AUTO_MS = 3200;
  let autoOn = true;
  let autoTimer = null;
  let autoSeen = false;

  function autoOrder() {
    return $$('[data-claim]', report).map((el) => String(el.dataset.claim));
  }

  function stopAuto() { clearInterval(autoTimer); autoTimer = null; }

  /* Restart the clock, so the first advance lands a full beat after whatever was
     keeping the panel busy (the scan replay, a scroll-away-and-back). */
  function resumeAuto() {
    if (!autoSeen || !autoOn || reduce) return;
    stopAuto();
    startAuto();
  }

  function startAuto() {
    if (!autoSeen || !autoOn || reduce || autoTimer) return;
    autoTimer = setInterval(() => {
      if (playing || document.hidden) return;
      const r = example.getBoundingClientRect();
      const visible = r.top < innerHeight && r.bottom > 0 &&
        (Math.min(r.bottom, innerHeight) - Math.max(r.top, 0)) / Math.max(1, r.height) >= 0.3;
      if (!visible) return;
      const order = autoOrder();
      if (!order.length) return;
      const i = order.indexOf(String(selected));
      render(order[(i + 1) % order.length]);
    }, AUTO_MS);
  }

  report.addEventListener('pointerdown', () => { autoOn = false; stopAuto(); });
  report.addEventListener('keydown', () => { autoOn = false; stopAuto(); });
  $('#counts').addEventListener('pointerdown', () => { autoOn = false; stopAuto(); });

  const example = $('#example');
  if (example && 'IntersectionObserver' in window) {
    new IntersectionObserver((entries) => {
      autoSeen = entries[0].isIntersecting;
      if (autoSeen) startAuto(); else stopAuto();
    }, { threshold: 0.3 }).observe(example);
  }

  /* ── the check: three states of one card ─────────────────────────────── */

  const STORY_CLAIM = 3;
  const story = $('#story-card');
  const stageWrap = () => $('.card-stage', story);
  let stage = 1;
  let storyLabel = '';

  function buildStory() {
    const c = claimById(STORY_CLAIM) || claims()[2];
    if (!c) return;
    storyLabel = c.label || '';
    // The check tells one story, not the whole card: the contradicted fact, whose note is
    // the payoff in stage 3. The example above already shows the card with every fact.
    const facts = [...(c.facts || [])]
      .sort((a, b) => (b.status === 'contradicted') - (a.status === 'contradicted'))
      .slice(0, 1);
    story.innerHTML = buildCard({ ...c, facts }, { stage: true, link: false });
    setStage(stage, false);
  }

  function setStage(n, notify = true) {
    stage = Math.max(1, Math.min(3, n));
    const w = stageWrap();
    if (w) w.dataset.stage = String(stage);

    // The label is the last thing assigned: until then the badge says so.
    const badge = w ? $('.badge', w) : null;
    if (badge) {
      const done = stage === 3;
      badge.textContent = done ? storyLabel : 'Checking';
      badge.className = 'badge ' + (done ? `tone-${tone(storyLabel)}` : 'tone-grey');
    }

    $$('#steps .step').forEach((s) => {
      s.setAttribute('aria-current', String(s.dataset.step) === String(stage) ? 'true' : 'false');
    });
    const bar = $('#story-bar');
    if (bar) bar.style.width = `${(stage / 3) * 100}%`;
    const cap = $('#story-caption');
    if (cap) cap.textContent = $$('#steps .step-title')[stage - 1].textContent;

    const src = $('[data-src]', story);
    if (src) {
      if (stage === 1) src.innerHTML = 'opening <span class="live">tech-ish.com</span>';
      else if (stage === 2) src.textContent = 'page read · quote found in the Q2 table';
      else src.textContent = 'quote verified · label assigned';
    }

    if (w && notify && !reduce && M) {
      const part = $('.parts li', w);
      if (part) M.animate(part, { opacity: [0.2, 1] }, { duration: 0.3, ease: 'easeOut' });
    }
  }

  // The line a step has to reach to become the current stage. On the wide layout the
  // steps are a screen tall, so the line sits low enough to give stage 3 a pinned beat.
  // Stacked, the steps are only a few lines each, so the line moves up: otherwise two
  // steps straddle it at once and the section opens on the wrong one.
  const readingLine = () =>
    innerHeight * (matchMedia('(max-width:1020px)').matches ? 0.2 : 0.55);

  $('#steps').addEventListener('click', (e) => {
    const b = e.target.closest('.step button');
    if (!b) return;
    const step = b.closest('.step');
    setStage(Number(step.dataset.step));
    // Click and scroll position have to agree, or the first scroll after the click hands
    // the stage straight back to the step the reading line is still on. So bring the
    // chosen step to the line: the click also moves the page, like a chapter link.
    // Two pixels past the line, because landing exactly on it can round to 495.0001 and
    // leave the stage on the previous step.
    const top = step.getBoundingClientRect().top + scrollY - readingLine() + 2;
    scrollTo({ top, behavior: reduce ? 'auto' : 'smooth' });
  });

  // The stage follows the step whose text has reached the reading line, a little below the
  // middle of the viewport. A scroll position, not an intersection band: with three tall
  // steps, a band hands two neighbours the same moment and the callback order decides it.
  {
    const steps = $$('#steps .step');
    let queued = false;
    const sync = () => {
      queued = false;
      const line = readingLine();
      let pick = 1;
      for (const s of steps) {
        if (s.getBoundingClientRect().top <= line) pick = Number(s.dataset.step);
      }
      if (pick !== stage) setStage(pick);
    };
    const onScroll = () => { if (!queued) { queued = true; requestAnimationFrame(sync); } };
    addEventListener('scroll', onScroll, { passive: true });
    addEventListener('resize', onScroll);
    sync();
  }

  /* ── reveals ─────────────────────────────────────────────────────────── */

  const reveal = ['.hero .eyebrow', '.hero .display', '.hero .lead', '.hero .actions',
    '.demo', '.band-head > *', '.check-head', '.story-side',
    '.key-in > *', '.limits .h2', '.spec-note', '.honest', '.close-in > *'];

  if (M && !reduce) {
    reveal.forEach((sel) => {
      $$(sel).forEach((el) => {
        el.style.opacity = '0';
        M.inView(el, () => {
          M.animate(el, { opacity: [0, 1], y: [14, 0] },
            { duration: 0.55, ease: [0.22, 1, 0.36, 1] });
        }, { margin: '0px 0px -10% 0px' });
      });
    });

    // The three assistants rise, then hand the element back to CSS so the hover scale is
    // not held down by an inline transform.
    $$('.findings > div').forEach((el) => {
      el.style.opacity = '0';
      M.inView(el, () => {
        M.animate(el, { opacity: [0, 1], y: [18, 0] },
          { duration: 0.55, ease: [0.22, 1, 0.36, 1] });
        // Motion leaves `opacity:1; transform:none` inline after the reveal; that beats
        // the hover scale and the sibling dim. Clear it once the animation has landed.
        setTimeout(() => { el.style.opacity = ''; el.style.transform = ''; }, 720);
      }, { margin: '0px 0px -12% 0px' });
    });

    // The check's three moves arrive like a deck: each dark card slides up as it enters.
    $$('#steps .step').forEach((el) => {
      el.style.opacity = '0';
      M.inView(el, () => {
        M.animate(el, { opacity: [0, 1], y: [76, 0] },
          { duration: 0.62, ease: [0.22, 1, 0.36, 1] });
      }, { margin: '0px 0px -14% 0px' });
    });

    // The hero is above the fold: let it arrive on load, not on scroll.
    M.animate('.hero .eyebrow, .hero .display, .hero .lead, .hero .actions',
      { opacity: [0, 1], y: [14, 0] },
      { duration: 0.6, delay: M.stagger(0.07), ease: [0.22, 1, 0.36, 1] });
  }

  /* ── limits: cards slide in left to right, then all numbers count up together ── */

  {
    const spec = $('.spec');
    if (spec) {
      const nums = $$('.num', spec);
      const targets = nums.map((el) => Number(el.textContent) || 0);
      const fire = () => {
        spec.classList.add('is-in');
        if (!M || reduce) return;
        M.animate(0, 1, {
          duration: 1.5, ease: [0.16, 1, 0.3, 1],
          onUpdate: (t) => {
            nums.forEach((el, i) => { el.textContent = String(Math.round(targets[i] * t)); });
          },
        });
      };
      if (M && !reduce) {
        // Armed: the cards are held left and invisible until the section is reached. JS
        // adds the class, so a blocked script leaves the numbers sitting in place.
        spec.classList.add('is-armed');
        nums.forEach((el) => { el.textContent = '0'; });
        M.inView(spec, () => {
          spec.classList.remove('is-armed');
          fire();
        }, { amount: 0.35 });
      } else {
        fire();
      }
    }
  }

  /* ── the MCP endpoint: click to copy ─────────────────────────────────── */

  {
    const btn = $('#copy-url');
    const flag = $('#copy-flag');
    let flagTimer = 0;
    const say = (text) => {
      if (!flag) return;
      flag.textContent = text;
      flag.classList.add('is-on');
      clearTimeout(flagTimer);
      flagTimer = setTimeout(() => {
        flag.textContent = '';
        flag.classList.remove('is-on');
      }, 1600);
    };
    const fallbackCopy = (text) => {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;left:-9999px;top:0';
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch { ok = false; }
      ta.remove();
      return ok;
    };
    if (btn) {
      btn.addEventListener('click', async () => {
        const text = btn.dataset.copy || btn.textContent.trim();
        let ok = false;
        try {
          if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(text);
            ok = true;
          }
        } catch { ok = false; }
        if (!ok) ok = fallbackCopy(text);
        say(ok ? 'Copied' : 'Press Ctrl+C');
      });
    }
  }

  /* ── start ───────────────────────────────────────────────────────────── */

  paintCounts();
  buildStory();
  render(3, false);
  lockStoryHeight();
  lockDemoHeight();

  let lockTimer = 0;
  addEventListener('resize', () => {
    clearTimeout(lockTimer);
    lockTimer = setTimeout(() => { lockStoryHeight(); lockDemoHeight(); }, 180);
  });
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => { lockStoryHeight(); lockDemoHeight(); }).catch(() => {});
  }

  if (M && !reduce) {
    const demo = $('#example');
    let played = false;
    M.inView(demo, () => { if (!played) { played = true; play(); } }, { amount: 0.35 });
  } else {
    paintMarks();
  }
})();
