"""Saves keep the file small, and a move redraws only the thumbnails it touched."""
from __future__ import annotations

import re

import fitz

from support import call, click_line, doc_id_of, fixture, open_file


def test_edit_does_not_recompress_the_file(server):
    doc = doc_id_of(server.base, fixture("embedded.pdf"))
    current = server.data_dir / "docs" / doc / "current.pdf"
    before = current.stat().st_size
    # The working copy is compressed at upload, so it is well under the original file size.
    assert before < fixture("embedded.pdf").stat().st_size * 0.7
    body = {"type": "text", "page": 0, "rect": [72, 600, 300, 620], "text": "small edit", "size": 12, "color": [0, 0, 0]}
    status, _ = call(server.base, "POST", f"/api/docs/{doc}/ops", {"ops": [body]})
    assert status == 200
    after = current.stat().st_size
    # An edit must not grow the file back toward its uncompressed size.
    assert after < before * 1.2


def test_move_redraws_only_touched_thumbnails(ui, server, tmp_path):
    out = fitz.open()
    for _ in range(20):
        out.insert_pdf(fitz.open(fixture("embedded.pdf")))
    path = tmp_path / "twenty.pdf"
    out.save(path)
    page = ui.page
    open_file(page, path)
    page.wait_for_timeout(800)
    assert page.locator(".thumb").count() >= 5
    thumb_hits = []

    def watch(req):
        m = re.search(r"\.png\?zoom=([\d.]+)", req.url)
        if m and float(m.group(1)) < 1.0:  # thumbnails are drawn small, pages large
            thumb_hits.append(req.url)

    page.on("request", watch)
    click_line(page, "Embedded line one")
    box = page.locator(".tl-box[title*='Embedded line one']").bounding_box()
    page.mouse.move(box["x"] + 20, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 60, box["y"] + box["height"] / 2 + 30, steps=5)
    page.mouse.up()
    page.wait_for_function("() => document.querySelectorAll('.tl-ghost').length === 0")
    page.wait_for_timeout(1500)
    page.remove_listener("request", watch)
    assert len(thumb_hits) <= 2, thumb_hits
    assert not ui.errors
