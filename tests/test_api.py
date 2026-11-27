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


def test_ocr_hands_the_engine_bytes_not_a_temp_file(tmp_path):
    pdf = tmp_path / "scan.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 100), "scan", fontsize=24)
    doc.save(pdf)
    doc.close()
    script = """
import json, sys
from pathlib import Path
from app import main as m

seen = []

class FakeEngine:
    def __call__(self, img):
        seen.append(type(img).__name__)
        return [], [0.0]

m._ocr_engine = FakeEngine()
doc_id = m._create_doc(Path(sys.argv[1]).read_bytes(), "scan.pdf")
m.ocr_page(doc_id, 0)
print(json.dumps(seen))
"""
    env = dict(os.environ, PDF_STUDIO_DATA=str(tmp_path / "data"), PDF_STUDIO_NO_WATCHDOG="1")
    out = subprocess.run([sys.executable, "-c", script, str(pdf)], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60, check=True)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == ["bytes"]


def test_ops_response_carries_the_same_info_as_get(server):
    doc = doc_id_of(server.base, fixture("multi.pdf"))
    status, body = call(server.base, "POST", f"/api/docs/{doc}/ops",
                        {"ops": [{"type": "rotate_page", "page": 0, "angle": 90}]})
    assert status == 200
    assert body["info"] == call(server.base, "GET", f"/api/docs/{doc}")[1]


def test_ocr_engine_loads_once_on_first_parallel_use(monkeypatch):
    import threading
    import time
    import types

    from app import main as m

    built = []

    class FakeOCR:
        def __init__(self):
            built.append(self)
            time.sleep(0.2)  # long enough for the other threads to arrive

    fake = types.ModuleType("rapidocr_onnxruntime")
    fake.RapidOCR = FakeOCR
    monkeypatch.setitem(sys.modules, "rapidocr_onnxruntime", fake)
    monkeypatch.setattr(m, "_ocr_engine", None)
    threads = [threading.Thread(target=m._get_ocr_engine) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(built) == 1


def test_document_locks_are_per_document():
    import threading

    from app import main as m

    held, release = threading.Event(), threading.Event()

    def hold_first_document():
        with m._doc_lock("first"):
            held.set()
            release.wait(5)

    holder = threading.Thread(target=hold_first_document)
    holder.start()
    try:
        assert held.wait(5)
        other = m._doc_lock("second")
        assert other.acquire(timeout=1)  # not blocked by the first document's lock
        other.release()
        assert m._doc_lock("first") is m._doc_lock("first")
    finally:
        release.set()
        holder.join()


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
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-H", "X-PDF-Studio: 1",
         "-F", f"{field}=@{path}", base + url_path],
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
    assert headers.get("Cache-Control") == "no-store"
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
        "c = TestClient(m.app, base_url='http://127.0.0.1', headers={'X-PDF-Studio': '1'})\n"
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


def watermark_rules(base, doc, rules):
    return call(base, "PUT", f"/api/docs/{doc}/watermarks", {"rules": rules})


def raw_get(base, path):
    with urllib.request.urlopen(base + path) as res:
        return res.read()


def read_only_export(base, doc, body):
    """Returns (status, bytes) for the read-only export, which is a file and not JSON."""
    req = urllib.request.Request(base + f"/api/docs/{doc}/export/readonly", data=json.dumps(body).encode(),
                                 method="POST", headers={"X-PDF-Studio": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def three_pages(base, doc):
    call(base, "POST", f"/api/docs/{doc}/pages/blank", {"after": 0})
    call(base, "POST", f"/api/docs/{doc}/pages/blank", {"after": -1})


def test_watermark_rules_are_saved_and_checked(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    status, _ = watermark_rules(server.base, doc, [{"text": "DRAFT", "rows": 2, "cols": 3}])
    assert status == 200
    rule = call(server.base, "GET", f"/api/docs/{doc}/watermarks")[1]["rules"][0]
    assert (rule["text"], rule["rows"], rule["cols"], rule["angle"], rule["layer"]) == ("DRAFT", 2, 3, 30, "above")
    bad = [
        {"text": "x", "color": "red"},
        {"text": "x", "layer": "middle"},
        {"text": "x", "pages": "one"},
        {"text": "x", "rows": 11},
        {"text": "x", "opacity": 0},
    ]
    for item in bad:
        assert watermark_rules(server.base, doc, [item])[0] == 422, item
    assert watermark_rules(server.base, doc, [{"text": "x"}] * 6)[0] == 422
    big = {"text": "x", "rows": 10, "cols": 10}
    assert watermark_rules(server.base, doc, [big] * 4)[0] == 400
    assert watermark_rules(server.base, doc, [big] * 3 + [dict(big, enabled=False)])[0] == 200


def test_watermark_grid_is_drawn_on_export_and_not_saved_into_the_document(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    three_pages(server.base, doc)
    before = call(server.base, "GET", f"/api/docs/{doc}")[1]
    status, _ = watermark_rules(server.base, doc, [{"text": "SECRET {page}/{total}", "rows": 2, "cols": 3,
                                                    "size": 12, "angle": 0}])
    assert status == 200
    after = call(server.base, "GET", f"/api/docs/{doc}")[1]
    assert (after["undo_steps"], len(after["pages"])) == (before["undo_steps"], 3)
    saved = saved_pdf(server.base, doc)
    assert saved.page_count == 3
    for index in range(3):
        assert word_text(saved, index).count("SECRET") == 6, word_text(saved, index)
    assert "SECRET 2/3" in word_text(saved, 1)


def test_watermark_pages_range_and_disabled_rule(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    three_pages(server.base, doc)
    watermark_rules(server.base, doc, [{"text": "ONLY", "rows": 1, "cols": 1, "pages": "2-3,9"},
                                       {"text": "OFF", "rows": 1, "cols": 1, "enabled": False}])
    saved = saved_pdf(server.base, doc)
    assert "ONLY" not in word_text(saved, 0)
    assert "ONLY" in word_text(saved, 1) and "ONLY" in word_text(saved, 2)
    assert all("OFF" not in word_text(saved, i) for i in range(3))


def test_positive_angle_rises_to_the_right(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    watermark_rules(server.base, doc, [{"text": "RISE7", "rows": 1, "cols": 1, "angle": 30, "size": 20}])
    saved = saved_pdf(server.base, doc)
    lines = [line for block in saved[0].get_text("dict")["blocks"] for line in block.get("lines", [])
             if any("RISE7" in span["text"] for span in line["spans"])]
    assert lines and lines[0]["dir"][1] < 0  # y grows downwards on the page, so a negative value rises


def test_watermark_accepts_cjk_text_and_date(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    status, _ = watermark_rules(server.base, doc, [{"text": "\u673a\u5bc6 {date}", "rows": 1, "cols": 1}])
    assert status == 200
    assert "\u673a\u5bc6" in word_text(saved_pdf(server.base, doc), 0)


def test_watermark_is_in_read_only_export(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    watermark_rules(server.base, doc, [{"text": "ONLY", "rows": 1, "cols": 1}])
    status, data = read_only_export(server.base, doc, {"owner_password": "ownerpw2", "printing": "none",
                                                      "changes": "none", "allow_copy": False})
    assert status == 200
    assert "ONLY" in word_text(pymupdf.open(stream=data, filetype="pdf"), 0)


def test_read_only_export_works_with_every_option_turned_off(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    status, data = read_only_export(server.base, doc, {"owner_password": "ownerpw2", "open_password": "openpw1",
                                                      "printing": "none", "changes": "none", "allow_copy": False})
    assert status == 200 and data.startswith(b"%PDF")


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


def test_read_only_export_limits_passwords_to_40_characters(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    base_body = {"printing": "none", "changes": "none", "allow_copy": False}
    status, data = read_only_export(server.base, doc, dict(base_body, owner_password="a" * 40))
    assert status == 200 and data.startswith(b"%PDF")
    status, data = read_only_export(server.base, doc, dict(base_body, owner_password="\u4e2d" * 40))
    assert status == 200
    status, data = read_only_export(server.base, doc, dict(base_body, owner_password="a" * 41))
    assert status == 400 and b"40 characters" in data
    status, data = read_only_export(server.base, doc, dict(base_body, owner_password="ownerpw2",
                                                          open_password="b" * 41))
    assert status == 400


def test_page_images_show_the_rules_and_follow_changes(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    watermark_rules(server.base, doc, [{"text": "ALPHA", "rows": 1, "cols": 1, "size": 30}])
    rev_before = call(server.base, "GET", f"/api/docs/{doc}")[1]["watermark_rev"]
    shown = raw_get(server.base, f"/api/docs/{doc}/pages/0.png?zoom=1")
    clean = raw_get(server.base, f"/api/docs/{doc}/pages/0.png?zoom=1&watermark=0")
    assert shown != clean
    watermark_rules(server.base, doc, [{"text": "BETA", "rows": 1, "cols": 1, "size": 30}])
    assert call(server.base, "GET", f"/api/docs/{doc}")[1]["watermark_rev"] != rev_before
    assert raw_get(server.base, f"/api/docs/{doc}/pages/0.png?zoom=1") != shown


def test_export_can_leave_watermarks_out(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    watermark_rules(server.base, doc, [{"text": "KEEPOUT", "rows": 1, "cols": 1}])
    with_marks = pymupdf.open(stream=raw_get(server.base, f"/api/docs/{doc}/export/pdf"), filetype="pdf")
    plain = pymupdf.open(stream=raw_get(server.base, f"/api/docs/{doc}/export/pdf?watermark=0"), filetype="pdf")
    assert "KEEPOUT" in word_text(with_marks, 0)
    assert "KEEPOUT" not in word_text(plain, 0)


def test_read_only_export_can_leave_watermarks_out(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    watermark_rules(server.base, doc, [{"text": "MAYBE", "rows": 1, "cols": 1}])
    base_body = {"owner_password": "ownerpw2", "printing": "none", "changes": "none", "allow_copy": False}
    status, data = read_only_export(server.base, doc, dict(base_body, watermarks=False))
    assert status == 200 and "MAYBE" not in word_text(pymupdf.open(stream=data, filetype="pdf"), 0)
    status, data = read_only_export(server.base, doc, base_body)
    assert status == 200 and "MAYBE" in word_text(pymupdf.open(stream=data, filetype="pdf"), 0)
