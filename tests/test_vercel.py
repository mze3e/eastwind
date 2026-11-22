"""Serverless public demo: synthetic state, offline actions, and routing."""
from __future__ import annotations

import html
import importlib.util
import json
import re
import shutil
import socket
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from kognita import verify_chain
from sqlmodel import Session


def load_entrypoint():
    path = Path(__file__).resolve().parents[1] / 'api' / 'index.py'
    spec = importlib.util.spec_from_file_location('eastwind_vercel_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def result_json(response):
    assert response.status_code == 200, response.text
    return json.loads(html.unescape(re.search(r'<pre>(.*?)</pre>', response.text, re.S).group(1)))


def test_entrypoint_requires_explicit_public_mode(monkeypatch):
    monkeypatch.delenv('EASTWIND_PUBLIC_DEMO', raising=False)
    with pytest.raises(RuntimeError, match='requires EASTWIND_PUBLIC_DEMO'):
        load_entrypoint()


def test_public_function_cold_start_actions_and_local_only(monkeypatch):
    monkeypatch.setenv('EASTWIND_PUBLIC_DEMO', '1')
    monkeypatch.setenv('EASTWIND_LLM_PROVIDER', 'openai')
    module = load_entrypoint()
    root = module.app.state.demo_root
    assert root.is_relative_to('/tmp')
    assert (root / 'admin.db').is_file()
    assert module.os.environ['EASTWIND_LLM_PROVIDER'] == 'mock'
    try:
        with TestClient(module.app) as client:
            def refused(*args, **kwargs):
                raise AssertionError('Public demo attempted a network connection or subprocess')

            monkeypatch.setattr(socket.socket, 'connect', refused)
            monkeypatch.setattr(socket, 'create_connection', refused)
            monkeypatch.setattr(subprocess, 'Popen', refused)
            page = client.get('/admin/')
            assert page.status_code == 200
            assert 'synthetic' in page.text and 'ephemeral' in page.text
            assert 'in-process mock' in page.text and 'shared' in page.text
            assert 'href="/admin/workflows"' in page.text
            assert "form-action 'self'" in page.headers['content-security-policy']
            assert "connect-src 'self'" in page.headers['content-security-policy']
            assert 'name="token"' not in client.get('/admin/workflows').text
            assert client.get('/api/index?__ew_path=policies&role=visitor').status_code == 200
            assert 'denied' in client.get('/api/index?__ew_path=policies&role=visitor').text
            assert client.get('/api/index?__ew_path=../evidence').status_code == 400
            for name in ('mcp', 'degraded'):
                assert client.post('/admin/workflows', data={'workflow': name}).status_code == 400
            assert client.post('/admin/workflows', data={'workflow': 'research', 'llm': 'openai'}).status_code == 400
            assert client.post('/admin/workflows', content='x=' + 'a' * 17000,
                               headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
            assert client.get('/admin/policies?' + 'x=' + 'a' * 5000).status_code == 414
            form = {'workflow': 'rebalance', 'role': 'agent', 'max_calls': '4'}
            held = result_json(client.post('/api/index?__ew_path=workflows', data=form))
            assert held['suspended'] is True
            assert str(held['approval_id']) in client.get('/admin/approvals').text
            approved = client.post('/admin/approvals/resolve', data={'run': held['run_id'],
                'approval': str(held['approval_id']), 'resolution': 'approve'})
            assert result_json(approved)['executed'] is True
            held2 = result_json(client.post('/admin/workflows', data=form))
            assert client.post('/admin/kill-switch', data={'state': 'engage'}).status_code == 200
            stopped = client.post('/admin/approvals/resolve', data={'run': held2['run_id'],
                'approval': str(held2['approval_id']), 'resolution': 'approve'})
            assert result_json(stopped)['executed'] is False
            assert client.post('/admin/kill-switch', data={'state': 'release'}).status_code == 200
            assert result_json(client.post('/admin/workflows', data={'workflow': 'client-review'}))['facts']['retrieved']
            assert result_json(client.post('/admin/workflows', data={'workflow': 'research'}))['facts']['retrieved']
            assert result_json(client.post('/admin/workflows', data={'workflow': 'egress'}))['facts']['blocked']
            assert result_json(client.post('/admin/workflows', data={'workflow': 'suitability'}))['facts']['suitability']['suitable']
            assert result_json(client.post('/admin/workflows', data={'workflow': 'budget'}))['facts']['budget_citations']
            assert result_json(client.post('/admin/workflows', data={'workflow': 'kill-switch'}))['facts']['retrieved'] == []
            assert result_json(client.post('/admin/workflows', data={'workflow': 'replay'}))['facts']['outcome'] == 'ALLOW'
            assert 'Conforms: True' in client.post('/admin/pwm/validate', data={'source': 'demo'}).text
            evidence = client.get('/admin/evidence')
            assert 'Chain verified' in evidence.text and 'npx --yes @kognita/verify@0.9.0' in evidence.text
            assert 'failed Python verification' in client.post('/admin/evidence/tamper', data={'actor_id': 'edited'}).text
            with Session(module.admin.state.engine) as session:
                assert verify_chain(session) > 0
    finally:
        module.admin.state.engine.dispose()
        shutil.rmtree(root)


def test_rewrite_config_and_independent_cold_starts(monkeypatch):
    monkeypatch.setenv('EASTWIND_PUBLIC_DEMO', '1')
    monkeypatch.setenv('EASTWIND_LLM_PROVIDER', 'mock')
    first, second = load_entrypoint(), load_entrypoint()
    try:
        assert first.root != second.root
        with TestClient(first.app) as one, TestClient(second.app) as two:
            held = result_json(one.post('/admin/workflows', data={'workflow': 'rebalance'}))
            assert held['run_id'] in one.get('/admin/approvals').text
            assert held['run_id'] not in two.get('/admin/approvals').text
        config = json.loads((Path(__file__).resolve().parents[1] / 'vercel.json').read_text())
        assert config['env']['EASTWIND_PUBLIC_DEMO'] == '1'
        assert any(item['source'] == '/admin/:path*' for item in config['rewrites'])
        assert any(item['source'] == '/admin/' for item in config['rewrites'])
        strict = next(item for item in config['headers'] if item['source'] == '/')
        assert "form-action 'none'" in strict['headers'][0]['value']
    finally:
        first.admin.state.engine.dispose()
        second.admin.state.engine.dispose()
        shutil.rmtree(first.root)
        shutil.rmtree(second.root)
