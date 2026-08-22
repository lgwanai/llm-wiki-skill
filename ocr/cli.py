#!/usr/bin/env python3
"""Stable command-line entry point for document OCR.

Canonical usage::

    wiki ocr --doctor
    wiki ocr textbook.pdf --smoke-pages 3
    wiki ocr textbook.pdf -o .wiki/source/textbook

``python -m ocr.cli``, ``ocr``, and ``llm-wiki-ocr`` expose the same interface.
PDF runs always emit an OCR manifest next to the generated
Markdown so an agent can verify the runtime and page coverage without probing
the environment or inventing a one-off harness.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import multiprocessing
import os
import re
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIN_MINERU_VERSION = (3, 4, 4)
MAX_MINERU_VERSION = (4, 0, 0)
_SOURCE_LIKE_SUFFIXES = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".doc",
    ".docx",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
}
_PAGINATED_SUFFIXES = {".pdf", ".doc", ".docx", ".ppt", ".pptx"}


def get_ocr_config() -> dict[str, Any]:
    """Return the selected standalone model config.

    Kept as a small public seam for callers that previously patched the CLI's
    configuration lookup; unlike the old implementation it has no Wiki import.
    """
    from ocr.config import get_model_config

    return get_model_config()


def _get_default_backend() -> str:
    """Read the standalone OCR configuration's default model."""
    config = get_ocr_config()
    return str(config.get("backend", "paddlevl"))


def resolve_output_dir(
    input_path: str | Path,
    requested: str | None,
    default: str | Path,
) -> Path:
    """Resolve and validate an OCR output directory without touching the input."""
    source = Path(input_path).expanduser()
    output_dir = Path(requested).expanduser() if requested else Path(default)

    if output_dir.exists() and not output_dir.is_dir():
        raise ValueError(f"OCR output must be a directory, not a file: {output_dir}")
    if requested and output_dir.suffix.lower() in _SOURCE_LIKE_SUFFIXES:
        raise ValueError(
            f"OCR output must be a directory, not a source-like file path: {output_dir}"
        )
    try:
        if output_dir.resolve() == source.resolve():
            raise ValueError("OCR output directory cannot be the source file path.")
    except FileNotFoundError:
        pass
    return output_dir


def validate_output_file(input_path: str | Path, output_path: str | Path) -> Path:
    """Validate a text output file path for single-image OCR."""
    source = Path(input_path).expanduser()
    output = Path(output_path).expanduser()
    if output.exists() and output.is_dir():
        raise ValueError(f"OCR text output must be a file, not a directory: {output}")
    try:
        if output.resolve() == source.resolve():
            raise ValueError("OCR text output cannot be the source file path.")
    except FileNotFoundError:
        pass
    return output


def _version_tuple(version: str) -> tuple[int, int, int]:
    """Return the first three numeric release components, ignoring pre-release.

    Pre-release suffixes (``rc``, ``dev``, ``a``, ``b``) are stripped before
    parsing so ``3.4.4rc1`` is treated as the ``3.4.4`` release for the
    ``>=3.4.4,<4`` range check; callers that must reject pre-releases should
    also consult :func:`_is_prerelease`.
    """
    release = re.split(r"[^0-9.]", version, maxsplit=1)[0]
    parts = [int(value) for value in re.findall(r"\d+", release)[:3]]
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def _is_prerelease(version: str) -> bool:
    """True if the version string carries a PEP 440 pre-release/dev suffix."""
    return bool(re.search(r"(?:a|b|rc|dev|alpha|beta)\d*$", version, re.IGNORECASE))


def inspect_mineru_runtime() -> dict[str, Any]:
    """Return a complete, side-effect-light MinerU readiness report."""
    from ocr._mineru_ocr import MINERU_JSON, _ensure_mineru_config

    _ensure_mineru_config()
    errors: list[str] = []
    warnings: list[str] = []

    try:
        mineru_version = importlib.metadata.version("mineru")
    except importlib.metadata.PackageNotFoundError:
        mineru_version = None
        errors.append("MinerU is not installed in this Python interpreter.")

    mineru_path: str | None = None
    try:
        spec = importlib.util.find_spec("mineru")
        if spec and spec.origin:
            mineru_path = str(Path(spec.origin).resolve())
    except (ImportError, ModuleNotFoundError, ValueError):
        pass

    if mineru_version:
        parsed_version = _version_tuple(mineru_version)
        if not (MIN_MINERU_VERSION <= parsed_version < MAX_MINERU_VERSION):
            errors.append(f"Unsupported MinerU {mineru_version}; required >=3.4.4,<4.")
        elif _is_prerelease(mineru_version):
            errors.append(
                f"MinerU {mineru_version} is a pre-release; a stable "
                ">=3.4.4,<4 release is required."
            )

    config_path = Path(os.environ.get("MINERU_TOOLS_CONFIG_JSON", str(MINERU_JSON))).expanduser()
    config: dict[str, Any] = {}
    if not config_path.is_file():
        errors.append(f"MinerU config does not exist: {config_path}")
    else:
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("top-level value must be an object")
            config = loaded
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"MinerU config is invalid: {exc}")

    models = config.get("models-dir", {}) if isinstance(config, dict) else {}
    pipeline_value = models.get("pipeline") if isinstance(models, dict) else None
    model_root = Path(str(pipeline_value)).expanduser() if pipeline_value else None
    model_source = os.environ.get("MINERU_MODEL_SOURCE") or config.get("model-source", "modelscope")
    model_root_exists = bool(model_root and model_root.is_dir())
    if model_source == "local" and not model_root_exists:
        errors.append(f"Local MinerU model directory does not exist: {model_root}")
    elif not model_root_exists:
        warnings.append("Local pipeline models were not found; MinerU may download them.")

    install_command = (
        f"{shlex.quote(sys.executable)} -m pip install -U {shlex.quote('mineru[all]>=3.4.4,<4')}"
    )
    return {
        "ready": not errors,
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
        },
        "mineru": {
            "version": mineru_version,
            "module_path": mineru_path,
            "required": ">=3.4.4,<4",
        },
        "config": {
            "path": str(config_path.resolve()),
            "exists": config_path.is_file(),
            "config_version": config.get("config_version"),
        },
        "models": {
            "source": model_source,
            "pipeline_root": str(model_root) if model_root else None,
            "pipeline_root_exists": model_root_exists,
        },
        "errors": errors,
        "warnings": warnings,
        "repair_command": install_command,
    }


def _print_doctor(report: dict[str, Any]) -> None:
    status = "READY" if report["ready"] else "NOT READY"
    print(f"MinerU OCR: {status}")
    print(f"Python: {report['python']['version']} ({report['python']['executable']})")
    mineru = report["mineru"]
    print(f"MinerU: {mineru['version'] or 'not installed'} ({mineru['module_path'] or '-'})")
    print(f"Config: {report['config']['path']}")
    print(f"Models: {report['models']['source']} ({report['models']['pipeline_root'] or '-'})")
    for warning in report["warnings"]:
        print(f"Warning: {warning}")
    for error in report["errors"]:
        print(f"Error: {error}", file=sys.stderr)
    if not report["ready"]:
        print(f"Repair: {report['repair_command']}", file=sys.stderr)


def _print_ovis_doctor(report: dict[str, Any]) -> None:
    """Print the standalone OvisOCR2 readiness report."""
    status = "READY" if report["ready"] else "NOT READY"
    print(f"OvisOCR2: {status}")
    print(f"Project: {report['project']}")
    print(f"Python: {report['python']['version'] or '-'} " f"({report['python']['executable']})")
    print(f"Model: {report['model']['path']}")
    for warning in report["warnings"]:
        print(f"Warning: {warning}")
    for error in report["errors"]:
        print(f"Error: {error}", file=sys.stderr)
    if not report["ready"]:
        print(f"Repair: {report['repair_command']}", file=sys.stderr)


def _print_paddlevl_doctor(report: dict[str, Any]) -> None:
    """Print the isolated PaddleOCR-VL-1.6 readiness report."""
    status = "READY" if report["ready"] else "NOT READY"
    print(f"PaddleOCR-VL-1.6: {status}")
    print(f"Python: {report['python']['version'] or '-'} " f"({report['python']['executable']})")
    print(f"Inference: {report['inference_backend']} ({report['machine']})")
    print(f"Model: {report['model']['path']}")
    print(f"Layout: {report['model']['layout_path']}")
    for warning in report["warnings"]:
        print(f"Warning: {warning}")
    for error in report["errors"]:
        print(f"Error: {error}", file=sys.stderr)
    if not report["ready"]:
        print(f"Repair: {report['repair_command']}", file=sys.stderr)


def _load_backend(name: str) -> Any:
    """Lazily instantiate one OCR backend."""
    from ocr.registry import create_backend

    return create_backend(name)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pdf_page_count(path: Path) -> int | None:
    try:
        import fitz

        with fitz.open(str(path)) as document:
            return int(document.page_count)
    except Exception:
        return None


def _content_list_for(markdown: Path, source_stem: str) -> Path | None:
    exact = markdown.with_name(f"{source_stem}_content_list.json")
    if exact.is_file():
        return exact
    candidates = sorted(markdown.parent.glob("*_content_list.json"))
    return candidates[0] if candidates else None


def _parsed_pages(content_list: Path | None) -> list[int]:
    if not content_list:
        return []
    try:
        entries = json.loads(content_list.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(entries, list):
        return []
    indexes = {
        int(entry["page_idx"])
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("page_idx"), int)
    }
    return [index + 1 for index in sorted(indexes)]


def write_ocr_manifest(
    source: Path,
    markdown: Path,
    backend: str,
    max_pages: int | None,
    elapsed_seconds: float,
    requested_path: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Write a deterministic OCR run report and return its path and data."""
    source = source.resolve()
    markdown = markdown.resolve()
    content_list = _content_list_for(markdown, source.stem)
    pages = _parsed_pages(content_list)
    source_pages = _pdf_page_count(source) if source.suffix.lower() == ".pdf" else None
    if source_pages and max_pages:
        expected_pages = min(source_pages, max_pages)
    elif max_pages:
        # Source page count unknown (e.g. undetermined PDF) but a cap was
        # requested: expect the capped page range so coverage stays meaningful
        # instead of silently defaulting to status "complete".
        expected_pages = max_pages
    else:
        expected_pages = source_pages
    coverage_complete: bool | None = None
    if expected_pages is not None and pages:
        coverage_complete = pages == list(range(1, expected_pages + 1))

    images = sorted(
        str(path.resolve())
        for path in markdown.parent.rglob("*")
        if path.is_file() and path.suffix.lower() in _SOURCE_LIKE_SUFFIXES - {".pdf"}
    )
    runtime: dict[str, Any] = {"python": sys.executable}
    if backend == "ovis":
        from ocr._ovis_ocr import inspect_ovis_runtime

        doctor = inspect_ovis_runtime()
        runtime["ovis_project"] = doctor["project"]
        runtime["ovis_python"] = doctor["python"]["executable"]
        runtime["ovis_model"] = doctor["model"]["path"]
    if backend == "paddlevl":
        from ocr._paddleocr_vl import inspect_paddleocr_vl_runtime

        doctor = inspect_paddleocr_vl_runtime()
        runtime["pipeline"] = doctor["pipeline"]
        runtime["inference_backend"] = doctor["inference_backend"]
        runtime["paddlevl_python"] = doctor["python"]["executable"]
        runtime["paddlevl_model"] = doctor["model"]["path"]
        runtime["layout_model"] = doctor["model"]["layout_path"]
    if backend == "mineru":
        doctor = inspect_mineru_runtime()
        runtime["mineru_version"] = doctor["mineru"]["version"]
        runtime["mineru_module_path"] = doctor["mineru"]["module_path"]

    data: dict[str, Any] = {
        "schema_version": 1,
        "status": "complete" if coverage_complete is not False else "incomplete",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "source_sha256": _sha256(source),
        "backend": backend,
        "runtime": runtime,
        "requested_max_pages": max_pages,
        "source_pages": source_pages,
        "expected_pages": expected_pages,
        "parsed_pages": pages,
        "parsed_page_count": len(pages) or None,
        "coverage_complete": coverage_complete,
        "markdown": str(markdown),
        "content_list": str(content_list.resolve()) if content_list else None,
        "images": images,
        "image_count": len(images),
        "elapsed_seconds": round(elapsed_seconds, 3),
    }
    manifest = (
        Path(requested_path).expanduser()
        if requested_path
        else markdown.with_name(f"{source.stem}_ocr_manifest.json")
    )
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest.resolve(), data


def build_parser() -> argparse.ArgumentParser:
    """Build the shared OCR argument parser."""
    from ocr.registry import MODELS

    default_backend = _get_default_backend()
    parser = argparse.ArgumentParser(
        description="Parse images and documents with a configurable OCR model",
        epilog=(
            "Commands: ocr list [--check], ocr use MODEL, "
            "ocr config {path,show,get,set}. Direct use: ocr FILE"
        ),
    )
    parser.add_argument("file", nargs="?", help="Image or PDF file path")
    parser.add_argument(
        "--backend",
        choices=[model.key for model in MODELS],
        default=default_backend,
        help=f"OCR backend (default: {default_backend})",
    )
    parser.add_argument("--batch", help="Process all images/PDFs in a directory")
    parser.add_argument("-o", "--output", help="Output directory for PDF results")
    page_group = parser.add_mutually_exclusive_group()
    page_group.add_argument("-n", "--max-pages", type=int, help="Maximum pages to process")
    page_group.add_argument(
        "--smoke-pages",
        type=int,
        metavar="N",
        help="Smoke-test only the first N pages (recommended: 3)",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Check the selected backend runtime without processing a file",
    )
    parser.add_argument("--manifest", help="Override the automatic OCR manifest path")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser


def _print_model_list(check: bool, as_json: bool) -> int:
    """Print supported OCR models and the current default."""
    from ocr.registry import list_models

    models = list_models(check=check)
    if as_json:
        print(json.dumps({"models": models}, ensure_ascii=False, indent=2))
        return 0
    print("DEFAULT  STATUS       KEY        MODEL")
    for model in models:
        marker = "*" if model["default"] else ""
        status = (
            "ready"
            if model["ready"] is True
            else "not-ready" if model["ready"] is False else "not-checked"
        )
        print(f"{marker:<7}  {status:<11}  {model['key']:<9}  {model['name']}")
        if check and model["detail"] != "ready":
            print(f"{'':22}{model['detail']}")
    return 0


def _run_list_command(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ocr list", description="List supported OCR models")
    parser.add_argument("--check", action="store_true", help="Probe local runtime readiness")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args(argv)
    return _print_model_list(args.check, args.json)


def _run_use_command(argv: list[str]) -> int:
    from ocr.config import set_default_model
    from ocr.registry import MODELS

    parser = argparse.ArgumentParser(prog="ocr use", description="Set the default OCR model")
    parser.add_argument("model", choices=[model.key for model in MODELS])
    args = parser.parse_args(argv)
    path = set_default_model(args.model)
    print(f"Default OCR model: {args.model}")
    print(f"Config: {path}")
    return 0


def _get_dotted_value(config: dict[str, Any], dotted_key: str) -> Any:
    value: Any = config
    for key in dotted_key.split("."):
        if not isinstance(value, dict) or key not in value:
            raise KeyError(dotted_key)
        value = value[key]
    return value


def _run_config_command(argv: list[str]) -> int:
    import yaml

    from ocr.config import get_config_path, load_config, set_config_value
    from ocr.registry import MODELS

    parser = argparse.ArgumentParser(prog="ocr config", description="Manage OCR configuration")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("path", help="Print the active config path")
    commands.add_parser("show", help="Print the complete config")
    get_parser = commands.add_parser("get", help="Read a dotted config value")
    get_parser.add_argument("key")
    set_parser = commands.add_parser("set", help="Set a dotted config value")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    args = parser.parse_args(argv)

    if args.action == "path":
        print(get_config_path())
        return 0
    config = load_config()
    if args.action == "show":
        print(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), end="")
        return 0
    key = args.key
    model_keys = {model.key for model in MODELS}
    if key.split(".", 1)[0] in model_keys:
        key = f"models.{key}"
    if args.action == "get":
        try:
            value = _get_dotted_value(config, key)
        except KeyError:
            print(f"Error: unknown configuration key: {args.key}", file=sys.stderr)
            return 1
        if isinstance(value, (dict, list)):
            print(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), end="")
        else:
            print(value)
        return 0
    value = yaml.safe_load(args.value)
    path = set_config_value(key, value)
    print(f"Set {key} = {value!r}")
    print(f"Config: {path}")
    return 0


def _validate_positive_pages(value: int | None) -> None:
    if value is not None and value < 1:
        raise ValueError("page limit must be at least 1")


def main(argv: list[str] | None = None) -> int:
    """Run OCR and return a process exit code."""
    multiprocessing.freeze_support()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv:
        command, command_args = raw_argv[0], raw_argv[1:]
        if command == "list":
            return _run_list_command(command_args)
        if command in {"use", "select", "default"}:
            return _run_use_command(command_args)
        if command == "config":
            return _run_config_command(command_args)
    parser = build_parser()
    args = parser.parse_args(raw_argv)

    if args.doctor:
        if args.backend == "paddlevl":
            from ocr._paddleocr_vl import inspect_paddleocr_vl_runtime

            report = inspect_paddleocr_vl_runtime()
        elif args.backend == "ovis":
            from ocr._ovis_ocr import inspect_ovis_runtime

            report = inspect_ovis_runtime()
        elif args.backend != "mineru":
            from ocr.registry import get_model

            ready, detail = get_model(args.backend).probe()
            report = {
                "ready": ready,
                "backend": args.backend,
                "detail": detail,
            }
        else:
            report = inspect_mineru_runtime()
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        elif args.backend == "mineru":
            _print_doctor(report)
        elif args.backend == "ovis":
            _print_ovis_doctor(report)
        elif args.backend == "paddlevl":
            _print_paddlevl_doctor(report)
        else:
            status = "READY" if report["ready"] else "NOT READY"
            print(f"{args.backend} OCR: {status}")
            print(f"Detail: {report['detail']}")
        return 0 if report["ready"] else 2

    if not args.file and not args.batch:
        parser.error("provide FILE, --batch DIRECTORY, or --doctor")

    max_pages = args.smoke_pages if args.smoke_pages is not None else args.max_pages
    try:
        _validate_positive_pages(max_pages)
        if args.backend == "paddlevl":
            from ocr._paddleocr_vl import inspect_paddleocr_vl_runtime

            readiness = inspect_paddleocr_vl_runtime()
            if not readiness["ready"]:
                if args.json:
                    print(json.dumps(readiness, ensure_ascii=False, indent=2))
                else:
                    _print_paddlevl_doctor(readiness)
                return 2
        if args.backend == "ovis":
            from ocr._ovis_ocr import inspect_ovis_runtime

            readiness = inspect_ovis_runtime()
            if not readiness["ready"]:
                if args.json:
                    print(json.dumps(readiness, ensure_ascii=False, indent=2))
                else:
                    _print_ovis_doctor(readiness)
                return 2
        if args.backend == "mineru":
            readiness = inspect_mineru_runtime()
            if not readiness["ready"]:
                if args.json:
                    print(json.dumps(readiness, ensure_ascii=False, indent=2))
                else:
                    _print_doctor(readiness)
                return 2
        ocr = _load_backend(args.backend)

        if args.batch:
            batch_dir = Path(args.batch).expanduser()
            if not batch_dir.is_dir():
                raise ValueError(f"not a directory: {batch_dir}")
            supported = _SOURCE_LIKE_SUFFIXES
            results: list[dict[str, Any]] = []
            for source in sorted(batch_dir.iterdir()):
                if not source.is_file() or source.suffix.lower() not in supported:
                    continue
                started = time.monotonic()
                if source.suffix.lower() in _PAGINATED_SUFFIXES:
                    output = resolve_output_dir(
                        source,
                        args.output,
                        source.with_name(f"{source.stem}_ocr"),
                    )
                    # A shared --output would let later files' MinerU results
                    # overwrite earlier ones; give each source its own subdir.
                    if args.output:
                        output = output / f"{source.stem}_ocr"
                    markdown = Path(ocr.ocr_pdf(str(source), output, max_pages=max_pages))
                    manifest, data = write_ocr_manifest(
                        source,
                        markdown,
                        args.backend,
                        max_pages,
                        time.monotonic() - started,
                    )
                    results.append(
                        {
                            "file": str(source.resolve()),
                            "output": str(markdown.resolve()),
                            "manifest": str(manifest),
                            "status": data["status"],
                        }
                    )
                else:
                    text = ocr.ocr_image(str(source))
                    results.append({"file": str(source.resolve()), "text_length": len(text)})
            print(json.dumps({"ocr_results": results}, indent=2, ensure_ascii=False))
            return 0

        source = Path(args.file).expanduser()
        if not source.is_file():
            raise ValueError(f"file does not exist: {source}")
        if source.suffix.lower() in _PAGINATED_SUFFIXES:
            output = resolve_output_dir(source, args.output, f"{source.stem}_ocr")
            started = time.monotonic()
            markdown = Path(ocr.ocr_pdf(str(source), output, max_pages=max_pages))
            manifest, data = write_ocr_manifest(
                source,
                markdown,
                args.backend,
                max_pages,
                time.monotonic() - started,
                args.manifest,
            )
            result = {
                "status": data["status"],
                "output": str(markdown.resolve()),
                "manifest": str(manifest),
                "parsed_pages": data["parsed_pages"],
                "image_count": data["image_count"],
            }
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"Output: {result['output']}")
                print(f"Manifest: {result['manifest']}")
            return 0 if data["status"] == "complete" else 3

        text = ocr.ocr_image(str(source))
        if args.output:
            output_file = validate_output_file(source, args.output)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(text, encoding="utf-8")
            print(f"Output: {output_file.resolve()}")
        else:
            print(text)
        return 0
    except Exception as exc:
        if args.json:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
