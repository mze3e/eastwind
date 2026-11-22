"""Local, authenticated Anthropic protocol bridge behind Kognita."""
from __future__ import annotations

import hmac
import ipaddress
import json
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from eastwind.llm.anthropic import AnthropicAdapter


def validate_alias(alias: str) -> str:
    name = alias.lower().rstrip(".")
    if not name or name in {"localhost", "127.0.0.1", "::1"} or any(c in name for c in "/:@[] "):
        raise ValueError("bridge alias must be a nonlocal-looking hostname")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(name, None, family=socket.AF_INET, type=socket.SOCK_STREAM)}
        if len(addresses) != 1 or not all(ipaddress.ip_address(address).is_loopback for address in addresses):
            raise ValueError("bridge alias must resolve only to loopback")
    except socket.gaierror as exc:
        raise ValueError("bridge alias must resolve only to loopback") from exc
    return name


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, alias: str, token: str, adapter: AnthropicAdapter):
        self.alias = validate_alias(alias)
        if len(token) < 32 or not token.isascii() or any(not (c.isalnum() or c in "-_") for c in token):
            raise ValueError("bridge token must be at least 32 URL-safe ASCII characters")
        self.token = token
        self.adapter = adapter
        address = socket.getaddrinfo(self.alias, None, family=socket.AF_INET, type=socket.SOCK_STREAM)[0][4][0]
        super().__init__((address, port), BridgeHandler)


class BridgeHandler(BaseHTTPRequestHandler):
    server: BridgeServer

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        host = urlsplit("//" + self.headers.get("Host", "")).hostname
        authorization = self.headers.get("Authorization", "")
        if (host != self.server.alias or not hmac.compare_digest(
                authorization, "Bearer " + self.server.token)):
            self.send_error(403)
            return
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError("invalid request size")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("request must be an object")
            response = self.server.adapter.complete(body)
            raw = json.dumps(response).encode()
        except (ValueError, TypeError, KeyError):
            self.send_error(400, "unsupported request")
            return
        except Exception:
            # Do not return provider exceptions, which may contain credentials.
            self.send_error(502, "provider request failed")
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def serve(port: int, alias: str, token: str, api_key: str) -> None:
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is required")
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise ValueError("install Eastwind with the anthropic extra") from exc
    with BridgeServer(port, alias, token, AnthropicAdapter(Anthropic(api_key=api_key))) as server:
        print(f"Anthropic bridge listening on {server.server_address[0]}:{server.server_port}", flush=True)
        server.serve_forever()
