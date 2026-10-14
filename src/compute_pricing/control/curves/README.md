# Curves whose labels match their evidence

The module provides contract arithmetic and a separate display of advertised
commitment references. Both keep actual dates, exact decimal strings, native
price units and explicit source scopes. Neither verifies available hardware,
offers a tradable forward or estimates a derivative hedge ratio.

`term_curve_contract()` describes the input to `evaluate_term_curve_payload()`.
One declared cohort specifies hardware, configuration, location, currency,
payment/cost/capacity scope, delivery start and GPU count. Every node must repeat
that exact cohort and declare its quote time, exclusive end date, rate, GPU count,
billable GPU-hours and reference. Current arithmetic requires explicitly stated
24x7 UTC calendar service and undiscounted nominal contract cashflows. Discounted
values, different payment schedules, starts or utilization assumptions require
separate models instead of being silently combined.

Actual calendar days determine the hours check: January and leap February have
different durations. There is no fixed month-hour constant. A whole-contract
average is shown separately from the amount difference divided by the incremental
hours between nested ends. The latter is arithmetic between independent bundle
quotes; it does not create the right to cancel one contract or trade only its
implied future interval. Different quote timestamps, stale quotes and negative
amount increments hold interval use. Missing requested tenors remain missing;
the module creates no interpolated or extrapolated prices.

`observed_commitment_curves()` receives the server's current retained market
index. The initial transform recognizes GetDeploying weekly provider-median
advertised GPU-hour aggregates and their native reservation-month labels. It
requires current admitted rights, matching retained-summary references, fresh
capture and event times, complete Monday-start weeks and the documented USD
conversion basis. A new download cannot make an old event period current.

Sources, adapter versions, weeks, models, currencies and billing scopes remain
separate. Unknown machine configuration and location are not localized or
converted into qualified capacity. Reservation months do not specify a delivery
start, exact calendar or billable GPU-hours, so advertised marks produce no
total contract amounts or implied interval rates. Conflicting observations
quarantine the selected rate; duplicate references do not sum provider counts
or become estimator weights. The output carries bounded references and explicit
coverage/truncation, without raw vendor records.

The index must be obtained internally by the API. Shape and freshness checks
here do not authenticate an arbitrary posted replacement index. All results
remain unverified, uncalibrated, ineligible for firm pricing and nonexecuting.
