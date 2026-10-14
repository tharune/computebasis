# Draft compute-services agreement and quote schedule

The three pricing demonstrations can produce a populated PDF from their saved,
evaluated receipt. This is an independently authored **compute-services master
agreement plus quote schedule**. It uses no financial-market master agreement
form or third-party contract template.

Every page states **NONBINDING - UNSIGNED - SIMULATED**. The default examples use invented
supplier, buyer and colocation party labels. Edited supplier and buyer labels
bind to the evaluated receipt and appear as escaped text in its document; evaluated inputs are scenario
assumptions, not verified assets, executed contracts or authorized signature
instructions. Governing law, courts, signature authority, detailed remedies and
legal approval remain unresolved. Downloading creates no reservation, payment,
collateral transfer, escrow, financing commitment or trade.

## What the schedule records

The schedule binds the demonstrated hardware model, whole nodes and GPU count,
service location and colocation assumptions, service window, native price basis,
fixed and variable cost ownership, power ownership and billing/settlement basis.
It preserves explicit SLA, response and credit-protection assumptions and marks
unknown terms as unresolved. Collateral, escrow, vesting and yield are separate
owned assumptions; a grade or financing rate does not invent any of these rights.

The economic supplement presents the evaluated contribution, funding and return
diagnostics with their declared denominators and timing basis. Supplier
prepayment, invoice application, balance settlement and expense recognition are
separate; applying a prepayment does not pay or expense it again. Deposits are
not profit or yield. Inference utilization and buyer collection assumptions are
not actual buyer commitments.

Financial totals are display-rounded where identified; long computed rate
results show `~` before their rounded display rather than spilling into the
schedule. The canonical
receipt preserves exact evaluated values. Reported NPV, IRR or scenario yield
is a modeled diagnostic, not a promised return or a verified market rate. An
unmodeled ownership term remains visibly unresolved rather than inheriting a
default counterparty or guessed percentage.

## Rendering and receipt boundary

`render_agreement_pdf(receipt)` returns PDF bytes from a saved snapshot envelope:
`snapshot_id`, `created_at` and `document` containing its versioned input, output
and model versions. The renderer verifies the canonical document digest, accepts
only the demo-pricing snapshot kind and requires the synthetic, nonexecuting
evaluation boundary. The document displays its receipt identifier, evaluation
date and model version so its commercial assumptions can be traced to the saved
decision. It does not display raw payloads, credentials, hidden extensions,
customer contact records, filesystem paths or arbitrary HTML/templates.

The local authenticated download route reads the existing saved snapshot.
It performs no live feed calls and does not recompute a changed scenario during
download. Changes need a new evaluated receipt and a new document. The renderer
uses built-in fonts, escapes values as text and loads no external asset or URL.

Generated PDFs and visual-review images belong outside Git. The repository
contains the fresh renderer, contract tests and this description only. The three
demonstration PDFs are intended for review of the application flow, and remain
unsigned drafts throughout.
