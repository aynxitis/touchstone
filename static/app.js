// Touchstone frontend. Every piece of report text, page text and model output is
// untrusted: it is only ever rendered with textContent, never innerHTML.
"use strict";

const MAX_CHARS = 20000;
const TONES = {
  "SOURCED": "green", "PARTIAL": "yellow", "COULDN'T CONFIRM": "yellow",
  "UNSUPPORTED": "yellow", "CONTRADICTED": "red",
  "UNVERIFIED": "blue", "OPINION": "blue", "SOURCE UNREACHABLE": "grey",
  "NO SOURCE GIVEN": "grey", "NOT CHECKED": "grey", "ERROR": "grey",
};
// Summary order and wording: "9 sourced, 3 partial, 1 contradicted, 2 unreachable"
const SUMMARY = [
  ["SOURCED", "sourced"], ["PARTIAL", "partial"], ["COULDN'T CONFIRM", "couldn't confirm"],
  ["UNSUPPORTED", "unsupported"],
  ["CONTRADICTED", "contradicted"], ["UNVERIFIED", "unverified"], ["OPINION", "opinion"],
  ["SOURCE UNREACHABLE", "unreachable"], ["NOT CHECKED", "not checked (time limit)"],
  ["ERROR", "failed"],
];
const SUMMARY_WORDS = new Map(SUMMARY);
const STATUS_TEXT = {
  stated: "stated", missing: "not found", contradicted: "contradicted",
  unconfirmed: "couldn't confirm",
  possible: "possibly stated",
};

const $ = (id) => document.getElementById(id);
const str = (v) => (typeof v === "string" ? v : "");
const arr = (v) => (Array.isArray(v) ? v : []);
const int = (v) => {
  const n = typeof v === "number" ? v : parseInt(v, 10);
  return Number.isInteger(n) && n >= 0 ? n : null;
};
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return str(u); } };

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = String(text);
  return e;
}

// Only http(s) links become clickable: a javascript: URL in a report would be XSS.
function safeUrl(u) {
  try {
    const url = new URL(u);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch { return null; }
}

let liveTimer = null;
function announce(text) {
  const node = $("live");
  if (!node) return;
  clearTimeout(liveTimer);
  node.textContent = "";
  liveTimer = setTimeout(() => { node.textContent = text; }, 180);
}

// ---------------- theme ----------------
const THEME_KEY = "touchstone.theme";

function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const btn = $("theme");
  if (!btn) return;
  btn.textContent = theme === "dark" ? "◑" : "◐";
  const next = theme === "dark" ? "light" : "dark";
  btn.setAttribute("aria-label", `Switch to ${next} theme`);
  btn.title = `Switch to ${next} theme`;
}

function initTheme() {
  let theme = "";
  try { theme = localStorage.getItem(THEME_KEY) || ""; } catch { /* private mode */ }
  if (theme !== "light" && theme !== "dark") {
    theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  applyTheme(theme);
}

function toggleTheme() {
  const theme = currentTheme() === "dark" ? "light" : "dark";
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* private mode */ }
  applyTheme(theme);
  layout();
}

// ---------------- state ----------------
const state = {
  report: "", name: "", running: false, startedAt: 0, elapsed: 0, tokens: null,
  lastRun: null, replay: false, selected: null, pager: [], pagerIdx: 0,
  filter: null, matchedOpen: false, hideOk: false,
  total: 0, done: 0, cited: 0, counts: {},
};
const doc = { units: [], claims: [], byNo: new Map(), unplaced: [] };

/* ---------------- markdown ----------------
   A small block parser, enough for the reports the engine is fed: headings,
   paragraphs, lists, tables (with a source line per row), quotes, rules, code.
   Every block gets data-line; table rows and list items become anchor units. */

const STOP = new Set(("a an the and or but if then than that this these those of to in on for with by " +
  "from as at is are was were be been it its his her their our your we you they i not no nor so such " +
  "about into over under more most less least can could may might will would should do does did has " +
  "have had also very just new said says one two three").split(" "));

function plain(text) {
  return String(text).replace(/`/g, "").replace(/\*\*/g, "").replace(/[*_]/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").trim();
}

function renderInline(text) {
  const frag = document.createDocumentFragment();
  let i = 0;
  let buf = "";
  const flush = () => {
    if (buf) { frag.append(document.createTextNode(buf)); buf = ""; }
  };
  while (i < text.length) {
    const ch = text[i];
    if (ch === "[") {
      const close = text.indexOf("]", i + 1);
      if (close > i && text[close + 1] === "(") {
        const end = urlEnd(text, close + 2);
        if (end > 0) {
          const label = text.slice(i + 1, close);
          const url = text.slice(close + 2, end).trim().split(/\s+/)[0];
          const href = safeUrl(url);
          flush();
          if (href) {
            const a = document.createElement("a");
            a.href = href;
            a.target = "_blank";
            a.rel = "noopener noreferrer";
            a.append(renderInline(label || url));
            frag.append(a);
          } else {
            frag.append(document.createTextNode(label ? `${label} (${url})` : url));
          }
          i = end + 1;
          continue;
        }
      }
    } else if (ch === "*" && text[i + 1] === "*") {
      const close = text.indexOf("**", i + 2);
      if (close > i + 2) {
        flush();
        const strong = el("strong");
        strong.append(renderInline(text.slice(i + 2, close)));
        frag.append(strong);
        i = close + 2;
        continue;
      }
    } else if (ch === "`") {
      const close = text.indexOf("`", i + 1);
      if (close > i) {
        flush();
        frag.append(el("code", "", text.slice(i + 1, close)));
        i = close + 1;
        continue;
      }
    } else if (ch === "*") {
      const close = text.indexOf("*", i + 1);
      if (close > i + 1 && !/\s/.test(text[i + 1] || "") && !/\s/.test(text[close - 1] || "")) {
        flush();
        const em = el("em");
        em.append(renderInline(text.slice(i + 1, close)));
        frag.append(em);
        i = close + 1;
        continue;
      }
    }
    buf += ch;
    i += 1;
  }
  flush();
  return frag;
}

function urlEnd(text, start) {
  let depth = 1;
  for (let i = start; i < text.length; i += 1) {
    if (text[i] === "(") depth += 1;
    else if (text[i] === ")") {
      depth -= 1;
      if (!depth) return i;
    } else if (text[i] === "\n") return -1;
  }
  return -1;
}

const isRuleLine = (l) => /^\s*((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$/.test(l);
const isHeadingLine = (l) => /^(#{1,6})\s+/.test(l);
const isFenceLine = (l) => /^\s*```/.test(l);
const isQuoteLine = (l) => /^\s*>/.test(l);
const isListLine = (l) => /^\s*([-*+]|\d+[.)])\s+/.test(l);

function isTableStart(lines, i) {
  return /\|/.test(lines[i] || "") &&
    /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[i + 1] || "");
}

function splitCells(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function renderTable(article, lines, i, addUnit) {
  const head = splitCells(lines[i]);
  const align = splitCells(lines[i + 1]).map((c) => {
    const left = c.startsWith(":");
    const right = c.endsWith(":");
    return left && right ? "center" : right ? "right" : left ? "left" : "";
  });
  const table = el("table");
  const thead = el("thead");
  const hrow = el("tr");
  const headText = [];
  head.forEach((cell, idx) => {
    const th = el("th");
    th.append(renderInline(cell));
    headText[idx] = th.textContent.trim();
    if (align[idx] === "right") th.classList.add("n");
    if (align[idx] && align[idx] !== "right") th.classList.add(`ta-${align[idx][0]}`);
    hrow.append(th);
  });
  thead.append(hrow);
  const tbody = el("tbody");
  let j = i + 2;
  while (j < lines.length && lines[j].trim() && lines[j].includes("|")) {
    const row = splitCells(lines[j]);
    if (!row.length) { j += 1; continue; }
    const tr = el("tr");
    const width = Math.max(head.length, row.length);
    for (let idx = 0; idx < width; idx += 1) {
      const td = el("td");
      td.dataset.l = headText[idx] || "";
      if (align[idx] === "right") td.classList.add("n");
      if (align[idx] && align[idx] !== "right") td.classList.add(`ta-${align[idx][0]}`);
      td.append(renderInline(row[idx] || ""));
      tr.append(td);
    }
    tbody.append(tr);
    addUnit(tr, "tr", j);
    j += 1;
  }
  table.append(thead, tbody);
  article.append(table);
  return j;
}

function renderList(article, lines, i, addUnit) {
  const first = /^\s*([-*+]|\d+[.)])\s+/.exec(lines[i]);
  const ordered = /\d/.test(first[1]);
  const list = el(ordered ? "ol" : "ul");
  article.append(list);
  let current = null;
  while (i < lines.length) {
    const m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i]);
    if (!m) break;
    const nested = m[1].length >= 2 && current;
    if (nested) {
      let sub = current.querySelector(":scope > ul, :scope > ol");
      if (!sub) { sub = el(/\d/.test(m[2]) ? "ol" : "ul"); current.append(sub); }
      const li = el("li");
      li.append(renderInline(m[3]));
      sub.append(li);
      addUnit(li, "li", i);
    } else {
      current = el("li");
      current.append(renderInline(m[3]));
      list.append(current);
      addUnit(current, "li", i);
    }
    i += 1;
  }
  return i;
}

function renderReport(article, text) {
  const units = [];
  const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
  const addUnit = (node, kind, line) => {
    const t = node.textContent.replace(/\s+/g, " ").trim();
    if (!t) return;
    node.dataset.line = String(line + 1);
    units.push({ el: node, kind, index: units.length, text: t, line: line + 1 });
  };
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i += 1; continue; }

    if (isFenceLine(line)) {
      const lang = line.replace(/^\s*```/, "").trim();
      const body = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) { body.push(lines[i]); i += 1; }
      i += 1;
      const pre = el("pre");
      const code = el("code");
      code.textContent = body.join("\n");
      if (lang) code.dataset.lang = lang;
      pre.append(code);
      article.append(pre);
      continue;
    }

    const h = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (h) {
      const heading = el(`h${h[1].length}`);
      heading.append(renderInline(h[2]));
      article.append(heading);
      i += 1;
      continue;
    }

    if (isRuleLine(line)) { article.append(el("hr")); i += 1; continue; }

    if (isTableStart(lines, i)) { i = renderTable(article, lines, i, addUnit); continue; }

    if (isQuoteLine(line)) {
      const body = [];
      while (i < lines.length && isQuoteLine(lines[i])) {
        body.push(lines[i].replace(/^\s*>\s?/, ""));
        i += 1;
      }
      const q = el("blockquote");
      q.append(renderInline(body.join(" ")));
      article.append(q);
      continue;
    }

    if (isListLine(line)) { i = renderList(article, lines, i, addUnit); continue; }

    const start = i;
    const buf = [line.trim()];
    i += 1;
    while (i < lines.length && lines[i].trim() &&
      !isFenceLine(lines[i]) && !isHeadingLine(lines[i]) && !isRuleLine(lines[i]) &&
      !isQuoteLine(lines[i]) && !isListLine(lines[i]) && !isTableStart(lines, i)) {
      buf.push(lines[i].trim());
      i += 1;
    }
    const p = el("p");
    p.append(renderInline(buf.join(" ")));
    article.append(p);
    addUnit(p, "p", start);
  }
  return units;
}

/* ---------------- anchoring ----------------
   The engine gives no line numbers and paraphrases table cells, so a claim is
   anchored to the smallest rendered unit (paragraph, list item, table row) that
   shares its figures and distinctive words. Two hits minimum; no best guess —
   anything under the threshold is listed in the tray as not located. */

const FIGURE = /(\d[\d,]*(?:\.\d+)?)\s*(%|percent\b|percentage points?\b|bn\b|billion\b|million\b|thousand\b)/gi;

function figureUnit(word) {
  const w = word.toLowerCase();
  if (w === "%") return "%";
  if (w.startsWith("percentage")) return "pp";
  if (w.startsWith("percent")) return "%";
  if (w.startsWith("b")) return "bn";
  if (w.startsWith("m")) return "m";
  return "k";
}

function figureValue(raw) {
  const s = raw.replace(/\s/g, "");
  const v = /^\d{1,3}(,\d{3})+$/.test(s) ? Number(s.replace(/,/g, "")) : Number(s.replace(",", "."));
  return Number.isFinite(v) ? v : null;
}

function figuresIn(text) {
  const out = [];
  FIGURE.lastIndex = 0;
  let m;
  while ((m = FIGURE.exec(text))) {
    const value = figureValue(m[1]);
    if (value !== null) out.push({ unit: figureUnit(m[2]), value, start: m.index, end: m.index + m[0].length });
  }
  return out;
}

function numbersOf(text) {
  return new Set(figuresIn(text).map((f) => `${f.value}${f.unit}`));
}

function wordsOf(text) {
  const out = new Set();
  const words = String(text).toLowerCase().replace(/[’']/g, "").match(/[a-z][a-z0-9-]{2,}/g) || [];
  for (const raw of words) {
    for (const w of raw.split("-")) {
      if (w.length >= 3 && !STOP.has(w)) out.add(w);
    }
  }
  return out;
}

function signalOf(label) {
  const l = String(label || "").toUpperCase();
  if (l === "CONTRADICTED") return "bad";
  if (l === "UNSUPPORTED" || l === "COULDN'T CONFIRM" || l === "PARTIAL") return "unsup";
  if (l === "SOURCED") return "ok";
  return "info";
}

const byUnit = (a, b) => (a.unit.index - b.unit.index) || ((a.offset || 0) - (b.offset || 0));

function matchUnit(text) {
  const cw = wordsOf(text);
  const cn = numbersOf(text);
  if (!cw.size && !cn.size) return null;
  let best = null, bestScore = 0, bestWords = 0, bestNums = 0;
  for (const unit of doc.units) {
    let score = 0, wn = 0, nn = 0;
    for (const n of cn) if (unit.nums.has(n)) { score += 2; nn += 1; }
    for (const w of cw) if (unit.words.has(w)) { score += 1; wn += 1; }
    if (score > bestScore) { bestScore = score; best = unit; bestWords = wn; bestNums = nn; }
  }
  if (!best || bestScore < 4) return null;
  if (bestNums === 0 && bestWords < 3) return null;
  return best;
}

function addGutter(unit, claim) {
  let box = unit.gbox;
  if (!box) {
    const cell = unit.el.tagName === "TR" ? unit.el.cells[0] : unit.el;
    if (!cell) return;
    box = el("span", "gmarks");
    cell.append(box);
    unit.gbox = box;
  }
  const mark = el("button", `gmark ${claim.kind}`);
  mark.type = "button";
  const title = `Claim ${claim.no}: ${claim.label.toLowerCase()}`;
  mark.title = title;
  mark.setAttribute("aria-label", `${title}. Show in document.`);
  mark.addEventListener("click", (ev) => {
    ev.preventDefault();
    ev.stopPropagation();
    selectClaim(claim.no, true);
  });
  box.append(mark);
  claim.gmark = mark;
}

function attachClaim(ev) {
  const no = int(ev.claim);
  if (no === null) return null;
  const label = str(ev.label).toUpperCase() || "UNKNOWN";
  const unit = matchUnit(str(ev.text));
  const claim = { no, label, text: str(ev.text), kind: signalOf(label), unit,
                  offset: 0, card: null, row: null, mark: null };
  doc.byNo.set(no, claim);
  doc.claims.push(claim);
  if (unit) {
    if (!unit.claims) unit.claims = [];
    claim.offset = unit.claims.length * 7;
    unit.claims.push(claim);
    addGutter(unit, claim);
  } else {
    doc.unplaced.push(claim);
  }
  renderRuler();
  return claim;
}

/* ---------------- ruler, pager, selection ---------------- */

function layout() {
  const pane = $("docpane");
  const ovr = $("ovr");
  const win = $("ovrwin");
  const top = $("totop");
  if (!pane || !ovr) return;
  if (!state.report) {
    ovr.hidden = true;
    top.hidden = true;
    return;
  }
  ovr.hidden = false;
  const sh = pane.scrollHeight;
  const ch = pane.clientHeight;
  const h = ovr.clientHeight;
  const scrollable = sh > ch + 4 && h > 0;
  win.style.display = scrollable ? "block" : "none";
  if (scrollable) {
    const winH = Math.max(16, Math.round((ch / sh) * h));
    const winTop = Math.round((pane.scrollTop / sh) * h);
    win.style.height = `${winH}px`;
    win.style.top = `${Math.max(0, Math.min(h - winH, winTop))}px`;
  }
  for (const c of doc.claims) {
    if (!c.mark || !c.unit) continue;
    const rect = c.unit.el.getBoundingClientRect();
    const paneRect = pane.getBoundingClientRect();
    const y = ((rect.top - paneRect.top + pane.scrollTop) / sh) * h + (c.offset || 0);
    c.mark.style.top = `${Math.max(0, Math.min(h - 9, Math.round(y)))}px`;
  }
  top.hidden = !scrollable;
  top.classList.toggle("low", pane.scrollTop < ch * 0.5);
  paintPager();
}

function renderRuler() {
  const ovr = $("ovr");
  for (const old of ovr.querySelectorAll(".ovr-mark")) old.remove();
  for (const c of doc.claims) c.mark = null;
  ovr.hidden = !state.report;
  if (!state.report) return;
  for (const c of [...doc.claims].filter((x) => x.unit).sort(byUnit)) {
    const mark = el("button", `ovr-mark m-${c.kind}`);
    mark.type = "button";
    const title = `Claim ${c.no}: ${c.label.toLowerCase()}`;
    mark.title = title;
    mark.setAttribute("aria-label", `${title}. Show in document.`);
    mark.addEventListener("click", (ev) => {
      ev.stopPropagation();
      selectClaim(c.no, true);
    });
    ovr.append(mark);
    c.mark = mark;
  }
  layout();
}

function selectClaim(no, scroll) {
  const claim = doc.byNo.get(Number(no));
  if (!claim) return;
  state.selected = claim.no;
  for (const node of document.querySelectorAll(".paper .is-sel, .card.is-sel, .mrow.is-sel")) {
    node.classList.remove("is-sel");
  }
  if (claim.unit) claim.unit.el.classList.add("is-sel");
  if (claim.card) claim.card.classList.add("is-sel");
  if (claim.row) claim.row.classList.add("is-sel");
  if (scroll && claim.unit) {
    claim.unit.el.scrollIntoView({ block: "center", behavior: "smooth" });
    if (claim.card) claim.card.scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (claim.row && !$("matched").hidden) {
      setMatchedOpen(true);
      claim.row.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }
  const at = state.pager.indexOf(claim);
  if (at >= 0) {
    state.pagerIdx = at;
    paintPager();
  }
}

function paintPager() {
  const bar = $("pagerbar");
  const total = state.pager.length;
  const idx = total ? Math.max(0, Math.min(state.pagerIdx, total - 1)) : 0;
  bar.classList.toggle("show", total > 0);
  $("pgn").textContent = total ? `${idx + 1} / ${total}` : "0 / 0";
  $("prev").disabled = idx <= 0;
  $("next").disabled = idx >= total - 1;
}

function rebuildPager() {
  state.pager = doc.claims.filter((c) => c.unit && (c.kind === "bad" || c.kind === "unsup")).sort(byUnit);
  if (state.selected !== null) {
    const at = state.pager.findIndex((c) => c.no === state.selected);
    if (at >= 0) state.pagerIdx = at;
  }
  state.pagerIdx = Math.min(state.pagerIdx, Math.max(0, state.pager.length - 1));
  paintPager();
}

function stepProblem(dir) {
  if (!state.pager.length) return;
  const at = Math.max(0, Math.min(state.pager.length - 1, state.pagerIdx + dir));
  state.pagerIdx = at;
  selectClaim(state.pager[at].no, true);
}

let rulerDrag = false;

function scrollFromRuler(y) {
  const pane = $("docpane");
  const rect = $("ovr").getBoundingClientRect();
  const frac = Math.min(1, Math.max(0, (y - rect.top) / rect.height));
  const max = pane.scrollHeight - pane.clientHeight;
  if (max > 0) pane.scrollTop = frac * max;
}

/* ---------------- card rendering ---------------- */

// The reason line restates the rows above it; only what the rows don't show is kept.
const REASON_PREFIX = [
  ["contradicted", "Contradicted by the page"], ["stated", "Stated"],
  ["unconfirmed", "Couldn't confirm (code check)"],
  ["possible", "Possibly stated, check the page line shown"], ["missing", "Not in the checked passages"],
];

function reasonExtra(ev) {
  let reason = str(ev.reason);
  const facts = arr(ev.facts).filter((f) => f && typeof f === "object");
  const shown = [];
  for (const [status, prefix] of REASON_PREFIX) {
    const xs = facts.filter((f) => str(f.status) === status).map((f) => str(f.fact));
    if (xs.length) shown.push(`${prefix}: ${xs.join("; ")}.`);
  }
  for (const f of facts) if (str(f.note)) shown.push(str(f.note));
  const framing = arr(ev.framing).filter((x) => str(x));
  if (framing.length) shown.push(`Framing not checked: ${framing.join("; ")}.`);
  for (const piece of shown) {
    const i = reason.indexOf(piece);
    const end = i + piece.length;
    if (i >= 0 && (i === 0 || reason[i - 1] === " ") && (end === reason.length || reason[end] === " ")) {
      reason = reason.slice(0, i) + reason.slice(end);
    }
  }
  return reason.replace(/\s{2,}/g, " ").trim();
}

// Marks the figures the engine's contradicted facts put in doubt, and the page's
// differing figures. Only a two-sided pair is ever marked.
function diffMarks(ev) {
  const claimText = str(ev.text);
  const claim = figuresIn(claimText);
  const claimMarks = [];
  const quoteMarks = new Map();
  arr(ev.facts).forEach((f, i) => {
    if (!f || typeof f !== "object" || str(f.status) !== "contradicted") return;
    const quote = str(f.quote);
    if (!quote) return;
    const fact = figuresIn(str(f.fact));
    const mine = claim.filter((c) => fact.some((g) => g.unit === c.unit && g.value === c.value));
    const theirs = figuresIn(quote).filter((q) =>
      mine.some((c) => c.unit === q.unit) &&
      !claim.some((c) => c.unit === q.unit && c.value === q.value) &&
      !fact.some((g) => g.unit === q.unit && g.value === q.value));
    if (!mine.length || !theirs.length) return;
    for (const m of mine) claimMarks.push({ ...m, title: "The figure the page contradicts" });
    quoteMarks.set(i, theirs.map((q) => ({ ...q, title: "The page's figure" })));
  });
  return { claimMarks, quoteMarks };
}

function appendMarked(node, text, marks) {
  const sorted = [...marks].filter((m) => m.start >= 0 && m.end > m.start && m.end <= text.length)
    .sort((a, b) => a.start - b.start);
  let pos = 0;
  for (const m of sorted) {
    if (m.start < pos) continue;
    if (m.start > pos) node.append(document.createTextNode(text.slice(pos, m.start)));
    const span = el("span", "diff", text.slice(m.start, m.end));
    if (m.title) span.title = m.title;
    node.append(span);
    pos = m.end;
  }
  if (pos < text.length) node.append(document.createTextNode(text.slice(pos)));
}

function renderCard(ev) {
  const label = str(ev.label) || "UNKNOWN";
  const tone = TONES[label] || "grey";
  const card = el("article", "card");
  card.dataset.label = label;
  const n = int(ev.claim);
  if (n !== null) card.dataset.claim = String(n);

  const head = el("div", "card-head");
  head.append(el("span", `badge tone-${tone}`, label));
  if (n !== null) head.append(el("span", "cno", `Claim ${n}`));
  card.append(head);

  const { claimMarks, quoteMarks } = diffMarks(ev);
  const claim = el("p", "claim");
  appendMarked(claim, str(ev.text), claimMarks);
  card.append(claim);
  for (const note of arr(ev.notes)) if (str(note)) card.append(el("p", "part-note", str(note)));

  const sources = arr(ev.sources).filter((s) => s && typeof s === "object");
  const multi = sources.length > 1;
  const parts = el("ul", "parts");
  const facts = arr(ev.facts)
    .map((f, i) => ({ f, i }))
    .filter(({ f }) => f && typeof f === "object")
    .sort((a, b) => {
      const ra = str(a.f.status) === "contradicted" ? 0 : 1;
      const rb = str(b.f.status) === "contradicted" ? 0 : 1;
      return ra - rb || a.i - b.i;
    });
  for (const { f, i } of facts) {
    const status = str(f.status);
    const li = el("li", status === "contradicted" ? "rejected" : "");
    li.dataset.status = status || "unknown";
    const ph = el("div", "part-head");
    ph.append(el("span", "tag", STATUS_TEXT[status] || "unclear"));
    ph.append(el("span", "part-text", str(f.fact)));
    li.append(ph);
    const where = [multi && str(f.source) ? host(f.source) : "", int(f.page) ? `p. ${f.page}` : ""]
      .filter(Boolean).join(", ");
    const quote = (text, marks) => {
      const q = el("blockquote", "quote");
      q.append(document.createTextNode("“"));
      appendMarked(q, text, marks || []);
      q.append(document.createTextNode("”"));
      if (where) q.append(el("span", "where", ` (${where})`));
      return q;
    };
    if (str(f.quote)) li.append(quote(str(f.quote), quoteMarks.get(i)));
    if (str(f.evidence)) {
      li.append(el("p", "part-note", "Not in the passages checked, but this line on the page has its figures. Check it:"));
      li.append(quote(str(f.evidence)));
    }
    if (str(f.rejected_quote)) {
      li.append(el("p", "part-note", `Quote given by the model, not found on the page: “${str(f.rejected_quote)}”`));
    }
    if (str(f.note)) li.append(el("p", "part-note", str(f.note)));
    parts.append(li);
  }
  for (const x of arr(ev.framing)) {
    if (!str(x)) continue;
    const li = el("li");
    const ph = el("div", "part-head");
    ph.append(el("span", "tag", "framing, not checked"));
    ph.append(el("span", "part-text", str(x)));
    li.append(ph);
    parts.append(li);
  }
  if (parts.childElementCount) card.append(parts);

  const extra = reasonExtra(ev);
  if (extra) card.append(el("p", "reason", extra));
  if (str(ev.detail)) card.append(el("p", "detail", `Details: ${str(ev.detail)}`));

  if (multi) {
    const list = el("ul", "sources");
    for (const s of sources) {
      const li = el("li");
      const href = safeUrl(str(s.url));
      if (href) {
        const a = el("a", "source", href);
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        li.append(a);
      } else {
        li.append(el("span", "source-plain", str(s.url)));
      }
      const outcome = str(s.label) === "SOURCE UNREACHABLE" ? str(s.reason) || "Could not be read." : str(s.label);
      li.append(el("span", "outcome", ` \u2014 ${outcome}`));
      if (str(s.note)) li.append(el("span", "outcome", ` (${str(s.note)})`));
      if (str(s.detail)) li.append(el("span", "detail", ` Details: ${str(s.detail)}`));
      list.append(li);
    }
    card.append(list);
    return card;
  }

  const href = safeUrl(str(ev.url));
  if (href) {
    const a = el("a", "source", href);
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    card.append(a);
  } else if (str(ev.url)) {
    card.append(el("span", "source-plain", str(ev.url)));
  }
  return card;
}

function appendFailure(ev) {
  const claim = attachClaim(ev);
  const card = renderCard(ev);
  if (claim) {
    claim.card = card;
    const head = card.querySelector(".card-head");
    if (claim.unit) {
      const show = el("button", "cardlink", "Show in document");
      show.type = "button";
      show.addEventListener("click", (e) => {
        e.stopPropagation();
        selectClaim(claim.no, true);
      });
      head.append(show);
      card.addEventListener("click", (e) => {
        if (e.target.closest("a, button, summary")) return;
        selectClaim(claim.no, true);
      });
    } else {
      head.append(el("span", "cardlink is-off", "Not located"));
      addTray(claim);
    }
  }
  $("cards").append(card);
  rebuildPager();
}

function addTray(claim) {
  const box = $("tray");
  box.hidden = false;
  const row = el("div", "trow");
  row.append(el("b", "", `Claim ${claim.no}`));
  row.append(document.createTextNode(" · "));
  row.append(el("span", "tlabel", claim.label));
  row.append(document.createTextNode(" — "));
  row.append(document.createTextNode(claim.text.length > 170 ? `${claim.text.slice(0, 167)}…` : claim.text));
  row.append(el("span", "twhy", "No distinctive match in the report"));
  box.append(row);
  const count = box.querySelectorAll(".trow").length;
  let key = box.querySelector(".tray-k");
  if (!key) { key = el("p", "tray-k"); box.prepend(key); }
  key.textContent = `${count} claim${count === 1 ? "" : "s"} not located in the report`;
}

/* ---------------- sourced group + filters ---------------- */

function ensureMatched() {
  if ($("mlist")) return;
  const box = $("matched");
  const card = el("section", "mcard");
  const head = el("button", "mhead");
  head.type = "button";
  head.id = "mhead";
  head.setAttribute("aria-expanded", "false");
  head.append(el("span", "mcount", "0"));
  head.append(el("span", "mlabel", " sourced claims"));
  head.append(el("span", "mchev", "›"));
  const list = el("ul", "mlist");
  list.id = "mlist";
  list.hidden = true;
  head.addEventListener("click", () => setMatchedOpen(!state.matchedOpen));
  card.append(head, list);
  box.append(card);
  head.querySelector(".mcount").id = "mcount";
  head.querySelector(".mlabel").id = "mlabel";
}

function setMatchedOpen(open) {
  state.matchedOpen = open;
  const head = $("mhead");
  const list = $("mlist");
  if (!head || !list) return;
  head.setAttribute("aria-expanded", String(open));
  list.hidden = !open;
}

function appendSourced(ev) {
  const claim = attachClaim(ev);
  if (!claim) return;
  ensureMatched();
  const row = el("button", "mrow");
  row.type = "button";
  row.dataset.claim = String(claim.no);
  row.append(el("span", "mno", String(claim.no)));
  row.append(el("span", "mtext", str(ev.text)));
  if (!claim.unit) {
    row.append(el("span", "mnote", "not located"));
    addTray(claim);
  }
  row.addEventListener("click", () => selectClaim(claim.no, true));
  claim.row = row;
  $("mlist").append(row);
  state.matchedCount = (state.matchedCount || 0) + 1;
  const count = state.matchedCount;
  $("mcount").textContent = String(count);
  $("mlabel").textContent = ` sourced claim${count === 1 ? "" : "s"}`;
  $("matched").hidden = false;
  applyFilter(state.filter);
}

function orderedLabels(counts) {
  const labels = SUMMARY.map(([k]) => k).filter((k) => counts[k]);
  for (const k of Object.keys(counts)) if (!SUMMARY_WORDS.has(k)) labels.push(k);
  return labels;
}

function labelText(k, counts) {
  return `${counts[k]} ${SUMMARY_WORDS.get(k) || k.toLowerCase()}`;
}

function summaryLine(counts, checked, cited) {
  const bits = orderedLabels(counts).map((k) => labelText(k, counts));
  const head = cited > checked
    ? `Checked ${checked} of ${cited} claims`
    : `${checked} claim${checked === 1 ? "" : "s"} checked`;
  return bits.length ? `${head}: ${bits.join(", ")}` : head;
}

function renderCounts(counts) {
  const box = $("counts");
  box.replaceChildren();
  state.filter = null;
  const labels = orderedLabels(counts);
  box.hidden = !labels.length;
  for (const k of labels) {
    const btn = el("button", "cnt");
    btn.type = "button";
    btn.dataset.label = k;
    btn.setAttribute("aria-pressed", "false");
    btn.setAttribute("aria-label", labelText(k, counts));
    btn.title = labelText(k, counts);
    btn.append(el("span", `dot dot-${TONES[k] || "grey"}`));
    btn.append(el("span", "", SUMMARY_WORDS.get(k) || k.toLowerCase()));
    btn.append(el("b", "", String(counts[k])));
    btn.addEventListener("click", () => applyFilter(state.filter === k ? null : k));
    box.append(btn);
  }
}

function applyFilter(label) {
  state.filter = label;
  for (const btn of $("counts").children) {
    btn.setAttribute("aria-pressed", String(btn.dataset.label === label));
  }
  for (const card of $("cards").children) {
    if (!card.dataset.label) continue;
    card.hidden = label !== null && card.dataset.label !== label;
  }
  const matched = $("matched");
  const has = (state.matchedCount || 0) > 0;
  matched.hidden = !has || (label !== null && label !== "SOURCED");
  if (!matched.hidden) setMatchedOpen(label === "SOURCED" ? true : state.matchedOpen);
}

/* ---------------- download + misc ---------------- */

function offerDownload(run) {
  run.created ||= new Date().toISOString();
  state.lastRun = run;
  $("export").disabled = false;
}

function downloadRun() {
  const run = state.lastRun;
  if (!run) return;
  const blob = new Blob([JSON.stringify(run, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `touchstone-run-${run.created.replace(/[:.]/g, "-")}.json`;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function countSentences(text) {
  return text.split(/(?<=[.!?])\s+(?=["\u201C(]?[A-Z0-9])/).filter((x) => /[A-Za-z0-9]/.test(x)).length;
}

function showNoLinks(claims) {
  $("nolinks-msg").textContent = claims === 1
    ? "This report cites no sources, so its 1 claim can't be checked."
    : `This report cites no sources, so none of its ${claims} claims can be checked.`;
  $("nolinks").hidden = false;
  stoneNoLinks(claims);
}

async function copyPrompt() {
  const text = $("fix-prompt").textContent;
  try {
    await navigator.clipboard.writeText(text);
    $("copy-prompt").textContent = "Copied";
  } catch {
    const range = document.createRange();
    range.selectNodeContents($("fix-prompt"));
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    $("copy-prompt").textContent = "Press Ctrl+C";
  }
}

/* ---------------- verdict stone + run states ---------------- */

let waitTimer = null;

function stopWaiting() {
  if (waitTimer) clearInterval(waitTimer);
  waitTimer = null;
  $("stone").classList.remove("is-wait");
}

function setStone(assay, verdict, mode) {
  $("assay").textContent = assay;
  $("verdict").textContent = verdict;
  const stone = $("stone");
  stone.classList.toggle("is-empty", mode === "empty");
  stone.classList.toggle("is-error", mode === "error");
  stone.classList.toggle("is-wait", mode === "wait");
}

function stoneEmpty() {
  stopWaiting();
  setStone("NO ASSAY", "Paste a report on the left to check it.", "empty");
  $("counts").hidden = true;
  $("runrow").hidden = true;
  $("progress").hidden = true;
  $("rerun").hidden = true;
  $("cancel").hidden = true;
  $("empty").hidden = false;
}

function stoneReady() {
  stopWaiting();
  $("empty").hidden = true;
  setStone("READY", "Nothing checked yet. Run the assay when you're ready.", "");
  $("counts").replaceChildren();
  $("counts").hidden = true;
  const links = (state.report.match(/https?:\/\/[^\s)>\]]+/g) || []).length;
  $("scope").textContent = `${state.report.length.toLocaleString()} characters · ${links} source link${links === 1 ? "" : "s"}`;
  $("run").textContent = "Run assay";
  $("run").disabled = false;
  $("runrow").hidden = false;
  $("progress").hidden = true;
  $("rerun").hidden = true;
  $("cancel").hidden = true;
}

function stoneRunning(total) {
  stopWaiting();
  setStone("RUNNING", total ? `Fetching ${total} source${total === 1 ? "" : "s"}…` : "Fetching sources…", "");
  $("counts").hidden = true;
  $("runrow").hidden = true;
  $("rerun").hidden = true;
  $("progress").hidden = false;
  $("bar").style.width = "0%";
}

function stoneProgress(done, total) {
  stopWaiting();
  setStone("RUNNING", done < total ? `Checking claim ${Math.min(done + 1, total)} of ${total}…` : "Finishing…", "");
  $("bar").style.width = `${total ? Math.round((done / total) * 100) : 0}%`;
}

function stoneDone(counts, done, cited) {
  stopWaiting();
  setStone(done ? `ASSAY · ${done} CLAIM${done === 1 ? "" : "S"}` : "ASSAY", summaryLine(counts, done, cited), "");
  $("counts").hidden = false;
  $("runrow").hidden = true;
  $("progress").hidden = true;
  $("rerun").hidden = false;
  $("cancel").hidden = true;
}

function stoneStopped(message, counts, done, cited) {
  stopWaiting();
  setStone("STOPPED", message, "error");
  $("counts").hidden = !done;
  $("runrow").hidden = false;
  $("run").textContent = "Try again";
  $("run").disabled = false;
  $("progress").hidden = true;
  $("rerun").hidden = true;
  $("cancel").hidden = true;
}

function stoneError(message) {
  stopWaiting();
  setStone("ERROR", message, "error");
  $("counts").hidden = true;
  $("runrow").hidden = false;
  $("run").textContent = "Try again";
  $("run").disabled = false;
  $("progress").hidden = true;
  $("rerun").hidden = true;
  $("cancel").hidden = true;
}

function stoneNoLinks(claims) {
  stopWaiting();
  setStone("NO LINKS", claims === 1
    ? "This report cites no sources, so its one claim can't be checked."
    : `This report cites no sources, so none of its ${claims} claims can be checked.`, "error");
  $("counts").hidden = true;
  $("runrow").hidden = true;
  $("progress").hidden = true;
  $("rerun").hidden = true;
  $("cancel").hidden = true;
}

function showWaiting(seconds) {
  stopWaiting();
  setStone("RUNNING", "", "wait");
  let left = seconds;
  const tick = () => {
    $("verdict").textContent = left > 0 ? `Waiting for capacity… (${left}s)` : "Resuming…";
    left -= 1;
    if (left < 0) stopWaiting();
  };
  tick();
  waitTimer = setInterval(tick, 1000);
}

function setProvenance(text) {
  $("provenance").textContent = text;
  $("provenance").title = text;
}

function provenanceFor(run, elapsed) {
  const bits = [];
  const tokens = int(run.tokens);
  if (tokens !== null) bits.push(`${tokens.toLocaleString()} tokens`);
  const urls = new Set();
  for (const c of arr(run.claims)) {
    if (str(c.url)) urls.add(str(c.url));
    for (const s of arr(c.sources)) if (str(s.url)) urls.add(str(s.url));
  }
  if (urls.size) bits.push(`${urls.size} source${urls.size === 1 ? "" : "s"}`);
  if (elapsed) {
    bits.push(elapsed < 60
      ? `${Math.round(elapsed)} s`
      : `${Math.floor(elapsed / 60)}m ${String(Math.round(elapsed % 60)).padStart(2, "0")}s`);
  }
  return bits.join(" · ");
}

function setBusy(busy) {
  for (const id of ["run", "rerun", "example", "run-live", "import", "import2", "new", "file", "check"]) {
    const node = $(id);
    if (node) node.disabled = busy;
  }
}

function resetRunView() {
  stopWaiting();
  state.lastRun = null;
  $("export").disabled = true;
  $("cards").replaceChildren();
  $("matched").replaceChildren();
  $("matched").hidden = true;
  state.matchedCount = 0;
  state.matchedOpen = false;
  $("tray").replaceChildren();
  $("tray").hidden = true;
  $("counts").replaceChildren();
  $("counts").hidden = true;
  state.filter = null;
  state.total = 0;
  state.done = 0;
  state.cited = 0;
  state.counts = {};
  state.tokens = null;
  state.elapsed = 0;
  state.selected = null;
  state.pager = [];
  state.pagerIdx = 0;
  doc.claims = [];
  doc.byNo = new Map();
  doc.unplaced = [];
  for (const unit of doc.units) {
    if (unit.gbox) { unit.gbox.remove(); unit.gbox = null; }
    unit.claims = [];
    unit.el.classList.remove("is-sel");
  }
  for (const old of $("ovr").querySelectorAll(".ovr-mark")) old.remove();
  $("replay").hidden = true;
  $("nolinks").hidden = true;
  $("copy-prompt").textContent = "Copy";
  $("runrow").hidden = true;
  $("rerun").hidden = true;
  $("cancel").hidden = true;
  $("progress").hidden = true;
  for (const id of ["uncited", "skipped"]) {
    const box = $(id);
    box.hidden = true;
    box.open = false;
    box.querySelector("ul").replaceChildren();
  }
  skippedWhy.clear();
  paintPager();
}

// Cited claims over a per-audit cap are listed (collapsed) so nobody reads the
// results as an audit of the whole report.
const skippedWhy = new Set();

function addSkipped(ev, reason) {
  const box = $("skipped");
  box.hidden = false;
  const li = el("li", "", `${int(ev.claim) !== null ? `Claim ${ev.claim}: ` : ""}${str(ev.text)}`);
  if (str(ev.url)) li.append(el("span", "source-plain", ` ${str(ev.url)}`));
  box.querySelector("ul").append(li);
  if (reason) skippedWhy.add(reason.replace(/\.$/, "").replace(/^L/, "l"));
  const n = box.querySelector("ul").childElementCount;
  const why = [...skippedWhy].join("; ");
  box.querySelector("summary").textContent =
    `Not checked${why ? ` (${why})` : ""}: ${n} claim${n === 1 ? "" : "s"}`;
}

function addUncited(text) {
  const box = $("uncited");
  box.hidden = false;
  box.querySelector("ul").append(el("li", "", text));
  const n = box.querySelector("ul").childElementCount;
  box.querySelector("summary").textContent =
    `No source given (${n} passage${n === 1 ? "" : "s"}): the report cites nothing for these, so they were not checked`;
}

/* ---------------- one results view, fed by live stream or replay ---------------- */

function selectFirstProblem() {
  if (state.selected !== null) return;
  const bad = doc.claims.find((c) => c.kind === "bad") || doc.claims.find((c) => c.kind === "unsup");
  if (bad) selectClaim(bad.no, false);
}

function resultsView(report) {
  let total = 0, cited = 0, limit = null, done = 0, finished = false, noLinks = false, sentences = 0, stopped = "";
  const counts = {};
  const run = { format: "touchstone-run", version: 1, created: "", report, cited: 0, checked: 0,
                tokens: null, stopped: null, claims: [], not_checked: [], uncited: [] };

  const handle = (ev) => {
    if (!ev || typeof ev !== "object") throw new Error("bad event");
    if (ev.type === "heartbeat") return;   // keep-alive for proxies while a claim is slow

    if (ev.type === "start") {
      total = int(ev.checked) ?? 0;
      cited = int(ev.cited) ?? total;
      run.cited = cited;
      run.checked = total;
      limit = int(ev.limit);
      state.total = total;
      state.cited = cited;
      if (cited === 0 && !int(ev.site_only)) { noLinks = true; stoneRunning(0); return; }
      stoneRunning(total);
      setProvenance(`Fetching ${total} source${total === 1 ? "" : "s"}…`);
      announce(`Checking ${total} cited claim${total === 1 ? "" : "s"}.`);
      return;
    }

    if (ev.type === "claim") {
      if (ev.claim === null && str(ev.site)) {
        // Cited only by a ChatGPT chip whose page link didn't survive the copy:
        // a card that says how to fix it, not one of the uncited passages.
        const { type, index, ...claim } = ev;
        run.claims.push(claim);
        appendFailure(ev);
        return;
      }
      if (ev.claim === null) {
        if (noLinks) sentences += countSentences(str(ev.text));
        else addUncited(str(ev.text));
        run.uncited.push(str(ev.text));
        return;
      }
      const { type, index, ...claim } = ev;
      run.claims.push(claim);
      done += 1;
      state.done = done;
      const label = str(ev.label) || "UNKNOWN";
      counts[label] = (counts[label] || 0) + 1;
      state.counts = counts;
      if (label === "SOURCED") appendSourced(ev);
      else appendFailure(ev);
      stoneProgress(done, total);
      setProvenance(`${done} of ${total} checked`);
      return;
    }

    if (ev.type === "wait") {
      // Free tiers pause between claims; say so for as long as it lasts.
      showWaiting(int(ev.seconds) ?? 10);
      return;
    }

    if (ev.type === "skipped") {
      const reason = str(ev.reason) || (limit ? `Limit of ${limit} claims per audit.` : "");
      addSkipped(ev, reason);
      run.not_checked.push({ claim: int(ev.claim), text: str(ev.text), url: str(ev.url),
                             label: "NOT CHECKED", reason });
      return;
    }

    if (ev.type === "quota") {
      stopped = str(ev.message) || "Touchstone's free daily capacity is used up, try again tomorrow.";
      run.stopped = stopped;
      return;
    }

    if (ev.type === "done") {
      finished = true;
      run.tokens = int(ev.tokens);
      state.tokens = run.tokens;
      state.elapsed = state.startedAt ? (Date.now() - state.startedAt) / 1000 : 0;
      if (noLinks) {
        showNoLinks(sentences);
        setProvenance("No sources read.");
        return;
      }
      if (done) offerDownload(run);
      if (stopped) {
        if (done) renderCounts(counts);
        stoneStopped(stopped, counts, done, cited);
      } else if (done) {
        stoneDone(counts, done, cited);
        renderCounts(counts);
        announce(`Done. ${summaryLine(counts, done, cited)}.`);
      } else {
        stoneError("No claim could be checked.");
      }
      setProvenance(provenanceFor(run, state.elapsed) || "Nothing was checked.");
      selectFirstProblem();
      return;
    }

    if (ev.type === "error") {
      stoneError(str(ev.error) || "The audit failed.");
    }
  };

  // A line that isn't a valid event: one grey card, the rest still render.
  const feed = (ev) => {
    try { handle(ev); } catch {
      const card = el("article", "card");
      card.append(el("p", "reason", "One result could not be read and was skipped."));
      $("cards").append(card);
    }
  };

  // The stream ended without "done".
  const endedEarly = () => {
    if (finished || $("stone").classList.contains("is-error")) return;
    stoneError(`The connection ended early. Claim ${done}/${total} done.`);
    if (done) {
      renderCounts(counts);
      setProvenance(provenanceFor(run, state.startedAt ? (Date.now() - state.startedAt) / 1000 : 0));
      run.stopped = "The connection ended early.";
      offerDownload(run);
    }
  };

  return { feed, endedEarly, progress: () => ({ done, total }) };
}

// Another visitor's audit holds the server (one at a time, up to 300 s): retry
// every 15 s for up to 6 minutes. A busy answer comes before the per-hour count,
// so these retries never use up the visitor's audits.
const BUSY_RETRY_S = 15;
const BUSY_MAX_S = 360;
let cancelBusy = null;

const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

function waitWhileBusy(message, since) {
  return new Promise((resolve) => {
    let left = BUSY_RETRY_S, timer = null;
    const finish = (retry) => {
      clearInterval(timer);
      cancelBusy = null;
      $("cancel").hidden = true;
      stopWaiting();
      resolve(retry);
    };
    const tick = () => {
      const waited = mmss(Math.round((Date.now() - since) / 1000));
      setStone("RUNNING", left > 0
        ? `${message} Next try in ${left}s (waiting ${waited}).`
        : "Trying again…", "wait");
      if (left-- <= 0) finish(true);
    };
    cancelBusy = () => finish(false);
    $("cancel").hidden = false;
    tick();
    timer = setInterval(tick, 1000);
  });
}

/* ---------------- audit ---------------- */

async function runAudit() {
  if (state.running) return;
  const report = state.report;
  if (!report.trim()) { showFront(); frontError("Paste a report first."); return; }
  if (report.length > MAX_CHARS) {
    stoneError(`Reports are limited to ${MAX_CHARS.toLocaleString()} characters.`);
    return;
  }

  resetRunView();
  state.running = true;
  state.replay = false;
  state.startedAt = Date.now();
  $("empty").hidden = true;
  $("replay").hidden = true;
  $("nolinks").hidden = true;
  setBusy(true);
  stoneRunning(0);
  setProvenance("Fetching sources…");
  const view = resultsView(report);

  try {
    const since = Date.now();
    let resp;
    for (;;) {
      resp = await withWakeNotice(() => fetch("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ report }),
      }));
      if (isWakePage(resp, "application/x-ndjson")) { stoneError(WAKE_RETRY); return; }
      if (resp.ok && resp.body) break;
      let body = null;
      try { body = await resp.json(); } catch { /* not JSON */ }
      const msg = body && typeof body === "object" ? str(body.error) : "";
      if (resp.status === 503 && body && body.busy === true) {
        if (Date.now() - since >= BUSY_MAX_S * 1000) {
          stoneError("Still busy — please try again later.");
          return;
        }
        if (!(await waitWhileBusy(msg || "Another audit is running.", since))) {
          stoneReady();
          announce("Cancelled.");
          return;
        }
        continue;
      }
      stoneError(msg || `The server refused the audit (HTTP ${resp.status}).`);
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done: eof } = await reader.read();
      buf += decoder.decode(value || new Uint8Array(), { stream: !eof });
      const lines = buf.split("\n");
      buf = eof ? "" : lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        let ev;
        try { ev = JSON.parse(line); } catch { ev = null; }
        view.feed(ev);
      }
      if (eof) break;
    }
    view.endedEarly();
  } catch {
    stoneError("Could not reach the server.");
  } finally {
    stopWaiting();
    if (cancelBusy) cancelBusy();
    state.running = false;
    setBusy(false);
    if ($("stone").classList.contains("is-wait")) stoneReady();
  }
}

// A sleeping or cold-starting host can take up to a minute to answer the first request.
const WAKE_AFTER_MS = 5000;
const WAKE_RETRY = "The server is waking up after a quiet spell. Try again in a minute.";

async function withWakeNotice(request) {
  const timer = setTimeout(() => {
    if (state.running) {
      announce("Waking up the server: the first request after a quiet spell can take up to a minute.");
    }
  }, WAKE_AFTER_MS);
  try { return await request(); } finally { clearTimeout(timer); }
}

// While waking, the host may answer with its own HTML loading page instead of our
// data: never parse that as results or load it into the report.
function isWakePage(resp, expected) {
  const type = (resp.headers.get("content-type") || "").toLowerCase();
  return resp.ok && !type.startsWith(expected);
}

/* ---------------- example, loading, boot ---------------- */

function validRun(run, report) {
  return !!run && typeof run === "object" && run.format === "touchstone-run" && run.version === 1
    && typeof run.report === "string" && run.report.trim() === report.trim()
    && Array.isArray(run.claims) && run.claims.length > 0
    && typeof run.created === "string" && !Number.isNaN(Date.parse(run.created));
}

// The saved run as the events a live audit would have streamed.
function runEvents(run) {
  const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : null);
  return [
    { type: "start", cited: run.cited, checked: run.checked, limit: null,
      site_only: run.claims.filter((c) => obj(c) && str(c.site)).length },
    ...arr(run.uncited).map((text) => ({ type: "claim", claim: null, text })),
    ...run.claims.map((c) => (obj(c) && (c.claim !== null || str(c.site)) ? { ...c, type: "claim" } : null)),
    ...arr(run.not_checked).map((c) => (obj(c) ? { ...c, type: "skipped" } : null)),
    ...(str(run.stopped) ? [{ type: "quota", message: run.stopped }] : []),
    { type: "done", tokens: run.tokens },
  ];
}

function replay(run) {
  resetRunView();
  state.replay = true;
  state.startedAt = 0;
  const view = resultsView(run.report);
  for (const ev of runEvents(run)) view.feed(ev);
  state.lastRun = run;   // the saved file exactly as it is
  $("export").disabled = false;
  const date = new Date(run.created).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  $("replay-msg").textContent = `Saved example run from ${date}. This is a real Perplexity answer; `
    + "we changed one figure (Samsung 18% → 19%) to show a catch.";
  $("replay").hidden = false;
  setProvenance(`saved run · ${provenanceFor(run, 0)}`);
  $("docpane").scrollTop = 0;
  requestAnimationFrame(layout);
}

const EXAMPLE_LOADED = "Example loaded. Run the assay to check it.";

async function loadExample() {
  if (state.running) return;
  $("example").disabled = true;
  let text;
  try {
    const resp = await withWakeNotice(() => fetch("/api/example"));
    if (isWakePage(resp, "text/plain")) { frontError(WAKE_RETRY); return; }
    if (!resp.ok) throw new Error();
    text = await resp.text();
  } catch {
    frontError("Could not load the example.");
    return;
  } finally {
    $("example").disabled = false;
  }
  if (!loadReport(text, "Example — Africa smartphone market")) return;
  let run = null;
  try {
    const resp = await fetch("/api/example-run");
    if (resp.ok && !isWakePage(resp, "application/json")) run = await resp.json();
  } catch { /* fall back to the text alone */ }
  if (validRun(run, text)) replay(run);
  else { stoneReady(); announce(EXAMPLE_LOADED); }
}

function reportName(text) {
  const m = /^#\s+(.+)$/m.exec(text);
  return m ? plain(m[1]).slice(0, 90) : "Pasted report";
}

function frontError(message) {
  $("fronterr").textContent = message || "";
}

function updateCount() {
  const n = $("report").value.length;
  $("count").textContent = `${n.toLocaleString()} / ${MAX_CHARS.toLocaleString()}`;
  $("count").classList.toggle("over", n > MAX_CHARS);
}

function loadReport(text, name) {
  const clean = String(text || "").replace(/^\uFEFF/, "");
  if (!clean.trim()) {
    frontError("Paste a report first.");
    return false;
  }
  if (clean.length > MAX_CHARS) {
    const msg = `Reports are limited to ${MAX_CHARS.toLocaleString()} characters.`;
    frontError(msg);
    if ($("front").hidden) setProvenance(msg);
    return false;
  }

  resetRunView();
  state.report = clean;
  state.name = name || reportName(clean);
  state.replay = false;
  state.running = false;
  state.startedAt = 0;
  state.elapsed = 0;
  state.selected = null;
  state.pager = [];
  state.pagerIdx = 0;

  $("report").value = clean;
  updateCount();
  frontError("");

  const article = $("paper");
  article.replaceChildren();
  doc.units = renderReport(article, clean);
  for (const unit of doc.units) {
    unit.words = wordsOf(unit.text);
    unit.nums = numbersOf(unit.text);
  }

  $("front").hidden = true;
  article.hidden = false;
  $("docname").textContent = state.name;
  $("docname").title = state.name;
  $("docname").hidden = false;
  $("new").hidden = false;
  $("docwrap").classList.add("has-doc");
  $("docpane").scrollTop = 0;

  renderRuler();
  stoneReady();
  setProvenance("Zero tokens until you run.");
  placeStone();
  layout();
  requestAnimationFrame(layout);
  setTimeout(layout, 80);
  announce(`${state.name} open. ${(clean.match(/https?:\/\/[^\s)>\]]+/g) || []).length} source links.`);
  return true;
}

function showFront(focus) {
  state.report = "";
  state.name = "";
  state.running = false;
  state.replay = false;
  state.selected = null;
  state.pager = [];
  state.pagerIdx = 0;
  resetRunView();
  doc.units = [];
  doc.claims = [];
  doc.byNo = new Map();
  doc.unplaced = [];

  $("paper").replaceChildren();
  $("paper").hidden = true;
  $("front").hidden = false;
  $("docwrap").classList.remove("has-doc");
  $("docname").hidden = true;
  $("new").hidden = true;
  $("ovr").hidden = true;
  for (const old of $("ovr").querySelectorAll(".ovr-mark")) old.remove();
  $("totop").hidden = true;
  $("report").value = "";
  updateCount();
  frontError("");
  stoneEmpty();
  setProvenance("Zero tokens until you run.");
  $("docpane").scrollTop = 0;
  placeStone();
  layout();
  if (focus) $("report").focus();
}

function openFromFront() {
  const text = $("report").value;
  if (!text.trim()) {
    frontError("Paste a report first.");
    $("report").focus();
    return;
  }
  loadReport(text, reportName(text));
}

async function importFile(file) {
  if (!file || state.running) return;
  if (!/\.(md|markdown|txt)$/i.test(file.name) && !/^text\//.test(file.type)) {
    frontError("Choose a .md or .txt report.");
    return;
  }
  let text = "";
  try {
    text = await file.text();
  } catch {
    frontError("Could not read that file.");
    return;
  }
  loadReport(text, file.name);
}

const narrow = window.matchMedia("(max-width: 699px)");

function placeStone() {
  const stone = $("stone");
  const rail = $("rail");
  const docpane = $("docpane");
  const grip = $("grip");
  if (narrow.matches) {
    if (stone.parentElement !== docpane) docpane.insertBefore(stone, docpane.firstChild);
    stone.classList.add("in-doc");
  } else if (stone.parentElement !== rail) {
    rail.insertBefore(stone, grip.nextSibling);
    stone.classList.remove("in-doc");
  }
  layout();
}

function setMatchedVisible(on) {
  state.hideOk = !on;
  $("docwrap").classList.toggle("hide-ok", !on);
  $("showmatched").setAttribute("aria-pressed", String(on));
}

function stepCard(dir) {
  const cards = [...$("cards").children].filter((card) => !card.hidden);
  if (!cards.length) return;
  const at = cards.findIndex((card) => card.classList.contains("is-sel"));
  let next = at < 0 ? 0 : at + dir;
  next = Math.max(0, Math.min(cards.length - 1, next));
  const no = int(cards[next].dataset.claim);
  if (no !== null) selectClaim(no, true);
  else cards[next].scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function bindEvents() {
  $("theme").addEventListener("click", toggleTheme);
  $("import").addEventListener("click", () => { if (!state.running) $("file").click(); });
  $("import2").addEventListener("click", () => { if (!state.running) $("file").click(); });
  $("file").addEventListener("change", (e) => {
    const file = e.target.files && e.target.files[0];
    e.target.value = "";
    if (file) importFile(file);
  });
  $("new").addEventListener("click", () => { if (!state.running) showFront(true); });
  $("export").addEventListener("click", downloadRun);
  $("help").addEventListener("click", () => $("shortcuts").showModal());
  $("check").addEventListener("click", openFromFront);
  $("example").addEventListener("click", loadExample);
  $("run").addEventListener("click", runAudit);
  $("rerun").addEventListener("click", runAudit);
  $("run-live").addEventListener("click", runAudit);
  $("cancel").addEventListener("click", () => { if (cancelBusy) cancelBusy(); });
  $("copy-prompt").addEventListener("click", copyPrompt);
  $("prev").addEventListener("click", () => stepProblem(-1));
  $("next").addEventListener("click", () => stepProblem(1));
  $("totop").addEventListener("click", () => $("docpane").scrollTo({ top: 0, behavior: "smooth" }));
  $("showmatched").addEventListener("click", () =>
    setMatchedVisible($("showmatched").getAttribute("aria-pressed") !== "true"));
  $("report").addEventListener("input", () => {
    updateCount();
    if ($("fronterr").textContent) frontError("");
  });
  $("shortcuts").addEventListener("click", (e) => {
    if (e.target === $("shortcuts")) $("shortcuts").close();
  });

  const ovr = $("ovr");
  ovr.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest(".ovr-mark") || !state.report) return;
    rulerDrag = true;
    try { ovr.setPointerCapture(e.pointerId); } catch { /* no capture */ }
    scrollFromRuler(e.clientY);
    e.preventDefault();
  });
  ovr.addEventListener("pointermove", (e) => { if (rulerDrag) scrollFromRuler(e.clientY); });
  ovr.addEventListener("pointerup", (e) => {
    rulerDrag = false;
    try { ovr.releasePointerCapture(e.pointerId); } catch { /* already released */ }
  });
  ovr.addEventListener("pointercancel", () => { rulerDrag = false; });

  let pending = false;
  $("docpane").addEventListener("scroll", () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; layout(); });
  });
  window.addEventListener("resize", () => { placeStone(); layout(); });
  if (narrow.addEventListener) narrow.addEventListener("change", placeStone);

  document.addEventListener("keydown", (e) => {
    const typing = e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement ||
      (e.target instanceof HTMLElement && e.target.isContentEditable);
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") {
      e.preventDefault();
      if (!state.running) $("file").click();
      return;
    }
    if (typing) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !state.running) {
        e.preventDefault();
        if (state.report) runAudit();
        else openFromFront();
      }
      return;
    }
    if ($("shortcuts").open) return;
    if (e.key === "?") { e.preventDefault(); $("shortcuts").showModal(); return; }
    if (e.key === "[") { e.preventDefault(); stepProblem(-1); return; }
    if (e.key === "]") { e.preventDefault(); stepProblem(1); return; }
    if (e.key.toLowerCase() === "j") { e.preventDefault(); stepCard(1); return; }
    if (e.key.toLowerCase() === "k") { e.preventDefault(); stepCard(-1); return; }
    if (e.key.toLowerCase() === "g") { e.preventDefault(); $("docpane").scrollTo({ top: 0, behavior: "smooth" }); }
  });

  // Drag a report anywhere onto the bench.
  let drags = 0;
  const hasFiles = (e) => Array.from((e.dataTransfer && e.dataTransfer.types) || []).includes("Files");
  window.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    drags += 1;
    $("drop").hidden = false;
  });
  window.addEventListener("dragover", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  });
  window.addEventListener("dragleave", () => {
    drags = Math.max(0, drags - 1);
    if (!drags) $("drop").hidden = true;
  });
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    drags = 0;
    $("drop").hidden = true;
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) importFile(file);
  });
}

function init() {
  initTheme();
  bindEvents();
  updateCount();
  showFront(false);
  placeStone();
  layout();
}

init();
