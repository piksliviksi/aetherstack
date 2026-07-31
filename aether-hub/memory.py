"""Shared agent memory on Redis — sessions + vector store (cosine in-process)."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore


PREFIX = os.environ.get("AETHER_MEMORY_PREFIX", "aether:mem")
DEFAULT_NAMESPACE = "default"
MAX_VECTORS_SCAN = int(os.environ.get("AETHER_MEMORY_MAX_SCAN", "5000"))


class MemoryStore:
    def __init__(self, url: str | None = None):
        self.url = url or os.environ.get("REDIS_URL") or "redis://127.0.0.1:6379/0"
        self._r = None
        if redis is not None:
            try:
                # Short connect/socket timeouts so missing Redis fails fast → memory fallback
                self._r = redis.Redis.from_url(
                    self.url,
                    decode_responses=True,
                    socket_connect_timeout=float(os.environ.get("AETHER_REDIS_CONNECT_TIMEOUT", "1.5")),
                    socket_timeout=float(os.environ.get("AETHER_REDIS_SOCKET_TIMEOUT", "3")),
                )
                self._r.ping()
            except Exception:
                self._r = None
        # In-memory fallback when Redis is down (dev only)
        self._local_sessions: dict[str, list] = {}
        self._local_vectors: dict[str, list[dict]] = {}

    @property
    def backend(self) -> str:
        return "redis" if self._r is not None else "memory-fallback"

    def health(self) -> dict[str, Any]:
        ok = False
        info = {}
        if self._r is not None:
            try:
                ok = bool(self._r.ping())
                info["redis"] = "pong"
            except Exception as e:
                info["redis_error"] = str(e)
        else:
            info["note"] = "redis-py missing or Redis unreachable; using process memory"
            ok = True  # degraded but usable
        return {"ok": ok, "backend": self.backend, **info}

    # ── sessions (short-term working memory) ─────────────────────────

    def _session_key(self, session_id: str) -> str:
        return f"{PREFIX}:session:{session_id}"

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        meta: dict | None = None,
    ) -> dict[str, Any]:
        msg = {
            "id": str(uuid.uuid4()),
            "ts": time.time(),
            "role": role,
            "content": content,
            "meta": meta or {},
        }
        if self._r is not None:
            key = self._session_key(session_id)
            self._r.rpush(key, json.dumps(msg))
            # keep last 200 messages
            self._r.ltrim(key, -200, -1)
            ttl = int(os.environ.get("AETHER_SESSION_TTL_SEC", "604800"))  # 7d
            self._r.expire(key, ttl)
        else:
            self._local_sessions.setdefault(session_id, []).append(msg)
            self._local_sessions[session_id] = self._local_sessions[session_id][-200:]
        return msg

    def get_session(self, session_id: str, limit: int = 50) -> list[dict]:
        if self._r is not None:
            raw = self._r.lrange(self._session_key(session_id), -limit, -1)
            out = []
            for line in raw:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return out
        return list(self._local_sessions.get(session_id, []))[-limit:]

    def clear_session(self, session_id: str) -> None:
        if self._r is not None:
            self._r.delete(self._session_key(session_id))
        else:
            self._local_sessions.pop(session_id, None)

    # ── vector memory (RAG-style shared store) ───────────────────────

    def _vec_key(self, namespace: str) -> str:
        return f"{PREFIX}:vec:{namespace}"

    def embed_text(self, text: str) -> list[float]:
        """
        Prefer Ollama embeddings; fall back to deterministic hash embedding
        so lab demos work without models (weaker recall quality).
        Set AETHER_HASH_EMBED=1 to skip network (tests / offline).
        """
        if os.environ.get("AETHER_HASH_EMBED", "").strip().lower() in ("1", "true", "yes"):
            return _hash_embed(text, dim=256)
        base = (
            os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("AETHER_EMBED_URL")
            or "http://host.docker.internal:11434"
        ).rstrip("/")
        model = os.environ.get("AETHER_EMBED_MODEL", "nomic-embed-text")
        body = json.dumps({"model": model, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/api/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        timeout = float(os.environ.get("AETHER_EMBED_TIMEOUT", "2.5"))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            emb = data.get("embedding")
            if isinstance(emb, list) and emb:
                return [float(x) for x in emb]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
            pass
        return _hash_embed(text, dim=256)

    def upsert_vector(
        self,
        text: str,
        namespace: str = DEFAULT_NAMESPACE,
        meta: dict | None = None,
        id: str | None = None,
        embedding: list[float] | None = None,
    ) -> dict[str, Any]:
        vid = id or str(uuid.uuid4())
        emb = embedding or self.embed_text(text)
        doc = {
            "id": vid,
            "ts": time.time(),
            "text": text,
            "embedding": emb,
            "meta": meta or {},
            "namespace": namespace,
            "dim": len(emb),
        }
        if self._r is not None:
            # Hash field id → json; sidecars for list of ids
            pipe = self._r.pipeline()
            pipe.hset(self._vec_key(namespace), vid, json.dumps(doc))
            pipe.sadd(f"{self._vec_key(namespace)}:ids", vid)
            pipe.execute()
        else:
            bucket = self._local_vectors.setdefault(namespace, [])
            bucket = [d for d in bucket if d.get("id") != vid]
            bucket.append(doc)
            self._local_vectors[namespace] = bucket[-MAX_VECTORS_SCAN:]
        return {"id": vid, "namespace": namespace, "dim": len(emb), "backend": self.backend}

    def search(
        self,
        query: str,
        namespace: str = DEFAULT_NAMESPACE,
        top_k: int = 5,
        embedding: list[float] | None = None,
    ) -> dict[str, Any]:
        q = embedding or self.embed_text(query)
        docs = self._load_vectors(namespace)
        scored = []
        for d in docs:
            emb = d.get("embedding") or []
            if not emb:
                continue
            scored.append((cosine(q, emb), d))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for score, d in scored[: max(1, min(top_k, 50))]:
            hits.append(
                {
                    "id": d.get("id"),
                    "score": round(float(score), 4),
                    "text": d.get("text"),
                    "meta": d.get("meta"),
                    "ts": d.get("ts"),
                }
            )
        return {
            "query": query,
            "namespace": namespace,
            "top_k": top_k,
            "hits": hits,
            "scanned": len(docs),
            "backend": self.backend,
            "embed_dim": len(q),
        }

    def _load_vectors(self, namespace: str) -> list[dict]:
        if self._r is not None:
            raw = self._r.hgetall(self._vec_key(namespace))
            out = []
            for _, v in list(raw.items())[:MAX_VECTORS_SCAN]:
                try:
                    out.append(json.loads(v))
                except json.JSONDecodeError:
                    continue
            return out
        return list(self._local_vectors.get(namespace, []))

    def list_vectors(self, namespace: str) -> list[dict]:
        """All vectors in a namespace, most-recent first (no query/embedding needed)."""
        docs = self._load_vectors(namespace)
        return sorted(docs, key=lambda d: d.get("ts") or 0, reverse=True)

    def stats(self, namespace: str = DEFAULT_NAMESPACE) -> dict[str, Any]:
        docs = self._load_vectors(namespace)
        return {
            "namespace": namespace,
            "count": len(docs),
            "backend": self.backend,
        }

    def list_vector_namespaces(self, prefix: str | None = None) -> list[str]:
        """List vector namespace names (for backup / admin)."""
        out: set[str] = set()
        if self._r is not None:
            try:
                pat = f"{PREFIX}:vec:*"
                cursor = 0
                while True:
                    cursor, keys = self._r.scan(cursor=cursor, match=pat, count=200)
                    for k in keys:
                        ks = str(k)
                        if ks.endswith(":ids"):
                            continue
                        # aether:mem:vec:{namespace}
                        marker = f"{PREFIX}:vec:"
                        if marker in ks:
                            ns = ks.split(marker, 1)[-1]
                            out.add(ns)
                    if cursor == 0:
                        break
            except Exception:
                pass
        for ns in self._local_vectors.keys():
            out.add(str(ns))
        names = sorted(out)
        if prefix:
            names = [n for n in names if n.startswith(prefix)]
        return names

    def list_session_ids(self, prefix: str | None = None) -> list[str]:
        out: set[str] = set()
        if self._r is not None:
            try:
                pat = f"{PREFIX}:session:*"
                cursor = 0
                while True:
                    cursor, keys = self._r.scan(cursor=cursor, match=pat, count=200)
                    for k in keys:
                        ks = str(k)
                        marker = f"{PREFIX}:session:"
                        if marker in ks:
                            out.add(ks.split(marker, 1)[-1])
                    if cursor == 0:
                        break
            except Exception:
                pass
        for sid in self._local_sessions.keys():
            out.add(str(sid))
        names = sorted(out)
        if prefix:
            names = [n for n in names if n.startswith(prefix) or prefix in n]
        return names

    def export_namespace(self, namespace: str) -> dict[str, Any]:
        docs = self._load_vectors(namespace)
        # strip large embeddings option handled by caller
        return {
            "namespace": namespace,
            "count": len(docs),
            "vectors": docs,
        }

    def export_session(self, session_id: str, limit: int = 500) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "messages": self.get_session(session_id, limit=limit),
        }


def cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        x = float(a[i])
        y = float(b[i])
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _hash_embed(text: str, dim: int = 256) -> list[float]:
    """Deterministic bag-of-hashes embedding (no model required)."""
    vec = [0.0] * dim
    tokens = text.lower().split()
    if not tokens:
        tokens = [text or ""]
    for tok in tokens:
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        for i in range(0, min(len(h), 16), 2):
            idx = int.from_bytes(h[i : i + 2], "little") % dim
            sign = 1.0 if h[i] % 2 == 0 else -1.0
            vec[idx] += sign
    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]
