"""
Embedding Service
==================
Primary:  BAAI/bge-small-en-v1.5  (33M params, better retrieval quality)
Fallback: all-MiniLM-L6-v2        (22M params, faster, less memory)

Both produce 384-dimensional vectors — fully interchangeable.
Model is selected via EMBED_MODEL environment variable.
"""

import os
import logging
from typing import Union

log = logging.getLogger("transitbot.embedder")

_model = None
_model_name = ""


def _load_model():
    global _model, _model_name
    if _model is not None:
        return _model

    preferred = os.environ.get("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
    fallback  = "all-MiniLM-L6-v2"

    from sentence_transformers import SentenceTransformer

    for model_id in [preferred, fallback]:
        try:
            log.info("Loading embedding model: %s", model_id)
            _model = SentenceTransformer(model_id)
            _model_name = model_id
            log.info("Embedding model loaded: %s (dim=%d)", model_id, get_dimension())
            return _model
        except Exception as e:
            log.warning("Failed to load %s: %s", model_id, e)

    raise RuntimeError("No embedding model could be loaded")


def embed(texts: Union[str, list[str]]) -> list[list[float]]:
    """
    Embed one or more texts. Returns list of float vectors.
    BGE-small works best with a query prefix for retrieval tasks.
    """
    model = _load_model()

    if isinstance(texts, str):
        texts = [texts]

    # BGE models use a query prefix for better retrieval
    if "bge" in _model_name.lower():
        texts = [f"Represent this sentence for searching relevant passages: {t}" for t in texts]

    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return vectors.tolist()


def embed_query(text: str) -> list[float]:
    """Embed a single search query. Returns one vector."""
    return embed(text)[0]


def embed_document(text: str) -> list[float]:
    """Embed a document for storage. Returns one vector."""
    model = _load_model()
    vectors = model.encode([text], normalize_embeddings=True, show_progress_bar=False)
    return vectors[0].tolist()


def get_dimension() -> int:
    """Return the embedding dimension (384 for both models)."""
    model = _load_model()
    return model.get_sentence_embedding_dimension()


def get_model_name() -> str:
    _load_model()
    return _model_name
