"""lingmo-assistant-flows: runs scheduled and event-triggered workflows in the
background, without the Assistente window. Started at login by
/etc/xdg/autostart/lingmo-assistant-flows.desktop (lingmo-session runs XDG
autostart entries); one instance per user (lock file + D-Bus name).

Light when idle: it sleeps until the next scheduled time or the next poll the
enabled workflows need (nothing is polled when no workflow needs it) and
reloads the workflows when their folder changes.

D-Bus: com.lingmo.AssistantFlows /AssistantFlows
  Run(s flow_id) -> s run_id       start a workflow now (global shortcuts use this)
  Running() -> s                   JSON [{run_id, flow_id, flow_name, status}]
  Reload()                         re-read the workflows
  Stop(s run_id)

A running workflow that takes more than a few seconds shows a notification
("Executando «…»"), replaced by the result; questions and per-run
confirmations are notifications with Permitir/Recusar buttons (and a reply
field for text questions). Unanswered questions expire after 30 minutes and the
run stops without doing anything.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import sys
import threading
import time
from typing import Optional

from .. import config, desktop, store, voice
from . import graph, runner, service, triggers

log = logging.getLogger("lingmo_assistant.flows")

BUS_NAME = "com.lingmo.AssistantFlows"
OBJECT_PATH = "/AssistantFlows"
ASK_TIMEOUT = 30 * 60
SHOW_RUNNING_AFTER = 3.0


class Questions:
    """Notification questions waiting for ActionInvoked / NotificationReplied."""

    def __init__(self):
        self.lock = threading.Lock()
        self.waiting: dict[int, dict] = {}

    def ask(self, kind: str, title: str, details: str, external: bool) -> Optional[dict]:
        actions = ["allow", "Permitir", "deny", "Recusar"]
        if external:
            actions[2:2] = ["always", "Permitir sempre"]
        if kind == "input":
            actions = ["deny", "Cancelar"]
        try:
            nid = desktop.notify("Assistente: " + title, details[:900], "dialog-question", actions=actions,
                                 timeout_ms=0)
        except desktop.DesktopError:
            return None
        entry = {"event": threading.Event(), "answer": None, "kind": kind}
        with self.lock:
            self.waiting[nid] = entry
        entry["event"].wait(ASK_TIMEOUT)
        with self.lock:
            self.waiting.pop(nid, None)
        return entry["answer"]

    def action(self, nid: int, key: str) -> None:
        with self.lock:
            entry = self.waiting.get(int(nid))
        if entry is None:
            return
        if entry["kind"] == "input":
            entry["answer"] = None
        else:
            entry["answer"] = {"allow": key in ("allow", "always"), "dont_ask": key == "always"}
        entry["event"].set()

    def replied(self, nid: int, text: str) -> None:
        with self.lock:
            entry = self.waiting.get(int(nid))
        if entry is None:
            return
        entry["answer"] = {"text": str(text)}
        entry["event"].set()

    def closed(self, nid: int) -> None:
        with self.lock:
            entry = self.waiting.get(int(nid))
        if entry is not None and entry["answer"] is None:
            entry["event"].set()


class FlowsService:
    def __init__(self, load_config=config.load, ai=None):
        from ..flows.ai import AI
        from .. import agent as agent_mod
        self.load_config = load_config
        db = None
        try:
            db = agent_mod.database()
        except Exception as exc:
            log.warning("no agent database: %s", type(exc).__name__)
        self.ai = ai or AI(load_config, db=db)
        self.watchers = triggers.Watchers()
        self.questions = Questions()
        self.speaker = voice.Speaker()
        self.wake = threading.Event()
        self.quit = threading.Event()
        self.flows: list[dict] = []
        self.mtime = -1.0
        self.lock = threading.Lock()
        self.runs: dict[str, runner.FlowRunner] = {}

    # ------------------------------------------------------------------ flows

    def reload(self, force: bool = False) -> None:
        try:
            m = service.FLOWS.mtime()
        except OSError:
            return
        if force or m != self.mtime:
            self.mtime = m
            self.flows = [f for f in service.FLOWS.list() if f.get("enabled", True)]

    def running(self) -> list[dict]:
        with self.lock:
            return [{"run_id": r.id, "flow_id": r.flow["id"], "flow_name": r.flow["name"],
                     "status": r.record["status"]} for r in self.runs.values()]

    def start(self, flow: dict, trigger_data: dict, source: str) -> str:
        with self.lock:
            if any(r.flow["id"] == flow["id"] for r in self.runs.values()):
                return ""
        def ask(kind, title, details, external, **_):
            return self.questions.ask(kind, title, details, external)

        def speak(text):
            self.speaker.speak(text, self.load_config(), config.state_dir() / "tmp")

        r = runner.FlowRunner(flow, emit=lambda *a, **k: None, ask=ask, load_config=self.load_config, ai=self.ai,
                              speak=speak, mode="run", source=source, trigger_data=trigger_data,
                              tool_ctx=self.ai.tool_ctx)
        with self.lock:
            self.runs[r.id] = r
        threading.Thread(target=self._run, args=(r,), daemon=True).start()
        return r.id

    def _run(self, r: runner.FlowRunner) -> None:
        shown = {"id": 0}

        def show_running():
            if r.record["status"] in ("running", "waiting") and r.record["ended"] is None:
                try:
                    shown["id"] = desktop.notify("Executando «%s»" % r.flow["name"], "Fluxo do Assistente em "
                                                 "andamento.", "lingmo-assistant", timeout_ms=0)
                except desktop.DesktopError:
                    pass
        timer = threading.Timer(SHOW_RUNNING_AFTER, show_running)
        timer.daemon = True
        timer.start()
        try:
            record = r.run()
        finally:
            timer.cancel()
            with self.lock:
                self.runs.pop(r.id, None)
        status = record["status"]
        try:
            if status in ("failed", "refused"):
                desktop.notify("«%s» não terminou" % r.flow["name"], record.get("error") or "", "dialog-warning",
                               replaces=shown["id"])
            elif shown["id"]:
                desktop.notify("«%s» concluído" % r.flow["name"], "", "lingmo-assistant", replaces=shown["id"],
                               timeout_ms=4000)
        except desktop.DesktopError:
            pass

    def run_now(self, flow_id: str, source: str = "shortcut") -> str:
        flow = service.FLOWS.get(flow_id)
        if flow is None or not flow.get("enabled", True):
            return ""
        return self.start(flow, runner.now_outputs(), source)

    # ------------------------------------------------------------------ loop

    def loop(self) -> None:
        self.reload(force=True)
        while not self.quit.is_set():
            self.reload()
            background = [f for f in self.flows
                          if (graph.trigger(f) or {}).get("type") in service.BACKGROUND_TRIGGERS]
            try:
                for flow, data in self.watchers.poll(background):
                    self.start(flow, data, "background")
            except Exception as exc:     # a broken watcher must not kill the service
                log.warning("trigger poll failed: %s", type(exc).__name__)
            wait = self.watchers.next_wakeup(background, time.monotonic())
            # never sleep through a folder change for long
            self.wake.wait(min(wait, 30.0))
            self.wake.clear()


# ====================================================================== D-Bus

def serve_dbus(svc: FlowsService) -> bool:
    try:
        import dbus
        import dbus.mainloop.glib
        import dbus.service
        from gi.repository import GLib
    except ImportError:
        log.warning("dbus-python/GLib not available: no D-Bus service")
        return False
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    try:
        bus = dbus.SessionBus()
        name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)
    except dbus.exceptions.DBusException:
        log.warning("D-Bus name taken or no session bus")
        return False

    class Obj(dbus.service.Object):
        @dbus.service.method(BUS_NAME, in_signature="s", out_signature="s")
        def Run(self, flow_id):
            return svc.run_now(str(flow_id))

        @dbus.service.method(BUS_NAME, in_signature="", out_signature="s")
        def Running(self):
            return json.dumps(svc.running(), ensure_ascii=False)

        @dbus.service.method(BUS_NAME, in_signature="", out_signature="")
        def Reload(self):
            svc.reload(force=True)
            svc.wake.set()

        @dbus.service.method(BUS_NAME, in_signature="s", out_signature="")
        def Stop(self, run_id):
            r = svc.runs.get(str(run_id))
            if r:
                r.stop()

    obj = Obj(bus, OBJECT_PATH)
    iface = "org.freedesktop.Notifications"
    bus.add_signal_receiver(lambda nid, key: svc.questions.action(int(nid), str(key)),
                            signal_name="ActionInvoked", dbus_interface=iface)
    bus.add_signal_receiver(lambda nid, text: svc.questions.replied(int(nid), str(text)),
                            signal_name="NotificationReplied", dbus_interface=iface)
    bus.add_signal_receiver(lambda nid, reason: svc.questions.closed(int(nid)),
                            signal_name="NotificationClosed", dbus_interface=iface)
    loop = GLib.MainLoop()
    t = threading.Thread(target=loop.run, daemon=True)
    t.start()
    svc._dbus_keep = (bus, name, obj, loop)
    return True


def call_running_service(method: str, *args: str) -> Optional[str]:
    try:
        return desktop.gdbus_call(BUS_NAME, OBJECT_PATH, BUS_NAME + "." + method,
                                  *[desktop._gvariant_str(a) for a in args])
    except desktop.DesktopError:
        return None


def lock_instance():
    d = config.state_dir()
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    fh = open(d / "flows.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def main(argv: Optional[list[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    from ..engine import setup_logging
    os.environ["AGNO_TELEMETRY"] = "false"
    os.environ.pop("OLLAMA_API_KEY", None)
    setup_logging()
    if "--run" in argv:
        idx = argv.index("--run")
        flow_id = argv[idx + 1] if idx + 1 < len(argv) else ""
        if not store.ID_RE.match(flow_id):
            print("lingmo-assistant-flows: invalid workflow id", file=sys.stderr)
            return 2
        if call_running_service("Run", flow_id) is not None:
            return 0
        # No service running: run it here, in the foreground
        svc = FlowsService()
        serve_dbus(svc)
        rid = svc.run_now(flow_id, "shortcut")
        while rid and svc.runs:
            time.sleep(0.5)
        return 0 if rid else 1
    if "--status" in argv:
        out = call_running_service("Running")
        print(out or "[]")
        return 0
    lock = lock_instance()
    if lock is None:
        return 0              # already running for this user
    svc = FlowsService()
    serve_dbus(svc)
    setup_logging()
    try:
        svc.loop()
    except KeyboardInterrupt:
        pass
    return 0
