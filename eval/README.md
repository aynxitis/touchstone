# Challenge suite (development set)

`eval/challenge/` is a synthetic, 80-claim challenge suite: four hand-made reports
(`report1.txt`..`report4.txt`, 20 lines each) citing mostly Wikipedia pages, with claims
deliberately altered to hit one failure mode each (rounding, qualifiers, wrong year, table
column mix-ups, wrong entity, French pages, unit conversion, opinion, bare homepage, 404,
no link...). `touchstone-answer-key.csv` holds the expected label, acceptable alternatives,
the exact page sentence and what was changed.

It is a **development set**: fixing the engine against it is allowed, so its pass rate is
not a real-world accuracy figure. Real accuracy comes only from fresh reports with fresh
labels (see CLAUDE.md, "held-out accuracy set").

Files:
- `run1_reportN.json`: the 16 Oct 2026 production run (web "Download results").
- `touchstone-run1-scored.csv`: the hand scoring of run 1 (56/80).
- `run2_reportN.json`: the Gemini CLI run after the fixes of 16 Oct 2026 (71/80).
- `run2r_reportN.json`: run 2's model replies re-scored with the final code (`rescore.py --out`,
  zero tokens; 72/80).

## Run

Spends Gemini quota (one call per cited page per 10 claims):

    PROVIDER=gemini .venv/bin/python quote_check.py eval/challenge/report1.txt --provider gemini \
        --max-claims 25 --cache eval/challenge/report1.pages.json --out eval/challenge/run2_report1.json

The `*.pages.json` caches are copies of other sites' pages: gitignored, never commit them.
Delete a cache to refetch the live pages.

## Score

    .venv/bin/python eval/score.py eval/challenge/run2_report{1,2,3,4}.json [--csv out.csv]

Claims are matched to answer-key rows by claim text + URL, not by claim number (numbering
skips uncited lines; no-link claims are in the run's "uncited" list). It prints each claim,
the pass rate overall and per category, FALSE SOURCED (SOURCED where the key expects
anything else), FALSE RED (CONTRADICTED where SOURCED/PARTIAL is expected) and safe misses
(amber where green or red was expected). It exits 1 if any claim is false SOURCED: that
count must stay 0.

To measure a code-check change without tokens, re-score a saved run instead
(`rescore.py RUN.json --cache eval/challenge/reportN.pages.json --out NEW.json`) and score NEW.json.
