from unittest.mock import MagicMock
from main import _do_search_memories


def test_search_memories_returns_ids_alongside_text():
    mock_mem0 = MagicMock()
    mock_mem0.search.return_value = {
        "results": [
            {"id": "id-1", "memory": "first match"},
            {"id": "id-2", "memory": "second match"},
        ]
    }
    text, ids = _do_search_memories(mock_mem0, "test-project", "query", "global")
    assert "first match" in text
    assert ids == ["id-1", "id-2"]


def test_search_memories_returns_empty_ids_when_no_results():
    mock_mem0 = MagicMock()
    mock_mem0.search.return_value = {"results": []}
    text, ids = _do_search_memories(mock_mem0, "test-project", "query", "global")
    assert ids == []
    assert "No relevant memories" in text


def test_search_memories_returns_ids_from_both_scopes():
    mock_mem0 = MagicMock()

    def search(query, filters, limit):
        if filters["user_id"].startswith("project:"):
            return {"results": [{"id": "p-1", "memory": "project mem"}]}
        return {"results": [{"id": "g-1", "memory": "global mem"}]}

    mock_mem0.search.side_effect = search
    text, ids = _do_search_memories(mock_mem0, "test-project", "query", "both")
    assert set(ids) == {"p-1", "g-1"}
