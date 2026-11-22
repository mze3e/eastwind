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
