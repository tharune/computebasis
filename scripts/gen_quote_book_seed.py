#!/usr/bin/env python3
"""Regenerate the quote-book seed from the fictional mock provider and quote workbook.

The quote book starts from the workbook's 12 providers and 38 quotes and extends them in
the same shape. Reading the workbook here, rather than at runtime, keeps the service free of
spreadsheet parsing. The workbook is invented test data and is deliberately NOT committed;
only the generated seed is, with the SHA-256 of the exact file it was read from.

    python scripts/gen_quote_book_seed.py WORKBOOK.xlsx          # rewrite the seed from a workbook
    python scripts/gen_quote_book_seed.py --check                # verify the committed seed is intact
    python scripts/gen_quote_book_seed.py --check WORKBOOK.xlsx  # also verify it matches that workbook

Reading a workbook needs `openpyxl`, which is not a repository dependency (pip install openpyxl).
`--check` without a workbook needs nothing: it recomputes the seed's content digest, which
catches hand edits to the generated file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "src" / "compute_pricing" / "control" / "quote_book" / "seed.py"
sys.path.insert(0, str(ROOT / "src"))

# Provider columns: workbook header -> seed key. Tier columns are stored as integers 1..3.
PROVIDER_FIELDS = {
    "Provider ID": "id", "Provider Name": "name", "Legal Entity": "entity", "Jurisdiction": "jurisdiction",
    "Regions Supported": "regions", "DC Locations": "dc_locations", "DC Tier": "dc_tier_claim",
    "SOC 2": "soc2", "ISO 27001": "iso27001", "SLA Uptime %": "sla_uptime", "SLA Remedy": "sla_remedy",
    "Owns or Leases DC": "dc_ownership", "References / Customers": "references",
    "Financial Standing": "financial_standing", "Source": "source", "Notes": "notes",
    "IPMI / OOB Access": "oob_access", "OOB Keys Held By": "oob_keys", "Self-Serve Reimage": "reimage",
    "DC-Ops SLA in Writing (outage, parts, power-cycle)": "dc_ops_sla",
    "Support Response (hrs, in writing)": "support_hours", "Named Support Contact": "named_contact",
    "Owner or Reseller": "kind", "Config Documented": "config_documented",
}
TIER_FIELDS = {"Certification Tier": "certification", "DC Tier Rating": "dc_tier", "SLA Tier": "sla",
               "Delivery Tier": "delivery", "Credit Tier": "credit", "Responsiveness Tier": "responsiveness"}
QUOTE_FIELDS = {
    "Quote ID": "id", "Provider": "provider", "DC Location": "location", "Country": "country",
    "GPU Model": "gpu", "GPUs per Node": "gpus_per_node", "Nodes Available": "nodes", "MOQ (nodes)": "moq",
    "Interconnect": "interconnect", "Cooling": "cooling", "Date Available": "available",
    "Lead Time (wks)": "lead_weeks", "Price / GPU Hr": "price", "Duration (months)": "months",
    "Down Payment %": "down_payment", "Payment Terms (days)": "payment_days", "Status": "status",
    "Date Posted": "posted", "Date Updated": "updated", "Quote Expiry": "expires",
}


def clean(value):
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def table(sheet, fields):
    headers = [cell.value for cell in sheet[2]]
    missing = [name for name in fields if name not in headers]
    if missing:
        raise SystemExit(f"workbook sheet {sheet.title!r} lacks columns: {missing}")
    rows = []
    for values in sheet.iter_rows(min_row=3, values_only=True):
        if values[0] is None:
            continue
        rows.append({headers[i]: values[i] for i in range(len(headers))})
    return rows


def content_digest(providers, quotes) -> str:
    """Digest of the seed rows themselves, independent of how the file is formatted."""
    canonical = json.dumps({"providers": list(providers), "quotes": list(quotes)}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def render(workbook_path: Path) -> str:
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("reading the workbook needs openpyxl (pip install openpyxl)") from None
    workbook = openpyxl.load_workbook(workbook_path, data_only=True)
    providers = []
    for raw in table(workbook["Providers"], {**PROVIDER_FIELDS, **TIER_FIELDS}):
        provider = {key: clean(raw[name]) for name, key in PROVIDER_FIELDS.items()}
        provider["tiers"] = {key: int(str(raw[name]).split()[-1]) for name, key in TIER_FIELDS.items()}
        providers.append(provider)
    quotes = [{key: clean(raw[name]) for name, key in QUOTE_FIELDS.items()} for raw in table(workbook["Quotes"], QUOTE_FIELDS)]
    digest = hashlib.sha256(workbook_path.read_bytes()).hexdigest()
    lines = [
        '"""Providers and quotes copied from a fictional mock workbook. GENERATED, do not edit.',
        "",
        "Regenerate with scripts/gen_quote_book_seed.py WORKBOOK.xlsx. The workbook is not part of this",
        "repository; SOURCE_SHA256 identifies the exact file these rows were read from, and",
        "CONTENT_SHA256 covers the rows below so hand edits are detected. Every name, entity and",
        "figure is invented test data.",
        '"""',
        "from __future__ import annotations",
        "",
        f"SOURCE = {workbook_path.name!r}",
        f"SOURCE_SHA256 = {digest!r}",
        f"CONTENT_SHA256 = {content_digest(providers, quotes)!r}",
        'AS_OF = "2026-10-13"  # the workbook\'s Assumptions as-of date',
        "",
        "PROVIDERS = (",
    ]
    lines += [f"    {provider!r}," for provider in providers]
    lines += [")", "", "QUOTES = ("]
    lines += [f"    {quote!r}," for quote in quotes]
    lines += [")", ""]
    return "\n".join(lines)


def verify_committed_seed() -> list[str]:
    """Problems with the committed seed that need no workbook; empty when it is intact."""
    from compute_pricing.control.quote_book import seed
    problems = []
    if content_digest(seed.PROVIDERS, seed.QUOTES) != seed.CONTENT_SHA256:
        problems.append("CONTENT_SHA256 does not match the rows; the generated seed was edited by hand")
    if len(seed.SOURCE_SHA256) != 64 or set(seed.SOURCE_SHA256) - set("0123456789abcdef"):
        problems.append("SOURCE_SHA256 is not a SHA-256 hex digest")
    names = {provider["name"] for provider in seed.PROVIDERS}
    if len(names) != len(seed.PROVIDERS) or not seed.QUOTES:
        problems.append("provider names must be unique and quotes present")
    unknown = sorted({quote["provider"] for quote in seed.QUOTES} - names)
    if unknown:
        problems.append(f"quotes reference unknown providers: {unknown}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("workbook", nargs="?", type=Path, help="path to the mock workbook (.xlsx), kept outside the repository")
    parser.add_argument("--check", action="store_true", help="verify the committed seed instead of writing it")
    args = parser.parse_args()
    if args.check:
        problems = verify_committed_seed()
        if not problems and args.workbook is not None and SEED.read_text() != render(args.workbook):
            problems.append(f"{SEED.relative_to(ROOT)} differs from {args.workbook.name}; regenerate it")
        for problem in problems:
            print(problem)
        if problems:
            return 1
        print("quote-book seed is intact" + (f" and matches {args.workbook.name}" if args.workbook else ""))
        return 0
    if args.workbook is None:
        parser.error("a workbook path is required to regenerate the seed")
    text = render(args.workbook)
    SEED.write_text(text)
    print(f"wrote {SEED.relative_to(ROOT)}: {text.count(chr(10))} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
