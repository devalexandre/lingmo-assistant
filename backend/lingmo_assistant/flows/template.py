"""`{{node.output}}` templates.

A placeholder is `{{ name.path }}`: the first part is a node id or one of the
special scopes (`var`, `loop`, `now`, `trigger`), the rest a dotted path into
that value (dict keys or list indexes). Unknown names render as an empty
string and are reported, never raise: a template can't run code, call
functions or reach anything outside the run's own variables.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any, Iterable

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}")
SPECIAL = ("var", "loop", "now", "trigger", "run")
MAX_RENDERED = 200_000


class Scope:
    """Variables visible to one node: node outputs, named variables, the loop."""

    def __init__(self, outputs: dict[str, dict] | None = None, variables: dict[str, Any] | None = None,
                 loop: dict[str, Any] | None = None, trigger_id: str = "", run: dict | None = None,
                 now: dt.datetime | None = None):
        self.outputs = outputs if outputs is not None else {}
        self.variables = variables if variables is not None else {}
        self.loop = loop or {}
        self.trigger_id = trigger_id
        self.run = run or {}
        self.now = now

    def child_loop(self, item: Any, index: int) -> "Scope":
        return Scope(self.outputs, self.variables, {"item": item, "index": index, "number": index + 1},
                     self.trigger_id, self.run, self.now)

    def root(self, name: str):
        if name == "var":
            return self.variables
        if name == "loop":
            return self.loop
        if name == "run":
            return self.run
        if name == "now":
            now = self.now or dt.datetime.now().astimezone()
            return {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
                    "datetime": now.strftime("%Y-%m-%d %H:%M"), "weekday": now.strftime("%A")}
        if name == "trigger":
            return self.outputs.get(self.trigger_id)
        return self.outputs.get(name)


_MISSING = object()


def lookup(scope: Scope, dotted: str):
    parts = dotted.split(".")
    value = scope.root(parts[0])
    if value is None:
        return _MISSING
    if len(parts) == 1:
        # `{{node}}` means the node's main output
        return value.get("output", "") if isinstance(value, dict) and parts[0] not in SPECIAL else value
    for part in parts[1:]:
        if isinstance(value, dict):
            if part not in value:
                return _MISSING
            value = value[part]
        elif isinstance(value, (list, tuple)) and part.isdigit():
            idx = int(part)
            if idx >= len(value):
                return _MISSING
            value = value[idx]
        else:
            return _MISSING
    return value


def to_text(value: Any) -> str:
    if value is None or value is _MISSING:
        return ""
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, (list, tuple)):
        return "\n".join(to_text(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def render(text: Any, scope: Scope, missing: list[str] | None = None) -> str:
    """Replaces every placeholder with the text of its value."""
    if not isinstance(text, str):
        return to_text(text)

    def sub(m):
        value = lookup(scope, m.group(1))
        if value is _MISSING and missing is not None:
            missing.append(m.group(1))
        return to_text(value)
    out = PLACEHOLDER.sub(sub, text)
    return out[:MAX_RENDERED]


def resolve(text: Any, scope: Scope, missing: list[str] | None = None) -> Any:
    """Like render(), but a field that is exactly one placeholder keeps the
    value's type (a list for a loop, a number for a comparison)."""
    if isinstance(text, str):
        m = PLACEHOLDER.fullmatch(text.strip())
        if m:
            value = lookup(scope, m.group(1))
            if value is _MISSING:
                if missing is not None:
                    missing.append(m.group(1))
                return ""
            return value
    return render(text, scope, missing)


def references(text: Any) -> list[str]:
    """Dotted names used in a field (for validation and the editor)."""
    if isinstance(text, str):
        return [m.group(1) for m in PLACEHOLDER.finditer(text)]
    if isinstance(text, (list, tuple)):
        out = []
        for v in text:
            out += references(v)
        return out
    if isinstance(text, dict):
        out = []
        for v in text.values():
            out += references(v)
        return out
    return []


def roots(names: Iterable[str]) -> set[str]:
    return {n.split(".", 1)[0] for n in names}
