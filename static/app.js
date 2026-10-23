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
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const motion = () => (reduceMotion.matches ? "auto" : "smooth");
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
  btn.dataset.mode = theme;
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

// ---------------- text size ----------------
// Two independent scopes. Reading changes the report and its claims;
// Interface changes the labels and controls around it. Both persist.
const READ_KEY = "touchstone.readsize";
const UI_KEY = "touchstone.uisize";
const SIZE_STEPS = new Set(["lg", "xl"]);
const SIZE_WORDS = { default: "Normal", lg: "Large", xl: "Largest" };
let textRead = "default";
let textUi = "default";

function storedSize(key) {
  let value = "";
  try { value = localStorage.getItem(key) || ""; } catch { /* private mode */ }
  return SIZE_STEPS.has(value) ? value : "default";
}

function syncTextSizeButtons() {
  for (const btn of document.querySelectorAll("#textmenu button[data-scope]")) {
    const active = (btn.dataset.scope === "read" ? textRead : textUi) === btn.dataset.size;
    btn.setAttribute("aria-pressed", String(active));
  }
}

function applyTextSize(read, ui) {
  textRead = read;
  textUi = ui;
  const root = document.documentElement;
  if (SIZE_STEPS.has(read)) root.dataset.read = read;
  else delete root.dataset.read;
  if (SIZE_STEPS.has(ui)) root.dataset.ui = ui;
  else delete root.dataset.ui;
  syncTextSizeButtons();
}

function initTextSize() {
  applyTextSize(storedSize(READ_KEY), storedSize(UI_KEY));
}

function setTextMenu(open, returnFocus) {
  const menu = $("textmenu");
  const btn = $("textsize");
  if (!menu || !btn) return;
  if (open) {
    menu.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    const active = menu.querySelector('button[aria-pressed="true"]') || menu.querySelector("button");
    if (active) active.focus();
    return;
  }
  const hadFocus = menu.contains(document.activeElement);
  menu.hidden = true;
  btn.setAttribute("aria-expanded", "false");
  if (returnFocus && hadFocus) btn.focus();
}

function toggleTextMenu() {
  const menu = $("textmenu");
  if (menu) setTextMenu(menu.hidden, true);
}

function setTextSize(scope, size) {
  if (scope !== "read" && scope !== "ui") return;
  if (size !== "default" && !SIZE_STEPS.has(size)) return;
  if (inline) {
    closeInline();
    if (inline) return;   // an empty block stays open; do not change type under it
  }
  applyTextSize(scope === "read" ? size : textRead, scope === "ui" ? size : textUi);
  try { localStorage.setItem(scope === "read" ? READ_KEY : UI_KEY, size); } catch { /* private mode */ }
  mmKey = "";
  announce(`${scope === "read" ? "Reading" : "Interface"} text: ${SIZE_WORDS[size]}.`);
  requestAnimationFrame(() => { layout(); });
}

// ---------------- view mode ----------------
const MODE_KEY = "touchstone.mode";
const MODES = new Set(["edit", "preview", "inline"]);
const MODE_WORDS = { edit: "Edit", preview: "Preview", inline: "Inline" };
let sourceDirty = false;

function storedMode() {
  let value = "";
  try { value = localStorage.getItem(MODE_KEY) || ""; } catch { /* private mode */ }
  return MODES.has(value) ? value : "inline";
}

// ---------------- state ----------------
const state = {
  report: "", name: "", running: false, startedAt: 0, elapsed: 0, tokens: null,
  mode: storedMode(),
  lastRun: null, lastRunExample: false, retryPlayback: false, replay: false, selected: null, pager: [], pagerIdx: 0,
  filter: null, matchedOpen: false, hideOk: true, abort: null, replaying: false,
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

let katexLoad = null;

/* KaTeX is self-hosted and loaded only when the report actually contains a
   formula. Its generated DOM is the one exception to the textContent rule:
   ordinary report text still never reaches innerHTML. */
function ensureKatex() {
  if (window.katex) return Promise.resolve(window.katex);
  if (katexLoad) return katexLoad;
  katexLoad = new Promise((resolve) => {
    if (!document.querySelector("link[data-katex]")) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/static/vendor/katex/katex.min.css";
      link.dataset.katex = "";
      document.head.append(link);
    }
    let script = document.querySelector("script[data-katex]");
    if (!script) {
      script = document.createElement("script");
      script.src = "/static/vendor/katex/katex.min.js";
      script.async = true;
      script.dataset.katex = "";
      document.head.append(script);
    }
    const done = () => resolve(window.katex || null);
    if (window.katex) done();
    else {
      script.addEventListener("load", done, { once: true });
      script.addEventListener("error", () => resolve(null), { once: true });
    }
  });
  return katexLoad;
}

function mathNode(tex, display) {
  const node = el(display ? "div" : "span", display ? "math-block" : "math-inline");
  node.dataset.tex = tex;
  node.textContent = tex;
  node.setAttribute("aria-label", `Formula: ${tex}`);
  return node;
}

function hydrateMath(root) {
  const nodes = [...root.querySelectorAll(".math-inline, .math-block")];
  if (!nodes.length) return;
  ensureKatex().then((katex) => {
    if (!katex) return;
    for (const node of nodes) {
      if (!node.isConnected || node.dataset.rendered === "1") continue;
      try {
        katex.render(node.dataset.tex || "", node, {
          displayMode: node.classList.contains("math-block"),
          throwOnError: false,
          trust: false,
          strict: "ignore",
        });
        node.dataset.rendered = "1";
      } catch { /* keep the TeX text as a readable fallback */ }
    }
    layout();
  });
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
    if (ch === "$") {
      const close = text.indexOf("$", i + 1);
      if (close > i + 1) {
        const body = text.slice(i + 1, close);
        if (!/\n/.test(body) && body.trim() === body && !/^\d[\d,.]*$/.test(body)) {
          flush();
          frag.append(mathNode(body, false));
          i = close + 1;
          continue;
        }
      }
    } else if (ch === "[") {
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
const isDisplayMathStart = (l) => /^\s*\$\$/.test(l);
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
  // Remember each top-level block's exact source range so the document can be
  // edited in place. Blocks, not lines: a click on a list or table edits the
  // whole construct, the way Obsidian keeps a rendered block as one widget.
  const markBlock = (node, from, to) => {
    if (!node) return;
    node.__src = lines.slice(from, to).join("\n");
    node.__from = from;
    node.__to = to;
    node.classList.add("blk");
  };
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

    if (isDisplayMathStart(line)) {
      const start = i;
      const first = line.replace(/^\s*\$\$/, "");
      let tex = "";
      if (first.trim().endsWith("$$")) {
        tex = first.trim().slice(0, -2).trim();
        i += 1;
      } else {
        const body = [];
        if (first.trim()) body.push(first.trim());
        i += 1;
        while (i < lines.length && !/^\s*\$\$\s*$/.test(lines[i])) {
          body.push(lines[i]);
          i += 1;
        }
        if (i < lines.length) i += 1;
        tex = body.join("\n").trim();
      }
      if (tex) {
        const node = mathNode(tex, true);
        article.append(node);
        markBlock(node, start, i);
        continue;
      }
    }

    if (isFenceLine(line)) {
      const start = i;
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
      markBlock(pre, start, i);
      continue;
    }

    const h = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (h) {
      const start = i;
      const heading = el(`h${h[1].length}`);
      heading.append(renderInline(h[2]));
      article.append(heading);
      i += 1;
      markBlock(heading, start, i);
      continue;
    }

    if (isRuleLine(line)) { article.append(el("hr")); i += 1; continue; }

    if (isTableStart(lines, i)) {
      const start = i;
      i = renderTable(article, lines, i, addUnit);
      markBlock(article.lastElementChild, start, i);
      continue;
    }

    if (isQuoteLine(line)) {
      const start = i;
      const body = [];
      while (i < lines.length && isQuoteLine(lines[i])) {
        body.push(lines[i].replace(/^\s*>\s?/, ""));
        i += 1;
      }
      const q = el("blockquote");
      q.append(renderInline(body.join(" ")));
      article.append(q);
      markBlock(q, start, i);
      continue;
    }

    if (isListLine(line)) {
      const start = i;
      i = renderList(article, lines, i, addUnit);
      markBlock(article.lastElementChild, start, i);
      continue;
    }

    const start = i;
    const buf = [line.trim()];
    i += 1;
    while (i < lines.length && lines[i].trim() &&
      !isFenceLine(lines[i]) && !isHeadingLine(lines[i]) && !isRuleLine(lines[i]) &&
      !isDisplayMathStart(lines[i]) && !isQuoteLine(lines[i]) && !isListLine(lines[i]) && !isTableStart(lines, i)) {
      buf.push(lines[i].trim());
      i += 1;
    }
    const p = el("p");
    p.append(renderInline(buf.join(" ")));
    article.append(p);
    addUnit(p, "p", start);
    markBlock(p, start, i);
  }
  hydrateMath(article);
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
  // Only problems colour the minimap, the way editor diagnostics do; sourced
  // and neutral text stays skeleton grey. Worst claim wins per block.
  if (claim.kind === "bad" || claim.kind === "unsup") {
    const rank = { bad: 2, unsup: 1 };
    if ((rank[claim.kind] || 0) >= (rank[unit.el.dataset.kind] || 0)) {
      unit.el.dataset.kind = claim.kind;
    }
  }
}

function attachClaim(ev) {
  const no = int(ev.claim);
  if (no === null) return null;
  const label = str(ev.label).toUpperCase() || "UNKNOWN";
  const unit = matchUnit(str(ev.text));
  const claim = { no, label, text: str(ev.text), kind: signalOf(label), unit,
                  ev, offset: 0, card: null, row: null, mark: null };
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

/* ---------------- minimap ---------------- */

let mmKey = "";
let mmScale = 0;
let mmOffX = 0;
let mmPreviewW = 0;
let mmSkeletonH = 0;

/* A code-editor minimap: not the text, a skeleton of the page's real line
   boxes at one uniform scale, so the preview keeps the document's proportions.
   Lines in a contradicted or unsupported block take that problem's colour. */
function drawMinimap() {
  const mm = $("minimap");
  const body = $("mmbody");
  const paper = $("paper");
  if (!mm || !body || !paper) return;
  if (!state.report || state.mode === "edit") {
    mm.hidden = true;
    mmKey = "";
    return;
  }
  mm.hidden = false;
  const w = mm.clientWidth;
  const h = mm.clientHeight;
  if (!w || !h) return;
  const key = `${w}x${h}|${state.report.length}|${doc.claims.length}`;
  if (key === mmKey) return;
  mmKey = key;

  const pcs = getComputedStyle(paper);
  const padL = parseFloat(pcs.paddingLeft) || 0;
  const padR = parseFloat(pcs.paddingRight) || 0;
  const prect = paper.getBoundingClientRect();
  const docW = paper.clientWidth - padL - padR;
  const docH = paper.scrollHeight;
  if (docW <= 0 || docH <= 0) return;
  // One scale for both axes: the preview keeps the page's proportions, and a
  // page taller than the gutter shrinks to fit it instead of losing its tail.
  const s = Math.min(w / docW, h / docH);
  const offX = Math.max(0, (w - docW * s) / 2);

  const frag = document.createDocumentFragment();
  const walker = document.createTreeWalker(paper, NodeFilter.SHOW_TEXT);
  let node;
  let count = 0;
  while ((node = walker.nextNode()) && count < 900) {
    if (!node.nodeValue.trim()) continue;
    const host = node.parentElement && node.parentElement.closest("[data-kind]");
    const kind = host ? host.dataset.kind : "";
    const range = document.createRange();
    range.selectNodeContents(node);
    for (const r of range.getClientRects()) {
      if (r.width < 1 || r.height < 1) continue;
      const barH = Math.max(1, r.height * s * 0.8);
      const bar = document.createElement("i");
      bar.className = "mm-line" + (kind ? ` is-${kind}` : "");
      bar.style.left = `${(offX + (r.left - prect.left - padL) * s).toFixed(2)}px`;
      bar.style.top = `${((r.top - prect.top) * s + (r.height * s - barH) / 2).toFixed(2)}px`;
      bar.style.width = `${Math.max(1, r.width * s).toFixed(2)}px`;
      bar.style.height = `${barH.toFixed(2)}px`;
      frag.append(bar);
      count += 1;
    }
  }
  body.replaceChildren(frag);
  mmScale = s;
  mmOffX = offX;
  mmPreviewW = docW * s;
  mmSkeletonH = docH * s;
}

function layout() {
  const pane = $("docpane");
  const ovr = $("ovr");
  const win = $("ovrwin");
  const top = $("totop");
  const mm = $("minimap");
  const mmSlider = $("mmslider");
  if (!pane || !ovr) return;
  if (!state.report) {
    ovr.hidden = true;
    top.hidden = true;
    if (mm) mm.hidden = true;
    return;
  }
  ovr.hidden = false;
  const stone = $("stone");
  const strip = narrow.matches && stone.classList.contains("in-doc") ? stone.offsetHeight : 0;
  const bar = $("docbar");
  const barH = bar && !bar.hidden ? bar.offsetHeight : 0;
  if (bar) bar.style.top = strip ? `${strip}px` : "";
  // Anchor the rail to the sticky bar's resting edge, not its live position.
  // Measuring the bar as it sticks made the whole rail jump on the first scroll.
  const topOffset = strip + barH;
  ovr.style.top = topOffset ? `${topOffset}px` : "";
  if (mm) mm.style.top = topOffset ? `${topOffset}px` : "";
  const sh = pane.scrollHeight;
  const ch = pane.clientHeight;
  const h = ovr.clientHeight;
  const scrollable = sh > ch + 4 && h > 0;
  if (state.mode === "edit") {
    if (mm) mm.hidden = true;
  } else {
    drawMinimap();
  }
  // A scrollbar always shows a slider. When the document fits, the thumb fills
  // the track in an idle state rather than vanishing and leaving only ticks.
  win.style.display = "block";
  win.classList.toggle("is-idle", !scrollable);
  if (scrollable) {
    // Match a code editor's viewport slider: the thumb travels over the track
    // that remains after its own height is removed.
    const winH = Math.max(40, Math.round((ch / sh) * h));
    const trackH = Math.max(0, h - winH);
    const maxScroll = Math.max(1, sh - ch);
    const winTop = Math.round((pane.scrollTop / maxScroll) * trackH);
    win.style.height = `${winH}px`;
    win.style.top = `${Math.max(0, Math.min(trackH, winTop))}px`;
    if (mmSlider) {
      // The band is the viewport drawn at the minimap's own scale, so it keeps
      // the page's proportions instead of stretching to the gutter.
      const bandH = Math.max(14, Math.round(ch * mmScale));
      const visH = Math.min(h, mmSkeletonH || h);
      const bandTop = Math.min(Math.max(0, visH - bandH), Math.round(pane.scrollTop * mmScale));
      mmSlider.style.left = `${mmOffX}px`;
      mmSlider.style.width = `${mmPreviewW}px`;
      mmSlider.style.height = `${Math.min(bandH, visH)}px`;
      mmSlider.style.top = `${bandTop}px`;
    }
  } else {
    win.style.height = `${Math.max(40, h - 8)}px`;
    win.style.top = "4px";
  }
  if (mmSlider) mmSlider.hidden = !scrollable;
  for (const c of doc.claims) {
    if (!c.mark || !c.unit || state.mode === "edit") continue;
    const rect = c.unit.el.getBoundingClientRect();
    const paneRect = pane.getBoundingClientRect();
    const y = ((rect.top - paneRect.top + pane.scrollTop) / sh) * h + (c.offset || 0);
    c.mark.style.top = `${Math.max(0, Math.min(h - 8, Math.round(y)))}px`;
  }
  top.hidden = !scrollable;
  paintPager();
  positionInlineFill();
}

function renderRuler() {
  const ovr = $("ovr");
  for (const old of ovr.querySelectorAll(".ovr-mark")) old.remove();
  for (const c of doc.claims) c.mark = null;
  ovr.hidden = !state.report;
  if (!state.report) return;
  if (state.mode === "edit") return;
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
  // Results can survive a switch to Edit (for example, a saved example opened
  // in the last-used mode). Selecting a claim still needs the rendered page,
  // so bring Preview back without touching the checked source.
  if (scroll && claim.unit && $("paper").hidden && state.mode === "edit" && !setMode("preview")) return;
  state.selected = claim.no;
  for (const node of document.querySelectorAll(".paper .is-sel, .card.is-sel, .mrow.is-sel")) {
    node.classList.remove("is-sel");
  }
  if (claim.unit) claim.unit.el.classList.add("is-sel");
  if (claim.card) claim.card.classList.add("is-sel");
  if (claim.row) claim.row.classList.add("is-sel");
  if (scroll && claim.unit) {
    claim.unit.el.scrollIntoView({ block: "center", behavior: motion() });
    if (claim.card) claim.card.scrollIntoView({ block: "nearest", behavior: motion() });
    if (claim.row && !$("matched").hidden) {
      setMatchedOpen(true);
      claim.row.scrollIntoView({ block: "nearest", behavior: motion() });
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
let rulerGrab = 0;

function scrollFromRuler(y) {
  const pane = $("docpane");
  const ovr = $("ovr");
  const win = $("ovrwin");
  const rect = ovr.getBoundingClientRect();
  const max = pane.scrollHeight - pane.clientHeight;
  const winH = win.offsetHeight;
  const track = rect.height - winH;
  if (max <= 0 || track <= 0) return;
  const top = Math.max(0, Math.min(track, y - rect.top - rulerGrab));
  pane.scrollTop = (top / track) * max;
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

function correctedClaim(ev) {
  const claimText = str(ev.text);
  const claimFigs = figuresIn(claimText);
  const reps = [];
  for (const f of arr(ev.facts)) {
    if (!f || typeof f !== "object" || str(f.status) !== "contradicted") continue;
    const quote = str(f.quote);
    if (!quote) continue;
    const factFigs = figuresIn(str(f.fact));
    const mine = claimFigs.filter((c) =>
      factFigs.some((g) => g.unit === c.unit && g.value === c.value));
    const theirs = figuresIn(quote).filter((q) =>
      mine.some((c) => c.unit === q.unit) &&
      !claimFigs.some((c) => c.unit === q.unit && c.value === q.value) &&
      !factFigs.some((g) => g.unit === q.unit && g.value === q.value));
    if (mine.length !== 1 || theirs.length !== 1) continue;
    reps.push({ start: mine[0].start, end: mine[0].end,
                replacement: quote.slice(theirs[0].start, theirs[0].end) });
  }
  if (!reps.length) return null;
  const unique = [...new Map(reps.map((r) => [`${r.start}:${r.end}`, r])).values()]
    .sort((a, b) => b.start - a.start);
  let out = claimText;
  for (const r of unique) out = out.slice(0, r.start) + r.replacement + out.slice(r.end);
  return out === claimText ? null : out;
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch { /* fall through */ }
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  } catch { return false; }
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
  card.tabIndex = 0;
  card.setAttribute("role", "group");
  card.setAttribute("aria-label", `${label}${n !== null ? ` claim ${n}` : ""}. Press Enter to show in document.`);
  card.addEventListener("keydown", (e) => {
    if (e.target !== card) return;
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (n !== null) selectClaim(n, true);
    }
  });

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
    const fix = correctedClaim(ev);
    if (fix) {
      const copy = el("button", "cardlink copyfix", "Copy fix");
      copy.type = "button";
      copy.dataset.fix = fix;
      copy.title = "Copy this claim with the page's figure";
      copy.addEventListener("click", async (e) => {
        e.stopPropagation();
        const ok = await copyText(fix);
        copy.textContent = ok ? "Copied" : "Copy failed";
        if (ok) announce("Corrected claim copied.");
        setTimeout(() => { copy.textContent = "Copy fix"; }, 1600);
      });
      head.append(copy);
    }
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
  row.addEventListener("click", () => showEvidence(claim));
  row.title = "Read the evidence";
  row.setAttribute("aria-haspopup", "dialog");
  claim.row = row;
  $("mlist").append(row);
  state.matchedCount = (state.matchedCount || 0) + 1;
  const count = state.matchedCount;
  $("mcount").textContent = String(count);
  $("mlabel").textContent = ` sourced claim${count === 1 ? "" : "s"}`;
  $("matched").hidden = false;
  applyFilter(state.filter);
}

let evidenceNo = null;

function showEvidence(claim) {
  if (!claim) return;
  const ev = claim.ev && typeof claim.ev === "object" ? claim.ev : {};
  evidenceNo = claim.no;
  const state = $("ev-state");
  const kind = String(claim.label || "").toLowerCase();
  state.textContent = claim.label || "Evidence";
  state.dataset.kind = kind.includes("contradic") ? "bad"
    : kind.includes("unsupport") ? "unsup" : "ok";
  $("ev-title").textContent = `Claim ${claim.no}`;
  $("ev-claim").textContent = claim.text;

  const factBox = $("ev-facts");
  factBox.replaceChildren();
  const facts = arr(ev.facts).filter((f) => f && typeof f === "object")
    .sort((a, b) => {
      const ra = str(a.status) === "contradicted" ? 0 : 1;
      const rb = str(b.status) === "contradicted" ? 0 : 1;
      return ra - rb;
    });
  for (const f of facts) {
    const box = el("div", "ev-fact");
    const head = el("div", "ev-fact-head");
    const status = str(f.status);
    const tag = el("span", "tag", STATUS_TEXT[status] || "unclear");
    tag.dataset.status = status || "unknown";
    head.append(tag);
    head.append(el("span", "part-text", str(f.fact)));
    box.append(head);
    if (str(f.quote)) {
      const q = el("blockquote", "quote");
      q.append(document.createTextNode("“" + str(f.quote) + "”"));
      box.append(q);
    }
    if (str(f.evidence)) {
      box.append(el("p", "part-note", "Not in the passages checked, but this line on the page has its figures:"));
      box.append(el("blockquote", "quote", "“" + str(f.evidence) + "”"));
    }
    if (str(f.rejected_quote)) {
      box.append(el("p", "part-note",
        `Quote given by the model, not found on the page: “${str(f.rejected_quote)}”`));
    }
    if (str(f.note)) box.append(el("p", "part-note", str(f.note)));
    factBox.append(box);
  }
  if (!facts.length) {
    factBox.append(el("p", "ev-note", "No per-fact evidence was recorded for this claim."));
  }

  const links = $("ev-links");
  links.replaceChildren();
  const sources = arr(ev.sources).filter((s) => s && typeof s === "object");
  if (sources.length) {
    links.append(el("p", "ev-kicker", sources.length === 1 ? "Source" : "Sources"));
    for (const s of sources) {
      const line = el("div", "ev-source");
      const href = safeUrl(str(s.url));
      if (href) {
        const a = el("a", "", href);
        a.href = href;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        line.append(a);
      } else if (str(s.url)) {
        line.append(el("span", "", str(s.url)));
      }
      if (str(s.label)) line.append(el("span", "ev-outcome", ` — ${str(s.label)}`));
      links.append(line);
    }
  }
  $("ev-show").disabled = !claim.unit;
  const dlg = $("evidence");
  if (!dlg.open) dlg.showModal();
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
    // Partial is a half-filled dot in the key, so its count uses the same mark.
    const tone = k === "PARTIAL" ? "half" : (TONES[k] || "grey");
    btn.append(el("span", `dot dot-${tone}`));
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
  state.lastRunExample = false;
  $("export").disabled = false;
  if (!state.replaying) saveHistory(run, false);
}

const HISTORY_KEY = "touchstone.history.v1";

function historyEntries() {
  try {
    const list = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(list)
      ? list.filter((x) => x && typeof x === "object" && x.run && typeof x.run === "object"
          && str(x.created) && str(x.run.report)).slice(0, 3)
      : [];
  } catch { return []; }
}

function historyCounts(run) {
  const counts = {};
  for (const c of arr(run && run.claims)) {
    if (c && typeof c === "object" && str(c.label)) {
      counts[str(c.label)] = (counts[str(c.label)] || 0) + 1;
    }
  }
  return counts;
}

function saveHistory(run, example) {
  if (!run || typeof run !== "object" || !state.report) return;
  const created = str(run.created) || new Date().toISOString();
  const name = state.name || "Pasted report";
  const entry = { name, created, example: Boolean(example), run };
  let list = historyEntries().filter((x) => !(x.created === created && x.name === name));
  list.unshift(entry);
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, 3))); } catch { /* full or private */ }
  renderHistory();
}

function renderHistory() {
  const box = $("recent");
  const list = $("recentlist");
  if (!box || !list) return;
  const entries = historyEntries();
  box.hidden = !entries.length;
  list.replaceChildren();
  for (const entry of entries) {
    const run = entry.run;
    const counts = historyCounts(run);
    const checked = int(run.checked) ?? arr(run.claims).length;
    const cited = int(run.cited) ?? checked;
    const verdict = checked ? summaryLine(counts, checked, cited) : "Saved check";
    const d = new Date(str(entry.created));
    const dateText = Number.isNaN(d.getTime())
      ? "" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
    const li = el("li");
    const btn = el("button", "recentitem");
    btn.type = "button";
    btn.append(el("span", "rname", str(entry.name) || "Pasted report"));
    btn.append(el("span", "rmeta",
      [dateText, `${checked} claim${checked === 1 ? "" : "s"}`].filter(Boolean).join(" · ")));
    btn.append(el("span", "rverdict", verdict));
    btn.title = `${str(entry.name) || "Pasted report"} — ${verdict}`;
    btn.setAttribute("aria-label",
      [str(entry.name) || "Pasted report", dateText, verdict].filter(Boolean).join(". "));
    btn.addEventListener("click", () => {
      if (state.running) return;
      const saved = entry.run;
      if (!validRun(saved, str(saved.report))) {
        setProvenance("That saved check can no longer be read.");
        return;
      }
      if (loadReport(str(saved.report), str(entry.name))) {
        replay(saved, { example: Boolean(entry.example) });
      }
    });
    li.append(btn);
    list.append(li);
  }
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

function clearSkeletons() {
  const box = $("skeletons");
  if (!box) return;
  box.replaceChildren();
  box.hidden = true;
}

function showSkeletons(count) {
  clearSkeletons();
  const box = $("skeletons");
  if (!box) return;
  for (let i = 0; i < count; i += 1) {
    const s = el("div", "skel");
    for (let j = 0; j < 4; j += 1) s.append(el("i"));
    box.append(s);
  }
  box.hidden = false;
}

function dropSkeleton() {
  const box = $("skeletons");
  if (!box) return;
  const s = box.querySelector(".skel");
  if (s) s.remove();
  if (!box.childElementCount) box.hidden = true;
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
  clearSkeletons();
  state.retryPlayback = false;
  setStone("NO CHECK", "Paste a report on the left to check it.", "empty");
  $("counts").hidden = true;
  $("runrow").hidden = true;
  $("progress").hidden = true;
  $("rerun").hidden = true;
  $("cancel").hidden = true;
  $("empty").hidden = false;
  renderHistory();
}

function stoneReady() {
  stopWaiting();
  clearSkeletons();
  state.retryPlayback = false;
  $("empty").hidden = true;
  setStone("READY", "Nothing checked yet. Run the check when you're ready.", "");
  $("counts").replaceChildren();
  $("counts").hidden = true;
  const links = (state.report.match(/https?:\/\/[^\s)>\]]+/g) || []).length;
  $("scope").textContent = `${state.report.length.toLocaleString()} characters · ${links} source link${links === 1 ? "" : "s"}`;
  $("run").textContent = "Run check";
  $("run").disabled = false;
  $("runrow").hidden = false;
  $("progress").hidden = true;
  $("rerun").hidden = true;
  $("cancel").hidden = true;
}

function stoneRunning(total) {
  stopWaiting();
  setStone("RUNNING", total ? `Fetching ${total} source${total === 1 ? "" : "s"}…` : "Fetching sources…", "");
  showSkeletons(3);
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
  clearSkeletons();
  setStone(done ? `CHECKED · ${done} CLAIM${done === 1 ? "" : "S"}` : "CHECKED", summaryLine(counts, done, cited), "");
  state.retryPlayback = false;
  $("counts").hidden = false;
  $("runrow").hidden = true;
  $("progress").hidden = true;
  // In a replay the notice above already carries the explicit "Run it live"
  // path; a live re-run must never sit one click away from a zero-token view.
  $("rerun").hidden = state.replay;
  $("cancel").hidden = true;
}

function stoneStopped(message, counts, done, cited, playback = false) {
  stopWaiting();
  clearSkeletons();
  setStone("STOPPED", message, "error");
  state.retryPlayback = Boolean(playback);
  $("counts").hidden = !done;
  $("runrow").hidden = false;
  $("run").textContent = playback ? "Replay" : "Try again";
  $("run").disabled = false;
  $("progress").hidden = true;
  $("rerun").hidden = true;
  $("cancel").hidden = true;
}

function stoneError(message) {
  stopWaiting();
  clearSkeletons();
  state.retryPlayback = false;
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
  clearSkeletons();
  state.retryPlayback = false;
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

// A replay never re-bills the saved run's token count. Showing the original
// number in the footer makes a zero-token path look expensive.
function replayProvenance(run, example) {
  const copy = { ...run, tokens: 0 };
  return `${example ? "replayed example" : "replayed"} · ${provenanceFor(copy, 0)}`;
}

function setBusy(busy) {
  for (const id of ["run", "rerun", "example", "run-live", "playback", "import", "import2", "new", "file", "check", "edit"]) {
    const node = $(id);
    if (node) node.disabled = busy;
  }
  for (const node of document.querySelectorAll("#mode-switch button, #modemenu button, #modebtn, #md-tools button")) {
    node.disabled = busy;
  }
  syncToolState();
}

function resetRunView() {
  stopWaiting();
  state.lastRun = null;
  state.lastRunExample = false;
  state.retryPlayback = false;
  $("export").disabled = true;
  $("cards").replaceChildren();
  clearSkeletons();
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
      dropSkeleton();
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
      const reason = str(ev.reason) || (limit ? `Limit of ${limit} claims per check.` : "");
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
      stoneError(str(ev.error) || "The check failed.");
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
  if (state.mode === "edit" && !commitSource()) return;
  // A check is read against the rendered page; do not leave the reader in a
  // raw source view where the claim marks and cards cannot point anywhere.
  if (state.mode === "edit" && !setMode("preview")) return;
  const report = state.report;
  if (!report.trim()) { showFront(); frontError("Paste a report first."); return; }
  if (report.length > MAX_CHARS) {
    stoneError(`Reports are limited to ${MAX_CHARS.toLocaleString()} characters.`);
    return;
  }

  resetRunView();
  state.running = true;
  state.replay = false;
  state.retryPlayback = false;
  state.startedAt = Date.now();
  const controller = new AbortController();
  state.abort = controller;
  $("empty").hidden = true;
  $("replay").hidden = true;
  $("nolinks").hidden = true;
  $("cancel").hidden = false;
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
        signal: controller.signal,
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
        if (!(await waitWhileBusy(msg || "Another check is running.", since))) {
          stoneReady();
          announce("Cancelled.");
          return;
        }
        continue;
      }
      stoneError(msg || `The server refused the check (HTTP ${resp.status}).`);
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
  } catch (e) {
    if (e && e.name === "AbortError") {
      clearSkeletons();
      if (state.done) {
        renderCounts(state.counts);
        stoneStopped(`Cancelled after ${state.done} of ${state.total} claims.`,
          state.counts, state.done, state.cited);
      } else {
        stoneReady();
        setProvenance("Cancelled.");
      }
      announce("Run cancelled.");
    } else {
      stoneError("Could not reach the server.");
    }
  } finally {
    stopWaiting();
    if (cancelBusy) cancelBusy();
    state.abort = null;
    state.running = false;
    $("cancel").hidden = true;
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

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function replay(run, opts = {}) {
  const slow = Boolean(opts.slow);
  resetRunView();
  state.replay = true;
  state.replaying = true;
  state.retryPlayback = false;
  state.startedAt = 0;
  state.lastRun = run;
  state.lastRunExample = Boolean(opts.example);
  $("export").disabled = false;
  const view = resultsView(run.report);
  const events = runEvents(run);
  const date = new Date(run.created).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  $("replay-title").textContent = opts.example ? "Saved example" : "Saved run";
  $("replay-date").textContent = date;
  $("replay-msg").textContent = opts.example
    ? `Saved example from ${date}. A real Perplexity answer, extended with more from the same sources; `
      + "one figure (Samsung 18% → 19%) is changed to show a catch."
    : `Saved run from ${date}. Replayed from this browser; no tokens spent.`;
  $("replay").hidden = false;
  $("railbody").scrollTop = 0;
  setProvenance("replaying · 0 tokens");
  $("docpane").scrollTop = 0;

  if (!slow) {
    for (const ev of events) view.feed(ev);
    state.replaying = false;
    state.lastRun = run;
    state.lastRunExample = Boolean(opts.example);
    saveHistory(run, opts.example);
    setProvenance(replayProvenance(run, opts.example));
    requestAnimationFrame(layout);
    return;
  }

  const playback = { cancelled: false };
  state.playback = playback;
  state.running = true;
  setBusy(true);
  $("cancel").hidden = false;
  announce("Playing back the saved run.");
  const start = events.shift();
  if (start) view.feed(start);
  for (const ev of events) {
    if (playback.cancelled) break;
    if (ev.type === "claim") await sleep(420);
    if (playback.cancelled) break;
    view.feed(ev);
    if (ev.type === "done") break;
  }
  if (playback.cancelled) {
    clearSkeletons();
    if (state.done) {
      renderCounts(state.counts);
      stoneStopped(`Playback stopped at claim ${state.done} of ${state.total}.`,
        state.counts, state.done, state.cited, true);
    } else {
      stoneReady();
    }
    setProvenance("Playback stopped · 0 tokens spent.");
  } else {
    state.lastRun = run;
    state.lastRunExample = Boolean(opts.example);
    saveHistory(run, opts.example);
    setProvenance(replayProvenance(run, opts.example));
  }
  state.playback = null;
  state.running = false;
  state.replaying = false;
  $("cancel").hidden = true;
  setBusy(false);
  requestAnimationFrame(layout);
}

const EXAMPLE_LOADED = "Example loaded. Run the check when you're ready.";

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
  if (validRun(run, text)) replay(run, { example: true });
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
  const clean = String(text || "").replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
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
  document.body.classList.add("has-report");
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
  document.title = `${state.name} · Touchstone`;

  $("report").value = clean;
  $("source").value = clean;
  sourceDirty = false;
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
  $("docbar").hidden = false;
  $("docname").textContent = state.name;
  $("docname").title = state.name;
  $("docname").hidden = false;
  $("new").hidden = false;
  $("showmatched").hidden = false;
  $("docwrap").classList.add("has-doc");
  $("docpane").scrollTop = 0;

  applyModeUI();
  stoneReady();
  setProvenance("Zero tokens until you run.");
  placeStone();
  layout();
  requestAnimationFrame(layout);
  setTimeout(layout, 80);
  announce(`${state.name} open. ${(clean.match(/https?:\/\/[^\s)>\]]+/g) || []).length} source links.`);
  return true;
}

/* ---------------- in-place block editor ----------------
   One surface, no edit button. A click turns the block under the pointer into
   its own Markdown source in place; Esc or clicking away renders it back. This
   is the block-level cousin of Obsidian's Live
   Preview: syntax is visible only while the block is active, and the rest of
   the document stays rendered. */

let inline = null;

// Strip inline Markdown while remembering where each visible character came
// from, so a click in the rendered block can land on the matching source.
function inlinePlain(src) {
  let text = "";
  const map = [];
  let i = 0;
  const push = (s, at) => {
    for (let k = 0; k < s.length; k += 1) { text += s[k]; map.push(at + k); }
  };
  while (i < src.length) {
    const rest = src.slice(i);
    let m;
    if ((m = /^\*\*([^*]+?)\*\*/.exec(rest))) { push(m[1], i + 2); i += m[0].length; }
    else if ((m = /^__([^_]+?)__/.exec(rest))) { push(m[1], i + 2); i += m[0].length; }
    else if ((m = /^\*([^*\n]+?)\*/.exec(rest))) { push(m[1], i + 1); i += m[0].length; }
    else if ((m = /^_([^_\n]+?)_/.exec(rest))) { push(m[1], i + 1); i += m[0].length; }
    else if ((m = /^`([^`]+?)`/.exec(rest))) { push(m[1], i + 1); i += m[0].length; }
    else if ((m = /^\$\$([\s\S]+?)\$\$/.exec(rest))) { push(m[1], i + 2); i += m[0].length; }
    else if ((m = /^\$([^$\n]+?)\$/.exec(rest))) { push(m[1], i + 1); i += m[0].length; }
    else if ((m = /^!\[([^\]]*)\]\([^)]*\)/.exec(rest))) { push(m[1], i + 2); i += m[0].length; }
    else if ((m = /^\[([^\]]*)\]\([^)]*\)/.exec(rest))) { push(m[1], i + 1); i += m[0].length; }
    else { text += rest[0]; map.push(i); i += 1; }
  }
  return { text, map };
}

function caretFromPoint(blk, x, y, src) {
  const at = src.length;
  if (!document.caretRangeFromPoint) return at;
  let cr = null;
  try { cr = document.caretRangeFromPoint(x, y); } catch { return at; }
  if (!cr || !blk.contains(cr.startContainer)) return at;
  const r = document.createRange();
  r.selectNodeContents(blk);
  try { r.setEnd(cr.startContainer, cr.startOffset); } catch { return at; }
  const prefix = r.toString();
  const { text, map } = inlinePlain(src);
  let idx = text.indexOf(prefix);
  if (idx >= 0) {
    idx += prefix.length;
  } else {
    // Line boxes can differ by a space; the last few rendered words still map.
    const tail = prefix.slice(-24).trim();
    if (!tail) return at;
    idx = text.lastIndexOf(tail);
    if (idx < 0) return at;
    idx += tail.length;
  }
  return idx < map.length ? map[idx] : src.length;
}

function growInline(ta) {
  ta.style.height = "auto";
  ta.style.height = `${Math.max(ta.scrollHeight, 24)}px`;
  if (inline && inline.ta === ta) positionInlineFill();
}

// The highlight is its own layer, so it can extend past the text box without
// moving the text or the caret. It reaches into the paper's left gutter and
// keeps a deliberate 6px of air above and below the source line.
function positionInlineFill() {
  if (!inline || !inline.fill) return;
  const { ta, fill } = inline;
  const paper = $("paper");
  if (!ta || !paper || !ta.isConnected) return;
  const cs = getComputedStyle(ta);
  const padL = parseFloat(cs.paddingLeft) || 0;
  const padR = parseFloat(cs.paddingRight) || 0;
  const textLeft = ta.offsetLeft + padL;
  const textRight = ta.offsetLeft + ta.offsetWidth - padR;
  const left = Math.max(0, textLeft - 12);
  const right = Math.min(paper.clientWidth - 2, textRight + 12);
  fill.style.left = `${left}px`;
  fill.style.width = `${Math.max(0, right - left)}px`;
  fill.style.top = `${Math.max(0, ta.offsetTop - 6)}px`;
  fill.style.height = `${ta.offsetHeight + 12}px`;
}

function adjacentBlock(blk, dir) {
  const blocks = [...$("paper").querySelectorAll(".blk")];
  const at = blocks.indexOf(blk);
  return at < 0 ? null : blocks[at + dir] || null;
}

function blockAfter(line) {
  return [...$("paper").querySelectorAll(".blk")].find((b) => b.__from >= line) || null;
}

function blockBefore(line) {
  return [...$("paper").querySelectorAll(".blk")].reverse().find((b) => b.__to <= line) || null;
}

// Arrow keys at the edge of a block continue into the adjacent block. The
// edit is committed first, so a changed block re-renders; locate the neighbour
// again by source line rather than holding a DOM node that the re-render replaced.
function moveInline(dir) {
  if (!inline || state.running) return false;
  const { ta, blk } = inline;
  if (!adjacentBlock(blk, dir)) return false;
  const from = blk.__from;
  const newLines = ta.value.replace(/\s+$/, "").split("\n").length;
  closeInline();
  if (inline) return false;   // rejected: the report cannot be empty or is too long
  const target = dir > 0 ? blockAfter(from + newLines) : blockBefore(from);
  if (!target) return false;
  openBlockEditor(target, 0, 0, dir > 0 ? "start" : "end");
  return true;
}

function applyEditedReport(next) {
  const pane = $("docpane");
  const y = pane.scrollTop;
  state.report = next;
  sourceDirty = false;
  $("report").value = next;
  if ($("source")) $("source").value = next;
  updateCount();
  resetRunView();
  const article = $("paper");
  article.replaceChildren();
  doc.units = renderReport(article, next);
  for (const unit of doc.units) {
    unit.words = wordsOf(unit.text);
    unit.nums = numbersOf(unit.text);
  }
  stoneReady();
  setProvenance("Edited · previous check cleared.");
  renderRuler();
  growSource();
  layout();
  pane.scrollTop = y;
  requestAnimationFrame(() => { pane.scrollTop = y; layout(); });
  announce("Report edited. Previous check cleared.");
}

/* ---------------- view modes and the Markdown bar ---------------- */

function growSource() {
  const ta = $("source");
  if (!ta || state.mode !== "edit" || $("sourceview").hidden) return;
  ta.style.height = "auto";
  ta.style.height = `${Math.max(ta.scrollHeight, 320)}px`;
}

function syncModeControls() {
  for (const btn of document.querySelectorAll("#mode-switch button[data-mode], #modemenu button[data-mode]")) {
    const active = btn.dataset.mode === state.mode;
    if (btn.getAttribute("role") === "menuitemradio") btn.setAttribute("aria-checked", String(active));
    else btn.setAttribute("aria-pressed", String(active));
  }
  const label = $("modebtn-label");
  if (label) label.textContent = MODE_WORDS[state.mode] || "Inline";
}

function closeHeadingMenu() {
  const menu = $("headingmenu");
  const btn = $("headingbtn");
  if (menu) menu.hidden = true;
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function closeModeMenu() {
  const menu = $("modemenu");
  const btn = $("modebtn");
  if (menu) menu.hidden = true;
  if (btn) btn.setAttribute("aria-expanded", "false");
}

function syncToolState() {
  const editing = !!state.report && (state.mode === "edit" || (state.mode === "inline" && !!inline));
  const tools = $("md-tools");
  const hint = $("toolhint");
  if (tools) tools.hidden = !editing;
  if (hint) hint.hidden = !(!!state.report && state.mode === "inline" && !inline);
  const bar = $("docbar");
  if (bar) bar.classList.toggle("has-tools", editing);
  if (!editing) closeHeadingMenu();
  for (const btn of document.querySelectorAll("#md-tools button")) {
    btn.disabled = state.running;
  }
  const modebtn = $("modebtn");
  if (modebtn) modebtn.disabled = state.running;
  for (const btn of document.querySelectorAll("#mode-switch button, #modemenu button")) {
    btn.disabled = state.running;
  }
}

function applyModeUI() {
  const has = !!state.report;
  const edit = has && state.mode === "edit";
  document.body.dataset.mode = state.mode;
  $("docbar").hidden = !has;
  $("paper").hidden = !has || edit;
  $("sourceview").hidden = !edit;
  if (edit) {
    if (!sourceDirty) $("source").value = state.report;
    growSource();
  }
  syncModeControls();
  syncToolState();
  mmKey = "";
  if (has) {
    renderRuler();
    layout();
  }
}

function commitSource() {
  if (!sourceDirty) return true;
  const next = $("source").value.replace(/\s+$/, "");
  if (!next.trim()) {
    setProvenance("Edit ignored: the report cannot be empty.");
    $("source").focus();
    return false;
  }
  if (next.length > MAX_CHARS) {
    setProvenance(`Edit ignored: reports are limited to ${MAX_CHARS.toLocaleString()} characters.`);
    $("source").focus();
    return false;
  }
  if (next !== state.report) applyEditedReport(next);
  sourceDirty = false;
  return true;
}

function setMode(next) {
  if (!MODES.has(next) || state.running || !state.report) return false;
  closeModeMenu();
  closeHeadingMenu();
  if (next === state.mode) {
    applyModeUI();
    return true;
  }
  if (inline) {
    closeInline();
    if (inline) return false;
  }
  if (state.mode === "edit" && next !== "edit" && !commitSource()) return false;
  if (next === "edit") {
    $("source").value = state.report;
    sourceDirty = false;
  }
  state.mode = next;
  try { localStorage.setItem(MODE_KEY, next); } catch { /* private mode */ }
  applyModeUI();
  placeStone();
  requestAnimationFrame(() => {
    layout();
    if (next === "edit") $("source").focus({ preventScroll: true });
  });
  announce(`${MODE_WORDS[next]} view.`);
  return true;
}

function onSourceInput() {
  const ta = $("source");
  if (!ta) return;
  const first = !sourceDirty;
  sourceDirty = true;
  $("report").value = ta.value;
  updateCount();
  if (first) {
    resetRunView();
    stoneReady();
    setProvenance("Edited: previous check cleared.");
    renderRuler();
  }
  growSource();
  layout();
}

function editorTarget() {
  if (state.mode === "edit") return $("source");
  if (state.mode === "inline" && inline) return inline.ta;
  return null;
}

function afterTool(ta) {
  if (inline && inline.ta === ta) {
    growInline(ta);
    positionInlineFill();
  }
  if (ta === $("source")) {
    onSourceInput();
  } else {
    layout();
  }
  ta.focus();
}

function toggleWrap(ta, open, close, placeholder) {
  const s = ta.selectionStart;
  const e = ta.selectionEnd;
  const raw = ta.value.slice(s, e);
  const wrapped = raw.length >= open.length + close.length &&
    raw.startsWith(open) && raw.endsWith(close);
  if (wrapped) {
    const inner = raw.slice(open.length, raw.length - close.length);
    ta.setRangeText(inner, s, e, "end");
    ta.setSelectionRange(s, s + inner.length);
  } else {
    // A selection or caret inside **…** (or the other marker pairs) toggles
    // the existing span off instead of stacking a second pair of markers.
    const outerStart = s - open.length;
    const outerEnd = e + close.length;
    const around = outerStart >= 0 &&
      ta.value.slice(outerStart, s) === open &&
      ta.value.slice(e, outerEnd) === close;
    if (around) {
      const startOffset = s - outerStart - open.length;
      const endOffset = e - outerStart - open.length;
      ta.setRangeText("", e, outerEnd, "end");
      ta.setRangeText("", outerStart, s, "end");
      ta.setSelectionRange(outerStart + startOffset, outerStart + endOffset);
    } else {
      const label = raw || placeholder;
      ta.setRangeText(`${open}${label}${close}`, s, e, "end");
      ta.setSelectionRange(s + open.length, s + open.length + label.length);
    }
  }
  afterTool(ta);
}

function selectedLines(ta) {
  const s = ta.selectionStart;
  const e = ta.selectionEnd;
  const start = ta.value.lastIndexOf("\n", Math.max(0, s - 1)) + 1;
  let end = ta.value.indexOf("\n", e);
  if (end < 0) end = ta.value.length;
  return { start, end, text: ta.value.slice(start, end) };
}

function linePrefix(ta, prefix) {
  const range = selectedLines(ta);
  const pattern = prefix === "- " ? /^[-*+]\s+/
    : prefix === "1. " ? /^\d+[.)]\s+/
    : /^>\s?/;
  const lines = range.text.split("\n");
  const all = lines.every((line) => pattern.test(line.replace(/^\s*/, "")));
  const next = lines.map((line) => {
    const indent = /^\s*/.exec(line)[0];
    const rest = line.slice(indent.length);
    return all ? indent + rest.replace(pattern, "") : indent + prefix + rest;
  }).join("\n");
  ta.setRangeText(next, range.start, range.end, "end");
  afterTool(ta);
}

function applyHeading(level, ta) {
  const range = selectedLines(ta);
  const lines = range.text.split("\n");
  const marker = "#".repeat(level);
  const same = new RegExp(`^${marker}\\s+`);
  const any = /^#{1,6}\s+/;
  const all = lines.every((line) => same.test(line.replace(/^\s*/, "")));
  const next = lines.map((line) => {
    const indent = /^\s*/.exec(line)[0];
    const rest = line.slice(indent.length);
    if (all) return indent + rest.replace(any, "");
    return `${indent}${marker} ${rest.replace(any, "")}`;
  }).join("\n");
  ta.setRangeText(next, range.start, range.end, "end");
  afterTool(ta);
}

function applyLink(ta) {
  const s = ta.selectionStart;
  const e = ta.selectionEnd;
  const label = ta.value.slice(s, e) || "link text";
  ta.setRangeText(`[${label}](https://)`, s, e, "end");
  const at = s + label.length + 3;
  ta.setSelectionRange(at, at + 8);
  afterTool(ta);
}

function insertBlock(ta, open, close, body) {
  const s = ta.selectionStart;
  const e = ta.selectionEnd;
  const before = ta.value.slice(0, s);
  const after = ta.value.slice(e);
  const lead = before && !before.endsWith("\n") ? "\n" : "";
  const trail = after && !after.startsWith("\n") ? "\n" : "";
  const text = `${lead}${open}\n${body}\n${close}${trail}`;
  const at = s + lead.length;
  ta.setRangeText(text, s, e, "end");
  ta.setSelectionRange(at + open.length + 1, at + open.length + 1 + body.length);
  afterTool(ta);
}

function applyCodeBlock(ta) {
  const body = ta.value.slice(ta.selectionStart, ta.selectionEnd);
  insertBlock(ta, "```", "```", body);
}

function applyMathBlock(ta) {
  const body = ta.value.slice(ta.selectionStart, ta.selectionEnd);
  insertBlock(ta, "$$", "$$", body);
}

function applyCommand(cmd) {
  const ta = editorTarget();
  if (!ta || state.running) return;
  if (cmd === "bold") toggleWrap(ta, "**", "**", "bold text");
  else if (cmd === "italic") toggleWrap(ta, "*", "*", "italic text");
  else if (cmd === "strike") toggleWrap(ta, "~~", "~~", "struck text");
  else if (cmd === "code") toggleWrap(ta, "`", "`", "code");
  else if (cmd === "link") applyLink(ta);
  else if (cmd === "math") toggleWrap(ta, "$", "$", "x");
  else if (cmd === "mathblock") applyMathBlock(ta);
  else if (cmd === "codeblock") applyCodeBlock(ta);
  else if (cmd === "ul") linePrefix(ta, "- ");
  else if (cmd === "ol") linePrefix(ta, "1. ");
  else if (cmd === "quote") linePrefix(ta, "> ");
  else if (cmd === "h1") applyHeading(1, ta);
  else if (cmd === "h2") applyHeading(2, ta);
  else if (cmd === "h3") applyHeading(3, ta);
}

function closeInline() {
  if (!inline) return false;
  const { ta, blk, fill } = inline;
  inline = null;
  document.body.classList.remove("is-editing");
  const src = ta.value.replace(/\s+$/, "");
  const changed = src !== blk.__src;
  if (!changed) {
    ta.remove();
    if (fill) fill.remove();
    blk.hidden = false;
    syncToolState();
    layout();
    return false;
  }
  const lines = state.report.split("\n");
  const next = lines.slice(0, blk.__from).concat(src.split("\n"), lines.slice(blk.__to)).join("\n");
  if (!next.trim()) {
    setProvenance("Edit ignored: the report cannot be empty.");
    inline = { ta, blk, fill };
    document.body.classList.add("is-editing");
    layout();
    ta.focus();
    return false;
  }
  if (next.length > MAX_CHARS) {
    setProvenance(`Edit ignored: reports are limited to ${MAX_CHARS.toLocaleString()} characters.`);
    inline = { ta, blk, fill };
    document.body.classList.add("is-editing");
    layout();
    ta.focus();
    return false;
  }
  ta.remove();
  if (fill) fill.remove();
  blk.hidden = false;
  applyEditedReport(next);
  syncToolState();
  return true;
}

function openBlockEditor(blk, x, y, caretAt) {
  if (state.mode !== "inline" || state.running || !blk || !blk.__src || !blk.isConnected) return;
  if (inline) {
    const committed = closeInline();
    // A rejected edit stays open and must keep its focus. A committed edit
    // re-renders the article, so the block this click landed on is gone; the
    // next click opens a block, while an unchanged edit continues.
    if (inline || committed || !blk.isConnected) return;
  }

  const ta = el("textarea", "inline-edit");
  ta.value = blk.__src;
  ta.spellcheck = false;
  ta.setAttribute("aria-label", "Edit this block's Markdown source");

  // Every block edits as the same plain source text. A heading, list item or
  // table stops carrying its rendered type size while the source is open; the
  // block's outside spacing is kept so the page does not jump.
  const bcs = getComputedStyle(blk);
  ta.style.fontFamily = "var(--mono)";
  ta.style.fontSize = "15px";
  ta.style.fontWeight = "400";
  ta.style.lineHeight = "1.6";
  ta.style.letterSpacing = "0";
  ta.style.textAlign = "left";
  ta.style.margin = bcs.margin;
  ta.style.padding = "0 12px 0 0";
  if (blk.tagName === "BLOCKQUOTE" || blk.tagName === "UL" || blk.tagName === "OL") {
    ta.style.paddingLeft = bcs.paddingLeft;
  }
  if (blk.tagName === "PRE") ta.style.padding = bcs.padding;
  ta.style.borderTop = "0";
  ta.style.color = "var(--ink)";
  ta.style.background = "transparent";

  const at = caretAt === "start" ? 0
    : caretAt === "end" ? ta.value.length
    : caretFromPoint(blk, x, y, ta.value);
  const fill = el("div", "inline-fill");
  fill.setAttribute("aria-hidden", "true");
  blk.hidden = true;
  blk.parentNode.insertBefore(fill, blk);
  blk.parentNode.insertBefore(ta, blk);
  inline = { ta, blk, fill };
  document.body.classList.add("is-editing");
  growInline(ta);
  positionInlineFill();
  syncToolState();
  ta.focus();
  const pos = Math.max(0, Math.min(ta.value.length, at));
  ta.setSelectionRange(pos, pos);
  layout();

  ta.addEventListener("input", () => {
    growInline(ta);
    layout();
  });
  ta.addEventListener("blur", () => { if (inline && inline.ta === ta) closeInline(); });
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closeInline();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      e.stopPropagation();
      closeInline();
      return;
    }
    if (e.key === "Tab") {
      e.preventDefault();
      const s = ta.selectionStart;
      const t = ta.selectionEnd;
      ta.setRangeText("  ", s, t, "end");
      growInline(ta);
      layout();
      return;
    }
    if (!e.shiftKey && !e.altKey && !e.ctrlKey && !e.metaKey &&
        (e.key === "ArrowUp" || e.key === "ArrowDown") &&
        ta.selectionStart === ta.selectionEnd &&
        ((e.key === "ArrowUp" && ta.selectionStart === 0) ||
         (e.key === "ArrowDown" && ta.selectionStart === ta.value.length))) {
      if (moveInline(e.key === "ArrowDown" ? 1 : -1)) {
        e.preventDefault();
        e.stopPropagation();
      }
      return;
    }
    if ((e.ctrlKey || e.metaKey) && !e.altKey) {
      const k = e.key.toLowerCase();
      if (k === "b") { e.preventDefault(); applyCommand("bold"); }
      else if (k === "i") { e.preventDefault(); applyCommand("italic"); }
      else if (k === "k") { e.preventDefault(); applyCommand("link"); }
    }
  });
}

function editVisibleBlock() {
  if (state.mode !== "inline" || state.running || !state.report) return;
  const pane = $("docpane");
  const prect = pane.getBoundingClientRect();
  const block = [...$("paper").querySelectorAll(".blk")].find((b) => {
    const r = b.getBoundingClientRect();
    return r.bottom > prect.top + 10 && r.top < prect.bottom - 10;
  });
  if (!block) return;
  const r = block.getBoundingClientRect();
  const y = Math.min(Math.max(r.top + 14, prect.top + 14), prect.bottom - 14);
  openBlockEditor(block, r.left + 14, y);
}

function bindInlineEditor() {
  const paper = $("paper");
  let down = null;
  paper.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    down = { x: e.clientX, y: e.clientY };
  });
  paper.addEventListener("click", (e) => {
    if (state.mode !== "inline" || state.running) return;
    if (e.target.closest("a, button, .inline-edit, .gmarks")) return;
    if (down) {
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      down = null;
      if (moved > 6) return;
    }
    const sel = document.getSelection();
    if (sel && !sel.isCollapsed) return;
    const blk = e.target.closest(".blk");
    if (!blk || !blk.__src) return;
    openBlockEditor(blk, e.clientX, e.clientY);
  });
}

function showFront(focus) {
  if (inline) {
    inline.ta.remove();
    if (inline.fill) inline.fill.remove();
    inline = null;
    document.body.classList.remove("is-editing");
  }
  state.report = "";
  state.name = "";
  state.running = false;
  document.body.classList.remove("has-report");
  state.replay = false;
  state.selected = null;
  state.pager = [];
  state.pagerIdx = 0;
  document.title = "Touchstone";
  resetRunView();
  doc.units = [];
  doc.claims = [];
  doc.byNo = new Map();
  doc.unplaced = [];

  $("paper").replaceChildren();
  $("paper").hidden = true;
  $("front").hidden = false;
  $("docbar").hidden = true;
  $("sourceview").hidden = true;
  $("source").value = "";
  sourceDirty = false;
  $("docwrap").classList.remove("has-doc");
  $("docname").hidden = true;
  $("new").hidden = true;
  $("showmatched").hidden = true;
  $("ovr").hidden = true;
  for (const old of $("ovr").querySelectorAll(".ovr-mark")) old.remove();
  $("totop").hidden = true;
  $("report").value = "";
  updateCount();
  frontError("");
  stoneEmpty();
  syncToolState();
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
const sheetMQ = window.matchMedia("(max-width: 1099px)");
let sheetDrag = null;
let sheetRestore = null;
let sheetRAF = 0;

function bench() { return document.querySelector(".body"); }

function sheetMin() {
  const grip = $("grip");
  return grip && grip.offsetHeight ? grip.offsetHeight : 26;
}

function sheetMax() {
  const body = bench();
  return body ? body.clientHeight : 0;
}

function queueSheetLayout() {
  if (sheetRAF) return;
  sheetRAF = requestAnimationFrame(() => { sheetRAF = 0; layout(); });
}

function setGripValue(height) {
  const grip = $("grip");
  if (!grip) return;
  const min = sheetMin();
  const max = Math.max(min, sheetMax());
  const pct = max <= min ? 100 : Math.round(((height - min) / (max - min)) * 100);
  grip.setAttribute("aria-valuenow", String(Math.max(0, Math.min(100, pct))));
  grip.setAttribute("aria-valuetext", height <= min + 1 ? "Results closed" : `${pct}% open`);
}

function applySheetHeight(height, { snap = false } = {}) {
  const body = bench();
  const rail = $("rail");
  if (!body || !rail || !sheetMQ.matches) return;
  const min = sheetMin();
  const max = Math.max(min, sheetMax());
  let h = Math.round(Math.max(min, Math.min(max, height)));
  if (snap) {
    if (h <= min + 28) h = min;
    else if (h >= max - 6) h = max;
  }
  body.style.setProperty("--sheet-h", `${h}px`);
  rail.classList.toggle("is-collapsed", h <= min + 1);
  setGripValue(h);
  queueSheetLayout();
}

function defaultSheetHeight() {
  return Math.round(window.innerHeight * (narrow.matches ? 0.44 : 0.42));
}

function collapseSheet() {
  const rail = $("rail");
  const h = rail.getBoundingClientRect().height;
  if (h > sheetMin() + 28) sheetRestore = h;
  applySheetHeight(sheetMin());
}

function expandSheet() {
  applySheetHeight(sheetRestore || defaultSheetHeight());
}

function toggleSheet() {
  const rail = $("rail");
  if (rail.classList.contains("is-collapsed")) expandSheet();
  else collapseSheet();
}

function syncSheet() {
  const body = bench();
  const rail = $("rail");
  if (!body || !rail) return;
  if (!sheetMQ.matches) {
    body.style.removeProperty("--sheet-h");
    rail.classList.remove("is-collapsed", "is-dragging");
    sheetDrag = null;
    sheetRestore = null;
    return;
  }
  if (body.style.getPropertyValue("--sheet-h")) {
    applySheetHeight(rail.getBoundingClientRect().height);
  } else {
    setGripValue(rail.getBoundingClientRect().height);
  }
}

function bindSheet() {
  const grip = $("grip");
  if (!grip) return;
  const onMove = (e) => {
    if (!sheetDrag) return;
    const dy = e.clientY - sheetDrag.y;
    if (!sheetDrag.moved && Math.abs(dy) > 3) sheetDrag.moved = true;
    if (sheetDrag.moved) {
      applySheetHeight(sheetDrag.h - dy);
      e.preventDefault();
    }
  };
  const onUp = (e) => finish(e);
  const onCancel = (e) => finish(e, true);
  const detach = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    window.removeEventListener("pointercancel", onCancel);
  };
  const finish = (e, cancelled = false) => {
    if (!sheetDrag) return;
    const { moved } = sheetDrag;
    const rail = $("rail");
    const h = rail.getBoundingClientRect().height;
    sheetDrag = null;
    detach();
    rail.classList.remove("is-dragging");
    document.body.classList.remove("is-sheet-drag");
    try { grip.releasePointerCapture(e.pointerId); } catch { /* already released */ }
    if (cancelled) return;
    if (!moved) {
      toggleSheet();
      return;
    }
    if (h > sheetMin() + 28) sheetRestore = h;
    applySheetHeight(h, { snap: true });
  };
  grip.addEventListener("pointerdown", (e) => {
    if (!sheetMQ.matches) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    const rail = $("rail");
    const h = rail.getBoundingClientRect().height;
    sheetDrag = { y: e.clientY, h, moved: false };
    if (h > sheetMin() + 28) sheetRestore = h;
    rail.classList.add("is-dragging");
    document.body.classList.add("is-sheet-drag");
    try { grip.setPointerCapture(e.pointerId); } catch { /* capture is optional */ }
    window.addEventListener("pointermove", onMove, { passive: false });
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    grip.focus({ preventScroll: true });
    e.preventDefault();
  });
  grip.addEventListener("keydown", (e) => {
    if (!sheetMQ.matches) return;
    const rail = $("rail");
    const h = rail.getBoundingClientRect().height;
    const min = sheetMin();
    const max = Math.max(min, sheetMax());
    const step = e.shiftKey ? 48 : 16;
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      let next = h + (e.key === "ArrowUp" ? step : -step);
      if (e.key === "ArrowDown" && next <= min + 28) next = min;
      next = Math.max(min, Math.min(max, next));
      if (h > min + 28) sheetRestore = h;
      applySheetHeight(next);
      e.preventDefault();
    } else if (e.key === "Home") {
      if (h > min + 28) sheetRestore = h;
      applySheetHeight(max);
      e.preventDefault();
    } else if (e.key === "End") {
      collapseSheet();
      e.preventDefault();
    } else if (e.key === "Enter" || e.key === " ") {
      toggleSheet();
      e.preventDefault();
    }
  });
}

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
  const btn = $("showmatched");
  btn.setAttribute("aria-pressed", String(on));
  btn.textContent = on ? "Hide sourced" : "Show sourced";
}

function stepCard(dir) {
  const cards = [...$("cards").querySelectorAll(":scope > .card")].filter((card) => !card.hidden);
  if (!cards.length) return;
  const at = cards.findIndex((card) => card.classList.contains("is-sel"));
  let next = at < 0 ? 0 : at + dir;
  next = Math.max(0, Math.min(cards.length - 1, next));
  const no = int(cards[next].dataset.claim);
  if (no !== null) selectClaim(no, true);
  else cards[next].scrollIntoView({ block: "nearest", behavior: motion() });
}

function bindEvents() {
  bindInlineEditor();
  bindSheet();
  const docbar = $("docbar");
  docbar.addEventListener("pointerdown", (e) => {
    if (e.target.closest("#md-tools button")) e.preventDefault();
  });
  docbar.addEventListener("click", (e) => {
    const mode = e.target.closest("button[data-mode]");
    if (mode) {
      e.preventDefault();
      setMode(mode.dataset.mode);
      return;
    }
    if (e.target.closest("#modebtn")) {
      const menu = $("modemenu");
      const open = menu.hidden;
      closeHeadingMenu();
      menu.hidden = !open;
      $("modebtn").setAttribute("aria-expanded", String(open));
      return;
    }
    if (e.target.closest("#headingbtn")) {
      const menu = $("headingmenu");
      const open = menu.hidden;
      closeModeMenu();
      menu.hidden = !open;
      $("headingbtn").setAttribute("aria-expanded", String(open));
      return;
    }
    const tool = e.target.closest("#md-tools button[data-cmd]");
    if (tool) {
      e.preventDefault();
      closeHeadingMenu();
      applyCommand(tool.dataset.cmd);
    }
  });
  $("source").addEventListener("input", onSourceInput);
  $("source").addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeModeMenu();
      closeHeadingMenu();
    }
    const mod = e.ctrlKey || e.metaKey;
    if (mod && !e.altKey) {
      const key = e.key.toLowerCase();
      if (key === "b" || key === "i" || key === "k") {
        e.preventDefault();
        e.stopPropagation();
        applyCommand(key === "b" ? "bold" : key === "i" ? "italic" : "link");
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        e.stopPropagation();
        if (commitSource()) runAudit();
        return;
      }
    }
    if (e.key === "Tab") {
      e.preventDefault();
      const s = e.target.selectionStart;
      const t = e.target.selectionEnd;
      e.target.setRangeText("  ", s, t, "end");
      onSourceInput();
    }
  });
  document.addEventListener("pointerdown", (e) => {
    if (!e.target.closest("#modebtn, #modemenu")) closeModeMenu();
    if (!e.target.closest("#headingbtn, #headingmenu")) closeHeadingMenu();
  });
  $("theme").addEventListener("click", toggleTheme);
  $("textsize").addEventListener("click", (e) => { e.stopPropagation(); toggleTextMenu(); });
  $("textmenu").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-scope]");
    if (!btn) return;
    setTextSize(btn.dataset.scope, btn.dataset.size);
  });
  document.addEventListener("pointerdown", (e) => {
    const menu = $("textmenu");
    if (!menu || menu.hidden) return;
    if (e.target.closest("#textmenu, #textsize")) return;
    setTextMenu(false, false);
  });
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
  $("run").addEventListener("click", () => {
    if (state.retryPlayback && state.lastRun) {
      replay(state.lastRun, { slow: true, example: state.lastRunExample });
      return;
    }
    runAudit();
  });
  $("rerun").addEventListener("click", runAudit);
  $("run-live").addEventListener("click", runAudit);
  $("playback").addEventListener("click", () => {
    if (!state.running && state.lastRun) {
      replay(state.lastRun, { slow: true, example: state.lastRunExample });
    }
  });
  $("cancel").addEventListener("click", () => {
    if (state.playback) { state.playback.cancelled = true; return; }
    if (cancelBusy) { cancelBusy(); return; }
    if (state.abort) state.abort.abort();
  });
  $("ev-show").addEventListener("click", () => {
    const no = evidenceNo;
    $("evidence").close();
    if (no !== null) selectClaim(no, true);
  });
  $("evidence").addEventListener("click", (e) => {
    if (e.target === $("evidence")) $("evidence").close();
  });
  $("copy-prompt").addEventListener("click", copyPrompt);
  $("prev").addEventListener("click", () => stepProblem(-1));
  $("next").addEventListener("click", () => stepProblem(1));
  $("totop").addEventListener("click", () => $("docpane").scrollTo({ top: 0, behavior: motion() }));
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
    const pane = $("docpane");
    if (pane.scrollHeight - pane.clientHeight <= 0) return;
    const win = $("ovrwin");
    const onThumb = e.target === win;
    rulerGrab = onThumb ? e.clientY - win.getBoundingClientRect().top : win.offsetHeight / 2;
    rulerDrag = true;
    try { ovr.setPointerCapture(e.pointerId); } catch { /* no capture */ }
    rulerGrab = Math.max(0, Math.min(win.offsetHeight || 0, rulerGrab));
    if (!onThumb) scrollFromRuler(e.clientY);
    e.preventDefault();
  });
  ovr.addEventListener("pointermove", (e) => { if (rulerDrag) scrollFromRuler(e.clientY); });
  ovr.addEventListener("pointerup", (e) => {
    rulerDrag = false;
    try { ovr.releasePointerCapture(e.pointerId); } catch { /* already released */ }
  });
  ovr.addEventListener("pointercancel", () => { rulerDrag = false; });
  ovr.addEventListener("wheel", (e) => {
    if (!state.report) return;
    $("docpane").scrollTop += e.deltaY;
    e.preventDefault();
  }, { passive: false });

  // The minimap is a second ruler, but it maps onto the preview's own scale:
  // clicking a line jumps to that line, and the empty space below the preview
  // is the tail of the document.
  const mmEl = $("minimap");
  if (mmEl) {
    let mmGrab = -1;
    const scrollFromMinimap = (clientY) => {
      const pane = $("docpane");
      if (!pane || !mmScale) return;
      const r = mmEl.getBoundingClientRect();
      const bandH = Math.max(14, Math.round(pane.clientHeight * mmScale));
      const visH = Math.min(r.height, mmSkeletonH || r.height);
      const grab = mmGrab < 0 ? bandH / 2 : mmGrab;
      const maxScroll = Math.max(0, pane.scrollHeight - pane.clientHeight);
      const bandTop = Math.min(Math.max(0, visH - bandH), clientY - r.top - grab);
      pane.scrollTop = Math.min(maxScroll, Math.max(0, bandTop / mmScale));
    };
    mmEl.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || !state.report) return;
      const pane = $("docpane");
      const win = $("mmslider");
      if (pane.scrollHeight - pane.clientHeight <= 0) return;
      const y = e.clientY - mmEl.getBoundingClientRect().top;
      mmGrab = win && !win.hidden && y >= win.offsetTop && y <= win.offsetTop + win.offsetHeight
        ? y - win.offsetTop
        : win ? win.offsetHeight / 2 : 0;
      rulerDrag = true;
      try { mmEl.setPointerCapture(e.pointerId); } catch { /* no capture */ }
      scrollFromMinimap(e.clientY);
      e.preventDefault();
    });
    mmEl.addEventListener("pointermove", (e) => { if (rulerDrag) scrollFromMinimap(e.clientY); });
    mmEl.addEventListener("pointerup", (e) => {
      rulerDrag = false;
      mmGrab = -1;
      try { mmEl.releasePointerCapture(e.pointerId); } catch { /* already released */ }
    });
    mmEl.addEventListener("pointercancel", () => { rulerDrag = false; mmGrab = -1; });
    mmEl.addEventListener("wheel", (e) => {
      if (!state.report) return;
      $("docpane").scrollTop += e.deltaY;
      e.preventDefault();
    }, { passive: false });
  }

  let pending = false;
  $("docpane").addEventListener("scroll", () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; layout(); });
  });
  window.addEventListener("resize", () => {
    placeStone();
    if (state.mode === "edit") growSource();
    syncSheet();
    layout();
  });
  if (narrow.addEventListener) narrow.addEventListener("change", placeStone);
  if (sheetMQ.addEventListener) sheetMQ.addEventListener("change", syncSheet);

  document.addEventListener("keydown", (e) => {
    if (e.defaultPrevented) return;
    const typing = e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLInputElement ||
      (e.target instanceof HTMLElement && e.target.isContentEditable);
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === "o") {
      e.preventDefault();
      if (!state.running) $("file").click();
      return;
    }
    if (typing) {
      if (mod && e.key === "Enter" && !state.running) {
        e.preventDefault();
        if (state.report) runAudit();
        else openFromFront();
      }
      return;
    }
    if (document.querySelector("dialog[open]")) return;
    if (!$("textmenu").hidden) {
      if (e.key === "Escape") {
        e.preventDefault();
        setTextMenu(false, true);
      }
      return;
    }
    if (!mod && !e.altKey && e.key.toLowerCase() === "e" && state.report && !state.running) {
      e.preventDefault();
      editVisibleBlock();
      return;
    }
    if (e.key === "Escape") {
      closeModeMenu();
      closeHeadingMenu();
      return;
    }
    if (e.key === "?") { e.preventDefault(); $("shortcuts").showModal(); return; }
    if (e.key === "[") { e.preventDefault(); stepProblem(-1); return; }
    if (e.key === "]") { e.preventDefault(); stepProblem(1); return; }
    if (e.key.toLowerCase() === "j") { e.preventDefault(); stepCard(1); return; }
    if (e.key.toLowerCase() === "k") { e.preventDefault(); stepCard(-1); return; }
    if (e.key.toLowerCase() === "g") { e.preventDefault(); $("docpane").scrollTo({ top: 0, behavior: motion() }); }
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
  initTextSize();
  bindEvents();
  updateCount();
  setMatchedVisible(!state.hideOk);
  showFront(false);
  applyModeUI();
  placeStone();
  syncSheet();
  layout();
}

init();
