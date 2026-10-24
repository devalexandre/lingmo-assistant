"""The mail nodes end to end: engine → Lingmo Mail's own worker (backend.py, as a
subprocess) → a local fake IMAPS/SMTPS server. Scratch HOME, a fake
secret-tool, a throw-away certificate: no real account or keyring is touched."""
import json
import os
from email.message import EmailMessage
from pathlib import Path

import pytest

from lingmo_assistant import config, mail, store
from lingmo_assistant.flows import graph, permissions, runner, service, templates, triggers

BACKEND = Path(__file__).resolve().parents[3] / "lingmo-mail" / "backend" / "backend.py"

pytestmark = pytest.mark.skipif(not BACKEND.is_file(), reason="lingmo-mail sources not next to this repo")


@pytest.fixture
def server(home, conf, tmp_path, monkeypatch):
    pytest.importorskip("aiosmtpd")
    from fake_mail import FakeMail
    conf(assistant_write=True)
    fm = FakeMail(tmp_path)
    acc = fm.account()
    accounts = home / ".config" / "lingmo-online-accounts" / "accounts.json"
    accounts.parent.mkdir(parents=True)
    accounts.write_text(json.dumps([acc]))
    bindir = tmp_path / "bin"
    bindir.mkdir()
    st = bindir / "secret-tool"
    st.write_text("#!/bin/sh\n[ \"$1\" = lookup ] && echo senha-de-teste\nexit 0\n")
    st.chmod(0o755)
    monkeypatch.setenv("PATH", "%s:%s" % (bindir, os.environ["PATH"]))
    monkeypatch.setenv("SSL_CERT_FILE", str(fm.cert))
    monkeypatch.setenv("LINGMO_ASSISTANT_MAIL_BACKEND", str(BACKEND))
    yield fm
    fm.close()


def message(sender, subject, body, attachment=None):
    m = EmailMessage()
    m["From"] = sender
    m["To"] = "eu@exemplo.com"
    m["Subject"] = subject
    m["Date"] = "Sat, 24 Oct 2026 09:00:00 -0300"
    m["Message-ID"] = "<%s@exemplo.com>" % abs(hash(subject))
    m.set_content(body)
    if attachment:
        m.add_attachment(attachment[1], maintype="application", subtype="pdf", filename=attachment[0])
    return m.as_bytes()


def approve(f):
    store.set_approval(f["id"], permissions.cap_hash(service.capabilities(f)), False)


def run(f, data, answers=None):
    asks = []
    answers = list(answers or [])

    def ask(**kw):
        asks.append(kw)
        return answers.pop(0) if answers else {"allow": True}
    r = runner.FlowRunner(f, emit=lambda *a, **k: None, ask=ask, trigger_data=data,
                          ai=_FakeAI("Obrigado, vou ver isso hoje."))
    return r.run(), asks


class _FakeAI:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    def complete(self, system, prompt, agent_def=None):
        self.prompts.append(prompt)
        return self.reply


def test_mail_worker_operations(server, home):
    server.box.add("INBOX", message("Chefe <chefe@empresa.com>", "Relatório", "Mande o relatório."))
    acc = mail.account("eu@exemplo.com")
    msgs = mail.list_messages(acc["id"], "INBOX", unread_only=True)
    assert [m["subject"] for m in msgs] == ["Relatório"]
    full = mail.read_message(acc["id"], msgs[0]["id"])
    assert "Mande o relatório." in full["body"]
    # peek: still unread for the user
    assert "\\Seen" not in server.box.folders["INBOX"][0]["flags"]
    # the user's filter rules never run from the assistant (checkNew is always false)
    assert not any("SEARCH" in l and "UID" in l and ">" in l for l in server.box.log)
    mail.organize(acc["id"], msgs[0]["id"], "INBOX", "star")
    assert "\\Flagged" in server.box.folders["INBOX"][0]["flags"]
    mail.organize(acc["id"], msgs[0]["id"], "INBOX", "move", "Trabalho")
    assert len(server.box.folders["Trabalho"]) == 1 and not server.box.folders["INBOX"]
    with pytest.raises(mail.MailError):
        mail.organize(acc["id"], msgs[0]["id"], "Trabalho", "delete")
    assert server.box.folders["Trash"] == []


def test_reply_boss_template_end_to_end(server, home):
    """New mail from the boss → watcher fires → AI drafts → per-run confirmation shows the
    draft → sent through SMTP as a reply."""
    f = graph.normalize(templates.instantiate("reply-boss"), keep_id=False)
    f["nodes"][2]["type"] = "logic.set"                  # no desktop notification in tests
    f["nodes"][2]["params"] = {"name": "fim", "value": "{{resposta.to}}"}
    f = service.save(f)
    approve(f)
    w = triggers.Watchers()
    server.box.add("INBOX", message("Outro <o@x.com>", "Antigo", "velho"))
    assert w.poll([f], 0) == []                             # baseline
    server.box.add("INBOX", message("Spam <s@x.com>", "Promoção", "compre"))
    server.box.add("INBOX", message("Chefe <chefe@empresa.com>", "Prazo do projeto", "Consegue até sexta?"))
    due = w.poll([f], 1000)
    assert len(due) == 1 and due[0][1]["subject"] == "Prazo do projeto"
    rec, asks = run(f, due[0][1], [{"allow": False}])
    assert rec["status"] == "done" and server.sent == []      # declined: nothing sent
    assert asks[0]["external"] and "Obrigado, vou ver isso hoje." in asks[0]["details"]
    assert "Para: Chefe <chefe@empresa.com>" in asks[0]["details"] and "De: eu@exemplo.com" in asks[0]["details"]
    rec, asks = run(f, due[0][1], [{"allow": True}])
    assert rec["status"] == "done", rec["error"]
    assert len(server.sent) == 1
    sent = server.sent[0].decode()
    assert "Subject: Re: Prazo do projeto" in sent and "In-Reply-To:" in sent
    assert "Obrigado, vou ver isso hoje." in sent and "> Consegue até sexta?" in sent


def test_save_attachments_template(server, home):
    f = graph.normalize(templates.instantiate("save-attachments"), keep_id=False)
    f["nodes"][2]["type"] = "logic.set"
    f["nodes"][2]["params"] = {"name": "fim", "value": "{{salvar.output}}"}
    f["nodes"][1]["params"]["dest"] = str(home / "Documents" / "Anexos")
    f = service.save(f)
    approve(f)
    w = triggers.Watchers()
    assert w.poll([f], 0) == []
    server.box.add("INBOX", message("Ana <ana@x.com>", "Contrato", "segue", ("../../etc/contrato.pdf", b"%PDF-1")))
    server.box.add("INBOX", message("Ana <ana@x.com>", "Sem anexo", "oi"))
    due = w.poll([f], 1000)
    assert [d[1]["subject"] for d in due] == ["Contrato"]
    rec, asks = run(f, due[0][1])
    assert rec["status"] == "done", rec["error"]
    saved = home / "Documents" / "Anexos" / "contrato.pdf"
    assert saved.read_bytes() == b"%PDF-1"
    # a second run never overwrites
    rec, _ = run(f, due[0][1])
    assert (home / "Documents" / "Anexos" / "contrato (2).pdf").exists()
    # outside the allowed folders: refused before the worker is asked
    f["nodes"][1]["params"]["dest"] = str(home / "fora")
    f = service.save(f)
    approve(f)
    rec, _ = run(f, due[0][1])
    assert rec["status"] == "failed" and not (home / "fora").exists()


def test_send_email_node_and_contact(server, home):
    f = graph.normalize({"id": "env", "name": "Enviar", "nodes": [
        {"id": "trigger", "type": "trigger.manual"},
        {"id": "m", "type": "action.mail.send", "params": {"to": "ana@x.com", "subject": "Oi {{trigger.output}}",
                                                           "body": "Corpo"}},
        {"id": "c", "type": "action.contacts.add", "params": {"name": "Ana", "email": "ana@x.com"}}],
        "edges": [{"from": "trigger", "to": "m"}, {"from": "m", "to": "c"}]})
    f = service.save(f)
    caps = service.capabilities(f)
    assert "enviar e-mails como eu@exemplo.com" in permissions.summary(caps)
    approve(f)
    rec, asks = run(f, {"output": "Ana"})
    assert rec["status"] == "done", rec["error"]
    assert "Subject: Oi Ana" in server.sent[0].decode()
    contacts = json.loads((home / ".local/share/lingmo-mail/contacts.json").read_text())
    items = contacts if isinstance(contacts, list) else contacts.get("contacts", [])
    assert any(c.get("name") == "Ana" for c in items)
