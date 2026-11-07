#!/usr/bin/env bash
set -euo pipefail

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
enable_startup=0
if [[ "${1:-}" == "--enable-startup" ]]; then
    enable_startup=1
elif [[ -n "${1:-}" && "${1:-}" != "--help" ]]; then
    echo "Usage: $0 [--enable-startup]" >&2
    exit 2
elif [[ "${1:-}" == "--help" ]]; then
    echo "Usage: $0 [--enable-startup]"
    echo "Install modelshell; optionally start it automatically from interactive Bash."
    exit 0
fi
prefix="${TINY_SHELL_PREFIX:-${HOME}/.local}"
share_dir="${prefix}/share/modelshell"
bin_dir="${prefix}/bin"
launcher="${bin_dir}/modelshell"

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import numpy, prompt_toolkit' >/dev/null 2>&1; then
    echo "tiny-shell needs Python 3, NumPy, and prompt_toolkit. Nothing was installed." >&2
    exit 1
fi
if [[ -e "$share_dir" && ! -f "$share_dir/.modelshell-owned" ]]; then
    echo "Refusing to replace an unowned path: $share_dir" >&2
    exit 1
fi
if [[ -e "$launcher" ]] && ! grep -q 'modelshell launcher' "$launcher"; then
    echo "Refusing to replace an existing launcher: $launcher" >&2
    exit 1
fi

mkdir -p "$prefix/share" "$bin_dir"
temp_dir="$(mktemp -d "${prefix}/share/.tiny-shell-trial.XXXXXX")"
trap 'rm -rf -- "$temp_dir"' EXIT
cp -a "$source_dir/app" "$source_dir/models" "$temp_dir/"
cp -a "$source_dir/data" "$temp_dir/"
cp "$source_dir/README.md" "$source_dir/ATTRIBUTION.md" "$source_dir/requirements.txt" "$source_dir/.gitignore" "$temp_dir/"
touch "$temp_dir/.modelshell-owned"
chmod -R go-w "$temp_dir"
if [[ -e "$share_dir" ]]; then rm -rf -- "$share_dir"; fi
mv "$temp_dir" "$share_dir"
trap - EXIT

cat > "$launcher" <<'SH'
#!/usr/bin/env bash
# modelshell launcher
set -e
export PYTHONDONTWRITEBYTECODE=1
bin_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd -- "${bin_dir}/../share/modelshell" && pwd)"
exec "${TINY_SHELL_PYTHON:-python3}" "$project_dir/app/tiny_shell.py" "$@"
SH
chmod 755 "$launcher"
echo "Installed ModelShell at: $launcher"
if (( enable_startup )); then
    bashrc="${HOME}/.bashrc"
    [[ -e "$bashrc" ]] || : > "$bashrc"
    if ! grep -Fq '# >>> ModelShell startup >>>' "$bashrc"; then
        launcher_quoted="$(printf '%q' "$launcher")"
        cat >> "$bashrc" <<RC

# >>> ModelShell startup >>>
if [[ \$- == *i* && -z \${MODELSHELL_ACTIVE:-} && -t 1 ]]; then
    export MODELSHELL_ACTIVE=1
    exec ${launcher_quoted}
fi
# <<< ModelShell startup <<<
RC
    fi
    echo "Interactive Bash startup enabled in $bashrc (remove with ./uninstall.sh)."
else
    echo "Run with: $launcher"
    echo "Use --enable-startup to start ModelShell from interactive Bash terminals."
fi
