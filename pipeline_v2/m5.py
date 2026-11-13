"""Collect local evidence with a fixed search and reading schedule."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from time import perf_counter

from .agent_harness.contracts import HarnessError, SourceExcerpt, ToolResult, fingerprint, source_hash
from .agent_harness.evidence import SourceDrift


SCHEDULE_VERSION = "m5-local-fixed-evidence-v1"
CHANNELS = ("case_bm25", "passage_bm25")


@dataclass(frozen=True)
class FixedSchedule:
    max_map_pages: int = 2
    max_anchor_needs: int = 2
    max_unmarked_needs: int = 2
    hits_per_channel: int = 5
    max_candidate_opens: int = 5

    def __post_init__(self):
        for name, minimum, maximum in (
            ("max_map_pages", 1, 20),
            ("max_anchor_needs", 0, 10),
            ("max_unmarked_needs", 0, 10),
            ("hits_per_channel", 1, 100),
            ("max_candidate_opens", 0, 50),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise HarnessError(f"Invalid fixed schedule {name}")


def _call(actions, name, args):
    result = actions[name](deepcopy(args))
    if not isinstance(result, ToolResult) or not isinstance(result.observation, dict):
        raise HarnessError(f"{name} must return a ToolResult")
    return result


def _bind_hash(hashes, case_id, value):
    if not isinstance(case_id, str) or not case_id or not source_hash(value):
        raise HarnessError("Invalid fixed baseline source identity")
    if hashes.setdefault(case_id, value) != value:
        raise SourceDrift(case_id)


def _query_map(actions, query_id, hashes, max_pages):
    rows = []
    offset = 0
    total = None
    for pages in range(1, max_pages + 1):
        result = _call(actions, "open_query", {"offset": offset})
        page = result.observation
        if page.get("case_id") != query_id:
            raise SourceDrift(query_id)
        _bind_hash(hashes, query_id, page.get("source_hash"))
        items = page.get("items")
        size = page.get("total")
        if (type(size) is not int or size < 0 or (total is not None and total != size)
                or type(page.get("offset")) is not int or page["offset"] != offset
                or not isinstance(items, list) or offset + len(items) > size):
            raise HarnessError("Invalid query map page")
        total = size
        rows.extend(items)
        end = offset + len(items)
        next_offset = page.get("next_offset")
        if next_offset is None and end == total:
            break
        if type(next_offset) is not int or not offset < next_offset == end < total:
            raise HarnessError("Invalid query map continuation")
        offset = next_offset
    return rows, {"pages_scanned": pages, "max_pages": max_pages,
                  "rows_scanned": len(rows), "total_rows": total,
                  "next_offset": next_offset, "complete": next_offset is None}


def _source_needs(rows, query_id, query_hash, schedule):
    caps = {"anchor": schedule.max_anchor_needs, "unmarked_paragraph": schedule.max_unmarked_needs}
    available = dict.fromkeys(caps, 0)
    selected = dict.fromkeys(caps, 0)
    needs = []
    for row in rows:
        anchor_refs = row.get("anchor_refs", [])
        if anchor_refs:
            kind = "anchor"
        elif row.get("unit_kind") == "paragraph":
            kind = "unmarked_paragraph"
        else:
            continue
        previews = [p for p in row.get("previews", []) if p["text"].strip()]
        if not previews:
            continue
        available[kind] += 1
        if selected[kind] >= caps[kind]:
            continue
        row_anchors = set(anchor_refs)
        preview = next((p for p in previews if row_anchors.intersection(p.get("anchor_refs", []))), previews[0])
        preview_anchors = list(preview.get("anchor_refs", []))
        lead = SourceExcerpt(query_id, query_hash, preview["span_bytes"],
                             preview["text"], preview["text_sha256"])
        start, end = row["span_bytes"]
        if not start <= lead.span_bytes[0] < lead.span_bytes[1] <= end:
            raise HarnessError("Query preview lies outside its navigation row")
        needs.append({
            "source_need_id": fingerprint([query_id, query_hash, row["handle"], kind]),
            "kind": kind,
            "handle": row["handle"],
            "anchor_refs": list(anchor_refs),
            "preview": {**lead.to_record(), "preview_id": preview["preview_id"],
                        "kind": "retrieval_lead", "anchor_refs": preview_anchors,
                        "matched_row_anchor_refs": [ref for ref in preview_anchors if ref in row_anchors]},
            "a_context_refs": [],
        })
        selected[kind] += 1
    return needs, {"eligible_in_scanned_map": available, "selected": selected, "caps": caps}


def _hits(result, limit):
    hits = result.observation.get("hits")
    if not isinstance(hits, list) or len(hits) > limit or result.excerpts:
        raise HarnessError("Invalid fixed baseline search result")
    return hits


def _hit_ref(hit, case_id, hashes):
    ref = hit.get("open_ref")
    if "source_hash" in hit:
        _bind_hash(hashes, case_id, hit["source_hash"])
    if ref is not None:
        if not isinstance(ref, dict) or ref.get("case_id") != case_id:
            raise SourceDrift(case_id)
        if "cursor" in ref:
            raise HarnessError("Search result cannot open a continuation page")
        _bind_hash(hashes, case_id, ref.get("source_hash"))
    return ref


def _check_overlap(case_id, span, raw, other_span, other_text):
    start, end = span
    other_start, other_end = other_span
    left, right = max(start, other_start), min(end, other_end)
    if left < right and raw[left - start:right - start] != other_text.encode("utf-8")[left - other_start:right - other_start]:
        raise SourceDrift(case_id)


def _record_open(result, case_id, hashes, catalog, requests, args):
    observation = result.observation
    if "case_id" in observation and observation["case_id"] != case_id:
        raise SourceDrift(case_id)
    if "source_hash" in observation:
        _bind_hash(hashes, case_id, observation["source_hash"])
    refs = []
    for excerpt in result.excerpts:
        if not isinstance(excerpt, SourceExcerpt):
            raise HarnessError("Invalid fixed baseline source excerpt")
        if excerpt.case_id != case_id:
            raise SourceDrift(case_id)
        _bind_hash(hashes, case_id, excerpt.source_hash)
        raw = excerpt.text.encode("utf-8")
        for known in catalog.values():
            if known["case_id"] == case_id:
                _check_overlap(case_id, excerpt.span_bytes, raw, known["span_bytes"], known["text"])
        catalog.setdefault(excerpt.ref, deepcopy(excerpt.to_record()))
        refs.append(excerpt.ref)
    records = []
    for request in result.source_requests:
        if request.get("case_id") != case_id:
            raise SourceDrift(case_id)
        _bind_hash(hashes, case_id, request.get("source_hash"))
        records.append(deepcopy(request))
    has_pending = (observation.get("next_cursor") is not None
                   or observation.get("complete") is False
                   or any(r.get("pending_spans") or r.get("next_cursor") is not None for r in records))
    status = "partial" if has_pending else "opened" if refs else "empty"
    entry = {"case_id": case_id, "arguments": deepcopy(args), "status": status,
             "excerpt_refs": list(dict.fromkeys(refs)), "source_requests": records,
             "observation": deepcopy(observation)}
    requests.append(entry)
    return entry


def _covers(span, opened):
    start, end = span
    for left, right in sorted(opened):
        if left > start:
            break
        start = max(start, right)
        if start >= end:
            return True
    return False


def _discover(actions, needs, query_id, hashes, limit):
    pairs = {}
    search_log = []
    for need in needs:
        need_id = need["source_need_id"]
        for channel in CHANNELS:
            args = {"channel": channel, "text": need["preview"]["text"], "limit": limit}
            result = _call(actions, "search_corpus", args)
            hits = _hits(result, limit)
            search_log.append({"source_need_id": need_id, "channel": channel, "limit": limit,
                               "returned_hits": len(hits),
                               "coverage": deepcopy(result.observation.get("coverage"))})
            for rank, hit in enumerate(hits, 1):
                candidate_id = hit.get("case_id")
                if not isinstance(candidate_id, str) or not candidate_id or candidate_id == query_id:
                    raise HarnessError("Invalid or self-matching candidate in corpus search")
                ref = _hit_ref(hit, candidate_id, hashes)
                pair = pairs.setdefault(candidate_id, {
                    "query_id": query_id, "candidate_id": candidate_id, "source_need_ids": [],
                    "retrieval_signals": [], "a_context_refs": [], "b_passage_refs": [],
                    "source_requests": [], "open_status": "not_scheduled", "case_relation": "unknown",
                })
                if need_id not in pair["source_need_ids"]:
                    pair["source_need_ids"].append(need_id)
                signal = {"source_need_id": need_id, "channel": channel, "rank": rank,
                          "score": hit.get("score"), "open_ref": deepcopy(ref)}
                pair["retrieval_signals"].append(signal)
    ordered = sorted(pairs.values(), key=lambda p: (
        min(s["rank"] for s in p["retrieval_signals"]), p["candidate_id"]))
    return ordered, search_log


def _candidate_ref(pair, actions, needs, hashes):
    # A passage lead is a usable locator. Case-level scores alone provide no span.
    signals = sorted(pair["retrieval_signals"], key=lambda s: s["rank"])
    direct = next((s for s in signals if s["open_ref"] is not None), None)
    if direct is not None:
        return direct["open_ref"], direct["source_need_id"], None
    candidate_id = pair["candidate_id"]
    need = needs[signals[0]["source_need_id"]]
    args = {"case_id": candidate_id, "text": need["preview"]["text"], "mode": "lexical", "limit": 1}
    result = _call(actions, "search_case", args)
    hits = _hits(result, 1)
    if hits and hits[0].get("case_id") != candidate_id:
        raise SourceDrift(candidate_id)
    ref = _hit_ref(hits[0], candidate_id, hashes) if hits else None
    return ref, need["source_need_id"], {"source_need_id": need["source_need_id"],
                                        "returned_hits": len(hits), "located": ref is not None}


def run_fixed_baseline(tools, *, schedule=None):
    """Open evidence on a fixed local schedule and leave all pair relations unknown."""
    started = perf_counter()
    schedule = FixedSchedule() if schedule is None else schedule
    if not isinstance(schedule, FixedSchedule):
        raise HarnessError("Expected a FixedSchedule")
    query_id = tools.query_case
    tools_fingerprint = tools.fingerprint
    if not isinstance(query_id, str) or not query_id or not isinstance(tools_fingerprint, str) or not tools_fingerprint:
        raise HarnessError("Invalid fixed baseline tools identity")
    actions = tools.actions()
    hashes, catalog, requests = {}, {}, []
    rows, map_coverage = _query_map(actions, query_id, hashes, schedule.max_map_pages)
    needs, need_coverage = _source_needs(rows, query_id, hashes[query_id], schedule)
    pairs, search_log = _discover(actions, needs, query_id, hashes, schedule.hits_per_channel)
    by_need = {need["source_need_id"]: need for need in needs}
    for need in needs:
        preview = need["preview"]
        preview_span = preview["span_bytes"]
        args = {"hit_spans": [list(preview_span)]}
        result = _call(actions, "open_query", args)
        opened = _record_open(result, query_id, hashes, catalog, requests, args)
        preview_raw = preview["text"].encode("utf-8")
        for ref in opened["excerpt_refs"]:
            excerpt = catalog[ref]
            _check_overlap(query_id, preview_span, preview_raw, excerpt["span_bytes"], excerpt["text"])
        need["a_context_refs"] = opened["excerpt_refs"]
        need["preview_span_fully_opened"] = _covers(
            preview_span, [catalog[ref]["span_bytes"] for ref in opened["excerpt_refs"]])
        need["source_requests"] = opened["source_requests"]
        need["open_status"] = opened["status"]
    for pair in pairs:
        pair["a_context_refs"] = list(dict.fromkeys(
            ref for need_id in pair["source_need_ids"] for ref in by_need[need_id]["a_context_refs"]))
    scheduled = pairs[:schedule.max_candidate_opens]
    for pair in scheduled:
        ref, locator_need_id, fallback = _candidate_ref(pair, actions, by_need, hashes)
        pair["locator_source_need_id"] = locator_need_id
        pair["locator_fallback"] = fallback
        if ref is None:
            pair["open_status"] = "unlocated"
            continue
        result = _call(actions, "open_source", ref)
        opened = _record_open(result, pair["candidate_id"], hashes, catalog, requests, ref)
        pair["source_requests"] = opened["source_requests"]
        pair["b_passage_refs"] = opened["excerpt_refs"]
        pair["open_status"] = opened["status"]
    coverage = {
        "query_map": map_coverage, "source_needs": need_coverage,
        "searches": search_log, "candidate_count": len(pairs),
        "candidate_open_cap": schedule.max_candidate_opens,
        "candidate_open_scheduled": len(scheduled),
        "candidate_open_attempts": sum(p["open_status"] in {"opened", "partial", "empty"} for p in scheduled),
        "candidate_open_pending": sum(p["open_status"] == "not_scheduled" for p in pairs),
    }
    return {"status": "evidence_collected", "query_id": query_id,
            "query_source_hash": hashes[query_id], "schedule_version": SCHEDULE_VERSION,
            "schedule": asdict(schedule), "tools_fingerprint": tools_fingerprint,
            "source_needs": needs, "pairs": pairs, "source_catalog": catalog,
            "source_requests": requests, "coverage": coverage, "selected": [],
            "selection_status": "pending_assessment",
            "model_requests": 0, "model_input_tokens": 0, "model_output_tokens": 0,
            "model_delivery_recorded": False, "elapsed_seconds": perf_counter() - started}
