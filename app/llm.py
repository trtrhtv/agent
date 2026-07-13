"""OpenRouter client. One cheap ROUTINE_MODEL for everything except product
content generation, which uses GENERATION_MODEL (see Module 2)."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import ROUTINE_MODEL, env

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 120.0


def chat(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4000,
) -> str:
    payload = {
        "model": model or ROUTINE_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {env('OPENROUTER_API_KEY')}",
        "X-Title": "TrendMill",
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.post(OPENROUTER_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


def extract_json(text: str) -> Any:
    """Parse JSON from an LLM reply, tolerating markdown fences and prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the outermost JSON object/array in the text.
        for open_ch, close_ch in (("{", "}"), ("[", "]")):
            start, end = text.find(open_ch), text.rfind(close_ch)
            if start != -1 and end > start:
                return json.loads(text[start : end + 1])
        raise


def chat_json(
    messages: list[dict[str, str]],
    model: str | None = None,
    temperature: float = 0.4,
    max_tokens: int = 4000,
) -> Any:
    """chat() + JSON parsing, with one retry that feeds the error back."""
    reply = chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)
    try:
        return extract_json(reply)
    except Exception:
        retry_messages = messages + [
            {"role": "assistant", "content": reply},
            {
                "role": "user",
                "content": "That was not valid JSON. Reply again with ONLY the "
                "valid JSON, no prose, no markdown fences.",
            },
        ]
        reply = chat(retry_messages, model=model, temperature=0.2, max_tokens=max_tokens)
        return extract_json(reply)
