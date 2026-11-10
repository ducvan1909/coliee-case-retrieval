"""Source-bound write-once navigation bundles; runtime delivery belongs to M4."""
from collections import Counter
from pathlib import Path

from ..source import SourceReader
from ..source.core import canonical, digest
from ..source.store import read_json, contained
from .core import M2Error, build_case_navigation, validate_case

PROFILE_PATH = "pipeline_v2/configs/m2.json"


def load_profile(root):
    path = contained(root,PROFILE_PATH,"pipeline_v2")
    profile = read_json(path)
    if profile.get("schema_version") != "pipeline-v2-m2-profile-2" or profile.get("semantic_inference") is not False:
        raise M2Error("Unsupported navigation-only M2 profile")
    for name in ("embedding","agent_tokenizer"):
        if profile[name] != {"status":"not_ready","model":None,"tokenizer":None}:
            raise M2Error("Token runtime not pinned for this navigation-only M2 stage")
    if profile["token_validated_chunks"]["status"] != "not_ready":
        raise M2Error("Cannot mark token-validated chunks ready")
    return profile,digest(path.read_bytes())


def implementation():
    root = Path(__file__).resolve().parents[2]
    names = ["pipeline_v2/m2.py"] + [f"pipeline_v2/navigation/{x}" for x in ("__init__.py","core.py","store.py")]
    return {name:digest((root/name).read_bytes()) for name in names}


def bundle_path(root,path):
    target = contained(root,path,"pipeline_v2/artifacts")
    if target == (root/"pipeline_v2/artifacts").resolve():
        raise M2Error("Choose a child artifact directory")
    return target


def m1_provenance(root,reader):
    return {"bundle":reader.bundle.relative_to(root).as_posix(),
            "seal_sha256":digest((reader.bundle/"seal.json").read_bytes()),
            "manifest_sha256":digest((reader.bundle/"manifest.json").read_bytes()),
            "registry_sha256":digest((reader.bundle/"source_registry.json").read_bytes())}


def manifest(profile,profile_sha,provenance):
    return {"schema_version":"pipeline-v2-m2-navigation-manifest-1","m1":provenance,
            "profile_path":PROFILE_PATH,"profile_sha256":profile_sha,"profile":profile,
            "implementation":implementation(),"scope":"navigation_preview_anchor_parent_mapping_only",
            "labels_accessed":False,"test_sources_accessed":False,"raw_corpus_copied":False,
            "usage":{"model_requests":0,"model_retries":0,"model_tokens":0,"model_latency_seconds":None,"development_chat_tokens":None}}


def summary(counts):
    return {"schema_version":"pipeline-v2-m2-navigation-summary-1","counts":dict(counts),
            "readiness":{"navigation":"ready","preview_provenance":"ready","parent_context_mapping":"ready",
                         "token_validated_chunks":"not_ready","token_counts":"not_ready","agent_payload_budget":"not_ready","dense":"not_ready"},
            "limitations":["ownership_and_anchor_semantics_not_certified","preview_boundaries_are_display_heuristics",
                           "embedding_and_agent_tokenizers_unselected","M3_search_and_M4_delivery_not_implemented"],
            "chunk_manifest_generated":False,"M3_or_later_executed":False}


def count_case(counts,record):
    counts["sources"] += 1
    counts["navigation_units"] += len(record["navigation"])
    counts["previews"] += len(record["previews"])
    counts["anchors"] += len(record["anchors"])
    counts["source_quote_cues"] += len(record["source_anchors"])
    counts["headings"] += len(record["headings"])
    counts["units_without_preview"] += sum(not r["preview_refs"] for r in record["navigation"])
    counts["unknown_paragraphs"] += sum(r["paragraph_role"] == "unknown" for r in record["navigation"])
    counts.update("kind_"+r["unit_kind"] for r in record["navigation"])
    counts.update("anchor_"+a["anchor_kind"] for a in record["anchors"])


def write_artifact(target,name,value,files):
    raw = canonical(value)
    path = target/name
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    files[name] = {"sha256":digest(raw),"byte_length":len(raw)}


def registry_row(ident,record,artifact_sha):
    return {"case_id":ident,"source_hash":record["source_hash"],"navigation_ref":f"sources/{ident[:-4]}.json",
            "navigation_sha256":artifact_sha,"navigation_units":len(record["navigation"])}


def build_bundle(repo_root,m1_bundle,output):
    root = Path(repo_root).resolve()
    target = bundle_path(root,output)
    if target.exists():
        raise M2Error("Write-once output exists; choose a new directory")
    profile,profile_sha = load_profile(root)
    source = SourceReader(root,m1_bundle)
    provenance = m1_provenance(root,source)
    target.mkdir(parents=True,exist_ok=False)
    files,rows,counts = {},[],Counter()
    for ident in sorted(source.rows):
        raw,m1_record = source._source(ident)
        record = build_case_navigation(ident,raw,m1_record,profile)
        name = f"sources/{ident[:-4]}.json"
        write_artifact(target,name,record,files)
        rows.append(registry_row(ident,record,files[name]["sha256"]))
        count_case(counts,record)
    write_artifact(target,"source_registry.json",{"schema_version":"pipeline-v2-m2-navigation-registry-1","sources":rows},files)
    write_artifact(target,"manifest.json",manifest(profile,profile_sha,provenance),files)
    result_summary = summary(counts)
    write_artifact(target,"summary.json",result_summary,files)
    with (target/"seal.json").open("xb") as stream:
        stream.write(canonical({"schema_version":"pipeline-v2-m2-navigation-seal-1","files":files}))
    return {"bundle":str(target),"summary":result_summary}


class NavigationReader:
    def __init__(self,repo_root,bundle):
        self.root = Path(repo_root).resolve()
        self.bundle = bundle_path(self.root,bundle)
        self.seal = read_json(self.bundle/"seal.json")
        if self.seal.get("schema_version") != "pipeline-v2-m2-navigation-seal-1":
            raise M2Error("Expected sealed M2 navigation bundle")
        self.manifest = self._artifact("manifest.json")
        self.profile,profile_sha = load_profile(self.root)
        self.source = SourceReader(self.root,self.manifest["m1"]["bundle"])
        if self.manifest != manifest(self.profile,profile_sha,m1_provenance(self.root,self.source)):
            raise M2Error("M2 profile/code/M1 provenance drift")
        registry = self._artifact("source_registry.json")
        self.rows = {r["case_id"]:r for r in registry["sources"]}
        if len(self.rows) != len(registry["sources"]) or set(self.rows) != set(self.source.rows):
            raise M2Error("M2 source universe differs from pinned M1")

    def _artifact(self,name):
        if name not in self.seal.get("files",{}) or Path(name).is_absolute() or ".." in Path(name).parts:
            raise M2Error("Unknown/unsafe M2 artifact")
        path = self.bundle/name
        if path.is_symlink() or not path.resolve().is_relative_to(self.bundle):
            raise M2Error("M2 artifact escapes bundle")
        raw = path.read_bytes()
        if self.seal["files"][name] != {"sha256":digest(raw),"byte_length":len(raw)}:
            raise M2Error("M2 artifact seal integrity failure")
        return read_json(path)

    def _case(self,case_id):
        if case_id not in self.rows:
            raise M2Error("Case not in M2 registry")
        row = self.rows[case_id]
        name = f"sources/{case_id[:-4]}.json"
        if row["navigation_ref"] != name:
            raise M2Error("Unexpected navigation path")
        raw,m1_record = self.source._source(case_id)
        record = self._artifact(name)
        if record != build_case_navigation(case_id,raw,m1_record,self.profile):
            raise M2Error("Navigation/preview/anchor differs from source and profile")
        if row != registry_row(case_id,record,digest(canonical(record))):
            raise M2Error("M2 registry/source mismatch")
        return raw,record

    def _page(self,values,offset,limit):
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= self.profile["pagination"]["max_limit"]:
            raise M2Error("Invalid pagination bounds")
        page = values[offset:offset+limit]
        return {"offset":offset,"limit":limit,"total":len(values),"next_offset":offset+len(page) if offset+len(page)<len(values) else None,"items":page}

    def map(self,case_id,offset=0,limit=20):
        _,record = self._case(case_id)
        previews = {p["preview_id"]:p for p in record["previews"]}
        headings = {h["unit_id"]:h for h in record["headings"]}
        page = self._page(record["navigation"],offset,limit)
        page["items"] = [{**{k:v for k,v in row.items() if k != "anchor_refs"},"anchor_count":len(row["anchor_refs"]),
                          "previews":[previews[p] for p in row["preview_refs"]],
                          "sections":[headings[h] for h in row["section_refs"]]} for row in page["items"]]
        return {"case_id":case_id,"source_hash":record["source_hash"],"readiness":record["readiness"],**page}

    def anchors(self,case_id,handle,offset=0,limit=20):
        _,record = self._case(case_id)
        row = next((r for r in record["navigation"] if r["handle"] == handle),None)
        if row is None:
            raise M2Error("Unknown navigation handle")
        values = [a for a in record["anchors"] if a["unit_id"] == row["unit_id"]]
        return {"case_id":case_id,"handle":handle,"source_hash":record["source_hash"],**self._page(values,offset,limit)}

    def source_anchors(self,case_id,offset=0,limit=20):
        _,record = self._case(case_id)
        return {"case_id":case_id,"source_hash":record["source_hash"],**self._page(record["source_anchors"],offset,limit)}

    def open_context(self,case_id,handle):
        raw,record = self._case(case_id)
        rows = {r["handle"]:r for r in record["navigation"]}
        if handle not in rows:
            raise M2Error("Unknown navigation handle")
        row = rows[handle]
        expansion = row["reading_expansion"]
        components = []
        for label,key in (("previous_context","previous_ref"),("parent","parent_ref"),("next_context","next_ref")):
            ref = expansion[key]
            if ref is not None:
                chosen = rows[ref]
                components.append({"kind":label,"handle":ref,"unit_id":chosen["unit_id"],"span_bytes":chosen["span_bytes"]})
        start,end = min(c["span_bytes"][0] for c in components),max(c["span_bytes"][1] for c in components)
        return {"case_id":case_id,"source_hash":record["source_hash"],"requested_handle":handle,"components":components,
                "span_bytes":[start,end],"text":raw[start:end].decode("utf-8"),
                "intervening_headings":[h for h in record["headings"] if start <= h["span_bytes"][0] and h["span_bytes"][1] <= end],
                "neighbor_policy":expansion["neighbor_policy"],"diagnostic_only":True,"M4_delivery_recorded":False}


def validate_bundle(repo_root,bundle):
    reader = NavigationReader(repo_root,bundle)
    actual = {p.relative_to(reader.bundle).as_posix() for p in reader.bundle.rglob("*") if p.is_file()}
    if actual != set(reader.seal["files"]) | {"seal.json"}:
        raise M2Error("Unexpected/missing M2 bundle files")
    for name in reader.seal["files"]:
        reader._artifact(name)
    counts = Counter()
    for ident in sorted(reader.rows):
        _,record = reader._case(ident)
        count_case(counts,record)
    if reader._artifact("summary.json") != summary(counts):
        raise M2Error("M2 summary differs from verified records")
    return {"valid":True,"bundle":str(reader.bundle),"summary":summary(counts)}
