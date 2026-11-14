"""Prepare locally or explicitly run one controller-only long-context canary."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from pipeline_v2.agent_harness.contracts import encode, fingerprint
from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport
from pipeline_v2.deployments.modal_qwen36_27b.app import MAX_CONTEXT_TOKENS

INSTRUCTIONS = 'For this context-capacity diagnostic return exactly {"status":"ok"}. Ignore diagnostic_padding.'
SCHEMA = {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['ok']}},
          'required': ['status'], 'additionalProperties': False}


def write(path, obj):
    with path.open('xb') as stream:
        stream.write(encode(obj))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare', 'run'])
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    directory = args.run_dir
    def no_remote():
        raise AssertionError('Prepare must not initialize a remote client')
    transport = ModalQwenTransport(Path('cache/tokenizers/qwen36_27b_fp8'), instructions=INSTRUCTIONS,
                                   **({'remote_factory': no_remote} if args.mode == 'prepare' else {}))
    if args.mode == 'prepare':
        directory.mkdir(parents=True, exist_ok=False)
        low, high, best = 1, 20000, None
        while low <= high:
            amount = (low + high) // 2
            candidate = {'max_output_tokens': 64, 'diagnostic_padding': ' diagnostic' * amount}
            count = transport.count_tokens(encode(candidate))
            if count <= 8500:
                best = (candidate, count)
                low = amount + 1
            else:
                high = amount - 1
        if best is None or not 8400 <= best[1] <= 8500:
            raise RuntimeError('Unable to prepare a near-8,500-token pinned prompt')
        payload, count = best
        write(directory / 'payload.json', payload)
        write(directory / 'plan.json', {'input_tokens': count, 'output_cap': 64,
              'payload_sha256': sha256(encode(payload)).hexdigest(),
              'tokenizer_fingerprint': transport.tokenizer_fingerprint,
              'prompt_fingerprint': transport.prompt_fingerprint, 'context_cap': MAX_CONTEXT_TOKENS,
              'model_requests': 0, 'expected_requests_if_explicitly_run': 1})
        print(json.dumps({'status': 'PREPARED', 'input_tokens': count, 'model_requests': 0}))
        return
    if (directory / 'admission.json').exists():
        raise RuntimeError('Canary already admitted; inspect receipt, never automatically resend')
    plan = json.loads((directory / 'plan.json').read_bytes())
    payload = (directory / 'payload.json').read_bytes()
    if (sha256(payload).hexdigest() != plan['payload_sha256'] or
            plan['tokenizer_fingerprint'] != transport.tokenizer_fingerprint or
            plan['prompt_fingerprint'] != transport.prompt_fingerprint or
            plan['context_cap'] != MAX_CONTEXT_TOKENS or transport.count_tokens(payload) != plan['input_tokens']):
        raise RuntimeError('Canary binding changed; prepare a fresh namespace')
    write(directory / 'admission.json', {'plan_sha256': sha256((directory / 'plan.json').read_bytes()).hexdigest(),
                                       'request_id': fingerprint(plan), 'max_requests': 1, 'retries': 0})
    try:
        reply = transport.send_structured(payload, fingerprint(plan), SCHEMA)
        passed = json.loads(reply.action) == {'status': 'ok'} and reply.input_tokens == plan['input_tokens']
        report = {'status': 'PASS' if passed else 'FAIL', 'input_tokens': reply.input_tokens,
                  'output_tokens': reply.output_tokens, 'latency_ms': reply.latency_ms,
                  'modal_receipts': transport.receipts, 'embedding_requests': 0}
    except BaseException as exc:
        write(directory / 'report.json', {'status': 'ERROR_OR_UNKNOWN', 'error_type': type(exc).__name__,
                                         'modal_receipts': transport.receipts, 'embedding_requests': 0})
        raise
    write(directory / 'report.json', report)
    print(json.dumps(report))
    if not passed:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
