"""System-aware candidates ranked by the base model and local pairwise reranker."""
import json
import os
import re
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path

from candidates import candidates, words, syntax_ok, SAFE_FLAGS
from model import ShellModel

MODEL_WORD = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]{0,39}/?$")


def _argument_position(line):
    parsed = words(line)
    trailing = bool(line) and line[-1].isspace()
    context = parsed if trailing else parsed[:-1]
    segment = context
    for index in range(len(context) - 1, -1, -1):
        if context[index] in {"&&", "||", ";", "|", "&", "<", ">", ">>", "2>", "1>", "(", ")"}:
            segment = context[index + 1:]
            break
    wrappers = {"sudo", "command", "env", "time", "nice", "nohup"}
    return bool(segment and not (len(segment) == 1 and segment[0] in wrappers))


class SuggestionEngine:
    def __init__(self, root, pairwise=False):
        root = Path(root)
        self.pairwise = pairwise
        self.model = ShellModel(root / "models")
        self.ranker = None
        self.counts = {}
        self.frequency = Counter()
        self.pairwise_unavailable = False
        if pairwise:
            try:
                self.ranker = json.loads((root / "models/pairwise_ranker.json").read_text(encoding="utf-8"))
                tables = json.loads((root / "models/frequency_tables.json").read_text(encoding="utf-8"))
                self.counts = {int(n): {tuple(key): Counter(values) for key, values in tab} for n, tab in tables["tables"].items()}
                self.frequency = Counter(tables["frequency"])
            except (OSError, ValueError, KeyError, TypeError):
                self.pairwise = False
                self.pairwise_unavailable = True
                self.ranker = None
                self.counts = {}
                self.frequency = Counter()
        self.fallbacks = 0
        self.syntax_rejections = 0
        self._cached = lru_cache(maxsize=64)(self._suggest_uncached)

    def suggest(self, line):
        try:
            return self._cached(line)
        except Exception:
            self.fallbacks += 1
            return candidates(line)[:10]

    def _suggest_uncached(self, line):
        options = candidates(line)
        # The local candidate generator supplies installed commands, known
        # flags, and filesystem entries. For arguments, expand a sparse pool
        # with a bounded slice of the model vocabulary so the model can rank
        # plausible next words even when the command has no hand-written map.
        if _argument_position(line) and len(options) < 10:
            trailing = bool(line) and line[-1].isspace()
            prefix = "" if trailing else (words(line)[-1] if words(line) else "")
            additions = []
            for word in self.model.vocab_list:
                if word in {"<pad>", "<unk>", "<bos>", "<eos>"}:
                    continue
                if not word.startswith(prefix) or word == prefix or not MODEL_WORD.fullmatch(word):
                    continue
                additions.append(line + word[len(prefix):])
                if len(additions) >= 256:
                    break
            options = list(dict.fromkeys([*options, *additions]))
        if not options:
            if not syntax_ok(line + "TINY_COMPLETION_TOKEN"):
                self.syntax_rejections += 1
            return []
        trailing = bool(line) and line[-1].isspace()
        context = words(line) if trailing else words(line)[:-1]
        log_probs = self.model.log_probabilities(context)
        command_context = next((os.path.basename(w) for w in context
                                if w not in {"sudo", "command", "env", "time", "nice", "nohup"}
                                and not w.startswith("-")), "")
        scored = []
        for option in options:
            parsed = words(option)
            if not parsed:
                continue
            word = parsed[-1]
            token_id = self.model.vocab.get(word)
            model_score = float(log_probs[token_id]) if token_id is not None else -20.0
            if word in SAFE_FLAGS.get(command_context, "").split():
                model_score += 30.0
            if self.pairwise:
                count = 0
                for n in (3, 2, 1):
                    if len(context) >= n:
                        count = self.counts[n].get(tuple(context[-n:]), {}).get(word, 0)
                        if count:
                            break
                if not count:
                    count = self.frequency.get(word, 0)
                feats = [model_score, math.log1p(count)]
                normalized = [(v - mean) / scale for v, mean, scale in zip(feats, self.ranker["feature_mean"], self.ranker["feature_scale"])]
                rank_score = sum(w * v for w, v in zip(self.ranker["weights"], normalized))
            else:
                rank_score = model_score
            scored.append((rank_score, model_score, option))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        return [item[2] for item in scored[:10]]

    @lru_cache(maxsize=1024)
    def correction(self, line):
        match = re.match(r"^(\s*)([A-Za-z0-9_.+-]+)(?=\s|$)(.*)$", line)
        if not match:
            return None
        before, word, tail = match.groups()
        if "/" in word or word.startswith(("$", "~")):
            return None
        installed = set()
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            try:
                installed.update(name for name in os.listdir(directory) if os.access(os.path.join(directory, name), os.X_OK))
            except OSError:
                pass
        if word in installed:
            return None
        candidates = [name for name in installed if _distance_one(word, name)]
        if not candidates:
            return None
        candidates.sort(key=lambda name: (0 if _swap(word, name) else 1, name.lower(), name))
        if len(candidates) > 1 and _distance_one(word, candidates[1]) == _distance_one(word, candidates[0]) and _swap(word, candidates[1]) == _swap(word, candidates[0]):
            return None
        return before + candidates[0] + tail


def _swap(a, b):
    if len(a) != len(b):
        return False
    diffs = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    return len(diffs) == 2 and diffs[1] == diffs[0] + 1 and a[diffs[0]] == b[diffs[1]] and a[diffs[1]] == b[diffs[0]]


def _distance_one(a, b):
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1 or _swap(a, b)
    shorter, longer = (a, b) if len(a) < len(b) else (b, a)
    i = j = edits = 0
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
        else:
            edits += 1
        j += 1
    edits += j < len(longer)
    return edits <= 1


