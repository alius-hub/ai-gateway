from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException

OPENAI_PROTOCOLS = {"openai", "openai_compatible"}
CLAUDE_PROTOCOLS = {"claude", "anthropic"}

ENDPOINTS = {
    "chat": "chat/completions",
    "embedding": "embeddings",
    "rerank": "rerank",
    "ocr": "ocr",
    "image": "images/generations",
}


def prepare(protocol: str, base: str, name: str, secret: str | None,
            body: dict, kind: str) -> tuple[str, dict[str, str], dict]:
    base = base.rstrip("/")
    headers: dict[str, str] = {}
    if protocol in OPENAI_PROTOCOLS:
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        prefix = base if base.endswith("/v1") else f"{base}/v1"
        return f"{prefix}/{ENDPOINTS[kind]}", headers, {**body, "model": name}
    if kind != "chat":
        raise HTTPException(422, "unsupported_model_protocol")
    messages = body["messages"]
    if any(not isinstance(message.get("content"), str) for message in messages):
        raise HTTPException(422, "multimodal_protocol_not_supported")
    system = "\n".join(
        message["content"] for message in messages if message.get("role") == "system"
    )
    conversation = [message for message in messages if message.get("role") != "system"]
    if protocol in CLAUDE_PROTOCOLS:
        headers["anthropic-version"] = "2023-06-01"
        if secret:
            headers["x-api-key"] = secret
        payload = {
            "model": name, "messages": conversation,
            "max_tokens": body["max_tokens"], "stream": body["stream"],
        }
        if system:
            payload["system"] = system
        for source, target in (("temperature", "temperature"), ("top_p", "top_p"),
                               ("stop", "stop_sequences")):
            if source in body:
                payload[target] = body[source]
        return f"{base if base.endswith('/v1') else f'{base}/v1'}/messages", headers, payload
    if protocol == "gemini":
        if secret:
            headers["x-goog-api-key"] = secret
        config = {}
        for source, target in (("max_tokens", "maxOutputTokens"), ("temperature", "temperature"),
                               ("top_p", "topP"), ("stop", "stopSequences")):
            if source in body:
                config[target] = body[source]
        payload: dict[str, Any] = {
            "contents": [
                {"role": "model" if message.get("role") == "assistant" else "user",
                 "parts": [{"text": message["content"]}]} for message in conversation
            ],
            "generationConfig": config,
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        prefix = base if base.endswith("/v1beta") else f"{base}/v1beta"
        action = "streamGenerateContent?alt=sse" if body["stream"] else "generateContent"
        return f"{prefix}/models/{quote(name, safe='')}:{action}", headers, payload
    raise HTTPException(422, "unsupported_model_protocol")


def usage_counts(payload: dict, protocol: str) -> tuple[int, int | None, int | None] | None:
    if protocol in OPENAI_PROTOCOLS:
        usage = payload.get("usage") or {}
        input_count, output_count = usage.get("prompt_tokens"), usage.get("completion_tokens")
        total = usage.get("total_tokens")
    elif protocol in CLAUDE_PROTOCOLS:
        usage = payload.get("usage") or {}
        input_count, output_count = usage.get("input_tokens"), usage.get("output_tokens")
        total = (
            input_count + output_count
            if type(input_count) is int and type(output_count) is int else None
        )
    else:
        usage = payload.get("usageMetadata") or {}
        input_count, output_count = usage.get("promptTokenCount"), usage.get("candidatesTokenCount")
        total = usage.get("totalTokenCount")
    if type(total) is not int or total < 0:
        return None
    return total, input_count if type(input_count) is int else None, (
        output_count if type(output_count) is int else None
    )


def normalize(payload: dict, protocol: str, kind: str, public_name: str) -> dict:
    if kind != "chat":
        field = "results" if kind == "rerank" else "data"
        if not isinstance(payload.get(field), list):
            # OCR providers have no shared result shape; a non-empty JSON object is required.
            if kind != "ocr" or not payload:
                raise ValueError("invalid provider response")
        return {**payload, "model": public_name}
    if protocol in OPENAI_PROTOCOLS:
        if not isinstance(payload.get("choices"), list):
            raise ValueError("invalid provider response")
        return {**payload, "model": public_name}
    if protocol in CLAUDE_PROTOCOLS:
        content = payload["content"]
        text = "".join(part.get("text", "") for part in content if part.get("type") == "text")
        counts = usage_counts(payload, protocol)
        return {
            "id": payload.get("id", "chatcmpl-gateway"), "object": "chat.completion",
            "model": public_name, "choices": [{"index": 0, "message": {
                "role": "assistant", "content": text,
            }, "finish_reason": payload.get("stop_reason") or "stop"}],
            "usage": {"prompt_tokens": counts[1], "completion_tokens": counts[2],
                      "total_tokens": counts[0]} if counts else {},
        }
    candidate = payload["candidates"][0]
    text = "".join(part.get("text", "") for part in candidate["content"]["parts"])
    counts = usage_counts(payload, protocol)
    return {
        "id": "chatcmpl-gateway", "object": "chat.completion", "model": public_name,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                     "finish_reason": candidate.get("finishReason", "stop").lower()}],
        "usage": {"prompt_tokens": counts[1], "completion_tokens": counts[2],
                  "total_tokens": counts[0]} if counts else {},
    }


def chunk(text: str, public_name: str) -> bytes:
    event = {
        "id": "chatcmpl-gateway", "object": "chat.completion.chunk", "model": public_name,
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode()
