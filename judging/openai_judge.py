"""OpenAI-backed judge. Same prompt, id mapping, quote pre-filter and sampling as AnthropicJudge;
only the transport differs. Reads OPENAI_API_KEY from the environment; the key is never logged or stored.

The default model is a placeholder: set ``JUDGE_MODEL`` (or pass ``model=``) to a model your account can use.
"""
from __future__ import annotations

import json
import os
from typing import Any

from .llm_judge import MAX_REASON_CHARS, SYSTEM_PROMPT, TOOL, AnthropicJudge

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

_FUNCTION = {
    "type": "function",
    "function": {"name": TOOL["name"], "description": TOOL["description"], "parameters": TOOL["input_schema"]},
}


class OpenAIJudge(AnthropicJudge):
    def __init__(self, model: str | None = None, client: Any = None, samples: int = 1, timeout: float = 15.0,
                 max_tokens: int = 1500):
        self.model = model or os.environ.get("JUDGE_MODEL") or DEFAULT_OPENAI_MODEL
        self.samples, self.timeout, self.max_tokens = max(1, samples), timeout, max_tokens
        if client is None:
            import openai  # lazy import

            client = openai.OpenAI(timeout=timeout, max_retries=0)  # retries belong to the worker
        self.client = client

    def _ask(self, system: str, user: str) -> dict[str, tuple[str, str]]:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            max_tokens=self.max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=[_FUNCTION],
            tool_choice={"type": "function", "function": {"name": TOOL["name"]}},
        )
        out: dict[str, tuple[str, str]] = {}
        calls = (resp.choices[0].message.tool_calls or []) if resp.choices else []
        for call in calls:
            if call.function.name != TOOL["name"]:
                continue
            try:
                args = json.loads(call.function.arguments or "{}")
            except ValueError:
                continue  # malformed JSON: leave edges unjudged so the worker retries
            for item in args.get("verdicts", []):
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    out[item["id"]] = (str(item.get("verdict", "")), str(item.get("reason", ""))[:MAX_REASON_CHARS])
        return out
