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
DEFAULT_GROK_MODEL = "grok-2-latest"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

_FUNCTION = {
    "type": "function",
    "function": {"name": TOOL["name"], "description": TOOL["description"], "parameters": TOOL["input_schema"]},
}
_FUNCTION_UPPER = {
    "type": "function",
    "function": {"name": "record_VERDICTS", "description": TOOL["description"], "parameters": TOOL["input_schema"]},
}


class OpenAIJudge(AnthropicJudge):
    def __init__(self, model: str | None = None, client: Any = None, samples: int = 1, timeout: float = 15.0,
                 max_tokens: int = 1500, base_url: str | None = None, api_key: str | None = None):
        self.model = model or os.environ.get("JUDGE_MODEL") or DEFAULT_OPENAI_MODEL
        self.samples, self.timeout, self.max_tokens = max(1, samples), timeout, max_tokens
        if client is None:
            import openai  # lazy import

            key = api_key or os.environ.get("OPENAI_API_KEY")
            url = base_url or os.environ.get("OPENAI_BASE_URL")
            client = openai.OpenAI(api_key=key, base_url=url, timeout=timeout, max_retries=0)  # retries belong to the worker
        self.client = client

    def _ask(self, system: str, user: str) -> dict[str, tuple[str, str]]:
        tools = [_FUNCTION, _FUNCTION_UPPER]
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            max_tokens=self.max_tokens,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            tools=tools,
            tool_choice={"type": "function", "function": {"name": TOOL["name"]}},
        )
        out: dict[str, tuple[str, str]] = {}
        calls = (resp.choices[0].message.tool_calls or []) if resp.choices else []
        for call in calls:
            if call.function.name.lower() != TOOL["name"].lower():
                continue
            try:
                args = json.loads(call.function.arguments or "{}")
            except ValueError:
                continue  # malformed JSON: leave edges unjudged so the worker retries
            for item in args.get("verdicts", []):
                if isinstance(item, dict) and isinstance(item.get("id"), str):
                    out[item["id"]] = (str(item.get("verdict", "")), str(item.get("reason", ""))[:MAX_REASON_CHARS])
        return out


class GrokJudge(OpenAIJudge):
    """xAI Grok or Groq Cloud judge (OpenAI-compatible wire API).

    Automatically detects key type:
    - If key starts with 'gsk_', routes to Groq Cloud (https://api.groq.com/openai/v1) with openai/gpt-oss-120b.
    - If key starts with 'xai-', routes to xAI (https://api.x.ai/v1) with grok-2-latest.
    """

    def __init__(self, model: str | None = None, client: Any = None, samples: int = 1, timeout: float = 15.0,
                 max_tokens: int = 1500, base_url: str | None = None, api_key: str | None = None):
        target_key = (
            api_key
            or os.environ.get("GROK_API_KEY")
            or os.environ.get("GROQ_API_KEY")
            or os.environ.get("XAI_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        is_groq = bool(target_key and target_key.startswith("gsk_"))
        
        if is_groq:
            env_model = os.environ.get("GROQ_MODEL") or os.environ.get("JUDGE_MODEL")
            if not env_model or env_model.startswith("gpt-"):
                target_model = model or DEFAULT_GROQ_MODEL
            else:
                target_model = model or env_model
        else:
            target_model = model or os.environ.get("GROK_MODEL") or os.environ.get("JUDGE_MODEL") or DEFAULT_GROK_MODEL
        
        default_url = "https://api.groq.com/openai/v1" if is_groq else "https://api.x.ai/v1"
        target_url = (
            base_url
            or os.environ.get("GROQ_BASE_URL")
            or os.environ.get("XAI_BASE_URL")
            or os.environ.get("GROK_BASE_URL")
            or default_url
        )
        super().__init__(
            model=target_model,
            client=client,
            samples=samples,
            timeout=timeout,
            max_tokens=max_tokens,
            base_url=target_url,
            api_key=target_key,
        )


GroqJudge = GrokJudge
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"


class GeminiJudge(OpenAIJudge):
    """Google Gemini AI judge via official OpenAI-compatible endpoint.

    Uses https://generativelanguage.googleapis.com/v1beta/openai/ with model gemini-1.5-flash or gemini-2.0-flash.
    """

    def __init__(self, model: str | None = None, client: Any = None, samples: int = 1, timeout: float = 15.0,
                 max_tokens: int = 1500, base_url: str | None = None, api_key: str | None = None):
        target_key = (
            api_key
            or os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
        )
        target_model = model or os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        default_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
        target_url = base_url or os.environ.get("GEMINI_BASE_URL") or default_url
        super().__init__(
            model=target_model,
            client=client,
            samples=samples,
            timeout=timeout,
            max_tokens=max_tokens,
            base_url=target_url,
            api_key=target_key,
        )


class FallbackJudge:
    """Wraps multiple judges and cascades on failure or 429 rate limits.

    Tries primary judge first; if primary hits 429 (rate limit) or connection error,
    automatically fails over to secondary judges seamlessly.
    """

    def __init__(self, judges: list[Any]):
        self.judges = [j for j in judges if j is not None]

    def judge_batch(self, rows: list[Any]) -> dict[str, Any]:
        if not self.judges:
            return {}
        last_err: Exception | None = None
        for idx, judge in enumerate(self.judges):
            try:
                return judge.judge_batch(rows)
            except Exception as e:
                err_str = str(e)
                last_err = e
                # Check if it's a rate limit (429), quota, timeout, or transient error
                if ("429" in err_str or "rate_limit" in err_str.lower() or "quota" in err_str.lower()
                        or "timeout" in err_str.lower() or "connection" in err_str.lower()):
                    # Failover to next configured judge in pool
                    continue
                else:
                    # Non-retryable error
                    raise e
        if last_err:
            raise last_err
        return {}
