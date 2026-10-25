"""Pinned tokenizer-only local accounting; never loads weights or calls inference."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import importlib.metadata
import json
from pathlib import Path

REVISION = 'c202236235762e1c871ad0ccb60c8ee5ba337b9a'
ASSETS = Path(__file__).resolve().parents[1] / 'assets/tokenizers/qwen35_9b' / REVISION
EXPECTED = {'tokenizer.json': '5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42',
            'tokenizer_config.json': '316230d6a809701f4db5ea8f8fc862bc3a6f3229c937c174e674ff3ca0a64ac8'}


def counter_identity():
    try:
        versions = {k: importlib.metadata.version(k) for k in ('tokenizers', 'jinja2')}
    except importlib.metadata.PackageNotFoundError:
        versions = None
    if not versions or not all((ASSETS / n).is_file() for n in EXPECTED):
        return {'method': 'full_serialized_payload_UTF8_bytes_plus128_fallback_not_provider_tokens'}
    for name, expected in EXPECTED.items():
        if hashlib.sha256((ASSETS / name).read_bytes()).hexdigest() != expected:
            raise ValueError('pinned tokenizer asset digest changed')
    return {'method': 'max_rendered_chat_and_full_serialized_payload_Qwen_tokens_plus128_reserve',
            'model': 'Qwen/Qwen3.5-9B', 'revision': REVISION, 'files': EXPECTED,
            'versions': versions, 'provider_usage': False}


@lru_cache(maxsize=1)
def _load():
    from tokenizers import Tokenizer
    from jinja2.sandbox import ImmutableSandboxedEnvironment
    cfg = json.loads((ASSETS / 'tokenizer_config.json').read_text(encoding='utf-8'))
    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True)
    def fail(_):
        raise ValueError('chat template rejected message')
    env.globals['raise_exception'] = fail
    env.filters['tojson'] = lambda x, **kwargs: json.dumps(x, ensure_ascii=False, **kwargs)
    return Tokenizer.from_file(str(ASSETS / 'tokenizer.json')), env.from_string(cfg['chat_template']), cfg


def input_reservation(payload):
    identity = counter_identity()
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if 'fallback' in identity['method']:
        return len(raw.encode('utf-8')) + 128
    tokenizer, template, cfg = _load()
    rendered = template.render(messages=payload['messages'], tools=None, add_generation_prompt=True,
                               enable_thinking=False, add_vision_id=False,
                               eos_token=cfg.get('eos_token'), bos_token=cfg.get('bos_token'))
    # The grammar is not normally prompt text; counting the entire HTTP payload
    # as well deliberately reserves more, not less, than the local chat count.
    chat_count = len(tokenizer.encode(rendered, add_special_tokens=False).ids)
    payload_count = len(tokenizer.encode(raw, add_special_tokens=False).ids)
    return max(chat_count, payload_count) + 128


def fetch():
    """Explicit public tokenizer download, not invoked by prepare/run."""
    from urllib.request import urlopen
    ASSETS.mkdir(parents=True, exist_ok=True)
    for name, digest in EXPECTED.items():
        path = ASSETS / name
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('existing tokenizer does not match pin')
            continue
        with urlopen('https://huggingface.co/Qwen/Qwen3.5-9B/resolve/' + REVISION + '/' + name, timeout=60) as response:
            raw = response.read(64 * 1024 * 1024 + 1)
        if len(raw) > 64 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('tokenizer download size/digest mismatch')
        with path.open('xb') as handle:
            handle.write(raw)


if __name__ == '__main__':
    import sys
    if sys.argv[1:] != ['fetch']:
        raise SystemExit('Usage: python -m knowledge_base.pipeline_v1.k0_authoring.token_budget fetch')
    fetch()
    print('Pinned Qwen tokenizer files ready; no weights or inference.')
