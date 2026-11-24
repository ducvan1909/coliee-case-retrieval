"""Operation-scoped exact projection memo; estimates never authorize admission."""
from copy import deepcopy
from functools import wraps
from hashlib import sha256

from pipeline_v2.agent_harness.contracts import fingerprint
from pipeline_v2.agent_harness.evidence import SourceDrift


class CompileMemo:
    def __init__(self):
        self.values = {}
        self.active = set()
        self.hits = self.misses = 0

    def get_or_build(self, key, build):
        if key in self.values:
            self.hits += 1
            return deepcopy(self.values[key])
        if key in self.active:
            raise RuntimeError('Recursive exact payload projection')
        self.misses += 1
        self.active.add(key)
        try:
            result = build()
            self.values[key] = deepcopy(result)
            return result
        finally:
            self.active.remove(key)


class CompileFrame(CompileMemo):
    """Shared history facts and source artifacts for one immutable compile phase."""
    def __init__(self, engine, state):
        super().__init__()
        self.generation = engine._runtime.generation
        self.history = engine._runtime
        self.snapshot = engine._runtime.snapshot()
        self.base = {'query_id': engine.harness.identity.query_id,
                     'query_source_hash': engine.harness.identity.query_source_hash,
                     'max_output_tokens': engine.harness.budget.max_output_tokens,
                     'query_delivery': 'continuation', 'observation_omitted': True,
                     'observation_scope': 'full_observation_omitted_bounded_feedback_included',
                     'candidate_count': len(state.candidates),
                     'active_assessment_count': len(state.active_assessments)}
        self.reader = engine.store.raw_reader
        self.verifier = engine.store.verify
        self.sources = {}
        self.source_opens = self.record_verifications = 0
        self.common_builds = 1

    def raw(self, case):
        if case not in self.sources:
            raw = self.reader(case)
            self.sources[case] = raw, sha256(raw).digest()
            self.source_opens += 1
        return self.sources[case][0]

    def verify(self, record):
        # Full canonical record/provenance is part of the key; identical text
        # with a different attribution overlay is not interchangeable.
        key = ('verified-record', fingerprint(record))
        def build():
            self.record_verifications += 1
            return self.verifier(record)
        return self.get_or_build(key, build)

    def verify_sources_fresh(self):
        for case, (_, expected) in self.sources.items():
            if sha256(self.reader(case)).digest() != expected:
                raise SourceDrift(case)

    def restore(self, store):
        store.raw_reader, store.verify = self.reader, self.verifier


def memoized_record(method):
    @wraps(method)
    def wrapped(self, state, target):
        memo = getattr(self, '_compile_memo', None)
        if memo is None:
            return method(self, state, target)
        key = ('source-record', self._runtime.generation, fingerprint(target))
        return memo.get_or_build(key, lambda: method(self, state, target))
    return wrapped


def memoized_feedback(method):
    @wraps(method)
    def wrapped(self, context):
        memo = getattr(self, '_compile_memo', None)
        if memo is None:
            return method(self, context)
        # The legacy helper initializes this working-context branch. A cache hit
        # must retain that side effect just as a fresh call does.
        if context.get('stage') == 'missing_evidence':
            self._progress(context)
        # _feedback does not inspect navigation/source record fields. Keep all
        # decision/pair/progress/repair fields in the key and omit only view shape.
        common = {key: value for key, value in context.items() if key not in {
            'query_leaf_region', 'query_map_region', 'query_span_record',
            'offset', 'back', 'revision', '_checking_query_span'}}
        key = fingerprint(['feedback', self._runtime.generation, common])
        return memo.get_or_build(key, lambda: method(self, context))
    return wrapped


def memoized_leaf(method):
    @wraps(method)
    def wrapped(self, state, context, progress_warning=None):
        memo = getattr(self, '_compile_memo', None)
        if memo is None:
            return method(self, state, context, progress_warning)
        backend = self.harness.hybrid_search
        key = fingerprint(['leaf', self._runtime.generation, context, progress_warning,
            self.render_page_size, self.harness.budget.max_payload_tokens,
            self.counter_binding, backend.remaining() if backend is not None else None])
        return memo.get_or_build(key, lambda: method(self, state, context, progress_warning))
    return wrapped
