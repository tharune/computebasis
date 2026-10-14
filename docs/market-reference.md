# Retained market references

The retained-reference study compares normalized price observations already in
the local snapshot store. It makes no vendor request and accepts no caller price
rows. Its output is an indicative reference for an explicit cohort, with the
source, snapshot and policy origin of each contributor. It never produces a
market bid, ask or orderbook midpoint, nor verifies physical inventory.

`GET /v1/market/reference/contract` describes the intake and returns an unknown
template. `POST /v1/market/reference/evaluate` accepts exactly three keys:

| Key | Meaning |
| --- | --- |
| `source_scopes` | One to 32 `{source_id, filters}` entries matching configured collection scopes. |
| `policy_revision` | The content hash of the current saved policy for that policy identity. |
| `cohort` | Explicit hardware, native unit, currency, price side and contract/reference terms. |

The server supplies the current UTC assessment time. It resolves the latest
retained snapshot for each requested source/filter scope and verifies snapshot
integrity. `max_pages` is a collection budget, so changing it cannot create a
different economic scope or duplicate source weight. The study checks current
server observe, retain and benchmark permissions, saved-policy activation and
head revision, retained capture freshness, and individual observation freshness
and permissions. Revoked sources are excluded before their retained rows are
used. A missing or stale requested scope holds the whole reference; it cannot
silently substitute a smaller source population.

The cohort requires `scope`, `hardware_model`, `hardware_memory_gib`, `currency`,
`native_unit`, `price_side`, `country_code`, `configuration`, `starts_at`,
`ends_at`, `gpu_count`, `aggregate_terms`, and `observation_period`. Financial
numbers are exact plain decimal strings. `native_unit` selects `gpu_hour` or
`node_hour`, and `price_side` selects asks or actual observed trades. Bid data
cannot be introduced as an ask reference.

For `aggregate_reference`, physical memory, region, delivery and quantity fields
must be explicitly null and configuration must be empty. `aggregate_terms`
contains the exact publisher billing label and reservation month tenor, while
`observation_period` identifies the publisher's measurement period. For example,
a published weekly advertised statistic stays a weekly advertised statistic.
A twelve-month reserved price does not imply delivery starting twelve months in
the future. The benchmark's internal one-GPU-hour aggregate target is a unit
normalization convention; it does not represent a purchased node or delivery
contract.

For `physical_offer`, memory, region, quantity, the seven canonical configuration
fields and both delivery timestamps are required. Aggregate terms and observation
period must be null. Every retained observation must match memory, configuration
and the delivery interval exactly. Numeric configuration values compare by exact
decimal value. A node rate can be divided only by its explicitly retained integer
accelerator count, and the requested allocation must contain whole nodes. These
checks produce a comparable indicative rate, not a firm physical offer.

The existing benchmark kernel applies the saved estimator, source/provider caps,
declared source quality and freshness decay. It handles superseded lots and
conflicting beneficial provider identities. Duplicate retained observation IDs
are quarantined. The result exposes contributors, exclusions, same-side price
range and the kernel's dispersion diagnostics. A range among asks is not a
bid/ask spread, and dispersion is not a calibrated confidence interval.

Catalog records never enter the price population. Token prices, energy, carbon,
FX, financial futures and cloud VM/catalog GPU-division diagnostics cannot become
physical GPU-hour evidence through this study. No implicit FX or model alias
conversion is performed.

Coverage always describes a selected retained sample. The study bypasses the
display index and its row budgets. It checks its 10,000-observation bound before
parsing rows, and exceeding the bound holds the result without computing a
prefix benchmark. A retained display projection also holds. Native upstream
pagination or unknown publisher coverage may yield an indicative retained-sample
reference with `upstream_complete=false`; it never establishes complete market
coverage. Only selected latest snapshots are integrity-checked, not all history.

Successful results have `status="indicative_reference"`, a `reference`, eligible
and rejected observations, source scopes, provenance and coverage. Held results
have no reference. In every case `physical_price_eligible`, `inventory_verified`,
`firm_price_eligible` and `execution_enabled` remain false; `bid`, `ask`, `midpoint`
and `spread` remain null. A frontend can display this study beside independently
declared deal economics without turning a statistical reference into trade
authority.
