# Durable local paper controls

`compute_pricing.control.execution.DurablePaperRepository` adds bounded SQLite
restart and retry handling to the existing paper-only decision state machine.
Every result declares `paper_only: true` and `execution_enabled: false`. It has
no dispatch worker, venue, wallet, lease, payment adapter or externally executing
HTTP route. The in-memory `PaperJournal` remains available separately.

The caller supplies the reviewed decision snapshot and explicit actor assertions.
Its hash binds amount/currency, proposer, as-of/expiry, economic inputs and
schema/policy/model/data versions. Authority is checked against those declared
values. The library does not authenticate people or establish the truth of bank,
capacity, credit or legal evidence. Economic viability cannot itself establish
funding, delivery rights or a mandate.

## Persistence and retry contract

Create the repository at an absolute nonsymlink SQLite file path outside every
Git checkout. The file is private to its owner (0600). Each `apply` uses
`BEGIN IMMEDIATE` and `synchronous=FULL`, replaying the complete command chain
before atomically writing its new command, historical receipt and paper leg
records. Separate instances serialize claims on the same canonical hold ID.
Different strings for the same economic resource require upstream identity
resolution; the repository cannot infer that equivalence.

`apply(command_id=..., intent_id=..., operation=..., payload=...,
expected_revision=...)` supports `create`, `hold`, `approve`, `submit_paper`,
`mark_unknown`, `reconcile` and `cancel`. Creation starts at revision zero;
committed commands advance the intent revision. A stale revision fails. The
same command ID and canonical request returns exactly its original receipt,
including after restart or intervening commands. A changed request under the
same command ID fails. Read `get(intent_id)` for current state; a retry receipt
is deliberately a historical acknowledgement.

Replay verifies ordered sequence, the linked SHA-256 command/receipt chain,
canonical requests, deterministic receipts, resource ownership and the complete
stored outbox. Triggers disallow command-row updates/deletion. Detected drift
fails recovery. This detects inconsistent local state; it is not an external
signature, and an administrator who replaces the database and recomputes its
history remains outside the trust boundary.

Limits are 2,000 commands, 32 MiB of command/receipt content, 256 KiB per encoded
command or receipt, 24 levels and 20,000 nodes per JSON tree. Floating-point
money is rejected. New writes fail at capacity until a reviewed migration or
archival workflow exists. Bounded full replay is a development design, not a
high-volume institutional architecture.

## Uncertainty and held resources

Submission generates deterministic item IDs from intent and leg identity,
binding each simulated item to the original snapshot hash. `pending_outbox`
returns at most 100 pending/unknown items with a total and truncation flag.
`dispatch_supported` is always false. These rows are audit artifacts, not a
queue connected to a trading or payment system.

Unknown outcomes survive restart and retain every hold. A proposer cannot
locally cancel a submitted or uncertain effect. An independent reconciler must
have matching currency/amount authority, cover every leg with named evidence,
and report a time at or after submission. Previously known matched/failed
outcomes cannot be overwritten by ordinary follow-up reconciliation. Correcting
authoritative evidence needs a separately designed correction workflow.

No hold may be released while any outcome is unknown. Once every outcome is
known, only explicitly named owned holds are released; matched capacity can
remain held for subsequent delivery. Mixed outcomes stay visible. SQLite
rollback rolls back local records, and never establishes reversal of an
external economic effect. Completion, compensation, refunds and later release
require their own independently approved lifecycle.

## Verification and production boundary

[The independent invented scenarios](../tests/test_durable_paper_repository_v7.py)
exercise restart/historical idempotency, concurrent instances, stale revisions,
proposer/amount/currency separation, version/expiry invalidation, deterministic
bounded outbox, unknown-state retention, scoped independent reconciliation,
known-outcome protection, failure after command insertion, append-only triggers,
drift detection, private permissions and invalid input. All are offline and
contain newly invented identities, dates and amounts.

Production still requires authenticated and revocable mandates, authoritative
cash/capacity/accounting transactions, certified per-rail adapters, source and
settlement reconciliation, constrained compensations, incident authority,
replication, backup/restore and witnessed recovery with measured RPO/RTO.
Passing these local tests cannot establish those operating guarantees.
