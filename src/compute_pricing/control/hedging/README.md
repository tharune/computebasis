# Declared hedge economics

ComputeBasis can study one linear futures position against a caller-declared
distribution of dollar losses. This is an offline numerical study. It has no
broker connector, live price reader or execution permission.

The public entry points are `hedge_contract()` and
`evaluate_hedge_payload(payload)`. The discovery template has unknown financial
terms. A caller must provide all required inputs; omission is not zero.

The request uses `hedge-study/1.0`, an assessment identifier and UTC instant,
explicit USD units, a tail confidence strictly between zero and one, contract
terms, a baseline cash ledger, and at least three scenarios. Each scenario
declares a unique ID, a positive probability, a signed dollar loss, the signed
dollar payoff of one long contract and dated variation margin. Probabilities
must sum exactly to one. Daily margin must telescope exactly to the supplied
terminal payoff.

Contract terms declare signed position bounds, USD settlement, the
`linear_futures` convention, a total fee per absolute contract, initial collateral
per absolute contract and posting/release dates. The cash book declares opening
unrestricted cash, its minimum required level, horizon dates and unique signed
baseline changes. IDs beginning with `hedge:` are reserved for generated cash
trace entries. Financial values are finite plain Decimal strings. Unknown
fields, other currencies, options, covariance matrices and automatic source
substitution are rejected.

The weighted scalar fit is `Cov(loss, long_payoff) / Var(long_payoff)`. The
implementation uses pairwise weighted identities for moments, with local
Decimal precision. Negative size means short. Zero payoff variance holds the
fit; zero covariance with positive variance identifies zero size. These are
in-sample scenario moments, not evidence of calibrated predictive performance.
The effective count `1 / sum(probability²)` describes weights rather than a
verified count of independent observations.

The continuous fit is projected onto the declared position interval. Zero and
the adjacent floor/ceiling integers are compared. Each candidate includes total
declared fees in economic loss. Its comparison rank uses variance, then expected
loss, subject to its bounds and all supplied funding paths. Zero remains an
unhedged reference if excluded by the bounds. The study does not search every
integer or certify a global funding-constrained optimum.

Discrete VaR uses the lower cumulative quantile. ES averages exactly the upper
tail probability mass, including the required fraction at its boundary. Negative
loss values remain gains. Separately, the dated cash calculation posts initial
collateral as an asset, charges fees, pays or receives signed variation margin,
and releases collateral. It never adds the terminal payoff a second time.
Funding shortage and its probability tail are distinct from economic loss.

Without verified intraday times, each date places debits before credits when
checking the cash trough. A hedge with a favorable final payoff can require
funding earlier. Economic losses do not automatically create cash debits: the
caller must supply those baseline movements once. Actual settlement, cleared
balances, source rights, margin hikes, intraday calls, clearing delays, collateral
haircuts, spreads and commissions are not verified by this module.

Input budgets are 256 scenarios, 512 baseline or per-scenario margin points,
8,192 combined cash points including repeated baseline entries, 100-character
Decimal strings and absolute position bounds up to one trillion. These are
software budgets, not approved trade limits.

Run this independently invented example from the repository root:

```sh
PYTHONPATH=src python - <<'PY'
from compute_pricing.control.hedging import evaluate_hedge_payload

request = {
    "schema_version": "hedge-study/1.0", "request_id": "example:paper-hedge",
    "as_of": "2052-09-08T00:00:00Z", "currency": "USD", "loss_unit": "USD",
    "payoff_unit": "USD_per_long_contract", "confidence": "0.8",
    "contract": {
        "payoff_kind": "linear_futures", "settlement_currency": "USD",
        "minimum_position": -3, "maximum_position": 3, "fee_per_contract": "0.75",
        "initial_collateral_per_contract": "3", "collateral_post_on": "2052-09-08",
        "collateral_release_on": "2052-09-12"
    },
    "cash": {
        "opening_cash": "70", "minimum_free_cash": "0",
        "start_date": "2052-09-08", "end_date": "2052-09-12", "baseline_events": []
    },
    "scenarios": [
        {"scenario_id": name, "probability": p, "unhedged_loss": loss,
         "long_contract_payoff": payoff,
         "variation_margin": [{"on": "2052-09-11", "cash_per_long_contract": payoff}]}
        for name, p, loss, payoff in (
            ("example:soft", "0.2", "9", "-6"),
            ("example:flat", "0.6", "18", "0"),
            ("example:firm", "0.2", "27", "6")
        )
    ]
}
report = evaluate_hedge_payload(request)
assert report["fit"]["minimum_variance_signed_contracts"] == "1.5"
assert report["preferred_compared_scenario_position"] == 1
assert report["execution_enabled"] is False
cash = next(row for row in report["candidates"] if row["position"] == 1)
assert cash["margin_liquidity"]["scenarios"][0]["ending_unrestricted_cash"] == "63.25"
print(report["status"], report["fit"]["minimum_variance_signed_contracts"])
PY
```

Expected output: `scenario_only 1.5`. The example is a synthetic mathematical
case, not a market observation or an offered contract.
