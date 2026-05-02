import asyncio
import time
import pytest
from unittest.mock import MagicMock
from main import _schedule_save, _do_save_memory, _do_save_session_learnings


async def _call_save_memory_tool(mem0, project_id, text, scope, cerebral_type):
    """Simulate what the MCP save_memory tool does."""
    await _schedule_save(_do_save_memory, mem0, project_id, text, scope, cerebral_type)
    return f"Queued to {scope} memory."


@pytest.mark.asyncio
async def test_save_memory_tool_returns_before_ollama():
    """save_memory tool must return before mem0.add() completes."""
    save_completed = []

    def slow_add(*a, **kw):
        time.sleep(0.5)
        save_completed.append(True)

    mock_mem0 = MagicMock()
    mock_mem0.add.side_effect = slow_add

    start = time.time()
    result = await _call_save_memory_tool(mock_mem0, "test-project", "some fact", "global", "fact")
    elapsed = time.time() - start

    assert elapsed < 0.2, f"Tool took {elapsed:.2f}s — should return immediately"
    assert "queued" in result.lower()


@pytest.mark.asyncio
async def test_schedule_save_returns_before_completion():
    completed = []

    def slow_fn():
        time.sleep(0.3)
        completed.append(True)

    task = await _schedule_save(slow_fn)
    assert not completed          # function hasn't finished yet
    await task
    assert completed              # now it has


@pytest.mark.asyncio
async def test_schedule_save_handles_exception_silently():
    def failing_fn():
        raise RuntimeError("simulated save failure")

    task = await _schedule_save(failing_fn)
    await task                   # should not raise
