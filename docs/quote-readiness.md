# Quote readiness and product identity

A compute reference, an economic purchase ceiling and an external quote answer
different questions. ComputeBasis preserves those meanings instead of presenting
every number as a tradable price. Current firm-price and execution flags remain
false; current public references establish neither physical supply nor a binding
buyer commitment.

## Readiness vocabulary

This vocabulary describes product readiness; it is not a replacement for the
pricing engine's `held`/`indicative` status or a grant of trading authority. The
new quote evaluator implements `held` and `comparable_two_sided`. A conditional
arithmetic book is not automatically an admitted indicative source. Render the
actual server status and evidence basis separately from any explanatory label.

| Readiness | Evidence and permitted presentation | Remaining boundary |
| --- | --- | --- |
| Research | Published aggregates, catalogs, caller-declared inputs or incomplete comparisons | Display the native reference and concrete gaps; external bid/ask or midpoint can remain null |
| Indicative | A current, permissioned comparison in explicitly matching units, size, delivery and commercial terms | A paper comparison or model result, not verified inventory, legal commitment or execution |
| Firm eligible | Future nonexecuting qualification after independent provider, contract, capacity, source and risk checks | Current service does not grant this state; order submission and money movement require a separate system |

Successful retrieval, a verified-shaped inline flag or a passed arithmetic check
cannot independently move research to firm eligibility. Saved feature weights do
not grant data rights or prove regional premiums, creditworthiness, uptime or
calibration. Missing required evidence produces named holds, not neutral zeroes.

## Products that require separate comparisons

| Product | Evidence needed | What cannot be inferred |
| --- | --- | --- |
| Current on-demand or spot compute | Specific current offer, hardware/configuration, location, availability, quantity, billing, preemption and SLA terms | A global advertisement does not establish local available inventory or guaranteed performance |
| Reserved compute beginning now | Contract-average price for a specific commitment and start, capacity, payment schedule, inclusion and cancellation terms | Reservation months alone provide no exact delivery calendar, future spot expectation or cancellable interval right |
| Future-start physical compute forward | Matching future delivery start/end, enforceable supplier/buyer obligations, capacity evidence, deposits/refunds and credit exposure | A current reservation average or extrapolated curve does not create a forward quote |
| Standardized financial future | Exact instrument specification, underlying/settlement, contract multiplier, currency, expiry, quotation unit, venue permissions and current side/depth | A financial mark is not a GPU rental rate or proof of a physical compute hedge |
| Inference service | Model/version, engine, quantization, topology, measured workload goodput/latency, privacy/license and billable input/output rules | Token list prices and model metadata do not establish GPUs needed or serving margin |
| Electricity | Delivery interval and area, native currency/MWh or tariff unit, demand/fixed/network/tax scope and contractual inclusion | A wholesale energy mark is not an all-in compute price or verified site tariff |

Financial futures and event claims remain outside GPU-hour benchmark averaging.
A hedge needs a separately measured exposure and basis relationship, applicable
liquidity, funding, collateral and settlement model. The research evaluator does
not infer hedge ratios from vendor names or convert a contingent payout into an
expected compute price.

## Separate the four price objects

| Object | UI label | Unknown behavior |
| --- | --- | --- |
| External buyer-side bid | Actual observed bid, with its terms and evidence | Null until an actual matching bid is available; a purchase ceiling is not a substitute |
| External supplier/seller ask | Actual observed ask, with its terms and evidence | A one-sided ask stays one-sided; no bid or spread is invented |
| Computed purchase constraint | Scenario or indicative purchase ceiling, with binding caps and cash-search basis | Cannot populate a held `bid`; a censored tested ceiling is not a measured liquidity maximum |
| Computed sale constraint | Required-margin scenario selling floor | A minimum modeled sale price is not a buyer offer or proof that it can be sold |

An advertised aggregate retains its source-native price role. A median of
comparable advertised asks can be labeled an advertised-ask reference; it never
supplies a market midpoint. Do not manufacture a bid by applying a spread or
margin to an advertisement.

## Pure quote packet

The input is exactly `{as_of,max_age_seconds,target,quotes}`. All monetary
fields use exact plain decimal strings; unknown required terms remain explicit.
The target identifies `product_role`, `hardware_model`, `configuration`, `region`,
`provider_scope`, `delivery_start`, `delivery_end`, `commitment_months`,
`payment_terms`, `cost_scope`, `unit`, `currency`, `quantity`, `quantity_unit` and
`contract_spec`. Quotes repeat the common product terms; target-only
`provider_scope` and `quantity` are replaced by quote identity and size fields.
Quote fields add `id`, `source_id`,
`provider_id`, `side`, `price`, `available_quantity`, `minimum_quantity`,
`observed_at`, `expires_at`, `status`, `quote_type`, `evidence_ref`, `rights` and
`source_quality`. Read the complete nested field sets from
`GET /v1/quotes/contract`; `POST /v1/quotes/evaluate` returns the usual immutable
decision envelope, stored with snapshot kind `quote_study`.

The exact roles are `spot`, `physical_forward`, `financial_future` and
`advertised_commitment`. Spot delivery contains `as_of`; a physical forward starts
after it. An advertised commitment has an explicit month tenor and null delivery
window. A financial future uses a cash-settled contract specification with an
unexpired contract, exact multiplier and its own quotation unit. The current
financial contract does not support physical settlement. Inference and power
retain their separate evaluators; they are not extra quote-book roles.

Physical configuration uses `accelerator_memory_gib`, `accelerators_per_node`,
`cpu_cores`, `ram_gib`, `storage_gib`, `network_gbps`, `interconnect`,
`privacy_class` and `tenancy`. Financial contracts instead require an empty
configuration and null physical region. Cost scope names `power`, `network`,
`support`, `taxes` and `platform_fees` as included, excluded, not applicable or
unknown. Unknown configuration, scope or payment terms hold comparability.
Provider scope is explicitly one provider or all declared providers. The latter
does not establish equal creditworthiness or delivery risk.

These are pure caller declarations until an API boundary binds the exact
normalized quote to a retained, integrity-checked source record and current
permission policy. An arbitrary evidence identifier or inline `verified` field
is not that boundary. Contract metadata and safe validation errors come from the
implemented quote contract rather than frontend guesses. Prices are selected
without source-quality weighting; declared quality is retained as a claim.
Requested quantity must fit each selected quote's minimum and available size.
Sizes are never summed across providers or venues to fabricate a fill.

For physical `spot` and `physical_forward` books, GPU-denominated target quantity,
quote minimum quantity and quote available quantity must each be a whole-node
multiple of `configuration.accelerators_per_node`. Whole integer GPU counts alone
do not establish an allocation that can be purchased: a node with four declared
accelerators cannot supply a two-GPU request under this whole-node contract.
Node-denominated quantities remain whole nodes; financial quantities remain whole
contracts. This validates declared sizing, not actual allocation or inventory.
Null target size yields `requested_quantity_unknown`; null quote size yields
`quote_size_unknown`. A nonmultiple produces the corresponding
`requested_quantity_not_whole_nodes`, `minimum_quantity_not_whole_nodes` or
`available_quantity_not_whole_nodes` hold/exclusion rather than a partial-device
fill. Missing configuration is not repaired with an inferred node count.

The required `source_quality` field can explicitly be null. It then excludes
that quote with `source_quality_unknown`; the evaluator does not assume perfect
quality, average a default weight or admit it because its price looks attractive.
A supplied quality remains a caller claim, and best-price selection remains
unweighted. Omitting the required key still rejects the exact request shape;
explicit null is the supported way to preserve unknown quality.

Under explicitly matching terms and supported size, fresh usable bid and ask
sides may yield the exact arithmetic midpoint `(bid + ask) / 2` only when
uncrossed. This is a two-sided quote diagnostic under the stated evidence basis,
not a fitted fair value, transaction price or executable spread. `best_bid` and
`best_ask` preserve the selected quote's IDs, exact price, size, age and declared
quality. `midpoint` and `spread` are nullable exact decimal strings. One-sided,
crossed, stale, unpermissioned or incomparable records preserve their unknowns
and holds. Identical currency labels do not establish equivalent region,
configuration, credit, SLA, payment or capacity scope. The successful arithmetic
status is `comparable_two_sided`; other books are `held`, with `hold_reasons` and
per-quote `exclusions`. `source_evidence_eligible`, `firm_price_eligible`,
`inventory_verified`, `tradable` and `execution_enabled` remain false in both
states. Signed financial prices keep their native meaning rather than becoming
nonnegative GPU rental prices.

Current advertised commitment records have no future-start delivery window. Their
native weeks, billing types, currencies, hardware and source versions stay in
separate cohorts. Null reservation months mean unspecified term. The observed
curve does not interpolate, extrapolate, discount or derive interval forwards.
Those records also lack qualified physical configuration, region and available
size. Do not auto-fill these gaps to force them into the explicit quote evaluator.
The declared term engine separately requires matching starts and full dated
24x7 billable hours. Its incremental amount/hour arithmetic has no delivery or
cancellation rights beyond the caller's declarations.

## Acceptance stories

1. An analyst selects a current native reference and sees source, observation
   period, capture, expiry, scope and explicit missing regional/capacity evidence.
   Switching currency or billing period changes the cohort rather than averaging
   incompatible marks.
2. Explicit comparable bid and ask sides can populate a conditional two-sided
   diagnostic. Presenting them as actual current external quotes additionally
   requires source binding. Removing a side, exceeding size, aging a record or
   changing delivery removes midpoint eligibility and exposes the reason. A
   crossed book is held, without repair or an executable-arbitrage claim.
3. A declared deal shows economic caps, a selling floor, margin basis and dated
   funding separately. Raising opening cash can remove a funding shortfall while
   leaving economic profit unchanged. It cannot remove evidence holds or create
   an external bid.
4. A future-start request without explicit future delivery and source/contract
   evidence remains incomplete. A twelve-month reservation label cannot fill
   those fields. A financial future retains its own instrument and settlement
   specification, outside the compute benchmark.
5. Inventory remains a separate declared paper plan. Quote selection, a positive
   margin, metadata discovery and a readiness label create no owned lot,
   reservation, sale, financial transaction or execution permission.

See the [frontend handoff](backend-frontend-handoff.md),
[pricing evidence gates](pricing-evidence-boundaries.md),
[source purposes](source-adapters.md) and
[observed/declared curve semantics](../src/compute_pricing/control/curves/README.md).
