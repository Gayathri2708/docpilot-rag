"""Local embeddings with fastembed (ONNX, CPU, no API key, no PyTorch).

The model is loaded lazily on first use and cached for the process lifetime.
bge models expect different handling for queries vs passages; fastembed's
query_embed / passage_embed take care of that.
"""

from functools import lru_cache

import numpy as np

from .config import settings


@lru_cache(maxsize=1)
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=settings.embedding_model)


def embed_passages(texts: list[str]) -> list[np.ndarray]:
    return [np.asarray(v, dtype=np.float32) for v in _model().passage_embed(texts)]


def embed_query(text: str) -> np.ndarray:
    return np.asarray(next(iter(_model().query_embed(text))), dtype=np.float32)
