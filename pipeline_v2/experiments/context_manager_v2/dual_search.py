"""CM4 two-view case fusion followed by passage-level reranking."""

from copy import deepcopy
from hashlib import sha256
from math import isfinite

from pipeline_v2.agent_harness import ToolResult
from pipeline_v2.agent_harness.contracts import HarnessError, fingerprint
from pipeline_v2.full_search.hybrid import RRF_K
from pipeline_v2.runtime_timing import measure


def _source_text(raw, span):
    if (not isinstance(span, (tuple, list)) or len(span) != 2
            or any(type(value) is not int for value in span)
            or not 0 <= span[0] < span[1] <= len(raw)):
        raise HarnessError('CM4 retrieval expects a bounded canonical source span')
    text = raw[span[0]:span[1]].decode('utf-8')
    if not text.strip():
        raise HarnessError('CM4 retrieval received an empty source span')
    return text


class DualSearch:
    def __init__(self, rerank, *, fallback=None, review_limit=10, pool_limit=50):
        if (type(review_limit) is not int or review_limit < 1
                or type(pool_limit) is not int or not 1 <= pool_limit <= 50):
            raise HarnessError('Invalid CM4 reranking limits')
        self.rerank = rerank
        self.fallback = fallback
        self.review_limit = review_limit
        self.pool_limit = pool_limit

    def __call__(self, action, execute_branch, raw_reader):
        args = action['args']
        need = args['_m6_need']
        anchor = need['a_anchor']
        source = need['a_sources'][0]
        query_case = source['case_id']
        query_raw = raw_reader(query_case)
        if sha256(query_raw).hexdigest() != source['source_hash']:
            raise HarnessError('CM4 retrieval anchor source changed')
        query = _source_text(query_raw, anchor['span_bytes'])
        rerank_query = query
        if ('text' in anchor and anchor['text'] != query) or (
                'span_bytes' in source and list(source['span_bytes']) != list(anchor['span_bytes'])):
            raise HarnessError('CM4 retrieval anchor differs from the approved source')

        rankings = {}
        branch_records = {}
        if need.get('source_bound'):
            expected = need.get('source_query_text')
            if (not isinstance(expected,str) or args['text'] != expected
                    or sha256(expected.encode('utf-8')).hexdigest() != need.get('source_query_sha256')):
                raise HarnessError('Source-bound retrieval text differs from its locked query')
            citations=[]
            for support in need.get('a_supports',[]):
                if support['source_hash'] != source['source_hash'] or support['case_id'] != query_case:
                    raise HarnessError('Source-bound support belongs to another source')
                text = _source_text(query_raw,support['span_bytes'])
                if text != support['text']:
                    raise HarnessError('Source-bound support text differs from canonical source')
                if support['role'] in ('citation', 'group_member') and text not in query:
                    citations.append(text)
            if expected != '\n'.join([query,*dict.fromkeys(citations)]):
                raise HarnessError('Source-bound query is not the canonical proposition and scoped citation')
            branches=(('source',expected),)
            rerank_query = expected
        else:
            branches=(('issue',args['text']),('verbatim',query))
        for name, text in branches:
            if name == 'verbatim' and text == args['text']:
                branch_records[name] = {'reused_branch': 'issue'}
                continue
            branch_action = deepcopy(action)
            branch_action['args']['text'] = text
            with measure('retrieval_branch'):
                observation = execute_branch(branch_action).observation
            rows = observation['hits']
            ids = [row['case_id'] for row in rows]
            if query_case in ids or len(ids) != len(set(ids)):
                raise HarnessError('CM4 branch must return distinct candidate cases')
            rankings[name] = {row['case_id']: (rank, row) for rank, row in enumerate(rows, 1)}
            branch_records[name] = {'request_id': observation.get('request_id'),
                                    'action_id': observation.get('cm4_branch_action_id'),
                                    'query_sha256': sha256(text.encode('utf-8')).hexdigest(),
                                    'source_span_bytes': list(anchor['span_bytes']),
                                    'cases': ids, 'timings': observation.get('timings', {})}

        case_scores = {}
        for ranking in rankings.values():
            for case, (rank, _) in ranking.items():
                case_scores[case] = case_scores.get(case, 0.0) + 1 / (RRF_K + rank)
        case_order = sorted(case_scores, key=lambda case: (-case_scores[case], case))
        passages, documents, missing = [], [], []
        for case_rank, case in enumerate(case_order[:self.pool_limit], 1):
            leads = {}
            for branch, ranking in rankings.items():
                if case not in ranking:
                    continue
                row = ranking[case][1]
                for channel, lead in (row.get('channels') or {'representative': row}).items():
                    _add_lead(leads, case, lead, branch, channel)
            if not leads and self.fallback is not None:
                for lead in self.fallback(case, query):
                    _add_lead(leads, case, lead, 'case_local', 'passage_bm25')
            if not leads:
                missing.append(case)
                continue
            raw = raw_reader(case)
            digest = sha256(raw).hexdigest()
            for row in leads.values():
                if row['source_hash'] != digest:
                    raise HarnessError('CM4 reranker candidate source changed')
                text = _source_text(raw, row['span_bytes'])
                preview = text[:320]
                start = row['span_bytes'][0]
                row.update(case_rank=case_rank, preview={
                    'text': preview, 'span_bytes': [start, start + len(preview.encode('utf-8'))],
                    'text_sha256': sha256(preview.encode('utf-8')).hexdigest()})
                passages.append(row)
                documents.append(text)

        with measure('reranker_client'):
            scores = list(self.rerank(rerank_query, documents)) if passages else []
        if (len(scores) != len(passages) or any(type(score) not in (float, int)
                                                or not isfinite(score) for score in scores)):
            raise HarnessError('CM4 reranker returned invalid scores')
        for passage, score in zip(passages, scores):
            passage['score'] = score
        passages.sort(key=lambda row: (-row['score'], row['case_rank'], row['hit_ref']))
        hits = [{**row, 'rank': rank} for rank, row in enumerate(passages[:self.review_limit], 1)]
        return ToolResult({
            'cm4_passage_review': True, 'm6_source_need': need, 'query_case': query_case,
            'hits': hits, 'dual_retrieval': {'branches': branch_records, 'case_union': case_order,
                'case_rrf': case_scores, 'rerank_pool': case_order[:self.pool_limit],
                'missing_passage': missing, 'scored_passages': [
                    {key: value for key, value in row.items() if key != 'preview'} for row in passages]},
        }, candidates=tuple(dict.fromkeys(row['case_id'] for row in hits)))


def _add_lead(leads, case, lead, branch, channel):
    open_ref = lead.get('open_ref')
    span = lead.get('span_bytes')
    if not open_ref or not span:
        return
    digest = lead.get('source_hash', open_ref.get('source_hash'))
    if lead.get('case_id', case) != case or open_ref.get('case_id') != case or open_ref.get('source_hash') != digest:
        raise HarnessError('CM4 passage lead is bound to a different source')
    hit_ref = fingerprint([case, digest, span])
    row = leads.setdefault(hit_ref, {'hit_ref': hit_ref, 'case_id': case, 'source_hash': digest,
                                   'span_bytes': list(span), 'open_ref': deepcopy(open_ref), 'origins': []})
    row['origins'].append({'branch': branch, 'channel': channel, 'rank': lead.get('rank'),
                           'score': lead.get('score'), 'open_ref': deepcopy(open_ref)})
