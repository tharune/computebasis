# Hourly vesting and hypothetical yield

The [hourly escrow calculator](../src/compute_pricing/control/demo_pricing/escrow.py)
models buyer prefunding as restricted principal. Service earns a portion each
hour; provider obligations, broker margin and refundable customer principal
remain separate. This is an illustrative settlement study, with no bank account,
custody connection, verified contract, insurance assertion or payment execution.

`escrow_contract()` returns the exact field contract and an all-null unknown
template. `evaluate_escrow(payload)` accepts a complete `hourly-escrow/1.0`
document. The pricing demo may generate an explicit constant hourly service
schedule from declared scenario controls; measured uptime does not automatically
become delivered or available service.

## Inputs

Every field is required; optional assertions still need explicit null values.
Money, rates, fractions, APR and native asset amounts are finite plain decimal
strings. Whole GPU counts and buffer hours are JSON integers. The UTC interval
must contain 1–2160 whole hours, with one explicit service fraction per hour.

| Fields | Meaning |
| --- | --- |
| `delivery_start`, `delivery_end`, `gpu_count` | UTC hourly horizon and whole capacity units |
| `service_basis`, `hourly_service_fractions` | `delivered` or `available_sla`; explicitly recognized fraction `[0,1]` for each hour |
| `buyer_rate`, `provider_rate` | USD per capacity GPU-hour; fractions determine recognized GPU-hours |
| `prefunded_principal`, `asset_kind`, `asset_unit` | Restricted native asset quantity, `bank_deposit` or `stable_asset`, and its unit |
| `asset_price_usd` | Declared USD value per native unit, or null; no automatic stable-asset parity |
| `liquidity`, `depeg_status` | Explicit liquidity and depeg status; unknowns and stress states hold cash release |
| `release_authorized`, `refund_at_end` | Caller assertions permitting disbursement and requesting terminal refund; true, false or null |
| `annual_yield_apr`, `yield_access` | Hypothetical nominal APR `[0,1]`; `hourly_withdrawable`, `accrued_only` or `unknown` |
| `yield_shares`, `entitlement_basis` | Explicit provider/broker/buyer fractions summing exactly to one, and an entitlement assertion or null |
| `opening_broker_cash`, `minimum_broker_cash`, `broker_operating_cost_per_hour` | Independent USD cash, floor and hourly operating obligation |
| `provider_risk_grade`, `buffer_hours`, `collateral_fraction` | Declared illustrative risk label and proposed buffer/collateral sizing; no cash is created |

Bank-deposit scenarios use unit `USD`, explicit USD mark `1` or null, and
`depeg_status:"not_applicable"`. Stable-asset scenarios require an explicit
native unit and `normal`, `depegged` or `unknown` depeg status. Even a declared
normal stable asset has no verified parity, redemption, insurance or liquidity.
Release authorization applies to modeled principal disbursements, including
the requested terminal refund; it is never legal verification.

## Accounting

For each hour, recognized GPU-hours equal capacity times the declared service
fraction. Buyer earnings and provider earnings use their separate rates. If a
USD mark is known, earned service moves principal from unearned to earned escrow,
up to the available principal. Missing prefunding becomes a buyer service
receivable; it does not become an invented funded balance.

An authorized, liquid and unstressed scenario can release earned principal.
Provider service obligations receive priority over broker operating obligations.
Payments are limited by available modeled cash; unpaid obligations stay owed.
Broker economic margin equals buyer service earnings minus provider earnings
and operating obligations, even when cash collection is held. It is distinct
from available broker cash. Unearned principal contributes zero broker funding.

Yield accrues before that hour's principal release:

```text
hourly native yield = opening restricted native principal × nominal APR / (365 × 24)
```

This is ACT/365F, without compounding. Previously released principal and accrued
yield are excluded from the next hour's principal base. Unearned principal and
earned principal still held in escrow remain in that base. The chosen APR is a
hypothesis, not a current account rate or promised return.

All yield is allocated to explicit party entitlements. Only an asserted
`hourly_withdrawable` scenario with known entitlement basis and release
conditions can credit the broker's share to broker cash. Provider and buyer
shares are separate asset payouts; they never become broker income. Accrued-only
yield remains an unpaid entitlement. A depeg or liquidity hold preserves both
principal restrictions and yield payables.

For example, invent a two-hour bank-deposit scenario with one GPU, buyer rate
`10`, provider rate `7`, principal `20`, full service and APR `0.0438`.
Opening principal is `20` then `10`, so hypothetical yield totals `0.00015` USD.
Provider service earnings are `14`, and broker service margin is `6`. Assigning
all yield to the broker increases its economic entitlement by `0.00015`; it
increases available cash only if the declared withdrawal conditions permit it.
An outage in the second hour leaves `10` principal refundable to the buyer and
reduces provider earnings to `7`; that principal does not become broker margin.

## Results and holds

The response separates `prefunding`, `settlement`, `yield`, `broker` and
`risk_proposal`. Native asset values use the declared unit; service obligations
and broker cash use USD. Unknown marks leave USD valuation, funding coverage
and principal-recognition allocation unknown. Known zero values stay zero, and
false authorizations remain distinct from unknown assertions.

`required_extra_cash_for_all_obligations_and_floor_usd` uses the minimum cash
path assuming all earned provider/operating obligations were paid. Actual cash
can stay nonnegative while unpaid provider obligations remain; the diagnostic
prevents that from appearing funded. `scenario_cash_floor_feasible` is a
conditional scenario result, never verified real funding. It is null when
required valuation or release conditions are unknown. Outstanding customer
principal or unpaid yield remains visible in `liability_tail_resolved` and the
individual liabilities; cash feasibility does not erase those obligations.

The buffer is declared provider rate times capacity times buffer hours;
collateral is maximum provider obligation times the declared collateral
fraction. Both are uncalibrated proposals. Neither is verified posted collateral
or added cash, and no grade implies a default risk haircut.

The calculator evaluates every hour but returns at most 24 evenly spaced chart
rows, including the first and last. Full aggregates do not use sampled rows.
Terminal refunds occur after the last chart hour and are separately reported.
This bounds payload and rendering work without concealing missing observations
or pretending a sampled chart is the complete cash ledger.

The pricing engine must reconcile its own billings and cash assumptions with
the native result. A simplified full-service pricing cash path cannot claim
support for partial service, depegged collateral, unknown marks or unavailable
yield by inserting those amounts as free opening cash. All source-evidence,
inventory, firm-price and execution flags remain false.
