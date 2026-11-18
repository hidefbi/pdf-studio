"""Backend API tests: uploads, history, rendering, page tools, bookmarks and comments."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pymupdf

from support import call, doc_id_of, fixture, saved_pdf, upload, word_text

ROOT = Path(__file__).resolve().parent.parent


def rotate(base, doc, angle=90):
    return call(base, "POST", f"/api/docs/{doc}/ops",
                {"ops": [{"type": "rotate_page", "page": 0, "angle": angle}]})[0]


def rotation(base, doc):
    return call(base, "GET", f"/api/docs/{doc}")[1]["pages"][0]["rotation"]


def get_bytes(base, path):
    with urllib.request.urlopen(base + path) as res:
        return res.read(), res.headers


def curl_upload(base, path, field="file", url_path="/api/docs"):
    out = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-F", f"{field}=@{path}", base + url_path],
        capture_output=True, text=True, check=True,
    )
    return int(out.stdout)


def test_identity_and_host_guard(server):
    status, body = call(server.base, "GET", "/api/identity")
    assert status == 200 and body == {"app": "pdf-studio"}
    req = urllib.request.Request(server.base + "/api/identity", headers={"Host": "evil.example"})
    try:
        urllib.request.urlopen(req)
        raise AssertionError("foreign Host header was accepted")
    except urllib.error.HTTPError as err:
        assert err.code == 400
        assert b"Invalid host header" in err.read()


def test_upload_accepts_pdf_and_rejects_junk(server, tmp_path):
    status, body = upload(server.base, fixture("embedded.pdf"))
    assert status == 200 and body["id"]
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf at all")
    assert upload(server.base, junk)[0] == 400


def test_upload_over_limit_is_refused_and_leaves_no_temp_file(server, tmp_path):
    big = tmp_path / "big.pdf"
    with open(big, "wb") as handle:
        handle.truncate(501 * 1024 * 1024)
    assert curl_upload(server.base, big) == 413
    assert not [name for name in os.listdir(server.data_dir) if name.endswith(".upload")]


def test_font_over_limit_is_refused(server, tmp_path):
    big = tmp_path / "big.ttf"
    with open(big, "wb") as handle:
        handle.truncate(31 * 1024 * 1024)
    assert curl_upload(server.base, big, url_path="/api/fonts") == 413


def test_history_is_capped_and_undo_stops_at_the_cap(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    for _ in range(35):
        assert rotate(server.base, doc) == 200
    assert call(server.base, "GET", f"/api/docs/{doc}")[1]["undo_steps"] == 30
    assert len(os.listdir(server.data_dir / "docs" / doc / "history")) == 30
    for _ in range(30):
        assert call(server.base, "POST", f"/api/docs/{doc}/undo")[0] == 200
    assert call(server.base, "POST", f"/api/docs/{doc}/undo")[0] == 409


def test_redo_round_trip_and_new_edit_clears_redo(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    for _ in range(3):
        rotate(server.base, doc)
    assert rotation(server.base, doc) == 270
    call(server.base, "POST", f"/api/docs/{doc}/undo")
    call(server.base, "POST", f"/api/docs/{doc}/undo")
    assert rotation(server.base, doc) == 90
    status, body = call(server.base, "POST", f"/api/docs/{doc}/redo")
    assert status == 200 and body["redo_steps"] == 1 and body["undo_steps"] == 2
    assert rotation(server.base, doc) == 180
    assert rotate(server.base, doc) == 200
    assert call(server.base, "GET", f"/api/docs/{doc}")[1]["redo_steps"] == 0
    assert call(server.base, "POST", f"/api/docs/{doc}/redo")[0] == 409


def test_legacy_document_without_redo_folder_still_works(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    rotate(server.base, doc)
    folder = server.data_dir / "docs" / doc
    shutil.rmtree(folder / "redo")
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    meta.pop("redo")
    meta.pop("version")
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    assert call(server.base, "POST", f"/api/docs/{doc}/undo")[0] == 200
    assert call(server.base, "POST", f"/api/docs/{doc}/redo")[0] == 200
    info = call(server.base, "GET", f"/api/docs/{doc}")[1]
    assert {"undo_steps", "redo_steps", "version"} <= set(info)


def test_delete_document_removes_it(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    assert call(server.base, "DELETE", f"/api/docs/{doc}")[0] == 200
    assert call(server.base, "GET", f"/api/docs/{doc}")[0] == 404
    assert not (server.data_dir / "docs" / doc).exists()
    assert call(server.base, "DELETE", f"/api/docs/{doc}")[0] == 404


def test_page_images_follow_document_versions(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    first, headers = get_bytes(server.base, f"/api/docs/{doc}/pages/0.png?zoom=2&v=0")
    assert "max-age" in headers.get("Cache-Control", "")
    assert get_bytes(server.base, f"/api/docs/{doc}/pages/0.png?zoom=2&v=0")[0] == first
    rotate(server.base, doc)
    edited, _ = get_bytes(server.base, f"/api/docs/{doc}/pages/0.png?zoom=2&v=1")
    assert edited != first
    call(server.base, "POST", f"/api/docs/{doc}/undo")
    assert get_bytes(server.base, f"/api/docs/{doc}/pages/0.png?zoom=2&v=2")[0] == first
    call(server.base, "POST", f"/api/docs/{doc}/redo")
    assert get_bytes(server.base, f"/api/docs/{doc}/pages/0.png?zoom=2&v=3")[0] == edited


def test_render_zoom_is_capped_at_4(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    assert call(server.base, "GET", f"/api/docs/{doc}/pages/0.png?zoom=4.5")[0] == 422
    assert call(server.base, "GET", f"/api/docs/{doc}/pages/0.png?zoom=4")[0] == 200


def test_render_cache_respects_its_byte_cap(tmp_path):
    """Runs in a child process, because the app reads its settings at import time."""
    code = (
        "import sys\n"
        "from fastapi.testclient import TestClient\n"
        "import app.main as m\n"
        "m.RENDER_CACHE_BYTES = 300_000\n"
        "c = TestClient(m.app, base_url='http://127.0.0.1')\n"
        "doc = c.post('/api/docs', files={'file': ('m.pdf', open(sys.argv[1], 'rb'), 'application/pdf')}).json()['id']\n"
        "c.post(f'/api/docs/{doc}/pages/blank', json={'after': 0})\n"
        "c.post(f'/api/docs/{doc}/pages/blank', json={'after': 0})\n"
        "for i in range(3):\n"
        "    for z in (1, 2, 3):\n"
        "        assert c.get(f'/api/docs/{doc}/pages/{i}.png', params={'zoom': z}).status_code == 200\n"
        "assert m._render_bytes <= 300_000, m._render_bytes\n"
        "assert m._render_cache\n"
        "c.delete(f'/api/docs/{doc}')\n"
        "assert not any(k[0] == doc for k in m._render_cache)\n"
        "print('CACHE_OK')\n"
    )
    env = dict(os.environ, PDF_STUDIO_DATA=str(tmp_path), PDF_STUDIO_NO_WATCHDOG="1")
    result = subprocess.run([sys.executable, "-W", "ignore", "-c", code, str(fixture("multi.pdf"))],
                            cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "CACHE_OK" in result.stdout


def test_encrypted_pdf_needs_the_password(server, encrypted_pdf):
    status, body = upload(server.base, encrypted_pdf)
    assert status == 401 and body["detail"] == "password required"
    status, body = upload(server.base, encrypted_pdf, password="nope")
    assert status == 401 and body["detail"] == "wrong password"
    status, body = upload(server.base, encrypted_pdf, password="secret")
    assert status == 200
    info = call(server.base, "GET", f"/api/docs/{body['id']}")[1]
    assert len(info["pages"]) == 2
    stored = pymupdf.open(server.data_dir / "docs" / body["id"] / "current.pdf")
    assert not stored.needs_pass and not stored.is_encrypted
    stored.close()


def test_blank_pages_insert_after_index(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    assert call(server.base, "POST", f"/api/docs/{doc}/pages/blank", {"after": 0})[1]["pages"] == 2
    assert call(server.base, "POST", f"/api/docs/{doc}/pages/blank", {"after": -1})[1]["pages"] == 3
    assert call(server.base, "POST", f"/api/docs/{doc}/pages/blank", {"after": 40})[0] == 404


def test_page_number_and_header_stamps(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    call(server.base, "POST", f"/api/docs/{doc}/pages/blank", {"after": 0})
    call(server.base, "POST", f"/api/docs/{doc}/pages/blank", {"after": -1})
    status, _ = call(server.base, "POST", f"/api/docs/{doc}/stamp",
                     {"text": "{page} / {total}", "where": "bottom-center", "size": 10, "color": "#666666"})
    assert status == 200
    saved = saved_pdf(server.base, doc)
    assert len(saved) == 3
    assert "2 / 3" in word_text(saved, 1) and "3 / 3" in word_text(saved, 2)
    status, _ = call(server.base, "POST", f"/api/docs/{doc}/stamp",
                     {"text": "{name} header", "where": "top-left", "pages": "current", "page": 0})
    assert status == 200
    saved = saved_pdf(server.base, doc)
    assert "header" in word_text(saved, 0) and "header" not in word_text(saved, 1)


def test_watermark_accepts_cjk_and_rotation_and_validates_input(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    status, _ = call(server.base, "POST", f"/api/docs/{doc}/stamp",
                     {"text": "\u673a\u5bc6 DRAFT", "where": "center", "angle": 45, "opacity": 0.3,
                      "behind": True, "color": "#cc0000", "size": 48})
    assert status == 200
    assert call(server.base, "POST", f"/api/docs/{doc}/stamp", {"text": "x", "where": "middle"})[0] == 400
    assert call(server.base, "POST", f"/api/docs/{doc}/stamp", {"text": "x", "color": "red"})[0] == 400


def test_bookmarks_round_trip_and_validation(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    items = [{"level": 1, "title": "Intro", "page": 1}, {"level": 2, "title": "Detail", "page": 1}]
    assert call(server.base, "PUT", f"/api/docs/{doc}/toc", {"items": items})[0] == 200
    read = call(server.base, "GET", f"/api/docs/{doc}/toc")[1]["items"]
    assert [i["title"] for i in read] == ["Intro", "Detail"]
    assert call(server.base, "PUT", f"/api/docs/{doc}/toc",
                {"items": [{"level": 2, "title": "x", "page": 1}]})[0] == 400
    assert call(server.base, "PUT", f"/api/docs/{doc}/toc",
                {"items": [{"level": 1, "title": "x", "page": 99}]})[0] == 400
    assert call(server.base, "PUT", f"/api/docs/{doc}/toc", {"items": []})[0] == 200


def test_comments_list_edit_undo_and_delete(server, annotated_pdf):
    doc = doc_id_of(server.base, annotated_pdf)
    items = call(server.base, "GET", f"/api/docs/{doc}/annotations")[1]["items"]
    assert len(items) == 1 and items[0]["content"] == "first note"
    xref = items[0]["xref"]
    assert call(server.base, "PATCH", f"/api/docs/{doc}/annotations/{xref}", {"content": "edited note"})[0] == 200
    assert call(server.base, "GET", f"/api/docs/{doc}/annotations")[1]["items"][0]["content"] == "edited note"
    assert call(server.base, "POST", f"/api/docs/{doc}/undo")[0] == 200
    assert call(server.base, "GET", f"/api/docs/{doc}/annotations")[1]["items"][0]["content"] == "first note"
    xref = call(server.base, "GET", f"/api/docs/{doc}/annotations")[1]["items"][0]["xref"]
    assert call(server.base, "DELETE", f"/api/docs/{doc}/annotations/{xref}")[0] == 200
    assert call(server.base, "GET", f"/api/docs/{doc}/annotations")[1]["items"] == []
    assert call(server.base, "PATCH", f"/api/docs/{doc}/annotations/999999", {"content": "x"})[0] == 404
