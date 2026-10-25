# Isolated bulk and corpus execution

App `coliee-qwen35-9b-bulk`, class `Server`; job Volume
`coliee-qwen35-9b-bulk-jobs`, subdirectory `/job-store/bulk-v1`.
Fixed gateway/server C4 and one L40S. Model revision
`c202236235762e1c871ad0ccb60c8ee5ba337b9a`, model cache, image,
12288 context/total tokens, CPU 4, memory 16384 MiB, grammar warmup,
cache report and mandatory EOS/runtime hooks match the concurrency deployment.
Baseline and concurrency sources/Volumes are untouched. All HTTP routes require
Modal proxy authentication. Do not expose the FastAPI app as a standalone public
server; it has no independent authentication layer. Access logs are disabled.

## Host interface

Canonical JSON is UTF-8, `sort_keys=True`, separators `(',', ':')`,
`ensure_ascii=False`, `allow_nan=False`. SHA-256 is lowercase hex.
Each capsule is exactly `{'job_id': sha256(canonical_json(payload)), 'payload': payload}`.
Streaming is unsupported. Duplicate IDs within a group are rejected.
Capsule list order is significant; payload object key order is not.

Group identity is exactly:

```python
sha256(canonical_json({'mode': 'bulk' if batch else 'corpus', 'jobs': ordered_capsules}))
```

- `POST /v1/batches`: `{'batch_id': group_id, 'jobs': ordered_capsules}`;
  recommend 16 jobs, maximum 32 jobs and 4 MiB request body.
- `POST /v1/corpora`: `{'corpus_id': group_id, 'jobs': ordered_capsules}`;
  maximum 600 jobs and 16 MiB request body. Submit the workload once; the server
  admits and checkpoints jobs without host subgroup submission.
- `GET /v1/batches/{group_id}?after=0&limit=16` and
  `GET /v1/corpora/{group_id}?after=0&limit=16` share the progress contract.

POST returns 202 and the progress envelope. IDs and manifests are immutable:
same mode/ID/capsules reuses existing state, even when unhealthy (unless store
durability is poisoned); ID/hash/payload conflict returns 409. A lost POST ack is
recoverable with GET or identical POST. Mode participates in the hash and storage
namespace, so batch and corpus have distinct identities. New workload admission
is blocked when unhealthy. Invalid shape/count/cursor returns 400; excessive
body returns 413; unknown group returns 404.

```json
{
  "group_id": "<64 lowercase hex>",
  "mode": "bulk",
  "status": "running",
  "counts": {"total": 16, "queued": 10, "running": 4,
             "completed": 2, "failed": 0, "interrupted": 0},
  "cursor": 2,
  "next_cursor": 2,
  "results": []
}
```

`cursor` echoes input `after`. `next_cursor = after + len(results)`. Terminal
events include completed, failed and interrupted jobs, exactly once per group,
in durable completion checkpoint order, **not source position**. Continue from
`next_cursor`; an earlier source job completing later is appended and cannot
be skipped. Cursor is an integer in `0..current_event_sequence`, limit is
`1..32`, default 16. An empty page keeps the same cursor. Poll until terminal
counts equal total and all pages are consumed; a terminal group may have more
than one page left. `status` is queued/running/completed/failed/interrupted;
an unfinished unhealthy group is blocked.

Each result includes `job_id`, `payload_sha256`, terminal `status`, the full raw
OpenAI `response`, canonical `response_sha256`, `usage`, `inference_seconds`,
`timestamps` (created/started/updated/finished UTC times) and `error`. Unknown or
unavailable fields are null; interrupted restart latency cannot be reconstructed.
Flat timestamps and provider HTTP status may additionally appear. Request payloads
are omitted. Raw responses are only returned through the authenticated API;
provider error messages/bodies and credentials are not logged or persisted as errors.

Private compatibility `POST /v1/jobs`, `GET /v1/jobs/{job_id}`, exclusive synchronous
`POST /v1/chat/completions`, and JSON diagnostic info/replay routes are retained.
Single-job admission returns 429 if the global window is full. Replay remains an
exclusive queued job with pinned diagnostic validation; no backend retry is added.

## Durability and controller

There is one process and one shared store mutex. The global admission window is
16 queued+running job markers across active groups and private replay jobs; C4
workers execute admitted jobs. Remaining capsules count as queued without a
marker. The payload manifest is atomically saved once under `active/{mode}/`
before its recoverable state index and any pending markers. It moves, without
rewriting its payload, to `manifests/{mode}/` when terminal. The entire manifest
is durable before POST acknowledgement. Pending job records refer to its capsule
by mode/group/index; terminal receipts omit payloads. Multiple groups referencing
the same immutable job share its receipt and never dispatch it twice.

`pending/` is separate from `archive/`. Workers choose from the in-memory pending
index, with no archive glob per claim. Startup scans pending markers and active
manifests once, rebuilds membership/status indexes, and reconciles only referenced
receipts. A crash before status-index or pending-marker creation retains the
authoritative active manifest. Unadmitted capsules are reconstructed from it.
Submission and recovery build per-group deques of unadmitted capsule indices.
Refill consumes these indices once, stopping immediately when the window is full;
it does not iterate finished manifest entries on every completion. Deques are
in-memory accelerators, rebuilt from the authoritative manifest/status/markers
after a crash. Shared-job entries already admitted or completed are skipped.
GET uses current status indexes and reads only the requested receipt page; it
does not read every historical response or the payload manifest on every poll.

A running claim and its status index must commit before backend dispatch. One
call maximum per job. Terminal receipt and terminal event index commit before
pending marker removal, allowing idempotent restart reconciliation. Commit
failure poisons the process, preventing further admission/dispatch/progress.
Normal running claims require one commit before dispatch. Normal terminal
persistence requires two commits: receipt+event index first, then pending-marker
cleanup, completed-manifest retirement and bounded refill together. No cleanup
or refill may dispatch before the first commit succeeds. POST acknowledges only
after its manifest, status index and admitted markers are durable. This reduces
completion commit overhead without weakening either durability barrier.
Recovery never resubmits running work: it becomes interrupted with unknown
outcome. Unknown transport/probe/restart outcomes set a durable sticky unhealthy
marker, blocking new claims/submissions/probes; already claimed calls can finish.
Redeploy does not clear this marker. There is no repair, flush, clear-latch,
backend retry or global cache operation. Known HTTP and decode failures are
terminal without retries. Blocked remaining jobs stay queued for explicit Main
handling outside this API. Shutdown grants all workers one shared grace budget;
unfinished running records remain for restart reconciliation.

The deployment keeps `min_containers=0` and a 120-second scaledown window.
Corpus workers are internal threads, not active Modal invocations. Server-side
admission removes the need to submit subgroups, but does **not** guarantee work
will run to completion after the client disconnects. If polling stops for more
than 120 seconds, Modal may terminate the container while backend inference is
running. Recovery then marks that work interrupted/unknown and fails closed as
above; it never retries the backend. Main's trial host polls every two seconds.
Continue polling for trial execution; no permanently warm `min_containers=1`
configuration or associated standing GPU cost is introduced. This lifecycle
limitation has not been tested remotely.

Probe/diagnostic reservations exclude all job inference, even when only one of
four workers is active. They reject busy state with 409 instead of waiting while
holding the store lock. Production job completion can occur out of order.

## Configuration preflight

`GET /v1/benchmark/info` returns `experiment: 'au-bulk-v1'`, the app and job Volume
above, C4/model/hardware/memory/context fields, `admission_window: 16`,
`backend_retry: false`, `exclusive_probes: true`, limits and:

```json
{"capabilities": {"bulk_submit": true, "incremental_progress": true,
                  "pending_queue": true, "corpus_runner": true}}
```

Inspect `unhealthy`, `ready`, `poisoned`, `stopping`, and
`backend_outcome_unknown`; info remains HTTP 200, `/health` is 503 when unhealthy.
These are configured facts, not live GPU scheduler or throughput evidence.

No deployment, model download, GPU inference or paid provider call is authorized
by this implementation task. Once Main separately authorizes deployment, use
the bulk file and recreate strategy to avoid old/new writers sharing this Volume.
Local mock protocol checks do not establish remote lifecycle behavior, GPU OOM
safety, throughput gain, latency benefit, or semantic AU quality.
