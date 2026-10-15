# Frontend architecture (Brief, Overview, Quotes, Pricing)

The workbench is static HTML, CSS and vanilla JavaScript in `src/compute_pricing/control/workbench/assets/`, served by FastAPI under a strict
CSP (`default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self'; connect-src 'self'`). So: no inline script
or style, no `innerHTML`, no `eval`, no `localStorage`, nothing from another origin, and nothing in a script may touch `.style`. Colour and
size reach the page only through CSS classes and SVG attributes. `docs/interface-design.md` is the design system (type, colour, charts,
motion, honesty); read it before drawing anything.

## One document, two pages

`html[data-page="landing"|"app"]` is set by `route.js` before first paint and by `showView`. The landing page is the `brief` view; the
app is `desk` (Overview), `quotes` and `pricing`. Hash routes (`/#desk`, `/#quotes`, `/#pricing`) drive it; any other hash opens the
landing page. `VIEWS` in `workbench.js` and the `APP` pattern in `route.js` list the same app pages, and a test holds them together.

## Files and who owns what

| File | Role |
| --- | --- |
| `book-adapter.js` | The only place that knows the wire shape. `normalizeBook` (`GET /v1/book`) and `normalizeDesk` (`GET /v1/book/desk`). |
| `demo-core.js` | Polling, `state`, helpers (`h`, `usd`, `pct`, `chip`, `fit`, ...), scenario controls, page registry. Exposes `window.ComputeDemo`. |
| `page-brief.js` | Landing page (Brief). |
| `page-overview.js`, `overview.css` | Overview: positions, brokered bids, market state, capacity. |
| `us-states.js`, `us-map.js`, `map.css` | The US capacity map component, `window.ComputeMap`. |
| `page-quotes.js`, `quotes.css` | Quotes. |
| `workbench-charts.js` | Shared SVG chart primitives. Change it only with the owner of the charts. |
| `landing-data.js`, `landing.css` | Landing-only derivations and styles. |
| `workbench.js` | The host: session bootstrap and CSRF, `api`, theme, routing, and `window.ComputeHost` (`api`, `byId`, `notify`, `showView`, `priceQuote`, `isSession`, `onView`, `onSession`). `priceQuote` is the Quotes-to-Pricing handoff (below). |
| `workbench.css` | The shared tokens, shell, controls and the grade and chart classes. |
| `route.js` | Runs before first paint so a reload on an app address never flashes the landing page. |
| `pricing-demo.js`, `pricing-demo-fields.js`, `pricing-demo-charts.js`, `pricing-demo-view.js`, `pricing-demo-app.js`, `pricing-demo.css` | Pricing: the example contracts, the editable terms, the assessment dialog (`/v1/pricing/demo/*`). The only owner of the Pricing form; it takes a quote through `ComputePricingDemo.loadQuote`. |

A page file is one IIFE: read helpers from `window.ComputeDemo`, draw into the elements `index.html` gives it, and end with
`ComputeDemo.register("desk", { render, resize: true })`. `render` is called on every new book, every view switch and (if `resize`) on
resize, so it must be idempotent and must cope with `state.data === null` (not loaded yet, or the server said no).

New script or stylesheet files go on their own line in the `<head>` of `index.html`; a name that starts `page-`, `us-` or `desk-` is
picked up by the test harness automatically. Put page styles in the page's own CSS file, reuse the tokens in `workbench.css`
(`--border`, `--surface`, `--text`, `--muted`, grade colours `--g-a`..), and give both themes a value for every colour you add.

## Handoff: Quotes to Pricing

**Price this quote** calls `ComputeHost.priceQuote(quote)` with the normalised quote and its exact price string. The host shows Pricing and
returns `ComputePricingDemo.loadQuote(quote)`, a `Promise<boolean>`: `true` when the form was filled now, `false` when the quote was queued
(no session yet, contract not loaded, an evaluation running) or rejected (no usable price). Pricing applies a queued quote the moment it can.
The quote's price becomes the fixed supplier ask, its GPU the hardware model and its stated down payment the supplier deposit; every other
term comes from the backend's invented example, and the form says so. Nothing is evaluated or saved until the person presses **Evaluate
contract**. If the Pricing scripts are missing the host says so in the notice bar.

## Data: what the pages may rely on

Pages read `ComputeDemo.state.data` (the normalised book) and `state.desk` (the normalised desk ledger, `null` until read or if it
cannot be). Never read the raw response.

- Money, rates and ratios arrive as exact decimal strings. The adapter turns them into numbers for drawing and keeps the exact text on
  `quote.exact` (and `position.exact`, `bid.exact`, `desk.summary.exact`). Print exact strings (or numbers rounded for display) in
  labels and tooltips; use the float only for geometry. Do not add a second pricing model in the page: if a figure is missing, ask the
  backend for it.
- A grade is `A`..`D`, or `U` for an unrated seller. `U` is never counted as a grade and never coloured as one.
- A quote's `missing` is the list of key terms it leaves out; `reason_codes` and the readable `reasons` say why it is not eligible
  (`contract start has passed`, `quote has expired`, `no down payment stated`, ...). `quote.ref` is the short label (`Q0149`) to
  print; `quote.id` is the key.
- A figure the server does not know is `null`. Draw "—" or say why, never `NaN`, `$NaN`, `undefined` or `0`.
- The book is simulated: every page says so, and nothing is executable (`execution_enabled: false`).
- The desk ledger is specified in `desk-ledger-contract.md`.

## Tests and checks

- `python -m unittest tests.test_quote_book_frontend` runs every `tests/workbench_*.test.js` (except `workbench_behavior`) against real
  simulator snapshots in a fake DOM. `tests/demo_harness.js` is the shared harness: `makePage(snapshot, { desk })`, `findAll`, `byClass`,
  `assertClean` (fails on `NaN`/`undefined` in text or attributes), `book` (normalised snapshots) and `deskFixture`
  (`tests/fixtures/desk-ledger.json`). Add a `tests/workbench_<page>.test.js` for your page.
- `node --test tests/workbench_behavior.test.js` (with `COMPUTEBASIS_WORKBENCH_ASSETS` set to the assets directory) covers the host script:
  session and CSRF handling, routing, scroll, theme, titles and the Quotes-to-Pricing handoff.
- `python scripts/validate.py` is the full offline gate. Run it before you hand work back.
- Look at it. The tests do not see layout. Serve with `python scripts/serve.py --store <path outside the repo>/decisions.sqlite --port <p>
  --no-auto-refresh`, open it in Playwright (Chromium is installed; `require('/opt/node-tools/node_modules/playwright')`,
  `executablePath: '/opt/pw-browsers/chromium'`), and check 1440, 1024, 768 and 390 px wide, both themes, and a book with and without
  scenarios. Nothing may overflow horizontally, overlap, or print `NaN`.
