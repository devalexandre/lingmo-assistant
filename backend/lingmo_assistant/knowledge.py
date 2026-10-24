"""Read-only knowledge search for agents (simple local RAG).

The agent's knowledge folders must be inside the allowed folders of Settings ›
IA (blocked areas stay blocked). Text documents are split in chunks and
embedded with a local Ollama embedding model (nomic-embed-text or another
installed one); the index lives in the engine's private data folder and is
updated incrementally by modification time. Without an embedding model the
search falls back to keyword scoring.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from pathlib import Path
from typing import Optional

from . import config, documents, paths, store

log = logging.getLogger("lingmo_assistant.knowledge")

CHUNK = 1200
OVERLAP = 150
MAX_FILES = 400
MAX_CHUNKS = 3000
EMBED_MODELS = ("nomic-embed-text", "mxbai-embed-large", "all-minilm", "snowflake-arctic-embed",
                "bge-m3", "embeddinggemma")


def embedding_model(host: str) -> Optional[str]:
    """The first installed embedding model, or None."""
    try:
        from ollama import Client
        tags = Client(host=host, timeout=5).list()
        names = [getattr(m, "model", None) or (m.get("model") if isinstance(m, dict) else None)
                 for m in (getattr(tags, "models", None) or tags.get("models", []))]
    except Exception as exc:
        log.info("embedding models unavailable: %s", type(exc).__name__)
        return None
    names = [n for n in names if n]
    for wanted in EMBED_MODELS:
        for n in names:
            if n.split(":")[0] == wanted:
                return n
    return None


def embed(host: str, model: str, texts: list[str]) -> list[list[float]]:
    from ollama import Client
    client = Client(host=host, timeout=120)
    out: list[list[float]] = []
    for i in range(0, len(texts), 16):
        res = client.embed(model=model, input=texts[i:i + 16])
        vecs = getattr(res, "embeddings", None) or res.get("embeddings")
        out += [list(v) for v in vecs]
    return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def chunks(text: str) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text)
    out = []
    i = 0
    while i < len(text) and len(out) < 200:
        out.append(text[i:i + CHUNK])
        i += CHUNK - OVERLAP
    return [c for c in out if c.strip()]


def roots(agent: dict, cfg: config.Config) -> list[Path]:
    policy = paths.PathPolicy(cfg.folders)
    out = []
    for raw in agent.get("knowledge") or []:
        try:
            p = policy.check_read(raw)
        except paths.PolicyError:
            continue
        if p.is_dir() and p not in out:
            out.append(p)
    return out


def index_path(agent_id: str) -> Path:
    d = config.data_dir() / "knowledge"
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d / (agent_id + ".json")


def _files(policy: paths.PathPolicy, folders: list[Path]):
    count = 0
    for root in folders:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and policy.allowed_child(Path(dirpath) / d)]
            for name in filenames:
                p = Path(dirpath) / name
                if name.startswith(".") or not policy.allowed_child(p):
                    continue
                if documents.kind(p) not in ("text", "html", "docx", "odt", "pdf"):
                    continue
                count += 1
                if count > MAX_FILES:
                    return
                yield p


def update_index(agent: dict, cfg: config.Config, host: str, model: Optional[str]) -> dict:
    policy = paths.PathPolicy(cfg.folders)
    folders = roots(agent, cfg)
    path = index_path(agent["id"])
    index = store.read_json(path, {}) or {}
    if index.get("model") != model:
        index = {"model": model, "files": {}}
    files = index.setdefault("files", {})
    alive = set()
    total = sum(len(f.get("chunks", [])) for f in files.values())
    for p in _files(policy, folders):
        key = str(p)
        alive.add(key)
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if key in files and files[key].get("mtime") == mtime:
            continue
        try:
            text = documents.extract_text(p)
        except (documents.DocumentError, paths.PolicyError, OSError):
            continue
        parts = chunks(text)[: max(0, MAX_CHUNKS - total)]
        vectors = embed(host, model, parts) if (model and parts) else []
        files[key] = {"mtime": mtime, "chunks": parts, "vectors": vectors}
        total += len(parts)
    for key in list(files):
        if key not in alive:
            del files[key]
    index["updated"] = time.time()
    store.write_json(path, index)
    return index


def search(agent: dict, cfg: config.Config, host: str, query: str, limit: int = 5) -> list[tuple[str, str, float]]:
    """[(file, excerpt, score)]"""
    model = embedding_model(host)
    index = update_index(agent, cfg, host, model)
    results: list[tuple[str, str, float]] = []
    if model:
        qv = embed(host, model, [query])[0]
        for f, entry in index.get("files", {}).items():
            for text, vec in zip(entry.get("chunks", []), entry.get("vectors", [])):
                results.append((f, text, cosine(qv, vec)))
    else:
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        for f, entry in index.get("files", {}).items():
            for text in entry.get("chunks", []):
                low = text.lower()
                score = sum(low.count(w) for w in words) / (1 + len(words))
                if score:
                    results.append((f, text, score))
    results.sort(key=lambda r: r[2], reverse=True)
    return results[:limit]


def fingerprint(agent: dict) -> str:
    return hashlib.sha1(json.dumps(agent.get("knowledge") or []).encode()).hexdigest()[:10]
