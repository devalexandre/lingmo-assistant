import json
import os
import sys
from pathlib import Path

import pytest

from lingmo_assistant import agenda

FAKE = r'''
import json, os, sys
req = json.loads(sys.stdin.readline())
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps(req) + "\n")
op = req.get("op")
if op == "range":
    data = [{"title": "Dentista", "start": "2026-10-08T09:00:00", "end": "2026-10-08T10:00:00", "allDay": False}]
elif op == "tasks":
    data = [{"title": "Pagar conta", "due": "2026-10-09", "done": False}]
elif op in ("save_event", "save_task"):
    data = {"calendarId": "pessoal", "file": "n.ics", "uid": "n"}
else:
    print(json.dumps({"ok": False, "error": "Operação desconhecida."}))
    sys.exit(1)
print(json.dumps({"ok": True, "data": data}))
'''


@pytest.fixture
def fake(tmp_path, monkeypatch):
    script = tmp_path / "calendar_backend.py"
    script.write_text(FAKE)
    log = tmp_path / "log.jsonl"
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("LINGMO_ASSISTANT_CALENDAR_BACKEND", str(script))
    return lambda: [json.loads(l) for l in log.read_text().splitlines()]


def test_read_ops(fake):
    import datetime as dt
    evs = agenda.events(dt.date(2026, 10, 7), 7)
    assert evs[0]["title"] == "Dentista"
    assert agenda.tasks()[0]["title"] == "Pagar conta"
    assert fake() == [{"op": "range", "start": "2026-10-07", "end": "2026-10-14"}, {"op": "tasks"}]


def test_create_only_never_sends_file(fake):
    ev = agenda.build_event("Dentista", "2026-10-08T09:00", reminder_minutes=15)
    ev["file"] = "existing.ics"          # even if something sneaks in
    ev["scope"] = "all"
    agenda.create_event(ev)
    task = agenda.build_task("Pagar", "2026-10-09", priority=1)
    task["file"] = "x.ics"
    agenda.create_task(task)
    sent = fake()
    assert sent[0] == {"op": "save_event", "event": {"title": "Dentista", "start": "2026-10-08T09:00",
                                                     "end": "2026-10-08T10:00", "allDay": False,
                                                     "location": "", "notes": "", "alarm": 15}}
    assert sent[1] == {"op": "save_task", "task": {"title": "Pagar", "due": "2026-10-09", "notes": "",
                                                   "priority": 1}}


def test_worker_error_is_relayed(fake, monkeypatch, tmp_path):
    with pytest.raises(agenda.CalendarError, match="Operação desconhecida"):
        agenda.call({"op": "delete_event"})


def test_validation():
    with pytest.raises(agenda.CalendarError):
        agenda.build_event("", "2026-10-08T09:00")
    with pytest.raises(agenda.CalendarError):
        agenda.build_event("x", "amanhã")
    with pytest.raises(agenda.CalendarError):
        agenda.build_event("x", "2026-10-08T09:00", "2026-10-08T08:00")
    with pytest.raises(agenda.CalendarError):
        agenda.build_task("x", priority=12)
    assert agenda.build_event("Férias", "2026-12-20", "2026-12-24", all_day=True)["end"] == "2026-12-24T00:00"


def test_missing_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("LINGMO_ASSISTANT_CALENDAR_BACKEND", str(tmp_path / "missing.py"))
    with pytest.raises(agenda.CalendarError, match="não está instalado"):
        agenda.tasks()


REAL = Path(os.environ.get("LINGMO_MAIL_BACKEND",
                           Path(__file__).resolve().parents[3] / "lingmo-mail" / "backend" / "calendar_backend.py"))


@pytest.mark.skipif(not REAL.is_file(), reason="lingmo-mail sources not available")
def test_real_worker_contract(tmp_path, monkeypatch):
    """Creates an event and a task with Lingmo Mail's real worker in a scratch data dir."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path))
    path = str(REAL)
    created = agenda.create_event(agenda.build_event("Dentista", "2026-10-08T09:00", "", False, "", "", 0), path)
    assert created.get("file", "").endswith(".ics")
    rem = agenda.build_event("Lembrete", "2026-10-08T07:00", "", False, "", "", 0)
    rem["end"] = rem["start"]
    agenda.create_event(rem, path)
    agenda.create_task(agenda.build_task("Pagar conta", "2026-10-09"), path)
    import datetime as dt
    titles = [e["title"] for e in agenda.events(dt.date(2026, 10, 8), 1, path)]
    assert sorted(titles) == ["Dentista", "Lembrete"]
    assert [t["title"] for t in agenda.tasks(path)] == ["Pagar conta"]
