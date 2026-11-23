"""Regressions: a page change ends an open edit, deleting a page drops the selection,
quick tool switches draw each text box once."""
from __future__ import annotations

import time

import fitz
from playwright.sync_api import expect

from support import click_line, fixture, open_file, saved_pdf


def two_page_pdf(tmp_path):
    out = fitz.open()
    out.insert_pdf(fitz.open(fixture("embedded.pdf")))
    out.insert_pdf(fitz.open(fixture("multi.pdf")))
    path = tmp_path / "two-pages.pdf"
    out.save(path)
    return path


def words(page_obj):
    return " ".join(w[4] for w in page_obj.get_text("words"))


def test_next_page_keeps_open_edit_on_its_own_page(ui, server, tmp_path):
    page = ui.page
    doc = open_file(page, two_page_pdf(tmp_path))
    click_line(page, "Embedded line one")
    box = page.locator(".tl-box[title*='Embedded line one']").bounding_box()
    page.mouse.dblclick(box["x"] + 20, box["y"] + box["height"] / 2)
    page.wait_for_timeout(400)
    page.keyboard.press("End")
    page.keyboard.type(" Z")
    page.wait_for_timeout(100)
    page.click("#next")
    page.wait_for_timeout(600)
    img = page.locator("#page-img").bounding_box()
    page.mouse.click(img["x"] + img["width"] - 15, img["y"] + img["height"] - 15)
    page.wait_for_timeout(1200)
    pdf = saved_pdf(server.base, doc)
    assert "Z" in words(pdf[0])
    assert "Z" not in words(pdf[1])
    assert not ui.errors


def test_delete_page_drops_selection(ui, server, tmp_path):
    page = ui.page
    open_file(page, two_page_pdf(tmp_path))
    click_line(page, "Embedded line one")
    assert page.locator(".tl-box.selected").count() == 1
    page.click("#delete-page")
    page.wait_for_timeout(1200)
    assert page.locator(".tl-box.selected").count() == 0
    assert not ui.errors


def test_overlapping_text_layer_draws_do_not_duplicate_boxes(ui, server):
    page = ui.page
    open_file(page, fixture("embedded.pdf"))
    page.click(".tool[data-tool='replace']")
    page.wait_for_timeout(800)
    settled = page.locator(".tl-box").count()
    assert settled > 0
    # Two draws started together both wait for the lines; each must still leave one set of boxes.
    count = page.evaluate("""async () => {
      const draw = window.pdfStudio.drawTextLayer;
      await Promise.all([draw(), draw(), draw()]);
      return document.querySelectorAll('.tl-box').length;
    }""")
    assert count == settled
    assert not ui.errors
