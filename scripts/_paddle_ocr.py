"""_paddle_ocr.py — Client for the local PaddleOCR-VL-1.5 server.

Provides a clean Python API for OCR operations, communicating with
the local serve  r started by ocr_server.py.

Usage:
    from _paddle_ocr import PaddleOCRLocal

    ocr = PaddleOCRLocal()  # default: http://127.0.0.1:8765
    text = ocr.image("screenshot.png")
    result = ocr.pdf("document.pdf")
    health = ocr.ping()
"""

import os
import urllib.error
import urllib.request
from typing import Optional


class PaddleOCRLocal:
    """Client for local PaddleOCR-VL-1.5 inference server."""

    def __init__(self, base_url: str = "http://127.0.0.1:8765"):
        self.base_url = base_url.rstrip("/")

    def ping(self) -> bool:
        """Check if the OCR server is running."""
        try:
            req = urllib.request.Request(f"{self.base_url}/health")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def image(self, filepath: str) -> Optional[str]:
        """OCR a single image file. Returns markdown text, or None on failure."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Image not found: {filepath}")

        boundary = "----ocrboundary"
        with open(filepath, "rb") as f:
            image_data = f.read()

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{os.path.basename(filepath)}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + image_data + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{self.base_url}/ocr/image",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

        try:
            import json
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
                return data.get("text") or data.get("markdown", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f"OCR server error ({e.code}): {body}")
        except urllib.error.URLError:
            raise RuntimeError(
                f"Cannot connect to OCR server at {self.base_url}. "
                f"Start it with: python scripts/ocr_server.py"
            )

    def pdf(self, filepath: str) -> Optional[str]:
        """OCR a PDF file. Returns combined markdown text, or None on failure."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"PDF not found: {filepath}")

        boundary = "----ocrboundary"
        with open(filepath, "rb") as f:
            pdf_data = f.read()

        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="pdf"; filename="{os.path.basename(filepath)}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode() + pdf_data + f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{self.base_url}/ocr/pdf",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

        try:
            import json
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode())
                return data.get("combined", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            raise RuntimeError(f"OCR server error ({e.code}): {body}")
        except urllib.error.URLError:
            raise RuntimeError(
                f"Cannot connect to OCR server at {self.base_url}. "
                f"Start it with: python scripts/ocr_server.py"
            )


def get_ocr_client(base_url: str = "http://127.0.0.1:8765") -> PaddleOCRLocal:
    """Factory: get an OCR client, verifying the server is reachable."""
    client = PaddleOCRLocal(base_url)
    if not client.ping():
        raise RuntimeError(
            f"OCR server not reachable at {base_url}. "
            f"Start it with: python scripts/ocr_server.py"
        )
    return client
