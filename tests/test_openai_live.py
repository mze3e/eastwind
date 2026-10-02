"""Live OpenAI call. Skipped unless OPENAI_API_KEY is set."""

from __future__ import annotations

import os

import pytest

from kognita import Classification, EgressDecision, make_engine

from eastwind.openai_chat import OpenAIChat
from eastwind.pack import CLIENTS
from eastwind.run import run_scenario

pytestmark = pytest.mark.openai


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY is not set")
def test_allow_makes_a_governed_openai_call():
    key = os.environ["OPENAI_API_KEY"]
    chat = OpenAIChat(api_key=key, model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    engine = make_engine(":memory:")
    result = run_scenario(
        "allow",
        engine=engine,
        completer=chat,
        destination_is_local=chat.destination_is_local,
    )
    client = CLIENTS["CL-1001"]
    assert result.evaluation.outcome.value == "ALLOW"
    assert result.model_called is True
    assert result.egress is not None
    assert result.egress.decision is EgressDecision.REDACT
    assert result.classification is Classification.C2
    assert client["email"] not in result.egress.sent_text
    assert client["account"] not in result.egress.sent_text
    assert client["name"] not in result.egress.sent_text
    assert isinstance(result.egress.response, str)
    assert result.egress.response.strip()
    assert "MODEL_CALL" in result.event_types
    assert "EGRESS" in result.event_types
    assert result.chain_length >= 4
