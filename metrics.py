import logging
from datetime import datetime, timezone

from qdrant_client import QdrantClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_payload_update(existing_metadata: dict | None) -> dict:
    """
    Merge metric fields into existing metadata. Preserves cerebral_type and any
    other fields. Initializes retrieval_count to 1 if absent (covers pre-metrics
    memories with metadata=None or partial metadata).
    """
    metadata = dict(existing_metadata) if existing_metadata else {}
    metadata["retrieval_count"] = int(metadata.get("retrieval_count", 0)) + 1
    metadata["last_retrieved_at"] = _now_iso()
    return {"metadata": metadata}


def bump_retrieval(client: QdrantClient, collection: str, memory_ids: list[str]) -> None:
    """
    Increment retrieval_count and update last_retrieved_at for each memory id.
    Designed to run in a background task — exceptions are logged, never raised.
    """
    if not memory_ids:
        return
    try:
        points = client.retrieve(
            collection_name=collection,
            ids=memory_ids,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            existing = (point.payload or {}).get("metadata")
            update = _build_payload_update(existing)
            client.set_payload(
                collection_name=collection,
                payload=update,
                points=[point.id],
            )
    except Exception as e:
        logging.error(f"bump_retrieval failed: {e}")
