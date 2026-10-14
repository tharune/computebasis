# Backend pricing flow

The backend exposes two distinct flows. Retained references describe permitted
source evidence. The independent book supplies an invented, populated demo.
Selecting a demo quote does not admit it into live market evidence or inventory.
Frontend code can use both flows without copying pricing or settlement formulas.

| Step | API | State and binding |
| --- | --- | --- |
| Populate editable demonstrations | `GET /v1/pricing/demo/contract` | Independent H100/L40S/A4000 cases, exact field paths/types/groups and an unknown-only intake template |
| Assess declared full contracts | `POST /v1/pricing/demo/evaluate` | Exact whole allocation, power and costs once, dated cash, restricted escrow, unfitted tenor/shock sensitivity; immutable synthetic receipt |
| Inspect scenario hardware context | `GET /v1/pricing/demo/references?hardware_model=H100` | Explicit model spelling aliases only; original configurations, ages, currencies and native units remain separate; display does not bind or alter economic caps |
| Download evaluated agreement | `GET /v1/pricing/demo/{snapshot_id}/agreement.pdf` | Authenticated saved demo receipt only, canonical integrity check, unsigned/nonbinding agreement and quote schedule; no source fetch or reevaluation |
| Browse refreshed sources | `GET /v1/market/current`, `GET /v1/market/events` | Shared retained cache, source timestamps, coverage and conditional revisions; clients do not fetch vendors |
| Compare retained evidence | `GET /v1/market/reference/contract`, `POST /v1/market/reference/evaluate` | Exact source scopes, current saved benchmark policy and comparable cohort; server resolves permitted rows |
| Inspect commitment observations | `GET /v1/market/curves` | Observed reservation durations; missing future-start quotes remain gaps |
| Select a simulated supplier | `GET /v1/book` | Independent providers, quote terms and exact ETag; explicit unknown terms and eligibility |
| Explore quality assumptions | `GET /v1/book/policy`, `POST /v1/book/policy/evaluate` | Detached complete policy and before/after preview on the same simulation state |
| Apply a simulation policy | `PUT /v1/book/policy` | Expected integer predecessor revision and increasing version; conflicts do not overwrite newer work |
| Price selected terms | `GET /v1/book/deal/contract`, `POST /v1/book/deal/evaluate` | Exact book ETag, whole nodes, supplier calendar/deposit/net terms, explicit buyer/cost/cash inputs |
| Retrieve a paper result | `GET /v1/decisions/{snapshot_id}` | Immutable submitted input and result; subsequent feed or policy changes cannot rewrite it |
| Assess owned power cost | `GET /v1/power/contract`, `POST /v1/power/evaluate`, `POST /v1/power/from-reference` | Included/unknown ownership, allocated IT/PUE, actual hours and tariff evidence stay distinct |

Read [retained reference semantics](market-reference.md),
[simulation policy controls](book-policy.md),
[quote-to-cash terms](book-deal.md),
[native source coverage](provider-source-coverage.md) and
[browser session integration](backend-frontend-handoff.md).

Automatically refreshed reference observations are not a live buyer order book.
A GPU/VM catalog does not establish capacity, a token tariff does not establish
measured inference goodput, and a reservation discount does not establish a
future-start contract. A GB grid-carbon observation is environmental context in
grams CO₂/kWh. Wholesale power and carbon data are never averaged into compute
prices or silently substituted for a site's all-in tariff.

Use one unit/cohort per comparison and display excluded evidence and exact
coverage alongside the reference. A true market midpoint requires admitted
matching bid and ask sides with adequate size; an ask-only reference has no
buyer bid or midpoint. Margin and cost-recovery floors require declared demand,
collection rates, cost ownership and cash timing. Error bands are not calibrated
confidence intervals. No new route enables execution or authenticates a signed
contract, cleared cash or physical inventory.

Frontend acceptance is explicit: preserve decimal strings, show unknown values
without replacing them with zero, read policy scale and category definitions,
show 409 as a request to refresh/review rather than automatically resubmit, and
keep simulated metrics visibly separate from retained source evidence. The
backend will never repair a UI by inventing an unknown provider score or buyer.
