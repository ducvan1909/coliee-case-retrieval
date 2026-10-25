"""On-demand mock renderer; source text is never persisted in region artifacts."""
from __future__ import annotations
import hashlib, math
from typing import Any


class RegionRenderError(ValueError):
    def __init__(self, detail: str, *, code="render_contract", location="<root>"):
        self.code, self.location, self.detail = code, location, detail
        super().__init__(f"[{code}] {location}: {detail}")


def render_region(text: str, region: dict[str, Any]) -> str:
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != region["source_hash"]:
        raise RegionRenderError("source hash mismatch", code="source_hash_mismatch", location="source_hash")
    pieces=[f"<REGION arm={region['arm']} case={region['case_id']} region={region['region_id']}>\n"]
    actual=[]
    for item in region["render_items"]:
        ref=item["span"]
        if ref["case_id"]!=region["case_id"] or ref["source_hash"]!=region["source_hash"] or not (0<=ref["start_char"]<=ref["end_char"]<=len(text)):
            raise RegionRenderError("invalid render span",code="offset_violation",location=item["render_key"])
        if item["role"]=="target":
            label=f"<TARGET refs={','.join(item['ref_ids'])} span={ref['start_char']}:{ref['end_char']}>\n"; close="\n</TARGET>\n"
        else:
            label=f"<CONTEXT reasons={','.join(item['reasons'])} span={ref['start_char']}:{ref['end_char']}>\n"; close="\n</CONTEXT>\n"
        pieces.extend((label,text[ref["start_char"]:ref["end_char"]],close)); actual.append(item["render_key"])
    pieces.append("</REGION>\n")
    if actual!=region["render_order"]: raise RegionRenderError("render order mismatch",code="render_order_mismatch",location="render_order")
    return "".join(pieces)

def render_base_region(text: str, region: dict[str, Any]) -> str:
    clone={**region,"arm":"base","region_id":"base"}
    return render_region(text,clone)


def render_metrics(text: str, region: dict[str, Any], chars_per_token: int) -> dict[str, int]:
    rendered=render_region(text,region)
    return {"rendered_chars":len(rendered),"estimated_input_tokens":math.ceil(len(rendered)/chars_per_token)}
