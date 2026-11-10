"""Write-once M1 bundles and source-backed reading; no evaluator input."""
from collections import Counter
import json
from pathlib import Path
import re

from .core import M1Error, Utf8Map, canonical, digest, parse_source, validate_marker_coverage

PROFILE_PATH = "pipeline_v2/configs/m1.json"
CORPUS_PATH = "data/task1_train_files_2026/cases"


def read_json(path):
    try:
        return json.loads(Path(path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M1Error(f"Cannot read JSON {path}: {exc}") from exc


def contained(root, path, boundary):
    path = Path(path)
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to((root / boundary).resolve()):
        raise M1Error(f"Path outside allowed scope {boundary}")
    return resolved


def load_profile(root):
    path = contained(root, PROFILE_PATH, "pipeline_v2")
    profile = read_json(path)
    if profile.get("schema_version") != "pipeline-v2-m1-profile-2" or profile.get("decode") != "utf-8-strict":
        raise M1Error("Unsupported M1 profile")
    if profile.get("semantic_speaker_or_holding") is not False:
        raise M1Error("M1 cannot infer legal speaker or holdings")
    return profile, digest(path.read_bytes())


def implementation(root):
    names = ["pipeline_v2/m1.py"] + [f"pipeline_v2/source/{name}" for name in ("__init__.py", "core.py", "store.py")]
    # Fingerprint the actual executing implementation, including synthetic repo
    # tests that supply corpus/config in a separate temporary directory.
    actual_root = Path(__file__).resolve().parents[2]
    return {name: digest((actual_root / name).read_bytes()) for name in names}


def m0_inputs(root, bundle):
    bundle = contained(root, bundle, "pipeline_v2/artifacts")
    seal = read_json(bundle / "seal.json")
    if seal.get("schema_version") != "pipeline-v2-m0-seal-1":
        raise M1Error("Expected sealed M0 bundle")
    values = {}
    for name in ("inventory.json", "candidate_manifest.json"):
        path = bundle / name
        raw = path.read_bytes()
        if path.is_symlink() or seal["files"].get(name) != {"sha256": digest(raw), "byte_length": len(raw)}:
            raise M1Error(f"M0 integrity failure: {name}")
        values[name] = read_json(path)
    inventory = values["inventory.json"]
    candidate = values["candidate_manifest.json"]
    rows = inventory["sources"]
    ids = [row["case_id"] for row in rows]
    if (inventory.get("split") != "train" or candidate.get("split") != "train" or
            candidate["candidate_ids"] != ids or len(set(ids)) != len(ids)):
        raise M1Error("M0 source/candidate universe mismatch")
    if candidate.get("source_manifest_sha256") != digest((bundle / "inventory.json").read_bytes()):
        raise M1Error("M0 candidate source fingerprint mismatch")
    for row in rows:
        if not re.fullmatch(r"\d{6}\.txt", row["case_id"]) or row["path"] != f"{CORPUS_PATH}/{row['case_id']}":
            raise M1Error("M0 inventory contains non-train source path")
    return bundle, rows, {"bundle": bundle.relative_to(root).as_posix(),
                          "inventory_sha256": digest((bundle / "inventory.json").read_bytes()),
                          "candidate_manifest_sha256": digest((bundle / "candidate_manifest.json").read_bytes())}


def source_bytes(root, row):
    path = contained(root, row["path"], CORPUS_PATH)
    if path.is_symlink():
        raise M1Error("Source symlink is not allowed")
    raw = path.read_bytes()
    if digest(raw) != row["sha256"] or len(raw) != row["byte_length"]:
        raise M1Error(f"Source drift: {row['case_id']}")
    return raw


def bundle_path(root, output):
    path = contained(root, output, "pipeline_v2/artifacts")
    if path == (root / "pipeline_v2/artifacts").resolve():
        raise M1Error("Choose a child bundle directory")
    return path


def write_file(target, name, value, files):
    raw = canonical(value)
    path = target / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    files[name] = {"sha256": digest(raw), "byte_length": len(raw)}


def expected_manifest(root, profile, profile_sha, provenance):
    return {"schema_version": "pipeline-v2-m1-manifest-2", "m0": provenance,
            "profile_path": PROFILE_PATH, "profile_sha256": profile_sha,
            "profile": profile, "implementation": implementation(root),
            "raw_copy": False, "labels_accessed": False, "test_sources_accessed": False,
            "usage": {"model_requests": 0, "model_retries": 0, "model_tokens": 0,
                      "model_latency_seconds": None, "development_chat_tokens": None}}


def summary_record(rows, counts, uncertainty, fixtures):
    return {"schema_version": "pipeline-v2-m1-summary-2", "source_count": len(rows),
            "total_bytes": sum(row["byte_length"] for row in rows), "unit_counts": dict(counts),
            "uncertainty_counts": dict(uncertainty), "fixture_checks": fixtures,
            "integrity": "ready", "structure": "observed_conservative_with_unknowns_not_corpus_accuracy_verified",
            "m2_executed": False, "dense_and_runtime": "not_ready"}


def fixture_checks(root, rows, profile):
    """Exposed diagnostic examples run before corpus build. No holdout tuning."""
    known = {row["case_id"]: row for row in rows}
    result = {"scope": "exposed_diagnostic_only", "checks": {}, "absent": []}
    for ident in profile.get("fixtures", []):
        if ident not in known:
            result["absent"].append(ident)
            continue
        record = parse_source(ident, source_bytes(root, known[ident]), profile)
        paragraphs = [u for u in record["units"] if u["unit_kind"] == "paragraph"]
        raw = source_bytes(root, known[ident])
        validate_marker_coverage(record, raw)
        if ident == "061295.txt":
            lookup = {u["unit_id"]: u for u in paragraphs}
            observed = {(lookup[s["attribution_unit_id"]]["observed_marker"], lookup[s["quoted_unit_id"]]["observed_marker"]) for s in record["sidecars"] if s["attribution_unit_id"]}
            ok = (12,9) in observed and (13,17) in observed and (14,10) in observed
        elif ident == "067620.txt":
            ones = [u for u in paragraphs if u["observed_marker"] == 1]
            ok = len(ones) >= 2 and len({u["language_region"] for u in ones}) >= 2
        elif ident == "062436.txt":
            ok = any(u["unit_kind"] == "heading" and raw[slice(*u["span_bytes"])].decode("utf-8").strip() == "The Respondent" for u in record["units"])
        elif ident == "000758.txt":
            ok = all(any(u["observed_marker"] == n for u in paragraphs) for n in (35,37,38,75))
        elif ident == "050936.txt":
            ok = any(u["observed_marker"] == 1 and u["paragraph_role"] == "quoted" for u in paragraphs) and all(any(u["observed_marker"] == n for u in paragraphs) for n in (30,31,54))
        else:
            ok = bool(paragraphs)
        result["checks"][ident] = "pass" if ok else "fail"
        if not ok:
            raise M1Error(f"Exposed structure fixture failed: {ident}")
    return result


def build_bundle(repo_root, m0_bundle, output):
    root = Path(repo_root).resolve()
    target = bundle_path(root, output)
    if target.exists():
        raise M1Error("Write-once output already exists")
    profile, profile_sha = load_profile(root)
    _, rows, provenance = m0_inputs(root, m0_bundle)
    corpus = contained(root, CORPUS_PATH, CORPUS_PATH)
    if sorted(p.name for p in corpus.iterdir()) != sorted(r["case_id"] for r in rows):
        raise M1Error("Corpus directory differs from frozen M0 inventory")
    fixtures = fixture_checks(root, rows, profile)
    target.mkdir(parents=True, exist_ok=False)
    files = {}
    registry = []
    counts = Counter({"role_current_case": 0, "role_quoted": 0, "role_unknown": 0})
    uncertainty = Counter()
    for row in rows:
        record = parse_source(row["case_id"], source_bytes(root, row), profile)
        name = f"sources/{row['case_id'][:-4]}.json"
        write_file(target, name, record, files)
        registry.append({"case_id": row["case_id"], "path": row["path"], "raw_sha256": row["sha256"],
                         "byte_length": row["byte_length"], "encoding": "utf-8",
                         "structure_ref": name, "structure_sha256": files[name]["sha256"],
                         "char_byte_map_ref": f"{name}#/char_byte_map", "corpus_manifest_id": provenance["inventory_sha256"]})
        counts.update(u["unit_kind"] for u in record["units"])
        counts.update("role_" + u["paragraph_role"] for u in record["units"] if u["unit_kind"] == "paragraph")
        counts["sidecars"] += len(record["sidecars"])
        for unit in record["units"]:
            uncertainty.update(unit["uncertainties"])
    summary = summary_record(rows, counts, uncertainty, fixtures)
    write_file(target, "source_registry.json", {"schema_version": "pipeline-v2-source-registry-2", "sources": registry}, files)
    write_file(target, "manifest.json", expected_manifest(root, profile, profile_sha, provenance), files)
    write_file(target, "summary.json", summary, files)
    with (target / "seal.json").open("xb") as stream:
        stream.write(canonical({"schema_version": "pipeline-v2-m1-seal-2", "files": files}))
    return {"bundle": str(target), "summary": summary}


class SourceReader:
    def __init__(self, repo_root, bundle):
        self.root = Path(repo_root).resolve()
        self.bundle = bundle_path(self.root, bundle)
        self.seal = read_json(self.bundle / "seal.json")
        if self.seal.get("schema_version") != "pipeline-v2-m1-seal-2":
            raise M1Error("Expected sealed M1 bundle")
        self.manifest = self._artifact("manifest.json")
        profile, profile_sha = load_profile(self.root)
        _, frozen_rows, provenance = m0_inputs(self.root, self.manifest["m0"]["bundle"])
        if self.manifest != expected_manifest(self.root, profile, profile_sha, provenance):
            raise M1Error("M1 code/config/M0 provenance drift")
        self.frozen_rows = {row["case_id"]: row for row in frozen_rows}
        registry = self._artifact("source_registry.json")
        self.rows = {row["case_id"]: row for row in registry["sources"]}
        if len(self.rows) != len(registry["sources"]):
            raise M1Error("Duplicate source registry IDs")
        if set(self.rows) != set(self.frozen_rows):
            raise M1Error("Registry differs from frozen M0 source universe")

    def _artifact(self, name):
        if name not in self.seal.get("files", {}) or Path(name).is_absolute() or ".." in Path(name).parts:
            raise M1Error("Unknown/unsafe artifact reference")
        path = self.bundle / name
        if path.is_symlink() or not path.resolve().is_relative_to(self.bundle):
            raise M1Error("Artifact path escapes sealed bundle")
        raw = path.read_bytes()
        if self.seal["files"][name] != {"sha256": digest(raw), "byte_length": len(raw)}:
            raise M1Error(f"Artifact integrity failure: {name}")
        return read_json(path)

    def _source(self, ident):
        if ident not in self.rows:
            raise M1Error("Case not in source registry")
        row = self.rows[ident]
        frozen = self.frozen_rows[ident]
        if (row["path"] != frozen["path"] or row["raw_sha256"] != frozen["sha256"] or
                row["byte_length"] != frozen["byte_length"] or
                row["structure_ref"] != f"sources/{ident[:-4]}.json" or
                row["corpus_manifest_id"] != self.manifest["m0"]["inventory_sha256"]):
            raise M1Error("Source registry differs from frozen M0 source")
        raw = source_bytes(self.root, frozen)
        record = self._artifact(row["structure_ref"])
        if self.seal["files"][row["structure_ref"]]["sha256"] != row["structure_sha256"]:
            raise M1Error("Registry/structure fingerprint mismatch")
        if record["raw_sha256"] != row["raw_sha256"] or record["case_id"] != ident:
            raise M1Error("Structure/source mismatch")
        validate_marker_coverage(record, raw)
        if record != parse_source(ident, raw, self.manifest["profile"]):
            raise M1Error("Structure/map/metadata differs from source and parser")
        expected_row = {"case_id": ident, "path": frozen["path"], "raw_sha256": frozen["sha256"],
                        "byte_length": frozen["byte_length"], "encoding": "utf-8",
                        "structure_ref": f"sources/{ident[:-4]}.json", "structure_sha256": digest(canonical(record)),
                        "char_byte_map_ref": f"sources/{ident[:-4]}.json#/char_byte_map",
                        "corpus_manifest_id": self.manifest["m0"]["inventory_sha256"]}
        if row != expected_row:
            raise M1Error("Source registry fields differ from expected source record")
        return raw, record

    def open_range(self, case_id, start, end):
        raw, record = self._source(case_id)
        mapping = Utf8Map(raw)
        a,b = mapping.byte_to_char(start), mapping.byte_to_char(end)
        if start > end:
            raise M1Error("Reversed source range")
        return {"case_id": case_id, "raw_sha256": record["raw_sha256"], "span_bytes": [start,end],
                "span_chars": [a,b], "text": raw[start:end].decode("utf-8"),
                "unit_ids": [u["unit_id"] for u in record["units"] if u["span_bytes"][0] < end and u["span_bytes"][1] > start],
                "unit_metadata": [u for u in record["units"] if u["span_bytes"][0] < end and u["span_bytes"][1] > start]}

    def open_unit(self, case_id, unit_id, before=0, after=0):
        if type(before) is not int or type(after) is not int or before < 0 or after < 0:
            raise M1Error("Neighbor counts must be nonnegative integers")
        _, record = self._source(case_id)
        units = record["units"]
        index = next((i for i,u in enumerate(units) if u["unit_id"] == unit_id), None)
        if index is None:
            raise M1Error("Unknown unit ID")
        chosen = units[max(0,index-before):min(len(units),index+after+1)]
        result = self.open_range(case_id, chosen[0]["span_bytes"][0], chosen[-1]["span_bytes"][1])
        result["requested_unit_id"] = unit_id
        return result


def validate_bundle(repo_root, bundle):
    root = Path(repo_root).resolve()
    reader = SourceReader(root, bundle)
    target = reader.bundle
    actual = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()}
    if actual != set(reader.seal["files"]) | {"seal.json"}:
        raise M1Error("Unexpected/missing bundle files")
    for name in reader.seal["files"]:
        reader._artifact(name)
    profile, profile_sha = load_profile(root)
    _, rows, provenance = m0_inputs(root, reader.manifest["m0"]["bundle"])
    if reader.manifest != expected_manifest(root, profile, profile_sha, provenance):
        raise M1Error("M1 code/config/M0 provenance drift")
    if set(reader.rows) != {r["case_id"] for r in rows}:
        raise M1Error("Registry universe drift")
    corpus = contained(root, CORPUS_PATH, CORPUS_PATH)
    if sorted(p.name for p in corpus.iterdir()) != sorted(r["case_id"] for r in rows):
        raise M1Error("Corpus directory differs from frozen M0 inventory")
    counts = Counter({"role_current_case": 0, "role_quoted": 0, "role_unknown": 0})
    uncertainty = Counter()
    for row in rows:
        raw, saved = reader._source(row["case_id"])
        counts.update(u["unit_kind"] for u in saved["units"])
        counts.update("role_" + u["paragraph_role"] for u in saved["units"] if u["unit_kind"] == "paragraph")
        counts["sidecars"] += len(saved["sidecars"])
        for unit in saved["units"]:
            uncertainty.update(unit["uncertainties"])
    summary = reader._artifact("summary.json")
    if summary != summary_record(rows, counts, uncertainty, fixture_checks(root, rows, profile)):
        raise M1Error("Summary counts drift")
    return {"valid": True, "source_count": len(rows), "integrity": "ready", "structure": summary["structure"]}
