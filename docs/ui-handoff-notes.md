# UI and quote book: development and hand-off notes

Status: draft PR `UI` -> `main`. Not merged; merging is pending explicit confirmation because it replaces the
three-view workbench frontend (Market, Deal economics, Inventory) described in [demo-sprint.md](demo-sprint.md).

## Goal and decisions

- A 2-4 minute public demo. Flow: **Brief -> Overview -> Quotes -> Pricing**. The earlier advanced pages stay
  reachable under **More**.
- Keep this flow in the public repo; the frontend lives on branch `UI`, everything is meant to reach `main` cleanly.
- The data is a **locally simulated quote book**: 28 providers and about 150 live quotes (153 at the starting tick,
  78 eligible), modelled on the Senthos mock provider and quote workbook v1.3. Cost of capital and failure
  probabilities are the workbook's own placeholders. Reference indexes are on-demand.
- One disclosure only: the footer line "Simulated data, generated locally. Indicative only; nothing here executes a
  trade." The API also carries `simulated: true` and `execution_enabled: false`. No claim of real market data.
- Nothing shipped may mention the two individuals named in the scrub rule (checked case-insensitively over the tree,
  the diff and commit messages).

## Architecture

Backend, package `compute_pricing/control/quote_book/`:

| File | Owns |
| --- | --- |
| `seed.py` | Generated from the workbook by `scripts/gen_quote_book_seed.py` (12 source providers, 38 source quotes, hashes). The workbook itself is not committed; `--check` does not need it. |
| `scoring.py` | Port of the workbook formulas: scorecard weights (certification .15, facility .15, SLA .20, delivery .15, credit .05, responsiveness .30), grades A>=85 / B>=70 / C>=55 / D, financing = price x 0.12 x down payment x months/24, failure probability = 1-(1-p)^(months/12), eligibility and basis. |
| `population.py` | Expands the seed to the 28-provider, ~150-quote population. |
| `market.py` | `QuoteBook`: deterministic simulator (`Random(f"{seed}:{tick}")`), wall-clock driven (3 s = 30 simulated minutes, catch-up capped at 12 steps, 90 warm-up steps), scenarios `price_war`, `supply_shock`, `downgrade`, controls `pause`, `resume`, `reset`. Process memory only. |

Routes (`api/quote_book.py`, registered directly on the app, not via a router, because route-iterating tests
need `.path`):

- `GET /v1/book` returns the snapshot, with a weak ETag `W/"book-{epoch}-{tick}-{version}"` and `304` on match.
- `POST /v1/book/control` takes `{action, scenario?}`. Session scope `book`; cookie session plus `X-Compute-CSRF`;
  `422 invalid_book_control` on bad input. Both are authenticated. The unknown-POST guard is unchanged.
- Two small additive edits elsewhere: `attach_quote_book(...)` in `api/app.py` and the `book` scope in
  `api/sessions.py`.

Frontend, `src/compute_pricing/control/workbench/assets/`:

- `index.html`: Brief, Overview, Quotes, Pricing, and the More menu holding the advanced pages.
- `workbench.js`: API client and session handling (cookie session, CSRF, `If-None-Match` support), the advanced
  pages, and `window.ComputeHost` (`api`, `element`, `byId`, `notify`, `showView`, `priceQuote`, `isSession`,
  `onView`, `onSession`). `loadIndex` keeps using `/v1/market/index`.
- `demo-core.js`, `page-brief.js`, `page-overview.js`, `page-quotes.js`: Brief, Overview and Quotes (see `frontend-architecture.md`). The core polls `GET /v1/book` every 2 s (conditional request, pauses
  when the tab is hidden), sends scenario controls, paints the status pill, keeps flags for recent scenario alerts
  in an in-memory client store.
- `workbench-charts.js`: SVG primitives built with `createElementNS` (sparkline, line chart, stacked bars, columns,
  bars, legend, ticks). The Brief draws its own `briefBars` inside `page-brief.js`. Colour only arrives through
  CSS classes (`--gc`).
- `workbench-drafts.js`: the structural request editors used by the advanced pages (unchanged behaviour).
- `workbench.css`, `favicon.svg`.

Pricing handoff: `priceQuote(quote)` switches to Pricing and loads the labelled synthetic example into the
**editor only**. Only `commercial.supplier_ask` is replaced with the quote's price. It never evaluates or saves
automatically (evaluation persists a snapshot and applies provenance rules).

Constraints enforced by tests: strict CSP (no inline style or script, no `innerHTML`, `localStorage`, `eval`, or
`setAttribute("style")`); every `byId("x")` id must exist in `index.html`; light, dark and system-mirror theme
tokens must stay in parity.

## Status

Done:

- Frontend ported onto the public lineage; endpoints renamed to `/v1/book` and `/v1/book/control` (JS and JS tests).
- Pricing handoff ported (`priceQuote`, `loadPricingExample`).
- Expected-loss colour now uses the existing warm `--warn` token (defined in light, dark and system-mirror).
- Dead code removed: `dumbbellFor`, `dumbbellLegend`, `costBars`, `costLegend` in the demo scripts;
  CSS `.swatch.dot-best-swatch`, `.swatch.ref-swatch`.
- Brief step 3: added space under the stat value (`.bf-steps .bf-stat-text`). **Not verified in a browser.**
- Docs: this file, plus a link from [quote-book.md](quote-book.md).

Not done:

- Browser walk-through on the public build (the flow was exercised in a browser on a private build before the
  port; the ported build has only had Node and Python tests).
- Remaining dead code: `ComputeCharts.dumbbell`, `ComputeCharts.scatter` and their tests, and CSS `.ch-track`,
  `.ch-connect`, `.ch-gap-label`, `.dot-cheap`, `.dot-best`, `.ch-ref`, `.ch-bubble`, `.ch-zero` (confirm with `rg`
  first; the only other `ch-ref` hit is inside the word "workbench-reference").
- Automated test that the handoff packet is accepted by the real `evaluate_pricing` (checked by hand earlier:
  status `indicative`, `firm_price_eligible: false`, sell floor scales with the supplier ask).
- `docs/interface-design.md` not updated for the new flow.
- Mutation spot-checks on the public tree; one known gap: the reset/epoch test in `workbench_demo.test.js` did not
  catch a mutant that disabled epoch tracking.
- Two wording edits from the replaced frontend ("unspecified term" instead of "no reserved tenor", two places in
  `workbench.js`) were not carried over.

Validation on the current tree:

- `scripts/validate.py`: passed (764 tests, 3 skipped; contract drift, doc links, ruff, CLI examples).
- Oracle tests: 43 tests passed across the five `test_quote_book_*` modules with
  `QUOTE_BOOK_WORKBOOK=<path to the v1.3 workbook>`; they skip without it.
- `node --check` clean on all assets and JS tests. Scrub: no banned names in the tree or commit messages; no
  stores, screenshots, workbook files, backups, or local paths.

Frontend tests replaced or adapted: `tests/workbench_behavior.test.js` was replaced by the version matching this
frontend (it previously also covered the Market and Deal economics views); one assertion in
`tests/test_workbench_v2.py` now expects `api("/v1/market/index"` instead of `api("/v1/demo/market"`. New:
`tests/workbench_demo.test.js` with `tests/test_quote_book_frontend.py`.

## Demo script (2-4 minutes)

1. Brief: the problem statement (headline price versus all-in cost, blank terms, weakest sellers cheapest).
2. Overview: scale (providers, quotes, GPUs), eligibility and basis, provider health.
3. Press **Price war**, then **Supply shock**; watch the alerts and the basis move. **Reset** returns to the start.
4. Quotes: sort, select a quote, open the cost breakdown.
5. **Price this quote** loads the editor on Pricing; press **Evaluate** to see the bid ceiling and sell floor.

Run it locally per the runbook in [demo-sprint.md](demo-sprint.md) (`scripts/local.py start ... --port 8002`).

## Known rough edges

- The Brief is about 6000 px tall at 390 px wide.
- The Provider health table scrolls horizontally at 390 px.
- The Supply shock effect on the best-eligible line is small.
- Scenario flags live in an in-memory client store for about 4.5 minutes, and are lost on reload once the alert
  has left the 40-item feed.
- The simulator is process memory only: restarting the server resets the book.

## Conflict map with the concurrent three-view frontend

- Replaced (our flow wins): `workbench/assets/index.html`, `workbench.css`, `workbench.js`, `workbench-drafts.js`
  (Market, Deal economics, Inventory views, commitment-curve UI, `loadDemoContract`, the demo scenario form).
- Added: the demo scripts, `workbench-charts.js`, `favicon.svg`.
- Preserved untouched: `workbench/routes.py`, `synthetic-pricing-request.json`, `synthetic-policy-document.json`,
  `world-land.json`, all backend routes (`/v1/demo/market`, `/v1/demo/contract`, `POST /v1/demo/scenario`,
  `api/demo.py`), all other tests and docs. Those `/v1/demo/*` routes remain but the frontend no longer calls them.
- Two-line additive edits: `api/app.py` (`attach_quote_book`), `api/sessions.py` (`book` scope).
- [demo-sprint.md](demo-sprint.md) still describes the replaced three-view UI; it needs a follow-up once the merge
  is approved.

Merge, once approved: `gh pr merge <PR number> --repo tharune/computebasis --merge`

## Next steps, in priority order

1. If `origin/main` has moved, rebase `UI` (no force-push to `main`) and re-run `scripts/validate.py`.
2. Browser walk-through on the public build on port 8002 per the runbook: Brief, Overview, Price war and Supply
   shock, Quotes, Price this quote, Evaluate; each More page once; check console errors.
3. Light-mode and 390 px sweeps of the lower Brief sections; check the step 3 spacing and the expected-loss colour.
4. Finish the dead-code removal listed above; add the `evaluate_pricing` handoff test; strengthen the reset test.
5. Update `docs/interface-design.md` and the stale parts of `docs/demo-sprint.md`.
6. After user approval, merge the PR, then delete the scratch `quote-book` branch if redundant (`UI` contains it).

## Pointers

The original uncommitted source of this UI, a preview server, a scratch store copy and screenshots exist only on
the author's machine and are not part of this repository; see the hand-off message for their locations.
