# ModelShell

One day I woke up and decided that a shell does not have to be deterministic. I wanted ALL the Linux commands!! Muahahaha... I'm such a great person. Anyways, professionally: 

ModelShell is an interactive Linux shell which in essence aims to be somewhat similar to Fish shell, which uses a local language model and local context to suggest command continuations as you type. The goal is to preserve Bash behavior, and Bash is the backend for the thing. It's not a custom command workflow. Pretty much everything about Bash, including environment variables, job control, aliases, and interactive programs, should all work per usual.

Suggestions appear as editable, gray, transparent text infront of what you have typed. ModelShell never executes a suggestion automatically. Typos get highlighted in red too.

This project is for anyone who feels like they want a terminal who feels truly alive. In my personal use as the dev (CatPrinceHQ) I can say that it really does feel that way. The terminal *sometimes* knows what I'm going to put down, even if it's something i've never typed before. It's truly incredible. Mind-reading like, maybe.

## What it does

- Uses local paths, installed commands, Git refs, SSH aliases, and Linux distribution information where relevant.
- Lets you cycle through all available candidates and accept the visible suggestion.
- Keeps the model in **RAM memory** for the duration of a ModelShell session. The overhead is tiny, it can run on pretty much anything. Don't worry about it eating your GPU. 
- Runs commands normally with the same bash backend for familiar use.

For those of you who think this project is useless, I can tell you specifically a good example of a usage that it helped me on.
On a git push, it automatically suggested the next version number, using the previous one that I pushed as context. I thought it was super neat.

## Install

### Requirements

- Linux
- Bash
- Python 3
- NumPy
- prompt_toolkit

Install the Python dependencies from the project directory if they are not already available:

```bash
python3 -m pip install --user -r requirements.txt
```

Some distributions restrict `pip --user` for system Python. In that case, install NumPy and prompt_toolkit using your distribution’s packages or use a Python virtual environment.

### Install and make ModelShell start in new Bash terminals

From the directory containing this README and `install.sh`, run:

```bash
cd /path/to/ModelShell
./install.sh --enable-startup
```

Replace `/path/to/ModelShell` with the directory where you cloned or unpacked this project. For example, if it is in `~/src/ModelShell`, use `cd ~/src/ModelShell`.

The installer places the launcher at `~/.local/bin/modelshell` and the program files at `~/.local/share/modelshell`. It adds a marked block to `~/.bashrc` so new interactive Bash terminals open ModelShell. This does not change your system login shell. The startup block is reversible; see [Uninstall](#update-and-uninstall).

To install without automatic startup, run `./install.sh` and launch ModelShell with:

```bash
~/.local/bin/modelshell
```

If you use a terminal profile with a custom command setting, you can set it to `~/.local/bin/modelshell` instead.

For a custom installation prefix, set `TINY_SHELL_PREFIX` before installing and use the same value when uninstalling. The installer does not install Python dependencies for you.

I use Kitty Terminal on Arch Linux personally, it seemed to work as expected. I can't guarantee functionality for other distros or terminals.

## Use it

The prompt shows the username followed by a colon. Suggestions appear as tinted ghost text after the cursor. Greenish gray indicates a higher-ranked choice; reddish gray indicates a lower-ranked choice. The ten color tints are reused for lower ranks and do not limit the number of suggestions.

| Key | Action |
| --- | --- |
| Right Arrow | Accept the visible suggestion |
| Ctrl+F | Accept the visible suggestion (alternate key) |
| Tab / Shift+Tab | Cycle forward or backward through suggestions |
| Up / Down | Cycle suggestions, or move through this session’s input history when no suggestions are available |
| Ctrl+G | Correct an unambiguous likely typo in the first command word |
| Enter | Send the editable input to Bash |
| Ctrl+C | Cancel the current input |
| Ctrl+D | Exit when the input is empty |
| Ctrl+P / Ctrl+N | Move through this session’s input history |

Disable suggestion colors with `MODELSHELL_COLOR=0`. Set `MODELSHELL_RANK_COLORS` to a comma-separated list of up to ten hex colors, for example:

```bash
MODELSHELL_RANK_COLORS='#a8b5aa,#b5aaa8' ~/.local/bin/modelshell
```

A one-color palette uses the same tint for every rank.

A good tip is that if you aren't finding what you want suggested in one or two tabs, then just type one more letter of your next piece. Every letter narrows the result by a minimum of 26 times (alphabet math!)

## Local context and privacy

### Bash history

History suggestions are enabled by default. At startup, ModelShell reads up to 500 lines or 256 KiB from the active Bash `HISTFILE`, whichever limit is reached first. It keeps those entries in session memory and ranks matching prior commands ahead of other candidates. History is processed locally and is not sent over the network.

History can contain passwords, tokens, private paths, or other sensitive text. Bash may also persist commands using its normal history settings. To disable history suggestions for a session:

```bash
MODELSHELL_HISTORY_CONTEXT=0 ~/.local/bin/modelshell
```

I use this own my own personal machine that nobody else uses so history is not personally an issue. It doesn't occur to me as something that should be too pertinent when using this shell but if your bash history is important DO beware especially on shared devices.

### Accepted-suggestion personalization (optional)

To remember suggestions you explicitly accept with Right Arrow or Ctrl+F, start ModelShell with:

```bash
MODELSHELL_LEARN_FROM_ACCEPTED=1 ~/.local/bin/modelshell
```

The local profile is stored at `${XDG_STATE_HOME:-~/.local/state}/modelshell/accepted_suggestions.json` with owner-only file permissions. It loads at startup and prioritizes previously accepted completions. It stores command text, which may include sensitive paths, hostnames, or secrets. It is separate from the shipped model and ranking data; it does not update the project’s training files or establish a benchmark improvement.

Unset `MODELSHELL_LEARN_FROM_ACCEPTED` or set it to `0` to turn this feature off. Delete `accepted_suggestions.json` to erase the saved profile.

### Other local sources

ModelShell uses Linux distribution information to prioritize relevant package managers, `PATH` to find installed command names, the current directory for file and directory candidates, local Git refs for branch suggestions, and configured SSH aliases for host completion. Candidate generation aims to use context that exists on the machine. The shell itself does not contact a network service.

ModelShell also sets GitHub CLI’s `GH_ACCESSIBLE_PROMPTER=true` in its Bash backend by default. This uses line-based prompts that avoid a terminal color-query issue observed with `gh auth login` in some terminal emulators. Set `MODELSHELL_GH_ACCESSIBLE_PROMPTER=0` to opt out. An explicitly set `GH_ACCESSIBLE_PROMPTER` value takes precedence.

Optional aggregate feedback is off by default. Enable it with `MODELSHELL_FEEDBACK=1 ~/.local/bin/modelshell`. It records counts and suggestion latency in `${XDG_STATE_HOME:-~/.local/state}/modelshell/feedback.json`. It does not contain command text, paths, usernames, hostnames, or suggestion text, and is not transmitted. Delete that file to clear it.

## The model

The bundled base model has **3,143,280 parameters** (width 240, four layers, four attention heads; the tied input/output embedding is counted once). Its checkpoint is `models/base_checkpoint.npz`, a 12,951,666-byte NumPy archive containing float32 arrays. The archive stores the tied embedding arrays twice, although the parameter count counts the shared weights once.

The model was trained on a scrubbed subset of [Shell Commands Used by Participants of Hands-on Cybersecurity Training](https://zenodo.org/records/6670113), a cybersecurity-lab command-history dataset. Those commands do not represent every kind of everyday Linux use. More information is in [ATTRIBUTION.md](ATTRIBUTION.md).

The optional pairwise reranker is a separate component fit from local candidate ratings. It is off by default; enable it for a session with:

```bash
TINY_SHELL_PAIRWISE=1 ~/.local/bin/modelshell
```

[ADD A PERSONAL NOTE ABOUT WHAT YOU LEARNED WHILE TRAINING OR EVALUATING THE MODEL. AVOID CLAIMING RESULTS YOU HAVE NOT VERIFIED.]

## Limitations and measurements

- Candidate generation is conservative. It can omit valid commands or arguments, and syntax checking does not prove that a command is safe or will succeed.
- Typo correction is limited to an unambiguous, likely one-edit typo in the first command word.
- ModelShell uses its own editor; Bash Readline bindings and prompt hooks do not control that editor.
- Terminal emulators can behave differently with the PTY bridge. Cursor flicker and close-confirmation behavior have not been verified across terminal applications. The process is labeled `modelshell`, but the emulator controls whether it asks you to confirm closing a terminal with a running process.
- The repository does not include the examples or source report needed to verify previously reported held-out model scores. Do not treat those scores as a validated benchmark.
- A direct engine benchmark on the development host measured 8.20 ms median and 72.36 ms p99 across 100 uncached prefixes. It excludes terminal redraw and the Bash/PTTY bridge and is not a hardware-independent guarantee. Full interactive-session memory, startup-to-prompt time, end-to-end per-keystroke latency, and idle CPU use have not been measured. The model archive size is not the same as runtime memory use.
- No controlled real-world study has measured whether local context improves acceptance or command success. Accepted-suggestion personalization is intended to adapt locally, but its effect has not been measured.

All issues are important to me, no matter how small. If you find one, PLEASE let me know!

## Update and uninstall

To update, run `./install.sh` again from a newer project copy. It refreshes the managed install and preserves the startup block if one is already enabled.

To uninstall, run this from the project directory:

```bash
./uninstall.sh
```

Uninstall removes the managed launcher, installed program files, and marked ModelShell block from `~/.bashrc`. It leaves other Bash startup settings, Bash history, and the project directory untouched. You can also remove the marked block manually by deleting the lines between `# >>> ModelShell startup >>>` and `# <<< ModelShell startup <<<` in `~/.bashrc`.

I hope you enjoy using ModelShell, and I plan to fix any issues submitted to the project.

## Contributing and project notes

Users; please test the app rigourously. Even if you find the worlds' smallest issue with it, make an issue. I will fix it ASAP.

The project is AI assisted by ChatGPT Codex and a local Qwen 4B model for pairwise ranking and shell project structuring. Model training was done by me personally
