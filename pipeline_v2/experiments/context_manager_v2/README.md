# CM4: query review

Current entry point: `live.py`; current tool contract: [CM4.md](CM4.md) and [MODEL_CONTEXT_FLOW.md](MODEL_CONTEXT_FLOW.md).

Use [AG_CHECK](../../reviews/cm4_query_review_v24/AG_CHECK.md) for fresh prepare, live commands and STOP. Only the user or AG runs Modal inference/deployment. No live semantic acceptance follows from local tests.

One search query must be explicitly concluded before the next. Survey all returned cards before deep candidate reads. Source-need decisions are `search_needed`, `no_search_needed`, and `need_more_context`; no citation is required to request a source search. Loop guard defaults to `warn`.

CM2/CM3 replay utilities are separate offline diagnostics, not alternate live policies. Their archived reference is [OFFLINE_REPLAY.md](OFFLINE_REPLAY.md). Do not use old run namespaces or old tool catalogs to control CM4.

Historical diagnostic records (not current run guides): `CM23_ACCEPTANCE.md`, `CM4_LOCAL_CHECK.md`, `REPORT.md`, `OFFLINE_ACCEPTANCE.md`, `PAIR_PROGRESS_FIX.md`, `TOOL_CONTRACT_FIX.md`, and `LIVE_*.md`. Their recorded metrics and receipts are preserved. Follow only the current CM4/AG_CHECK links above for live operation.
