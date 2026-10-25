"""Private frozen adapter with portable binding and unchanged receipt replay."""
import copy
import time
import types
from urllib import request

from . import core
from .paths import repository, resolve
from ..k0_authoring_v2 import runner as frozen_runner
from ..au_compact.runner import _atomic


def run(output_root=core.DEFAULT_RUN, repo_root=None, cfg=None, execute=False, mock=False,
        max_new_requests=None, opener=request.urlopen, clock=time.perf_counter, sleep=time.sleep):
    core.require(not (execute and mock), 'execute/mock mutually exclusive')
    repo = repository(repo_root)
    root = resolve(repo, output_root)
    checked = core.preflight(output_root, repo, cfg)
    w = core.load(root / 'input/workload.json')
    if cfg is None:
        if execute:
            from argparse import Namespace
            from ..au_context_paired.__main__ import study_config
            cfg, _, _ = study_config(Namespace())
        else:
            cfg = core.frozen.runtime_config(w['identity'])
    cfg = frozen_runner._config(cfg)
    core.frozen.profile(w, cfg)
    if execute:
        core.frozen.require_cpu(root)
    if not execute and not mock:
        result = {**checked, 'status': 'not_executed', 'network_requests': 0, 'mode': 'dryrun'}
        _atomic(root / 'dryrun/run.json', result)
        return result
    module = frozen_runner._adapter()
    # Only this private module receives the portable core; frozen imports stay untouched.
    proxy = types.ModuleType(__package__ + '._private_core')
    proxy.__dict__.update(core.frozen.__dict__)
    proxy.preflight = lambda workload, cfg=None: core.preflight(output_root, repo, cfg)
    proxy.code_hash = lambda: w['code_sha256']
    module.core = proxy
    original_profile = module.profile
    module.profile = lambda work, config: {**original_profile(work, config),
        'readiness_seconds': config['readiness_seconds']}
    # Expanded paths exist in memory only. Hash/job IDs derive from the unchanged
    # relative workload digest; no absolute source path occurs in request payloads.
    expanded = copy.deepcopy(w)
    expanded['source_store'] = str(resolve(repo, w['source_store']))
    expanded['parent_bindings'] = [{**b, 'path': str(resolve(repo, b['path']))} for b in w['parent_bindings']]
    result = module.run(expanded, root, cfg=cfg, execute=execute, mock=mock,
        max_new_requests=max_new_requests, opener=opener, clock=clock, sleep=sleep)
    return result
