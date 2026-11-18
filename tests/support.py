"""Shared helpers for the test suite: HTTP calls, uploads and PDF checks."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pymupdf

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> Path:
    return FIXTURES / name


def call(base: str, method: str, path: str, body=None, headers=None):
    """Returns (status, parsed JSON or None). Error bodies are parsed too."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"X-PDF-Studio": "1", **(headers or {})})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, _parse(res.read())
    except urllib.error.HTTPError as err:
        return err.code, _parse(err.read())


def _parse(raw: bytes):
    """JSON when the body is JSON, otherwise the raw bytes (e.g. a PNG)."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def upload(base: str, path: Path, password: str | None = None, filename: str = "test.pdf"):
    """Multipart upload of a file from disk. Returns (status, parsed JSON or text)."""
    boundary = uuid.uuid4().hex
    parts = []

    def field(name, value, extra=""):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"{extra}\r\n\r\n'.encode())
        parts.append(value)
        parts.append(b"\r\n")

    field("file", path.read_bytes(), f'; filename="{filename}"\r\nContent-Type: application/pdf')
    if password is not None:
        field("password", password.encode())
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(base + "/api/docs", data=b"".join(parts), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("X-PDF-Studio", "1")
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            return err.code, json.loads(raw)
        except ValueError:
            return err.code, raw.decode(errors="replace")


def doc_id_of(base: str, path: Path) -> str:
    status, body = upload(base, path)
    assert status == 200, (status, body)
    return body["id"]


def saved_pdf(base: str, doc: str) -> pymupdf.Document:
    with urllib.request.urlopen(base + f"/api/docs/{doc}/export/pdf") as res:
        return pymupdf.open(stream=res.read(), filetype="pdf")


def word_text(doc: pymupdf.Document, page: int = 0) -> str:
    return " ".join(w[4] for w in doc[page].get_text("words"))


def fonts_with(doc: pymupdf.Document, token: str) -> list[str]:
    found = []
    for block in doc[0].get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if token in span["text"]:
                    found.append(span["font"])
    return found


def open_file(page, path: Path) -> str:
    """Opens a file through the Open button and returns the document id."""
    page.set_input_files("#file-input", path)
    page.wait_for_selector("#stage:not([hidden])")
    page.wait_for_timeout(900)
    return page.evaluate("() => localStorage.getItem('pdfstudio.doc')")


def click_line(page, title: str) -> dict:
    """Clicks a text line by its title, after closing any open editor."""
    page.keyboard.press("Escape")
    page.wait_for_timeout(250)
    box = page.locator(f".tl-box[title*='{title}']").bounding_box()
    page.mouse.click(box["x"] + 20, box["y"] + box["height"] / 2)
    page.wait_for_timeout(400)
    return box


def saved_text(base: str, doc: str) -> str:
    return word_text(saved_pdf(base, doc))
