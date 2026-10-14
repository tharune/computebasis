# Declared pricing demonstrations

The pricing demonstration composes the existing compute-pricing, allocated-power and dated-cash kernels. Its opt-in H100, L40S and A4000 cases describe invented providers, buyers and facilities. Loading a case fills editable inputs; an empty form contains unknown values and cannot produce a price. Rates use USD per GPU-hour and full-node capacity uses whole node counts.

`GET /v1/pricing/demo/contract` describes each nested input path, type, group and available invented case. `POST /v1/pricing/demo/evaluate` saves the declared input and evaluated output. The saved result includes the receipt-bound agreement terms consumed by the nonbinding, unsigned PDF. A declaration of compliance, privacy, credit, ownership or uptime does not verify that declaration.

## Economic channels

Let `H` be actual UTC calendar hours, `N` the declared node count times GPUs per node, `u` billed utilization, `B` the buyer rate, `q` the expected collection share, and `S` the supplier rate. Gross billings are `G = H × N × u × B`; expected collections are `q × G`. The entire `H × N` supplier allocation is purchased, including capacity not sold. Fees are declared separately on collected amounts and gross billings.

Operating expenses, incremental power and supplier-deposit financing are expected cost channels. The capital budget is `H × N × declared allowance per GPU-hour`. It reduces economic profit and reserves available cash during the scenario, but it is not also an expense payment. Its release therefore explains the difference between net operating cash and profit after the capital budget. Provider quality grades have no second monetary premium; geographic or compliance premiums are not inferred from labels.

Financing uses declared supplier down payment times declared simple APR times actual term days divided by 365. The resulting purchase-cost fraction is rounded upward to 12 decimal places before it enters both cost and cash equations. This conservative declared financing scenario is not a lender quote. A fixed rate must have identical low/current/high values. A variable rate evaluates the selected rate within its declared bounds; the bounds do not constitute a stochastic price model.

Allocated power applies GPU idle/load watts, allocated shared-host watts, declared utilization, PUE and tariff to the actual interval. `included` retains the physical energy estimate and assigns zero additional compute power cost. `excluded` adds that cost once. The current cash model supports explicitly broker-paid incremental power; an unknown or different payer holds that cost model. There is no automatic tariff, demand charge or tax verification.

The purchase ceiling is the greatest supported purchase tick satisfying the declared economic margin and dated liquidity constraint. The selling floor covers costs and the explicit capital budget; minimum-margin and target-margin asks are separate. These are conditional scenario numbers. The underlying synthetic benchmark remains held, its submitted bid is null, and physical, firm-price and execution eligibility remain false.

## Funding and protection

The H100 case uses a partial supplier prepayment with the remaining balance due at the service milestone. The L40S case uses a smaller deposit and a variable supply range. The weak-grade A4000 illustration requires the explicit hourly restricted-escrow mode. This demonstration policy is an uncalibrated proposal, not an assertion that a grade guarantees performance.

Ordinary settlement models prepayments, supplier invoices, prepaid application, invoice payments, full buyer billings and earned revenue, receipts, uncollected receivable writeoffs, fees and operating expenses. Dates and same-day event order are declared; they do not prove intraday bank settlement. Cash shortfall and required funding use the ordered trough and the declared minimum cash floor. Increasing opening cash can remove a funding shortfall without changing economic profit.

Hourly escrow records customer funds as restricted principal. Earned service is billed and explicitly released before the corresponding supplier payment; remaining customer principal is refunded under the declared terms. Principal is not revenue or unrestricted opening cash. Proposed provider collateral is not added to cash and does not automatically reduce the risk budget. Asset marks, liquidity, depeg state, release permission, service completion and adequate prefunding must be explicit. Unknown or adverse funding terms hold the pricing cash result. The composed hourly demonstration requires full declared service and collection and supports at most 1,500 hours within the cash-event budget.

The independent hourly helper also shows hypothetical yield on opening restricted principal for each hour and separate party entitlements. Neither accrued nor paid yield is included in this pricing engine's profit or cash projection. The escrow helper's service-only broker calculation is shown separately from the full pricing cash path, which also includes power, operating costs, fees and capital reserves. Refund and unpaid-yield liabilities remain disclosed after cash feasibility is assessed.

NPV discounts the dated changes in unrestricted operating cash using the declared ACT/365 discount rate. IRR remains unknown because an equity financing and distribution timeline has not been declared. Restricted customer principal cannot be relabelled invested equity to manufacture an IRR.

## Declared sensitivity surfaces and retained context

The surface uses the explicit annual volatility, declared standardized shocks and actual tenor days:

`R(t,z) = R(0) × exp(σ × sqrt(t) × z − 0.5 × σ² × t)`, where `t = days / 365`.

It is an unfitted lognormal sensitivity with zero declared arithmetic drift, not a market forward curve, calibrated volatility estimate, confidence interval or risk-neutral forecast. Economic caps are recomputed for each declared tenor using fixed operating cost amortization and simple deposit financing. A separate collection-sensitivity grid reduces the declared collection share by each explicit shock, with a floor of zero. The grids do not recalculate dated funding feasibility; the full dated cash result belongs to the selected contract only.

The opt-in cases declare tenor days `1, 3, 7, 14, 30, 45, 60, 90, 180, 365` and shocks `-3, -2, -1, 0, 1, 2, 3`. All 70 mesh points are calculated directly from the same declared formula. Editable axes use comma-separated plain decimal strings; no live-market interpolation fills the mesh.

A server-supplied retained indicative reference may appear separately when its evidence eligibility, exact model, USD currency and GPU-hour output unit match. It remains context; it does not change the scenario caps, qualify a physical offer or generate a bid. Each result includes immutable input and decision hashes and preserves all unknown and hold reasons.

## Offline example

```python
from compute_pricing.control.demo_pricing import demo_scenarios, evaluate_demo_pricing

for case in demo_scenarios():
    result = evaluate_demo_pricing(case["inputs"])
    print(case["id"], result["status"], result["summary"]["purchase_ceiling"])
```

The focused tests include an independent leap-calendar cash and cost oracle, power inclusion, editable capacity/utilization/cash/capital controls, restricted-principal conservation, escrow holds, unfitted stresses, unit-safe context and immutable agreement terms.
