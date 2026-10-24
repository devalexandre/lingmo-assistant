"""The user's assistant documents in ~/.local/share/lingmo/assistant:

    workflows/<id>.json          versioned workflow documents (see flows/graph.py)
    workflows/.history/<id>/     the previous 10 revisions of each workflow
    agents/<id>.json             custom agents (see agents.py)
    runs/<flow id>/<run id>.json run history with a per-node log
    approvals.json               capability approvals (never part of a workflow file,
                                 so an imported file can't approve itself)

Removing a workflow or agent moves its file to a `.trash` folder next to it:
the assistant never destroys documents.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import config

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
HISTORY_KEEP = 10
RUNS_KEEP = 50
_lock = threading.RLock()


def root() -> Path:
    return config.user_dir()


def _dir(name: str) -> Path:
    d = root() / name
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def write_json(path: Path, data, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


class DocumentStore:
    """One folder of JSON documents keyed by id."""

    def __init__(self, folder: str, normalize: Callable[[dict], dict]):
        self.folder = folder
        self.normalize = normalize

    def path(self, doc_id: str) -> Path:
        if not ID_RE.match(doc_id or ""):
            raise ValueError("Identificador inválido.")
        return _dir(self.folder) / (doc_id + ".json")

    def list(self) -> list[dict]:
        out = []
        for p in sorted(_dir(self.folder).glob("*.json")):
            data = read_json(p)
            if not isinstance(data, dict):
                continue
            try:
                out.append(self.normalize(data))
            except ValueError:
                continue
        return out

    def get(self, doc_id: str) -> Optional[dict]:
        data = read_json(self.path(doc_id))
        if not isinstance(data, dict):
            return None
        try:
            return self.normalize(data)
        except ValueError:
            return None

    def mtime(self) -> float:
        d = _dir(self.folder)
        latest = d.stat().st_mtime
        for p in d.glob("*.json"):
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                pass
        return latest

    def save(self, doc: dict) -> dict:
        with _lock:
            doc = self.normalize(doc)
            path = self.path(doc["id"])
            old = read_json(path)
            if isinstance(old, dict):
                hist = _dir(self.folder) / ".history" / doc["id"]
                hist.mkdir(parents=True, exist_ok=True, mode=0o700)
                write_json(hist / ("%d.json" % int(old.get("revision") or 0)), old)
                revs = sorted(hist.glob("*.json"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
                for extra in revs[:-HISTORY_KEEP]:
                    extra.unlink()
                doc["revision"] = int(old.get("revision") or 0) + 1
                doc["created"] = old.get("created") or time.time()
            else:
                doc["revision"] = max(1, int(doc.get("revision") or 0) + 1)
                doc["created"] = doc.get("created") or time.time()
            doc["updated"] = time.time()
            write_json(path, doc)
            return doc

    def remove(self, doc_id: str) -> bool:
        """Moves the document to .trash (recoverable)."""
        with _lock:
            path = self.path(doc_id)
            if not path.exists():
                return False
            trash = _dir(self.folder) / ".trash"
            trash.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.move(str(path), str(trash / ("%s-%d.json" % (doc_id, int(time.time())))))
            return True


# ------------------------------------------------------------------ approvals

def approvals_path() -> Path:
    return root() / "approvals.json"


def approvals() -> dict:
    data = read_json(approvals_path(), {})
    return data if isinstance(data, dict) else {}


def approval(flow_id: str) -> dict:
    a = approvals().get(flow_id)
    return a if isinstance(a, dict) else {}


def set_approval(flow_id: str, cap_hash: str, dont_ask: bool, account_note: str = "") -> dict:
    with _lock:
        data = approvals()
        entry = {"hash": cap_hash, "approved_at": time.time(), "dont_ask": bool(dont_ask)}
        data[flow_id] = entry
        write_json(approvals_path(), data)
        return entry


def set_dont_ask(flow_id: str, dont_ask: bool) -> None:
    with _lock:
        data = approvals()
        if flow_id in data and isinstance(data[flow_id], dict):
            data[flow_id]["dont_ask"] = bool(dont_ask)
            write_json(approvals_path(), data)


# ------------------------------------------------------------------ runs

def runs_dir(flow_id: str) -> Path:
    if not ID_RE.match(flow_id or ""):
        raise ValueError("Identificador inválido.")
    return _dir("runs") / flow_id


def save_run(run: dict) -> None:
    d = runs_dir(run["flow_id"])
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_json(d / (run["id"] + ".json"), run)


def prune_runs(flow_id: str) -> None:
    d = runs_dir(flow_id)
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for extra in files[:-RUNS_KEEP]:
        try:
            extra.unlink()
        except OSError:
            pass


def list_runs(flow_id: str, limit: int = 50) -> list[dict]:
    d = runs_dir(flow_id)
    if not d.exists():
        return []
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for p in files:
        r = read_json(p)
        if isinstance(r, dict):
            out.append({k: r.get(k) for k in ("id", "flow_id", "flow_name", "status", "mode", "started",
                                               "ended", "trigger", "error", "source")})
    return out


def get_run(flow_id: str, run_id: str) -> Optional[dict]:
    if not ID_RE.match(run_id or ""):
        return None
    r = read_json(runs_dir(flow_id) / (run_id + ".json"))
    return r if isinstance(r, dict) else None
