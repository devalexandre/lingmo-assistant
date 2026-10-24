"""Workflows: graph validation, templates, logic nodes, the permission gate,
the scheduler, trigger watchers, shortcuts and the engine protocol."""
import datetime as dt
import json
import time

import pytest

from fakemodel import FakeModel
from lingmo_assistant import config, store
from lingmo_assistant.flows import graph, nodes, permissions, runner, schedule, service, template, templates, triggers
from lingmo_assistant.flows.ai import AI


def flow(nodes_, edges, name="Teste", fid="f1"):
    return graph.normalize({"id": fid, "name": name, "nodes": nodes_, "edges": edges})


def n(id_, type_, **params):
    return {"id": id_, "type": type_, "params": params}


def e(a, b, port="out"):
    return {"from": a, "port": port, "to": b}


class Recorder:
    def __init__(self, answers=None):
        self.events = []
        self.asks = []
        self.answers = list(answers or [])

    def emit(self, type_, **fields):
        self.events.append(dict(fields, type=type_))

    def ask(self, **kw):
        self.asks.append(kw)
        return self.answers.pop(0) if self.answers else {"allow": True}

    def statuses(self, node):
        return [ev["status"] for ev in self.events if ev["type"] == "flow_node" and ev["node"] == node]


def run_flow(f, rec=None, cfg_loader=config.load, ai=None, mode="run", data=None, approve=True):
    rec = rec or Recorder()
    if approve:
        caps = service.capabilities(f, accounts={})
        store.set_approval(f["id"], permissions.cap_hash(caps), False)
    r = runner.FlowRunner(f, emit=rec.emit, ask=rec.ask, load_config=cfg_loader, ai=ai, mode=mode,
                          trigger_data=data or {"output": "oi"}, sleep=lambda s: None)
    return r.run(), rec


# ------------------------------------------------------------------ templating

def test_template_render_and_resolve():
    s = template.Scope(outputs={"mail": {"subject": "Oi", "list": ["a", "b"], "output": "corpo"},
                                "t": {"text": "x"}}, variables={"nome": "Ana"}, trigger_id="t",
                       now=dt.datetime(2026, 10, 24, 9, 5))
    missing = []
    assert template.render("Re: {{mail.subject}} {{ var.nome }} {{trigger.text}}", s, missing) == "Re: Oi Ana x"
    assert template.render("{{mail}}", s) == "corpo"
    assert template.render("{{mail.list.1}} {{now.date}} {{now.time}}", s) == "b 2026-10-24 09:05"
    assert template.resolve("{{mail.list}}", s) == ["a", "b"]
    assert template.render("{{nada.x}}|{{mail.zz}}", s, missing) == "|"
    assert missing == ["nada.x", "mail.zz"]
    # no code, no attribute access beyond the run's own data
    assert template.render("{{mail.__class__}}", s) == ""
    assert template.render("{{ 1+1 }}", s) == "{{ 1+1 }}"
    assert template.references({"a": "{{x.y}} {{var.z}}", "b": ["{{loop.item}}"]}) == ["x.y", "var.z", "loop.item"]


# ------------------------------------------------------------------ validation

def test_validation_rules():
    ok = flow([n("trigger", "trigger.manual"), n("aviso", "action.system.notify", title="Oi {{trigger.output}}")],
              [e("trigger", "aviso")])
    assert graph.errors(ok) == []

    no_trigger = flow([n("aviso", "action.system.notify", title="x")], [])
    assert any("gatilho" in i["message"] for i in graph.errors(no_trigger))

    two = flow([n("a", "trigger.manual"), n("b", "trigger.manual")], [])
    assert any("só um gatilho" in i["message"] for i in graph.errors(two))

    cyc = flow([n("trigger", "trigger.manual"), n("a", "logic.wait", seconds=1), n("b", "logic.wait", seconds=1)],
               [e("trigger", "a"), e("a", "b"), e("b", "a")])
    assert any("ciclo" in i["message"] for i in graph.errors(cyc))

    bad = flow([n("trigger", "trigger.manual"), n("x", "logic.if", value="1", op="contains"),
                n("Bad Id", "logic.wait", seconds=1), n("z", "action.system.notify", title="{{ghost.output}}")],
               [e("trigger", "x"), e("x", "z", "maybe"), e("z", "trigger")])
    msgs = " | ".join(i["message"] for i in graph.errors(bad))
    assert "Saída «maybe» inexistente" in msgs
    assert "Identificador inválido" in msgs
    assert "não há bloco «ghost»" in msgs
    assert "Um gatilho não recebe ligações" in msgs

    required = flow([n("trigger", "trigger.manual"), n("m", "action.mail.send", to="", subject="", body="")],
                    [e("trigger", "m")])
    assert len([i for i in graph.errors(required) if i["node"] == "m"]) == 3

    sched = flow([n("trigger", "trigger.schedule", schedule={"kind": "daily", "time": "25:00"})], [])
    assert any("Hora inválida" in i["message"] for i in graph.errors(sched))

    # warnings: unreachable node, reference to a node that doesn't run before
    w = flow([n("trigger", "trigger.manual"), n("a", "action.system.notify", title="{{b.output}}"),
              n("b", "action.system.notify", title="x")], [e("trigger", "a")])
    levels = {(i["node"], i["level"]) for i in graph.validate(w)}
    assert ("b", "warning") in levels and ("a", "warning") in levels


def test_every_template_is_valid_and_declares_its_capabilities():
    for t in templates.TEMPLATES:
        f = graph.normalize(templates.instantiate(t["template"]), keep_id=False)
        assert graph.errors(f) == [], t["template"]
    reply = graph.normalize(templates.instantiate("reply-boss"), keep_id=False)
    caps = permissions.capabilities(reply, {"acc1": "voce@exemplo.com"})
    text = permissions.summary(caps)
    assert "responder e-mails como voce@exemplo.com" in text and "pergunta a você" in text
    assert any(c.external for c in caps)


def test_variables_for_autocomplete():
    f = flow([n("trigger", "trigger.email"), n("x", "ai.extract", text="{{trigger.body}}", fields=["data", "hora"]),
              n("rep", "logic.loop", items="{{x.data}}"), n("in", "action.system.notify", title="{{loop.item}}"),
              n("after", "logic.set", name="final", value="1")],
             [e("trigger", "x"), e("x", "rep"), e("rep", "in", "each"), e("rep", "after", "done")])
    texts = [v["text"] for v in graph.variables_for(f, "in")]
    assert "{{trigger.subject}}" in texts and "{{x.hora}}" in texts and "{{loop.item}}" in texts
    assert "{{loop.item}}" not in [v["text"] for v in graph.variables_for(f, "after")]


# ------------------------------------------------------------------ permission gate

def test_delete_is_impossible(home, conf):
    conf(assistant_write=True)
    # no node type deletes
    assert not [t for t in nodes.TYPES if any(w in t.type for w in nodes.FORBIDDEN_WORDS)]
    assert "delete" not in [o["value"] for o in nodes.MAIL_ACTIONS]
    # a hand-written file asking for a delete action or node type is refused
    f = flow([n("trigger", "trigger.manual"), n("x", "action.mail.organize", message="1", action="delete"),
              n("y", "action.files.delete", path="~/Documents/a")], [e("trigger", "x"), e("x", "y")])
    msgs = [i["message"] for i in graph.errors(f)]
    assert "Fluxos não podem apagar nada." in msgs and "Opção inválida em «Ação»." in msgs
    with pytest.raises(permissions.PermissionDenied):
        permissions.check_node({"type": "action.files.delete"}, config.load())
    # and the mail layer never sends a delete, even if asked directly
    from lingmo_assistant import mail
    for req in ({"op": "act", "action": "delete"}, {"op": "remove"}, {"op": "deleteContact"},
                {"op": "act", "action": "move", "permanent": True}, {"op": "applyRules"}):
        with pytest.raises(mail.MailError):
            mail.call(req)


def test_write_needs_approval_and_global_caps(home, conf, tmp_path):
    conf(assistant_write=True)
    target = home / "Documents" / "log.txt"
    f = flow([n("trigger", "trigger.manual"),
              n("w", "action.files.write", path=str(target), content="linha {{trigger.output}}", mode="append")],
             [e("trigger", "w")])
    rec, _ = run_flow(f, approve=False)
    assert rec["status"] == "refused" and "Aprove" in rec["error"] and not target.exists()

    caps = permissions.capabilities(f)
    assert permissions.summary(caps).startswith("Este fluxo pode criar arquivos")
    store.set_approval(f["id"], permissions.cap_hash(caps), False)
    rec, events = run_flow(f, approve=False)
    assert rec["status"] == "done" and target.read_text() == "linha oi"

    # changing what the flow can do invalidates the approval
    f2 = flow(f["nodes"] + [n("m", "action.clock.alarm", time="07:00")], f["edges"] + [e("w", "m")])
    assert not permissions.is_approved(f2["id"], permissions.capabilities(f2))

    # the global switch in Settings caps everything, even an approved flow
    conf(assistant_write=False)
    rec, events = run_flow(f)
    assert rec["status"] == "failed" and "escrita" in rec["error"]
    assert target.read_text() == "linha oi"
    # and a tool unticked in Settings too
    conf(assistant_write=True, assistant_tools="system_info")
    rec, _ = run_flow(f)
    assert rec["status"] == "failed" and "desmarcada" in rec["error"]


def test_files_stay_in_allowed_folders(home, conf):
    conf(assistant_write=True)
    for bad in ("/etc/passwd-copy", str(home / ".ssh" / "x"), str(home / "fora.txt")):
        f = flow([n("trigger", "trigger.manual"), n("w", "action.files.write", path=bad, content="x", mode="create")],
                 [e("trigger", "w")], fid="fx")
        rec, _ = run_flow(f)
        assert rec["status"] == "failed", bad
    assert not (home / "fora.txt").exists()


def test_external_nodes_ask_every_run_unless_dont_ask(home, conf, monkeypatch):
    conf(assistant_write=True)
    from lingmo_assistant import mail
    sent = []
    monkeypatch.setattr(mail, "accounts", lambda: [{"id": "a1", "name": "Eu", "email": "eu@x.com"}])
    monkeypatch.setattr(mail, "send", lambda acc, draft: sent.append((acc, draft)) or {"sent": True})
    f = flow([n("trigger", "trigger.manual"),
              n("m", "action.mail.send", to="ana@x.com", subject="Oi", body="Texto {{trigger.output}}")],
             [e("trigger", "m")])
    # declined: nothing sent, branch stops
    rec, r = run_flow(f, Recorder([{"allow": False}]))
    assert rec["status"] == "done" and sent == [] and r.statuses("m")[-1] == "declined"
    assert "Para: ana@x.com" in r.asks[0]["details"] and r.asks[0]["external"] is True
    # allowed with "não perguntar de novo"
    rec, r = run_flow(f, Recorder([{"allow": True, "dont_ask": True}]))
    assert len(sent) == 1 and sent[0][1]["body"] == "Texto oi"
    # approval keeps dont_ask only until re-approved; next run doesn't ask
    caps = permissions.capabilities(f)
    store.set_dont_ask(f["id"], True)
    rec, r = run_flow(f, Recorder([]), approve=False)
    assert r.asks == [] and len(sent) == 2
    # "Testar" always asks for every write
    rec, r = run_flow(f, Recorder([{"allow": False}]), mode="test", approve=False)
    assert len(r.asks) == 1 and len(sent) == 2
    del caps


# ------------------------------------------------------------------ logic nodes

def test_condition_switch_set_and_loop(home, conf):
    conf()
    f = flow([n("trigger", "trigger.manual"),
              n("cond", "logic.if", value="{{trigger.output}}", op="contains", compare="URGENTE"),
              n("sim", "logic.set", name="rota", value="sim"),
              n("nao", "logic.set", name="rota", value="nao"),
              n("sw", "logic.switch", value="{{var.rota}}", cases=["sim", "nao"]),
              n("lista", "logic.set", name="itens", value="{{trigger.items}}"),
              n("rep", "logic.loop", items="{{var.itens}}"),
              n("cada", "logic.set", name="ultimo", value="{{loop.number}}:{{loop.item}}"),
              n("fim", "logic.set", name="fim", value="{{rep.count}}")],
             [e("trigger", "cond"), e("cond", "sim", "true"), e("cond", "nao", "false"), e("sim", "sw"),
              e("nao", "sw"), e("sw", "lista", "case_0"), e("lista", "rep"), e("rep", "cada", "each"),
              e("rep", "fim", "done")])
    assert graph.errors(f) == []
    rec, r = run_flow(f, data={"output": "isto é URGENTE", "items": ["a", "b", "c"]})
    assert rec["status"] == "done"
    ran = [s["node"] for s in rec["steps"]]
    assert "sim" in ran and "nao" not in ran
    assert ran.count("cada") == 3 and ran.index("fim") > ran.index("cada")
    last = [s for s in rec["steps"] if s["node"] == "cada"][-1]
    assert last["outputs"]["output"] == "3:c"
    assert [s for s in rec["steps"] if s["node"] == "fim"][0]["outputs"]["output"] == "3"

    rec, r = run_flow(f, data={"output": "tranquilo", "items": []})
    ran = [s["node"] for s in rec["steps"]]
    assert "nao" in ran and "lista" not in ran      # switch went to case_1, which isn't connected


def test_loop_over_text_lines_and_limit(home, conf):
    conf()
    f = flow([n("trigger", "trigger.manual"), n("rep", "logic.loop", items="{{trigger.output}}", max=2),
              n("cada", "logic.set", name="x", value="{{loop.item}}")],
             [e("trigger", "rep"), e("rep", "cada", "each")])
    rec, _ = run_flow(f, data={"output": "um\n\ndois\ntrês"})
    assert [s["outputs"]["output"] for s in rec["steps"] if s["node"] == "cada"] == ["um", "dois"]


def test_compare_ops():
    assert runner.compare("gt", "10", "9") and runner.compare("lt", "2,5", "3")
    assert runner.compare("empty", "  ", "") and runner.compare("not_empty", "x", "")
    assert runner.compare("equals", "Sim", "sim") and runner.compare("starts", "Re: oi", "re:")
    assert not runner.compare("gt", "abc", "1")


def test_ask_user_and_stop(home, conf):
    conf()
    f = flow([n("trigger", "trigger.manual"), n("q", "logic.ask", mode="input", question="Nome?"),
              n("s", "logic.set", name="n", value="Olá {{q.output}}")], [e("trigger", "q"), e("q", "s", "yes")])
    rec, r = run_flow(f, Recorder([{"text": "Ana"}]))
    assert rec["status"] == "done" and rec["steps"][-1]["outputs"]["output"] == "Olá Ana"
    assert "waiting" in r.statuses("q")
    rec, r = run_flow(f, Recorder([None]))         # no answer (window closed): stopped, nothing else ran
    assert rec["status"] == "stopped" and all(s["node"] != "s" for s in rec["steps"])


def test_run_history_is_logged(home, conf):
    conf()
    f = flow([n("trigger", "trigger.manual"), n("s", "logic.set", name="a", value="1")], [e("trigger", "s")])
    rec, _ = run_flow(f)
    runs = store.list_runs("f1")
    assert runs[0]["id"] == rec["id"] and runs[0]["status"] == "done"
    full = store.get_run("f1", rec["id"])
    assert [s["node"] for s in full["steps"]] == ["trigger", "s"]
    assert full["steps"][1]["inputs"]["name"] == "a"


# ------------------------------------------------------------------ AI nodes (fake model)

def test_ai_nodes_with_fake_model(home, conf):
    conf()
    script = [("text", "urgente"), ("text", 'Claro: {"data": "2026-10-25", "hora": "14:00"}'), ("text", "- resumo")]
    ai = AI(config.load, model_factory=lambda cfg: FakeModel(id=cfg.model, script=script))
    f = flow([n("trigger", "trigger.manual"), n("c", "ai.classify", text="{{trigger.output}}", categories=["normal", "urgente"]),
              n("x", "ai.extract", text="{{trigger.output}}", fields=["data", "hora"]),
              n("s", "ai.summarize", text="{{trigger.output}}"),
              n("v", "logic.set", name="quando", value="{{x.data}} {{x.hora}} {{c.category}}")],
             [e("trigger", "c"), e("c", "x"), e("x", "s"), e("s", "v")])
    rec, _ = run_flow(f, ai=ai, data={"output": "Reunião amanhã às 14h, urgente!"})
    assert rec["status"] == "done", rec["error"]
    assert rec["steps"][-1]["outputs"]["output"] == "2026-10-25 14:00 urgente"


def test_ask_agent_confirmation_goes_through_the_flow(home, conf, monkeypatch):
    conf(assistant_write=True)
    monkeypatch.setenv("LINGMO_ASSISTANT_NOTES_DIR", str(home / "notes"))
    from lingmo_assistant import agents
    agents.STORE.save({"id": "notas", "name": "Notas", "tools": ["notes_write"], "instructions": "Anote."})
    script = [("tool", "create_note", {"title": "Compras", "content": "- leite"}), ("text", "Criei a nota.")]
    ai = AI(config.load, model_factory=lambda cfg: FakeModel(id=cfg.model, script=script),
            tools_supported=lambda m: True)
    f = flow([n("trigger", "trigger.manual"), n("ag", "ai.agent", agent="notas", prompt="anote leite")],
             [e("trigger", "ag")])
    caps = permissions.capabilities(f, agent_tools={"notas": ["notes_write"]})
    assert "pelo agente" in permissions.summary(caps)
    rec, r = run_flow(f, Recorder([{"allow": True}]), ai=ai)
    assert rec["status"] == "done", rec["error"]
    assert r.asks and r.asks[0]["title"] == "Criar página no Notas" and "- leite" in r.asks[0]["details"]
    assert list((home / "notes").glob("*.md"))


# ------------------------------------------------------------------ scheduler

def test_schedule_next_times():
    tz = dt.timezone(dt.timedelta(hours=-3))
    base = dt.datetime(2026, 10, 24, 8, 30, tzinfo=tz)      # a Saturday
    assert schedule.next_after({"kind": "daily", "time": "09:00"}, base) == base.replace(hour=9, minute=0)
    assert schedule.next_after({"kind": "daily", "time": "08:00"}, base).day == 25
    wd = schedule.next_after({"kind": "weekdays", "time": "09:00", "days": [0, 1, 2, 3, 4]}, base)
    assert wd.date() == dt.date(2026, 10, 26) and wd.hour == 9
    assert schedule.next_after({"kind": "interval", "minutes": 45}, base) == base.replace(hour=9, minute=0)
    assert schedule.next_after({"kind": "monthly", "day": 1, "time": "07:00"}, base).date() == dt.date(2026, 11, 1)
    assert schedule.next_after({"kind": "once", "datetime": "2026-10-24T08:00"}, base) is None
    assert schedule.next_after({"kind": "cron", "cron": "*/15 9-10 * * 1-5"}, base) == \
        dt.datetime(2026, 10, 26, 9, 0, tzinfo=tz)
    assert schedule.next_after({"kind": "cron", "cron": "0 12 1 1 *"}, base).date() == dt.date(2027, 1, 1)
    # Sunday as 0 and 7
    assert schedule.next_after({"kind": "cron", "cron": "0 10 * * 7"}, base).date() == dt.date(2026, 10, 25)
    for bad in ({"kind": "cron", "cron": "60 * * * *"}, {"kind": "weekdays", "time": "9:00", "days": []},
                {"kind": "interval", "minutes": 0}, {"kind": "x"}, "daily"):
        with pytest.raises(schedule.ScheduleError):
            schedule.check(bad)
    assert schedule.describe({"kind": "weekdays", "time": "09:00", "days": [0, 1, 2, 3, 4]}) == "Seg a sex às 09:00"


def test_schedule_watcher_fires_once_per_slot(home, conf):
    conf()
    tz = dt.timezone.utc
    now = {"t": dt.datetime(2026, 10, 24, 8, 59, 30, tzinfo=tz)}
    w = triggers.Watchers(clock=lambda: now["t"])
    f = flow([n("trigger", "trigger.schedule", schedule={"kind": "daily", "time": "09:00"})], [])
    assert w.poll([f], 0) == []
    assert 25 <= w.next_wakeup([f], 0) <= 31
    now["t"] = now["t"].replace(hour=9, minute=0, second=5)
    due = w.poll([f], 1)
    assert len(due) == 1 and due[0][1]["time"] == "09:00"
    assert w.poll([f], 2) == []


def test_file_watcher(home, conf):
    conf()
    w = triggers.Watchers()
    f = flow([n("trigger", "trigger.file", folder=str(home / "Downloads"), pattern="*.pdf")], [])
    (home / "Downloads" / "velho.pdf").write_text("x")
    assert w.poll([f], 0) == []                  # baseline
    (home / "Downloads" / "novo.pdf").write_text("x")
    (home / "Downloads" / "nota.txt").write_text("x")
    due = w.poll([f], 100)
    assert [d[1]["name"] for d in due] == ["novo.pdf"] and due[0][1]["event"] == "created"
    # outside the allowed folders: never watched
    f2 = flow([n("trigger", "trigger.file", folder="/etc")], [], fid="f2")
    assert w.poll([f2], 200) == [] and w.poll([f2], 300) == []


def test_email_watcher_baseline_and_filter(home, conf, monkeypatch):
    conf()
    from lingmo_assistant import mail
    box = [{"id": "1", "sender": "Chefe <chefe@empresa.com>", "subject": "Antigo", "unread": True}]
    monkeypatch.setattr(mail, "accounts", lambda: [{"id": "a1", "name": "", "email": "eu@x.com"}])
    monkeypatch.setattr(mail, "list_messages", lambda *a, **k: list(box))
    monkeypatch.setattr(mail, "read_message", lambda acc, uid, folder: {"body": "corpo %s" % uid,
                                                                       "attachments": []})
    f = flow([n("trigger", "trigger.email", from_contains="chefe@empresa.com")], [])
    w = triggers.Watchers()
    assert w.poll([f], 0) == []
    box.insert(0, {"id": "2", "sender": "Outro <o@x.com>", "subject": "Spam", "unread": True})
    box.insert(0, {"id": "3", "sender": "Chefe <chefe@empresa.com>", "subject": "Relatório", "unread": True})
    due = w.poll([f], 1000)
    assert len(due) == 1 and due[0][1]["uid"] == "3" and due[0][1]["body"] == "corpo 3"
    assert due[0][1]["from_address"] == "chefe@empresa.com"
    assert w.poll([f], 2000) == []


# ------------------------------------------------------------------ store, import, shortcuts, voice match

def test_store_revisions_import_and_trash(home, conf):
    conf()
    f = flow([n("trigger", "trigger.manual")], [], fid="abc")
    s1 = service.save(f)
    s2 = service.save(dict(s1, name="Outro nome"))
    assert (s1["revision"], s2["revision"]) == (1, 2)
    assert (store.root() / "workflows" / ".history" / "abc" / "1.json").exists()
    store.set_approval("abc", "hash", True)
    imported = service.import_text(service.export_text("abc"))
    assert imported["id"] != "abc" and imported["enabled"] is False
    assert store.approval(imported["id"]) == {}            # never imported with an approval
    with pytest.raises(graph.FlowError):
        service.import_text('{"format": "other"}')
    service.remove("abc")
    assert service.FLOWS.get("abc") is None and list((store.root() / "workflows" / ".trash").glob("abc-*.json"))


def test_shortcut_sync_never_touches_other_entries(home, conf):
    conf()
    path = service.shortcuts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[Meta%2BI]\nComment=Assistant\nExec=lingmo-assistant\n\n[Meta%2BShift%2BG]\nExec=outra-coisa\n")
    f = flow([n("trigger", "trigger.shortcut", key="Meta+Shift+F")], [], fid="sc1")
    g = flow([n("trigger", "trigger.shortcut", key="Meta+Shift+G")], [], fid="sc2")
    service.save(f)
    assert service.save(g)
    text = path.read_text()
    assert "[Meta%2BShift%2BF]\nComment=Fluxo: Teste\nExec=lingmo-assistant-flows --run sc1" in text
    assert "--run sc2" not in text and "Exec=outra-coisa" in text and "Exec=lingmo-assistant\n" in text
    service.remove("sc1")
    text = path.read_text()
    assert "sc1" not in text and "[Meta%2BI]" in text


def test_voice_phrase_matching(home, conf):
    conf()
    from lingmo_assistant import voice
    assert voice.keyword_score("Me acorde às sete, por favor", "me acorde às sete") == 1.0
    assert voice.keyword_score("ME ACORDE AS SETE", "me acorde às sete") == 1.0
    assert voice.keyword_score("qual a previsão do tempo", "me acorde às sete") == 0.0
    t = graph.normalize(templates.instantiate("voice-alarm"), keep_id=False)
    service.save(t)
    assert service.match_voice("Me acorde às sete") is not None
    assert service.match_voice("toque uma música") is None
    assert voice.speech_text("# Título\n**negrito** e [link](https://x.y)\n```py\nx\n```") == \
        "Título negrito e link (código)"


def test_agents_store_and_caps(home, conf):
    conf(assistant_write=False)
    from lingmo_assistant import agents
    names = [a["name"] for a in agents.all_agents()]
    for s in ("Secretária de e-mail", "Organizador de agenda", "Resumidor de documentos", "Redator"):
        assert s in names
    assert agents.find("@secretaria")["id"] == "secretaria-de-email"
    assert agents.find("Redator")["id"] == "redator"
    a = agents.find("secretaria-de-email")
    eff = agents.effective_config(config.load(), a)
    # write group off in Settings: the agent's write tools stay off
    assert eff.enabled_tools() == ["calendar_read", "mail_read"]
    assert agents.write_tools(a, config.load()) == []
    bad = agents.normalize({"name": "X", "tools": ["mail_write", "rm_rf"], "temperature": 9})
    assert bad["tools"] == ["mail_write"] and bad["temperature"] == 2.0


def test_agent_knowledge_search(home, conf, monkeypatch):
    """Read-only RAG over allowed folders, with a stand-in embedding model."""
    conf()
    from lingmo_assistant import knowledge
    kb = home / "Documents" / "Empresa"
    kb.mkdir()
    (kb / "ferias.md").write_text("Política de férias: 30 dias por ano, pedir com 45 dias de antecedência.")
    (kb / "reembolso.txt").write_text("Reembolso de despesas: enviar notas em até 10 dias.")
    (home / ".ssh" / "chave.txt").write_text("segredo")

    def fake_embed(host, model, texts):
        return [[t.lower().count("férias"), t.lower().count("reembolso"), 1.0] for t in texts]
    monkeypatch.setattr(knowledge, "embedding_model", lambda host: "nomic-embed-text")
    monkeypatch.setattr(knowledge, "embed", fake_embed)
    agent = {"id": "rh", "knowledge": [str(kb), str(home / ".ssh"), "/etc"]}
    hits = knowledge.search(agent, config.load(), "http://x", "quantos dias de férias?")
    assert hits[0][0].endswith("ferias.md")
    assert all(".ssh" not in h[0] and not h[0].startswith("/etc") for h in hits)
    # without an embedding model: keyword fallback
    monkeypatch.setattr(knowledge, "embedding_model", lambda host: None)
    hits = knowledge.search(agent, config.load(), "http://x", "reembolso despesas")
    assert hits[0][0].endswith("reembolso.txt")
