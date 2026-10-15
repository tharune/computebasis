# Desk ledger contract (`GET /v1/book/desk`)

The Overview shows the desk's simulated positions and brokered bids beside the market, and a US map of where supply is. The quote book
(`GET /v1/book`, schema `synthetic-quote-book/1.0`) has no notion of either, so this endpoint adds them. It is built only from the book's
own population and prices, is deterministic for a given book, and is labelled invented in every place a number could be mistaken for a
trade. Nothing here is inventory, a firm price, or executable.

The frontend reads this through `BookAdapter.normalizeDesk` and draws it. It never computes a second financial model: every money
figure below is computed by the server, and the page prints it (or draws a bar proportional to it).

## Request and caching

- `GET /v1/book/desk`, same cookie session and CSRF rules as `GET /v1/book`. Read-only; no body.
- Strong `ETag` over the response; `If-None-Match` answers `304`. The ledger changes when the book does (marks move with prices), so a
  client that polls beside `/v1/book` mostly gets `304`.
- It follows the book through scenarios and resets: `POST /v1/book/control` reset returns the ledger to its starting state, and the
  `meta.epoch` and `meta.tick` match the book's.

## Honesty flags (same family as the book)

Top level, all required, with these exact values: `simulated: true`, `synthetic: true`, `source_evidence_eligible: false`,
`inventory_verified: false`, `firm_price_eligible: false`, `execution_enabled: false`. `meta.ledger_basis` is
`deterministic_invented_desk_positions_and_bids_not_trades`; `meta.placement_basis` is
`illustrative_metro_assignment_not_vendor_location`. A page that draws the ledger must say it is simulated.

## Shape

Money is a decimal string in USD (per GPU-hour where the name says so, otherwise whole contract dollars), rates and shares are decimal
strings in `0..1`, counts are integers, dates are `YYYY-MM-DD`, times are `YYYY-MM-DDTHH:MM:SSZ`. A figure the server cannot know is
`null`, never `0` and never a string like `"n/a"`.

```jsonc
{
  "schema_version": "synthetic-desk-ledger/1.0",
  "simulated": true, "synthetic": true, "source_evidence_eligible": false,
  "inventory_verified": false, "firm_price_eligible": false, "execution_enabled": false,
  "meta": {
    "as_of": "2032-06-01", "time": "2032-06-01T00:00:00Z", "tick": 0, "epoch": 0, "seed": 4271,
    "book_schema_version": "synthetic-quote-book/1.0",
    "ledger_basis": "deterministic_invented_desk_positions_and_bids_not_trades",
    "placement_basis": "illustrative_metro_assignment_not_vendor_location"
  },
  "summary": {
    "positions": 6,                       // count of positions
    "position_gpus": 1536,                // GPUs held across positions
    "position_notional_usd": "4104960.00",// price x GPUs x contract hours, summed
    "unrealized_usd": "-31840.12",        // sum of positions[].unrealized_usd; null if any mark is null
    "unrealized_basis": "mark_is_current_best_eligible_all_in_cost_per_model",
    "bids": 14, "bids_open": 4, "bids_filled": 6, "bids_declined": 3, "bids_expired": 1,
    "bid_gpus": 2816, "filled_gpus": 1536, "open_gpus": 640,
    "fill_rate": "0.6667",                // filled / (filled + declined + expired); null when none decided
    "sites": 72, "us_sites": 10,
    "us_supply_gpus": 9801, "supply_gpus": 48890, "us_supply_share": "0.2005"   // quoted capacity, live quotes only
  },
  "sites": [ /* one per distinct book location, see below */ ],
  "positions": [ /* see below */ ],
  "bids": [ /* see below */ ]
}
```

### `sites[]`

One per distinct `location` in the book (72 in the starting book), so every quote's `location` joins to exactly one site by `name`.

```jsonc
{
  "id": "site-demo-01-a",                 // stable; derived from the book's site name
  "name": "Demo Site 01-A (US)",          // equals quote.location
  "provider_id": "provider-demo-001", "provider": "Demo Supplier 01", "provider_grade": "A",   // "A".."D", or null when the seller is unrated
  "country": "US",
  "placement": { "label": "Ashburn, VA", "state": "VA", "lat": 39.0438, "lon": -77.4875 },   // state is null outside the US; lat/lon are always present
  "capacity": {
    "gpus": 2024, "quotes": 6, "eligible_quotes": 4, "eligible_gpus": 1480,   // live quotes at this site only
    "models": { "B300": 640, "H100": 1384 }                                   // GPUs by model, live quotes only, models with none omitted
  },
  "position_gpus": 256, "open_bid_gpus": 128
}
```

US sites are placed in a fixed list of contiguous-US data-centre metros by a stable hash of the site id (so a site never moves between
requests or restarts). Non-US sites are placed at their country's capital or main data-centre metro, with `state: null`. The placement is
invented for the picture; it says nothing about where a real seller operates.

### `positions[]`

Capacity the desk holds under contract. Every position is at one site and one model.

```jsonc
{
  "id": "pos-0001", "site_id": "site-demo-01-a", "provider_id": "provider-demo-001", "model": "B300",
  "gpus": 256, "months": 6, "start": "2032-03-01", "end": "2032-09-01", "status": "active",   // "active" | "upcoming"
  "price": "7.0500",                       // contract price, USD per GPU-hour
  "mark": "7.1008",                        // the book's current best eligible all-in cost for the model, USD per GPU-hour; null when none
  "mark_basis": "model_best_eligible_all_in",
  "unrealized_usd": "28714.60",            // (mark - price) x gpus x remaining contract hours; null when mark is null
  "remaining_hours": 2208, "notional_usd": "7969996.80"
}
```

### `bids[]`

Bids the desk brokered for buyers. A bid names a book quote, so it joins to the quote table.

```jsonc
{
  "id": "bid-0001", "quote_id": "quote-demo-0037", "site_id": "site-demo-07-a", "provider_id": "provider-demo-007", "model": "B300",
  "gpus": 128, "months": 6,
  "ask": "6.9110",                         // the quote's price when the bid was placed, USD per GPU-hour
  "bid": "6.7800",                         // USD per GPU-hour
  "status": "filled",                      // "open" | "filled" | "declined" | "expired"
  "placed": "2032-05-28T14:20:00Z", "decided": "2032-05-29T09:05:00Z",   // decided is null while open
  "position_id": "pos-0003"                // set when a filled bid became a position, else null
}
```

`quote_id` always exists in the book that was current when the ledger was built; the quote may have expired or changed since, so a
page must tolerate a missing join.

## What the server guarantees (and the tests check)

1. Deterministic: the same book gives the same bytes, so the `ETag` is stable.
2. Joins hold: every `positions[].site_id` and `bids[].site_id` is in `sites`; every `sites[].provider_id` is a book provider; every
   `bids[].quote_id` is a book quote; every `bids[].position_id` is in `positions`.
3. `sites[].capacity` sums equal the book's live quotes grouped by `location`, where live is the book's own rule (the quotes counted in
   `kpis.live_quotes`: active, at least one node, an expiry that is after `as_of`); `summary.supply_gpus` equals `kpis.gpus`.
4. Summary counts equal the lists; `fill_rate` is `null` when no bid is decided.
5. No `NaN`, `Infinity`, empty string where a number belongs, or float for money.
6. The honesty flags above are present and have the stated values.
