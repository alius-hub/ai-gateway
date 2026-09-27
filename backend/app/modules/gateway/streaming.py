from __future__ import annotations

import codecs
import json
import re
from dataclasses import dataclass
from typing import Callable

import httpx

from app.modules.gateway.adapters import CLAUDE_PROTOCOLS, OPENAI_PROTOCOLS, chunk, usage_counts


@dataclass
class StreamUsage:
    total: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    text: str = ""
    completed: bool = False
    seen: bool = False


async def events(response: httpx.Response, archive: Callable[[bytes], None] | None = None):
    data: list[str] = []
    event = ""
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    pending = ""
    async for raw in response.aiter_bytes():
        if archive:
            archive(raw)
        pending += decoder.decode(raw)
        while match := re.search(r"\r\n|\r|\n", pending):
            if match.group() == "\r" and match.end() == len(pending):
                break
            line, pending = pending[:match.start()], pending[match.end():]
            if not line:
                if data:
                    yield event, "\n".join(data)
                data, event = [], ""
            elif line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif line.startswith("event:"):
                event = line[6:].strip()
    pending += decoder.decode(b"", final=True)
    if pending:
        line = pending.rstrip("\r")
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif line.startswith("event:"):
            event = line[6:].strip()
    if data:
        yield event, "\n".join(data)


def translate(protocol: str, event: str, data: str, model: str,
              usage: StreamUsage) -> bytes | None:
    if data == "[DONE]":
        usage.completed = True
        return None
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("invalid SSE payload")
    if event == "error" or payload.get("error") is not None:
        raise ValueError("provider stream error")
    usage.seen = True
    if protocol in OPENAI_PROTOCOLS:
        counts = usage_counts(payload, protocol)
        if counts:
            usage.total, usage.input_tokens, usage.output_tokens = counts
        payload["model"] = model
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
    if protocol in CLAUDE_PROTOCOLS:
        if event == "error" or payload.get("type") == "error":
            raise ValueError("provider stream error")
        if event == "message_start":
            count = (payload.get("message") or {}).get("usage", {}).get("input_tokens")
            if type(count) is int:
                usage.input_tokens = count
        elif event == "message_delta":
            count = (payload.get("usage") or {}).get("output_tokens")
            if type(count) is int:
                usage.output_tokens = count
        elif event == "message_stop":
            usage.completed = True
        elif event == "content_block_delta":
            delta = payload.get("delta") or {}
            if delta.get("type") == "text_delta" and isinstance(delta.get("text"), str):
                return chunk(delta["text"], model)
        if usage.input_tokens is not None and usage.output_tokens is not None:
            usage.total = usage.input_tokens + usage.output_tokens
        return None
    if protocol == "gemini":
        counts = usage_counts(payload, protocol)
        if counts:
            usage.total, usage.input_tokens, usage.output_tokens = counts
            usage.completed = True
        candidates = payload.get("candidates") or []
        if candidates:
            if candidates[0].get("finishReason"):
                usage.completed = True
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(part.get("text", "") for part in parts)
            delta = text[len(usage.text):] if text.startswith(usage.text) else text
            usage.text = text
            if delta:
                return chunk(delta, model)
        return None
    raise ValueError("unsupported SSE protocol")
