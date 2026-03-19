import hashlib
import logging
import re
import time
from typing import Dict, List, Tuple

logger = logging.getLogger("policy_helper")

import numpy as np
from qdrant_client import QdrantClient, models as qm

from .ingest import chunk_text, doc_hash
from .settings import settings

TITLE_HINTS = {
    "Returns_and_Refunds.md": "returns",
    "Warranty_Policy.md": "warranty",
    "Delivery_and_Shipping.md": "shipping",
    "Product_Catalog.md": "catalog",
    "Compliance_Notes.md": "compliance",
}


def _normalize_token(token: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "", token.lower())
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("ing"):
        return token[:-3]
    if len(token) > 3 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _tokenize(text: str) -> List[str]:
    return [normalized for raw in re.split(r"\W+", text) if (normalized := _normalize_token(raw))]


def _norm_set(words: set) -> set:
    return {_normalize_token(w) for w in words} - {""}


POLICY_HINTS = {
    "returns": _norm_set({"return", "refund", "refunds", "changeofmind", "damaged", "defective"}),
    "warranty": _norm_set({"warranty", "damaged", "defective", "misuse", "repair", "coverage"}),
    "shipping": _norm_set({"shipping", "delivery", "sla", "courier", "bulky", "malaysia", "east", "west"}),
    "catalog": _norm_set({"sku", "product", "price", "category", "availability", "warranty"}),
    "compliance": _norm_set({"pdpa", "mask", "privacy", "identifier", "address", "ic"}),
}


def _ngrams(tokens: List[str], n: int = 2) -> List[str]:
    if len(tokens) < n:
        return []
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def _keyword_overlap(query_tokens: List[str], text_tokens: List[str]) -> float:
    if not query_tokens or not text_tokens:
        return 0.0
    query_set = set(query_tokens)
    text_set = set(text_tokens)
    return len(query_set & text_set) / max(len(query_set), 1)


def _phrase_overlap(query_tokens: List[str], text_tokens: List[str]) -> float:
    query_phrases = set(_ngrams(query_tokens, 2))
    text_phrases = set(_ngrams(text_tokens, 2))
    if not query_phrases or not text_phrases:
        return 0.0
    return len(query_phrases & text_phrases) / max(len(query_phrases), 1)


def _intent_boost(query_tokens: List[str], meta: Dict) -> float:
    hint_group = TITLE_HINTS.get(meta.get("title", ""))
    if not hint_group:
        return 0.0
    matched = POLICY_HINTS[hint_group] & set(query_tokens)
    if not matched:
        return 0.0
    return min(0.22, 0.06 * len(matched))


def _mmr_select(scored: List[Tuple[float, Dict]], k: int, lambda_mult: float) -> List[Tuple[float, Dict]]:
    selected: List[Tuple[float, Dict]] = []
    candidates = list(scored)

    while candidates and len(selected) < k:
        best_idx = 0
        best_score = float("-inf")
        for idx, (relevance, meta) in enumerate(candidates):
            diversity_penalty = 0.0
            vector = meta.get("_vector")
            if selected and vector is not None:
                diversity_penalty = max(
                    float(np.dot(vector, chosen_meta["_vector"]))
                    for _, chosen_meta in selected
                    if chosen_meta.get("_vector") is not None
                )
            mmr_score = (lambda_mult * relevance) - ((1.0 - lambda_mult) * diversity_penalty)
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx
        selected.append(candidates.pop(best_idx))
    return selected


def _best_excerpt(text: str, query_tokens: List[str], max_chars: int = 220) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", compact)
    if not sentences:
        sentences = [compact]
    ranked = sorted(
        sentences,
        key=lambda sentence: (
            _phrase_overlap(query_tokens, _tokenize(sentence)),
            _keyword_overlap(query_tokens, _tokenize(sentence)),
            len(sentence),
        ),
        reverse=True,
    )
    excerpt = ranked[0][:max_chars].strip()
    return excerpt + ("..." if len(ranked[0]) > max_chars else "")


def _mask_sensitive_text(text: str) -> str:
    text = re.sub(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[redacted-email]", text, flags=re.I)
    text = re.sub(r"\b\d{6}-\d{2}-\d{4}\b", "[redacted-ic]", text)
    text = re.sub(r"\b\d{12}\b", "[redacted-ic]", text)
    text = re.sub(r"\b(?:\+?6?0?1\d{1}[- ]?\d{3,4}[- ]?\d{4})\b", "[redacted-phone]", text)
    text = re.sub(
        r"\b\d{1,5}\s+(?:[A-Za-z0-9.,'/-]+\s+)?(?:Street|St|Road|Rd|Jalan|Lorong|Avenue|Ave|Lane|Ln|Drive|Dr|Taman)\b[^\n]*",
        "[redacted-address]",
        text,
        flags=re.I,
    )
    return text


def sanitize_public_text(text: str) -> str:
    return _mask_sensitive_text(text) if settings.mask_sensitive_output else text


class LocalEmbedder:
    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype="float32")
        tokens = _tokenize(text)
        for token in tokens + _ngrams(tokens, 2):
            h = hashlib.sha1(token.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            v[idx] += 1.0
        v = v / (np.linalg.norm(v) + 1e-9)
        return v


class InMemoryStore:
    def __init__(self, dim: int = 384):
        self.dim = dim
        self.vecs: List[np.ndarray] = []
        self.meta: List[Dict] = []
        self._hashes = set()

    def upsert(self, vectors: List[np.ndarray], metadatas: List[Dict]):
        for vector, metadata in zip(vectors, metadatas):
            hsh = metadata.get("hash")
            if hsh and hsh in self._hashes:
                continue
            self.vecs.append(vector.astype("float32"))
            self.meta.append(metadata)
            if hsh:
                self._hashes.add(hsh)

    def search(self, query: np.ndarray, k: int = 4) -> List[Tuple[float, Dict]]:
        if not self.vecs:
            return []
        matrix = np.vstack(self.vecs)
        q = query.reshape(1, -1)
        sims = (matrix @ q.T).ravel() / (np.linalg.norm(matrix, axis=1) * (np.linalg.norm(q) + 1e-9) + 1e-9)
        idx = np.argsort(-sims)[:k]
        out = []
        for i in idx:
            meta = dict(self.meta[i])
            meta["_vector"] = self.vecs[i]
            out.append((float(sims[i]), meta))
        return out


class QdrantStore:
    def __init__(self, collection: str, dim: int = 384, retries: int = 5, retry_delay: float = 2.0):
        self.collection = collection
        self.dim = dim
        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(1, retries + 1):
            try:
                self.client = QdrantClient(url=settings.qdrant_host, timeout=10.0)
                self._ensure_collection()
                return
            except Exception as exc:
                last_exc = exc
                if attempt < retries:
                    logger.info("Qdrant not ready (attempt %d/%d): %s — retrying in %.0fs", attempt, retries, exc, retry_delay)
                    time.sleep(retry_delay)
        raise last_exc

    def _ensure_collection(self):
        existing = {c.name for c in self.client.get_collections().collections}
        if self.collection not in existing:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=qm.VectorParams(size=self.dim, distance=qm.Distance.COSINE),
            )

    def upsert(self, vectors: List[np.ndarray], metadatas: List[Dict]):
        points = []
        for idx, (vector, metadata) in enumerate(zip(vectors, metadatas)):
            point_id = metadata.get("id") or metadata.get("hash") or idx
            if isinstance(point_id, str):
                point_id = int(hashlib.sha1(point_id.encode("utf-8")).hexdigest()[:16], 16)
            points.append(qm.PointStruct(id=point_id, vector=vector.tolist(), payload=metadata))
        self.client.upsert(collection_name=self.collection, points=points)

    def search(self, query: np.ndarray, k: int = 4) -> List[Tuple[float, Dict]]:
        res = self.client.search(
            collection_name=self.collection,
            query_vector=query.tolist(),
            limit=k,
            with_payload=True,
            with_vectors=True,
        )
        out = []
        for item in res:
            payload = dict(item.payload)
            if item.vector is not None:
                payload["_vector"] = np.array(item.vector, dtype="float32")
            out.append((float(item.score), payload))
        return out


class StubLLM:
    def generate(self, query: str, contexts: List[Dict]) -> str:
        if not contexts:
            return "I could not find a grounded answer in the indexed documents."

        query_tokens = _tokenize(query)
        sections = []
        for ctx in contexts[:3]:
            excerpt = _best_excerpt(ctx.get("text", ""), query_tokens)
            if excerpt:
                label = ctx.get("section") or ctx.get("title") or "Source"
                sections.append(f"- {label}: {excerpt}")

        lines = ["Grounded answer:"]
        lines.extend(sections or ["- I found relevant policy sections, but they need manual review."])
        lines.append("Sources:")
        for ctx in contexts:
            section = ctx.get("section") or "Section"
            lines.append(f"- {ctx.get('title')} — {section}")
        return "\n".join(lines)


class OpenRouterLLM:
    def __init__(self, api_key: str, model: str = "openai/gpt-4o-mini"):
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
        self.model = model

    def generate(self, query: str, contexts: List[Dict]) -> str:
        prompt = (
            "You are a helpful company policy assistant.\n"
            "Answer only from the provided sources.\n"
            "Be concise, accurate, and cite source title plus section when relevant.\n"
            "If the sources are insufficient, say so.\n\n"
            f"Question: {query}\n\nSources:\n"
        )
        for ctx in contexts:
            prompt += f"- {ctx.get('title')} | {ctx.get('section')}\n{ctx.get('text')[:700]}\n---\n"
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return resp.choices[0].message.content


class Metrics:
    def __init__(self):
        self.t_retrieval: List[float] = []
        self.t_generation: List[float] = []
        self.total_queries: int = 0

    def add_retrieval(self, ms: float):
        self.t_retrieval.append(ms)

    def add_generation(self, ms: float):
        self.t_generation.append(ms)
        self.total_queries += 1

    def summary(self) -> Dict:
        avg_r = sum(self.t_retrieval) / len(self.t_retrieval) if self.t_retrieval else 0.0
        avg_g = sum(self.t_generation) / len(self.t_generation) if self.t_generation else 0.0
        p95_r = sorted(self.t_retrieval)[int(len(self.t_retrieval) * 0.95)] if self.t_retrieval else 0.0
        p95_g = sorted(self.t_generation)[int(len(self.t_generation) * 0.95)] if self.t_generation else 0.0
        return {
            "avg_retrieval_latency_ms": round(avg_r, 2),
            "avg_generation_latency_ms": round(avg_g, 2),
            "p95_retrieval_latency_ms": round(p95_r, 2),
            "p95_generation_latency_ms": round(p95_g, 2),
            "total_queries": self.total_queries,
        }


class RAGEngine:
    def __init__(self):
        self.embedder = LocalEmbedder(dim=384)
        if settings.vector_store == "qdrant":
            try:
                self.store = QdrantStore(collection=settings.collection_name, dim=384)
            except Exception:
                self.store = InMemoryStore(dim=384)
        else:
            self.store = InMemoryStore(dim=384)

        if settings.llm_provider == "openrouter" and settings.openrouter_api_key:
            try:
                self.llm = OpenRouterLLM(
                    api_key=settings.openrouter_api_key,
                    model=settings.llm_model,
                )
                self.llm_name = f"openrouter:{settings.llm_model}"
            except Exception:
                self.llm = StubLLM()
                self.llm_name = "stub"
        else:
            self.llm = StubLLM()
            self.llm_name = "stub"

        self.metrics = Metrics()
        self._doc_titles = set()
        self._chunk_count = 0

    def ingest_chunks(self, chunks: List[Dict]) -> Tuple[int, int]:
        vectors = []
        metas = []
        doc_titles_before = set(self._doc_titles)

        for chunk in chunks:
            text = chunk["text"]
            hsh = doc_hash(text)
            section = chunk.get("section")
            retrieval_text = f"{chunk['title']} {section or ''} {text}"
            meta = {
                "id": hsh,
                "hash": hsh,
                "title": chunk["title"],
                "section": section,
                "text": text,
                "tokens": _tokenize(retrieval_text),
                "phrases": _ngrams(_tokenize(retrieval_text), 2),
            }
            vectors.append(self.embedder.embed(retrieval_text))
            metas.append(meta)
            self._doc_titles.add(chunk["title"])

        self.store.upsert(vectors, metas)
        inserted = len(metas)
        self._chunk_count += inserted
        return (len(self._doc_titles) - len(doc_titles_before), inserted)

    def retrieve(self, query: str, k: int = 4) -> List[Dict]:
        t0 = time.time()
        query_tokens = _tokenize(query)
        query_text = " ".join(query_tokens)
        qv = self.embedder.embed(query_text or query)
        candidates = self.store.search(qv, k=max(k * 4, 12))

        rescored: List[Tuple[float, Dict]] = []
        for dense_score, meta in candidates:
            lexical_score = _keyword_overlap(query_tokens, meta.get("tokens", []))
            phrase_score = _phrase_overlap(query_tokens, meta.get("tokens", []))
            title_tokens = _tokenize(f"{meta.get('title', '')} {meta.get('section') or ''}")
            title_score = _keyword_overlap(query_tokens, title_tokens)
            policy_boost = _intent_boost(query_tokens, meta)
            final_score = (
                (0.42 * dense_score)
                + (0.30 * lexical_score)
                + (0.18 * phrase_score)
                + (0.10 * title_score)
                + policy_boost
            )
            rescored.append((final_score, meta))

        rescored.sort(key=lambda item: item[0], reverse=True)
        filtered = rescored
        if rescored:
            top_score = rescored[0][0]
            filtered = [
                item for item in rescored
                if item[0] >= max(settings.retrieval_score_floor, top_score * 0.42)
            ] or rescored[: min(2, len(rescored))]

        selected = _mmr_select(filtered, k=k, lambda_mult=settings.mmr_lambda)
        self.metrics.add_retrieval((time.time() - t0) * 1000.0)

        output = []
        for score, meta in selected:
            cleaned = dict(meta)
            cleaned.pop("_vector", None)
            cleaned["_score"] = round(score, 4)
            output.append(cleaned)
        return output

    def generate(self, query: str, contexts: List[Dict]) -> str:
        t0 = time.time()
        answer = self.llm.generate(query, contexts)
        self.metrics.add_generation((time.time() - t0) * 1000.0)
        return sanitize_public_text(answer)

    def stats(self) -> Dict:
        metrics = self.metrics.summary()
        metrics.update(
            {
                "total_docs": len(self._doc_titles),
                "total_chunks": self._chunk_count,
                "embedding_model": settings.embedding_model,
                "llm_model": self.llm_name,
            }
        )
        return metrics


def build_chunks_from_docs(docs: List[Dict], chunk_size: int, chunk_overlap: int) -> List[Dict]:
    chunks = []
    for doc in docs:
        for chunk in chunk_text(doc["text"], chunk_size, chunk_overlap):
            chunks.append(
                {
                    "title": doc["title"],
                    "section": doc.get("section"),
                    "text": chunk,
                }
            )
    return chunks
