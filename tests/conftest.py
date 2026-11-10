import pytest

import event_core as core


@pytest.fixture(autouse=True)
def _graph_gate_off_by_default(monkeypatch):
    """Most tests lock levels with tiny placeholder graphs. The F1 gate has its own tests (test_graph_gate.py),
    which switch it on explicitly. The env var (not just a monkeypatch) is inherited by multiprocessing workers."""
    monkeypatch.setenv("UL_GRAPH_GATE", "off")
    monkeypatch.setattr(core, "_GATE", {})
