# Shared portfolio and inference diagnostics

ComputeBasis evaluates explicit candidate plans. It does not assume market
prices, opening funds, holdings, demand, calibrated weights or approval from
public listing data. The local tools return reproducible paper calculations and
data holds; firm quoting and all financial execution remain disabled.

## One portfolio, one resource ledger

`GET /v1/portfolio/template` returns an unfilled `request` and permitted route
kinds. `POST /v1/portfolio/evaluate` uses the financial snapshot envelope:
`{snapshot_id, created_at, versions, result, execution_enabled:false}`. Both
require an authenticated local session or configured API-client bearer key;
browser writes use same-origin session/CSRF controls. The template performs no
collection and creates no holdings.

The request includes a schema/request/as-of/policy version, one complete dated
`cash` request, one complete `capacity` ledger, `routes`, `supplies`, baseline
cash/exposure ownership, actual supplied `exposures` and `limits`, reviewed
`underwriting_requests`, and an explicit `minimum_free_cash`. There are no
default values in the blank funds, currency, account or calendar fields.

| Input | Required meaning |
| --- | --- |
| `cash` | Existing dated-cash contract: one entity/account/currency, complete ordered events, opening balances, nonoverlapping reserves and at most one explicit facility. Include baseline and candidates together through signing, complete supply and final settlement/maturity. |
| `capacity.lots` | Canonical lot/site/unit IDs and half-open UTC availability, supplier entity, hardware model and nullable exact positive whole `accelerators_per_unit`. A GPU unit is one accelerator. CPU/unknown units never acquire an inferred GPU count. |
| `capacity.reservations`, `maintenance`, `baseline_allocation_ids` | Complete global physical allocations and downtime. Candidate reservation allocation ID equals its route ID; every other allocation must be declared as baseline. |
| `routes` | Unique ID, inference/resale/forward kind, buyer entity, exact reservation, owned cash/exposure IDs, economics, explicit supplier-cost allocations, nullable inference request and underwriting request ID. |
| `route.economics` | Matching currency and exact strings for gross billings, expected collections, distribution fees, nonpurchase costs and separate policy capital. No collection/default forecast is estimated from these values. |
| `supplies` | One cost record per lot: unique supply ID, actual candidate purchase cost, matching currency and owned supplier cash/accounting event IDs. Complete supply cost is retained even when capacity is idle or unallocated. |
| `exposures`, `limits` | One baseline plus candidate set, uniquely owned, with explicit supplier/buyer/group/site/currency mapping and mandatory limits. Values are declared exposure measures, not automatically calculated PD/LGD or relationship verification. |
| `underwriting_requests` | Current as-of, exact supplier/site/lot/buyer/transaction(route ID)/portfolio(request ID), applicable required neutral core, and current caller-qualified evidence. Additional requirements are possible; weakening the material core does not pass this check. |

All global cash events/exposures have exactly one owner. An invoice/deposit
application cannot be credited to a different buyer route. Supplier cash and
expense reconcile once; route gross invoices/earned revenue, collections,
operating payments and expenses reconcile. Previously paid baseline assets need
their own treatment; they cannot be made zero-cost candidate supply implicitly.

Model `shared-portfolio-candidate/1.2.0` additionally evaluates gross ledger
floors in date and declared same-day event order. Supplier prepayments and buyer
receivables retain their supply/route, counterparty, lot, site, declared group
and currency attribution. Each entity/group/site/currency floor is the peak
of simultaneously outstanding balances, rather than a sum of peaks from
different times. Declared exposure amounts cannot fall below those floors;
explicit limits must cover them. Unknown opening/baseline attribution or
ambiguous ownership/groups holds the assessment. Restricted deposits and
refund liabilities remain separate, with no receivable offset.

The returned `ledger_exposure_floor` includes balance components, event/date
witnesses, scope comparisons and missing-attribution diagnostics. Its group
memberships are still caller claims. Gross accounting obligations are not
calibrated EAD, authenticated intraday settlement, collateral rights or a
stochastic delivery/default forecast. Those remaining exposures stay unknown.
`exposures.declared_measures_admitted` reports the declared-input check while
`exposures.admitted` and `checks.exposure` include the conservative floor.

Inference joins the declared full deployment to the reserved physical count,
hardware, interval and policy. Its measured benchmark hash must be linked in
the reviewed workload evidence. Engine billings, collections, fees, full idle
GPU costs and operating costs must agree with route allocations. No serving
measurement is inferred from a model catalog or device name.

The result contains independent cash/capacity/exposure/evidence/reconciliation
checks, all blockers, the full shared cash schedule, typed capacity and limit
reports, per-route economics and immutable hashes. It is `held` or `indicative`,
with `firm_price_eligible:false` and `execution_enabled:false`. A full set of
caller-verified evidence pointers is not proof of artifact authenticity or
substantive credit/security/legal eligibility.

Candidate contribution/profit is **before financing costs not attributed in
route operating costs**. The shared cash schedule includes the supplied loan
draws/interest/paydowns, but loan principal is not revenue or an operating
expense. Do not interpret a positive operating result as full-deal net profit.
Restricted deposits and undrawn facilities are not unrestricted bank money.
The check evaluates a supplied candidate rather than choosing joint bids,
allocations or an optimal portfolio.

Native usable unearned advances, receivable writeoffs, forfeitures and credit
notes remain treasury acceptance work. Incomplete or fabricated invoice/receipt
workarounds cannot qualify as complete account reconciliation. No bank balance,
actual contract, identity, forecast probability or external approval is created.

## Explicit inference price floors

`POST /v1/inference/evaluate` retains its qualified-workload cost contract.
Optional `pricing_policy` adds diagnostics only when every parameter is declared:

```json
{
  "required_margin": null,
  "margin_basis": null,
  "policy_capital_amount": null,
  "task_price_tick": null,
  "rate_ticks": {
    "input_per_million": null,
    "output_per_million": null,
    "cached_input_per_million": null,
    "request_fee": null
  }
}
```

This is an unfilled form shape, not a valid policy. Set exact decimal strings and
an explicit margin basis `gross_billings` or `collected_revenue`. Positive ticks
cannot be finer than the supported monetary grid. Capital is separate from
expected cash costs/reserves and cannot duplicate a `policy_capital` cost item.

For served requests `N`, declared expected cost `C`, capital `K`, collection
share `q`, collection fee `fc`, gross fee `fg`, and margin `m`:

```text
fee_factor = q × (1 - fc) - fg
margin_factor = fee_factor - m          for gross-billing margin
margin_factor = fee_factor - m × q      for collected-revenue margin
zero_expected_task_floor = C / (N × fee_factor)
zero_economic_task_floor = (C + K) / (N × fee_factor)
required_margin_task_floor = (C + K) / (N × margin_factor)
```

The expected/economic/current-profit outputs retain exact denominators and
separate capital. Buy/sell instructions are not created. Nonpositive volume or
denominator holds; a zero sale vector cannot be proportionally scaled into a
fabricated quote. Missing policy parameters do not receive default margins.

The proportional native rate vector scales the declared input/output/cache/
request prices for that exact workload mix and rounds each nonzero rate upward
to its explicit tick. It is one mix-specific feasible vector, not the unique
minimum, a universal tariff or a buyer-demand-validated target ask. A changed
context/token/cache/tool mix requires re-evaluation and workload qualification.

## Base GPU rate: a conditional economic limit

The optional request field `supplier_ceiling_policy` asks a narrow question:
at the declared inference volume and sale tariff, how much expected economic
budget remains for the base GPU rental rate? It creates no cash-funded or
market-qualified bid. Use this exact unfilled shape:

```json
{
  "buy_tick_per_gpu_hour": null,
  "nonpurchase_costs_complete": null,
  "nonpurchase_costs_rate_independent": null
}
```

The tick must be an exact positive decimal string on the supported monetary
grid (minimum `0.000000000001`). Both Boolean assertions must explicitly be
`true`, and the existing full margin/capital `pricing_policy` must be calculable.
Null or false assumptions hold the limit; there is no default margin, capital,
coverage or tick. Invalid types or unknown policy fields are rejected.

Let `G` be gross billings, `H` be all payable allocated GPU-hours, `O` be every
declared expected cost other than the single base `gpu_allocation` cost owner,
and `K` the separate capital charge. With collection share `q`, fees `fc` and
`fg`, required margin `m`, and margin denominator factor `d` (`1` for gross
billings, `q` for collected revenue):

```text
base GPU budget = G × [q × (1 - fc) - fg - m × d] - O - K
economic rate limit = base GPU budget / H
permitted buy-grid limit = tick × floor(economic rate limit / tick)
```

Allocated GPU-hours include idle capacity throughout the whole deployment
horizon. Measured availability and request throughput constrain service volume;
they do not remove the corresponding rental expense. All declared fixed,
per-request and per-GPU-hour operating items stay in `O` at that same horizon
and volume, while capital is deducted once. Financing costs must be declared
where they belong; the capital charge alone is not proof that all financing
expense is covered, nor is loan principal an operating cost.

Coverage and rate independence are caller claims, not evidence established by
the tool. The closed form assumes every cost in `O` remains unchanged as the
base rental price varies. If node fees, financing interest, insurance or another
cost depends on that price, this assertion must be false until a model reprices
those terms. An explicit empty cost list plus complete coverage asserts zero
operating overhead; absent knowledge cannot be represented that way.

The nested `pricing_diagnostics.supplier_buy_ceiling` report preserves the
signed budget and its ownership. It returns a downward-grid rate only when
the budget is nonnegative, and verifies `grid_rate × H <= budget`. Negative
budgets hold with null rate fields. An exactly zero limit is explicit and
affords no positive supplier rate. Zero billings/served volume or an infeasible
fee/margin denominator cannot generate a supplier recommendation. The report's
current-quote check uses the original monetary inequality, rather than rounding
an existing supplier quote into feasibility.

Even an indicative economic limit has `cash_funding_assessed:false`,
`market_qualified_bid:false`, `firm_price_eligible:false` and
`execution_enabled:false`. Aggregate expected revenue does not provide payment
dates, cleared funds, enforceable buyer collections, credit qualification or
deliverable market comparisons. A candidate acquisition still needs the full
dated shared cash/facility ledger, capacity/evidence/credit limits, rights and
independent admission. This diagnostic is not a substitute for those checks.

The [invented supplier-budget tests](../tests/test_inference_supplier_ceiling.py)
verify fee and margin bases, capital ownership, idle hours, adverse and zero
budgets, conservative boundary precision, and a last affordable tick whose next
increment fails the required margin. They supply no empirical demand or market
parameters.

## Local versus routed crossover

Routed token/request charges remain separate from complete operating costs.
`external_route.cost_items` must be an explicitly declared bounded array, with
unique canonical IDs and economic ownership, matching currency, exact amount
and basis `whole_horizon` or `per_request`. An explicitly empty list asserts no
additional costs; omission means unknown overhead and holds the all-in crossover.
`upstream_model_rates` and `routing_fee` are reserved owned channels so those
charges cannot be duplicated as additional operating items.

The legacy routed `cost` is upstream model plus declared routing charges.
Separate `all_in_cost` and contribution include the supplied routed operating
items. Both require the same accepted model/precision/quantization, current rate
and full service interval; neither verifies route privacy/SLO or future demand.

Local and routed cost curves are `F_local + v_local × N` and
`F_route + v_route × N`, using the same declared horizon/workload. The crossover
is their algebraic intersection. The output reports the whole-request threshold
and direction, tests that threshold against the actual cost inequality, and
compares it with measured qualified request capacity. Reverse/no-crossing/equal
curves remain explicit. A threshold outside qualified capacity does not become
an attainable utilization forecast. Measured aggregate goodput is not multiplied
by batch or parallelism again, and idle GPU cost remains payable.

These diagnostics require independent actual workload, fee, demand, privacy,
credit, liquidity and model acceptance before any commitment. Offline synthetic
tests exercise exact boundaries and conservation; they do not supply that evidence.

Native advance application, unpaid-invoice credit notes and noncash write-offs reconcile net service billing without duplicating cash or losses. Forfeiture requires a separately declared nonservice income amount. Date-only exposure admission applies same-day gross asset increases before decreases; the supplied order is diagnostic rather than settlement evidence. New persisted inventory must be explicitly declared. See [current capabilities](features.md).
