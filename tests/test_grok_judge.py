import os
from unittest.mock import MagicMock, patch
import pytest

from judging.openai_judge import GrokJudge, DEFAULT_GROK_MODEL
from judging import service


def test_grok_judge_initialization_defaults(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key-12345")
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.delenv("XAI_BASE_URL", raising=False)

    judge = GrokJudge()
    assert judge.model == DEFAULT_GROK_MODEL
    assert str(judge.client.base_url) == "https://api.x.ai/v1/"
    assert judge.client.api_key == "xai-test-key-12345"


def test_grok_judge_custom_model_and_key(monkeypatch):
    monkeypatch.setenv("GROK_API_KEY", "grok-custom-key")
    monkeypatch.setenv("JUDGE_MODEL", "grok-beta")

    judge = GrokJudge()
    assert judge.model == "grok-beta"
    assert judge.client.api_key == "grok-custom-key"


def test_service_ensure_worker_handles_grok(monkeypatch):
    monkeypatch.setenv("JUDGING_ENABLED", "1")
    monkeypatch.setenv("JUDGE_PROVIDER", "grok")
    monkeypatch.setenv("XAI_API_KEY", "xai-test-key")

    service.reset()
    with patch("judging.worker.JudgeWorker.start") as mock_start:
        service.ensure_worker()
        assert len(service._workers) > 0
        assert mock_start.called
    service.reset()
