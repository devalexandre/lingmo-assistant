"""The AI nodes' helper: plain completions (summarise, classify, extract,
translate, AI reply drafts, voice-phrase matching) and "ask an agent", whose
write tools keep agno's requires_confirmation: a pause becomes a workflow
confirmation and the agno run continues with the user's answer."""
from __future__ import annotations

import logging
from typing import Callable, Optional

from agno.agent import Agent

from .. import agent as agent_mod, agents, config, tools

log = logging.getLogger("lingmo_assistant.flows")


class AIError(Exception):
    pass


class AI:
    def __init__(self, load_config: Callable[[], config.Config] = config.load, model_factory=None, db=None,
                 tool_ctx: Optional[tools.ToolContext] = None, tools_supported=None):
        self.load_config = load_config
        self.model_factory = model_factory          # tests: cfg -> model
        self.db = db
        self.tool_ctx = tool_ctx or tools.ToolContext(load_config)
        self.tools_supported = tools_supported or agent_mod.supports_tools
        self.confirm: Callable[[str, str], bool] = lambda title, details: False

    def bind(self, confirm: Callable[[str, str], bool]) -> None:
        self.confirm = confirm

    def _model(self, cfg: config.Config, temperature=None):
        if not cfg.model:
            raise AIError("Nenhum modelo de IA escolhido em Configurações › IA.")
        if self.model_factory:
            return self.model_factory(cfg)
        return agent_mod.make_model(cfg, temperature)

    def complete(self, system: str, prompt: str, agent_def: Optional[dict] = None) -> str:
        cfg = agents.effective_config(self.load_config(), agent_def)
        model = self._model(cfg, 0.3 if agent_def is None else agent_def.get("temperature"))
        a = Agent(model=model, system_message=system, telemetry=False, markdown=False)
        try:
            result = a.run(prompt)
        except Exception as exc:
            raise AIError(agent_mod_friendly(exc, cfg.model)) from exc
        text = str(result.content or "").strip()
        if getattr(result, "status", None) is not None and str(getattr(result.status, "value", result.status)) == "ERROR":
            raise AIError(agent_mod_friendly(Exception(text), cfg.model))
        return text

    def ask_agent(self, agent_def: Optional[dict], prompt: str, session_id: str = "") -> str:
        """Runs the agent with its tools; confirmations go through self.confirm."""
        base = self.load_config()
        cfg = agents.effective_config(base, agent_def)
        model = self._model(cfg, agent_def.get("temperature") if agent_def else None)
        supported = self.tools_supported(cfg.model) if cfg.model else None
        tools_on = supported is not False and bool(cfg.enabled_tools())
        a = agent_mod.build_agent(cfg, self.tool_ctx, self.db, tools_on, model=model, agent_def=agent_def)
        import uuid
        kwargs = {"session_id": session_id or ("flow-" + uuid.uuid4().hex)} if self.db is not None else {}
        try:
            result = a.run(prompt, **kwargs)
            for _ in range(12):
                if not getattr(result, "is_paused", False):
                    break
                for req in list(result.requirements or []):
                    if not req.needs_confirmation:
                        continue
                    te = req.tool_execution
                    fn = te.tool_name or ""
                    try:
                        pv = self.tool_ctx.preview(fn, te.tool_args or {})
                    except tools.KNOWN_ERRORS as exc:
                        req.reject(note="Refused automatically: %s" % exc)
                        continue
                    if self.confirm(pv.title, pv.details):
                        req.confirm()
                    else:
                        req.reject(note="The user declined this action. Nothing was written.")
                result = a.continue_run(run_response=result, requirements=result.requirements, **kwargs)
        except AIError:
            raise
        except Exception as exc:
            if type(exc).__name__ in ("Stopped",):
                raise
            raise AIError(agent_mod_friendly(exc, cfg.model)) from exc
        return str(result.content or "").strip()

    def match_phrase(self, utterance: str, phrases: list[str]) -> bool:
        """Does what was said mean the same as one of the phrases? (voice trigger, "IA" mode)"""
        answer = self.complete(
            "Você decide se um comando de voz tem o mesmo pedido que alguma das frases de referência. "
            "Responda só SIM ou NAO.",
            "Comando: %s\nFrases de referência:\n%s" % (utterance, "\n".join("- " + p for p in phrases)))
        return answer.strip().upper().startswith("SIM")


def agent_mod_friendly(exc: Exception, model: str) -> str:
    from ..engine import friendly_error
    return friendly_error("%s %s" % (type(exc).__name__, exc), model)
