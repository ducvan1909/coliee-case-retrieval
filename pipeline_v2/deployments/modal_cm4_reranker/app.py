"""Qwen3 passage scoring on one Modal L4."""

from pathlib import Path
from time import perf_counter

import modal

from pipeline_v2.experiments.context_manager_v2.reranker_protocol import (
    APP_NAME, BATCH_SIZE, INSTRUCTION, MAX_TOKENS, MODEL, REVISION,
)


CACHE = '/models/huggingface'
app = modal.App(APP_NAME)
volume = modal.Volume.from_name('coliee-cm4-reranker-hf-v1', create_if_missing=True)
PROTOCOL = 'pipeline_v2/experiments/context_manager_v2/reranker_protocol.py'
image = (modal.Image.debian_slim(python_version='3.11')
         .pip_install('torch==2.7.1', 'transformers==4.53.2', 'huggingface-hub==0.33.4', 'safetensors==0.5.3')
         .env({'HF_HOME': CACHE, 'HF_HUB_DISABLE_TELEMETRY': '1'})
         .workdir('/root')
         .add_local_file(Path(__file__).resolve().parents[3] / PROTOCOL, '/root/' + PROTOCOL)
         .add_local_file(__file__, '/root/pipeline_v2/deployments/modal_cm4_reranker/app.py'))


@app.cls(image=image, gpu='L4', volumes={CACHE: volume}, min_containers=0, max_containers=1,
         scaledown_window=60, startup_timeout=900, timeout=300, retries=0, include_source=False)
class Reranker:
    @modal.enter()
    def load(self):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        started = perf_counter()
        self.gpu = torch.cuda.get_device_name(0)
        if torch.cuda.device_count() != 1 or 'L4' not in self.gpu.split():
            raise RuntimeError('Expected one NVIDIA L4')
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, padding_side='left')
        self.model = AutoModelForCausalLM.from_pretrained(
            MODEL, revision=REVISION, torch_dtype=torch.bfloat16).to('cuda').eval()
        self.answer_tokens = self.tokenizer.convert_tokens_to_ids(['no', 'yes'])
        if len(set(self.answer_tokens)) != 2 or self.tokenizer.unk_token_id in self.answer_tokens:
            raise RuntimeError('Reranker answer tokens are unavailable')
        self.prefix = self.tokenizer.encode(
            '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query '
            'and the Instruct provided. Note that the answer can only be "yes" or "no".'
            '<|im_end|>\n<|im_start|>user\n', add_special_tokens=False)
        self.suffix = self.tokenizer.encode(
            '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n', add_special_tokens=False)
        volume.commit()
        self.load_seconds = perf_counter() - started

    @modal.method()
    def score(self, request_id, query, documents):
        import torch

        started = perf_counter()
        rendered = [f'<Instruct>: {INSTRUCTION}\n<Query>: {query}\n<Document>: {text}' for text in documents]
        tokenized = self.tokenizer(rendered, add_special_tokens=False, return_attention_mask=False)['input_ids']
        rows = [self.prefix + tokens + self.suffix for tokens in tokenized]
        lengths = [len(row) for row in rows]
        if any(count > MAX_TOKENS for count in lengths):
            raise ValueError('A reranker pair exceeds the pinned context limit')
        scores = []
        padded_tokens = 0
        with torch.inference_mode():
            for offset in range(0, len(rows), BATCH_SIZE):
                batch = self.tokenizer.pad({'input_ids': rows[offset:offset + BATCH_SIZE]},
                                           padding=True, return_attention_mask=True, return_tensors='pt')
                padded_tokens += batch['input_ids'].numel()
                logits = self.model(**batch.to('cuda'), use_cache=False, logits_to_keep=1).logits
                scores.extend(logits[:, -1, self.answer_tokens].float().softmax(dim=-1)[:, 1].tolist())
        return {'request_id': request_id, 'model': MODEL, 'revision': REVISION, 'gpu': self.gpu,
                'scores': scores, 'pair_tokens': lengths, 'input_tokens': sum(lengths),
                'padded_input_tokens': padded_tokens, 'output_tokens': 0,
                'load_seconds': self.load_seconds, 'inference_seconds': perf_counter() - started}
