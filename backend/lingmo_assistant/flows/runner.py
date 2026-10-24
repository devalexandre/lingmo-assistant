"""Runs one workflow: follows the graph from the trigger, resolves templates,
applies the permission gate, asks for confirmation where needed (the run
pauses until the user answers) and logs every step.

Events (sent with `emit(type, **fields)`):
  flow_run_started {run_id, flow_id, flow_name, mode}
  flow_node        {run_id, flow_id, node, status: running|done|error|declined|skipped|waiting,
                    output (preview), error}
  flow_ask         {run_id, flow_id, request_id, node, kind: confirm|input, title, details, external}
  flow_run_done    {run_id, flow_id, status: done|failed|stopped|refused, error}
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
import uuid
from typing import Any, Callable, Optional

from .. import config, store
from . import actions, graph, nodes, permissions, template

log = logging.getLogger("lingmo_assistant.flows")

MAX_STEPS = 1000
PREVIEW = 2000


class Stopped(Exception):
    pass


class Refused(Exception):
    pass


def _preview(value: Any) -> str:
    text = template.to_text(value)
    return text if len(text) <= PREVIEW else text[:PREVIEW] + "…"


def compare(op: str, left: Any, right: Any) -> bool:
    ltext, rtext = template.to_text(left).strip(), template.to_text(right).strip()
    if op == "empty":
        return ltext == ""
    if op == "not_empty":
        return ltext != ""
    if op in ("gt", "lt"):
        try:
            a, b = float(ltext.replace(",", ".")), float(rtext.replace(",", "."))
        except ValueError:
            return False
        return a > b if op == "gt" else a < b
    a, b = ltext.lower(), rtext.lower()
    if op == "contains":
        return b in a
    if op == "not_contains":
        return b not in a
    if op == "equals":
        return a == b
    if op == "not_equals":
        return a != b
    if op == "starts":
        return a.startswith(b)
    return False


def as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return list(value.values())
    text = template.to_text(value)
    return [line.strip() for line in text.splitlines() if line.strip()]


class FlowRunner:
    def __init__(self, flow: dict, *, emit: Callable[..., None], ask: Callable[..., Any],
                 load_config: Callable[[], config.Config] = config.load, ai=None,
                 speak: Optional[Callable[[str], None]] = None, mode: str = "run", source: str = "app",
                 trigger_data: Optional[dict] = None, tool_ctx=None, sleep: Callable[[float], None] | None = None):
        self.flow = flow
        self.emit_fn = emit
        self.ask_fn = ask
        self.load_config = load_config
        self.ai = ai
        self.speak = speak
        self.mode = mode if mode in ("run", "test") else "run"
        self.source = source
        self.trigger_data = trigger_data or {}
        self.tool_ctx = tool_ctx
        self.stop_event = threading.Event()
        self.sleep = sleep
        self.id = uuid.uuid4().hex[:16]
        self.steps = 0
        self.record = {"id": self.id, "flow_id": flow["id"], "flow_name": flow["name"],
                       "revision": flow.get("revision", 0), "mode": self.mode, "source": source,
                       "status": "running", "started": time.time(), "ended": None, "trigger": "", "error": "",
                       "steps": []}
        self.by_id = graph.node_map(flow)
        self.succ = graph.successors(flow)

    # ------------------------------------------------------------------ plumbing

    def emit(self, type_: str, **fields) -> None:
        try:
            self.emit_fn(type_, run_id=self.id, flow_id=self.flow["id"], **fields)
        except Exception as exc:     # a client gone away must not break the run
            log.warning("emit failed: %s", type(exc).__name__)

    def stop(self) -> None:
        self.stop_event.set()

    def _save(self) -> None:
        try:
            store.save_run(self.record)
        except (OSError, ValueError) as exc:
            log.warning("run log not saved: %s", type(exc).__name__)

    def _wait(self, seconds: float) -> None:
        if self.sleep is not None:
            self.sleep(seconds)
            return
        if self.stop_event.wait(seconds):
            raise Stopped()

    # ------------------------------------------------------------------ run

    def run(self) -> dict:
        cfg = self.load_config()
        self.emit("flow_run_started", flow_name=self.flow["name"], mode=self.mode)
        status, error = "done", ""
        try:
            errs = graph.errors(self.flow)
            if errs:
                raise Refused(errs[0]["message"])
            caps = permissions.capabilities(self.flow, agent_tools=self._agent_tools(cfg))
            if not permissions.is_approved(self.flow["id"], caps):
                raise Refused("Aprove o que este fluxo pode fazer antes de executá-lo (abra e salve o fluxo).")
            trig = graph.trigger(self.flow)
            scope = template.Scope(trigger_id=trig["id"], run={"id": self.id, "mode": self.mode})
            outputs = dict(self.trigger_data)
            outputs.setdefault("output", "")
            scope.outputs[trig["id"]] = outputs
            self.record["trigger"] = _preview(outputs.get("output") or nodes.get(trig["type"]).label)[:300]
            self._log(trig, "done", {}, outputs)
            self.emit("flow_node", node=trig["id"], status="done", output=_preview(outputs.get("output")), error="")
            self._follow(trig["id"], ["out"], scope)
        except Stopped:
            status, error = "stopped", "Parado."
        except Refused as exc:
            status, error = "refused", str(exc)
        except permissions.PermissionDenied as exc:
            status, error = "refused", str(exc)
        except _NodeFailed as exc:
            status, error = "failed", str(exc)
        except Exception as exc:
            log.error("flow failed: %s", type(exc).__name__)
            status, error = "failed", "Erro interno ao executar o fluxo."
        self.record.update(status=status, error=error, ended=time.time())
        self._save()
        try:
            store.prune_runs(self.flow["id"])
        except (OSError, ValueError):
            pass
        self.emit("flow_run_done", status=status, error=error)
        return self.record

    def _agent_tools(self, cfg) -> dict[str, list[str]]:
        from .. import agents
        out = {}
        for n in self.flow["nodes"]:
            if n["type"] == "ai.agent":
                ref = str((n.get("params") or {}).get("agent") or "")
                a = agents.find(ref) if ref else None
                if a:
                    out[ref] = agents.write_tools(a, cfg)
        return out

    def _follow(self, node_id: str, ports: list[str], scope: template.Scope) -> None:
        for port, target in self.succ.get(node_id, []):
            if port in ports:
                self._exec(target, scope)

    def _log(self, node, status, inputs, outputs, error="", started=None) -> dict:
        nt = nodes.get(node["type"])
        entry = {"node": node["id"], "type": node["type"], "label": node.get("label") or (nt.label if nt else ""),
                 "status": status, "started": started or time.time(), "ended": time.time(),
                 "inputs": {k: _preview(v) for k, v in (inputs or {}).items()},
                 "outputs": {k: _preview(v) for k, v in (outputs or {}).items()}, "error": error}
        self.record["steps"].append(entry)
        if len(self.record["steps"]) % 5 == 0:
            self._save()
        return entry

    def _render_params(self, node: dict, scope: template.Scope) -> tuple[dict, list[str]]:
        nt = nodes.get(node["type"])
        raw = graph.params_of(node)
        missing: list[str] = []
        out: dict[str, Any] = {}
        for p in nt.params:
            v = raw.get(p.name)
            if p.kind in ("text", "textarea", "folder", "path", "language", "account", "time"):
                out[p.name] = template.render(v, scope, missing) if v is not None else ""
            elif p.kind == "number":
                out[p.name] = template.render(v, scope, missing) if isinstance(v, str) else v
            elif p.kind == "list":
                out[p.name] = [template.render(x, scope, missing) for x in (v or [])] if isinstance(v, list) \
                    else as_list(template.resolve(v, scope, missing))
            else:
                out[p.name] = v
        return out, missing

    def _exec(self, node_id: str, scope: template.Scope) -> None:
        if self.stop_event.is_set():
            raise Stopped()
        self.steps += 1
        if self.steps > MAX_STEPS:
            raise _NodeFailed("O fluxo passou do limite de %d passos." % MAX_STEPS)
        node = self.by_id[node_id]
        nt = nodes.get(node["type"])
        cfg = self.load_config()
        started = time.time()
        self.emit("flow_node", node=node_id, status="running", output="", error="")
        try:
            permissions.check_node(node, cfg)
        except permissions.PermissionDenied as exc:
            self._log(node, "error", {}, {}, str(exc), started)
            self.emit("flow_node", node=node_id, status="error", output="", error=str(exc))
            raise _NodeFailed("%s: %s" % (node.get("label") or nt.label, exc)) from None
        params, missing = self._render_params(node, scope)
        try:
            ports, outputs = self._do(node, nt, params, scope, cfg)
        except Stopped:
            self._log(node, "stopped", params, {}, "", started)
            raise
        except _Declined as exc:
            self._log(node, "declined", params, {}, str(exc), started)
            self.emit("flow_node", node=node_id, status="declined", output="", error=str(exc))
            return
        except (actions.ActionError, ValueError) as exc:
            msg = str(exc) or "Falhou."
            self._log(node, "error", params, {}, msg, started)
            self.emit("flow_node", node=node_id, status="error", output="", error=msg)
            raise _NodeFailed("%s: %s" % (node.get("label") or nt.label, msg)) from None
        if outputs is not None:
            scope.outputs[node_id] = outputs
        entry = self._log(node, "done", params, outputs or {}, "", started)
        if missing:
            entry["warnings"] = ["{{%s}} estava vazio" % m for m in sorted(set(missing))]
        self.emit("flow_node", node=node_id, status="done", output=_preview((outputs or {}).get("output", "")), error="")
        if node["type"] != "logic.loop":
            self._follow(node_id, ports, scope)

    def _confirm(self, node, title, details, external) -> None:
        if not self._ask_allow(node, title, details, external):
            raise _Declined("Você recusou: nada foi feito.")

    def _ask_allow(self, node, title, details, external) -> bool:
        request_id = uuid.uuid4().hex[:16]
        self.record["status"] = "waiting"
        self._save()
        self.emit("flow_node", node=node["id"], status="waiting", output="", error="")
        answer = self.ask_fn(kind="confirm", run_id=self.id, flow=self.flow, node=node["id"], request_id=request_id,
                             title=title, details=details, external=external)
        self.record["status"] = "running"
        if answer is None or self.stop_event.is_set():
            raise Stopped()
        allow = answer.get("allow") if isinstance(answer, dict) else bool(answer)
        if isinstance(answer, dict) and answer.get("dont_ask") and allow and self.mode == "run" and external:
            store.set_dont_ask(self.flow["id"], True)
        self.emit("flow_node", node=node["id"], status="running", output="", error="")
        return bool(allow)

    def _do(self, node, nt, p, scope, cfg):
        t = node["type"]
        if t == "logic.if":
            ok = compare(p.get("op", "contains"), template.resolve(graph.params_of(node).get("value"), scope),
                         p.get("compare", ""))
            return (["true"] if ok else ["false"]), {"output": "sim" if ok else "não"}
        if t == "logic.switch":
            value = template.to_text(p.get("value", "")).strip().lower()
            cases = [str(c).strip().lower() for c in (p.get("cases") or [])]
            for i, c in enumerate(cases):
                if value == c or (c and c in value):
                    return ["case_%d" % i], {"output": p["cases"][i]}
            return ["default"], {"output": value}
        if t == "logic.loop":
            items = as_list(template.resolve(graph.params_of(node).get("items"), scope))
            limit = int(actions._num(p.get("max"), 50) or 50)
            items = items[:max(1, min(limit, 500))]
            scope.outputs[node["id"]] = {"output": "%d itens" % len(items), "count": len(items)}
            for i, item in enumerate(items):
                child = scope.child_loop(item, i)
                for port, target in self.succ.get(node["id"], []):
                    if port == "each":
                        self._exec(target, child)
            self._follow(node["id"], ["done"], scope)
            return [], {"output": "%d itens" % len(items), "count": len(items)}
        if t == "logic.wait":
            seconds = max(0.0, min(actions._num(p.get("seconds"), 0), 24 * 3600))
            self._wait(seconds)
            return ["out"], {"output": "Esperou %g s" % seconds}
        if t == "logic.set":
            name = str(p.get("name") or "").strip()
            value = template.resolve(graph.params_of(node).get("value"), scope)
            scope.variables[name] = value
            return ["out"], {"output": template.to_text(value)}
        if t == "logic.ask":
            request_id = uuid.uuid4().hex[:16]
            kind = "input" if p.get("mode") == "input" else "confirm"
            self.record["status"] = "waiting"
            self._save()
            self.emit("flow_node", node=node["id"], status="waiting", output="", error="")
            answer = self.ask_fn(kind=kind, run_id=self.id, flow=self.flow, node=node["id"], request_id=request_id,
                                 title=self.flow["name"], details=p.get("question", ""), external=False)
            self.record["status"] = "running"
            if answer is None or self.stop_event.is_set():
                raise Stopped()
            if kind == "input":
                text = answer.get("text", "") if isinstance(answer, dict) else str(answer)
                return ["yes"], {"output": str(text)[:10000]}
            allow = answer.get("allow") if isinstance(answer, dict) else bool(answer)
            return (["yes"] if allow else ["no"]), {"output": "sim" if allow else "não"}

        ctx = actions.Ctx(cfg, ai=self.ai, speak=self.speak, stopped=self.stop_event.is_set, tool_ctx=self.tool_ctx)
        if self.ai is not None and hasattr(self.ai, "bind"):
            self.ai.bind(lambda title, details: self._ask_allow(node, title, details, False))
        if permissions.needs_run_confirmation(node, self.flow["id"], self.mode):
            try:
                title, details = actions.preview(ctx, t, p)
            except (actions.ActionError, ValueError) as exc:
                raise actions.ActionError(str(exc)) from exc
            except Exception as exc:
                from .. import tools
                if isinstance(exc, tools.KNOWN_ERRORS):
                    raise actions.ActionError(str(exc)) from exc
                raise
            self._confirm(node, title, details, bool(nt.capability and nt.capability.external))
        return ["out"], actions.run(ctx, t, p)


class _NodeFailed(Exception):
    pass


class _Declined(Exception):
    pass


def now_outputs() -> dict:
    now = dt.datetime.now()
    return {"output": "Executado manualmente em %s" % now.strftime("%Y-%m-%d %H:%M")}
