"""Local verification of the exact source-only 32/64 presentation manifest."""
from __future__ import annotations

import copy
import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from ..au_context_paired.build import fingerprint, read_json, render_request
from ..au_context_paired.preflight import validate_workload
from ..au_compact.prompting import build_prompt

DEFAULT_MANIFEST = Path('knowledge_base/pipeline_v1/outputs/au_method_audit_20261014/presentation_preflight_v1/presentation_manifest.json')
DEFAULT_PARENT = Path('knowledge_base/pipeline_v1/outputs/au_context_paired/pilot_20261014_084923_recovered_v1/workload.json')
FROZEN_SHA256 = '36165a29324300bb5fbd80c34c694fa112ca94cd636f9acc85ad13e75eb6f526'
BUDGET = {'max_requests': 64, 'max_provider_attempts': 100,
          'max_total_input_tokens': 800000, 'max_total_output_tokens': 80000}
STRATEGY = 'GET /health ready (bounded 600s); existing stable grammar evidence; no warmup/probe POST'


class PresentationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PresentationError(message)


def code_hash():
    return fingerprint({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in sorted(Path(__file__).parent.glob('*.py'))})


def profile(parent, cfg):
    identity = parent['identity']
    keys = ('model', 'url', 'enable_thinking', 'transport', 'string_decoder')
    require(all(cfg.get(k) == identity.get(k) for k in keys), 'parent runtime identity mismatch')
    require(cfg.get('model') == 'Qwen/Qwen3.5-9B' and cfg.get('enable_thinking') is False
            and cfg.get('transport') == 'jobs' and cfg.get('string_decoder') == 'host_validated',
            'requires 9B, thinking=false, jobs, host_validated')
    expected_jobs = identity['url'].removesuffix('/chat/completions') + '/jobs'
    require(cfg.get('jobs_url', '').rstrip('/') == expected_jobs, 'parent jobs URL mismatch')
    for url in (cfg['url'], cfg['jobs_url']):
        parts = urlsplit(url)
        require(parts.scheme == 'https' and parts.netloc and not
                (parts.username or parts.password or parts.query or parts.fragment), 'unsafe endpoint URL')
    require(cfg.get('expected_model_revision') in (None, identity['expected_model_revision']),
            'parent revision mismatch')
    return {**{k: cfg[k] for k in keys}, 'jobs_url': expected_jobs,
            'expected_model_revision': identity['expected_model_revision'],
            'endpoint_verification': 'historical_parent_operator_verification; no_live_check',
            'runtime_revision_setting_present': cfg.get('expected_model_revision') is not None,
            **{k: cfg.get(k) for k in ('timeout', 'job_wait_seconds', 'job_poll_seconds')}}


class RoundTrip(HTMLParser):
    """Parse source and ownership separately from visual markup."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.atom = self.part = self.cue = None
        self.buf, self.partbuf, self.cuebuf = [], [], []
        self.atoms, self.roles, self.cues, self.order, self.groups = {}, [], [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        require(tag in {'au_compact_region', 'target', 'context', 'target_body', 'context_padding',
                        'target_set', 'context_set', 'source_cue', 'quote_delimiter'}, 'unknown rendering tag')
        if tag in ('target_set', 'context_set'):
            self.groups.append(tag)
        if tag in ('target', 'context'):
            require(self.atom is None, 'nested source atom')
            self.atom = (a['atom_id'], tag, a['span']); self.buf = []
        if tag in ('target_body', 'context_padding'):
            require(self.part is None and self.atom is not None, 'invalid role nesting')
            self.part = (tag, a['span']); self.partbuf = []
        if tag in ('source_cue', 'quote_delimiter'):
            require(self.cue is None and self.atom is not None, 'invalid cue nesting')
            self.cue = (tag, a['span']); self.cuebuf = []

    def handle_data(self, data):
        if self.atom: self.buf.append(data)
        if self.part: self.partbuf.append(data)
        if self.cue: self.cuebuf.append(data)

    def handle_endtag(self, tag):
        if tag in ('source_cue', 'quote_delimiter'):
            require(self.cue is not None and self.cue[0] == tag, 'cue closing mismatch')
            self.cues.append((*self.cue, ''.join(self.cuebuf))); self.cue = None
        if tag in ('target_body', 'context_padding'):
            require(self.part is not None and self.part[0] == tag, 'role closing mismatch')
            self.roles.append((*self.part, ''.join(self.partbuf))); self.part = None
        if tag in ('target', 'context'):
            require(self.atom is not None, 'missing source atom')
            aid, role, span = self.atom
            text = ''.join(self.buf)
            require(role == tag and aid not in self.atoms and text.startswith('\n') and text.endswith('\n'),
                    'duplicate/invalid source atom')
            self.atoms[aid] = (role, span, text[1:-1]); self.order.append(aid); self.atom = None


def verify_render(text, catalog, cue_pattern):
    parser = RoundTrip(); parser.feed(text); parser.close()
    require(parser.atom is None and parser.part is None and parser.cue is None, 'incomplete render')
    require(set(parser.atoms) == set(catalog['atoms']), 'render catalog IDs mismatch')
    for aid, atom in catalog['atoms'].items():
        require(parser.atoms[aid] == ('target' if atom['target_intersecting'] else 'context',
                f"{atom['start_char']}:{atom['end_char']}", atom['quote']), 'source roundtrip mismatch')
    for tag, span, quote in parser.cues:
        start, end = map(int, span.split(':'))
        require(end - start == len(quote) and any(a['start_char'] <= start < end <= a['end_char']
                and a['quote'][start-a['start_char']:end-a['start_char']] == quote
                for a in catalog['atoms'].values()), 'cue source offsets mismatch')
        require(bool(re.fullmatch(cue_pattern, quote)) if tag == 'source_cue' else quote in ('"', '“', '”'),
                'cue not literal source rule')
    return parser


def validate_manifest(manifest, parent, cfg=None):
    m = copy.deepcopy(manifest); digest = m.pop('manifest_sha256', None)
    require(digest == fingerprint(m) == FROZEN_SHA256, 'exact frozen manifest hash mismatch')
    validate_workload(parent, cfg=cfg)
    require(m['parent_workload_sha256'] == parent['workload_sha256'], 'parent workload mismatch')
    require(m['model'] == parent['identity']['model'] and m['model_revision'] == parent['identity']['expected_model_revision'],
            'model/revision mismatch')
    require(m['source_store'] == parent['source_store'] and m['atom_root'] == parent['atom_root'], 'source roots mismatch')
    require(m['target_count'] == 32 and m['potential_requests'] == 64 and len(m['rows']) == 32, 'requires full32/64')
    originals = {r['request_id']: r for r in parent['manifest']['requests']}
    pairs = {p['pair_id']: p for p in parent['pairs']}
    ids, seen_pairs, jobs = set(), set(), set()
    prompt_bytes = 0
    for row in m['rows']:
        require(row['pair_id'] not in seen_pairs and row['pair_id'] in pairs, 'duplicate/foreign pair')
        seen_pairs.add(row['pair_id']); pair = pairs[row['pair_id']]
        require(row['case_id'] == pair['case_id'] and row['target'] == pair['target'], 'target changed')
        require(sorted(row['variant_order']) == ['P0', 'P1'], 'invalid arm order')
        require([v['arm'] for v in row['variants']] == ['P0', 'P1'], 'invalid variants')
        parsed = []
        grammars = []
        for v in row['variants']:
            q, payload = v['request'], v['payload']
            require(q['request_id'] not in ids, 'duplicate request'); ids.add(q['request_id'])
            original = copy.deepcopy(originals[pair['request_ids']['G']]); original['request_id'] = q['request_id']
            require(q == original, 'request differs from original G except ID')
            rendered = render_request(q, m['source_store'], m['atom_root'])
            catalog = rendered['catalog']
            require(v['catalog_sha256'] == fingerprint(catalog['atoms']), 'catalog hash mismatch')
            require(v['source_chars'] == sum(len(a['quote']) for a in catalog['atoms'].values()), 'source chars changed')
            require(v['payload_sha256'] == fingerprint(payload) and v['payload_sha256'] not in jobs, 'payload hash/uniqueness mismatch')
            jobs.add(v['payload_sha256'])
            expected = {'model': m['model'], 'messages': [{'role': 'user', 'content': build_prompt(q, v['rendered']) + m['common_legend']}],
                        'temperature': 0, 'max_tokens': 800, **rendered['decoding'],
                        'chat_template_kwargs': {'enable_thinking': False}}
            require(payload == expected and bool(payload.get('ebnf')), 'frozen prompt/grammar/model/cap mismatch')
            inp = sum(len(x['content'].encode('utf-8')) for x in payload['messages'])
            require(inp == v['input_reservation_utf8_bytes'] and v['output_reservation_tokens'] == 800, 'reservation mismatch')
            prompt_bytes += inp
            if v['arm'] == 'P0': require(v['rendered'] == rendered['rendered'], 'P0 renderer changed')
            p = verify_render(v['rendered'], catalog, m['cue_pattern']); parsed.append(p)
            atoms = sorted(catalog['atoms'].values(), key=lambda a: (a['start_char'], a['end_char'], a['atom_id']))
            if v['arm'] == 'P1':
                require(p.groups == ['target_set', 'context_set'], 'P1 grouping mismatch')
                atoms = [a for a in atoms if a['target_intersecting']] + [a for a in atoms if not a['target_intersecting']]
            require(p.order == [a['atom_id'] for a in atoms], 'source ordering mismatch')
            grammars.append(payload['ebnf'].replace(q['request_id'], 'paired-canonical-request'))
        require(parsed[0].atoms == parsed[1].atoms and sorted(parsed[0].roles) == sorted(parsed[1].roles), 'paired source/roles mismatch')
        require(grammars[0] == grammars[1], 'paired grammar differs except request ID')
    require(seen_pairs == set(pairs) and len(ids) == len(jobs) == 64 and prompt_bytes == 585718, 'full frozen workload mismatch')
    require(prompt_bytes <= BUDGET['max_total_input_tokens'] and 64*800 <= BUDGET['max_total_output_tokens'], 'budget exceeded')
    return prompt_bytes


def preflight(manifest, *, parent=None, cfg=None):
    m = read_json(manifest) if isinstance(manifest, (str, Path)) else manifest
    p = read_json(parent or DEFAULT_PARENT) if not isinstance(parent, dict) else parent
    inp = validate_manifest(m, p, cfg)
    run_profile = profile(p, cfg) if cfg is not None else None
    return {'artifact_type': 'AUPresentationPairedPreflight', 'status': 'pass', 'network_requests': 0,
            'manifest_sha256': m['manifest_sha256'], 'workload_sha256': m['manifest_sha256'],
            'parent_workload_sha256': p['workload_sha256'], 'target_count': 32, 'unique_requests': 64,
            'prompt_reservation_utf8_bytes': inp, 'output_reservation_tokens': 51200,
            'budget': BUDGET, 'code_sha256': code_hash(), 'run_profile': run_profile,
            'readiness_strategy': STRATEGY, 'semantic_quality': 'not_assessed',
            'input_estimate_method': 'full_prompt_utf8_bytes; not provider tokens'}
