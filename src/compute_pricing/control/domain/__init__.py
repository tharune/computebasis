"""Exact, auditable shared contracts for generalized compute pricing."""
from .contracts import (
    Configuration, EvidenceRef, FeatureDefinition, FeatureObservation,
    FeatureOwnership, FeatureRegistry, Hardware, MarketObservation, MoneyRate,
    NormalizedPrice, Permission, PolicySnapshot, PricingRequest, Region,
    RegisteredFeature, ValidationError, admission_blockers, admission_warnings, exact_decimal,
    parse_evidence_ref, parse_feature_definition, parse_feature_observation,
    parse_market_observation, parse_normalized_price, parse_policy_snapshot,
    parse_pricing_request, parse_record, utc_instant,
)
from .spec import SCHEMA_VERSION

__all__ = [
    "Configuration", "EvidenceRef", "FeatureDefinition", "FeatureObservation",
    "FeatureOwnership", "FeatureRegistry", "Hardware", "MarketObservation",
    "MoneyRate", "NormalizedPrice", "Permission", "PolicySnapshot",
    "PricingRequest", "Region", "RegisteredFeature", "ValidationError",
    "SCHEMA_VERSION", "admission_blockers", "admission_warnings", "exact_decimal", "parse_evidence_ref",
    "parse_feature_definition", "parse_feature_observation",
    "parse_market_observation", "parse_normalized_price", "parse_policy_snapshot",
    "parse_pricing_request", "parse_record", "utc_instant",
]
