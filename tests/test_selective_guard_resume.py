import copy
import unittest
from knowledge_base.pipeline_v1.selective_reading.runtime import _resume_guard,_budget,GUARD_COMPAT_IMPLEMENTATION
from knowledge_base.pipeline_v1.selective_reading.core import CAPS


class GuardResumeTests(unittest.TestCase):
    def state(self):
        return {'identity':{'source':'locked','model':'9B','prompt':'unchanged','implementation_sha256':GUARD_COMPAT_IMPLEMENTATION},
                'stop_reason':'budget_exhausted','finished':False,
                'groups':{'g':{'finished':True,'reservations':[{'job_id':'a','estimate':1000}]}},
                'rows':{'a':{'receipt':{'usage':{'input_tokens':100,'output_tokens':10,'total_tokens':110}}}}}

    def test_guard_only_migration_preserves_rows_usage_and_actual_ceiling(self):
        state=self.state();rows=copy.deepcopy(state['rows']);cost=_budget(state);caps=copy.deepcopy(CAPS)
        new={**state['identity'],'implementation_sha256':'new-code'}
        _resume_guard(state,new,260000)
        self.assertEqual(rows,state['rows']);self.assertEqual(cost,_budget(state));self.assertEqual(CAPS,caps)
        self.assertEqual(state['identity'],new);self.assertEqual(state['effective_input_estimate_bytes'],260000)
        self.assertTrue(state['guard_override_history'][0]['source_model_prompt_schema_policy_unchanged'])

    def test_reader_or_unknown_code_change_rejected(self):
        for field,value in [('model','other'),('prompt','changed')]:
            s=self.state();new={**s['identity'],'implementation_sha256':'new-code',field:value}
            with self.assertRaises(ValueError):_resume_guard(s,new,260000)
        s=self.state();s['identity']['implementation_sha256']='unknown-old-code'
        with self.assertRaises(ValueError):_resume_guard(s,{**s['identity'],'implementation_sha256':'new-code'},260000)

    def test_pending_unknown_or_other_stop_rejected(self):
        for kind in ('pending','unknown','other_stop'):
            s=self.state();new={**s['identity'],'implementation_sha256':'new-code'}
            if kind=='pending':s['groups']['g']['finished']=False
            elif kind=='unknown':s['rows']['a']['receipt']['usage']=None
            else:s['stop_reason']='provider_outcome_unknown'
            with self.assertRaises(ValueError):_resume_guard(s,new,260000)

    def test_cap_bounds_and_bool_rejected(self):
        for cap in (True,200000,300001):
            s=self.state()
            with self.assertRaises(ValueError):_resume_guard(s,{**s['identity'],'implementation_sha256':'new-code'},cap)


if __name__=='__main__':unittest.main()
