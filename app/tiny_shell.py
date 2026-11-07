#!/usr/bin/env python3
"""Bash-backed interactive shell frontend with local model suggestions."""
import asyncio
import html
import json
import os
import pty
import re
import select
import shutil
import signal
import sys
import tempfile
import termios
import time
import tty
import uuid
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.document import Document
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.layout.processors import Processor, Transformation

from candidates import syntax_ok
from engine import SuggestionEngine

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_TERM = os.environ.get("TERM")
ORIGINAL_NO_COLOR = os.environ.get("NO_COLOR")
PROMPT_TAG = "\x1eTSH_PROMPT_" + uuid.uuid4().hex + "\x1f"
STATE_TAG = "\x1eTSH_STATE_" + uuid.uuid4().hex + ":"
STATE_END = ":\x1f"


class Feedback:
    def __init__(self):
        self.enabled = os.environ.get("MODELSHELL_FEEDBACK", os.environ.get("TINY_SHELL_FEEDBACK")) == "1"
        self.path = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "modelshell" / "feedback.json"
        self.data = {"suggestions_shown": 0, "suggestions_accepted": 0, "suggestions_dismissed": 0,
                     "corrections_applied": 0, "fallbacks": 0, "syntax_rejections": 0,
                     "latency_count": 0, "latency_total_ms": 0.0, "latency_max_ms": 0.0,
                     **{f"latency_le_{limit}ms": 0 for limit in (5, 10, 25, 50, 100, 250, 500, 1000)},
                     "latency_over_1000ms": 0}
        if self.enabled:
            try:
                old = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(old, dict) and all(isinstance(v, (int, float)) for v in old.values()):
                    for key in self.data:
                        self.data[key] += old.get(key, 0)
            except (OSError, ValueError):
                pass

    def add(self, key, amount=1):
        if not self.enabled:
            return
        self.data[key] += amount
        self.save()

    def latency(self, ms):
        if not self.enabled:
            return
        self.data["latency_count"] += 1
        self.data["latency_total_ms"] += ms
        self.data["latency_max_ms"] = max(self.data["latency_max_ms"], ms)
        for limit in (5, 10, 25, 50, 100, 250, 500, 1000):
            if ms <= limit:
                self.data[f"latency_le_{limit}ms"] += 1
                break
        else:
            self.data["latency_over_1000ms"] += 1
        self.save()

    def save(self):
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        fd, tmp_name = tempfile.mkstemp(prefix=".tiny-shell-feedback-", dir=self.path.parent)
        tmp = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.write(json.dumps(self.data, sort_keys=True) + "\n")
        os.replace(tmp, self.path)


class TrialLexer(Lexer):
    def __init__(self, engine):
        self.engine = engine

    def lex_document(self, document):
        lines = document.lines
        def get_line_tokens(index):
            line = lines[index]
            corrected = self.engine.correction(line)
            if not corrected:
                return [("", line)]
            old_first = line.lstrip().split(None, 1)[0] if line.strip() else ""
            start = len(line) - len(line.lstrip())
            return [("", line[:start]), ("class:typo", old_first), ("", line[start + len(old_first):])]
        return get_line_tokens


class TrialSuggest(AutoSuggest):
    def __init__(self, engine, state, feedback):
        self.engine, self.state, self.feedback = engine, state, feedback

    def get_suggestion(self, buffer, document):
        if document.cursor_position != len(document.text):
            return None
        line = document.text
        if self.state.get("line") != line:
            self.state["line"] = line
            self.state["index"] = 0
            self.state["shown_key"] = None
            start = time.perf_counter()
            fallbacks = getattr(self.engine, "fallbacks", 0)
            rejections = getattr(self.engine, "syntax_rejections", 0)
            self.state["items"] = self.engine.suggest(line)
            elapsed = (time.perf_counter() - start) * 1000
            self.state["latency"] = elapsed
            self.feedback.latency(elapsed)
            if getattr(self.engine, "fallbacks", 0) > fallbacks:
                self.feedback.add("fallbacks")
            if getattr(self.engine, "syntax_rejections", 0) > rejections:
                self.feedback.add("syntax_rejections")
        items = self.state.get("items", [])
        if not items:
            return None
        chosen = items[self.state["index"] % len(items)]
        if chosen.startswith(line) and len(chosen) > len(line):
            self.state["active"] = True
            shown_key = (line, self.state["index"] % len(items))
            if self.state.get("shown_key") != shown_key:
                self.feedback.add("suggestions_shown")
                self.state["shown_key"] = shown_key
            return Suggestion(chosen[len(line):])
        return None


class RankedGhost(Processor):
    """Tint the ghost text according to its current rank."""
    def __init__(self, state):
        self.state = state

    def apply_transformation(self, transformation_input):
        fragments = transformation_input.fragments
        rank = min(9, max(0, int(self.state.get("index", 0))))
        return Transformation([
            (f"class:rank-{rank}" if "auto-suggestion" in style else style, text)
            for style, text, *rest in fragments
        ])


def styled_prompt():
    user = html.escape(os.environ.get("USER", "user"))
    return HTML(f"<ansigreen>{user}</ansigreen>: ")


def _write_all(fd, data):
    view = memoryview(data)
    while view:
        sent = os.write(fd, view)
        view = view[sent:]


def _read_until(fd, marker, show=True, collect=False):
    buf = bytearray()
    while True:
        ready, _, _ = select.select([fd], [], [], 0.15)
        if not ready:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return bytes(buf), False
        if not chunk:
            return bytes(buf), False
        buf.extend(chunk)
        idx = buf.find(marker)
        if idx >= 0:
            before, after = bytes(buf[:idx]), bytes(buf[idx + len(marker):])
            if show and before:
                _write_all(1, before)
            return before + after, True
        if len(buf) > len(marker) + 65536:
            # Preserve a possible marker prefix while streaming command output.
            flush_len = len(buf) - len(marker)
            if show:
                _write_all(1, bytes(buf[:flush_len]))
            del buf[:flush_len]


def _read_state(fd):
    prompt_literal = PROMPT_TAG[1:-1]
    command = (" PROMPT_COMMAND=; "
               + "PS1=$'\\036" + prompt_literal + "\\037'; stty -echo; "
               + "printf '\\036" + STATE_TAG[1:] + "%s\\037%s" + STATE_END.replace("\x1f", "\\037")
               + "' \"$PWD\" \"$PATH\"\n")
    _write_all(fd, command.encode())
    data, ok = _read_until(fd, PROMPT_TAG.encode(), show=False)
    raw = data
    start = raw.find(STATE_TAG.encode())
    if start < 0:
        return ok
    end = raw.find(STATE_END.encode(), start + len(STATE_TAG))
    if end < 0:
        return ok
    payload = raw[start + len(STATE_TAG):end]
    cwd, sep, path = payload.partition(b"\x1f")
    if sep:
        try:
            os.chdir(os.fsdecode(cwd))
            os.environ["PWD"] = os.fsdecode(cwd)
            os.environ["PATH"] = os.fsdecode(path)
        except OSError:
            pass
    return ok


def _write_rc(path):
    # Readline hooks in a user's bashrc are not useful to this custom line editor.
    text = f'''bind() {{ :; }}
if [[ -r "$HOME/.bashrc" && "${{TINY_SHELL_SKIP_BASHRC:-0}}" != 1 ]]; then
    source "$HOME/.bashrc"
fi
unset -f bind
PROMPT_COMMAND=
HISTCONTROL="ignorespace${{HISTCONTROL:+:$HISTCONTROL}}"
if [[ -z "${{GH_ACCESSIBLE_PROMPTER+x}}" && "${{MODELSHELL_GH_ACCESSIBLE_PROMPTER:-1}}" != 0 ]]; then
    export GH_ACCESSIBLE_PROMPTER=true
fi
PS1=$'\\036{PROMPT_TAG[1:-1]}\\037'
stty -echo
'''
    Path(path).write_text(text, encoding="utf-8")


def load_engine(root, pairwise=False):
    try:
        engine = SuggestionEngine(root, pairwise=pairwise)
        if engine.pairwise_unavailable:
            print("tiny-shell: pairwise ranker unavailable; using base model ranking", file=sys.stderr)
        return engine, engine.pairwise_unavailable
    except Exception as exc:
        print(f"tiny-shell: model could not be loaded ({type(exc).__name__}); using deterministic local candidates", file=sys.stderr)
        engine = SuggestionEngine.__new__(SuggestionEngine)
        engine.model = None
        engine.ranker = None
        engine.counts = {}
        engine.frequency = {}
        engine.fallbacks = 0
        engine.syntax_rejections = 0
        engine.pairwise = False
        engine._cached = lambda line: __import__("candidates").candidates(line)[:10]
        engine.correction = SuggestionEngine.correction.__get__(engine, SuggestionEngine)
        return engine, True


async def _interactive_loop(fd, engine, feedback):
    state = {"line": None, "items": [], "index": 0, "active": False}
    kb = KeyBindings()
    session = None

    def cycle(event, direction=1):
        buffer = event.current_buffer
        items = engine.suggest(buffer.text)
        if not items:
            return False
        if state.get("line") != buffer.text:
            state.update(line=buffer.text, items=items, index=0)
        else:
            state["items"] = items
            state["index"] = (state.get("index", 0) + direction) % len(items)
        selected = state["items"][state["index"] % len(state["items"])]
        # prompt_toolkit caches AutoSuggest output per buffer text. Cycling
        # does not change that text, so update the cached ghost explicitly.
        buffer.suggestion = Suggestion(selected[len(buffer.text):]) if selected.startswith(buffer.text) else None
        state["active"] = True
        event.app.invalidate()
        return True

    @kb.add("tab")
    def _tab(event):
        if not cycle(event, 1):
            event.current_buffer.insert_text("\t")

    @kb.add("s-tab")
    def _shift_tab(event):
        cycle(event, -1)

    @kb.add("enter")
    def _enter(event):
        # A syntactically incomplete line becomes a continuation line. The
        # command is sent to Bash only after the whole buffer passes bash -n.
        if syntax_ok(event.current_buffer.text):
            event.current_buffer.validate_and_handle()
        else:
            feedback.add("syntax_rejections")
            event.current_buffer.insert_text("\n")

    @kb.add("up")
    def _up(event):
        if not cycle(event, -1):
            event.current_buffer.history_backward()

    @kb.add("down")
    def _down(event):
        if not cycle(event, 1):
            event.current_buffer.history_forward()

    def accept_suggestion(event):
        buf = event.current_buffer
        suggestion = buf.suggestion
        if suggestion:
            buf.insert_text(suggestion.text)
            feedback.add("suggestions_accepted")
            state["active"] = False
            state["line"] = None
        else:
            buf.cursor_right(count=1)

    @kb.add("c-f")
    def _accept(event):
        accept_suggestion(event)

    @kb.add("right")
    def _right(event):
        if event.current_buffer.cursor_position == len(event.current_buffer.text):
            accept_suggestion(event)
        else:
            event.current_buffer.cursor_right(count=1)

    @kb.add("c-g")
    def _correct(event):
        buf = event.current_buffer
        correction = engine.correction(buf.text)
        if correction:
            pos = buf.cursor_position
            was_at_end = pos == len(buf.text)
            buf.text = correction
            buf.cursor_position = len(correction) if was_at_end else min(len(correction), pos)
            feedback.add("corrections_applied")
            state["line"] = None
            state["active"] = False

    style = Style.from_dict(_style_rules())
    engine_lexer = TrialLexer(engine)

    def toolbar():
        items = state.get("items", [])
        count = len(items)
        position = (state.get("index", 0) % count + 1) if count else 0
        return HTML(f"<bottom-toolbar>{position}/{count}  ·  ↑/↓ or Tab: cycle  ·  Right/Ctrl-F: accept suggestion  ·  Ctrl-G: fix command typo  ·  Enter: run typed line</bottom-toolbar>")

    def right_prompt():
        count = len(state.get("items", []))
        position = (state.get("index", 0) % count + 1) if count else 0
        return HTML(f"<ansigray>[{position}/{count}]</ansigray>" if count else "")

    session = PromptSession(
        message=styled_prompt,
        multiline=True,
        auto_suggest=TrialSuggest(engine, state, feedback),
        rprompt=right_prompt,
        lexer=engine_lexer,
        input_processors=[RankedGhost(state)],
        style=style,
        key_bindings=kb,
        bottom_toolbar=toolbar,
        prompt_continuation=lambda width, line_number, wrap_count: HTML("<ansicyan>... </ansicyan>"),
        reserve_space_for_menu=0,
        enable_history_search=True,
    )

    async def run_bridge():
        old = termios.tcgetattr(0)
        try:
            tty.setraw(0)
            prompt_marker = PROMPT_TAG.encode()
            pending = bytearray()
            while True:
                ready, _, _ = select.select([0, fd], [], [], 0.05)
                if 0 in ready:
                    data = os.read(0, 4096)
                    if not data:
                        break
                    _write_all(fd, data)
                if fd in ready:
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    pending.extend(chunk)
                    idx = pending.find(prompt_marker)
                    if idx >= 0:
                        visible = bytes(pending[:idx])
                        if visible:
                            _write_all(1, visible)
                        return True
                    if len(pending) > len(prompt_marker):
                        flush = len(pending) - len(prompt_marker)
                        _write_all(1, bytes(pending[:flush]))
                        del pending[:flush]
        finally:
            termios.tcsetattr(0, termios.TCSADRAIN, old)
        return False

    while True:
        state.update(line=None, items=[], index=0, active=False)
        try:
            line = await session.prompt_async()
        except KeyboardInterrupt:
            _write_all(1, b"\r\n")
            continue
        except EOFError:
            line = "exit"
        if not line:
            continue
        if state.get("active"):
            feedback.add("suggestions_dismissed")
        _write_all(1, b"\r\n")
        _write_all(fd, line.encode("utf-8", "surrogateescape") + b"\n")
        alive = await run_bridge()
        if not alive:
            break
        _write_all(1, b"\r\n")
        # Pull cwd and PATH back from Bash so local file/command candidates stay current.
        try:
            _read_state(fd)
            if hasattr(engine._cached, "cache_clear"):
                engine._cached.cache_clear()
            if hasattr(engine.correction, "cache_clear"):
                engine.correction.cache_clear()
        except OSError:
            pass


def main():
    # Some embedded terminals label themselves "dumb" despite supporting ANSI.
    if os.environ.get("TERM", "") in {"", "dumb"}:
        os.environ["TERM"] = "xterm-256color"
    # This frontend needs color for ghost text and typo highlighting. Preserve
    # the user's NO_COLOR setting for programs running in the Bash backend.
    os.environ.pop("NO_COLOR", None)
    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")
    feedback = Feedback()
    engine, fallback = load_engine(ROOT, pairwise=os.environ.get("TINY_SHELL_PAIRWISE") == "1")
    print("ModelShell  ·  Ctrl+G: correct command typo  ·  Right Arrow: accept suggestion")
    print("Suggestion color shows rank: greenish gray is higher, reddish gray is lower. Tab/Shift+Tab or ↑/↓ cycles.")
    if fallback and feedback.enabled:
        feedback.add("fallbacks")
    if not shutil.which("bash"):
        print("tiny-shell requires Bash on PATH", file=sys.stderr)
        return 2
    fd, rc = tempfile.mkstemp(prefix="tiny-shell-rc-")
    os.close(fd)
    _write_rc(rc)
    pid = None
    master = None
    try:
        pid, master = pty.fork()
        if pid == 0:
            env = os.environ.copy()
            if ORIGINAL_TERM is None:
                env.pop("TERM", None)
            else:
                env["TERM"] = ORIGINAL_TERM
            if ORIGINAL_NO_COLOR is None:
                env.pop("NO_COLOR", None)
            else:
                env["NO_COLOR"] = ORIGINAL_NO_COLOR
            env["PS1"] = PROMPT_TAG
            os.execvpe("bash", ["bash", "--noprofile", "--noediting", "--rcfile", rc, "-i"], env)
        os.set_blocking(master, True)
        _read_until(master, PROMPT_TAG.encode(), show=False)
        _read_state(master)
        asyncio.run(_interactive_loop(master, engine, feedback))
    finally:
        try:
            if master is not None:
                os.close(master)
        except OSError:
            pass
        if pid is not None:
            try:
                os.kill(pid, signal.SIGHUP)
                os.waitpid(pid, 0)
            except (OSError, ChildProcessError):
                pass
        try:
            os.unlink(rc)
        except OSError:
            pass
    return 0


def _style_rules():
    """Build legible rank colors, with a neutral opt-out and user palette."""
    rules = {"typo": "fg:#ff5555 underline", "bottom-toolbar": "fg:#aaaaaa bg:#202020"}
    if os.environ.get("MODELSHELL_COLOR", "1").lower() in {"0", "false", "no", "off"}:
        colors = ["#888888"] * 10
    elif os.environ.get("MODELSHELL_RANK_COLORS"):
        supplied = [item.strip() for item in os.environ["MODELSHELL_RANK_COLORS"].split(",") if item.strip()]
        colors = [item if item.startswith("#") else "#" + item for item in supplied[:10]]
        if not colors or any(not re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", item) for item in colors):
            colors = ["#a8b5aa", "#b5aaa8"]
        colors = (colors + [colors[-1]] * 10)[:10]
    else:
        colors = ["#748b78", "#7d8a7d", "#867f7c", "#8d7777", "#936f73"]
        colors = [colors[min(4, round(i * 4 / 9))] for i in range(10)]
    rules.update({f"rank-{index}": f"fg:{color}" for index, color in enumerate(colors)})
    return rules


if __name__ == "__main__":
    raise SystemExit(main())
