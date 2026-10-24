"""Protocol requests for agents, workflows and voice (see docs/protocol.md,
"Protocol 2"). Kept apart from engine.py: the Engine owns one of these and
forwards the request types it doesn't handle itself."""
from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from .. import agents, config, store, voice
from . import graph, runner, service

log = logging.getLogger("lingmo_assistant.flows")

TYPES = {
    "models", "agents", "agent_save", "agent_remove", "flow_catalogue", "flows", "flow_get", "flow_new",
    "flow_save", "flow_approve", "flow_set_enabled", "flow_remove", "flow_import", "flow_export", "flow_validate",
    "flow_run", "flow_answer", "flow_stop", "flow_runs", "flow_run_log", "voice_start", "voice_stop",
    "voice_cancel", "voice_status", "speak", "speak_stop", "voice_command",
}


class _Ask:
    def __init__(self):
        self.event = threading.Event()
        self.answer: Any = None


class Handler:
    def __init__(self, engine):
        from .ai import AI
        self.engine = engine
        self.out = engine.out
        mf = engine.model_factory
        self.ai = AI(engine.load_config, model_factory=mf, db=engine.db, tool_ctx=engine.ctx,
                     tools_supported=engine.tools_supported_fn)
        self.runs: dict[str, runner.FlowRunner] = {}
        self.asks: dict[str, _Ask] = {}
        self.lock = threading.Lock()
        self.recorder: Optional[voice.Recorder] = None
        self.speaker = voice.Speaker()
        # Each engine owns its recordings; another instance's abandoned files
        # must never be reused or removed by this one.
        self.tmp = Path(tempfile.mkdtemp(prefix="lingmo-assistant-%d-" % _uid()))

    def handle(self, kind: str, r: dict) -> None:
        try:
            getattr(self, "on_" + kind)(r)
        except (ValueError, graph.FlowError) as exc:
            self.out.emit("error", message=str(exc) or "Pedido inválido.", request=kind)
        except Exception as exc:
            log.error("%s failed: %s", kind, type(exc).__name__)
            self.out.emit("error", message="Erro interno do assistente.", request=kind)

    def closing(self) -> None:
        for r in list(self.runs.values()):
            r.stop()
        with self.lock:
            for a in self.asks.values():
                a.event.set()
        if self.recorder:
            self.recorder.cancel()
        self.speaker.stop()

    # ------------------------------------------------------------------ models and agents

    def on_models(self, r):
        self.out.emit("models", items=installed_models(self.engine.load_config()))

    def emit_agents(self):
        cfg = self.engine.load_config()
        tools = [{"id": t, "group": g, "enabled": cfg.tool_enabled(t)} for t, (g, _) in config.TOOLS.items()]
        self.out.emit("agents", items=agents.all_agents(), tools=tools, read=cfg.read, write=cfg.write,
                      default_model=cfg.model)

    def on_agents(self, r):
        self.emit_agents()

    def on_agent_save(self, r):
        doc = r.get("agent")
        if not isinstance(doc, dict):
            raise ValueError("Agente inválido.")
        doc = dict(doc)
        if not doc.get("id"):
            base = agents.slug(doc.get("name", ""))
            aid, i = base, 2
            while agents.STORE.get(aid) is not None:
                aid, i = "%s-%d" % (base, i), i + 1
            doc["id"] = aid
        saved = agents.STORE.save(doc)
        self.out.emit("agent_saved", agent=saved)
        self.emit_agents()

    def on_agent_remove(self, r):
        agents.STORE.remove(str(r.get("id") or ""))
        self.emit_agents()

    # ------------------------------------------------------------------ workflows

    def on_flow_catalogue(self, r):
        cat = service.node_catalogue()
        cfg = self.engine.load_config()
        try:
            from .. import mail
            accounts = mail.accounts()
        except Exception:
            accounts = []
        from .. import tools
        self.out.emit("flow_catalogue", categories=cat["categories"], types=cat["types"], templates=cat["templates"],
                      accounts=accounts, agents=[{"id": a["id"], "name": a["name"], "emoji": a["emoji"]}
                                                 for a in agents.all_agents()],
                      folders=[tools.short_path(f) for f in cfg.folders],
                      tools={t: cfg.tool_enabled(t) for t in config.TOOLS})

    def on_flows(self, r):
        self.out.emit("flows", items=service.list_flows(self.engine.load_config()),
                      running=[{"run_id": x.id, "flow_id": x.flow["id"], "status": x.record["status"]}
                               for x in self.runs.values()])

    def on_flow_get(self, r):
        flow = service.FLOWS.get(str(r.get("id") or ""))
        if flow is None:
            raise ValueError("Fluxo não encontrado.")
        self.out.emit("flow", flow=flow, info=service.describe(flow, self.engine.load_config()))

    def on_flow_new(self, r):
        template = str(r.get("template") or "")
        if template:
            flow = service.from_template(template)
        else:
            flow = graph.normalize({"name": r.get("name") or "Novo fluxo", "nodes": [
                {"id": "trigger", "type": "trigger.manual", "x": 60, "y": 120, "params": {}}], "edges": []},
                keep_id=False)
        flow["revision"] = 0
        self.out.emit("flow", flow=flow, info=service.describe(flow, self.engine.load_config()), unsaved=True)

    def on_flow_validate(self, r):
        flow = graph.normalize(r.get("flow") or {})
        info = service.describe(flow, self.engine.load_config())
        self.out.emit("flow_issues", id=flow["id"], issues=info["issues"], summary=info["summary"],
                      capabilities=info["capabilities"], approved=info["approved"])

    def on_flow_save(self, r):
        flow = graph.normalize(r.get("flow") or {})
        if graph.errors(flow) and flow.get("enabled", True):
            # saved, but switched off until it's valid
            flow["enabled"] = False
        saved = service.save(flow)
        self.out.emit("flow_saved", flow=saved, info=service.describe(saved, self.engine.load_config()))
        self.on_flows({})

    def on_flow_approve(self, r):
        info = service.approve(str(r.get("id") or ""), str(r.get("cap_hash") or ""), bool(r.get("dont_ask")))
        flow = service.FLOWS.get(info["id"])
        self.out.emit("flow_saved", flow=flow, info=info)
        self.on_flows({})

    def on_flow_set_enabled(self, r):
        flow = service.FLOWS.get(str(r.get("id") or ""))
        if flow is None:
            raise ValueError("Fluxo não encontrado.")
        flow["enabled"] = bool(r.get("enabled"))
        if flow["enabled"] and graph.errors(flow):
            raise ValueError("Corrija os erros do fluxo antes de ativá-lo.")
        saved = service.save(flow)
        self.out.emit("flow_saved", flow=saved, info=service.describe(saved, self.engine.load_config()))
        self.on_flows({})

    def on_flow_remove(self, r):
        service.remove(str(r.get("id") or ""))
        self.on_flows({})

    def on_flow_import(self, r):
        text = r.get("text")
        if not isinstance(text, str) or len(text) > 2 * 1024 * 1024:
            raise ValueError("Arquivo inválido.")
        saved = service.import_text(text)
        self.out.emit("flow_saved", flow=saved, info=service.describe(saved, self.engine.load_config()))
        self.on_flows({})

    def on_flow_export(self, r):
        fid = str(r.get("id") or "")
        self.out.emit("flow_export", id=fid, text=service.export_text(fid))

    def on_flow_runs(self, r):
        fid = str(r.get("flow_id") or "")
        self.out.emit("flow_runs", flow_id=fid, items=store.list_runs(fid))

    def on_flow_run_log(self, r):
        run = store.get_run(str(r.get("flow_id") or ""), str(r.get("run_id") or ""))
        if run is None:
            raise ValueError("Execução não encontrada.")
        self.out.emit("flow_run_log", run=run)

    def on_flow_run(self, r, trigger_data: Optional[dict] = None, source: str = "app"):
        fid = str(r.get("flow_id") or "")
        flow = service.FLOWS.get(fid)
        if flow is None:
            raise ValueError("Salve o fluxo antes de executá-lo.")
        if any(x.flow["id"] == fid for x in self.runs.values()):
            raise ValueError("Este fluxo já está rodando.")
        mode = "test" if r.get("mode") == "test" else "run"

        def ask(kind, run_id, flow, node, request_id, title, details, external):
            a = _Ask()
            with self.lock:
                self.asks[request_id] = a
            self.out.emit("flow_ask", run_id=run_id, flow_id=flow["id"], request_id=request_id, node=node,
                          kind=kind, title=title, details=details, external=external)
            while not a.event.wait(0.5):
                if self.engine.closing.is_set() or run_obj.stop_event.is_set():
                    break
            with self.lock:
                self.asks.pop(request_id, None)
            self.out.emit("flow_ask_resolved", run_id=run_id, request_id=request_id)
            return a.answer

        def speak(text):
            self.speaker.speak(text, self.engine.load_config(), self.tmp)

        data = trigger_data if trigger_data is not None else dict(runner.now_outputs(), text=str(r.get("text") or ""))
        run_obj = runner.FlowRunner(flow, emit=self.out.emit, ask=ask, load_config=self.engine.load_config,
                                    ai=self.ai, speak=speak, mode=mode, source=source, trigger_data=data,
                                    tool_ctx=self.engine.ctx)
        with self.lock:
            self.runs[run_obj.id] = run_obj

        def work():
            try:
                run_obj.run()
            finally:
                with self.lock:
                    self.runs.pop(run_obj.id, None)
        threading.Thread(target=work, daemon=True).start()
        return run_obj.id

    def on_flow_answer(self, r):
        with self.lock:
            a = self.asks.get(str(r.get("request_id") or ""))
        if a is None:
            self.out.emit("error", message="Esta pergunta não existe mais.")
            return
        if "text" in r:
            a.answer = {"text": str(r.get("text") or "")[:10000]} if r.get("allow", True) else None
        else:
            a.answer = {"allow": bool(r.get("allow")), "dont_ask": bool(r.get("dont_ask"))}
        a.event.set()

    def on_flow_stop(self, r):
        run_obj = self.runs.get(str(r.get("run_id") or ""))
        if run_obj:
            run_obj.stop()

    # ------------------------------------------------------------------ voice

    def on_voice_status(self, r):
        self.out.emit("voice_status", **voice.status())

    def on_voice_start(self, r):
        if self.recorder is not None:
            self.recorder.stop()          # a second press ends the recording
            return
        last = {"t": 0.0}

        def level(value, seconds):
            import time
            now = time.monotonic()
            if now - last["t"] >= 0.08:
                last["t"] = now
                self.out.emit("voice_level", level=round(value, 3), seconds=round(seconds, 1))

        rec = voice.Recorder(level)
        self.recorder = rec
        threading.Thread(target=self._listen, args=(rec, bool(r.get("commands", True))), daemon=True).start()

    def _listen(self, rec: voice.Recorder, commands: bool) -> None:
        wav = None
        try:
            self.speaker.stop()
            self.out.emit("voice_state", state="listening")
            pcm = rec.record()
            self.recorder = None
            if rec.cancelled:
                self.out.emit("voice_state", state="idle")
                return
            if not pcm:
                self.out.emit("voice_state", state="idle", message="Não ouvi nada.")
                self.out.emit("voice_text", text="", flow_id="")
                return
            self.out.emit("voice_state", state="transcribing")
            wav = voice.write_wav(pcm, self.tmp)
            text = voice.transcribe(wav, self.engine.load_config())
            wav.unlink()
            wav = None
            flow = service.match_voice(text, self.ai) if (commands and text) else None
            self.out.emit("voice_text", text=text, flow_id=flow["id"] if flow else "",
                          flow_name=flow["name"] if flow else "")
            self.out.emit("voice_state", state="idle")
            if flow is not None:
                self.on_flow_run({"flow_id": flow["id"]}, {"text": text, "output": text}, "voice")
        except voice.VoiceError as exc:
            self.out.emit("voice_state", state="error", message=str(exc))
        except Exception as exc:
            log.error("voice failed: %s", type(exc).__name__)
            self.out.emit("voice_state", state="error", message="A voz falhou.")
        finally:
            self.recorder = None
            if wav is not None:
                try:
                    wav.unlink()
                except OSError:
                    pass

    def on_voice_stop(self, r):
        if self.recorder is not None:
            self.recorder.stop()

    def on_voice_cancel(self, r):
        if self.recorder is not None:
            self.recorder.cancel()

    def on_voice_command(self, r):
        text = str(r.get("text") or "").strip()
        flow = service.match_voice(text, self.ai) if text else None
        self.out.emit("voice_text", text=text, flow_id=flow["id"] if flow else "",
                      flow_name=flow["name"] if flow else "")
        if flow is not None:
            self.on_flow_run({"flow_id": flow["id"]}, {"text": text, "output": text}, "voice")

    def on_speak(self, r):
        text = str(r.get("text") or "")

        def work():
            self.out.emit("speak_state", speaking=True)
            try:
                kept = self.speaker.speak(text, self.engine.load_config(), self.tmp)
                if kept:
                    self.out.emit("speak_file", path=str(kept))
            except voice.VoiceError as exc:
                self.out.emit("error", message=str(exc), request="speak")
            finally:
                self.out.emit("speak_state", speaking=False)
        threading.Thread(target=work, daemon=True).start()

    def on_speak_stop(self, r):
        self.speaker.stop()


def _uid() -> int:
    import os
    return os.getuid()


def installed_models(cfg: config.Config) -> list[dict]:
    """Installed Ollama models with capability tags (same ids as Settings' tags)."""
    from .. import agent as agent_mod
    try:
        from ollama import Client
        client = Client(host=agent_mod.ollama_host(), timeout=10)
        listing = client.list()
        models = getattr(listing, "models", None) or listing.get("models", [])
    except Exception as exc:
        log.info("models unavailable: %s", type(exc).__name__)
        return []
    out = []
    for m in models:
        name = getattr(m, "model", None) or (m.get("model") if isinstance(m, dict) else "")
        size = getattr(m, "size", None) or (m.get("size") if isinstance(m, dict) else 0) or 0
        try:
            info = client.show(name)
            caps = list(getattr(info, "capabilities", None) or (info.get("capabilities") if isinstance(info, dict) else [])
                        or [])
        except Exception:
            caps = []
        tags = []
        if "tools" in caps:
            tags.append({"id": "tools", "text": "Ferramentas"})
        if "thinking" in caps:
            tags.append({"id": "thinking", "text": "Raciocínio"})
        if "vision" in caps:
            tags.append({"id": "vision", "text": "Visão"})
        if "embedding" in caps:
            tags.append({"id": "embedding", "text": "Embeddings"})
        if size and size < 2.6e9 and "embedding" not in caps:
            tags.append({"id": "fast", "text": "Rápido"})
        if any(k in name for k in ("qwen", "gemma", "llama3", "mistral", "aya")) and "embedding" not in caps:
            tags.append({"id": "multilingual", "text": "Multilíngue"})
        out.append({"name": name, "size": size, "tools": "tools" in caps, "thinking": "thinking" in caps,
                    "embedding": "embedding" in caps, "tags": tags, "in_use": name == cfg.model,
                    "recommended": "tools" in caps and "embedding" not in caps})
    return out


