# Quote-to-deal backend flow

`GET /v1/book/deal/contract` returns an empty explicit input contract.
`POST /v1/book/deal/evaluate` evaluates one independently simulated supplier
quote, saves an immutable paper receipt and returns its supplier cash path.
Both endpoints require the same local authentication as the rest of the desk.
Browser writes require the origin-bound session and CSRF token.

Read `GET /v1/book`, select a quote with `eligible: true`, and retain its exact
ETag as `book_revision`. Supply `quote_id`, a whole integer `nodes` that meets
the supplier MOQ and quoted maximum, and every buyer, operating-cost, cash and
settlement input in the contract. No buyer, utilization, collection rate or bank
balance is automatically supplied. A changed book or policy returns HTTP 409;
reload the selected quote and explicitly reevaluate. A held quote returns 422.

The server binds price, USD/GPU-hour unit, GPU model, GPUs per node, location,
country, term, delivery start, deposit fraction and net days from the book.
Client overrides of these terms are rejected. The contract ends at the clipped
calendar anniversary of the stated months, including leap days. Purchased
GPU-hours equal selected nodes times GPUs per node times actual UTC hours.
The buyer's billed utilization affects revenue only. Unsold time still incurs
the full supplier commitment.

The caller must explicitly choose `single_full_contract_invoice` and provide
its invoice date. This narrow billing scenario treats down payment as a fraction
of the full supplier contract value, paid on `deposit_on`, then applied to that
invoice once. The remaining balance is due invoice date plus the quoted net
calendar days. Bank holidays, cutoffs and monthly billing are not inferred.
Zero deposit creates no prepaid event; full deposit creates no duplicate final
cash payment. Supplier cost recognition occurs once at delivery completion.
Same-day outgoing cash precedes buyer receipts conservatively. Settlements must
fit the bounded ten-year scenario horizon.

The receipt includes `book_binding`, selected supplier terms, exact submitted
assumptions, the original revision, supplier balance due date, an input digest,
cost-recovery and margin-floor diagnostics, and
`scenario_supplier_cash_schedule`. The latter shows actual supplier-ask cash,
its minimum/date, unresolved liabilities and extra funding required. It is
separate from the searched purchase-cap cash path.

Scoring premiums, loss scenarios and deposit APR are not automatically added to
this native cash ledger. Owned operating, power, network and servicing costs
must be supplied once in the caller's explicit cost assumption. The invented
book anchor remains display-only. The result is held for admitted market pricing,
contains no usable submitted bid, and cannot reserve inventory, execute a trade,
move cash or prove actual buyer demand. Updating the book cannot rewrite a saved
receipt. Frontend owners can adopt these endpoints without reproducing ledger
or calendar arithmetic in JavaScript.

After installation, `python scripts/book_deal_example.py` runs one opt-in
independently invented scenario offline, checks final liability settlement and
prints the selling floor and funding gap. Its invented buyer and cash inputs
demonstrate mechanics and are never loaded automatically by the API.
