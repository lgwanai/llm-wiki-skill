#!/usr/bin/env python3
"""Deterministic EPUB to Markdown conversion with persistent image extraction."""

from __future__ import annotations

import hashlib
import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from markdownify import markdownify

IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
MAX_EPUB_MEMBERS = 20_000
MAX_RESOURCE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024  # cumulative cap across images


@dataclass(frozen=True)
class EpubItem:
    """One OPF manifest item with an archive-absolute member path."""

    identifier: str
    member: str
    media_type: str
    properties: frozenset[str]


def _safe_member(base_member: str, href: str) -> str | None:
    """Resolve an EPUB href without permitting paths outside the archive root."""
    path = unquote(urlsplit(href).path).replace("\\", "/")
    if not path or path.startswith("/"):
        return None
    member = posixpath.normpath(posixpath.join(posixpath.dirname(base_member), path))
    if member == ".." or member.startswith("../"):
        return None
    return member.lstrip("./")


def _find_member(member: str, names: dict[str, str]) -> str | None:
    """Find an archive member, tolerating EPUBs with inconsistent path case."""
    if member in names.values():
        return member
    return names.get(member.casefold())


def _container_opf(archive: zipfile.ZipFile, names: dict[str, str]) -> str:
    container_name = _find_member("META-INF/container.xml", names)
    if not container_name:
        raise ValueError("Invalid EPUB: META-INF/container.xml is missing")
    root = ElementTree.fromstring(archive.read(container_name))
    rootfile = root.find(".//{*}rootfile")
    opf_path = rootfile.get("full-path", "") if rootfile is not None else ""
    normalized = posixpath.normpath(unquote(opf_path).replace("\\", "/")).lstrip("/")
    found = _find_member(normalized, names) if normalized else None
    if not found:
        raise ValueError(f"Invalid EPUB: package document is missing: {opf_path or '-'}")
    return found


def _opf_items(opf: ElementTree.Element, opf_member: str) -> tuple[dict[str, EpubItem], list[str]]:
    items: dict[str, EpubItem] = {}
    for node in opf.findall(".//{*}manifest/{*}item"):
        identifier = node.get("id", "").strip()
        href = node.get("href", "").strip()
        member = _safe_member(opf_member, href)
        if not identifier or not member:
            continue
        items[identifier] = EpubItem(
            identifier=identifier,
            member=member,
            media_type=node.get("media-type", "").strip().lower(),
            properties=frozenset(node.get("properties", "").split()),
        )

    spine = [
        node.get("idref", "").strip()
        for node in opf.findall(".//{*}spine/{*}itemref")
        if node.get("idref", "").strip()
    ]
    return items, spine


def _metadata_title(opf: ElementTree.Element, fallback: str) -> str:
    title = opf.find(".//{*}metadata/{*}title")
    if title is not None and title.text and title.text.strip():
        return title.text.strip()
    return fallback


def _cover_item(opf: ElementTree.Element, items: dict[str, EpubItem]) -> EpubItem | None:
    for item in items.values():
        if "cover-image" in item.properties:
            return item
    for meta in opf.findall(".//{*}metadata/{*}meta"):
        if meta.get("name", "").lower() == "cover":
            return items.get(meta.get("content", ""))
    return None


def _safe_asset_name(member: str) -> str:
    member_path = PurePosixPath(member)
    stem = re.sub(r"[^a-zA-Z0-9_.-]+", "-", member_path.stem).strip("-") or "image"
    suffix = member_path.suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        suffix = ".bin"
    digest = hashlib.sha256(member.encode("utf-8")).hexdigest()[:10]
    return f"{stem}-{digest}{suffix}"


def _extract_image(
    archive: zipfile.ZipFile,
    member: str,
    names: dict[str, str],
    assets_dir: Path,
    extracted_total: list[int],
) -> Path | None:
    found = _find_member(member, names)
    if not found:
        return None
    info = archive.getinfo(found)
    if info.file_size > MAX_RESOURCE_BYTES:
        raise ValueError(f"EPUB image is too large ({info.file_size} bytes): {found}")
    if extracted_total[0] + info.file_size > MAX_TOTAL_EXTRACTED_BYTES:
        raise ValueError(
            f"EPUB cumulative image extraction limit ({MAX_TOTAL_EXTRACTED_BYTES} bytes) "
            f"exceeded at {found}"
        )
    destination = assets_dir / _safe_asset_name(found)
    if not destination.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read(found))
    extracted_total[0] += info.file_size
    return destination.resolve()


def _chapter_markdown(
    archive: zipfile.ZipFile,
    item: EpubItem,
    names: dict[str, str],
    assets_dir: Path,
    referenced_images: set[str],
    extracted_total: list[int],
) -> tuple[str, str]:
    found = _find_member(item.member, names)
    if not found:
        return "", ""
    soup = BeautifulSoup(archive.read(found), "html.parser")
    for unwanted in soup.find_all(["script", "style"]):
        unwanted.decompose()

    for image in soup.find_all("img"):
        source = str(image.get("src", "")).strip()
        member = _safe_member(found, source) if source else None
        extracted = (
            _extract_image(archive, member, names, assets_dir, extracted_total) if member else None
        )
        if extracted:
            image["src"] = str(extracted)
            referenced_images.add(member or "")
        elif source:
            image.replace_with(f"[EPUB image unavailable: {source}]")

    # SVG <image> elements are common in illustrated EPUB textbooks, but
    # markdownify only understands HTML <img>. Convert them before Markdown.
    for image in soup.find_all("image"):
        source = str(image.get("href") or image.get("xlink:href") or "").strip()
        member = _safe_member(found, source) if source else None
        extracted = (
            _extract_image(archive, member, names, assets_dir, extracted_total) if member else None
        )
        if extracted:
            replacement = soup.new_tag("img")
            replacement["src"] = str(extracted)
            replacement["alt"] = str(image.get("aria-label") or image.get("title") or "EPUB image")
            image.replace_with(replacement)
            referenced_images.add(member or "")
        elif source:
            image.replace_with(f"[EPUB image unavailable: {source}]")

    title_node = soup.find(["h1", "h2", "title"])
    title = title_node.get_text(" ", strip=True) if title_node else ""
    body: Any = soup.body or soup
    content = markdownify(
        str(body),
        heading_style="ATX",
        bullets="-",
        strip=["html", "body"],
    )
    content = re.sub(r"\n{3,}", "\n\n", content).strip()
    return content, title


def epub_to_markdown(source_path: Path, assets_dir: Path) -> str:
    """Convert an EPUB in spine order and preserve every referenced local image."""
    source_path = source_path.resolve()
    try:
        archive = zipfile.ZipFile(source_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid EPUB archive: {source_path}: {exc}") from exc

    with archive:
        if len(archive.infolist()) > MAX_EPUB_MEMBERS:
            raise ValueError(f"EPUB contains too many archive members: {len(archive.infolist())}")
        names = {name.casefold(): name for name in archive.namelist()}
        opf_member = _container_opf(archive, names)
        opf = ElementTree.fromstring(archive.read(opf_member))
        items, spine = _opf_items(opf, opf_member)
        title = _metadata_title(opf, source_path.stem)
        chapters = [items[item_id] for item_id in spine if item_id in items]
        if not chapters:
            chapters = [
                item
                for item in items.values()
                if item.media_type in {"application/xhtml+xml", "text/html"}
                and "nav" not in item.properties
            ]

        lines = [
            f"# {title}",
            "",
            f"> EPUB source: `{source_path.name}`",
            "> EPUB has no reliable fixed page numbers; use section locators "
            "below for traceability.",
            "",
        ]
        referenced_images: set[str] = set()
        extracted_total: list[int] = [0]
        cover = _cover_item(opf, items)
        if cover:
            cover_path = _extract_image(archive, cover.member, names, assets_dir, extracted_total)
            if cover_path:
                lines.extend([f"![Cover]({cover_path})", ""])
                referenced_images.add(cover.member)

        section_number = 0
        for item in chapters:
            content, chapter_title = _chapter_markdown(
                archive,
                item,
                names,
                assets_dir,
                referenced_images,
                extracted_total,
            )
            if not content:
                continue
            section_number += 1
            locator = chapter_title or PurePosixPath(item.member).stem
            lines.extend(
                [
                    f"## EPUB Section {section_number}: {locator}",
                    "",
                    f"> EPUB locator: `{item.member}`",
                    "",
                    content,
                    "",
                ]
            )

        if section_number == 0:
            raise ValueError("EPUB contains no readable spine content")
        return "\n".join(lines).strip() + "\n"
