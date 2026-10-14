# Public source adapters and economic units

Six documented public feeds are admitted narrowly for local analysis. Admission, retention, benchmark role and execution permissions remain separate. No price response creates owned capacity, a delivery right or a firm quote. Startup does not collect feeds; the user explicitly requests bounded reads.

| Feed | Supported retrieval | Economic boundary |
| --- | --- | --- |
| GetDeploying | Published CC BY dataset, latest complete weekly cohort | Advertised aggregate GPU-hour reference; no physical lot or regional premium |
| Azure Retail Prices | Explicit region, exact SKU or SKU prefix; bounded pages | Native VM consumption-hour retail meter; GPU count/model unknown |
| AWS published price lists | Explicit Lightsail/ECS/Bedrock service and region; version-pinned price-file join | Native currency/unit/tier/term catalog; CPU, memory, token and bundle meters remain distinct |
| OpenRouter Models | Anonymous Models GET, optional search/modalities, bounded offset/pages | Current-default advertised prompt/completion rates; conditions retained and unapplied |
| ECB | Official daily EUR-base XML | Attributed informational FX; no settlement quote |
| Hugging Face Hub | Explicit public author/task, bounded metadata records | Licensing/gating/revision discovery; no weights, prices or goodput |

## Primary interface and use evidence

[GetDeploying dataset](https://getdeploying.com/dataset/gpu-prices) files use [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Preserve attribution and observed weekly periods; retrieval does not refresh an old price date.

[Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices) documents unauthenticated internal comparison. Reservation, DevTest, non-hour, nonprimary and tiered meters remain outside this adapter's accepted hourly population. Raw-feed public redistribution is not admitted.

[AWS Price List purpose](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/price-changes.html) describes cost control, scenarios and forecasting. [Published regional-file documentation](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-the-aws-price-list-bulk-api-fetching-price-list-files-manually.html) supports direct downloads. Native OnDemand/Reserved dimensions retain exact ranges, effective/publication times and selected product attributes. Unknown-region/unsupported/future-effective records report exclusions. [AWS terms](https://aws.amazon.com/terms/) and [agreement](https://aws.amazon.com/agreement/) do not grant a raw-feed redistribution license through this tool. Oversized EC2 catalogs and credentialed Query APIs stay disabled.

[OpenRouter's Models overview](https://openrouter.ai/docs/guides/overview/models) documents freely available model information and anonymous Models GET integrations. This supports the narrow local catalog comparison path. [Its terms](https://openrouter.ai/terms) contain broader resale, automation and Materials restrictions; the tension remains recorded. No website scraping, provider queries, model calls, access resale or broad archive/raw redistribution is admitted. Obtain an independent legal review before a commercial routing/resale or broader archival use. Token conversion is exact; missing stays unknown and explicit zero stays zero. Invalid native or converted base/conditional rates quarantine only the affected model as unpriced technical metadata; valid peers survive. Catalogue retrieval completeness and usable-price coverage are reported separately. Current-default prices and workload/time/context overrides are not a future provider quote.

[ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) are informational. Its [reuse conditions](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html) require accurate attribution, free-availability and derived-modification notices where applicable.

[Hugging Face Hub APIs](https://huggingface.co/docs/hub/en/api) and [anonymous tiers](https://huggingface.co/docs/hub/en/rate-limits) support scoped public metadata discovery. Repository licensing and serving qualification remain independent.

## Configuration and safety boundaries

The [source admission file](../examples/source-admission.json) records reviewed purposes; the [collection plan](../examples/collection-plan.json) supplies editable scopes. Neither contains observed prices, runtime keys or data snapshots. Source-quality rules in a saved pricing policy never grant data rights or enable execution. Current liveness stays unverified until a separate recorded probe; a successful probe is evidence for that instant.

Other candidates remain visible with rights, authentication, scale, instrument or schema blockers. Oracle/OVHcloud/Scaleway require documented commercial retention/reuse scope. Vast and Runpod require scoped read credentials. Licensed indices and event/futures markets need applicable specifications and permissions and remain outside GPU-hour averaging. Direct model serving vendors need actual API/price, license/privacy and measured workload evidence.

Transport pins public DNS addresses, verifies TLS, constrains endpoints/query/redirect scope, paces reads and bounds bytes/pages/cardinality. Missing or partial pagination never claims worldwide coverage. AWS/OpenRouter retain normalized technical fields and field names of unknown additions rather than raw descriptions or source objects. Raw pricing/catalog records, credentials and user inventory always remain outside Git. Offline tests use independent invented payloads and make no network request.
