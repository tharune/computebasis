# Great Britain grid-carbon context

`gb_carbon_intensity` adds national grid-carbon context to the backend. The
[official API](https://api.carbonintensity.org.uk/) covers **Great Britain**,
not the whole United Kingdom. Its [national intensity schema](https://carbon-intensity.github.io/api-definitions/#intensity)
keeps the publisher's half-hour **forecast** separate from its **estimated actual**
intensity, in `gCO2/kWh`. The latter is an estimate from metered generation;
it is not a site's measured emissions. Timestamps are UTC. The national
from/to endpoint is anonymous and documents a maximum fourteen-day range;
this connector deliberately limits each request to seven days.

## Source use and attribution

The [publisher terms](https://github.com/carbon-intensity/terms) identify
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and impose additional
API-use restrictions. The configured purpose is attributed, normalized local
grid-carbon context in compute comparisons and scenarios. It is not resale of
API access or a replacement carbon-data service. Keep the attribution and
modification notice; use no publisher logo or endorsement claim. Respect
source revocation, cooldowns and rate-limit responses. The terms can change,
so a recorded review is distinct from unlimited future permission.

The example admission grants observation, retention and comparison for this
context role, with execution denied. The shared `benchmark: PASS` purpose gate
does **not** admit a carbon record into the physical GPU-price benchmark:
`gpu_hour_benchmark_eligible` and `price_eligible` are always false. The source
adapter retains selected normalized facts with attribution; raw responses and
runtime snapshots stay outside Git. Tests use independently invented values.

## Request and dynamic collection

Use the existing authenticated `POST /v1/sources/gb_carbon_intensity/collect`
route. The browser reads retained evidence from the local backend rather than
contacting the publisher directly. A rolling request is:

```json
{"filters":{"rolling_hours":24,"limit":336}}
```

Supply **exactly one** of `rolling_hours` or the pair `start`/`end`, plus `limit`.
Rolling hours must be a whole number from 1 through 168. Explicit boundaries
use `YYYY-MM-DDThh:mmZ`, aligned to UTC half hours, with a positive interval
between thirty minutes and seven days. `limit` is a local selected-record
budget from 1 through 336, not an upstream pagination parameter. Unknown
parameters, postcode queries, arbitrary endpoints and authentication are
outside this connector. One pinned HTTPS GET reads the national interval API.

Rolling collection resolves its window once at the start of a read. It ends
at the latest completed UTC half-hour boundary and looks backwards by the
requested hours; crossing a half-hour during retrieval cannot shift the
response scope. Explicit future windows may have forecasts and missing
actuals, and partial source coverage remains visible. The general and compact
backend plans include one rolling twenty-four-hour scope; the focused public
demo display plan remains unchanged.

The configured transport cooldown is sixty seconds. Automatic refresh has a
minimum thirty-minute cadence, including when a caller supplies a faster
cadence or smaller freshness budget. This is bounded context polling rather
than a high-frequency feed. Configure a source's rights and enabled state
before collecting; runtime availability is reported separately.

## Retained contract and missing evidence

Each `catalog_records` entry has `kind: grid_carbon_reference`, `geography: GB`,
`native_unit: gCO2/kWh`, `interval_minutes: 30`, `starts_at` and `ends_at`.
`native_intensity.forecast` and `native_intensity.actual` are exact decimal
strings as published, or null. Explicit zero remains zero. Null and absent
values are never filled from each other, interpolated, averaged into a compute
price or silently replaced. `missing_intensity_fields` distinguishes absent
fields from explicit null. A row with neither value remains held.

`actual_basis` identifies the publisher estimate, while `forecast_basis`
identifies the model forecast. `carbon_index` retains recognized publisher
labels without mapping them to a quality score or pricing coefficient.
Unrecognized labels remain null with an explicit status. Unknown field names
are visible; their opaque values and the original response row are dropped.

Coverage distinguishes the expected interval grid from available forecast and
actual values. `complete` concerns selected interval coverage;
`forecast_complete` and `actual_complete` additionally require their own
values. Empty responses, missing intervals and local selection truncation
remain partial. At most one interval touching each requested boundary can be
omitted, with a reported count; an outside or duplicate interval fails. The
parser bounds response size to 512 KiB and inspects at most 338 rows.

`observed_at` records retrieval, not original publication or revision time.
`source_published_at` stays null and `publisher_revision_known` stays false.
The two-hour retrieval expiry is an operational recheck budget; it never
changes the delivery interval or authenticates the freshness of the underlying
estimate. A newly retrieved old interval is still an old delivery interval.

## Connecting energy and carbon deliberately

A separately evidenced energy profile can produce an illustrative grid-carbon
scenario for matching GB intervals:

`kg CO2 = sum(interval electricity kWh × selected intensity gCO2/kWh) / 1000`

The scenario must declare whether it uses forecast or estimated actual and
retain every interval's source, missing-value state and time alignment. Include
facility/PUE allocation once: facility electricity already containing cooling
must not receive another cooling multiplier. National average intensity does
not qualify a site's supplier mix, renewable certificates, lifecycle emissions,
marginal emissions or an emissions-compliance claim. A location label alone
does not establish a valid regional/site join.

This connector makes no automatic emissions-cost adjustment. Such a scenario
would additionally need an explicit, independently supported carbon-cost
assumption and cost ownership; intensity itself has no monetary price. Every
row has site-emissions, marginal-emissions, carbon-credit, retail-tariff,
firm-price and execution qualification disabled. No GPU allocation, physical
inventory, creditworthiness or inference-performance evidence is inferred.

Run the offline contract tests with:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python \
  -m unittest test_carbon_source_contract -v
```
