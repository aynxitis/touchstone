# Touchstone — landing page

The public page for Touchstone, rebuilt from the design export in
`human/Landing page-html/` to live in the app's own visual world.

Plain HTML, CSS and about 30 lines of JS. No framework, no dependency, no build
step, no external request: the faces are self-hosted and every screenshot is
local.

## View it

    cd landing
    python -m http.server 8032

Then open <http://127.0.0.1:8032/>. It also works from any static host as-is.

## What is where

| File | What it is |
| --- | --- |
| `index.html` | The page. One document, seven sections. |
| `landing.css` | Layout, type, the app's marks, motion, breakpoints. |
| `tokens.css` | The app's light-world tokens, copied from `../static/style.css :root`. |
| `landing.js` | Reveal fallback for engines without scroll-driven animation, and the gold progress rule. |
| `fonts/` | Archivo and Newsreader (self-hosted, OFL; licences beside them). |
| `shots/` | The app screenshots the page shows, plus `src/` with the full captures they were cropped from. |
| `favicon.svg` | The app's own favicon. |

## The design system is the app's

`tokens.css` is a copy of the light-world half of `../static/style.css :root` —
paper, desk, ink, graphite, gold, the five verdict marks. **`static/style.css` is
the source of truth.** If a token changes in the app, change it here in the same
commit, or the page starts drifting from the product it describes.

The page deliberately has **no theme switch**. The app's default world is light,
so the page is light; the only graphite is the top bar and the two bands that
frame the story.

## Screenshots are real

Every image comes from the running app, replaying the saved example
(`examples/demo_run.json`) — zero tokens, no model call:

| Asset | Source |
| --- | --- |
| `app-results` | 1440×900, the whole review screen after the replay |
| `app-card` | the contradicted claim card, captured as its own element |
| `app-card-phone` | the same card as the 390 layout renders it |
| `app-table` | the report's brand table with the red margin mark |
| `app-phone` | the 390×844 screen |

`shots/src/` holds the untouched captures. To redo them, run the app locally and
re-run the capture script (kept outside the repo, in
`_temp/touchstone-ui/landing-capture*.mjs`):

    cd .. && .venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8031
    node _temp/touchstone-ui/landing-capture.mjs

The card is a 2× capture of a 412px-wide element, so it is shown at 412–436px
CSS and never scaled up. Below 700px the figures switch to the phone captures
through `<picture>` — a 1440 capture squeezed into 350px is unreadable, which is
the whole reason those variants exist.

## Motion

One authored moment: the gold hairline in the evidence section draws itself as
you scroll. Everything else is a single reveal (16px rise, 520ms, once).

- Scroll-driven (`animation-timeline: view()`) where the engine supports it, so
  the reveal scrubs with the scroll rather than firing on a timer.
- Elsewhere `landing.js` adds `motion-fallback` and one `IntersectionObserver`
  does the same job once per element.
- Without JS the page is fully visible — nothing is hidden by default.
- `prefers-reduced-motion: reduce` removes every transform and leaves all
  content visible.

## Checks that were run

- Impeccable detector: 0 findings at 1440×900, 768×1024 and 390×844.
- Contrast measured from the rendered colours: lowest 6.2:1 for body text,
  5.0:1 for captions — no sampled pair under 4.5:1.
- Keyboard pass with visible focus rings, skip link first.
- No horizontal overflow at any of the three widths.
- `check-evidence.js` passes on the rendered record (kept outside the repo, in
  the vault's `_temp/landing-evidence/`, with the screenshots it cites).
