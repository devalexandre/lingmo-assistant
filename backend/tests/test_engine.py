import io
import json
import threading
import time

import pytest

from fakemodel import FakeModel
from lingmo_assistant import config, engine as engine_mod
from lingmo_assistant.agent import database


class Capture:
    def __init__(self):
        self.lines = []
        self.cond = threading.Condition()

    def write(self, s):
        with self.cond:
            for line in s.splitlines():
                if line.strip():
                    self.lines.append(json.loads(line))
            self.cond.notify_all()

    def flush(self):
        pass

    def wait_for(self, type_, count=1, timeout=20):
        deadline = time.monotonic() + timeout
        with self.cond:
            while sum(1 for e in self.lines if e["type"] == type_) < count:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise AssertionError("no %s event; got %s" % (type_, [e["type"] for e in self.lines]))
                self.cond.wait(left)
            return [e for e in self.lines if e["type"] == type_][count - 1]

    def types(self):
        return [e["type"] for e in self.lines]


@pytest.fixture
def make_engine(home, conf, tmp_path, monkeypatch):
    monkeypatch.setenv("LINGMO_ASSISTANT_NOTES_DIR", str(home / "notes"))
    conf(assistant_write=True)
    db = database(str(tmp_path / "a.db"))

    def make(script, supported=True):
        cap = Capture()
        models = []

        def factory(cfg):
            m = FakeModel(id=cfg.model, script=script)
            models.append(m)
            return m
        eng = engine_mod.Engine(engine_mod.Output(cap), db=db, model_factory=factory,
                                tools_supported=lambda model: supported)
        return eng, cap, models
    return make


def test_protocol_framing_and_streaming(make_engine):
    eng, cap, _ = make_engine([("think", "hmm", "Olá mundo")])
    stdin = io.StringIO('{"type":"chat","conversation_id":"c1","message":"oi"}\nnot json\n{"type":"what"}\n')
    engine_mod.serve(stdin, eng.out, eng)
    assert cap.lines[0]["type"] == "ready" and cap.lines[0]["protocol"] == 1
    done = cap.wait_for("done")
    text = "".join(e["text"] for e in cap.lines if e["type"] == "token")
    assert text.strip() == "Olá mundo"
    assert any(e["type"] == "thinking" for e in cap.lines)
    assert done["stats"]["tokens_per_s"] == 20.0 and done["stopped"] is False
    errors = [e["message"] for e in cap.lines if e["type"] == "error"]
    assert "Pedido inválido (JSON)." in errors and "Pedido desconhecido." in errors


def test_tool_events(make_engine):
    eng, cap, _ = make_engine([("tool", "system_info", {}), ("text", "Pronto")])
    eng.handle({"type": "chat", "conversation_id": "c1", "message": "minha cpu?"})
    cap.wait_for("done")
    start = cap.wait_for("tool_start")
    end = cap.wait_for("tool_end")
    assert start["tool"] == "system_info" and end["ok"] is True and "CPU" in end["output"]


def test_confirmation_allow(make_engine, home):
    eng, cap, models = make_engine([("tool", "create_note", {"title": "Compras", "content": "- leite"}),
                                    ("text", "Criei a nota")])
    eng.handle({"type": "chat", "conversation_id": "c1", "message": "crie"})
    req = cap.wait_for("confirmation_required")
    assert req["tool"] == "notes_write" and "Título: Compras" in req["details"] and "- leite" in req["details"]
    assert not list((home / "notes").glob("*.md")) if (home / "notes").exists() else True
    eng.handle({"type": "confirm", "request_id": req["request_id"], "allow": True})
    cap.wait_for("done")
    files = list((home / "notes").glob("*.md"))
    assert len(files) == 1 and "# Compras" in files[0].read_text()
    end = cap.wait_for("tool_end")
    assert end["ok"] is True and end["function"] == "create_note"


def test_confirmation_deny(make_engine, home):
    eng, cap, models = make_engine([("tool", "write_file", {"path": "~/Documents/x.txt", "content": "oi"}),
                                    ("text", "Ok, não criei")])
    eng.handle({"type": "chat", "conversation_id": "c1", "message": "crie"})
    req = cap.wait_for("confirmation_required")
    eng.handle({"type": "confirm", "request_id": req["request_id"], "allow": False})
    cap.wait_for("done")
    assert not (home / "Documents" / "x.txt").exists()
    # the model was told the user declined
    assert any("declined" in (c or "") for r, c in models[0].seen[-1] if r == "tool")


def test_invalid_write_refused_without_asking(make_engine, home):
    eng, cap, _ = make_engine([("tool", "write_file", {"path": "~/.ssh/authorized_keys.txt", "content": "k"}),
                               ("text", "Não posso")])
    eng.handle({"type": "chat", "conversation_id": "c1", "message": "crie"})
    cap.wait_for("done")
    assert "confirmation_required" not in cap.types()
    assert cap.wait_for("tool_end")["ok"] is False


def test_stop_while_waiting_then_resume_elsewhere(make_engine, home):
    eng, cap, _ = make_engine([("tool", "create_note", {"title": "Depois", "content": "x"})])
    eng.handle({"type": "chat", "conversation_id": "c9", "message": "crie"})
    req = cap.wait_for("confirmation_required")
    eng.handle({"type": "stop"})
    done = cap.wait_for("done")
    assert done["stopped"] is True
    # a second engine (the Assistente app) picks the paused run up from the database
    eng2, cap2, _ = make_engine([("text", "Feito")])
    eng2.handle({"type": "history", "conversation_id": "c9"})
    hist = cap2.wait_for("history")
    assert [p["request_id"] for p in hist["pending"]] == [req["request_id"]]
    assert hist["messages"][0] == {"role": "user", "text": "crie"}
    eng2.handle({"type": "confirm", "request_id": req["request_id"], "allow": True})
    cap2.wait_for("done")
    files = list((home / "notes").glob("*.md"))
    assert len(files) == 1 and "# Depois" in files[0].read_text()


def test_conversations_list_history_delete(make_engine):
    eng, cap, _ = make_engine([("text", "a"), ("text", "b")])
    eng.handle({"type": "chat", "conversation_id": "c1", "message": "Primeira pergunta"})
    cap.wait_for("done")
    eng.handle({"type": "chat", "conversation_id": "c1", "message": "segunda"})
    cap.wait_for("done", 2)
    eng.handle({"type": "list_conversations"})
    items = cap.wait_for("conversations")["items"]
    assert items[0]["id"] == "c1" and items[0]["title"] == "Primeira pergunta"
    eng.handle({"type": "history", "conversation_id": "c1"})
    msgs = cap.wait_for("history")["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user", "assistant"]
    eng.handle({"type": "delete_conversation", "conversation_id": "c1"})
    cap.wait_for("deleted")
    eng.handle({"type": "list_conversations"})
    assert cap.wait_for("conversations", 2)["items"] == []
    eng.handle({"type": "history", "conversation_id": "../x"})
    assert cap.lines[-1]["type"] == "error"


def test_model_without_tools(make_engine):
    eng, cap, models = make_engine([("text", "Só conversa")], supported=False)
    eng.handle({"type": "chat", "conversation_id": "c1", "message": "oi"})
    cap.wait_for("done")
    assert "ferramentas" in cap.wait_for("notice")["message"]
    assert "no tools" in models[0].seen[0][0][1]


def test_busy_and_bad_requests(make_engine):
    eng, cap, _ = make_engine([("tool", "create_note", {"title": "x", "content": ""})])
    eng.handle({"type": "chat", "conversation_id": "c1", "message": "crie"})
    cap.wait_for("confirmation_required")
    eng.handle({"type": "chat", "conversation_id": "c1", "message": "outra"})
    assert cap.lines[-1] == {"type": "error", "conversation_id": "c1", "message": "Aguarde a resposta atual terminar."}
    eng.handle({"type": "confirm", "request_id": "nope", "allow": True})
    assert "não existe" in cap.lines[-1]["message"]
    eng.handle({"type": "stop"})
    cap.wait_for("done")


def test_stdout_is_protected(tmp_path):
    import os
    import subprocess
    import sys
    code = ("import os,sys; sys.path.insert(0, %r)\n"
            "from lingmo_assistant import engine\n"
            "s = engine.protect_stdout()\n"
            "print('stray print'); os.write(1, b'stray fd write\\n')\n"
            "engine.Output(s).emit('ready')\n") % str(__import__('pathlib').Path(__file__).resolve().parents[1])
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.stdout == '{"type":"ready"}\n'
    assert "stray print" in res.stderr and "stray fd write" in res.stderr


def test_friendly_errors():
    f = engine_mod.friendly_error
    assert "não está rodando" in f("ConnectError [Errno 111] Connection refused", "m")
    assert "não está instalado" in f("ResponseError model 'x' not found (status code: 404)", "x")
    assert "ferramentas" in f("registry.ollama.ai/library/gemma does not support tools", "gemma")
