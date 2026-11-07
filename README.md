# ModelShell

## Current implementation update — 2026-11-07

- **History suggestions are on by default.** At startup ModelShell reads up to 256 KiB / 500 lines from the active Bash `HISTFILE`, keeps the bounded entries in process memory, and suggests matching prior commands first. To opt out for a session, start it with `MODELSHELL_HISTORY_CONTEXT=0 ~/.local/bin/modelshell`. History stays local; Bash may still persist commands under its normal settings. History can contain secrets, so users who share a machine should consider disabling this feature.
- **Suggestion cycling is uncapped.** Tab and Shift+Tab cycle through every result in the local candidate set. The model ranks those candidates; it does not make 256 separate requests. The model computes one vocabulary score vector when the input changes, then ranks candidate completions. The color palette still has ten tint bands, with later ranks using the last band.
- **Path suggestions are context-aware.** ModelShell offers filesystem paths after common path-taking commands such as `ls`, `cd`, `cat`, `cp`, and `grep`, or when the typed prefix is already path-shaped. It should not suggest `Downloads/` after `gh `.
- **Nested launches are guarded.** Running `modelshell` while ModelShell is already active prints a message instead of starting a second editor in the same terminal. If a ModelShell session is started automatically from `.bashrc`, the installer uses a one-time launch marker so the initial start is still allowed. The process is labeled `modelshell` to avoid a Python close prompt; the terminal emulator controls its own “process is running” close confirmation, so ModelShell cannot remove that prompt itself.
- **Bare `bash` hands the terminal to regular Bash.** It preserves the current directory and exported environment. Type `exit` to close that terminal session. The launcher and Linux process are labeled `modelshell` instead of `python3`. This label does not suppress a terminal emulator’s “process is running” close confirmation; that behavior is controlled by the terminal emulator.
- **Tab no longer inserts a literal tab.** If there are no suggestions, Tab does nothing instead of placing a `^I` in the command line. Tab cycling now requests a prompt_toolkit redraw after changing the selected item so the ghost suggestion and cursor stay synchronized; whether this resolves every terminal-specific cursor flicker still needs testing across terminals.
- **Accepted-suggestion learning is available by opt-in.** Start with `MODELSHELL_LEARN_FROM_ACCEPTED=1 ~/.local/bin/modelshell`. Each Right Arrow/Ctrl+F acceptance is stored in `${XDG_STATE_HOME:-~/.local/state}/modelshell/accepted_suggestions.json` with owner-only permissions. The profile loads at startup and accepted completions rank first; it is separate from the bundled training/ranking data and never changes benchmark artifacts. It stores command text and may contain paths, hostnames, or secrets. Disable it by unsetting the variable or setting it to `0`; delete that JSON file to clear it. This is personalization, not a measured benchmark improvement.
- **The bundled model is trained.** It has 3,143,280 parameters. `models/base_checkpoint.npz` is 12,951,666 bytes (about 12.35 MiB) and stores NumPy float32 arrays. The archive duplicates the tied embedding arrays even though the parameter count counts the tied weights once.
- **Benchmark limits:** the repository does not include the benchmark examples or the referenced source report. The previously printed held-out scores, prefix lengths, and training overlap therefore cannot be verified from the repository. Do not treat the reported scores as validated results. The current direct engine benchmark measured 8.20 ms median / 72.36 ms p99 across 100 uncached prefixes on the development host; this excludes terminal redraw and the Bash/PTTY bridge.

### Accuracy notes for statements retained below

The original README text fetched from GitHub is retained below. These notes flag claims that are outdated, inaccurate, or unverifiable in the current implementation rather than silently removing them.

- The introduction says suggestions are limited to “at most ten” results. That was the prior UI cap; cycling now includes every matching candidate.
- The “Important Info” paragraph calls the bundled model “untrained.” The base checkpoint was trained on the attributed shell-command corpus. The separate preference reranker and its ratings are distinct artifacts; saying the checkpoint is untrained conflates them.
- The same paragraph says the current terminal is identified as `python3`. The updated launcher sets its argv/process name to `modelshell`. Some terminal applications may still identify processes from the executable path, so this label change cannot guarantee the close-dialog wording on every desktop.
- The requirements paragraph estimates “3.5MB or so” of RAM. That is not supported by the current measurements: the model archive is about 12.35 MiB, and the measured engine process reached 51.2 MiB maximum RSS on the development host. Full interactive-session RAM has not been measured.
- The startup section says there are only ten candidates. That cap has been removed; the ten-color palette is only a set of rank tint bands.
- The local-context paragraph says username and hostname feed suggestions. Those inputs have been removed; distribution ID, PATH, filesystem entries, Git refs, and configured SSH aliases are the current local candidate sources.
- The history paragraphs say ModelShell does not read Bash history and suggest adding history support. That is now stale: history context is enabled by default, bounded to the recent tail described above, and can be disabled with `MODELSHELL_HISTORY_CONTEXT=0`.
- The suggestion-quality paragraph calls the offline scores “held-out.” The data and referenced source report are absent, so the split, prefix lengths, and overlap with training cannot be checked. The held-out characterization is unverified, not a validated quality claim.
- The limitations paragraph says vocabulary expansion may suggest arbitrary unsupported words. The current engine ranks locally generated candidates and matching history commands; it has no arbitrary model-generated fallback. Candidate coverage can still be incomplete, and `bash -n` is only a syntax check.

ModelShell is an interactive Linux shell with a local next-part (not token, thank god) command suggestion AI, and a persistent Bash backend. Bash still executes your entered commands, so everything from Bash variables, functions, aliases, job control, and foreground interactive programs should work per usual. Suggestions are editable text only; they never execute automatically. Beware; this is stated more indirectly at the end, but I'm not responsible for damage this does if for some reason it suggests something like 'rm -rf' and you press Enter without review. Read Important Info farther down this README.

The bundled model has **3,143,280 parameters** (width 240, 4 layers, 4 attention heads; its tied input/output embedding is counted once). It was trained on a scrubbed subset of the public *Shell Commands Used by Participants of Hands-on Cybersecurity Training* dataset. That corpus consists of cybersecurity lab command histories and is not representative of all ordinary Linux use. The model predicts shell words; ModelShell combines that ranking with local candidates. The earlier ten-choice cap has been removed; cycling traverses the full candidate set. The optional pairwise reranker is a separate locally fit ranking component. Provenance is in [ATTRIBUTION.md](ATTRIBUTION.md).

# Important Info
**Historical project note (partly outdated):** the following proof-of-concept warning reflects an earlier version. The bundled checkpoint is trained; see the accuracy notes above for what remains unverified.

ModelShell in it's current state is a proof of concept rather than something I expect people to use each day. Issue reports are great. If your system is beefy, a larger model, maybe 10M-20M parameters would benefit the program- but I didn't train one. You could definitely do it yourself though in substitution of the model I made. Just use Pytorch and a good dataset. The model is untrained (my pairwise judgements, in testing, actually made it's accuracy WORSE.) 

**Historical issue report:** the launcher and Linux process are now labeled `modelshell` to reduce Python process close prompts. Terminal-specific close-dialog behavior has not been verified across desktop environments.
Yes, the project is aided by ChatGPT Codex. Yes, It's vibecoded. But i tested the thing myself for an extended period and did not see issues pop up, so I wouldn't worry about the fact that AI code can be unstable or vulnerable here.

## Requirements and install

Linux with Bash, Python 3, NumPy, and prompt_toolkit are required. The model loads into the frontend process RAM once at session startup and remains available until that session exits. This creates overhead. The earlier “3.5MB” estimate is unsupported; see the current measured memory figures above. Install dependencies with your distribution package manager or `python3 -m pip install --user -r requirements.txt`. (Remember, run that from the project directory!)

Speaking of the project directory, From it, you can install ModelShell and start it in future interactive Bash terminals with:

```bash
cd /path/to/project
./install.sh --enable-startup
```

Replace `/path/to/project` with the directory containing this README and `install.sh`. For example, if you downloaded or cloned the project into `~/src/modelshell`, use `cd ~/src/modelshell`. The installer places the launcher in `~/.local/bin` and program/model files in `~/.local/share/modelshell`; the startup block uses the launcher's absolute path, so `~/.local/bin` does not need to be on `PATH` for automatic startup. The command above adds a marked, reversible block to `~/.bashrc`, so new interactive Bash terminals start ModelShell automatically.

The block starts ModelShell only for an interactive terminal and guards the Bash backend against launching a second ModelShell. If you use a terminal profile with a “custom command” field, you can instead set it to `~/.local/bin/modelshell`. This does not replace `/bin/bash` as the system login shell.

For isolated installs, set `TINY_SHELL_PREFIX` to a user-owned directory before install and uninstall. Re-running the installer updates the managed installation; it refuses to replace unowned paths. The installer does not install Python packages itself.

## Startup and keys

At startup, the help line describes the important features. The prompt is `username:`. Suggestions appear as gray-tinted ghost text after the cursor. Greenish gray indicates a higher rank; reddish gray indicates a lower rank. The ten tint bands do not limit the number of suggestions.

| Key | Action |
| --- | --- |
| Right Arrow | Accept the visible suggestion at end of input |
| Ctrl+F | Accept the visible suggestion (alternate binding) |
| Tab / Shift+Tab | Cycle forward/backward through all available candidates |
| Up / Down | Cycle suggestions when available; otherwise move through this session's in-memory input history |
| Ctrl+G | Correct an unambiguous likely typo in the first command word |
| Enter | Send the visible editable line to Bash |
| Ctrl+C | Cancel the current input |
| Ctrl+D | Exit when the input is empty |
| Ctrl+P / Ctrl+N | Move through this session's input history |

Suggestion colors can be disabled with `MODELSHELL_COLOR=0`. Set `MODELSHELL_RANK_COLORS` to a comma-separated palette of up to ten hex colors, for example `MODELSHELL_RANK_COLORS='#a8b5aa,#b5aaa8'`. A one-color palette uses the same color for all ranks. Model ranking is available by default; start with `TINY_SHELL_PAIRWISE=1 modelshell` to use the optional preference reranker.

## Local context and privacy

ModelShell uses the current Linux distribution ID to prioritize its package manager after `sudo`. It also uses the current `PATH` to find installed executable names, the current directory for local file names, and a few local facts for relevant completions (for example the current username for `chown`). These values stay on the machine. No network service is contacted by the shell.

ModelShell sets GitHub CLI's `GH_ACCESSIBLE_PROMPTER=true` in the Bash backend by default. This uses GitHub's line-based accessible prompts, which avoid a terminal color-query reply issue that can otherwise make `gh auth login` abort in some terminal emulators. If you prefer GitHub's arrow-key menus, launch ModelShell with `MODELSHELL_GH_ACCESSIBLE_PROMPTER=0` or set that variable to `0` in your Bash startup file. An explicitly set `GH_ACCESSIBLE_PROMPTER` value takes precedence.

**Historical behavior (superseded):** ModelShell now reads a bounded recent tail of the active Bash `HISTFILE` by default; use `MODELSHELL_HISTORY_CONTEXT=0` to disable it. The following paragraphs describe the earlier behavior: ModelShell does **not** read `~/.bash_history` for suggestions. The input history shown by Up/Down or Ctrl+P/Ctrl+N is held in memory for the current ModelShell session. Commands are passed to interactive Bash, which follows its normal `HISTFILE` behavior and may append them to Bash history. Since no history-based suggestion mode is implemented, ModelShell does not expose history entries to the model. The backend reads `~/.bashrc` to retain user aliases and environment setup unless `TINY_SHELL_SKIP_BASHRC=1` is set. As with ordinary Bash startup, that file can itself run arbitrary user-configured commands.

**Historical suggestion (implemented since):** history-based suggestions are now implemented and enabled by default, with bounded local processing and the opt-out above. Not like the thing connects to the internet anyways, but I would just beware.

Accepted-suggestion personalization is separately opt-in with `MODELSHELL_LEARN_FROM_ACCEPTED=1`; unlike aggregate feedback, this stores accepted command text locally. It is not merged into the shipped ranking JSON.

Optional aggregate feedback is off by default. Enable it with `MODELSHELL_FEEDBACK=1 modelshell`; it stores counts and suggestion latency in `${XDG_STATE_HOME:-~/.local/state}/modelshell/feedback.json` with owner-only directory permissions. The file contains no command text, paths, usernames, hostnames, or suggestion text. It stays local and is not transmitted. Remove the file to clear it.

## Update, uninstall, and recovery

Run `./install.sh` again to update from a newer project copy. To uninstall:

```bash
./uninstall.sh
```

Uninstall removes only the managed launcher, installed program directory, and (if present) the marked ModelShell block in `~/.bashrc`. It leaves unrelated startup settings, Bash history, and project files in place. If you enabled startup, closing the current terminal or running `exec bash --noprofile` starts Bash without ModelShell after uninstall.

You can always run `/bin/bash` directly. To recover from a broken startup configuration, edit `~/.bashrc` and remove the block between `# >>> ModelShell startup >>>` and `# <<< ModelShell startup <<<`, or run the project's `./uninstall.sh`.

## Suggestion quality and known limits

Local context sources are selected for usefulness and privacy: distribution ID helps choose a package manager, `PATH` and current-directory entries supply real local candidates, local Git refs and configured SSH aliases supply grounded arguments, and history ranks matching prior commands. **Historical text correction:** the prior username/hostname completion behavior has been removed; those values are not suggestion inputs. This release has no controlled real-world ablation showing that any context source improves user acceptance or command success. An older report records offline held-out results from the source cybersecurity-lab corpus; the source report and examples are absent, so the split and training overlap cannot be verified. These are not validated or real-world quality measurements. Earlier machine timings in that report were recorded on a prior build and should not be treated as current-build measurements.

Candidate generation is intentionally conservative and can omit valid commands or arguments. Vocabulary expansion can suggest a word that a particular command does not accept. `bash -n` checks syntax without running a command; it does not establish safety or success. Typo correction only considers a likely one-edit typo in the first command word and applies only an unambiguous installed-command match. Bash Readline bindings and prompt hooks do not control ModelShell's custom editor. Unusual terminal applications may interact differently with the PTY bridge.

The checkpoint and training data attribution are documented, but the original code license has not been established in the supplied project. Choose and add a code license before publishing a public GitHub repository; do not treat the dataset's CC BY 4.0 terms as a license for the code or every generated artifact.
