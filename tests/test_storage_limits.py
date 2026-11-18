"""Private file modes, and the limits on page count and pixel size."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pymupdf

from support import call, doc_id_of, fixture, upload

ROOT = Path(__file__).resolve().parent.parent


def mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


def make_pdf(folder: Path, name: str, pages: int, width: float = 595, height: float = 842) -> Path:
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page(width=width, height=height)
    path = folder / name
    doc.save(path)
    doc.close()
    return path


def test_saved_files_are_private(server):
    doc = doc_id_of(server.base, fixture("align.pdf"))
    folder = server.data_dir / "docs" / doc
    assert mode(folder) == 0o700
    assert mode(folder / "current.pdf") == 0o600
    assert mode(folder / "meta.json") == 0o600
    status, _ = call(server.base, "POST", f"/api/docs/{doc}/ops",
                     {"ops": [{"type": "rotate_page", "page": 0, "angle": 90}]})
    assert status == 200
    assert mode(folder / "current.pdf") == 0o600
    assert mode(folder / "history" / "000001.pdf") == 0o600


def test_old_files_are_tightened_on_start(tmp_path):
    old = tmp_path / "docs" / "old"
    old.mkdir(parents=True)
    meta = old / "meta.json"
    meta.write_text("{}")
    os.chmod(meta, 0o644)
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    index = fonts / "index.json"
    index.write_text("[]")
    os.chmod(index, 0o644)
    code = "import os, sys\nimport app.main\nprint(*(oct(os.stat(p).st_mode & 0o777) for p in sys.argv[1:]))\n"
    env = dict(os.environ, PDF_STUDIO_DATA=str(tmp_path), PDF_STUDIO_NO_WATCHDOG="1")
    result = subprocess.run([sys.executable, "-c", code, str(meta), str(index)],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.split() == ["0o600", "0o600"]


def test_upload_over_page_limit_is_refused(server, tmp_path):
    status, body = upload(server.base, make_pdf(tmp_path, "long.pdf", pages=2001))
    assert status == 413, body


def test_blank_page_stops_at_page_limit(server, tmp_path):
    status, body = upload(server.base, make_pdf(tmp_path, "full.pdf", pages=2000))
    assert status == 200, body
    assert call(server.base, "POST", f"/api/docs/{body['id']}/pages/blank", {"after": 0})[0] == 413


def test_merge_over_page_limit_is_refused(server, tmp_path):
    first = upload(server.base, make_pdf(tmp_path, "a.pdf", pages=1500))[1]["id"]
    second = upload(server.base, make_pdf(tmp_path, "b.pdf", pages=1500))[1]["id"]
    assert call(server.base, "POST", "/api/merge", {"ids": [first, second], "name": "both"})[0] == 413


def test_pixel_budget_applies_to_render_export_and_ocr(server, tmp_path):
    status, body = upload(server.base, make_pdf(tmp_path, "huge.pdf", pages=1, width=14400, height=14400))
    assert status == 200, body
    doc = body["id"]
    assert call(server.base, "GET", f"/api/docs/{doc}/pages/0.png?zoom=0.2")[0] == 200
    assert call(server.base, "GET", f"/api/docs/{doc}/pages/0.png?zoom=4")[0] == 413
    assert call(server.base, "GET", f"/api/docs/{doc}/export/png?zoom=4")[0] == 413
    assert call(server.base, "GET", f"/api/docs/{doc}/export/images?zoom=4")[0] == 413
    assert call(server.base, "POST", f"/api/docs/{doc}/pages/0/ocr")[0] == 413


def test_normal_page_renders_at_top_zoom(server):
    doc = doc_id_of(server.base, fixture("align.pdf"))
    assert call(server.base, "GET", f"/api/docs/{doc}/pages/0.png?zoom=4")[0] == 200
    status, body = call(server.base, "GET", f"/api/docs/{doc}/export/images")
    assert status == 200 and body[:2] == b"PK"


def test_upload_reports_unlocked_copy(server, tmp_path):
    locked = tmp_path / "locked.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "LOCKED BODY")
    doc.save(locked, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="own-test-1", user_pw="pw-test-1")
    doc.close()
    status, body = upload(server.base, locked, password="pw-test-1")
    assert status == 200 and body["unlocked"] is True
    status, body = upload(server.base, fixture("align.pdf"))
    assert status == 200 and body["unlocked"] is False


def test_leftovers_are_removed_on_start(tmp_path):
    leftover = tmp_path / "pdfstudio-old.upload.plain"
    leftover.write_bytes(b"x")
    stale = tmp_path / "docs" / "old" / "current.tmp"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"x")
    users_file = tmp_path / "other.zip"
    users_file.write_bytes(b"keep")
    env = dict(os.environ, PDF_STUDIO_DATA=str(tmp_path), PDF_STUDIO_NO_WATCHDOG="1")
    result = subprocess.run([sys.executable, "-c", "import app.main"],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    assert not leftover.exists()
    assert not stale.exists()
    assert users_file.read_bytes() == b"keep"
