"""Self-contained CPU probe. Never imports the production AU dependency tree."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import re
import sys
import time
from pathlib import Path

VERSION = 'au-length-probe-v1'
ORIGINAL_VARIANTS = ('host_validated', 'bounded', 'max_chars')
VARIANTS = (*ORIGINAL_VARIANTS, 'json_schema')
KINDS = ('holding', 'standard_of_review', 'statutory_hook', 'procedural_rule',
         'fact_pattern_rule', 'foreign_law', 'other')
CAPS = {'claim': 500, 'limits': 250, 'question': 200}
EOS = (248044, 248046)
IDS = ('s1', 'c1')


def build_grammar(ids=IDS, variant='host_validated'):
    """Mirror au_claim._grammar exactly for host_validated; IDs are literals only.

    max_chars uses an experimental rule annotation, probed by compilation. It is
    deliberately never considered a decoded-character constraint.
    """
    ids = tuple(ids)
    if variant not in ORIGINAL_VARIANTS or not ids or len(ids) > 32:
        raise ValueError('invalid variant or ID count')
    if any(not isinstance(i, str) or not re.fullmatch(r'[sc][1-9][0-9]{0,5}', i) for i in ids):
        raise ValueError('only fixed s/c IDs are supported')
    lit = lambda s: json.dumps(s, ensure_ascii=True)
    jlit = lambda s: lit(json.dumps(s, ensure_ascii=True))
    rules = []
    def rule(name, value): rules.append(name + ' ::= ' + value)
    def obj(parts): return lit('{') + ' ' + (' ' + lit(',') + ' ').join(parts) + ' ' + lit('}')
    def field(key, body): return lit(json.dumps(key) + ':') + ' ' + body
    rule('root', obj([field('aus', 'aus'), field('context_request', 'context')]))
    rule('aus', lit('[') + ' (au (' + lit(',') + ' au){0,2})? ' + lit(']'))
    separate = variant != 'host_validated'
    rule('au', obj([field('claim', 'claim-text' if separate else 'text'), field('kind', 'kind'),
                    field('evidence_ids', 'refs'), field('limits', 'nullable-text')]))
    rule('context', jlit(None) + ' | ' + obj([field('question', 'question-text' if separate else 'text')]))
    rule('kind', ' | '.join(jlit(k) for k in (*KINDS, None)))
    rule('refs', lit('[') + ' ref (' + lit(',') + ' ref)* ' + lit(']'))
    rule('ref', ' | '.join(jlit(k) for k in ids))
    rule('nullable-text', jlit(None) + ' | ' + ('limits-text' if separate else 'text'))
    if separate:
        for field_name, cap in CAPS.items():
            body = r'"\"" json-char{1,' + str(cap) + r'} "\""'
            if variant == 'max_chars':
                body = r'"\"" json-char* "\""'
            name = field_name + '-text'
            if variant == 'max_chars': name += '[max_chars=' + str(cap + 2) + ']'
            rule(name, body)
    else:
        rule('text', r'"\"" json-char* "\""')
    rule('json-char', r'[\x20-\x21\x23-\x5b\x5d-\uD7FF\uE000-\U0010FFFF] | "\\" (["\\/bfnrt] | "u" scalar-hex) | "\\u" [dD] [89aAbB] hex hex "\\u" [dD] [c-fC-F] hex hex')
    rule('scalar-hex', '[0-9a-cA-Ce-fE-F] hex hex hex | [dD] [0-7] hex hex')
    rule('hex', '[0-9a-fA-F]')
    return '\n'.join(rules) + '\n'


def build_schema(ids=IDS):
    """Native JSON Schema compiler input, with the same canonical wire shape."""
    ids = tuple(ids)
    # Reuse the fixed-ID guard; never interpolate external schemas or refs.
    build_grammar(ids)
    def obj(properties):
        return {'type': 'object', 'properties': properties,
                'required': list(properties), 'additionalProperties': False}
    def text(cap): return {'type': 'string', 'minLength': 1, 'maxLength': cap}
    def nullable(schema): return {'anyOf': [schema, {'type': 'null'}]}
    au = obj({'claim': text(500), 'kind': {'enum': [*KINDS, None]},
              'evidence_ids': {'type': 'array', 'minItems': 1,
                               'items': {'type': 'string', 'enum': list(ids)}},
              'limits': nullable(text(250))})
    return obj({'aus': {'type': 'array', 'minItems': 0, 'maxItems': 3, 'items': au},
                'context_request': nullable(obj({'question': text(200)}))})


def host_valid(value):
    """Wire validity only: no source bindings, entailment, or normalized AU output."""
    def text(v, cap):
        return (isinstance(v, str) and 1 <= len(v) <= cap and bool(v.strip())
                and not any(0xD800 <= ord(c) <= 0xDFFF for c in v))
    if not isinstance(value, dict) or set(value) != {'aus', 'context_request'}:
        return False
    if not isinstance(value['aus'], list) or len(value['aus']) > 3:
        return False
    ctx = value['context_request']
    if ctx is not None and (not isinstance(ctx, dict) or set(ctx) != {'question'} or not text(ctx['question'], 200)):
        return False
    for au in value['aus']:
        if not isinstance(au, dict) or set(au) != {'claim', 'kind', 'evidence_ids', 'limits'}:
            return False
        refs = au['evidence_ids']
        if (not text(au['claim'], 500) or au['kind'] not in (*KINDS, None)
                or (au['limits'] is not None and not text(au['limits'], 250))
                or not isinstance(refs, list) or not refs or any(r not in IDS for r in refs) or 's1' not in refs):
            return False
    return True


def build_cases():
    """Canonical JSON synthetic completions; expected grammar vs host are distinct."""
    cases = []
    def add(name, value, *, bounded=True, unbounded=True, ascii=True, replay=False):
        raw = json.dumps(value, ensure_ascii=ascii, separators=(',', ':'))
        cases.append(dict(name=name, text=raw, expected={'host_validated': unbounded, 'bounded': bounded},
                          host_valid=host_valid(value), replay=replay))
    def wire(field='claim', text='x'):
        au = {'claim': 'x', 'kind': None, 'evidence_ids': ['s1'], 'limits': None}
        value = {'aus': [au], 'context_request': None}
        if field == 'question': value['context_request'] = {'question': text}
        else: au[field] = text
        return value
    add('null_valid', {'aus': [], 'context_request': None}, replay=True)
    for field, cap in CAPS.items():
        for label, unit, ascii in [('ascii', 'a', False), ('bmp', '\u00e9', False),
                                   ('nonbmp', '\U0001f600', False), ('escaped_unicode', '\U0001f600', True),
                                   ('combining', 'e\u0301', False), ('quote', '"', True),
                                   ('backslash', '\\', True), ('control_escape', '\n', True)]:
            for size in (cap - 1, cap, cap + 1):
                text = (unit * (size // len(unit) + 1))[:size]
                if label == 'control_escape': text = 'a' + text[1:]
                add(f'{field}_{label}_{size}', wire(field, text), bounded=size <= cap,
                    ascii=ascii, replay=label == 'ascii' and size == cap)
        add(field + '_one', wire(field, 'x'), replay=True)
        add(field + '_empty', wire(field, ''), bounded=False)
        add(field + '_whitespace_host_invalid', wire(field, ' '))
        add(field + '_lone_high', wire(field, '\ud800'), bounded=False, unbounded=False)
        add(field + '_lone_low', wire(field, '\udfff'), bounded=False, unbounded=False)
        add(field + '_surrogate_pair_cap', wire(field, 'a' * (cap - 1) + '\U0001f600'), replay=True)
        for escape, decoded in [('b', '\b'), ('f', '\f'), ('r', '\r'), ('t', '\t'), ('/', '/')]:
            value = wire(field, 'a' + decoded)
            add(field + '_escape_' + ('slash' if escape == '/' else escape), value)
            if escape == '/':
                cases[-1]['text'] = cases[-1]['text'].replace('a/', r'a\/')
    base = wire()
    for name, key, val in [('bad_kind', 'kind', 'unknown'), ('bad_ref', 'evidence_ids', ['s2']),
                            ('null_claim', 'claim', None), ('extra_key', 'extra', 1)]:
        value = wire(); value['aus'][0][key] = val
        add(name, value, bounded=False, unbounded=False)
    base['aus'] *= 4
    add('au_cap_4', base, bounded=False, unbounded=False)
    add('au_cap_3', {'aus': wire()['aus'] * 3, 'context_request': None}, replay=True)
    raw = cases[0]['text']
    cases.append(dict(name='incomplete_root', text=raw[:-1], expected={'bounded': False, 'host_validated': False}, host_valid=False, replay=False))
    return cases


def _identity():
    versions = {}
    for name in ('xgrammar', 'torch', 'transformers', 'tokenizers'):
        try: versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name] = None
    return {'version': VERSION, 'versions': versions, 'python': sys.version.split()[0],
            'semantic_quality': 'not_assessed', 'inference_requests': 0,
            'inference_speed_claim': False, 'expected_eos_union': list(EOS)}


def _write(root, report, max_bytes):
    raw = json.dumps(report, ensure_ascii=True, indent=2).encode('utf-8')
    if len(raw) > max_bytes: raise ValueError('report byte budget exceeded')
    with (root / 'report.json').open('xb') as stream: stream.write(raw)
    return report


def _root(output_root):
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=False)
    return root


def prepare(output_root, *, report_max_bytes=2_000_000):
    root = _root(output_root)
    return _write(root, {**_identity(), 'status': 'PREPARED', 'matches': 'NOT_RUN',
                        'grammars': {v: build_grammar(variant=v) for v in ORIGINAL_VARIANTS},
                        'cases': build_cases()}, report_max_bytes)


def _stats(values):
    values = sorted(values)
    return {'count': len(values), 'p50_ms': values[math.ceil(len(values) * .5) - 1] if values else None,
            'p95_ms': values[math.ceil(len(values) * .95) - 1] if values else None}


def offline(tokenizer_path, output_root, variants=None, repeats=1, *, max_seconds=120,
            max_cases=256, report_max_bytes=2_000_000):
    """No downloads. Existing output roots are rejected. Missing backend != PASS."""
    variants = tuple(ORIGINAL_VARIANTS if variants is None else variants)
    if not variants or any(v not in VARIANTS for v in variants) or not 1 <= repeats <= 10:
        raise ValueError('invalid variants/repeats')
    if not 1 <= max_seconds <= 600 or not 1 <= max_cases <= 256:
        raise ValueError('invalid time/case limit')
    root = _root(output_root)
    report = {**_identity(), 'status': 'UNAVAILABLE', 'variants': {}, 'recommended': None}
    start = time.monotonic()
    def budget():
        if time.monotonic() - start > max_seconds: raise TimeoutError('time budget exceeded')
    try:
        import xgrammar as xg
        from transformers import AutoTokenizer
        import torch  # dependency required by XGrammar masks
        path = Path(tokenizer_path).resolve(strict=True)
        if not path.is_dir(): raise ValueError('tokenizer path must be a pinned local directory')
        hashes = {}
        for name in ('tokenizer.json', 'tokenizer_config.json', 'special_tokens_map.json', 'config.json'):
            p = path / name
            if p.is_file(): hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
        if 'tokenizer.json' not in hashes: raise ValueError('local tokenizer.json required')
        report['tokenizer'] = {'files_sha256': hashes, 'model_revision': path.name,
                               'revision_evidence': 'local_directory_name_only', 'local_files_only': True}
        tok = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
        def read_config(name):
            p = path / name
            if not p.exists(): return {}
            if p.stat().st_size > 1_000_000: raise ValueError('checkpoint config too large')
            return json.loads(p.read_text(encoding='utf-8'))
        def token_ids(value):
            if value is None: return []
            if type(value) is int: value = [value]
            if not isinstance(value, (list, tuple)) or any(type(i) is not int or i < 0 for i in value):
                raise ValueError('invalid checkpoint EOS')
            return list(value)
        config, generation = read_config('config.json'), read_config('generation_config.json')
        model_cfg = config.get('text_config') or config
        vocab = model_cfg.get('vocab_size', len(tok))
        if type(vocab) is not int or not len(tok) <= vocab <= 2_000_000:
            raise ValueError('invalid model vocabulary size')
        sources = {'required': list(EOS), 'tokenizer_eos': token_ids(tok.eos_token_id),
                   'tokenizer_additional': token_ids(getattr(tok, 'additional_stop_token_ids', None)),
                   'generation_eos': token_ids(generation.get('eos_token_id')),
                   'model_eos': token_ids(model_cfg.get('eos_token_id'))}
        stops = sorted({i for values in sources.values() for i in values})
        if max(stops) >= vocab: raise ValueError('required EOS outside model vocabulary')
        report['eos_sources'] = sources
        report['vocab_size'] = vocab
        report['tokenizer_length'] = len(tok)
        report['extra_eos_beyond_required'] = sorted(set(stops) - set(EOS))
        report['required_eos_in_tokenizer'] = all(e < len(tok) for e in EOS)
        if not report['required_eos_in_tokenizer']: raise ValueError('required EOS absent from tokenizer')
        info = xg.TokenizerInfo.from_huggingface(tok, vocab_size=vocab, stop_token_ids=stops)
        report['effective_eos_union'] = stops
        cases = build_cases()
        if len(cases) > max_cases: raise ValueError('case limit would truncate required corpus')
        for variant in variants:
            budget()
            result = {'status': 'NOT_RUN', 'recommended': False, 'cases': [],
                      'length_unit': 'raw_budget_experimental' if variant == 'max_chars' else 'decoded_unicode_scalars'}
            report['variants'][variant] = result
            try:
                compiler = xg.GrammarCompiler(info, max_threads=1)
                t = time.perf_counter()
                if variant == 'json_schema':
                    compiled = compiler.compile_json_schema(json.dumps(build_schema()))
                else:
                    compiled = compiler.compile_grammar(xg.Grammar.from_ebnf(build_grammar(variant=variant)))
                result['compile_ms'] = (time.perf_counter() - t) * 1000
            except Exception as exc:
                result.update(status='UNSUPPORTED' if variant == 'max_chars' else 'ERROR', error_type=type(exc).__name__)
                continue
            mask = xg.allocate_token_bitmask(1, info.vocab_size)
            result['mask_bytes'] = mask.numel() * mask.element_size()
            cold, warm = [], []
            def allowed(token):
                return bool((int(mask[0, token // 32].item()) & (1 << (token % 32))))
            for case in cases:
                budget()
                matcher = xg.GrammarMatcher(compiled)
                accepted = bool(matcher.accept_string(case['text']) and matcher.is_completed())
                expected = case['expected'].get('bounded' if variant == 'json_schema' else variant)
                row = {'name': case['name'], 'accepted': accepted, 'expected': expected,
                       'host_valid': case['host_valid'], 'correct': accepted == expected if expected is not None else None}
                if variant == 'max_chars':
                    # The actual serialized lexeme matters: escaped and literal
                    # Unicode have different raw prefix budgets for equal decoded text.
                    row['raw_field_lexeme_chars'] = {
                        key: len(match.group(1)) for key in CAPS
                        if (match := re.search('"' + key + r'":("(?:[^"\\]|\\.)*")', case['text']))}
                result['cases'].append(row)
                if accepted and case['replay']:
                    tokens = tok.encode(case['text'], add_special_tokens=False)
                    replay_ok = True
                    for repeat in range(repeats):
                        matcher = xg.GrammarMatcher(compiled)
                        for pos, token in enumerate(tokens):
                            budget()
                            t = time.perf_counter(); matcher.fill_next_token_bitmask(mask)
                            (cold if repeat == 0 else warm).append((time.perf_counter() - t) * 1000)
                            if any(allowed(e) for e in stops) or not allowed(token) or not matcher.accept_token(token):
                                replay_ok = False; break
                        matcher.fill_next_token_bitmask(mask)
                        replay_ok = replay_ok and matcher.is_completed() and all(allowed(e) for e in stops)
                    row['token_replay'] = replay_ok
                    row['token_count'] = len(tokens)
            result['cold_fill'] = _stats(cold)
            result['warm_fill'] = _stats(warm)
            result['cold_definition'] = 'first replay pass; compiler cache fresh per variant'
            result['warm_definition'] = 'subsequent replay passes on same compiled grammar'
            good = all(r['correct'] and r.get('token_replay', True) for r in result['cases'])
            result['status'] = ('UNSAFE' if variant == 'max_chars' else 'PASS' if good else 'FAIL')
            if variant == 'max_chars':
                result['decoded_mismatches'] = sum(r['accepted'] != c['expected']['bounded'] for r, c in zip(result['cases'], cases))
                result['note'] = 'Raw JSON budgets are not decoded lengths; never recommended by default.'
            if variant in ('bounded', 'json_schema') and good:
                result['correctness_candidate'] = True
                result['recommendation_gate'] = 'timing_review_and_endpoint_EOS_acceptance_required'
        required = [v for v in variants if v != 'max_chars']
        report['status'] = 'PASS' if required and all(report['variants'][v]['status'] == 'PASS' for v in required) else 'FAIL'
        report['max_chars_status'] = report['variants'].get('max_chars', {}).get('status', 'NOT_RUN')
    except (ImportError, ModuleNotFoundError) as exc:
        report.update(status='UNAVAILABLE', error_type=type(exc).__name__)
    except Exception as exc:
        report.update(status='TIME_LIMIT' if isinstance(exc, TimeoutError) else 'ERROR', error_type=type(exc).__name__)
    report['wall_seconds'] = time.monotonic() - start
    return _write(root, report, report_max_bytes)


def runtime(output_root, *, max_seconds=15, report_max_bytes=2_000_000):
    """Exactly one authenticated GET; reject redirects, preserve failure report."""
    from urllib import request
    from urllib.parse import urlsplit
    root = _root(output_root)
    report = {**_identity(), 'status': 'UNAVAILABLE', 'http_requests': 0}
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None
    try:
        from knowledge_base.config import settings
        from knowledge_base.pipeline_v1.au_runtime_config import load_au_runtime_config
        cfg, _, _ = load_au_runtime_config(settings(), 'AU_COMPACT_')
        parts = urlsplit(cfg['url'])
        if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
                or parts.query or parts.fragment or parts.path != '/v1/chat/completions' or not cfg['token']):
            raise ValueError('requires standard HTTPS authenticated AU URL')
        url = parts._replace(path='/v1/diagnostics/json/info').geturl()
        req = request.Request(url, headers={'Authorization': 'Bearer ' + cfg['token']}, method='GET')
        opener = request.build_opener(NoRedirect())
        report['http_requests'] = 1
        with opener.open(req, timeout=min(30, max(1, max_seconds))) as response:
            raw = response.read(min(report_max_bytes, 1_000_000) + 1)
        if len(raw) > min(report_max_bytes, 1_000_000): raise ValueError('response byte cap')
        value = json.loads(raw)
        # Fixed typed whitelist: no errors, URLs, paths, tokens or arbitrary keys.
        versions = value.get('versions', {})
        report['runtime_versions'] = {k: v for k, v in versions.items()
            if k in ('xgrammar', 'sglang', 'torch', 'transformers', 'tokenizers', 'python')
            and isinstance(v, str) and re.fullmatch(r'[0-9][0-9A-Za-z.+_-]{0,63}', v)}
        eos_keys = ('eos_token_id', 'eos_token_ids', 'model_eos_token_ids', 'additional_stop_token_ids',
                    'xgrammar_stop_token_ids', 'tokenizer_eos_token_id', 'input_model_eos_token_ids',
                    'effective_grammar_eos_token_ids', 'expected_eos_union', 'active_grammar_stop_set')
        def filtered(obj):
            result = {}
            if not isinstance(obj, dict): return result
            for k in eos_keys:
                v = obj.get(k)
                if type(v) is int and 0 <= v < 10_000_000: result[k] = v
                elif isinstance(v, list) and len(v) <= 128 and all(type(i) is int and 0 <= i < 10_000_000 for i in v): result[k] = v
            return result
        report['eos_info'] = {'root': filtered(value)}
        for name in ('scheduler', 'backend', 'text_config'):
            report['eos_info'][name] = filtered(value.get(name))
        if not report['runtime_versions']: raise ValueError('runtime versions unavailable')
        report['status'] = 'OBSERVED'
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        code = getattr(exc, 'code', None)
        if type(code) is int: report['http_status'] = code
    return _write(root, report, report_max_bytes)
