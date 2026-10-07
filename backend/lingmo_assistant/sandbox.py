"""Runs read-only programs inside a bubblewrap sandbox.

The whole filesystem is mounted read-only, every blocked area that exists is
hidden (empty tmpfs over directories, /dev/null over files), there is no
network, the process gets its own session (no terminal injection) and dies with
the engine. argv only: never a shell.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config, paths

TIMEOUT = 10          # seconds
OUTPUT_LIMIT = 32 * 1024


class SandboxError(Exception):
    pass


@dataclass
class Result:
    returncode: int
    output: str
    truncated: bool
    timed_out: bool = False


def bwrap_path() -> str | None:
    override = os.environ.get("LINGMO_ASSISTANT_BWRAP")
    if override:
        return override if os.access(override, os.X_OK) else None
    return shutil.which("bwrap", path="/usr/bin:/bin")


def mask_args(home: Path | None = None) -> list[str]:
    """Hide every blocked location that exists."""
    args: list[str] = []
    seen: set[str] = set()
    for p in paths.blocked_paths(home):
        key = str(p)
        if key in seen or not os.path.lexists(p):
            continue
        seen.add(key)
        if os.path.islink(p):
            continue   # its resolved target is in the list too and gets masked
        if p.is_dir():
            args += ["--tmpfs", key]
        else:
            args += ["--ro-bind", "/dev/null", key]
    return args


def build_argv(command: list[str], home: Path | None = None, bwrap: str | None = None,
               devices: bool = False) -> list[str]:
    """devices=True exposes the host /dev (nvidia-smi needs the GPU nodes);
    otherwise the program gets a minimal private /dev."""
    if not command or not os.path.isabs(command[0]):
        raise SandboxError("Comando precisa de caminho absoluto.")
    bwrap = bwrap or bwrap_path()
    if not bwrap:
        raise SandboxError("O bubblewrap (bwrap) não está instalado; por segurança o assistente "
                           "não executa comandos sem ele. Instale o pacote bubblewrap.")
    home = home or config.home()
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": str(home),
        "TERM": "dumb",
        "SYSTEMD_PAGER": "",
        "SYSTEMD_COLORS": "0",
        "NO_COLOR": "1",
    }
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        env["XDG_RUNTIME_DIR"] = runtime   # systemctl/journalctl --user
    dbus = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if dbus and dbus.startswith("unix:path="):
        env["DBUS_SESSION_BUS_ADDRESS"] = dbus
    argv = [bwrap,
            "--ro-bind", "/", "/",
            *(["--dev-bind", "/dev", "/dev"] if devices else ["--dev", "/dev"]),
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--unshare-net",
            "--unshare-ipc",
            "--unshare-uts",
            "--die-with-parent",
            "--new-session",
            "--cap-drop", "ALL",
            "--clearenv"]
    for key, value in env.items():
        argv += ["--setenv", key, value]
    argv += mask_args(home)
    argv += ["--chdir", "/", "--"]
    argv += command
    return argv


def run(command: list[str], timeout: int = TIMEOUT, limit: int = OUTPUT_LIMIT,
        devices: bool = False) -> Result:
    argv = build_argv(command, devices=devices)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, close_fds=True, start_new_session=True)
    except OSError as exc:
        raise SandboxError("Não foi possível executar o comando.") from exc
    try:
        out, _ = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate()
        timed_out = True
    truncated = len(out) > limit
    text = out[:limit].decode("utf-8", errors="replace")
    return Result(proc.returncode, text, truncated, timed_out)
