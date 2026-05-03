from datetime import datetime
from unittest.mock import MagicMock
from metrics import bump_retrieval, _build_payload_update


def test_build_payload_update_initializes_count_and_timestamp():
    update = _build_payload_update(existing_payload=None)
    assert update["retrieval_count"] == 1
    assert "last_retrieved_at" in update
    datetime.fromisoformat(update["last_retrieved_at"])


def test_build_payload_update_increments_existing_count():
    """Existing top-level retrieval_count gets incremented; cerebral_type left alone."""
    existing = {"cerebral_type": "preference", "retrieval_count": 5, "data": "..."}
    update = _build_payload_update(existing_payload=existing)
    assert update["retrieval_count"] == 6
    # Update is a patch — should NOT include cerebral_type, since set_payload
    # merges and we don't want to touch unrelated fields.
    assert "cerebral_type" not in update


def test_build_payload_update_handles_pre_metrics_payload():
    """Pre-metrics memories have cerebral_type but no retrieval_count — initialize to 1."""
    existing = {"cerebral_type": "warning", "data": "..."}
    update = _build_payload_update(existing_payload=existing)
    assert update["retrieval_count"] == 1


def test_bump_retrieval_calls_qdrant_set_payload():
    mock_client = MagicMock()
    point1 = MagicMock(id="mem-1", payload={"retrieval_count": 2, "cerebral_type": "fact"})
    point2 = MagicMock(id="mem-2", payload={})
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
