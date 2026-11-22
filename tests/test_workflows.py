"""Offline wealth-agent workflows and their governance boundaries."""
import json

import pytest
from sqlmodel import Session
from kognita.models import Approval, EvidenceEvent
from sqlmodel import select

from eastwind.agents.data import CLIENT, SOURCE
from eastwind.agents.workflows import (WealthAgent, budget, client_review, degraded, egress,
    kill_switch, mcp, rebalance, replay, research, run_workflow, suitability)
from eastwind.cli import main


def test_review_masks_agent_fields_and_denies_before_read(tmp_path):
    agent = client_review(tmp_path / "agent.db")
    rm = client_review(tmp_path / "rm.db", role="relationship_manager")
    denied = client_review(tmp_path / "visitor.db", role="visitor")
    agent_profile = agent.steps[0]["data"]
    assert agent_profile["email"] == "[MASKED]"
    assert "tax_identifier" not in agent_profile
    assert rm.steps[0]["data"]["email"] == CLIENT["email"]
    assert rm.steps[0]["data"]["tax_identifier"] == "[MASKED]"
    assert denied.steps[0]["outcome"] == "DENY"
    assert denied.facts["retrieved"] == []
    assert [step["tool"] for step in agent.steps] == ["client_profile", "account_holdings", "summarize_review"]
    assert agent.facts["chain_length"] > 0


def test_suitability_obeys_client_risk_and_mandate(tmp_path):
    low = suitability(tmp_path / "low.db")
    high = suitability(tmp_path / "high.db", product_id="INS-HK-NOTE")
    assert low.facts["suitability"]["suitable"] is True
    assert high.facts["suitability"]["suitable"] is False
    assert high.facts["suitability"]["mandate"] == "MANDATE-1"
    assert [step["outcome"] for step in high.steps] == ["ALLOW"] * 3


def test_source_checks_precede_retrieval_and_stop_plan(tmp_path):
    allowed = research(tmp_path / "allowed.db")
    denied = research(tmp_path / "denied.db", source_id="unapproved")
    assert allowed.steps[1]["data"]["text"] == SOURCE["text"]
    assert denied.steps[-1]["data"] == {"denied": True, "citation": "C3-UNAPPROVED"}
    assert denied.facts["retrieved"] == []
    assert len(denied.steps) == 2


def test_approval_release_is_rechecked_after_kill_switch(tmp_path):
    result = rebalance(tmp_path / "approval.db")
    assert result.steps[-1]["outcome"] == "HUMAN_APPROVAL"
    assert result.facts["held"] and result.facts["checkpoint"]
    assert result.facts["denied_executed"] is False
    assert result.facts["approved_executed"] is True
    assert result.facts["approved_before_stop"] is True
    assert result.facts["stopped_executed"] is False
    assert result.facts["proposal_count"] == 1
    from kognita import make_engine
    with Session(make_engine(tmp_path / "approval.db")) as session:
        approvals = session.exec(select(Approval)).all()
        assert len(approvals) >= 3
        assert any(row.status.value == "REJECTED" for row in approvals)
        events = session.exec(select(EvidenceEvent)).all()
        assert any("KILL_SWITCH" in json.dumps(event.payload) for event in events)


def test_budget_and_kill_switch_prevent_tool_execution(tmp_path):
    limited = budget(tmp_path / "budget.db")
    assert [step["outcome"] for step in limited.steps] == ["ALLOW", "DENY"]
    assert limited.facts["retrieved"] == ["client_profile"]
    assert any("max_calls" in c for c in limited.facts["budget_citations"])
    stopped = kill_switch(tmp_path / "stop.db")
    assert stopped.steps[0]["outcome"] == "DENY"
    assert "KILL_SWITCH" in stopped.facts["checks"]
    assert stopped.facts["retrieved"] == []


def test_egress_blocks_restricted_data_before_provider(tmp_path):
    result = egress(tmp_path / "egress.db")
    assert result.facts["blocked"] is True
    assert result.facts["provider_calls"] == 0


def test_mcp_uses_proxy_and_forwards_tool(tmp_path):
    result = mcp(tmp_path / "mcp.db")
    assert result.steps[0]["status"] == 200
    assert result.steps[0]["outcome"] == "ALLOW"
    assert result.facts["backend_calls"] == ["house_view"]


def test_degraded_mode_fails_closed_for_remote_and_client_data(tmp_path):
    result = degraded(tmp_path / "gateway.db")
    assert result.facts["fail_closed_status"] == 503
    assert result.facts["fail_closed_forwarded"] == 0
    assert result.facts["degraded_local_status"] == 200
    assert result.facts["degraded_remote_outcome"] == "DENY"
    assert result.facts["degraded_remote_forwarded"] == 0
    assert result.facts["degraded_c2_outcome"] == "DENY"
    assert result.facts["degraded_c2_forwarded"] == 0
    assert result.facts["degraded_chain"] is True


def test_replay_and_reconstruction_of_review_decision(tmp_path):
    path = tmp_path / "replay.db"
    review = client_review(path)
    result = replay(path)
    assert result.facts["request_id"] == review.steps[0]["request_id"]
    assert result.facts["interaction_id"] == review.facts["interaction_id"]
    assert result.facts["report"]["interaction_id"] == review.facts["interaction_id"]
    assert result.facts["outcome"] == "ALLOW"
    assert result.facts["request_id"]
    assert len(result.facts["report"]["questions"]) >= 10
    assert result.facts["report"]["findings"] == []
    model_question = next(q for q in result.facts["report"]["questions"]
                          if q["question"] == "What model or agent produced it?")
    assert any(model["provider"] == "mock" for model in model_question["answer"]["models"])
    assert result.facts["chain_length"] > 0


def test_cli_selects_workflows_and_fails_closed_on_real_llm(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("EASTWIND_LLM_PROVIDER", raising=False)
    assert main(["workflow", "client-review", "--db", str(tmp_path), "--role", "visitor"]) == 0
    assert '"outcome": "DENY"' in capsys.readouterr().out
    assert main(["workflow", "research", "--db", str(tmp_path), "--llm", "openai"]) == 1
    assert "offline mock" in capsys.readouterr().err
    with pytest.raises(ValueError, match="unknown workflow"):
        run_workflow("missing", tmp_path)


def test_unapproved_source_version_is_not_retrieved(tmp_path):
    agent = WealthAgent(tmp_path / "source.db")
    with Session(agent.engine) as session:
        step = agent.call(session, "retrieve_house_view", arguments={"version": "missing"})
        assert json.loads(step.data) == {"denied": True, "citation": "C3-UNAPPROVED"}
        assert agent.reads == []
        session.commit()


def test_incomplete_workflow_store_fails_closed(tmp_path):
    from kognita.models import Policy
    path = tmp_path / "old.db"
    agent = WealthAgent(path)
    with Session(agent.engine) as session:
        policy = session.exec(select(Policy).where(Policy.regime == "ROLE_ENTITLEMENT")).one()
        session.delete(policy)
        session.commit()
    with pytest.raises(ValueError, match="lacks required mandate or policies"):
        WealthAgent(path)


def test_policy_resolution_loads_no_client_identity_fields():
    from eastwind.agents.workflows import PACK
    from eastwind.pack import client_envelope
    subjects = PACK.load_subjects(client_envelope("client_profile"))
    assert "name" not in subjects["client"]
    assert "email" not in subjects["client"]
    assert "account" not in subjects["client"]
    assert subjects["client"]["domicile"] == "SG"


def test_model_arguments_cannot_widen_role(tmp_path):
    agent = WealthAgent(tmp_path / "role.db", role="visitor")
    with Session(agent.engine) as session:
        result = agent.call(session, "client_profile", arguments={"role": "relationship_manager"})
        assert result.outcome.value == "DENY"
        assert result.data is None
        assert agent.reads == []
        proposal = agent.call(session, "propose_trade", arguments={"role": "relationship_manager"})
        assert proposal.outcome.value == "DENY"
        assert not agent.proposals
        session.commit()


def test_kill_switch_stops_mock_model_before_planning(tmp_path, monkeypatch):
    from eastwind.llm import MockClient

    def forbidden(*args, **kwargs):
        raise AssertionError("mock model must not run after the kill switch")

    monkeypatch.setattr(MockClient, "complete", forbidden)
    result = kill_switch(tmp_path / "stopped.db")
    assert result.steps[0]["tool"] == "model_call"
    assert result.steps[0]["outcome"] == "DENY"
    assert not result.facts["retrieved"]


def test_model_step_is_evidenced_before_client_tool(tmp_path):
    from kognita import make_engine
    path = tmp_path / "review.db"
    result = client_review(path)
    with Session(make_engine(path)) as session:
        events = session.exec(select(EvidenceEvent).order_by(EvidenceEvent.sequence)).all()
        model = next(event for event in events if event.event_type == "MODEL_CALL")
        client = next(event for event in events if event.correlation_id == result.steps[0]["request_id"])
        assert model.sequence < client.sequence


def test_missing_approval_policy_fails_closed(tmp_path):
    from kognita.models import Policy
    path = tmp_path / "old-trade.db"
    agent = WealthAgent(path)
    with Session(agent.engine) as session:
        policy = session.exec(select(Policy).where(Policy.regime == "TRADE_PROPOSAL")).one()
        session.delete(policy)
        session.commit()
    with pytest.raises(ValueError, match="lacks required mandate or policies"):
        WealthAgent(path)


def test_approved_unsuitable_product_cannot_create_proposal(tmp_path):
    from kognita import Run, continue_run
    agent = WealthAgent(tmp_path / "unsuitable.db")
    with Session(agent.engine) as session:
        run = Run()
        held = agent.call(session, "propose_trade", run=run, arguments={"product_id": "INS-HK-NOTE"})
        assert held.outcome.value == "HUMAN_APPROVAL"
        approval = session.exec(select(Approval).where(Approval.decision_id == held.evaluation.decision_id)).one()
        session.commit()
        result = continue_run(session, run.id, {approval.id: True}, evidence=agent.writer,
                              registry=agent.registry, approver_name="risk.officer@eastwind.example")
        assert json.loads(result.data)["denied"] is True
        assert not agent.proposals
        session.commit()
