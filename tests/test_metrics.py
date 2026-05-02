from datetime import datetime
from unittest.mock import MagicMock
from metrics import bump_retrieval, _build_payload_update


def test_build_payload_update_initializes_count_and_timestamp():
    update = _build_payload_update(existing_metadata=None)
    assert update["metadata"]["retrieval_count"] == 1
    assert "last_retrieved_at" in update["metadata"]
    datetime.fromisoformat(update["metadata"]["last_retrieved_at"])


def test_build_payload_update_increments_existing_count():
    existing = {"cerebral_type": "preference", "retrieval_count": 5}
    update = _build_payload_update(existing_metadata=existing)
    assert update["metadata"]["retrieval_count"] == 6
    assert update["metadata"]["cerebral_type"] == "preference"


def test_build_payload_update_handles_partial_metadata():
    """Pre-metrics memories may have cerebral_type but no retrieval_count."""
    existing = {"cerebral_type": "warning"}
    update = _build_payload_update(existing_metadata=existing)
    assert update["metadata"]["retrieval_count"] == 1
    assert update["metadata"]["cerebral_type"] == "warning"


def test_bump_retrieval_calls_qdrant_set_payload():
    mock_client = MagicMock()
    point1 = MagicMock(id="mem-1", payload={"metadata": {"retrieval_count": 2}})
    point2 = MagicMock(id="mem-2", payload={"metadata": None})
    mock_client.retrieve.return_value = [point1, point2]
    bump_retrieval(mock_client, "cerebral", ["mem-1", "mem-2"])
    assert mock_client.set_payload.call_count == 2


def test_bump_retrieval_handles_empty_id_list():
    mock_client = MagicMock()
    bump_retrieval(mock_client, "cerebral", [])
    mock_client.set_payload.assert_not_called()
    mock_client.retrieve.assert_not_called()


def test_bump_retrieval_swallows_exceptions():
    """A metric update failure must never break the calling search."""
    mock_client = MagicMock()
    mock_client.retrieve.side_effect = RuntimeError("qdrant down")
    bump_retrieval(mock_client, "cerebral", ["mem-1"])  # must not raise
