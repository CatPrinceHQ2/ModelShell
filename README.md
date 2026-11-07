# ModelShell

ModelShell is an interactive Linux shell with a local next-part (not token, thank god) command suggestion AI, and a persistent Bash backend. Bash still executes your entered commands, so everything from Bash variables, functions, aliases, job control, and foreground interactive programs should work per usual. Suggestions are editable text only; they never execute automatically. Beware; this is stated more indirectly at the end, but I'm not responsible for damage this does if for some reason it suggests something like 'rm -rf' and you press Enter without review. Read Important Info farther down this README.

The bundled model has **3,143,280 parameters** (width 240, 4 layers, 4 attention heads; its tied input/output embedding is counted once). It was trained on a scrubbed subset of the public *Shell Commands Used by Participants of Hands-on Cybersecurity Training* dataset. That corpus consists of cybersecurity lab command histories and is not representative of all ordinary Linux use. The model predicts shell words; ModelShell combines that ranking with local candidates and returns at most ten next-word choices. The optional pairwise reranker is a separate locally fit ranking component. Provenance is in [ATTRIBUTION.md](ATTRIBUTION.md).

# Important Info
ModelShell in it's current state is a proof of concept rather than something I expect people to use each day. Issue reports are great. If your system is beefy, a larger model, maybe 10M-20M parameters would benefit the program- but I didn't train one. You could definitely do it yourself though in substitution of the model I made. Just use Pytorch and a good dataset. The model is untrained (my pairwise judgements, in testing, actually made it's accuracy WORSE.) 

A known issue is that terminals running ModelShell show that they are running python3 and ask permission to be closed out.
Yes, the project is aided by ChatGPT Codex. Yes, It's vibecoded. But i tested the thing myself for an extended period and did not see issues pop up, so I wouldn't worry about the fact that AI code can be unstable or vulnerable here.

## Requirements and install

Linux with Bash, Python 3, NumPy, and prompt_toolkit are required. The model loads into the frontend process RAM once at session startup and remains available until that session exits. This creates a little overhead, but 3.5MB or so of RAM shouldn't be too expensive. Install dependencies with your distribution package manager or `python3 -m pip install --user -r requirements.txt`. (Remember, run that from the project directory!)

Speaking of the project directory, From it, you can install ModelShell and start it in future interactive Bash terminals with:

```bash
cd /path/to/project
./install.sh --enable-startup
```

Replace `/path/to/project` with the directory containing this README and `install.sh`. For example, if you downloaded or cloned the project into `~/src/modelshell`, use `cd ~/src/modelshell`. The installer places the launcher in `~/.local/bin` and program/model files in `~/.local/share/modelshell`; the startup block uses the launcher's absolute path, so `~/.local/bin` does not need to be on `PATH` for automatic startup. The command above adds a marked, reversible block to `~/.bashrc`, so new interactive Bash terminals start ModelShell automatically.

The block starts ModelShell only for an interactive terminal and guards the Bash backend against launching a second ModelShell. If you use a terminal profile with a “custom command” field, you can instead set it to `~/.local/bin/modelshell`. This does not replace `/bin/bash` as the system login shell.

For isolated installs, set `TINY_SHELL_PREFIX` to a user-owned directory before install and uninstall. Re-running the installer updates the managed installation; it refuses to replace unowned paths. The installer does not install Python packages itself.

## Startup and keys

At startup, the help line describes the important features. The prompt is `username:`. Suggestions appear as gray-tinted ghost text after the cursor. Greenish gray indicates a higher rank; reddish gray indicates a lower rank... out of 10 total, of course.

| Key | Action |
| --- | --- |
| Right Arrow | Accept the visible suggestion at end of input |
| Ctrl+F | Accept the visible suggestion (alternate binding) |
| Tab / Shift+Tab | Cycle forward/backward through up to ten candidates |
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

ModelShell does **not** read `~/.bash_history` for suggestions. The input history shown by Up/Down or Ctrl+P/Ctrl+N is held in memory for the current ModelShell session. Commands are passed to interactive Bash, which follows its normal `HISTFILE` behavior and may append them to Bash history. Since no history-based suggestion mode is implemented, ModelShell does not expose history entries to the model. The backend reads `~/.bashrc` to retain user aliases and environment setup unless `TINY_SHELL_SKIP_BASHRC=1` is set. As with ordinary Bash startup, that file can itself run arbitrary user-configured commands.

Editing the code to make ModelShell read your bash history may improve it's performance by a small amount, at the cost of more and more of your system RAM, but this is untested and also risks your privacy a little. Not like the thing connects to the internet anyways, but I would just beware.

Optional aggregate feedback is off by default. Enable it with `MODELSHELL_FEEDBACK=1 modelshell`; it stores counts and suggestion latency in `${XDG_STATE_HOME:-~/.local/state}/modelshell/feedback.json` with owner-only directory permissions. The file contains no command text, paths, usernames, hostnames, or suggestion text. It stays local and is not transmitted. Remove the file to clear it.

## Update, uninstall, and recovery

Run `./install.sh` again to update from a newer project copy. To uninstall:

```bash
./uninstall.sh
```

Uninstall removes only the managed launcher, installed program directory, and (if present) the marked ModelShell block in `~/.bashrc`. It leaves unrelated startup settings, Bash history, and project files in place. If you enabled startup, closing the current terminal or running `exec bash --noprofile` starts Bash without ModelShell after uninstall.

You can always run `/bin/bash` directly. To recover from a broken startup configuration, edit `~/.bashrc` and remove the block between `# >>> ModelShell startup >>>` and `# <<< ModelShell startup <<<`, or run the project's `./uninstall.sh`.

## Suggestion quality and known limits

Local context sources are selected for usefulness and privacy: distribution ID helps choose a package manager, `PATH` and current-directory entries supply real local candidates, and the current username/hostname support a small set of host/user argument completions. This release has no controlled real-world ablation showing that any context source improves user acceptance or command success. The included report contains offline held-out results from the source cybersecurity-lab corpus; these are not real-world quality measurements. Earlier machine timings in that report were recorded on a prior build and should not be treated as current-build measurements.

Candidate generation is intentionally conservative and can omit valid commands or arguments. Vocabulary expansion can suggest a word that a particular command does not accept. `bash -n` checks syntax without running a command; it does not establish safety or success. Typo correction only considers a likely one-edit typo in the first command word and applies only an unambiguous installed-command match. Bash Readline bindings and prompt hooks do not control ModelShell's custom editor. Unusual terminal applications may interact differently with the PTY bridge.

The checkpoint and training data attribution are documented, but the original code license has not been established in the supplied project. Choose and add a code license before publishing a public GitHub repository; do not treat the dataset's CC BY 4.0 terms as a license for the code or every generated artifact.
