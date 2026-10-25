# Plan 10 v16 accounting audit — 2026-10-08

Scope: read-only interpretation of `outputs/plan10_pair_20261008_142127`.
No rerun and no provider request was made for this audit.

All 192 locked source requests were dispatched. P2a recorded 8 protocol-verified,
76 `finish_reason=length`, and 12 host/protocol-invalid unresolved rows; P2b recorded
8, 75, and 13 respectively. This is an incomplete model-silver protocol run, not a
semantic-quality, human-gold, or retrieval result.

The dominant failure is output truncation at the 1200-token baseline cap. It is evidence
that this cap was insufficient for many rendered regions under this model/prompt; it does
not establish that a higher cap would be legally correct or improve AU quality. No
automatic rerun or structural repair is authorized by this note.

Runtime accounting before this patch can understate provider cost for HTTP 200 responses
that host validation rejected. Future runs retain safe provider usage, finish reason, and
latency for those rows while continuing to omit raw provider bodies.
