"""A scripted stand-in for the Ollama model (no network)."""
import json
from dataclasses import dataclass, field

from agno.models.response import ModelResponse

from lingmo_assistant.agent import LingmoOllama


@dataclass
class FakeModel(LingmoOllama):
    # Each step: ("text", "answer") or ("tool", name, {args}) or ("think", "…", "answer")
    script: list = field(default_factory=list)
    seen: list = field(default_factory=list)

    def invoke_stream(self, messages, assistant_message, **kwargs):
        self.seen.append([(m.role, m.content) for m in messages])
        step = self.script.pop(0) if self.script else ("text", "fim")
        if step[0] == "tool":
            r = ModelResponse()
            r.tool_calls = [{"type": "function", "function": {"name": step[1], "arguments": json.dumps(step[2])}}]
            yield r
            return
        if step[0] == "think":
            r = ModelResponse()
            r.reasoning_content = step[1]
            yield r
            step = ("text", step[2])
        for word in step[1].split(" "):
            r = ModelResponse()
            r.content = word + " "
            yield r
        self.usage.eval_count += 10
        self.usage.eval_ns += 500_000_000

    def invoke(self, messages, assistant_message, **kwargs):
        self.seen.append([(m.role, m.content) for m in messages])
        step = self.script.pop(0) if self.script else ("text", "resumo")
        r = ModelResponse()
        if step[0] == "tool":
            r.tool_calls = [{"type": "function", "function": {"name": step[1], "arguments": json.dumps(step[2])}}]
            return r
        r.content = step[1]
        return r
