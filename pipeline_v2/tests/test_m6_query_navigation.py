"""RT3 structural coverage, bounded maps and receipt-driven browsing fixtures."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jsonschema import ValidationError

from pipeline_v2.agent_harness import Budget, RunIdentity
from pipeline_v2.agent_harness.contracts import HarnessError, ModelReply, encode, fingerprint
from pipeline_v2.agent_harness.adaptive_policy import catalog, translate
from pipeline_v2.agent_harness.ledger import RunState
from pipeline_v2.m6 import AdaptiveConfig, AdaptiveHarness
from pipeline_v2.query_navigation import HierarchicalM3Tools, QueryNavigationConfig, QueryTree
from pipeline_v2.tests.test_m3_source_tools import SourceToolsFixture
from pipeline_v2.tests.test_m4_tools import LexicalFixture


def counter(payload):
    # Include a fixed instruction/template allowance; fixtures never send a model request.
    return len(payload.decode('utf-8')) // 4 + 100


class QueryTreeTests(unittest.TestCase):
    def tree(self, text, navigation=(), *, headings=(), case_id=None, **kwargs):
        raw = text.encode('utf-8')
        return QueryTree(raw, sha256(raw).hexdigest(), navigation, QueryNavigationConfig(**kwargs),
                         headings=headings, case_id=case_id)

    def assert_cover(self, tree):
        queue, leaves = [tree.root_ref], []
        visited = 0
        while queue:
            ref = queue.pop()
            node = tree.region(ref)
            children = tree.children(ref)
            visited += 1
            self.assertLess(visited, 20000, 'tree must terminate')
            left, right = node['span_bytes']
            self.assertTrue(tree.raw[left:right].decode('utf-8'))
            if children:
                self.assertLessEqual(len(children), tree.config.max_children)
                self.assertGreaterEqual(len(children), 2)
                expected = left
                for child in children:
                    self.assertEqual(child['span_bytes'][0], expected)
                    self.assertLess(child['span_bytes'][1] - child['span_bytes'][0], right - left)
                    expected = child['span_bytes'][1]
                    self.assertEqual(tree.parent(child['region_ref']), ref)
                self.assertEqual(expected, right)
                queue.extend(row['region_ref'] for row in children)
            else:
                self.assertLessEqual(right - left, tree.config.leaf_bytes)
                leaves.append((left, right))
        spans = sorted(leaves)
        self.assertEqual(spans[0][0], 0)
        self.assertEqual(spans[-1][1], len(tree.raw))
        self.assertTrue(all(one[1] == two[0] for one, two in zip(spans, spans[1:])))

    def test_no_heading_giant_paragraph_multibyte_and_unmapped_gaps_all_covered(self):
        for text in ('🙂漢字é' * 1000, '\nHEADER\n\n' + 'abc ' * 700 + '\n\nTRAILER\n', '🙂x'):
            with self.subTest(size=len(text)):
                raw = text.encode()
                structure = [{'handle': 'p', 'unit_kind': 'paragraph', 'span_bytes': [0, len(raw)]}]
                tree = self.tree(text, structure, leaf_bytes=64)
                self.assert_cover(tree)
        text = 'HEAD\n\n' + 'body ' * 150 + '\nGAP\n' + 'tail ' * 80 + '\nEND'
        tree = self.tree(text, [{'handle': 'h', 'unit_kind': 'heading', 'span_bytes': [0, 4]},
                                {'handle': 'p', 'unit_kind': 'paragraph', 'span_bytes': [6, 200]}], leaf_bytes=64)
        self.assert_cover(tree)

    def test_literals_are_exact_begin_middle_end_and_heading(self):
        text = 'HEADER\n' + 'É漢🙂abc ' * 50
        tree = self.tree(text, [{'unit_kind': 'paragraph', 'span_bytes': [7, len(text.encode())]}],
                         headings=[{'span_bytes': [0, 6], 'text': 'HEADER', 'text_sha256': sha256(b'HEADER').hexdigest()}],
                         leaf_bytes=80)
        page = tree.page(tree.root_ref, 12)
        for row in page['children']:
            self.assertEqual([part['position'] for part in row['snippets']], ['begin', 'middle', 'end'])
            for literal in [*row['snippets'], *([row['heading']] if 'heading' in row else [])]:
                start, end = literal['span_bytes']
                self.assertEqual(literal['text'].encode(), tree.raw[start:end])
                self.assertEqual(literal['text_sha256'], sha256(tree.raw[start:end]).hexdigest())
        self.assertEqual(next(row for row in page['children'] if row.get('heading'))['heading']['text'], 'HEADER')
        with self.assertRaisesRegex(HarnessError, 'heading text/hash'):
            self.tree(text, headings=[{'span_bytes': [0, 6], 'text': 'invented'}])

    def test_refs_stateless_config_source_version_bound_and_bad_paths_rejected(self):
        text = 'word ' * 1000
        one, two = self.tree(text, leaf_bytes=80), self.tree(text, leaf_bytes=80)
        ref = one.children(one.children(one.root_ref)[-1]['region_ref'])[0]['region_ref']
        self.assertEqual(one.region(ref), two.region(ref))
        for foreign in (self.tree(text + 'x', leaf_bytes=80), self.tree(text, leaf_bytes=81)):
            with self.assertRaises(HarnessError): foreign.region(ref)
        case_tree = self.tree(text, leaf_bytes=80, case_id='000001.txt')
        with self.assertRaises(HarnessError): self.tree(text, leaf_bytes=80, case_id='000002.txt').region(case_tree.root_ref)
        for bad in ('wrong', one.root_ref + '.99', one.root_ref + '.01', one.root_ref + '.-1'):
            with self.assertRaises(HarnessError): one.region(bad)
        for kwargs in ({'max_children': 1}, {'leaf_bytes': 1}, {'mode': 'flat'}, {'map_max_tokens': True}, {'snippet_chars': 0}):
            with self.assertRaises(HarnessError): QueryNavigationConfig(**kwargs)


class FakeController:
    count_tokens = staticmethod(counter)

    def __init__(self, steps=()):
        self.steps, self.payloads = list(steps), []

    def send_structured(self, payload, request_id, schema):
        body = json.loads(payload)
        self.payloads.append(body)
        return ModelReply(self.steps.pop(0)(body), 1, 1, 1)


class NavigationHarnessTests(SourceToolsFixture):
    def setUp(self):
        super().setUp()
        self.query = '000001.txt'
        # Keep full raw itself above the fixture's payload cap, independently
        # of how compact the navigation metadata becomes.
        self.text = 'HEADER\n\n' + ('Énoncé 漢字🙂: notice and fairness. ' * 1000) + '\nTRAILING'
        raw = self.text.encode()
        self.add_case(self.query, self.text, [{'handle': 'giant', 'span_bytes': [8, len(raw) - 9]}],
                      headings=[{'handle': 'head', 'span_bytes': [0, 6], 'text': 'HEADER'}])
        self.short = 'Short whole query about notice.'
        self.add_case('000002.txt', self.short, [{'handle': 'short', 'span_bytes': [0, len(self.short.encode())]}])
        self.reader = self.make_session()
        self.addCleanup(self.reader.close)
        self.tools = HierarchicalM3Tools(self.reader, LexicalFixture(), self.query,
                                         byte_budget=128, map_limit=2,
                                         navigation_config=QueryNavigationConfig(leaf_bytes=256),
                                         count_tokens=counter, output_token_cap=384)

    def agent(self, path, transport=None, tools=None, **kwargs):
        tools = tools or self.tools
        identity = RunIdentity('nav-test', tools.query_case, tools.query_tree.source_hash,
                               'candidate', 'index', 'profile', 'model', 'prompt', tools.fingerprint, 'tokenizer')
        return AdaptiveHarness(path, identity=identity, budget=Budget(12, 12, 100000, 7400, 384),
                               m3_tools=tools, transport=transport or FakeController(), **kwargs)

    @staticmethod
    def choose(body, name, predicate=lambda row: True):
        options = body['m6']['query_maps' if name == 'expand_query_map' else 'query_targets']
        key = next(key for key, row in options.items() if predicate(row))
        return {'action': name, 'args': {'map_ref' if name == 'expand_query_map' else 'query_ref': key}}

    def test_map_only_initial_fits_caps_and_retains_routes_for_every_child(self):
        initial, whole = self.tools.query_start()
        self.assertEqual(initial.excerpts, ())
        self.assertEqual(whole.text, self.text)
        with TemporaryDirectory() as path:
            agent = self.agent(path)
            prepared = agent.prepare()
            self.assertEqual(prepared['status'], 'ready')
            body = prepared['payload']
            self.assertLessEqual(prepared['input_tokens'], 7400)
            page = body['m6']['query_navigation']
            self.assertLessEqual(self.tools.page_tokens(page), 2400)
            self.assertEqual(page['current']['span_bytes'], [0, len(self.text.encode())])
            self.assertEqual(len(page['children']), 6)
            routes = {row['binding']['region_ref'] for row in body['m6']['query_targets'].values()}
            self.assertTrue({row['region_ref'] for row in page['children']} <= routes)
            self.assertFalse(body['excerpts'])
            names = {row['name'] for row in body['available_tools']}
            self.assertIn('expand_query_map', names)
            self.assertNotIn('search_cases_by_issue', names)
            self.assertNotIn('assess_case_link', names)
            self.assertTrue(all(not {**page['status_defaults'], **row['status']}['preview_seen'] for row in page['children']))
            self.assertTrue(all(any(snippet['text'] for snippet in row['snippets']) for row in page['children']))

    def test_raw_read_at_root_middle_child_and_continuation_uses_accepted_tools(self):
        root = self.tools.query_tree.root_ref
        refs = [root, self.tools.query_tree.children(root)[3]['region_ref']]
        for ref in refs:
            with self.subTest(ref=ref):
                result = self.tools.open_query({'navigation_mode': 'raw', 'region_ref': ref, 'visit_epoch': 0})
                start, end = self.tools.query_tree.region(ref)['span_bytes']
                self.assertTrue(result.excerpts)
                first = result.excerpts[0]
                self.assertEqual(first.span_bytes[0], start)
                self.assertLessEqual(sum(len(row.text.encode()) for row in result.excerpts), 128)
                self.assertEqual(first.text.encode(), self.text.encode()[first.span_bytes[0]:first.span_bytes[1]])
                self.assertIn('continuation', result.observation)
                continuation = self.tools.expand_source(result.observation['continuation'])
                self.assertTrue(continuation.excerpts)
                self.assertNotEqual(first.ref, continuation.excerpts[0].ref)

    def test_navigation_resume_back_sibling_and_actual_raw_receipt_grounding(self):
        root = self.tools.query_tree.root_ref
        child = self.tools.query_tree.children(root)[2]['region_ref']
        sibling = self.tools.query_tree.children(root)[3]['region_ref']
        def expand(ref):
            return lambda body: self.choose(body, 'expand_query_map', lambda row: row['binding']['region_ref'] == ref)
        def read(ref):
            return lambda body: self.choose(body, 'read_query_passages', lambda row: row['binding']['region_ref'] == ref)
        steps = [expand(child), expand(root), read(sibling),
                 lambda body: {'action': 'finish_case_review', 'args': {'reason': 'no_progress'}}]
        transport = FakeController(steps)
        with TemporaryDirectory() as path:
            agent = self.agent(path, transport)
            result = agent.run()
            self.assertEqual(result['stop_reason'], 'no_progress')
            payloads = transport.payloads
            self.assertEqual(payloads[1]['m6']['query_navigation']['current']['region_ref'], child)
            self.assertEqual(payloads[2]['m6']['query_navigation']['current']['region_ref'], root)
            self.assertTrue(payloads[3]['m6']['a_paragraphs'])
            self.assertTrue(all(row['paragraph_coverage'] == 'partial' for row in payloads[3]['m6']['a_paragraphs'].values()))
            self.assertTrue(all(counter(encode(body)) <= 7400 for body in payloads))
            # Payload immediately after opening is offered, not retrospectively read.
            sibling_row = next(row for row in payloads[3]['m6']['query_navigation']['children'] if row['region_ref'] == sibling)
            self.assertEqual({**payloads[3]['m6']['query_navigation']['status_defaults'], **sibling_row['status']}['raw_read'], 'unread')
            self.assertEqual(sibling_row['status']['raw_offered'], 'partial')
            resumed = self.agent(path, FakeController()).inspect()
            self.assertEqual(resumed['stop_reason'], result['stop_reason'])
            state = RunState(agent.events())
            rebuilt = self.tools.registry(agent.events(), state, payloads[-1])[0]
            rebuilt_sibling = next(row for row in rebuilt['children'] if row['region_ref'] == sibling)
            self.assertEqual(rebuilt_sibling['status']['raw_read'], 'partial')

    def test_repeated_root_map_revisits_are_allowed_but_stop_without_new_progress(self):
        root = self.tools.query_tree.root_ref
        step = lambda body: self.choose(body, 'expand_query_map', lambda row: row['binding']['region_ref'] == root)
        with TemporaryDirectory() as path:
            transport = FakeController([step] * 10)
            result = self.agent(path, transport, config=AdaptiveConfig(no_progress_actions=3)).run()
            self.assertEqual(result['stop_reason'], 'no_progress')
            self.assertEqual(len(transport.payloads), 3)

    def test_stale_navigation_ref_rejected_after_epoch_and_opened_unreceived_not_seen(self):
        with TemporaryDirectory() as path:
            agent = self.agent(path)
            body = agent.prepare()['payload']
            child = self.tools.query_tree.children(self.tools.query_tree.root_ref)[0]['region_ref']
            old = self.choose(body, 'expand_query_map', lambda row: row['binding']['region_ref'] == child)
            internal = translate(body, old)
            opened = self.tools.open_query(internal['args'])
            events = [{'kind': 'action_started', 'action_id': 'one', 'action': internal, 'executes_tool': True},
                      {'kind': 'action_result', 'action_id': 'one', 'status': 'success',
                       'result': {'observation': opened.observation, 'candidates': []}}]
            page, maps, reads = self.tools.registry(events, RunState(), body)
            self.assertFalse({**page['status_defaults'], **page['current']['status']}['map_seen'])
            self.assertTrue(page['current']['status']['map_opened'])
            changed = json.loads(json.dumps(body))
            changed['m6'].update(query_navigation=page, query_maps=maps, query_targets=reads)
            with self.assertRaises(ValidationError): translate(changed, old)
            self.assertLessEqual(self.tools.page_tokens(page), 2400)

    def test_short_whole_query_delivery_retained_and_impossible_mapcap_explicit(self):
        tools = HierarchicalM3Tools(self.reader, LexicalFixture(), '000002.txt', byte_budget=128, map_limit=2,
                                     navigation_config=QueryNavigationConfig(), count_tokens=counter)
        with TemporaryDirectory() as path:
            prepared = self.agent(path, tools=tools).prepare()
            self.assertEqual(prepared['status'], 'ready')
            self.assertEqual(prepared['payload']['query_delivery'], 'full')
            self.assertEqual(prepared['payload']['excerpts'][0]['text'], self.short)
        with self.assertRaisesRegex(HarnessError, 'cannot fit'):
            too_small = HierarchicalM3Tools(self.reader, LexicalFixture(), '000002.txt', byte_budget=128, map_limit=2,
                                            navigation_config=QueryNavigationConfig(map_max_tokens=1), count_tokens=counter)
            too_small.query_start()

    def test_actual_pinned_counter_retains_literal_content_for_each_child(self):
        tokenizer = Path.cwd() / 'cache/tokenizers/qwen36_27b_fp8'
        if not (tokenizer / 'tokenizer.json').is_file():
            self.skipTest('Pinned tokenizer assets unavailable locally')
        from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
        from pipeline_v2.m6_live import INSTRUCTIONS
        transport = ModalQwenTransport(tokenizer, instructions=INSTRUCTIONS)
        tools = HierarchicalM3Tools(self.reader, LexicalFixture(), self.query, byte_budget=128, map_limit=2,
                                    navigation_config=QueryNavigationConfig(), count_tokens=transport.count_tokens,
                                    output_token_cap=384)
        with TemporaryDirectory() as path:
            agent = self.agent(path, transport=transport, tools=tools)
            prepared = agent.prepare()
            self.assertEqual(prepared['status'], 'ready')
            page = prepared['payload']['m6']['query_navigation']
            self.assertGreaterEqual(page['snippet_chars'], 1)
            self.assertLessEqual(tools.page_tokens(page), 2400)
            self.assertLessEqual(prepared['input_tokens'], 7400)
            self.assertEqual(len(page['children']), 6)
            self.assertTrue(all(any(item['text'] for item in row['snippets']) for row in page['children']))

    def test_actual_pinned_root_and_internal_read_deliver_raw_and_search_tool(self):
        tokenizer = Path.cwd() / 'cache/tokenizers/qwen36_27b_fp8'
        if not (tokenizer / 'tokenizer.json').is_file():
            self.skipTest('Pinned tokenizer assets unavailable locally')
        from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
        from pipeline_v2.m6_live import INSTRUCTIONS
        pinned = ModalQwenTransport(tokenizer, instructions=INSTRUCTIONS)
        tools = HierarchicalM3Tools(self.reader, LexicalFixture(), self.query, byte_budget=128, map_limit=2,
                                    navigation_config=QueryNavigationConfig(), count_tokens=pinned.count_tokens,
                                    output_token_cap=384)
        root = tools.query_tree.root_ref
        for ref in (root, tools.query_tree.children(root)[2]['region_ref']):
            with self.subTest(ref=ref), TemporaryDirectory() as path:
                steps = [lambda body: self.choose(body, 'read_query_passages', lambda row: row['binding']['region_ref'] == ref),
                         lambda body: {'action': 'finish_case_review', 'args': {'reason': 'no_progress'}}]
                controller = FakeController(steps)
                controller.count_tokens = pinned.count_tokens
                result = self.agent(path, transport=controller, tools=tools).run()
                self.assertEqual(result['stop_detail'], 'controller_stop')
                self.assertEqual(len(controller.payloads), 2)
                body = controller.payloads[1]
                self.assertTrue(body['excerpts'])
                self.assertTrue(body['m6']['a_paragraphs'])
                self.assertIn('search_cases_by_issue', {row['name'] for row in body['available_tools']})
                self.assertLessEqual(pinned.count_tokens(encode(body)), 7400)
                page = body['m6']['query_navigation']
                routes = {row['binding']['region_ref'] for row in body['m6']['query_targets'].values()}
                self.assertTrue({row['region_ref'] for row in page['children']} <= routes)
                self.assertTrue(all(any(item['text'] for item in row['snippets']) for row in page['children']))
                self.assertTrue(any(row['description']['purpose'] == 'continue_pending_raw_page'
                                    for row in body['m6']['expansions'].values()),
                                'Raw continuation must survive payload option trimming')


if __name__ == '__main__':
    unittest.main()
