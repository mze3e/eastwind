"""Offline planning and gateway-only model clients for Eastwind."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

PROVIDERS = ("mock", "openai", "anthropic", "xai", "ollama", "openai-compatible")
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

    def complete(self, messages: list[dict], *, workflow: str = "client-review") -> dict:
        calls = self.plan(workflow)
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": f"call_{i}", "type": "function", "function": {
                "name": call.name, "arguments": json.dumps(call.arguments, sort_keys=True)}}
            for i, call in enumerate(calls, 1)]}


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
        return cls(selected, os.getenv("EASTWIND_LLM_MODEL", "eastwind-mock"),
                   os.getenv("EASTWIND_LLM_GATEWAY_URL", ""),
                   os.getenv("EASTWIND_LLM_KEY_ENV", KEY_NAMES.get(selected, "")))

    def validate(self) -> None:
        if self.provider == "mock":
            return
        parsed = urlparse(self.gateway)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("a local Kognita gateway URL is required for a real provider")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("gateway URL must not contain credentials, a query, or a fragment")
        if self.provider != "ollama" and (not self.key_env or not os.getenv(self.key_env)):
            raise ValueError(f"provider key is missing: set {self.key_env or 'EASTWIND_LLM_KEY_ENV'} in the gateway environment")
        if self.provider == "anthropic":
            raise ValueError("Anthropic native messages are not supported by the Kognita 0.9 gateway; no request was sent")


class GatewayClient:
    """Send compatible requests to a separately configured local gateway only.

    The gateway owns upstream credentials. Identity headers must be supplied by
    the caller from its governed run, not inferred from environment variables.
    """
    def __init__(self, settings: Settings, headers: dict[str, str]):
        settings.validate()
        if settings.provider == "mock":
            raise ValueError("use MockClient for the in-process mock")
        if not headers:
            raise ValueError("governed identity headers are required")
        if any(name.lower() in {"authorization", "x-api-key", "proxy-authorization"} for name in headers):
            raise ValueError("provider credentials must stay with the gateway")
        self.settings, self.headers = settings, dict(headers)

    def complete(self, messages: list[dict], **kwargs: object) -> dict:
        body = json.dumps({"model": self.settings.model, "messages": messages, **kwargs}).encode()
        headers = {**self.headers, "Content-Type": "application/json"}
        request = Request(self.settings.gateway.rstrip("/") + "/v1/chat/completions", data=body, headers=headers)
        # Neither proxy configuration nor a redirect may move this request
        # away from the configured local gateway.
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=30) as response:
            return json.load(response)
