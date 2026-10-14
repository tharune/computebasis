# Backend and frontend handoff

ComputeBasis separates market research, declared deal arithmetic and paper
inventory. The backend owns source admission, normalization, comparable cohorts,
price calculations, cash schedules and evidence holds. The frontend presents
those results and explicit inputs. It does not manufacture missing quotes or
compute a second financial model in the browser.

This contract describes the current public backend. Integration with a separately
served frontend remains incomplete until its exact revision, serving origin and
API schemas have been verified together. Backend route availability alone does
not establish frontend synchronization.

## Stable workflow endpoints

| Workflow | Request | Response and meaning |
| --- | --- | --- |
| Session | `POST /v1/session/bootstrap`, body `{}` | Short-lived local cookie plus in-memory `csrf_token`; no vendor key in the page |
| Market screen | `GET /v1/demo/market` | Bounded, index-compatible public display with `commitment_curves` and `refresh_operations`; no vendor collection on this GET |
| Configured retained view | `GET /v1/market/current` | Bounded configured-scope projection, `data_revision` and conditional ETag; input changes and known expiry deadlines invalidate its shared cache |
| Retained notifications | `GET /v1/market/events` | Bounded same-origin SSE lease; change notifications trigger a retained GET, not vendor reads |
| Quote study | `GET /v1/quotes/contract`, `POST /v1/quotes/evaluate` | Exact comparable quote declarations; persisted `quote_study` decision envelope, never a live firm quote |
| Advanced evidence | `GET /v1/market/index` | Retained normalized observations, catalogs, source scopes, snapshots and separate collection/history/display coverage |
| Source admission | `GET /v1/sources` | Dynamic implementation and policy states; an enabled source is not proof of a successful current capture |
| Refresh operations | `GET /v1/market/refresh/status` | Per-scope attempt, success, next-due and in-progress states; `running` alone does not mean a vendor request is active |
| Deal intake | `GET /v1/demo/contract` | Typed fields, unknown template and an explicitly labeled synthetic sample; fetching it does not populate a deal |
| Compact scenario | `POST /v1/demo/scenario` | Flat explicit controls expanded into the complete pricing and dated-cash model, in an immutable decision envelope |
| Full pricing | `POST /v1/pricing/evaluate` | Full declared or retained-market request; current policy and exact retained evidence are checked on the server |
| Commitment marks | `GET /v1/market/curves` | Separate observed native cohorts; references, gaps, conflicts and display limits remain visible |
| Declared term arithmetic | `GET /v1/curves/contract`, `POST /v1/curves/evaluate` | Matching dated contract averages and conditional incremental-interval arithmetic; no invented forward quotes |
| Electricity | `GET /v1/power/contract`, `POST /v1/power/evaluate`, `POST /v1/power/from-reference` | Explicit power-cost ownership, or a server-bound wholesale-reference scenario; no automatic GPU-price promotion |
| Paper inventory | `GET /v1/inventory`, `POST /v1/inventory/evaluate`, `PUT /v1/inventory` | Read, pure preview and explicit compare-and-swap replacement are separate operations |
| Decision replay | `GET /v1/decisions/{snapshot_id}` | The submitted request, result and versions for a retained decision; not a current market refresh |

Evaluation responses use `{snapshot_id,created_at,versions,result,execution_enabled}`.
Unwrap `result` for display and keep the complete envelope available for replay.
Do not assume market indexes or contract metadata use this evaluation envelope.
The shared market screen displays the admitted GetDeploying, ECB and Energinet
purposes; the wider internal catalog has separate use and redistribution scopes.
Read the current policy and coverage rather than hardcoding a feed count.

Matching route names do not establish compatible services. In this backend,
`/v1/demo/market` is retained public evidence, not an arbitrary simulation bundle.
New frontend integrations should use `/v1/market/current` and `/v1/quotes/*`,
verify `/health` and returned schema versions, and inspect the documented DTOs.
Do not replace a simulation service solely because both expose the same path.

## Exact values and unknowns

Money, rates, ratios and financial quantities travel as plain decimal strings.
An explicit `"0"` differs from `null`, an absent field or an empty control. Keep
the original string through editing and submission; JavaScript `Number` is not a
financial serialization path. Integer metadata counts and boolean gates remain
their documented types. Dates and UTC instants follow the individual contract;
market capture timestamps may include fractional seconds. Never assume a fixed
730-hour month or turn a source capture time into a new observation date.

Totals may use exact decimal presentation at two cents with the full value in a
tooltip and complete response. Round a required funding amount upward for display
so the visible amount does not understate the requirement. Rates retain their
tick precision. Convert decimals to floating point only for chart pixel positions;
the exact backend values stay in labels, accessible descriptions and details.

The compact deal POST is a flat object, without an `inputs` wrapper. It requires
`gpu_count`, `delivery_start`, `delivery_end`, `billed_utilization`, `supplier_rate`,
`buyer_rate`, `reference_rate`, `collection_share`, `fee_on_collected`,
`fee_on_gross`, `fixed_operating_cost`, `opening_cash`, `minimum_cash`,
`required_margin`, `tick_size` and nested `payment_dates`. The six payment dates
are `supplier_payment_on`, `buyer_invoice_on`, `buyer_receipt_on`,
`operating_cost_on`, `fees_on` and `writeoff_on`. Render their types and labels
from `/v1/demo/contract`; unknown values start empty. The sample is opt-in,
synthetic and editable. It creates no holding or market observation.

## Market presentation

Show source, native currency/unit, price role, observation period, capture time,
expiry and stale state together. A reference is not a bid/ask spread. VM-hour,
node-hour, GPU-hour, token, MWh and currency-exchange records cannot share an
unqualified price axis. ECB rates are informational; an electricity reference
is not an all-in facility tariff; a model recipe is not measured serving capacity.

Commitment groups preserve source/version, hardware model, currency, billing
type and observation week. A null reservation-month value means **unspecified
term**, including when billing type is `RESERVATION`. Draw observed points without
interpolation. Conflicts hold the node; missing terms stay missing. Configuration,
region and capacity remain unknown when the source does not establish them.
Provider counts are native support metadata, not inventory or automatic weights.

`as_of` is the index assessment time. Each source's capture and original price
period are separate. Show returned counts and explicit truncation from `coverage`;
a fast configured-scope projection does not represent the entire compute market.
Polling the display updates retained evidence, while backend collection follows
the approved scope/cadence configuration.

## Deal results and inventory

The scenario screen reads `economics`, `ask` and `cash_constraint`. Its computed
purchase ceiling and selling floor are scenario diagnostics, not external market
quotes. Unbound evidence keeps `bid: null` and visible holds. Never replace this
with `tested_purchase_tick`, a market reference, a zero or a midpoint.

`scenario_supplier_cash_schedule` is the cash path at the supplied supplier rate.
`cash_constraint.selected_schedule` is the path at the tested search ceiling;
these must not be substituted without changing the chart's label. Plot
`free_cash`, `minimum_ordered_free_cash` and, when returned, `minimum_cash_floor`.
Show `supplied_ask_required_extra_cash` and its feasibility separately from profit.
The economic margin uses the returned `margin_basis`; the compact contract uses
gross billings. A positive profit does not fund an earlier supplier payment.

Inventory is a declared paper plan. Available, reserved, sold, maintenance and
unavailable have distinct meanings; unsold includes available, reserved and
maintenance within active availability. Report unit kinds separately and leave
unknown coordinates unlocated. A market quote does not add owned units. An
invented inventory preview cannot be persisted as a declared plan. Replacements
carry the current `expected_revision`; conflicts preserve the local draft.

## Session, errors and updates

Use the exact configured same origin, `credentials: "same-origin"` and the
in-memory `X-Compute-CSRF` token for browser writes. Do not store keys, cookies,
drafts or received records in browser persistence. If a frontend development
server has a different origin, agree the serving integration before testing;
do not bypass Host, Origin, Fetch Metadata or CSRF checks to make it connect.

Both `scripts/local.py` and `scripts/serve.py` accept `--browser-origin` for a
separate loopback frontend using a same-origin development proxy. The backend
still listens on `127.0.0.1`; its default port remains 8000, and omitting the flag
keeps browser authorization bound to `http://127.0.0.1:8000`. For a frontend opened
at `http://localhost:5173`, set the runtime variable to an absolute directory
outside Git and launch with:

```sh
python scripts/local.py start --runtime "$COMPUTEBASIS_RUNTIME" \
  --browser-origin http://localhost:5173
```

The frontend requests relative `/v1/...` URLs. Its proxy forwards them to the
fixed loopback backend while preserving the browser's exact `Host`, `Origin` and
Fetch Metadata headers. A minimal Vite proxy section is:

```js
server: {
  proxy: {
    "/v1": { target: "http://127.0.0.1:8000", changeOrigin: false }
  }
}
```

Do not rewrite the browser Origin or Fetch Metadata, or change Host to the backend
address. The forwarded Host must match the configured frontend origin, including
the port. `localhost` and `127.0.0.1` are distinct origins. Session bootstrap and
logout also use the relative proxy path; keep cookies and CSRF protection rather
than adding a pasted API key or permissive CORS policy. With a frontend origin
configured, direct browser requests to the backend origin intentionally fail that
frontend session boundary.

Launcher flags are startup configuration. `local.py start` can reuse an existing
service without applying changed flags. Stop the owned service, wait until it has
finished draining, and restart with the desired origin/port/configuration; restart
the development proxy if its configuration changes. No command here establishes
that a separate frontend has already been integrated.

A read may renew its expired session and retry once. A write is never
automatically replayed after expiry, cancellation, timeout or an unknown response.
Preserve edits and let the user retry or reconcile. HTTP 422 is an input rejection;
HTTP 503 is an unavailable store/service; a valid held calculation is still a
successful response whose reasons must be shown. Out-of-order responses and
responses after logout cannot repaint cleared state. Refreshes do not overwrite
edited deal or fixed-time inventory drafts.

## Quote DTO evolution and acceptance

The additive `/market/current` DTO keeps the index shape and adds
`schema_version: "current-market/1.0"`, `data_revision`, `cache_max_age_seconds`,
`commitment_curves` and `refresh_operations`. It selects the latest explicitly
configured source/filter scopes; `coverage` states that this is neither the full
market nor a full-history integrity scan. Each category returns at most 1,000
records with its complete count and truncation state. Use explicitly scoped
collection and retained snapshots for complete candidate evidence, rather than
using this display prefix as a weighted pricing population. The shared cache
lasts at most 60 seconds, rebuilds at known source/record freshness deadlines,
and invalidates immediately on
store, policy, plan or operation changes, and time-based expiry is rechecked.
Pricing evaluations independently revalidate their evidence.

Send the previous `ETag` as `If-None-Match`. Preserve the last coherent body on
HTTP 304; it has no JSON body and is not an input error. ETag changes reflect
evidence, rights, freshness, coverage and operation state, not clock labels alone.
A new assessment time is not a new source observation.

SSE uses the local read session and same-origin boundary, rechecking authorization
while open. `lease_seconds` defaults to 30 and accepts 1–60; the process permits
eight concurrent streams and returns 429 with `Retry-After` when full. The server
supplies a 2,000 ms reconnection delay. Listen for `market_update`, whose data contains
`schema_version: "market-event/1.0"`, `data_revision`, `as_of`, `view_endpoint`,
`source_count`, `returned_observations`, `returned_catalog_records` and
`execution_enabled: false`. The event ID is the revision. Comments mean retained
evidence is unchanged; `source_count` counts enabled sources, not successful live
captures. `market_unavailable` reports unavailable retained evidence,
`session_expired` requires a new local session, and `stream_renew` requests
reconnection with `reconnect: true`. Coalesce update events into a conditional
GET. Reconnect obtains a current notification rather than a historical event
replay; preserve local drafts and renew an expired session without replaying a
write. Neither subscriptions nor GETs fetch vendors per client. Conditional GETs
still require authentication, including when they return 304.

The [quote-readiness contract](quote-readiness.md) distinguishes conceptual
readiness from the new evaluator's actual `held`/`comparable_two_sided` statuses.
`best_bid` and `best_ask` are quote objects with `price` and supporting IDs, size
and age, not bare prices. `midpoint` and `spread` are nullable decimal strings.
`advertised_reference.ask_median` is separately labeled and never a midpoint.
The evaluator always returns `source_evidence_eligible`, `firm_price_eligible`,
`inventory_verified`, `tradable` and `execution_enabled` as false. Its evidence
basis is `caller_declared_not_server_admitted`. An added quote route does not
rename existing pricing statuses, grant firm pricing or add an execution path.

The frontend integration is accepted when an unknown form stays unknown until a
deliberate action, current/stale references keep native scopes, an edited scenario
recalculates backend profit and funding, changed inputs invalidate prior results,
external bid/ask gaps remain visible, paper inventory survives explicit revision
rules, and session loss cannot restore old records. Verify this against the exact
backend and frontend revisions with offline fixtures and an actual local browser.

See [evidence boundaries](pricing-evidence-boundaries.md),
[sessions and refresh](local-session-refresh.md),
[inventory and policy](inventory-and-policy.md),
[power ownership](electricity-and-compute-costs.md) and the
[curve contract](../src/compute_pricing/control/curves/README.md).
