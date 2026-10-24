"""The workflow permission gate.

1. Nothing deletes: no node type can, validation refuses any that would, and
   the action layer only calls create/send/move operations.
2. Every node that writes, sends or creates declares a Capability. When a
   workflow is saved the user approves its capabilities once, from a plain
   summary ("Este fluxo pode enviar e-mails como voce@…, criar alarmes"); the
   approval is kept outside the workflow file, keyed by a hash of the
   capabilities, so changing what the flow can do needs a new approval and an
   imported file can't approve itself.
3. External nodes (sending e-mail, replying) also ask on every run, unless the
   user ticked "não perguntar de novo para este fluxo". In "Testar" mode every
   writing node asks.
4. The global switches in Settings › IA cap everything, at run time: a node
   whose tool id is off (or whose group, read/write, is off) is refused.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .. import config, store
from . import graph, nodes


class PermissionDenied(Exception):
    pass


@dataclass
class Cap:
    tools: tuple[str, ...]
    text: str
    writes: bool
    external: bool
    nodes: list[str]
    ident: str = ""          # stable identity for the approval hash (not the display text)

    def to_dict(self) -> dict:
        return {"tools": list(self.tools), "text": self.text, "writes": self.writes,
                "external": self.external, "nodes": self.nodes}


def _account_label(account_ref: str, accounts: dict[str, str]) -> str:
    ref = (account_ref or "").strip()
    if not ref or "{{" in ref:
        if len(accounts) == 1:
            return next(iter(accounts.values()))
        return "a sua conta de e-mail"
    return accounts.get(ref, ref)


def capabilities(flow: dict, accounts: dict[str, str] | None = None,
                 agent_tools: dict[str, list[str]] | None = None) -> list[Cap]:
    """Distinct capabilities of a workflow, in node order.

    accounts: mail account id -> address (for "como voce@…");
    agent_tools: agent id -> its enabled write tool ids (an "ask an agent" node
    can do what its agent's tools can, each asking for confirmation)."""
    accounts = accounts or {}
    agent_tools = agent_tools or {}
    caps: dict[tuple, Cap] = {}
    for n in flow["nodes"]:
        nt = nodes.get(n["type"])
        if nt is None:
            continue
        params = graph.params_of(n)
        found: list[tuple[tuple[str, ...], str, bool, bool, str]] = []
        if nt.capability:
            verb = nt.capability.verb
            ident = verb
            if "{account}" in verb:
                ref = str(params.get("account") or "")
                ident = verb.replace("{account}", "{account:%s}" % ("" if "{{" in ref else ref))
                verb = verb.replace("{account}", _account_label(ref, accounts))
            found.append((nt.capability.tools, verb, nt.capability.writes, nt.capability.external, ident))
        if nt.type == "ai.agent":
            for tid in agent_tools.get(str(params.get("agent") or ""), []):
                label = AGENT_TOOL_VERBS.get(tid)
                if label:
                    text = label + " (pelo agente, pedindo confirmação)"
                    found.append(((tid,), text, True, False, text))
        for tools, verb, writes, external, ident in found:
            key = (tools, ident)
            if key in caps:
                caps[key].nodes.append(n["id"])
            else:
                caps[key] = Cap(tools, verb, writes, external, [n["id"]], ident)
    return list(caps.values())


AGENT_TOOL_VERBS = {
    "notes_write": "criar e completar notas", "calendar_write": "criar eventos e tarefas",
    "files_write": "criar arquivos nas pastas permitidas", "mail_write": "enviar e-mails",
    "alarms_write": "criar alarmes", "desktop_actions": "abrir apps e sites",
}


def summary(caps: list[Cap]) -> str:
    """"Este fluxo pode enviar e-mails como voce@…, criar alarmes e ler seu calendário."""
    if not caps:
        return "Este fluxo não lê nem altera nada: só usa a lógica e a IA local."
    texts = [c.text for c in caps]
    joined = texts[0] if len(texts) == 1 else ", ".join(texts[:-1]) + " e " + texts[-1]
    out = "Este fluxo pode " + joined + "."
    if any(c.external for c in caps):
        out += " Antes de enviar algo, ele pergunta a você a cada execução."
    return out


def cap_hash(caps: list[Cap]) -> str:
    data = sorted([list(c.tools), c.ident or c.text, c.writes, c.external] for c in caps)
    return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


def needs_approval(caps: list[Cap]) -> bool:
    return any(c.writes or c.external for c in caps) or bool(caps)


def is_approved(flow_id: str, caps: list[Cap]) -> bool:
    if not needs_approval(caps):
        return True
    return store.approval(flow_id).get("hash") == cap_hash(caps)


def check_node(node: dict, cfg: config.Config) -> None:
    """Global caps (Settings › IA) for one node, at run time."""
    lowered = node.get("type", "").lower()
    if any(w in lowered for w in nodes.FORBIDDEN_WORDS):
        raise PermissionDenied("Fluxos não podem apagar nada.")
    nt = nodes.get(node.get("type", ""))
    if nt is None:
        raise PermissionDenied("Tipo de bloco desconhecido.")
    if nt.capability is None:
        return
    for tid in nt.capability.tools:
        if not cfg.tool_enabled(tid):
            raise PermissionDenied(cfg.denial(tid))


def needs_run_confirmation(node: dict, flow_id: str, mode: str) -> bool:
    nt = nodes.get(node.get("type", ""))
    if nt is None or nt.capability is None:
        return False
    if mode == "test":
        return nt.capability.writes or nt.capability.external
    if nt.capability.external:
        return not store.approval(flow_id).get("dont_ask", False)
    return False
