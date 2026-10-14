# Provider price coverage and access paths

The backend distinguishes a provider's own tariff/API from a publisher's derived
catalog. Both can inform comparison, with their native units and evidence limits.
Neither establishes current GPU availability, a complete physical supply price,
an executable midpoint, counterparty credit or accepted workload performance.

| Provider/path | Current useful data | Access and remaining boundary |
| --- | --- | --- |
| AWS through GPUHunt | Published instance-hour USD, provider location, CPU/RAM, claimed GPU type/count/per-device memory and spot flag | Anonymous versioned publisher archive; normalized local comparison only. This is not an AWS quote, independent supply or verified whole-device allocation. |
| Azure through GPUHunt | The same publisher-derived GPU/VM fields, separate from Azure retail meter observations | Anonymous publisher archive with per-provider version. Catalog terms and price age remain unverified; no inferred VM availability. |
| GCP through GPUHunt | GPU/VM specification claims and publisher-composed hourly references, including spot distinctions | Anonymous publisher archive. Unknown conditional flags or provider terms, including DWS calendar mode, hold the price rather than becoming normal on-demand or forward offers. |
| Azure direct retail API | Native VM consumption-hour retail list meter by explicit region/SKU, bounded pagination | Existing anonymous internal-analysis admission. GPU configuration/count needs a separately supported SKU join; a VM-hour is not automatically a GPU-hour. |
| AWS direct published price files | Existing Lightsail/ECS/Bedrock/Lambda/S3/SageMaker native meters by service/region | Public file download is documented, but large EC2 files and authenticated Query APIs are outside the current bounded adapter. No arbitrary increase to response limits. |
| GCP direct Cloud Billing Catalog | Public SKU descriptions/regions/tiered unit prices once configured | The [official guide](https://docs.cloud.google.com/billing/v1/how-tos/catalog-api) requires an enabled API and API key. `gcp_cloud_billing` remains an unavailable candidate; no key or anonymous bypass is presumed. |
| Vast direct offer search | Existing parser describes documented offer-search inputs/native quantities | The [official search contract](https://docs.vast.ai/api-reference/search/search-offers) uses Bearer authentication. No public-only request, reservation or trade is performed. |
| [SkyPilot published catalogs](https://github.com/skypilot-org/skypilot-catalog) | Documented GPU/VM/region/spot schema is technically relevant | `skypilot_catalog` remains rights-pending: its catalog repository has no explicit data license. The separate SkyPilot software repository's Apache license is not silently applied to catalog data. |

## GPUHunt integration contract

The [publisher README](https://github.com/dstackai/gpuhunt) documents public catalog
query/use. Its [catalog reader contract](https://github.com/dstackai/gpuhunt/blob/main/src/gpuhunt/_internal/catalog.py)
defines per-provider versioned public archives, while its
[model contract](https://github.com/dstackai/gpuhunt/blob/main/src/gpuhunt/_internal/models.py)
describes instance prices in USD per hour and hardware memory in publisher GB.
The repository code uses [MPL-2.0](https://github.com/dstackai/gpuhunt/blob/main/LICENSE).
ComputeBasis uses a fresh independent parser rather than copying or installing
that package. Admission is narrowly scoped to documented local normalized catalog
comparison; it grants no raw-catalog public redistribution, vendor account access
or execution. Displays retain publisher attribution and claim status.

`source_id` is `gpuhunt_catalog`, with role `publisher_gpu_vm_reference`.
Use `GET /v1/sources` for the current parameters and permission state. The existing
`POST /v1/sources/gpuhunt_catalog/collect` performs an explicit admitted read;
configured app-owned refresh can use the same collector. No browser directly
contacts a cloud provider. A request supplies:

```json
{
  "filters": {
    "provider": "gcp",
    "location_prefix": "us-central1-",
    "limit": 200,
    "spot": false
  }
}
```

Provider is limited to `aws`, `azure` or `gcp`; supply exactly one `location` or
`location_prefix`. `gpu_name`, boolean `spot` and an explicit publisher `version`
are optional. A prefix is a literal selection of published location labels,
not a verified physical country/site mapping. Explicit versions support replay;
they cannot make an old catalog fresh.

Without a requested version, the collector reads the fixed provider `version`
manifest and then that exact `/v3/{provider}/{version}/catalog.zip`. It never
follows an arbitrary URL or queries online-provider APIs. It permits one expected
provider CSV and an optional matching version member, without extraction to disk.
Bounds are 2 MiB compressed, 16 MiB expanded CSV, 100,000 scanned rows, 24 header
fields and at most 1,000 returned records. Encryption, symlinks, unsupported
compression, unexpected/path-bearing/duplicate members and disproportionate
expansion fail. Truncation and complete scanned-scope counts remain explicit.

Normalized records are `gpu_vm_reference` catalog rows, not price observations
for the physical benchmark. `native_price` is a publisher-derived USD
`instance_hour` reference. `normalized_price_diagnostic` divides the whole instance
price by the positive whole publisher accelerator count; it is not a verified
exclusive-device price. Published float strings are preserved as exact decimal
values **as published**, without claiming original cloud-vendor precision.
CPU-only, TPU and unknown GPU-vendor rows are excluded from this GPU path.

Missing price or unmodeled `flags`/`provider_data` leaves a held technical record,
with `native_price` and its normalized diagnostic null. `reported_price`, when
present, remains an explicitly conditional publisher fact. Unknown provider-data
values and raw rows are not retained. An explicit false known DWS flag is different
from absent/true/unknown terms; spot false alone does not prove on-demand eligibility.

## Time, independence and output use

Every record carries `publisher_catalog_version` and `publisher_catalog_date`.
`observed_at`, `catalog_observed_at` and `raw_capture_at` record retrieval, and expiry is conservatively anchored to the
catalog calendar date at UTC midnight, not a repeated download. The original
vendor quote observation time remains null with `vendor_price_age_known: false`.
Neither a new publisher file nor its S3 modification time authenticates the
underlying vendor price age.

The output has `quantity_available: null`, `whole_device_allocation_verified:
false`, `physical_inventory_verified: false`, `gpu_hour_benchmark_eligible: false`,
`firm_price_eligible: false` and `execution_enabled: false`. Reference price side
is `publisher_reference_not_midpoint`. Multiple regions/zones or a direct Azure
meter plus an Azure publisher row do not create independent underlying supply.
Attached GPU configurations that share a CPU VM name/location remain separate
references by GPU type/count/memory, host specification and conditional scope.
Only inconsistent prices for that same complete scope are conflicts.
Hardware, OS/license, payment/commitment, topology, quantity and actual inclusion
terms still need a complete comparable contract before monetary qualification.

The focused public demo retains its existing GetDeploying/ECB/Energinet display
scope. GPUHunt expands backend reference coverage; public redisplay beyond its
admitted purpose needs its own decision. Raw archives, vendor/customer documents,
credentials and runtime records stay outside Git. All connector tests use
independently invented archives and make no network request.
