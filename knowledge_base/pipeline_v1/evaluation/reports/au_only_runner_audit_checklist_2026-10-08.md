# AU-only runner — independent audit checklist

Date: 2026-10-08  
Scope: implementation-readiness checklist. At audit time no AU-only runner module/CLI was present; existing `au_baseline` is a Plan07/P2a/P2b runner and is not evidence for this requirement. No Modal call or runtime-code edit was made.

## Required boundary

An AU-only runner must take a frozen AU-only manifest as its sole workload authority. At runtime it must not import, resolve, load, or require `analysis_regions`, P2a/P2b, `ContextHint`, their reports, their policies, or their artifact references. A source store is permitted only to reopen exact source text after manifest identity validation.

The runner must not silently fall back to the Plan07 pointer. Its CLI defaults, imports, manifest loader, prompt builder, cache key, output schema, and preflight must all be independently free of that dependency graph.

## Mandatory manifest checks

Before preflight or any provider setup, validate:

* manifest schema/version and canonical manifest hash;
* case ID, source version/hash, and current source bytes hash;
* exact target IDs, uniqueness across the entire manifest, and deterministic target order;
* target spans/quotes/checksums within the verified source, with no duplicate or overlapping owner assignment unless the AU-only contract explicitly permits it;
* explicit prompt/schema/model/cap identities and request/cache identity including all of them; and
* every requested source span is a manifest-approved span. No dynamically inserted P2/ContextHint source span is allowed.

Mutations of source hash, target ID, target order, duplicate target, span/quote, schema, cap, or model must fail before the opener/provider is invoked.

## Preflight and credentials

`preflight` must construct and validate the locked AU-only requests and all aggregate reservations without resolving a token, calling `modal_config(...require_credentials=True)`, or touching Modal. It should report configuration incompleteness distinctly from credential absence. A fake environment with no secrets must still run preflight deterministically.

Remote execution remains explicit (`--execute` plus a finite request cap) and may require credentials only after preflight succeeds.

## Result taxonomy and accounting

Persist a safe receipt for every attempted request, with these disjoint meanings:

| Class | Provider call / usage treatment |
|---|---|
| `protocol_verified` | Provider returned and output passed structural/protocol validation. |
| `host_validation` (or equivalent) | Provider returned HTTP 200/result but local schema/span/target validation failed; retain safe provider usage, finish reason, latency, and response hash/length, never raw body. |
| provider HTTP/transport/malformed response | Preserve safe diagnostic; provider usage is `unavailable`, not asserted as zero. |
| semantic review outcome | Separate from structural/protocol status. It requires its own adjudicated evidence and cannot be inferred from valid JSON/AU spans. |
| budget/target/per-request stop | No provider call; explicit stop reason. |

`length`/`content_filter` after a provider response must retain safe provider usage, remain terminal unless a separately documented repair policy applies, and never be misclassified as transport. Accounting reports must separate known provider usage, unavailable provider usage attempts, reservation envelopes, and no-call stops.

## Cache, resume, and budget checks

Cache entries must bind exact request identity, manifest hash, source hash, model/prompt/schema/caps, and safe receipt. A stale/corrupt/mismatched entry fails closed. Valid cache hits consume no new provider attempt or runtime reservation; a resume must not overwrite the previous attempt without immutable archive/provenance.

Preflight reserves all allowed AU-only logical requests and bounded retry/warmup slots before dispatch. Runtime shares one budget state across the complete AU-only manifest, persists attempts write-ahead, and prevents a request/provider attempt exceeding any cap before calling the opener. `length` usage counts toward actual known usage and the selected reservation policy.

## Required automated tests

1. Import/AST or dependency-injection test: loading/running AU-only preflight succeeds when P2/ContextHint modules/reports are deliberately unavailable; source search must find no runtime imports of them.
2. Source-hash, target duplicate, target-order, span/quote, and manifest-hash mutations each fail before a fake opener is called.
3. Preflight with empty credentials succeeds/fails only on non-secret configuration; remote execute without explicit authorization does not dispatch.
4. HTTP-200 valid response, HTTP-200 malformed/schema/span-invalid response, HTTP error, transport error, `length`, and content filter each persist the correct distinct status/receipt/usage semantics.
5. A fabricated semantically weak but structurally valid response cannot be labeled semantic-pass; a semantic metric is absent unless a supplied adjudicated evaluation fixture supports it.
6. Cache hit is free; wrong cache identity fails; resume archives/references the predecessor row; cache and request identity change with model/prompt/schema/cap/source changes.
7. Aggregate source/provider/token/USD boundaries, including one request beyond each cap, fail before opener invocation; retry/warmup counters persist across resume.
8. Output manifest/report has exact target coverage, no duplicates, explicit incomplete reasons, and does not claim P2 comparison, ContextHint effect, retrieval quality, or human-gold semantic accuracy.

## Acceptance decision rule

Pass only when the implementation and tests demonstrate all the above with fake openers and local fixtures. A green legacy Plan10 suite alone is insufficient because it exercises P2-derived workload construction. Even a structurally valid AU-only result is not an AU semantic-quality result without adjudicated gold/review.
