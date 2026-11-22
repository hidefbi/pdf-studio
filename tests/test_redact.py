"""Redact removes text, pictures, drawings and comments in the area, and drops the undo history."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from support import call, doc_id_of, fixture, open_file, saved_pdf, saved_text

PICTURE = pymupdf.Rect(60, 300, 260, 500)  # solid red picture
AREA = [200, 280, 320, 360]  # cuts the picture's corner and holds the secret text, a drawing and a note
RED = (255, 0, 0)


def make_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "redact.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((210, 330), "Secret plan", fontsize=14)
    page.insert_text((72, 700), "Keep this", fontsize=14)
    img = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20), False)
    img.set_rect(img.irect, RED)
    page.insert_image(PICTURE, pixmap=img)
    page.draw_rect(pymupdf.Rect(270, 290, 300, 310), color=(0, 0, 1), fill=(0, 0, 1))
    page.add_text_annot((300, 340), "private note")
    doc.save(path)
    doc.close()
    return path


def redact(base: str, doc: str, rect: list[float]):
    return call(base, "POST", f"/api/docs/{doc}/ops", {"ops": [{"type": "redact", "page": 0, "rect": rect}]})


def pixel(base: str, doc: str, x: float, y: float) -> tuple[int, int, int]:
    pdf = saved_pdf(base, doc)
    try:
        pix = pdf[0].get_pixmap(matrix=pymupdf.Matrix(1, 1), clip=pymupdf.Rect(x, y, x + 1, y + 1), alpha=False)
        return tuple(pix.samples[0:3])
    finally:
        pdf.close()


def left_in_area(base: str, doc: str):
    pdf = saved_pdf(base, doc)
    try:
        area = pymupdf.Rect(AREA)
        # Only the blue drawing counts; the redaction leaves its own cover fill behind.
        drawings = [d for d in pdf[0].get_drawings() if area.intersects(d["rect"]) and d.get("fill") == (0, 0, 1)]
        notes = [a for a in pdf[0].annots() or [] if area.intersects(a.rect)]
        return drawings, notes
    finally:
        pdf.close()


def test_redact_removes_text_pictures_drawings_and_notes(tmp_path, server):
    doc = doc_id_of(server.base, make_pdf(tmp_path))
    assert pixel(server.base, doc, 230, 340) == RED  # picture under the area before the redact
    assert left_in_area(server.base, doc) != ([], [])  # drawing and note are there before

    status, body = redact(server.base, doc, AREA)
    assert status == 200, body

    text = saved_text(server.base, doc)
    assert "Secret" not in text and "Keep" in text
    assert pixel(server.base, doc, 230, 340) != RED  # inside the area the picture is blanked
    assert pixel(server.base, doc, 100, 450) == RED  # the rest of the picture stays
    assert left_in_area(server.base, doc) == ([], [])


def test_redact_drops_undo_history_and_old_copies(tmp_path, server):
    doc = doc_id_of(server.base, make_pdf(tmp_path))
    status, body = call(server.base, "POST", f"/api/docs/{doc}/ops",
                        {"ops": [{"type": "rect", "page": 0, "rect": [60, 600, 120, 640], "color": [0, 0, 0]}]})
    assert status == 200, body
    status, info = call(server.base, "GET", f"/api/docs/{doc}")
    assert info["undo_steps"] == 1

    status, body = redact(server.base, doc, AREA)
    assert status == 200, body
    status, info = call(server.base, "GET", f"/api/docs/{doc}")
    assert info["undo_steps"] == 0 and info["redo_steps"] == 0

    status, _ = call(server.base, "POST", f"/api/docs/{doc}/undo")
    assert status == 409

    doc_dir = server.data_dir / "docs" / doc
    extra = [p.name for p in doc_dir.rglob("*") if p.is_file() and p.name not in ("current.pdf", "meta.json")]
    assert extra == []
    for path in doc_dir.rglob("*"):
        if path.is_file():
            assert b"Secret" not in path.read_bytes(), path.name


def test_redact_needs_a_real_area(tmp_path, server):
    doc = doc_id_of(server.base, make_pdf(tmp_path))
    status, body = redact(server.base, doc, [100, 100, 100, 100])
    assert status == 400, body


def test_old_replace_text_op_is_gone(tmp_path, server):
    doc = doc_id_of(server.base, make_pdf(tmp_path))
    status, _ = call(server.base, "POST", f"/api/docs/{doc}/ops",
                     {"ops": [{"type": "replace_text", "page": 0, "rect": AREA, "text": ""}]})
    assert status == 400


def test_ordinary_edits_still_keep_undo(tmp_path, server):
    doc = doc_id_of(server.base, make_pdf(tmp_path))
    call(server.base, "POST", f"/api/docs/{doc}/ops",
         {"ops": [{"type": "rect", "page": 0, "rect": [60, 600, 120, 640], "color": [0, 0, 0]}]})
    status, info = call(server.base, "GET", f"/api/docs/{doc}")
    assert info["undo_steps"] == 1


def test_redact_keeps_the_page_background_and_its_colour(tmp_path, server):
    tint = (0.9, 0.9, 0.7)
    path = tmp_path / "tint.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(0, 0, 612, 792), color=None, fill=tint)
    page.insert_text((210, 330), "Secret plan", fontsize=14)
    doc.save(path)
    doc.close()
    doc_id = doc_id_of(server.base, path)

    status, body = redact(server.base, doc_id, AREA)
    assert status == 200, body
    assert "Secret" not in saved_text(server.base, doc_id)

    colour = pixel(server.base, doc_id, 205, 285)  # inside the area, away from the text
    assert all(abs(a - b) <= 2 for a, b in zip(colour, (229, 229, 178)))
    pdf = saved_pdf(server.base, doc_id)
    try:
        backgrounds = [d for d in pdf[0].get_drawings() if d["rect"].width > 600]
    finally:
        pdf.close()
    assert backgrounds, "the page background was removed"


def test_redact_tool_erases_the_line_and_clears_undo(ui, server):
    page = ui.page
    doc = open_file(page, fixture("embedded.pdf"))
    first = page.locator(".tl-box").first
    word = first.get_attribute("title").split()[0]
    assert word in saved_text(server.base, doc)

    box = first.bounding_box()
    page.click("[data-tool='redact']")
    page.mouse.move(box["x"] - 2, box["y"] - 2)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] + 2, box["y"] + box["height"] + 2, steps=6)
    page.mouse.up()
    page.wait_for_timeout(900)

    assert word not in saved_text(server.base, doc).split()
    assert page.is_disabled("#undo")
    assert not ui.errors
