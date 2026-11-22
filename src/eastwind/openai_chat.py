"""Compatibility wrapper for a Kognita gateway-backed chat client."""
from __future__ import annotations

from dataclasses import dataclass, field

from eastwind.llm import GatewayClient, Settings

DEFAULT_MODEL = "gpt-4o-mini"


@dataclass
class OpenAIChat:
    """Send a chat request through the configured gateway, never to a provider."""
    api_key: str = field(default="", repr=False)
    model: str = DEFAULT_MODEL
    headers: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def destination_is_local(self) -> bool:
        return False

    def __call__(self, redacted_user: str) -> str:
        configured = Settings.from_env("openai")
        settings = Settings(configured.provider, self.model, configured.gateway, configured.key_env)
        result = GatewayClient(settings, self.headers).complete([{"role": "user", "content": redacted_user}])
        return result["choices"][0]["message"].get("content") or ""
