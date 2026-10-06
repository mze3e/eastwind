"""OpenAI chat completions as the callable behind ``EgressGuard.send``.

kognita 0.3 ships the AI gateway (``kognita serve``) and
``kognita.adapters.OpenAICompatibleEmbedder``. It still does not ship a
chat-completions client. This callable is the OpenAI SDK installed by
``kognita[openai]``. ``EgressGuard.send`` is the only path that may invoke it
on the direct workshop run: the guard receives the raw prompt, redacts or
refuses, and the SDK sees the text the guard decided to send. The gateway
scenario points the same SDK at ``base_url`` instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kognita import LLMConfig

DEFAULT_MODEL = "gpt-4o-mini"
DESTINATION = "api.openai.com"

SYSTEM_PROMPT = (
    "You are the eligibility assistant for Eastwind Private, a fictional "
    "workshop institution. Answer the relationship manager in at most three "
    "sentences. Use only the house guidance in the user message. If that "
    "guidance does not support a statement, say so. Keep placeholder tokens "
    "such as [TERM_1] exactly as written."
)


@dataclass
class OpenAIChat:
    """One governed chat-completions call. ``api_key`` is omitted from ``repr``."""

    api_key: str = field(repr=False)
    model: str = DEFAULT_MODEL
    system: str = field(default=SYSTEM_PROMPT, repr=False)

    @property
    def destination_is_local(self) -> bool:
        """Cloud OpenAI is outside the trust boundary. ``LLMConfig`` fails closed."""
        return LLMConfig(
            provider="openai",
            api_key=self.api_key,
            model=self.model,
        ).is_local()

    def __call__(self, redacted_user: str) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        completion = client.chat.completions.create(
            model=self.model,
            temperature=0,
            max_tokens=300,
            messages=[
                {"role": "system", "content": self.system},
                {"role": "user", "content": redacted_user},
            ],
        )
        return completion.choices[0].message.content or ""
