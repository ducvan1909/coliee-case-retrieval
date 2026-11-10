"""Deploy explicitly: python -m pipeline_v2.m3_opt deploy.

Only four small files are uploaded; corpus, vectors and credentials stay local.
"""
import json
from pathlib import Path
import modal

ROOT=Path("/root") if Path("/root/pipeline_v2/configs/m3_opt.json").exists() else Path(__file__).resolve().parents[3]
PROFILE_PATH=ROOT/"pipeline_v2/configs/m3_opt.json"
PROFILE=json.loads(PROFILE_PATH.read_bytes())["embedding"]
image=(modal.Image.debian_slim(python_version="3.12")
       .pip_install("torch=="+PROFILE["torch"],"transformers=="+PROFILE["transformers"],"tokenizers=="+PROFILE["tokenizers"],"modal==1.5.3")
       .add_local_file(str(PROFILE_PATH),"/root/pipeline_v2/configs/m3_opt.json")
       .add_local_file(str(ROOT/"pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json"),"/root/pipeline_v2/configs/qwen3_embedding_4b_tokenizer.lock.json")
       .add_local_file(str(Path(__file__).with_name("engine.py")),"/root/engine.py")
       .add_local_file(str(Path(__file__)),"/root/qwen3_embed.py"))
app=modal.App(PROFILE["modal_app"])
volume=modal.Volume.from_name(PROFILE["modal_volume"],create_if_missing=True)


@app.cls(image=image,gpu=PROFILE["gpu"],volumes={"/model-cache":volume},min_containers=0,max_containers=1,
         scaledown_window=PROFILE["scaledown_window_seconds"],timeout=600,startup_timeout=1800,retries=0,include_source=False)
class Embedder:
    @modal.enter()
    def load(self):
        from engine import Engine
        self.engine=Engine()
        volume.commit()

    @modal.method()
    def encode(self,texts,kind="document"):
        return self.engine.encode(texts,kind)
