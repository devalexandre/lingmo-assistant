"""Desktop actions: notifications, alarms and timers in Lingmo Clock, opening
apps or https addresses, screenshots.

D-Bus calls go through `gdbus` (argv, no shell), so the engine needs no D-Bus
binding for one-shot calls.
"""
from __future__ import annotations

import configparser
import datetime as dt
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

TIMEOUT = 15


class DesktopError(Exception):
    pass


def _gvariant_str(value: str) -> str:
    """A GVariant text literal for gdbus (single-quoted, escaped)."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"


def gdbus_call(dest: str, path: str, method: str, *args: str, timeout: int = TIMEOUT) -> str:
    gdbus = shutil.which("gdbus")
    if not gdbus:
        raise DesktopError("gdbus não está instalado.")
    argv = [gdbus, "call", "--session", "--dest", dest, "--object-path", path, "--method", method,
            "--timeout", str(timeout), *args]
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout + 5,
                              close_fds=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DesktopError("O serviço %s não respondeu." % dest) from exc
    if proc.returncode != 0:
        raise DesktopError("O serviço %s não respondeu." % dest)
    return proc.stdout.decode("utf-8", "replace").strip()


# ------------------------------------------------------------------ notifications

def notify(title: str, body: str = "", icon: str = "lingmo-assistant", replaces: int = 0,
           timeout_ms: int = -1, actions: list[str] | None = None) -> int:
    acts = ("[" + ", ".join(_gvariant_str(a) for a in actions) + "]") if actions else "@as []"
    out = gdbus_call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                     "org.freedesktop.Notifications.Notify",
                     _gvariant_str("Assistente"), str(int(replaces)), _gvariant_str(icon),
                     _gvariant_str(title[:200]), _gvariant_str(body[:2000]), acts,
                     "{'desktop-entry': <'lingmo-assistant'>}", "@i %d" % int(timeout_ms))   # "@i": "-1" isn't an option
    m = re.search(r"(?:uint32\s+)?(\d+)\s*,?\s*\)\s*$", out)     # "(uint32 7,)"
    return int(m[1]) if m else 0


# ------------------------------------------------------------------ clock

CLOCK = ("com.lingmo.Clock", "/Clock", "com.lingmo.Clock")


def parse_alarm_time(value: str) -> str:
    m = re.fullmatch(r"\s*(\d{1,2})(?::|h)?(\d{2})?\s*", str(value or ""))
    if not m:
        raise DesktopError("Hora do alarme inválida (use HH:MM).")
    h, mi = int(m[1]), int(m[2] or 0)
    if h > 23 or mi > 59:
        raise DesktopError("Hora do alarme inválida (use HH:MM).")
    return "%02d:%02d" % (h, mi)


def add_alarm(time_text: str, label: str) -> str:
    """Lingmo Clock's D-Bus addAlarm (the service is D-Bus activated, so the clock
    starts in the background if needed); an older clock without it gets the
    `--add-alarm` command line."""
    when = parse_alarm_time(time_text)
    label = " ".join(str(label or "Alarme").split())[:100] or "Alarme"
    try:
        gdbus_call(CLOCK[0], CLOCK[1], CLOCK[2] + ".addAlarm", _gvariant_str(when), _gvariant_str(label))
    except DesktopError:
        tool = shutil.which("lingmo-clock")
        if not tool:
            raise DesktopError("O Relógio do Lingmo não está instalado.") from None
        _spawn([tool, "--add-alarm", when, label])
    return when


def start_timer(minutes, label: str) -> int:
    try:
        seconds = int(round(float(minutes) * 60))
    except (TypeError, ValueError):
        raise DesktopError("Duração do timer inválida.") from None
    if not 1 <= seconds <= 24 * 3600:
        raise DesktopError("O timer vai de 1 segundo a 24 horas.")
    label = " ".join(str(label or "Timer").split())[:100] or "Timer"
    try:
        gdbus_call(CLOCK[0], CLOCK[1], CLOCK[2] + ".startTimer", str(seconds), _gvariant_str(label))
    except DesktopError:
        tool = shutil.which("lingmo-clock")
        if not tool:
            raise DesktopError("O Relógio do Lingmo não está instalado.") from None
        _spawn([tool, "--timer", str(seconds)])
    return seconds


# ------------------------------------------------------------------ open

APP_DIRS = ["/usr/share/applications", "/usr/local/share/applications"]


def _desktop_dirs() -> list[Path]:
    home = Path(os.path.expanduser("~"))
    dirs = [home / ".local/share/applications"] + [Path(d) for d in APP_DIRS]
    dirs += [Path("/var/lib/flatpak/exports/share/applications")]
    return dirs


def find_app(name: str) -> Path | None:
    key = name.strip().lower().removesuffix(".desktop")
    if not re.fullmatch(r"[\w.\- ]{1,100}", key):
        return None
    candidates = []
    for d in _desktop_dirs():
        if not d.is_dir():
            continue
        exact = d / (key + ".desktop")
        if exact.is_file():
            return exact
        candidates += list(d.glob("*.desktop"))
    for p in candidates:
        cp = configparser.RawConfigParser(strict=False, interpolation=None)
        try:
            cp.read(p, encoding="utf-8")
            entry = cp["Desktop Entry"]
        except (configparser.Error, KeyError, UnicodeDecodeError):
            continue
        names = [entry.get("Name", ""), entry.get("Name[pt_BR]", "")]
        if any(n.strip().lower() == key for n in names if n) and entry.get("NoDisplay", "false") != "true":
            return p
    return None


def app_argv(desktop: Path) -> list[str]:
    cp = configparser.RawConfigParser(strict=False, interpolation=None)
    cp.read(desktop, encoding="utf-8")
    exec_line = cp["Desktop Entry"].get("Exec", "")
    argv = [a for a in shlex.split(exec_line) if not re.fullmatch(r"%[a-zA-Z]", a)]
    if not argv:
        raise DesktopError("Este aplicativo não pode ser aberto.")
    return argv


def open_target(target: str) -> str:
    """Opens an installed app (by desktop id or name) or an https:// address."""
    target = str(target or "").strip()
    if re.match(r"^https://[^\s]+$", target, re.I) or re.match(r"^mailto:[^\s]+$", target, re.I):
        _spawn(["xdg-open", target])
        return target
    if "://" in target or target.startswith(("/", "~", "file:")):
        raise DesktopError("Só abro aplicativos instalados e endereços https://.")
    desktop = find_app(target)
    if desktop is None:
        raise DesktopError("Aplicativo não encontrado: %s" % target)
    _spawn(app_argv(desktop))
    return desktop.stem


def _spawn(argv: list[str]) -> None:
    if os.environ.get("LINGMO_ASSISTANT_DRY_DESKTOP"):
        # Tests: record instead of launching anything
        with open(os.environ["LINGMO_ASSISTANT_DRY_DESKTOP"], "a", encoding="utf-8") as f:
            f.write(" ".join(argv) + "\n")
        return
    try:
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except OSError as exc:
        raise DesktopError("Não foi possível abrir: %s" % argv[0]) from exc


# ------------------------------------------------------------------ screenshot

def screenshot(folder: Path) -> Path:
    tool = shutil.which("lingmo-screenshot")
    if not tool:
        raise DesktopError("O Lingmo Screenshots não está instalado.")
    name = "Captura %s.png" % dt.datetime.now().strftime("%Y-%m-%d %H-%M-%S")
    target = folder / name
    try:
        subprocess.run([tool, "full", "--path", str(target)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=30, close_fds=True)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DesktopError("A captura de tela falhou.") from exc
    if not target.is_file():
        raise DesktopError("A captura de tela falhou.")
    return target
