# AU-only runner focused cache-fix final audit

Date: 2026-10-08  
Scope: cache-key P0 repair, fake `length` and HTTP-200 host-validation paths, resume behavior, and focused regression tests. No Modal call and no runtime edit.

## Verdict

**PASS for the prior cache-key/cache-resume P0.** No remaining cache P0 was found in the tested paths.  
**Conditional remote-budget blocker remains:** if a USD cap is configured, the runner must reject missing price rates; current code does not do so.

## Cache P0 repair — verified

The token aggregation loop now uses `usage_field`, leaving request `key` unchanged before the cache row is persisted. The new AU-only tests exercise the exact failure modes found in the prior audit:

| Fake provider path | First-run receipt | Second run |
|---|---|---|
| `finish_reason=length`, usage `{7,8,15}` | `output_truncated`, usage retained, hashed cache key (not `total_tokens`) | cache hit; opener call count stays at 10 |
| HTTP-200 `stop` with invalid `{}` output, usage `{7,8,15}` | `host_validation`, usage retained, hashed cache key | cache hit; opener call count stays at 10 |

The test uses one temporary root with `cache_dir=root/cache`, so the same persisted `runtime_ledger.json` and cache rows are exercised on the second invocation. This demonstrates the repair both preserves known usage and accepts the persisted cache row without another provider call.

The current code also retains the preceding P0 repairs: provider-attempt preflight gate, actual contract evidence-span/attribution-span checks, model/thinking configuration binding, and write-ahead ledger counters.

## Test result

```
python -m unittest knowledge_base.pipeline_v1.tests.test_au_only knowledge_base.pipeline_v1.tests.test_plan10 -v
Ran 38 tests ... OK
```

AU-only now has five focused tests. The new two cover `run` for length/host-validation with known usage and resume cache hit. Plan10 remains regression evidence only.

## Remaining blocker before a USD-capped remote run

`preflight` computes `reserved_usd_micros=None` when both per-1K price rates are zero, even if `max_usd_micros` is set. It therefore does not append `usd_cap`; runtime likewise reserves zero USD. A configured USD ceiling then has no enforceable meaning.

Required fail-closed rule: if `max_usd_micros` is non-null, require at least one nonzero/known provider price rate (or a documented fixed-price method), otherwise preflight must fail with a distinct missing-price error before provider setup. Add a no-price+USD-cap fixture and one-over-USD-cap no-opener fixture.

If no USD cap is requested, this condition does not invalidate the tested cache fix. If a USD cap is part of the intended remote authorization, it remains a P0 budget blocker.

## Residual test gaps (not observed failures)

No AU-only test yet covers HTTP/transport `usage_unavailable`, an actually schema-valid but bad evidence quote/span, model/thinking mismatch, or an aggregate cap stop after a persisted partial ledger. These should be added before a broader unattended remote campaign. They do not negate the focused cache-resume PASS above.

`complete` remains protocol completion only; the artifact continues to set `semantic_gold=false` and makes no semantic-quality claim.
