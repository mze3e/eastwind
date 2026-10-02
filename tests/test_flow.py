"""The governed path: no retrieval and no model on DENY; redacted egress on ALLOW."""

from __future__ import annotations

import json

import pytest
from sqlmodel import Session, select

from kognita import (
    ChainBreak,
    Classification,
    EgressDecision,
    EmbedderConfig,
    EvidenceEvent,
    Outcome,
    make_engine,
    verify_chain,
)
from kognita.adapters import OpenAICompatibleEmbedder

from eastwind.openai_chat import OpenAIChat
from eastwind.pack import CLIENTS
from eastwind.run import run_scenario


def test_openai_adapter_treats_hosted_embeddings_as_remote():
    embedder = OpenAICompatibleEmbedder(
        EmbedderConfig(
            provider="openai",
            model="text-embedding-3-small",
            dimension=1536,
            api_key="not-used",
        )
    )
    assert embedder.is_local is False
    assert embedder._url == "https://api.openai.com/v1/embeddings"


def test_llm_config_marks_openai_cloud_as_not_local():
    chat = OpenAIChat(api_key="not-used")
    assert chat.destination_is_local is False


def test_deny_does_not_retrieve_or_call_the_model():
    calls: list[str] = []

    def spy(text: str) -> str:
        calls.append(text)
        raise AssertionError("model callable must not run on DENY")

    engine = make_engine(":memory:")
    result = run_scenario("deny", engine=engine, completer=spy, call_model=True)
    assert result.evaluation.outcome is Outcome.DENY
    assert result.retrieval_called is False
    assert result.retrieved_titles == []
    assert result.model_called is False
    assert result.egress is None
    assert calls == []
    assert result.event_types == ["POLICY_DECISION"]
    blob = json.dumps(result.evaluation.to_dict())
    assert "lena.vogel@" not in blob
    assert "HK-PB-2002771" not in blob

    with Session(engine) as session:
        payloads = [row.payload for row in session.exec(select(EvidenceEvent)).all()]
    evidence_blob = json.dumps(payloads)
    assert "lena.vogel@" not in evidence_blob
    assert "mei.tan@" not in evidence_blob


def test_allow_redacts_before_the_model_and_restores_the_reply():
    seen: list[str] = []
    client = CLIENTS["CL-1001"]

    def spy(text: str) -> str:
        seen.append(text)
        return "Eligible. Speak with [TERM_1] at [EMAIL_1] about account [ACCOUNT_1]."

    engine = make_engine(":memory:")
    result = run_scenario("allow", engine=engine, completer=spy, destination_is_local=False)
    assert result.evaluation.outcome is Outcome.ALLOW
    assert result.retrieval_called is True
    assert "House view — SGD money market eligibility" in result.retrieved_titles
    assert "Steering note — Mei Tan consolidation" not in result.retrieved_titles
    assert "DFSA cross-border promotion" not in result.retrieved_titles
    assert result.classification is Classification.C2
    assert result.model_called is True
    assert result.egress is not None
    assert result.egress.decision is EgressDecision.REDACT
    assert len(seen) == 1
    sent = seen[0]
    assert client["email"] not in sent
    assert client["name"] not in sent
    assert client["account"] not in sent
    assert "[EMAIL_1]" in sent
    assert "[TERM_1]" in sent
    assert "[ACCOUNT_1]" in sent
    restored = result.egress.response
    assert client["name"] in restored
    assert client["email"] in restored
    assert client["account"] in restored
    assert result.event_types == ["POLICY_DECISION", "RETRIEVAL", "MODEL_CALL", "EGRESS"]

    with Session(engine) as session:
        payloads = [row.payload for row in session.exec(select(EvidenceEvent)).all()]
    evidence_blob = json.dumps(payloads)
    assert client["email"] not in evidence_blob
    assert client["account"] not in evidence_blob
    assert client["name"] not in evidence_blob
    model_events = [
        payload
        for payload in payloads
        if payload.get("decision") == "REDACT" and payload.get("sent") is True
    ]
    assert model_events
    assert all(event["manifest_hash"] for event in model_events)


def test_allow_without_a_completer_retrieves_and_skips_the_model():
    engine = make_engine(":memory:")
    result = run_scenario("allow", engine=engine, completer=None, call_model=True)
    assert result.evaluation.outcome is Outcome.ALLOW
    assert result.retrieval_called is True
    assert result.model_called is False
    assert result.model_skip_reason == "OPENAI_API_KEY is not set"
    assert "MODEL_CALL" not in result.event_types
    assert "RETRIEVAL" in result.event_types


def test_tamper_breaks_the_chain():
    engine = make_engine(":memory:")
    run_scenario("deny", engine=engine, call_model=False)
    with Session(engine) as session:
        event = session.exec(select(EvidenceEvent)).one()
        event.payload = {"tampered": True}
        session.add(event)
        session.commit()
        with pytest.raises(ChainBreak, match="payload does not match its hash"):
            verify_chain(session)
