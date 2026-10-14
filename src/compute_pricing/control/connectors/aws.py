"""Published, bounded AWS price-file references; native meters stay distinct."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import urllib.parse
from typing import Any, Mapping

from .transport import ConnectorError, RawResponse, ReadOnlyTransport, ReadRequest, SOURCE_SPECS, SourcePolicy, parse_utc, utc_string

SOURCE_ID = "aws_public_pricing"
# These are reviewed retrieval contracts, not a model/SKU or economic-value list.
SUPPORTED_SERVICES = frozenset({"AmazonLightsail", "AmazonECS", "AmazonBedrock", "AWSLambda", "AmazonS3", "AmazonSageMaker"})
MAX_PRODUCTS = 5000
MAX_TARIFFS = 5000
MAX_REGIONS = 256
MAX_ATTRIBUTES = 128
PRODUCT_ATTRIBUTE_FIELDS = frozenset({"regionCode", "fromRegionCode", "toRegionCode", "location", "locationType",
    "servicecode", "instanceType", "instanceSize", "vcpu", "memory", "storage", "operatingSystem",
    "processorArchitecture", "processorFeatures", "preInstalledSw", "tenancy", "usagetype", "operation",
    "group", "bundle", "transfer", "cpuArchitecture", "gpuMemory", "model", "modelId", "modelType",
    "inferenceType", "requestType", "usageType", "memoryType", "bundleType", "type", "storageClass", "volumeType",
    "archtype", "architecture", "transferType", "fromLocation", "toLocation", "fromLocationType", "toLocationType"})


def _attributes(value, code):
    if not isinstance(value, dict) or len(value) > MAX_ATTRIBUTES:
        raise ConnectorError(code)
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 128 or not isinstance(item, str) or len(item) > 4096:
            raise ConnectorError(code)
    return value


def aws_filters(filters: Mapping[str, Any] | None) -> dict[str, str]:
    if not isinstance(filters, Mapping) or set(filters) - {"service", "region", "sku"}:
        raise ConnectorError("aws_explicit_service_region_required")
    service, region = filters.get("service"), filters.get("region")
    if not isinstance(service, str) or service not in SUPPORTED_SERVICES:
        raise ConnectorError("aws_service_not_admitted")
    if not isinstance(region, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", region):
        raise ConnectorError("aws_explicit_region_required")
    result = {"service": service, "region": region}
    sku = filters.get("sku")
    if sku is not None:
        if not isinstance(sku, str) or not re.fullmatch(r"[A-Z0-9]{1,64}", sku):
            raise ConnectorError("aws_sku_invalid")
        result["sku"] = sku
    return result


def aws_request(filters: Mapping[str, Any] | None) -> ReadRequest:
    options = aws_filters(filters)
    return ReadRequest(SOURCE_SPECS[SOURCE_ID],
        "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/" + options["service"] + "/current/region_index.json")


def _text(value, code, *, max_length=4096):
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ConnectorError(code)
    return value


def parse_aws(raw: RawResponse, policy: SourcePolicy, *, filters: Mapping[str, Any]) -> Any:
    from .adapters import ConnectorBatch, _jsonable, _permission, decimal_string, decimal_value, json_payload
    if raw.source_id != SOURCE_ID or policy.source_id != SOURCE_ID:
        raise ConnectorError("source_policy_mismatch")
    captured = parse_utc(raw.captured_at)
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, captured)
    options = aws_filters(filters)
    payload = json_payload(raw)
    if not isinstance(payload, dict) or payload.get("formatVersion") not in {"v1", "v1.0"} or payload.get("offerCode") != options["service"]:
        raise ConnectorError("aws_catalog_contract_changed")
    products, terms = payload.get("products"), payload.get("terms")
    if not isinstance(products, dict) or len(products) > MAX_PRODUCTS or not isinstance(terms, dict) or len(terms) > 8:
        raise ConnectorError("aws_catalog_shape_or_budget_changed")
    version = _text(payload.get("version"), "aws_catalog_version_missing", max_length=32)
    if not re.fullmatch(r"[0-9]{14}", version):
        raise ConnectorError("aws_catalog_version_invalid")
    published = parse_utc(payload.get("publicationDate"))
    if published > captured:
        raise ConnectorError("future_source_observation")
    if payload.get("regionCode") is not None and payload["regionCode"] != options["region"]:
        raise ConnectorError("aws_response_scope_mismatch")
    unknown_region_skus, region_bases = set(), {}
    for sku, product in products.items():
        if not isinstance(product, dict) or product.get("sku") != sku or not re.fullmatch(r"[A-Z0-9]{1,64}", sku):
            raise ConnectorError("aws_product_identity_invalid")
        attributes = _attributes(product.get("attributes"), "aws_product_attributes_invalid")
        if attributes.get("servicecode", options["service"]) != options["service"]:
            raise ConnectorError("aws_response_scope_mismatch")
        primary, origin, destination = attributes.get("regionCode"), attributes.get("fromRegionCode"), attributes.get("toRegionCode")
        if primary:
            if primary != options["region"]:
                raise ConnectorError("aws_response_scope_mismatch")
            region_bases[sku] = "published_product_region_code"
        elif origin == options["region"]:
            region_bases[sku] = "published_transfer_from_region_code"
        elif destination == options["region"]:
            region_bases[sku] = "published_transfer_to_region_code"
        elif origin or destination:
            raise ConnectorError("aws_response_scope_mismatch")
        else:
            unknown_region_skus.add(sku)
    catalog, seen, exclusions = [], set(), []
    exclusions.extend({"sku": sku, "reason": "native_meter_region_unknown"} for sku in sorted(unknown_region_skus))
    sku_term_count, offer_count, dimension_count = 0, 0, 0
    for term_type, sku_terms in terms.items():
        if term_type not in {"OnDemand", "Reserved"}:
            exclusions.append({"term_type": term_type, "reason": "unsupported_term_structure_retained_in_source_hash"})
            continue
        if not isinstance(sku_terms, dict):
            raise ConnectorError("aws_terms_shape_changed")
        sku_term_count += len(sku_terms)
        if sku_term_count > MAX_TARIFFS:
            raise ConnectorError("aws_tariff_budget_exceeded")
        for sku, offerings in sku_terms.items():
            if sku not in products or not isinstance(offerings, dict):
                raise ConnectorError("aws_unjoined_product_term")
            offer_count += len(offerings)
            if offer_count > MAX_TARIFFS:
                raise ConnectorError("aws_tariff_budget_exceeded")
            for offer_key, offer in offerings.items():
                if not isinstance(offer, dict) or offer.get("sku") != sku:
                    raise ConnectorError("aws_term_identity_invalid")
                term_code = _text(offer.get("offerTermCode"), "aws_term_code_missing", max_length=64)
                if offer_key != sku + "." + term_code:
                    raise ConnectorError("aws_term_identity_invalid")
                effective = parse_utc(offer.get("effectiveDate"))
                if effective > captured:
                    exclusions.append({"sku": sku, "term_type": term_type, "reason": "future_effective_tariff"})
                    continue
                dimensions = offer.get("priceDimensions")
                term_attributes = _attributes(offer.get("termAttributes", {}), "aws_term_attributes_invalid")
                if not isinstance(dimensions, dict):
                    raise ConnectorError("aws_price_dimensions_invalid")
                dimension_count += len(dimensions)
                if dimension_count > MAX_TARIFFS:
                    raise ConnectorError("aws_tariff_budget_exceeded")
                for rate_code, dimension in dimensions.items():
                    if not isinstance(dimension, dict) or dimension.get("rateCode") != rate_code or not rate_code.startswith(offer_key + "."):
                        raise ConnectorError("aws_dimension_identity_invalid")
                    unit = _text(dimension.get("unit"), "aws_native_unit_missing", max_length=128)
                    # Native ranges are not quantities that this platform owns.
                    begin = decimal_value(dimension.get("beginRange", dimension.get("startingRange")))
                    end_value = dimension.get("endRange", dimension.get("endingRange"))
                    if end_value != "Inf" and decimal_value(end_value) <= begin:
                        raise ConnectorError("aws_price_range_invalid")
                    rates = dimension.get("pricePerUnit")
                    if not isinstance(rates, dict) or not rates or len(rates) > 32:
                        raise ConnectorError("aws_native_price_missing")
                    applies_to = dimension.get("appliesTo", [])
                    if not isinstance(applies_to, list) or len(applies_to) > MAX_ATTRIBUTES or any(not isinstance(item, str) or len(item) > 128 for item in applies_to):
                        raise ConnectorError("aws_price_scope_invalid")
                    for currency, rate in rates.items():
                        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
                            raise ConnectorError("aws_currency_invalid")
                        amount = decimal_value(rate)
                        identity = (sku, term_type, offer_key, rate_code, currency)
                        if identity in seen:
                            raise ConnectorError("aws_duplicate_tariff")
                        seen.add(identity)
                        if len(seen) > MAX_TARIFFS:
                            raise ConnectorError("aws_tariff_budget_exceeded")
                        if sku in unknown_region_skus or "sku" in options and options["sku"] != sku:
                            continue
                        if len(catalog) >= MAX_TARIFFS:
                            raise ConnectorError("aws_tariff_budget_exceeded")
                        record = {"schema_version": "native-cloud-meter/1.0", "source_id": SOURCE_ID,
                            "id": "aws-tariff-" + hashlib.sha256("|".join(identity).encode()).hexdigest()[:24],
                            "source_version": "aws-published-price/v1", "publisher_version": version,
                            "kind": "cloud_meter_tariff", "service_code": options["service"], "sku": sku,
                            "provider_region": options["region"], "native_region_basis": region_bases[sku], "product_family": products[sku].get("productFamily"),
                            "source_catalog_region": options["region"], "region_is_physical_delivery_claim": False,
                            "native_price": {"amount": decimal_string(amount), "currency": currency, "unit": unit},
                            "term_type": term_type, "offer_term_code": term_code, "rate_code": rate_code,
                            "range_start": decimal_string(begin), "range_end": end_value,
                            "term_attributes": term_attributes, "applies_to": applies_to, "effective_at": utc_string(effective),
                            "publication_at": utc_string(published), "observed_at": raw.captured_at,
                            "ingested_at": raw.captured_at, "expires_at": utc_string(captured + dt.timedelta(seconds=policy.max_age_s)),
                            "status": "claimed", "gpu_hour_benchmark_eligible": False,
                            "physical_inventory_verified": False, "execution_enabled": False,
                            "rights": _permission(policy), "attribution": policy.attribution,
                            "admission_scope": "local_aws_cost_comparison_no_raw_redistribution",
                            "evidence": {"artifact_sha256": raw.sha256, "accessed_at": raw.captured_at, "locator": raw.endpoint_path},
                            "extensions": {"product_attributes": {key: value for key, value in products[sku]["attributes"].items() if key in PRODUCT_ATTRIBUTE_FIELDS},
                                "unknown_product_attribute_names": sorted(set(products[sku]["attributes"]) - PRODUCT_ATTRIBUTE_FIELDS),
                                "unknown_product_field_names": sorted(set(products[sku]) - {"sku", "productFamily", "attributes"}),
                                "unknown_offer_field_names": sorted(set(offer) - {"sku", "offerTermCode", "effectiveDate", "termAttributes", "priceDimensions"}),
                                "unknown_dimension_field_names": sorted(set(dimension) - {"rateCode", "description", "unit", "beginRange", "endRange", "startingRange", "endingRange", "pricePerUnit", "appliesTo"}),
                                "billing_cap_and_inclusion_not_inferred": True, "vcpus_not_physical_cores_or_gpus": True}}
                        catalog.append(_jsonable(record))
    return ConnectorBatch(SOURCE_ID, raw.metadata(), (), tuple(catalog), warnings=(
        "native_tariff_not_verified_inventory_or_gpu_hour",
        "billing_units_tiers_reserved_terms_and_monthly_caps_require_separate_cost_model",
        "public_price_file_not_firm_supplier_quote_or_public_redistribution_license"), coverage={
            "complete": not exclusions, "population": "selected_sku_native_tariffs_from_downloaded_regional_file" if "sku" in options else "downloaded_regional_published_native_tariffs",
            "products_received": len(products), "tariffs_received": len(seen), "rows_accepted": len(catalog),
            "scope": options, "excluded_terms": exclusions, "compute_price_observations": 0,
            "gpu_hour_benchmark_eligible": False, "request_count": 1})


def collect_aws(policy: SourcePolicy, transport: ReadOnlyTransport, filters: Mapping[str, Any] | None):
    from .adapters import _jsonable, json_payload
    import dataclasses
    options = aws_filters(filters)
    for purpose in ("observe", "retain", "benchmark"):
        policy.require(purpose, transport.clock())
    index_raw = transport.fetch(aws_request(options), policy)
    index = json_payload(index_raw)
    if not isinstance(index, dict) or index.get("formatVersion") not in {"v1", "v1.0"} or not isinstance(index.get("regions"), dict) or len(index["regions"]) > MAX_REGIONS:
        raise ConnectorError("aws_region_index_shape_changed")
    region = index["regions"].get(options["region"])
    if not isinstance(region, dict) or region.get("regionCode") != options["region"]:
        raise ConnectorError("aws_region_not_in_current_catalog")
    target = _text(region.get("currentVersionUrl"), "aws_region_url_missing", max_length=512)
    url = urllib.parse.urljoin("https://pricing.us-east-1.amazonaws.com", target)
    request = ReadRequest(SOURCE_SPECS[SOURCE_ID], url)
    parts = request.validate()
    expected = r"/offers/v1\.0/aws/" + re.escape(options["service"]) + r"/(current|[0-9]{14})/" + re.escape(options["region"]) + r"/index\.json"
    if not re.fullmatch(expected, parts.path):
        raise ConnectorError("aws_region_url_scope_changed")
    transport.wait_for_source(SOURCE_ID, max_wait_s=transport.max_wait_s)
    price_raw = transport.fetch(request, policy)
    if len(index_raw.body) + len(price_raw.body) > 8 * 1024 * 1024:
        raise ConnectorError("aws_collection_size_budget")
    batch = parse_aws(price_raw, policy, filters=options)
    requested_version = parts.path.split("/")[-3]
    if requested_version != "current" and json_payload(price_raw).get("version") != requested_version:
        raise ConnectorError("aws_region_price_version_mismatch")
    pages = [index_raw.metadata(), price_raw.metadata()]
    metadata = {**price_raw.metadata(), "pages": pages, "total_bytes": sum(item["bytes"] for item in pages)}
    return dataclasses.replace(batch, raw_metadata=_jsonable(metadata), coverage={**batch.coverage,
        "request_count": 2, "region_index_sha256": index_raw.sha256,
        "available_region_count": len(index["regions"]), "all_services": False, "all_market_inventory": False})
