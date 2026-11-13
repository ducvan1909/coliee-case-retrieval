"""Prepare the discovery pilot without reading labels or sending model requests."""

import argparse
import json
from pathlib import Path

from pipeline_v2.agent_harness.contracts import HarnessError, encode
from pipeline_v2.deployments.modal_qwen36_27b.app import MAX_CONTEXT_TOKENS
from pipeline_v2.m6_live import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path.cwd()
    manifest = json.loads(Path(__file__).with_name('manifest.json').read_bytes())
    cohort = json.loads((root / manifest['cohort']).read_bytes())
    queries = manifest['queries']
    if queries != cohort['discovery_queries'][:3] or set(queries) & set(cohort['holdout_queries']):
        raise HarnessError('Pilot queries differ from the frozen discovery prefix')
    profile = manifest['profile']
    budget = profile['budget']
    if budget['max_payload_tokens'] + budget['max_output_tokens'] > MAX_CONTEXT_TOKENS:
        raise HarnessError('Pilot budget exceeds the deployed context limit')
    args.runs_dir.mkdir(parents=True, exist_ok=False)
    summary = {}
    for query in queries:
        plan = prepare(root, args.runs_dir / query, {**profile, 'query_id': query})
        summary[query] = {'status': plan['preflight_status'], 'input_tokens': plan['first_payload_input_tokens']}
        print(query, summary[query], flush=True)
    (args.runs_dir / 'preflight_summary.json').write_bytes(encode(summary))
    return 0 if all(row['status'] == 'ready' for row in summary.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
