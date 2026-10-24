"""Protocol 2 end to end through Engine.handle(): agents, workflows (save →
approve → run → ask → answer), voice commands and speech (when piper and
whisper are installed)."""
import os
import shutil
from pathlib import Path

import pytest

from fakemodel import FakeModel
from lingmo_assistant import engine as engine_mod, voice
from lingmo_assistant.agent import database
from test_engine import Capture


@pytest.fixture
def eng(home, conf, tmp_path, monkeypatch):
    monkeypatch.setenv("LINGMO_ASSISTANT_NOTES_DIR", str(home / "notes"))
    conf(assistant_write=True)
    cap = Capture()
    script = []
    e = engine_mod.Engine(engine_mod.Output(cap), db=database(str(tmp_path / "a.db")),
                          model_factory=lambda cfg: FakeModel(id=cfg.model, script=script),
                          tools_supported=lambda m: True)
    e.script = script
    yield e, cap
    e.closing.set()
    e.extra.closing()


def test_voice_storage_is_private_per_engine(eng):
    from lingmo_assistant.flows.protocol import Handler
    import stat

    e, _ = eng
    other = Handler(e)
    try:
        assert e.extra.tmp != other.tmp
        assert stat.S_IMODE(e.extra.tmp.stat().st_mode) == 0o700
        assert stat.S_IMODE(other.tmp.stat().st_mode) == 0o700
        abandoned = e.extra.tmp / "voice-old.wav"
        abandoned.write_bytes(b"private recording")
        assert not list(other.tmp.glob("voice-*.wav"))
        other.closing()
        assert abandoned.read_bytes() == b"private recording"
    finally:
        other.closing()


def test_agents_requests(eng):
    e, cap = eng
    e.handle({"type": "agents"})
    ev = cap.wait_for("agents")
    assert len(ev["items"]) == 4 and any(t["id"] == "mail_write" for t in ev["tools"])
    e.handle({"type": "agent_save", "agent": {"name": "Meu Agente", "emoji": "🦉", "tools": ["notes_read"],
                                             "instructions": "Seja breve."}})
    saved = cap.wait_for("agent_saved")["agent"]
    assert saved["id"] == "meu-agente"
    e.handle({"type": "agent_save", "agent": {"name": "Meu Agente"}})
    assert cap.wait_for("agent_saved", 2)["agent"]["id"] == "meu-agente-2"
    e.handle({"type": "agent_remove", "id": "meu-agente-2"})
    assert all(a["id"] != "meu-agente-2" for a in cap.wait_for("agents", 4)["items"])


def test_chat_with_agent_uses_its_instructions(eng):
    e, cap = eng
    e.script.append(("text", "Oi!"))
    e.handle({"type": "chat", "conversation_id": "c9", "message": "olá", "agent": "@redator"})
    cap.wait_for("done")
    e.handle({"type": "history", "conversation_id": "c9"})
    assert cap.wait_for("history")["agent"] == "redator"
    e.handle({"type": "chat", "conversation_id": "c8", "message": "olá", "agent": "ninguem"})
    assert "Agente não encontrado" in cap.wait_for("error")["message"]


def test_flow_lifecycle(eng, home):
    e, cap = eng
    e.handle({"type": "flow_catalogue"})
    cat = cap.wait_for("flow_catalogue")
    assert {c["id"] for c in cat["categories"]} == {"triggers", "actions", "ai", "logic"}
    assert len(cat["templates"]) == 5
    e.handle({"type": "flow_new", "template": "meeting-reminder"})
    new = cap.wait_for("flow")
    assert new["unsaved"] and new["info"]["issues"] == []

    target = home / "Documents" / "fluxo.txt"
    doc = {"id": "teste1", "name": "Teste", "nodes": [
        {"id": "trigger", "type": "trigger.manual", "params": {}},
        {"id": "q", "type": "logic.ask", "params": {"mode": "confirm", "question": "Seguir?"}},
        {"id": "w", "type": "action.files.write", "params": {"path": str(target), "content": "ok", "mode": "create"}}],
        "edges": [{"from": "trigger", "to": "q"}, {"from": "q", "port": "yes", "to": "w"}]}
    e.handle({"type": "flow_save", "flow": doc})
    saved = cap.wait_for("flow_saved")
    info = saved["info"]
    assert info["approved"] is False and info["summary"] == "Este fluxo pode criar arquivos nas pastas permitidas."
    e.handle({"type": "flow_run", "flow_id": "teste1"})
    done = cap.wait_for("flow_run_done")
    assert done["status"] == "refused"
    e.handle({"type": "flow_approve", "id": "teste1", "cap_hash": "outro"})
    assert "mudou" in cap.wait_for("error")["message"]
    e.handle({"type": "flow_approve", "id": "teste1", "cap_hash": info["cap_hash"]})
    assert cap.wait_for("flow_saved", 2)["info"]["approved"] is True

    e.handle({"type": "flow_run", "flow_id": "teste1", "mode": "test"})
    ask = cap.wait_for("flow_ask")
    assert ask["kind"] == "confirm" and ask["node"] == "q"
    e.handle({"type": "flow_answer", "request_id": ask["request_id"], "allow": True})
    ask2 = cap.wait_for("flow_ask", 2)              # test mode: the write asks too
    assert ask2["node"] == "w" and "fluxo.txt" in ask2["details"]
    e.handle({"type": "flow_answer", "request_id": ask2["request_id"], "allow": True})
    done = cap.wait_for("flow_run_done", 2)
    assert done["status"] == "done" and target.read_text() == "ok"
    running = [ev for ev in cap.lines if ev["type"] == "flow_node" and ev["run_id"] == done["run_id"]]
    assert [ev["status"] for ev in running if ev["node"] == "w"] == ["running", "waiting", "running", "done"]

    e.handle({"type": "flow_runs", "flow_id": "teste1"})
    runs = cap.wait_for("flow_runs")["items"]
    assert [r["status"] for r in runs][:2] == ["done", "refused"]
    e.handle({"type": "flow_run_log", "flow_id": "teste1", "run_id": runs[0]["id"]})
    assert [s["node"] for s in cap.wait_for("flow_run_log")["run"]["steps"]] == ["trigger", "q", "w"]

    e.handle({"type": "flow_export", "id": "teste1"})
    text = cap.wait_for("flow_export")["text"]
    e.handle({"type": "flow_import", "text": text})
    imported = cap.wait_for("flow_saved", 3)
    assert imported["flow"]["id"] != "teste1" and imported["info"]["approved"] is False
    e.handle({"type": "flow_remove", "id": imported["flow"]["id"]})
    e.handle({"type": "flows"})
    flows = cap.wait_for("flows", 5)["items"]
    assert [f["id"] for f in flows] == ["teste1"]


def test_voice_command_runs_matching_flow(eng, home):
    e, cap = eng
    from lingmo_assistant.flows import graph, permissions, service, templates
    doc = graph.normalize({"id": "vz", "name": "Voz", "nodes": [
        {"id": "trigger", "type": "trigger.voice", "params": {"phrases": ["boa noite assistente"]}},
        {"id": "s", "type": "logic.set", "params": {"name": "x", "value": "{{trigger.text}}"}}],
        "edges": [{"from": "trigger", "to": "s"}]})
    service.save(doc)
    del templates, permissions
    e.handle({"type": "voice_command", "text": "Boa noite, assistente!"})
    vt = cap.wait_for("voice_text")
    assert vt["flow_id"] == "vz"
    done = cap.wait_for("flow_run_done")
    assert done["status"] == "done"
    e.handle({"type": "voice_command", "text": "abre o navegador"})
    assert cap.wait_for("voice_text", 2)["flow_id"] == ""


REAL_MODELS = Path(os.path.expanduser("~/.local/share/lingmo/whisper-models"))   # read-only use
needs_voice = pytest.mark.skipif(
    not (voice.piper_binary() and voice.whisper_binary() and list(REAL_MODELS.glob("ggml-*.bin"))
         and list(Path("/usr/share/piper-voices").rglob("pt_BR-*.onnx"))),
    reason="piper-tts, a pt_BR voice, whisper-cli and a whisper model are needed")


@needs_voice
def test_speech_round_trip(eng, home, tmp_path, monkeypatch):
    """piper says a phrase into a WAV, the "microphone" plays that WAV, whisper transcribes it."""
    e, cap = eng
    models = tmp_path / "models"
    models.mkdir()
    real = sorted(REAL_MODELS.glob("ggml-*.bin"))[0]
    (models / real.name).symlink_to(real)            # the user's model, read-only
    monkeypatch.setenv("LINGMO_WHISPER_MODELS", str(models))
    out = tmp_path / "tts"
    out.mkdir()
    monkeypatch.setenv("LINGMO_ASSISTANT_TTS_OUTPUT", str(out))
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    e.handle({"type": "speak", "text": "**Me acorde às sete horas.**"})
    wav = Path(cap.wait_for("speak_file", timeout=120)["path"])
    assert voice.wav_duration(wav) > 1.0
    monkeypatch.setenv("LINGMO_ASSISTANT_VOICE_INPUT", str(wav))
    e.handle({"type": "voice_start"})
    assert cap.wait_for("voice_state")["state"] == "listening"
    text = cap.wait_for("voice_text", timeout=300)["text"]
    assert any(ev["type"] == "voice_level" and ev["level"] > 0.1 for ev in cap.lines)
    assert "acorde" in text.lower() and ("sete" in text.lower() or "7" in text)
    assert not list(Path(e.extra.tmp).glob("voice-*.wav"))        # recording removed
