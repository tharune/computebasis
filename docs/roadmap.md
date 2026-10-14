# Build roadmap

The initial release demonstrates configurable arithmetic against synthetic inputs. Live pricing and execution remain future work. Each task requires evidence beyond a working example.

| Task | Deliverable | Acceptance |
| --- | --- | --- |
| CB-01 | Typed input contract and feature registry | Units, currency, dates, null/zero and extensions have explicit behavior; schemas are versioned. |
| CB-02 | Evidence and observation store | Values, normalization lineage, timestamps and rights survive ingestion; reimport does not duplicate offers. |
| CB-03 | Read-only source adapters | Permitted access, pagination, quotas, retries, schema changes and staleness are tested without transaction permissions. |
| CB-04 | Comparable benchmark pipeline | Product cohorts, deduplication, source concentration, outliers and final normalized weights are explainable; insufficient support is visible. |
| CB-05 | Configuration and regional adjustment research | Estimates pass time and provider holdouts, common-support checks and sensitivity tests; unsupported extrapolation is held. |
| CB-06 | Daily contract cash and capacity schedules | Actual calendars, invoice lags, restricted advances, refunds and obligations reconcile; concurrent allocations cannot oversell. |
| CB-07 | Risk-aware bid/ask solver | Credit and performance losses have distinct owners; price-dependent costs, funding limits and tick rounding reconcile under downside scenarios. |
| CB-08 | Workload-specific inference economics | Measured goodput, latency, memory, quantization and whole-replica idle costs support comparisons with routed services. |
| CB-09 | Reproducible workbench and validation | Every result links to inputs and versions; meaningful updates recalculate results; independent validation covers enabled models. |

Start with CB-01 and the evidence contract before parallel adapter/model work. Daily cash scheduling can use declared synthetic terms while source admission proceeds. Publish uncertainty after calibration and validation.

Later research includes forward capacity contracts, hedging basis risk and financing receivables. These require observed outcomes, actual instrument or lender terms and applicable permissions. They are not active features.
