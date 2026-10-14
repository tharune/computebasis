"""Strict, versioned process-local simulation policy helpers and HTTP routes."""
from copy import deepcopy
from decimal import Decimal, localcontext
import json
import re

from fastapi import Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from compute_pricing.control._numbers import calculation_precision, text_number
from compute_pricing.control.domain import ValidationError
from compute_pricing.control.quote_book.scoring import CATEGORIES, GRADES, validate_assumptions, validate_policy

SCHEMA = "book-policy/1.0"
MAX_REVISIONS = 64
MAX_DOCUMENT_BYTES = 16384


class BookPolicyConflict(ValueError):
    pass


class BookPolicyCapacity(ValueError):
    pass


class BookPolicyNotFound(ValueError):
    pass


def policy_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})\.(?:0|[1-9][0-9]{0,5})", value):
        raise ValidationError("book policy: bounded major.minor.patch version required")
    return tuple(int(part) for part in value.split("."))


def default_document(scorecard=None):
    return {"schema_version": SCHEMA, "policy_id": "independent-simulation", "version": "1.0.0",
            "scorecard": validate_policy(scorecard), "economics": validate_assumptions()}


def validate_document(document):
    if not isinstance(document, dict) or set(document) != {"schema_version", "policy_id", "version", "scorecard", "economics"}:
        raise ValidationError("book policy: complete known document fields required")
    if document["schema_version"] != SCHEMA:
        raise ValidationError("book policy: unsupported schema")
    identity = document["policy_id"]
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,127}", identity):
        raise ValidationError("book policy: bounded canonical identity required")
    policy_version(document["version"])
    try:
        encoded = json.dumps(document, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise ValidationError("book policy: exact JSON document required") from None
    if len(encoded.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise ValidationError("book policy: document budget exceeded")
    if not isinstance(document["scorecard"], dict) or not isinstance(document["economics"], dict):
        raise ValidationError("book policy: explicit scorecard and economics required")
    scorecard = validate_policy(document["scorecard"])
    economics = validate_assumptions(document["economics"])
    if Decimal(economics["deposit_apr"]) > 1:
        raise ValidationError("book policy: deposit APR must be in [0,1]")
    return {"schema_version": SCHEMA, "policy_id": identity, "version": document["version"],
            "scorecard": scorecard, "economics": economics}


def update_payload(payload):
    if not isinstance(payload, dict) or set(payload) != {"expected_revision", "document"}:
        raise ValidationError("book policy: exact expected_revision and document required")
    if type(payload["expected_revision"]) is not int or payload["expected_revision"] < 0:
        raise ValidationError("book policy: nonnegative integer predecessor required")
    return payload["expected_revision"], validate_document(payload["document"])


def comparison(before, after):
    fields = ("grade", "eligible", "risk_adjusted", "risk_adjusted_scorecard",
              "financing", "exposure", "missing_fields", "ineligible_reasons")
    prior = {row["id"]: row for row in before["quotes"]}
    changes = []
    for row in after["quotes"]:
        left = {key: deepcopy(prior[row["id"]][key]) for key in fields}
        right = {key: deepcopy(row[key]) for key in fields}
        if left == right:
            continue
        deltas = {}
        for key in ("risk_adjusted", "risk_adjusted_scorecard", "financing", "exposure"):
            if left[key] is None or right[key] is None:
                deltas[key] = None
            else:
                with localcontext() as context:
                    context.prec = calculation_precision([left[key], right[key]]) + 8
                    deltas[key] = text_number(Decimal(right[key]) - Decimal(left[key]))
        changes.append({"quote_id": row["id"], "before": left, "after": right, "delta": deltas})
    old_providers = {row["id"]: row for row in before["providers"]}
    provider_changes = [{"provider_id": row["id"],
        "before": {key: old_providers[row["id"]][key] for key in ("grade", "score_exact")},
        "after": {key: row[key] for key in ("grade", "score_exact")}}
        for row in after["providers"] if any(old_providers[row["id"]][key] != row[key] for key in ("grade", "score_exact"))]
    summarize = lambda frame: {key: deepcopy(frame[key]) for key in ("kpis", "models", "grade_mix", "field_gaps")}
    return {"before": summarize(before), "after": summarize(after),
            "changed_quotes": len(changes), "quote_changes": changes,
            "changed_providers": len(provider_changes), "provider_changes": provider_changes,
            "alternative_models": ["exposure", "scorecard"], "cost_models_combined": False}


def book_policy_contract():
    return {"schema_version": SCHEMA, "document_fields": ["schema_version", "policy_id", "version", "scorecard", "economics"],
            "write_fields": ["expected_revision", "document"], "default_document": default_document(),
            "scorecard_categories": list(CATEGORIES), "grades": list(GRADES),
            "decimal_encoding": "finite_plain_decimal_strings", "unknown_values_defaulted": False,
            "weights_sum": "1", "deposit_apr_bounds": ["0", "1"],
            "probability_and_recovery_bounds": ["0", "1"], "maximum_revisions": MAX_REVISIONS,
            "maximum_document_bytes": MAX_DOCUMENT_BYTES, "storage": "process_memory_only",
            "preview_advances_time": False, "historical_policy_replay_is_quote_snapshot": False,
            "simulated": True, "source_evidence_eligible": False, "firm_price_eligible": False,
            "execution_enabled": False}


def read_book_policy(book, revision=None):
    return book.read_policy(revision)


def evaluate_book_policy(book, payload):
    expected, document = update_payload(payload)
    return book.evaluate_policy(expected, document)


def update_book_policy(book, payload):
    expected, document = update_payload(payload)
    return book.update_policy(expected, document)


def attach_book_policy(app, *, get_book, authenticated, json_body):
    async def call(function, *args):
        try:
            return await run_in_threadpool(function, *args)
        except BookPolicyConflict:
            raise HTTPException(409, detail="book_policy_revision_conflict") from None
        except BookPolicyCapacity:
            raise HTTPException(409, detail="book_policy_history_capacity") from None
        except BookPolicyNotFound:
            raise HTTPException(404, detail="book_policy_revision_not_found") from None
        except (ValueError, TypeError, ArithmeticError):
            raise HTTPException(422, detail="invalid_book_policy") from None

    @app.get("/v1/book/policy/contract", dependencies=[Depends(authenticated)])
    async def contract():
        return book_policy_contract()

    @app.get("/v1/book/policy", dependencies=[Depends(authenticated)])
    async def current():
        return await call(read_book_policy, get_book())

    @app.get("/v1/book/policy/revisions/{revision}", dependencies=[Depends(authenticated)])
    async def historical(revision: int):
        return await call(read_book_policy, get_book(), revision)

    @app.post("/v1/book/policy/evaluate", dependencies=[Depends(authenticated)])
    async def preview(request: Request):
        return await call(evaluate_book_policy, get_book(), await json_body(request))

    @app.put("/v1/book/policy", dependencies=[Depends(authenticated)])
    async def update(request: Request):
        return await call(update_book_policy, get_book(), await json_body(request))
