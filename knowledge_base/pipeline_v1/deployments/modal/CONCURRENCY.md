# STEP1: single-GPU concurrency experiment

App: `coliee-qwen35-9b-concurrency`, class `Server` (Modal URL suffix
`--coliee-qwen35-9b-concurrency-server`). The public port 8000 forwards through
the durable gateway to private SGLang port 8001. All routes require Modal proxy
authentication; there is no standalone authentication layer.

`PLX_BENCH_CONCURRENCY` is a deployment-time parameter: exactly `1`, `2`, or `4`,
default `1`. Invalid or empty values fail before app/Volume construction. The
same value configures gateway workers, SGLang `--max-running-requests`, and
`--cuda-graph-max-bs`, and is baked into the image environment. Changing it
requires replacing the experimental deployment. HTTP routing capacity remains
4/8 so job polling can continue during inference; it is not GPU concurrency.

The model revision, one L40S, context length and max-total-tokens (both 12288),
warmup, serving image, mandatory EOS union and runtime hooks match baseline.
Model cache is shared. Jobs exclusively use
`coliee-qwen35-9b-concurrency-jobs`; baseline job Volume is never mounted.
This experimental Volume survives redeploys, but each N uses its own durable
subdirectory: `/job-store/c1`, `/job-store/c2`, or `/job-store/c4`. Workers only
scan their configured subdirectory. Identical payloads within the same N reuse
terminal receipts: the harness must use distinct per-run request identities to
measure fresh inference and separate local output directories. Never copy
baseline receipts into this Volume.

## Preflight interface for Main's harness

Authenticated `GET /v1/benchmark/info` performs no inference and takes no
inference reservation. It returns HTTP 200 even when unavailable, so inspect
`ready`, `poisoned`, `stopping`, and `backend_outcome_unknown`. `/health` returns
the same fields with HTTP 503 when unavailable. Example configured fields:

```json
{
  "experiment": "au-concurrency-v1",
  "app": "coliee-qwen35-9b-concurrency",
  "gateway_concurrency": 2,
  "server_concurrency": 2,
  "cuda_graph_max_bs": 2,
  "max_containers": 1,
  "model": "Qwen/Qwen3.5-9B",
  "model_revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
  "gpu": "L40S:1",
  "cpu": 4,
  "memory_mb": 16384,
  "context_length": 12288,
  "max_total_tokens": 12288,
  "job_volume": "coliee-qwen35-9b-concurrency-jobs",
  "job_store_subdir": "c2",
  "backend_retry": false,
  "exclusive_probes": true,
  "configuration_evidence": "configured_not_live_scheduler",
  "ready": true,
  "poisoned": false,
  "stopping": false,
  "backend_outcome_unknown": false
}
```

The harness must reject baseline URLs, mismatched experiment/app/model/revision,
gateway/server/N, limits or Volume, and any unhealthy safety field before
submitting jobs. These are configured capabilities; live scheduler observations
remain available through the existing exclusive `/v1/diagnostics/json/info`.
CLI/harness changes are outside STEP1's scope.

## Queue and safety contract

Existing job IDs, canonical hashes, POST/GET job routes and response fields are
preserved. N bounded workers recheck queued state under the store mutex and
commit `running` before one backend call. Atomic file replacement and Volume
commits are serialized; slot waiting never holds the store mutex. Probe and
diagnostic reservations exclude every active worker and each other (busy gives
409). Diagnostic replay additionally saves `inference_mode: exclusive` on the
queued job so its eventual inference also runs alone, including after restart.

Unknown dispatch outcome is a sticky fail-closed latch: subsequent admission,
claims and probes stop; already claimed calls may finish and save results.
Transport failures are not retried. Known HTTP failures and response decode
failures remain terminal and are not retried. Commit failure poisons the gateway.
Stop gives all workers one shared grace budget and leaves still-running records
intact. Recovery requires a fresh gateway AND fresh backend container; running
records become interrupted, terminal records never redispatch, queued jobs resume.

## Prepared commands (not executed during implementation)

From repository root, when Main authorizes deployment, choose one N per recreate:

```powershell
$env:PLX_BENCH_CONCURRENCY = '1' # then '2' or '4' for another deployment
.\.venv\Scripts\modal.exe deploy knowledge_base\pipeline_v1\deployments\modal\qwen35_9b_concurrency.py --strategy recreate --stream-logs
```

`recreate` avoids overlapping old/new containers writing the same experimental
job Volume. Do not deploy baseline, edit `.env`, or invoke the baseline diagnostic
CLI for this experiment. Local mock/protocol checks do not establish GPU capacity,
throughput, latency improvement, OOM safety, or AU semantic quality.
