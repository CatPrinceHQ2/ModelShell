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

HISTORY_LIMIT_BYTES = 256 * 1024
HISTORY_LIMIT_LINES = 500


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


class AcceptedContext:
    """Opt-in local personalization from explicitly accepted ghost suggestions."""
    LIMIT = 1000

    def __init__(self):
        self.enabled = os.environ.get("MODELSHELL_LEARN_FROM_ACCEPTED") == "1"
        state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        self.path = state_home / "modelshell" / "accepted_suggestions.json"
        self.counts = Counter()
        if self.enabled:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                self.counts.update({line: max(0, int(count)) for line, count in payload.get("accepted", {}).items()
                                    if isinstance(line, str) and isinstance(count, int) and len(line) <= 4096})
            except (OSError, ValueError, TypeError, AttributeError):
                pass

    def completions(self, line):
        if not self.enabled:
            return []
        return sorted((text for text in self.counts if text.startswith(line) and len(text) > len(line)),
                      key=lambda text: (-self.counts[text], text))

    def remember(self, full_line):
        if not self.enabled or not full_line.strip() or len(full_line) > 4096:
            return
        self.counts[full_line] += 1
        if len(self.counts) > self.LIMIT:
            self.counts = Counter(dict(self.counts.most_common(self.LIMIT)))
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        temp_path = None
        try:
            import tempfile
            fd, temp_path = tempfile.mkstemp(prefix=".accepted-suggestions-", dir=self.path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as target:
                json.dump({"accepted": dict(self.counts)}, target, sort_keys=True)
                target.write("\n")
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, self.path)
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)


class HistoryContext:
    """Bounded, in-memory Bash-history completion source; opt out with value 0."""
    def __init__(self):
        self.enabled = os.environ.get("MODELSHELL_HISTORY_CONTEXT", "1") != "0"
        self.path = None
        self.entries = []

    def set_file(self, raw_path):
        path = None
        if self.enabled and raw_path:
            path = Path(os.path.expandvars(os.path.expanduser(raw_path)))
            if not path.is_absolute():
                path = Path.cwd() / path
            path = path.resolve(strict=False)
        if path == self.path:
            return
        self.path = path
        self.entries = []
        if path is None:
            return
        try:
            if not path.is_file():
                return
            with path.open("rb") as source:
                size = source.seek(0, os.SEEK_END)
                start = max(0, size - HISTORY_LIMIT_BYTES)
                source.seek(start)
                payload = source.read(HISTORY_LIMIT_BYTES)
            if start:
                payload = payload.partition(b"\n")[2]
            lines = payload.decode("utf-8", "replace").splitlines()
        except OSError:
            return
        for line in lines:
            line = line.strip()
            if not line or re.fullmatch(r"#\d+", line):
                continue
            self.entries.append(line)
        self.entries = self.entries[-HISTORY_LIMIT_LINES:]

    def remember(self, line):
        if self.enabled and line.strip():
            self.entries.append(line.strip())
            self.entries = self.entries[-HISTORY_LIMIT_LINES:]

    def completions(self, line):
        """Return prior full commands matching the current input, most frequent/recent first."""
        if not self.enabled or not self.entries:
            return []
        counts = Counter()
        last_seen = {}
        for index, command in enumerate(self.entries):
            if not command.startswith(line) or len(command) <= len(line):
                continue
            counts[command] += 1
            last_seen[command] = index
        return sorted(counts, key=lambda item: (-counts[item], -last_seen[item], item))

    def rank(self, line, grounded_options):
        """Prefer history completions that also occur in the current candidate set."""
        grounded = set(grounded_options)
        return [item for item in self.completions(line) if item in grounded]


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
        self.history = HistoryContext()
        self.accepted = AcceptedContext()
        self._cached = lru_cache(maxsize=64)(self._suggest_uncached)

    def set_history_file(self, path):
        self.history.set_file(path)
        if hasattr(self._cached, "cache_clear"):
            self._cached.cache_clear()

    def remember(self, line):
        self.history.remember(line)
        if hasattr(self._cached, "cache_clear"):
            self._cached.cache_clear()

    def remember_accepted(self, full_line):
        self.accepted.remember(full_line)
        if hasattr(self._cached, "cache_clear"):
            self._cached.cache_clear()

    def suggest(self, line):
        try:
            return self._cached(line)
        except Exception:
            self.fallbacks += 1
            return self.history.completions(line) + candidates(line)

    def _suggest_uncached(self, line):
        learned = self.accepted.completions(line)
        options = list(dict.fromkeys(learned + self.history.completions(line) + candidates(line)))
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
        model_ranked = [item[2] for item in scored]
        accepted_ranked = [item for item in learned if item in options]
        history_ranked = self.history.rank(line, options)
        preferred = set(accepted_ranked + history_ranked)
        return accepted_ranked + history_ranked + [item for item in model_ranked if item not in preferred]

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


