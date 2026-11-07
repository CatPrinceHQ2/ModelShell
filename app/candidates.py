#!/usr/bin/env python3
"""Suggest one locally available shell word; never executes suggestions."""
import argparse
from functools import lru_cache
import glob
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

SAFE_FLAGS = {
    "ls": "-la -l -a -h -R -t -r -S -d -F -1",
    "grep": "-i -n -v -r -R -w -E -F -l -L -c",
    "find": "-name -iname -type -maxdepth -mindepth -print",
    "git": "status log diff show add commit branch checkout switch pull push fetch clone",
    "systemctl": "status start stop restart reload enable disable is-active list-units suspend hibernate reboot poweroff",
    "python": "-c -m -V --version", "python3": "-c -m -V --version",
    "cp": "-r -a -i -n -v", "mv": "-i -n -v", "mkdir": "-p -v",
    "tar": "-c -x -t -f -v -z -j", "curl": "-I -L -o -O -s -S",
    "wget": "-O -q -c", "cat": "-n -b -A", "head": "-n -c",
    "tail": "-n -f -c", "sort": "-r -n -u -k", "du": "-h -s -d",
    "pacman": "-S -Ss -Syu -Q -Qi -Ql -R",
    "apt": "install update upgrade search remove show list",
    "dnf": "install update upgrade search remove info list",
    "zypper": "install update search remove info list",
}
OPS = {"&&", "||", ";", "|", "&", "<", ">", ">>", "2>", "1>", "(", ")"}
SAFE_WORD = re.compile(r"^[A-Za-z0-9_./:+@%=-]+/?$")
DISTRO_PACKAGE_MANAGER = {
    "arch": "pacman", "manjaro": "pacman", "endeavouros": "pacman",
    "debian": "apt", "ubuntu": "apt", "linuxmint": "apt", "pop": "apt",
    "fedora": "dnf", "rhel": "dnf", "centos": "dnf", "rocky": "dnf", "almalinux": "dnf",
    "opensuse": "zypper", "opensuse-leap": "zypper", "opensuse-tumbleweed": "zypper",
}
PATH_ARGUMENT_COMMANDS = {
    ".", "bash", "cat", "cd", "chmod", "chown", "code", "cp", "du", "file", "find",
    "grep", "head", "less", "ln", "ls", "mkdir", "mktemp", "more", "mv", "nano",
    "nl", "python", "python2", "python3", "readlink", "realpath", "rm", "rmdir",
    "rsync", "scp", "sed", "sh", "source", "stat", "tail", "tar", "touch", "tree",
    "unlink", "unzip", "vim", "vi", "wc", "which", "xargs", "xdg-open", "zip",
}


@lru_cache(maxsize=1)
def system_context():
    values = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as source:
            for line in source:
                key, sep, value = line.rstrip().partition("=")
                if sep:
                    values[key] = value.strip('"').lower()
    except OSError:
        pass
    ids = [values.get("ID", "")] + values.get("ID_LIKE", "").split()
    manager = next((DISTRO_PACKAGE_MANAGER[item] for item in ids if item in DISTRO_PACKAGE_MANAGER), "")
    return values.get("ID", "unknown"), manager


@lru_cache(maxsize=1)
def configured_ssh_hosts():
    """Read concrete SSH aliases only; wildcard patterns are not suggestions."""
    hosts = set()
    config = Path.home() / ".ssh/config"
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return hosts
    for line in lines:
        try:
            fields = shlex.split(line, comments=True)
        except ValueError:
            continue
        if len(fields) < 2 or fields[0].lower() != "host":
            continue
        hosts.update(value for value in fields[1:] if not any(char in value for char in "*!?"))
    return hosts


@lru_cache(maxsize=16)
def git_branches(cwd):
    """Return branch refs already present in this local repository."""
    try:
        result = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes"],
            cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=0.2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    return tuple(dict.fromkeys(
        ref for ref in result.stdout.splitlines()
        if ref and not ref.endswith("/HEAD")
    ))


def words(line):
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return re.findall(r"[^\s]+", line)


def syntax_ok(line):
    # bash -n parses syntax only; it does not run the command.
    try:
        p = subprocess.run(["bash", "-n"], input=line + "\n", text=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=0.25, check=False)
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@lru_cache(maxsize=512)
def candidates(line):
    trailing = bool(line) and line[-1].isspace()
    parsed = words(line)
    prefix = "" if trailing or not parsed else parsed[-1]
    context = parsed if trailing else parsed[:-1]
    segment = context
    for index in range(len(context) - 1, -1, -1):
        if context[index] in OPS:
            segment = context[index + 1:]
            break
    wrappers = {"sudo", "command", "env", "time", "nice", "nohup"}
    command_position = not segment or (segment[0] in wrappers and len(segment) == 1)
    pool = set()
    if command_position:
        for d in os.environ.get("PATH", "").split(os.pathsep):
            if os.path.isdir(d):
                try:
                    pool.update(name for name in os.listdir(d)
                                if os.path.isfile(os.path.join(d, name)) and os.access(os.path.join(d, name), os.X_OK))
                except OSError:
                    pass
        pool.update(("cd", "echo", "exit", "export", "help", "history", "jobs", "pwd", "type", "which"))
    else:
        command = next((w for w in segment if w not in OPS and w not in wrappers and not w.startswith("-")), "")
        command_only = command and len([w for w in segment if w not in wrappers and w not in OPS]) == 1
        if prefix.startswith("-"):
            pool.update(SAFE_FLAGS.get(os.path.basename(command), "").split())
        else:
            if command_only:
                pool.update(SAFE_FLAGS.get(os.path.basename(command), "").split())
            command_name = os.path.basename(command)
            if command_name in {"ssh", "scp", "sftp", "rsync", "ping"}:
                pool.update(configured_ssh_hosts())
            if command_name == "git" and len(segment) >= 2 and segment[1] in {"checkout", "switch", "merge", "rebase"}:
                pool.update(git_branches(os.getcwd()))
            # Offer filesystem entries only in a command context that commonly
            # accepts paths, or when the user has already typed a path-shaped prefix.
            # This avoids suggesting e.g. `gh Downloads/` after `gh `.
            path_context = command_name in PATH_ARGUMENT_COMMANDS or (
                bool(prefix) and (prefix.startswith(("/", "./", "../", "~/")) or "/" in prefix)
            )
            if path_context:
                expanded = os.path.expanduser(prefix or "*")
                for path in glob.glob(expanded + "*"):
                    if not os.path.exists(path):
                        continue
                    rendered = path
                    home = str(Path.home())
                    if prefix.startswith("~") and rendered.startswith(home + os.sep):
                        rendered = "~" + rendered[len(home):]
                    pool.add(rendered.rstrip("/") + ("/" if os.path.isdir(path) else ""))
    # Every accepted suggestion is a single plain shell word. One parse check
    # covers that token class and avoids launching Bash once per candidate.
    syntax_template_valid = syntax_ok(line + "TINY_COMPLETION_TOKEN")
    if not syntax_template_valid:
        return []
    results = []
    for word in pool:
        if not word.startswith(prefix) or word == prefix or not SAFE_WORD.fullmatch(word):
            continue
        # Repeating the immediately previous token is almost never useful and
        # caused the observed `path path path` suggestion loop.
        if trailing and segment and segment[-1] not in OPS and word == segment[-1]:
            continue
        results.append(word)
    distro_id, package_manager = system_context()
    command_context = os.path.basename(segment[0]) if segment else ""
    preferred = "-la" if command_context == "ls" else ""
    def rank(word):
        is_package_manager = command_context == "sudo" and word == package_manager
        is_common_sudo = command_context == "sudo" and word == "systemctl"
        return (not (is_package_manager or is_common_sudo or word == preferred),
                not is_package_manager, word.lower(), word)
    return [line + w[len(prefix):] for w in sorted(results, key=rank)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--line", help="current command line; defaults to stdin")
    ap.add_argument("--limit", type=int, default=1)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    line = args.line if args.line is not None else input()
    ranked = candidates(line)[:max(1, args.limit)]
    for item in ranked:
        print(json.dumps({"line": item}) if args.json else item)


if __name__ == "__main__":
    main()
