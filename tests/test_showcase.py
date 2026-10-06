"""Offline coverage for every eastwind showcase scenario. No API key, no network."""

from __future__ import annotations

from pathlib import Path

from eastwind.cli import main
from eastwind.showcase import SCENARIO_ORDER, run_named


def _run(name: str, tmp_path: Path) -> dict:
    result = run_named(name, tmp_path)
    assert result.facts, result.text()
    return result.facts


def test_authorise_fails_closed_and_stops_the_agent(tmp_path: Path):
    facts = _run("authorise", tmp_path)
    assert facts["precedence"] == ("DENY", "ESCALATE", "HUMAN_APPROVAL", "ALLOW")
    assert facts["deny_outcome"] == "DENY"
    assert facts["deny_retrieval"] is False
    assert facts["deny_events"] == ["POLICY_DECISION"]
    assert "HK_SFC" in facts["deny_citations"]
    assert "DIFC_DFSA" in facts["deny_citations"]
    assert facts["allow_outcome"] == "ALLOW"
    assert facts["allow_retrieval"] is True
    assert "House view — SGD money market eligibility" in facts["allow_titles"]
    assert facts["unzoned_hidden"] is True
    assert facts["c3_hidden"] is True
    assert facts["purpose_missing_outcome"] == "DENY"
    assert facts["unregistered_outcome"] == "DENY"
    assert "not registered" in facts["unregistered_citation"]
    assert facts["kill_switch_outcome"] == "DENY"
    assert "Kill switch" in facts["kill_switch_citation"]


def test_egress_allows_redacts_and_blocks(tmp_path: Path):
    facts = _run("egress", tmp_path)
    assert facts["allow_decision"] == "ALLOW"
    assert facts["redact_decision"] == "REDACT"
    assert facts["redact_sent_hides_email"] is True
    assert facts["redact_sent_hides_account"] is True
    assert facts["redact_sent_hides_name"] is True
    assert facts["redact_restored_email"] is True
    assert facts["redact_restored_name"] is True
    assert facts["local_decision"] == "ALLOW"
    assert facts["local_saw_email"] is True
    assert facts["block_raised"] is True
    assert facts["block_not_called"] is True
    assert facts["call_count"] == 3


def test_classify_does_not_let_text_widen_a_decision(tmp_path: Path):
    facts = _run("classify", tmp_path)
    assert facts["ask_vague_outcome"] == "ESCALATE"
    assert facts["ask_vague_results"] == 0
    assert facts["ask_vague_confidence"] < 0.8
    assert facts["ask_clear_outcome"] == "ALLOW"
    assert facts["ask_clear_label"] == "C2"
    assert facts["ask_clear_confidence"] >= 0.8
    assert facts["plain_outcome"] == "DENY"
    assert facts["plain_label"] == "C2"
    assert facts["injection_outcome"] == "DENY"
    assert facts["injection_label"] == "C2"
    assert facts["injection_principal"] == "rm.sg@eastwind.example"
    assert facts["claimed_label"] == "C1"
    assert facts["governed_clear_executed"] is True
    assert facts["governed_clear_label"] == "C2"
    assert facts["governed_vague_outcome"] == "ESCALATE"
    assert facts["governed_vague_executed"] is False
    assert facts["typed_executed"] is True
    assert facts["typed_label"] == "C0"
    assert facts["typed_classifier_absent"] is True
    assert facts["tools_ran"] == ["classify_tool", "typed_classification"]


def test_budget_cites_each_exceeded_cap(tmp_path: Path):
    facts = _run("budget", tmp_path)
    assert facts["first_outcome"] == "ALLOW"
    assert facts["first_executed"] is True
    assert facts["max_calls"] == "max_calls"
    assert facts["max_calls_executed"] is False
    assert facts["wall_clock_seconds"] == "wall_clock_seconds"
    assert facts["wall_executed"] is False
    assert facts["classification_ceiling"] == "classification_ceiling"
    assert facts["ceiling_executed"] is False
    assert facts["max_cost_usd"] == "max_cost_usd"
    assert facts["cost_executed"] is False
    assert facts["ran"] == 1


def test_approval_holds_resumes_and_requires_two_signatures(tmp_path: Path):
    facts = _run("approval", tmp_path)
    assert facts["held"] is True
    assert facts["checkpoint"] is True
    assert facts["denied_executed"] is False
    assert facts["granted_executed"] is True
    assert facts["confirmation_required"] is True
    assert facts["marked_status"] == "MARKED"
    assert facts["marked_executed"] is False
    assert facts["confirmed_status"] == "APPROVED"
    assert facts["confirmed_executed"] is True
    assert facts["ran"] == ["draft_client_letter", "release_structured_note"]


def test_replay_pins_erasure_and_reconstruct(tmp_path: Path):
    facts = _run("replay", tmp_path)
    assert facts["replay_outcome"] == "ALLOW"
    assert facts["erasure_replay_outcome"] == "ALLOW"
    assert facts["supersede_replay_outcome"] == "ALLOW"
    assert facts["successor_id"]
    assert facts["report_json"] is True
    assert facts["report_txt"] is True
    assert facts["report_interaction"]
    assert facts["report_questions"] >= 10
    assert "retrieved item" in facts["item_mismatch"]
    assert "does not match its hash" in facts["retained_mismatch"]
    assert "in-place" in facts["policy_edit_refused"]
    assert "edited in place" in facts["policy_mismatch"]


def test_effective_date_replays_march(tmp_path: Path):
    facts = _run("effective", tmp_path)
    assert facts["march_outcome"] == "DENY"
    assert facts["march_after_outcome"] == "DENY"
    assert facts["october_outcome"] == "ALLOW"
    assert facts["replay_outcome"] == "DENY"
    assert facts["successor_id"]


def test_gateway_stand_in_identity_and_failure_modes(tmp_path: Path):
    facts = _run("gateway", tmp_path)
    assert "kognita serve" in facts["serve_command"]
    assert facts["base_url"].endswith("/v1")
    assert facts["upstream_calls"] == 1
    assert facts["upstream_hid_email"] is True
    assert facts["upstream_hid_account"] is True
    assert facts["caller_saw_email"] is True
    assert facts["caller_saw_account"] is True
    assert facts["missing_agent_status"] == 403
    assert facts["missing_agent_outcome"] == "DENY"
    assert facts["unlisted_agent_status"] == 403
    assert facts["unlisted_agent_outcome"] == "DENY"
    assert facts["fail_closed_status"] == 503
    assert facts["fail_closed_forwarded"] == 0
    assert facts["degraded_local_status"] == 200
    assert facts["degraded_local_forwarded"] == 1
    assert facts["degraded_recovered"] is True
    assert facts["degraded_chain"] is True
    assert facts["degraded_remote_forwarded"] == 0
    assert facts["degraded_remote_outcome"] == "DENY"
    assert facts["degraded_c2_forwarded"] == 0
    assert facts["degraded_c2_outcome"] == "DENY"
    assert facts["degraded_c2_label"] == "C2"
    assert facts["system_trigger_outcome"] == "ALLOW"
    assert facts["system_trigger_forwarded"] == 1
    assert facts["system_trigger_actor"] == "SYSTEM"


def test_mcp_forwards_only_a_released_call(tmp_path: Path):
    facts = _run("mcp", tmp_path)
    assert facts["allowed_status"] == 200
    assert "house_view" in facts["allowed_text"]
    assert facts["deny_status"] == 403
    assert facts["deny_outcome"] == "DENY"
    assert facts["escalate_status"] == 403
    assert facts["escalate_outcome"] == "ESCALATE"
    assert facts["approval_status"] == 403
    assert facts["approval_outcome"] == "HUMAN_APPROVAL"
    assert facts["backend_calls"] == ["house_view"]


def test_conformance_kit_passes_on_the_eastwind_pack(tmp_path: Path):
    facts = _run("conformance", tmp_path)
    assert facts["count"] >= 10
    assert "test_unregistered_agent_is_denied" in facts["passed"]
    assert "test_human_approval_opens_a_bound_approval" in facts["passed"]
    assert "test_outcome_precedence_is_fail_closed" in facts["passed"]


def test_cli_all_runs_every_scenario(tmp_path: Path, capsys):
    code = main(["showcase", "all", "--db", str(tmp_path / "tour")])
    captured = capsys.readouterr()
    assert code == 0, captured.err
    for name in SCENARIO_ORDER:
        assert f"Scenario  {name}" in captured.out
