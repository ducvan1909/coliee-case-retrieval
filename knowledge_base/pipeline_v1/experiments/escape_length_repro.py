"""Small, source-free JSON Schema length reproduction; no inference or downloads."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def fixtures(cap=8):
    if type(cap) is not int or not 1 <= cap <= 32:
        raise ValueError('cap must be 1..32')
    schema = {'type': 'object', 'properties': {'text': {
        'type': 'string', 'minLength': 1, 'maxLength': cap}},
        'required': ['text'], 'additionalProperties': False}
    rows = []
    for label, char in [('ascii', 'a'), ('quote', '"'), ('backslash', '\\'),
                        ('newline', '\n'), ('bmp', '\u00e9'), ('nonbmp', '\U0001f600')]:
        for size in (max(1, cap - 1), cap, cap + 1):
            value = char * size
            for ascii_only in (False, True):
                text = json.dumps({'text': value}, ensure_ascii=ascii_only, separators=(',', ':'))
                rows.append({'name': f'{label}_{size}_ascii_{ascii_only}', 'json': text,
                             'decoded_length': len(value),
                             'serialized_string_content_length': len(text) - len('{"text":""}'),
                             'expected': size <= cap})
    return {'schema': schema, 'cases': rows, 'inference_requests': 0,
            'purpose': 'Isolate acceptance differences for equal decoded lengths; not token-mask or endpoint certification.'}


def evaluate(tokenizer_path, cap=8):
    report = fixtures(cap)
    try:
        import xgrammar as xg
        from transformers import AutoTokenizer
    except ImportError:
        return {**report, 'status': 'unavailable', 'reason': 'optional_dependencies_missing'}
    path = Path(tokenizer_path)
    # Never resolve a model name through the network.
    if not path.is_dir():
        return {**report, 'status': 'unavailable', 'reason': 'local_tokenizer_missing'}
    tok = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
    config_path = path / 'config.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    vocab = config.get('vocab_size', len(tok))
    eos = tok.eos_token_id
    stops = eos if isinstance(eos, list) else [eos] if eos is not None else []
    info = xg.TokenizerInfo.from_huggingface(tok, vocab_size=vocab, stop_token_ids=stops)
    compiled = xg.GrammarCompiler(info, max_threads=1).compile_json_schema(json.dumps(report['schema']))
    for row in report['cases']:
        matcher = xg.GrammarMatcher(compiled)
        row['accepted'] = bool(matcher.accept_string(row['json']) and matcher.is_completed())
        row['correct'] = row['accepted'] == row['expected']
    report.update(status='pass' if all(r['correct'] for r in report['cases']) else 'fail',
                  xgrammar_version=importlib.metadata.version('xgrammar'),
                  root_cause='not_established; acceptance observations only')
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', required=True)
    p.add_argument('--cap', type=int, default=8)
    p.add_argument('--tokenizer-path')
    p.add_argument('--max-seconds', type=int, default=60)
    p.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    output = Path(a.output).resolve()
    if output.exists():
        p.error('use a fresh output file')
    if not 1 <= a.max_seconds <= 120:
        p.error('max-seconds must be 1..120')
    report = fixtures(a.cap)
    if not a.tokenizer_path:
        report['status'] = 'prepared'
    elif a.worker:
        try:
            report = evaluate(a.tokenizer_path, a.cap)
        except Exception as exc:
            report.update(status='error', error_type=type(exc).__name__)
    else:
        with tempfile.TemporaryDirectory(prefix='escape-repro-') as temp:
            child = Path(temp) / 'report.json'
            try:
                subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker',
                                '--output', str(child), '--cap', str(a.cap),
                                '--tokenizer-path', a.tokenizer_path],
                               timeout=a.max_seconds, capture_output=True, check=False)
                report = json.loads(child.read_text(encoding='utf-8')) if child.exists() else {
                    **report, 'status': 'error', 'reason': 'worker_failed'}
            except subprocess.TimeoutExpired:
                report.update(status='incomplete', reason='native_compiler_deadline')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(f"ESCAPE REPRO {report['status'].upper()} — {output}; inference=0")
    return 0 if report['status'] in ('prepared', 'pass') else 3


if __name__ == '__main__':
    raise SystemExit(main())
