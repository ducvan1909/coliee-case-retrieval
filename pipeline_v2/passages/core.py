"""Raw Unicode slices with measured token bounds, not inferred legal units."""
import re

from ..source.core import Utf8Map, canonical, digest
from .tokenizer import PassageError


def split_text(text, tokenizer, profile):
    """Keep fitting parents intact; split longer parents with measured overlap.

    Offset mappings propose cuts only. Each returned raw substring is encoded
    independently with special tokens; no decoded token string becomes source.
    Whitespace cuts are preferred. A codepoint fallback preserves long words.
    """
    maximum, target, overlap = (profile[k] for k in ("max_input_tokens", "target_tokens", "overlap_tokens"))
    if not (type(maximum) is int and type(target) is int and type(overlap) is int
            and 0 <= overlap < target <= maximum):
        raise PassageError("Invalid target/overlap/max token profile")
    if not text:
        raise PassageError("Empty structural parent")
    total = tokenizer.count(text)
    if total <= maximum:
        return [{"start": 0, "end": len(text), "token_count": total, "overlap_tokens": 0,
                 "boundary_method": "whole_parent", "word_boundary_split": False}]
    result, start, previous_end = [], 0, 0
    while start < len(text):
        tail = text[start:]
        offsets = tokenizer.offsets(tail)
        positive = sorted(set(b for a, b in offsets if b > 0))
        if not positive:
            # Some tokenizers omit whitespace offsets; raw must still survive.
            end = len(text)
        else:
            end = start + positive[min(target, len(positive)) - 1]
        end = min(len(text), max(start + 1, end))
        # Prefer a nearby whitespace boundary, preserving whitespace in spans.
        if end < len(text):
            matches = list(re.finditer(r"\s+", text[start:end]))
            if matches and matches[-1].end() >= (end-start)//2:
                end = start + matches[-1].end()
        count = tokenizer.count(text[start:end])
        # Exact re-encoding is the gate, even if offset counts suggested a fit.
        while count > maximum:
            end = start + max(1, (end-start)*3//4)
            count = tokenizer.count(text[start:end])
            if end == start+1 and count > maximum:
                raise PassageError("One Unicode codepoint exceeds full-input cap")
        # Avoid overlap-only chunks and guarantee advancing coverage.
        if end <= previous_end:
            start = previous_end
            continue
        actual_overlap = tokenizer.count_content(text[start:previous_end]) if result and start < previous_end else 0
        result.append({"start": start, "end": end, "token_count": count,
                       "overlap_tokens": actual_overlap,
                       "boundary_method": "whitespace_or_codepoint_fallback_not_sentence_verified",
                       "word_boundary_split": end < len(text) and not text[end-1].isspace() and not text[end].isspace()})
        if end == len(text):
            break
        # Offset mapping picks an overlap start; exact re-encode measures cap.
        piece = text[start:end]
        offsets = tokenizer.offsets(piece)
        candidates = sorted(set(a for a,b in offsets if 0 <= a < len(piece)))
        candidate = candidates[max(0, len(candidates)-overlap)] if overlap and candidates else len(piece)
        next_start = start + candidate
        whites = list(re.finditer(r"\s+", text[next_start:end]))
        if whites:
            next_start += whites[0].end()
        while next_start < end and tokenizer.count_content(text[next_start:end]) > overlap:
            next_start += 1
        previous_end = end
        start = max(start+1, min(end, next_start))
    if not result or result[0]["start"] != 0 or result[-1]["end"] != len(text):
        raise PassageError("Incomplete parent coverage")
    return result


def build_case_passages(case_id, raw, navigation, profile, tokenizer):
    mapping = Utf8Map(raw)
    source_hash = digest(raw)
    policy_hash = digest(canonical(profile))
    passages, parents = [], []
    for row in navigation["navigation"]:
        bs, be = row["span_bytes"]
        cs, ce = mapping.byte_to_char(bs), mapping.byte_to_char(be)
        body = mapping.text[cs:ce]
        slices = split_text(body, tokenizer, profile)
        ids = [f"{case_id[:-4]}:{digest(canonical([row['unit_id'],policy_hash,tokenizer.fingerprint,s['start'],s['end']]))[:24]}" for s in slices]
        parents.append({"unit_id": row["unit_id"], "handle": row["handle"], "span_bytes": [bs,be], "passage_refs": ids})
        for i, part in enumerate(slices):
            a, b = cs+part["start"], cs+part["end"]
            value = mapping.text[a:b]
            byte_span = [mapping.char_to_byte(a),mapping.char_to_byte(b)]
            passages.append({"passage_id": ids[i], "chunk_id": ids[i], "case_id": case_id,
                             "source_hash": source_hash, "parent_unit_ids": [row["unit_id"]],
                             "parent_handle": row["handle"], "parent_span_bytes": [bs,be],
                             "span_bytes": byte_span, "span_chars": [a,b], "text": value,
                             "text_sha256": digest(value.encode("utf-8")), "exact_input_sha256": digest(value.encode("utf-8")),
                             "full_input_tokens": part["token_count"], "overlap_tokens_with_previous": part["overlap_tokens"],
                             "split_order": i, "split_count": len(slices),
                             "previous_sibling_ref": ids[i-1] if i else None,
                             "next_sibling_ref": ids[i+1] if i+1 < len(ids) else None,
                             "boundary_method": part["boundary_method"], "word_boundary_split": part["word_boundary_split"],
                             "section_refs": row["section_refs"], "paragraph_role": row["paragraph_role"],
                             "observed_marker": row["observed_marker"], "unit_kind": row["unit_kind"],
                             "language_region": row["language_region"], "uncertainties": row["uncertainties"],
                             "role_evidence_refs": row["role_evidence_refs"],
                             "reading_expansion": row["reading_expansion"], "policy_hash": policy_hash,
                             "tokenizer_fingerprint": tokenizer.fingerprint,
                             "embedding_view": {"template": "{body}", "prefix": "", "add_special_tokens": True,
                                                "truncation": False, "runtime_compatibility": "pending_endpoint_preflight"}})
    return {"schema_version": "pipeline-v2-m2-passages-case-1", "case_id": case_id, "source_hash": digest(raw),
            "policy_hash": policy_hash, "tokenizer_fingerprint": tokenizer.fingerprint,
            "navigation_sha256": digest(canonical(navigation)), "parents": parents, "passages": passages,
            "scope": "all_navigation_units_no_role_or_language_filter",
            "excluded_structural_views": "heading_and_whitespace_remain_source_addressable_not_standalone_embeddings"}
