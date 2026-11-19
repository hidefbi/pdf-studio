"""Removing one line must leave the text around it alone."""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import pytest

from support import fixture

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.linetext import remove_line  # noqa: E402

CANVAS_FONT = Path("/mnt/skills/examples/canvas-design/canvas-fonts/BigShoulders-Regular.ttf")


def lines(doc, index=0):
    out = []
    for block in doc[index].get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            out.append({
                "bbox": [round(v, 2) for v in line["bbox"]],
                "origin": [round(v, 2) for v in spans[0]["origin"]],
                "text": "".join(s["text"] for s in line["spans"]).strip(),
                "size": round(max(spans, key=lambda s: len(s["text"]))["size"], 2),
            })
    return out


def find(doc, prefix):
    return next(line for line in lines(doc) if line["text"].startswith(prefix))


def texts(doc):
    return [line["text"] for line in lines(doc)]


def put(doc, text, origin, size=11, font="helv"):
    doc[0].insert_text(pymupdf.Point(*origin), text, fontname=font, fontsize=size)


def set_content(page, stream, font="helv"):
    page.insert_text((1, 1), "x", fontname=font, fontsize=1)
    page.parent.update_stream(page.get_contents()[0], stream)
    for xref in page.get_contents()[1:]:
        page.parent.update_stream(xref, b"")


def test_removes_only_the_target_line(tmp_path):
    doc = pymupdf.open(fixture("multi.pdf"))
    before = texts(doc)
    target = find(doc, "Billing")
    remove_line(doc, 0, target["bbox"], target["origin"])
    after = texts(doc)
    assert "Billing period March" not in after
    assert sorted(before) == sorted(after + ["Billing period March"])


def test_nothing_else_on_the_page_changes(tmp_path):
    doc = pymupdf.open(fixture("multi.pdf"))
    target = find(doc, "Row item 5")
    box = pymupdf.Rect(target["bbox"])
    page_rect = doc[0].rect
    margin = 1.0
    keep = [
        pymupdf.Rect(0, 0, page_rect.width, box.y0 - margin),
        pymupdf.Rect(0, box.y1 + margin, page_rect.width, page_rect.height),
        pymupdf.Rect(0, box.y0, box.x0 - margin, box.y1),
        pymupdf.Rect(box.x1 + margin, box.y0, page_rect.width, box.y1),
    ]
    before = [doc[0].get_pixmap(clip=r, alpha=False).samples for r in keep]
    remove_line(doc, 0, target["bbox"], target["origin"])
    after = [doc[0].get_pixmap(clip=r, alpha=False).samples for r in keep]
    assert before == after


def test_repeated_size_steps_keep_the_neighbour(tmp_path):
    doc = pymupdf.open(fixture("multi.pdf"))
    neighbour = find(doc, "Account")["text"]
    for _ in range(5):
        line = find(doc, "Billing")
        size = round(line["size"]) + 1
        remove_line(doc, 0, line["bbox"], line["origin"])
        put(doc, line["text"], line["origin"], size=size)
    assert neighbour in texts(doc)
    assert find(doc, "Billing")["size"] == 16


def test_dragged_text_over_another_line_keeps_it(tmp_path):
    doc = pymupdf.open(fixture("multi.pdf"))
    source = find(doc, "Billing")
    under = find(doc, "Account")
    remove_line(doc, 0, source["bbox"], source["origin"])
    put(doc, source["text"], (source["origin"][0], under["origin"][1] + 4))
    moved = find(doc, "Billing")
    remove_line(doc, 0, moved["bbox"], moved["origin"])
    put(doc, moved["text"], moved["origin"], size=moved["size"] + 4)
    assert under["text"] in texts(doc)


def test_kerned_array_with_spacing_and_scale(tmp_path):
    doc = pymupdf.open()
    set_content(doc.new_page(), (
        b"BT /helv 12 Tf 2 Tz 1 Tc 50 700 Td [(Hel) -300 (lo) 200 (wor)] TJ ET\n"
        b"BT /helv 12 Tf 50 680 Td (Second line) Tj ET\n"))
    target = find(doc, "Helowor")
    remove_line(doc, 0, target["bbox"], target["origin"])
    assert texts(doc) == ["Second line"]


def test_quote_operators(tmp_path):
    doc = pymupdf.open()
    set_content(doc.new_page(), (
        b"BT /helv 12 Tf 14 TL 50 660 Td (First line) ' (Second line) ' ET\n"
        b"BT /helv 12 Tf 50 600 Td (Third line) Tj ET\n"))
    target = find(doc, "Second")
    remove_line(doc, 0, target["bbox"], target["origin"])
    assert sorted(texts(doc)) == ["First line", "Third line"]


def test_part_of_a_split_array_stays_in_place(tmp_path):
    doc = pymupdf.open()
    set_content(doc.new_page(), b"BT /helv 12 Tf 50 700 Td [(Left) -4000 (Right)] TJ ET\n")
    right = find(doc, "Right")
    left = find(doc, "Left")
    remove_line(doc, 0, left["bbox"], left["origin"])
    kept = find(doc, "Right")
    assert kept["origin"] == right["origin"]


def test_embedded_two_byte_font(tmp_path):
    if not CANVAS_FONT.exists():
        pytest.skip("sample font not available")
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((1, 1), "x", fontname="F1", fontfile=str(CANVAS_FONT), fontsize=1)
    page.insert_text((50, 100), "EMBEDDED ONE", fontname="F1", fontsize=14)
    page.insert_text((50, 130), "EMBEDDED TWO", fontname="F1", fontsize=14)
    target = find(doc, "EMBEDDED TWO")
    remove_line(doc, 0, target["bbox"], target["origin"])
    assert "EMBEDDED ONE" in texts(doc)
    assert "EMBEDDED TWO" not in texts(doc)


def test_chinese_text_from_the_built_in_font(tmp_path):
    chinese = "".join(chr(c) for c in (0x4F60, 0x597D, 0x4E16, 0x754C))  # four Chinese characters
    first = chr(0x4F60)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), "Account 12345", fontname="helv", fontsize=11)
    page.insert_text((50, 130), chinese, fontname="china-s", fontsize=11)
    target = next(line for line in lines(doc) if first in line["text"])
    remove_line(doc, 0, target["bbox"], target["origin"])
    assert "Account 12345" in texts(doc)
    assert not any(first in text for text in texts(doc))


def test_rotated_page(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=300)
    page.insert_text((50, 100), "Rotated one", fontname="helv", fontsize=12)
    page.insert_text((50, 130), "Rotated two", fontname="helv", fontsize=12)
    page.set_rotation(90)
    target = find(doc, "Rotated two")
    remove_line(doc, 0, target["bbox"], target["origin"])
    assert "Rotated one" in texts(doc)
    assert "Rotated two" not in texts(doc)


def test_text_inside_a_form_is_refused(tmp_path):
    source = pymupdf.open()
    source.new_page().insert_text((50, 100), "Inside form", fontname="helv", fontsize=11)
    doc = pymupdf.open()
    page = doc.new_page()
    page.show_pdf_page(page.rect, source, 0)
    target = find(doc, "Inside")
    with pytest.raises(ValueError):
        remove_line(doc, 0, target["bbox"], target["origin"])
    assert "Inside form" in texts(doc)


def test_missing_origin_is_refused(tmp_path):
    doc = pymupdf.open(fixture("multi.pdf"))
    target = find(doc, "Billing")
    with pytest.raises(ValueError):
        remove_line(doc, 0, target["bbox"], None)


def test_api_refuses_an_edit_it_cannot_do_safely(server, tmp_path):
    from support import call, doc_id_of

    source = pymupdf.open()
    source.new_page().insert_text((50, 100), "Inside form", fontname="helv", fontsize=11)
    wrapper = pymupdf.open()
    page = wrapper.new_page()
    page.show_pdf_page(page.rect, source, 0)
    path = tmp_path / "form.pdf"
    wrapper.save(path)
    doc = doc_id_of(server.base, path)
    line = next(ln for ln in call(server.base, "GET", f"/api/docs/{doc}/pages/0/lines")[1]["lines"]
                if ln["text"].startswith("Inside"))
    body = {
        "type": "replace_span", "page": 0, "rect": line["bbox"], "origin": line["origin"],
        "text": "Changed", "font": "auto", "font_xref": line["font_xref"],
        "base_font": line["base_font"], "size": line["size"], "color": [0, 0, 0],
        "align": None, "block": None,
    }
    status, reply = call(server.base, "POST", f"/api/docs/{doc}/ops", {"ops": [body]})
    assert status == 400
    assert reply["detail"] == "this text cannot be changed safely"
    lines_after = call(server.base, "GET", f"/api/docs/{doc}/pages/0/lines")[1]["lines"]
    assert any(ln["text"].startswith("Inside") for ln in lines_after)
