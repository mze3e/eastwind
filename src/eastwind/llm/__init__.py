"""Offline planning and gateway-only model clients for Eastwind."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

PROVIDERS = ("mock", "openai", "anthropic", "xai", "ollama", "openai-compatible")
DEFAULT_MODELS = {"mock": "eastwind-mock", "openai": "gpt-4o-mini",
                  "anthropic": "claude-sonnet-4-6", "xai": "grok-4",
                  "ollama": "llama3.2", "openai-compatible": ""}
DEFAULT_BASE_URLS = {"openai": "https://api.openai.com", "anthropic": "https://api.anthropic.com",
                     "xai": "https://api.x.ai", "ollama": "http://127.0.0.1:11434",
                     "openai-compatible": ""}
KEY_NAMES = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
             "xai": "XAI_API_KEY", "openai-compatible": "EASTWIND_LLM_API_KEY"}
PLANS = {
    "client-review": ("client_profile", "account_holdings", "summarize_review"),
    "suitability": ("client_profile", "product_profile", "check_suitability"),
    "rebalance": ("account_holdings", "check_suitability", "propose_trade"),
    "research": ("approved_sources", "retrieve_house_view", "summarize_research"),
}


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict


class MockClient:
    """Deterministic plans, with no network or credentials."""

    def plan(self, workflow: str) -> list[ToolCall]:
        try:
            return [ToolCall(name, {}) for name in PLANS[workflow]]
        except KeyError as exc:
            raise ValueError(f"unknown workflow: {workflow}") from exc

    def answer(self, prompt: str) -> str:
        return "House guidance was reviewed locally. Confirm suitability before making a recommendation."

    def complete(self, messages: list[dict], *, workflow: str = "client-review",
                 model: str = "eastwind-mock") -> dict:
        calls = self.plan(workflow)
        message = {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function", "function": {
                "name": call.name, "arguments": json.dumps(call.arguments, sort_keys=True)}}
            for i, call in enumerate(calls, 1)]}
        return {"id": "chatcmpl-eastwind", "object": "chat.completion", "created": 0,
                "model": model, "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 0,
                "completion_tokens": 0, "total_tokens": 0}}



@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    gateway: str
    key_env: str

    @classmethod
    def from_env(cls, provider: str | None = None) -> "Settings":
        selected = provider or os.getenv("EASTWIND_LLM_PROVIDER", "mock")
        if selected not in PROVIDERS:
            raise ValueError(f"unknown LLM provider: {selected}")
        return cls(selected, os.getenv("EASTWIND_LLM_MODEL") or DEFAULT_MODELS[selected],
                   os.getenv("EASTWIND_LLM_GATEWAY_URL", ""),
                   os.getenv("EASTWIND_LLM_KEY_ENV") or KEY_NAMES.get(selected, ""))

    def validate(self) -> None:
        if self.provider == "mock" and not self.gateway:
            return
        if self.provider not in PROVIDERS:
            raise ValueError(f"unknown LLM provider: {self.provider}")
        if not self.model.strip():
            raise ValueError("EASTWIND_LLM_MODEL is required")
        parsed = urlparse(self.gateway)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("a local Kognita gateway URL is required for a real provider")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
            raise ValueError("gateway URL must be an origin without credentials, path, query, or fragment")
        if self.provider not in {"mock", "ollama"} and (not self.key_env or not os.getenv(self.key_env)):
            raise ValueError(f"provider key is missing: set {self.key_env or 'EASTWIND_LLM_KEY_ENV'} in the gateway environment")


class GatewayClient:
    """Send compatible requests to a separately configured local gateway only.

    The gateway owns upstream credentials. Identity headers must be supplied by
    the caller from its governed run, not inferred from environment variables.
    """
    def __init__(self, settings: Settings, headers: dict[str, str]):
        settings.validate()
        if not settings.gateway:
            raise ValueError("a local Kognita gateway URL is required for gateway mode")
        if not headers:
            raise ValueError("governed identity headers are required")
        if any(name.lower() in {"authorization", "x-api-key", "api-key", "x-goog-api-key", "proxy-authorization"} for name in headers):
            raise ValueError("provider credentials must stay with the gateway")
        self.settings, self.headers = settings, dict(headers)

    def complete(self, messages: list[dict], **kwargs: object) -> dict:
        if {"model", "messages", "stream"} & kwargs.keys():
            raise ValueError("model, messages and streaming cannot be overridden")
        body = json.dumps({"model": self.settings.model, "messages": messages, **kwargs}).encode()
        headers = {**self.headers, "Content-Type": "application/json"}
        request = Request(self.settings.gateway.rstrip("/") + "/v1/chat/completions", data=body, headers=headers)
        # Neither proxy configuration nor a redirect may move this request
        # away from the configured local gateway.
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        opener = build_opener(ProxyHandler({}), NoRedirect())
        try:
            # Kognita 0.9 rejects GET with this response. This detects common
            # origin mixups; it is not cryptographic service authentication.
            try:
                opener.open(Request(self.settings.gateway.rstrip("/") + "/v1/chat/completions"), timeout=5)
            except HTTPError as probe:
                if probe.code != 405 or json.loads(probe.read()) != {"error": "the gateway only proxies model calls"}:
                    raise ValueError("configured endpoint is not a Kognita gateway") from probe
            else:
                raise ValueError("configured endpoint is not a Kognita gateway")
            with opener.open(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"Kognita gateway refused the model call (HTTP {exc.code})") from exc
        except URLError as exc:
            raise RuntimeError("Kognita gateway is unavailable") from exc
