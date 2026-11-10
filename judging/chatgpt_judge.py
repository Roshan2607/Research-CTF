"""Judge that spends the organiser's ChatGPT plan allowance (Sign in with ChatGPT) via the Responses API.

Constraints from OpenAI's docs for this flow: ``POST https://api.openai.com/v1/responses`` with ``store=false`` and
``stream=true``; success only after ``response.completed``. Tool calling / structured outputs are not documented for
this flow, so the model is asked for a JSON object in plain text and the result is validated like any other judge.
Prompt, id mapping, quote pre-filter and sampling are inherited from AnthropicJudge.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from . import chatgpt_auth
from .llm_judge import MAX_REASON_CHARS, SYSTEM_PROMPT, AnthropicJudge

BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-6.1-terra"  # fastest of the 8 tested; verdicts matched the largest model (see load tests)
JSON_INSTRUCTION = (
    "\n\nReply with ONLY a JSON object, no prose and no code fences, of the form "
    '{"verdicts": [{"id": "e1", "verdict": "supported|plausible|unsupported|abstain", "reason": "..."}]} '
    "with exactly one entry per edge id. Instead of calling record_verdicts, put these verdicts in that JSON."
)


class ChatGPTError(RuntimeError):
    pass


def parse_verdict_json(text: str) -> dict[str, tuple[str, str]]:
    text = (text or "").strip()
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for item in data.get("verdicts", []) if isinstance(data, dict) else []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            out[item["id"]] = (str(item.get("verdict", "")), str(item.get("reason", ""))[:MAX_REASON_CHARS])
    return out


class ChatGPTJudge(AnthropicJudge):
    def __init__(self, model: str | None = None, samples: int = 1, timeout: float = 25.0,
                 token_provider: Callable[[], str] | None = None, client_factory: Callable[[str], Any] | None = None):
        import os

        self.model = model or os.environ.get("JUDGE_MODEL") or ""
        self.samples, self.timeout = max(1, samples), timeout
        self.token_provider = token_provider or chatgpt_auth.get_access_token
        self.client_factory = client_factory or self._default_client

    def _default_client(self, token: str):
        import openai

        return openai.OpenAI(api_key=token, base_url=BASE_URL, timeout=self.timeout, max_retries=0)

    def list_models(self) -> list[dict]:
        """Models this account may use (``visibility == 'list'``); each ``slug`` is what to pass as model."""
        import requests

        r = requests.get(f"{BASE_URL}/models", headers={"Authorization": f"Bearer {self.token_provider()}"}, timeout=15)
        r.raise_for_status()
        return [m for m in r.json().get("models", []) if m.get("visibility") == "list"]

    def _resolve_model(self) -> str:
        if not self.model:
            slugs = [m["slug"] for m in self.list_models()]
            if not slugs:
                raise ChatGPTError("no models available to this ChatGPT account")
            self.model = DEFAULT_MODEL if DEFAULT_MODEL in slugs else slugs[0]
        return self.model

    def _ask(self, system: str, user: str) -> dict[str, tuple[str, str]]:
        client = self.client_factory(self.token_provider())
        stream = client.responses.create(
            model=self._resolve_model(),
            input=[{"role": "system", "content": system + JSON_INSTRUCTION}, {"role": "user", "content": user}],
            store=False,
            stream=True,
        )
        chunks: list[str] = []
        completed = False
        for ev in stream:
            kind = getattr(ev, "type", "")
            if kind == "response.output_text.delta":
                chunks.append(getattr(ev, "delta", "") or "")
            elif kind == "response.completed":
                completed = True
            elif kind in ("response.failed", "response.incomplete"):
                err = getattr(getattr(getattr(ev, "response", None), "error", None), "code", None) or kind
                raise ChatGPTError(str(err))
        if not completed:  # per docs, a stream that ends without response.completed is a failure
            raise ChatGPTError("stream ended without response.completed")
        return parse_verdict_json("".join(chunks))
