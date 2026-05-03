import logging
from datetime import datetime, timezone

from qdrant_client import QdrantClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_payload_update(existing_payload: dict | None) -> dict:
    """
    Returns the flat payload patch to feed into Qdrant set_payload.

    mem0 stores user-supplied metadata as TOP-LEVEL Qdrant payload keys (e.g.
    `cerebral_type: "fact"`). On read, it collects all non-core payload keys
    into a `metadata` dict on the returned record. So we must also write
    metric fields flat at the top level — nesting under a "metadata" key
    causes mem0 to double-wrap them on retrieval.

    set_payload merges into existing payload, so this only touches our two
    metric keys and leaves cerebral_type, data, hash, etc. alone.
    """
    payload = existing_payload or {}
    new_count = int(payload.get("retrieval_count", 0)) + 1
    return {
        "retrieval_count": new_count,
        "last_retrieved_at": _now_iso(),
    }


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
            update = _build_payload_update(point.payload)
            client.set_payload(
                collection_name=collection,
                payload=update,
                points=[point.id],
            )
    except Exception as e:
        logging.error(f"bump_retrieval failed: {e}")
