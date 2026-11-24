"""Offline 0c2da9f/current engine differential on scripted passage fixtures.

Loads baseline code from local Git objects, writes only temporary fixture runs,
and never invokes a provider. Token counts here use a fixture counter.
"""
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
PACKAGE = 'pipeline_v2.experiments.context_manager_v2'

from pipeline_v2.agent_harness import ledger
from pipeline_v2.agent_harness.contracts import fingerprint
from pipeline_v2.experiments.context_manager_v2 import engine as current
from pipeline_v2.experiments.context_manager_v2.cli import choose
from pipeline_v2.experiments.context_manager_v2.tests import test_passage_review as fixtures


def baseline(name):
    path = 'pipeline_v2/experiments/context_manager_v2/' + name + '.py'
    result = subprocess.run(['git', '-C', str(ROOT), '-c', 'safe.directory=G:/Git/coliee-case-retrieval',
        'show', '0c2da9f:' + path], check=True, capture_output=True)
    module = types.ModuleType(PACKAGE + '._oracle_' + name)
    module.__package__, module.__file__ = PACKAGE, str(ROOT / path)
    sys.modules[module.__name__] = module
    exec(compile(result.stdout, module.__file__, 'exec'), module.__dict__)
    return module


class FixedClock:
    @staticmethod
    def now(tz=None):
        return datetime(2026, 11, 24, 0, 0, 0, tzinfo=timezone.utc)


def normalized_state(engine):
    result = engine.state().snapshot()
    result['config']['cm23'].pop('code', None)
    return result


def run():
    old = baseline('engine')
    old.query_review, old.passage_review = baseline('query_review'), baseline('passage_review')
    stages = []
    with TemporaryDirectory() as directory, ExitStack() as stack:
        stack.enter_context(patch.object(ledger, 'datetime', FixedClock))
        stack.enter_context(patch('pipeline_v2.agent_harness.harness.perf_counter', return_value=0.0))
        stack.enter_context(patch.object(old, 'perf_counter', return_value=0.0))
        stack.enter_context(patch.object(current, 'perf_counter', return_value=0.0))
        fixture = fixtures.PassageReviewTests()
        with patch.object(fixtures, 'Engine', old.Engine):
            left, _ = fixture.make_engine(Path(directory) / 'old', page_size=1)
        right, _ = fixture.make_engine(Path(directory) / 'new', page_size=1)
        for engine in (left, right):
            engine.survey_first = engine.identity_check_enabled = True

        def compare(name):
            packets = left.prepare(admit=False), right.prepare(admit=False)
            for key in ('payload', 'input_tokens', 'status'):
                assert packets[0][key] == packets[1][key], (name, key)
            for key in ('schema', 'handles', 'dispatch_m6', 'wire_aliases', 'coverage', 'excerpts', 'context'):
                assert packets[0]['manifest'][key] == packets[1]['manifest'][key], (name, key)
            assert left.context() == right.context(), name
            assert normalized_state(left) == normalized_state(right), (name, 'state')
            assert right._runtime.prefix_sha256 == fingerprint(right.events()), name
            stages.append({'stage': name, 'exact_wire_schema_refs_context_state': True,
                           'fixture_counter_input_tokens': packets[1]['input_tokens']})
            return packets

        compare('source_before_approval')
        from pipeline_v2.experiments.context_manager_v2.tests.test_source_gate import screen
        for engine in (left, right):
            engine.step(lambda p: screen(p, 'The Court applied the notice fairness rule in this dispute.'))
        compare('permit')
        for engine in (left, right):
            engine.step(lambda p: choose(p, 'search_cases_by_issue'))
        compare('first_B_cards')
        for engine in (left, right):
            fixture.survey_then_open(engine, 'B_A')
        packets = compare('B_open')
        roles = []
        for engine, prepared in zip((left, right), packets):
            fields = fixture.identity_check_fields(prepared)
            role = {key: [field['items']['enum'][0]] for key, field in fields.items()}
            roles.append(role)
            engine.step({'action': 'request_identity_check', 'args': role})
        compare('identity_only')
        for engine, role in zip((left, right), roles):
            engine.step({'action': 'conclude_candidate', 'args': {
                'identity_relation': 'insufficient_evidence', 'reason': 'Scripted identity packet comparison.',
                'bridge': 'No legal judgment is inferred by this fixture.',
                'a_refs': role['a_refs'], 'b_refs': role['b_rule_refs'], 'identity_refs': role['b_identity_refs']}})
        compare('after_conclusion_auto_return')
        for engine in (left, right):
            engine.step(lambda p: choose(p, 'show_context_page'))
        compare('second_B_cards')
        for engine in (left, right):
            fixture.survey_then_open(engine, 'B_B')
        compare('second_B_open')
        for engine in (left, right):
            engine.step(lambda p: choose(p, 'return_to_candidates', reason='Keep this candidate pending.'))
        compare('returned_pending')
        for engine in (left, right):
            engine.step(lambda p: choose(p, 'conclude_search_query', reason='Remaining candidate stays pending.'))
        compare('partial_query_conclusion')
        stats = deepcopy(right._runtime.stats)
    return {'baseline_commit': '0c2da9f', 'provider_requests': 0,
        'limitations': 'Scripted fixture source/retrieval, fixture counter; not legal quality or live performance.',
        'production_binding': current.code_binding(), 'stages': stages, 'runtime_stats': stats}


if __name__ == '__main__':
    report = run()
    target = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).with_name('legacy_parity.json')
    if target.exists():
        raise SystemExit('Choose a new output path; existing report is preserved')
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'stages': len(report['stages']), 'provider_requests': 0, 'runtime_stats': report['runtime_stats']}))
