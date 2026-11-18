"""Picture layers, moves and deletes, through the API and the browser."""
from __future__ import annotations

import base64

import pymupdf

from support import call, doc_id_of, fixture


SPOT = [55, 330, 200, 360]  # covers "Row item 3" on multi.pdf


def make_png_uri():
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 120, 60), False)
    pix.set_rect(pix.irect, (200, 30, 30))
    return "data:image/png;base64," + base64.b64encode(pix.tobytes("png")).decode()


def test_picture_layers_move_delete_and_undo(server):
    doc = doc_id_of(server.base, fixture("multi.pdf"))
    path = server.data_dir / "docs" / doc / "current.pdf"

    def dark(rect):
        """Dark pixels inside rect, read from the saved page as it looks on screen."""
        pdf = pymupdf.open(path)
        pix = pdf[0].get_pixmap(clip=pymupdf.Rect(rect), dpi=144)
        count = 0
        for i in range(0, len(pix.samples), 9):
            if sum(pix.samples[i:i + 3]) < 200:
                count += 1
        pdf.close()
        return count

    def words_ok():
        pdf = pymupdf.open(path)
        words = [w[4] for w in pdf[0].get_text("words")]
        pdf.close()
        return all(t in words for t in ("Row", "item", "3"))

    def images():
        return call(server.base, "GET", f"/api/docs/{doc}/pages/0/images")[1]["images"]

    def op(body):
        return call(server.base, "POST", f"/api/docs/{doc}/ops", {"ops": [body]})

    op({"type": "image", "page": 0, "rect": SPOT, "image": make_png_uri()})
    ims = images()
    assert len(ims) == 1
    box = ims[0]["bbox"]
    assert dark(box) == 0

    op({"type": "set_image_layer", "page": 0, "xref": ims[0]["xref"], "rect": ims[0]["bbox"], "z": "under"})
    assert dark(box) > 20
    assert words_ok()

    op({"type": "set_image_layer", "page": 0, "xref": images()[0]["xref"], "rect": SPOT, "z": "top"})
    assert dark(box) == 0

    op({"type": "set_image_layer", "page": 0, "xref": images()[0]["xref"], "rect": SPOT, "z": "bottom"})
    assert dark(box) > 20

    cur = images()[0]
    op({"type": "set_image_layer", "page": 0, "xref": cur["xref"], "rect": cur["bbox"], "z": "top"})
    cur = images()[0]
    op({"type": "move_image", "page": 0, "xref": cur["xref"], "rect": cur["bbox"], "dest": [400, 600]})
    moved = images()
    assert len(moved) == 1 and abs(moved[0]["bbox"][0] - 400) < 1
    assert dark(box) > 20
    assert words_ok()

    m = moved[0]
    op({"type": "delete_image", "page": 0, "xref": m["xref"], "rect": m["bbox"]})
    assert images() == []
    assert words_ok() and dark(box) > 20

    call(server.base, "POST", f"/api/docs/{doc}/undo")
    assert len(images()) == 1


def test_right_click_on_text_over_picture_opens_picture_menu(ui_small, server):
    ui = ui_small
    page = ui.page
    doc = doc_id_of(server.base, fixture("multi.pdf"))
    # The picture covers the text line, so the text box sits on top of the picture.
    call(server.base, "POST", f"/api/docs/{doc}/ops", {"ops": [
        {"type": "image", "page": 0, "rect": SPOT, "image": make_png_uri()},
    ]})
    page.evaluate(f"() => window.pdfStudio.openDoc('{doc}')")
    page.wait_for_selector("#stage:not([hidden])")
    page.wait_for_timeout(900)

    line = page.locator(".tl-box[title*='Row item 3']").first
    line.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    bb = line.bounding_box()
    page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2, button="right")
    page.wait_for_timeout(300)
    assert page.locator("#img-menu").is_visible()
    assert not ui.errors


def test_picture_menu_and_delete_key_in_browser(ui_small, server):
    ui = ui_small
    page = ui.page
    doc = doc_id_of(server.base, fixture("multi.pdf"))
    # A free area: text lines sit above pictures in the page, so a picture over text cannot be clicked.
    op = {"ops": [{"type": "image", "page": 0, "rect": [400, 600, 520, 660], "image": make_png_uri()}]}
    call(server.base, "POST", f"/api/docs/{doc}/ops", op)
    page.evaluate(f"() => window.pdfStudio.openDoc('{doc}')")
    page.wait_for_selector("#stage:not([hidden])")
    page.wait_for_timeout(900)

    box = page.locator(".img-box").first
    box.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    bb = box.bounding_box()
    page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
    page.wait_for_timeout(300)
    page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2, button="right")
    page.wait_for_timeout(300)
    assert page.locator("#img-menu").is_visible()
    page.locator("#img-menu [data-img='bottom']").click()
    page.wait_for_timeout(1300)
    assert not page.locator("#img-menu").is_visible()
    assert len(call(server.base, "GET", f"/api/docs/{doc}/pages/0/images")[1]["images"]) == 1

    box = page.locator(".img-box").first
    box.scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    bb = box.bounding_box()
    page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
    page.wait_for_timeout(300)
    page.keyboard.press("Delete")
    page.wait_for_timeout(1300)
    assert call(server.base, "GET", f"/api/docs/{doc}/pages/0/images")[1]["images"] == []
    assert not ui.errors
