"""Offline coverage for the kognita 0.4 showcase scenarios. No API key, no network."""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import pytest

from eastwind.showcase import SCENARIO_ORDER, V04_SCENARIOS, run_named


def _run(name: str, tmp_path: Path) -> dict:
    result = run_named(name, tmp_path)
    assert result.facts, result.text()
    return result.facts


def test_every_0_4_scenario_is_in_the_tour():
    assert V04_SCENARIOS == (
        "register",
        "policy",
        "ingest",
        "contact",
        "communicate",
        "outcomes",
        "breaker",
        "packs",
        "recorder",
        "adapters",
    )
    assert set(V04_SCENARIOS) <= set(SCENARIO_ORDER)


def test_register_empty_denies_and_live_cites_the_owner(tmp_path: Path):
    facts = _run("register", tmp_path)
    assert facts["empty_outcome"] == "DENY"
    assert "USE_CASE_REGISTERED" in facts["empty_citation"]
    assert facts["empty_ran"] is False
    assert facts["registered"] == ["ELIGIBILITY_CHECK"]
    assert facts["allow_outcome"] == "ALLOW"
    assert "accountable owner: Head of Conduct" in facts["allow_citation"]
    assert facts["suspended_outcome"] == "DENY"
    assert "suspended" in facts["suspended_citation"]


def test_policy_language_validates_tests_diffs_explains_and_refuses_uncited(tmp_path: Path):
    facts = _run("policy", tmp_path)
    assert facts["strict_ok"] is True
    assert facts["draft_refused"] is True
    assert facts["scenarios_ok"] is True
    assert facts["diff_modified"] is True
    assert facts["explain_cites"] is True
    assert facts["load_ok"] is True
    assert facts["uncited_load_refused"] is True


def test_ingest_classifies_per_section_or_skips_without_docling(tmp_path: Path):
    facts = _run("ingest", tmp_path)
    if importlib.util.find_spec("docling") is None:
        assert facts["skipped"] == "docling extra not installed"
        return
    assert facts["empty_zones_refused"] is True
    labels = dict(facts["items"])
    assert labels["SGD money market"] == "C1"
    assert labels["Booking centre"] == "C1"
    assert labels["Steering group"] == "C3"


def test_do_not_contact_holds_until_a_cited_reversal(tmp_path: Path):
    facts = _run("contact", tmp_path)
    assert facts["origination_outcome"] == "do not contact"
    assert facts["reoriginate_refused"] is True
    assert facts["later_contact_outcome"] == "DENY"
    assert facts["later_contact_sent"] is False
    assert "do not contact" in facts["later_contact_citation"]
    assert facts["after_reversal_outcome"] == "ALLOW"
    assert facts["after_reversal_sent"] is True
    assert facts["reconstruct_questions"] == 10


def test_communication_needs_a_channel_a_decision_and_clean_content(tmp_path: Path):
    facts = _run("communicate", tmp_path)
    assert facts["personal_refused"] is True
    assert facts["undecided_outcome"] == "DENY"
    assert facts["unregistered_outcome"] == "DENY"
    assert facts["claim_outcome"] == "DENY"
    assert facts["sent_outcome"] == "ALLOW"
    assert facts["interventions"] == ["pause", "override", "recover"]
    assert facts["complaint_kind"] == "client complaint"
    assert facts["complaint_model_version"] == "gpt-4o-mini"


def test_outcomes_near_misses_review_and_metrics(tmp_path: Path):
    facts = _run("outcomes", tmp_path)
    assert facts["bad_kind_refused"] is True
    assert facts["near_misses"]["verifier block"] == 1
    assert facts["near_misses"]["blocked action"] >= 1
    assert facts["finding"] == "confirmed problem"
    assert facts["metrics"]["reliability"] == "not measured"
    assert facts["coverage_reviewed"] == 1.0


def test_breaker_drill_revocation_and_affected_clients(tmp_path: Path):
    facts = _run("breaker", tmp_path)
    assert facts["undrilled_outcome"] == "DENY"
    assert "no drill scheduled" in facts["undrilled_citation"]
    assert facts["drilled_outcome"] == "ALLOW"
    assert facts["breaker_outcome"] == "DENY"
    assert "CIRCUIT_BREAKER" in facts["breaker_citation"]
    assert facts["reset_outcome"] == "ALLOW"
    assert facts["provider_revoked_status"] == 403
    assert facts["provider_revoked_forwarded"] == 0
    assert facts["reinstated_status"] == 200
    assert facts["reinstated_forwarded"] == 1
    assert facts["kill_switch_release_refused"] is True
    assert facts["agent_revoked_outcome"] == "DENY"
    assert facts["affected_clients"] == ["CL-1001"]


def test_packs_list_load_and_a_pinned_update(tmp_path: Path):
    facts = _run("packs", tmp_path)
    assert "private-banking" in facts["packs"]
    assert "two-signature-approval-chains" in facts["packs"]
    assert all(" " not in name for name in facts["packs"])
    assert facts["load_ok"] is True
    assert facts["tampered_refused"] is True
    assert facts["pinned_installed"] is True
    assert "PACK_UPDATE_REFUSED" in facts["policy_change_actions"]


def test_recorder_lists_shows_exports_and_alerts(tmp_path: Path):
    facts = _run("recorder", tmp_path)
    assert facts["runs_listed"] == 4
    assert facts["show_outcome"] == "DENY"
    assert facts["show_failing_citations"] >= 1
    assert facts["export_written"] is True
    assert "repeated denials" in facts["alerts_fired"]
    assert facts["otel"] in {"attached", "refused"}


def test_adapters_refuse_through_the_shared_binding(tmp_path: Path):
    facts = _run("adapters", tmp_path)
    assert facts["allowed"] == "eligibility answered for CL-1001"
    assert facts["refused"] is True
    assert facts["hermes_directive"] == "block"
    assert set(facts["skipped"]) | set(facts["installed"]) == {
        "hermes-agent",
        "openai-agents",
        "langgraph",
        "pydantic-ai",
    }


@pytest.mark.parametrize("name", V04_SCENARIOS)
def test_each_scenario_runs_twice_and_quickly(name: str, tmp_path: Path):
    run_named(name, tmp_path)
    started = time.perf_counter()
    run_named(name, tmp_path)
    assert time.perf_counter() - started < 15
