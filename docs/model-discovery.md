# Public model metadata discovery

The public Hugging Face Hub API exposes model metadata through `GET /api/models`.
This adapter accepts an explicitly supplied author, `pipeline_tag=text-generation`,
an integer limit of 1–100 and `full=true`. It makes one bounded public GET through
the existing admitted HTTPS transport. It never supplies an API key, follows a
model-file route, downloads weights, accesses a private repository, runs inference
or incurs an inference/deployment charge.

The [official Hub API documentation](https://huggingface.co/docs/hub/en/api)
describes open information endpoints, and the [rate-limit documentation](https://huggingface.co/docs/hub/en/rate-limits)
documents anonymous API use. Anonymous quotas can change; response throttling,
source intervals and request budgets remain enforced. Current [terms](https://huggingface.co/terms-of-service)
make public repository content available through service functionality subject to
its accompanying license. Metadata discovery admission is limited to public
catalog metadata. It does not grant permission to use weights, distribute model
cards or serve a model contrary to its own license/gating conditions.

Every record remains `kind=model_metadata`, with `price=null`, no market-price
observations, `qualification_verified=false` and execution disabled. The parser
preserves declared license tags, card metadata, gating, private/unknown visibility,
repository revision and source creation/modification dates. Unexpected explicitly
private records fail closed. Unknown tags and new metadata remain unpriced; they
cannot establish technical compatibility, model quality, runtime goodput, privacy,
creditworthiness, copyright permission or paid demand.

Catalog observation time is the actual response capture time: a current public
catalog can legitimately describe a repository whose files last changed years
ago. The separate repository timestamps preserve that distinction. Missing dates
and licenses remain unknown; a fetch never becomes a new model benchmark. Evidence
keeps the raw-response hash, endpoint path, capture time and source attribution.
Raw responses and model metadata snapshots remain outside Git.

One response is a bounded lower-bound result, not a complete global or author
catalog. Pagination is not followed; reaching the caller's limit can hide further
models. Coverage always reports `complete=false`, zero price observations and an
explicit possibility of truncation. An empty result produces no fabricated model
or price. This is a fourth source role for model discovery, not a fourth
independently comparable compute-price feed.

Example manual collection scope, using an invented organization:

```json
{"filters":{"author":"invented-author","pipeline_tag":"text-generation","limit":25,"full":true}}
```

The adapter does not trigger an automatic collector or scheduler. Source admission
and manual collection are separate from any permission to benchmark or deploy a
particular model. Production model licensing, accepted gated agreements, serving
security/privacy evidence and measured exact-workload qualification remain gates.
