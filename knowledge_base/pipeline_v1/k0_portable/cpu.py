"""Offline native probe over pinned repository tokenizer and installed packages."""
import os
import sys
import types
from pathlib import Path

from .paths import repository, resolve
from ..k0_authoring.token_budget import ASSETS, EXPECTED


def main():
    import argparse
    import hashlib
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root')
    p.add_argument('--bundle', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    repo = repository(a.repo_root)
    bundle, output = resolve(repo, a.bundle), resolve(repo, a.output)
    tokenizer = ASSETS / 'tokenizer.json'
    if hashlib.sha256(tokenizer.read_bytes()).hexdigest() != EXPECTED['tokenizer.json']:
        raise ValueError('tokenizer digest changed')
    helper = Path(__file__).resolve().parents[1] / 'experiments/k0_grammar_cpu_probe.py'
    text = helper.read_text(encoding='utf-8')
    replacements = {
        "        sys.path[:0] = [str(deps / 'pinned'), str(deps / 'runtime')]":
            '        # Use installed packages only; no legacy outputs dependency.',
        "        tokenizer_path = deps / 'tokenizer.json'":
            '        tokenizer_path = PORTABLE_TOKENIZER',
    }
    for anchor, replacement in replacements.items():
        if text.count(anchor) != 1:
            raise ValueError('frozen CPU adapter anchor changed')
        text = text.replace(anchor, replacement)
    module = types.ModuleType(__package__ + '._cpu_probe')
    module.__file__ = str(helper)
    module.PORTABLE_TOKENIZER = tokenizer
    exec(compile(text, str(helper), 'exec'), module.__dict__)
    previous = sys.argv
    try:
        # This probe uses NumPy CPU masks, never Torch tensor allocation. Avoid
        # an unrelated optional C++ build during TVM-FFI import on new machines.
        os.environ.setdefault('TVM_FFI_DISABLE_TORCH_C_DLPACK', '1')
        sys.argv = [str(helper), '--bundle', str(bundle), '--output', str(output)]
        return module.main()
    finally:
        sys.argv = previous


if __name__ == '__main__':
    raise SystemExit(main())
