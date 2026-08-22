#!/usr/bin/env python3
"""Isolated PaddleOCR-VL-1.6 worker used by :mod:`ocr._paddleocr_vl`."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Any


def _free_port() -> int:
    """Reserve an ephemeral loopback port number."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(process: subprocess.Popen[str], port: int, timeout: float) -> None:
    """Wait until the child MLX server accepts TCP connections."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"MLX-VLM server exited with code {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("MLX-VLM server did not become ready within 30 seconds")


def _start_server(output_dir: Path) -> tuple[subprocess.Popen[str], str, IO[str]]:
    """Start a private MLX-VLM server and return process, URL, and log handle."""
    port = _free_port()
    log_handle = (output_dir / "mlx-vlm-server.log").open("w", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-m", "mlx_vlm.server", "--port", str(port)],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        _wait_for_server(process, port, timeout=30)
    except Exception:
        process.terminate()
        process.wait(timeout=10)
        log_handle.close()
        raise
    return process, f"http://127.0.0.1:{port}/", log_handle


def _stop_server(process: subprocess.Popen[str] | None, log_handle: IO[str] | None) -> None:
    """Stop only the private child server created by this worker."""
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if log_handle is not None:
        log_handle.close()


def _prefix_assets(content: str, page_dir_name: str) -> str:
    """Make page-local generated image paths relative to the root report."""
    content = content.replace('src="imgs/', f'src="{page_dir_name}/imgs/')
    content = content.replace("](imgs/", f"]({page_dir_name}/imgs/")
    return content


def run(args: argparse.Namespace) -> Path:
    """Run the full layout + VLM pipeline and assemble ordered Markdown."""
    from paddleocr import PaddleOCRVL

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    server_process: subprocess.Popen[str] | None = None
    server_log: IO[str] | None = None
    server_url = args.server_url

    if args.inference_backend == "mlx-vlm-server" and not server_url:
        server_process, server_url, server_log = _start_server(output_dir)

    pipeline: Any | None = None
    try:
        kwargs: dict[str, Any] = {
            "pipeline_version": "v1.6",
            "layout_detection_model_dir": args.layout_model_path,
            "vl_rec_backend": args.inference_backend,
            "device": args.device,
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_queues": False,
        }
        if args.inference_backend == "mlx-vlm-server":
            kwargs.update(
                {
                    "vl_rec_server_url": server_url,
                    "vl_rec_api_model_name": args.model_path,
                }
            )
        else:
            kwargs["vl_rec_model_dir"] = args.model_path

        pipeline = PaddleOCRVL(**kwargs)
        results = pipeline.predict(
            args.input,
            temperature=0.0,
            max_new_tokens=args.max_new_tokens,
        )
        sections: list[str] = []
        parsed_pages: list[dict[str, int]] = []
        for page_number, result in enumerate(results, start=1):
            page_dir_name = f"page-{page_number:03d}"
            page_dir = output_dir / page_dir_name
            page_dir.mkdir(parents=True, exist_ok=True)
            result.save_to_markdown(str(page_dir))
            result.save_to_json(str(page_dir))
            markdown_files = sorted(page_dir.glob("*.md"))
            if not markdown_files:
                raise RuntimeError(f"No Markdown emitted for page {page_number}")
            content = markdown_files[0].read_text(encoding="utf-8").strip()
            sections.append(f"## Page {page_number}\n\n" + _prefix_assets(content, page_dir_name))
            parsed_pages.append({"page_idx": page_number - 1})

        if not sections:
            raise RuntimeError("PaddleOCR-VL-1.6 returned zero pages")
        report = output_dir / f"{args.source_stem}.md"
        report.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
        content_list = output_dir / f"{args.source_stem}_content_list.json"
        content_list.write_text(
            json.dumps(parsed_pages, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return report
    finally:
        if pipeline is not None:
            close = getattr(pipeline, "close", None)
            if callable(close):
                close()
        _stop_server(server_process, server_log)


def build_parser() -> argparse.ArgumentParser:
    """Build the isolated worker CLI."""
    parser = argparse.ArgumentParser(description="PaddleOCR-VL-1.6 worker")
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--source-stem", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--layout-model-path", required=True)
    parser.add_argument(
        "--inference-backend",
        default="mlx-vlm-server",
        choices=["mlx-vlm-server", "native"],
    )
    parser.add_argument("--server-url", default="")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the worker CLI."""
    args = build_parser().parse_args(argv)
    report = run(args)
    print(json.dumps({"status": "complete", "output": str(report)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
