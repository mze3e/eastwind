import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

from eastwind.llm import GatewayClient, MockClient, Settings
from eastwind.llm.server import MockHandler


def test_mock_plans_are_deterministic_and_distinct():
    mock = MockClient()
    assert mock.plan("client-review") == mock.plan("client-review")
    assert [call.name for call in mock.plan("rebalance")][-1] == "propose_trade"
    with pytest.raises(ValueError):
        mock.plan("unknown")


def test_mock_http_returns_openai_tool_calls():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"model": "demo", "messages": [], "workflow": "research"}).encode()
        request = Request(f"http://127.0.0.1:{server.server_port}/v1/chat/completions", data=body)
        with urlopen(request) as response:
            result = json.load(response)
        assert result["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "approved_sources"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_provider_fails_closed_without_gateway_or_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="gateway"):
        GatewayClient(Settings("openai", "model", "", "OPENAI_API_KEY"), {"agent_name": "agent"})
    with pytest.raises(ValueError, match="key"):
        GatewayClient(Settings("openai", "model", "http://127.0.0.1:8092", "OPENAI_API_KEY"), {"agent_name": "agent"})
    with pytest.raises(ValueError, match="gateway"):
        GatewayClient(Settings("ollama", "model", "https://example.com", ""), {"agent_name": "agent"})


@pytest.mark.parametrize("provider,key_name", [
    ("openai", "OPENAI_API_KEY"), ("xai", "XAI_API_KEY"),
    ("openai-compatible", "EASTWIND_LLM_API_KEY"), ("ollama", ""),
    ("anthropic", "ANTHROPIC_API_KEY"),
])
def test_presets_send_only_to_configured_gateway(provider, key_name, monkeypatch):
    if key_name:
        monkeypatch.setenv(key_name, "test-only-key")
    observed = []

    class Handler(MockHandler):
        def do_GET(self):
            body = b'{"error":"the gateway only proxies model calls"}'
            self.send_response(405)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            observed.append(dict(self.headers))
            super().do_POST()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        settings = Settings(provider, "test-model", f"http://127.0.0.1:{server.server_port}", key_name)
        response = GatewayClient(settings, {"agent_name": "test"}).complete(
            [{"role": "user", "content": "hello"}])
        assert response["model"] == "test-model"
        assert not any(key.lower() in {"authorization", "x-api-key"} for key in observed[0])
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_gateway_client_refuses_provider_credentials_and_paths(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    with pytest.raises(ValueError, match="credentials"):
        GatewayClient(Settings("openai", "model", "http://127.0.0.1:1", "OPENAI_API_KEY"),
                      {"Authorization": "Bearer test-only-key"})
    with pytest.raises(ValueError, match="origin"):
        Settings("openai", "model", "http://127.0.0.1:1/v1", "OPENAI_API_KEY").validate()


def test_anthropic_native_translation_and_bridge_authentication():
    from types import SimpleNamespace
    from urllib.error import HTTPError
    from eastwind.llm.anthropic import AnthropicAdapter
    from eastwind.llm.bridge import BridgeServer

    calls = []
    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(id="msg-test", model="claude-test", stop_reason="tool_use",
                usage=SimpleNamespace(input_tokens=4, output_tokens=3),
                model_dump=lambda: {"content": [{"type": "tool_use", "id": "tool-1",
                    "name": "house_view", "input": {"market": "SG"}}]})

    adapter = AnthropicAdapter(SimpleNamespace(messages=Messages()))
    bridge = BridgeServer(0, "127.0.0.2", "x" * 32, adapter)
    thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    thread.start()
    body = json.dumps({"model": "claude-test", "messages": [
        {"role": "system", "content": "Follow policy"}, {"role": "user", "content": "Research"}],
        "tools": [{"type": "function", "function": {"name": "house_view",
                    "parameters": {"type": "object"}}}], "tool_choice": "required"}).encode()
    origin = f"http://127.0.0.2:{bridge.server_port}/v1/chat/completions"
    # Bypass environment HTTP proxy settings when calling the loopback alias.
    from urllib.request import ProxyHandler, build_opener
    opener = build_opener(ProxyHandler({}))
    try:
        with pytest.raises(HTTPError) as refused:
            opener.open(Request(origin, data=body, headers={"Authorization": "Bearer wrong"}))
        assert refused.value.code == 403
        assert calls == []
        with opener.open(Request(origin, data=body, headers={"Authorization": "Bearer " + "x" * 32})) as response:
            result = json.load(response)
        assert calls[0]["system"] == "Follow policy"
        assert calls[0]["tool_choice"] == {"type": "any"}
        assert result["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "house_view"
        assert result["usage"]["total_tokens"] == 7
    finally:
        bridge.shutdown()
        bridge.server_close()
        thread.join()


def test_mock_fronted_by_real_kognita_gateway(tmp_path, monkeypatch, capsys):
    import os
    import subprocess
    from sqlmodel import Session
    from eastwind.local_servers import free_port, wait_for_port
    from eastwind.pack import AGENT_NAME, _headers, seed_agent, register_usecases
    from eastwind.showcase import _kognita_cmd, _engine

    seen = []
    class Handler(MockHandler):
        def do_POST(self):
            seen.append(self.path)
            super().do_POST()

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    path = tmp_path / "gateway.db"
    engine = _engine(path)
    with Session(engine) as session:
        seed_agent(session)
        register_usecases(session)
        headers = _headers(session)
        session.commit()
    engine.dispose()
    port = free_port()
    command = _kognita_cmd("serve", "--provider", "openai-compatible", "--upstream",
        f"http://127.0.0.1:{upstream.server_port}", "--purpose", "ELIGIBILITY_CHECK",
        "--purposes", "ELIGIBILITY_CHECK", "--agent", AGENT_NAME,
        "--principal", "rm.sg@eastwind.example", "--actor-location", "SG",
        "--db", str(path), "--port", str(port))
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               env={**os.environ, "NO_PROXY": "127.0.0.1"})
    try:
        wait_for_port(port)
        settings = Settings("mock", "eastwind-local", f"http://127.0.0.1:{port}", "")
        try:
            result = GatewayClient(settings, headers).complete([{"role": "user", "content": "House guidance."}])
        except Exception as exc:
            if hasattr(exc, "read"):
                pytest.fail(exc.read().decode())
            raise
        assert result["model"] == "eastwind-local"
        assert result["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "client_profile"
        assert seen == ["/v1/chat/completions"]
        from eastwind.cli import main
        monkeypatch.setenv("EASTWIND_LLM_GATEWAY_URL", f"http://127.0.0.1:{port}")
        monkeypatch.setenv("EASTWIND_LLM_GATEWAY_DB", str(path))
        monkeypatch.setenv("EASTWIND_LLM_MODEL", "eastwind-local")
        assert main(["run", "allow", "--llm", "ollama", "--fresh", "--db", str(tmp_path / "scenario.db")]) == 0
        assert "Egress" in capsys.readouterr().out
        assert len(seen) == 2
    finally:
        process.terminate()
        process.wait(timeout=10)
        upstream.shutdown()
        upstream.server_close()
        thread.join()


def test_anthropic_path_runs_through_kognita_gateway(tmp_path, monkeypatch):
    import os
    import subprocess
    from types import SimpleNamespace
    from sqlmodel import Session
    from kognita.providers import ProviderRecord, _register, _view
    from eastwind import pack
    from eastwind.llm.anthropic import AnthropicAdapter
    from eastwind.llm.bridge import BridgeServer
    from eastwind.local_servers import free_port, wait_for_port
    from eastwind.showcase import _engine, _kognita_cmd

    calls = []
    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(id="message", model="claude-test", stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=2, output_tokens=3),
                model_dump=lambda: {"content": [{"type": "text", "text": "House guidance noted."}]})

    bridge = BridgeServer(0, "127.0.0.2", "t" * 32, AnthropicAdapter(SimpleNamespace(messages=Messages())))
    thread = threading.Thread(target=bridge.serve_forever, daemon=True)
    thread.start()
    path = tmp_path / "anthropic-gateway.db"
    engine = _engine(path)
    monkeypatch.setattr(pack, "MODEL_CARDS", (*pack.MODEL_CARDS, ("127.0.0.2", "claude-test", "claude-test")))
    with Session(engine) as session:
        pack.seed_agent(session)
        pack.register_usecases(session)
        _register(session, "127.0.0.2", _view(session.get(ProviderRecord, "127.0.0.1")))
        headers = pack._headers(session, model="claude-test")
        from kognita import Run
        from kognita.models import RunRecord
        run = Run()
        session.add(RunRecord(id=run.id))
        headers["run_id"] = run.id
        session.commit()
    engine.dispose()
    port = free_port()
    command = _kognita_cmd("serve", "--provider", "openai-compatible", "--upstream",
        f"http://127.0.0.2:{bridge.server_port}", "--purpose", "ELIGIBILITY_CHECK",
        "--purposes", "ELIGIBILITY_CHECK", "--agent", pack.AGENT_NAME,
        "--principal", "rm.sg@eastwind.example", "--actor-location", "SG",
        "--db", str(path), "--port", str(port))
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={**os.environ, "NO_PROXY": "127.0.0.1,127.0.0.2", "no_proxy": "127.0.0.1,127.0.0.2",
             "KOGNITA_PROVIDER_KEY": "t" * 32})
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only-key")
    try:
        wait_for_port(port)
        settings = Settings("anthropic", "claude-test", f"http://127.0.0.1:{port}", "ANTHROPIC_API_KEY")
        try:
            result = GatewayClient(settings, headers).complete([
                {"role": "user", "content": "Email test.user@example.com about house guidance."}])
        except Exception as exc:
            if hasattr(exc, "read"):
                pytest.fail(exc.read().decode())
            raise
        assert result["choices"][0]["message"]["content"] == "House guidance noted."
        assert len(calls) == 1
        assert "test.user@example.com" not in json.dumps(calls[0])
        assert "test-only-key" not in json.dumps(calls[0])
    finally:
        process.terminate()
        process.wait(timeout=10)
        bridge.shutdown()
        bridge.server_close()
        thread.join()


def test_environment_presets_and_mock_default(monkeypatch):
    monkeypatch.delenv("EASTWIND_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("EASTWIND_LLM_MODEL", raising=False)
    monkeypatch.delenv("EASTWIND_LLM_KEY_ENV", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    assert Settings.from_env().provider == "mock"
    for provider, key in (("openai", "OPENAI_API_KEY"), ("xai", "XAI_API_KEY"),
                          ("anthropic", "ANTHROPIC_API_KEY"),
                          ("openai-compatible", "EASTWIND_LLM_API_KEY")):
        assert Settings.from_env(provider).key_env == key
    assert Settings.from_env("ollama").model == "llama3.2"


def test_gateway_client_refuses_redirect(monkeypatch):
    from http.server import BaseHTTPRequestHandler
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            body = b'{"error":"the gateway only proxies model calls"}'
            self.send_response(405)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            seen.append(self.path)
            self.send_response(307)
            self.send_header("Location", "/another-endpoint")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = GatewayClient(Settings("ollama", "model", f"http://127.0.0.1:{server.server_port}", ""),
                               {"agent_name": "agent"})
        with pytest.raises(RuntimeError, match="HTTP 307"):
            client.complete([{"role": "user", "content": "test"}])
        assert seen == ["/v1/chat/completions"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_direct_provider_origin_is_rejected_without_sending_request():
    calls = []
    class Handler(MockHandler):
        def do_POST(self):
            calls.append(self.path)
            super().do_POST()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = GatewayClient(Settings("ollama", "model", f"http://127.0.0.1:{server.server_port}", ""),
                               {"agent_name": "agent"})
        with pytest.raises(ValueError, match="not a Kognita gateway"):
            client.complete([{"role": "user", "content": "test"}])
        assert calls == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_bridge_refuses_local_gateway_classification_and_weak_token():
    from eastwind.llm.bridge import BridgeServer
    with pytest.raises(ValueError, match="nonlocal-looking"):
        BridgeServer(0, "127.0.0.1", "x" * 32, object())
    with pytest.raises(ValueError, match="token"):
        BridgeServer(0, "127.0.0.2", "short", object())


def test_real_cli_requires_gateway_store(monkeypatch, tmp_path, capsys):
    from eastwind.cli import main
    monkeypatch.setenv("EASTWIND_LLM_GATEWAY_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("EASTWIND_LLM_MODEL", "llama3.2")
    monkeypatch.delenv("EASTWIND_LLM_GATEWAY_DB", raising=False)
    assert main(["run", "allow", "--llm", "ollama", "--db", str(tmp_path / "scenario.db")]) == 1
    assert "EASTWIND_LLM_GATEWAY_DB" in capsys.readouterr().err
