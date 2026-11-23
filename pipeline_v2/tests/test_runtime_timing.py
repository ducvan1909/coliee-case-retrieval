"""Contract tests for opt-in, hierarchical timing profiles."""
import unittest

from pipeline_v2.runtime_timing import TimingProfile, measure, timed


class Trace:
    def __init__(self):
        self.events = []

    def emit(self, kind, **data):
        self.events.append((kind, data))


class RuntimeTimingTests(unittest.TestCase):
    def test_nested_parts_report_calls_and_nonnegative_exclusive_time(self):
        trace = Trace()
        profile = TimingProfile(True, trace)

        @timed('leaf')
        def leaf():
            return 'done'

        with profile.record('compile_context', request_id='T1'):
            with measure('read_ledger'):
                leaf()
                leaf()

        kind, event = trace.events[-1]
        self.assertEqual(kind, 'timing_breakdown')
        self.assertEqual(event['status'], 'success')
        self.assertEqual(event['scope'], 'compile_context')
        self.assertEqual(event['request_id'], 'T1')
        parts = event['parts']
        self.assertEqual(parts['read_ledger']['calls'], 1)
        self.assertEqual(parts['leaf']['calls'], 2)
        self.assertIn('unmeasured', parts)
        self.assertTrue(all(item['exclusive_ms'] >= 0 for item in parts.values()))
        # Exclusive regions partition measured and unmeasured elapsed time.
        accounted = sum(item['exclusive_ms'] for item in parts.values())
        self.assertLessEqual(abs(accounted - event['elapsed_ms']), 0.02)

    def test_exception_still_emits_breakdown_and_propagates(self):
        trace = Trace()
        profile = TimingProfile(True, trace)
        with self.assertRaisesRegex(ValueError, 'broken'):
            with profile.record('compile_context', request_id='T2'):
                with measure('read_source'):
                    raise ValueError('broken')
        kind, event = trace.events[-1]
        self.assertEqual(kind, 'timing_breakdown')
        self.assertEqual(event['status'], 'error')
        self.assertEqual(event['parts']['read_source']['calls'], 1)

    def test_disabled_profile_is_transparent_and_emits_no_timing_event(self):
        trace = Trace()
        profile = TimingProfile(False, trace)
        with profile.record('compile_context'):
            with measure('unneeded'):
                value = 4 + 5
        self.assertEqual(value, 9)
        self.assertEqual(trace.events, [])
        self.assertEqual(profile.summary(), {})

    def test_summary_keeps_samples_separated_by_scope_and_part(self):
        trace = Trace()
        profile = TimingProfile(True, trace)
        for request_id in ('T1', 'T2'):
            with profile.record('compile_context', request_id=request_id):
                with measure('serialize'):
                    sum(range(20))
        summary = profile.summary()['compile_context']
        self.assertEqual(summary['serialize']['calls'], 2)
        self.assertEqual(summary['serialize']['samples'], 2)
        self.assertIn(summary['serialize']['slowest_request_id'], ('T1', 'T2'))
        self.assertIn('p50_ms', summary['serialize'])
        self.assertIn('p95_ms', summary['serialize'])


if __name__ == '__main__':
    unittest.main()
