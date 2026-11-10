"""Write-once token passage bundles bound to raw, navigation and tokenizer."""
from collections import Counter
from pathlib import Path

from ..navigation import NavigationReader
from ..navigation.store import bundle_path, write_artifact
from ..source.core import canonical, digest
from ..source.store import contained, read_json
from .core import build_case_passages
from .tokenizer import PassageError, PinnedTokenizer

PROFILE_PATH = "pipeline_v2/configs/m2_passages.json"


def load_profile(root):
    path = contained(root, PROFILE_PATH, "pipeline_v2")
    profile = read_json(path)
    if (profile.get("schema_version") != "pipeline-v2-m2-passages-profile-1" or
        profile.get("document_template") != "{body}" or profile.get("add_special_tokens") is not True or
        profile.get("truncation") is not False or profile.get("merge_parents") is not False or
        profile.get("semantic_inference") is not False):
        raise PassageError("Unsupported token passage profile")
    return profile, digest(path.read_bytes())


def implementation():
    root = Path(__file__).resolve().parents[2]
    names = ["pipeline_v2/m2_passages.py"] + ["pipeline_v2/passages/"+x for x in ("__init__.py","core.py","store.py","tokenizer.py")]
    return {name:digest((root/name).read_bytes()) for name in names}


def expected_manifest(root, nav, profile, profile_sha, tokenizer):
    return {"schema_version":"pipeline-v2-m2-passages-manifest-1",
            "navigation":{"bundle":nav.bundle.relative_to(root).as_posix(),
                          "seal_sha256":digest((nav.bundle/"seal.json").read_bytes()),
                          "manifest_sha256":digest((nav.bundle/"manifest.json").read_bytes()),
                          "registry_sha256":digest((nav.bundle/"source_registry.json").read_bytes())},
            "m1":nav.manifest["m1"],"m0":nav.source.manifest["m0"],
            "profile_path":PROFILE_PATH,"profile_sha256":profile_sha,"profile":profile,
            "tokenizer_lock_sha256":tokenizer.lock_sha256,"tokenizer_fingerprint":tokenizer.fingerprint,
            "implementation":implementation(),"labels_accessed":False,"test_sources_accessed":False,
            "usage":{"model_requests":0,"model_retries":0,"model_tokens":0,"development_chat_tokens":None},
            "dense_runtime":"not_ready","M3_or_later_executed":False}


def count_case(counts, record):
    counts["sources"] += 1
    counts["parent_units"] += len(record["parents"])
    counts["passages"] += len(record["passages"])
    counts["split_parents"] += sum(len(p["passage_refs"])>1 for p in record["parents"])
    for p in record["passages"]:
        counts["full_input_tokens"] += p["full_input_tokens"]
        counts["max_full_input_tokens"] = max(counts["max_full_input_tokens"],p["full_input_tokens"])
        counts["overlap_tokens"] += p["overlap_tokens_with_previous"]
        counts["word_boundary_splits"] += p["word_boundary_split"]
        counts["role_"+str(p["paragraph_role"])] += 1
        counts["kind_"+p["unit_kind"]] += 1
        counts["token_bin_"+str((p["full_input_tokens"]//64)*64)] += 1


def summary(counts):
    return {"schema_version":"pipeline-v2-m2-passages-summary-1","counts":dict(counts),
            "readiness":{"local_token_counts":"ready","token_validated_passages":"ready",
                         "parent_context_mapping":"ready","embedding_runtime":"not_ready","indexes":"not_ready"},
            "limitations":["provisional_overlapping_profile_not_quality_optimized","ownership_language_not_semantically_verified",
                           "whitespace_boundaries_not_sentence_verified","endpoint_rendering_preflight_required",
                           "M4_payload_budget_and_delivery_not_implemented"]}


def registry_row(case_id, record):
    return {"case_id":case_id,"source_hash":record["source_hash"],"passages_ref":f"sources/{case_id[:-4]}.json",
            "passages_sha256":digest(canonical(record)),"passage_count":len(record["passages"]),"parent_count":len(record["parents"])}


def build_bundle(repo_root, navigation_bundle, output):
    root = Path(repo_root).resolve()
    target = bundle_path(root, output)
    if target.exists():
        raise PassageError("Write-once output exists; choose a new directory")
    profile, sha = load_profile(root)
    tokenizer = PinnedTokenizer(root,profile["tokenizer_lock"])
    nav = NavigationReader(root,navigation_bundle)
    manifest = expected_manifest(root,nav,profile,sha,tokenizer)
    target.mkdir(parents=True,exist_ok=False)
    files, rows, counts = {}, [], Counter()
    for case_id in sorted(nav.rows):
        raw, record = nav._case(case_id)
        result = build_case_passages(case_id,raw,record,profile,tokenizer)
        write_artifact(target,f"sources/{case_id[:-4]}.json",result,files)
        rows.append(registry_row(case_id,result))
        count_case(counts,result)
    tokenizer.verify()
    fresh_nav = NavigationReader(root,navigation_bundle)
    if manifest != expected_manifest(root,fresh_nav,*load_profile(root),tokenizer):
        raise PassageError("Inputs changed during build")
    write_artifact(target,"source_registry.json",{"schema_version":"pipeline-v2-m2-passages-registry-1","sources":rows},files)
    write_artifact(target,"manifest.json",manifest,files)
    write_artifact(target,"summary.json",summary(counts),files)
    with (target/"seal.json").open("xb") as stream:
        stream.write(canonical({"schema_version":"pipeline-v2-m2-passages-seal-1","files":files}))
    return {"bundle":str(target),"summary":summary(counts)}


class PassageReader:
    def __init__(self,repo_root,bundle):
        self.root = Path(repo_root).resolve()
        self.bundle = bundle_path(self.root,bundle)
        self.seal = read_json(self.bundle/"seal.json")
        if self.seal.get("schema_version") != "pipeline-v2-m2-passages-seal-1":
            raise PassageError("Expected sealed token passage bundle")
        self.manifest = self._artifact("manifest.json")
        self.profile, sha = load_profile(self.root)
        self.tokenizer = PinnedTokenizer(self.root,self.profile["tokenizer_lock"])
        self.nav = NavigationReader(self.root,self.manifest["navigation"]["bundle"])
        if self.manifest != expected_manifest(self.root,self.nav,self.profile,sha,self.tokenizer):
            raise PassageError("Passage profile/code/navigation/tokenizer provenance drift")
        registry = self._artifact("source_registry.json")
        self.rows = {r["case_id"]:r for r in registry["sources"]}
        if len(self.rows)!=len(registry["sources"]) or set(self.rows)!=set(self.nav.rows):
            raise PassageError("Passage source universe differs from navigation")

    def _artifact(self,name):
        if name not in self.seal.get("files",{}) or Path(name).is_absolute() or ".." in Path(name).parts:
            raise PassageError("Unknown/unsafe passage artifact")
        path = self.bundle/name
        if path.is_symlink() or not path.resolve().is_relative_to(self.bundle):
            raise PassageError("Passage artifact escapes bundle")
        raw = path.read_bytes()
        if self.seal["files"][name] != {"sha256":digest(raw),"byte_length":len(raw)}:
            raise PassageError("Passage seal integrity failure")
        return read_json(path)

    def _case(self,case_id,verify_tokenizer=True):
        if case_id not in self.rows:
            raise PassageError("Case not in passage registry")
        if verify_tokenizer:
            self.tokenizer.verify()
            # Reconstruct upstream readers so their current profile/code/M0/M1
            # checks run again rather than trusting a cached in-memory chain.
            self.nav = NavigationReader(self.root,self.manifest["navigation"]["bundle"])
        profile, sha = load_profile(self.root)
        if self.manifest != expected_manifest(self.root,self.nav,profile,sha,self.tokenizer):
            raise PassageError("Passage inputs drifted after reader construction")
        raw, nav_record = self.nav._case(case_id)
        result = self._artifact(f"sources/{case_id[:-4]}.json")
        if result != build_case_passages(case_id,raw,nav_record,profile,self.tokenizer):
            raise PassageError("Passage differs from exact source/tokenizer/profile")
        if self.rows[case_id] != registry_row(case_id,result):
            raise PassageError("Passage registry mismatch")
        return raw,result

    def inspect(self,case_id,offset=0,limit=20):
        if type(offset) is not int or type(limit) is not int or offset<0 or not 1<=limit<=self.profile["pagination_max_limit"]:
            raise PassageError("Invalid passage pagination bounds")
        _, record = self._case(case_id)
        items = record["passages"][offset:offset+limit]
        return {"case_id":case_id,"source_hash":record["source_hash"],"offset":offset,"limit":limit,
                "total":len(record["passages"]),"next_offset":offset+len(items) if offset+len(items)<len(record["passages"]) else None,"items":items}

    def open_context(self,case_id,passage_id):
        _, record = self._case(case_id)
        hit = next((p for p in record["passages"] if p["passage_id"]==passage_id),None)
        if hit is None:
            raise PassageError("Unknown passage ID")
        opened = self.nav.open_context(case_id,hit["parent_handle"])
        return {**opened,"hit_passage_id":passage_id,"hit_span_bytes":hit["span_bytes"],
                "hit_text":hit["text"],"hit_is_distinct_from_context":True}


def validate_bundle(repo_root,bundle):
    reader = PassageReader(repo_root,bundle)
    actual = {p.relative_to(reader.bundle).as_posix() for p in reader.bundle.rglob("*") if p.is_file()}
    if actual != set(reader.seal["files"])|{"seal.json"}:
        raise PassageError("Unexpected/missing passage bundle files")
    for name in reader.seal["files"]:
        reader._artifact(name)
    counts = Counter()
    for case_id in sorted(reader.rows):
        # Tokenizer assets are verified once at both ends of this local batch;
        # interactive reads verify on each call, with no long-lived trust cache.
        _, record = reader._case(case_id,verify_tokenizer=False)
        count_case(counts,record)
    reader.tokenizer.verify()
    fresh_nav = NavigationReader(reader.root,reader.manifest["navigation"]["bundle"])
    if reader.manifest != expected_manifest(reader.root,fresh_nav,*load_profile(reader.root),reader.tokenizer):
        raise PassageError("Upstream inputs changed during validation")
    if reader._artifact("summary.json") != summary(counts):
        raise PassageError("Passage summary mismatch")
    return {"valid":True,"bundle":str(reader.bundle),"summary":summary(counts)}
