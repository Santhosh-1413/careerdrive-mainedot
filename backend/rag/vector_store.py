"""
Qdrant Vector Store
====================
qdrant-client >= 1.9: client.search() renamed to client.query_points().
Results returned via result.points (not the list directly).
"""

import os
import logging
from typing import Optional
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue, MatchAny,
)

import hashlib

log = logging.getLogger("transitbot.vectorstore")


def _make_id(text: str) -> int:
    """Stable numeric ID from any string. Used as Qdrant point ID."""
    return int(hashlib.md5(text.encode()).hexdigest()[:8], 16)

COLLECTIONS = ["roles", "skills", "tools", "certifications", "career_paths"]
VECTOR_DIM  = 384

_client: Optional[QdrantClient] = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        _client = QdrantClient(url=url)
        log.info("Qdrant connected at %s", url)
    return _client


def ensure_collections():
    client = get_client()
    existing = {c.name for c in client.get_collections().collections}
    for name in COLLECTIONS:
        if name not in existing:
            client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            log.info("Created collection: %s", name)


def upsert(collection: str, points: list[dict]):
    client = get_client()
    client.upsert(
        collection_name=collection,
        points=[PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"]) for p in points],
    )
    log.info("Upserted %d points into '%s'", len(points), collection)


def _build_filter(filters: Optional[dict]) -> Optional[Filter]:
    if not filters:
        return None
    conditions = []
    for field, value in filters.items():
        if isinstance(value, list):
            conditions.append(FieldCondition(key=field, match=MatchAny(any=value)))
        else:
            conditions.append(FieldCondition(key=field, match=MatchValue(value=value)))
    return Filter(must=conditions)


def search(
    collection: str,
    query_vector: list[float],
    limit: int = 5,
    filters: Optional[dict] = None,
) -> list:
    """
    Semantic vector search using query_points() (qdrant-client >= 1.9).
    Returns list of ScoredPoint — access .payload on each item.
    """
    result = get_client().query_points(
        collection_name=collection,
        query=query_vector,
        limit=limit,
        query_filter=_build_filter(filters),
        with_payload=True,
    )
    return result.points


def get_by_id(collection: str, doc_id: int) -> Optional[dict]:
    results = get_client().retrieve(
        collection_name=collection,
        ids=[doc_id],
        with_payload=True,
    )
    return results[0].payload if results else None


def get_by_ids(collection: str, ids: list) -> list[dict]:
    if not ids:
        return []
    results = get_client().retrieve(
        collection_name=collection,
        ids=list(ids),
        with_payload=True,
    )
    return [r.payload for r in results]


def filter_search(collection: str, filters: dict, limit: int = 20) -> list[dict]:
    """Pure payload filter — uses scroll() which is unchanged across versions."""
    results, _ = get_client().scroll(
        collection_name=collection,
        scroll_filter=_build_filter(filters),
        limit=limit,
        with_payload=True,
    )
    return [r.payload for r in results]


def collection_count(collection: str) -> int:
    try:
        return get_client().count(collection_name=collection).count
    except Exception:
        return 0


def is_populated() -> bool:
    try:
        return collection_count("roles") > 0
    except Exception:
        return False
