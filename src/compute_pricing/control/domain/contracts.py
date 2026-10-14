"""Validated compute contracts. Values are claims, never execution authority.

Financial numbers cross the boundary as exact decimal strings. Missing values
remain null. Unknown intake fields are preserved in explicit extensions, which
the pricing engine must not consume without a registered feature owner.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, fields
from datetime import datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Mapping

from .spec import DEFAULTS, SCHEMA_VERSION, SPECS


class ValidationError(ValueError):
    """Invalid domain shape or an ambiguous input; messages omit raw values."""


def utc_instant(value: str) -> datetime:
    _validate_value(value, SPECS["MarketObservation"]["properties"]["observed_at"], "timestamp")
    return datetime.fromisoformat(value[:-1] + "+00:00")


def exact_decimal(value: str, *, nonnegative: bool = False) -> Decimal:
    from .spec import decimal
    _validate_value(value, decimal(minimum=0 if nonnegative else None), "decimal")
    return Decimal(value)


def _encode(value: Any) -> Any:
    if isinstance(value, Record):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(item) for item in value]
    return value


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _check_json(value: Any, path: str, *, depth: int = 0) -> None:
    if depth > 32:
        raise ValidationError(f"{path}: JSON nesting exceeds limit")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError(f"{path}: nonfinite raw JSON value")
        return
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValidationError(f"{path}: JSON object keys must be strings")
        for key, item in value.items():
            _check_json(item, f"{path}.{key}", depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _check_json(item, path, depth=depth + 1)
        return
    raise ValidationError(f"{path}: JSON value required")


def _validate_value(value: Any, spec: dict, path: str) -> None:
    if "anyOf" in spec:
        if value is None:
            return
        return _validate_value(value, spec["anyOf"][0], path)
    if "$ref" in spec:
        return _validate_object(spec["$ref"].split("/")[-1], value, path)
    allowed = spec.get("type", ())
    allowed = (allowed,) if isinstance(allowed, str) else allowed
    if value is None:
        if "null" not in allowed:
            raise ValidationError(f"{path}: null is not allowed")
        return
    if isinstance(value, bool):
        actual = "boolean"
    elif isinstance(value, str):
        actual = "string"
    elif isinstance(value, Mapping):
        actual = "object"
    elif isinstance(value, (list, tuple)):
        actual = "array"
    else:
        actual = "number"
    if actual not in allowed:
        raise ValidationError(f"{path}: wrong value type")
    if "enum" in spec and value not in spec["enum"]:
        raise ValidationError(f"{path}: unsupported value")
    if actual == "string":
        if len(value) > spec.get("maxLength", 10000):
            raise ValidationError(f"{path}: string exceeds limit")
        if "pattern" in spec and not re.fullmatch(spec["pattern"], value):
            raise ValidationError(f"{path}: invalid canonical format")
        if spec.get("format") == "date-time":
            try:
                datetime.fromisoformat(value[:-1] + "+00:00")
            except ValueError as exc:
                raise ValidationError(f"{path}: invalid calendar timestamp") from exc
        if spec.get("x-decimal"):
            number = Decimal(value)
            if "x-decimal-minimum" in spec and number < Decimal(spec["x-decimal-minimum"]):
                raise ValidationError(f"{path}: value below allowed bound")
            if "x-decimal-maximum" in spec and number > Decimal(spec["x-decimal-maximum"]):
                raise ValidationError(f"{path}: value above allowed bound")
    elif actual == "array":
        if len(value) > spec.get("maxItems", 10000):
            raise ValidationError(f"{path}: too many items")
        for item in value:
            _validate_value(item, spec["items"], path)
    elif actual == "object":
        _check_json(value, path)


def _validate_object(name: str, raw: Any, path: str) -> None:
    if not isinstance(raw, Mapping):
        raise ValidationError(f"{path}: object required")
    spec = SPECS[name]
    unknown = set(raw) - set(spec["properties"])
    if unknown:
        raise ValidationError(f"{path}: unknown fields must be retained as extensions")
    for key in spec["required"]:
        if key not in raw:
            raise ValidationError(f"{path}.{key}: required field missing")
    for key, value in raw.items():
        _validate_value(value, spec["properties"][key], f"{path}.{key}")


class Record:
    def to_dict(self) -> dict[str, Any]:
        return {item.name: _encode(getattr(self, item.name)) for item in fields(self)}

    def __post_init__(self) -> None:
        name = type(self).__name__
        raw = self.to_dict()
        _validate_object(name, raw, name)
        for item in fields(self):
            value = getattr(self, item.name)
            spec = SPECS[name]["properties"][item.name]
            ref = spec.get("$ref")
            if "anyOf" in spec:
                ref = spec["anyOf"][0].get("$ref")
            if value is not None and ref and not isinstance(value, RECORDS[ref.split("/")[-1]]):
                raise ValidationError(f"{name}.{item.name}: typed record required; use parser")
            if spec.get("type") == "array" and "$ref" in spec["items"]:
                expected = RECORDS[spec["items"]["$ref"].split("/")[-1]]
                if any(not isinstance(child, expected) for child in value):
                    raise ValidationError(f"{name}.{item.name}: typed records required; use parser")
            if isinstance(value, (Mapping, list, tuple)):
                object.__setattr__(self, item.name, _freeze_json(value))
        _validate_relations(self)


@dataclass(frozen=True)
class Permission(Record):
    status: str
    observe: str = "UNKNOWN"
    retain: str = "UNKNOWN"
    benchmark: str = "UNKNOWN"
    execution: str = "UNKNOWN"
    verified_by: str | None = None
    scope: tuple[str, ...] = ()
    expires_at: str | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceRef(Record):
    id: str
    source_id: str
    accessed_at: str
    artifact_sha256: str | None = None
    locator: str | None = None
    event_at: str | None = None
    verifier: str | None = None
    status: str = "claimed"
    scope: tuple[str, ...] = ()
    expires_at: str | None = None
    permission: Permission | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MoneyRate(Record):
    amount: str
    currency: str
    unit: str
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Hardware(Record):
    model: str | None = None
    accelerator_count: str | None = None
    memory_gib: str | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Region(Record):
    country_code: str | None = None
    subdivision: str | None = None
    locality: str | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Configuration(Record):
    cpu_cores: str | None = None
    ram_gib: str | None = None
    storage_gib: str | None = None
    network_gbps: str | None = None
    interconnect: str | None = None
    privacy_class: str | None = None
    tenancy: str | None = None
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketObservation(Record):
    id: str
    source_id: str
    kind: str
    observed_at: str
    ingested_at: str
    schema_version: str = SCHEMA_VERSION
    source_version: str | None = None
    offer_id: str | None = None
    lot_id: str | None = None
    provider_group_id: str | None = None
    price_side: str | None = None
    price: MoneyRate | None = None
    hardware: Hardware | None = None
    region: Region | None = None
    configuration: Configuration | None = None
    quantity: str | None = None
    quantity_unit: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    expires_at: str | None = None
    status: str = "claimed"
    rights: Permission | None = None
    evidence: tuple[EvidenceRef, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)

    def admission_blockers(self, as_of: str, *, purpose: str = "benchmark") -> tuple[str, ...]:
        return admission_blockers(self, as_of, purpose=purpose)

    def admission_warnings(self, as_of: str) -> tuple[str, ...]:
        return admission_warnings(self, as_of)


@dataclass(frozen=True)
class FeatureDefinition(Record):
    feature_id: str
    value_type: str
    owning_path: str
    owner_model: str
    unit: str | None = None
    required: bool = False
    minimum: str | None = None
    maximum: str | None = None
    allowed_values: tuple[str, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureObservation(Record):
    feature_id: str
    status: str
    value: str | bool | None = None
    unit: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    transform_id: str | None = None
    owner_model: str | None = None
    owning_path: str | None = None
    evidence: tuple[EvidenceRef, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureOwnership(Record):
    feature_id: str
    owning_path: str
    owner_model: str
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedPrice(Record):
    observation_id: str
    source_id: str
    source_price: MoneyRate
    normalized_price: MoneyRate
    model_version: str
    policy_version: str
    lot_id: str | None = None
    normalization_steps: tuple[str, ...] = ()
    status: str = "unknown"
    blockers: tuple[str, ...] = ()
    feature_ownership: tuple[FeatureOwnership, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicySnapshot(Record):
    policy_id: str
    version: str
    model_version: str
    registry_version: str
    effective_at: str
    schema_version: str = SCHEMA_VERSION
    expires_at: str | None = None
    critical_market_fields: tuple[str, ...] = ()
    critical_feature_ids: tuple[str, ...] = ()
    parameters: Mapping[str, Any] = field(default_factory=dict)
    extensions: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PricingRequest(Record):
    request_id: str
    as_of: str
    observations: tuple[MarketObservation, ...]
    policy: PolicySnapshot
    schema_version: str = SCHEMA_VERSION
    features: tuple[FeatureObservation, ...] = ()
    normalized_prices: tuple[NormalizedPrice, ...] = ()
    extensions: Mapping[str, Any] = field(default_factory=dict)


RECORDS = {record.__name__: record for record in (Permission, EvidenceRef, MoneyRate, Hardware, Region, Configuration, MarketObservation, FeatureDefinition, FeatureObservation, FeatureOwnership, NormalizedPrice, PolicySnapshot, PricingRequest)}


def _validate_relations(record: Record) -> None:
    if getattr(record, "schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ValidationError("schema_version: unsupported contract version")
    pairs = (("starts_at", "ends_at"), ("valid_from", "valid_until"), ("effective_at", "expires_at"))
    for start, end in pairs:
        left, right = getattr(record, start, None), getattr(record, end, None)
        if left is not None and right is not None and utc_instant(left) >= utc_instant(right):
            raise ValidationError(f"{type(record).__name__}: interval must have positive duration")
    if isinstance(record, MarketObservation):
        if utc_instant(record.observed_at) > utc_instant(record.ingested_at):
            raise ValidationError("MarketObservation: source time cannot exceed ingestion time")
        if record.expires_at and utc_instant(record.expires_at) <= utc_instant(record.observed_at):
            raise ValidationError("MarketObservation: expiry must follow source observation")
    if isinstance(record, Hardware) and record.accelerator_count is not None:
        count = Decimal(record.accelerator_count)
        if count != count.to_integral_value():
            raise ValidationError("Hardware: accelerator count must be integral")
    if isinstance(record, FeatureObservation):
        if record.status == "known" and record.value is None:
            raise ValidationError("FeatureObservation: known value cannot be null")
        if record.status == "missing" and record.value is not None:
            raise ValidationError("FeatureObservation: missing state cannot contain a value")
    if isinstance(record, FeatureDefinition):
        if record.minimum is not None and record.maximum is not None and Decimal(record.minimum) > Decimal(record.maximum):
            raise ValidationError("FeatureDefinition: inverted bounds")
        if record.value_type in {"boolean", "string"} and (record.minimum is not None or record.maximum is not None):
            raise ValidationError("FeatureDefinition: numeric bounds require numeric feature")
        if record.value_type != "string" and record.allowed_values:
            raise ValidationError("FeatureDefinition: allowed values require string feature")
    if isinstance(record, NormalizedPrice):
        if record.source_price != record.normalized_price and not record.normalization_steps:
            raise ValidationError("NormalizedPrice: price changes require explicit normalization steps")
        feature_ids = [item.feature_id for item in record.feature_ownership]
        if len(set(feature_ids)) != len(feature_ids):
            raise ValidationError("NormalizedPrice: each feature has one owning path")
    if isinstance(record, PolicySnapshot):
        for path in record.critical_market_fields:
            if not _known_market_path(path):
                raise ValidationError("PolicySnapshot: unknown critical market path")
        if len(set(record.critical_feature_ids)) != len(record.critical_feature_ids):
            raise ValidationError("PolicySnapshot: duplicate critical feature")
        if len(set(record.critical_market_fields)) != len(record.critical_market_fields):
            raise ValidationError("PolicySnapshot: duplicate critical market field")
    if isinstance(record, PricingRequest):
        identities = [item.id for item in record.observations]
        if len(set(identities)) != len(identities):
            raise ValidationError("PricingRequest: duplicate observation identity")
        features = [item.feature_id for item in record.features]
        if len(set(features)) != len(features):
            raise ValidationError("PricingRequest: duplicate feature identity")
        as_of = utc_instant(record.as_of)
        if utc_instant(record.policy.effective_at) > as_of or (record.policy.expires_at and utc_instant(record.policy.expires_at) <= as_of):
            raise ValidationError("PricingRequest: policy is inactive at as-of")
        for normalized in record.normalized_prices:
            if normalized.observation_id not in identities:
                raise ValidationError("PricingRequest: normalization has no source observation")
            if normalized.policy_version != record.policy.version or normalized.model_version != record.policy.model_version:
                raise ValidationError("PricingRequest: normalization version mismatch")
            source = next(item for item in record.observations if item.id == normalized.observation_id)
            if normalized.source_id != source.source_id or normalized.source_price != source.price:
                raise ValidationError("PricingRequest: normalization source lineage mismatch")
        normalized_ids = [item.observation_id for item in record.normalized_prices]
        if len(set(normalized_ids)) != len(normalized_ids):
            raise ValidationError("PricingRequest: duplicate normalized source observation")


def _known_market_path(path: str) -> bool:
    spec = SPECS["MarketObservation"]
    for segment in path.split("."):
        if segment == "extensions" or segment not in spec.get("properties", {}):
            return False
        spec = spec["properties"][segment]
        if "anyOf" in spec:
            spec = spec["anyOf"][0]
        if "$ref" in spec:
            spec = SPECS[spec["$ref"].split("/")[-1]]
    return True


def parse_record(name: str, raw: Mapping[str, Any]) -> Record:
    if name not in RECORDS:
        raise ValidationError("contract: unknown record type")
    if not isinstance(raw, Mapping):
        raise ValidationError(f"{name}: object required")
    spec = SPECS[name]
    properties = spec["properties"]
    if not isinstance(raw.get("extensions", {}), Mapping):
        raise ValidationError(f"{name}.extensions: object required")
    extensions = dict(raw.get("extensions", {}))
    for key in set(raw) - set(properties):
        if key in extensions:
            raise ValidationError(f"{name}.extensions: field collision")
        extensions[key] = raw[key]
    result = {"extensions": extensions}
    for key, prop in properties.items():
        if key == "extensions":
            continue
        if key in raw:
            value = raw[key]
        elif key in DEFAULTS.get(name, {}):
            value = DEFAULTS[name][key]
        elif key in spec["required"]:
            raise ValidationError(f"{name}.{key}: required field missing")
        elif prop.get("type") == "array":
            value = []
        elif prop.get("type") == "object":
            value = {}
        else:
            value = None
        ref = prop.get("$ref")
        if "anyOf" in prop:
            ref = prop["anyOf"][0].get("$ref")
        if ref and value is not None:
            value = parse_record(ref.split("/")[-1], value)
        elif prop.get("type") == "array":
            item_ref = prop["items"].get("$ref")
            if not isinstance(value, (list, tuple)):
                raise ValidationError(f"{name}.{key}: array required")
            value = tuple(parse_record(item_ref.split("/")[-1], item) if item_ref else item for item in value)
        _validate_value(_encode(value), prop, f"{name}.{key}")
        result[key] = value
    return RECORDS[name](**result)


def parse_market_observation(raw: Mapping[str, Any]) -> MarketObservation:
    return parse_record("MarketObservation", raw)


def parse_evidence_ref(raw: Mapping[str, Any]) -> EvidenceRef:
    return parse_record("EvidenceRef", raw)


def parse_feature_observation(raw: Mapping[str, Any]) -> FeatureObservation:
    return parse_record("FeatureObservation", raw)


def parse_feature_definition(raw: Mapping[str, Any]) -> FeatureDefinition:
    return parse_record("FeatureDefinition", raw)


def parse_normalized_price(raw: Mapping[str, Any]) -> NormalizedPrice:
    return parse_record("NormalizedPrice", raw)


def parse_policy_snapshot(raw: Mapping[str, Any]) -> PolicySnapshot:
    return parse_record("PolicySnapshot", raw)


def parse_pricing_request(raw: Mapping[str, Any]) -> PricingRequest:
    return parse_record("PricingRequest", raw)


def admission_blockers(observation: MarketObservation, as_of: str, *, purpose: str = "benchmark", policy: PolicySnapshot | None = None) -> tuple[str, ...]:
    """Compute price-use gates. Indicative use preserves claimed asset status.

Scopes govern price-data use, independently of permission to execute a trade.
Firm qualification needs separate provider/contract/capacity/risk reviews.
"""
    if purpose not in {"indicative", "benchmark", "firm"}:
        raise ValidationError("admission: unsupported purpose")
    now = utc_instant(as_of)
    blockers = []
    if utc_instant(observation.observed_at) > now or utc_instant(observation.ingested_at) > now:
        blockers.append("observation_not_yet_available")
    if observation.expires_at is None:
        blockers.append("missing_expiry")
    elif utc_instant(observation.expires_at) <= now:
        blockers.append("expired_observation")
    if observation.status != "verified" and not (purpose == "indicative" and observation.status == "claimed"):
        blockers.append("unverified_observation")
    if observation.source_version is None or not observation.source_version.strip():
        blockers.append("missing_source_version")
    rights = observation.rights
    if rights is None or rights.status != "allowed" or rights.benchmark != "PASS" or rights.verified_by is None:
        blockers.append("unverified_benchmark_permission")
    if rights is None or rights.observe != "PASS":
        blockers.append("unverified_observation_permission")
    if rights is not None and rights.expires_at is not None and utc_instant(rights.expires_at) <= now:
        blockers.append("expired_permission")
    if observation.kind in {"model_token_price", "financial_future_mark", "event_contract_price"}:
        blockers.append("incompatible_compute_benchmark_kind")
    if observation.price is not None and observation.price.unit not in {"gpu_hour", "node_hour"}:
        blockers.append("incompatible_compute_benchmark_unit")
    if observation.price is not None and observation.price.unit == "node_hour":
        count = observation.hardware.accelerator_count if observation.hardware else None
        if count is None or Decimal(count) <= 0:
            blockers.append("missing_positive_node_accelerator_count")
    if policy is not None:
        if utc_instant(policy.effective_at) > now:
            blockers.append("policy_not_yet_effective")
        if policy.expires_at and utc_instant(policy.expires_at) <= now:
            blockers.append("expired_policy")
    for path in ("price", "price_side", "hardware.model") + (policy.critical_market_fields if policy else ()):
        value: Any = observation.to_dict()
        for segment in path.split("."):
            value = value.get(segment) if isinstance(value, Mapping) else None
        if value is None or value == "":
            blockers.append(f"missing_critical:{path}")
    if purpose == "firm":
        blockers.append("firm_pricing_review_not_implemented")
        for key in ("offer_id", "lot_id", "provider_group_id", "quantity", "quantity_unit", "starts_at", "ends_at"):
            if getattr(observation, key) is None:
                blockers.append(f"missing_firm_term:{key}")
        if observation.kind not in {"firm_supplier_rfq", "confirmed_rental_trade", "buyer_bid"}:
            blockers.append("nonfirm_observation_kind")
        if observation.quantity is not None and Decimal(observation.quantity) <= 0:
            blockers.append("nonpositive_firm_quantity")
    return tuple(dict.fromkeys(blockers))


def admission_warnings(observation: MarketObservation, as_of: str) -> tuple[str, ...]:
    utc_instant(as_of)
    warnings = []
    if observation.status == "claimed":
        warnings.append("claimed_data_not_verified_asset_capacity")
    if observation.kind == "aggregate_advertised_index":
        warnings.append("aggregate_advertised_prices_not_executable_offers")
    if observation.region is None or observation.region.country_code is None:
        warnings.append("missing_region_prevents_localized_comparison")
    if observation.lot_id is None or observation.provider_group_id is None:
        warnings.append("independent_supply_identity_unknown")
    if observation.extensions:
        warnings.append("unregistered_extensions_not_used_in_pricing")
    return tuple(warnings)


@dataclass(frozen=True)
class RegisteredFeature:
    feature_id: str
    value: Decimal | int | str | bool
    unit: str | None
    owning_path: str
    owner_model: str


@dataclass(frozen=True)
class FeatureRegistry:
    """Explicit ownership prevents extras from silently changing formulas."""
    version: str
    definitions: tuple[FeatureDefinition, ...] = ()
    _definitions: Mapping[str, FeatureDefinition] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_value(self.version, SPECS["PolicySnapshot"]["properties"]["registry_version"], "registry.version")
        definitions = {}
        for definition in self.definitions:
            if not isinstance(definition, FeatureDefinition):
                raise ValidationError("registry: typed definition required")
            if definition.feature_id in definitions:
                raise ValidationError("registry: duplicate feature definition")
            definitions[definition.feature_id] = definition
        object.__setattr__(self, "definitions", tuple(self.definitions))
        object.__setattr__(self, "_definitions", MappingProxyType(definitions))

    def with_definition(self, definition: FeatureDefinition, *, version: str) -> FeatureRegistry:
        if version == self.version:
            raise ValidationError("registry: definition changes require a new version")
        return FeatureRegistry(version, self.definitions + (definition,))

    def activate(self, observation: FeatureObservation, *, as_of: str) -> RegisteredFeature:
        definition = self._definitions.get(observation.feature_id)
        if definition is None:
            raise ValidationError("feature: unregistered field cannot affect pricing")
        now = utc_instant(as_of)
        if observation.status != "known" or observation.value is None:
            raise ValidationError("feature: known value required")
        if observation.valid_from is None or observation.valid_until is None:
            raise ValidationError("feature: explicit validity interval required")
        if utc_instant(observation.valid_from) > now or utc_instant(observation.valid_until) <= now:
            raise ValidationError("feature: inactive at as-of")
        if observation.unit != definition.unit:
            raise ValidationError("feature: registered unit mismatch")
        if observation.owner_model is not None and observation.owner_model != definition.owner_model:
            raise ValidationError("feature: model ownership mismatch")
        if observation.owning_path is not None and observation.owning_path != definition.owning_path:
            raise ValidationError("feature: pricing path ownership mismatch")
        raw = observation.value
        if definition.value_type in {"decimal", "integer"}:
            value = exact_decimal(raw)
            if definition.value_type == "integer":
                if value != value.to_integral_value():
                    raise ValidationError("feature: integer value required")
                value = int(value)
            if definition.minimum is not None and value < Decimal(definition.minimum):
                raise ValidationError("feature: below registered bound")
            if definition.maximum is not None and value > Decimal(definition.maximum):
                raise ValidationError("feature: above registered bound")
        elif definition.value_type == "boolean":
            if not isinstance(raw, bool):
                raise ValidationError("feature: boolean value required")
            value = raw
        else:
            if not isinstance(raw, str):
                raise ValidationError("feature: string value required")
            if definition.allowed_values and raw not in definition.allowed_values:
                raise ValidationError("feature: outside registered categories")
            value = raw
        return RegisteredFeature(definition.feature_id, value, definition.unit, definition.owning_path, definition.owner_model)

    def required_blockers(self, observations: tuple[FeatureObservation, ...], *, as_of: str, policy: PolicySnapshot | None = None) -> tuple[str, ...]:
        if policy is not None and policy.registry_version != self.version:
            return ("registry_version_mismatch",)
        identities = [item.feature_id for item in observations]
        if len(identities) != len(set(identities)):
            return ("duplicate_feature_observation",)
        supplied = {item.feature_id: item for item in observations}
        required = {key for key, value in self._definitions.items() if value.required}
        if policy:
            required.update(policy.critical_feature_ids)
        blockers = []
        for key in sorted(required):
            if key not in supplied:
                blockers.append(f"missing_required_feature:{key}")
            else:
                try:
                    self.activate(supplied[key], as_of=as_of)
                except ValidationError:
                    blockers.append(f"unusable_required_feature:{key}")
        return tuple(blockers)
