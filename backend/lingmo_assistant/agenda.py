"""Lingmo Mail calendar through its own worker (calendar_backend.py).

The worker takes one JSON request on stdin and answers one JSON line
({"ok": true, "data": ...} or {"ok": false, "error": "<pt-BR>"}). Only the
read operations (range, tasks) and the *create* forms of save_event/save_task
are used: requests are built here field by field and never carry a "file",
so an existing event or task can't be edited, and delete ops are never sent.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys

CANDIDATES = [
    "/usr/libexec/lingmo-mail/calendar_backend.py",
    "/usr/lib/lingmo-mail/calendar_backend.py",
]
TIMEOUT = 30
REPLY_LIMIT = 8 * 1024 * 1024


class CalendarError(Exception):
    pass


def backend_path() -> str | None:
    override = os.environ.get("LINGMO_ASSISTANT_CALENDAR_BACKEND")
    if override:
        return override if os.path.isfile(override) else None
    for c in CANDIDATES:
        if os.path.isfile(c):
            return c
    return None


def call(request: dict, path: str | None = None, python: str | None = None) -> object:
    path = path or backend_path()
    if not path:
        raise CalendarError("O calendário do Lingmo Mail não está instalado.")
    argv = [python or sys.executable or "/usr/bin/python3", "-I", path]
    try:
        proc = subprocess.run(argv, input=(json.dumps(request, ensure_ascii=False) + "\n").encode(),
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=TIMEOUT, close_fds=True)
    except subprocess.TimeoutExpired as exc:
        raise CalendarError("O calendário demorou demais para responder.") from exc
    except OSError as exc:
        raise CalendarError("Não foi possível abrir o calendário.") from exc
    line = proc.stdout[:REPLY_LIMIT].split(b"\n", 1)[0]
    try:
        reply = json.loads(line)
    except ValueError as exc:
        raise CalendarError("Resposta inválida do calendário.") from exc
    if not isinstance(reply, dict):
        raise CalendarError("Resposta inválida do calendário.")
    if not reply.get("ok"):
        raise CalendarError(str(reply.get("error") or "O calendário recusou a operação."))
    return reply.get("data")


# ------------------------------------------------------------------ validation

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOCAL = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$")


def parse_day(value: str) -> dt.date:
    if not isinstance(value, str) or not DAY.match(value.strip()):
        raise CalendarError("Data inválida (use AAAA-MM-DD): %s" % value)
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise CalendarError("Data inválida: %s" % value) from exc


def parse_local(value: str) -> dt.datetime:
    if not isinstance(value, str) or not LOCAL.match(value.strip()):
        raise CalendarError("Data e hora inválidas (use AAAA-MM-DDTHH:MM): %s" % value)
    try:
        return dt.datetime.fromisoformat(value.strip().replace(" ", "T"))
    except ValueError as exc:
        raise CalendarError("Data e hora inválidas: %s" % value) from exc


def _line(value, limit, what):
    text = (value or "")
    if not isinstance(text, str):
        raise CalendarError("%s inválido." % what)
    text = text.replace("\r", " ").replace("\n", " ").strip()
    if len(text) > limit:
        raise CalendarError("%s longo demais." % what)
    return text


def _text(value, limit, what):
    text = value or ""
    if not isinstance(text, str):
        raise CalendarError("%s inválido." % what)
    if len(text) > limit:
        raise CalendarError("%s longo demais." % what)
    return text


def build_event(title: str, start: str, end: str = "", all_day: bool = False, location: str = "",
                notes: str = "", reminder_minutes: int | None = None) -> dict:
    """The exact `event` object sent with save_event (a new event: no file)."""
    title = _line(title, 500, "Título")
    if not title:
        raise CalendarError("Dê um título ao evento.")
    if all_day:
        first = parse_day((start or "")[:10])
        last = parse_day((end or start or "")[:10])
        if last < first:
            raise CalendarError("O fim precisa ser depois do início.")
        start_s, end_s = first.isoformat() + "T00:00", last.isoformat() + "T00:00"
    else:
        s = parse_local(start)
        e = parse_local(end) if end else s + dt.timedelta(hours=1)
        if e < s:
            raise CalendarError("O fim precisa ser depois do início.")
        start_s, end_s = s.strftime("%Y-%m-%dT%H:%M"), e.strftime("%Y-%m-%dT%H:%M")
    event = {
        "title": title,
        "start": start_s,
        "end": end_s,
        "allDay": bool(all_day),
        "location": _line(location, 500, "Local"),
        "notes": _text(notes, 20000, "Notas"),
    }
    if reminder_minutes is not None:
        try:
            minutes = int(reminder_minutes)
        except (TypeError, ValueError) as exc:
            raise CalendarError("Lembrete inválido.") from exc
        if not 0 <= minutes <= 60 * 24 * 28:
            raise CalendarError("Lembrete inválido.")
        event["alarm"] = minutes
    return event


def build_task(title: str, due: str = "", notes: str = "", priority: int = 0) -> dict:
    title = _line(title, 500, "Título")
    if not title:
        raise CalendarError("Dê um título à tarefa.")
    due = (due or "").strip()
    if due:
        if DAY.match(due):
            due = parse_day(due).isoformat()
        else:
            due = parse_local(due).strftime("%Y-%m-%dT%H:%M")
    try:
        priority = int(priority or 0)
    except (TypeError, ValueError) as exc:
        raise CalendarError("Prioridade inválida.") from exc
    if not 0 <= priority <= 9:
        raise CalendarError("Prioridade inválida (0 a 9).")
    return {"title": title, "due": due, "notes": _text(notes, 20000, "Notas"), "priority": priority}


# ------------------------------------------------------------------ operations

def events(start: dt.date, days: int, path: str | None = None) -> list[dict]:
    days = max(1, min(int(days), 366))
    end = start + dt.timedelta(days=days)
    data = call({"op": "range", "start": start.isoformat(), "end": end.isoformat()}, path)
    return data if isinstance(data, list) else []


def tasks(path: str | None = None) -> list[dict]:
    data = call({"op": "tasks"}, path)
    return data if isinstance(data, list) else []


def create_event(event: dict, path: str | None = None) -> dict:
    clean = {k: event[k] for k in ("title", "start", "end", "allDay", "location", "notes", "alarm") if k in event}
    data = call({"op": "save_event", "event": clean}, path)
    return data if isinstance(data, dict) else {}


def create_task(task: dict, path: str | None = None) -> dict:
    clean = {k: task[k] for k in ("title", "due", "notes", "priority") if k in task}
    data = call({"op": "save_task", "task": clean}, path)
    return data if isinstance(data, dict) else {}


def describe_event(e: dict) -> str:
    when = e.get("start", "")
    if e.get("allDay"):
        when = when[:10] + " (dia inteiro)"
    else:
        when = when.replace("T", " ")[:16] + " – " + e.get("end", "").replace("T", " ")[11:16]
    parts = ["%s · %s" % (when, e.get("title", ""))]
    if e.get("location"):
        parts.append("local: " + e["location"])
    if e.get("rrule"):
        parts.append("repete: " + e["rrule"])
    return " · ".join(parts)


def describe_task(t: dict) -> str:
    status = "[x]" if t.get("done") else "[ ]"
    due = (" · prazo " + t["due"].replace("T", " ")[:16]) if t.get("due") else ""
    return "%s %s%s" % (status, t.get("title", ""), due)

