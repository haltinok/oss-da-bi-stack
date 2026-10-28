"""The stand-in model behind the same `client.messages.create` interface as the Anthropic SDK: it answers with one tool call, composed by the rules
in composer.py. The builder's loop, its checks and its service run unchanged around it, so everything but the language understanding is exercised
without an API key. Never mistaken for an LLM: results carry mode "standin" and the page says so."""
from __future__ import annotations

import re
import uuid
from types import SimpleNamespace

import yaml
from dashspec import catalog as cat

from builder import composer


def _block(**kw):
    return SimpleNamespace(**kw, model_dump=lambda kw=kw: dict(kw))


class StandInClient:
    def __init__(self, catalog: cat.Catalog, role: str):
        self.catalog, self.role = catalog, role
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, *, messages, **_kw):
        first = messages[0]["content"]
        text = first if isinstance(first, str) else ""
        m = re.search(r"```yaml\n(.*?)```", text, re.S)
        current = m.group(1) if m else None
        prompt = text.split("\n\nThe current dashboard")[0]
        f = re.search(r"^Focus: panel id ([\w-]+)", prompt, re.M)
        focus = f.group(1) if f else None
        prompt = re.sub(r"\n*Focus: .*", "", prompt, flags=re.S)
        from builder.core import visible_catalog
        comp = composer.compose(prompt, visible_catalog(self.catalog, self.role), self.role, current, focus)
        usage = SimpleNamespace(input_tokens=0, output_tokens=0)
        if comp.spec is None:
            call = _block(type="tool_use", id=f"toolu_{uuid.uuid4().hex[:12]}", name="cannot_build", input={"reason": comp.reason})
        else:
            summary = " ".join(comp.notes) or "Composed from your request by keyword rules."
            call = _block(type="tool_use", id=f"toolu_{uuid.uuid4().hex[:12]}", name="submit_dashboard",
                          input={"yaml": yaml.safe_dump(comp.spec, sort_keys=False, allow_unicode=True, width=140), "summary": summary})
        return SimpleNamespace(content=[call], stop_reason="tool_use", usage=usage)
