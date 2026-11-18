"""Source identity and recoverable publication of one wiki revision."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Any

_SECRET_PATTERNS = (
    (r"(?:sk|pk|rk)-[a-zA-Z0-9]{20,}", "[REDACTED: API key]"),
    (r"(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}", "[REDACTED: GitHub token]"),
    (
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        "[REDACTED: Private key]",
    ),
    (
        r"""(?i)(\b(?:password|api[_ -]?key|access[_ -]?token|auth[_ -]?token|"""
        r"""client[_ -]?secret|secret[_ -]?key)\b["']?[ \t]*[=:][ \t]*)"""
        r"""(?:"([^"\r\n]*)"|'([^'\r\n]*)'|([^\s,;}<>"']+))""",
        None,
    ),
)


def strip_secrets(content: str) -> str:
    """Redact credential values while preserving quoted field syntax."""

    def redact_field(match: re.Match[str]) -> str:
        quote = '"' if match[2] is not None else "'" if match[3] is not None else ""
        return f"{match[1]}{quote}[REDACTED]{quote}"

    # Handle named fields before replacing token-shaped values with placeholders.
    for pattern, replacement in reversed(_SECRET_PATTERNS):
        content = re.sub(
            pattern, redact_field if replacement is None else replacement, content, flags=re.DOTALL
        )
    return content


def source_id_for(path: Path, wiki_dir: Path) -> str:
    """Use a project-relative origin where possible and a full origin otherwise."""
    origin = path.resolve()
    try:
        locator = "project:" + origin.relative_to(wiki_dir.resolve().parent).as_posix()
    except ValueError:
        locator = "file:" + origin.as_posix()
    return hashlib.sha256(locator.encode("utf-8")).hexdigest()[:24]


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def json_bytes(data: dict[str, Any]) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def active_path(wiki_dir: Path, source_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{24}", source_id):
        raise ValueError("Invalid source ID")
    return wiki_dir / "source" / "evidence" / ".active" / f"{source_id}.json"


def active_source(wiki_dir: Path, source_id: str) -> dict[str, Any]:
    return read_json(active_path(wiki_dir, source_id))


def current_compiled_table(wiki_dir: Path, description: str | None) -> bool:
    """Keep historical tables addressable without returning their values in search."""
    marker = re.search(r"\[compile:([a-f0-9]{24}):([a-f0-9]{32})\]$", description or "")
    if marker is None:
        return True
    source_id, revision = marker.groups()
    return active_source(wiki_dir, source_id).get("compiled_revision") == revision


@contextmanager
def _file_lock(wiki_dir: Path, *, write: bool) -> Iterator[None]:
    path = wiki_dir / ".compile.lock"
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            mode = msvcrt.LK_NBLCK if write else msvcrt.LK_NBRLCK
            while True:
                try:
                    msvcrt.locking(handle.fileno(), mode, 1)
                    break
                except OSError as exc:
                    if exc.errno not in {13, 36}:
                        raise
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX if write else fcntl.LOCK_SH)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _journal(wiki_dir: Path) -> Path:
    return wiki_dir / "compile_runs" / ".publication" / "journal.json"


def _destination(wiki_dir: Path, relative: str) -> Path:
    path = wiki_dir / relative
    if not path.resolve().is_relative_to(wiki_dir) or path.is_symlink():
        raise ValueError(f"Invalid publication destination: {relative}")
    return path


def _recover(wiki_dir: Path) -> None:
    journal_path = _journal(wiki_dir)
    journal = read_json(journal_path)
    if not journal:
        return
    for relative, backup in journal["files"].items():
        destination = _destination(wiki_dir, relative)
        if backup is None:
            destination.unlink(missing_ok=True)
        else:
            atomic_bytes(destination, (journal_path.parent / backup).read_bytes())
    journal_path.unlink()
    shutil.rmtree(journal_path.parent / journal["backup_dir"], ignore_errors=True)


_read_state = threading.local()


@contextmanager
def publication_view(wiki_dir: str | Path) -> Iterator[None]:
    """Read a consistent wiki and recover a publication interrupted mid-write."""
    root = Path(wiki_dir).resolve()
    held = getattr(_read_state, "roots", set())
    if root in held or not root.is_dir():
        yield
        return
    while True:
        with _file_lock(root, write=False):
            if not _journal(root).exists():
                _read_state.roots = held | {root}
                try:
                    yield
                finally:
                    _read_state.roots = held
                return
        with _file_lock(root, write=True):
            _recover(root)


def consistent_read(wiki_dir: Callable[[], Path]) -> Callable:
    """Use the current wiki for each call of a public query entry point."""

    def decorate(function: Callable) -> Callable:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with publication_view(wiki_dir()):
                return function(*args, **kwargs)

        return wrapped

    return decorate


@contextmanager
def publication_write(wiki_dir: Path) -> Iterator[None]:
    """Exclude readers and publishers while changing revision state."""
    root = wiki_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with _file_lock(root, write=True):
        _recover(root)
        yield


def publish_changes(
    wiki_dir: Path,
    prepare: Callable[[], Mapping[str, bytes | None]],
) -> None:
    """Commit a file set under one lock, restoring the old set on interruption."""
    root = wiki_dir.resolve()
    with publication_write(root):
        changes = prepare()
        if not changes:
            return
        journal_path = _journal(root)
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        # Keep backups available if the process dies or recovery fails.
        backup_dir = Path(tempfile.mkdtemp(prefix="backups-", dir=journal_path.parent))
        try:
            backups = {}
            for index, relative in enumerate(changes):
                destination = _destination(root, relative)
                backup = backup_dir / str(index)
                if destination.is_file():
                    shutil.copyfile(destination, backup)
                    backups[relative] = backup.relative_to(journal_path.parent).as_posix()
                else:
                    backups[relative] = None
            journal = {"files": backups, "backup_dir": backup_dir.name}
            atomic_bytes(journal_path, json_bytes(journal))
            try:
                for relative, data in changes.items():
                    destination = _destination(root, relative)
                    if data is None:
                        destination.unlink(missing_ok=True)
                    else:
                        atomic_bytes(destination, data)
            except BaseException:
                _recover(root)
                raise
            journal_path.unlink()
        finally:
            if not journal_path.exists():
                shutil.rmtree(backup_dir, ignore_errors=True)
