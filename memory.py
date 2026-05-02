import os
from dotenv import load_dotenv
from mem0 import Memory
from qdrant_client import QdrantClient

load_dotenv()

_client: Memory | None = None
_qdrant: QdrantClient | None = None

GLOBAL_USER_ID = os.getenv("CEREBRAL_USER_ID", "dhruvin")
QDRANT_COLLECTION = "cerebral"


def get_client() -> Memory:
    global _client
    if _client is None:
        _client = Memory.from_config(_build_config())
    return _client


def get_qdrant_client() -> QdrantClient:
    """Direct Qdrant client for payload-only mutations (e.g. metric updates)
    that should bypass mem0's LLM extraction pipeline."""
    global _qdrant
    if _qdrant is None:
        qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")
        _qdrant = QdrantClient(url=qdrant_url)
    return _qdrant


def project_user_id(project_name: str) -> str:
    return f"project:{project_name}"


def _build_config() -> dict:
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333")

    return {
        "llm": {
            "provider": "ollama",
            "config": {
                "model": "llama3.2:3b",
                "temperature": 0.1,
                "ollama_base_url": ollama_url,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": "nomic-embed-text",
                "embedding_dims": 768,
                "ollama_base_url": ollama_url,
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "url": qdrant_url,
                "collection_name": "cerebral",
                "embedding_model_dims": 768,
            },
        },
    }
