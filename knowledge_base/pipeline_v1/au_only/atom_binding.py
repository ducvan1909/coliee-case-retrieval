"""Fail-closed explicit binding to one immutable Plan04 atom map; never glob."""
import hashlib,json
from pathlib import Path
class AtomBindingError(ValueError): pass
def resolve(binding):
 p=Path(binding["atom_map_path"])
 if not p.is_file(): raise AtomBindingError("atom map missing")
 raw=p.read_bytes();sha=hashlib.sha256(raw).hexdigest()
 if sha!=binding["atom_map_sha256"]: raise AtomBindingError("atom map sha mismatch")
 value=json.loads(raw)
 if value.get("case_id")!=binding["case_id"] or value.get("source_hash")!=binding["source_hash"]: raise AtomBindingError("case/source mismatch")
 if value.get("segmenter_version")!=binding["segmenter_version"] or value.get("policy_sha256")!=binding["policy_sha256"]: raise AtomBindingError("segmenter/policy mismatch")
 return value
