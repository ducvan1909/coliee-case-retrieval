"""Exercise the default adapter with the real extraction transport signature."""
import json
import tempfile
import unittest
from unittest.mock import patch
from knowledge_base.pipeline_v1.concurrency_benchmark import core


class DefaultAdapterTests(unittest.TestCase):
    def test_adapter_supplies_required_opener(self):
        with patch.object(core.runner, '_call', autospec=True, return_value=('compact','receipt')) as call:
            cfg={};q={};catalog={}
            self.assertEqual(core._default_call(cfg,q,'text',catalog=catalog),('compact','receipt'))
            call.assert_called_once_with(cfg,q,'text',core.urlrequest.urlopen,catalog=catalog)

    def test_default_run_reaches_real_call_and_jobs_transport_without_network(self):
        cfg={'url':'https://account--coliee-qwen35-9b-concurrency-server.us-west.modal.direct/v1/chat/completions',
             'token':'private-test-token','model':core.MODEL,'enable_thinking':False}
        q={'request_id':'original','expected_target_ids':['target'],'case_id':'013009',
           'spec':{'caps':{'output_tokens':800}},'hint_payload':{'version':'context-hint-payload-v1','hint_ids':[]}}
        manifest={'benchmark_id':'adapter-test','requests':[q]}
        task={'request':q,'source':'source','binding':{},'rendered':'fixed text',
              'catalog':{'atoms':{'sa-test':{'target_intersecting':True}}}}
        effective=core._effective(q,manifest,1)
        compact={'request_id':effective['request_id'],'target_id':'target','decision':'hard_negative',
                 'coverage_status':'complete','aus':[],'hard_negative_reason':'fact_only','unresolved_reason':None}
        envelope={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(compact)}}],
                  'usage':{'prompt_tokens':10,'completion_tokens':20,'total_tokens':30}}
        info={'experiment':core.VERSION,'gateway_concurrency':1,'server_concurrency':1,'max_containers':1,
              'model':core.MODEL,'context_length':12288,'max_total_tokens':12288,
              'app':'coliee-qwen35-9b-concurrency','cuda_graph_max_bs':1,'gpu':'L40S:1',
              'backend_retry':False,'exclusive_probes':True,'model_revision':'c202236235762e1c871ad0ccb60c8ee5ba337b9a',
              'job_volume':'coliee-qwen35-9b-concurrency-jobs','job_store_subdir':'c1','cpu':4,'memory_mb':16384,'ready':True}
        with tempfile.TemporaryDirectory() as root, patch.object(core,'prepare',return_value=[task]), \
             patch.object(core.runner,'build_prompt',return_value='fixed prompt'), \
             patch.object(core.runner,'build_decoding',return_value={}), \
             patch.object(core.runner,'complete_job',return_value=(envelope,{})) as jobs, \
             patch.object(core.runner,'_normalize',return_value={'target_results':[]}), \
             patch.object(core.urlrequest,'urlopen',side_effect=AssertionError('network forbidden')) as opener:
            result=core.run(manifest,source_store='not-source',atom_root='not-atoms',cfg=cfg,concurrency=1,
                            output_root=root,execute=True,capability_fetch=lambda cfg:info,
                            warmup_fn=lambda *args:{'status':'success'})
            self.assertEqual(result['completed_count'],1)
            self.assertTrue(result['protocol_pass'])
            self.assertFalse(result['stop_dispatch'])
            self.assertEqual(result['tokens']['total_tokens'],30)
            self.assertIs(jobs.call_args.args[2],opener)
            opener.assert_not_called()


if __name__=='__main__':unittest.main()
