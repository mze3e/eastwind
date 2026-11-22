"""Optional gateway-backed live call, disabled unless explicitly enabled."""

from __future__ import annotations

import os

import pytest

from kognita import Classification, EgressDecision, make_engine

from eastwind.openai_chat import OpenAIChat
from eastwind.pack import CLIENTS
from eastwind.run import run_scenario

pytestmark = [pytest.mark.openai, pytest.mark.live]


@pytest.mark.skipif(os.environ.get("EASTWIND_RUN_LIVE") != "1", reason="live tests are disabled")
def test_allow_makes_a_governed_openai_call():
    key = os.environ["OPENAI_API_KEY"]
    from sqlmodel import Session
    from kognita import Run
    from kognita.models import RunRecord
    from eastwind.pack import _headers

    gateway_engine = make_engine(os.environ["EASTWIND_LLM_GATEWAY_DB"])
    model = os.environ.get("EASTWIND_LLM_MODEL", "gpt-4o-mini")
    with Session(gateway_engine) as session:
        headers = _headers(session, model=model)
        run = Run()
        session.add(RunRecord(id=run.id))
        headers["run_id"] = run.id
        session.commit()
    chat = OpenAIChat(api_key=key, model=model, headers=headers)
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
