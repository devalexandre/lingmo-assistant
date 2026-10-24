"""Workflow documents: format, normalisation and validation.

A workflow is versioned JSON:

    {"format": "lingmo-assistant-flow", "format_version": 1,
     "id": "…", "name": "…", "description": "", "revision": 3, "enabled": true,
     "nodes": [{"id": "trigger", "type": "trigger.email", "label": "", "x": 0, "y": 0,
                "params": {…}}],
     "edges": [{"from": "trigger", "port": "out", "to": "draft"}]}

Node ids are what templates use ({{draft.output}}). The graph must be acyclic
(loops are a node, not a cycle) with exactly one trigger.
"""
from __future__ import annotations

import copy
import re
import uuid
from collections import defaultdict, deque

from . import nodes, schedule, template

FORMAT = "lingmo-assistant-flow"
FORMAT_VERSION = 1
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
FLOW_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_NODES = 200
MAX_EDGES = 400
MAX_PARAM = 20000


class FlowError(ValueError):
    pass


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def normalize(doc: dict, keep_id: bool = True) -> dict:
    """A clean copy with only known keys; raises FlowError on a malformed file."""
    if not isinstance(doc, dict):
        raise FlowError("Arquivo de fluxo inválido.")
    if doc.get("format", FORMAT) != FORMAT:
        raise FlowError("Este arquivo não é um fluxo do Assistente.")
    version = doc.get("format_version", FORMAT_VERSION)
    if not isinstance(version, int) or version > FORMAT_VERSION:
        raise FlowError("Este fluxo foi feito por uma versão mais nova do Assistente.")
    fid = str(doc.get("id") or "") if keep_id else ""
    if not FLOW_ID_RE.match(fid):
        fid = new_id()
    out = {
        "format": FORMAT, "format_version": FORMAT_VERSION, "id": fid,
        "name": " ".join(str(doc.get("name") or "Fluxo sem nome").split())[:120] or "Fluxo sem nome",
        "description": str(doc.get("description") or "")[:2000],
        "revision": int(doc.get("revision") or 0) if str(doc.get("revision") or "0").isdigit() else 0,
        "enabled": bool(doc.get("enabled", True)),
        "created": float(doc.get("created") or 0) if isinstance(doc.get("created"), (int, float)) else 0,
        "updated": float(doc.get("updated") or 0) if isinstance(doc.get("updated"), (int, float)) else 0,
        "nodes": [], "edges": [],
    }
    raw_nodes = doc.get("nodes") or []
    raw_edges = doc.get("edges") or []
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        raise FlowError("Arquivo de fluxo inválido.")
    if len(raw_nodes) > MAX_NODES or len(raw_edges) > MAX_EDGES:
        raise FlowError("Fluxo grande demais.")
    for n in raw_nodes:
        if not isinstance(n, dict):
            raise FlowError("Arquivo de fluxo inválido.")
        params = n.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        clean = {}
        for k, v in params.items():
            if not isinstance(k, str) or len(k) > 40:
                continue
            if isinstance(v, str):
                v = v[:MAX_PARAM]
            elif isinstance(v, list):
                v = [x[:MAX_PARAM] if isinstance(x, str) else x for x in v[:50]
                     if isinstance(x, (str, int, float, bool))]
            elif isinstance(v, dict):
                v = copy.deepcopy(v)
            elif not isinstance(v, (int, float, bool)) and v is not None:
                continue
            clean[k] = v
        out["nodes"].append({
            "id": str(n.get("id") or ""), "type": str(n.get("type") or ""),
            "label": str(n.get("label") or "")[:120],
            "x": float(n.get("x") or 0) if isinstance(n.get("x"), (int, float)) else 0.0,
            "y": float(n.get("y") or 0) if isinstance(n.get("y"), (int, float)) else 0.0,
            "params": clean,
        })
    for e in raw_edges:
        if not isinstance(e, dict):
            raise FlowError("Arquivo de fluxo inválido.")
        out["edges"].append({"from": str(e.get("from") or ""), "port": str(e.get("port") or "out"),
                             "to": str(e.get("to") or "")})
    return out


def params_of(node: dict) -> dict:
    """The node's params with the type's defaults filled in."""
    nt = nodes.get(node.get("type", ""))
    values = dict(node.get("params") or {})
    if nt:
        for p in nt.params:
            if p.name not in values:
                values[p.name] = copy.deepcopy(p.default)
    return values


def triggers(flow: dict) -> list[dict]:
    return [n for n in flow["nodes"] if n["type"].startswith("trigger.")]


def trigger(flow: dict) -> dict | None:
    t = triggers(flow)
    return t[0] if t else None


def node_map(flow: dict) -> dict[str, dict]:
    return {n["id"]: n for n in flow["nodes"]}


def successors(flow: dict) -> dict[str, list[tuple[str, str]]]:
    """node id -> [(port, target id)] in file order."""
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for e in flow["edges"]:
        out[e["from"]].append((e["port"], e["to"]))
    return out


def ancestors(flow: dict) -> dict[str, set[str]]:
    """node id -> every node that can run before it."""
    preds: dict[str, set[str]] = defaultdict(set)
    for e in flow["edges"]:
        preds[e["to"]].add(e["from"])
    result: dict[str, set[str]] = {}
    for n in flow["nodes"]:
        seen, todo = set(), list(preds[n["id"]])
        while todo:
            x = todo.pop()
            if x in seen:
                continue
            seen.add(x)
            todo.extend(preds[x])
        result[n["id"]] = seen
    return result


def loop_bodies(flow: dict) -> dict[str, str]:
    """node id -> id of the loop whose "Para cada" branch it is in (innermost)."""
    succ = successors(flow)
    inside: dict[str, str] = {}
    for n in flow["nodes"]:
        if n["type"] != "logic.loop":
            continue
        todo = [t for p, t in succ[n["id"]] if p == "each"]
        seen = set()
        while todo:
            x = todo.pop()
            if x in seen:
                continue
            seen.add(x)
            inside.setdefault(x, n["id"])
            todo.extend(t for _, t in succ[x])
    return inside


def has_cycle(flow: dict) -> bool:
    indeg = {n["id"]: 0 for n in flow["nodes"]}
    succ = successors(flow)
    for e in flow["edges"]:
        if e["to"] in indeg:
            indeg[e["to"]] += 1
    queue = deque(k for k, v in indeg.items() if v == 0)
    visited = 0
    while queue:
        x = queue.popleft()
        visited += 1
        for _, t in succ[x]:
            if t in indeg:
                indeg[t] -= 1
                if indeg[t] == 0:
                    queue.append(t)
    return visited != len(indeg)


def _issue(issues, level, node, message):
    issues.append({"level": level, "node": node, "message": message})


def validate(flow: dict) -> list[dict]:
    """[{level: error|warning, node: id or "", message (pt-BR)}]; errors block saving as enabled
    and running."""
    issues: list[dict] = []
    ids = [n["id"] for n in flow["nodes"]]
    by_id = node_map(flow)
    for n in flow["nodes"]:
        nid = n["id"]
        if not ID_RE.match(nid):
            _issue(issues, "error", nid, "Identificador inválido: use letras minúsculas, números e _.")
        if ids.count(nid) > 1:
            _issue(issues, "error", nid, "Há dois blocos com o mesmo identificador «%s»." % nid)
        if nid in template.SPECIAL and not (nid == "trigger" and n["type"].startswith("trigger.")):
            _issue(issues, "error", nid, "«%s» é um nome reservado." % nid)
        lowered = n["type"].lower()
        if any(w in lowered for w in nodes.FORBIDDEN_WORDS):
            _issue(issues, "error", nid, "Fluxos não podem apagar nada.")
            continue
        nt = nodes.get(n["type"])
        if nt is None:
            _issue(issues, "error", nid, "Tipo de bloco desconhecido: %s." % n["type"])
            continue
        params = params_of(n)
        for p in nt.params:
            value = params.get(p.name)
            if p.required and (value is None or value == "" or value == [] or value == {}):
                _issue(issues, "error", nid, "Preencha «%s»." % p.label)
            if p.kind == "select" and p.options and isinstance(value, str) and value \
                    and value not in [o["value"] for o in p.options]:
                _issue(issues, "error", nid, "Opção inválida em «%s»." % p.label)
            if p.kind == "schedule":
                try:
                    schedule.check(value)
                except schedule.ScheduleError as exc:
                    _issue(issues, "error", nid, str(exc))
            if p.kind == "number" and value not in (None, "") and not template.references(value):
                try:
                    float(value)
                except (TypeError, ValueError):
                    _issue(issues, "error", nid, "«%s» precisa ser um número." % p.label)
        for value in params.values():
            if isinstance(value, str) and any(w in value.lower() for w in ("delete", "expunge")) \
                    and n["type"] == "action.mail.organize":
                _issue(issues, "error", nid, "Fluxos não podem apagar nada.")
        if n["type"] == "logic.set" and not re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,39}$", str(params.get("name") or "")):
            _issue(issues, "error", nid, "Nome de variável inválido.")
    trig = triggers(flow)
    if not trig:
        _issue(issues, "error", "", "O fluxo precisa de um gatilho.")
    elif len(trig) > 1:
        for t in trig[1:]:
            _issue(issues, "error", t["id"], "Use só um gatilho por fluxo.")
    seen_edges = set()
    for e in flow["edges"]:
        src, dst = by_id.get(e["from"]), by_id.get(e["to"])
        if src is None or dst is None:
            _issue(issues, "error", e["from"] if src else e["to"], "Ligação para um bloco que não existe.")
            continue
        if e["port"] not in nodes.ports_for(src):
            _issue(issues, "error", src["id"], "Saída «%s» inexistente." % e["port"])
        dnt = nodes.get(dst["type"])
        if dnt is not None and not dnt.has_input:
            _issue(issues, "error", dst["id"], "Um gatilho não recebe ligações.")
        if e["from"] == e["to"]:
            _issue(issues, "error", src["id"], "Um bloco não pode ligar a si mesmo.")
        key = (e["from"], e["port"], e["to"])
        if key in seen_edges:
            _issue(issues, "warning", src["id"], "Ligação repetida.")
        seen_edges.add(key)
    for n in flow["nodes"]:
        for ref in template.references(n.get("params") or {}):
            root = ref.split(".", 1)[0]
            if root not in template.SPECIAL and root not in by_id:
                _issue(issues, "error", n["id"], "{{%s}}: não há bloco «%s»." % (ref, root))
    if has_cycle(flow):
        _issue(issues, "error", "", "O fluxo tem um ciclo. Para repetir, use o bloco «Repetir para cada».")
        return issues
    anc = ancestors(flow)
    bodies = loop_bodies(flow)
    t0 = trig[0]["id"] if trig else ""
    for n in flow["nodes"]:
        if n["type"].startswith("trigger."):
            continue
        if t0 and t0 not in anc[n["id"]]:
            _issue(issues, "warning", n["id"], "Este bloco não está ligado ao gatilho e nunca roda.")
        for ref in template.references(n.get("params") or {}):
            root = ref.split(".", 1)[0]
            if root in ("var", "now", "run"):
                continue
            if root == "loop":
                if n["id"] not in bodies:
                    _issue(issues, "warning", n["id"], "{{%s}} só existe dentro de «Repetir para cada»." % ref)
                continue
            if root == "trigger":
                continue
            if root not in by_id:
                continue
            elif root not in anc[n["id"]]:
                _issue(issues, "warning", n["id"], "{{%s}}: «%s» não roda antes deste bloco." % (ref, root))
            else:
                parts = ref.split(".")
                if len(parts) > 1 and parts[1] not in nodes.outputs_for(by_id[root]) \
                        and not by_id[root]["type"].startswith("ai.extract"):
                    _issue(issues, "warning", n["id"], "{{%s}}: «%s» não tem a saída «%s»." % (ref, root, parts[1]))
    return issues


def errors(flow: dict) -> list[dict]:
    return [i for i in validate(flow) if i["level"] == "error"]


def variables_for(flow: dict, node_id: str) -> list[dict]:
    """What a node's text fields can use, for the editor's autocomplete."""
    by_id = node_map(flow)
    anc = ancestors(flow).get(node_id, set())
    out = []
    trig = trigger(flow)
    for n in flow["nodes"]:
        if n["id"] not in anc:
            continue
        nt = nodes.get(n["type"])
        for o in nodes.outputs_for(n):
            out.append({"text": "{{%s.%s}}" % (n["id"], o), "node": n["id"],
                        "label": "%s › %s" % (n.get("label") or (nt.label if nt else n["id"]), o)})
    if trig and trig["id"] in anc:
        for o in nodes.outputs_for(trig):
            out.append({"text": "{{trigger.%s}}" % o, "node": trig["id"], "label": "Gatilho › %s" % o})
    for n in flow["nodes"]:
        if n["type"] == "logic.set" and n["id"] in anc:
            name = str((n.get("params") or {}).get("name") or "")
            if name:
                out.append({"text": "{{var.%s}}" % name, "node": n["id"], "label": "Variável › %s" % name})
    if node_id in loop_bodies(flow):
        out += [{"text": "{{loop.item}}", "node": "", "label": "Item da repetição"},
                {"text": "{{loop.number}}", "node": "", "label": "Número do item"}]
    out += [{"text": "{{now.date}}", "node": "", "label": "Data de hoje"},
            {"text": "{{now.time}}", "node": "", "label": "Hora atual"}]
    del by_id
    return out
