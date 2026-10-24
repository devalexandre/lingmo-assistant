"""Schedules for the "Agendamento" trigger: the friendly forms the editor's
picker writes, plus classic 5-field cron for advanced users.

    {"kind": "daily",    "time": "09:00"}
    {"kind": "weekdays", "time": "09:00", "days": [0, 1, 2, 3, 4]}   # 0 = Monday
    {"kind": "interval", "minutes": 30}
    {"kind": "monthly",  "day": 1, "time": "09:00"}
    {"kind": "once",     "datetime": "2026-10-25T09:00"}
    {"kind": "cron",     "cron": "0 9 * * 1-5"}                      # 0/7 = Sunday

Times are local wall-clock times.
"""
from __future__ import annotations

import datetime as dt
import re

KINDS = ("daily", "weekdays", "interval", "monthly", "once", "cron")
DAY_NAMES = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


class ScheduleError(ValueError):
    pass


def _time(value) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value or ""))
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        raise ScheduleError("Hora inválida no agendamento (use HH:MM).")
    return int(m[1]), int(m[2])


def _field(text: str, lo: int, hi: int, name: str) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        m = re.fullmatch(r"(\*|\d+(?:-\d+)?)(?:/(\d+))?", part.strip())
        if not m:
            raise ScheduleError("Cron inválido no campo %s." % name)
        base, step = m[1], int(m[2] or 1)
        if step < 1:
            raise ScheduleError("Cron inválido no campo %s." % name)
        if base == "*":
            a, b = lo, hi
        elif "-" in base:
            a, b = (int(x) for x in base.split("-"))
        else:
            a = b = int(base)
            if m[2]:
                b = hi
        if a < lo or b > hi or a > b:
            raise ScheduleError("Cron fora do intervalo no campo %s." % name)
        values.update(range(a, b + 1, step))
    return values


class Cron:
    def __init__(self, expr: str):
        parts = str(expr or "").split()
        if len(parts) != 5:
            raise ScheduleError("Cron precisa de 5 campos: minuto hora dia mês dia-da-semana.")
        self.minutes = _field(parts[0], 0, 59, "minuto")
        self.hours = _field(parts[1], 0, 23, "hora")
        self.dom = _field(parts[2], 1, 31, "dia")
        self.months = _field(parts[3], 1, 12, "mês")
        dow = _field(parts[4], 0, 7, "dia da semana")
        self.dow = {(d % 7) for d in dow}          # cron: 0 = Sunday
        self.dom_any = parts[2] == "*"
        self.dow_any = parts[4] == "*"

    def day_matches(self, d: dt.date) -> bool:
        if d.month not in self.months:
            return False
        cron_dow = (d.weekday() + 1) % 7
        dom_ok, dow_ok = d.day in self.dom, cron_dow in self.dow
        if self.dom_any and self.dow_any:
            return True
        if self.dom_any:
            return dow_ok
        if self.dow_any:
            return dom_ok
        return dom_ok or dow_ok

    def next_after(self, after: dt.datetime) -> dt.datetime | None:
        start = after.replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        day = start.date()
        for _ in range(366 * 5):
            if self.day_matches(day):
                for h in sorted(self.hours):
                    for mi in sorted(self.minutes):
                        cand = dt.datetime.combine(day, dt.time(h, mi), tzinfo=after.tzinfo)
                        if cand >= start:
                            return cand
            day += dt.timedelta(days=1)
        return None


def check(spec) -> dict:
    """Validates a schedule; returns it normalised."""
    if not isinstance(spec, dict):
        raise ScheduleError("Agendamento inválido.")
    kind = spec.get("kind")
    if kind not in KINDS:
        raise ScheduleError("Tipo de agendamento desconhecido.")
    out = {"kind": kind}
    if kind in ("daily", "weekdays", "monthly"):
        _time(spec.get("time"))
        out["time"] = str(spec["time"]).strip()
    if kind == "weekdays":
        days = spec.get("days")
        if not isinstance(days, list) or not days or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
            raise ScheduleError("Escolha ao menos um dia da semana.")
        out["days"] = sorted(set(days))
    if kind == "interval":
        try:
            minutes = int(spec.get("minutes"))
        except (TypeError, ValueError):
            raise ScheduleError("Intervalo inválido.") from None
        if not 1 <= minutes <= 7 * 24 * 60:
            raise ScheduleError("O intervalo vai de 1 minuto a 7 dias.")
        out["minutes"] = minutes
    if kind == "monthly":
        try:
            day = int(spec.get("day"))
        except (TypeError, ValueError):
            raise ScheduleError("Dia do mês inválido.") from None
        if not 1 <= day <= 31:
            raise ScheduleError("Dia do mês inválido.")
        out["day"] = day
    if kind == "once":
        try:
            dt.datetime.fromisoformat(str(spec.get("datetime")))
        except ValueError:
            raise ScheduleError("Data e hora inválidas (use AAAA-MM-DDTHH:MM).") from None
        out["datetime"] = str(spec["datetime"])
    if kind == "cron":
        Cron(spec.get("cron"))
        out["cron"] = " ".join(str(spec["cron"]).split())
    return out


def next_after(spec, after: dt.datetime) -> dt.datetime | None:
    """The first fire time strictly after `after` (minute precision)."""
    s = check(spec)
    kind = s["kind"]
    base = after.replace(second=0, microsecond=0)
    if kind == "cron":
        return Cron(s["cron"]).next_after(after)
    if kind == "interval":
        midnight = base.replace(hour=0, minute=0)
        elapsed = int((base - midnight).total_seconds() // 60)
        step = s["minutes"]
        nxt = midnight + dt.timedelta(minutes=(elapsed // step + 1) * step)
        return nxt
    if kind == "once":
        when = dt.datetime.fromisoformat(s["datetime"])
        if when.tzinfo is None and after.tzinfo is not None:
            when = when.replace(tzinfo=after.tzinfo)
        return when if when > after else None
    h, m = _time(s["time"])
    day = base.date()
    for i in range(0, 400):
        d = day + dt.timedelta(days=i)
        if kind == "weekdays" and d.weekday() not in s["days"]:
            continue
        if kind == "monthly" and d.day != s["day"]:
            continue
        cand = dt.datetime.combine(d, dt.time(h, m), tzinfo=after.tzinfo)
        if cand > after:
            return cand
    return None


def describe(spec) -> str:
    """Plain pt-BR text for the node card ("Seg a sex às 09:00")."""
    try:
        s = check(spec)
    except ScheduleError:
        return "Agendamento inválido"
    kind = s["kind"]
    if kind == "daily":
        return "Todo dia às %s" % s["time"]
    if kind == "weekdays":
        days = s["days"]
        if days == [0, 1, 2, 3, 4]:
            label = "Seg a sex"
        elif days == [5, 6]:
            label = "Fins de semana"
        elif len(days) == 7:
            label = "Todo dia"
        else:
            label = ", ".join(DAY_NAMES[d] for d in days).capitalize()
        return "%s às %s" % (label, s["time"])
    if kind == "interval":
        mins = s["minutes"]
        return "A cada %d min" % mins if mins < 60 or mins % 60 else "A cada %d h" % (mins // 60)
    if kind == "monthly":
        return "Dia %d de cada mês às %s" % (s["day"], s["time"])
    if kind == "once":
        return "Uma vez em %s" % s["datetime"].replace("T", " ")
    return "Cron: %s" % s["cron"]
