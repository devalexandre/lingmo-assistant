"""Background trigger watchers used by the flows service.

Each watcher is polled by the service loop and returns the workflows to run
with their trigger data. They only look at what the enabled workflows need
(a service with only scheduled flows never polls mail, files or USB) and keep
their state in ~/.local/state/lingmo-assistant/triggers.json so mail that was
already there, or an event already announced, doesn't fire again after a
restart. The first look at a mailbox or folder only records a baseline.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

from .. import agenda, config, mail, paths, store
from . import actions, graph, schedule

log = logging.getLogger("lingmo_assistant.flows")

EMAIL_EVERY = 120
CALENDAR_EVERY = 60
FILE_EVERY = 10
USB_EVERY = 5
BATTERY_EVERY = 60


def state_path() -> Path:
    return config.state_dir() / "triggers.json"


class State:
    def __init__(self):
        self.data = store.read_json(state_path(), {}) or {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        try:
            store.write_json(state_path(), self.data)
        except OSError as exc:
            log.warning("trigger state not saved: %s", type(exc).__name__)


class Watchers:
    """Returns due (flow, trigger_data) pairs; `now` and polling are injectable for tests."""

    def __init__(self, clock: Callable[[], dt.datetime] = lambda: dt.datetime.now().astimezone()):
        self.clock = clock
        self.state = State()
        self.next_poll: dict[str, float] = {}
        self.next_fire: dict[str, dt.datetime] = {}
        self.file_seen: dict[str, dict[str, float]] = {}
        self.usb_seen: Optional[set[str]] = None
        self.login_done = False

    # ------------------------------------------------------------------ helpers

    def _due(self, key: str, every: float, now_mono: float) -> bool:
        if now_mono >= self.next_poll.get(key, 0):
            self.next_poll[key] = now_mono + every
            return True
        return False

    def next_wakeup(self, flows: list[dict], now_mono: float) -> float:
        """Seconds until something might be due (the loop sleeps this long)."""
        waits = [300.0]
        now = self.clock()
        for f in flows:
            t = graph.trigger(f)
            if t is None:
                continue
            if t["type"] == "trigger.schedule":
                when = self.next_fire.get(f["id"])
                if when:
                    waits.append(max(1.0, (when - now).total_seconds()))
            elif t["type"] in ("trigger.email", "trigger.calendar", "trigger.file", "trigger.system"):
                for key, nxt in self.next_poll.items():
                    waits.append(max(1.0, nxt - now_mono))
                waits.append(FILE_EVERY)
        return min(waits)

    # ------------------------------------------------------------------ poll

    def poll(self, flows: list[dict], now_mono: Optional[float] = None) -> list[tuple[dict, dict]]:
        now_mono = time.monotonic() if now_mono is None else now_mono
        due: list[tuple[dict, dict]] = []
        by_kind: dict[str, list[dict]] = {}
        for f in flows:
            t = graph.trigger(f)
            if f.get("enabled", True) and t is not None:
                by_kind.setdefault(t["type"], []).append(f)
        due += self.poll_schedule(by_kind.get("trigger.schedule", []))
        if by_kind.get("trigger.email") and self._due("email", EMAIL_EVERY, now_mono):
            due += self.poll_email(by_kind["trigger.email"])
        if by_kind.get("trigger.calendar") and self._due("calendar", CALENDAR_EVERY, now_mono):
            due += self.poll_calendar(by_kind["trigger.calendar"])
        if by_kind.get("trigger.file") and self._due("file", FILE_EVERY, now_mono):
            due += self.poll_files(by_kind["trigger.file"])
        if by_kind.get("trigger.system"):
            due += self.poll_system(by_kind["trigger.system"], now_mono)
        if due:
            self.state.save()
        return due

    def poll_schedule(self, flows: list[dict]) -> list[tuple[dict, dict]]:
        now = self.clock()
        due = []
        alive = set()
        for f in flows:
            alive.add(f["id"])
            spec = graph.params_of(graph.trigger(f)).get("schedule")
            key = f["id"] + ":" + json.dumps(spec, sort_keys=True)
            try:
                if key not in self.next_fire:
                    self.next_fire[key] = schedule.next_after(spec, now)
                when = self.next_fire[key]
            except schedule.ScheduleError:
                continue
            self.next_fire[f["id"]] = when
            if when is not None and now >= when:
                due.append((f, actions.schedule_outputs(when)))
                self.next_fire[key] = schedule.next_after(spec, now)
                self.next_fire[f["id"]] = self.next_fire[key]
        for k in list(self.next_fire):
            if k.split(":", 1)[0] not in alive:
                del self.next_fire[k]
        return due

    def poll_email(self, flows: list[dict]) -> list[tuple[dict, dict]]:
        due = []
        try:
            accounts = mail.accounts()
        except mail.MailError as exc:
            log.info("mail unavailable: %s", type(exc).__name__)
            return due
        cfg = config.load()
        if not cfg.tool_enabled("mail_read"):
            return due
        wanted_accounts = set()
        for f in flows:
            ref = str(graph.params_of(graph.trigger(f)).get("account") or "")
            for a in accounts:
                if not ref or ref in (a["id"], a["email"]):
                    wanted_accounts.add(a["id"])
        for acc in accounts:
            if acc["id"] not in wanted_accounts:
                continue
            key = "mail:" + acc["id"]
            try:
                msgs = mail.list_messages(acc["id"], "INBOX", unread_only=False, limit=25)
            except mail.MailError as exc:
                log.info("mail poll failed: %s", type(exc).__name__)
                continue
            seen = self.state.get(key)
            ids = [str(m.get("id")) for m in msgs]
            if seen is None:                 # first look: baseline only
                self.state.set(key, ids[:200])
                continue
            seen_set = set(seen)
            new = [m for m in msgs if str(m.get("id")) not in seen_set and m.get("unread", True)]
            self.state.set(key, (ids + [s for s in seen if s not in ids])[:500])
            for m in reversed(new):
                for f in flows:
                    p = graph.params_of(graph.trigger(f))
                    ref = str(p.get("account") or "")
                    if ref and ref not in (acc["id"], acc["email"]):
                        continue
                    if not actions.email_matches(p, m):
                        continue
                    try:
                        full = mail.read_message(acc["id"], m.get("id"), "INBOX")
                    except mail.MailError:
                        full = None
                    due.append((f, actions.email_outputs(acc, m, full)))
        return due

    def poll_calendar(self, flows: list[dict]) -> list[tuple[dict, dict]]:
        due = []
        cfg = config.load()
        if not cfg.tool_enabled("calendar_read"):
            return due
        now = self.clock()
        try:
            evs = agenda.events(now.date(), 2)
        except agenda.CalendarError as exc:
            log.info("calendar unavailable: %s", type(exc).__name__)
            return due
        fired = set(self.state.get("calendar_fired", []))
        for f in flows:
            p = graph.params_of(graph.trigger(f))
            minutes = actions._num(p.get("minutes_before"), 10)
            title_has = str(p.get("title_contains") or "").strip().lower()
            for e in evs:
                if e.get("allDay"):
                    continue
                try:
                    start = agenda.parse_local(str(e.get("start", ""))).replace(tzinfo=now.tzinfo)
                except agenda.CalendarError:
                    continue
                if title_has and title_has not in str(e.get("title", "")).lower():
                    continue
                left = (start - now).total_seconds() / 60
                key = "%s|%s|%s" % (f["id"], e.get("uid") or e.get("title"), e.get("start"))
                if 0 <= left <= minutes and key not in fired:
                    fired.add(key)
                    due.append((f, {"title": e.get("title", ""), "start": start.strftime("%H:%M"),
                                    "location": e.get("location", ""), "minutes": round(left),
                                    "output": "%s às %s" % (e.get("title", ""), start.strftime("%H:%M"))}))
        self.state.set("calendar_fired", sorted(fired)[-500:])
        return due

    def poll_files(self, flows: list[dict]) -> list[tuple[dict, dict]]:
        due = []
        cfg = config.load()
        policy = paths.PathPolicy(cfg.folders)
        for f in flows:
            p = graph.params_of(graph.trigger(f))
            try:
                folder = policy.check_read(str(p.get("folder") or ""))
            except paths.PolicyError:
                continue
            if not folder.is_dir():
                continue
            snapshot: dict[str, float] = {}
            try:
                with os.scandir(folder) as it:
                    for i, entry in enumerate(it):
                        if i > 2000:
                            break
                        if entry.name.startswith(".") or not entry.is_file(follow_symlinks=False):
                            continue
                        if entry.name.endswith((".part", ".crdownload", ".tmp")):
                            continue
                        if actions.file_matches(p.get("pattern"), entry.name):
                            snapshot[entry.name] = entry.stat().st_mtime
            except OSError:
                continue
            key = f["id"]
            before = self.file_seen.get(key)
            self.file_seen[key] = snapshot
            if before is None:
                continue
            for name, mtime in sorted(snapshot.items()):
                if name not in before or before[name] != mtime:
                    event = "created" if name not in before else "modified"
                    full = folder / name
                    due.append((f, {"path": str(full), "name": name, "event": event,
                                    "output": "%s: %s" % ("Novo arquivo" if event == "created" else "Arquivo alterado",
                                                          name)}))
        return due

    def poll_system(self, flows: list[dict], now_mono: float) -> list[tuple[dict, dict]]:
        due = []
        events = {graph.params_of(graph.trigger(f)).get("event"): True for f in flows}
        if "login" in events and not self.login_done:
            self.login_done = True
            session = os.environ.get("XDG_SESSION_ID", "") + ":" + _boot_id()
            if self.state.get("login_session") != session:
                self.state.set("login_session", session)
                for f in flows:
                    if graph.params_of(graph.trigger(f)).get("event") == "login":
                        due.append((f, {"event": "login", "detail": "", "output": "Sessão iniciada"}))
        if "usb" in events and self._due("usb", USB_EVERY, now_mono):
            current = usb_devices()
            if self.usb_seen is not None:
                for dev in sorted(set(current) - self.usb_seen):
                    for f in flows:
                        if graph.params_of(graph.trigger(f)).get("event") == "usb":
                            due.append((f, {"event": "usb", "detail": current[dev],
                                            "output": "USB conectado: %s" % current[dev]}))
            self.usb_seen = set(current)
        if "battery_low" in events and self._due("battery", BATTERY_EVERY, now_mono):
            level, discharging = battery()
            if level is not None:
                for f in flows:
                    p = graph.params_of(graph.trigger(f))
                    if p.get("event") != "battery_low":
                        continue
                    threshold = actions._num(p.get("threshold"), 15)
                    key = "battery:" + f["id"]
                    armed = self.state.get(key, True)
                    if discharging and level <= threshold and armed:
                        self.state.set(key, False)
                        due.append((f, {"event": "battery_low", "detail": "%d%%" % level,
                                        "output": "Bateria em %d%%" % level}))
                    elif level > threshold + 5 or not discharging:
                        self.state.set(key, True)
        return due


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def usb_devices() -> dict[str, str]:
    out = {}
    for d in glob.glob("/sys/bus/usb/devices/*"):
        name = os.path.basename(d)
        if ":" in name or name.startswith("usb"):
            continue
        try:
            product = Path(d, "product").read_text().strip()
        except OSError:
            product = name
        out[name + ":" + product] = product
    return out


def battery() -> tuple[Optional[int], bool]:
    for d in glob.glob("/sys/class/power_supply/BAT*"):
        try:
            level = int(Path(d, "capacity").read_text().strip())
            status = Path(d, "status").read_text().strip()
        except (OSError, ValueError):
            continue
        return level, status == "Discharging"
    return None, False
