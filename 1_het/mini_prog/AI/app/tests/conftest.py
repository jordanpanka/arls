import pytest

from app.tools.base import RESULT_CACHE
from app.tools.code_graph import GRAPH_CACHE


@pytest.fixture(autouse=True)
def isolated_agent_state(monkeypatch):
    RESULT_CACHE.entries.clear()
    GRAPH_CACHE.entries.clear()
    from app.services import chat_service
    monkeypatch.setattr(chat_service.trace_collector, "enabled", False)
    yield
    RESULT_CACHE.entries.clear()
    GRAPH_CACHE.entries.clear()
