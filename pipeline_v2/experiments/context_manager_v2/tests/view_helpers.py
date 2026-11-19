"""Inspect host bindings separately from the compact model-facing view."""
from copy import deepcopy


def canonical_ref(prepared, ref):
    return prepared['manifest'].get('wire_aliases', {}).get(ref, ref)


def wire_ref(prepared, ref):
    return next((key for key, value in prepared['manifest'].get('wire_aliases', {}).items() if value == ref), ref)


def host_payload(prepared):
    payload = deepcopy(prepared['payload'])
    manifest = prepared['manifest']
    payload['m6'] = deepcopy(manifest['dispatch_m6'])
    payload['excerpts'] = deepcopy(manifest['excerpts'])
    payload['current_payload_source_refs'] = [row['ref'] for row in payload['excerpts']]
    query = next((row for row in payload['excerpts'] if row['case_id'] == payload['query_id']), None)
    if query:
        payload['query_source_hash'] = query['source_hash']
    return payload
