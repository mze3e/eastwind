"""Local stand-ins so the gateway and MCP demos never leave the machine."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MCP_TOOLS = (
    "house_view",
    "offer_autocall",
    "vague_note",
    "draft_client_letter",
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_port(port: int, timeout: float = 15.0) -> None:
    """Block until ``127.0.0.1:port`` accepts a TCP connection."""
    import time

    deadline = time.time() + timeout
    last = "not started"
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError as exc:
            last = str(exc)
            time.sleep(0.05)
    raise RuntimeError(f"127.0.0.1:{port} did not accept a connection ({last})")


class _Quiet(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return


class OpenAIStandIn(ThreadingHTTPServer):
    """OpenAI-compatible origin. Echoes the user message it actually received."""

    received: list[bytes]

    def __init__(self) -> None:
        self.received = []
        super().__init__(("127.0.0.1", 0), _OpenAIHandler)
        self.daemon_threads = True

    @property
    def origin(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"


class _OpenAIHandler(_Quiet):
    def do_POST(self) -> None:  # noqa: N802 — stdlib name
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        server: OpenAIStandIn = self.server  # type: ignore[assignment]
        server.received.append(body)
        content = "House guidance noted."
        try:
            payload = json.loads(body.decode("utf-8"))
            messages = payload.get("messages") or []
            for message in reversed(messages):
                if isinstance(message, dict) and message.get("role") == "user":
                    text = message.get("content")
                    if isinstance(text, str) and text.strip():
                        content = text
                    break
        except (UnicodeDecodeError, json.JSONDecodeError):
            content = "unreadable"
        reply = {
            "id": "chatcmpl-eastwind",
            "object": "chat.completion",
            "model": "eastwind-stand-in",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
            },
        }
        raw = json.dumps(reply).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class McpStandIn(ThreadingHTTPServer):
    """A one-process MCP server for the Eastwind tools."""

    calls: list[str]

    def __init__(self) -> None:
        self.calls = []
        super().__init__(("127.0.0.1", 0), _McpHandler)
        self.daemon_threads = True

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}/mcp"


class _McpHandler(_Quiet):
    def do_POST(self) -> None:  # noqa: N802 — stdlib name
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""
        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = {}
        method = message.get("method")
        params = message.get("params") or {}
        rpc_id = message.get("id")
        server: McpStandIn = self.server  # type: ignore[assignment]
        if method == "tools/list":
            result: dict[str, Any] = {
                "tools": [
                    {"name": name, "description": f"Eastwind Private tool {name}"}
                    for name in MCP_TOOLS
                ]
            }
        elif method == "tools/call":
            name = str(params.get("name") or "")
            server.calls.append(name)
            result = {
                "content": [
                    {"type": "text", "text": f"Eastwind Private tool {name} ran."}
                ]
            }
        else:
            result = {}
        raw = json.dumps({"jsonrpc": "2.0", "id": rpc_id, "result": result}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve_in_thread(server: ThreadingHTTPServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, name=type(server).__name__, daemon=True)
    thread.start()
    return thread
