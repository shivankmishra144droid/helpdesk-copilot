"""Shared embedding interface; ONNX serving does not import PyTorch."""
import os
from pathlib import Path
import numpy as np

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"

class OnnxEncoder:
    def __init__(self, model_name="all-MiniLM-L6-v2"):
        if model_name not in ("all-MiniLM-L6-v2", MODEL_ID):
            raise ValueError("The ONNX adapter supports only all-MiniLM-L6-v2")
        import onnxruntime as ort
        from tokenizers import Tokenizer
        from huggingface_hub import hf_hub_download
        local = os.getenv("ONNX_MODEL_DIR")
        def artifact(name):
            if local:
                return str(Path(local) / name)
            return hf_hub_download(MODEL_ID, name, revision=MODEL_REVISION)
        self.tokenizer = Tokenizer.from_file(artifact("tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.getenv("ONNX_THREADS", "1"))
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        self.session = ort.InferenceSession(artifact("onnx/model.onnx"), sess_options=options, providers=["CPUExecutionProvider"])

    def encode(self, sentences, normalize_embeddings=False, show_progress_bar=False, batch_size=8, **kwargs):
        single = isinstance(sentences, str)
        texts = [sentences] if single else list(sentences)
        if not texts:
            return np.empty((0, 384), dtype=np.float32)
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        batches = []
        for start in range(0, len(texts), min(batch_size, 8)):
            tokens = self.tokenizer.encode_batch(texts[start:start + min(batch_size, 8)])
            arrays = {"input_ids": np.array([t.ids for t in tokens], dtype=np.int64),
                      "attention_mask": np.array([t.attention_mask for t in tokens], dtype=np.int64),
                      "token_type_ids": np.array([t.type_ids for t in tokens], dtype=np.int64)}
            feed = {entry.name: arrays[entry.name] for entry in self.session.get_inputs()}
            hidden = self.session.run(None, feed)[0]
            mask = arrays["attention_mask"][..., None].astype(np.float32)
            pooled = (hidden * mask).sum(axis=1) / np.maximum(mask.sum(axis=1), 1e-9)
            if normalize_embeddings:
                pooled /= np.maximum(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12)
            batches.append(pooled.astype(np.float32))
        result = np.concatenate(batches)
        return result[0] if single else result

class SentenceTransformer:
    """Compatibility factory for modules sharing the embedding interface."""
    def __new__(cls, model_name="all-MiniLM-L6-v2", **kwargs):
        backend = os.getenv("EMBEDDING_BACKEND", "torch").lower()
        if backend == "onnx":
            return OnnxEncoder(model_name)
        if backend != "torch":
            raise ValueError("EMBEDDING_BACKEND must be torch or onnx")
        from sentence_transformers import SentenceTransformer as TorchEncoder
        return TorchEncoder(model_name, **kwargs)
