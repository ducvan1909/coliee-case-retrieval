"""Read immutable M2 records without rebuilding every passage for each hit."""
from pathlib import Path

from ..passages import PassageReader
from ..source.core import digest
from .common import M3Error


class Corpus:
    def __init__(self, root, bundle, expected_seal_sha256=None):
        self.root = Path(root).resolve()
        self.reader = PassageReader(self.root, bundle)
        self.bundle = self.reader.bundle
        self.seal_sha256 = digest((self.bundle/"seal.json").read_bytes())
        if expected_seal_sha256 is not None and self.seal_sha256!=expected_seal_sha256:
            raise M3Error("M2 seal is not the accepted bundle")

    def _iter_cases(self,cases):
        for case_id in sorted(cases):
            raw, _ = self.reader.nav.source._source(case_id)
            record = self.reader._artifact(f"sources/{case_id[:-4]}.json")
            nav=self.reader.nav._artifact(f"sources/{case_id[:-4]}.json")
            preview_counts={r["unit_id"]:len(r["preview_refs"]) for r in nav["navigation"]}
            if record["source_hash"] != digest(raw):
                raise M3Error("M2/raw source hash drift")
            for p in record["passages"]:
                a, b = p["span_bytes"]
                if p["source_hash"] != record["source_hash"] or raw[a:b].decode("utf-8") != p["text"] or digest(raw[a:b]) != p["exact_input_sha256"]:
                    raise M3Error("M2 passage differs from raw source")
                yield {**p,"navigation_preview_count":preview_counts[p["parent_unit_ids"][0]]}

    def iter_passages(self):
        return self._iter_cases(self.reader.rows)

    def selected(self, ids):
        wanted = set(ids)
        found = {}
        cases={i.split(":",1)[0]+".txt" for i in wanted}
        if not cases.issubset(self.reader.rows):raise M3Error("Unknown pilot case")
        for p in self._iter_cases(cases):
            if p["passage_id"] in wanted:
                found[p["passage_id"]] = p
        if set(found) != wanted:
            raise M3Error("Pilot passage missing from pinned M2")
        return [found[i] for i in ids]

    def open(self, passage_id):
        case_id = passage_id.split(":", 1)[0]+".txt"
        return self.reader.open_context(case_id, passage_id)
