"""Fixed allowlist of read-only commands for the shell_read tool.

The model sends one command line; it is split with shlex (no shell ever runs
it), checked against the allowlist below with per-command argument rules, and
executed through sandbox.run. Anything unknown, any shell syntax, any argument
outside the rules is refused.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil

from . import paths, sandbox

# "~" is allowed (expanded for path arguments), quotes are handled by shlex
FORBIDDEN_CHARS = set(";|&$`<>(){}\n\r\\!*?")

UNIT = re.compile(r"^(?!-)[A-Za-z0-9@_.:-]{1,128}$")
PACKAGE = re.compile(r"^(?!-)[a-z0-9@._+-]{1,128}$")
SEARCH_TERM = re.compile(r"^(?!-)[A-Za-z0-9._+-]{1,64}$")
COLUMNS = re.compile(r"^[A-Za-z0-9_%,:-]{1,200}$")


class CommandError(Exception):
    """Refusal with a pt-BR message for the model."""


def _flags(args: list[str], allowed: set[str], cmd: str) -> list[str]:
    for a in args:
        if a not in allowed:
            raise CommandError(f"Argumento não permitido para {cmd}: {a}")
    return args


def _short_flags(arg: str, letters: str) -> bool:
    return arg.startswith("-") and not arg.startswith("--") and len(arg) > 1 \
        and all(c in letters for c in arg[1:])


def _int(value: str, low: int, high: int, what: str) -> str:
    if not value.isdigit() or not low <= int(value) <= high:
        raise CommandError(f"{what} inválido.")
    return value


class Validator:
    """Turns validated args into the final argument list (paths resolved)."""

    def __init__(self, policy: paths.PathPolicy):
        self.policy = policy

    def path(self, raw: str) -> str:
        try:
            return str(self.policy.check_read(raw))
        except paths.PolicyError as exc:
            raise CommandError(str(exc)) from exc

    # Each returns the argument list to run, or raises CommandError
    def lscpu(self, a):
        return _flags(a, {"-e", "-J", "--extended", "--json"}, "lscpu")

    def lsblk(self, a):
        out, i = [], 0
        while i < len(a):
            arg = a[i]
            if arg in ("-o", "--output") and i + 1 < len(a) and COLUMNS.match(a[i + 1]):
                out += [arg, a[i + 1]]
                i += 2
                continue
            if _short_flags(arg, "fdJbalpmS") or arg in ("--fs", "--json", "--nodeps", "--all"):
                out.append(arg)
                i += 1
                continue
            raise CommandError(f"Argumento não permitido para lsblk: {arg}")
        return out

    def free(self, a):
        for arg in a:
            if not (_short_flags(arg, "hmgbwtk") or arg in ("--human", "--wide", "--total", "--si")):
                raise CommandError(f"Argumento não permitido para free: {arg}")
        return a

    def df(self, a):
        out = []
        for arg in a:
            if _short_flags(arg, "hHTlia") or arg in ("--human-readable", "--print-type", "--local", "--inodes"):
                out.append(arg)
            elif not arg.startswith("-"):
                out.append(self.path(arg))
            else:
                raise CommandError(f"Argumento não permitido para df: {arg}")
        return out

    def uname(self, a):
        for arg in a:
            if not _short_flags(arg, "asnrvmpio"):
                raise CommandError(f"Argumento não permitido para uname: {arg}")
        return a

    def uptime(self, a):
        return _flags(a, {"-p", "-s", "--pretty", "--since"}, "uptime")

    def ps(self, a):
        out, i = [], 0
        while i < len(a):
            arg = a[i]
            if arg in ("aux", "-e", "-A", "-ef", "-eF", "-ely", "--no-headers", "-H"):
                out.append(arg)
            elif arg in ("-o", "-eo") and i + 1 < len(a) and COLUMNS.match(a[i + 1]):
                out += [arg, a[i + 1]]
                i += 1
            elif arg.startswith("--sort=") and COLUMNS.match(arg[7:]):
                out.append(arg)
            elif arg == "--sort" and i + 1 < len(a) and COLUMNS.match(a[i + 1]):
                out += [arg, a[i + 1]]
                i += 1
            else:
                raise CommandError(f"Argumento não permitido para ps: {arg}")
            i += 1
        return out

    def sensors(self, a):
        return _flags(a, {"-j", "-f", "-A"}, "sensors")

    def nvidia_smi(self, a):
        if not a or a in (["-L"], ["-q"]):
            return a
        if len(a) == 3 and a[0] == "-q" and a[1] == "-d" and re.match(r"^[A-Z_,]{1,80}$", a[2]):
            return a
        out = []
        for arg in a:
            if re.match(r"^--query-(gpu|compute-apps)=[a-z0-9_.,]{1,400}$", arg) \
                    or re.match(r"^--format=csv(,noheader)?(,nounits)?$", arg):
                out.append(arg)
            else:
                raise CommandError(f"Argumento não permitido para nvidia-smi: {arg}")
        return out

    def lspci(self, a):
        for arg in a:
            if not (_short_flags(arg, "knvm") or arg == "-nn" or arg == "-mm"):
                raise CommandError(f"Argumento não permitido para lspci: {arg}")
        return a

    def lsusb(self, a):
        return _flags(a, {"-t", "-v", "--tree"}, "lsusb")

    def pacman(self, a):
        if not a:
            raise CommandError("Use: pacman -Q | -Qi pacote | -Qs termo | -Ss termo | -Si pacote | -Ql pacote")
        op = a[0]
        rest = a[1:]
        if op in ("-Q", "-Qe", "-Qm", "-Qn", "-Qdt", "-Qu"):
            if len(rest) > 1 or (rest and not PACKAGE.match(rest[0])):
                raise CommandError("Pacote inválido.")
            if op == "-Qu" and rest:
                raise CommandError("Use só pacman -Qu.")
            return a
        if op in ("-Qi", "-Si", "-Ql"):
            if len(rest) != 1 or not PACKAGE.match(rest[0]):
                raise CommandError("Informe um pacote.")
            return a
        if op in ("-Qs", "-Ss"):
            if len(rest) != 1 or not SEARCH_TERM.match(rest[0]):
                raise CommandError("Informe um termo de busca simples.")
            return a
        raise CommandError(f"Operação do pacman não permitida: {op}")

    def systemctl(self, a):
        rest = list(a)
        out = ["--no-pager"]
        if rest and rest[0] == "--user":
            out.append(rest.pop(0))
        if not rest:
            raise CommandError("Use: systemctl status UNIDADE | list-units | --failed | list-timers")
        verb = rest.pop(0)
        if verb in ("status", "is-active", "is-enabled", "is-failed"):
            if verb != "status" and len(rest) != 1:
                raise CommandError("Informe uma unidade.")
            if len(rest) > 1 or (rest and not UNIT.match(rest[0])) or (rest and rest[0].startswith("-")):
                raise CommandError("Unidade inválida.")
            return out + [verb] + rest
        if verb in ("list-units", "list-timers", "list-sockets", "--failed", "list-unit-files"):
            for arg in rest:
                if not re.match(r"^--(type|state)=[a-z,-]{1,60}$", arg) and arg != "--all":
                    raise CommandError(f"Argumento não permitido para systemctl: {arg}")
            return out + [verb] + rest
        raise CommandError(f"Operação do systemctl não permitida: {verb}")

    def journalctl(self, a):
        out = ["--no-pager"]
        has_n = False
        i = 0
        while i < len(a):
            arg = a[i]
            nxt = a[i + 1] if i + 1 < len(a) else None
            if arg in ("--user", "-b", "--boot", "-k", "--dmesg", "-r", "--reverse"):
                out.append(arg)
            elif arg in ("-n", "--lines") and nxt is not None:
                out += ["-n", _int(nxt, 1, 500, "Número de linhas")]
                has_n = True
                i += 1
            elif re.match(r"^-n\d{1,3}$", arg):
                out += ["-n", _int(arg[2:], 1, 500, "Número de linhas")]
                has_n = True
            elif arg in ("-p", "--priority") and nxt is not None and re.match(
                    r"^([0-7]|emerg|alert|crit|err|warning|notice|info|debug)$", nxt):
                out += ["-p", nxt]
                i += 1
            elif arg in ("-u", "--unit", "--user-unit") and nxt is not None and UNIT.match(nxt) \
                    and not nxt.startswith("-"):
                out += [arg, nxt]
                i += 1
            elif arg in ("-o", "--output") and nxt in ("short", "cat", "short-iso", "short-precise"):
                out += ["-o", nxt]
                i += 1
            elif arg == "--since" and nxt in ("today", "yesterday", "-1h", "-24h", "-2h", "-30min"):
                out += ["--since", nxt]
                i += 1
            else:
                raise CommandError(f"Argumento não permitido para journalctl: {arg}")
            i += 1
        if not has_n:
            out += ["-n", "100"]   # never dump the whole journal
        return out

    def hostnamectl(self, a):
        return _flags(a, {"status"}, "hostnamectl")

    def timedatectl(self, a):
        return _flags(a, {"status"}, "timedatectl")

    def du(self, a):
        out, targets = [], 0
        i = 0
        while i < len(a):
            arg = a[i]
            if _short_flags(arg, "shc"):
                out.append(arg)
            elif re.match(r"^--max-depth=\d$", arg):
                out.append(arg)
            elif arg == "-d" and i + 1 < len(a):
                out += ["-d", _int(a[i + 1], 0, 3, "Profundidade")]
                i += 1
            elif not arg.startswith("-"):
                out.append(self.path(arg))
                targets += 1
            else:
                raise CommandError(f"Argumento não permitido para du: {arg}")
            i += 1
        if not targets:
            raise CommandError("Informe uma pasta permitida para o du.")
        return out

    def ls(self, a):
        out, targets = [], 0
        for arg in a:
            if _short_flags(arg, "lahtrS1RFdi"):
                out.append(arg)
            elif not arg.startswith("-"):
                out.append(self.path(arg))
                targets += 1
            else:
                raise CommandError(f"Argumento não permitido para ls: {arg}")
        if not targets:
            raise CommandError("Informe uma pasta permitida para o ls.")
        if any("R" in f for f in out if f.startswith("-")):
            raise CommandError("ls recursivo não é permitido; use a busca de arquivos.")
        return out

    def no_args(self, name):
        def check(a):
            if a:
                raise CommandError(f"{name} não aceita argumentos aqui.")
            return a
        return check

    def lsmem(self, a):
        return _flags(a, {"--summary", "-b"}, "lsmem")

    def swapon(self, a):
        return _flags(a, {"--show"}, "swapon") or ["--show"]

    def findmnt(self, a):
        return _flags(a, {"-l", "-D", "--df", "-t", "--real"}, "findmnt")

    def flatpak(self, a):
        if a in (["list"], ["list", "--app"], ["list", "--runtime"], ["--version"]):
            return a
        raise CommandError("Use: flatpak list [--app|--runtime]")


def allowed_commands(v: Validator) -> dict:
    return {
        "lscpu": v.lscpu, "lsblk": v.lsblk, "free": v.free, "df": v.df, "uname": v.uname,
        "uptime": v.uptime, "ps": v.ps, "sensors": v.sensors,
        "nvidia-smi": v.nvidia_smi, "lspci": v.lspci, "lsusb": v.lsusb, "pacman": v.pacman,
        "systemctl": v.systemctl, "journalctl": v.journalctl, "hostnamectl": v.hostnamectl,
        "timedatectl": v.timedatectl, "du": v.du, "ls": v.ls, "lsmem": v.lsmem,
        "swapon": v.swapon, "findmnt": v.findmnt, "flatpak": v.flatpak,
        "lsmod": v.no_args("lsmod"), "nproc": v.no_args("nproc"), "whoami": v.no_args("whoami"),
        "date": v.no_args("date"), "hostname": v.no_args("hostname"), "who": v.no_args("who"),
        "locale": v.no_args("locale"),
    }


def command_names() -> list[str]:
    return sorted(allowed_commands(Validator(paths.PathPolicy([]))).keys())


def parse(command_line: str, policy: paths.PathPolicy, which=None) -> list[str]:
    """Validated argv (absolute program path first) or CommandError."""
    if not isinstance(command_line, str) or not command_line.strip():
        raise CommandError("Comando vazio.")
    if len(command_line) > 400:
        raise CommandError("Comando longo demais.")
    bad = sorted({c for c in command_line if c in FORBIDDEN_CHARS or (ord(c) < 32 and c != " ")})
    if bad:
        raise CommandError("Sintaxe de shell não é permitida (só um comando simples, sem "
                           + " ".join(repr(c) for c in bad) + ").")
    try:
        parts = shlex.split(command_line, comments=False, posix=True)
    except ValueError as exc:
        raise CommandError("Comando mal formado.") from exc
    if not parts:
        raise CommandError("Comando vazio.")
    name = parts[0]
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    commands = allowed_commands(Validator(policy))
    if name not in commands:
        raise CommandError(f"Comando não permitido: {name}. Permitidos: " + ", ".join(sorted(commands)))
    args = commands[name](parts[1:])
    which = which or (lambda n: shutil.which(n, path="/usr/bin:/bin:/usr/sbin:/sbin"))
    program = which(name)
    if not program:
        raise CommandError(f"O programa {name} não está instalado.")
    return [program] + list(args)


def run(command_line: str, policy: paths.PathPolicy) -> tuple[bool, str]:
    argv = parse(command_line, policy)
    result = sandbox.run(argv, devices=os.path.basename(argv[0]) == "nvidia-smi")
    text = result.output
    if result.timed_out:
        text += "\n[interrompido: passou de %d s]" % sandbox.TIMEOUT
    if result.truncated:
        text += "\n[saída cortada em %d KB]" % (sandbox.OUTPUT_LIMIT // 1024)
    return result.returncode == 0 and not result.timed_out, text
