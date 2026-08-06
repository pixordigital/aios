"""Memory manager — working buffer → summary → vector retrieval tiers.

AIOS-inspired pipeline: extractor → injector → formatter → write barrier.

Tier 1: in-memory working buffer (last N messages)
Tier 2: periodic LLM-generated conversation summaries stored in DB
Tier 3: vector store for semantic search across all memories
"""

import json
import logging
import math
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import select

from aios.db.backend import DatabaseBackend

from aios.config import settings
from aios.db.models import Message

logger = logging.getLogger(__name__)

# ponytail: lightweight sqlite + brute-force for vector search. Swap for pgvector/FAISS at >10k vectors.
_VEC_DB: dict[str, sqlite3.Connection] = {}
_EMBED_DIM = 384  # matches all-MiniLM-L6-v2 if installed


def _vec_db(agent_id: str) -> sqlite3.Connection:
    """Lazy-init per-agent vector store with FTS5."""
    if agent_id not in _VEC_DB:
        db_path = Path(settings.app_data_dir) / "vectors" / f"{agent_id}.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, embedding BLOB, content TEXT, created_at TEXT)")
        # FTS5 for full-text search alongside vector search
        try:
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(id, content, content=memories, content_rowid=rowid)")
        except sqlite3.OperationalError:
            pass  # FTS5 already exists
        _VEC_DB[agent_id] = conn
    return _VEC_DB[agent_id]


# ─── Embedding engine ───

_SENTENCE_TRANSFORMER = None  # lazy-loaded singleton


def _load_sentence_transformer():
    """Try loading sentence-transformers. Returns None if not installed."""
    global _SENTENCE_TRANSFORMER
    if _SENTENCE_TRANSFORMER is None:
        try:
            from sentence_transformers import SentenceTransformer
            _SENTENCE_TRANSFORMER = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Loaded sentence-transformers model for embeddings")
        except ImportError:
            _SENTENCE_TRANSFORMER = False  # sentinel
    return _SENTENCE_TRANSFORMER if _SENTENCE_TRANSFORMER is not False else None


def _bow_embed(text: str) -> list[float]:
    """Bag-of-ngrams embedding — no deps, captures semantic signal better than SHA256.

    Uses character n-gram (2-4) frequencies with TF-IDF-like weighting.
    Deterministic, fast, 384-dim output for cosine sim compatibility.
    """
    text = text.lower()
    ngrams: Counter = Counter()
    for n in (2, 3, 4):
        for i in range(len(text) - n + 1):
            ngrams[text[i:i+n]] += 1

    if not ngrams:
        return [0.0] * _EMBED_DIM

    max_freq = max(ngrams.values())
    total = sum(ngrams.values())
    vec = [0.0] * _EMBED_DIM
    for gram, count in ngrams.items():
        idx = hash(gram) % _EMBED_DIM
        tf = count / max_freq
        idf = math.log1p(total / (count + 1))
        vec[idx] += tf * idf

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def _embed(text: str) -> list[float]:
    """Get embedding vector for text. Uses sentence-transformers if available, else BOW fallback."""
    st = _load_sentence_transformer()
    if st:
        return st.encode(text, normalize_embeddings=True).tolist()
    return _bow_embed(text)


# ─── Memory Pipeline ───

class Extractor:
    """Extract key information from conversation messages for memory.

    Three-part memory: classify into skill (how-to), fact (user preference/
    identity), or rubric (expectation/standard). Stores type in DB Memory.type.
    """

    KEY_PATTERNS = ["remember", "note", "important", "my name is", "i am",
                    "don't forget", "save this", "key fact", "user prefers"]
    SKILL_PATTERNS = ["always", "never", "whenever", "how to", "steps", "workflow",
                      "you should", "make sure to", "remember to"]
    RUBRIC_PATTERNS = ["should", "must", "expected", "standard", "quality",
                       "i expect", "i want you to", "make sure"]

    def extract(self, role: str, content: str) -> dict | None:
        """Return {type, content} extracted info or None if nothing notable."""
        if role != "user":
            return None
        lower = content.lower()
        # require an explicit memory signal (remember/note/prefers...) first
        triggered = any(p in lower for p in self.KEY_PATTERNS)
        if not triggered:
            return None
        memory_type = "fact"
        for pattern in self.SKILL_PATTERNS:
            if pattern in lower:
                memory_type = "skill"
                break
        for pattern in self.RUBRIC_PATTERNS:
            if pattern in lower:
                memory_type = "rubric"
                break
        return {"type": memory_type, "content": content[:300]}


class Injector:
    """Decide what memories to inject into agent context."""

    def select(self, memories: list[dict], recent_top_k: int = 3,
               score_threshold: float = 0.1) -> list[dict]:
        """Select best memories for injection. Filters by score, caps at top_k."""
        scored = [m for m in memories if m.get("score", 0) >= score_threshold]
        scored.sort(key=lambda m: -m.get("score", 0))
        return scored[:recent_top_k]


class Formatter:
    """Render selected memories as system prompt additions."""

    def format(self, memories: list[dict]) -> str:
        if not memories:
            return ""
        lines = []
        for m in memories:
            score = m.get("score", 0)
            content = m.get("content", "")[:200]
            lines.append(f"- [s={score:.2f}] {content}")
        return "Relevant past context:\n" + "\n".join(lines)


class WriteBarrier:
    """Rate-limit and batch memory writes to avoid thrashing.

    ponytail: simple time-based throttle. Upgrade to batch coalescing
    when write throughput grows.
    """

    def __init__(self, min_interval: float = 2.0):
        self._last_write: dict[str, float] = {}
        self._min_interval = min_interval

    def allow(self, key: str) -> bool:
        """Check if write is allowed (not rate-limited)."""
        now = time.time()
        last = self._last_write.get(key, 0.0)
        if now - last < self._min_interval:
            return False
        self._last_write[key] = now
        return True


# ─── MemoryManager ───

class MemoryManager:
    """Three-tier memory with AIOS pipeline: extract → inject → format → write barrier."""

    def __init__(self, agent_id: str, llm_provider=None):
        self.agent_id = agent_id
        self._llm = llm_provider
        self._buffers: dict[str, list[dict]] = defaultdict(list)
        self._loaded: set[str] = set()
        self._summary_interval = 20
        # pipeline stages
        self.extractor = Extractor()
        self.injector = Injector()
        self.formatter = Formatter()
        self.write_barrier = WriteBarrier(min_interval=2.0)

    async def add(self, conversation_id: str, role: str, content: str) -> None:
        if not content:
            return
        self._buffers[conversation_id].append({"role": role, "content": content})

        # extract key info for long-term memory (three-part: skill/fact/rubric)
        extracted = self.extractor.extract(role, content)
        if extracted and self.write_barrier.allow(f"extract:{conversation_id}"):
            mtype = extracted["type"]
            await self._store_vector(f"[{mtype}] {extracted['content']}")

        # tier 1: sliding window
        max_short = 50
        if len(self._buffers[conversation_id]) > max_short:
            removed = self._buffers[conversation_id].pop(0)
            # tier 2: auto-summarize when buffer fills
            if len(self._buffers[conversation_id]) % self._summary_interval == 0:
                await self._summarize(conversation_id, removed["content"])

    async def get_recent(self, conversation_id: str, limit: int = 20,
                         db: DatabaseBackend | None = None) -> list[dict]:
        if conversation_id not in self._loaded and db is not None:
            await self._load_from_db(conversation_id, db)
        return self._buffers.get(conversation_id, [])[-limit:]

    async def get_context_injections(self, query: str, top_k: int = 3) -> list[dict]:
        """Get formatted memory injections for context building.

        Runs the full pipeline: hybrid search → injector select → formatter render.
        Returns list of system-prompt-style dicts to append to context.
        """
        similar = await self.search_hybrid(query, top_k=top_k * 2)
        selected = self.injector.select(similar, recent_top_k=top_k)
        formatted = self.formatter.format(selected)
        if formatted:
            return [{"role": "system", "content": formatted}]
        return []

    async def search_similar(self, query: str, top_k: int = 5) -> list[dict]:
        """Tier 3: vector similarity search across stored memories."""
        vec = _embed(query)
        conn = _vec_db(self.agent_id)
        rows = conn.execute("SELECT id, content, embedding FROM memories ORDER BY rowid").fetchall()
        scored = []
        for rid, content, emb_bytes in rows:
            stored = json.loads(emb_bytes)
            dot = sum(a * b for a, b in zip(vec, stored))
            norm_self = sum(v * v for v in vec) ** 0.5 or 1
            norm_stored = sum(v * v for v in stored) ** 0.5 or 1
            sim = dot / (norm_self * norm_stored)
            scored.append((sim, rid, content))
        scored.sort(key=lambda x: -x[0])
        return [{"id": r[1], "content": r[2], "score": round(r[0], 3)} for r in scored[:top_k]]

    async def search_fts(self, query: str, top_k: int = 5) -> list[dict]:
        """FTS5 full-text search for exact keyword matches."""
        conn = _vec_db(self.agent_id)
        try:
            rows = conn.execute(
                "SELECT id, content, rank FROM memories_fts WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, top_k),
            ).fetchall()
            return [{"id": r[0], "content": r[1], "score": abs(r[2])} for r in rows]
        except sqlite3.OperationalError:
            return []

    async def search_hybrid(self, query: str, top_k: int = 5) -> list[dict]:
        """Hybrid search: merge FTS5 exact + vector semantic results."""
        vec_results = await self.search_similar(query, top_k=top_k)
        fts_results = await self.search_fts(query, top_k=top_k)

        # merge by id, take max score
        merged: dict[str, dict] = {}
        for r in vec_results + fts_results:
            rid = r["id"]
            if rid not in merged or r["score"] > merged[rid]["score"]:
                merged[rid] = r
        results = sorted(merged.values(), key=lambda x: -x["score"])
        return results[:top_k]

    async def get_agent_memories(self, top_k: int = 10) -> list[dict]:
        """Load memories across all conversations for this agent (cross-conversation)."""
        conn = _vec_db(self.agent_id)
        rows = conn.execute(
            "SELECT id, content, created_at FROM memories ORDER BY rowid DESC LIMIT ?",
            (top_k,),
        ).fetchall()
        return [{"id": r[0], "content": r[1], "created_at": r[2]} for r in rows]

    async def _store_vector(self, content: str) -> None:
        """Store content + embedding in vector DB. Also indexes in FTS5."""
        import uuid
        conn = _vec_db(self.agent_id)
        vec = _embed(content)
        rid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO memories (id, embedding, content, created_at) VALUES (?, ?, ?, datetime('now'))",
            (rid, json.dumps(vec), content),
        )
        # FTS5 index
        try:
            conn.execute("INSERT INTO memories_fts(id, content) VALUES (?, ?)", (rid, content))
        except Exception:
            pass
        conn.commit()

    async def _summarize(self, conversation_id: str, dropped_content: str) -> None:
        """Tier 2: store a summary memory for dropped content."""
        if not self._llm:
            await self._store_vector(dropped_content)
            return
        try:
            summary = await self._llm.chat(
                messages=[
                    {"role": "system", "content": "Summarize this message briefly for future retrieval."},
                    {"role": "user", "content": dropped_content},
                ],
                model="openai/gpt-4o-mini",
                max_tokens=200,
            )
            summary_text = summary.get("content", "") or dropped_content[:200]
            await self._store_vector(summary_text)
        except Exception:
            logger.exception("LLM summarization failed, storing raw content")
            await self._store_vector(dropped_content[:200])

    async def _load_from_db(self, conversation_id: str, db: DatabaseBackend) -> None:
        result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .limit(50)
        )
        for msg in result.scalars().all():
            self._buffers[conversation_id].append({
                "role": msg.role,
                "content": msg.content,
            })
        self._loaded.add(conversation_id)

    async def clear(self, conversation_id: str) -> None:
        self._buffers.pop(conversation_id, None)
        self._loaded.discard(conversation_id)
