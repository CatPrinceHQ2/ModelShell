#!/usr/bin/env bash
set -euo pipefail
prefix="${TINY_SHELL_PREFIX:-${HOME}/.local}"
share_dir="${prefix}/share/modelshell"
launcher="${prefix}/bin/modelshell"
if [[ -e "$share_dir" ]]; then
    if [[ ! -f "$share_dir/.modelshell-owned" ]]; then
        echo "Refusing to remove an unowned path: $share_dir" >&2
        exit 1
    fi
    rm -rf -- "$share_dir"
fi
if [[ -e "$launcher" ]]; then
    if ! grep -q 'modelshell launcher' "$launcher"; then
        echo "Refusing to remove an unrecognized launcher: $launcher" >&2
        exit 1
    fi
    rm -f -- "$launcher"
fi
if [[ -f "${HOME}/.bashrc" ]] && grep -Fq '# >>> ModelShell startup >>>' "${HOME}/.bashrc"; then
    temp="$(mktemp "${HOME}/.bashrc.modelshell.XXXXXX")"
    awk '
      $0 == "# >>> ModelShell startup >>>" { skip=1; next }
      $0 == "# <<< ModelShell startup <<<" { skip=0; next }
      !skip { print }
    ' "${HOME}/.bashrc" > "$temp"
    chmod --reference="${HOME}/.bashrc" "$temp"
    cat -- "$temp" > "${HOME}/.bashrc"
    rm -f -- "$temp"
    echo "Removed the ModelShell startup block from ~/.bashrc."
fi
echo "ModelShell has been removed from $prefix. Your Bash history and unrelated startup settings remain."
