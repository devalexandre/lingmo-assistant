"""Lingmo Intents in the Assistant.

Every action an installed app declares (/usr/share/lingmo/intents/<app>.json)
becomes, automatically:

* an agno tool for the chat (``intent_<id>``, e.g. ``intent_clock_alarm_create``),
  with the parameters of the manifest's schema; read-only intents run at once,
  every other one pauses for the confirmation card;
* a block of the visual Flows ("intent.<id>"), see flows/nodes.py.

Both are filtered by the same gate the apps apply (lingmo_intents.Gate:
assistant_read / assistant_write, the tool checkboxes, Settings › IA › "Ações
dos apps", protected paths) and run through D-Bus with the caller identity
("assistant" or "flows"); the app checks everything again.

When an intent covers a hand-written tool (create_alarm → clock.alarm.create…),
the hand-written one is left out so the model sees each action once.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
from typing import Any

log = logging.getLogger("lingmo_assistant.intents")

try:
    import lingmo_intents as li
except ImportError:  # development tree: ../lingmo-intents/python
    _dev = os.path.join(os.path.dirname(__file__), "..", "..", "..", "lingmo-intents", "python")
    if os.path.isdir(_dev):
        sys.path.append(os.path.abspath(_dev))
    try:
        import lingmo_intents as li
    except ImportError:
        li = None

PREFIX = "intent_"
TOOL_FALLBACK = "intents"        # contract id reported for intents without an assistantTool

# Hand-written chat tools that an installed intent replaces
REPLACES = {
    "create_alarm": "clock.alarm.create", "start_timer": "clock.timer.start",
    "send_email": "mail.send", "reply_email": "mail.reply",
    "list_emails": "mail.search", "read_email": "mail.read",
    "create_note": "notes.create", "append_to_note": "notes.append",
    "create_event": "calendar.event.create", "create_task": "tasks.create",
}

_lock = threading.Lock()
_registry = None


def available() -> bool:
    return li is not None


def registry():
    global _registry
    with _lock:
        if _registry is None and li is not None:
            _registry = li.Registry()
        return _registry


def reset() -> None:
    """Forget the registry (tests change LINGMO_INTENTS_DIRS)."""
    global _registry
    with _lock:
        _registry = None


def all_intents() -> list:
    reg = registry()
    return reg.intents() if reg else []


def get(intent_id: str):
    reg = registry()
    return reg.intent(intent_id) if reg else None


def gate():
    return li.Gate.load() if li else None


def function_name(intent_id: str) -> str:
    return PREFIX + intent_id.replace(".", "_")


def intent_for_function(function: str):
    if not function.startswith(PREFIX):
        return None
    for i in all_intents():
        if function_name(i.id) == function:
            return i
    return None


def is_intent_function(function: str) -> bool:
    return function.startswith(PREFIX) and intent_for_function(function) is not None


def tool_id(intent) -> str:
    return intent.assistant_tool or TOOL_FALLBACK


def usable(intent, caller: str = "assistant") -> bool:
    g = gate()
    return bool(g) and g.allows_caller(intent, caller)


def replaced_functions() -> set[str]:
    """Hand-written functions whose intent is installed and allowed."""
    out = set()
    for fn, iid in REPLACES.items():
        intent = get(iid)
        if intent is not None and usable(intent):
            out.add(fn)
    return out


# ------------------------------------------------------------------ schema → model

def model_schema(intent) -> dict:
    """The parameter schema as the model sees it (JSON Schema, English)."""
    props = {}
    for name, prop in intent.properties.items():
        p: dict[str, Any] = {"type": prop.get("type", "string")}
        desc = [li.localized(prop.get("title"), "en"), li.localized(prop.get("description"), "en")]
        fmt = prop.get("format")
        hints = {"time": "24-hour time HH:MM", "date": "date YYYY-MM-DD", "date-time": "YYYY-MM-DDTHH:MM",
                 "email": "an email address", "email-list": "email addresses separated by commas",
                 "file": "absolute path of a file (or ~/...)", "folder": "absolute path of a folder (or ~/...)",
                 "uri": "an URL"}
        if fmt in hints:
            desc.append(hints[fmt])
        if "default" in prop:
            p["default"] = prop["default"]
            desc.append("default: %s" % json.dumps(prop["default"], ensure_ascii=False))
        for key in ("enum", "minimum", "maximum", "maxLength"):
            if key in prop:
                p[key] = prop[key]
        if p["type"] == "array":
            p["items"] = {"type": (prop.get("items") or {}).get("type", "string")}
        p["description"] = ". ".join(d for d in desc if d)
        props[name] = p
    return {"type": "object", "properties": props, "required": [r for r in intent.required if r in props]}


def model_description(intent) -> str:
    caps = ", ".join(intent.capabilities)
    text = "%s (%s app). %s Capabilities: %s." % (li.localized(intent.title, "en"), li.localized(intent.app_name, "en"),
                                                   li.localized(intent.description, "en"), caps)
    if not intent.read_only:
        text += " The user is asked to confirm before it runs."
    if intent.needs_ui:
        text += " Opens a window."
    examples = intent.examples.get("en", [])[:3]
    if examples:
        text += " Examples: " + "; ".join(examples)
    return text


# ------------------------------------------------------------------ previews and results

def _value_text(v) -> str:
    if isinstance(v, bool):
        return "sim" if v else "não"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return str(v)


def details(intent, params: dict) -> str:
    """The exact call, in plain pt-BR, for the confirmation card."""
    lines, long = [], []
    for name in intent.properties:
        if name not in params or params[name] in ("", [], None):
            continue
        prop = intent.properties[name]
        label = intent.param_title(name, "pt_BR")
        text = _value_text(params[name])
        if prop.get("x-multiline") or "\n" in text:
            long.append(text)
        else:
            lines.append("%s: %s" % (label, text))
    out = intent.app_name_text("pt_BR") + " › " + intent.summary_text(params, "pt_BR")
    if lines:
        out += "\n" + "\n".join(lines)
    if long:
        out += "\n\n" + "\n\n".join(long)
    if intent.needs_ui:
        out += "\n\n(abre uma janela)"
    return out


def check(intent, args: dict, caller: str) -> dict:
    """Clean parameters after the gate (with the user's confirmation assumed).
    Raises lingmo_intents.IntentError."""
    params = intent.validate(args)
    gate().check(intent, params, {"caller": caller, "confirmed": True})
    return params


def result_text(intent, result: dict) -> str:
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if len(text) > 12000:
        text = text[:12000] + "\n[…]"
    return text


def execute(intent, params: dict, caller: str, extra: dict | None = None) -> dict:
    ctx = {"caller": caller, "confirmed": not intent.read_only}
    ctx.update(extra or {})
    return li.execute(intent, params, ctx)


# ------------------------------------------------------------------ agno tools

def functions(ctx, cfg) -> list:
    """agno Functions for every installed intent the assistant may use now."""
    if li is None:
        return []
    from agno.tools.function import Function
    from . import tools as tools_mod
    out = []
    for intent in all_intents():
        if not usable(intent):
            continue
        name = function_name(intent.id)
        tools_mod.FUNCTION_TOOL[name] = tool_id(intent)

        def entry(_intent=intent, _name=name, **kwargs):
            return _run_tool(ctx, _intent, _name, kwargs)

        out.append(Function(name=name, description=model_description(intent), parameters=model_schema(intent),
                            entrypoint=entry, skip_entrypoint_processing=True,
                            requires_confirmation=not intent.read_only))
    return out


def _run_tool(ctx, intent, name: str, args: dict) -> str:
    from . import tools as tools_mod
    try:
        params = check(intent, args, "assistant")
        result = execute(intent, params, "assistant")
    except li.IntentError as exc:
        return ctx._done(name, False, exc.message, "Erro: " + exc.message)
    except Exception as exc:  # never leak contents into logs
        log.warning("intent %s failed: %s", intent.id, type(exc).__name__)
        return ctx._done(name, False, "Erro inesperado.", "Erro: a ação falhou.")
    text = result_text(intent, result)
    if intent.read_only:
        text = tools_mod.untrusted("the %s app (%s)" % (intent.app_name_text("en"), intent.id), text)
    summary = intent.summary_text(params, "pt_BR")
    return ctx._done(name, True, summary, text)


def preview(function: str, args: dict):
    """(tool id, title, details) of a pending intent call; raises paths.PolicyError when invalid."""
    from . import paths
    intent = intent_for_function(function)
    if intent is None:
        raise paths.PolicyError("Ação desconhecida.")
    try:
        params = check(intent, args, "assistant")
    except li.IntentError as exc:
        raise paths.PolicyError(exc.message) from None
    return tool_id(intent), "%s › %s" % (intent.app_name_text("pt_BR"), intent.title_text("pt_BR")), details(intent, params)


def args_summary(function: str, args: dict) -> str:
    intent = intent_for_function(function)
    if intent is None:
        return ""
    try:
        params = intent.validate(args)
    except li.IntentError:
        params = dict(args or {})
    return (intent.app_name_text("pt_BR") + " › " + " ".join(intent.summary_text(params, "pt_BR").split()))[:120]
