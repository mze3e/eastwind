"""Offline coverage of the real 0.5.1 APIs and localhost gateway."""
from pathlib import Path
import time

import pytest
from sqlmodel import Session, select

from kognita import make_engine
from kognita.canonical import hash_text
from kognita.models import EvidenceEvent

from eastwind.showcase import PLAIN_EMAIL, SCENARIO_ORDER, V04_SCENARIOS, V05_SCENARIOS, run_named


def _run(name: str, tmp_path: Path) -> dict:
    result = run_named(name, tmp_path)
    assert result.facts, result.text()
    assert result.facts['allow_outcome'] == 'ALLOW', result.text()
    assert result.facts['deny_outcome'] == 'DENY', result.text()
    assert result.facts['chain_length'] > 0
    assert 'cite' in result.text()
    return result.facts


def _failed(facts: dict, label: str, rule: str) -> None:
    assert any(c['check'] == rule and c['result'] == 'fail' and c['citation']
               for c in facts[label + '_checks'])


def test_every_05_scenario_is_registered_once():
    assert V05_SCENARIOS == ('autonomy', 'credentials', 'authority', 'blastradius', 'anomaly',
                             'taint', 'triggers', 'providerkey', 'proposal', 'recovery')
    assert len(set(SCENARIO_ORDER)) == len(SCENARIO_ORDER)
    assert set(V05_SCENARIOS) <= set(SCENARIO_ORDER)
    assert set(V04_SCENARIOS).isdisjoint(V05_SCENARIOS)


def test_autonomy_needs_reviewed_identity_and_earned_promotion(tmp_path: Path):
    facts = _run('autonomy', tmp_path)
    assert {c['check'] for c in facts['allow_checks']} == {'S1-IDENTITY', 'S1-DEPLOYMENT', 'S1-LEVEL'}
    assert all(c['result'] == 'pass' for c in facts['allow_checks'])
    _failed(facts, 'deny', 'S1-LEVEL')
    assert 'S1-PROMOTION' in facts['promotion_refused']


def test_credentials_are_live_and_child_budgets_are_reserved(tmp_path: Path):
    facts = _run('credentials', tmp_path)
    assert facts['verified'] is True
    assert facts['revoked_verified'] is False
    assert facts['delegated_outcome'] == 'ALLOW'
    assert facts['parent_calls_reserved'] == 8
    _failed(facts, 'missing', 'S2-CREDENTIAL')
    _failed(facts, 'deny', 'S2-CREDENTIAL')
    assert any(c['check'] == 'S6B-RUN-ISOLATION' and c['result'] == 'pass'
               for c in facts['delegated_checks'])


def test_authority_cannot_widen_or_survive_revocation(tmp_path: Path):
    facts = _run('authority', tmp_path)
    assert 'S3-ATTENUATION' in facts['widening_refused']
    assert any(c['check'] == 'S3-HUMAN-ENTITLEMENT' and c['result'] == 'pass'
               for c in facts['allow_checks'])
    _failed(facts, 'deny', 'S3-DELEGATION')


def test_blast_radius_has_independent_daily_and_product_limits(tmp_path: Path):
    facts = _run('blastradius', tmp_path)
    assert all(c['result'] == 'pass' for c in facts['allow_checks'])
    _failed(facts, 'deny', 'S4-DAILY-ACTIONS')
    _failed(facts, 'product', 'S4-PRODUCTS')
    _failed(facts, 'transaction', 'S4-DAILY-TRANSACTIONS')
    _failed(facts, 'transaction', 'S4-EXECUTION-AUTHORITY')


def test_anomaly_contains_and_revokes_the_workload(tmp_path: Path):
    facts = _run('anomaly', tmp_path)
    _failed(facts, 'deny', 'S6-PRIVILEGE-PROBING')
    _failed(facts, 'stopped', 'KILL_SWITCH')
    _failed(facts, 'stopped', 'S6-QUARANTINE')
    assert facts['kill_switch'] is True
    assert facts['credential_live'] is False
    assert {'ANOMALY_QUARANTINED', 'ANOMALY_TOOLS_STOPPED', 'ANOMALY_ALERT'} <= set(facts['containment_actions'])


def test_client_data_cannot_be_published_by_rotating_runs(tmp_path: Path):
    facts = _run('taint', tmp_path)
    assert facts['client_data'] and facts['rotated_client_data']
    assert facts['taint_citations'] == ['S5-TAINT']
    _failed(facts, 'deny', 'S5-PUBLIC-CONTENT')
    _failed(facts, 'rotated', 'S5-PUBLIC-CONTENT')


def test_system_trigger_is_listed_and_evidenced_as_system(tmp_path: Path):
    facts = _run('triggers', tmp_path)
    assert facts['forwarded'] == 1
    assert facts['actor'] == 'SYSTEM'
    assert facts['trigger_recorded'] is True
    _failed(facts, 'deny', 'SYSTEM_TRIGGER')
    assert 'S2-SYSTEM-TRIGGER' in facts['deny_checks'][0]['citation']


def test_provider_key_is_gateway_held_and_never_retained(tmp_path: Path):
    facts = _run('providerkey', tmp_path)
    assert facts['allow_status'] == 200
    assert facts['deny_status'] == 403
    assert facts['forwarded'] == 4
    assert facts['inference_statuses'] == {path: 200 for path in (
        '/v1/chat/completions', '/v1/completions', '/v1/responses', '/v1/embeddings')}
    assert facts['provider_key_received'] is True
    assert facts['secrets_absent'] is True
    assert facts['allowlisted_response'] is True
    _failed(facts, 'deny', 'S2-PROVIDER-KEY')
    _failed(facts, 'endpoint', 'S5-MODEL-ENDPOINT')
    _failed(facts, 'attachment', 'S5-UNSUPPORTED-CONTENT')
    assert facts['endpoint_status'] == facts['attachment_status'] == 403


def test_proposal_holds_then_applies_the_exact_diff_once(tmp_path: Path):
    facts = _run('proposal', tmp_path)
    assert facts['held_outcome'] == 'HUMAN_APPROVAL'
    assert facts['held_unchanged'] is True
    assert 'PROPOSAL-APPROVAL' in facts['pending_refused']
    assert facts['applied_title'].endswith('(reviewed)')
    assert 'PROPOSAL-BINDING' in facts['reapply_refused']


def test_recovery_retries_only_unfinished_compensations(tmp_path: Path):
    facts = _run('recovery', tmp_path)
    assert facts['failed_state'] == 'paused'
    assert facts['first_steps'] == [('historical_eligibility', 'completed'),
                                   ('house_view', 'failed'), ('check_eligibility', 'completed')]
    assert facts['recovered_state'] == 'recovered'
    assert facts['retry_steps'] == ['already_completed', 'completed', 'already_completed']
    assert facts['attempts'] == ['historical_eligibility', 'house_view', 'check_eligibility', 'house_view']
    assert facts['remaining_effects'] == []
    _failed(facts, 'deny', 'PAUSE')


def test_classifier_hash_includes_argument_keys(tmp_path: Path):
    run_named('classify', tmp_path)
    with Session(make_engine(tmp_path / 'classify.db')) as session:
        events = session.exec(select(EvidenceEvent)).all()
        tool = next(e.payload for e in events if e.payload.get('envelope', {}).get('tool') == 'classify_tool'
                    and e.payload.get('outcome') == 'ALLOW')
        digest = tool['attributes']['classifier']['input_hash']
        assert digest == hash_text('note\n' + PLAIN_EMAIL)
        assert digest != hash_text(PLAIN_EMAIL)


@pytest.mark.parametrize('name', V05_SCENARIOS)
def test_each_scenario_runs_twice_and_quickly(name: str, tmp_path: Path):
    _run(name, tmp_path)
    start = time.perf_counter()
    _run(name, tmp_path)
    assert time.perf_counter() - start < 15
