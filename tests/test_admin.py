"""Offline tests of the local administration UI and real continuations."""
import html
import json
import re

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from eastwind.admin import create_app
from eastwind.cli import main
from kognita import verify_chain
from kognita.models import Approval, GovernanceDecision, RunRecord

TOKEN = 'local-test-token'


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, TOKEN)
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


def post(client, path, **values):
    return client.post(path, data={'token': TOKEN, **values})


def run(client, name, **values):
    result = post(client, '/workflows', workflow=name, role=values.get('role', 'agent'),
                  max_calls=str(values.get('max_calls', 4)))
    assert result.status_code == 200, result.text
    return json.loads(html.unescape(re.search(r'<pre>(.*?)</pre>', result.text, re.S).group(1)))


def resolve(client, held, decision):
    return post(client, '/approvals/resolve', run=held['run_id'],
                approval=str(held['approval_id']), resolution=decision)


def test_pages_roles_and_tour(client):
    for url in ['/', '/agents', '/policies', '/approvals', '/kill-switch', '/budgets', '/evidence',
                '/replay', '/reconstruction', '/pwm', '/workflows', '/tour']:
        response = client.get(url)
        assert response.status_code == 200, url
        assert TOKEN not in response.text
    agent = client.get('/policies?role=agent').text
    manager = client.get('/policies?role=relationship_manager').text
    assert '<td>email</td><td>masked</td>' in agent
    assert '<td>email</td><td>visible</td>' in manager
    assert '<td>tax_identifier</td><td>denied</td>' in agent
    assert 'account_holdings' in agent and 'lineage' in agent.lower()
    assert client.get('/policies?role=unknown').status_code == 400
    tour = client.get('/tour').text
    for section in ['Permitted context', 'mandated action', 'provable record', '/policies', '/approvals', '/evidence']:
        assert section in tour


def test_actions_require_token_and_do_not_modify_state(client):
    paths = ['/workflows', '/approvals/resolve', '/approvals/grant', '/kill-switch', '/evidence/tamper',
             '/replay', '/reconstruction', '/pwm/validate']
    with Session(client.app.state.engine) as session:
        before = verify_chain(session)
    for path in paths:
        response = client.post(path, data={'token': 'incorrect'})
        assert response.status_code == 403, path
        assert TOKEN not in response.text
    with Session(client.app.state.engine) as session:
        assert verify_chain(session) == before
        assert not session.exec(select(RunRecord)).all()
    assert client.post('/kill-switch', content=f'token={TOKEN}&token=wrong',
                       headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 400


def test_approval_grant_deny_and_stop_at_release(client):
    held = run(client, 'rebalance')
    assert held['outcome'] == 'HUMAN_APPROVAL' and held['suspended']
    assert str(held['approval_id']) in client.get('/approvals').text
    denied = resolve(client, held, 'deny')
    assert denied.status_code == 200 and '&quot;executed&quot;: false' in denied.text
    second = run(client, 'rebalance')
    approved = resolve(client, second, 'approve')
    assert approved.status_code == 200 and '&quot;executed&quot;: true' in approved.text
    assert resolve(client, second, 'approve').status_code == 404
    third = run(client, 'rebalance')
    staged = post(client, '/approvals/grant', run=third['run_id'], approval=str(third['approval_id']))
    assert staged.status_code == 200
    with Session(client.app.state.engine) as session:
        assert session.get(Approval, third['approval_id']).status.value == 'APPROVED'
    assert post(client, '/kill-switch', state='engage').status_code == 200
    stopped = resolve(client, third, 'approve')
    assert stopped.status_code == 200 and '&quot;executed&quot;: false' in stopped.text
    assert post(client, '/kill-switch', state='release').status_code == 200
    with Session(client.app.state.engine) as session:
        assert verify_chain(session) > 0
        assert session.get(Approval, held['approval_id']).status.value == 'REJECTED'


def test_workflows_budgets_evidence_replay_and_reconstruction(client):
    result = run(client, 'client-review', max_calls=2)
    assert any(step['outcome'] == 'DENY' for step in result['steps'])
    assert '2' in client.get('/budgets').text
    result = run(client, 'client-review')
    assert result['facts']['retrieved'] == ['client_profile', 'account_holdings']
    with Session(client.app.state.engine) as session:
        decision = session.exec(select(GovernanceDecision).where(GovernanceDecision.tool == 'client_profile')
                                .order_by(GovernanceDecision.id.desc())).first()
        request_id, interaction_id = decision.request_id, result['facts']['interaction_id']
    assert 'ALLOW' in post(client, '/replay', request_id=request_id).text
    assert 'Reconstruction report' in post(client, '/reconstruction', interaction_id=interaction_id).text
    assert 'Chain verified' in client.get('/evidence').text
    assert 'payload_hash' in client.get('/evidence/event?sequence=1').text
    assert client.get('/evidence/event?sequence=999999').status_code == 404
    assert client.get('/evidence/export').json()['event_count'] > 0
    assert 'failed Python verification' in post(client, '/evidence/tamper').text
    assert 'Chain verified' in client.get('/evidence').text
    assert run(client, 'research')['facts']['retrieved'] == ['house_view']
    assert run(client, 'suitability')['facts']['suitability']['suitable'] is True


def test_other_workflows_and_denied_retrieval(client):
    visitor = run(client, 'client-review', role='visitor')
    assert visitor['facts']['retrieved'] == []
    assert run(client, 'budget')['facts']['budget_citations']
    assert run(client, 'egress')['facts']['blocked'] is True
    assert run(client, 'kill-switch')['facts']['retrieved'] == []
    assert 'Current state: off' in client.get('/kill-switch').text
    assert run(client, 'mcp')['facts']['backend_calls']
    assert run(client, 'degraded')['facts']['fail_closed_forwarded'] == 0
    run(client, 'client-review')
    assert run(client, 'replay')['facts']['outcome'] == 'ALLOW'


def test_pwm_export_validate(client):
    response = client.get('/pwm/export')
    assert response.status_code == 200 and 'AIAgent' in response.text
    response = post(client, '/pwm/validate')
    assert response.status_code == 200 and 'Conforms: True' in response.text
    assert 'AIAgent' in client.get('/pwm/export?source=admin').text
    assert 'Conforms: False' in post(client, '/pwm/validate', source='admin').text


def test_suspended_run_survives_restart(tmp_path):
    with TestClient(create_app(tmp_path, TOKEN)) as first:
        held = run(first, 'rebalance')
    with TestClient(create_app(tmp_path, TOKEN)) as second:
        assert held['run_id'] in second.get('/approvals').text
        response = resolve(second, held, 'approve')
        assert response.status_code == 200 and '&quot;executed&quot;: true' in response.text


def test_cli_binds_locally_and_token_configuration(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr('uvicorn.run', lambda app, **kwargs: calls.append(kwargs))
    monkeypatch.delenv('EASTWIND_ADMIN_TOKEN', raising=False)
    assert main(['admin', '--db', str(tmp_path / 'generated')]) == 0
    assert 'Generated local admin token:' in capsys.readouterr().out
    assert calls[-1]['host'] == '127.0.0.1' and calls[-1]['port'] == 8090
    monkeypatch.setenv('EASTWIND_ADMIN_TOKEN', TOKEN)
    assert main(['admin', '--db', str(tmp_path / 'configured')]) == 0
    assert TOKEN not in capsys.readouterr().out
    assert main(['admin', '--host', '0.0.0.0', '--db', str(tmp_path / 'refused')]) == 1
    assert not (tmp_path / 'refused').exists()
