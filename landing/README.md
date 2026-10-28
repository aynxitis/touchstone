# Touchstone — landing page

The public page for Touchstone, built from the design export in
`human/Landing page-html/` to live in the app's own visual world. It is served at
`/`; the product itself is at `/app`.

Plain HTML, CSS and one script. No framework, no build step, no external request:
the faces are self-hosted, the motion engine is vendored, and **there are no
screenshots** — the example on the page is the app's own card, rendered live.

## View it

    cd .. && python dev.py

Then open <http://127.0.0.1:8031/>. `dev.py` bootstraps a `.venv` on first run,
starts `uvicorn app:app` on 8031, and reloads on edits to `app.py`, `static/` or
`landing/`. It never creates `.env`.

Any static host works too, because the page has no server dependency:

    python -m http.server 8032        # inside landing/

The one difference is the embedded copy of the saved run (below): on the app the
page fetches `/api/example-run`, on a file server it uses the copy in
`landing.js`. Both are the same record.

## What is where

| File | What it is |
| --- | --- |
| `index.html` | The page. One document: hero, example, problem, check, verdicts, limits, close, footer. |
| `privacy.html` | Privacy policy. Same shell and tokens, prose in `.legal`. |
| `terms.html` | Terms of service. Same shell and tokens, prose in `.legal`. |
| `error.html` | The error page: a giant number, one plain sentence, two ways back. Served by `app.py` for 404/500. |
| `landing.css` | Layout, type, the app's card, the graphite bands, breakpoints, legal prose. |
| `error.css` | Only the error page's layout: no script, no inline style, so it renders under the app's CSP. |
| `tokens.css` | The app's light-world tokens, copied from `../static/style.css :root`. |
| `landing.js` | The live example, the three-stage check, the reveals, the limits count-up. |
| `vendor/` | Motion 14.6.0 (UMD, MIT) and its licence. `window.Motion`, no package manager. |
| `fonts/` | Archivo and Newsreader (self-hosted, OFL; licences beside them). |
| `favicon.svg` | The favicon — the gem mark, same file as `logo.svg`. |
| `logo.svg` | The gem mark, full colour. Navbar, footer and favicon — the app's topbar wordmark uses `/static/logo.svg`, the same drawing. |
| `logo-app.svg` | The app icon (the gem on its rounded tile). Fronts the close CTA. |

## The design system is the app's

`tokens.css` is a copy of the light-world half of `../static/style.css :root` —
paper, desk, ink, graphite, gold, the verdict colours. **`static/style.css` is the
source of truth.** If a token changes in the app, change it here in the same
commit, or the page starts drifting from the product it describes.

The page deliberately has **no theme switch**. The app's default world is light, so
the page is light; the graphite is the top bar, the two bands (problem, verdicts)
and the check's step cards. Chrome stays monochrome + gold. The app's verdict
colours appear where a verdict is shown or explained: the live card's badges and
dots, the report's margin marks, the verdict key's four dots, and the "Other
outcomes" dots. They are the app's own on-graphite tokens (`--ok-on`,
`--warn-on`, `--fail-on`, `--brown-on`, `--blue-on`, `--violet-on`), not invented
traffic-light hues, so the key and the product cannot disagree.

The legal pages reuse the same tokens and shell: paper prose, graphite footer,
a back link in the nav.

## The example is the product's own card

No image is involved. `landing.js` builds the report rows and the verdict card from
`examples/demo_run.json` — the same saved run the app replays — reusing the app's
own class names (`.card`, `.badge.tone-*`, `.cno`, `.claim`, `.diff`, `.parts`,
`.tag`, `.quote`, `.part-note`, `.source`, `.rejected`, `.counts`, `.cnt`, `.dot`).
So a change to the app's card markup shows up here as a diff, not as a stale
picture.

It is interactive:

- clicking a report row or a table row shows that claim's card;
- clicking **5 sourced / 1 unsupported / 1 contradicted** jumps to an example of
  that verdict;
- **Replay** re-runs the scan line and the mark pops.

Zero tokens, no model call. The counts are painted from the record, never zeroed.

The panel reserves the height of its **tallest** card, so picking a shorter claim
does not drag every section below it up or down. `lockDemoHeight()` measures all
seven cards in a hidden, absolutely positioned probe inside `.result`, sets
`min-height`, and re-measures after the fetch, after fonts load, and on resize
(180ms debounce). The reservation is a fixed pixel height, not a guess per claim:
733px for the demo at 1440 (result 678px), 1560px at 390, constant across all
seven claims.

## The check is a scroll story

One claim (the Samsung Q2 share in the report) goes through three states as you
scroll:

1. **The page is opened** — the evidence is there but blurred, the badge says
   `Checking`, and the source line reads `opening tech-ish.com`. The claim's mark
   is still plain: the verdict has not been given.
2. **The quote is verified** — the evidence sharpens, the quote is readable, still
   unlabelled: no status tag, no strike-through.
3. **The label follows** — `CONTRADICTED`, in the app's red; only now do the
   claim's 19%, the page's 18%, the status tag, the strike-through and the note
   explaining the difference appear.

The steps are graphite cards with the number in Archivo (not the mono label face)
at up to 58px. At ≥1021px the story is two equal columns and every step card is
exactly the claim card's size: `lockStoryHeight()` measures `.story-card` and sets
`--story-h` on `.story`, so width and height match the card (544×379 at 1440).
Titles run 21–26px; body copy 16.5–17.5px at .66 opacity (.82 when current), not
the old grey-on-grey. Each card rises into place on its own `inView` trigger
(76px, 620ms), like a deck being dealt from below.

The card is sticky beside the steps at ≥1021px, so it stays put while the steps
advance. A stage changes when its step reaches a reading line 55% down the
viewport; the steps are also buttons, so keyboard users can pick one directly —
a click moves the page to that step's line too, so the next scroll cannot hand the
stage straight back. Below 1021px the steps come first and the card is the
conclusion: the label lands as the card enters, then the reader scrolls into the
finished verdict. The card's height does not change between stages — nothing jumps
when the label lands.

## The rest of the page

- **The problem** — heading and standfirst stack, left-aligned like every other
  band (no side-by-side grid); three cards, one per assistant, each with its real
  mark (Gemini, ChatGPT, Perplexity, inlined simple-icons paths) and Perplexity
  last. At rest all three are equal and medium-sized; hovering grows one to 1.035,
  dims the others to .975/.72 and gives the hovered card a thick gold edge
  (1px border + 2px inset ring). Below 900px they stack and the scaling is
  disabled. The Motion reveal's inline `transform`/`opacity` is cleared once the
  animation lands, so CSS owns the hover again.
- **The verdict key** — two columns, the app's four outcome dots (green, half
  amber, amber, red) and no invented descriptions. There is no full-width rule
  anywhere in the band: each row carries its own 1px bottom hairline, and on
  hover a 2px tick slides left-to-right along that line **in the hovered
  outcome's own colour** (green/half/yellow rows tick `--ok-on`/`--warn-on`, red
  rows tick `--fail-on` — mapped with `:has()` on the row's dot class), while the
  name shifts right 8px. "Other outcomes" is the same treatment: the app's dots
  (yellow, brown, blue, violet, grey, grey, and a hollow red error ring) beside
  larger labels, with every gloss removed, and the same per-row hairline +
  outcome-coloured sliding tick (yellow/brown/blue/violet/error mapped from the
  dot's `data-tone`).
- **The limits** — three large graphite cards on paper, each a proper card with
  the number top-left and the label bottom-left: numbers up to 132px, labels
  20–27px in sans (not footnote grey). The caveat belongs **inside** each card:
  a bold lead (Don't paste anything private / It checks the page, not the truth /
  Free, not commercial) and the sentence under it, as a `.spec-body` `<dd>`
  in the same `<dl>`. The only text that stays on the paper is the gloss —
  "Only the first ones, in report order, are checked." — as a `.spec-note`
  `<p>` after the `</dl>`. All three cards are `grid-row: span 4` items of one
  `.spec` grid using `grid-template-rows: subgrid` (number · air · label ·
  caveat), so the three labels and the three caveats share a row and none of
  them drifts (labels measured at 462/462/462 at 1440 and 367/367/367 at 1024;
  below 700px the cards stack, so each keeps its own baseline). JS adds
  `is-armed` (held left, invisible), then `is-in` on `inView`; CSS slides them
  in left-to-right with a 110ms stagger. The numbers go 0 → 25/8/5 over 1.5s
  on one shared clock, so all three stop together. Hover lifts a card 6px and
  draws a 3px gold inset ring plus a gold border; the entrance uses
  `animation-fill-mode: backwards`, so the animation does not hold an inline
  transform that would block the hover.
- **The close** — the close and the footer share one screen: `.endcap` is
  `min-height:100svh` and a column flex container, the close takes the free space
  and centres its content, the footer keeps its natural height at the bottom, so
  the page ends on a full panel (measured 750+150 = 900 at 1440×900,
  662+182 = 844 at 390×844). The verdict side-list is gone; the fine print is
  16.5px sans. The MCP endpoint is a button: gold on hover, click copies it, and
  the status says "Copied" for 1.6s (with a select-and-Ctrl+C fallback when the
  Clipboard API is unavailable).
- **Nav and footer** — the navbar shows the gem mark and "Touchstone" (the brand
  links back to the landing page itself, `./`, not to the app; the old
  "Prototype" chip is gone). Below 700px the section links collapse into a
  hamburger: a real `<button>` toggled by JS (`html.js` gates the collapse), the
  panel drops flush under the bar, and Escape or picking a link closes it — and
  with JS off the links simply stay visible (wrapped under the brand), so
  navigation never depends on the script. Section links (and back-to-top) scroll
  smoothly, gated behind `prefers-reduced-motion`. The nav CTA is paper-white and
  turns gold on hover; "See how it works" keeps one grey hairline at rest that
  simply turns gold and thickens (1px -> 2px) on hover — no slide, no second
  line. The gem and the name share one optical centre: Newsreader's
  line box carries descent space the glyphs don't use ("Touchstone" has no
  descenders), so plain box-centring left the gem 2.5px low — both navbar and
  footer nudge the gem up 2.5px to the name's ink centre (measured, delta 0
  after). The close CTA is fronted by `logo-app.svg`, sized by viewport height
  (`clamp(120px,20vh,200px)`; the close's vertical air is `clamp(40px,10svh,88px)`
  so a short window gives back padding before the icon shrinks), so endcap +
  footer still fill exactly one viewport (measured 900/720/844 with the logo at
  180/144/169px wide). The footer repeats the gem + wordmark like the navbar.
  In the app itself the topbar wordmark now carries `/static/logo.svg` and links
  to `/` — the way home, not a self-link — and it is set in the **same face as
  the landing navbar**: Newsreader 22px/400 (was Archivo 20px/600), with the
  gem at 26px and the same 2.5px optical nudge, so the brand mark is identical
  on both surfaces. The app's UI-scale feature keeps working off the same base
  (`calc(22px * var(--ui))`).
  The footer is a graphite band: serif wordmark, `© 2026 Touchstone · Built in
  the Thirduni program`, privacy and terms links, and a white "Open the app" button. Both
  legal pages are ordinary files served from the landing root, so they work on
  the app and on a plain static host.

## A dead end looks like the product

`error.html` + `error.css` are the 404/500 page, and the shell is the landing
page's own — the same `<header class="bar">` (gem, section links, Open-the-app
button, hamburger), the same `<footer class="foot">`, the same `landing.css` —
so a dead end is unmistakably Touchstone. Between them, one centred stack: the
code itself in Newsreader and the page's own gold (`--gold`), at
`clamp(128px, 23vw, 330px)` (330px at 1440, 132.6px at 390); then a plain
sentence — "This page doesn't exist. / The link may be old, or the page may have
moved." — and two buttons in the landing's vocabulary (an ink `.btn` back to the
landing page, a quiet `.link` to the app).

The three parts fill **exactly one viewport** — `height:100svh` (not
min-height), bar at the top, footer at the bottom, the stack centred in the
middle by `margin:auto`. Below 820px of height the number yields first, with
the fit solved exactly: `0.8 × font ≤ svh − (bar + footer + non-code stack +
padding)`, written as `clamp(112px, min(23vw, calc((100svh - 538px)/0.8)),
330px)` — so the stack stays dead-centred down to ~660px-tall windows instead
of overflowing. In a window too short to fit the stack at all (a 420px-tall
one), `margin:auto` falls back to start alignment and the middle region scrolls
its content internally: the page itself still never scrolls, and nothing is
unreachable. Measured at 1440×900, 1280×720, 390×844, 500×420: scrollHeight
equals innerHeight everywhere, deltas 0.

`app.py` wires it up: `error_page(code)` reads `error.html` per request and
replaces the `<!--code-->`, `<!--title-->`, `<!--line-->` runs from `ERROR_COPY`,
so the page can change without a restart. `StarletteHTTPException` handler: a
404/405/500 for a page a person can land on gets the HTML; anything under
`/api/`, `/mcp`, `/healthz`, `/static/`, `/fonts/`, `/vendor/` falls through to
Starlette's own handler, so JSON stays JSON and `GET /mcp` keeps its
`405 · Allow: POST`. An unhandled exception gets the 500 copy and is logged. `/error`
(e.g. `/error?code=500`) previews the page as a 200 without breaking a link first.

`landing.js` is deliberately **not** loaded on this page: it binds `#report`,
`#counts` and friends, which don't exist here, and would throw on load. The
shell's one behaviour — `js` marker + hamburger (click, Escape, link-click
close) — lives in a tiny `error.js` that mirrors `landing.js`'s burger block.
No-JS is fine: the section links simply stay visible.

The page uses no inline style or script — only `/tokens.css`, `/landing.css` and
`/error.css` — so it renders under the app's `style-src 'self'` CSP whether it
came from the app or from a static host. The URLs are absolute for the same
reason the page can be served at any path: a 404 at `/foo/bar` must still find
its stylesheet.

## Motion

Motion 14.6.0 (the engine behind Framer Motion, vendored as a UMD build) does the
timing: the reveal pass, the scan line, the mark pops, the card fade.

- **One authored loop, then it walks.** The example plays once when it scrolls
  into view (scan line, mark pops, card fade), then auto-advances claim by claim
  in report order, every 3.2s, looping. It pauses while the panel is off-screen
  and resumes when it returns; any pointer or keyboard interaction stops it for
  good, except the Replay button, which re-arms the walk. `prefers-reduced-motion`
  skips the whole thing and shows the static card (claim 3).
- **Reveals are one gesture.** 14px rise, 550ms, once per element, `inView` driven.
  The hero plays on load because it is already on screen. Two exceptions carry the
  section's meaning: the findings cards rise 18px and then release their inline
  transform to CSS, and each step card rises 76px on its own trigger. The limits
  are CSS-owned after a JS arm (`is-armed` → `is-in`) so the staggered slide-in
  cannot fight the hover lift.
- **One drawn line.** The gold rule under "source" is a 5px dash rule built from
  percentage tiles (`background-size:10% 5px`, each tile's dash running 0–72%),
  so the run always ends on a full dash — no clipped fragment hanging off the
  right edge on narrow screens — revealed by a `scaleX` keyframe (0.85s, 450ms
  delay) on the hero's load, not a scroll effect; under reduced motion it stays
  fully drawn.
- **Without JS the page still reads.** The report, the 5/1/1 counts, the verdict copy
  and every section are static; each card slot says the card is rendered live, with a
  link to the app. The two cards themselves need the script. A failed `motion.js`
  request leaves the page readable rather than blank.
- **`prefers-reduced-motion: reduce`** skips the animation entirely: counts and
  marks are set, all three stages of the story are visible, nothing is hidden.
- If an animation is cancelled mid-play the panel is still filled: the card render
  happens whether or not the scan line finishes, so a rejected animation can never
  leave the example empty.

## Checks that were run

- Behaviour, in headless Edge at 1440×900 (Puppeteer, kept outside the repo in the
  vault's `_temp/touchstone-ui/`): Motion present, counts 5/1/1, summary line
  correct, row click switches the card, count click switches it back, story stages
  1→2→3 with the right captions and badges, reduced-motion shows everything, zero
  console errors and zero failed requests.
- The design-review pass measured the requested states, not just eyeballed them:
  nav CTA `rgb(240,240,237)` → gold `rgb(201,162,39)`; the link's gold rule
  `matrix(0,…)` → `matrix(1,…)`; the headline rule is 5px tall, tiled at
  `10% 5px` with each tile's dash running 0–72%, so it ends on a full dash at
  every width;
  the eyebrow ends in ", no sign-up" and the old hero fine print is gone.
- The example measured 733px (result 678px) at 1440 and 1560px at 390, the same
  for all seven claims; no card overflowed its reserved area.
- Findings order Gemini → ChatGPT → Perplexity, three 22px marks; hover is
  `scale(1.035)` with siblings at `.975` and opacity `.72`; the hovered card gets
  `border-color: rgb(201,162,39)` and a 2px inset gold ring, all three `none` at
  rest. The dark step cards measured `rgb(35,36,39)`, a 58px Archivo number,
  14px gaps, and **exactly the claim card's 544×379** (all three 544×379, inside
  a 544px column); titles 26px, body 17.5px at `.82` when current. The key's dots
  measured the app's green/amber/red, and "Other outcomes" renders seven labels
  with no descriptions and the app's yellow/brown/blue/violet/grey/error dots.
  The limits landed on 25/8/5 in cards 372×404, with a 27px label and a 129.6px
  number; hover moved `translateY(-6px)` and drew a 3px gold inset ring. The gold
  close button turned `rgb(23,24,26)` on hover; the MCP URL turned gold, and a
  click put `touchstone.aynx.dev/mcp` on the clipboard with "Copied" shown.
- The story's geometry was measured at 1440×900, 1024×800 and 390×844: every
  stage starts with its step title on screen. At 1440 the pinned card is 379px
  and stages 2 and 3 each hold for ≈390px of scroll; at 1024 the card is 398px
  with a ≈355px stage-3 hold. On a phone the steps come first (216px each, not
  forced to the card height) and the card is fully labelled by the time it is in
  view; its settled height there is 415px.
- Viewport captures were taken at 1440 and 390 after scrolling the page, since the
  reveals start at `opacity: 0`; no horizontal overflow at any width, and the
  privacy and terms pages fit both widths.
- With scripting disabled, the page still reads: counts 5/1/1, the report's verdict
  marks are coloured, and each card slot says the card is rendered live with a link to
  the app.
- `test_security.py` covers `/`, the root files (including the legal pages and
  `error.css`), `/fonts/*` and `/vendor/motion.js`: 200 with `no-cache`, the legal
  pages' text is asserted, and `/README.md` stays private.
- The error page was measured at 1440×900 and 390×844: a 330px / 132.6px
  Newsreader number, a 58px / 28.9px heading, no page scroll, no console error,
  `text/html` at 404 with `no-cache`, `/api/nope` still `application/json`, and
  `/mcp` still 404 JSON on its own (405 + `Allow: POST` with MCP enabled, per
  `test_mcp.py`).
- The limits note was measured inside the first card at all three widths (card
  background `rgb(26,27,29)`, note bottom 37px / 30px / 25px above the card's
  edge), and the three labels share one baseline at 1440 and 1024 (462/462/462,
  367/367/367) with the note on the shared row below the first one.
- The brand round (headless Edge, fresh profile, cache off): the navbar gem is
  26px tall and the brand links `./`, no `Prototype` chip anywhere; the burger
  is hidden at 1440 and shown at 390 — open panel flush under the bar
  (panel top 64 vs bar bottom 65), `aria-expanded` flips, picking a link closes
  it, Escape closes it, and with JS disabled the three section links stay
  visible on mobile. The dash rule reports `background-size: 10% 5px`. The link
  hover shows one line: grey 1px at rest, gold 2px on hover (border-bottom
  colour + width). Endcap + footer sum 900/720/844 at the three viewports with
  the close logo at 180/144/169px wide and no content overflow (the lap height
  needed the close's air to go from `7vw` to `10svh` — 747 → 720 at 1280×720).
  The gem's centre and the wordmark's ink centre measure equal (delta 0) in the
  navbar, the footer and the app topbar at 1440 and 390. `/favicon.svg`
  is the gem (200), `/logo.svg` and `/logo-app.svg` serve 200, and the app's
  wordmark reports `href="/"`, Newsreader, 26px gem, 22px text. `verify-landing`,
  `check-nojs` and `check-static` all ended with zero console errors and zero
  failed requests; `test_security.py` passes offline (the app index now links
  3 versioned refs: style.css, app.js, logo.svg) and `test_mcp.py` passes.
