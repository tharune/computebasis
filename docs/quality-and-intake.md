# Table intake and verification

This release bounds concurrent collection
and makes workbook intake extensible without turning source cells into approved
pricing facts. It retains the existing public-source admission, immutable
snapshots, Decimal arithmetic and read-only/paper limits.

## Schema-neutral local evidence

`compute_pricing.control.ingest.tabular.extract_table` accepts caller-selected workbook bytes,
worksheet and header row. No field list, quote count, expected provider count,
country map, source price or issuer name is embedded in the neutral extractor.
It retains arbitrary text headers, data under blank headers, blank/zero/boolean
distinctions and stored numeric text without a float round trip. Formulas are
preserved separately from cached text; neither becomes a qualified value.

```python
from pathlib import Path
from compute_pricing.control.ingest.tabular import extract_table

result = extract_table(Path("local-evidence.xlsx").read_bytes(),
                       sheet_name="Your selected worksheet", header_row=1)
```

The caller is responsible for authorized local evidence and storage outside Git.
This is a pure library operation, with no upload route, vendor request, automatic
persistence or execution. The content hash is deterministic for the selected
stored table. Currency, units, timezone, counterparty meaning and pricing
eligibility require an explicit later mapping and evidence review. Observe and
retain rights remain `UNKNOWN` for arbitrary caller-supplied bytes; local
processing does not assert redistribution rights. Benchmark and execution
permissions remain `FAIL`.

The reader rejects duplicate ZIP member names, ambiguous relationships and
incorrect typed XML roots in addition to its existing archive, XML declaration,
grid, style, formula and numeric limits. An encoding-aware scan checks cell and
XML-element budgets before constructing worksheet trees. The neutral path also
caps cumulative stored cells across every workbook sheet at 100,000, including
unselected sheets. Conflicting cell payloads are refused. Individual text fields
are bounded, and streamed hashing enforces a 4 MiB serialized-table budget to
prevent repeated shared strings from amplifying output. Table budgets refuse excessive rows,
columns or rectangular expansion instead of silently emitting partial tables.
Independent invented ZIP tests cover refusal and exact-value boundaries.
See [third-party notices](third-party-notices.md).

## Verification

Offline validation now requires Python 3.12 and Node 24 for the dependency-free
frontend behavior suite. Node is a test dependency; serving the browser assets
requires no JavaScript build or npm installation. Supply `COMPUTEBASIS_NODE` only
when Node is not on PATH. Public Actions remain disabled; contributors run the entire offline suite locally.

Frontend behavior tests execute actual handlers against an invented DOM/API
harness. They complement HTTP/security checks; they do not establish visual
browser quality. Where loopback navigation is blocked by the browser automation
environment, document that limitation instead of bypassing it.

The local service remains development persistence and auth. Institutional
execution still needs transactional financial journals, identity/roles,
calibrated risk inputs and independent recovery/security acceptance.
