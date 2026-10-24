import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["AGNO_TELEMETRY"] = "false"
os.environ.pop("OLLAMA_API_KEY", None)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A scratch $HOME with the XDG dirs inside it."""
    h = tmp_path / "home"
    (h / "Documents").mkdir(parents=True)
    (h / "Downloads").mkdir()
    (h / ".ssh").mkdir()
    (h / ".ssh" / "id_ed25519").write_text("PRIVATE")
    (h / ".netrc").write_text("machine x password y")
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(h / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(h / ".local" / "share"))
    monkeypatch.delenv("LINGMO_ASSISTANT_NOTES_DIR", raising=False)
    # No app actions unless a test installs manifests (lingmo-intents)
    (h / "intents").mkdir()
    monkeypatch.setenv("LINGMO_INTENTS_DIRS", str(h / "intents"))
    monkeypatch.setenv("LINGMO_INTENTS_LOCALE", "pt_BR")
    from lingmo_assistant import intents
    intents.reset()
    return h


def write_conf(home: Path, text: str) -> Path:
    p = home / ".config" / "lingmoos" / "ai.conf"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def conf(home):
    def make(**keys):
        lines = ["[General]", "provider=ollama", "model=fake:1b"]
        for k, v in keys.items():
            if isinstance(v, bool):
                v = "true" if v else "false"
            lines.append("%s=%s" % (k, v))
        return write_conf(home, "\n".join(lines) + "\n")
    return make
