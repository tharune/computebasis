# Independently generated quote book

This demonstration generates 32 synthetic suppliers and resellers and 192
baseline GPU offers across six hardware families. Every company name, price,
location claim, quality tier and commercial term is invented for this simulation.
The generator depends on its explicit seed and simulated assessment date. It
does not ingest vendor offers, customer records or documents. All responses
declare `simulated: true` and `execution_enabled: false`.

## Coverage and regeneration

Each hardware family starts with 32 quotes: B300, GB300, B200, H200, H100 and
Pro 6000. The population includes varied provider tiers, regional/site claims,
whole-node sizes, topology, cooling, durations, deposits, payment timing,
delivery starts and expiries. Some records deliberately omit terms or present
stale/unsupported states. They remain visible with explicit ranking holds.
Sample labels identify demo entities; they imply no relationship to a real
provider, customer or site.

Run the deterministic generator check offline:

```sh
python scripts/gen_quote_book_seed.py --check
```

The population generator exposes explicit seed/date inputs for repeatable tests.
It returns fresh independent objects; editing a returned record cannot modify
the baseline. The baseline prices and policy values are illustrative parameters,
not captured market statistics or calibrated estimates.

## Separate scenario economics from market quotes

The backend computes provider scores from an explicit illustrative weighting
policy. These scores and grade bands organize a simulation; they do not verify
attestation, financial standing, SLA compliance or delivery performance.
The demo rating scale runs from zero to four, with higher values representing
stronger declared characteristics. An unknown rating is not a zero rating.

Quote costing uses exact decimal inputs and the actual delivery calendar.
Contract notional is the declared GPU allocation times its rate times billable
calendar hours. A stated deposit supports a simple declared financing scenario;
its annual-day convention and recovery/failure assumptions remain explicit.
An unknown deposit differs from a zero deposit. Unknown inputs required by an
economic component leave that component unknown and prevent ranking admission.
A missing model reference does not become zero replacement loss.

`eligible` means eligible for the current synthetic ranking rule. It does not
grant source evidence admission, verify capacity or qualify a tradable quote.
The model's cheapest offer, best admitted scenario cost and their relative
gap are illustrative summaries. Grouping by GPU family does not establish
comparable region, delivery, topology, SLA or commercial scope. It is not a
physical compute benchmark, market bid/ask midpoint or inventory valuation.
The displayed model gap is `best eligible scenario cost / lowest displayed
native offer - 1`; its aggregate weights supported model gaps by their current
synthetic quoted GPU counts. Weight and coverage metadata disclose excluded
models and units. Contract-value sums disclose known and unknown component counts.

For explicit comparable bid and ask declarations, use the separate
[quote-study contract](quote-readiness.md). For retained publisher records, use
the [current-market and update contracts](backend-frontend-handoff.md).
Simulation offers do not enter either evidence population or the paper inventory.

## API and clock

| Route | Required local scope | Behavior |
| --- | --- | --- |
| `GET /v1/book` | `read` | One coherent simulated snapshot; conditional ETag reads return 304 when unchanged |
| `POST /v1/book/control` | `book` | Explicit pause, resume, reset or named synthetic scenario |

Control bodies are exactly `{"action":"pause"}`, `{"action":"resume"}`,
`{"action":"reset"}` or `{"action":"scenario","scenario":"price_war"}`.
The other scenario names are `supply_shock` and `downgrade`. Invalid actions or
extra fields are rejected. Browser writes require the exact configured
Host/Origin/Fetch Metadata boundary and current CSRF token. Bearer credentials
remain server-side. No unauthenticated read bypass exists for conditional GETs.

The book lives only in bounded process memory. Its changing clock is simulated
time, distinct from current UTC and source capture timestamps. The seeded
update path is reproducible; pause/resume/reset and scenarios create no trade,
sale, physical reservation, financing draw or payment. A synthetic withdrawal
is not a confirmed sale. Catch-up work, history and alerts are bounded.

The snapshot exposes `meta`, `kpis`, `models`, `grade_mix`, `supply`, `expiry`,
`completeness`, `field_gaps`, `providers`, `quotes`, `alerts`, `series` and
`assumptions`. Monetary values and rates serialize as decimal strings; nullable
values retain their unknown meaning. Counts remain integers. Use schema/version
metadata and `synthetic` flags instead of assuming another service's DTO has
the same meaning. The frontend controls and rendering remain a separate
integration task.
