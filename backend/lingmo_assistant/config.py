"""Reads ~/.config/lingmoos/ai.conf (written by Lingmo Settings with QSettings).

The file is re-read for every message, so changes made in Settings while the
assistant is open apply to the next question. Missing values mean the defaults
of docs/assistant-contract.md.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

READ = "read"
WRITE = "write"

# Contract tool ids -> (group, checked by default)
TOOLS: dict[str, tuple[str, bool]] = {
    "system_info": (READ, True),
    "shell_read": (READ, True),
    "read_files": (READ, True),
    "search_files": (READ, True),
    "notes_read": (READ, True),
    "calendar_read": (READ, True),
    "web": (READ, False),
    "mail_read": (READ, True),
    "notes_write": (WRITE, True),
    "calendar_write": (WRITE, True),
    "files_write": (WRITE, True),
    "mail_write": (WRITE, True),
    "alarms_write": (WRITE, True),
    "desktop_actions": (WRITE, True),
}
DEFAULT_TOOLS = [tid for tid, (_, on) in TOOLS.items() if on]

# Folder names under $HOME offered by default (only the ones that exist)
DEFAULT_FOLDER_NAMES = ["Documents", "Documentos", "Downloads", "Desktop",
                        "Área de Trabalho", "Pictures", "Imagens"]


def home() -> Path:
    return Path(os.path.expanduser("~"))


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(home() / ".config")
    return Path(base) / "lingmoos" / "ai.conf"


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or str(home() / ".local" / "share"))


def data_dir() -> Path:
    """The engine's private state (chat history database)."""
    return data_home() / "lingmo-assistant"


def user_dir() -> Path:
    """The user's own assistant documents: workflows, agents, run history
    (~/.local/share/lingmo/assistant)."""
    return data_home() / "lingmo" / "assistant"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(home() / ".local" / "state")
    return Path(base) / "lingmo-assistant"


# ------------------------------------------------------------------ QSettings INI

def _unescape_ini(raw: str) -> list[str] | str:
    """Decodes a QSettings INI value: plain string, quoted string or string list.

    Mirrors QSettingsPrivate::iniUnescapedStringList: unquoted commas split a
    list, "..." quotes protect commas/spaces, backslash escapes inside.
    """
    raw = raw.strip()
    if raw == "@Invalid()":
        return []
    items: list[str] = []
    current: list[str] = []
    in_quotes = False
    saw_comma = False
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            i += 1
            if nxt in "abfnrtv":
                current.append({"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r",
                                "t": "\t", "v": "\v"}[nxt])
            elif nxt == "x":
                hexdigits = ""
                while i + 1 < len(raw) and len(hexdigits) < 4 and raw[i + 1] in "0123456789abcdefABCDEF":
                    hexdigits += raw[i + 1]
                    i += 1
                if hexdigits:
                    current.append(chr(int(hexdigits, 16)))
            elif nxt == "0":
                current.append("\0")
            else:
                current.append(nxt)
        elif ch == "," and not in_quotes:
            saw_comma = True
            items.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    last = "".join(current)
    if saw_comma:
        items.append(last.strip())
        return items
    value = last if '"' in raw else last.strip()
    if value.startswith("@String(") and value.endswith(")"):
        value = value[len("@String("):-1]
    return value


def read_ini(path: Path) -> dict[str, list[str] | str]:
    """Top-level ([General]) keys plus "group/key" for the others."""
    values: dict[str, list[str] | str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    group = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            group = line[1:-1].strip()
            if group.lower() == "general":
                group = ""
            continue
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        key = key.strip().replace("%2F", "/")
        values[(group + "/" + key) if group else key] = _unescape_ini(raw)
    return values


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, list):
        value = value[0] if value else ""
    if not isinstance(value, str) or value == "":
        return default
    return value.strip().lower() in ("true", "1", "yes", "on")


def _as_list(value) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [v for v in value if v]
    return [value] if value else []


# ------------------------------------------------------------------ config

@dataclass
class Config:
    provider: str = "ollama"
    model: str = ""
    think: bool = False
    read: bool = True
    write: bool = False
    tools: set[str] = field(default_factory=lambda: set(DEFAULT_TOOLS))
    folders: list[Path] = field(default_factory=list)
    # Voice (assistant_voice_* keys; see docs/assistant-contract.md)
    voice_replies: bool = False
    tts_voice: str = ""          # "" = automatic (piper voice for the locale, else espeak-ng)
    tts_rate: float = 1.0        # 0.5 (slow) .. 2.0 (fast)
    stt_model: str = ""          # whisper model name; "" = fast automatic choice
    subtitle_model: str = ""     # Lingmo Studio / Settings transcription model
    subtitle_language: str = ""

    def group_allowed(self, group: str) -> bool:
        return self.read if group == READ else self.write

    def tool_enabled(self, tool_id: str) -> bool:
        """A tool runs only when checked AND its group permission is on."""
        if tool_id not in TOOLS or tool_id not in self.tools:
            return False
        group = TOOLS[tool_id][0]
        return self.read if group == READ else self.write

    def denial(self, tool_id: str) -> str:
        """Why a tool can't run, in pt-BR, for the model to relay."""
        if tool_id not in TOOLS:
            return "Ferramenta desconhecida."
        group = TOOLS[tool_id][0]
        if group == READ and not self.read:
            return "A permissão de leitura do assistente está desligada em Configurações › IA."
        if group == WRITE and not self.write:
            return "A permissão de escrita do assistente está desligada em Configurações › IA."
        return "Esta ferramenta está desmarcada em Configurações › IA."

    def enabled_tools(self) -> list[str]:
        return [tid for tid in TOOLS if self.tool_enabled(tid)]


def default_folders() -> list[Path]:
    h = home()
    return [h / name for name in DEFAULT_FOLDER_NAMES if (h / name).is_dir()]


def load(path: Path | None = None) -> Config:
    values = read_ini(path or config_path())

    def get(key):
        # Older Settings builds stored the AI keys under an [ai] group
        return values.get(key, values.get("ai/" + key))

    cfg = Config()
    provider = get("provider")
    cfg.provider = (provider if isinstance(provider, str) and provider else "ollama")
    model = get("model")
    cfg.model = model if isinstance(model, str) else ""
    cfg.think = _as_bool(get("think"), False)
    cfg.read = _as_bool(get("assistant_read"), True)
    cfg.write = _as_bool(get("assistant_write"), False)
    tools = _as_list(get("assistant_tools"))
    cfg.tools = set(DEFAULT_TOOLS) if tools is None else {t.strip() for t in tools if t.strip() in TOOLS}
    folders = _as_list(get("assistant_folders"))
    if folders is None:
        cfg.folders = default_folders()
    else:
        out = []
        for f in folders:
            p = Path(os.path.expanduser(f.strip()))
            if p.is_absolute() and p not in out:
                out.append(p)
        cfg.folders = out
    cfg.voice_replies = _as_bool(get("assistant_voice_replies"), False)
    voice = get("assistant_tts_voice")
    cfg.tts_voice = voice.strip() if isinstance(voice, str) else ""
    try:
        rate = float(get("assistant_tts_rate") or 1.0)
    except (TypeError, ValueError):
        rate = 1.0
    cfg.tts_rate = min(2.0, max(0.5, rate))
    for attr, key in (("stt_model", "assistant_stt_model"), ("subtitle_model", "subtitle_model"),
                      ("subtitle_language", "subtitle_language")):
        value = get(key)
        setattr(cfg, attr, value.strip() if isinstance(value, str) else "")
    return cfg
