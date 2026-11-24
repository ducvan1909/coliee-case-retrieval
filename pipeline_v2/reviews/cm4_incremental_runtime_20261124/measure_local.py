"""Reproduce local projection/token measurements. Never calls a provider.

Run from repository root with .venv/Scripts/python.exe. Output is a new report;
the historical SQLite ledger is opened mode=ro and checked unchanged.
"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from pipeline_v2.agent_harness.contracts import encode, fingerprint
from pipeline_v2.agent_harness.ledger import Ledger, RunState
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.experiments.context_manager_v2.engine import Engine, code_binding
from pipeline_v2.experiments.context_manager_v2.live import SURVEY_FIRST_INSTRUCTIONS
from pipeline_v2.experiments.context_manager_v2.prompt_profiles import InputPolicy
from pipeline_v2.experiments.context_manager_v2.runtime_snapshot import RuntimeSnapshot, default_context


class ReadOnlyLedger(Ledger):
    @contextmanager
    def _connect(self, name, **kwargs):
        db = sqlite3.connect((self.path / name).resolve().as_uri() + '?mode=ro', uri=True)
        try:
            yield db
        finally:
            db.close()


def forbidden():
    raise AssertionError('No provider execution is permitted by this measurement')


def process_memory():
    """OS working-set counters; no optional package or heap tracing overhead."""
    if sys.platform == 'win32':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                *[(name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                    'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL('psapi', use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        values = Counters()
        values.cb = ctypes.sizeof(values)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(values), values.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return {'working_set_bytes': values.WorkingSetSize, 'peak_working_set_bytes': values.PeakWorkingSetSize}
    import resource
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {'peak_rss_bytes': value if sys.platform == 'darwin' else value * 1024}


def measure():
    source = ROOT / 'cache/cm4-survey-first-ag-20261123-120716794/session'
    path = source / 'events.sqlite3'
    before = sha256(path.read_bytes()).hexdigest()
    ledger = ReadOnlyLedger(source)

    def legacy():
        events = ledger.read()
        state, context = RunState(events), default_context()
        for event in events:
            if event.get('cm_context'):
                context = deepcopy(event['cm_context'])
            if event.get('cm_auto_query_view'):
                context.update(deepcopy(event['cm_auto_query_view']))
        Engine._sync_missing(context)
        return state.snapshot(), context, fingerprint(events)

    memory_before = process_memory()
    start = perf_counter()
    runtime = RuntimeSnapshot(ledger)
    runtime.sync()
    startup = perf_counter() - start
    memory_after_bootstrap = process_memory()

    def incremental():
        runtime.sync()
        context = deepcopy(runtime.context)
        Engine._sync_missing(context)
        return deepcopy(runtime.state.snapshot()), context, runtime.prefix_sha256

    baseline = legacy()
    assert incremental() == baseline
    samples = {'legacy': [], 'incremental': []}
    for i in range(5):
        order = [('legacy', legacy), ('incremental', incremental)]
        for name, method in order if i % 2 == 0 else reversed(order):
            start = perf_counter()
            value = method()
            samples[name].append((perf_counter() - start) * 1000)
            assert value == baseline
    assert sha256(path.read_bytes()).hexdigest() == before

    transport = ModalQwenTransport(ROOT / 'cache/tokenizers/qwen36_27b_fp8',
        instructions=SURVEY_FIRST_INSTRUCTIONS, remote_factory=forbidden, wait_seconds=None)
    audit = ROOT / 'cache/cm4-catalog-audit-0c2da9f-20261123'
    profiles = []
    for name in ['real_A_0', 'real_A_1', 'default_fixture_permit', 'default_fixture_B_cards_page1',
                 'default_fixture_B_open', 'default_fixture_identity_only']:
        saved = json.loads((audit / (name + '.json')).read_text(encoding='utf-8'))
        payload, schema = saved['payload'], saved['decoder_schema']
        original = encode(payload), encode(schema)
        row = {'name': name, 'baseline_input': transport.count_tokens(encode(payload)), 'variants': {}}
        for catalog, instructions in [('compact_catalog_v1', 'full'), ('full', 'phase_instructions_v1'),
                                      ('compact_catalog_v1', 'phase_instructions_v1')]:
            policy = InputPolicy(transport, catalog_profile=catalog, instruction_profile=instructions)
            body, tokens, spec = policy.prepare(payload, schema)
            transport.verify_frozen_request(encode(body), schema, spec)
            assert body['excerpts'] == payload['excerpts'] and body['m6'] == payload['m6']
            assert (encode(payload), encode(schema)) == original
            row['variants'][catalog + '+' + instructions] = {
                'input_tokens': tokens, 'phase': spec['profile_id'],
                'saved_percent': round(100 * (row['baseline_input'] - tokens) / row['baseline_input'], 2)}
        profiles.append(row)
    return {'scope': 'Historical state/context/hash benchmark and fixed-packet input measurements; not live inference/compile latency.',
        'provider_requests': 0, 'production_binding': code_binding(),
        'projection': {'events': runtime.last_seq, 'bootstrap_seconds': startup, 'samples_ms': samples,
            'p50_ms': {key: statistics.median(values) for key, values in samples.items()},
            'runtime_stats': runtime.stats, 'source_db_unchanged': True,
            'memory_before_runtime': memory_before, 'memory_after_runtime_bootstrap': memory_after_bootstrap,
            'memory_after_all_measurements': process_memory()}, 'input_profiles': profiles}


if __name__ == '__main__':
    report = measure()
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).with_name('local_measurement.json')
    if target.exists():
        raise SystemExit('Choose a new output path; existing measurement is preserved')
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(target), 'p50_ms': report['projection']['p50_ms'], 'provider_requests': 0}))
