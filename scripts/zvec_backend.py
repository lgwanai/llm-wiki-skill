"""Optional Zvec semantic index for native OKF concepts."""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

try:
    from .okf import concept_id, iter_concepts, read_markdown
except ImportError:  # Direct script/module loading via scripts/ on sys.path.
    from okf import concept_id, iter_concepts, read_markdown

_WRITE_LOCK = threading.Lock()


@contextmanager
def _process_lock(path: Path):
    """Serialize index writers across CLI processes on POSIX systems."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    try:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except ImportError:
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except ImportError:
            pass
        handle.close()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _concept_text(path: Path) -> tuple[dict, str]:
    metadata, body, error = read_markdown(path)
    if error:
        return {}, ""
    headings = "\n".join(line for line in body.splitlines() if line.startswith("#"))
    text = "\n".join(
        part
        for part in (
            str(metadata.get("title", "")),
            str(metadata.get("description", "")),
            " ".join(str(tag) for tag in metadata.get("tags", []) or []),
            headings,
            body,
        )
        if part
    )
    return metadata, text[:32_000]


@lru_cache(maxsize=2)
def _embedding(model_source: str):
    from zvec.extension import DefaultLocalDenseEmbedding

    return DefaultLocalDenseEmbedding(model_source=model_source)


def _collection(index_path: Path, dimension: int, writable: bool):
    import zvec

    option = zvec.CollectionOption(read_only=not writable, enable_mmap=True)
    if index_path.exists():
        return zvec.open(path=str(index_path), option=option)
    if not writable:
        return None
    schema = zvec.CollectionSchema(
        name="llm_wiki_okf",
        fields=[
            zvec.FieldSchema("concept_id", zvec.DataType.STRING),
            zvec.FieldSchema("path", zvec.DataType.STRING),
            zvec.FieldSchema("title", zvec.DataType.STRING),
            zvec.FieldSchema("type", zvec.DataType.STRING),
            zvec.FieldSchema("content_hash", zvec.DataType.STRING),
        ],
        vectors=[
            zvec.VectorSchema(
                "embedding",
                zvec.DataType.VECTOR_FP32,
                dimension=dimension,
                index_param=zvec.HnswIndexParam(metric_type=zvec.MetricType.COSINE),
            )
        ],
    )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    return zvec.create_and_open(path=str(index_path), schema=schema, option=option)


def sync_index(pages_dir: str | Path, wiki_dir: str | Path, config: dict) -> dict:
    """Incrementally synchronize OKF concepts into Zvec by content hash."""
    try:
        import zvec
    except ImportError:
        return {"available": False, "updated": 0, "deleted": 0}

    pages_root = Path(pages_dir).resolve()
    index_path = Path(wiki_dir) / str(config.get("index_path", "graph/zvec"))
    manifest_path = index_path.parent / "zvec_manifest.json"
    model_source = str(config.get("model_source", "modelscope"))
    embedder = _embedding(model_source)
    dimension = int(embedder.dimension)
    current: dict[str, dict] = {}
    updates = []
    lock_path = index_path.parent / ".zvec-write.lock"
    with _WRITE_LOCK, _process_lock(lock_path):
        old = {}
        if manifest_path.exists():
            try:
                old = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                old = {}
        collection = _collection(index_path, dimension, writable=True)
        try:
            for path in iter_concepts(pages_root):
                metadata, text = _concept_text(path)
                if not text:
                    continue
                identifier = concept_id(path, pages_root)
                digest = _hash(text)
                doc_id = _hash(identifier)[:32]
                current[identifier] = {
                    "hash": digest,
                    "path": str(path),
                    "doc_id": doc_id,
                }
                if old.get(identifier, {}).get("hash") == digest:
                    continue
                vector = embedder.embed(text)
                updates.append(
                    zvec.Doc(
                        id=doc_id,
                        fields={
                            "concept_id": identifier,
                            "path": str(path),
                            "title": str(metadata.get("title", path.stem)),
                            "type": str(metadata.get("type", "Reference")),
                            "content_hash": digest,
                        },
                        vectors={"embedding": vector},
                    )
                )
            if updates:
                collection.upsert(updates)
            deleted = sorted(set(old) - set(current))
            if deleted:
                collection.delete(
                    ids=[old[item].get("doc_id", _hash(item)[:32]) for item in deleted]
                )
            if updates and bool(config.get("optimize", True)):
                collection.optimize()
            manifest_path.write_text(
                json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        finally:
            close = getattr(collection, "close", None)
            if callable(close):
                close()
    return {"available": True, "updated": len(updates), "deleted": len(deleted)}


def vector_search(
    query: str,
    pages_dir: str | Path,
    wiki_dir: str | Path,
    config: dict,
    limit: int = 10,
) -> list[dict]:
    """Search the optional Zvec semantic index, synchronizing it first."""
    if not config.get("enabled", False) or config.get("backend") != "zvec":
        return []
    status = sync_index(pages_dir, wiki_dir, config)
    if not status.get("available"):
        return []
    import zvec

    model_source = str(config.get("model_source", "modelscope"))
    embedder = _embedding(model_source)
    index_path = Path(wiki_dir) / str(config.get("index_path", "graph/zvec"))
    collection = _collection(index_path, int(embedder.dimension), False)
    if collection is None:
        return []
    try:
        raw = collection.query(
            zvec.Query(field_name="embedding", vector=embedder.embed(query)),
            topk=limit,
        )
    finally:
        close = getattr(collection, "close", None)
        if callable(close):
            close()
    results = []
    for item in raw:
        fields = item.get("fields", {}) if isinstance(item, dict) else getattr(item, "fields", {})
        internal_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", "")
        identifier = fields.get("concept_id", internal_id)
        score = item.get("score", 0) if isinstance(item, dict) else getattr(item, "score", 0)
        results.append(
            {
                "file": identifier,
                "path": fields.get("path", ""),
                "score": float(score),
                "stream": "vector",
                "text": fields.get("title", ""),
                "type": fields.get("type", "Reference"),
            }
        )
    return results
