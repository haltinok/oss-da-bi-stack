"""Which language model the builder talks to, and how.

Anthropic's own API is the default (`claude-opus-5-5`). Anything that speaks the Anthropic Messages API works through the same SDK by pointing it at another
base URL, which is how DeepSeek is supported (https://api-docs.deepseek.com/guides/anthropic_api): `BUILDER_PROVIDER=deepseek` plus `DEEPSEEK_API_KEY`, or
set `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY` and `BUILDER_MODEL` for any other compatible server (a self-hosted open model behind such a gateway too).

Requests to a provider other than Anthropic are plainer: the system prompt is one string (no cache markers) and no effort setting is sent, since those are
Anthropic features a compatible endpoint may reject or ignore.
"""
from __future__ import annotations

import os

PRESETS = {
    # DeepSeek's Anthropic-compatible endpoint. deepseek-flash is its cheap model; deepseek-v4-pro its strongest. Override with BUILDER_MODEL.
    "deepseek": {"base_url": "https://api.deepseek.com/anthropic", "model": "deepseek-flash", "key_env": "DEEPSEEK_API_KEY", "label": "DeepSeek"},
}
DEFAULT_MODEL = "claude-opus-5-5"


def provider() -> str:
    name = os.environ.get("BUILDER_PROVIDER", "anthropic").strip().lower() or "anthropic"
    if name != "anthropic" and name not in PRESETS:
        raise SystemExit(f"BUILDER_PROVIDER must be anthropic or one of {sorted(PRESETS)}, got {name!r}")
    return name


def _preset() -> dict:
    return PRESETS.get(provider(), {})


def base_url() -> str:
    return os.environ.get("ANTHROPIC_BASE_URL") or _preset().get("base_url", "")


def model() -> str:
    return os.environ.get("BUILDER_MODEL") or _preset().get("model", DEFAULT_MODEL)


def api_key() -> str:
    preset = _preset()
    return (os.environ.get(preset["key_env"], "") if preset else "") or os.environ.get("ANTHROPIC_API_KEY", "")


def has_key() -> bool:
    return bool(api_key())


def is_anthropic() -> bool:
    url = base_url()
    return not url or "anthropic.com" in url


def label() -> str:
    """Who reads the request, for the page: Claude, DeepSeek, or the host of another compatible server."""
    if provider() != "anthropic":
        return _preset()["label"]
    return "Claude" if is_anthropic() else (base_url().split("//")[-1].split("/")[0] or "a compatible server")


def make_client(timeout: float):
    import anthropic
    return anthropic.Anthropic(api_key=api_key(), base_url=base_url() or None, timeout=timeout, max_retries=1)


def request_kwargs(system_blocks: list[dict], effort: str) -> dict:
    """The provider-specific part of a messages.create call: the model, the system prompt, and (Anthropic only) cache markers and the effort setting."""
    if is_anthropic():
        return {"model": model(), "system": system_blocks, **({"output_config": {"effort": effort}} if effort else {})}
    return {"model": model(), "system": "\n\n".join(b["text"] for b in system_blocks)}
