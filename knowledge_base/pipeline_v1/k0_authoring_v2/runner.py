"""Private frozen runner adapter; never mutate imported v1 modules."""
from __future__ import annotations

import copy
import math
import time
import types
from pathlib import Path
from urllib import request as urlrequest

from . import core
from ..k0_authoring import runner as frozen
from ..au_compact.runner import _atomic


def _adapter():
    # Executed with this package's relative imports: .core/.tools resolve to v2.
    # All transport/accounting implementation is still the exact bound frozen code.
    module = types.ModuleType(__package__ + '._private_runner')
    module.__file__, module.__package__ = frozen.__file__, __package__
    exec(compile(Path(frozen.__file__).read_text(encoding='utf-8'),
                 frozen.__file__, 'exec'), module.__dict__)
    old_report = module._report
    old_advance = module._advance

    def advance(case, state, job, receipt):
        result = old_advance(case, state, job, receipt)
        if receipt.get('normalized') is None and 'raw_response' in receipt:
            for sid in job['active_scope_ids']:
                result['read_ledger'][sid].update(state='unresolved', assessed=False)
            result['work_scope_complete'] = False
        return result

    module._advance = advance

    def report(root, w, accounting, states, pauses, mock, started, clock):
        result = old_report(root, w, accounting, states, pauses, mock, started, clock)
        for row in result['results']:
            row['work_scope_complete'] = bool(row['state']['work_scope_complete']) and not row['pause_reason']
        work_complete = all(row['work_scope_complete'] for row in result['results']) and not pauses
        execution_complete = all(row['state']['finished'] for row in result['results']) and not pauses
        result.update(artifact_type='K0AuthoringRunV2',
            status='complete' if execution_complete else 'incomplete',
            execution_complete=execution_complete, work_scope_complete=work_complete,
            protocol_complete=execution_complete,
            semantic_pass=False, K1_allowed=False, corpus_dispatch_allowed=False)
        _atomic(root / 'run.json', result)
        return result

    module._report = report
    return module


def _config(cfg):
    cfg = copy.deepcopy(cfg)
    # Always produce floats, including at caps. Reapplying is byte-idempotent.
    for key, default, cap in [('readiness_seconds', 600, 600),
                              ('job_wait_seconds', 600, 600),
                              ('job_poll_seconds', 1, 60), ('timeout', 60, 60)]:
        value = cfg.get(key, default)
        core.require(type(value) in (int, float) and math.isfinite(value) and value > 0,
                     'invalid runtime time bound')
        cfg[key] = float(min(value, cap))
    return cfg


def run(workload, output_root, cfg=None, execute=False, mock=False,
        opener=urlrequest.urlopen, clock=time.perf_counter, sleep=time.sleep,
        max_new_requests=None, controls_root=core.DEFAULT_CONTROLS):
    core.require(not (execute and mock), 'execute/mock mutually exclusive')
    root = Path(output_root).resolve()
    core.require(isinstance(workload, (str, Path)) and
                 Path(workload).resolve() == root / 'input/workload.json',
                 'run requires exact ROOT/input/workload.json')
    w = core.load(workload)
    core.preflight(workload, cfg)
    # Apply guards even on dry-run and before creating any execution artifacts.
    core.guard_output(root, [w['source_store'], *[Path(b['path']).parent for b in w['parent_bindings']]])
    for path in root.rglob('*'):
        core.require(not path.is_symlink() and path.resolve().is_relative_to(root),
                     'redirected output artifact')
    if cfg is None:
        if execute:
            from argparse import Namespace
            from ..au_context_paired.__main__ import study_config
            cfg, _, _ = study_config(Namespace())
        else:
            cfg = core.runtime_config(w['identity'])
    cfg = _config(cfg)
    core.profile(w, cfg)
    if execute:
        core.require_cpu(root)
        core.require_controls(controls_root, w)
    module = _adapter()
    profile = module.profile

    def bound_profile(w, cfg):
        return {**profile(w, cfg), 'readiness_seconds': cfg['readiness_seconds']}

    module.profile = bound_profile
    return module.run(workload, root, cfg=cfg, execute=execute, mock=mock,
        opener=opener, clock=clock, sleep=sleep, max_new_requests=max_new_requests)
