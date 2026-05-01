from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from threading import Lock

import numpy as np

from jarvis.config import Settings


class HashEmbeddingModel:
    """
    Lightweight local embedding model based on a hashing trick.
    Deterministic and fast, suitable for local-first semantic recall.
    """

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    def embed(self, text: str) -> np.ndarray:
        vec = np.zeros(self._dim, dtype=np.float32)
        for token in re.findall(r"[a-zA-Z0-9_]+", text.lower()):
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % self._dim
            sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.astype(np.float32)


class SentenceTransformerEmbeddingModel:
    """
    Optional real embedding adapter. It is loaded only when configured so the
    base local assistant remains lightweight.
    """

    def __init__(self, model_name: str, dim: int) -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore

        self._model = SentenceTransformer(model_name)
        self._dim = dim

    def embed(self, text: str) -> np.ndarray:
        vec = np.array(self._model.encode(text, normalize_embeddings=True), dtype=np.float32)
        if vec.shape[0] == self._dim:
            return vec
        if vec.shape[0] > self._dim:
            clipped = vec[: self._dim]
            norm = np.linalg.norm(clipped)
            return (clipped / norm).astype(np.float32) if norm > 0 else clipped.astype(np.float32)
        padded = np.zeros(self._dim, dtype=np.float32)
        padded[: vec.shape[0]] = vec
        norm = np.linalg.norm(padded)
        return (padded / norm).astype(np.float32) if norm > 0 else padded


class VectorMemoryStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._embedder = self._build_embedder(settings)
        self._ids_path = Path(settings.faiss_ids_path)
        self._index_path = Path(settings.faiss_index_path)
        self._fallback_matrix_path = self._index_path.with_suffix(".npy")
        self._lock = Lock()
        self._ids: list[int] = []
        self._use_faiss = False
        self._faiss = None

        self._load_ids()
        self._init_index()

    def _build_embedder(self, settings: Settings):
        if settings.embedding_provider.lower() in {"sentence_transformers", "sentence-transformer", "sbert"}:
            try:
                return SentenceTransformerEmbeddingModel(settings.embedding_model_name, settings.vector_dim)
            except Exception:
                return HashEmbeddingModel(dim=settings.vector_dim)
        return HashEmbeddingModel(dim=settings.vector_dim)

    def _init_index(self) -> None:
        try:
            import faiss  # type: ignore

            self._faiss = faiss
            self._use_faiss = True
            if self._index_path.exists():
                self._index = faiss.read_index(str(self._index_path))
            else:
                self._index = faiss.IndexFlatIP(self._settings.vector_dim)
            # Keep id list in sync with index size.
            if len(self._ids) > self._index.ntotal:
                self._ids = self._ids[: self._index.ntotal]
                self._save_ids()
            elif len(self._ids) < self._index.ntotal:
                # Best-effort recovery if ids file is behind index content.
                missing = self._index.ntotal - len(self._ids)
                self._ids.extend([-1] * missing)
                self._save_ids()
        except Exception:
            self._use_faiss = False
            if self._fallback_matrix_path.exists():
                self._vectors = np.load(self._fallback_matrix_path)
            else:
                self._vectors = np.zeros((0, self._settings.vector_dim), dtype=np.float32)
            if len(self._ids) > len(self._vectors):
                self._ids = self._ids[: len(self._vectors)]
                self._save_ids()

    def _load_ids(self) -> None:
        if not self._ids_path.exists():
            self._ids = []
            return
        try:
            self._ids = [int(x) for x in json.loads(self._ids_path.read_text(encoding="utf-8"))]
        except Exception:
            self._ids = []

    def _save_ids(self) -> None:
        self._ids_path.write_text(json.dumps(self._ids), encoding="utf-8")

    def _save_index(self) -> None:
        if self._use_faiss:
            assert self._faiss is not None
            self._faiss.write_index(self._index, str(self._index_path))
        else:
            np.save(self._fallback_matrix_path, self._vectors)
        self._save_ids()

    def add(self, *, vector_id: int, text: str) -> None:
        embedding = self._embedder.embed(text).astype(np.float32)
        with self._lock:
            if self._use_faiss:
                self._index.add(np.array([embedding], dtype=np.float32))
            else:
                self._vectors = np.vstack([self._vectors, embedding])
            self._ids.append(vector_id)
            self._save_index()

    def search(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        if not query.strip():
            return []
        q = self._embedder.embed(query)
        with self._lock:
            if not self._ids:
                return []
            limit = min(top_k, len(self._ids))
            if self._use_faiss:
                scores, indices = self._index.search(np.array([q], dtype=np.float32), limit)
                pairs = []
                for idx, score in zip(indices[0].tolist(), scores[0].tolist()):
                    if idx < 0 or idx >= len(self._ids):
                        continue
                    vector_id = self._ids[idx]
                    if vector_id < 0:
                        continue
                    pairs.append((vector_id, float(score)))
                return pairs
            sims = np.dot(self._vectors, q)
            ranked = np.argsort(-sims)[:limit]
            return [(self._ids[int(i)], float(sims[int(i)])) for i in ranked if self._ids[int(i)] >= 0]

    @staticmethod
    def should_store_semantic(text: str) -> bool:
        cleaned = text.strip().lower()
        if not cleaned:
            return False
        trivial = {"ok", "okay", "thanks", "thank you", "yes", "no", "hi", "hello"}
        if cleaned in trivial:
            return False
        if len(cleaned) < 12:
            return False
        token_count = len(re.findall(r"[a-zA-Z0-9_]+", cleaned))
        return token_count >= 4
