"""Offline semantic review packet: exact evidence and region, no inferred verdict."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ..source_contract import open_source
from .core import build_evidence_catalog
from .manifest import _binding_path, write_json


REVIEW_CHECKS = [
    "authority_qualification: legal proposition/holding versus fact, history or party assertion",
    "target_ownership: TARGET contributes to this legal proposition, not merely an unrelated ID",
    "claim_support: selected evidence supports every material claim clause",
    "attribution: speaker/reporting voice and court endorsement are distinguished",
    "qualification: conditions, exceptions and limits remain within claim/evidence",
    "coverage: compare against entire supplied region for missed TARGET authority",
    "duplicate: separate legal propositions rather than paraphrases of the same AU",
]


def build_packet(report, source_store, atom_root):
    rows = []
    for row in report.get("request_ledger", []):
        request = row["request"]
        source = open_source(source_store, request["case_id"], request["source_hash"])
        catalog = build_evidence_catalog(request, _binding_path(request["atom_binding"], atom_root), source)
        atoms = catalog["atoms"]
        proposals = []
        compact = row.get("compact_response")
        for index, au in enumerate(compact.get("aus", []) if isinstance(compact, dict) else []):
            if not isinstance(au, dict):
                proposals.append({"au_index": index, "proposal": au, "review_status": "pending", "invalid_shape": True})
                continue
            refs = au.get("evidence_ref_ids", [])
            evidence = [atoms[aid] for aid in refs if isinstance(aid, str) and aid in atoms] if isinstance(refs, list) else []
            proposals.append({"au_index": index, "proposal": au, "selected_evidence": evidence,
                              "unknown_evidence_ids": [aid for aid in refs if not isinstance(aid, str) or aid not in atoms] if isinstance(refs, list) else [],
                              "review_status": "pending", "semantic_verdict": None})
        rows.append({"case_id": request["case_id"], "source_hash": request["source_hash"],
                     "request_id": request["request_id"], "target_ids": request["expected_target_ids"],
                     "source_refs": request["source_refs"], "protocol_status": row["status"],
                     "model_decision": compact.get("decision") if isinstance(compact, dict) else None,
                     "region_atoms": sorted(atoms.values(), key=lambda a: (a["start_char"], a["end_char"])),
                     "proposals": proposals, "target_omission_review": "pending"})
    return {"artifact_type": "AUCompactSemanticReviewPacket", "schema_version": "au-semantic-review-packet-v1",
            "semantic_gold": False, "semantic_quality_claim": False, "review_status": "pending",
            "review_checks": REVIEW_CHECKS, "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--source-store", default="knowledge_base/pipeline_v1/outputs/source_store_v1")
    parser.add_argument("--atom-root", default="knowledge_base/pipeline_v1/outputs/plan04_sentence_atoms_v1")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = Path(args.run).read_bytes()
    packet = build_packet(json.loads(raw.decode("utf-8")), args.source_store, args.atom_root)
    packet["run_sha256"] = hashlib.sha256(raw).hexdigest()
    write_json(args.output, packet)
    print(f"AU-COMPACT REVIEW-PACKET READY — semantic review PENDING — output: {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
