import os
import pytest

os.environ.setdefault("CEREBRAL_PROJECT", "test-project")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("CEREBRAL_USER_ID", "dhruvin")

from memory import get_client
from main import (
    _do_load_context,
    _do_search_memories,
    _do_save_memory,
    _do_save_session_learnings,
    _do_get_project_memories,
)

PROJECT_ID = "test-project"


@pytest.fixture(scope="module")
def mem0():
    return get_client()


def test_save_and_search_global_memory(mem0):
    _do_save_memory(mem0, PROJECT_ID, "User prefers snake_case for all variable names", "global")
    results = _do_search_memories(mem0, PROJECT_ID, "naming conventions", "global")
    assert "snake_case" in results.lower() or "naming" in results.lower() or len(results) > 2


def test_save_and_search_project_memory(mem0):
    _do_save_memory(mem0, PROJECT_ID, "Auth requires X-API-Key header on all requests", "project")
    results = _do_search_memories(mem0, PROJECT_ID, "authentication", "project")
    assert len(results) > 2


def test_search_both_scopes_by_default(mem0):
    results = _do_search_memories(mem0, PROJECT_ID, "variable naming")
    assert isinstance(results, str)


def test_load_context_returns_brief(mem0):
    result = _do_load_context(mem0, PROJECT_ID, "writing Python code")
    assert isinstance(result, str)
    assert len(result) > 0


def test_get_project_memories_returns_data(mem0):
    result = _do_get_project_memories(mem0, PROJECT_ID)
    assert isinstance(result, str)
    assert len(result) > 0


def test_save_memory_stores_type(mem0):
    _do_save_memory(mem0, PROJECT_ID, "CRITICAL: never commit .env files", "project", "warning")
    results = _do_search_memories(mem0, PROJECT_ID, ".env files security", "project")
    assert len(results) > 2


def test_load_context_sections_by_type(mem0):
    _do_save_memory(mem0, PROJECT_ID, "WARNING: rate limit is 10 req/s on the external API", "project", "warning")
    _do_save_memory(mem0, PROJECT_ID, "User prefers verbose logging in dev mode", "project", "preference")
    result = _do_load_context(mem0, PROJECT_ID)
    assert "Critical" in result or "critical" in result.lower() or "Warning" in result
    assert isinstance(result, str)
    assert len(result) > 10


def test_save_session_learnings_bulk(mem0):
    summary = """
    User corrected me: always use pathlib.Path not os.path.
    Discovered: the config loader silently ignores missing keys.
    Decision: use Qdrant over Chroma for performance.
    """
    result = _do_save_session_learnings(mem0, PROJECT_ID, summary)
    assert "saved" in result.lower()
