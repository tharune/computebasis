"""One declarative contract source for runtime, JSON Schema and UI types."""
from __future__ import annotations

SCHEMA_VERSION = "1.0.0"
ID_PATTERN = r"^[a-z][a-z0-9]*(?:[._:/-][a-z0-9]+)*$"
DECIMAL_PATTERN = r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"
UTC_PATTERN = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
VERSION_PATTERN = r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
GATES = ("PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE")
STATUSES = ("claimed", "verified", "stale", "rejected")
PRICE_UNITS = ("gpu_hour", "node_hour", "token", "input_million_tokens", "output_million_tokens", "contract")
OWNING_PATHS = ("price", "cost", "loss", "constraint", "diagnostic")
MARKET_KINDS = ("listing_ask", "firm_supplier_rfq", "confirmed_rental_trade", "buyer_bid", "aggregate_advertised_index", "model_token_price", "financial_future_mark", "event_contract_price")


def string(*, nullable=False, pattern=None, enum=None, maximum=512):
    result = {"type": ["string", "null"] if nullable else "string", "maxLength": maximum}
    if pattern:
        result["pattern"] = pattern
    if enum:
        result["enum"] = list(enum) + ([None] if nullable else [])
    return result


def decimal(*, nullable=False, minimum=None, maximum=None):
    pattern = DECIMAL_PATTERN if minimum is None or minimum < 0 else r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$"
    result = string(nullable=nullable, pattern=pattern, maximum=128)
    result["x-decimal"] = True
    if minimum is not None:
        result["x-decimal-minimum"] = str(minimum)
    if maximum is not None:
        result["x-decimal-maximum"] = str(maximum)
    return result


def identity(*, nullable=False):
    return string(nullable=nullable, pattern=ID_PATTERN, maximum=128)


def instant(*, nullable=False):
    result = string(nullable=nullable, pattern=UTC_PATTERN, maximum=32)
    result["format"] = "date-time"
    return result


def version():
    return string(pattern=VERSION_PATTERN, maximum=40)


def reference(name, *, nullable=False):
    ref = {"$ref": f"#/$defs/{name}"}
    return {"anyOf": [ref, {"type": "null"}]} if nullable else ref


def array(item):
    return {"type": "array", "items": item, "maxItems": 10000}


def object_contract(properties, required):
    return {"type": "object", "properties": {**properties, "extensions": {"type": "object", "additionalProperties": True}}, "required": list(required), "additionalProperties": False}


SPECS = {
    "Permission": object_contract({
        "status": string(enum=("allowed", "pending", "denied")),
        "observe": string(enum=GATES), "retain": string(enum=GATES),
        "benchmark": string(enum=GATES), "execution": string(enum=GATES),
        "verified_by": identity(nullable=True), "scope": array(string()),
        "expires_at": instant(nullable=True),
    }, ("status",)),
    "EvidenceRef": object_contract({
        "id": identity(), "source_id": identity(),
        "artifact_sha256": string(nullable=True, pattern=r"^[a-f0-9]{64}$", maximum=64),
        "locator": string(nullable=True, maximum=2048), "event_at": instant(nullable=True),
        "accessed_at": instant(), "verifier": identity(nullable=True),
        "status": string(enum=STATUSES), "scope": array(string()),
        "expires_at": instant(nullable=True), "permission": reference("Permission", nullable=True),
    }, ("id", "source_id", "accessed_at")),
    "MoneyRate": object_contract({
        "amount": decimal(minimum=0), "currency": string(pattern=r"^[A-Z]{3}$", maximum=3),
        "unit": string(enum=PRICE_UNITS),
    }, ("amount", "currency", "unit")),
    "Hardware": object_contract({
        "model": string(nullable=True), "accelerator_count": decimal(nullable=True, minimum=0),
        "memory_gib": decimal(nullable=True, minimum=0),
    }, ()),
    "Region": object_contract({
        "country_code": string(nullable=True, pattern=r"^[A-Z]{2}$", maximum=2),
        "subdivision": string(nullable=True), "locality": string(nullable=True),
    }, ()),
    "Configuration": object_contract({
        "cpu_cores": decimal(nullable=True, minimum=0), "ram_gib": decimal(nullable=True, minimum=0),
        "storage_gib": decimal(nullable=True, minimum=0), "network_gbps": decimal(nullable=True, minimum=0),
        "interconnect": string(nullable=True), "privacy_class": string(nullable=True),
        "tenancy": string(nullable=True),
    }, ()),
    "MarketObservation": object_contract({
        "schema_version": version(), "id": identity(), "source_id": identity(), "source_version": string(nullable=True),
        "offer_id": identity(nullable=True), "lot_id": identity(nullable=True), "provider_group_id": identity(nullable=True),
        "kind": string(enum=MARKET_KINDS), "price_side": string(enum=("ask", "bid", "trade", "mark"), nullable=True),
        "price": reference("MoneyRate", nullable=True), "hardware": reference("Hardware", nullable=True),
        "region": reference("Region", nullable=True), "configuration": reference("Configuration", nullable=True),
        "quantity": decimal(nullable=True, minimum=0), "quantity_unit": string(enum=("gpu", "node"), nullable=True),
        "starts_at": instant(nullable=True), "ends_at": instant(nullable=True),
        "observed_at": instant(), "ingested_at": instant(), "expires_at": instant(nullable=True),
        "status": string(enum=STATUSES), "rights": reference("Permission", nullable=True),
        "evidence": array(reference("EvidenceRef")),
    }, ("id", "source_id", "kind", "observed_at", "ingested_at")),
    "FeatureDefinition": object_contract({
        "feature_id": identity(), "value_type": string(enum=("decimal", "integer", "string", "boolean")),
        "unit": string(nullable=True), "owning_path": string(enum=OWNING_PATHS), "owner_model": identity(),
        "required": {"type": "boolean"}, "minimum": decimal(nullable=True), "maximum": decimal(nullable=True),
        "allowed_values": array(string()),
    }, ("feature_id", "value_type", "owning_path", "owner_model")),
    "FeatureObservation": object_contract({
        "feature_id": identity(), "value": {"type": ["string", "boolean", "null"]}, "unit": string(nullable=True),
        "status": string(enum=("known", "missing", "stale", "conflicted")),
        "valid_from": instant(nullable=True), "valid_until": instant(nullable=True),
        "transform_id": identity(nullable=True), "owner_model": identity(nullable=True),
        "owning_path": string(enum=OWNING_PATHS, nullable=True), "evidence": array(reference("EvidenceRef")),
    }, ("feature_id", "status")),
    "FeatureOwnership": object_contract({
        "feature_id": identity(), "owning_path": string(enum=OWNING_PATHS), "owner_model": identity(),
    }, ("feature_id", "owning_path", "owner_model")),
    "NormalizedPrice": object_contract({
        "observation_id": identity(), "source_id": identity(), "lot_id": identity(nullable=True),
        "source_price": reference("MoneyRate"), "normalized_price": reference("MoneyRate"),
        "normalization_steps": array(string()), "status": string(enum=("indicative", "comparable", "rejected", "unknown")),
        "blockers": array(string()), "model_version": string(), "policy_version": version(),
        "feature_ownership": array(reference("FeatureOwnership")),
    }, ("observation_id", "source_id", "source_price", "normalized_price", "model_version", "policy_version")),
    "PolicySnapshot": object_contract({
        "schema_version": version(), "policy_id": identity(), "version": version(), "model_version": string(),
        "registry_version": version(), "effective_at": instant(), "expires_at": instant(nullable=True),
        "critical_market_fields": array(string()), "critical_feature_ids": array(identity()),
        "parameters": {"type": "object", "additionalProperties": True},
    }, ("policy_id", "version", "model_version", "registry_version", "effective_at")),
    "PricingRequest": object_contract({
        "schema_version": version(), "request_id": identity(), "as_of": instant(),
        "observations": array(reference("MarketObservation")), "features": array(reference("FeatureObservation")),
        "policy": reference("PolicySnapshot"), "normalized_prices": array(reference("NormalizedPrice")),
    }, ("request_id", "as_of", "observations", "policy")),
}

DEFAULTS = {
    "Permission": {"observe": "UNKNOWN", "retain": "UNKNOWN", "benchmark": "UNKNOWN", "execution": "UNKNOWN"},
    "EvidenceRef": {"status": "claimed"}, "MarketObservation": {"schema_version": SCHEMA_VERSION, "status": "claimed"},
    "FeatureDefinition": {"required": False}, "NormalizedPrice": {"status": "unknown"},
    "PolicySnapshot": {"schema_version": SCHEMA_VERSION}, "PricingRequest": {"schema_version": SCHEMA_VERSION},
}
