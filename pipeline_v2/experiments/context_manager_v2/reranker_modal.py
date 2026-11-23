"""Pinned CM4 reranker client with a durable receipt per exact batch."""

import json
from math import isfinite
from pathlib import Path
from time import perf_counter

from pipeline_v2.agent_harness.contracts import HarnessError, TransportError, fingerprint
from pipeline_v2.experiments.context_manager_v1.core import write_once
from .reranker_protocol import APP_NAME, BATCH_SIZE, INSTRUCTION, MAX_TOKENS, MODEL, REVISION


class ModalReranker:
    def __init__(self, directory, function_id):
        self.directory = Path(directory)
        self.function_id = function_id
        self.method = None

    def __call__(self, query, documents):
        import modal
        from pipeline_v2.agent_harness.modal_qwen import ModalQwenTransport

        request = fingerprint([APP_NAME, MODEL, REVISION, INSTRUCTION, MAX_TOKENS, BATCH_SIZE,
                               self.function_id, query, documents])
        root = self.directory / request
        result_path = root / 'result.json'
        if result_path.exists():
            result = json.loads(result_path.read_bytes())
            self._validate(result, request, len(documents))
            return result['scores']
        if (root / 'admission.json').exists():
            raise HarnessError('CM4 reranker request already admitted without a usable receipt')
        if self.method is None:
            method = modal.Cls.from_name(APP_NAME, 'Reranker')().score.hydrate()
            if method.object_id != self.function_id:
                raise HarnessError('CM4 reranker Modal function does not match the prepared ID')
            self.method = method
        write_once(root / 'admission.json', {'request_id': request, 'function_id': self.function_id,
                                           'model': MODEL, 'revision': REVISION, 'pair_count': len(documents)})
        started = perf_counter()
        receipt = {'request_id': request, 'call_id': None}
        try:
            call = self.method.spawn(request, query, documents)
            receipt['call_id'] = call.object_id
            write_once(root / 'submission.json', receipt)
            result = ModalQwenTransport._wait_for_result(call, receipt, component='modal_reranker')
            self._validate(result, request, len(documents))
            write_once(result_path, {**result, **receipt, 'elapsed_seconds': perf_counter() - started})
        except Exception as exc:
            unknown = exc.unknown if isinstance(exc, TransportError) else True
            write_once(root / 'failure.json', {**receipt, 'error_type': type(exc).__name__, 'unknown': unknown,
                                               'elapsed_seconds': perf_counter() - started})
            raise
        return result['scores']

    def usage(self):
        results = [json.loads(path.read_bytes()) for path in self.directory.glob('*/result.json')]
        failures = [json.loads(path.read_bytes()) for path in self.directory.glob('*/failure.json')]
        admitted = sum(1 for _ in self.directory.glob('*/admission.json'))
        return {'admitted': admitted, 'completed': len(results), 'failed': len(failures),
                'unaccounted_admissions': admitted - len(results),
                'known_input_tokens': sum(sum(row['pair_tokens']) for row in results),
                'known_padded_input_tokens': sum(row.get('padded_input_tokens', 0) for row in results),
                'known_output_tokens': sum(row.get('output_tokens', 0) for row in results),
                'observed_elapsed_seconds': sum(row['elapsed_seconds'] for row in [*results, *failures])}

    @staticmethod
    def _validate(result, request, count):
        if (not isinstance(result, dict) or result.get('request_id') != request
                or result.get('revision') != REVISION or result.get('model') != MODEL
                or 'L4' not in str(result.get('gpu', '')).split()
                or not isinstance(result.get('scores'), list) or len(result['scores']) != count
                or any(type(score) not in (int, float) or not isfinite(score) for score in result['scores'])
                or not isinstance(result.get('pair_tokens'), list) or len(result['pair_tokens']) != count
                or any(type(tokens) is not int or not 0 < tokens <= MAX_TOKENS for tokens in result['pair_tokens'])):
            raise HarnessError('CM4 reranker returned a mismatched or incomplete receipt')
