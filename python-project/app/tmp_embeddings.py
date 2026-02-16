"""
TMP Embedding Engine — FAISS-powered vector search for smart tool discovery.

Uses FAISS (Facebook AI Similarity Search) as the vector database for fast,
accurate nearest-neighbor search over tool embeddings.

Key improvement: Each tool gets MULTIPLE embeddings — one for the description
and one for EACH example query. So "buy bitcoin" matches directly against
"buy EURUSD" instead of a long description blob. This dramatically improves
search quality for short queries.

Supports two embedding providers:
  1. Local sentence-transformers (free, runs on CPU, no API needed)
  2. OpenAI embeddings (higher quality, requires API key)
"""

import os
import json
import logging
import numpy as np
import faiss
from typing import Optional

log = logging.getLogger("tmp-embeddings")

# ─── Configuration ───────────────────────────────────────────────────────────

EMBEDDING_PROVIDER = os.environ.get("TMP_EMBEDDING_PROVIDER", "local")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_EMBEDDING_MODEL = os.environ.get("TMP_OPENAI_MODEL", "text-embedding-3-small")
LOCAL_MODEL_NAME = os.environ.get("TMP_LOCAL_MODEL", "all-MiniLM-L6-v2")

# ─── Local Model Cache ──────────────────────────────────────────────────────

_local_model = None


def _get_local_model():
    """Lazy-load the local sentence-transformers model."""
    global _local_model
    if _local_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            log.info(f"Loading local embedding model: {LOCAL_MODEL_NAME}")
            _local_model = SentenceTransformer(LOCAL_MODEL_NAME)
            log.info("Local embedding model loaded successfully")
        except ImportError:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers\n"
                "Or set TMP_EMBEDDING_PROVIDER=openai and provide OPENAI_API_KEY"
            )
    return _local_model


# ─── FAISS Index ─────────────────────────────────────────────────────────────

class FAISSToolIndex:
    """
    FAISS-powered vector index for tool discovery.

    Each tool gets MULTIPLE entries in the index:
      - One for the full description
      - One for EACH example query (weighted higher)

    This means a short query like "buy bitcoin" gets matched against
    short example strings like "buy EURUSD" — much better similarity.
    """

    def __init__(self):
        self.index: Optional[faiss.IndexFlatIP] = None  # Inner product (cosine on normalized vecs)
        self.index_to_tool: list[dict] = []  # Maps FAISS index position → tool metadata
        self.dimension: int = 0
        self.tool_count: int = 0
        self._built = False

    def build(self, tools: list[dict]):
        """
        Build FAISS index from tool definitions.

        Each tool dict should have:
          name, description, category, tags, examples, endpoint, method, parameters
        """
        all_texts = []
        all_mappings = []  # Each entry: tool metadata dict

        for tool in tools:
            meta = {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters"),
                "category": tool.get("category"),
                "tags": tool.get("tags"),
                "examples": tool.get("examples"),
                "endpoint": tool.get("endpoint"),
                "method": tool.get("method"),
            }

            # 1) Embed the description (full context)
            desc_text = f"{tool['name']}: {tool.get('description', '')}"
            if tool.get("tags"):
                desc_text += f" [{', '.join(tool['tags'])}]"
            all_texts.append(desc_text)
            all_mappings.append(meta)

            # 2) Embed each example query INDIVIDUALLY
            # This is the key insight — short queries match short examples
            for example in (tool.get("examples") or []):
                all_texts.append(example)
                all_mappings.append(meta)

        if not all_texts:
            log.warning("No texts to index")
            return

        # Compute all embeddings in one batch
        embeddings = compute_embeddings_batch(all_texts)
        vectors = np.array(embeddings, dtype=np.float32)

        # Normalize for cosine similarity (FAISS IndexFlatIP = dot product on normalized = cosine)
        faiss.normalize_L2(vectors)

        self.dimension = vectors.shape[1]
        self.index = faiss.IndexFlatIP(self.dimension)
        self.index.add(vectors)
        self.index_to_tool = all_mappings
        self.tool_count = len(tools)
        self._built = True

        log.info(f"FAISS index built: {len(tools)} tools → {len(all_texts)} vectors ({self.dimension}D)")

    def search(self, query: str, top_k: int = 5, threshold: float = 0.15,
               category: Optional[str] = None) -> list[dict]:
        """
        Search for the most relevant tools.

        Returns deduplicated tools ranked by their BEST matching vector.
        Category filter is case-insensitive.
        """
        if not self._built or self.index is None:
            return []

        # Normalize category for case-insensitive comparison
        cat_lower = category.lower() if category else None

        # Embed the query
        q_vec = np.array([compute_embedding(query)], dtype=np.float32)
        faiss.normalize_L2(q_vec)

        # Search more results than needed since we'll deduplicate
        search_k = min(self.index.ntotal, top_k * 10)
        scores, indices = self.index.search(q_vec, search_k)

        # Deduplicate — keep the HIGHEST score per tool name
        seen = {}
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            score = float(score)
            if score < threshold:
                continue

            tool_meta = self.index_to_tool[idx]
            name = tool_meta["name"]

            # Category filter (case-insensitive)
            if cat_lower and (tool_meta.get("category") or "").lower() != cat_lower:
                continue

            if name not in seen or score > seen[name]["score"]:
                seen[name] = {**tool_meta, "score": round(score, 4)}

        # Sort by score and return top_k
        results = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    @property
    def is_built(self) -> bool:
        return self._built

    @property
    def total_vectors(self) -> int:
        return self.index.ntotal if self.index else 0


# ─── Global Index Instance ──────────────────────────────────────────────────

_faiss_index = FAISSToolIndex()


def get_faiss_index() -> FAISSToolIndex:
    """Get the global FAISS index instance."""
    return _faiss_index


def rebuild_faiss_index():
    """Rebuild the FAISS index from the database."""
    global _faiss_index
    from app.database import SessionLocal
    from app.models.tmp_tool import TMPTool

    db = SessionLocal()
    try:
        tools = db.query(TMPTool).all()
        tool_dicts = []
        for t in tools:
            tool_dicts.append({
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
                "category": t.category,
                "tags": t.tags,
                "examples": t.examples,
                "endpoint": t.endpoint,
                "method": t.method,
            })

        _faiss_index = FAISSToolIndex()
        if tool_dicts:
            _faiss_index.build(tool_dicts)
        return _faiss_index
    finally:
        db.close()


# ─── Core Embedding Functions ────────────────────────────────────────────────


def compute_embedding(text: str) -> list[float]:
    """Compute an embedding vector for the given text."""
    if not text or not text.strip():
        return []
    if EMBEDDING_PROVIDER == "openai":
        return _compute_openai_embedding(text)
    else:
        return _compute_local_embedding(text)


def compute_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Compute embeddings for multiple texts at once (more efficient)."""
    if not texts:
        return []
    if EMBEDDING_PROVIDER == "openai":
        return _compute_openai_embeddings_batch(texts)
    else:
        return _compute_local_embeddings_batch(texts)


def build_tool_embedding_text(name: str, description: str,
                               parameters: Optional[dict] = None,
                               examples: Optional[list] = None,
                               tags: Optional[list] = None,
                               category: Optional[str] = None) -> str:
    """Build the text string that will be embedded for a tool (legacy, used by seed script)."""
    parts = [f"Tool: {name}", f"Description: {description}"]
    if category:
        parts.append(f"Category: {category}")
    if tags:
        parts.append(f"Tags: {', '.join(tags)}")
    if parameters:
        param_names = list(parameters.keys()) if isinstance(parameters, dict) else []
        if param_names:
            parts.append(f"Parameters: {', '.join(param_names)}")
    if examples:
        parts.append(f"Example queries: {'; '.join(examples[:5])}")
    return "\n".join(parts)


# ─── Provider Implementations ────────────────────────────────────────────────


def _compute_local_embedding(text: str) -> list[float]:
    model = _get_local_model()
    embedding = model.encode(text, normalize_embeddings=True)
    return embedding.tolist()


def _compute_local_embeddings_batch(texts: list[str]) -> list[list[float]]:
    model = _get_local_model()
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=32)
    return [e.tolist() for e in embeddings]


def _compute_openai_embedding(text: str) -> list[float]:
    import requests
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set.")
    resp = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={"model": OPENAI_EMBEDDING_MODEL, "input": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def _compute_openai_embeddings_batch(texts: list[str]) -> list[list[float]]:
    import requests
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set.")
    resp = requests.post(
        "https://api.openai.com/v1/embeddings",
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
        json={"model": OPENAI_EMBEDDING_MODEL, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    data.sort(key=lambda x: x["index"])
    return [d["embedding"] for d in data]


# ─── Utility ─────────────────────────────────────────────────────────────────


def get_provider_info() -> dict:
    idx = get_faiss_index()
    return {
        "provider": EMBEDDING_PROVIDER,
        "model": OPENAI_EMBEDDING_MODEL if EMBEDDING_PROVIDER == "openai" else LOCAL_MODEL_NAME,
        "has_api_key": bool(OPENAI_API_KEY) if EMBEDDING_PROVIDER == "openai" else True,
        "vector_db": "FAISS",
        "index_built": idx.is_built,
        "total_vectors": idx.total_vectors,
        "tools_indexed": idx.tool_count,
    }
