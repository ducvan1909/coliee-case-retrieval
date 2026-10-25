"""Offline native K0 grammar replay; consumes prebuilt grammars, never imports K0.

Run with the existing Python310 runtime and --bundle/--output paths. The caller
owns the wall-clock timeout. Reports are checkpointed during the run; payloads,
grammar text, example text, environment and exception messages are not logged.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
VOCAB_SIZE = 248320
STOP_IDS = [248044, 248046]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def save_report(path, report, started):
    report['elapsed_seconds'] = round(time.perf_counter() - started, 6)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=True, indent=2) + '\n',
                         encoding='utf-8')
    os.replace(temporary, path)


def location(prefix):
    """Describe an AU-array boundary versus a string without copying its value."""
    if re.search(r'"aus"\s*:\s*\[\s*$', prefix):
        return 'after_aus_array_open'
    in_string = escaped = False
    for char in prefix:
        if escaped:
            escaped = False
        elif in_string and char == '\\':
            escaped = True
        elif char == '"':
            in_string = not in_string
    return 'inside_text' if in_string else 'json_structure'


def check_example(text, expected, compiled, tokenizer, xgr, np):
    started = time.perf_counter()
    direct = xgr.GrammarMatcher(compiled)
    accepted = bool(direct.accept_string(text))
    complete = bool(direct.is_completed()) if accepted else False
    row = {
        'example_sha256': digest(text.encode('utf-8')),
        'expected_accept': expected,
        'accept_string': accepted,
        'string_completed': complete,
        'passed': (accepted and complete) if expected else not accepted,
    }
    if not expected:
        # Require parser rejection, rather than treating an accepted incomplete
        # prefix as proof that the negative example was rejected.
        row['rejected_as_string'] = not accepted
        row['passed'] = not accepted
        row['elapsed_seconds'] = round(time.perf_counter() - started, 6)
        return row

    token_ids = tokenizer.encode(text, add_special_tokens=False)
    row.update(token_ids=token_ids, token_count=len(token_ids),
               tokens_checked=0, first_failed_mask=None, first_failure=None,
               token_checks=[], aus_boundary_checks=[])
    matcher = xgr.GrammarMatcher(compiled)
    mask = np.full((1, (VOCAB_SIZE + 31) // 32), -1, dtype=np.int32)

    def allowed(token):
        return 0 <= token < VOCAB_SIZE and bool(
            (int(mask[0, token // 32]) >> (token % 32)) & 1)

    def fill(obj):
        mask.fill(-1)
        obj.fill_next_token_bitmask(mask)

    def fail(kind, details):
        row['passed'] = False
        if row['first_failure'] is None:
            row['first_failure'] = dict(kind=kind, **details)

    # Direct boundary checks separate an AU-entry branch failure from text-token
    # failures, including when a tokenizer token crosses the '[' boundary.
    for match in re.finditer(r'"aus"\s*:\s*\[', text):
        boundary = xgr.GrammarMatcher(compiled)
        prefix_ok = bool(boundary.accept_string(text[:match.end()]))
        checkpoint = {'character_offset': match.end(), 'prefix_accepted': prefix_ok}
        if prefix_ok:
            fill(boundary)
            checkpoint['next_character_acceptance'] = {
                char: bool(boundary.fork().accept_string(char)) for char in ('{', ']')}
            checkpoint['next_token_masks'] = {
                char: [{'token_id': token, 'allowed': allowed(token)}
                       for token in tokenizer.encode(char, add_special_tokens=False)]
                for char in ('{', ']')}
        row['aus_boundary_checks'].append(checkpoint)

    for index in range(len(token_ids) + 1):
        fill(matcher)
        eos_allowed = {str(token): allowed(token) for token in STOP_IDS}
        eos_expected = index == len(token_ids)
        eos_accepted = {str(token): bool(matcher.fork().accept_token(token))
                        for token in STOP_IDS}
        details = {'token_index': index, 'eos_expected': eos_expected,
                   'eos_mask_allowed': eos_allowed, 'eos_accept_token': eos_accepted}
        if any(value != eos_expected for value in list(eos_allowed.values())
               + list(eos_accepted.values())):
            fail('eos_mismatch', details)
        if eos_expected:
            row['final_eos'] = details
            row['token_completed'] = bool(matcher.is_completed())
            if not row['token_completed']:
                fail('incomplete_token_replay', details)
            break
        token = token_ids[index]
        permitted = allowed(token)
        token_accepted = bool(matcher.accept_token(token))
        details.update(token_id=token, mask_allowed=permitted,
                       accept_token=token_accepted)
        row['token_checks'].append(details)
        row['tokens_checked'] += 1
        if not permitted or not token_accepted:
            prefix = tokenizer.decode(token_ids[:index], skip_special_tokens=False,
                                      clean_up_tokenization_spaces=False)
            details = dict(details, location=location(prefix),
                           prefix_character_count=len(prefix),
                           mask_word_index=token // 32,
                           mask_word_unsigned=int(mask[0, token // 32]) & 0xffffffff
                           if 0 <= token < VOCAB_SIZE else None)
            if not permitted and row['first_failed_mask'] is None:
                row['first_failed_mask'] = details
            fail('token_mask_or_accept_failure', details)
            # Mask rejection is evidence even if the parser accepts the token.
            # Continue only while parser state remains valid.
            if not token_accepted:
                break
    row['replayed_all_tokens'] = row['tokens_checked'] == len(token_ids)
    row['elapsed_seconds'] = round(time.perf_counter() - started, 6)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Refuse to replace an earlier diagnostic. Checkpoints only replace the
    # report reserved by this invocation.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        stream.write('{}\n')
    started = time.perf_counter()
    report = {'status': 'running', 'protocol_pass': False, 'semantic_quality_assessed': False,
              'inference_requests': 0, 'remote_requests': 0, 'device': 'cpu',
              'vocab_size': VOCAB_SIZE, 'stop_token_ids': STOP_IDS, 'jobs': []}
    save_report(args.output, report, started)
    try:
        raw_bundle = args.bundle.read_bytes()
        report['bundle_sha256'] = digest(raw_bundle)
        bundle = json.loads(raw_bundle.decode('utf-8-sig'))
        jobs = bundle['jobs'] if isinstance(bundle, dict) else bundle
        if not isinstance(jobs, list) or not jobs:
            raise ValueError('Expected nonempty jobs list')
        for job in jobs:
            if not isinstance(job, dict) or not isinstance(job.get('name'), str):
                raise ValueError('Invalid job')
            if not isinstance(job.get('grammar'), str) or not job['grammar']:
                raise ValueError('Invalid grammar')
            for key in ('positive_examples', 'negative_examples'):
                examples = job.get(key)
                if not isinstance(examples, list) or not examples or any(
                        not isinstance(text, str) for text in examples):
                    raise ValueError('Expected nonempty string example lists')
        deps = ROOT / 'outputs/grammar_diagnostic_deps'
        sys.dont_write_bytecode = True
        sys.path[:0] = [str(deps / 'pinned'), str(deps / 'runtime')]
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        import xgrammar as xgr
        import numpy as np
        from importlib.metadata import version
        from transformers import PreTrainedTokenizerFast
        report['versions'] = {name: version(name) for name in
                              ('xgrammar', 'transformers', 'tokenizers', 'numpy')}
        report['xgrammar_version'] = report['versions']['xgrammar']
        report['python_version'] = sys.version.split()[0]
        if report['versions']['xgrammar'] != '0.2.1':
            raise RuntimeError('Expected pinned XGrammar')
        tokenizer_path = deps / 'tokenizer.json'
        report['tokenizer_path'] = str(tokenizer_path.resolve())
        report['tokenizer_sha256'] = digest(tokenizer_path.read_bytes())
        tokenizer = PreTrainedTokenizerFast(tokenizer_file=str(tokenizer_path),
                                            eos_token='<|im_end|>')
        tokenizer.additional_stop_token_ids = []
        info = xgr.TokenizerInfo.from_huggingface(tokenizer, vocab_size=VOCAB_SIZE,
                                                  stop_token_ids=STOP_IDS)
        report['actual_stop_token_ids'] = list(info.stop_token_ids)
        if sorted(info.stop_token_ids) != STOP_IDS:
            raise RuntimeError('Stop token mismatch')
        compiler = xgr.GrammarCompiler(info, max_threads=1)
        compiled_by_hash = {}
        report['unique_grammars_compiled'] = 0
        save_report(args.output, report, started)
        for job in jobs:
            grammar_hash = digest(job['grammar'].encode('utf-8'))
            result = {'name': job['name'], 'grammar_sha256': grammar_hash,
                      'status': 'compiling', 'positive_examples': [], 'negative_examples': []}
            report['jobs'].append(result)
            save_report(args.output, report, started)
            job_started = time.perf_counter()
            try:
                compile_started = time.perf_counter()
                cached = grammar_hash in compiled_by_hash
                if not cached:
                    compiled_by_hash[grammar_hash] = compiler.compile_grammar(job['grammar'])
                    report['unique_grammars_compiled'] += 1
                compiled = compiled_by_hash[grammar_hash]
                result.update(compile_seconds=round(time.perf_counter() - compile_started, 6),
                              reused_compilation=cached, status='replaying')
                save_report(args.output, report, started)
                for key, expected in (('positive_examples', True), ('negative_examples', False)):
                    for index, example in enumerate(job[key]):
                        result['active_example'] = {'kind': key, 'index': index}
                        save_report(args.output, report, started)
                        row = check_example(example, expected, compiled, tokenizer, xgr, np)
                        row['index'] = index
                        result[key].append(row)
                        save_report(args.output, report, started)
                result.pop('active_example', None)
                result['passed'] = all(row['passed'] for key in
                    ('positive_examples', 'negative_examples') for row in result[key])
                result['status'] = 'passed' if result['passed'] else 'failed'
            except Exception as exc:
                result.update(status='error', passed=False, error_type=type(exc).__name__)
            result['elapsed_seconds'] = round(time.perf_counter() - job_started, 6)
            save_report(args.output, report, started)
        report['protocol_pass'] = all(job['passed'] for job in report['jobs'])
        report['status'] = 'pass' if report['protocol_pass'] else 'fail'
    except Exception as exc:
        report.update(status='fail', error_type=type(exc).__name__)
    save_report(args.output, report, started)
    print(json.dumps({'status': report['status'], 'jobs': len(report['jobs']),
                      'elapsed_seconds': report['elapsed_seconds'],
                      'inference_requests': 0}))
    return 0 if report['protocol_pass'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
