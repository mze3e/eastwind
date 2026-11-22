"""Native Anthropic adapter for a gateway-owned OpenAI-compatible bridge.

The bridge is an upstream of Kognita, never the agent's model client. Its
shared bearer credential must be held only by the gateway and this bridge.
"""
from __future__ import annotations

import json
from typing import Any


class AnthropicAdapter:
    def __init__(self, client: Any):
        self.client = client

    def complete(self, request: dict) -> dict:
        supported = {"model", "messages", "max_tokens", "temperature", "top_p",
                     "stop", "tools", "tool_choice", "stream", "n"}
        if set(request) - supported or request.get("stream") or request.get("n", 1) != 1:
            raise ValueError("unsupported request options")
        messages = []
        system = []
        for message in request.get("messages", []):
            role = message.get("role")
            if role in ("system", "developer"):
                if not isinstance(message.get("content"), str):
                    raise ValueError("system content must be text")
                system.append(message["content"])
            elif role == "tool":
                messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message.get("content") or ""}]})
            elif role in ("user", "assistant"):
                content = message.get("content") or ""
                if not isinstance(content, str):
                    raise ValueError("only text content is supported")
                blocks = ([{"type": "text", "text": content}] if content else [])
                for call in message.get("tool_calls", []):
                    function = call["function"]
                    blocks.append({"type": "tool_use", "id": call["id"], "name": function["name"], "input": json.loads(function["arguments"])})
                if not blocks:
                    raise ValueError("empty messages are not supported")
                messages.append({"role": role, "content": blocks})
            else:
                raise ValueError("unsupported message role")
        if not messages:
            raise ValueError("at least one user or assistant message is required")
        args: dict[str, Any] = {"model": request["model"], "messages": messages,
                                "max_tokens": request.get("max_tokens", 1024)}
        if system:
            args["system"] = "\n".join(system)
        if "temperature" in request:
            args["temperature"] = request["temperature"]
        if "top_p" in request:
            args["top_p"] = request["top_p"]
        if "stop" in request:
            stop = request["stop"]
            args["stop_sequences"] = [stop] if isinstance(stop, str) else stop
        if request.get("tools"):
            args["tools"] = [{"name": tool["function"]["name"],
                              "description": tool["function"].get("description", ""),
                              "input_schema": tool["function"].get("parameters", {"type": "object"})}
                             for tool in request["tools"] if tool.get("type") == "function"]
            if len(args["tools"]) != len(request["tools"]):
                raise ValueError("unsupported tool type")
        choice = request.get("tool_choice")
        if choice is not None:
            if "tools" not in args:
                raise ValueError("tool choice requires tools")
            if choice == "none":
                del args["tools"]
            elif choice in ("auto", "required"):
                args["tool_choice"] = {"type": "auto" if choice == "auto" else "any"}
            elif isinstance(choice, dict) and choice.get("type") == "function":
                args["tool_choice"] = {"type": "tool", "name": choice["function"]["name"]}
            else:
                raise ValueError("unsupported tool choice")
        response = self.client.messages.create(**args)
        blocks = response.model_dump()["content"]
        if any(block["type"] not in {"text", "tool_use"} for block in blocks):
            raise ValueError("unsupported provider response")
        text = "".join(block["text"] for block in blocks if block["type"] == "text")
        calls = [{"id": block["id"], "type": "function", "function": {"name": block["name"], "arguments": json.dumps(block["input"], sort_keys=True)}}
                 for block in blocks if block["type"] == "tool_use"]
        message: dict[str, Any] = {"role": "assistant", "content": text or None}
        if calls:
            message["tool_calls"] = calls
        usage = response.usage
        return {"id": response.id, "object": "chat.completion", "created": 0,
                "model": response.model, "choices": [{"index": 0, "message": message,
                "finish_reason": "tool_calls" if calls else ("length" if response.stop_reason == "max_tokens" else "stop")}],
                "usage": {"prompt_tokens": usage.input_tokens, "completion_tokens": usage.output_tokens,
                          "total_tokens": usage.input_tokens + usage.output_tokens}}
