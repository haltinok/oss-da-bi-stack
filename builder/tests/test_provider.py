"""Which model the builder talks to: Anthropic by default, DeepSeek or another Anthropic-compatible server by settings; and the real SDK's wire format against a fake server."""
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from dashspec import catalog as cat

from builder import core, provider

REPO = pathlib.Path(__file__).resolve().parents[2]
CATALOG = cat.from_model(REPO / "cube" / "model")
GOOD = (REPO / "dashboards" / "regional-sales.yml").read_text()
ENV = ("BUILDER_PROVIDER", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "BUILDER_MODEL", "BUILDER_SPEC_REFERENCE")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)


def test_anthropic_is_the_default():
    assert (provider.provider(), provider.model(), provider.base_url(), provider.is_anthropic(), provider.has_key(), provider.label()) == ("anthropic", "claude-opus-5-5", "", True, False, "Claude")


def test_deepseek_is_one_setting_with_its_own_key_and_a_cheap_default_model(monkeypatch):
    monkeypatch.setenv("BUILDER_PROVIDER", "deepseek")
    assert provider.base_url() == "https://api.deepseek.com/anthropic" and provider.model() == "deepseek-flash" and not provider.is_anthropic() and provider.label() == "DeepSeek"
    assert not provider.has_key()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek")
    assert provider.has_key() and provider.api_key() == "sk-deepseek"
    monkeypatch.setenv("BUILDER_MODEL", "deepseek-v4-pro")
    assert provider.model() == "deepseek-v4-pro"


def test_any_compatible_server_works_by_its_address(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://llm.internal.example/anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    monkeypatch.setenv("BUILDER_MODEL", "open-model")
    assert not provider.is_anthropic() and provider.label() == "llm.internal.example" and provider.model() == "open-model" and provider.has_key()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    assert provider.is_anthropic() and provider.label() == "Claude"


def test_an_unknown_provider_is_refused(monkeypatch):
    monkeypatch.setenv("BUILDER_PROVIDER", "nonsense")
    with pytest.raises(SystemExit):
        provider.provider()


BLOCKS = [{"type": "text", "text": "SYSTEM A", "cache_control": {"type": "ephemeral"}}, {"type": "text", "text": "SYSTEM B"}]


def test_anthropic_gets_cache_markers_and_the_effort_setting_others_get_plain_text(monkeypatch):
    a = provider.request_kwargs(BLOCKS, "medium")
    assert a["model"] == "claude-opus-5-5" and a["system"] == BLOCKS and a["output_config"] == {"effort": "medium"}
    assert "output_config" not in provider.request_kwargs(BLOCKS, "")
    monkeypatch.setenv("BUILDER_PROVIDER", "deepseek")
    d = provider.request_kwargs(BLOCKS, "medium")
    assert d == {"model": "deepseek-flash", "system": "SYSTEM A\n\nSYSTEM B"}


def test_the_prompt_carries_the_field_reference_and_examples_the_role_can_use():
    system = core.system_blocks(CATALOG, "admin")[0]["text"]
    assert "The complete field reference" in system and "| `drill` |" in system and "| `by_label` |" in system and "| `sum` |" in system and "pie" in system
    assert "Rules the validator enforces" in system, "the validator's rules are in the prompt too"
    assert "drill:" in system and "type: pie" in system and "locale: tr-TR" in system, "an example with a drill-down and a pie, with Turkish labels"
    rep = core.system_blocks(CATALOG, "rep")[0]["text"]
    assert "gross_profit" not in rep and "margin_pct" not in rep and "type: pie" in rep, "a rep's prompt never names a profit member, not even in the rules"
    mk = core.system_blocks(CATALOG, "marketing")[0]["text"]
    assert "internet_sales" not in mk and "vendor_name" not in mk and "lead_time_days" not in mk, "a marketing user's prompt names no sales member and no supplier member"


def test_the_reference_can_be_left_out_to_save_tokens(monkeypatch):
    monkeypatch.setattr(core, "SPEC_REFERENCE", False)
    assert "| `drill` |" not in core.system_blocks(CATALOG, "admin")[0]["text"]


def test_a_code_fence_around_the_yaml_is_tolerated():
    for wrapped in (f"```yaml\n{GOOD}```", f"```\n{GOOD}\n```", f"  ```yml\n{GOOD}\n```  "):
        built, problems = core.check_submission(wrapped, CATALOG, "manager")
        assert built is not None, problems


class FakeAnthropic(BaseHTTPRequestHandler):
    """An Anthropic-compatible server (what DeepSeek's endpoint looks like to the SDK): records the request and answers with a tool call."""
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeAnthropic.seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        out = {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "stop_reason": "tool_use", "stop_sequence": None,
               "content": [{"type": "tool_use", "id": "toolu_1", "name": "submit_dashboard", "input": {"yaml": GOOD, "summary": "Made by the fake."}}],
               "usage": {"input_tokens": 1234, "output_tokens": 56}}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def sent_key(seen):
    """The SDK sends the key as `Authorization: Bearer` (older versions: `x-api-key`); a compatible endpoint takes either."""
    h = seen["headers"]
    return h.get("x-api-key") or h["authorization"].removeprefix("Bearer ")


def run_against_fake(monkeypatch, **env):
    FakeAnthropic.seen.clear()
    server = HTTPServer(("127.0.0.1", 0), FakeAnthropic)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for k, v in {"ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}/anthropic", **env}.items():
        monkeypatch.setenv(k, v)
    try:
        client = provider.make_client(30)
        return core.run_build(client, CATALOG, "manager", "regional sales", mode="llm"), FakeAnthropic.seen[0]
    finally:
        server.shutdown()


def test_the_real_sdk_talks_to_a_compatible_server_in_the_plain_wire_format(monkeypatch):
    """Not mocked at the SDK: the request really goes over HTTP with the headers and JSON a compatible endpoint receives."""
    out, seen = run_against_fake(monkeypatch, BUILDER_PROVIDER="deepseek", DEEPSEEK_API_KEY="sk-deepseek", BUILDER_MODEL="deepseek-flash")
    assert out["status"] == "ok" and out["model"] == "deepseek-flash" and out["usage"]["input_tokens"] == 1234 and out["message"] == "Made by the fake."
    assert seen["path"] == "/anthropic/v1/messages" and sent_key(seen) == "sk-deepseek"
    body = seen["body"]
    assert body["model"] == "deepseek-flash" and isinstance(body["system"], str) and "cache_control" not in json.dumps(body["system"]) and "output_config" not in body
    assert [t["name"] for t in body["tools"]] == ["submit_dashboard", "cannot_build"] and body["tools"][0]["input_schema"]["required"] == ["yaml"]
    assert body["messages"][0] == {"role": "user", "content": "regional sales"} and body["max_tokens"] == core.MAX_TOKENS
    assert "| `drill` |" in body["system"], "the whole field reference reaches the model"


def test_the_real_sdk_sends_cache_markers_and_effort_to_anthropic_style_servers(monkeypatch):
    out, seen = run_against_fake(monkeypatch, ANTHROPIC_API_KEY="sk-ant-test")
    assert out["status"] == "ok" and sent_key(seen) == "sk-ant-test" and seen["body"]["model"] == "claude-opus-5-5"
    assert isinstance(seen["body"]["system"], str), "a local address is not anthropic.com, so it gets the plain request"
    monkeypatch.setattr(provider, "is_anthropic", lambda: True)                       # what api.anthropic.com gets: blocks with a cache marker and the effort setting
    out, seen = run_against_fake(monkeypatch, ANTHROPIC_API_KEY="sk-ant-test")
    assert seen["body"]["system"][0]["cache_control"] == {"type": "ephemeral"} and seen["body"]["output_config"] == {"effort": "medium"}
