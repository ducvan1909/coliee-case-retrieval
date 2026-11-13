"""Independent behavioral checks for the local fixed M5 evidence baseline."""

from hashlib import sha256
import unittest

from pipeline_v2.agent_harness import SourceDrift, SourceExcerpt, ToolResult
from pipeline_v2.agent_harness.contracts import HarnessError
from pipeline_v2.m5 import FixedSchedule, run_fixed_baseline


def digest(raw):
    return sha256(raw).hexdigest()


def make_excerpt(case_id, source_hash, start, text, provenance=None):
    raw = text.encode("utf-8")
    return SourceExcerpt(case_id, source_hash, (start, start + len(raw)), text, digest(raw),
                         provenance or {"fixture": case_id, "offset": start})


class FixedTools:
    """Small M4-shaped tool double with explicit map, search, and open receipts."""

    def __init__(self, rows, *, candidate_hits=None, case_hits=None, open_results=None,
                 map_page_size=None, query_id="A.txt", query_hash=None):
        self.query_case = query_id
        self.fingerprint = "fixture-tools-fingerprint"
        self.query_hash = query_hash or "a" * 64
        self.rows = rows
        self.candidate_hits = candidate_hits or {}
        self.case_hits = case_hits or {}
        self.open_results = open_results or {}
        self.map_page_size = map_page_size or max(1, len(rows))
        self.calls = []

    def actions(self):
        return {"open_query": self.open_query, "search_corpus": self.search_corpus,
                "search_case": self.search_case, "open_source": self.open_source}

    def open_query(self, args):
        args = dict(args)
        self.calls.append(("open_query", args))
        if "offset" in args:
            offset = args["offset"]
            end = min(len(self.rows), offset + self.map_page_size)
            return ToolResult({"case_id": self.query_case, "source_hash": self.query_hash,
                               "total": len(self.rows), "offset": offset,
                               "next_offset": end if end < len(self.rows) else None,
                               "items": [{k: v for k, v in row.items() if k != "a_excerpt"
                                          and k != "a_source_request"}
                                         for row in self.rows[offset:end]]})
        if set(args) == {"hit_spans"}:
            span = args["hit_spans"][0]
            row = next(r for r in self.rows if r["span_bytes"] == span)
            pending = row.get("a_source_request")
            return ToolResult({"case_id": self.query_case, "source_hash": self.query_hash,
                               "complete": pending is None}, excerpts=(row["a_excerpt"],),
                              source_requests=() if pending is None else (pending,))
        if set(args) != {"handles"}:
            raise AssertionError(f"unexpected query open arguments: {args}")
        excerpts = tuple(self.rows_by_handle[h]["a_excerpt"] for h in args["handles"])
        pending = self.rows_by_handle[args["handles"][0]].get("a_source_request")
        requests = () if pending is None else (pending,)
        return ToolResult({"case_id": self.query_case, "source_hash": self.query_hash,
                           "complete": pending is None}, excerpts=excerpts,
                          source_requests=requests)

    @property
    def rows_by_handle(self):
        return {row["handle"]: row for row in self.rows}

    def search_corpus(self, args):
        args = dict(args)
        self.calls.append(("search_corpus", args))
        hits = self.candidate_hits.get((args["text"], args["channel"]), [])
        return ToolResult({"hits": list(hits), "coverage": {"fixture": True}})

    def search_case(self, args):
        args = dict(args)
        self.calls.append(("search_case", args))
        return ToolResult({"hits": list(self.case_hits.get(args["case_id"], []))})

    def open_source(self, args):
        args = dict(args)
        self.calls.append(("open_source", args))
        value = self.open_results[args["case_id"]]
        if callable(value):
            value = value(args)
        return value


def map_row(handle, text, start, *, anchor_refs=(), unit_kind="paragraph",
            preview_id=None, preview_anchor_refs=None):
    raw = text.encode("utf-8")
    source_hash = "a" * 64
    excerpt = make_excerpt("A.txt", source_hash, start, text, {"fixture_handle": handle})
    preview = {"preview_id": preview_id or f"preview-{handle}", "text": text,
               "text_sha256": digest(raw), "span_bytes": [start, start + len(raw)],
               "anchor_refs": list(anchor_refs if preview_anchor_refs is None else preview_anchor_refs)}
    return {"handle": handle, "span_bytes": [start, start + len(raw)], "unit_kind": unit_kind,
            "anchor_refs": list(anchor_refs), "previews": [preview], "a_excerpt": excerpt}


def lead(case_id, source_hash, *, passage_id="p1", score=1.0):
    return {"case_id": case_id, "source_hash": source_hash, "score": score,
            "open_ref": {"case_id": case_id, "source_hash": source_hash,
                         "passage_ids": [passage_id]}}


class M5FixedBaselineTests(unittest.TestCase):
    def test_fixed_order_caps_dedup_and_same_preview_keeps_need_provenance(self):
        # Identical preview text in two handles still represents two source needs/locations.
        rows = [map_row("a-anchor-1", "quoted issue", 0, anchor_refs=("anchor-1",)),
                map_row("a-anchor-2", "quoted issue", 20, anchor_refs=("anchor-2",)),
                map_row("a-unmarked-1", "unmarked issue", 40),
                map_row("a-unmarked-2", "ignored by per-kind cap", 60)]
        rows[0]["a_source_request"] = {"case_id": "A.txt", "source_hash": "a" * 64,
                                        "pending_spans": [[100, 140]], "next_cursor": "A-cursor"}
        b_hash = "b" * 64
        hits = {("quoted issue", channel): [lead("B.txt", b_hash), lead("B.txt", b_hash, passage_id="p2")]
                for channel in ("case_bm25", "passage_bm25")}
        hits.update({("unmarked issue", channel): [lead("B.txt", b_hash)]
                     for channel in ("case_bm25", "passage_bm25")})
        tools = FixedTools(rows, candidate_hits=hits, map_page_size=2)
        tools.open_results["B.txt"] = ToolResult(
            {"case_id": "B.txt", "source_hash": b_hash, "next_cursor": "cursor-B", "complete": False},
            excerpts=(make_excerpt("B.txt", b_hash, 100, "opened B evidence"),),
            source_requests=({"case_id": "B.txt", "source_hash": b_hash,
                             "pending_spans": [[120, 180]], "next_cursor": "cursor-B"},))
        schedule = FixedSchedule(max_map_pages=2, max_anchor_needs=1,
                                 max_unmarked_needs=1, hits_per_channel=2,
                                 max_candidate_opens=1)

        result = run_fixed_baseline(tools, schedule=schedule)

        self.assertEqual([n["handle"] for n in result["source_needs"]],
                         ["a-anchor-1", "a-unmarked-1"])
        self.assertEqual(len({n["source_need_id"] for n in result["source_needs"]}), 2)
        self.assertEqual(result["source_needs"][0]["preview"]["text"], "quoted issue")
        self.assertEqual([call for call, _ in tools.calls if call == "search_corpus"],
                         ["search_corpus"] * 4)
        search_args = [args for name, args in tools.calls if name == "search_corpus"]
        self.assertEqual([(a["channel"], a["text"]) for a in search_args], [
            ("case_bm25", "quoted issue"), ("passage_bm25", "quoted issue"),
            ("case_bm25", "unmarked issue"), ("passage_bm25", "unmarked issue")])
        self.assertEqual([name for name, _ in tools.calls], [
            "open_query", "open_query", "search_corpus", "search_corpus", "search_corpus",
            "search_corpus", "open_query", "open_query", "open_source"])
        self.assertEqual([args for name, args in tools.calls if name == "open_query"], [
            {"offset": 0}, {"offset": 2}, {"hit_spans": [[0, len("quoted issue") ] ]},
            {"hit_spans": [[40, 40 + len("unmarked issue")]]}])
        self.assertEqual(len(result["pairs"]), 1)
        pair = result["pairs"][0]
        self.assertEqual(pair["candidate_id"], "B.txt")
        self.assertEqual(len(pair["source_need_ids"]), 2)
        self.assertEqual(pair["case_relation"], "unknown")
        self.assertEqual(pair["open_status"], "partial")
        self.assertEqual(pair["source_need_ids"], [n["source_need_id"] for n in result["source_needs"]])
        self.assertEqual(result["source_needs"][0]["source_requests"][0]["pending_spans"], [[100, 140]])
        self.assertEqual(len(pair["b_passage_refs"]), 1)
        self.assertEqual(pair["source_requests"][0]["pending_spans"], [[120, 180]])
        self.assertEqual(result["source_needs"][0]["preview_span_fully_opened"], True)
        self.assertEqual(pair["locator_source_need_id"], result["source_needs"][0]["source_need_id"])
        self.assertEqual(len(pair["retrieval_signals"]), 6)
        self.assertEqual(len([args for name, args in tools.calls if name == "open_source"]), 1)
        self.assertEqual(result["coverage"]["candidate_open_scheduled"], 1)
        self.assertEqual(result["model_requests"], 0)
        self.assertFalse(result["model_delivery_recorded"])
        self.assertEqual(result["selected"], [])

    def test_candidate_cap_limits_opens_not_dossiers_and_case_only_lead_uses_bounded_fallback(self):
        row = map_row("need-1", "need text", 0, anchor_refs=("cue",))
        b_hash, c_hash, d_hash = "b" * 64, "c" * 64, "d" * 64
        hits = {("need text", channel): [
            {"case_id": "B.txt", "score": 3.0},
            {"case_id": "C.txt", "score": 2.0, "source_hash": c_hash},
            lead("D.txt", d_hash, score=1.0),
        ] for channel in ("case_bm25", "passage_bm25")}
        tools = FixedTools([row], candidate_hits=hits,
                           case_hits={"B.txt": [lead("B.txt", b_hash)]})
        tools.open_results["B.txt"] = ToolResult({"case_id": "B.txt", "source_hash": b_hash},
            excerpts=(make_excerpt("B.txt", b_hash, 10, "B raw excerpt"),))
        tools.open_results["D.txt"] = ToolResult({"case_id": "D.txt", "source_hash": d_hash},
            excerpts=(make_excerpt("D.txt", d_hash, 20, "D raw excerpt"),))

        result = run_fixed_baseline(tools, schedule=FixedSchedule(max_map_pages=1,
            max_anchor_needs=1, max_unmarked_needs=0, hits_per_channel=3, max_candidate_opens=2))

        self.assertEqual([p["candidate_id"] for p in result["pairs"]], ["B.txt", "C.txt", "D.txt"])
        self.assertEqual(result["coverage"]["candidate_count"], 3)
        self.assertEqual(result["coverage"]["candidate_open_scheduled"], 2)
        b = result["pairs"][0]
        self.assertEqual(b["locator_fallback"], {"source_need_id": result["source_needs"][0]["source_need_id"],
                                                  "returned_hits": 1, "located": True})
        self.assertEqual(b["locator_source_need_id"], result["source_needs"][0]["source_need_id"])
        self.assertEqual(b["open_status"], "opened")
        self.assertEqual(result["pairs"][1]["open_status"], "unlocated")
        self.assertEqual(result["pairs"][2]["open_status"], "not_scheduled")
        self.assertTrue(all(p["case_relation"] == "unknown" for p in result["pairs"]))
        b_searches = [args for name, args in tools.calls if name == "search_case"]
        self.assertEqual(b_searches, [
            {"case_id": "B.txt", "text": "need text", "mode": "lexical", "limit": 1},
            {"case_id": "C.txt", "text": "need text", "mode": "lexical", "limit": 1},
        ])
        self.assertEqual([args["case_id"] for name, args in tools.calls if name == "open_source"],
                         ["B.txt"])

    def test_a_raw_context_and_candidate_refs_come_only_from_actual_opens(self):
        row = map_row("need", "visible preview", 0, anchor_refs=("a1",))
        b_hash = "b" * 64
        tools = FixedTools([row], candidate_hits={
            ("visible preview", channel): [lead("B.txt", b_hash)]
            for channel in ("case_bm25", "passage_bm25")})
        tools.open_results["B.txt"] = ToolResult(
            {"case_id": "B.txt", "source_hash": b_hash},
            excerpts=(make_excerpt("B.txt", b_hash, 500, "actual B raw excerpt"),))

        result = run_fixed_baseline(tools)

        need = result["source_needs"][0]
        pair = result["pairs"][0]
        a_excerpt = tools.rows[0]["a_excerpt"]
        b_excerpt = next(e for e in tools.open_results["B.txt"].excerpts)
        self.assertEqual(need["preview"]["ref"], a_excerpt.ref)
        self.assertEqual(need["a_context_refs"], [a_excerpt.ref])
        self.assertEqual(pair["a_context_refs"], [a_excerpt.ref])
        self.assertEqual(pair["b_passage_refs"], [b_excerpt.ref])
        self.assertEqual(result["source_catalog"][a_excerpt.ref]["case_id"], "A.txt")
        self.assertEqual(result["source_catalog"][b_excerpt.ref]["case_id"], "B.txt")
        self.assertEqual(pair["case_relation"], "unknown")

    def test_query_case_search_hit_fails_closed_instead_of_becoming_candidate(self):
        row = map_row("need", "query text", 0, anchor_refs=("cue",))
        tools = FixedTools([row], candidate_hits={
            ("query text", channel): [{"case_id": "A.txt"}]
            for channel in ("case_bm25", "passage_bm25")})
        with self.assertRaises(HarnessError):
            run_fixed_baseline(tools)

    def test_wrong_source_hash_and_source_drift_fail_closed(self):
        row = map_row("need", "query text", 0, anchor_refs=("cue",))
        b_hash = "b" * 64
        tools = FixedTools([row], candidate_hits={
            ("query text", channel): [lead("B.txt", b_hash)]
            for channel in ("case_bm25", "passage_bm25")})
        tools.open_results["B.txt"] = ToolResult(
            {"case_id": "B.txt", "source_hash": "c" * 64},
            excerpts=(make_excerpt("B.txt", "c" * 64, 10, "changed source"),))
        with self.assertRaises(SourceDrift):
            run_fixed_baseline(tools)

        tools = FixedTools([row], query_hash="d" * 64)
        # The map source identity cannot silently change between pages.
        def changed_query_hash(args):
            tools.calls.append(("open_query", dict(args)))
            return ToolResult({"case_id": "A.txt", "source_hash": "e" * 64,
                               "total": 1, "offset": 0, "next_offset": None,
                               "items": [row]})
        tools.actions = lambda: {"open_query": changed_query_hash,
            "search_corpus": tools.search_corpus, "search_case": tools.search_case,
            "open_source": tools.open_source}
        # Page two cannot silently bind the same query case to a different source.
        def changing_page(args):
            offset = args["offset"]
            return ToolResult({"case_id": "A.txt", "source_hash": "d" * 64 if offset == 0 else "e" * 64,
                               "total": 2, "offset": offset,
                               "next_offset": 1 if offset == 0 else None,
                               "items": [row if offset == 0 else map_row("other", "other", 20)]})
        tools.rows = [row, map_row("other", "other", 20)]
        tools.map_page_size = 1
        tools.actions = lambda: {"open_query": changing_page,
            "search_corpus": tools.search_corpus, "search_case": tools.search_case,
            "open_source": tools.open_source}
        with self.assertRaises(SourceDrift):
            run_fixed_baseline(tools)

    def test_repeated_preview_text_retains_two_a_refs_but_one_unknown_pair(self):
        rows = [map_row("need-one", "same preview", 0, anchor_refs=("cue-1",)),
                map_row("need-two", "same preview", 30, anchor_refs=("cue-2",))]
        b_hash = "b" * 64
        hits = {("same preview", channel): [lead("B.txt", b_hash)]
                for channel in ("case_bm25", "passage_bm25")}
        tools = FixedTools(rows, candidate_hits=hits)
        tools.open_results["B.txt"] = ToolResult(
            {"case_id": "B.txt", "source_hash": b_hash},
            excerpts=(make_excerpt("B.txt", b_hash, 100, "B source"),))

        result = run_fixed_baseline(tools, schedule=FixedSchedule(max_anchor_needs=2,
            max_unmarked_needs=0, max_candidate_opens=1))

        self.assertEqual([n["handle"] for n in result["source_needs"]], ["need-one", "need-two"])
        self.assertNotEqual(result["source_needs"][0]["source_need_id"],
                            result["source_needs"][1]["source_need_id"])
        self.assertNotEqual(result["source_needs"][0]["a_context_refs"],
                            result["source_needs"][1]["a_context_refs"])
        self.assertEqual(len(result["pairs"]), 1)
        self.assertEqual(result["pairs"][0]["source_need_ids"],
                         [need["source_need_id"] for need in result["source_needs"]])
        self.assertEqual(result["pairs"][0]["case_relation"], "unknown")

    def test_schedule_rejects_bool_caps(self):
        with self.assertRaises(HarnessError):
            FixedSchedule(max_map_pages=True)


if __name__ == "__main__":
    unittest.main()
