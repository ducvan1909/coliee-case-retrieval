"""Arm masking and stale-binding guards use the frozen local paired pilot."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from knowledge_base.pipeline_v1.context_hint_experiment.review import masked_packet, bind_reviews, costs

ROOT=Path(__file__).resolve().parents[3]
PIPE=ROOT/'knowledge_base/pipeline_v1'
RUN=PIPE/'outputs/plan11_hint_pairs_run_20261011'

class ContextHintReviewTests(unittest.TestCase):
    def setUp(self):
        self.report=json.loads((RUN/'run.json').read_text(encoding='utf-8'))
        self.packet,self.ids=masked_packet(self.report,PIPE/'outputs/source_store_v1',PIPE/'outputs/plan04_sentence_atoms_v1')

    def test_mask_removes_arm_hint_receipts_but_preserves_source_and_all_proposals(self):
        self.assertEqual(len(self.packet['rows']),8)
        self.assertEqual(sum(len(r['proposals']) for r in self.packet['rows']),7)
        for row in self.packet['rows']:
            self.assertNotIn('request_id',row)
            for forbidden in ('arm','hint_payload','receipt'): self.assertNotIn(forbidden,row)
            self.assertTrue(row['region_atoms'])
        self.assertEqual(len({b['review_id'] for b in self.ids}),8)

    def test_costs_include_both_arms_and_shared_known_overhead(self):
        pairing=json.loads((PIPE/'outputs/plan11_hint_pairs_20261011/pairing.json').read_text(encoding='utf-8'))
        result=costs(self.report,pairing)
        self.assertEqual(result['arms']['P2a']['requests'],4)
        self.assertEqual(result['arms']['P2b']['requests'],4)
        self.assertEqual(result['known_provider_total_tokens'],22345)
        self.assertFalse(result['quality_claim'])

    def test_stale_packet_binding_fails_before_any_review_is_applied(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            packet_raw=(RUN/'review_packet.masked.json').read_bytes()
            (root/'packet.json').write_bytes(packet_raw)
            (root/'ids.json').write_bytes((RUN/'review_bindings.private.json').read_bytes())
            reviewed={'packet_sha256':'0'*64,'reviews':[]}
            (root/'review.json').write_text(json.dumps(reviewed),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'exact masked packet'):
                bind_reviews(RUN/'run.json',root/'packet.json',root/'ids.json',root/'review.json')

    def test_private_mapping_swap_is_rejected_even_if_headers_and_id_set_match(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); raw=(RUN/'review_packet.masked.json').read_bytes()
            (root/'packet.json').write_bytes(raw)
            ids=json.loads((RUN/'review_bindings.private.json').read_text(encoding='utf-8'))
            a,b=ids['bindings'][:2]; a['request_id'],b['request_id']=b['request_id'],a['request_id']
            (root/'ids.json').write_text(json.dumps(ids),encoding='utf-8')
            (root/'review.json').write_text(json.dumps({'packet_sha256':hashlib.sha256(raw).hexdigest(),'reviews':[]}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'mapping locator'):
                bind_reviews(RUN/'run.json',root/'packet.json',root/'ids.json',root/'review.json')

if __name__=='__main__': unittest.main()
