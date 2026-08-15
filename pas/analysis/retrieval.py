"""Hybrid semantic + lexical retrieval (spec 40).

Two ranking signals, combined:

* **BM25** over the claim text. Catches exact terminology — product names,
  "SOC 2", "SAML" — which embeddings blur together.
* **Cosine similarity** over embeddings. Catches paraphrase — "who might eat our
  lunch" matching a claim about competitive threat — which keywords miss.

Neither alone is adequate, and the failure modes are complementary, so the score
is a weighted blend of both. Embeddings are cached by content hash, so the cost
is paid once per claim rather than once per question, and a provider failure
degrades to lexical-only rather than breaking search.
"""

from __future__ import annotations

import array
import hashlib
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

#: Blend weights. Lexical is weighted slightly higher because this corpus is
#: dense with proper nouns and compliance acronyms, where exact match matters.
LEXICAL_WEIGHT = 0.55
SEMANTIC_WEIGHT = 0.45

#: Standard BM25 parameters.
BM25_K1 = 1.5
BM25_B = 0.75

#: Embedding requests are batched; too large a batch risks a provider limit.
EMBED_BATCH_SIZE = 96

_STOPWORDS = frozenset(
    """the a an and or but of to in for on with is are was were be been am i my we our you your
    it its this that these those what which who whom how why when where should would could can
    do does did have has had will shall me us them they he she at by from as if then than so
    about into over under again more most other some such no nor not only own same too very
    s t just don now""".split()
)


def tokenise(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) > 1 and token not in _STOPWORDS
    ]


def content_hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", (text or "").strip().lower()).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Vector serialisation
# ---------------------------------------------------------------------------


def pack_vector(vector: Sequence[float]) -> bytes:
    """Store as float32 — half the size of float64 at no meaningful precision cost."""
    return array.array("f", vector).tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    values = array.array("f")
    values.frombytes(blob)
    return list(values)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity, guarding against zero vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ---------------------------------------------------------------------------
# BM25
# ---------------------------------------------------------------------------


@dataclass
class BM25Index:
    """A small in-memory BM25 index.

    Rebuilt per query over a few hundred claims, which is fast enough that
    persisting it would add complexity for no gain.
    """

    documents: list[list[str]] = field(default_factory=list)
    doc_frequencies: Counter = field(default_factory=Counter)
    average_length: float = 0.0

    @classmethod
    def build(cls, texts: Iterable[str]) -> "BM25Index":
        documents = [tokenise(text) for text in texts]
        frequencies: Counter = Counter()
        for tokens in documents:
            frequencies.update(set(tokens))
        total = sum(len(tokens) for tokens in documents)
        return cls(
            documents=documents,
            doc_frequencies=frequencies,
            average_length=(total / len(documents)) if documents else 0.0,
        )

    def score(self, query: str, index: int) -> float:
        if index >= len(self.documents):
            return 0.0
        tokens = self.documents[index]
        if not tokens:
            return 0.0

        counts = Counter(tokens)
        length = len(tokens)
        total_docs = len(self.documents)
        score = 0.0

        for term in set(tokenise(query)):
            frequency = counts.get(term, 0)
            if frequency == 0:
                continue
            containing = self.doc_frequencies.get(term, 0)
            # Standard BM25 IDF with the +1 smoothing that keeps it non-negative.
            idf = math.log(1 + (total_docs - containing + 0.5) / (containing + 0.5))
            denominator = frequency + BM25_K1 * (
                1 - BM25_B + BM25_B * (length / (self.average_length or 1))
            )
            score += idf * (frequency * (BM25_K1 + 1)) / denominator
        return score


def normalise_scores(scores: list[float]) -> list[float]:
    """Scale to 0-1 so lexical and semantic scores are comparable."""
    if not scores:
        return []
    highest = max(scores)
    lowest = min(scores)
    span = highest - lowest
    if span <= 0:
        return [1.0 if highest > 0 else 0.0 for _ in scores]
    return [(score - lowest) / span for score in scores]


# ---------------------------------------------------------------------------
# Hybrid retriever
# ---------------------------------------------------------------------------


@dataclass
class Scored:
    item: dict[str, Any]
    score: float
    lexical: float
    semantic: float


class HybridRetriever:
    """Ranks evidence by blended lexical and semantic similarity."""

    def __init__(self, conn, *, config, provider, workspace_id: str):
        self._conn = conn
        self._config = config
        self._provider = provider
        self._workspace_id = workspace_id

    # -- embedding cache ---------------------------------------------------

    def _cached_vectors(self, hashes: list[str]) -> dict[str, list[float]]:
        if not hashes:
            return {}
        placeholders = ",".join("?" * len(hashes))
        rows = self._conn.execute(
            f"SELECT content_hash, vector FROM embeddings"
            f" WHERE model = ? AND content_hash IN ({placeholders})",
            [self._config.embedding_model, *hashes],
        ).fetchall()
        return {row["content_hash"]: unpack_vector(row["vector"]) for row in rows}

    def _store_vectors(self, pairs: list[tuple[str, str, list[float]]]) -> None:
        from ..storage.repositories import new_id, utcnow

        for digest, text, vector in pairs:
            self._conn.execute(
                "INSERT OR IGNORE INTO embeddings (id, workspace_id, model, content_hash,"
                " dim, vector, preview, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    new_id("emb"),
                    self._workspace_id,
                    self._config.embedding_model,
                    digest,
                    len(vector),
                    pack_vector(vector),
                    text[:200],
                    utcnow(),
                ),
            )
        self._conn.commit()

    def embed_texts(self, texts: list[str], *, analysis_id: str | None = None) -> dict[str, list[float]]:
        """Return a hash -> vector map, embedding only what is not cached."""
        from ..storage import repositories as repo

        digests = {text: content_hash(text) for text in texts}
        cached = self._cached_vectors(sorted(set(digests.values())))

        missing = [text for text, digest in digests.items() if digest not in cached]
        # Deduplicate: the same claim text embedded twice is wasted spend.
        missing = list(dict.fromkeys(missing))

        for start in range(0, len(missing), EMBED_BATCH_SIZE):
            batch = missing[start : start + EMBED_BATCH_SIZE]
            try:
                vectors, usage = self._provider.embed(
                    model=self._config.embedding_model, texts=batch
                )
            except Exception as exc:
                # Degrade to lexical-only rather than failing the question.
                logger.warning("Embedding failed, falling back to lexical: %s", exc)
                return cached

            self._store_vectors(
                [(digests[text], text, vector) for text, vector in zip(batch, vectors)]
            )
            for text, vector in zip(batch, vectors):
                cached[digests[text]] = vector

            repo.record_usage(
                self._conn,
                workspace_id=self._workspace_id,
                analysis_id=analysis_id,
                agent_run_id=None,
                provider=usage.provider,
                model=usage.model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=0,
                total_tokens=usage.total_tokens,
                cost_usd=usage.cost_usd,
                latency_ms=usage.latency_ms,
            )

        return cached

    # -- ranking -----------------------------------------------------------

    def rank(
        self,
        question: str,
        items: list[dict[str, Any]],
        *,
        limit: int = 24,
        analysis_id: str | None = None,
    ) -> list[Scored]:
        """Rank items against the question, best first."""
        if not items:
            return []

        texts = [f"{item.get('claim', '')} {item.get('detail', '')}".strip() for item in items]

        lexical_index = BM25Index.build(texts)
        lexical_raw = [lexical_index.score(question, i) for i in range(len(items))]
        lexical = normalise_scores(lexical_raw)

        semantic = [0.0] * len(items)
        if self._config.embeddings_enabled and self._config.is_configured:
            vectors = self.embed_texts(texts + [question], analysis_id=analysis_id)
            query_vector = vectors.get(content_hash(question))
            if query_vector:
                raw = []
                for text in texts:
                    vector = vectors.get(content_hash(text))
                    raw.append(cosine(query_vector, vector) if vector else 0.0)
                # Cosine over these embeddings clusters around 0.1-0.6, so
                # normalising spreads the range that actually discriminates.
                semantic = normalise_scores(raw)

        scored: list[Scored] = []
        for index, item in enumerate(items):
            # Evidence grade and confidence still matter: a verified fact should
            # outrank a hypothesis of equal textual relevance.
            weight = {
                "verified_fact": 1.25,
                "strong_inference": 1.12,
                "user_supplied": 1.18,
                "weak_inference": 0.92,
                "ai_hypothesis": 0.85,
            }.get(item.get("grade", ""), 1.0)
            confidence = 0.6 + 0.4 * float(item.get("confidence", 0.5) or 0.5)

            blended = (
                LEXICAL_WEIGHT * lexical[index] + SEMANTIC_WEIGHT * semantic[index]
            ) * weight * confidence

            scored.append(
                Scored(
                    item=item,
                    score=blended,
                    lexical=lexical[index],
                    semantic=semantic[index],
                )
            )

        scored.sort(key=lambda s: s.score, reverse=True)
        return [entry for entry in scored if entry.score > 0][:limit]

    def stats(self) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(vector)), 0) AS bytes"
            " FROM embeddings WHERE workspace_id = ?",
            (self._workspace_id,),
        ).fetchone()
        return {
            "cached_vectors": row["n"],
            "cache_bytes": row["bytes"],
            "model": self._config.embedding_model,
            "enabled": self._config.embeddings_enabled,
        }
