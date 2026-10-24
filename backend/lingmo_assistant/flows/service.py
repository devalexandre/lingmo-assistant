"""Workflow documents for the engine and the background service: listing with
a plain description, saving (with the capability summary to approve),
approving, importing, and the global-shortcut entries in lingmo-chotkeys."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from .. import agents, config, mail, store
from . import graph, nodes, permissions, schedule, templates

log = logging.getLogger("lingmo_assistant.flows")

FLOWS = store.DocumentStore("workflows", graph.normalize)
SHORTCUT_EXEC = "lingmo-assistant-flows --run "
BACKGROUND_TRIGGERS = ("trigger.schedule", "trigger.email", "trigger.calendar", "trigger.file", "trigger.system")


def mail_accounts() -> dict[str, str]:
    try:
        return {a["id"]: a["email"] for a in mail.accounts()}
    except mail.MailError:
        return {}


def agent_tools(flow: dict, cfg: config.Config) -> dict[str, list[str]]:
    out = {}
    for n in flow["nodes"]:
        if n["type"] == "ai.agent":
            ref = str((n.get("params") or {}).get("agent") or "")
            a = agents.find(ref) if ref else None
            if a:
                out[ref] = agents.write_tools(a, cfg)
    return out


def capabilities(flow: dict, cfg: Optional[config.Config] = None, accounts: Optional[dict] = None):
    cfg = cfg or config.load()
    return permissions.capabilities(flow, accounts if accounts is not None else mail_accounts(),
                                    agent_tools(flow, cfg))


def trigger_text(flow: dict) -> str:
    t = graph.trigger(flow)
    if t is None:
        return "Sem gatilho"
    p = graph.params_of(t)
    kind = t["type"]
    if kind == "trigger.schedule":
        return schedule.describe(p.get("schedule"))
    if kind == "trigger.email":
        if p.get("from_contains"):
            return "E-mail de %s" % p["from_contains"]
        return "Novo e-mail" + (" com anexo" if p.get("has_attachment") else "")
    if kind == "trigger.calendar":
        return "%s min antes de eventos" % p.get("minutes_before")
    if kind == "trigger.file":
        return "Mudanças em %s" % p.get("folder")
    if kind == "trigger.shortcut":
        return "Atalho %s" % p.get("key")
    if kind == "trigger.voice":
        phrases = p.get("phrases") or []
        return "Voz: \"%s\"" % (phrases[0] if phrases else "")
    if kind == "trigger.system":
        return {"login": "Ao entrar na sessão", "usb": "USB conectado", "battery_low": "Bateria fraca"}.get(
            p.get("event"), "Evento do sistema")
    return "Manual"


def describe(flow: dict, cfg: Optional[config.Config] = None, accounts: Optional[dict] = None) -> dict:
    cfg = cfg or config.load()
    caps = capabilities(flow, cfg, accounts)
    appr = store.approval(flow["id"])
    issues = graph.validate(flow)
    blocked = []
    for c in caps:
        for tid in c.tools:
            if not cfg.tool_enabled(tid):
                blocked.append(cfg.denial(tid))
    t = graph.trigger(flow)
    return {"id": flow["id"], "name": flow["name"], "description": flow.get("description", ""),
            "enabled": flow.get("enabled", True), "revision": flow.get("revision", 0),
            "updated": flow.get("updated", 0), "trigger_type": t["type"] if t else "",
            "trigger_text": trigger_text(flow), "capabilities": [c.to_dict() for c in caps],
            "summary": permissions.summary(caps), "cap_hash": permissions.cap_hash(caps),
            "approved": permissions.is_approved(flow["id"], caps), "dont_ask": bool(appr.get("dont_ask")),
            "issues": issues, "blocked": sorted(set(blocked)), "nodes": len(flow["nodes"]),
            "background": bool(t and t["type"] in BACKGROUND_TRIGGERS),
            "spotlight": bool(t and t["type"] == "trigger.manual" and graph.params_of(t).get("spotlight"))}


def list_flows(cfg: Optional[config.Config] = None) -> list[dict]:
    cfg = cfg or config.load()
    accounts = mail_accounts()
    items = [describe(f, cfg, accounts) for f in FLOWS.list()]
    return sorted(items, key=lambda d: d["name"].lower())


def save(doc: dict) -> dict:
    flow = FLOWS.save(doc)
    try:
        sync_shortcuts()
    except OSError as exc:
        log.warning("shortcuts not updated: %s", type(exc).__name__)
    return flow


def remove(flow_id: str) -> bool:
    ok = FLOWS.remove(flow_id)
    try:
        sync_shortcuts()
    except OSError:
        pass
    return ok


def approve(flow_id: str, cap_hash: str, dont_ask: bool) -> dict:
    flow = FLOWS.get(flow_id)
    if flow is None:
        raise ValueError("Fluxo não encontrado.")
    caps = capabilities(flow)
    current = permissions.cap_hash(caps)
    if cap_hash and cap_hash != current:
        raise ValueError("O fluxo mudou desde que o resumo foi mostrado. Revise e aprove de novo.")
    store.set_approval(flow_id, current, dont_ask)
    return describe(flow)


def import_text(text: str) -> dict:
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise graph.FlowError("O arquivo não é um fluxo válido (JSON).") from exc
    flow = graph.normalize(doc, keep_id=True)
    if FLOWS.get(flow["id"]) is not None:
        flow["id"] = graph.new_id()
        flow["name"] = flow["name"] + " (importado)"
    flow["revision"] = 0
    flow["enabled"] = False         # the user reviews and approves it first
    return save(flow)


def export_text(flow_id: str) -> str:
    flow = FLOWS.get(flow_id)
    if flow is None:
        raise ValueError("Fluxo não encontrado.")
    return json.dumps(flow, ensure_ascii=False, indent=2)


def from_template(template_id: str) -> dict:
    doc = templates.instantiate(template_id)
    if doc is None:
        raise ValueError("Modelo não encontrado.")
    return graph.normalize(doc, keep_id=False)


# ------------------------------------------------------------------ voice triggers

def voice_flows() -> list[dict]:
    out = []
    for f in FLOWS.list():
        t = graph.trigger(f)
        if f.get("enabled", True) and t and t["type"] == "trigger.voice":
            out.append(f)
    return out


def match_voice(text: str, ai=None) -> Optional[dict]:
    """The enabled workflow whose voice phrases match what was said."""
    from .. import voice
    best, best_score = None, 0.0
    ai_candidates = []
    for f in voice_flows():
        p = graph.params_of(graph.trigger(f))
        phrases = [str(x) for x in (p.get("phrases") or []) if str(x).strip()]
        score = voice.match_keywords(text, phrases)
        if score >= 0.75 and score > best_score:
            best, best_score = f, score
        elif p.get("match") == "ai":
            ai_candidates.append((f, phrases))
    if best is not None or ai is None:
        return best
    for f, phrases in ai_candidates:
        try:
            if ai.match_phrase(text, phrases):
                return f
        except Exception as exc:
            log.info("voice match failed: %s", type(exc).__name__)
    return None


# ------------------------------------------------------------------ shortcuts (lingmo-chotkeys)

def shortcuts_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(config.home() / ".config")
    return Path(base) / "lingmoglobalshortcutsrc"


def _encode_group(key: str) -> str:
    return "".join(c if (c.isalnum() and c.isascii()) or c in "_-." else "%%%02X" % ord(c) for c in key)


def _decode_group(group: str) -> str:
    return re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m[1], 16)), group)


def _parse_ini(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            sections.append((s[1:-1], []))
        else:
            sections[-1][1].append(line)
    return sections


def valid_key(key: str) -> bool:
    parts = key.split("+")
    mods = {"Meta", "Ctrl", "Alt", "Shift"}
    return bool(key) and len(key) < 40 and all(p for p in parts) and all(p in mods for p in parts[:-1]) \
        and re.fullmatch(r"[A-Za-z0-9]|F\d{1,2}|Space|Return|Print|Home|End|Insert|Pause", parts[-1]) is not None


def sync_shortcuts() -> list[str]:
    """Writes one chotkeys entry per enabled workflow with a shortcut trigger and
    removes the entries of workflows that no longer have one. Never touches
    shortcuts it didn't create; returns conflicts (keys already taken)."""
    wanted: dict[str, str] = {}
    for f in FLOWS.list():
        t = graph.trigger(f)
        if f.get("enabled", True) and t and t["type"] == "trigger.shortcut":
            key = str(graph.params_of(t).get("key") or "").strip()
            if valid_key(key):
                wanted.setdefault(key, f["id"])
    path = shortcuts_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    sections = _parse_ini(text)
    kept, conflicts, present = [], [], set()
    for name, lines in sections:
        execs = [l.split("=", 1)[1].strip() for l in lines if l.strip().startswith("Exec=")]
        ours = bool(execs) and execs[0].startswith(SHORTCUT_EXEC)
        key = _decode_group(name)
        if ours:
            fid = execs[0][len(SHORTCUT_EXEC):].strip()
            if wanted.get(key) == fid:
                present.add(key)
                kept.append((name, lines))
            continue
        if name and key in wanted:
            conflicts.append(key)
            wanted.pop(key)
        kept.append((name, lines))
    for key, fid in wanted.items():
        if key in present:
            continue
        flow = FLOWS.get(fid)
        kept.append((_encode_group(key), ["Comment=Fluxo: %s" % (flow["name"] if flow else fid),
                                           "Exec=%s%s" % (SHORTCUT_EXEC, fid), ""]))
    out = []
    for name, lines in kept:
        if name:
            out.append("[%s]" % name)
        out += lines
    new = "\n".join(out).strip("\n") + "\n"
    if new.strip() != text.strip():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".lingmoglobalshortcutsrc-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(new)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    return conflicts


def node_catalogue() -> dict:
    cat = nodes.catalogue()
    cat["templates"] = templates.list_templates()
    return cat
