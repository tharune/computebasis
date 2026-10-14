# Electricity and compute cost ownership

Compute offers often include electricity, while electricity market references
describe a different product. The power evaluator keeps these scopes separate.
The input contract is available at `GET /v1/power/contract`; declared scenarios
use `POST /v1/power/evaluate`. Inputs use plain decimal strings, explicit currency
and UTC intervals. A missing input has no implied value.

For each continuously powered interval, allocated IT watts equal GPU count times
the utilization-weighted idle/load watts, plus allocated host, network and storage
watts. Facility energy equals IT kW times PUE times actual UTC hours. PUE includes
facility overhead; adding cooling again would duplicate that allocation. Unsold
capacity still consumes idle power. Hardware TDP alone does not establish average
consumption or the complete host allocation.

Demand charges require dated, unique, nonoverlapping billing periods. The entire
period must be covered by the power profile, and the declared allocated peak must
cover facility load in that period. There is no automatic partial-period proration.
Network, tax, fixed and other charges have explicit currency and ownership. An
empty charge list asserts there are no such charges; it does not verify a tariff.
Retail revenue/sales averages already include many charges and cannot receive
these adders without a separate tariff decomposition.

If a compute quote includes power, incremental electricity cost is zero. If it
excludes power, the evaluator returns the declared scenario cost. Unknown inclusion
returns null and a hold. Both powered GPU-hour and sold GPU-hour denominators are
reported, with a null sold-hour result when there are no sales. Scenario output
does not automatically change a compute bid or permit financial execution.

An independently invented example allocates three GPUs at 80 W idle and 420 W
loaded, 180 W of shared IT load, utilization 25%, and PUE 1.2 for ten hours. This
uses 8.1 kWh. At a declared EUR 0.16/kWh the energy cost is EUR 1.296: EUR 0.0432
per powered GPU-hour, or EUR 0.144 per sold GPU-hour when nine GPU-hours are sold.
This is arithmetic, not a measured configuration or an offered tariff.

## Anonymous day-ahead references

The Energinet adapter requests a fixed documented endpoint with one price area,
an explicit one-to-seven-day date range or completed-day rolling range, and a
maximum of 1,000 rows. Query dates refer to the Danish calendar; delivery intervals
are normalized to UTC. Daylight-saving days therefore contain 92 or 100 quarter
hours. The default collection schedule is daily and the backend retains a bounded
normalized cache rather than making a vendor request for each browser client.
These choices follow the [official API guidance](https://www.energidataservice.dk/guides/api-guides)
and [DayAheadPrices metadata](https://api.energidataservice.dk/meta/dataset/DayAheadPrices).

Native signed EUR/MWh and DKK/MWh are retained as energy references. DKK prices
include the publisher's currency conversion. No conversion to a compute GPU-hour
benchmark occurs. Negative prices are preserved, and a negative scenario energy
cost is held until contractual credit pass-through is established. Network,+demand, taxes, location basis and retail contract terms remain separate. Partial
coverage stays partial, without interpolation or a sample-price fallback.

`POST /v1/power/from-reference` binds a power profile to current retained intervals
on the server. It verifies the native 15-minute contract, complete requested
coverage and conflicts between overlapping retained queries. MWh rates are divided
by 1,000 to obtain kWh rates. The resulting scenario remains held as a wholesale
reference rather than a verified site tariff. Snapshot references record evidence
used; retrieval time does not establish the original publication time.

Energi Data Service permits commercial reuse under CC-BY 4.0 with appropriate
attribution and disclosure of changes. Normalized outputs credit Energinet, disclose
the transformation, and imply no endorsement. See the [official terms](https://www.energidataservice.dk/terms-and-conditions)
and [CC-BY 4.0 license](https://creativecommons.org/licenses/by/4.0/).
Repository examples and tests are independently invented and contain no captured
vendor response data.
