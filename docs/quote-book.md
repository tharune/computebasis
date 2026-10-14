# Simulated quote book

A local, seeded market of GPU providers and quotes for demonstrations. It lets a viewer see
how the same quote looks once seller quality, financing and failure risk are priced in, and how
a book changes when a price war, supply shock or provider downgrade hits it. It is **simulated
data**: nothing here is evidence, a price source or inventory, and every response carries
`"simulated": true` and `"execution_enabled": false`.

## Data and provenance

The starting book is the 12 providers and 38 quotes of a fictional mock workbook (the Senthos
mock provider and quote workbook, v1.3). The service extends them to about 28 providers and 150
quotes in the same shape with seeded, invented rows. The workbook is not committed; only the
generated `src/compute_pricing/control/quote_book/seed.py` is, with `SOURCE_SHA256` naming the
exact file and `CONTENT_SHA256` covering the rows so hand edits are caught.

```sh
python scripts/gen_quote_book_seed.py WORKBOOK.xlsx          # regenerate (needs openpyxl)
python scripts/gen_quote_book_seed.py --check                # verify the committed seed, no workbook
python scripts/gen_quote_book_seed.py --check WORKBOOK.xlsx  # also compare with a workbook
QUOTE_BOOK_WORKBOOK=WORKBOOK.xlsx python -m unittest tests.test_quote_book_scoring tests.test_quote_book_market
```

The last command also runs the workbook oracle, which recomputes the workbook's own cached
scores, grades and all-in costs from the seed.

## Economics

The formulas port the workbook's scoring and quote analysis one for one:

- Provider quality is the weighted tier score (certification 15%, facility tier 15%, SLA 20%,
  delivery 15%, credit 5%, responsiveness 30%) mapped to grades A to D.
- All-in cost is the quoted price plus financing on the down payment plus expected loss if the
  seller fails. The grade sets the failure probability and the pricing premium.
- A quote is eligible only when its all-in cost can be computed, a down payment is stated, the
  grade is C or better and at most three of ten key terms are missing.
- Basis is the best eligible all-in cost over the cheapest quoted price, minus one.

The cost of capital and the failure probabilities are the workbook's own placeholders, not
calibrated estimates, and the on-demand references are index prices that overstate what a
term resale would earn.

## Clock and scenarios

The book advances with the wall clock, three seconds per step (30 simulated minutes), and
catches up at most 12 steps after a pause. Each step draws from an RNG seeded by the book seed
and the step number, so a given seed replays identically. The workbook's rows stay exactly as
published until the clock starts. The book is process memory only and nothing is persisted.

Scenarios: `price_war` (weaker sellers undercut B300), `supply_shock` (large H200 offers are
withdrawn) and `downgrade` (the largest grade A seller loses its standing). Their effects are
pinned so they do not drift back on the next step.

## API

| Route | Scope | Purpose |
| --- | --- | --- |
| `GET /v1/book` | `read` | The book as one snapshot with a weak `ETag`; `304` when `If-None-Match` is current. |
| `POST /v1/book/control` | `book` | `{"action": "pause" \| "resume" \| "reset"}` or `{"action": "scenario", "scenario": "price_war" \| "supply_shock" \| "downgrade"}`. |

Both routes use the application's shared authentication: a bearer API key, or a browser session.
A browser session also needs same-origin fetch metadata, and `POST` needs its CSRF header. Prices
are decimal strings. The snapshot holds `meta`, `kpis`, per-model `models`, `grade_mix`, `supply`,
`expiry`, `completeness`, `field_gaps`, `providers`, `quotes`, `alerts`, `series` and the
`assumptions` used. An invalid control body returns `422`.

The package is `compute_pricing.control.quote_book`; the routes live in
`compute_pricing/control/api/quote_book.py`.

The frontend that draws this book (Brief, Overview, Quotes, Pricing) and the hand-off status are in
[ui-handoff-notes.md](ui-handoff-notes.md).
