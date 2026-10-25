"""lingmo-assistant-engine: NDJSON worker on stdin/stdout (see docs/protocol.md).

stdout carries protocol lines only: at start-up the real stdout is duplicated
into a private descriptor and fd 1 is pointed at stderr, so nothing printed by
a library can corrupt the stream. Logs go to stderr and never contain message
text, document contents or tool arguments.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import PROTOCOL_VERSION, __version__, config, shell

log = logging.getLogger("lingmo_assistant.engine")

# ask_image carries the screen crop as base64 (up to 8 MiB decoded)
MAX_LINE = 12 * 1024 * 1024
MAX_MESSAGE = 32000
OUTPUT_PREVIEW = 4000


class Output:
    """Thread-safe NDJSON writer."""

    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()

    def emit(self, type_: str, **fields: Any) -> None:
        line = json.dumps({"type": type_, **fields}, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            self.stream.write(line + "\n")
            self.stream.flush()


def protect_stdout():
    """Returns a text stream on the original stdout; fd 1 becomes stderr."""
    fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return os.fdopen(fd, "w", encoding="utf-8", buffering=1)


def friendly_error(exc_text: str, model: str) -> str:
    t = exc_text.lower()
    if "does not support tools" in t:
        return "O modelo %s não tem suporte a ferramentas." % model
    if "not found" in t and ("model" in t or "pull" in t or "404" in t):
        return "O modelo %s não está instalado. Instale em Configurações › IA." % model
    if any(k in t for k in ("connection refused", "connecterror", "failed to connect", "connect call failed",
                            "name or service not known", "connection error", "all connection attempts")):
        return "O Ollama não está rodando. Inicie com “systemctl start ollama” ou em Configurações › IA."
    if "timeout" in t or "timed out" in t:
        return "A IA demorou demais para responder. Tente um modelo menor."
    return "Não foi possível falar com a IA."


@dataclass
class Pending:
    request_id: str
    conversation_id: str
    event: threading.Event = field(default_factory=threading.Event)
    allow: Optional[bool] = None


class Engine:
    def __init__(self, out: Output, db=None, load_config: Callable[[], config.Config] = config.load,
                 model_factory=None, tools_supported: Optional[Callable[[str], Optional[bool]]] = None,
                 vision_supported: Optional[Callable[[str], Optional[bool]]] = None):
        from . import agent as agent_mod, tools as tools_mod
        self.agent_mod = agent_mod
        self.tools_mod = tools_mod
        self.out = out
        self.load_config = load_config
        self.model_factory = model_factory          # tests: cfg -> model
        self.tools_supported_fn = tools_supported or agent_mod.supports_tools
        self.vision_supported_fn = vision_supported or agent_mod.supports_vision
        self.db = db if db is not None else agent_mod.database()
        self.ctx = tools_mod.ToolContext(load_config)
        self.ctx.summarizer = agent_mod.make_summarizer(
            load_config, (lambda: model_factory(load_config())) if model_factory else None)
        self.cfg = load_config()
        self.worker: Optional[threading.Thread] = None
        self.stop_flag = threading.Event()
        self.closing = threading.Event()
        self.pending: dict[str, Pending] = {}
        self.lock = threading.Lock()
        # Paused runs found in the database (another process, e.g. Spotlight, left them)
        self.stored: dict[str, tuple[str, str]] = {}          # request_id -> (conversation, run_id)
        self.stored_answers: dict[str, dict[str, bool]] = {}  # run_id -> {request_id: allow}
        self.notified_no_tools: set[str] = set()
        self.conv_agents: dict[str, str] = {}
        from .flows import protocol as flows_protocol
        self.flows_protocol = flows_protocol
        self.extra = flows_protocol.Handler(self)

    # ------------------------------------------------------------------ requests

    def handle(self, request: dict) -> None:
        kind = request.get("type") if isinstance(request, dict) else None
        if kind == "chat":
            self.chat(str(request.get("conversation_id") or ""), request.get("message"),
                      str(request.get("agent") or ""))
        elif kind == "ask_image":
            self.ask_image(request)
        elif kind in self.flows_protocol.TYPES:
            self.extra.handle(kind, request)
        elif kind == "confirm":
            self.confirm(str(request.get("request_id") or ""), bool(request.get("allow")))
        elif kind == "stop":
            self.stop()
        elif kind in ("reload_config", "status"):
            self.agent_mod.forget_capabilities() if kind == "reload_config" else None
            self.emit_config("config")
        elif kind == "list_conversations":
            self.list_conversations()
        elif kind == "history":
            self.history(str(request.get("conversation_id") or ""))
        elif kind == "delete_conversation":
            self.delete_conversation(str(request.get("conversation_id") or ""))
        else:
            self.out.emit("error", message="Pedido desconhecido.")

    def busy(self) -> bool:
        if self.worker is None:
            return False
        if self.worker.is_alive():
            # "done" is the worker's last act: a request right after it may
            # arrive while the thread is still returning
            self.worker.join(timeout=0.3)
        return self.worker.is_alive()

    def emit_config(self, kind: str = "config") -> None:
        cfg = self.cfg = self.load_config()
        supported = self.tools_supported_fn(cfg.model) if cfg.model else None
        vision = self.vision_supported_fn(cfg.model) if cfg.model else None
        self.out.emit(kind, version=__version__, protocol=PROTOCOL_VERSION, provider=cfg.provider,
                      model=cfg.model, think=cfg.think, tools_supported=supported, vision=vision,
                      read=cfg.read, write=cfg.write, tools=cfg.enabled_tools(), busy=self.busy())

    def _valid_conversation(self, conv: str) -> bool:
        return 0 < len(conv) <= 100 and all(c.isalnum() or c in "-_" for c in conv)

    def _check_message(self, conv: str, message) -> bool:
        if not self._valid_conversation(conv):
            self.out.emit("error", message="Conversa inválida.")
            return False
        if not isinstance(message, str) or not message.strip():
            self.out.emit("error", conversation_id=conv, message="Mensagem vazia.")
            return False
        if len(message) > MAX_MESSAGE:
            self.out.emit("error", conversation_id=conv, message="Mensagem longa demais.")
            return False
        if self.busy():
            self.out.emit("error", conversation_id=conv, message="Aguarde a resposta atual terminar.")
            return False
        return True

    def _agent_for(self, conv: str, agent_ref: str):
        """(ok, agent definition or None) for a request's optional "agent"."""
        if not agent_ref:
            return True, self._conversation_agent(conv)
        from . import agents
        agent_def = agents.find(agent_ref)
        if agent_def is None:
            self.out.emit("error", conversation_id=conv, message="Agente não encontrado: %s" % agent_ref)
            return False, None
        self._remember_agent(conv, agent_def["id"])
        return True, agent_def

    def ask_image(self, request: dict) -> None:
        """A question about an area of the screen (see screen.py)."""
        from . import screen
        conv = str(request.get("conversation_id") or "")
        message = request.get("message")
        if not self._check_message(conv, message):
            return
        try:
            req = screen.parse(request)
        except screen.ScreenError as exc:
            self.out.emit("error", conversation_id=conv, message=str(exc))
            return
        ok, agent_def = self._agent_for(conv, str(request.get("agent") or ""))
        if not ok:
            return
        self._start(lambda: self._ask_image(conv, message.strip(), req, agent_def))

    def _ask_image(self, conv: str, message: str, req, agent_def=None) -> None:
        from . import agents, screen
        model_name = agents.effective_config(self.load_config(), agent_def).model
        if not model_name:
            self.out.emit("error", conversation_id=conv,
                          message="Nenhum modelo de IA escolhido. Escolha um em Configurações › IA.")
            return
        if not req.intent:
            req.intent = screen.guess_intent(message)
        refusal = screen.cannot_read_message(req)
        if refusal:
            self.out.emit("error", conversation_id=conv, message=refusal)
            return
        can_see = bool(req.image) and self.vision_supported_fn(model_name) is True
        if not can_see and not req.ocr_text:
            self.out.emit("error", conversation_id=conv, message=screen.no_text_message(req, model_name))
            return
        # Translating reliable text: the words are enough (and much faster)
        vision = can_see and not screen.text_only(req)
        # A direct answer: no reasoning for screen questions, whatever ai.conf says
        # Translating or copying text needs no tools: a shorter prompt, a steadier small model
        setup = self._setup(conv, agent_def, think=False, extra_context=screen.context(req, vision, can_see),
                            exclude_functions=screen.EXCLUDED_FUNCTIONS, tools=not screen.text_only(req),
                            temperature=screen.TEXT_TEMPERATURE if screen.text_only(req) else None)
        if setup is None:
            return
        cfg, agent, model = setup
        self.out.emit("image_mode", conversation_id=conv, mode="vision" if vision else "ocr", model=cfg.model,
                      ocr_chars=len(req.ocr_text))
        self.out.emit("started", conversation_id=conv)
        clock = _Clock()
        images = None
        if vision:
            from agno.media import Image
            images = [Image(content=req.image, mime_type=req.mime, format=req.mime.split("/")[-1])]
        metadata = {"screen": True, "screen_mode": "vision" if vision else "ocr"}
        prompt = message
        if screen.text_only(req):
            # The text goes in the message; the history shows the question alone
            prompt = screen.with_text(message, req)
            metadata["screen_question"] = message
        try:
            stream = agent.run(prompt, session_id=conv, stream=True, stream_events=True, images=images,
                               metadata=metadata)
            self._drive(conv, agent, model, cfg, stream, clock,
                        before_done=lambda: self._name_conversation(conv, message, screen.title(message)))
        except Exception as exc:
            self._fail(conv, cfg, exc)

    def chat(self, conv: str, message, agent_ref: str = "") -> None:
        if not self._valid_conversation(conv):
            self.out.emit("error", message="Conversa inválida.")
            return
        if not isinstance(message, str) or not message.strip():
            self.out.emit("error", conversation_id=conv, message="Mensagem vazia.")
            return
        if len(message) > MAX_MESSAGE:
            self.out.emit("error", conversation_id=conv, message="Mensagem longa demais.")
            return
        if self.busy():
            self.out.emit("error", conversation_id=conv, message="Aguarde a resposta atual terminar.")
            return
        agent_def = None
        if agent_ref:
            from . import agents
            agent_def = agents.find(agent_ref)
            if agent_def is None:
                self.out.emit("error", conversation_id=conv, message="Agente não encontrado: %s" % agent_ref)
                return
            self._remember_agent(conv, agent_def["id"])
        else:
            agent_def = self._conversation_agent(conv)
        self._start(lambda: self._chat(conv, message.strip(), agent_def))

    def _start(self, target) -> None:
        self.stop_flag.clear()
        self.worker = threading.Thread(target=self._guard(target), daemon=True)
        self.worker.start()

    def _guard(self, target):
        def run():
            try:
                target()
            except Exception as exc:
                log.error("worker failed: %s", type(exc).__name__)
                self.out.emit("error", message="Erro interno do assistente.")
        return run

    def confirm(self, request_id: str, allow: bool) -> None:
        with self.lock:
            pending = self.pending.get(request_id)
        if pending is not None:
            pending.allow = allow
            pending.event.set()
            return
        stored = self.stored.get(request_id)
        if stored is None:
            self.out.emit("error", message="Este pedido de confirmação não existe mais.")
            return
        conv, run_id = stored
        answers = self.stored_answers.setdefault(run_id, {})
        answers[request_id] = allow
        self.out.emit("confirmation_resolved", conversation_id=conv, request_id=request_id, allow=allow)
        waiting = [r for r, (c, rid) in self.stored.items() if rid == run_id and r not in answers]
        if waiting:
            return
        if self.busy():
            self.out.emit("error", conversation_id=conv, message="Aguarde a resposta atual terminar.")
            return
        for r in [r for r, (c, rid) in self.stored.items() if rid == run_id]:
            del self.stored[r]
        self.stored_answers.pop(run_id, None)
        self._start(lambda: self._resume_stored(conv, run_id, answers))

    def stop(self) -> None:
        self.stop_flag.set()
        with self.lock:
            for p in self.pending.values():
                p.event.set()

    # ------------------------------------------------------------------ runs

    # ------------------------------------------------------------------ agents per conversation

    def _agents_file(self):
        return config.data_dir() / "conversation-agents.json"

    def _load_conv_agents(self) -> dict:
        from . import store
        data = store.read_json(self._agents_file(), {})
        return data if isinstance(data, dict) else {}

    def _remember_agent(self, conv: str, agent_id: str) -> None:
        from . import store
        data = self._load_conv_agents()
        if data.get(conv) == agent_id:
            return
        data[conv] = agent_id
        if len(data) > 2000:
            data = dict(list(data.items())[-2000:])
        try:
            store.write_json(self._agents_file(), data)
        except OSError:
            pass

    def _conversation_agent(self, conv: str):
        from . import agents
        aid = self._load_conv_agents().get(conv)
        return agents.find(aid) if aid else None

    def _setup(self, conv: str, agent_def=None, think: Optional[bool] = None, extra_context: str = "",
               exclude_functions: frozenset = frozenset(), tools: bool = True,
               temperature: Optional[float] = None):
        from . import agents
        import dataclasses
        base = self.load_config()
        cfg = agents.effective_config(base, agent_def)
        if think is not None:
            cfg = dataclasses.replace(cfg, think=think)
        self.cfg = base
        if cfg.provider != "ollama":
            self.out.emit("error", conversation_id=conv,
                          message="O Assistente usa modelos do Ollama. Escolha Ollama em Configurações › IA.")
            return None
        if not cfg.model:
            self.out.emit("error", conversation_id=conv,
                          message="Nenhum modelo de IA escolhido. Escolha um em Configurações › IA.")
            return None
        supported = self.tools_supported_fn(cfg.model)
        tools_on = tools and supported is not False and bool(cfg.enabled_tools())
        if supported is False and conv not in self.notified_no_tools:
            self.notified_no_tools.add(conv)
            self.out.emit("notice", conversation_id=conv,
                          message="O modelo %s não tem suporte a ferramentas: respondo só conversando. "
                                  "Escolha um modelo com ferramentas em Configurações › IA." % cfg.model)
        if temperature is None and agent_def:
            temperature = agent_def.get("temperature")
        model = self.model_factory(cfg) if self.model_factory else self.agent_mod.make_model(cfg, temperature)
        agent = self.agent_mod.build_agent(cfg, self.ctx, self.db, tools_on, model=model, agent_def=agent_def,
                                           extra_context=extra_context, exclude_functions=exclude_functions)
        return cfg, agent, model

    def _chat(self, conv: str, message: str, agent_def=None) -> None:
        setup = self._setup(conv, agent_def)
        if setup is None:
            return
        cfg, agent, model = setup
        self.out.emit("started", conversation_id=conv)
        clock = _Clock()
        try:
            stream = agent.run(message, session_id=conv, stream=True, stream_events=True)
            self._drive(conv, agent, model, cfg, stream, clock,
                        before_done=lambda: self._name_conversation(conv, message))
        except Exception as exc:
            self._fail(conv, cfg, exc)

    def _resume_stored(self, conv: str, run_id: str, answers: dict[str, bool]) -> None:
        setup = self._setup(conv, self._conversation_agent(conv))
        if setup is None:
            return
        cfg, agent, model = setup
        run = self._find_run(conv, run_id)
        if run is None or not run.requirements:
            self.out.emit("error", conversation_id=conv, message="Este pedido de confirmação não existe mais.")
            return
        for req in run.requirements:
            if not req.needs_confirmation:
                continue
            if answers.get(req.id):
                req.confirm()
            else:
                req.reject(note="The user declined this action. Nothing was written.")
        self.out.emit("started", conversation_id=conv)
        clock = _Clock()
        try:
            stream = agent.continue_run(run_id=run_id, requirements=run.requirements, session_id=conv,
                                        stream=True, stream_events=True)
            self._drive(conv, agent, model, cfg, stream, clock)
        except Exception as exc:
            self._fail(conv, cfg, exc)

    def _fail(self, conv: str, cfg: config.Config, exc: Exception) -> None:
        log.warning("run failed: %s", type(exc).__name__)
        text = "%s %s" % (type(exc).__name__, exc)
        if "does not support tools" in text.lower():
            self.agent_mod._caps_cache[cfg.model] = False
        self.out.emit("error", conversation_id=conv, message=friendly_error(text, cfg.model))

    def _drive(self, conv, agent, model, cfg, stream, clock, before_done=None) -> None:
        """Forwards one run's events; on a pause asks for confirmation and continues."""
        stopped = False
        while True:
            outcome, event = self._forward(conv, stream)
            if outcome == "paused":
                if self.stop_flag.is_set():
                    stopped = True
                    break
                clock.pause()
                answered = self._ask(conv, event)
                clock.resume()
                if not answered:
                    stopped = True
                    break
                stream = agent.continue_run(run_id=event.run_id, requirements=event.requirements,
                                            session_id=conv, stream=True, stream_events=True)
                continue
            if outcome == "error":
                self.out.emit("error", conversation_id=conv, message=friendly_error(event, cfg.model))
                return
            stopped = outcome == "stopped"
            break
        if before_done is not None:
            before_done()   # e.g. the title, so a list right after "done" has it
        usage = getattr(model, "usage", None)
        tps = usage.tokens_per_s() if usage else 0.0
        self.out.emit("done", conversation_id=conv, stopped=stopped,
                      stats={"seconds": round(clock.elapsed(), 1), "tokens_per_s": round(tps, 1),
                             "tokens": usage.eval_count if usage else 0, "model": cfg.model})

    def _forward(self, conv, stream):
        try:
            for ev in stream:
                if self.stop_flag.is_set():
                    _close(stream)
                    return "stopped", None
                name = getattr(ev, "event", "")
                if name == "RunContent":
                    content = getattr(ev, "content", None)
                    if isinstance(content, str) and content:
                        self.out.emit("token", conversation_id=conv, text=content)
                    reasoning = getattr(ev, "reasoning_content", None)
                    if reasoning:
                        self.out.emit("thinking", conversation_id=conv, text=reasoning)
                elif name == "ReasoningContentDelta":
                    if getattr(ev, "reasoning_content", ""):
                        self.out.emit("thinking", conversation_id=conv, text=ev.reasoning_content)
                elif name == "ToolCallStarted" and ev.tool is not None:
                    fn = ev.tool.tool_name or ""
                    self.out.emit("tool_start", conversation_id=conv,
                                  tool=self.tools_mod.FUNCTION_TOOL.get(fn, fn), function=fn,
                                  args_summary=self.tools_mod.args_summary(fn, ev.tool.tool_args or {}))
                elif name == "ToolCallCompleted" and ev.tool is not None:
                    self._tool_end(conv, ev.tool)
                elif name == "RunPaused":
                    return "paused", ev
                elif name == "RunError":
                    return "error", str(getattr(ev, "content", "") or "")
                elif name == "RunCancelled":
                    return "stopped", None
                elif name == "RunCompleted":
                    return "done", ev
        except GeneratorExit:
            raise
        return ("stopped" if self.stop_flag.is_set() else "done"), None

    def _tool_end(self, conv, tool) -> None:
        fn = tool.tool_name or ""
        record = self.ctx.pop_record(fn)
        ok = record.ok if record else not tool.tool_call_error
        summary = record.summary if record else ("" if ok else "Falhou")
        if tool.confirmed is False:
            ok, summary = False, "Recusado"
        self.out.emit("tool_end", conversation_id=conv, tool=self.tools_mod.FUNCTION_TOOL.get(fn, fn),
                      function=fn, ok=ok, summary=summary, output=_display_output(tool.result))

    def _ask(self, conv, event) -> bool:
        """Confirmation for every write requirement; False when stopped."""
        for req in list(event.requirements or []):
            if not req.needs_confirmation:
                continue
            te = req.tool_execution
            fn = te.tool_name or ""
            try:
                preview = self.ctx.preview(fn, te.tool_args or {})
            except self.tools_mod.KNOWN_ERRORS as exc:
                # Invalid or forbidden: refuse without bothering the user
                req.reject(note="Refused automatically: %s" % exc)
                self.out.emit("tool_end", conversation_id=conv, tool=self.tools_mod.FUNCTION_TOOL.get(fn, fn),
                              function=fn, ok=False, summary=str(exc), output="")
                continue
            pending = Pending(req.id, conv)
            with self.lock:
                self.pending[req.id] = pending
            self.out.emit("confirmation_required", conversation_id=conv, request_id=req.id,
                          tool=preview.tool, function=fn, title=preview.title, details=preview.details)
            while not pending.event.wait(0.5):
                if self.stop_flag.is_set() or self.closing.is_set():
                    break
            with self.lock:
                self.pending.pop(req.id, None)
            if pending.allow is None:
                # Left paused in the database: the Assistente app can still answer it
                return False
            self.out.emit("confirmation_resolved", conversation_id=conv, request_id=req.id,
                          allow=bool(pending.allow))
            if pending.allow:
                req.confirm()
            else:
                req.reject(note="The user declined this action. Nothing was written.")
        return True

    # ------------------------------------------------------------------ conversations

    def _session(self, conv: str):
        from agno.db.base import SessionType
        try:
            return self.db.get_session(session_id=conv, session_type=SessionType.AGENT)
        except Exception as exc:
            log.warning("session read failed: %s", type(exc).__name__)
            return None

    def _find_run(self, conv: str, run_id: str):
        session = self._session(conv)
        for run in (getattr(session, "runs", None) or []):
            if run.run_id == run_id:
                return run
        return None

    def _name_conversation(self, conv: str, message: str, title: str = "") -> None:
        from agno.db.base import SessionType
        session = self._session(conv)
        if session is None:
            return
        data = session.session_data or {}
        if data.get("session_name"):
            return
        if not title:
            title = " ".join(message.split())
            title = title if len(title) <= 60 else title[:57].rstrip() + "…"
        try:
            self.db.rename_session(session_id=conv, session_type=SessionType.AGENT, session_name=title)
        except Exception as exc:
            log.warning("rename failed: %s", type(exc).__name__)

    def list_conversations(self) -> None:
        from agno.db.base import SessionType
        items = []
        try:
            sessions = self.db.get_sessions(session_type=SessionType.AGENT, sort_by="updated_at",
                                            sort_order="desc", limit=200, include_runs=False)
        except Exception as exc:
            log.warning("list failed: %s", type(exc).__name__)
            sessions = []
        conv_agents = self._load_conv_agents()
        for s in sessions or []:
            if str(s.session_id).startswith("flow-"):
                continue      # workflow "ask an agent" runs, not conversations
            title = (s.session_data or {}).get("session_name") or "Conversa"
            items.append({"id": s.session_id, "title": title, "updated": s.updated_at or s.created_at or 0,
                          "agent": conv_agents.get(s.session_id, "")})
        self.out.emit("conversations", items=items)

    def history(self, conv: str) -> None:
        if not self._valid_conversation(conv):
            self.out.emit("error", message="Conversa inválida.")
            return
        session = self._session(conv)
        messages, pending = [], []
        title = ""
        if session is not None:
            title = (session.session_data or {}).get("session_name") or ""
            for run in session.runs or []:
                status = str(getattr(run.status, "value", run.status))
                if status == "REGENERATED":
                    continue
                text = run.input.input_content if run.input else ""
                meta = getattr(run, "metadata", None) or {}
                if meta.get("screen") and isinstance(meta.get("screen_question"), str):
                    # the question, without the screen text it carried
                    text = meta["screen_question"]
                if isinstance(text, str) and text:
                    item = {"role": "user", "text": text}
                    if meta.get("screen"):
                        # asked about an area of the screen (the picture itself isn't stored)
                        item["screen"] = str(meta.get("screen_mode") or "ocr")
                    messages.append(item)
                tools = []
                for t in run.tools or []:
                    fn = t.tool_name or ""
                    ok = not t.tool_call_error and t.confirmed is not False
                    if status == "PAUSED" and t.requires_confirmation and t.confirmed is None:
                        continue
                    tools.append({"tool": self.tools_mod.FUNCTION_TOOL.get(fn, fn), "function": fn,
                                  "args_summary": self.tools_mod.args_summary(fn, t.tool_args or {}),
                                  "ok": ok, "summary": "Recusado" if t.confirmed is False else "",
                                  "output": _display_output(t.result)})
                # A paused run's content is agno's placeholder, not an answer
                answer = run.content if isinstance(run.content, str) and status != "PAUSED" else ""
                if answer or tools:
                    messages.append({"role": "assistant", "text": answer or "", "tools": tools})
                if status == "PAUSED" and run is session.runs[-1]:
                    for req in run.requirements or []:
                        if not req.needs_confirmation:
                            continue
                        te = req.tool_execution
                        try:
                            pv = self.ctx.preview(te.tool_name or "", te.tool_args or {})
                        except self.tools_mod.KNOWN_ERRORS as exc:
                            pv = None
                            reason = str(exc)
                        if pv is None:
                            pending.append({"request_id": req.id, "tool": self.tools_mod.FUNCTION_TOOL.get(
                                te.tool_name or "", ""), "function": te.tool_name, "title": "Ação inválida",
                                "details": reason, "invalid": True})
                        else:
                            pending.append({"request_id": req.id, "tool": pv.tool, "function": pv.function,
                                            "title": pv.title, "details": pv.details})
                        self.stored[req.id] = (conv, run.run_id)
        self.out.emit("history", conversation_id=conv, title=title, messages=messages, pending=pending,
                      agent=self._load_conv_agents().get(conv, ""))

    def delete_conversation(self, conv: str) -> None:
        """Removes the app's own chat history for this conversation (never user data)."""
        if not self._valid_conversation(conv):
            self.out.emit("error", message="Conversa inválida.")
            return
        try:
            self.db.delete_session(conv)
        except Exception as exc:
            log.warning("delete failed: %s", type(exc).__name__)
            self.out.emit("error", conversation_id=conv, message="Não foi possível apagar a conversa.")
            return
        self.out.emit("deleted", conversation_id=conv)


class _Clock:
    """Wall time of a run, minus the time spent waiting for the user."""

    def __init__(self):
        self.start = time.monotonic()
        self.waited = 0.0
        self.paused_at = None

    def pause(self):
        self.paused_at = time.monotonic()

    def resume(self):
        if self.paused_at is not None:
            self.waited += time.monotonic() - self.paused_at
            self.paused_at = None

    def elapsed(self) -> float:
        return time.monotonic() - self.start - self.waited


def _close(stream) -> None:
    close = getattr(stream, "close", None)
    if close:
        try:
            close()
        except Exception:
            pass


def _display_output(result) -> str:
    if not isinstance(result, str):
        return ""
    text = result
    for marker in ("<<<END OF UNTRUSTED CONTENT>>>",):
        text = text.replace(marker, "")
    if text.startswith("<<<UNTRUSTED CONTENT"):
        text = text.split(">>>\n", 1)[-1]
    text = text.strip()
    return text if len(text) <= OUTPUT_PREVIEW else text[:OUTPUT_PREVIEW] + "\n…"


def setup_logging() -> None:
    level = logging.DEBUG if os.environ.get("LINGMO_ASSISTANT_DEBUG") else logging.WARNING
    logging.basicConfig(stream=sys.stderr, level=level, format="lingmo-assistant: %(levelname)s %(message)s")
    # agno logs tool arguments and errors with contents: silence it unless debugging
    if not os.environ.get("LINGMO_ASSISTANT_DEBUG"):
        for name in list(logging.root.manager.loggerDict):
            if name.startswith("agno"):
                logging.getLogger(name).disabled = True
        logging.getLogger("agno").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)


def serve(stdin, out: Output, engine: Engine) -> None:
    engine.emit_config("ready")
    while True:
        line = stdin.readline(MAX_LINE + 1)
        if not line:
            break
        if len(line) > MAX_LINE:
            out.emit("error", message="Pedido grande demais.")
            # drop the rest of the oversized line
            while line and not line.endswith("\n"):
                line = stdin.readline(MAX_LINE)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            out.emit("error", message="Pedido inválido (JSON).")
            continue
        engine.handle(request)
    # stdin closed: finish the current answer (a pending confirmation counts as
    # unanswered and stays paused in the database), then exit
    engine.closing.set()
    engine.extra.closing()
    if engine.worker is not None:
        engine.worker.join()


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--list-commands" in argv:
        print(json.dumps(shell.command_names()))
        return 0
    if "--version" in argv:
        print(__version__)
        return 0
    if "--flows-daemon" in argv or "--run" in argv or "--status" in argv:
        from .flows import daemon
        return daemon.main(argv)
    if "--voice-status" in argv:
        from . import voice
        print(voice.dumps_status())
        return 0
    os.environ["AGNO_TELEMETRY"] = "false"
    # Local only: never send prompts to the Ollama cloud
    os.environ.pop("OLLAMA_API_KEY", None)
    stream = protect_stdout()
    setup_logging()
    out = Output(stream)
    try:
        engine = Engine(out)
        setup_logging()   # agno loggers exist now
    except Exception as exc:
        log.error("start-up failed: %s", type(exc).__name__)
        out.emit("error", message="O motor do assistente não pôde iniciar (dependências ausentes?).")
        return 1
    serve(sys.stdin, out, engine)
    return 0
