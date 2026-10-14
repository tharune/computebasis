# Workspace workflows

ComputeBasis opens a loopback browser session automatically. A short-lived
HttpOnly Strict cookie identifies the session; a page-memory CSRF token protects
permitted mutations. Exact origin, host and Fetch Metadata checks bind browser
access to the configured local service. This is development convenience, not
enterprise identity. Ending the session clears received data, fields, drafts and
results. Explicit machine clients can use a separate bearer key.

The backend reads approved public GET scopes at startup and at configured
intervals while the application runs. Concurrent requests for the same scope
share one worker; cooldowns, admission checks and retry backoff apply. No operating
system jobs are installed. The browser synchronizes retained evidence and status
every minute without replacing drafts or silently repricing a decision.

## Working through a candidate

1. **Overview and Markets:** inspect current source coverage, timestamps and native
   economic units. Global advertised cohorts, regional meters, model catalogs,
   token rates and FX have distinct roles. Overlapping records are not independent
   capacity. Financial or event-contract marks do not become GPU prices by averaging.
2. **Inventory:** declare physical sites, unit identities and supply/commitment
   intervals. Sold, reserved and maintenance positions consume units only in their
   intervals. Unknown coordinates stay unmapped. A listing never creates a holding.
3. **Underwriting:** derive required subjects and typed factors from the versioned
   catalog. Claims need identity, units, validity, evidence and permitted use.
   Checklist completeness does not authenticate the artifacts or estimate credit.
4. **Pricing:** supply buyer/supplier terms, cost ownership, collection/fee fractions,
   margin basis, ticks and full dated funding. Compare the economic, market,
   explicit-stress and cash bid caps. Selling floors and bid ceilings remain
   indicative and depend on the submitted evidence and assumptions.
5. **Inference:** match model/runtime/version, precision, quantization, parallel
   deployment, workload and SLO to measured whole-deployment goodput. Count goodput
   once and cost all allocated GPUs, including idle time. Optional pricing policy
   produces expected-cost, economic and required-margin task floors, a proportional
   upward-ticked rate vector at one declared token mix, and qualified-capacity
   crossover diagnostics. Explicit routed operating items are required for an
   all-in comparison; missing items are not zero platform cost.
6. **Cash and Portfolio:** reconcile one full cash/facility account, global physical
   ledger and baseline-plus-candidate limits across inference, resale and future
   delivery. Assign cash events and exposures once. Retain idle/unallocated supply
   cost. Operating contribution and economic profit are **before financing** unless
   those charges are explicitly attributed; shared cash includes supplied facility
   flows and cannot treat financing proceeds as revenue.
7. **Policies:** version source weights, recency, support, concentration and feature
   ownership. Custom fields remain visible. A supported independently validated
   owning model is required before a critical factor can affect money.

## Exact inputs

Structured inputs begin blank. Money and registered decimal/integer evidence
remain exact strings; JSON count fields remain bounded integer literals. Null,
zero and false are distinct. Additional fields preserve their supplied meaning;
they do not become arbitrary pricing multipliers. Large or specialized packets
remain editable in advanced JSON.

Reading JSON into fields rejects duplicate keys, lossy numeric literals and
reserved keys. Editing stale controls cannot overwrite a changed advanced draft.
Reset inputs is an explicit unsaved-draft action; it does not delete stored
inventory or snapshots. Evaluation submits the original JSON bytes and preserves
an immutable response. Later edits mark the result as previous input. Expired
read sessions may renew once; mutations are never automatically replayed.

See [source admission](source-adapters.md), [session/refresh behavior](local-session-refresh.md),
[underwriting](underwriting-assessment.md), [shared portfolio](portfolio-and-inference-diagnostics.md)
and [durable paper controls](durable-paper-controls.md).

## Operating boundary

Public price feeds cannot supply signed contract rights, cleared bank assets,
supplier credit, buyer demand, privacy acceptance or measured workload quality.
Local paper controls execute nothing. Firm pricing, actual rails and volume need
authoritative identity, shared transactional holds, independently accepted models,
enforceable terms, qualified delivery and witnessed accounting/recovery evidence.
Future localization, tail models and allocation optimizers remain separate
research and approval work; no default regional premium, loss probability or
confidence interval is fabricated.
