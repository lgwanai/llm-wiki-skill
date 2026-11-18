"""Share native OKF pages and their attachments in a portable ZIP."""

from __future__ import annotations

import filecmp
import os
import posixpath
import re
import shutil
import stat
import unicodedata
from collections.abc import Iterable, Sequence
from contextlib import suppress
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory
from urllib.parse import unquote
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from .okf import RESERVED, read_markdown, validate_bundle

_INLINE_LINK = re.compile(r"\]\((<[^>\n]+>(?:[^)\n]*)|[^)\n]+)\)")
_REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]\n]+\]:[ \t]+(.+)$", re.MULTILINE)
_LINK_TITLE = re.compile(r"""\s+(?:"[^"]*"|'[^']*'|\([^)]*\))\s*$""")


def _portable_path(name: str) -> PurePosixPath:
    parts = name.split("/")
    if any(
        part.startswith(".")
        or not part
        or part.endswith((" ", "."))
        or PureWindowsPath(part).is_reserved()
        or re.search(r'[\x00-\x1f<>:"\\|?*]', part)
        for part in parts
    ):
        raise ValueError(f"unsafe or non-portable bundle path: {name!r}")
    return PurePosixPath(*parts)


def _check_path_collisions(
    files: set[PurePosixPath], directories: Iterable[PurePosixPath] = ()
) -> None:
    """Catch file/directory and case or Unicode collisions before writing."""
    seen: dict[str, PurePosixPath] = {}
    for path in sorted((*files, *directories)):
        for component in (path, *path.parents[:-1]):
            key = unicodedata.normalize("NFC", component.as_posix()).casefold()
            if key in seen and seen[key] != component:
                raise ValueError(f"conflicting bundle paths: {seen[key]} and {component}")
            seen[key] = component
        if any(parent in files for parent in path.parents):
            raise ValueError(f"bundle path has a file as parent: {path}")


def _bundle_files(root: Path) -> set[PurePosixPath]:
    if not root.is_dir() or root.is_symlink():
        raise ValueError(f"wiki pages directory is missing or is a symlink: {root}")

    def walk_error(error: OSError) -> None:
        raise error

    files = set()
    for directory, subdirs, names in os.walk(root, onerror=walk_error):
        parent = Path(directory)
        subdirs[:] = [
            name
            for name in subdirs
            if not name.startswith(".") and not (parent / name).is_symlink()
        ]
        for name in names:
            if name.startswith(".") or name in RESERVED:
                continue
            path = parent / name
            if stat.S_ISREG(path.lstat().st_mode):
                files.add(PurePosixPath(path.relative_to(root).as_posix()))
    return files


def _attachment_paths(
    root: Path, page: PurePosixPath, files: set[PurePosixPath]
) -> set[PurePosixPath]:
    metadata, body, _ = read_markdown(root / page)
    links = _INLINE_LINK.findall(body) + _REFERENCE_LINK.findall(body)
    visuals = metadata.get("visuals", [])
    if isinstance(visuals, dict):
        visuals = [visuals]
    if isinstance(visuals, list):
        for visual in visuals:
            if isinstance(visual, dict):
                links.extend(
                    value
                    for key in ("image", "source_image")
                    if isinstance(value := visual.get(key), str)
                )

    attachments = set()
    for link in links:
        link = link.strip()
        if link.startswith("<") and ">" in link:
            link = link[1 : link.index(">")]
        else:
            link = _LINK_TITLE.sub("", link)
        target = unquote(re.split(r"[?#]", link, maxsplit=1)[0])
        if not target or target.startswith("//") or re.match(r"^[\w+.-]+:", target):
            continue
        relative = (
            target[1:] if target.startswith("/") else posixpath.join(page.parent.as_posix(), target)
        )
        path = PurePosixPath(posixpath.normpath(relative))
        if path.suffix != ".md" and path in files:
            attachments.add(path)
    return attachments


def export_zip(
    root: Path,
    archive: Path,
    *,
    module_dirs: Sequence[str] = (),
    page_ids: Sequence[str] = (),
    force: bool = False,
) -> dict:
    """Export the wiki or a selection, keeping bundle-relative paths unchanged."""
    archive = archive.expanduser().absolute()
    if archive.suffix.lower() != ".zip":
        raise ValueError("export destination must end in .zip")
    if archive.resolve().is_relative_to(root.resolve()):
        raise ValueError("export destination must be outside the wiki pages directory")
    if archive.is_symlink() or (archive.exists() and not archive.is_file()):
        raise ValueError(f"export destination must be a regular file: {archive}")
    if archive.exists() and not force:
        raise FileExistsError(f"{archive} already exists; use --force to overwrite it")

    files = _bundle_files(root)
    selected = set() if module_dirs or page_ids else files
    for name in module_dirs:
        folder = _portable_path(name.rstrip("/"))
        matches = {path for path in files if path.is_relative_to(folder) and path != folder}
        if not any(path.suffix == ".md" for path in matches):
            raise ValueError(f"module has no wiki pages: {name}")
        selected.update(matches)
    for identifier in page_ids:
        name = identifier if identifier.endswith(".md") else f"{identifier}.md"
        path = _portable_path(name)
        if path not in files:
            raise ValueError(f"wiki page not found: {name}")
        selected.add(path)

    pages = sorted(path for path in selected if path.suffix == ".md")
    if not pages:
        raise ValueError("there are no wiki pages to export")
    report = validate_bundle(root, paths=[root / page for page in pages])
    if not report["valid"]:
        return report
    if module_dirs or page_ids:
        for page in pages:
            selected.update(_attachment_paths(root, page, files))
    for path in selected:
        _portable_path(path.as_posix())
    _check_path_collisions(selected)

    archive.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".wiki-export-", dir=archive.parent) as directory:
        staged = Path(directory) / "bundle.zip"
        with ZipFile(staged, "w", ZIP_DEFLATED, strict_timestamps=False) as bundle:
            for path in sorted(selected):
                bundle.write(root / path, path.as_posix())
        if force:
            staged.replace(archive)
        else:
            os.link(staged, archive)
    return {
        **report,
        "exported": len(pages),
        "attachments": len(selected) - len(pages),
        "destination": str(archive),
    }


def _zip_members(bundle: ZipFile) -> dict[PurePosixPath, ZipInfo]:
    members = {}
    directories = set()
    seen = set()
    for info in bundle.infolist():
        path = _portable_path(
            info.orig_filename.removesuffix("/") if info.is_dir() else info.orig_filename
        )
        mode = stat.S_IFMT(info.external_attr >> 16) if info.create_system == 3 else 0
        expected = stat.S_IFDIR if info.is_dir() else stat.S_IFREG
        if mode not in (0, expected) or path in seen:
            raise ValueError(f"duplicate or non-regular ZIP member: {info.filename!r}")
        seen.add(path)
        if info.is_dir():
            directories.add(path)
        else:
            members[path] = info
    _check_path_collisions(set(members), directories)
    return {path: info for path, info in members.items() if path.name not in RESERVED}


def _stage_bundle(archive: Path, staging: Path) -> tuple[dict, set[PurePosixPath]]:
    staging.mkdir()
    with ZipFile(archive.expanduser()) as bundle:
        members = _zip_members(bundle)
        if not any(path.suffix == ".md" for path in members):
            raise ValueError("ZIP contains no OKF concept pages")
        if sum(info.file_size for info in members.values()) > shutil.disk_usage(staging).free:
            raise ValueError("not enough disk space to unpack the ZIP")
        for path, info in members.items():
            output = staging / path
            output.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, output.open("xb") as target:
                shutil.copyfileobj(source, target)
    return validate_bundle(staging), set(members)


def validate_zip(archive: Path) -> dict:
    """Validate a ZIP without changing the wiki."""
    with TemporaryDirectory(prefix="wiki-validate-") as directory:
        report, _ = _stage_bundle(archive, Path(directory) / "pages")
    return report


def _destination_exists(root: Path, path: PurePosixPath) -> bool:
    for folder in (root, *(root / parent for parent in reversed(path.parents[:-1]))):
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise ValueError(f"wiki destination is not a regular directory: {folder}")
    target = root / path
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ValueError(f"wiki destination is not a regular file: {target}")
    return target.exists()


def _install_files(
    staging: Path, root: Path, pending: dict[PurePosixPath, bool], backups: Path
) -> None:
    """Publish complete files, restoring changed entries if an installation fails."""
    installed = []
    created_dirs = []
    try:
        for path, exists in pending.items():
            source = staging / path
            target = root / path
            for parent in (root, *(root / part for part in reversed(path.parents[:-1]))):
                try:
                    parent.mkdir()
                except FileExistsError:
                    if parent.is_symlink() or not parent.is_dir():
                        raise
                else:
                    created_dirs.append(parent)
            identity = source.stat()
            if exists:
                backup = backups / path
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.link(target, backup)
                source.replace(target)
            else:
                os.link(source, target)
            installed.append((path, exists, identity))
    except OSError:
        for path, existed, identity in reversed(installed):
            target = root / path
            if target.exists() and os.path.samestat(target.lstat(), identity):
                if existed:
                    (backups / path).replace(target)
                else:
                    target.unlink()
        for folder in reversed(created_dirs):
            # Another writer may already have added files to a new directory.
            if not any(folder.iterdir()):
                folder.rmdir()
        raise


def import_zip(root: Path, archive: Path, *, force: bool = False) -> dict:
    """Validate and merge a ZIP without overwriting a different file by default."""
    root.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".wiki-import-", dir=root.parent) as directory:
        work = Path(directory)
        staging = work / "pages"
        report, members = _stage_bundle(archive, staging)
        if not report["valid"]:
            return report

        pending = {}
        conflicts = []
        skipped = 0
        for path in sorted(members):
            exists = _destination_exists(root, path)
            if exists and (root / path).samefile(archive.expanduser()):
                raise ValueError(f"import would replace the source ZIP: {path.as_posix()}")
            if exists and filecmp.cmp(staging / path, root / path, shallow=False):
                skipped += 1
            elif exists and not force:
                conflicts.append(path.as_posix())
            else:
                pending[path] = exists
        if conflicts:
            return {
                **report,
                "valid": False,
                "imported": 0,
                "destination": str(root),
                "conflicts": conflicts,
                "message": "No files imported. Use --force to overwrite conflicting files.",
            }

        # Publish attachments before the pages that can refer to them.
        ordered = dict(sorted(pending.items(), key=lambda item: item[0].suffix == ".md"))
        _install_files(staging, root, ordered, work / "backups")
    pages = sum(path.suffix == ".md" for path in pending)
    attachments = len(pending) - pages
    if attachments:
        # Existing page bytes may have been skipped even though images are now available.
        graph = root.parent / "graph"
        if not graph.is_symlink():
            with suppress(OSError):
                (graph / ".visual_index.json").unlink(missing_ok=True)
    return {
        **report,
        "imported": pages,
        "attachments": attachments,
        "skipped": skipped,
        "overwritten": sum(pending.values()),
        "destination": str(root),
    }
