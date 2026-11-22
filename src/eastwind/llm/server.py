"""OpenAI-compatible local HTTP endpoint for the deterministic mock."""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from eastwind.llm import MockClient


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 1_000_000:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(size))
            if payload.get("stream"):
                raise ValueError("streaming is not supported")
            workflow = payload.get("workflow", "client-review")
            message = MockClient().complete(payload.get("messages", []), workflow=workflow)
            result = {"id": "chatcmpl-eastwind", "object": "chat.completion", "created": 0,
                      "model": payload.get("model", "eastwind-mock"),
                      "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls"}],
                      "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}
            raw = json.dumps(result).encode()
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.send_error(400, str(exc))
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve(host: str = "127.0.0.1", port: int = 8091) -> None:
    with ThreadingHTTPServer((host, port), MockHandler) as server:
        server.serve_forever()
