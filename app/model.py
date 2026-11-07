"""Small NumPy inference runtime for the exported local shell checkpoint."""
import json
from pathlib import Path

import numpy as np

PAD, UNK, BOS, EOS = "<pad>", "<unk>", "<bos>", "<eos>"


class ShellModel:
    def __init__(self, model_dir):
        model_dir = Path(model_dir)
        vocab_payload = json.loads((model_dir / "vocab.json").read_text(encoding="utf-8"))
        self.vocab_list = vocab_payload["vocab"]
        self.vocab = {word: i for i, word in enumerate(self.vocab_list)}
        self.config = vocab_payload["config"]
        with np.load(model_dir / "base_checkpoint.npz", allow_pickle=False) as weights:
            self.weights = {key: weights[key] for key in weights.files}

    def _linear(self, x, prefix):
        weight_key = prefix + "_weight" if prefix.endswith("in_proj") else prefix + ".weight"
        bias_key = prefix + "_bias" if prefix.endswith("in_proj") else prefix + ".bias"
        w = self.weights[weight_key]
        b = self.weights.get(bias_key)
        out = x @ w.T
        return out if b is None else out + b

    def _norm(self, x, prefix):
        mean = x.mean(axis=-1, keepdims=True)
        var = ((x - mean) ** 2).mean(axis=-1, keepdims=True)
        return ((x - mean) / np.sqrt(var + 1e-5)) * self.weights[prefix + ".weight"] + self.weights[prefix + ".bias"]

    def logits(self, words):
        c = self.config
        ids = [self.vocab[BOS]] + [self.vocab.get(w, self.vocab[UNK]) for w in words]
        ids = ids[-c["max_len"]:]
        x = self.weights["token_embedding.weight"][ids] + self.weights["position_embedding.weight"][:len(ids)]
        width, heads = c["width"], c["heads"]
        head_dim = width // heads
        for layer in range(c["layers"]):
            root = f"blocks.layers.{layer}"
            residual = x
            h = self._norm(x, root + ".norm1")
            qkv = self._linear(h, root + ".self_attn.in_proj")
            q, k, v = np.split(qkv, 3, axis=-1)
            q = q.reshape(len(ids), heads, head_dim).transpose(1, 0, 2)
            k = k.reshape(len(ids), heads, head_dim).transpose(1, 0, 2)
            v = v.reshape(len(ids), heads, head_dim).transpose(1, 0, 2)
            scores = (q @ k.transpose(0, 2, 1)) / np.sqrt(head_dim)
            scores = np.where(np.triu(np.ones((len(ids), len(ids)), dtype=bool), 1)[None, :, :], -1e9, scores)
            scores -= scores.max(axis=-1, keepdims=True)
            attention = np.exp(scores)
            attention /= attention.sum(axis=-1, keepdims=True)
            joined = (attention @ v).transpose(1, 0, 2).reshape(len(ids), width)
            x = residual + self._linear(joined, root + ".self_attn.out_proj")
            residual = x
            h = self._norm(x, root + ".norm2")
            h = self._linear(h, root + ".linear1")
            h = 0.5 * h * (1.0 + np.tanh(np.sqrt(2.0 / np.pi) * (h + 0.044715 * h ** 3)))
            x = residual + self._linear(h, root + ".linear2")
        x = self._norm(x, "norm")[-1]
        return self.weights["output.weight"] @ x

    def log_probabilities(self, words):
        logits = self.logits(words)
        m = float(np.max(logits))
        return logits - (m + np.log(np.exp(logits - m).sum()))
